import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, select, func, text
from sqlalchemy.pool import QueuePool
from sqlalchemy.orm import Session

from .schema import (
    Base, Experiment, Request, LambdaExecution, HandlerEvent,
    ContainerStart, RpcCall, Pricing, PricingComponent,
    MetricsEcs, MetricsAlb, Phase, ScalingRule, get_schema_documentation,
)
from .importer import import_experiment, import_all_experiments, init_database, backfill_nulls, _run_post_processing, _calculate_phase_starts
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


def get_database_url() -> str:
    """Get PostgreSQL database URL from config."""
    from .config import get_database_url as get_url
    return get_url()


def create_db_engine(url: str, echo: bool = False):
    return create_engine(
        url,
        echo=echo,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=30,
    )


def cmd_init(args):
    url = get_database_url()
    print(f"Database: {url.split('@')[-1] if '@' in url else url}")

    engine = create_db_engine(url, echo=args.verbose)
    init_database(engine, drop_existing=args.drop)


def cmd_import(args):
    url = get_database_url()
    print(f"Database: {url.split('@')[-1] if '@' in url else url}")

    engine = create_db_engine(url, echo=args.verbose)
    exp_dir = Path(args.directory).resolve()

    with Session(engine) as session:
        exp_id = import_experiment(
            session,
            exp_dir,
            force=args.force,
            batch_size=args.batch_size,
        )
        if exp_id:
            print(f"\nSuccessfully imported experiment {exp_id}")


def cmd_import_all(args):
    url = get_database_url()
    print(f"Database: {url.split('@')[-1] if '@' in url else url}")

    engine = create_db_engine(url, echo=args.verbose)
    results_dir = Path(args.results_dir).resolve()

    with Session(engine) as session:
        ids = import_all_experiments(
            session,
            results_dir,
            force=args.force,
            batch_size=args.batch_size,
        )
        print(f"\nSuccessfully imported {len(ids)} experiments")


def cmd_list(args):
    url = get_database_url()
    engine = create_db_engine(url, echo=args.verbose)

    with Session(engine) as session:
        experiments = session.execute(
            select(Experiment).order_by(Experiment.id)
        ).scalars().all()

        if not experiments:
            print("No experiments in database")
            return

        print(f"\n{'ID':>4} {'Architecture':<15} {'Auth Strategy':<25} {'RAM':>8} {'Name'}")
        print("-" * 100)

        for exp in experiments:
            print(f"{exp.id:>4} {exp.architecture:<15} {exp.auth_strategy:<25} {exp.ram_in_mb:>6}MB {exp.name}")

        print(f"\nTotal: {len(experiments)} experiments")


def cmd_delete(args):
    url = get_database_url()
    engine = create_db_engine(url, echo=args.verbose)

    with Session(engine) as session:
        exp = session.get(Experiment, args.experiment_id)
        if not exp:
            print(f"Experiment {args.experiment_id} not found")
            return

        if not args.yes:
            confirm = input(f"Delete experiment '{exp.name}'? [y/N] ")
            if confirm.lower() != 'y':
                print("Cancelled")
                return

        session.delete(exp)
        session.commit()
        print(f"Deleted experiment {args.experiment_id}")


def cmd_stats(args):
    url = get_database_url()
    engine = create_db_engine(url, echo=args.verbose)

    with Session(engine) as session:
        # Experiment counts by architecture
        print("\n=== Experiments by Architecture ===")
        result = session.execute(
            select(Experiment.architecture, func.count(Experiment.id))
            .group_by(Experiment.architecture)
        )
        for arch, count in result:
            print(f"  {arch}: {count}")

        # Experiment counts by auth strategy
        print("\n=== Experiments by Auth Strategy ===")
        result = session.execute(
            select(Experiment.auth_strategy, func.count(Experiment.id))
            .group_by(Experiment.auth_strategy)
        )
        for auth, count in result:
            print(f"  {auth}: {count}")

        # Table row counts
        print("\n=== Table Row Counts ===")
        tables = [
            ("experiments", Experiment),
            ("phases", Phase),
            ("scaling_rules", ScalingRule),
            ("requests", Request),
            ("lambda_executions", LambdaExecution),
            ("handler_events", HandlerEvent),
            ("container_starts", ContainerStart),
            ("rpc_calls", RpcCall),
            ("pricing", Pricing),
            ("pricing_components", PricingComponent),
            ("metrics_alb", MetricsAlb),
            ("metrics_ecs", MetricsEcs),
        ]

        for name, model in tables:
            count = session.execute(select(func.count()).select_from(model)).scalar()
            print(f"  {name}: {count:,}")


