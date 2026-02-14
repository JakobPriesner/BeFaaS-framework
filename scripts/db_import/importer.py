"""
Main import orchestration for BeFaaS benchmark results.

This module coordinates:
1. Parsing all data sources from an experiment directory
2. Efficiently batch-inserting data into the database using PostgreSQL COPY
3. Progress reporting for large log file imports

Performance optimizations:
- Uses PostgreSQL COPY for 10-50x faster bulk inserts
- Optionally drops indexes during import and rebuilds after
- Pre-calculates derived fields at insert time to avoid slow UPDATE queries
- Uses single set-based UPDATE for post-processing (no batched loops)
- Commits periodically to prevent PostgreSQL memory buildup
"""

import os
import sys
import time
import csv
from io import StringIO
from pathlib import Path
from typing import Optional, Generator, Any
from datetime import datetime

from sqlalchemy import create_engine, insert, select, delete, text
from sqlalchemy.orm import Session

# Configuration via environment variables
USE_OPTIMIZED_PROCESSING = os.getenv('DB_IMPORT_OPTIMIZED', 'true').lower() == 'true'
# Use PostgreSQL COPY for bulk inserts (much faster than INSERT)
USE_COPY_INSERT = os.getenv('DB_IMPORT_USE_COPY', 'true').lower() == 'true'
# Drop indexes during import for faster inserts (rebuilds after)
DROP_INDEXES_DURING_IMPORT = os.getenv('DB_IMPORT_DROP_INDEXES', 'true').lower() == 'true'
# Batch size for COPY operations (larger = fewer round trips)
COPY_BATCH_SIZE = int(os.getenv('DB_IMPORT_COPY_BATCH_SIZE', '100000'))
# Batch size for post-processing UPDATE statements (reduce if database has memory issues)
POST_PROCESS_BATCH_SIZE = int(os.getenv('DB_IMPORT_BATCH_SIZE', '50000'))
# Commit frequency: commit after this many records to prevent memory buildup
# Set to 0 to disable intermediate commits (original behavior)
COMMIT_EVERY_N_RECORDS = int(os.getenv('DB_IMPORT_COMMIT_EVERY', '500000'))
# Skip x_pair enrichment during insert and do it in post-processing instead
# This is faster for large datasets because database JOINs are more efficient than Python dict lookups
ENRICH_IN_POST_PROCESSING = os.getenv('DB_IMPORT_ENRICH_POST', 'true').lower() == 'true'
# Backpressure: delay (in seconds) after each flush to prevent overwhelming the database
# Set to 0 to disable (original behavior). Default 0.1s provides gentle backpressure.
FLUSH_DELAY_SECONDS = float(os.getenv('DB_IMPORT_FLUSH_DELAY', '0.1'))

from .schema import (
    Base, Experiment, ScalingRule, Phase, Request, LambdaExecution,
    HandlerEvent, ContainerStart, RpcCall, Pricing, PricingComponent,
    MetricsEcs, MetricsAlb, SchemaDocumentation,
    create_tables, add_table_comments, add_column_comments, populate_schema_documentation
)
from .parsers import (
    parse_directory_name,
    parse_hardware_config,
    parse_benchmark_config,
    parse_experiment_start_time,
    parse_error_description,
    parse_pricing,
    parse_artillery_log,
    parse_aws_log,
    parse_alb_metrics,
    parse_ecs_metrics,
)


class ImportProgress:
    """Simple progress reporter."""

    def __init__(self, total: int = 0, desc: str = ""):
        self.total = total
        self.desc = desc
        self.current = 0
        self.last_percent = -1

    def update(self, n: int = 1):
        self.current += n
        if self.total > 0:
            percent = int(100 * self.current / self.total)
            if percent != self.last_percent and percent % 5 == 0:
                self.last_percent = percent
                print(f"  {self.desc}: {percent}% ({self.current:,}/{self.total:,})", flush=True)

    def finish(self):
        if self.total > 0:
            print(f"  {self.desc}: 100% ({self.current:,} records)", flush=True)
        else:
            print(f"  {self.desc}: {self.current:,} records", flush=True)


def _batch_insert(session: Session, table, records: list, batch_size: int = 5000, flush_every: int = 100000):
    """
    Efficiently insert records in batches using executemany with reduced flush frequency.

    Args:
        session: SQLAlchemy session
        table: SQLAlchemy model class
        records: List of dictionaries with column values
        batch_size: Number of records per batch for SQL insert
        flush_every: Number of records after which to flush (reduces I/O overhead)
    """
    if not records:
        return

    total_processed = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        session.execute(insert(table), batch)
        total_processed += len(batch)

        # Only flush every flush_every records instead of after every batch
        if total_processed >= flush_every:
            session.flush()
            total_processed = 0

    # Final flush for remaining records
    if total_processed > 0:
        session.flush()


def _batch_insert_generator(session: Session, table, record_generator, batch_size: int = 5000, flush_every: int = 100000):
    """
    Memory-efficient batch insert using generators instead of building full record lists.

    Args:
        session: SQLAlchemy session
        table: SQLAlchemy model class
        record_generator: Generator yielding record dictionaries
        batch_size: Number of records per batch for SQL insert
        flush_every: Number of records after which to flush
    """
    batch = []
    total_processed = 0

    for record in record_generator:
        batch.append(record)

        if len(batch) >= batch_size:
            session.execute(insert(table), batch)
            total_processed += len(batch)
            batch = []  # Clear batch to free memory

            # Only flush every flush_every records
            if total_processed >= flush_every:
                session.flush()
                total_processed = 0

    # Insert final batch
    if batch:
        session.execute(insert(table), batch)
        total_processed += len(batch)

    # Final flush
    if total_processed > 0:
        session.flush()


# =============================================================================
# PostgreSQL COPY-based bulk insertion (10-50x faster than INSERT)
# =============================================================================

# Column order for each table (must match database schema)
TABLE_COLUMNS = {
    'requests': [
        'experiment_id', 'x_pair', 'context_id', 'timestamp_ms', 'latency_ms',
        'relative_time_ms', 'phase_relative_time_ms', 'endpoint', 'status_code',
        'auth_type', 'is_error', 'is_timeout', 'error_type', 'error_code',
        'phase_index', 'phase_name', 'handler_duration_ms', 'network_overhead_ms'
    ],
    'lambda_executions': [
        'experiment_id', 'request_id', 'function_name', 'timestamp_ms',
        'duration_ms', 'billed_duration_ms', 'init_duration_ms', 'memory_size_mb',
        'max_memory_used_mb', 'is_cold_start', 'relative_time_ms'
    ],
    'handler_events': [
        'experiment_id', 'x_pair', 'context_id', 'lambda_request_id', 'function_name',
        'route', 'status_code', 'is_cold_start', 'request_count', 'timestamp_ms',
        'duration_ms', 'relative_time_ms', 'phase_relative_time_ms', 'is_protected_endpoint',
        'phase_index', 'phase_name', 'auth_type'
    ],
    'container_starts': [
        'experiment_id', 'lambda_request_id', 'function_name', 'deployment_id',
        'timestamp_ms', 'container_start_time_ms', 'relative_time_ms'
    ],
    'rpc_calls': [
        'experiment_id', 'direction', 'x_pair', 'context_id', 'lambda_request_id',
        'function_name', 'target_function', 'call_x_pair', 'call_type', 'duration_ms',
        'success', 'is_cold_start', 'timestamp_ms', 'received_at_ms', 'relative_time_ms',
        'phase_index', 'phase_name', 'auth_type'
    ],
}

# Indexes to drop/recreate for faster import (keyed by table name)
TABLE_INDEXES = {
    'requests': [
        ('idx_req_exp', 'experiment_id'),
        ('idx_req_exp_ts', 'experiment_id, timestamp_ms'),
        ('idx_req_exp_endpoint', 'experiment_id, endpoint'),
        ('idx_req_exp_auth', 'experiment_id, auth_type'),
        ('idx_req_exp_phase', 'experiment_id, phase_index'),
        ('idx_req_xpair', 'x_pair'),
        ('idx_req_latency', 'experiment_id, latency_ms'),
        ('idx_req_exp_xpair', 'experiment_id, x_pair'),
        ('idx_req_exp_context', 'experiment_id, context_id'),
    ],
    'lambda_executions': [
        ('idx_lambda_exp', 'experiment_id'),
        ('idx_lambda_exp_fn', 'experiment_id, function_name'),
        ('idx_lambda_exp_cold', 'experiment_id, is_cold_start'),
        ('idx_lambda_reqid', 'request_id'),
    ],
    'handler_events': [
        ('idx_handler_exp', 'experiment_id'),
        ('idx_handler_exp_fn', 'experiment_id, function_name'),
        ('idx_handler_xpair', 'x_pair'),
        ('idx_handler_exp_auth', 'experiment_id, auth_type'),
        ('idx_handler_exp_xpair', 'experiment_id, x_pair'),
        ('idx_handler_exp_phase_idx', 'experiment_id, phase_index'),
        ('idx_handler_exp_context', 'experiment_id, context_id'),
    ],
    'container_starts': [
        ('idx_cold_exp', 'experiment_id'),
        ('idx_cold_exp_fn', 'experiment_id, function_name'),
    ],
    'rpc_calls': [
        ('idx_rpc_exp', 'experiment_id'),
        ('idx_rpc_exp_dir', 'experiment_id, direction'),
        ('idx_rpc_exp_fn', 'experiment_id, function_name'),
        ('idx_rpc_xpair', 'x_pair'),
        ('idx_rpc_exp_xpair', 'experiment_id, x_pair'),
        ('idx_rpc_exp_context', 'experiment_id, context_id'),
    ],
}


