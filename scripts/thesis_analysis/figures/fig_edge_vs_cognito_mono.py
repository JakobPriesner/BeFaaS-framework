#!/usr/bin/env python3
"""Generate edge_vs_cognito_monolith.pdf for fig:edge-vs-cognito-mono.

2×2 grid of grouped bar charts showing absolute P50/P75/P99 latency for
None, Cognito, and Edge auth on Monolith hardware tiers (S/M/L/XL).
Demonstrates that at k=1 call depth, Edge is strictly worse than Cognito.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

PROTECTED = ('/setUser', '/addCartItem', '/cart', '/checkout')
HW_CONFIGS = [
    (512, 0.25, 'Mono S'), (1024, 0.5, 'Mono M'),
    (2048, 1.0, 'Mono L'), (8192, 4.0, 'Mono XL'),
]
AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
}
PERCENTILES = [0.50, 0.75, 0.90, 0.95, 0.99]
PCTL_LABELS = ['P50', 'P75', 'P90', 'P95', 'P99']
PCTL_COLS_TO_PLOT = ['P50', 'P75', 'P99']
AUTH_TO_PLOT = ['none', 'service-integrated', 'edge']


def compute_percentiles(ram, cpu):
    eps_sql = ','.join(f"'{e}'" for e in PROTECTED)
    pctl_selects = ',\n            '.join(
        f"percentile_cont({p}) WITHIN GROUP (ORDER BY r.latency_ms) "
        f"FILTER (WHERE NOT r.is_error) AS p{int(p*100)}"
        for p in PERCENTILES
    )
    return query_df(f"""
        SELECT e.auth_strategy,
               COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
               {pctl_selects}
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = 'monolith'
          AND e.ram_in_mb = {ram}
          AND e.cpu_in_vcpu = {cpu}
          AND r.phase_name = 'Baseline'
          AND NOT r.is_error
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND r.endpoint IN ({eps_sql})
        GROUP BY e.auth_strategy
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)


def main():
    all_rows = []
    for ram, cpu, hw_label in HW_CONFIGS:
        df = compute_percentiles(ram, cpu)
        if df.empty:
            continue
        for col in ['p50', 'p75', 'p90', 'p95', 'p99']:
            df[col] = df[col].astype(float)
        for _, row in df.iterrows():
            r = {'config': hw_label, 'auth_strategy': row['auth_strategy'],
                 'auth_label': AUTH_SHORT.get(row['auth_strategy'], row['auth_strategy'])}
            for p, pl in zip(['p50', 'p75', 'p90', 'p95', 'p99'], PCTL_LABELS):
                r[pl] = round(float(row[p]), 1)
            all_rows.append(r)

    result_df = pd.DataFrame(all_rows)
    if result_df.empty:
        print('No data'); return

    n_hw = len(HW_CONFIGS)
    ncols = (n_hw + 1) // 2
    nrows = 2
    fig, axes_flat = plt.subplots(nrows, ncols, figsize=(6 * ncols, 6 * nrows), sharey=True)
    axes_list = axes_flat.flatten()

    for idx, (ram, cpu, hw_label) in enumerate(HW_CONFIGS):
        ax = axes_list[idx]
        config_data = result_df[result_df['config'] == hw_label]
        if config_data.empty:
            ax.set_title(f'{hw_label}\n(no data)', fontsize=11)
            continue

        x = np.arange(len(PCTL_COLS_TO_PLOT))
        width = 0.25

        for i, auth in enumerate(AUTH_TO_PLOT):
            row = config_data[config_data['auth_strategy'] == auth]
            if row.empty:
                continue
            row = row.iloc[0]
            vals = [row[p] for p in PCTL_COLS_TO_PLOT]
            label = AUTH_SHORT.get(auth, auth)
            color = AUTH_COLORS.get(label, '#999999')
            offset = (i - len(AUTH_TO_PLOT) / 2 + 0.5) * width
            bars = ax.bar(x + offset, vals, width, label=label, color=color, alpha=0.85)
            for bar, val in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                        f'{val:.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

        ax.set_xticks(x)
        ax.set_xticklabels(PCTL_COLS_TO_PLOT, fontsize=11)
        ax.set_ylabel('Latency (ms)', fontsize=11)
        ax.set_title(f'{hw_label} (k=1)', fontweight='bold', fontsize=12, color='#D32F2F')
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.3)
        ax.tick_params(labelsize=10)

    for idx in range(len(HW_CONFIGS), len(axes_list)):
        axes_list[idx].set_visible(False)

    fig.suptitle('Monolith: Edge vs Cognito — Auth-Only Latency by Call Depth\n'
                 '(Baseline phase, excl. argon2id)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/edge_vs_cognito_monolith.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
