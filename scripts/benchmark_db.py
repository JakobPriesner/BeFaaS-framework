#!/usr/bin/env python3
"""
Benchmark Database Importer

Focused script for importing benchmark results into PostgreSQL for auth overhead analysis.
Correlates Lambda execution data with artillery logs via x_pair for enriched analytics.

Usage:
    python benchmark_db.py init                              # Create tables
    python benchmark_db.py import <results_dir>              # Import one benchmark
    python benchmark_db.py import-all <dir> [dir...]         # Import all benchmarks
    python benchmark_db.py views                             # Create analytical views
    python benchmark_db.py schema                            # Print schema SQL to stdout

    # Export to SQL file instead of database:
    python benchmark_db.py import <results_dir> --export-sql <output.sql>
    python benchmark_db.py import-all <dir> [dir...] --export-sql <output.sql>
"""

import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    create_engine, Column, Integer, Float, String, DateTime,
    Boolean, ForeignKey, Index, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()


# =============================================================================
# Models
# =============================================================================

class Experiment(Base):
    """Benchmark configuration and metadata"""
    __tablename__ = 'experiments'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    architecture = Column(String(50), index=True)
    auth_strategy = Column(String(50), index=True)
    memory_mb = Column(Integer, index=True)
    cpu_units = Column(Integer, index=True)  # Fargate CPU units (microservices/monolith only)
    bundle_mode = Column(String(50))
    run_timestamp = Column(DateTime)

    # Timing metadata (populated during import)
    benchmark_start_ms = Column(Float)
    benchmark_end_ms = Column(Float)

    requests = relationship("Request", back_populates="experiment", cascade="all, delete-orphan")
    lambda_executions = relationship("LambdaExecution", back_populates="experiment", cascade="all, delete-orphan")
    handler_events = relationship("HandlerEvent", back_populates="experiment", cascade="all, delete-orphan")
    container_starts = relationship("ContainerStart", back_populates="experiment", cascade="all, delete-orphan")
    rpc_in_events = relationship("RpcIn", back_populates="experiment", cascade="all, delete-orphan")
    rpc_out_events = relationship("RpcOut", back_populates="experiment", cascade="all, delete-orphan")
    phases = relationship("Phase", back_populates="experiment", cascade="all, delete-orphan")
    function_pricing = relationship("FunctionPricing", back_populates="experiment", cascade="all, delete-orphan")
    ecs_metrics = relationship("EcsMetric", back_populates="experiment", cascade="all, delete-orphan")
    alb_metrics = relationship("AlbMetric", back_populates="experiment", cascade="all, delete-orphan")


class Request(Base):
    """HTTP request from artillery logs - client-side latency"""
    __tablename__ = 'requests'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    # Correlation
    x_pair = Column(String(100), index=True)

    # Timing
    timestamp_ms = Column(Float, index=True)
    latency_ms = Column(Float, index=True)
    relative_time_ms = Column(Float, index=True)
    phase_relative_time_ms = Column(Float)

    # Request info
    endpoint = Column(String(200), index=True)
    status_code = Column(Integer, index=True)
    auth_type = Column(String(50), index=True)
    expected_failure = Column(Boolean, default=False)

    # Timeout/Error info
    is_timeout = Column(Boolean, default=False, index=True)
    is_error = Column(Boolean, default=False, index=True)
    error_type = Column(String(50))  # 'timeout', 'connection_error', 'error'
    error_code = Column(String(50))  # e.g., 'ETIMEDOUT', 'ECONNRESET'
    error_message = Column(String(500))

    # Phase info
    phase_index = Column(Integer, index=True)
    phase_name = Column(String(100))

    experiment = relationship("Experiment", back_populates="requests")

    __table_args__ = (
        Index('idx_req_exp_auth', 'experiment_id', 'auth_type'),
        Index('idx_req_exp_phase', 'experiment_id', 'phase_index'),
        Index('idx_req_xpair', 'experiment_id', 'x_pair'),
        Index('idx_req_exp_timeout', 'experiment_id', 'is_timeout'),
    )


class LambdaExecution(Base):
    """Lambda invocation from CloudWatch REPORT - server-side execution"""
    __tablename__ = 'lambda_executions'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    # Identifiers
    request_id = Column(String(100), index=True)
    function_name = Column(String(100), index=True)

    # Timing from REPORT
    timestamp_ms = Column(Float, index=True)
    duration_ms = Column(Float, index=True)
    billed_duration_ms = Column(Float)
    init_duration_ms = Column(Float)

    # Memory
    memory_size_mb = Column(Integer)
    max_memory_used_mb = Column(Integer)

    # Derived
    is_cold_start = Column(Boolean, default=False, index=True)

    # Relative timing (calculated from benchmark start)
    relative_time_ms = Column(Float, index=True)

    experiment = relationship("Experiment", back_populates="lambda_executions")

    __table_args__ = (
        Index('idx_lambda_exp_fn', 'experiment_id', 'function_name'),
        Index('idx_lambda_exp_cold', 'experiment_id', 'is_cold_start'),
    )


class HandlerEvent(Base):
    """
    BEFAAS handler event - enriched with artillery correlation.
    This is the main table for auth overhead analysis as it links
    Lambda execution to request context via x_pair.
    """
    __tablename__ = 'handler_events'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    # Correlation keys
    x_pair = Column(String(100), index=True)
    context_id = Column(String(50), index=True)
    lambda_request_id = Column(String(100), index=True)  # Links to lambda_executions.request_id

    # Handler info from BEFAAS
    function_name = Column(String(100), index=True)
    route = Column(String(200), index=True)
    status_code = Column(Integer, index=True)
    is_cold_start = Column(Boolean, default=False, index=True)
    request_count = Column(Integer)  # Container reuse count

    # Timing from BEFAAS handler
    timestamp_ms = Column(Float, index=True)
    duration_ms = Column(Float, index=True)

    # === Enriched from artillery correlation via x_pair ===
    # Auth info
    auth_type = Column(String(50), index=True)
    expected_failure = Column(Boolean, default=False)

    # Phase info
    phase_index = Column(Integer, index=True)
    phase_name = Column(String(100))

    # Relative timing
    relative_time_ms = Column(Float, index=True)
    phase_relative_time_ms = Column(Float)

    experiment = relationship("Experiment", back_populates="handler_events")

    __table_args__ = (
        Index('idx_handler_exp_fn', 'experiment_id', 'function_name'),
        Index('idx_handler_exp_route', 'experiment_id', 'route'),
        Index('idx_handler_exp_auth', 'experiment_id', 'auth_type'),
        Index('idx_handler_exp_phase', 'experiment_id', 'phase_index'),
        Index('idx_handler_xpair', 'experiment_id', 'x_pair'),
    )


class ContainerStart(Base):
    """
    Container cold start event - captures when a new Lambda container starts.
    Logged at the beginning of a cold start invocation.
    """
    __tablename__ = 'container_starts'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    # Correlation
    lambda_request_id = Column(String(100), index=True)

    # Function info
    function_name = Column(String(100), index=True)
    deployment_id = Column(String(50))

    # Timing
    timestamp_ms = Column(Float, index=True)
    container_start_time_ms = Column(Float)

    # Relative timing
    relative_time_ms = Column(Float, index=True)

    experiment = relationship("Experiment", back_populates="container_starts")

    __table_args__ = (
        Index('idx_container_exp_fn', 'experiment_id', 'function_name'),
    )


class RpcIn(Base):
    """
    Incoming RPC event - marks when a function receives an RPC call.
    Can be correlated with the caller's RpcOut via x_pair.
    """
    __tablename__ = 'rpc_in_events'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    # Correlation keys
    x_pair = Column(String(100), index=True)
    context_id = Column(String(50), index=True)
    lambda_request_id = Column(String(100), index=True)

    # Function info
    function_name = Column(String(100), index=True)

    # RPC details
    received_at_ms = Column(Float)
    is_cold_start = Column(Boolean, default=False, index=True)

    # Timing
    timestamp_ms = Column(Float, index=True)
    relative_time_ms = Column(Float, index=True)

    # Enriched from artillery correlation
    auth_type = Column(String(50), index=True)
    phase_index = Column(Integer, index=True)
    phase_name = Column(String(100))

    experiment = relationship("Experiment", back_populates="rpc_in_events")

    __table_args__ = (
        Index('idx_rpcin_exp_fn', 'experiment_id', 'function_name'),
        Index('idx_rpcin_xpair', 'experiment_id', 'x_pair'),
    )


class RpcOut(Base):
    """
    Outgoing RPC event - captures inter-function calls.
    Links caller to callee via call_x_pair for call graph reconstruction.
    """
    __tablename__ = 'rpc_out_events'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    # Correlation keys (caller context)
    x_pair = Column(String(100), index=True)  # Caller's xPair
    context_id = Column(String(50), index=True)
    lambda_request_id = Column(String(100), index=True)

    # Function info (caller)
    function_name = Column(String(100), index=True)

    # RPC call details
    target_function = Column(String(100), index=True)  # Called function name
    call_x_pair = Column(String(100), index=True)  # xPair of the callee (for joining)
    call_type = Column(String(50))  # e.g., "direct"
    duration_ms = Column(Float, index=True)
    success = Column(Boolean, default=True)

    # Timing
    timestamp_ms = Column(Float, index=True)
    relative_time_ms = Column(Float, index=True)

    # Enriched from artillery correlation
    auth_type = Column(String(50), index=True)
    phase_index = Column(Integer, index=True)
    phase_name = Column(String(100))

    experiment = relationship("Experiment", back_populates="rpc_out_events")

    __table_args__ = (
        Index('idx_rpcout_exp_fn', 'experiment_id', 'function_name'),
        Index('idx_rpcout_exp_target', 'experiment_id', 'target_function'),
        Index('idx_rpcout_xpair', 'experiment_id', 'x_pair'),
        Index('idx_rpcout_call_xpair', 'experiment_id', 'call_x_pair'),
    )