def _format_value_for_copy(value: Any) -> str:
    """Format a Python value for PostgreSQL COPY (tab-separated)."""
    if value is None:
        return '\\N'  # PostgreSQL NULL representation
    if isinstance(value, bool):
        return 't' if value else 'f'
    if isinstance(value, (int, float)):
        return str(value)
    # Escape special characters for COPY format
    s = str(value)
    s = s.replace('\\', '\\\\')  # Escape backslashes first
    s = s.replace('\t', '\\t')   # Escape tabs
    s = s.replace('\n', '\\n')   # Escape newlines
    s = s.replace('\r', '\\r')   # Escape carriage returns
    return s


def _copy_insert(session: Session, table_name: str, records: list[dict], columns: list[str], commit: bool = False):
    """
    Bulk insert records using PostgreSQL COPY command.

    This is 10-50x faster than INSERT for large batches because:
    - Single network round-trip for entire batch
    - Minimal SQL parsing overhead
    - No per-row constraint checking until end

    Args:
        session: SQLAlchemy session
        table_name: Name of the target table
        records: List of record dictionaries
        columns: List of column names in order
        commit: If True, commit after COPY to free PostgreSQL buffers
    """
    if not records:
        return

    # Get raw psycopg2 connection
    raw_conn = session.connection().connection
    cursor = raw_conn.cursor()

    try:
        # Build tab-separated data in memory
        buffer = StringIO()
        for record in records:
            row = [_format_value_for_copy(record.get(col)) for col in columns]
            buffer.write('\t'.join(row) + '\n')

        buffer.seek(0)

        # Execute COPY
        columns_str = ', '.join(columns)
        cursor.copy_expert(
            f"COPY {table_name} ({columns_str}) FROM STDIN WITH (FORMAT text, NULL '\\N')",
            buffer
        )
    finally:
        # Always close cursor to prevent resource leak
        cursor.close()

    # Commit to free PostgreSQL buffers and write to disk
    # This prevents memory buildup and long final commits
    if commit:
        session.commit()


def _copy_insert_generator(
    session: Session,
    table_name: str,
    record_generator: Generator[dict, None, None],
    columns: list[str],
    batch_size: int = COPY_BATCH_SIZE,
    progress_callback=None
) -> int:
    """
    Memory-efficient bulk insert using COPY with streaming from generator.

    Args:
        session: SQLAlchemy session
        table_name: Name of the target table
        record_generator: Generator yielding record dictionaries
        columns: List of column names in order
        batch_size: Number of records per COPY batch
        progress_callback: Optional callback(count) for progress reporting

    Returns:
        Total number of records inserted
    """
    batch = []
    total_inserted = 0

    for record in record_generator:
        batch.append(record)

        if len(batch) >= batch_size:
            _copy_insert(session, table_name, batch, columns)
            total_inserted += len(batch)
            if progress_callback:
                progress_callback(total_inserted)
            batch = []

    # Insert remaining records
    if batch:
        _copy_insert(session, table_name, batch, columns)
        total_inserted += len(batch)

    return total_inserted


def _drop_indexes(session: Session, table_name: str):
    """Drop all non-primary-key indexes on a table for faster bulk insert."""
    if table_name not in TABLE_INDEXES:
        return

    for idx_name, _ in TABLE_INDEXES[table_name]:
        try:
            session.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        except Exception as e:
            print(f"    Warning: Could not drop index {idx_name}: {e}")

    session.flush()


def _create_indexes(session: Session, table_name: str):
    """Recreate indexes on a table after bulk insert."""
    if table_name not in TABLE_INDEXES:
        return

    for idx_name, columns in TABLE_INDEXES[table_name]:
        try:
            session.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({columns})"))
        except Exception as e:
            print(f"    Warning: Could not create index {idx_name}: {e}")

    session.flush()


def _drop_all_large_table_indexes(session: Session):
    """Drop indexes on all large tables before import."""
    print("  Dropping indexes for faster import...")
    for table_name in TABLE_INDEXES:
        _drop_indexes(session, table_name)


def _rebuild_all_indexes(session: Session):
    """Rebuild indexes on all large tables after import."""
    print("  Rebuilding indexes...")
    start = time.time()
    for table_name in TABLE_INDEXES:
        _create_indexes(session, table_name)
    print(f"  Indexes rebuilt in {time.time() - start:.1f}s")


def _set_fast_import_mode(session: Session, enable: bool = True):
    """
    Configure PostgreSQL for fast bulk import.

    When enabled:
    - Disables synchronous_commit for 2-3x faster writes
    - Sets work_mem higher for better sort/hash performance

    Should be disabled after import to restore durability guarantees.
    """
    if enable:
        session.execute(text("SET synchronous_commit = OFF"))
        session.execute(text("SET work_mem = '256MB'"))
    else:
        session.execute(text("SET synchronous_commit = ON"))
        session.execute(text("RESET work_mem"))


def _calculate_phase_starts(phases):
    """
    Pre-calculate phase start times to avoid correlated subqueries.

    Args:
        phases: List of Phase objects

    Returns:
        Dictionary mapping phase_index to cumulative start time in milliseconds
    """
    phase_starts = {0: 0}  # First phase starts at 0
    cumulative = 0

    # Sort phases by index and calculate cumulative start times
    sorted_phases = sorted(phases, key=lambda p: p.phase_index)
    for i, phase in enumerate(sorted_phases[:-1]):  # Exclude last phase
        next_phase_idx = sorted_phases[i + 1].phase_index
        cumulative += phase.duration_seconds * 1000 if phase.duration_seconds else 0
        phase_starts[next_phase_idx] = cumulative

    return phase_starts


def _is_protected_endpoint(route):
    """Determine if a route is a protected endpoint requiring authentication."""
    if not route:
        return False
    if '/login' in route:
        return False
    if '/register' in route:
        return False
    if '/health' in route:
        return False
    if route.startswith('GET /api/products'):
        return False
    if '/api/' in route:
        return True
    return False


def _create_lambda_execution_records(lambda_executions, experiment_id, benchmark_start=None):
    """Generator for lambda execution records with pre-calculated fields."""
    for e in lambda_executions:
        record = {
            'experiment_id': experiment_id,
            'request_id': e.request_id,
            'function_name': e.function_name,
            'timestamp_ms': e.timestamp_ms,
            'duration_ms': e.duration_ms,
            'billed_duration_ms': e.billed_duration_ms,
            'init_duration_ms': e.init_duration_ms,
            'memory_size_mb': e.memory_size_mb,
            'max_memory_used_mb': e.max_memory_used_mb,
            'is_cold_start': e.is_cold_start,
        }
        # Calculate relative_time_ms at insert time
        if benchmark_start and e.timestamp_ms:
            record['relative_time_ms'] = e.timestamp_ms - benchmark_start
        yield record


def _create_handler_event_records(handler_events, experiment_id, benchmark_start=None,
                                   phase_starts=None, x_pair_lookup=None, skip_enrichment=False):
    """Generator for handler event records with pre-calculated fields.

    Args:
        skip_enrichment: If True, skip x_pair lookup enrichment (do it in post-processing instead)
    """
    for e in handler_events:
        record = {
            'experiment_id': experiment_id,
            'x_pair': e.x_pair,
            'context_id': e.context_id,
            'lambda_request_id': e.lambda_request_id,
            'function_name': e.function_name,
            'route': e.route,
            'status_code': e.status_code,
            'is_cold_start': e.is_cold_start,
            'request_count': e.request_count,
            'timestamp_ms': e.timestamp_ms,
            'duration_ms': e.duration_ms,
            # Calculate is_protected_endpoint at insert time
            'is_protected_endpoint': _is_protected_endpoint(e.route),
        }

        # Calculate relative_time_ms at insert time
        if benchmark_start and e.timestamp_ms:
            record['relative_time_ms'] = e.timestamp_ms - benchmark_start

        # Enrich with phase/auth info from context_id lookup (unless skipping for post-processing)
        # NOTE: We use context_id (not x_pair) because internal RPC calls (e.g., cart receiving
        # a call from frontend) have x_pairs that are generated call_x_pairs which don't exist
        # in the lookup.
        if not skip_enrichment and x_pair_lookup and e.context_id and e.context_id in x_pair_lookup:
            lookup = x_pair_lookup[e.context_id]
            record['phase_index'] = lookup.get('phase_index')
            record['phase_name'] = lookup.get('phase_name')
            record['auth_type'] = lookup.get('auth_type')

            # Calculate phase_relative_time_ms at insert time
            if phase_starts and record.get('relative_time_ms') is not None:
                phase_idx = record.get('phase_index')
                if phase_idx is not None and phase_idx in phase_starts:
                    record['phase_relative_time_ms'] = record['relative_time_ms'] - phase_starts[phase_idx]

        yield record


