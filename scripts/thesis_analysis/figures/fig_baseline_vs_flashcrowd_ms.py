#!/usr/bin/env python3
"""Generate delta_auth_baseline_vs_flashcrowd_microservices.pdf."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

ARCH = 'microservices'
PROTECTED = ('/setUser', '/addCartItem', '/cart', '/checkout')
HW_CONFIGS = [(512, 0.25, 'MS S'), (1024, 0.5, 'MS M'), (1769, 1.0, 'MS 1769'),
              (2048, 1.0, 'MS L'), (8192, 4.0, 'MS XL')]


def compute_phase_percentiles(ram, cpu, phase_name):
    eps_sql = ','.join(f"'{e}'" for e in PROTECTED)
    return query_df(f"""
        SELECT e.id AS experiment_id, e.auth_strategy,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL} AND e.architecture = '{ARCH}'
          AND e.ram_in_mb = {ram} AND e.cpu_in_vcpu = {cpu}
          AND r.phase_name = '{phase_name}'
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND r.endpoint IN ({eps_sql})
        GROUP BY e.id, e.auth_strategy
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 30
    """)


def main():
    auth_strategies = ['Cognito', 'Manual', 'Edge']
    auth_map = {'service-integrated': 'Cognito', 'service-integrated-manual': 'Manual', 'edge': 'Edge'}
    rows = []
    for ram, cpu, hw_label in HW_CONFIGS:
        df_bl = compute_phase_percentiles(ram, cpu, 'Baseline')
        df_fc = compute_phase_percentiles(ram, cpu, 'Flash Crowd')
        if df_bl.empty or df_fc.empty:
            continue
        df_bl['p99'] = df_bl['p99'].astype(float)
        df_fc['p99'] = df_fc['p99'].astype(float)
        bl_none = df_bl[df_bl['auth_strategy'] == 'none']
        fc_none = df_fc[df_fc['auth_strategy'] == 'none']
        if bl_none.empty or fc_none.empty:
            continue
        for auth_db, auth_label in auth_map.items():
            bl_auth = df_bl[df_bl['auth_strategy'] == auth_db]
            fc_auth = df_fc[df_fc['auth_strategy'] == auth_db]
            if bl_auth.empty or fc_auth.empty:
                continue
            d_bl = bl_auth['p99'].mean() - bl_none['p99'].mean()
            d_fc = fc_auth['p99'].mean() - fc_none['p99'].mean()
            amp = d_fc / d_bl if abs(d_bl) > 0.5 else None
            rows.append({'hw_label': hw_label, 'auth_label': auth_label,
                         'delta_p99_baseline': d_bl, 'delta_p99_flashcrowd': d_fc,
                         'amplification_p99': amp})

    if not rows:
        print('No MS data')
        return
    result = pd.DataFrame(rows)
    n_hw = len(HW_CONFIGS)
    fig, axes = plt.subplots(1, n_hw, figsize=(5 * n_hw, 6), sharey=False)
    if n_hw == 1:
        axes = [axes]
    for ax, (ram, cpu, hw_label) in zip(axes, HW_CONFIGS):
        ad = result[result['hw_label'] == hw_label]
        if ad.empty:
            ax.set_title(f'{hw_label}\n(no data)', fontsize=10); continue
        auths_present = [a for a in auth_strategies if a in ad['auth_label'].values]
        if not auths_present:
            continue
        x = np.arange(len(auths_present))
        width = 0.35
        vals_bl, vals_fc, colors = [], [], []
        for al in auths_present:
            row = ad[ad['auth_label'] == al].iloc[0]
            vals_bl.append(row['delta_p99_baseline'])
            vals_fc.append(row['delta_p99_flashcrowd'])
            colors.append(AUTH_COLORS.get(al, '#999999'))
        bars1 = ax.bar(x - width / 2, vals_bl, width, label='Baseline',
                       color=colors, alpha=0.85, edgecolor='black', linewidth=0.5)
        bars2 = ax.bar(x + width / 2, vals_fc, width, label='Flash Crowd',
                       color=colors, alpha=0.45, edgecolor='black', linewidth=0.5, hatch='///')
        for bar, val in zip(bars1, vals_bl):
            y = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, y + (1 if y >= 0 else -1),
                    f'{val:+.0f}', ha='center', va='bottom' if y >= 0 else 'top',
                    fontsize=7, fontweight='bold')
        for bar, val in zip(bars2, vals_fc):
            y = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, y + (1 if y >= 0 else -1),
                    f'{val:+.0f}', ha='center', va='bottom' if y >= 0 else 'top',
                    fontsize=7, fontweight='bold')
        for i, al in enumerate(auths_present):
            row = ad[ad['auth_label'] == al].iloc[0]
            if row['amplification_p99'] is not None:
                max_val = max(abs(vals_bl[i]), abs(vals_fc[i]))
                ax.annotate(f'{row["amplification_p99"]:.1f}x',
                            (x[i], max_val + 8), ha='center', fontsize=8,
                            color='darkred', fontweight='bold')
        ax.set_xticks(x); ax.set_xticklabels(auths_present, fontsize=9)
        ax.set_ylabel('ΔAuth P99 (ms)', fontsize=9)
        ax.set_title(hw_label, fontsize=10, fontweight='bold')
        ax.legend(fontsize=7); ax.grid(axis='y', alpha=0.3)
        ax.axhline(y=0, color='black', linewidth=0.5)
    fig.suptitle('Microservices: Auth Overhead — Baseline vs Flash Crowd\n'
                 '(ΔP99, auth-only endpoints, excl. argon2id)', fontsize=12, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/delta_auth_baseline_vs_flashcrowd_microservices.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