def cmd_query(args):
    url = get_database_url()
    engine = create_db_engine(url, echo=args.verbose)

    with engine.connect() as conn:
        result = conn.execute(text(args.sql))

        # Print column headers
        if result.keys():
            headers = list(result.keys())
            print("\t".join(headers))
            print("-" * 80)

            # Print rows
            for row in result:
                print("\t".join(str(v) for v in row))


def cmd_schema_info(args):
    print(get_schema_documentation())


def dry_run_experiment(experiment_dir: Path) -> dict:
    """
    Parse all data from an experiment directory without database operations.

    Returns a dict with counts of what would be imported.
    """
    if not experiment_dir.is_dir():
        print(f"Error: {experiment_dir} is not a directory")
        return {}

    print(f"\n{'='*60}")
    print(f"DRY RUN: {experiment_dir.name}")
    print(f"{'='*60}")

    stats = {
        'scaling_rules': 0,
        'phases': 0,
        'requests': 0,
        'lambda_executions': 0,
        'handler_events': 0,
        'container_starts': 0,
        'rpc_calls': 0,
        'pricing_components': 0,
        'metrics_alb': 0,
        'metrics_ecs': 0,
    }

    # Parse directory name
    dir_meta = parse_directory_name(experiment_dir)
    print(f"\n[Directory Metadata]")
    print(f"  Name: {dir_meta.name}")
    print(f"  Architecture: {dir_meta.architecture}")
    print(f"  Auth Strategy: {dir_meta.auth_strategy}")
    print(f"  RAM: {dir_meta.ram_in_mb} MB")
    if dir_meta.cpu_in_vcpu:
        print(f"  CPU: {dir_meta.cpu_in_vcpu} vCPU")
    if dir_meta.run_timestamp:
        print(f"  Timestamp: {dir_meta.run_timestamp}")

    # Parse hardware config
    hw_path = experiment_dir / "hardware_config.json"
    if hw_path.exists():
        hw_config = parse_hardware_config(hw_path)
        if hw_config:
            print(f"\n[Hardware Config] {hw_path.name}")
            # Show RAM with fallback note if needed
            if hw_config.ram_in_mb and hw_config.ram_in_mb > 0:
                print(f"  RAM: {hw_config.ram_in_mb} MB")
            else:
                print(f"  RAM: {dir_meta.ram_in_mb} MB (from directory name, config has 0)")
            if hw_config.cpu_in_vcpu:
                print(f"  CPU: {hw_config.cpu_in_vcpu} vCPU")
            stats['scaling_rules'] = len(hw_config.scaling_rules)
            if hw_config.scaling_rules:
                services = set(r.service_name for r in hw_config.scaling_rules)
                print(f"  Scaling Rules: {len(hw_config.scaling_rules)} rules for {len(services)} service(s)")
                for svc in sorted(services):
                    svc_rules = [r for r in hw_config.scaling_rules if r.service_name == svc]
                    rule_types = ', '.join(r.rule_type for r in svc_rules)
                    min_cap = svc_rules[0].min_capacity
                    max_cap = svc_rules[0].max_capacity
                    print(f"    {svc}: {rule_types} (min={min_cap}, max={max_cap})")
    else:
        print(f"\n[Hardware Config] NOT FOUND")

    # Parse benchmark config
    bm_path = experiment_dir / "benchmark_configuration.json"
    if bm_path.exists():
        bm_config = parse_benchmark_config(bm_path)
        if bm_config:
            print(f"\n[Benchmark Config] {bm_path.name}")
            print(f"  HTTP Timeout: {bm_config.http_timeout_seconds}s")
    else:
        # Show default value that will be used
        default_timeout = 10 if dir_meta.architecture == 'faas' else 30
        print(f"\n[Benchmark Config] NOT FOUND (will use default: {default_timeout}s)")

    # Parse start time
    st_path = experiment_dir / "experiment_start_time.txt"
    if st_path.exists():
        start_time = parse_experiment_start_time(st_path)
        if start_time:
            print(f"\n[Start Time] {st_path.name}")
            print(f"  Timestamp MS: {start_time.timestamp_ms}")
            if start_time.iso_string:
                print(f"  ISO: {start_time.iso_string}")
    else:
        print(f"\n[Start Time] NOT FOUND")

    # Parse error description
    err_path = experiment_dir / "error_description.md"
    if err_path.exists():
        error_desc = parse_error_description(err_path)
        print(f"\n[Error Description] {err_path.name}")
        if error_desc:
            print(f"  Content: {error_desc[:100]}..." if len(error_desc) > 100 else f"  Content: {error_desc}")
        else:
            print(f"  Content: (empty)")
    else:
        print(f"\n[Error Description] NOT FOUND")

    # Parse pricing
    pricing_path = experiment_dir / "pricing" / "pricing.json"
    if pricing_path.exists():
        pricing = parse_pricing(pricing_path)
        if pricing:
            print(f"\n[Pricing] {pricing_path.name}")
            print(f"  Region: {pricing.meta.region}")
            if pricing.meta.duration_minutes:
                print(f"  Duration: {pricing.meta.duration_minutes:.1f} min")
            if pricing.lambda_pricing:
                print(f"  Lambda Total Cost: ${pricing.lambda_pricing.total_cost}")
                print(f"  Lambda Invocations: {pricing.lambda_pricing.total_invocations:,}")
            if pricing.fargate:
                print(f"  Fargate Total Cost: ${pricing.fargate.total_cost}")
            if pricing.alb:
                print(f"  ALB Total Cost: ${pricing.alb.total_cost}")
            if pricing.redis:
                print(f"  Redis Total Cost: ${pricing.redis.total_cost}")
            if pricing.cognito:
                print(f"  Cognito Cost: ${pricing.cognito.cost}")
            stats['pricing_components'] = len(pricing.lambda_functions) + len(pricing.fargate_services)
            print(f"  Pricing Components: {stats['pricing_components']}")
    else:
        print(f"\n[Pricing] NOT FOUND")

    # Parse ALB metrics
    alb_path = experiment_dir / "cloudwatch" / "alb_metrics.csv"
    if alb_path.exists():
        alb_metrics = parse_alb_metrics(alb_path)
        stats['metrics_alb'] = len(alb_metrics)
        print(f"\n[ALB Metrics] {alb_path.name}")
        print(f"  Rows: {len(alb_metrics):,}")
    else:
        print(f"\n[ALB Metrics] NOT FOUND")

    # Parse ECS metrics
    ecs_path = experiment_dir / "cloudwatch" / "ecs_metrics.csv"
    if ecs_path.exists():
        ecs_metrics = parse_ecs_metrics(ecs_path)
        stats['metrics_ecs'] = len(ecs_metrics)
        print(f"\n[ECS Metrics] {ecs_path.name}")
        print(f"  Rows: {len(ecs_metrics):,}")
    else:
        print(f"\n[ECS Metrics] NOT FOUND")

    # Parse artillery log (streaming)
    artillery_path = experiment_dir / "logs" / "artillery.log"
    if artillery_path.exists():
        file_size = artillery_path.stat().st_size / (1024 * 1024)
        print(f"\n[Artillery Log] {artillery_path.name} ({file_size:.1f} MB)")
        print(f"  Parsing (streaming)...", end="", flush=True)

        for result, requests in parse_artillery_log(artillery_path, batch_size=50000):
            if result.phases:
                stats['phases'] = len(result.phases)
            stats['requests'] += len(requests)

        print(f" done")
        print(f"  Phases: {stats['phases']}")
        print(f"  Requests: {stats['requests']:,}")
    else:
        print(f"\n[Artillery Log] NOT FOUND")

    # Parse AWS log (streaming)
    aws_path = experiment_dir / "logs" / "aws.log"
    if aws_path.exists():
        file_size = aws_path.stat().st_size / (1024 * 1024)
        print(f"\n[AWS Log] {aws_path.name} ({file_size:.1f} MB)")
        print(f"  Parsing (streaming)...", end="", flush=True)

        for batch in parse_aws_log(aws_path, batch_size=50000):
            stats['lambda_executions'] += len(batch.lambda_executions)
            stats['handler_events'] += len(batch.handler_events)
            stats['container_starts'] += len(batch.container_starts)
            stats['rpc_calls'] += len(batch.rpc_calls)

        print(f" done")
        print(f"  Lambda Executions: {stats['lambda_executions']:,}")
        print(f"  Handler Events: {stats['handler_events']:,}")
        print(f"  Container Starts: {stats['container_starts']:,}")
        print(f"  RPC Calls: {stats['rpc_calls']:,}")
    else:
        print(f"\n[AWS Log] NOT FOUND")

    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY - Records that would be inserted:")
    print(f"{'='*60}")
    total = 0
    for table, count in stats.items():
        if count > 0:
            print(f"  {table}: {count:,}")
            total += count
    print(f"  {'─'*40}")
    print(f"  TOTAL: {total:,} records")

    return stats


