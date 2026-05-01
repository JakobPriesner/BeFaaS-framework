#!/usr/bin/env python3
"""Generate cold_start_per_function.pdf for fig:cold-start-per-function.

2-panel horizontal bar chart: (1) cold start count per function,
(2) avg init duration per function. Representative experiment
(512MB, none auth).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL


def main():
    rep_exp = query_df(f"""
        SELECT e.id
        FROM experiments e
        JOIN lambda_executions l ON l.experiment_id = e.id
        WHERE e.architecture = 'faas' AND {EXCLUDE_SQL}
          AND e.ram_in_mb = 512 AND e.auth_strategy = 'none'
        GROUP BY e.id
        HAVING COUNT(*) > 1000
        ORDER BY e.id
        LIMIT 1
    """)
    if rep_exp.empty:
        rep_exp = query_df(f"""
            SELECT e.id
            FROM experiments e
            JOIN lambda_executions l ON l.experiment_id = e.id
            WHERE e.architecture = 'faas' AND {EXCLUDE_SQL}
            GROUP BY e.id
            HAVING COUNT(*) > 1000
            ORDER BY e.id
            LIMIT 1
        """)
    if rep_exp.empty:
        print('No data'); return

    exp_id = int(rep_exp.iloc[0]['id'])

    func_data = query_df(f"""
        SELECT
            l.function_name,
            COUNT(CASE WHEN l.is_cold_start THEN 1 END) AS cold_starts,
            AVG(l.init_duration_ms) FILTER (WHERE l.is_cold_start) AS avg_init_ms
        FROM lambda_executions l
        WHERE l.experiment_id = {exp_id}
        GROUP BY l.function_name
        HAVING COUNT(CASE WHEN l.is_cold_start THEN 1 END) > 0
        ORDER BY cold_starts
    """)
    if func_data.empty:
        print('No cold start data'); return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, max(4, len(func_data) * 0.3)))

    ax1.barh(func_data['function_name'], func_data['cold_starts'], color='#e74c3c', alpha=0.7)
    ax1.set_xlabel('Cold Start Count')
    ax1.set_title(f'Cold Starts per Function (Exp {exp_id})')
    ax1.grid(axis='x', alpha=0.3)

    ax2.barh(func_data['function_name'], func_data['avg_init_ms'], color='#3498db', alpha=0.7)
    ax2.set_xlabel('Avg Init Duration (ms)')
    ax2.set_title('Avg Cold Start Init Duration')
    ax2.grid(axis='x', alpha=0.3)

    plt.tight_layout()
    path = f"{PLOT_DIR}/cold_start_per_function.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