def _create_container_start_records(container_starts, experiment_id, benchmark_start=None):
    """Generator for container start records with pre-calculated fields."""
    for cs in container_starts:
        record = {
            'experiment_id': experiment_id,
            'lambda_request_id': cs.lambda_request_id,
            'function_name': cs.function_name,
            'deployment_id': cs.deployment_id,
            'timestamp_ms': cs.timestamp_ms,
            'container_start_time_ms': cs.container_start_time_ms,
        }
        # Calculate relative_time_ms at insert time
        if benchmark_start and cs.timestamp_ms:
            record['relative_time_ms'] = cs.timestamp_ms - benchmark_start
        yield record


def _create_rpc_call_records(rpc_calls, experiment_id, benchmark_start=None, x_pair_lookup=None, skip_enrichment=False):
    """Generator for RPC call records with pre-calculated fields.

    Args:
        skip_enrichment: If True, skip x_pair lookup enrichment (do it in post-processing instead)
    """
    for rpc in rpc_calls:
        record = {
            'experiment_id': experiment_id,
            'direction': rpc.direction,
            'x_pair': rpc.x_pair,
            'context_id': rpc.context_id,
            'lambda_request_id': rpc.lambda_request_id,
            'function_name': rpc.function_name,
            'target_function': rpc.target_function,
            'call_x_pair': rpc.call_x_pair,
            'call_type': getattr(rpc, 'call_type', None),
            'duration_ms': rpc.duration_ms,
            'success': getattr(rpc, 'success', None),
            'is_cold_start': getattr(rpc, 'is_cold_start', None),
            'timestamp_ms': rpc.timestamp_ms,
            'received_at_ms': getattr(rpc, 'received_at_ms', None),
        }

        # Calculate relative_time_ms at insert time
        if benchmark_start and rpc.timestamp_ms:
            record['relative_time_ms'] = rpc.timestamp_ms - benchmark_start

        # Enrich with phase/auth info from context_id lookup (unless skipping for post-processing)
        # NOTE: We use context_id (not x_pair) because internal RPC calls have x_pairs
        # that are generated call_x_pairs which don't exist in the lookup.
        if not skip_enrichment and x_pair_lookup and rpc.context_id and rpc.context_id in x_pair_lookup:
            lookup = x_pair_lookup[rpc.context_id]
            record['phase_index'] = lookup.get('phase_index')
            record['phase_name'] = lookup.get('phase_name')
            record['auth_type'] = lookup.get('auth_type')

        yield record


def _create_optimized_request_records(requests, experiment_id, benchmark_start=None, phase_starts=None):
    """
    Create request records with pre-calculated derived fields.

    This eliminates the need for post-processing UPDATE statements.
    """
    records = []
    for r in requests:
        record = {
            'experiment_id': experiment_id,
            'x_pair': r.x_pair,
            'context_id': r.context_id,
            'timestamp_ms': r.timestamp_ms,
            'latency_ms': getattr(r, '_latency_ms', None),  # Match legacy field access
            'endpoint': r.endpoint,
            'status_code': r.status_code,
            'is_error': r.is_error,
            'is_timeout': r.is_timeout,
            'phase_index': r.phase_index,
            'phase_name': r.phase_name,
            'auth_type': r.auth_type,
            'error_type': getattr(r, 'error_type', None),
            'error_code': getattr(r, 'error_code', None),
        }

        # Calculate relative_time_ms during record creation
        if benchmark_start and r.timestamp_ms:
            record['relative_time_ms'] = r.timestamp_ms - benchmark_start

            # Calculate phase_relative_time_ms during record creation
            if r.phase_index is not None and phase_starts and r.phase_index in phase_starts:
                record['phase_relative_time_ms'] = record['relative_time_ms'] - phase_starts[r.phase_index]

        records.append(record)

    return records


def _post_process_optimized(session, exp_id, benchmark_start=None, phase_starts=None, enrich_from_requests=False):
    """
    Optimized post-processing using single set-based UPDATEs.

    The previous batched UPDATE approach was extremely slow because:
    1. Each batch iteration re-scanned and re-joined the entire tables
    2. The LIMIT in subquery prevented PostgreSQL from using indexes efficiently
    3. No stable ordering caused potential duplicate processing

    This new approach uses single UPDATE statements that let PostgreSQL
    optimize the entire operation using its query planner and indexes.

    Args:
        enrich_from_requests: If True, also enrich handler_events and rpc_calls
                             with phase/auth info from requests table (faster than
                             Python dict lookups during import for large datasets)
    """
    total_start = time.time()
    print(f"  Post-processing derived fields...", flush=True)

    # Step 0: Calculate relative_time_ms for all tables
    if benchmark_start:
        print(f"    Calculating relative_time_ms...", flush=True)
        step_start = time.time()

        # Requests
        result = session.execute(text("""
            UPDATE requests
            SET relative_time_ms = timestamp_ms - :start
            WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
        """), {"start": benchmark_start, "exp_id": exp_id})
        requests_updated = result.rowcount

        # Handler events
        result = session.execute(text("""
            UPDATE handler_events
            SET relative_time_ms = timestamp_ms - :start
            WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
        """), {"start": benchmark_start, "exp_id": exp_id})
        handlers_updated = result.rowcount

        # Lambda executions
        result = session.execute(text("""
            UPDATE lambda_executions
            SET relative_time_ms = timestamp_ms - :start
            WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
        """), {"start": benchmark_start, "exp_id": exp_id})
        lambda_updated = result.rowcount

        # RPC calls
        result = session.execute(text("""
            UPDATE rpc_calls
            SET relative_time_ms = timestamp_ms - :start
            WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
        """), {"start": benchmark_start, "exp_id": exp_id})
        rpc_updated = result.rowcount

        # Container starts
        result = session.execute(text("""
            UPDATE container_starts
            SET relative_time_ms = timestamp_ms - :start
            WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
        """), {"start": benchmark_start, "exp_id": exp_id})
        container_updated = result.rowcount

        session.commit()
        print(f"      Updated requests={requests_updated:,}, handlers={handlers_updated:,}, lambda={lambda_updated:,}, rpc={rpc_updated:,}, containers={container_updated:,} ({time.time() - step_start:.1f}s)", flush=True)

        # Calculate phase_relative_time_ms for requests
        if phase_starts:
            print(f"    Calculating phase_relative_time_ms for requests...", flush=True)
            step_start = time.time()

            # Build CASE statement for phase start times
            case_parts = []
            for phase_idx, start_ms in phase_starts.items():
                case_parts.append(f"WHEN {phase_idx} THEN {start_ms}")
            case_sql = "CASE phase_index " + " ".join(case_parts) + " ELSE 0 END"

            result = session.execute(text(f"""
                UPDATE requests
                SET phase_relative_time_ms = relative_time_ms - ({case_sql})
                WHERE experiment_id = :exp_id
                  AND relative_time_ms IS NOT NULL
                  AND phase_index IS NOT NULL
                  AND phase_relative_time_ms IS NULL
            """), {"exp_id": exp_id})
            phase_rel_updated = result.rowcount
            session.commit()
            print(f"      Updated {phase_rel_updated:,} rows ({time.time() - step_start:.1f}s)", flush=True)

    # Step 1: Enrich handler_events with phase/auth info from requests (if skipped during import)
    # NOTE: We join on context_id (not x_pair) because internal RPC calls (e.g., cart receiving
    # a call from frontend) have x_pairs that are generated call_x_pairs which don't exist in requests.
    if enrich_from_requests:
        print(f"    Enriching handler_events from requests...", flush=True)
        step_start = time.time()

        result = session.execute(text("""
            UPDATE handler_events h
            SET phase_index = r.phase_index,
                phase_name = r.phase_name,
                auth_type = r.auth_type
            FROM requests r
            WHERE h.experiment_id = :exp_id
              AND r.experiment_id = :exp_id
              AND h.context_id = r.context_id
              AND h.context_id IS NOT NULL
              AND h.phase_index IS NULL
        """), {"exp_id": exp_id})
        handler_enriched = result.rowcount
        session.commit()
        print(f"      Enriched {handler_enriched:,} handler_events ({time.time() - step_start:.1f}s)", flush=True)

        # Step 2: Calculate phase_relative_time_ms for handler_events
        if phase_starts:
            print(f"    Calculating phase_relative_time_ms for handler_events...", flush=True)
            step_start = time.time()

            # Build CASE statement for phase start times
            case_parts = []
            for phase_idx, start_ms in phase_starts.items():
                case_parts.append(f"WHEN {phase_idx} THEN {start_ms}")
            case_sql = "CASE phase_index " + " ".join(case_parts) + " ELSE 0 END"

            result = session.execute(text(f"""
                UPDATE handler_events
                SET phase_relative_time_ms = relative_time_ms - ({case_sql})
                WHERE experiment_id = :exp_id
                  AND relative_time_ms IS NOT NULL
                  AND phase_index IS NOT NULL
                  AND phase_relative_time_ms IS NULL
            """), {"exp_id": exp_id})
            phase_rel_updated = result.rowcount
            session.commit()
            print(f"      Updated {phase_rel_updated:,} rows ({time.time() - step_start:.1f}s)", flush=True)

        # Step 3: Enrich rpc_calls with phase/auth info from requests
        # NOTE: We join on context_id (not x_pair) because internal RPC calls have x_pairs
        # that are generated call_x_pairs which don't exist in the requests table.
        # The context_id is propagated throughout the entire call chain.
        print(f"    Enriching rpc_calls from requests...", flush=True)
        step_start = time.time()

        result = session.execute(text("""
            UPDATE rpc_calls rc
            SET phase_index = r.phase_index,
                phase_name = r.phase_name,
                auth_type = r.auth_type
            FROM requests r
            WHERE rc.experiment_id = :exp_id
              AND r.experiment_id = :exp_id
              AND rc.context_id = r.context_id
              AND rc.context_id IS NOT NULL
              AND rc.phase_index IS NULL
        """), {"exp_id": exp_id})
        rpc_enriched = result.rowcount
        session.commit()
        print(f"      Enriched {rpc_enriched:,} rpc_calls ({time.time() - step_start:.1f}s)", flush=True)

    # Step 4: Calculate handler_duration_ms and network_overhead_ms for requests
    print(f"    Calculating handler_duration_ms...", flush=True)
    step_start = time.time()

    # Count rows to process for progress feedback
    count_result = session.execute(text("""
        SELECT COUNT(*)
        FROM requests r
        WHERE r.experiment_id = :exp_id
          AND r.x_pair IS NOT NULL
          AND r.handler_duration_ms IS NULL
    """), {"exp_id": exp_id})
    total_to_process = count_result.scalar() or 0

    if total_to_process == 0:
        print(f"      No requests need handler_duration_ms calculation", flush=True)
    else:
        print(f"      Processing {total_to_process:,} requests...", flush=True)

        # Single set-based UPDATE - let PostgreSQL optimize using indexes
        result = session.execute(text("""
            UPDATE requests r
            SET handler_duration_ms = he.duration_ms,
                network_overhead_ms = r.latency_ms - he.duration_ms
            FROM handler_events he
            WHERE r.experiment_id = :exp_id
              AND he.experiment_id = :exp_id
              AND r.x_pair = he.x_pair
              AND r.x_pair IS NOT NULL
              AND he.duration_ms IS NOT NULL
              AND r.handler_duration_ms IS NULL
        """), {"exp_id": exp_id})

        updated = result.rowcount
        session.commit()
        print(f"      Updated {updated:,} requests ({time.time() - step_start:.1f}s)", flush=True)

    print(f"  Post-processing completed in {time.time() - total_start:.1f}s", flush=True)