class Phase(Base):
    """
    Phase definition from artillery phases_loaded event.
    Contains the configured duration for each benchmark phase.
    """
    __tablename__ = 'phases'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    phase_index = Column(Integer, index=True)
    phase_name = Column(String(100))
    duration_seconds = Column(Integer)  # Configured duration in seconds

    experiment = relationship("Experiment", back_populates="phases")

    __table_args__ = (
        Index('idx_phase_exp_idx', 'experiment_id', 'phase_index'),
    )


class FunctionPricing(Base):
    """
    Per-function pricing data from pricing.json.
    Contains cost breakdown for each Lambda function in the experiment.
    """
    __tablename__ = 'function_pricing'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    function_name = Column(String(100), index=True)

    # Usage metrics
    invocations = Column(Integer)
    duration_ms = Column(Float)
    gb_seconds = Column(Float)

    # Cost breakdown
    request_cost = Column(Float)
    compute_cost = Column(Float)
    total_cost = Column(Float)

    experiment = relationship("Experiment", back_populates="function_pricing")

    __table_args__ = (
        Index('idx_pricing_exp_fn', 'experiment_id', 'function_name'),
    )


class EcsMetric(Base):
    """
    ECS container metrics from CloudWatch.
    Time-series data for CPU, memory, and task counts per service.
    """
    __tablename__ = 'ecs_metrics'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    service_name = Column(String(100), index=True)
    timestamp = Column(DateTime, index=True)

    # Resource utilization (percentage)
    cpu_percent = Column(Float)
    memory_percent = Column(Float)

    # Task counts
    running_tasks = Column(Integer)
    desired_tasks = Column(Integer)

    experiment = relationship("Experiment", back_populates="ecs_metrics")

    __table_args__ = (
        Index('idx_ecs_exp_service', 'experiment_id', 'service_name'),
        Index('idx_ecs_exp_ts', 'experiment_id', 'timestamp'),
    )


class AlbMetric(Base):
    """
    ALB (Application Load Balancer) metrics from CloudWatch.
    Time-series data for request counts, response times, and HTTP status codes.
    """
    __tablename__ = 'alb_metrics'

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey('experiments.id', ondelete='CASCADE'), nullable=False, index=True)

    timestamp = Column(DateTime, index=True)

    # Request metrics
    request_count = Column(Integer)
    response_time_avg = Column(Float)
    response_time_p95 = Column(Float)

    # HTTP status counts
    http_2xx_count = Column(Integer)
    http_4xx_count = Column(Integer)
    http_5xx_count = Column(Integer)

    # Connection metrics
    active_connections = Column(Integer)
    healthy_hosts = Column(Integer)

    experiment = relationship("Experiment", back_populates="alb_metrics")

    __table_args__ = (
        Index('idx_alb_exp_ts', 'experiment_id', 'timestamp'),
    )


# =============================================================================
# Database Connection
# =============================================================================

def get_engine():
    """Create engine from environment or .env file"""
    from urllib.parse import quote_plus

    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

    db_type = os.environ.get('DB_TYPE', 'postgresql')

    if db_type == 'sqlite':
        db_path = os.environ.get('DB_SQLITE_PATH', 'benchmark.db')
        return create_engine(f'sqlite:///{db_path}')

    host = os.environ.get('DB_HOST', 'localhost')
    port = os.environ.get('DB_PORT', '5432')
    name = os.environ.get('DB_NAME', 'postgres')
    user = os.environ.get('DB_USER', 'postgres')
    password = quote_plus(os.environ.get('DB_PASSWORD', ''))

    return create_engine(f'postgresql://{user}:{password}@{host}:{port}/{name}')


# =============================================================================
# DataWriter - Unified interface for DB or SQL file output
# =============================================================================

# Table column definitions for SQL generation
TABLE_COLUMNS = {
    'experiments': ['id', 'name', 'architecture', 'auth_strategy', 'memory_mb',
                    'cpu_units', 'bundle_mode', 'run_timestamp', 'benchmark_start_ms', 'benchmark_end_ms'],
    'requests': ['experiment_id', 'x_pair', 'timestamp_ms', 'latency_ms', 'relative_time_ms',
                 'phase_relative_time_ms', 'endpoint', 'status_code', 'auth_type', 'expected_failure',
                 'phase_index', 'phase_name', 'is_timeout', 'is_error', 'error_type', 'error_code', 'error_message'],
    'lambda_executions': ['experiment_id', 'request_id', 'function_name', 'timestamp_ms', 'duration_ms',
                          'billed_duration_ms', 'init_duration_ms', 'memory_size_mb', 'max_memory_used_mb',
                          'is_cold_start', 'relative_time_ms'],
    'handler_events': ['experiment_id', 'x_pair', 'context_id', 'lambda_request_id', 'function_name',
                       'route', 'status_code', 'is_cold_start', 'request_count', 'timestamp_ms',
                       'duration_ms', 'auth_type', 'expected_failure', 'phase_index', 'phase_name',
                       'relative_time_ms', 'phase_relative_time_ms'],
    'container_starts': ['experiment_id', 'lambda_request_id', 'function_name', 'deployment_id',
                         'timestamp_ms', 'container_start_time_ms', 'relative_time_ms'],
    'rpc_in_events': ['experiment_id', 'x_pair', 'context_id', 'lambda_request_id', 'function_name',
                      'received_at_ms', 'is_cold_start', 'timestamp_ms', 'relative_time_ms',
                      'auth_type', 'phase_index', 'phase_name'],
    'rpc_out_events': ['experiment_id', 'x_pair', 'context_id', 'lambda_request_id', 'function_name',
                       'target_function', 'call_x_pair', 'call_type', 'duration_ms', 'success',
                       'timestamp_ms', 'relative_time_ms', 'auth_type', 'phase_index', 'phase_name'],
    'phases': ['experiment_id', 'phase_index', 'phase_name', 'duration_seconds'],
    'function_pricing': ['experiment_id', 'function_name', 'invocations', 'duration_ms',
                         'gb_seconds', 'request_cost', 'compute_cost', 'total_cost'],
    'ecs_metrics': ['experiment_id', 'service_name', 'timestamp', 'cpu_percent', 'memory_percent',
                    'running_tasks', 'desired_tasks'],
    'alb_metrics': ['experiment_id', 'timestamp', 'request_count', 'response_time_avg', 'response_time_p95',
                    'http_2xx_count', 'http_4xx_count', 'http_5xx_count', 'active_connections', 'healthy_hosts'],
}

MODEL_MAP = {
    'experiments': Experiment,
    'requests': Request,
    'lambda_executions': LambdaExecution,
    'handler_events': HandlerEvent,
    'container_starts': ContainerStart,
    'rpc_in_events': RpcIn,
    'rpc_out_events': RpcOut,
    'phases': Phase,
    'function_pricing': FunctionPricing,
    'ecs_metrics': EcsMetric,
    'alb_metrics': AlbMetric,
}


def sql_value(val):
    """Convert a Python value to SQL literal"""
    if val is None:
        return 'NULL'
    if isinstance(val, bool):
        return 'TRUE' if val else 'FALSE'
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, datetime):
        return f"'{val.isoformat()}'"
    # String - escape single quotes
    s = str(val).replace("'", "''")
    return f"'{s}'"


