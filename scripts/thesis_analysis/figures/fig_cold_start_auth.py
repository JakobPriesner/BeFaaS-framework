#!/usr/bin/env python3
"""Generate cold_start_auth.pdf for fig:cold-start-auth.

2-panel: (1) Cold start rate (%) by auth strategy vs Lambda memory,
(2) Avg init duration by auth strategy vs Lambda memory.
FaaS only, excludes argon2id.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
}


def main():
    cs_summary = query_df(f"""
        SELECT
            e.auth_strategy,
            e.ram_in_mb,
            COUNT(*) AS total_invocations,
            SUM(CASE WHEN l.is_cold_start THEN 1 ELSE 0 END) AS cold_starts,
            AVG(l.init_duration_ms) FILTER (WHERE l.init_duration_ms > 0) AS avg_init_ms,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY l.init_duration_ms)
                FILTER (WHERE l.init_duration_ms > 0) AS median_init_ms,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY l.init_duration_ms)
                FILTER (WHERE l.init_duration_ms > 0) AS p99_init_ms
        FROM experiments e
        JOIN lambda_executions l ON l.experiment_id = e.id
        WHERE e.architecture = 'faas' AND {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND l.duration_ms > 0 AND l.duration_ms < 30000
        GROUP BY e.auth_strategy, e.ram_in_mb
    """)
    if cs_summary.empty:
        print('No data'); return

    cs_summary['cold_start_pct'] = cs_summary['cold_starts'] / cs_summary['total_invocations'] * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    ax = axes[0]
    for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
        sub = cs_summary[cs_summary['auth_strategy'] == auth].sort_values('ram_in_mb')
        if not sub.empty:
            ax.plot(sub['ram_in_mb'], sub['cold_start_pct'], 'o-',
                    label=AUTH_SHORT.get(auth, auth),
                    color=AUTH_COLORS.get(AUTH_SHORT.get(auth, auth), '#999'), linewidth=2)
    ax.set_xlabel('Lambda Memory (MB)')
    ax.set_ylabel('Cold Start Rate (%)')
    ax.set_title('Cold Start Rate by Auth Strategy', fontweight='bold')
    ax.legend()
    ax.grid(alpha=0.3)

    ax = axes[1]
    for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
        sub = cs_summary[cs_summary['auth_strategy'] == auth].sort_values('ram_in_mb')
        if not sub.empty:
            ax.plot(sub['ram_in_mb'], sub['avg_init_ms'], 'o-',
                    label=AUTH_SHORT.get(auth, auth),
                    color=AUTH_COLORS.get(AUTH_SHORT.get(auth, auth), '#999'), linewidth=2)
    ax.set_xlabel('Lambda Memory (MB)')
    ax.set_ylabel('Avg Init Duration (ms)')
    ax.set_title('Cold Start Init Duration by Auth Strategy', fontweight='bold')
    ax.legend()
    ax.grid(alpha=0.3)

    fig.suptitle('Cold Start × Authentication Interaction (FaaS)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/cold_start_auth.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
