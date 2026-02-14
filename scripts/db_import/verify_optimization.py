#!/usr/bin/env python3
"""
Verification script for db_import optimizations.

This script verifies that the optimized db_import implementation produces
identical results to the legacy version, ensuring data integrity while
providing performance improvements.

Usage:
    python verify_optimization.py <experiment_directory>

Environment Variables:
    DB_IMPORT_OPTIMIZED=true/false - Toggle optimized vs legacy processing
"""

import os
import sys
import time
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Tuple
import json
import sqlite3
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from cli import create_engine_from_config
from importer import import_experiment
from sqlalchemy import text
from sqlalchemy.orm import Session


class OptimizationVerifier:
    def __init__(self, experiment_dir: Path, config_file: Path = None):
        self.experiment_dir = experiment_dir
        self.config_file = config_file or Path(__file__).parent / "config.py"
        self.results = {}

    def run_verification(self) -> Dict[str, Any]:
        """
        Run complete verification comparing optimized vs legacy implementations.

        Returns:
            Dictionary containing verification results and performance metrics
        """
        print(f"🔍 Verification: db_import optimization for {self.experiment_dir.name}")
        print("=" * 80)

        # Create temporary databases for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_db = Path(temp_dir) / "legacy.db"
            optimized_db = Path(temp_dir) / "optimized.db"

            # Test both implementations
            legacy_results = self._test_implementation(
                self.experiment_dir, legacy_db, optimized=False, label="Legacy"
            )

            optimized_results = self._test_implementation(
                self.experiment_dir, optimized_db, optimized=True, label="Optimized"
            )

            # Compare data integrity
            data_comparison = self._compare_databases(legacy_db, optimized_db)

            # Calculate performance improvements
            performance_analysis = self._analyze_performance(legacy_results, optimized_results)

            # Generate report
            report = {
                'experiment_name': self.experiment_dir.name,
                'timestamp': datetime.utcnow().isoformat(),
                'legacy_results': legacy_results,
                'optimized_results': optimized_results,
                'data_integrity': data_comparison,
                'performance_analysis': performance_analysis,
                'verification_passed': data_comparison['identical'],
                'performance_improvement': performance_analysis['total_improvement_percent']
            }

            self._print_report(report)
            return report

    def _test_implementation(self, experiment_dir: Path, db_path: Path,
                           optimized: bool, label: str) -> Dict[str, Any]:
        """Test a single implementation and return results."""
        print(f"\n📊 Testing {label} Implementation")
        print("-" * 40)

        # Set environment variable for implementation choice
        os.environ['DB_IMPORT_OPTIMIZED'] = 'true' if optimized else 'false'

        # Create in-memory SQLite database for testing
        engine = f"sqlite:///{db_path}"

        start_time = time.time()
        memory_before = self._get_memory_usage()

        try:
            # Import experiment
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            from schema import create_tables

            engine_obj = create_engine(engine)
            create_tables(engine_obj)

            with Session(engine_obj) as session:
                exp_id = import_experiment(
                    session, experiment_dir,
                    force=True, batch_size=10000
                )

                # Gather statistics
                stats = self._gather_database_stats(session, exp_id)

        except Exception as e:
            print(f"❌ {label} implementation failed: {e}")
            raise

        end_time = time.time()
        memory_after = self._get_memory_usage()

        results = {
            'success': exp_id is not None,
            'experiment_id': exp_id,
            'execution_time_seconds': end_time - start_time,
            'memory_usage_mb': memory_after - memory_before,
            'database_stats': stats,
            'timestamp': datetime.utcnow().isoformat()
        }

        print(f"✅ {label} completed in {results['execution_time_seconds']:.2f}s")
        print(f"   Memory used: {results['memory_usage_mb']:.1f}MB")
        print(f"   Records imported: {sum(stats.values()):,}")

        return results

    def _gather_database_stats(self, session: Session, exp_id: int) -> Dict[str, int]:
        """Gather record counts and basic statistics from database."""
        tables = [
            'experiments', 'phases', 'requests', 'handler_events',
            'lambda_executions', 'rpc_calls', 'container_starts',
            'metrics_alb', 'metrics_ecs', 'pricing', 'pricing_components'
        ]

        stats = {}
        for table in tables:
            try:
                result = session.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE experiment_id = :exp_id"),
                    {"exp_id": exp_id}
                ).scalar()
                stats[table] = result or 0
            except:
                stats[table] = 0

        return stats

    def _compare_databases(self, legacy_db: Path, optimized_db: Path) -> Dict[str, Any]:
        """Compare data between legacy and optimized databases."""
        print(f"\n🔍 Comparing Database Contents")
        print("-" * 40)

        comparison = {
            'identical': True,
            'table_comparisons': {},
            'field_comparisons': {},
            'errors': []
        }

        try:
            legacy_conn = sqlite3.connect(legacy_db)
            optimized_conn = sqlite3.connect(optimized_db)

            # Compare table record counts
            tables = ['requests', 'handler_events', 'lambda_executions', 'rpc_calls', 'container_starts']

            for table in tables:
                legacy_count = legacy_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                optimized_count = optimized_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

                comparison['table_comparisons'][table] = {
                    'legacy_count': legacy_count,
                    'optimized_count': optimized_count,
                    'identical': legacy_count == optimized_count
                }

                if legacy_count != optimized_count:
                    comparison['identical'] = False
                    print(f"❌ {table}: Legacy={legacy_count:,}, Optimized={optimized_count:,}")
                else:
                    print(f"✅ {table}: {legacy_count:,} records (identical)")

            # Compare critical derived fields for requests table
            if comparison['table_comparisons']['requests']['identical']:
                derived_fields = [
                    'relative_time_ms', 'phase_relative_time_ms',
                    'handler_duration_ms', 'network_overhead_ms'
                ]

                for field in derived_fields:
                    field_comparison = self._compare_field_values(
                        legacy_conn, optimized_conn, 'requests', field
                    )
                    comparison['field_comparisons'][f'requests.{field}'] = field_comparison

                    if not field_comparison['identical']:
                        comparison['identical'] = False
                        print(f"❌ requests.{field}: Field values differ")
                    else:
                        print(f"✅ requests.{field}: Field values identical")

            legacy_conn.close()
            optimized_conn.close()

        except Exception as e:
            comparison['errors'].append(str(e))
            comparison['identical'] = False
            print(f"❌ Database comparison failed: {e}")

        return comparison

    def _compare_field_values(self, legacy_conn, optimized_conn, table: str, field: str) -> Dict[str, Any]:
        """Compare specific field values between databases."""
        try:
            # Sample 1000 random records to compare field values
            legacy_values = legacy_conn.execute(f"""
                SELECT {field} FROM {table}
                WHERE {field} IS NOT NULL
                ORDER BY RANDOM() LIMIT 1000
            """).fetchall()

            optimized_values = optimized_conn.execute(f"""
                SELECT {field} FROM {table}
                WHERE {field} IS NOT NULL
                ORDER BY RANDOM() LIMIT 1000
            """).fetchall()

            # Convert to sets for comparison
            legacy_set = set(row[0] for row in legacy_values)
            optimized_set = set(row[0] for row in optimized_values)

            return {
                'identical': legacy_set == optimized_set,
                'legacy_sample_size': len(legacy_values),
                'optimized_sample_size': len(optimized_values),
                'common_values': len(legacy_set & optimized_set),
                'legacy_only': len(legacy_set - optimized_set),
                'optimized_only': len(optimized_set - legacy_set)
            }

        except Exception as e:
            return {
                'identical': False,
                'error': str(e)
            }

    def _analyze_performance(self, legacy: Dict[str, Any],
                           optimized: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze performance improvements."""
        print(f"\n📈 Performance Analysis")
        print("-" * 40)

        time_improvement = (
            (legacy['execution_time_seconds'] - optimized['execution_time_seconds'])
            / legacy['execution_time_seconds'] * 100
        )

        memory_improvement = (
            (legacy['memory_usage_mb'] - optimized['memory_usage_mb'])
            / max(legacy['memory_usage_mb'], 1) * 100
        )

        analysis = {
            'execution_time_improvement_percent': round(time_improvement, 1),
            'memory_improvement_percent': round(memory_improvement, 1),
            'total_improvement_percent': round(time_improvement, 1),  # Primary metric
            'legacy_time_seconds': legacy['execution_time_seconds'],
            'optimized_time_seconds': optimized['execution_time_seconds'],
            'legacy_memory_mb': legacy['memory_usage_mb'],
            'optimized_memory_mb': optimized['memory_usage_mb']
        }

        print(f"⚡ Execution time: {time_improvement:+.1f}% improvement")
        print(f"🧠 Memory usage: {memory_improvement:+.1f}% improvement")
        print(f"📊 Overall improvement: {time_improvement:.1f}%")

        return analysis

    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0  # psutil not available

    def _print_report(self, report: Dict[str, Any]):
        """Print final verification report."""
        print(f"\n📋 Verification Report")
        print("=" * 80)
        print(f"Experiment: {report['experiment_name']}")
        print(f"Timestamp: {report['timestamp']}")
        print()

        if report['verification_passed']:
            print("✅ DATA INTEGRITY: PASSED - Optimized implementation produces identical results")
        else:
            print("❌ DATA INTEGRITY: FAILED - Results differ between implementations")

        print(f"🚀 PERFORMANCE: {report['performance_improvement']:+.1f}% improvement")

        print(f"\nExecution Times:")
        print(f"  Legacy:    {report['legacy_results']['execution_time_seconds']:.2f}s")
        print(f"  Optimized: {report['optimized_results']['execution_time_seconds']:.2f}s")

        if not report['verification_passed']:
            print(f"\n❗ Issues Found:")
            for table, comparison in report['data_integrity']['table_comparisons'].items():
                if not comparison['identical']:
                    print(f"  {table}: {comparison['legacy_count']} != {comparison['optimized_count']}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python verify_optimization.py <experiment_directory>")
        sys.exit(1)

    experiment_dir = Path(sys.argv[1])
    if not experiment_dir.exists():
        print(f"Error: Experiment directory {experiment_dir} does not exist")
        sys.exit(1)

    verifier = OptimizationVerifier(experiment_dir)
    report = verifier.run_verification()

    # Save report to file
    report_file = experiment_dir.parent / f"verification_report_{experiment_dir.name}.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n📄 Report saved to: {report_file}")

    # Exit with appropriate code
    sys.exit(0 if report['verification_passed'] else 1)


if __name__ == '__main__':
    main()