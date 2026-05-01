#!/usr/bin/env python3
"""Generate interaction_arch_auth.pdf for fig:interaction-arch-auth.

2-panel grouped bar chart (P50 | P99) showing Architecture × Auth Strategy
interaction at comparable hardware (FaaS/512, MS/L, Mono/L).
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


def load_experiment_p99(experiment_id, arch):
    eps = ('/frontend/setUser', '/frontend/addCartItem', '/frontend/cart', '/frontend/checkout') \
        if arch == 'faas' else ('/setUser', '/addCartItem', '/cart', '/checkout')
    eps_sql = ','.join(f"'{e}'" for e in eps)
    df = query_df(f"""
        SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99,
               percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p50,
               COUNT(*) FILTER (WHERE NOT r.is_error) AS n
        FROM requests r
        WHERE r.experiment_id = {experiment_id}
          AND r.phase_name = 'Baseline' AND r.endpoint IN ({eps_sql})
    """)
    if df.empty or df.iloc[0]['n'] < 50:
        return None, None
    return float(df.iloc[0]['p50']), float(df.iloc[0]['p99'])


def main():
    configs = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu
        FROM experiments e
        WHERE {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        ORDER BY e.architecture, e.ram_in_mb, e.auth_strategy
    """)

    rows = []
    for _, exp in configs.iterrows():
        auth_label = AUTH_SHORT.get(exp['auth_strategy'], exp['auth_strategy'])
        p50, p99 = load_experiment_p99(exp['id'], exp['architecture'])
        if p99 is None:
            continue
        rows.append({
            'architecture': exp['architecture'],
            'auth_label': auth_label,
            'ram_in_mb': exp['ram_in_mb'],
            'cpu': exp['cpu'],
            'p50': p50, 'p99': p99,
        })

    data = pd.DataFrame(rows)
    comparable = data[
        ((data['architecture'] == 'faas') & (data['ram_in_mb'] == 512)) |
        ((data['architecture'] == 'microservices') & (data['cpu'] == 1.0)) |
        ((data['architecture'] == 'monolith') & (data['cpu'] == 1.0))
    ].copy()

    if comparable.empty:
        print('No comparable data'); return

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=False)
    arch_order = ['faas', 'microservices', 'monolith']
    arch_labels = ['FaaS/512 MB', 'MS/L', 'Mono/L']
    auth_order = [a for a in ['None', 'Cognito', 'Manual', 'Edge'] if a in AUTH_COLORS]
    n_auth = len(auth_order)
    bar_width = 0.8 / n_auth

    for ax, metric, metric_label in [(axes[0], 'p50', 'P50'), (axes[1], 'p99', 'P99')]:
        for i, al in enumerate(auth_order):
            ad = comparable[comparable['auth_label'] == al]
            if ad.empty:
                continue
            heights, positions = [], []
            for j, arch in enumerate(arch_order):
                aa = ad[ad['architecture'] == arch]
                if aa.empty:
                    continue
                heights.append(aa[metric].mean())
                positions.append(j + (i - (n_auth - 1) / 2) * bar_width)
            ax.bar(positions, heights, width=bar_width,
                   color=AUTH_COLORS[al], label=al, edgecolor='white', linewidth=0.5)

        ax.set_xticks(range(len(arch_order)))
        ax.set_xticklabels(arch_labels)
        ax.set_ylabel(f'{metric_label}-Latenz (ms)')
        ax.set_title(f'{metric_label} — Architektur × Strategie')
        ax.grid(axis='y', alpha=0.3)
        if metric == 'p99':
            ax.set_yscale('log')
            ax.set_ylabel(f'{metric_label}-Latenz (ms, log.)')

    axes[0].legend(title='Strategie', loc='upper left', fontsize=9)
    plt.tight_layout()
    path = f"{PLOT_DIR}/interaction_arch_auth.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
