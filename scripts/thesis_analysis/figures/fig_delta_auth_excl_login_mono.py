#!/usr/bin/env python3
"""Generate delta_auth_excl_login_monolith.pdf for fig:delta-auth-excl-login-mono.

Monolith: ΔAuth P99 with login vs excluding login (setUser).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

ARCH = 'monolith'
EPS_WITH = ('/setUser', '/addCartItem', '/cart', '/checkout')
EPS_WITHOUT = ('/addCartItem', '/cart', '/checkout')

HW_CONFIGS = [
    (512, 0.25, 'Mono S'), (1024, 0.5, 'Mono M'),
    (2048, 1.0, 'Mono L'), (8192, 4.0, 'Mono XL'),
]


def compute_percentiles(ram, cpu, endpoints):
    eps_sql = ','.join(f"'{e}'" for e in endpoints)
    return query_df(f"""
        SELECT e.id AS experiment_id, e.auth_strategy,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL} AND e.architecture = '{ARCH}'
          AND e.ram_in_mb = {ram} AND e.cpu_in_vcpu = {cpu}
          AND r.phase_name = 'Baseline'
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND r.endpoint IN ({eps_sql})
        GROUP BY e.id, e.auth_strategy
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 30
    """)


def main():
    auth_strategies = ['Cognito', 'Manual', 'Edge']
    rows = []
    for ram, cpu, hw_label in HW_CONFIGS:
        df_with = compute_percentiles(ram, cpu, EPS_WITH)
        df_without = compute_percentiles(ram, cpu, EPS_WITHOUT)
        if df_with.empty or df_without.empty:
            continue
        df_with['p99'] = df_with['p99'].astype(float)
        df_without['p99'] = df_without['p99'].astype(float)
        for auth_db, auth_label in [('service-integrated', 'Cognito'),
                                     ('service-integrated-manual', 'Manual'),
                                     ('edge', 'Edge')]:
            with_none = df_with[df_with['auth_strategy'] == 'none']
            with_auth = df_with[df_with['auth_strategy'] == auth_db]
            wo_none = df_without[df_without['auth_strategy'] == 'none']
            wo_auth = df_without[df_without['auth_strategy'] == auth_db]
            if with_none.empty or with_auth.empty or wo_none.empty or wo_auth.empty:
                continue
            rows.append({
                'hw_label': hw_label, 'auth_label': auth_label,
                'delta_p99_with': with_auth['p99'].mean() - with_none['p99'].mean(),
                'delta_p99_excl': wo_auth['p99'].mean() - wo_none['p99'].mean(),
            })

    if not rows:
        print('No Mono data')
        return

    result = pd.DataFrame(rows)
    n_hw = len(HW_CONFIGS)
    fig, axes = plt.subplots(1, n_hw, figsize=(5 * n_hw, 6), sharey=False)
    if n_hw == 1:
        axes = [axes]

    for ax, (ram, cpu, hw_label) in zip(axes, HW_CONFIGS):
        ad = result[result['hw_label'] == hw_label]
        if ad.empty:
            ax.set_title(f'{hw_label}\n(no data)', fontsize=10)
            continue
        auths_present = [a for a in auth_strategies if a in ad['auth_label'].values]
        if not auths_present:
            continue
        x = np.arange(len(auths_present))
        width = 0.35
        vals_with, vals_excl, colors = [], [], []
        for al in auths_present:
            row = ad[ad['auth_label'] == al].iloc[0]
            vals_with.append(row['delta_p99_with'])
            vals_excl.append(row['delta_p99_excl'])
            colors.append(AUTH_COLORS.get(al, '#999999'))
        bars1 = ax.bar(x - width / 2, vals_with, width, label='With login',
                       color=colors, alpha=0.85, edgecolor='black', linewidth=0.5)
        bars2 = ax.bar(x + width / 2, vals_excl, width, label='Excl. login',
                       color=colors, alpha=0.45, edgecolor='black', linewidth=0.5, hatch='///')
        for bar, val in zip(bars1, vals_with):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                    f'{val:+.0f}', ha='center', va='bottom', fontsize=7, fontweight='bold')
        for bar, val in zip(bars2, vals_excl):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                    f'{val:+.0f}', ha='center', va='bottom', fontsize=7, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(auths_present, fontsize=9)
        ax.set_ylabel('ΔAuth P99 (ms)', fontsize=9)
        ax.set_title(hw_label, fontsize=10, fontweight='bold')
        ax.legend(fontsize=7)
        ax.grid(axis='y', alpha=0.3)
        ax.axhline(y=0, color='black', linewidth=0.5)

    fig.suptitle('Monolith: Auth Overhead With vs Excluding Login\n'
                 '(ΔP99, Baseline phase, excl. argon2id)', fontsize=12, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/delta_auth_excl_login_monolith.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
