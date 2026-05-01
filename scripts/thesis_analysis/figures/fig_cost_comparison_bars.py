#!/usr/bin/env python3
"""Generate cost_comparison_bars.pdf for fig:cost-comparison-bars.

1×3 horizontal bar chart showing cost per 1M successful requests
per architecture, sorted by cost. Excludes argon2id.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, ARCH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
}


def hw_label(row):
    if row['architecture'] == 'faas':
        return f"{row['ram_in_mb']}MB"
    return {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(float(row['cpu']), f"{row['cpu']}v")


def main():
    pricing = query_df(f"""
        SELECT
            e.id, e.architecture, e.auth_strategy,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            COALESCE(p.lambda_total_cost, 0) +
            COALESCE(p.api_gw_cost, 0) +
            COALESCE(p.fargate_total_cost, 0) +
            COALESCE(p.alb_total_cost, 0) +
            COALESCE(p.redis_total_cost, 0) +
            COALESCE(p.cognito_cost, 0) AS total_cost
        FROM experiments e
        JOIN pricing p ON p.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
    """)

    perf = query_df(f"""
        SELECT e.id,
               COUNT(*) FILTER (WHERE NOT r.is_error) AS successful_requests
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.id
        HAVING COUNT(*) > 50000
    """)

    if pricing.empty or perf.empty:
        print('No data'); return

    merged = pricing.merge(perf, on='id', how='inner')
    merged['total_cost'] = merged['total_cost'].astype(float)
    merged['cost_per_1M'] = merged['total_cost'] / merged['successful_requests'] * 1_000_000
    merged['cost_per_1M'] = merged['cost_per_1M'].replace([np.inf, -np.inf], np.nan)
    merged = merged[merged['ram_in_mb'] != 1796]
    merged['hw'] = merged.apply(hw_label, axis=1)
    merged['auth_label'] = merged['auth_strategy'].map(AUTH_SHORT)

    cost_avg = merged.groupby(['architecture', 'auth_label', 'hw']).agg(
        mean_cost_per_1M=('cost_per_1M', 'mean'),
    ).reset_index()

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = cost_avg[cost_avg['architecture'] == arch].sort_values('mean_cost_per_1M')
        if arch_data.empty:
            ax.set_title(f'{arch} (no pricing data)'); continue

        labels = [f"{r['auth_label']}\n{r['hw']}" for _, r in arch_data.iterrows()]
        values = arch_data['mean_cost_per_1M'].values
        colors = [ARCH_COLORS[arch]] * len(values)

        bars = ax.barh(labels, values, color=colors, alpha=0.85)
        ax.set_xlabel('Cost per 1M Requests ($)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.grid(axis='x', alpha=0.3)

        for bar, val in zip(bars, values):
            ax.text(bar.get_width() + max(values) * 0.02, bar.get_y() + bar.get_height() / 2,
                    f'${val:.2f}', va='center', fontsize=8)

    fig.suptitle('Cost per 1M Successful Requests by Configuration\n'
                 '(excluding argon2id)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/cost_comparison_bars.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