class DataWriter:
    """
    Unified interface for writing data to either database or SQL file.
    Handles batching and thread-safe file writes.
    """

    def __init__(self, session=None, sql_file: Path = None, batch_size: int = 1000):
        """
        Initialize DataWriter.

        Args:
            session: SQLAlchemy session for database mode
            sql_file: Path to SQL output file for export mode
            batch_size: Number of rows to batch before writing (for SQL mode)
        """
        self.session = session
        self.sql_file = sql_file
        self.batch_size = batch_size
        self.export_mode = sql_file is not None

        # For SQL export mode
        self._file_lock = threading.Lock()
        self._batches = {}  # table_name -> list of row dicts
        self._experiment_id_counter = 0
        self._known_experiments = {}  # name -> id

        if self.export_mode:
            # Initialize file with header
            with open(self.sql_file, 'w') as f:
                f.write(f"-- BeFaaS Benchmark Data Export\n")
                f.write(f"-- Generated: {datetime.now().isoformat()}\n\n")

    def _write_sql(self, sql: str):
        """Thread-safe write to SQL file"""
        with self._file_lock:
            with open(self.sql_file, 'a') as f:
                f.write(sql)

    def _flush_batch(self, table: str):
        """Flush a table's batch to file"""
        if table not in self._batches or not self._batches[table]:
            return

        rows = self._batches[table]
        columns = TABLE_COLUMNS[table]
        col_str = ', '.join(columns)

        # Write in chunks for very large batches
        chunk_size = 500
        sql_parts = []

        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i+chunk_size]
            values = []
            for row in chunk:
                vals = ', '.join(sql_value(row.get(c)) for c in columns)
                values.append(f"({vals})")

            sql_parts.append(f"INSERT INTO {table} ({col_str}) VALUES\n" + ',\n'.join(values) + ';\n')

        self._write_sql('\n'.join(sql_parts) + '\n')
        self._batches[table] = []

    def flush_all(self):
        """Flush all pending batches"""
        if self.export_mode:
            for table in list(self._batches.keys()):
                self._flush_batch(table)

    def get_next_experiment_id(self) -> int:
        """Get next experiment ID (for SQL export mode)"""
        self._experiment_id_counter += 1
        return self._experiment_id_counter

    def experiment_exists(self, name: str):
        """Check if experiment exists. Returns experiment or None."""
        if self.export_mode:
            if name in self._known_experiments:
                return type('Exp', (), {'id': self._known_experiments[name]})()
            return None
        else:
            return self.session.query(Experiment).filter_by(name=name).first()

    def insert_experiment(self, name: str, config: dict, explicit_id: int = None) -> int:
        """Insert experiment and return its ID

        Args:
            name: Experiment name
            config: Experiment configuration dict
            explicit_id: If provided, use this ID instead of generating one (SQL export mode only)
        """
        if self.export_mode:
            if explicit_id is not None:
                exp_id = explicit_id
                # Update counter to avoid ID conflicts
                if explicit_id > self._experiment_id_counter:
                    self._experiment_id_counter = explicit_id
            else:
                exp_id = self.get_next_experiment_id()
            self._known_experiments[name] = exp_id
            row = {
                'id': exp_id,
                'name': name,
                'architecture': config.get('architecture'),
                'auth_strategy': config.get('auth_strategy'),
                'memory_mb': config.get('memory_mb'),
                'cpu_units': config.get('cpu_units'),
                'bundle_mode': config.get('bundle_mode'),
                'run_timestamp': config.get('run_timestamp'),
                'benchmark_start_ms': None,
                'benchmark_end_ms': None
            }
            # Write experiment immediately (not batched)
            columns = TABLE_COLUMNS['experiments']
            col_str = ', '.join(columns)
            vals = ', '.join(sql_value(row.get(c)) for c in columns)
            self._write_sql(f"INSERT INTO experiments ({col_str}) VALUES ({vals});\n\n")
            return exp_id
        else:
            experiment = Experiment(name=name, **config)
            self.session.add(experiment)
            self.session.commit()
            return experiment.id

    def update_experiment(self, experiment_id: int, **kwargs):
        """Update experiment fields"""
        if self.export_mode:
            sets = ', '.join(f"{k} = {sql_value(v)}" for k, v in kwargs.items())
            self._write_sql(f"UPDATE experiments SET {sets} WHERE id = {experiment_id};\n")
        else:
            self.session.query(Experiment).filter_by(id=experiment_id).update(kwargs)
            self.session.commit()

    def bulk_insert(self, table: str, rows: list):
        """Insert multiple rows into a table"""
        if not rows:
            return

        if self.export_mode:
            if table not in self._batches:
                self._batches[table] = []
            self._batches[table].extend(rows)

            # Flush if batch is large enough
            if len(self._batches[table]) >= self.batch_size:
                self._flush_batch(table)
        else:
            model = MODEL_MAP[table]
            self.session.bulk_insert_mappings(model, rows)
            self.session.flush()

    def insert_one(self, table: str, row: dict):
        """Insert a single row"""
        self.bulk_insert(table, [row])

    def commit(self):
        """Commit changes (DB mode) or flush batches (SQL mode)"""
        if self.export_mode:
            self.flush_all()
        else:
            self.session.commit()

    def close(self):
        """Clean up resources"""
        if self.export_mode:
            self.flush_all()
        elif self.session:
            self.session.close()


# =============================================================================
# Import Functions
# =============================================================================

def parse_experiment_name(name: str) -> dict:
    """Parse experiment directory name.

    FaaS format: faas_none_256MB_minimal_2026-01-09T10-26-01-144Z
    Microservices/Monolith format: microservices_service-integrated_1024cpu_2048MB_2026-01-14T22-12-28-085Z
    """
    parts = name.split('_')
    if len(parts) < 5:
        return {}

    architecture = parts[0]
    auth_strategy = parts[1]

    # Detect format based on architecture or presence of 'cpu' in parts[2]
    if architecture in ('microservices', 'monolith') or 'cpu' in parts[2]:
        # Microservices/Monolith format: arch_auth_CPUcpu_MEMMb_timestamp
        cpu_units = int(parts[2].replace('cpu', ''))
        memory_mb = int(parts[3].replace('MB', ''))
        bundle_mode = None  # Not applicable for microservices/monolith
        timestamp_start_idx = 4
    else:
        # FaaS format: arch_auth_MEMMb_bundle_timestamp
        cpu_units = None
        memory_mb = int(parts[2].replace('MB', ''))
        bundle_mode = parts[3]
        timestamp_start_idx = 4

    # Parse timestamp: 2026-01-09T10-26-01-144Z -> 2026-01-09T10:26:01.144Z
    timestamp_str = '_'.join(parts[timestamp_start_idx:])
    try:
        # Format: 2026-01-09T10-26-01-144Z
        # Split into date and time parts
        if 'T' in timestamp_str:
            date_part, time_part = timestamp_str.split('T', 1)
            # time_part: 10-26-01-144Z -> 10:26:01.144
            time_part = time_part.rstrip('Z')
            time_components = time_part.split('-')
            if len(time_components) >= 4:
                hour, minute, second, ms = time_components[0], time_components[1], time_components[2], time_components[3]
                iso_str = f"{date_part}T{hour}:{minute}:{second}.{ms}+00:00"
                run_timestamp = datetime.fromisoformat(iso_str)
            else:
                run_timestamp = None
        else:
            run_timestamp = None
    except Exception:
        run_timestamp = None

    return {
        'architecture': architecture,
        'auth_strategy': auth_strategy,
        'memory_mb': memory_mb,
        'cpu_units': cpu_units,
        'bundle_mode': bundle_mode,
        'run_timestamp': run_timestamp
    }


def extract_endpoint(url: str) -> str:
    """Extract endpoint path from URL"""
    if not url:
        return None
    if '://' in url:
        url = url.split('://', 1)[1]
    if '/' in url:
        return '/' + '/'.join(url.split('/')[1:]).rstrip('/') or '/'
    return '/'


def import_dump_json(writer: DataWriter, experiment_id: int, dump_path: Path, batch_size: int = 50000):
    """
    Single-pass import of dump.json that:
    1. Builds x_pair lookup for AWS log correlation
    2. Imports requests with relative timing
    3. Calculates benchmark_start_ms and phase_starts
    4. Imports phase definitions from phases_loaded event

    Returns:
        - xpair_lookup: {x_pair: {phase_index, phase_name, auth_type, ...}}
        - benchmark_start_ms: earliest timestamp
        - phase_starts: {phase_index: start_ms}
    """
    if not dump_path.exists():
        print(f"    No dump.json found")
        return {}, None, {}

    file_size = dump_path.stat().st_size
    file_size_mb = file_size / 1024 / 1024
    print(f"    Processing dump.json ({file_size_mb:.1f} MB)...")

    # Skip empty files
    if file_size < 10:
        print(f"    dump.json is empty or too small, skipping")
        return {}, None, {}

    # Fix truncated JSON if needed
    with open(dump_path, 'rb') as f:
        f.seek(-10, 2)
        if f.read().strip().endswith(b'}}'):
            print(f"    Fixing truncated JSON...")
            with open(dump_path, 'a') as fa:
                fa.write(']\n')

    try:
        import ijson
        use_streaming = True
    except ImportError:
        use_streaming = False
        print("    Note: pip install ijson for lower memory usage")

    # First pass: collect all timing info to calculate relative times correctly
    print(f"    Pass 1: Collecting timing metadata...")
    benchmark_start_ms = None
    phase_starts = {}

    def collect_timing(entry):
        nonlocal benchmark_start_ms

        logentry = entry.get('__logentry__', {})
        data = logentry.get('data', {})
        phase = data.get('phase', {})

        now_ms = data.get('now')
        phase_idx = phase.get('index')

        if now_ms is not None:
            if benchmark_start_ms is None or now_ms < benchmark_start_ms:
                benchmark_start_ms = now_ms
            if phase_idx is not None:
                if phase_idx not in phase_starts or now_ms < phase_starts[phase_idx]:
                    phase_starts[phase_idx] = now_ms

    if use_streaming:
        with open(dump_path, 'rb') as f:
            for entry in ijson.items(f, 'item'):
                collect_timing(entry)
    else:
        with open(dump_path, 'r') as f:
            data = json.load(f)
            for entry in data:
                collect_timing(entry)

    print(f"    Pass 2: Importing requests and building lookup...")

    # Second pass: build lookup and import requests with correct relative times
    xpair_lookup = {}
    before_events = {}
    batch = []
    request_count = 0
    lookup_count = 0

    def process_entry(entry):
        nonlocal request_count, lookup_count

        logentry = entry.get('__logentry__', {})
        data = logentry.get('data', {})
        event = data.get('event', {})
        phase = data.get('phase', {})

        event_type = event.get('type')
        x_pair = event.get('xPair')
        now_ms = data.get('now')
        phase_idx = phase.get('index')

        # Handle None -> False for expected_failure
        expected_failure = bool(event.get('expectedFailure'))

        if event_type == 'before' and x_pair:
            before_events[x_pair] = {
                'now_ms': now_ms,
                'phase_index': phase_idx,
                'phase_name': phase.get('name'),
                'auth_type': event.get('authType'),
                'expected_failure': expected_failure,
                'endpoint': extract_endpoint(event.get('url'))
            }

        elif event_type == 'after' and x_pair and x_pair in before_events:
            before = before_events.pop(x_pair)

            # Build lookup entry for AWS log correlation
            xpair_lookup[x_pair] = {
                'phase_index': before['phase_index'],
                'phase_name': before['phase_name'],
                'auth_type': before['auth_type'],
                'expected_failure': before['expected_failure'],
                'endpoint': before['endpoint'],
                'status_code': event.get('statusCode'),
                'timestamp_ms': now_ms
            }
            lookup_count += 1

            # Import request if we have valid timing
            if now_ms and before['now_ms']:
                phase_idx = before['phase_index']

                # Calculate relative times
                relative_time_ms = None
                phase_relative_time_ms = None
                if benchmark_start_ms is not None:
                    relative_time_ms = now_ms - benchmark_start_ms
                if phase_idx is not None and phase_idx in phase_starts:
                    phase_relative_time_ms = now_ms - phase_starts[phase_idx]

                batch.append({
                    'experiment_id': experiment_id,
                    'x_pair': x_pair,
                    'timestamp_ms': now_ms,
                    'latency_ms': now_ms - before['now_ms'],
                    'relative_time_ms': relative_time_ms,
                    'phase_relative_time_ms': phase_relative_time_ms,
                    'endpoint': before['endpoint'],
                    'status_code': event.get('statusCode'),
                    'auth_type': before['auth_type'],
                    'expected_failure': before['expected_failure'],
                    'phase_index': phase_idx,
                    'phase_name': before['phase_name'],
                    'is_timeout': False,
                    'is_error': False
                })
                request_count += 1

                if len(batch) >= batch_size:
                    writer.bulk_insert('requests', batch)
                    batch.clear()
                    print(f"      {request_count:,} requests...")

        # Handle timeout and error events
        elif event_type in ('timeout', 'connection_error', 'error'):
            # Get before event info if available
            before = before_events.pop(x_pair, None) if x_pair else None

            phase_idx = phase.get('index')
            if before:
                phase_idx = before.get('phase_index', phase_idx)

            # Calculate relative times
            relative_time_ms = None
            phase_relative_time_ms = None
            if benchmark_start_ms is not None and now_ms:
                relative_time_ms = now_ms - benchmark_start_ms
            if phase_idx is not None and phase_idx in phase_starts and now_ms:
                phase_relative_time_ms = now_ms - phase_starts[phase_idx]

            # Calculate latency from duration if available, or from before event
            latency_ms = event.get('durationMs')
            if not latency_ms and before and before.get('now_ms') and now_ms:
                latency_ms = now_ms - before['now_ms']

            batch.append({
                'experiment_id': experiment_id,
                'x_pair': x_pair,
                'timestamp_ms': now_ms,
                'latency_ms': latency_ms,
                'relative_time_ms': relative_time_ms,
                'phase_relative_time_ms': phase_relative_time_ms,
                'endpoint': before['endpoint'] if before else extract_endpoint(event.get('url')),
                'status_code': None,
                'auth_type': before['auth_type'] if before else event.get('authType'),
                'expected_failure': before['expected_failure'] if before else bool(event.get('expectedFailure')),
                'phase_index': phase_idx,
                'phase_name': before['phase_name'] if before else phase.get('name'),
                'is_timeout': event_type == 'timeout',
                'is_error': event_type in ('connection_error', 'error'),
                'error_type': event_type,
                'error_code': event.get('errorCode'),
                'error_message': event.get('errorMessage', '')[:500] if event.get('errorMessage') else None
            })
            request_count += 1

            if len(batch) >= batch_size:
                writer.bulk_insert('requests', batch)
                batch.clear()
                print(f"      {request_count:,} requests...")

    if use_streaming:
        with open(dump_path, 'rb') as f:
            for entry in ijson.items(f, 'item'):
                process_entry(entry)
    else:
        # Reuse data if we loaded it in pass 1
        if not use_streaming:
            for entry in data:
                process_entry(entry)

    if batch:
        writer.bulk_insert('requests', batch)

    writer.commit()
    print(f"    Imported {request_count:,} requests, built {lookup_count:,} x_pair lookups")
    return xpair_lookup, benchmark_start_ms, phase_starts