def import_experiment(
    session: Session,
    experiment_dir: Path,
    force: bool = False,
    batch_size: int = 10000,
    skip_post_processing: bool = False,
) -> Optional[int]:
    """
    Import a single experiment directory into the database.

    Args:
        session: SQLAlchemy session
        experiment_dir: Path to experiment directory
        force: If True, delete existing experiment data before importing
        batch_size: Batch size for large table inserts
        skip_post_processing: If True, skip post-processing (caller handles it after index rebuild)

    Returns:
        Experiment ID if successful, None otherwise
    """
    if not experiment_dir.is_dir():
        print(f"Error: {experiment_dir} is not a directory")
        return None

    print(f"\nImporting: {experiment_dir.name}")

    # Parse directory name for basic metadata
    dir_meta = parse_directory_name(experiment_dir)
    print(f"  Architecture: {dir_meta.architecture}, Auth: {dir_meta.auth_strategy}")

    # Check if experiment already exists
    existing = session.execute(
        select(Experiment).where(Experiment.name == dir_meta.name)
    ).scalar_one_or_none()

    if existing:
        if force:
            print(f"  Deleting existing experiment (id={existing.id})")
            session.execute(delete(Experiment).where(Experiment.id == existing.id))
            session.flush()
        else:
            # Check if the previous import completed: if the directory is not renamed
            # (no '.' prefix), this import was interrupted. Re-import it.
            renamed_path = experiment_dir.parent / f".{experiment_dir.name}"
            if renamed_path.exists():
                # Both renamed and original exist - shouldn't happen, skip
                print(f"  Experiment already exists (id={existing.id}), skipping. Use --force to reimport.")
                return existing.id
            # Directory not renamed → previous import was interrupted, re-import
            request_count = session.execute(
                text("SELECT COUNT(*) FROM requests WHERE experiment_id = :eid"),
                {"eid": existing.id}
            ).scalar() or 0
            if request_count > 0:
                # Has data and directory not renamed → likely post-processing was interrupted.
                # Skip COPY phase, just return ID so post-processing can re-run.
                print(f"  Experiment exists (id={existing.id}) with {request_count:,} requests - resuming post-processing")
                return existing.id
            else:
                # No data → previous import failed early, delete and reimport
                print(f"  Experiment exists (id={existing.id}) but has no data - reimporting")
                session.execute(delete(Experiment).where(Experiment.id == existing.id))
                session.flush()

    # Parse configuration files
    hardware_config = parse_hardware_config(experiment_dir / "hardware_config.json")
    benchmark_config = parse_benchmark_config(experiment_dir / "benchmark_configuration.json")
    start_time = parse_experiment_start_time(experiment_dir / "experiment_start_time.txt")
    error_desc = parse_error_description(experiment_dir / "error_description.md")
    pricing_data = parse_pricing(experiment_dir / "pricing" / "pricing.json")

    # Determine AWS service type
    aws_service = None
    if dir_meta.architecture == 'faas':
        aws_service = 'lambda'
    elif dir_meta.architecture in ('microservices', 'monolith'):
        aws_service = 'ecs_fargate'

    # Use hardware config values if available, fallback to directory parsing
    # Note: Some hardware configs have ram_in_mb=0, so use directory name as fallback
    ram_in_mb = dir_meta.ram_in_mb
    cpu_in_vcpu = dir_meta.cpu_in_vcpu
    if hardware_config:
        if hardware_config.ram_in_mb and hardware_config.ram_in_mb > 0:
            ram_in_mb = hardware_config.ram_in_mb
        if hardware_config.cpu_in_vcpu:
            cpu_in_vcpu = hardware_config.cpu_in_vcpu

    # Determine http_timeout: from config file, or use known defaults by architecture
    # Default timeouts: FaaS=10s, microservices/monolith=30s
    http_timeout = None
    if benchmark_config and benchmark_config.http_timeout_seconds:
        http_timeout = benchmark_config.http_timeout_seconds
    else:
        # Apply known defaults when config file is missing
        if dir_meta.architecture == 'faas':
            http_timeout = 10
        elif dir_meta.architecture in ('microservices', 'monolith'):
            http_timeout = 30

    # Create experiment record
    experiment = Experiment(
        name=dir_meta.name,
        architecture=dir_meta.architecture,
        auth_strategy=dir_meta.auth_strategy,
        run_timestamp=dir_meta.run_timestamp,
        aws_service=aws_service,
        ram_in_mb=ram_in_mb or 0,
        bundle_mode=hardware_config.bundle_mode if hardware_config else None,
        cpu_in_vcpu=cpu_in_vcpu,
        cpu_units=int(cpu_in_vcpu * 1024) if cpu_in_vcpu else None,
        password_hash_algorithm=hardware_config.password_hash_algorithm if hardware_config else None,
        jwt_sign_algorithm=hardware_config.jwt_sign_algorithm if hardware_config else None,
        http_timeout_seconds=http_timeout,
        start_timestamp_ms=start_time.timestamp_ms if start_time else None,
        error_description=error_desc,
    )

    # Add pricing metadata if available
    if pricing_data:
        experiment.pricing_region = pricing_data.meta.region
        experiment.pricing_start_time = pricing_data.meta.start_time
        experiment.pricing_end_time = pricing_data.meta.end_time
        experiment.pricing_duration_minutes = pricing_data.meta.duration_minutes
        experiment.pricing_duration_hours = pricing_data.meta.duration_hours
        experiment.pricing_collected_at = pricing_data.meta.collected_at

    session.add(experiment)
    session.flush()  # Get experiment ID
    exp_id = experiment.id
    print(f"  Created experiment (id={exp_id})")

    # Import per-service scaling rules (ECS only)
    if hardware_config and hardware_config.scaling_rules:
        for rule in hardware_config.scaling_rules:
            session.add(ScalingRule(
                experiment_id=exp_id,
                service_name=rule.service_name,
                rule_type=rule.rule_type,
                target_value=rule.target_value,
                min_capacity=rule.min_capacity,
                max_capacity=rule.max_capacity,
                cpu_units=rule.cpu_units,
                memory_mb=rule.memory_mb,
                scale_in_cooldown_sec=rule.scale_in_cooldown_sec,
                scale_out_cooldown_sec=rule.scale_out_cooldown_sec,
            ))
        services = set(r.service_name for r in hardware_config.scaling_rules)
        print(f"  Imported {len(hardware_config.scaling_rules)} scaling rules for {len(services)} service(s)")

    # Import pricing data
    if pricing_data:
        pricing_record = Pricing(experiment_id=exp_id)

        # Lambda pricing
        if pricing_data.lambda_pricing:
            lp = pricing_data.lambda_pricing
            pricing_record.lambda_total_invocations = lp.total_invocations
            pricing_record.lambda_total_duration_ms = lp.total_duration_ms
            pricing_record.lambda_total_gb_seconds = lp.total_gb_seconds
            pricing_record.lambda_memory_gb = lp.memory_gb
            pricing_record.lambda_request_cost = lp.request_cost
            pricing_record.lambda_compute_cost = lp.compute_cost
            pricing_record.lambda_total_cost = lp.total_cost

        # API Gateway
        if pricing_data.api_gateway:
            ag = pricing_data.api_gateway
            pricing_record.api_gw_total_requests = ag.total_requests
            pricing_record.api_gw_cost = ag.cost
            pricing_record.api_gw_rate_per_million = ag.rate_per_million

        # Fargate
        if pricing_data.fargate:
            fg = pricing_data.fargate
            pricing_record.fargate_task_cpu = fg.task_cpu
            pricing_record.fargate_task_memory_mb = fg.task_memory_mb
            pricing_record.fargate_total_cost = fg.total_cost
            pricing_record.fargate_rate_vcpu_per_hour = fg.rate_vcpu_per_hour
            pricing_record.fargate_rate_memory_gb_per_hour = fg.rate_memory_gb_per_hour

        # ALB
        if pricing_data.alb:
            alb = pricing_data.alb
            pricing_record.alb_duration_hours = alb.duration_hours
            pricing_record.alb_hourly_cost = alb.hourly_cost
            pricing_record.alb_estimated_lcu = alb.estimated_lcu
            pricing_record.alb_lcu_cost = alb.lcu_cost
            pricing_record.alb_total_cost = alb.total_cost
            pricing_record.alb_rate_hourly = alb.rate_hourly
            pricing_record.alb_rate_lcu_per_hour = alb.rate_lcu_per_hour

        # Redis
        if pricing_data.redis:
            rd = pricing_data.redis
            pricing_record.redis_instance_type = rd.instance_type
            pricing_record.redis_duration_hours = rd.duration_hours
            pricing_record.redis_hourly_rate = rd.hourly_rate
            pricing_record.redis_total_cost = rd.total_cost

        # Cognito
        if pricing_data.cognito:
            cg = pricing_data.cognito
            pricing_record.cognito_mau = cg.mau
            pricing_record.cognito_cost = cg.cost
            pricing_record.cognito_rate_first_50k = cg.rate_first_50k
            pricing_record.cognito_rate_next_50k = cg.rate_next_50k
            pricing_record.cognito_rate_next_900k = cg.rate_next_900k
            pricing_record.cognito_rate_over_1m = cg.rate_over_1m
            pricing_record.cognito_note = cg.note

        session.add(pricing_record)
        print(f"  Imported pricing summary")

        # Import per-function Lambda pricing
        for fn in pricing_data.lambda_functions:
            session.add(PricingComponent(
                experiment_id=exp_id,
                component_type='lambda_function',
                component_name=fn.function_name,
                invocations=fn.invocations,
                duration_ms=fn.duration_ms,
                gb_seconds=fn.gb_seconds,
                request_cost=fn.request_cost,
                compute_cost=fn.compute_cost,
                total_cost=fn.total_cost,
            ))

        # Import per-service Fargate pricing
        for svc in pricing_data.fargate_services:
            session.add(PricingComponent(
                experiment_id=exp_id,
                component_type='fargate_service',
                component_name=svc.service_name,
                task_cpu=svc.task_cpu,
                task_memory_mb=svc.task_memory_mb,
                avg_running_tasks=svc.avg_running_tasks,
                vcpu_hours=svc.vcpu_hours,
                memory_gb_hours=svc.memory_gb_hours,
                vcpu_cost=svc.vcpu_cost,
                memory_cost=svc.memory_cost,
                total_cost=svc.total_cost,
            ))

        component_count = len(pricing_data.lambda_functions) + len(pricing_data.fargate_services)
        if component_count > 0:
            print(f"  Imported {component_count} pricing components")

    session.flush()

    # Import CloudWatch metrics
    alb_metrics_path = experiment_dir / "cloudwatch" / "alb_metrics.csv"
    if alb_metrics_path.exists():
        alb_metrics = parse_alb_metrics(alb_metrics_path)
        if alb_metrics:
            records = [
                {
                    'experiment_id': exp_id,
                    'timestamp': m.timestamp,
                    'request_count': m.request_count,
                    'response_time_avg': m.response_time_avg,
                    'response_time_p95': m.response_time_p95,
                    'http_2xx_count': m.http_2xx_count,
                    'http_4xx_count': m.http_4xx_count,
                    'http_5xx_count': m.http_5xx_count,
                    'active_connections': m.active_connections,
                    'healthy_hosts': m.healthy_hosts,
                }
                for m in alb_metrics
            ]
            _batch_insert(session, MetricsAlb, records)
            print(f"  Imported {len(records)} ALB metrics")

    ecs_metrics_path = experiment_dir / "cloudwatch" / "ecs_metrics.csv"
    if ecs_metrics_path.exists():
        ecs_metrics = parse_ecs_metrics(ecs_metrics_path)
        if ecs_metrics:
            records = [
                {
                    'experiment_id': exp_id,
                    'timestamp': m.timestamp,
                    'service_name': m.service_name,
                    'cpu_percent': m.cpu_percent,
                    'memory_percent': m.memory_percent,
                    'running_tasks': m.running_tasks,
                    'desired_tasks': m.desired_tasks,
                }
                for m in ecs_metrics
            ]
            _batch_insert(session, MetricsEcs, records)
            print(f"  Imported {len(records)} ECS metrics")

    session.flush()

    # Import artillery log (client-side requests)
    artillery_path = experiment_dir / "logs" / "artillery.log"
    # These will be populated during request parsing for use in aws.log parsing
    x_pair_lookup = {}
    benchmark_start_ms = None
    phase_starts = {}

    if artillery_path.exists():
        print(f"  Parsing artillery.log...")
        total_requests = 0
        records_since_commit = 0  # Track records since last commit
        phases_imported = False
        phases_data = []
        start = time.time()

        # Buffer for chunked COPY insert
        request_buffer = []

        def flush_request_buffer(force_commit=False):
            """Flush request buffer to database using COPY."""
            nonlocal request_buffer, total_requests, records_since_commit
            if not request_buffer:
                return
            if USE_COPY_INSERT:
                # Commit periodically to prevent memory buildup in PostgreSQL
                should_commit = force_commit or (
                    COMMIT_EVERY_N_RECORDS > 0 and
                    records_since_commit + len(request_buffer) >= COMMIT_EVERY_N_RECORDS
                )
                _copy_insert(session, 'requests', request_buffer, TABLE_COLUMNS['requests'], commit=should_commit)
                if should_commit:
                    records_since_commit = 0
                else:
                    records_since_commit += len(request_buffer)
            else:
                _batch_insert(session, Request, request_buffer)
            total_requests += len(request_buffer)
            request_buffer = []

            # Backpressure: small delay to prevent overwhelming the database
            if FLUSH_DELAY_SECONDS > 0:
                time.sleep(FLUSH_DELAY_SECONDS)

        for result, requests in parse_artillery_log(artillery_path, batch_size=batch_size):
            # Import phases from first batch
            if not phases_imported and result.phases:
                for phase in result.phases:
                    phase_obj = Phase(
                        experiment_id=exp_id,
                        phase_index=phase.index,
                        phase_name=phase.name,
                        duration_seconds=phase.duration_seconds,
                    )
                    session.add(phase_obj)
                    phases_data.append(phase_obj)

                # Pre-calculate phase start times for optimized record creation
                if USE_OPTIMIZED_PROCESSING:
                    phase_starts = _calculate_phase_starts(phases_data)

                session.flush()  # Commit phases before inserting requests
                print(f"  Imported {len(result.phases)} phases")
                phases_imported = True

            # Update benchmark timestamps
            if result.benchmark_start_ms:
                experiment.benchmark_start_ms = result.benchmark_start_ms
                benchmark_start_ms = result.benchmark_start_ms  # Store for aws.log parsing
            if result.benchmark_end_ms:
                experiment.benchmark_end_ms = result.benchmark_end_ms

            # Build request records
            if requests:
                if USE_OPTIMIZED_PROCESSING:
                    # Use optimized record creation with pre-calculated derived fields
                    records = _create_optimized_request_records(
                        requests, exp_id,
                        benchmark_start=result.benchmark_start_ms,
                        phase_starts=phase_starts
                    )
                    # Build context_id lookup only if NOT deferring enrichment to post-processing
                    # NOTE: We use context_id (not x_pair) because internal RPC calls have x_pairs
                    # that are generated call_x_pairs which don't exist in requests.
                    # Skipping this saves ~500MB memory and processing time for large datasets
                    if not ENRICH_IN_POST_PROCESSING:
                        for r in requests:
                            if r.context_id:
                                x_pair_lookup[r.context_id] = {
                                    'phase_index': r.phase_index,
                                    'phase_name': r.phase_name,
                                    'auth_type': r.auth_type,
                                    'latency_ms': getattr(r, '_latency_ms', None),
                                }
                else:
                    # Legacy record creation
                    records = [
                        {
                            'experiment_id': exp_id,
                            'x_pair': r.x_pair,
                            'context_id': r.context_id,
                            'timestamp_ms': r.timestamp_ms,
                            'latency_ms': getattr(r, '_latency_ms', None),
                            'endpoint': r.endpoint,
                            'status_code': r.status_code,
                            'auth_type': r.auth_type,
                            'phase_index': r.phase_index,
                            'phase_name': r.phase_name,
                            'is_error': r.is_error,
                            'is_timeout': r.is_timeout,
                            'error_type': r.error_type,
                            'error_code': r.error_code,
                        }
                        for r in requests
                    ]

                request_buffer.extend(records)

                # Flush when buffer is large enough
                if len(request_buffer) >= COPY_BATCH_SIZE:
                    flush_request_buffer()

                current_count = total_requests + len(request_buffer)
                if current_count % 100000 == 0 and current_count > 0:
                    elapsed = time.time() - start
                    rate = current_count / elapsed if elapsed > 0 else 0
                    print(f"    Requests: {current_count:,} ({rate:,.0f}/s)...", flush=True)

        # Final flush with forced commit
        flush_request_buffer(force_commit=True)

        if total_requests > 0:
            elapsed = time.time() - start
            rate = total_requests / elapsed if elapsed > 0 else 0
            print(f"  Imported {total_requests:,} requests in {elapsed:.1f}s ({rate:,.0f}/s)")
            if x_pair_lookup and not ENRICH_IN_POST_PROCESSING:
                print(f"  Built context_id lookup with {len(x_pair_lookup):,} entries for enrichment")
            elif ENRICH_IN_POST_PROCESSING:
                print(f"  Enrichment deferred to post-processing (faster for large datasets)")

    # Import AWS log (server-side events)
    aws_log_path = experiment_dir / "logs" / "aws.log"
    if aws_log_path.exists():
        if ENRICH_IN_POST_PROCESSING:
            print(f"  Parsing aws.log (enrichment deferred to post-processing)...")
        else:
            print(f"  Parsing aws.log (with insert-time enrichment)...")

        # Use streaming COPY: collect events up to COPY_BATCH_SIZE, then flush
        all_lambda = []
        all_handlers = []
        all_container_starts = []
        all_rpc = []
        total_lambda = 0
        total_handlers = 0
        total_container_starts = 0
        total_rpc = 0
        event_count = 0
        records_since_commit = 0  # Track records since last commit
        start = time.time()

        def flush_buffers(force_commit=False):
            """Flush all buffers to database using COPY."""
            nonlocal all_lambda, all_handlers, all_container_starts, all_rpc
            nonlocal total_lambda, total_handlers, total_container_starts, total_rpc
            nonlocal records_since_commit

            batch_total = len(all_lambda) + len(all_handlers) + len(all_container_starts) + len(all_rpc)
            if batch_total == 0:
                return

            # Determine if we should commit after this flush
            should_commit = force_commit or (
                COMMIT_EVERY_N_RECORDS > 0 and
                records_since_commit + batch_total >= COMMIT_EVERY_N_RECORDS
            )

            if USE_COPY_INSERT:
                if all_lambda:
                    _copy_insert(session, 'lambda_executions', all_lambda, TABLE_COLUMNS['lambda_executions'])
                    total_lambda += len(all_lambda)
                    all_lambda = []
                if all_handlers:
                    _copy_insert(session, 'handler_events', all_handlers, TABLE_COLUMNS['handler_events'])
                    total_handlers += len(all_handlers)
                    all_handlers = []
                if all_container_starts:
                    _copy_insert(session, 'container_starts', all_container_starts, TABLE_COLUMNS['container_starts'])
                    total_container_starts += len(all_container_starts)
                    all_container_starts = []
                if all_rpc:
                    _copy_insert(session, 'rpc_calls', all_rpc, TABLE_COLUMNS['rpc_calls'])
                    total_rpc += len(all_rpc)
                    all_rpc = []

                # Commit to free PostgreSQL buffers and prevent memory buildup
                if should_commit:
                    session.commit()
                    records_since_commit = 0
                else:
                    records_since_commit += batch_total
            else:
                if all_lambda:
                    _batch_insert(session, LambdaExecution, all_lambda)
                    total_lambda += len(all_lambda)
                    all_lambda = []
                if all_handlers:
                    _batch_insert(session, HandlerEvent, all_handlers)
                    total_handlers += len(all_handlers)
                    all_handlers = []
                if all_container_starts:
                    _batch_insert(session, ContainerStart, all_container_starts)
                    total_container_starts += len(all_container_starts)
                    all_container_starts = []
                if all_rpc:
                    _batch_insert(session, RpcCall, all_rpc)
                    total_rpc += len(all_rpc)
                    all_rpc = []

            # Backpressure: small delay to prevent overwhelming the database
            if FLUSH_DELAY_SECONDS > 0:
                time.sleep(FLUSH_DELAY_SECONDS)

        for batch in parse_aws_log(aws_log_path, batch_size=batch_size):
            # Lambda executions - with relative_time_ms calculated at insert
            if batch.lambda_executions:
                for record in _create_lambda_execution_records(
                    batch.lambda_executions, exp_id,
                    benchmark_start=benchmark_start_ms
                ):
                    all_lambda.append(record)

            # Handler events - with all derived fields calculated at insert
            if batch.handler_events:
                for record in _create_handler_event_records(
                    batch.handler_events, exp_id,
                    benchmark_start=benchmark_start_ms,
                    phase_starts=phase_starts,
                    x_pair_lookup=x_pair_lookup,
                    skip_enrichment=ENRICH_IN_POST_PROCESSING
                ):
                    all_handlers.append(record)

            # Container starts - with relative_time_ms calculated at insert
            if batch.container_starts:
                for record in _create_container_start_records(
                    batch.container_starts, exp_id,
                    benchmark_start=benchmark_start_ms
                ):
                    all_container_starts.append(record)

            # RPC calls - with derived fields calculated at insert
            if batch.rpc_calls:
                for record in _create_rpc_call_records(
                    batch.rpc_calls, exp_id,
                    benchmark_start=benchmark_start_ms,
                    x_pair_lookup=x_pair_lookup,
                    skip_enrichment=ENRICH_IN_POST_PROCESSING
                ):
                    all_rpc.append(record)

            # Flush buffers when they get large enough
            buffer_size = len(all_lambda) + len(all_handlers) + len(all_container_starts) + len(all_rpc)
            if buffer_size >= COPY_BATCH_SIZE:
                flush_buffers()

            # Progress update
            event_count = total_lambda + total_handlers + total_container_starts + total_rpc + buffer_size
            if event_count % 500000 == 0 and event_count > 0:
                elapsed = time.time() - start
                rate = event_count / elapsed if elapsed > 0 else 0
                print(f"    Events: {event_count:,} ({rate:,.0f}/s)...", flush=True)

        # Final flush with forced commit
        flush_buffers(force_commit=True)

        elapsed = time.time() - start
        total_events = total_lambda + total_handlers + total_container_starts + total_rpc
        rate = total_events / elapsed if elapsed > 0 else 0
        print(f"  Inserted {total_events:,} events in {elapsed:.1f}s ({rate:,.0f}/s)")
        print(f"  Imported from aws.log:")
        if total_lambda > 0:
            print(f"    Lambda executions: {total_lambda:,}")
        if total_handlers > 0:
            print(f"    Handler events: {total_handlers:,}")
        if total_container_starts > 0:
            print(f"    Container starts: {total_container_starts:,}")
        if total_rpc > 0:
            print(f"    RPC calls: {total_rpc:,}")

    # Note: Data has been committed during import, no need for additional flush

    if skip_post_processing:
        session.commit()
        print(f"  Data import complete for experiment {exp_id} (post-processing deferred)")
        return exp_id

    # === POST-PROCESSING: Calculate derived fields ===
    _run_post_processing(session, exp_id, experiment, phase_starts)

    session.commit()
    print(f"  Completed import for experiment {exp_id}")

    # Rename directory to mark as imported (add '.' prefix)
    _rename_imported_dir(experiment_dir)

    return exp_id


