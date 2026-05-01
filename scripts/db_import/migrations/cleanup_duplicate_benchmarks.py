#!/usr/bin/env python3
"""
Cleanup: Mark duplicate experiment imports (detected via benchmark_start_ms)
with an `import_failure` reason so they stay in the database for audit but are
excluded from all analyses.

Background
----------
`benchmark_start_ms` is the minimum Artillery event timestamp in the run and is
set at benchmark start (see `scripts/experiment/config.js` + `db_import/parsers/
artillery.py`). Two successful, independent benchmark runs can never share the
same value: Artillery is only started after Terraform has provisioned new
infrastructure, and the first emitted event defines `benchmark_start_ms`.

When two or more experiments share one `benchmark_start_ms`, the root cause is
the central workload deploy log that Artillery re-reads when a run crashes
before `workload.sh` rewrites it (see `scripts/workload.sh:196` and
`scripts/logs.sh:63-67`). In that case the second run imports the PREVIOUS
run's artillery.log and carries all its xPairs. Consequence: every request,
handler event, lambda execution, RPC call, ECS/ALB metric point gets inserted
a second time under a new experiment id — inflating aggregates, distorting
P99 baselines and producing artefacts such as the Monolith L "none" outlier.

Behavior
--------
1. Ensure column `experiments.import_failure` (TEXT, nullable) exists.
2. Group experiments by `benchmark_start_ms`; any group with > 1 row is a
   duplicate cluster.
3. For each cluster verify a ≥99% `x_pair` overlap between the "keep" run and
   every "drop" run (sanity check; should always be 100%).
4. Show the full list to the user (KEEP vs MARK).
5. Ask once for interactive confirmation (y/N).
6. On confirmation, set `import_failure = 'duplicate_benchmark_start_ms:<bms>'`
   for every drop row inside ONE transaction. No rows are deleted.

All analysis SQL should then filter `WHERE e.import_failure IS NULL`, which is
centralised in `scripts/thesis_analysis/db_connection.py` via EXCLUDE_SQL.

Usage
-----
    python -m db_import.migrations.cleanup_duplicate_benchmarks [--dry-run] [--yes]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import List

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0] + "/scripts")
from db_import.config import get_database_url


@dataclass
class ExperimentRow:
    id: int
    name: str
    run_timestamp: str
    architecture: str
    auth_strategy: str
    ram_in_mb: int | None
    cpu_in_vcpu: float | None
    x_pair_count: int
    import_failure: str | None


@dataclass
class DuplicateGroup:
    benchmark_start_ms: int
    keep: ExperimentRow
    drop: List[ExperimentRow]
    overlaps: dict[int, float]  # drop.id → overlap ratio against keep


def ensure_import_failure_column(engine: Engine) -> None:
    """Add experiments.import_failure (TEXT, nullable) if it doesn't exist yet."""
    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'experiments' AND column_name = 'import_failure'
        """)).fetchone()
        if exists:
            return
        print("Adding column experiments.import_failure (TEXT)...")
        conn.execute(text("""
            ALTER TABLE experiments
                ADD COLUMN import_failure TEXT
        """))
        conn.execute(text("""
            COMMENT ON COLUMN experiments.import_failure IS
            'If set, indicates this experiment row is unusable for analysis. '
            'Value is a short machine-readable reason, e.g. '
            '''duplicate_benchmark_start_ms:<bms>''. Analyses must filter '
            'WHERE import_failure IS NULL.'
        """))
        print("Column added.")


def find_duplicate_groups(engine: Engine) -> List[DuplicateGroup]:
    """Return all experiment clusters that share a benchmark_start_ms."""
    groups: List[DuplicateGroup] = []

    with engine.connect() as conn:
        cluster_rows = conn.execute(text("""
            SELECT benchmark_start_ms,
                   array_agg(id ORDER BY run_timestamp NULLS LAST, id) AS ids
              FROM experiments
             WHERE benchmark_start_ms IS NOT NULL
             GROUP BY benchmark_start_ms
            HAVING COUNT(*) > 1
             ORDER BY benchmark_start_ms
        """)).fetchall()

        for cluster in cluster_rows:
            ids = list(cluster.ids)
            detail_rows = conn.execute(text("""
                SELECT e.id, e.name, e.run_timestamp::text AS run_timestamp,
                       e.architecture, e.auth_strategy,
                       e.ram_in_mb, e.cpu_in_vcpu,
                       e.import_failure,
                       (SELECT COUNT(DISTINCT x_pair)
                          FROM requests WHERE experiment_id = e.id) AS x_pair_count
                  FROM experiments e
                 WHERE e.id = ANY(:ids)
                 ORDER BY e.run_timestamp NULLS LAST, e.id
            """), {"ids": ids}).fetchall()

            exps = [ExperimentRow(**dict(r._mapping)) for r in detail_rows]
            keep, drops = exps[0], exps[1:]

            overlaps: dict[int, float] = {}
            for d in drops:
                overlap_row = conn.execute(text("""
                    WITH keep_xp AS (
                        SELECT DISTINCT x_pair FROM requests
                         WHERE experiment_id = :keep_id AND x_pair IS NOT NULL
                    ),
                    drop_xp AS (
                        SELECT DISTINCT x_pair FROM requests
                         WHERE experiment_id = :drop_id AND x_pair IS NOT NULL
                    )
                    SELECT
                        (SELECT COUNT(*) FROM drop_xp) AS drop_total,
                        (SELECT COUNT(*) FROM drop_xp d
                           JOIN keep_xp k ON k.x_pair = d.x_pair) AS common
                """), {"keep_id": keep.id, "drop_id": d.id}).one()
                drop_total = overlap_row.drop_total or 0
                common = overlap_row.common or 0
                overlaps[d.id] = (common / drop_total) if drop_total else 0.0

            groups.append(DuplicateGroup(
                benchmark_start_ms=cluster.benchmark_start_ms,
                keep=keep,
                drop=drops,
                overlaps=overlaps,
            ))

    return groups


def format_exp(e: ExperimentRow) -> str:
    hw = f"{e.ram_in_mb}MB" if e.architecture == "faas" else \
         f"{e.ram_in_mb}MB/{e.cpu_in_vcpu}vCPU"
    flag = f"  import_failure={e.import_failure!r}" if e.import_failure else ""
    return (f"id={e.id:>4}  ts={e.run_timestamp}  "
            f"{e.architecture:<13} {e.auth_strategy:<26} {hw:<16} "
            f"x_pairs={e.x_pair_count}{flag}")


def print_plan(groups: List[DuplicateGroup]) -> list[tuple[int, int]]:
    """Return list of (drop_id, benchmark_start_ms) tuples."""
    to_mark: list[tuple[int, int]] = []
    total_drops = sum(len(g.drop) for g in groups)

    print(f"\nFound {len(groups)} duplicate cluster(s), "
          f"{total_drops} experiment(s) to mark as import_failure.\n")
    print("=" * 100)

    for g in groups:
        print(f"\nbenchmark_start_ms = {g.benchmark_start_ms}")
        print(f"  [KEEP] {format_exp(g.keep)}")
        for d in g.drop:
            overlap_pct = g.overlaps.get(d.id, 0.0) * 100
            marker = "MARK" if overlap_pct >= 99.0 else "MARK?"
            print(f"  [{marker:<5}] {format_exp(d)}  "
                  f"x_pair_overlap_vs_KEEP={overlap_pct:.1f}%")
            to_mark.append((d.id, g.benchmark_start_ms))

    print("\n" + "=" * 100)
    print(f"Total experiments to mark: {len(to_mark)}")
    print(f"IDs: {[i for i, _ in to_mark]}")
    return to_mark


def mark_all(engine: Engine,
             to_mark: list[tuple[int, int]],
             dry_run: bool) -> None:
    if not to_mark:
        print("Nothing to mark.")
        return
    with engine.begin() as conn:
        total = 0
        for drop_id, bms in to_mark:
            reason = f"duplicate_benchmark_start_ms:{bms}"
            result = conn.execute(text("""
                UPDATE experiments
                   SET import_failure = :reason
                 WHERE id = :id
                   AND (import_failure IS NULL OR import_failure = :reason)
            """), {"reason": reason, "id": drop_id})
            total += result.rowcount
        print(f"\nMarked {total} experiment row(s) as import_failure.")
        if dry_run:
            print("[DRY RUN] Rolling back.")
            conn.rollback()


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    auto_yes = "--yes" in sys.argv or "-y" in sys.argv

    if dry_run:
        print("=== DRY RUN MODE ===")

    engine = create_engine(get_database_url())
    ensure_import_failure_column(engine)
    groups = find_duplicate_groups(engine)

    if not groups:
        print("No duplicate clusters found. Database is clean.")
        return 0

    to_mark = print_plan(groups)

    low_overlap = [
        (g.benchmark_start_ms, d.id, g.overlaps[d.id])
        for g in groups for d in g.drop
        if g.overlaps[d.id] < 0.99
    ]
    if low_overlap:
        print("\nWARNING: the following drops have <99% x_pair overlap with "
              "the kept experiment. Please review before confirming:")
        for bms, did, ov in low_overlap:
            print(f"  bms={bms}  drop_id={did}  overlap={ov*100:.1f}%")

    if not auto_yes:
        print("\nMark ALL listed experiments as import_failure in a single "
              "transaction? [y/N] ", end="", flush=True)
        answer = sys.stdin.readline().strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted. No changes made.")
            return 1

    mark_all(engine, to_mark, dry_run)
    print("Done." if not dry_run else "Dry run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
