#!/usr/bin/env python3
"""
Migration: Backfill service_cpu_info from S3 hardware_config.json files

Adds a service_cpu_info JSONB column to the experiments table and populates it
by fetching hardware_config.json from S3 for each experiment.

S3 locations checked (in order):
  s3://jakobs-benchmark-results/imported/<name>/hardware_config.json
  s3://jakobs-benchmark-results/webservice/<name>/hardware_config.json

Usage:
    AWS_PROFILE=playground python -m db_import.migrations.migrate_cpu_info [--dry-run]
"""

import json
import sys
from sqlalchemy import create_engine, text

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("ERROR: boto3 is required. Install with: pip install boto3")
    sys.exit(1)

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0] + "/scripts")
from db_import.config import get_database_url

S3_BUCKET = "jakobs-benchmark-results"
S3_PREFIXES = ["imported", "webservice"]


def fetch_hardware_config_from_s3(s3_client, experiment_name: str) -> dict | None:
    """Try both S3 prefixes and return parsed hardware_config.json, or None if not found."""
    for prefix in S3_PREFIXES:
        key = f"{prefix}/{experiment_name}/hardware_config.json"
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
            content = response["Body"].read().decode("utf-8")
            return json.loads(content)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                continue
            print(f"  [WARN] S3 error for {key}: {e}")
            continue
        except json.JSONDecodeError as e:
            print(f"  [WARN] Invalid JSON in {key}: {e}")
            return None
    return None


def migrate(dry_run=False):
    engine = create_engine(get_database_url())
    s3_client = boto3.session.Session(profile_name="playground").client("s3")

    with engine.begin() as conn:
        # Step 1: Add column if missing
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'experiments' AND column_name = 'service_cpu_info'
        """))
        if result.fetchone():
            print("Column service_cpu_info already exists, skipping ALTER TABLE.")
        else:
            print("Adding service_cpu_info JSONB column to experiments...")
            conn.execute(text("""
                ALTER TABLE experiments
                    ADD COLUMN service_cpu_info JSONB
            """))
            conn.execute(text("""
                COMMENT ON COLUMN experiments.service_cpu_info IS
                'CPU info of the service host from /proc/cpuinfo: model_name, vendor_id, cpu_MHz, cache_size, cpu_cores, bogomips'
            """))
            print("Column added.")

        # Step 2: Fetch experiments that still have no cpu_info
        result = conn.execute(text("""
            SELECT id, name FROM experiments
            WHERE service_cpu_info IS NULL
            ORDER BY id
        """))
        experiments = result.fetchall()
        print(f"\nFound {len(experiments)} experiments without service_cpu_info.\n")

        updated = 0
        skipped_no_file = 0
        skipped_no_field = 0

        for exp_id, exp_name in experiments:
            hw = fetch_hardware_config_from_s3(s3_client, exp_name)

            if hw is None:
                print(f"  [{exp_id}] {exp_name}: hardware_config.json not found in S3 — skipping")
                skipped_no_file += 1
                continue

            cpu_info = hw.get("service_cpu_info")
            if not cpu_info:
                print(f"  [{exp_id}] {exp_name}: no service_cpu_info field — skipping")
                skipped_no_field += 1
                continue

            print(f"  [{exp_id}] {exp_name}: {cpu_info.get('model_name', 'unknown CPU')}")
            if not dry_run:
                conn.execute(text("""
                    UPDATE experiments
                    SET service_cpu_info = :cpu_info
                    WHERE id = :exp_id
                """), {
                    "cpu_info": json.dumps(cpu_info),
                    "exp_id": exp_id,
                })
            updated += 1

        print(f"\nSummary:")
        print(f"  Updated:              {updated}")
        print(f"  Skipped (no file):    {skipped_no_file}")
        print(f"  Skipped (no field):   {skipped_no_field}")

        if dry_run:
            print("\n[DRY RUN] Rolling back all changes.")
            conn.rollback()
        else:
            print("\nMigration complete.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN MODE ===\n")
    migrate(dry_run=dry_run)