def cmd_post_process(args):
    """Run post-processing for specific experiment IDs."""
    url = get_database_url()
    print(f"Database: {url.split('@')[-1] if '@' in url else url}")

    engine = create_db_engine(url, echo=args.verbose)

    with Session(engine) as session:
        exp_ids = args.experiment_ids

        print(f"\n=== Post-processing {len(exp_ids)} experiments ===")
        for i, exp_id in enumerate(exp_ids, 1):
            print(f"\n[{i}/{len(exp_ids)}] Post-processing experiment {exp_id}...")
            experiment = session.execute(
                select(Experiment).where(Experiment.id == exp_id)
            ).scalar_one_or_none()

            if not experiment:
                print(f"  Experiment {exp_id} not found, skipping")
                continue

            # Reconstruct phase_starts from the phases table
            phases = session.execute(
                select(Phase).where(Phase.experiment_id == exp_id).order_by(Phase.phase_index)
            ).scalars().all()
            phase_starts = _calculate_phase_starts(phases) if phases else {}

            _run_post_processing(session, exp_id, experiment, phase_starts)
            session.commit()

        print(f"\nPost-processing complete for {len(exp_ids)} experiments")


def cmd_backfill(args):
    """Backfill NULL columns using derived data."""
    url = get_database_url()
    print(f"Database: {url.split('@')[-1] if '@' in url else url}")

    engine = create_db_engine(url, echo=args.verbose)

    with Session(engine) as session:
        backfill_nulls(session)