def _rename_imported_dir(experiment_dir: Path):
    """Rename directory to mark as imported (add '.' prefix)."""
    new_name = f".{experiment_dir.name}"
    new_path = experiment_dir.parent / new_name
    try:
        experiment_dir.rename(new_path)
        print(f"  Renamed directory to: {new_name}")
    except OSError as e:
        print(f"  Warning: Could not rename directory: {e}")


def _run_post_processing(session: Session, exp_id: int, experiment, phase_starts: dict):
    """Run post-processing for a single experiment (requires indexes to be present)."""
    if USE_OPTIMIZED_PROCESSING:
        # Use optimized post-processing with bulk operations
        # If ENRICH_IN_POST_PROCESSING is enabled, also enrich handler_events and rpc_calls
        _post_process_optimized(
            session, exp_id, experiment.benchmark_start_ms,
            phase_starts=phase_starts,
            enrich_from_requests=ENRICH_IN_POST_PROCESSING
        )
    else:
        # Legacy post-processing (for rollback compatibility)
        print(f"  Post-processing: calculating derived fields (legacy)...")

        # Get benchmark_start_ms for relative time calculations
        benchmark_start = experiment.benchmark_start_ms
        if benchmark_start:
            # Calculate relative_time_ms for requests
            session.execute(text("""
                UPDATE requests
                SET relative_time_ms = timestamp_ms - :start
                WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
            """), {"start": benchmark_start, "exp_id": exp_id})

            # Calculate relative_time_ms for handler_events
            session.execute(text("""
                UPDATE handler_events
                SET relative_time_ms = timestamp_ms - :start
                WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
            """), {"start": benchmark_start, "exp_id": exp_id})

            # Calculate relative_time_ms for lambda_executions
            session.execute(text("""
                UPDATE lambda_executions
                SET relative_time_ms = timestamp_ms - :start
                WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
            """), {"start": benchmark_start, "exp_id": exp_id})

            # Calculate relative_time_ms for rpc_calls
            session.execute(text("""
                UPDATE rpc_calls
                SET relative_time_ms = timestamp_ms - :start
                WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
            """), {"start": benchmark_start, "exp_id": exp_id})

            # Calculate relative_time_ms for container_starts
            session.execute(text("""
                UPDATE container_starts
                SET relative_time_ms = timestamp_ms - :start
                WHERE experiment_id = :exp_id AND relative_time_ms IS NULL
            """), {"start": benchmark_start, "exp_id": exp_id})

            print(f"    Calculated relative_time_ms for all tables")

        # Calculate phase_relative_time_ms for requests (requires phase start times)
        # First, get phase start times from the phases table
        session.execute(text("""
            UPDATE requests r
            SET phase_relative_time_ms = r.relative_time_ms - (
                SELECT COALESCE(SUM(p2.duration_seconds) * 1000, 0)
                FROM phases p2
                WHERE p2.experiment_id = r.experiment_id
                  AND p2.phase_index < r.phase_index
            )
            WHERE r.experiment_id = :exp_id
              AND r.relative_time_ms IS NOT NULL
              AND r.phase_index IS NOT NULL
              AND r.phase_relative_time_ms IS NULL
        """), {"exp_id": exp_id})
        print(f"    Calculated phase_relative_time_ms for requests")

        # Enrich handler_events with phase info from requests (via context_id join)
        # NOTE: We join on context_id (not x_pair) because internal RPC calls have x_pairs
        # that are generated call_x_pairs which don't exist in the requests table.
        session.execute(text("""
            UPDATE handler_events h
            SET phase_index = r.phase_index,
                phase_name = r.phase_name,
                auth_type = r.auth_type
            FROM requests r
            WHERE h.experiment_id = :exp_id
              AND r.experiment_id = :exp_id
              AND h.context_id = r.context_id
              AND h.context_id IS NOT NULL
              AND h.phase_index IS NULL
        """), {"exp_id": exp_id})
        print(f"    Enriched handler_events with phase/auth info from requests")

        # Calculate phase_relative_time_ms for handler_events
        session.execute(text("""
            UPDATE handler_events h
            SET phase_relative_time_ms = h.relative_time_ms - (
                SELECT COALESCE(SUM(p2.duration_seconds) * 1000, 0)
                FROM phases p2
                WHERE p2.experiment_id = h.experiment_id
                  AND p2.phase_index < h.phase_index
            )
            WHERE h.experiment_id = :exp_id
              AND h.relative_time_ms IS NOT NULL
              AND h.phase_index IS NOT NULL
              AND h.phase_relative_time_ms IS NULL
        """), {"exp_id": exp_id})
        print(f"    Calculated phase_relative_time_ms for handler_events")

        # Enrich rpc_calls with phase/auth info from requests (via context_id join)
        # NOTE: We join on context_id (not x_pair) because internal RPC calls have x_pairs
        # that are generated call_x_pairs which don't exist in the requests table.
        session.execute(text("""
            UPDATE rpc_calls rc
            SET phase_index = r.phase_index,
                phase_name = r.phase_name,
                auth_type = r.auth_type
            FROM requests r
            WHERE rc.experiment_id = :exp_id
              AND r.experiment_id = :exp_id
              AND rc.context_id = r.context_id
              AND rc.context_id IS NOT NULL
              AND rc.phase_index IS NULL
        """), {"exp_id": exp_id})
        print(f"    Enriched rpc_calls with phase/auth info from requests")

        # Calculate is_protected_endpoint based on route patterns
        # Protected endpoints typically require auth (non-login/register routes under /api/)
        session.execute(text("""
            UPDATE handler_events
            SET is_protected_endpoint = CASE
                WHEN route LIKE '%/login%' THEN FALSE
                WHEN route LIKE '%/register%' THEN FALSE
                WHEN route LIKE '%/health%' THEN FALSE
                WHEN route LIKE 'GET /api/products%' THEN FALSE
                WHEN route LIKE '%/api/%' THEN TRUE
                ELSE FALSE
            END
            WHERE experiment_id = :exp_id AND is_protected_endpoint IS NULL
        """), {"exp_id": exp_id})
        print(f"    Calculated is_protected_endpoint for handler_events")

        # Calculate handler_duration_ms and network_overhead_ms for requests
        session.execute(text("""
            UPDATE requests r
            SET handler_duration_ms = h.duration_ms,
                network_overhead_ms = r.latency_ms - h.duration_ms
            FROM handler_events h
            WHERE r.experiment_id = :exp_id
              AND h.experiment_id = :exp_id
              AND r.x_pair = h.x_pair
              AND r.x_pair IS NOT NULL
              AND r.handler_duration_ms IS NULL
              AND h.duration_ms IS NOT NULL
        """), {"exp_id": exp_id})
        print(f"    Calculated handler_duration_ms and network_overhead_ms for requests")