def import_artillery_errors(writer: DataWriter, experiment_id: int, artillery_log_path: Path,
                            benchmark_start_ms: float, phase_starts: dict, batch_size: int = 50000):
    """
    Import error/timeout events from artillery.log that are not in dump.json.

    The befaas/analysis container only includes matched before/after pairs in dump.json.
    Error events (ETIMEDOUT, connection errors, etc.) are standalone and get discarded.
    This function parses artillery.log directly to capture these error events.

    Note: Only imports events not already in the database (based on x_pair).
    """
    if not artillery_log_path.exists():
        print(f"    No artillery.log found for error import")
        return 0

    file_size_mb = artillery_log_path.stat().st_size / 1024 / 1024
    print(f"    Importing error events from artillery.log ({file_size_mb:.1f} MB)...")

    import re
    befaas_pattern = re.compile(r'BEFAAS[:\s]*(\{.*\})')

    batch = []
    error_count = 0
    skipped_count = 0

    # Get existing x_pairs to avoid duplicates
    existing_xpairs = set()
    try:
        result = writer.session.execute(
            text("SELECT x_pair FROM requests WHERE experiment_id = :exp_id AND x_pair IS NOT NULL"),
            {'exp_id': experiment_id}
        )
        existing_xpairs = {row[0] for row in result}
    except Exception as e:
        print(f"    Warning: Could not fetch existing x_pairs: {e}")

    with open(artillery_log_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            # Find BEFAAS JSON in line (may have ANSI codes or terraform prefixes)
            match = befaas_pattern.search(line)
            if not match:
                continue

            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

            event = data.get('event', {})
            event_type = event.get('type')

            # Only process error events (timeout, connection_error, error)
            if event_type not in ('timeout', 'connection_error', 'error'):
                continue

            x_pair = event.get('xPair')

            # Skip if already in database
            if x_pair and x_pair in existing_xpairs:
                skipped_count += 1
                continue

            # Extract timing info
            now_ms = data.get('now')
            phase = data.get('phase', {})
            phase_idx = phase.get('index')
            phase_name = phase.get('name')

            # Calculate relative times (convert to float to handle Decimal types)
            relative_time_ms = None
            phase_relative_time_ms = None
            if benchmark_start_ms is not None and now_ms is not None:
                relative_time_ms = float(now_ms) - float(benchmark_start_ms)
            if phase_idx is not None and phase_idx in phase_starts and now_ms is not None:
                phase_relative_time_ms = float(now_ms) - float(phase_starts[phase_idx])

            # Extract endpoint from URL
            url = event.get('url', '')
            endpoint = extract_endpoint(url)

            # Get error details
            error_code = event.get('errorCode')
            error_message = event.get('errorMessage', '')
            duration_ms = event.get('durationMs')

            # Determine is_timeout based on error code or event type
            is_timeout = (
                event_type == 'timeout' or
                error_code in ('ETIMEDOUT', 'ESOCKETTIMEDOUT', 'TIMEOUT')
            )

            batch.append({
                'experiment_id': experiment_id,
                'x_pair': x_pair,
                'timestamp_ms': now_ms,
                'latency_ms': duration_ms,
                'relative_time_ms': relative_time_ms,
                'phase_relative_time_ms': phase_relative_time_ms,
                'endpoint': endpoint,
                'status_code': None,  # No HTTP status for errors
                'auth_type': event.get('authType'),
                'expected_failure': False,
                'phase_index': phase_idx,
                'phase_name': phase_name,
                'is_timeout': is_timeout,
                'is_error': not is_timeout,  # Non-timeout errors
                'error_type': event_type,
                'error_code': error_code,
                'error_message': str(error_message)[:500] if error_message else None
            })
            error_count += 1

            if x_pair:
                existing_xpairs.add(x_pair)

            if len(batch) >= batch_size:
                writer.bulk_insert('requests', batch)
                batch.clear()
                print(f"      {error_count:,} errors imported...")

    if batch:
        writer.bulk_insert('requests', batch)

    writer.commit()
    print(f"    Imported {error_count:,} error events ({skipped_count:,} duplicates skipped)")
    return error_count


def import_aws_logs(writer: DataWriter, experiment_id: int, aws_log_path: Path,
                    xpair_lookup: dict, benchmark_start_ms: float, phase_starts: dict,
                    batch_size: int = 50000):
    """
    Import Lambda executions and handler events from aws.log.
    Handler events are enriched with data from xpair_lookup.
    """
    if not aws_log_path.exists():
        print(f"    No aws.log found")
        return 0, 0

    file_size_mb = aws_log_path.stat().st_size / 1024 / 1024
    print(f"    Importing AWS logs ({file_size_mb:.1f} MB)...")

    report_pattern = re.compile(
        r'REPORT RequestId: (?P<request_id>[^\t]+)\t'
        r'Duration: (?P<duration>[\d.]+) ms\t'
        r'Billed Duration: (?P<billed>[\d.]+) ms\t'
        r'Memory Size: (?P<mem_size>\d+) MB\t'
        r'Max Memory Used: (?P<mem_used>\d+) MB'
        r'(?:\tInit Duration: (?P<init>[\d.]+) ms)?'
    )
    handler_pattern = re.compile(r'BEFAAS[:\s]*(\{.*\})')
    # Pattern to extract Lambda request ID from CloudWatch log message format:
    # "2026-01-09T10:34:39.165Z\te623841d-c9da-4da7-8a7d-d4eb61f0a8f7\tINFO\t..."
    lambda_reqid_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}T[\d:.]+Z\t([a-f0-9-]{36})\t')

    lambda_batch = []
    handler_batch = []
    container_start_batch = []
    rpc_in_batch = []
    rpc_out_batch = []
    lambda_count = 0
    handler_count = 0
    container_start_count = 0
    rpc_in_count = 0
    rpc_out_count = 0
    line_count = 0

    # Find earliest AWS log timestamp for relative timing if no benchmark_start_ms
    aws_start_ms = benchmark_start_ms

    def extract_fn_name(entry):
        fn = entry.get('fnName', '')
        if '/' in fn:
            return fn.split('/')[-1]
        log_group = entry.get('logGroup', '')
        return log_group.split('/')[-1] if log_group else fn

    def flush_batches():
        nonlocal lambda_batch, handler_batch, container_start_batch, rpc_in_batch, rpc_out_batch
        if lambda_batch:
            writer.bulk_insert('lambda_executions', lambda_batch)
            lambda_batch = []
        if handler_batch:
            writer.bulk_insert('handler_events', handler_batch)
            handler_batch = []
        if container_start_batch:
            writer.bulk_insert('container_starts', container_start_batch)
            container_start_batch = []
        if rpc_in_batch:
            writer.bulk_insert('rpc_in_events', rpc_in_batch)
            rpc_in_batch = []
        if rpc_out_batch:
            writer.bulk_insert('rpc_out_events', rpc_out_batch)
            rpc_out_batch = []

    with open(aws_log_path, 'r') as f:
        for line in f:
            line_count += 1
            try:
                entry = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            ts_ms = entry.get('timestamp')
            msg = entry.get('message', '')
            fn_name = extract_fn_name(entry)

            # Track earliest timestamp
            if ts_ms and (aws_start_ms is None or ts_ms < aws_start_ms):
                aws_start_ms = ts_ms

            # Lambda REPORT line
            match = report_pattern.search(msg)
            if match:
                init = match.group('init')
                relative_time_ms = None
                if aws_start_ms and ts_ms:
                    relative_time_ms = ts_ms - aws_start_ms

                lambda_batch.append({
                    'experiment_id': experiment_id,
                    'request_id': match.group('request_id'),
                    'function_name': fn_name,
                    'timestamp_ms': ts_ms,
                    'duration_ms': float(match.group('duration')),
                    'billed_duration_ms': float(match.group('billed')),
                    'init_duration_ms': float(init) if init else None,
                    'memory_size_mb': int(match.group('mem_size')),
                    'max_memory_used_mb': int(match.group('mem_used')),
                    'is_cold_start': init is not None,
                    'relative_time_ms': relative_time_ms
                })
                lambda_count += 1

            # BEFAAS events (handler, coldStart, rpcIn, rpcOut)
            elif 'BEFAAS' in msg:
                hmatch = handler_pattern.search(msg)
                if hmatch:
                    try:
                        data = json.loads(hmatch.group(1))
                        event_data = data.get('event', {})
                        befaas_fn = data.get('fn', {}).get('name', fn_name)
                        deployment_id = data.get('deploymentId')

                        # Extract Lambda request ID from CloudWatch log message prefix
                        lambda_request_id = None
                        reqid_match = lambda_reqid_pattern.match(msg)
                        if reqid_match:
                            lambda_request_id = reqid_match.group(1)

                        # Common enrichment for events with xPair
                        x_pair = event_data.get('xPair')
                        context_id = event_data.get('contextId')
                        enrichment = xpair_lookup.get(x_pair, {})
                        phase_idx = enrichment.get('phase_index')

                        # Calculate relative time
                        relative_time_ms = None
                        if aws_start_ms and ts_ms:
                            relative_time_ms = ts_ms - aws_start_ms

                        # Handler event
                        handler = event_data.get('handler')
                        if handler:
                            phase_relative_time_ms = None
                            if phase_idx is not None and phase_idx in phase_starts and ts_ms:
                                phase_relative_time_ms = ts_ms - phase_starts[phase_idx]

                            handler_batch.append({
                                'experiment_id': experiment_id,
                                'x_pair': x_pair,
                                'context_id': context_id,
                                'lambda_request_id': lambda_request_id,
                                'function_name': befaas_fn,
                                'route': handler.get('route'),
                                'status_code': handler.get('statusCode'),
                                'is_cold_start': handler.get('coldStart', False),
                                'request_count': handler.get('requestCount'),
                                'timestamp_ms': ts_ms,
                                'duration_ms': handler.get('durationMs'),
                                'auth_type': enrichment.get('auth_type'),
                                'expected_failure': enrichment.get('expected_failure', False),
                                'phase_index': phase_idx,
                                'phase_name': enrichment.get('phase_name'),
                                'relative_time_ms': relative_time_ms,
                                'phase_relative_time_ms': phase_relative_time_ms
                            })
                            handler_count += 1

                        # Container cold start event (no xPair, just coldStart + containerStartTime)
                        elif event_data.get('coldStart') is True and 'containerStartTime' in event_data:
                            container_start_batch.append({
                                'experiment_id': experiment_id,
                                'lambda_request_id': lambda_request_id,
                                'function_name': befaas_fn,
                                'deployment_id': deployment_id,
                                'timestamp_ms': ts_ms,
                                'container_start_time_ms': event_data.get('containerStartTime'),
                                'relative_time_ms': relative_time_ms
                            })
                            container_start_count += 1

                        # RPC incoming event
                        elif 'rpcIn' in event_data:
                            rpc_in = event_data.get('rpcIn')
                            rpc_in_batch.append({
                                'experiment_id': experiment_id,
                                'x_pair': x_pair,
                                'context_id': context_id,
                                'lambda_request_id': lambda_request_id,
                                'function_name': befaas_fn,
                                'received_at_ms': rpc_in.get('receivedAt'),
                                'is_cold_start': rpc_in.get('coldStart', False),
                                'timestamp_ms': ts_ms,
                                'relative_time_ms': relative_time_ms,
                                'auth_type': enrichment.get('auth_type'),
                                'phase_index': phase_idx,
                                'phase_name': enrichment.get('phase_name')
                            })
                            rpc_in_count += 1

                        # RPC outgoing event
                        elif 'rpcOut' in event_data:
                            rpc_out = event_data.get('rpcOut')
                            rpc_out_batch.append({
                                'experiment_id': experiment_id,
                                'x_pair': x_pair,
                                'context_id': context_id,
                                'lambda_request_id': lambda_request_id,
                                'function_name': befaas_fn,
                                'target_function': rpc_out.get('target'),
                                'call_x_pair': rpc_out.get('callXPair'),
                                'call_type': rpc_out.get('callType'),
                                'duration_ms': rpc_out.get('durationMs'),
                                'success': rpc_out.get('success', True),
                                'timestamp_ms': ts_ms,
                                'relative_time_ms': relative_time_ms,
                                'auth_type': enrichment.get('auth_type'),
                                'phase_index': phase_idx,
                                'phase_name': enrichment.get('phase_name')
                            })
                            rpc_out_count += 1

                    except json.JSONDecodeError:
                        pass

            # Flush batches periodically
            if len(lambda_batch) >= batch_size:
                flush_batches()
                print(f"      {lambda_count:,} lambda executions, {handler_count:,} handlers ({line_count:,} lines)...")

            if len(handler_batch) >= batch_size:
                flush_batches()

    # Flush remaining
    flush_batches()

    writer.commit()
    print(f"    Imported {lambda_count:,} lambda executions, {handler_count:,} handler events")
    print(f"    Imported {container_start_count:,} container starts, {rpc_in_count:,} rpc_in, {rpc_out_count:,} rpc_out")
    return lambda_count, handler_count


