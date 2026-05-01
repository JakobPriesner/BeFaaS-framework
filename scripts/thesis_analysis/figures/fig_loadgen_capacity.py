#!/usr/bin/env python3
"""Generate loadgen_capacity.pdf for fig:loadgen-capacity.

NOTE: The loadgen metrics (EC2 CPU utilization and network bandwidth) are NOT
stored in the PostgreSQL database. The `metrics_loadgen` table does not exist.
This data was originally collected from CloudWatch for the loadgen EC2 instance.

This script is a PLACEHOLDER. To regenerate this figure from data, the loadgen
CloudWatch metrics need to be imported into the database or provided as CSV.

For now, this script verifies the existing PDF exists.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import PLOT_DIR


def main():
    path = os.path.join(PLOT_DIR, 'loadgen_capacity.pdf')
    if os.path.exists(path):
        print(f"EXISTS (external data, not regenerated): {path}")
    else:
        print(f"WARNING: {path} not found. This figure requires loadgen CloudWatch "
              f"metrics that are not in the database. Import metrics_loadgen data or "
              f"provide a CSV with columns: timestamp, cpu_percent, network_out_mbps")


if __name__ == '__main__':
    main()