def import_all_experiments(
    session: Session,
    results_dir: Path,
    force: bool = False,
    batch_size: int = 10000,
) -> list[int]:
    """
    Import all experiments from a results directory.

    Uses a two-phase approach when indexes are dropped:
      Phase 1: COPY all experiment data without indexes (fast bulk insert)
      Phase 2: Rebuild indexes, then run post-processing for all experiments (fast JOINs)

    This prevents the previous issue where post-processing JOINs ran without indexes,
    causing quadratic slowdown and apparent freezes after 5-8 experiments.

    Args:
        session: SQLAlchemy session
        results_dir: Path to directory containing experiment subdirectories
        force: If True, reimport existing experiments
        batch_size: Batch size for large table inserts

    Returns:
        List of imported experiment IDs
    """
    if not results_dir.is_dir():
        print(f"Error: {results_dir} is not a directory")
        return []

    # Find all experiment directories
    exp_dirs = sorted([
        d for d in results_dir.iterdir()
        if d.is_dir() and not d.name.startswith('.')
    ])

    print(f"Found {len(exp_dirs)} experiment directories")

    if len(exp_dirs) == 0:
        return []

    defer_post_processing = DROP_INDEXES_DURING_IMPORT and USE_COPY_INSERT

    # Enable fast import mode
    if USE_COPY_INSERT:
        print("  Enabling fast import mode (synchronous_commit=OFF)...")
        _set_fast_import_mode(session, enable=True)

    # Drop indexes before bulk import for faster inserts
    if defer_post_processing:
        _drop_all_large_table_indexes(session)
        session.commit()

    import_start = time.time()
    imported_ids = []
    # Track experiment dirs for deferred post-processing
    imported_dirs = []
    try:
        # Phase 1: Import all experiment data (COPY only when indexes are dropped)
        for i, exp_dir in enumerate(exp_dirs, 1):
            print(f"\n[{i}/{len(exp_dirs)}] ", end="")
            exp_id = import_experiment(
                session, exp_dir, force=force, batch_size=batch_size,
                skip_post_processing=defer_post_processing,
            )
            if exp_id:
                imported_ids.append(exp_id)
                if defer_post_processing:
                    imported_dirs.append(exp_dir)
    finally:
        # Rebuild indexes after all COPY inserts complete
        if defer_post_processing:
            _rebuild_all_indexes(session)
            session.commit()

        # Restore normal PostgreSQL settings
        if USE_COPY_INSERT:
            print("  Restoring normal database settings...")
            _set_fast_import_mode(session, enable=False)
            session.commit()

    # Phase 2: Run post-processing for all experiments (with indexes present)
    if defer_post_processing and imported_ids:
        print(f"\n=== Post-processing {len(imported_ids)} experiments (with indexes) ===")
        for i, exp_id in enumerate(imported_ids, 1):
            print(f"\n[{i}/{len(imported_ids)}] Post-processing experiment {exp_id}...")
            experiment = session.execute(
                select(Experiment).where(Experiment.id == exp_id)
            ).scalar_one()

            # Reconstruct phase_starts from the phases table
            phases = session.execute(
                select(Phase).where(Phase.experiment_id == exp_id).order_by(Phase.phase_index)
            ).scalars().all()
            phase_starts = _calculate_phase_starts(phases) if phases else {}

            _run_post_processing(session, exp_id, experiment, phase_starts)
            session.commit()

        # Rename directories after successful post-processing
        for exp_dir in imported_dirs:
            _rename_imported_dir(exp_dir)

    total_time = time.time() - import_start
    print(f"\nImported {len(imported_ids)} experiments in {total_time:.1f}s")
    return imported_ids