def cmd_reset(args):
    """Reset hidden folders by removing the '.' prefix from folder names."""
    target_dir = Path(args.directory).resolve()

    if not target_dir.is_dir():
        print(f"Error: {target_dir} is not a directory")
        return

    # Find all hidden directories (starting with '.')
    hidden_dirs = sorted([
        d for d in target_dir.iterdir()
        if d.is_dir() and d.name.startswith('.') and not d.name.startswith('..')
    ])

    if not hidden_dirs:
        print(f"No hidden folders found in {target_dir}")
        return

    print(f"Found {len(hidden_dirs)} hidden folder(s) in {target_dir}:\n")
    for d in hidden_dirs:
        new_name = d.name[1:]  # Remove leading '.'
        print(f"  {d.name} -> {new_name}")

    if not args.yes:
        confirm = input(f"\nRename {len(hidden_dirs)} folder(s)? [y/N] ")
        if confirm.lower() != 'y':
            print("Cancelled")
            return

    print()
    renamed = 0
    for d in hidden_dirs:
        new_name = d.name[1:]  # Remove leading '.'
        new_path = d.parent / new_name

        if new_path.exists():
            print(f"  ⚠️  Skipped {d.name}: {new_name} already exists")
            continue

        try:
            d.rename(new_path)
            print(f"  ✓ Renamed {d.name} -> {new_name}")
            renamed += 1
        except Exception as e:
            print(f"  ✗ Failed to rename {d.name}: {e}")

    print(f"\nRenamed {renamed}/{len(hidden_dirs)} folder(s)")


def cmd_dry_run(args):
    """Dry run: parse a single experiment without database."""
    exp_dir = Path(args.directory).resolve()
    dry_run_experiment(exp_dir)


