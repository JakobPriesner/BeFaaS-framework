#!/usr/bin/env python3
"""Generate interaction_auth_hw.pdf for fig:interaction-auth-hw.

1×3 small-multiple: Auth Strategy × HW Tier within each architecture.
Grouped bars (log P99) reveal non-uniform scaling = interaction effect.
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


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    return {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(float(cpu), f"{cpu}vCPU")


def load_experiment_p99(experiment_id, arch):
    eps = ('/frontend/setUser', '/frontend/addCartItem', '/frontend/cart', '/frontend/checkout') \
        if arch == 'faas' else ('/setUser', '/addCartItem', '/cart', '/checkout')
    eps_sql = ','.join(f"'{e}'" for e in eps)
    df = query_df(f"""
        SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99,
               COUNT(*) FILTER (WHERE NOT r.is_error) AS n
        FROM requests r
        WHERE r.experiment_id = {experiment_id}
          AND r.phase_name = 'Baseline' AND r.endpoint IN ({eps_sql})
    """)
    if df.empty or df.iloc[0]['n'] < 50:
        return None
    return float(df.iloc[0]['p99'])


def main():
    configs = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu
        FROM experiments e
        WHERE {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
    """)

    rows = []
    for _, exp in configs.iterrows():
        p99 = load_experiment_p99(exp['id'], exp['architecture'])
        if p99 is None:
            continue
        rows.append({
            'architecture': exp['architecture'],
            'auth_label': AUTH_SHORT.get(exp['auth_strategy'], exp['auth_strategy']),
            'hw': hw_label(exp['architecture'], exp['ram_in_mb'], exp['cpu']),
            'p99': p99,
        })

    data = pd.DataFrame(rows)
    if data.empty:
        print('No data'); return

    arch_hw_orders = {
        'faas': ['256MB', '512MB', '1024MB', '1769MB'],
        'microservices': ['S', 'M', 'L', 'XL'],
        'monolith': ['S', 'M', 'L', 'XL'],
    }
    arch_titles = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}
    auth_order = [a for a in ['None', 'Cognito', 'Manual', 'Edge'] if a in AUTH_COLORS]
    n_auth = len(auth_order)
    bar_width = 0.8 / n_auth

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = data[data['architecture'] == arch]
        hw_order = arch_hw_orders[arch]

        for i, al in enumerate(auth_order):
            ad = arch_data[arch_data['auth_label'] == al]
            if ad.empty:
                continue
            heights, positions = [], []
            for j, hw in enumerate(hw_order):
                ha = ad[ad['hw'] == hw]
                if ha.empty:
                    continue
                heights.append(ha['p99'].mean())
                positions.append(j + (i - (n_auth - 1) / 2) * bar_width)
            ax.bar(positions, heights, width=bar_width,
                   color=AUTH_COLORS[al], label=al, edgecolor='white', linewidth=0.5)

        ax.set_xticks(range(len(hw_order)))
        ax.set_xticklabels(hw_order)
        ax.set_xlabel('Hardware-Tier')
        ax.set_title(arch_titles[arch])
        ax.grid(axis='y', alpha=0.3)
        ax.set_yscale('log')

    axes[0].set_ylabel('P99-Latenz (ms, log.)')
    axes[0].legend(title='Strategie', loc='upper left', fontsize=8)
    plt.tight_layout()
    path = f"{PLOT_DIR}/interaction_auth_hw.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
