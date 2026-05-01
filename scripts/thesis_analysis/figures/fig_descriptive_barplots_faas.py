#!/usr/bin/env python3
"""Generate descriptive_stats_barplots_baseline_faas.pdf for fig:descriptive-barplots-faas.

Bar chart: mean ± StdDev of auth-only P99 per auth strategy per HW tier.
FaaS architecture, Baseline phase only.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, hw_label_from_row,
                           AUTH_COLORS_DETAILED, HW_TIERS_ALL)

ALPHA = 0.05
ARCH = 'faas'
PRIMARY_AUTH_LABELS = ['None', 'Cognito', 'Manual (bcrypt)', 'Edge']

PROTECTED_ENDPOINTS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)


def query_data():
    eps = ','.join(f"'{e}'" for e in PROTECTED_ENDPOINTS)
    df = query_df(f"""
        SELECT e.id AS experiment_id, e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu_in_vcpu,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL} AND e.architecture = '{ARCH}'
          AND r.phase_name = 'Baseline' AND r.endpoint IN ({eps})
        GROUP BY e.id, e.architecture, e.auth_strategy,
                 e.password_hash_algorithm, e.with_cloudfront,
                 e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)
    df['p99'] = df['p99'].astype(float)
    df['hw'] = df.apply(hw_label_from_row, axis=1)
    df['auth_label'] = df.apply(
        lambda r: auth_label_detailed(
            r['auth_strategy'],
            r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
            bool(r['with_cf']) if r['with_cf'] else False), axis=1)
    return df


def main():
    per_exp = query_data()
    if per_exp.empty:
        print('No FaaS Baseline data')
        return

    hw_labels = [t[2] for t in HW_TIERS_ALL.get(ARCH, [])]
    plot_data = []
    for hw_label in hw_labels:
        mask = (
            (per_exp['hw'] == hw_label) &
            (per_exp['auth_label'].isin(PRIMARY_AUTH_LABELS)) &
            (~per_exp['with_cf'])
        )
        subset = per_exp[mask]
        for auth_label in PRIMARY_AUTH_LABELS:
            vals = subset[subset['auth_label'] == auth_label]['p99'].values
            if len(vals) > 0:
                plot_data.append({
                    'hw': hw_label, 'auth': auth_label,
                    'mean': np.mean(vals),
                    'std': np.std(vals, ddof=1) if len(vals) > 1 else 0.0,
                    'n': len(vals),
                })

    if not plot_data:
        print('No data for barplots')
        return

    pdf = pd.DataFrame(plot_data)
    hws_present = [h for h in hw_labels if h in pdf['hw'].values]
    n_hw = len(hws_present)
    n_auth = len(PRIMARY_AUTH_LABELS)

    fig, ax = plt.subplots(figsize=(10, 7))
    bar_width = 0.8 / n_auth
    x = np.arange(n_hw)

    for i, auth_label in enumerate(PRIMARY_AUTH_LABELS):
        auth_data = pdf[pdf['auth'] == auth_label]
        means, stds, ns = [], [], []
        for hw in hws_present:
            hw_row = auth_data[auth_data['hw'] == hw]
            if len(hw_row) > 0:
                means.append(hw_row['mean'].iloc[0])
                stds.append(hw_row['std'].iloc[0])
                ns.append(int(hw_row['n'].iloc[0]))
            else:
                means.append(0); stds.append(0); ns.append(0)

        color = AUTH_COLORS_DETAILED.get(auth_label, '#999999')
        bars = ax.bar(x + i * bar_width, means, bar_width,
                      yerr=stds, capsize=4, label=auth_label, color=color,
                      edgecolor='white', error_kw={'linewidth': 1.2})
        for j, (bar, n) in enumerate(zip(bars, ns)):
            if n > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + stds[j] + 5,
                        f'n={n}', ha='center', va='bottom', fontsize=8, color='#555')

    ax.set_xticks(x + bar_width * (n_auth - 1) / 2)
    ax.set_xticklabels(hws_present, fontsize=11)
    ax.set_title('FaaS (Lambda): Auth-only P99 (Baseline)', fontsize=13, fontweight='bold')
    ax.set_xlabel('Hardware-Tier', fontsize=12)
    ax.set_ylabel('Auth-only P99 (ms)', fontsize=12)
    ax.legend(fontsize=9, loc='upper right')
    ax.grid(axis='y', alpha=0.3)
    ax.tick_params(labelsize=10)

    plt.tight_layout()
    path = f"{PLOT_DIR}/descriptive_stats_barplots_baseline_faas.pdf"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