def backfill_nulls(session: Session):
    """
    Backfill NULL columns across all experiments using derived data.

    This fixes columns that were left NULL during import because the
    enrichment JOIN (context_id match between handler_events/rpc_calls
    and requests) failed. This happens for:
    - Monolith experiments: server-side instrumentation generates different
      x_pair/context_id values than the client (Artillery)
    - Internal RPC calls: triggered by other handlers, not direct client requests,
      so their context_ids don't appear in the requests table
    - Experiments without phases defined

    Strategy:
    1. auth_type: Set from experiments.auth_strategy (same for all rows in an experiment)
    2. phase_index/phase_name: Assign based on relative_time_ms falling within phase
       time boundaries (derived from requests table per experiment)
    3. phase_relative_time_ms: Calculate from relative_time_ms and phase start boundary

    Columns that remain NULL after backfill (inherently missing data):
    - metrics_alb/metrics_ecs partial NULLs: CloudWatch data gaps
    - requests.handler_duration_ms: No matching handler_events by x_pair
    - relative_time_ms where benchmark_start_ms is NULL
    """
    total_start = time.time()
    print("\n=== Backfilling NULL columns ===\n", flush=True)

    # Increase work_mem for faster UPDATE operations
    session.execute(text("SET work_mem = '256MB'"))

    # Get all experiments
    experiments = session.execute(
        select(Experiment).order_by(Experiment.id)
    ).scalars().all()

    total_stats = {
        'handler_auth': 0,
        'handler_phase': 0,
        'handler_phase_rel': 0,
        'rpc_auth': 0,
        'rpc_phase': 0,
        'request_auth': 0,
    }

    for exp in experiments:
        exp_id = exp.id
        exp_start = time.time()
        print(f"[Experiment {exp_id}] {exp.name}", flush=True)

        # --- Step 1: Set auth_type from experiment's auth_strategy ---
        auth_strategy = exp.auth_strategy

        result = session.execute(text("""
            UPDATE handler_events
            SET auth_type = :auth
            WHERE experiment_id = :exp_id AND auth_type IS NULL
        """), {"auth": auth_strategy, "exp_id": exp_id})
        handler_auth_updated = result.rowcount
        total_stats['handler_auth'] += handler_auth_updated
        if handler_auth_updated:
            session.commit()

        result = session.execute(text("""
            UPDATE rpc_calls
            SET auth_type = :auth
            WHERE experiment_id = :exp_id AND auth_type IS NULL
        """), {"auth": auth_strategy, "exp_id": exp_id})
        rpc_auth_updated = result.rowcount
        total_stats['rpc_auth'] += rpc_auth_updated
        if rpc_auth_updated:
            session.commit()

        result = session.execute(text("""
            UPDATE requests
            SET auth_type = :auth
            WHERE experiment_id = :exp_id AND auth_type IS NULL
        """), {"auth": auth_strategy, "exp_id": exp_id})
        request_auth_updated = result.rowcount
        total_stats['request_auth'] += request_auth_updated
        if request_auth_updated:
            session.commit()

        if handler_auth_updated or rpc_auth_updated or request_auth_updated:
            print(f"  auth_type: handlers={handler_auth_updated:,}, rpc={rpc_auth_updated:,}, requests={request_auth_updated:,}", flush=True)

        # --- Step 2: Compute phase boundaries from requests ---
        # For each phase, get the min and max relative_time_ms from requests
        phase_boundaries = session.execute(text("""
            SELECT phase_index, phase_name,
                   MIN(relative_time_ms) as phase_start,
                   MAX(relative_time_ms) as phase_end
            FROM requests
            WHERE experiment_id = :exp_id
              AND phase_index IS NOT NULL
              AND relative_time_ms IS NOT NULL
            GROUP BY phase_index, phase_name
            ORDER BY phase_index
        """), {"exp_id": exp_id}).fetchall()

        if not phase_boundaries:
            print(f"  No phase boundaries available, skipping phase assignment ({time.time() - exp_start:.1f}s)", flush=True)
            continue

        # Build non-overlapping ranges: each phase starts at its min,
        # ends at the start of the next phase (or infinity for the last)
        phase_ranges = []
        for i, pb in enumerate(phase_boundaries):
            phase_idx = pb[0]
            phase_name = pb[1]
            range_start = pb[2]  # min relative_time_ms for this phase
            if i + 1 < len(phase_boundaries):
                range_end = phase_boundaries[i + 1][2]  # start of next phase
            else:
                range_end = None  # no upper bound for last phase
            phase_ranges.append((phase_idx, phase_name, range_start, range_end))

        # Build CASE expressions for phase assignment (reused for handlers and rpc)
        case_idx_parts = []
        case_name_parts = []
        for phase_idx, phase_name, range_start, range_end in phase_ranges:
            if range_end is not None:
                condition = f"relative_time_ms >= {range_start} AND relative_time_ms < {range_end}"
            else:
                condition = f"relative_time_ms >= {range_start}"
            case_idx_parts.append(f"WHEN {condition} THEN {phase_idx}")
            safe_name = phase_name.replace("'", "''")
            case_name_parts.append(f"WHEN {condition} THEN '{safe_name}'")

        # Handle events before the first phase (assign to first phase)
        first_start = phase_ranges[0][2]
        case_idx_parts.insert(0, f"WHEN relative_time_ms < {first_start} THEN {phase_ranges[0][0]}")
        safe_first_name = phase_ranges[0][1].replace("'", "''")
        case_name_parts.insert(0, f"WHEN relative_time_ms < {first_start} THEN '{safe_first_name}'")

        case_idx_sql = "CASE " + " ".join(case_idx_parts) + " END"
        case_name_sql = "CASE " + " ".join(case_name_parts) + " END"

        # Build CASE for phase start times (for phase_relative_time_ms)
        phase_start_parts = []
        for phase_idx, _, range_start, _ in phase_ranges:
            phase_start_parts.append(f"WHEN {phase_idx} THEN {range_start}")
        phase_start_sql = "CASE phase_index " + " ".join(phase_start_parts) + " END"

        # --- Step 3: Assign phase_index/phase_name to handler_events ---
        handler_phase_updated = 0
        result = session.execute(text(f"""
            UPDATE handler_events
            SET phase_index = ({case_idx_sql}),
                phase_name = ({case_name_sql})
            WHERE experiment_id = :exp_id
              AND phase_index IS NULL
              AND relative_time_ms IS NOT NULL
        """), {"exp_id": exp_id})
        handler_phase_updated = result.rowcount
        total_stats['handler_phase'] += handler_phase_updated
        if handler_phase_updated:
            session.commit()

        # --- Step 4: Calculate phase_relative_time_ms for handler_events ---
        result = session.execute(text(f"""
            UPDATE handler_events
            SET phase_relative_time_ms = relative_time_ms - ({phase_start_sql})
            WHERE experiment_id = :exp_id
              AND phase_index IS NOT NULL
              AND relative_time_ms IS NOT NULL
              AND phase_relative_time_ms IS NULL
        """), {"exp_id": exp_id})
        handler_phase_rel_updated = result.rowcount
        total_stats['handler_phase_rel'] += handler_phase_rel_updated
        if handler_phase_rel_updated:
            session.commit()

        if handler_phase_updated or handler_phase_rel_updated:
            print(f"  handler_events: phase_assigned={handler_phase_updated:,}, phase_rel_time={handler_phase_rel_updated:,}", flush=True)

        # --- Step 5: Assign phase_index/phase_name to rpc_calls ---
        result = session.execute(text(f"""
            UPDATE rpc_calls
            SET phase_index = ({case_idx_sql}),
                phase_name = ({case_name_sql})
            WHERE experiment_id = :exp_id
              AND phase_index IS NULL
              AND relative_time_ms IS NOT NULL
        """), {"exp_id": exp_id})
        rpc_phase_updated = result.rowcount
        total_stats['rpc_phase'] += rpc_phase_updated
        if rpc_phase_updated:
            session.commit()
            print(f"  rpc_calls: phase_assigned={rpc_phase_updated:,}", flush=True)

        print(f"  Done ({time.time() - exp_start:.1f}s)", flush=True)

    # Restore work_mem
    session.execute(text("RESET work_mem"))
    session.commit()

    # Summary
    print(f"\n=== Backfill Summary ===", flush=True)
    print(f"  handler_events.auth_type:            {total_stats['handler_auth']:,} rows updated", flush=True)
    print(f"  handler_events.phase_index/name:     {total_stats['handler_phase']:,} rows updated", flush=True)
    print(f"  handler_events.phase_relative_time:  {total_stats['handler_phase_rel']:,} rows updated", flush=True)
    print(f"  rpc_calls.auth_type:                 {total_stats['rpc_auth']:,} rows updated", flush=True)
    print(f"  rpc_calls.phase_index/name:          {total_stats['rpc_phase']:,} rows updated", flush=True)
    print(f"  requests.auth_type:                  {total_stats['request_auth']:,} rows updated", flush=True)
    print(f"\nBackfill completed in {time.time() - total_start:.1f}s", flush=True)


def init_database(engine, drop_existing: bool = False):
    """
    Initialize the database schema.

    Args:
        engine: SQLAlchemy engine
        drop_existing: If True, drop all tables before creating
    """
    if drop_existing:
        print("Dropping existing tables...")
        Base.metadata.drop_all(engine)

    print("Creating tables...")
    create_tables(engine)

    print("Adding table comments...")
    add_table_comments(engine)

    print("Adding column comments...")
    add_column_comments(engine)

    print("Populating schema documentation...")
    with Session(engine) as session:
        populate_schema_documentation(session)

    print("Database initialized successfully")