def import_phases(writer: DataWriter, experiment_id: int, dump_path: Path):
    """
    Import phase definitions from phases_loaded event in dump.json.
    This is a separate lightweight pass that only looks for the phases_loaded event.
    """
    if not dump_path.exists():
        return 0

    phase_count = 0
    phases = []

    try:
        import ijson
        use_streaming = True
    except ImportError:
        use_streaming = False

    def find_phases(entry):
        nonlocal phase_count
        logentry = entry.get('__logentry__', {})
        data = logentry.get('data', {})
        event = data.get('event', {})

        if event.get('type') == 'phases_loaded':
            for phase in event.get('phases', []):
                phases.append({
                    'experiment_id': experiment_id,
                    'phase_index': phase.get('index'),
                    'phase_name': phase.get('name'),
                    'duration_seconds': phase.get('duration')
                })
                phase_count += 1
            return True  # Found phases, can stop
        return False

    if use_streaming:
        with open(dump_path, 'rb') as f:
            for entry in ijson.items(f, 'item'):
                if find_phases(entry):
                    break
    else:
        with open(dump_path, 'r') as f:
            data = json.load(f)
            for entry in data:
                if find_phases(entry):
                    break

    if phases:
        writer.bulk_insert('phases', phases)
        writer.commit()
        print(f"    Imported {phase_count} phase definitions")

    return phase_count


def import_pricing(writer: DataWriter, experiment_id: int, pricing_path: Path):
    """
    Import per-function pricing data from pricing.json.
    """
    if not pricing_path.exists():
        return 0

    with open(pricing_path, 'r') as f:
        pricing_data = json.load(f)

    resources = pricing_data.get('resources', {})
    lambda_pricing = resources.get('lambda', {})
    per_function = lambda_pricing.get('per_function', {})

    pricing_records = []
    for fn_name, fn_data in per_function.items():
        # Skip functions with no invocations
        if fn_data.get('invocations', 0) == 0:
            continue

        pricing_records.append({
            'experiment_id': experiment_id,
            'function_name': fn_name,
            'invocations': fn_data.get('invocations'),
            'duration_ms': fn_data.get('duration_ms'),
            'gb_seconds': fn_data.get('gb_seconds'),
            'request_cost': fn_data.get('request_cost'),
            'compute_cost': fn_data.get('compute_cost'),
            'total_cost': fn_data.get('total_cost')
        })

    if pricing_records:
        writer.bulk_insert('function_pricing', pricing_records)
        writer.commit()
        print(f"    Imported {len(pricing_records)} function pricing records")

    return len(pricing_records)


