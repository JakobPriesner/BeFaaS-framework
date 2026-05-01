#!/usr/bin/env python3
"""Generate edge_cognito_crossover_monolith_l.pdf for fig:edge-cognito-crossover.

Single-panel crossover plot for Monolith L: ΔAuth at fine-grained percentiles
(P50–P99 in 5% steps) for Edge vs Cognito. Marks the crossover point where
Edge becomes worse than Cognito.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

ARCH = 'monolith'
RAM = 2048
CPU = 1.0
HW_LABEL = 'Mono L'

PROTECTED = ('/setUser', '/addCartItem', '/cart', '/checkout')
PERCENTILES = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.97, 0.99]

STRATEGY_NAMES = {
    'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual (bcrypt)',
    'edge': 'Edge',
}
COLORS = {
    'service-integrated': '#2196F3',
    'service-integrated-manual': '#F44336',
    'edge': '#4CAF50',
}


def main():
    eps_sql = ','.join(f"'{e}'" for e in PROTECTED)
    pctl_selects = ',\n        '.join(
        f"percentile_cont({p}) WITHIN GROUP (ORDER BY r.latency_ms) "
        f"FILTER (WHERE NOT r.is_error) AS p{int(p*100)}"
        for p in PERCENTILES
    )
    df = query_df(f"""
        SELECT e.id AS experiment_id, e.auth_strategy,
               COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
               {pctl_selects}
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = '{ARCH}'
          AND e.ram_in_mb = {RAM}
          AND e.cpu_in_vcpu = {CPU}
          AND r.phase_name = 'Baseline'
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND r.endpoint IN ({eps_sql})
        GROUP BY e.id, e.auth_strategy
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        ORDER BY e.auth_strategy, e.id
    """)
    if df.empty:
        print('No data'); return

    pct_cols = [f'p{int(p*100)}' for p in PERCENTILES]
    grouped = df.groupby('auth_strategy')[pct_cols].mean()
    if 'none' not in grouped.index:
        print('No none baseline'); return

    none_vals = grouped.loc['none']
    delta_df = pd.DataFrame({
        strat: grouped.loc[strat] - none_vals
        for strat in grouped.index if strat != 'none'
    })

    x_positions = np.array([p * 100 for p in PERCENTILES])
    pct_labels = [f'P{int(p*100)}' for p in PERCENTILES]

    fig, ax = plt.subplots(figsize=(7, 5))
    for strat in delta_df.columns:
        vals = delta_df[strat].values
        name = STRATEGY_NAMES.get(strat, strat)
        color = COLORS.get(strat, '#999999')
        ax.plot(x_positions, vals, 'o-', label=name, color=color,
                linewidth=1.8, markersize=5)

    if 'edge' in delta_df.columns and 'service-integrated' in delta_df.columns:
        edge_vals = delta_df['edge'].values
        cog_vals = delta_df['service-integrated'].values
        diff = edge_vals - cog_vals
        for i in range(len(diff) - 1):
            if diff[i] <= 0 and diff[i+1] > 0:
                frac = -diff[i] / (diff[i+1] - diff[i])
                crossover_pct = PERCENTILES[i] + frac * (PERCENTILES[i+1] - PERCENTILES[i])
                crossover_x = x_positions[i] + frac * (x_positions[i+1] - x_positions[i])
                crossover_y = edge_vals[i] + frac * (edge_vals[i+1] - edge_vals[i])
                ax.axvline(x=crossover_x, color='gray', linestyle='--', alpha=0.7, linewidth=1)
                ax.annotate(f'Crossover: P{int(crossover_pct*100)}',
                            xy=(crossover_x, crossover_y),
                            xytext=(crossover_x + 3, crossover_y - 20),
                            arrowprops=dict(arrowstyle='->', color='gray'),
                            fontsize=8, color='gray')
                break

    ax.set_xticks(x_positions)
    ax.set_xticklabels(pct_labels, rotation=45, fontsize=8)
    ax.set_ylabel('ΔAuth (ms)', fontsize=10)
    ax.set_xlabel('Percentile', fontsize=10)
    ax.set_xlim(47, 102)
    ax.set_title(f'ΔAuth Crossover: Edge vs Cognito — {HW_LABEL}',
                 fontsize=12, fontweight='bold')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color='black', linewidth=0.5)
    plt.tight_layout()
    path = f"{PLOT_DIR}/edge_cognito_crossover_monolith_l.pdf"
    fig.savefig(path, bbox_inches='tight', dpi=300)
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
