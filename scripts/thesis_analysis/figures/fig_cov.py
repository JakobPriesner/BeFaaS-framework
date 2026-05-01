#!/usr/bin/env python3
"""Generate latency_cov_comparison.pdf for fig:cov.

2×3 grid — Row 1: CoV (%) by phase per architecture,
Row 2: Tail ratio (P99/P50) by phase per architecture.
Auth strategies: None, Cognito, Edge. Excludes argon2id.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
}


def main():
    df = query_df(f"""
        SELECT
            e.id, e.architecture, e.auth_strategy,
            r.phase_name,
            AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_lat,
            STDDEV(r.latency_ms) FILTER (WHERE NOT r.is_error) AS std_lat,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.phase_name IS NOT NULL
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.id, e.architecture, e.auth_strategy, r.phase_name
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 200
    """)
    if df.empty:
        print('No data'); return

    for col in ['mean_lat', 'std_lat', 'p50', 'p99']:
        df[col] = df[col].astype(float)

    df['cov'] = (df['std_lat'] / df['mean_lat'] * 100).where(df['mean_lat'] > 0, 0)
    df['tail_ratio'] = (df['p99'] / df['p50']).where(df['p50'] > 0, 0)

    cov_avg = df.groupby(['architecture', 'auth_strategy', 'phase_name']).agg(
        cov_mean=('cov', 'mean'),
        tail_ratio_mean=('tail_ratio', 'mean'),
    ).reset_index()

    phase_order = ['Baseline', 'Morning rush', 'Stabilization',
                   'Flash Crowd', 'Step Down', 'Cool-down']
    auth_order = ['none', 'service-integrated', 'edge']

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    for i, arch in enumerate(['faas', 'microservices', 'monolith']):
        ax = axes[0][i]
        arch_data = cov_avg[cov_avg['architecture'] == arch]
        x = np.arange(len(phase_order))
        width = 0.25

        for j, auth in enumerate(auth_order):
            auth_data = arch_data[arch_data['auth_strategy'] == auth]
            vals = []
            for phase in phase_order:
                match = auth_data[auth_data['phase_name'] == phase]
                vals.append(match.iloc[0]['cov_mean'] if not match.empty else 0)
            offset = (j - 1) * width
            ax.bar(x + offset, vals, width, label=AUTH_SHORT.get(auth, auth), alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels([p[:8] for p in phase_order], rotation=30, ha='right', fontsize=8)
        ax.set_ylabel('CoV (%)')
        ax.set_title(f'{arch} — Latency CoV', fontweight='bold')
        ax.legend(fontsize=7)
        ax.grid(axis='y', alpha=0.3)

    for i, arch in enumerate(['faas', 'microservices', 'monolith']):
        ax = axes[1][i]
        arch_data = cov_avg[cov_avg['architecture'] == arch]
        x = np.arange(len(phase_order))
        width = 0.25

        for j, auth in enumerate(auth_order):
            auth_data = arch_data[arch_data['auth_strategy'] == auth]
            vals = []
            for phase in phase_order:
                match = auth_data[auth_data['phase_name'] == phase]
                vals.append(match.iloc[0]['tail_ratio_mean'] if not match.empty else 0)
            offset = (j - 1) * width
            ax.bar(x + offset, vals, width, label=AUTH_SHORT.get(auth, auth), alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels([p[:8] for p in phase_order], rotation=30, ha='right', fontsize=8)
        ax.set_ylabel('P99/P50 Ratio')
        ax.set_title(f'{arch} — Tail Latency Ratio', fontweight='bold')
        ax.legend(fontsize=7)
        ax.grid(axis='y', alpha=0.3)
        ax.axhline(y=5, color='red', linestyle='--', alpha=0.3)

    fig.suptitle('Latency Predictability: CoV and Tail Ratio by Architecture\n'
                 '(excluding argon2id)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/latency_cov_comparison.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