def import_cloudwatch_metrics(writer: DataWriter, experiment_id: int, cloudwatch_dir: Path):
    """
    Import ECS and ALB metrics from CloudWatch metrics.json.

    ECS metrics are stored per-service with timestamp-based data points.
    ALB metrics are aggregated across the load balancer.
    """
    metrics_path = cloudwatch_dir / 'metrics.json'
    if not metrics_path.exists():
        return 0, 0

    with open(metrics_path, 'r') as f:
        metrics_data = json.load(f)

    metrics = metrics_data.get('metrics', {})

    # Parse ECS metrics - group by service and timestamp
    ecs_data = {}  # {(service_name, timestamp): {cpu_percent, memory_percent, ...}}

    for metric_name, metric_info in metrics.items():
        data_points = metric_info.get('data_points', [])
        if not data_points:
            continue

        # Parse ECS metrics
        if metric_name.startswith('ECS CPU - '):
            service_name = metric_name.replace('ECS CPU - ', '')
            for dp in data_points:
                key = (service_name, dp['timestamp'])
                if key not in ecs_data:
                    ecs_data[key] = {'service_name': service_name, 'timestamp': dp['timestamp']}
                ecs_data[key]['cpu_percent'] = dp['value']

        elif metric_name.startswith('ECS Memory - '):
            service_name = metric_name.replace('ECS Memory - ', '')
            for dp in data_points:
                key = (service_name, dp['timestamp'])
                if key not in ecs_data:
                    ecs_data[key] = {'service_name': service_name, 'timestamp': dp['timestamp']}
                ecs_data[key]['memory_percent'] = dp['value']

        elif metric_name.startswith('ECS Running Tasks - '):
            service_name = metric_name.replace('ECS Running Tasks - ', '')
            for dp in data_points:
                key = (service_name, dp['timestamp'])
                if key not in ecs_data:
                    ecs_data[key] = {'service_name': service_name, 'timestamp': dp['timestamp']}
                ecs_data[key]['running_tasks'] = int(dp['value']) if dp['value'] is not None else None

        elif metric_name.startswith('ECS Desired Tasks - '):
            service_name = metric_name.replace('ECS Desired Tasks - ', '')
            for dp in data_points:
                key = (service_name, dp['timestamp'])
                if key not in ecs_data:
                    ecs_data[key] = {'service_name': service_name, 'timestamp': dp['timestamp']}
                ecs_data[key]['desired_tasks'] = int(dp['value']) if dp['value'] is not None else None

    # Parse ALB metrics - group by timestamp
    alb_data = {}  # {timestamp: {request_count, response_time_avg, ...}}

    alb_metric_mapping = {
        'ALB Request Count': 'request_count',
        'ALB Target Response Time (avg)': 'response_time_avg',
        'ALB Target Response Time (p95)': 'response_time_p95',
        'ALB HTTP 2XX Count': 'http_2xx_count',
        'ALB HTTP 4XX Count': 'http_4xx_count',
        'ALB HTTP 5XX Count': 'http_5xx_count',
        'ALB Active Connections': 'active_connections',
        'Target Group Healthy Hosts': 'healthy_hosts',
    }

    for metric_name, field_name in alb_metric_mapping.items():
        metric_info = metrics.get(metric_name, {})
        data_points = metric_info.get('data_points', [])
        for dp in data_points:
            ts = dp['timestamp']
            if ts not in alb_data:
                alb_data[ts] = {'timestamp': ts}
            value = dp['value']
            # Convert counts to integers
            if field_name in ('request_count', 'http_2xx_count', 'http_4xx_count', 'http_5xx_count',
                            'active_connections', 'healthy_hosts'):
                value = int(value) if value is not None else None
            alb_data[ts][field_name] = value

    # Convert to records and insert
    ecs_records = []
    for key, data in ecs_data.items():
        # Parse timestamp string to datetime
        ts_str = data['timestamp']
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            ts = None

        ecs_records.append({
            'experiment_id': experiment_id,
            'service_name': data['service_name'],
            'timestamp': ts,
            'cpu_percent': data.get('cpu_percent'),
            'memory_percent': data.get('memory_percent'),
            'running_tasks': data.get('running_tasks'),
            'desired_tasks': data.get('desired_tasks'),
        })

    alb_records = []
    for ts_str, data in alb_data.items():
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            ts = None

        alb_records.append({
            'experiment_id': experiment_id,
            'timestamp': ts,
            'request_count': data.get('request_count'),
            'response_time_avg': data.get('response_time_avg'),
            'response_time_p95': data.get('response_time_p95'),
            'http_2xx_count': data.get('http_2xx_count'),
            'http_4xx_count': data.get('http_4xx_count'),
            'http_5xx_count': data.get('http_5xx_count'),
            'active_connections': data.get('active_connections'),
            'healthy_hosts': data.get('healthy_hosts'),
        })

    if ecs_records:
        writer.bulk_insert('ecs_metrics', ecs_records)
    if alb_records:
        writer.bulk_insert('alb_metrics', alb_records)

    if ecs_records or alb_records:
        writer.commit()
        print(f"    Imported {len(ecs_records)} ECS metrics, {len(alb_records)} ALB metrics")

    return len(ecs_records), len(alb_records)


def import_experiment(writer: DataWriter, results_dir: Path, existing_experiment_id: int = None, errors_only: bool = False):
    """Import a single benchmark experiment with full correlation

    Args:
        writer: DataWriter instance
        results_dir: Path to experiment results directory
        existing_experiment_id: If provided, use this experiment ID instead of creating new one
                               (useful for re-importing or adding data to existing experiment)
        errors_only: If True, only import error events from artillery.log (skip dump.json and other imports)
    """
    name = results_dir.name
    print(f"\nImporting: {name}")

    if existing_experiment_id:
        # Use provided experiment ID
        print(f"  Using existing experiment_id={existing_experiment_id}")
        experiment_id = existing_experiment_id

        # For SQL export mode, we still need to create the experiment record
        if writer.export_mode:
            config = parse_experiment_name(name)
            writer.insert_experiment(name, config, explicit_id=existing_experiment_id)
    else:
        # Check if exists
        existing = writer.experiment_exists(name)
        if existing:
            print(f"  Already exists (id={existing.id}), skipping")
            return existing.id

        # Create experiment
        config = parse_experiment_name(name)
        experiment_id = writer.insert_experiment(name, config)

    dump_path = results_dir / 'analysis' / 'dump.json'
    aws_log_path = results_dir / 'logs' / 'aws.log'
    artillery_log_path = results_dir / 'logs' / 'artillery.log'
    pricing_path = results_dir / 'pricing' / 'pricing.json'
    cloudwatch_dir = results_dir / 'cloudwatch'

    if errors_only:
        # Only import error events from artillery.log
        print("  Errors-only mode: importing artillery errors only")
        # Get benchmark_start_ms from existing experiment or from artillery.log
        benchmark_start_ms = None
        phase_starts = {}
        try:
            # Try to get from existing experiment
            exp = writer.experiment_exists(name)
            if exp and exp.benchmark_start_ms:
                benchmark_start_ms = exp.benchmark_start_ms
        except Exception:
            pass
        import_artillery_errors(
            writer, experiment_id, artillery_log_path, benchmark_start_ms, phase_starts
        )
        print(f"  Done (id={experiment_id})")
        return experiment_id

    # Step 1: Import dump.json (builds lookup + imports requests in optimized passes)
    xpair_lookup, benchmark_start_ms, phase_starts = import_dump_json(
        writer, experiment_id, dump_path
    )

    # Step 1b: Import error events from artillery.log (not captured in dump.json)
    import_artillery_errors(
        writer, experiment_id, artillery_log_path, benchmark_start_ms, phase_starts
    )

    # Update experiment with timing metadata
    if benchmark_start_ms:
        writer.update_experiment(experiment_id, benchmark_start_ms=benchmark_start_ms)

    # Step 2: Import phase definitions from dump.json
    import_phases(writer, experiment_id, dump_path)

    # Step 3: Import AWS logs with enrichment from xpair_lookup
    import_aws_logs(writer, experiment_id, aws_log_path, xpair_lookup, benchmark_start_ms, phase_starts)

    # Step 4: Import pricing data
    import_pricing(writer, experiment_id, pricing_path)

    # Step 5: Import CloudWatch metrics (ECS and ALB - for microservices/monolith)
    import_cloudwatch_metrics(writer, experiment_id, cloudwatch_dir)

    print(f"  Done (id={experiment_id})")
    return experiment_id


def import_all(writer: DataWriter, base_dirs: list):
    """Import all experiments from one or more base directories"""
    for base_dir in base_dirs:
        base_dir = Path(base_dir)
        results_path = base_dir / 'webservice'
        if not results_path.exists():
            results_path = base_dir
            if not results_path.exists():
                print(f"Not found: {results_path}")
                continue

        print(f"\nScanning: {results_path}")
        for exp_dir in sorted(results_path.iterdir()):
            if exp_dir.is_dir() and not exp_dir.name.startswith('.'):
                if (exp_dir / 'analysis' / 'dump.json').exists() or (exp_dir / 'logs' / 'aws.log').exists():
                    try:
                        import_experiment(writer, exp_dir)
                    except Exception as e:
                        print(f"  Error: {e}")
                        import traceback
                        traceback.print_exc()


# =============================================================================
# Schema and Views SQL Generation
# =============================================================================