def cmd_dry_run_all(args):
    """Dry run: parse all experiments without database."""
    results_dir = Path(args.results_dir).resolve()

    if not results_dir.is_dir():
        print(f"Error: {results_dir} is not a directory")
        return

    # Find all experiment directories
    exp_dirs = sorted([
        d for d in results_dir.iterdir()
        if d.is_dir() and not d.name.startswith('.')
    ])

    print(f"Found {len(exp_dirs)} experiment directories")

    all_stats = {}
    totals = {
        'scaling_rules': 0,
        'phases': 0,
        'requests': 0,
        'lambda_executions': 0,
        'handler_events': 0,
        'container_starts': 0,
        'rpc_calls': 0,
        'pricing_components': 0,
        'metrics_alb': 0,
        'metrics_ecs': 0,
    }

    for i, exp_dir in enumerate(exp_dirs, 1):
        print(f"\n[{i}/{len(exp_dirs)}]", end="")
        stats = dry_run_experiment(exp_dir)
        all_stats[exp_dir.name] = stats

        for key, value in stats.items():
            totals[key] += value

    # Grand total
    print(f"\n\n{'#'*60}")
    print(f"GRAND TOTAL - All {len(exp_dirs)} experiments:")
    print(f"{'#'*60}")
    grand_total = 0
    for table, count in totals.items():
        if count > 0:
            print(f"  {table}: {count:,}")
            grand_total += count
    print(f"  {'─'*40}")
    print(f"  GRAND TOTAL: {grand_total:,} records")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="BeFaaS Benchmark Database Import Tool (PostgreSQL only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Database configuration is read from .env file or environment variables.\n"
               "Required: DB_TYPE=postgresql, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose SQL logging",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize database schema")
    init_parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop existing tables before creating",
    )

    # import command
    import_parser = subparsers.add_parser("import", help="Import a single experiment")
    import_parser.add_argument(
        "directory",
        help="Path to experiment directory",
    )
    import_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Reimport existing experiment",
    )
    import_parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Batch size for large table inserts (default: 10000)",
    )

    # import-all command
    import_all_parser = subparsers.add_parser("import-all", help="Import all experiments from directory")
    import_all_parser.add_argument(
        "results_dir",
        help="Path to results directory containing experiment subdirectories",
    )
    import_all_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Reimport existing experiments",
    )
    import_all_parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Batch size for large table inserts (default: 10000)",
    )

    # list command
    subparsers.add_parser("list", help="List all experiments")

    # delete command
    delete_parser = subparsers.add_parser("delete", help="Delete an experiment")
    delete_parser.add_argument(
        "experiment_id",
        type=int,
        help="Experiment ID to delete",
    )
    delete_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    # stats command
    subparsers.add_parser("stats", help="Show database statistics")

    # query command
    query_parser = subparsers.add_parser("query", help="Run a SQL query")
    query_parser.add_argument(
        "sql",
        help="SQL query to execute",
    )

    # schema-info command (no database required)
    subparsers.add_parser(
        "schema-info",
        help="Print schema documentation for AI/human reference"
    )

    # post-process command
    pp_parser = subparsers.add_parser(
        "post-process",
        help="Run post-processing for specific experiment IDs (resume after crash)"
    )
    pp_parser.add_argument(
        "experiment_ids",
        type=int,
        nargs="+",
        help="Experiment IDs to post-process",
    )

    # backfill command
    subparsers.add_parser(
        "backfill",
        help="Backfill NULL columns (auth_type, phase_index, phase_name, phase_relative_time_ms) using derived data"
    )

    # dry-run command (no database required)
    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Test parsing a single experiment without database"
    )
    dry_run_parser.add_argument(
        "directory",
        help="Path to experiment directory",
    )

    # dry-run-all command (no database required)
    dry_run_all_parser = subparsers.add_parser(
        "dry-run-all",
        help="Test parsing all experiments without database"
    )
    dry_run_all_parser.add_argument(
        "results_dir",
        help="Path to results directory containing experiment subdirectories",
    )

    # reset command (no database required)
    reset_parser = subparsers.add_parser(
        "reset",
        help="Unhide folders by removing '.' prefix from folder names"
    )
    reset_parser.add_argument(
        "directory",
        help="Path to directory containing hidden folders to reset",
    )
    reset_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch to command handler
    commands = {
        "init": cmd_init,
        "import": cmd_import,
        "import-all": cmd_import_all,
        "list": cmd_list,
        "delete": cmd_delete,
        "stats": cmd_stats,
        "query": cmd_query,
        "schema-info": cmd_schema_info,
        "dry-run": cmd_dry_run,
        "dry-run-all": cmd_dry_run_all,
        "post-process": cmd_post_process,
        "backfill": cmd_backfill,
        "reset": cmd_reset,
    }

    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()