def generate_schema_sql():
    """Generate CREATE TABLE statements for PostgreSQL"""
    return """-- BeFaaS Benchmark Database Schema
-- Generated by benchmark_db.py

-- Drop existing tables (in reverse dependency order)
DROP TABLE IF EXISTS alb_metrics CASCADE;
DROP TABLE IF EXISTS ecs_metrics CASCADE;
DROP TABLE IF EXISTS function_pricing CASCADE;
DROP TABLE IF EXISTS phases CASCADE;
DROP TABLE IF EXISTS rpc_out_events CASCADE;
DROP TABLE IF EXISTS rpc_in_events CASCADE;
DROP TABLE IF EXISTS container_starts CASCADE;
DROP TABLE IF EXISTS handler_events CASCADE;
DROP TABLE IF EXISTS lambda_executions CASCADE;
DROP TABLE IF EXISTS requests CASCADE;
DROP TABLE IF EXISTS experiments CASCADE;

-- Experiments table
CREATE TABLE experiments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    architecture VARCHAR(50),
    auth_strategy VARCHAR(50),
    memory_mb INTEGER,
    cpu_units INTEGER,
    bundle_mode VARCHAR(50),
    run_timestamp TIMESTAMP,
    benchmark_start_ms DOUBLE PRECISION,
    benchmark_end_ms DOUBLE PRECISION
);
CREATE INDEX idx_experiments_architecture ON experiments(architecture);
CREATE INDEX idx_experiments_auth_strategy ON experiments(auth_strategy);
CREATE INDEX idx_experiments_memory_mb ON experiments(memory_mb);

-- Requests table
CREATE TABLE requests (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    x_pair VARCHAR(100),
    timestamp_ms DOUBLE PRECISION,
    latency_ms DOUBLE PRECISION,
    relative_time_ms DOUBLE PRECISION,
    phase_relative_time_ms DOUBLE PRECISION,
    endpoint VARCHAR(200),
    status_code INTEGER,
    auth_type VARCHAR(50),
    expected_failure BOOLEAN DEFAULT FALSE,
    is_timeout BOOLEAN DEFAULT FALSE,
    is_error BOOLEAN DEFAULT FALSE,
    error_type VARCHAR(50),
    error_code VARCHAR(50),
    error_message VARCHAR(500),
    phase_index INTEGER,
    phase_name VARCHAR(100)
);
CREATE INDEX idx_requests_experiment_id ON requests(experiment_id);
CREATE INDEX idx_requests_x_pair ON requests(x_pair);
CREATE INDEX idx_requests_endpoint ON requests(endpoint);
CREATE INDEX idx_requests_auth_type ON requests(auth_type);
CREATE INDEX idx_req_exp_auth ON requests(experiment_id, auth_type);
CREATE INDEX idx_req_exp_phase ON requests(experiment_id, phase_index);

-- Lambda executions table
CREATE TABLE lambda_executions (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    request_id VARCHAR(100),
    function_name VARCHAR(100),
    timestamp_ms DOUBLE PRECISION,
    duration_ms DOUBLE PRECISION,
    billed_duration_ms DOUBLE PRECISION,
    init_duration_ms DOUBLE PRECISION,
    memory_size_mb INTEGER,
    max_memory_used_mb INTEGER,
    is_cold_start BOOLEAN DEFAULT FALSE,
    relative_time_ms DOUBLE PRECISION
);
CREATE INDEX idx_lambda_experiment_id ON lambda_executions(experiment_id);
CREATE INDEX idx_lambda_function_name ON lambda_executions(function_name);
CREATE INDEX idx_lambda_exp_fn ON lambda_executions(experiment_id, function_name);

-- Handler events table
CREATE TABLE handler_events (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    x_pair VARCHAR(100),
    context_id VARCHAR(50),
    lambda_request_id VARCHAR(100),
    function_name VARCHAR(100),
    route VARCHAR(200),
    status_code INTEGER,
    is_cold_start BOOLEAN DEFAULT FALSE,
    request_count INTEGER,
    timestamp_ms DOUBLE PRECISION,
    duration_ms DOUBLE PRECISION,
    auth_type VARCHAR(50),
    expected_failure BOOLEAN DEFAULT FALSE,
    phase_index INTEGER,
    phase_name VARCHAR(100),
    relative_time_ms DOUBLE PRECISION,
    phase_relative_time_ms DOUBLE PRECISION
);
CREATE INDEX idx_handler_experiment_id ON handler_events(experiment_id);
CREATE INDEX idx_handler_function_name ON handler_events(function_name);
CREATE INDEX idx_handler_exp_fn ON handler_events(experiment_id, function_name);
CREATE INDEX idx_handler_exp_auth ON handler_events(experiment_id, auth_type);

-- Container starts table
CREATE TABLE container_starts (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    lambda_request_id VARCHAR(100),
    function_name VARCHAR(100),
    deployment_id VARCHAR(50),
    timestamp_ms DOUBLE PRECISION,
    container_start_time_ms DOUBLE PRECISION,
    relative_time_ms DOUBLE PRECISION
);
CREATE INDEX idx_container_experiment_id ON container_starts(experiment_id);
CREATE INDEX idx_container_function_name ON container_starts(function_name);

-- RPC in events table
CREATE TABLE rpc_in_events (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    x_pair VARCHAR(100),
    context_id VARCHAR(50),
    lambda_request_id VARCHAR(100),
    function_name VARCHAR(100),
    received_at_ms DOUBLE PRECISION,
    is_cold_start BOOLEAN DEFAULT FALSE,
    timestamp_ms DOUBLE PRECISION,
    relative_time_ms DOUBLE PRECISION,
    auth_type VARCHAR(50),
    phase_index INTEGER,
    phase_name VARCHAR(100)
);
CREATE INDEX idx_rpcin_experiment_id ON rpc_in_events(experiment_id);
CREATE INDEX idx_rpcin_function_name ON rpc_in_events(function_name);

-- RPC out events table
CREATE TABLE rpc_out_events (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    x_pair VARCHAR(100),
    context_id VARCHAR(50),
    lambda_request_id VARCHAR(100),
    function_name VARCHAR(100),
    target_function VARCHAR(100),
    call_x_pair VARCHAR(100),
    call_type VARCHAR(50),
    duration_ms DOUBLE PRECISION,
    success BOOLEAN DEFAULT TRUE,
    timestamp_ms DOUBLE PRECISION,
    relative_time_ms DOUBLE PRECISION,
    auth_type VARCHAR(50),
    phase_index INTEGER,
    phase_name VARCHAR(100)
);
CREATE INDEX idx_rpcout_experiment_id ON rpc_out_events(experiment_id);
CREATE INDEX idx_rpcout_function_name ON rpc_out_events(function_name);
CREATE INDEX idx_rpcout_target_function ON rpc_out_events(target_function);

-- Phases table
CREATE TABLE phases (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    phase_index INTEGER,
    phase_name VARCHAR(100),
    duration_seconds INTEGER
);
CREATE INDEX idx_phases_experiment_id ON phases(experiment_id);

-- Function pricing table
CREATE TABLE function_pricing (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    function_name VARCHAR(100),
    invocations INTEGER,
    duration_ms DOUBLE PRECISION,
    gb_seconds DOUBLE PRECISION,
    request_cost DOUBLE PRECISION,
    compute_cost DOUBLE PRECISION,
    total_cost DOUBLE PRECISION
);
CREATE INDEX idx_pricing_experiment_id ON function_pricing(experiment_id);
CREATE INDEX idx_pricing_function_name ON function_pricing(function_name);

-- ECS metrics table
CREATE TABLE ecs_metrics (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    service_name VARCHAR(100),
    timestamp TIMESTAMP,
    cpu_percent DOUBLE PRECISION,
    memory_percent DOUBLE PRECISION,
    running_tasks INTEGER,
    desired_tasks INTEGER
);
CREATE INDEX idx_ecs_experiment_id ON ecs_metrics(experiment_id);
CREATE INDEX idx_ecs_service_name ON ecs_metrics(service_name);
CREATE INDEX idx_ecs_timestamp ON ecs_metrics(timestamp);

-- ALB metrics table
CREATE TABLE alb_metrics (
    id SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    timestamp TIMESTAMP,
    request_count INTEGER,
    response_time_avg DOUBLE PRECISION,
    response_time_p95 DOUBLE PRECISION,
    http_2xx_count INTEGER,
    http_4xx_count INTEGER,
    http_5xx_count INTEGER,
    active_connections INTEGER,
    healthy_hosts INTEGER
);
CREATE INDEX idx_alb_experiment_id ON alb_metrics(experiment_id);
CREATE INDEX idx_alb_timestamp ON alb_metrics(timestamp);

"""


AUTH_VIEWS = {
    # Overall auth overhead comparison (from client-side requests)
    'v_auth_overhead': """
        CREATE OR REPLACE VIEW v_auth_overhead AS
        SELECT
            e.architecture,
            e.auth_strategy,
            e.memory_mb,
            COUNT(*) as request_count,
            AVG(r.latency_ms) as avg_latency_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.latency_ms) as p50_latency_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY r.latency_ms) as p95_latency_ms,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY r.latency_ms) as p99_latency_ms
        FROM experiments e
        JOIN requests r ON e.id = r.experiment_id
        GROUP BY e.architecture, e.auth_strategy, e.memory_mb
    """,

    # Auth overhead delta: none vs service-integrated
    'v_auth_delta': """
        CREATE OR REPLACE VIEW v_auth_delta AS
        WITH stats AS (
            SELECT
                e.architecture,
                e.auth_strategy,
                e.memory_mb,
                AVG(r.latency_ms) as avg_ms,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.latency_ms) as p50_ms,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY r.latency_ms) as p95_ms,
                COUNT(*) as requests
            FROM experiments e
            JOIN requests r ON e.id = r.experiment_id
            GROUP BY e.architecture, e.auth_strategy, e.memory_mb
        )
        SELECT
            n.architecture,
            n.memory_mb,
            n.avg_ms as none_avg_ms,
            a.avg_ms as auth_avg_ms,
            (a.avg_ms - n.avg_ms) as overhead_avg_ms,
            n.p50_ms as none_p50_ms,
            a.p50_ms as auth_p50_ms,
            (a.p50_ms - n.p50_ms) as overhead_p50_ms,
            n.p95_ms as none_p95_ms,
            a.p95_ms as auth_p95_ms,
            (a.p95_ms - n.p95_ms) as overhead_p95_ms,
            n.requests as none_requests,
            a.requests as auth_requests
        FROM stats n
        JOIN stats a ON n.architecture = a.architecture AND n.memory_mb = a.memory_mb
        WHERE n.auth_strategy = 'none' AND a.auth_strategy = 'service-integrated'
    """,

    # Handler duration by function and phase (MAIN VIEW for your use case)
    'v_handler_by_function_phase': """
        CREATE OR REPLACE VIEW v_handler_by_function_phase AS
        SELECT
            e.architecture,
            e.auth_strategy,
            e.memory_mb,
            h.function_name,
            h.phase_index,
            h.phase_name,
            h.auth_type,
            COUNT(*) as request_count,
            AVG(h.duration_ms) as avg_duration_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY h.duration_ms) as p50_duration_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY h.duration_ms) as p95_duration_ms,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY h.duration_ms) as p99_duration_ms,
            SUM(CASE WHEN h.is_cold_start THEN 1 ELSE 0 END) as cold_starts,
            SUM(CASE WHEN h.expected_failure THEN 1 ELSE 0 END) as expected_failures
        FROM experiments e
        JOIN handler_events h ON e.id = h.experiment_id
        WHERE h.duration_ms IS NOT NULL
        GROUP BY e.architecture, e.auth_strategy, e.memory_mb,
                 h.function_name, h.phase_index, h.phase_name, h.auth_type
    """,

    # Handler auth overhead delta by function
    'v_handler_auth_delta': """
        CREATE OR REPLACE VIEW v_handler_auth_delta AS
        WITH stats AS (
            SELECT
                e.architecture,
                e.auth_strategy,
                e.memory_mb,
                h.function_name,
                AVG(h.duration_ms) as avg_ms,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY h.duration_ms) as p50_ms,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY h.duration_ms) as p95_ms,
                COUNT(*) as requests
            FROM experiments e
            JOIN handler_events h ON e.id = h.experiment_id
            WHERE h.duration_ms IS NOT NULL
            GROUP BY e.architecture, e.auth_strategy, e.memory_mb, h.function_name
        )
        SELECT
            n.architecture,
            n.memory_mb,
            n.function_name,
            n.avg_ms as none_avg_ms,
            a.avg_ms as auth_avg_ms,
            (a.avg_ms - n.avg_ms) as overhead_avg_ms,
            n.p50_ms as none_p50_ms,
            a.p50_ms as auth_p50_ms,
            (a.p50_ms - n.p50_ms) as overhead_p50_ms,
            n.p95_ms as none_p95_ms,
            a.p95_ms as auth_p95_ms,
            (a.p95_ms - n.p95_ms) as overhead_p95_ms,
            n.requests as none_requests,
            a.requests as auth_requests
        FROM stats n
        JOIN stats a ON n.architecture = a.architecture
            AND n.memory_mb = a.memory_mb
            AND n.function_name = a.function_name
        WHERE n.auth_strategy = 'none' AND a.auth_strategy = 'service-integrated'
    """,

    # Cold start impact on handler duration
    'v_cold_start_impact': """
        CREATE OR REPLACE VIEW v_cold_start_impact AS
        SELECT
            e.architecture,
            e.auth_strategy,
            e.memory_mb,
            h.function_name,
            h.is_cold_start,
            h.auth_type,
            COUNT(*) as request_count,
            AVG(h.duration_ms) as avg_duration_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY h.duration_ms) as p50_duration_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY h.duration_ms) as p95_duration_ms
        FROM experiments e
        JOIN handler_events h ON e.id = h.experiment_id
        WHERE h.duration_ms IS NOT NULL
        GROUP BY e.architecture, e.auth_strategy, e.memory_mb,
                 h.function_name, h.is_cold_start, h.auth_type
    """,

    # Lambda execution stats by function
    'v_lambda_by_function': """
        CREATE OR REPLACE VIEW v_lambda_by_function AS
        SELECT
            e.architecture,
            e.auth_strategy,
            e.memory_mb,
            l.function_name,
            COUNT(*) as invocation_count,
            AVG(l.duration_ms) as avg_duration_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.duration_ms) as p50_duration_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY l.duration_ms) as p95_duration_ms,
            SUM(CASE WHEN l.is_cold_start THEN 1 ELSE 0 END) as cold_starts,
            AVG(l.init_duration_ms) FILTER (WHERE l.is_cold_start) as avg_init_duration_ms,
            AVG(l.max_memory_used_mb) as avg_memory_mb
        FROM experiments e
        JOIN lambda_executions l ON e.id = l.experiment_id
        GROUP BY e.architecture, e.auth_strategy, e.memory_mb, l.function_name
    """,

    # Handler by route
    'v_handler_by_route': """
        CREATE OR REPLACE VIEW v_handler_by_route AS
        SELECT
            e.architecture,
            e.auth_strategy,
            e.memory_mb,
            h.function_name,
            h.route,
            h.auth_type,
            COUNT(*) as request_count,
            AVG(h.duration_ms) as avg_duration_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY h.duration_ms) as p50_duration_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY h.duration_ms) as p95_duration_ms,
            SUM(CASE WHEN h.is_cold_start THEN 1 ELSE 0 END) as cold_starts
        FROM experiments e
        JOIN handler_events h ON e.id = h.experiment_id
        WHERE h.duration_ms IS NOT NULL
        GROUP BY e.architecture, e.auth_strategy, e.memory_mb,
                 h.function_name, h.route, h.auth_type
    """,

    # Requests by phase
    'v_requests_by_phase': """
        CREATE OR REPLACE VIEW v_requests_by_phase AS
        SELECT
            e.architecture,
            e.auth_strategy,
            e.memory_mb,
            r.phase_index,
            r.phase_name,
            r.auth_type,
            COUNT(*) as request_count,
            AVG(r.latency_ms) as avg_latency_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.latency_ms) as p50_latency_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY r.latency_ms) as p95_latency_ms,
            SUM(CASE WHEN r.expected_failure THEN 1 ELSE 0 END) as expected_failures
        FROM experiments e
        JOIN requests r ON e.id = r.experiment_id
        WHERE r.phase_index IS NOT NULL
        GROUP BY e.architecture, e.auth_strategy, e.memory_mb,
                 r.phase_index, r.phase_name, r.auth_type
        ORDER BY r.phase_index
    """
}


def generate_views_sql():
    """Generate CREATE VIEW statements"""
    sql = "\n-- Analytical Views\n"
    for name, view_sql in AUTH_VIEWS.items():
        sql += f"\n{view_sql.strip()};\n"
    return sql


def create_views(session):
    """Create analytical views (PostgreSQL only)"""
    conn = session.connection()
    if conn.dialect.name != 'postgresql':
        print("Views require PostgreSQL")
        return

    print("Creating views...")
    for name, sql in AUTH_VIEWS.items():
        try:
            session.execute(text(sql))
            print(f"  {name}")
        except Exception as e:
            print(f"  {name}: ERROR - {e}")
    session.commit()
    print("Done")


# =============================================================================
# CLI
# =============================================================================

def parse_args():
    """Parse command line arguments"""
    args = sys.argv[1:]

    # Extract --export-sql flag
    export_sql_file = None
    if '--export-sql' in args:
        idx = args.index('--export-sql')
        if idx + 1 < len(args):
            export_sql_file = Path(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        else:
            print("Error: --export-sql requires a file path")
            sys.exit(1)

    # Extract --experiment-id flag
    experiment_id = None
    if '--experiment-id' in args:
        idx = args.index('--experiment-id')
        if idx + 1 < len(args):
            try:
                experiment_id = int(args[idx + 1])
            except ValueError:
                print("Error: --experiment-id requires an integer")
                sys.exit(1)
            args = args[:idx] + args[idx + 2:]
        else:
            print("Error: --experiment-id requires an integer value")
            sys.exit(1)

    # Extract --errors-only flag
    errors_only = '--errors-only' in args
    if errors_only:
        args.remove('--errors-only')

    return args, export_sql_file, experiment_id, errors_only


def main():
    args, export_sql_file, experiment_id, errors_only = parse_args()

    # Validate --errors-only requires --experiment-id
    if errors_only and experiment_id is None:
        print("Error: --errors-only requires --experiment-id")
        sys.exit(1)

    if len(args) < 1:
        print(__doc__)
        print("\nCommands:")
        print("  init                              Initialize database tables")
        print("  import <dir>                      Import single experiment")
        print("  import-all <dir> [dir...]         Import all experiments from directories")
        print("  views                             Create analytical views")
        print("  schema                            Print schema SQL to stdout")
        print("")
        print("Options:")
        print("  --export-sql <file.sql>           Export to SQL file instead of database")
        print("                                    (works with import and import-all)")
        print("  --experiment-id <id>              Use existing experiment ID (skips creation)")
        print("  --errors-only                     Only import error events from artillery.log")
        print("                                    (requires --experiment-id)")
        return

    cmd = args[0]

    # Commands that don't need database connection
    if cmd == 'schema':
        print(generate_schema_sql())
        print(generate_views_sql())
        return

    # Import commands - can use either DB or SQL export
    if cmd == 'import' and len(args) > 1:
        if export_sql_file:
            writer = DataWriter(sql_file=export_sql_file, batch_size=1000)
            import_experiment(writer, Path(args[1]), existing_experiment_id=experiment_id, errors_only=errors_only)
            writer.close()
            print(f"\nSQL exported to: {export_sql_file}")
        else:
            engine = get_engine()
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            session = Session()
            writer = DataWriter(session=session)
            try:
                import_experiment(writer, Path(args[1]), existing_experiment_id=experiment_id, errors_only=errors_only)
            finally:
                writer.close()
        return

    if cmd == 'import-all' and len(args) > 1:
        if export_sql_file:
            writer = DataWriter(sql_file=export_sql_file, batch_size=1000)
            import_all(writer, args[1:])
            writer.close()
            print(f"\nSQL exported to: {export_sql_file}")
        else:
            engine = get_engine()
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            session = Session()
            writer = DataWriter(session=session)
            try:
                import_all(writer, args[1:])
            finally:
                writer.close()
        return

    # Commands that need database connection
    engine = get_engine()

    if cmd == 'init':
        Base.metadata.create_all(engine)
        print("Tables created")
        return

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        if cmd == 'views':
            create_views(session)
        else:
            print(f"Unknown command: {cmd}")
    finally:
        session.close()


if __name__ == '__main__':
    main()