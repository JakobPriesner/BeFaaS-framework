#!/usr/bin/env python3
"""
10 - Throughput & Capacity Analysis
Analyzes effective throughput (req/s) per configuration,
capacity limits, and the relationship between auth overhead and throughput.
Outputs: throughput_comparison_all.pdf, phase_throughput_comparison.pdf,
         throughput_vs_errors.pdf, throughput_summary.csv

Fully differentiated: bcrypt vs argon2id, with/without CloudFront.
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import numpy as np

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL, EXCLUDE_SQL_BY_EXP_ID,
                           auth_label_detailed, hw_label_from_row,
                           AUTH_COLORS_DETAILED, HW_TIERS_ALL)

PHASE_ORDER = ['Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
               'Flash Crowd', 'Step Down', 'Cool-down']

# Consistent label order for plots
AUTH_LABEL_ORDER = [
    'None', 'None+CF',
    'Cognito', 'Cognito+CF',
    'Manual (bcrypt)', 'Manual (bcrypt)+CF',
    'Manual (argon2id)', 'Manual (argon2id)+CF',
    'Edge', 'Edge+CF',
    'Edge-Sel.', 'Edge-Sel.+CF',
]


def main():
    print("=" * 70)
    print("10 - THROUGHPUT & CAPACITY ANALYSIS — FULL DIFFERENTIATION")
    print("=" * 70)

    # 1. Throughput per phase per experiment
    df = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            COALESCE(e.with_cloudfront, false) AS with_cf,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            r.phase_name,
            COUNT(*) AS request_count,
            COUNT(CASE WHEN NOT r.is_error THEN 1 END) AS success_count,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS error_count,
            (MAX(r.relative_time_ms) - MIN(r.relative_time_ms)) / 1000.0 AS phase_duration_s
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name IS NOT NULL AND r.phase_name != 'None'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.auth_strategy, e.password_hash_algorithm,
                 e.with_cloudfront, e.ram_in_mb, e.cpu_in_vcpu, r.phase_name
        HAVING COUNT(*) > 50
        ORDER BY e.id, r.phase_name
    """)

    # Avoid division by zero for very short phases
    df['phase_duration_s'] = df['phase_duration_s'].clip(lower=1.0)
    df['throughput_rps'] = df['request_count'] / df['phase_duration_s']
    df['success_rps'] = df['success_count'] / df['phase_duration_s']
    df['error_rate'] = (df['error_count'] / df['request_count'] * 100).round(2)

    # Compute hw and auth labels
    df['hw'] = df.apply(lambda r: hw_label_from_row(r), axis=1)
    df['auth_label'] = df.apply(
        lambda r: auth_label_detailed(
            r['auth_strategy'],
            r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
            bool(r['with_cf'])),
        axis=1)

    # 2. Total throughput comparison
    totals = df.groupby(['experiment_id', 'architecture', 'auth_strategy', 'auth_label',
                         'hw', 'algo', 'with_cf']).agg({
        'request_count': 'sum',
        'success_count': 'sum',
        'error_count': 'sum',
    }).reset_index()

    # Get total benchmark duration from request timestamps
    durations = query_df(f"""
        SELECT experiment_id,
               (MAX(relative_time_ms) - MIN(relative_time_ms)) / 1000.0 AS total_duration_s
        FROM requests
        WHERE {EXCLUDE_SQL_BY_EXP_ID}
        GROUP BY experiment_id
        HAVING (MAX(relative_time_ms) - MIN(relative_time_ms)) > 0
    """)
    totals = totals.merge(durations, on='experiment_id', how='left')
    totals['total_duration_s'] = totals['total_duration_s'].clip(lower=1.0)
    totals['avg_rps'] = totals['request_count'] / totals['total_duration_s']
    totals['success_rps'] = totals['success_count'] / totals['total_duration_s']

    print("\n--- TOTAL THROUGHPUT COMPARISON ---")
    best = totals.sort_values('request_count', ascending=False).drop_duplicates(
        subset=['architecture', 'auth_label', 'hw'], keep='first')

    print(f"\n{'Exp':>4s} {'Arch':>15s} {'AuthLabel':>25s} {'HW':>6s} "
          f"{'TotalReqs':>12s} {'AvgRPS':>8s} {'SucRPS':>8s}")
    for _, r in best.sort_values(['architecture', 'auth_label', 'hw']).iterrows():
        print(f"{r['experiment_id']:>4.0f} {r['architecture']:>15s} {r['auth_label']:>25s} {r['hw']:>6s} "
              f"{r['request_count']:>12,} {r['avg_rps']:>8.1f} {r['success_rps']:>8.1f}")

    # --- PLOT 1: Throughput bar chart per architecture (combined, enlarged) ---
    fig, axes = plt.subplots(1, 3, figsize=(22, 9), sharey=True)
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = best[best['architecture'] == arch]
        if arch_data.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        hw_tiers = [hw for _, _, hw in HW_TIERS_ALL[arch] if hw in arch_data['hw'].values]
        present_labels = [l for l in AUTH_LABEL_ORDER if l in arch_data['auth_label'].values]

        x = np.arange(len(hw_tiers))
        n_auth = len(present_labels)
        width = 0.8 / max(n_auth, 1)

        for i, auth_l in enumerate(present_labels):
            auth_vals = []
            for hw in hw_tiers:
                match = arch_data[(arch_data['auth_label'] == auth_l) & (arch_data['hw'] == hw)]
                auth_vals.append(match.iloc[0]['avg_rps'] if not match.empty else 0)
            offset = (i - n_auth / 2 + 0.5) * width
            color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
            bars = ax.bar(x + offset, auth_vals, width, label=auth_l, color=color, alpha=0.85)
            for bar, val in zip(bars, auth_vals):
                if val > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                            f'{val:.0f}', ha='center', va='bottom', fontsize=7)

        ax.set_xticks(x)
        ax.set_xticklabels(hw_tiers, fontsize=10)
        ax.set_xlabel('Hardware-Tier', fontsize=11)
        if ax == axes[0]:
            ax.set_ylabel('Durchschn. Durchsatz (Req/s)', fontsize=11)
        ax.set_title(f'{arch.capitalize()}', fontweight='bold', fontsize=12)
        ax.grid(axis='y', alpha=0.3)

    # Single shared legend below all subplots
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=8,
               loc='upper center', bbox_to_anchor=(0.5, 0.02),
               ncol=len(labels), framealpha=0.9)
    fig.suptitle('Durchschnittlicher Durchsatz nach Architektur, Authentifizierung und Hardware\n'
                 '(alle Varianten inkl. Algorithmen und CloudFront)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout(rect=[0, 0.05, 1, 0.95])
    path = f"{PLOT_DIR}/throughput_comparison_all.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"\nSaved: {path}")
    plt.close()

    # --- PLOT 1b: Per-architecture throughput bar charts ---
    arch_display = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}
    for arch in ['faas', 'microservices', 'monolith']:
        arch_data = best[best['architecture'] == arch]
        if arch_data.empty:
            continue

        hw_tiers = [hw for _, _, hw in HW_TIERS_ALL[arch] if hw in arch_data['hw'].values]
        present_labels = [l for l in AUTH_LABEL_ORDER if l in arch_data['auth_label'].values]

        x = np.arange(len(hw_tiers))
        n_auth = len(present_labels)
        width = 0.8 / max(n_auth, 1)

        fig, ax = plt.subplots(figsize=(10, 7))
        has_err_annotation = False
        missing_slots = []

        for i, auth_l in enumerate(present_labels):
            auth_vals = []
            err_vals = []
            present = []
            for hw in hw_tiers:
                match = arch_data[(arch_data['auth_label'] == auth_l) & (arch_data['hw'] == hw)]
                if not match.empty:
                    auth_vals.append(match.iloc[0]['avg_rps'])
                    err_vals.append(match.iloc[0]['error_count'] / max(match.iloc[0]['request_count'], 1) * 100)
                    present.append(True)
                else:
                    auth_vals.append(0)
                    err_vals.append(0)
                    present.append(False)
            offset = (i - n_auth / 2 + 0.5) * width
            color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
            bars = ax.bar(x + offset, auth_vals, width, label=auth_l, color=color, alpha=0.85)
            for j, p in enumerate(present):
                if not p:
                    missing_slots.append(x[j] + offset)
            for bar, val, err in zip(bars, auth_vals, err_vals):
                if val > 0:
                    bx = bar.get_x() + bar.get_width() / 2
                    bh = bar.get_height()
                    # Throughput label above bar
                    ax.text(bx, bh + 0.5, f'{val:.0f}',
                            ha='center', va='bottom', fontsize=7)
                    # Error rate directly below throughput label, in red
                    if err >= 2:
                        has_err_annotation = True
                        err_str = f'{err:.0f}%' if err >= 10 else f'{err:.1f}%'
                        # Place inside bar near the top (below the throughput number)
                        y_pos = max(bh - 8, bh * 0.5) if bh > 20 else bh + 5
                        ax.text(bx, y_pos, err_str, ha='center', va='top',
                                fontsize=6, fontweight='bold', color='#c62828',
                                bbox=dict(boxstyle='round,pad=0.1',
                                          facecolor='white', edgecolor='none',
                                          alpha=0.8))

        # Mark slots without data
        y_hi = ax.get_ylim()[1]
        for xm in missing_slots:
            ax.text(xm, y_hi * 0.02, '–',
                    ha='center', va='bottom', fontsize=9,
                    color='#999', fontweight='bold')

        ax.set_xticks(x)
        ax.set_xticklabels(hw_tiers, fontsize=10)
        ax.set_xlabel('Hardware-Tier', fontsize=11)
        ax.set_ylabel('Durchschn. Durchsatz (Req/s)', fontsize=11)
        ax.set_title(f'Durchsatz: {arch_display[arch]}', fontweight='bold', fontsize=13)
        ax.tick_params(labelsize=9)
        ax.grid(axis='y', alpha=0.3)

        # Legend below plot
        legend_note = 'Rot = Fehlerrate (nur Werte \u2265 2%)' if has_err_annotation else None
        ax.legend(fontsize=8, title=legend_note, title_fontsize=8,
                  loc='upper center', bbox_to_anchor=(0.5, -0.10),
                  ncol=4, framealpha=0.9)

        plt.tight_layout()
        path = f"{PLOT_DIR}/throughput_comparison_{arch}.pdf"
        fig.savefig(path, dpi=300, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # --- PLOT 2: Phase-wise throughput timeline ---
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_df = df[df['architecture'] == arch]
        if arch_df.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        # Pick best experiment per auth_label
        exp_totals = arch_df.groupby(['experiment_id', 'auth_label', 'hw'])['request_count'].sum()
        best_exps = exp_totals.reset_index().sort_values('request_count', ascending=False)
        best_exps = best_exps.drop_duplicates(subset=['auth_label'], keep='first')

        for _, meta in best_exps.iterrows():
            exp_data = arch_df[arch_df['experiment_id'] == meta['experiment_id']]
            phases = [p for p in PHASE_ORDER if p in exp_data['phase_name'].values]
            if len(phases) < 3:
                continue
            exp_ordered = exp_data.set_index('phase_name').loc[phases]
            color = AUTH_COLORS_DETAILED.get(meta['auth_label'], '#999')
            linestyle = '--' if '+CF' in meta['auth_label'] else '-'
            ax.plot(range(len(phases)), exp_ordered['throughput_rps'], 'o-',
                    label=f"{meta['auth_label']} ({meta['hw']})",
                    color=color, linestyle=linestyle,
                    linewidth=2, markersize=5)

        ax.set_xticks(range(len(PHASE_ORDER)))
        ax.set_xticklabels(PHASE_ORDER, rotation=35, ha='right', fontsize=8)
        ax.set_ylabel('Durchsatz (Req/s)')
        ax.set_title(f'{arch.capitalize()}', fontweight='bold')
        ax.legend(fontsize=6)
        ax.grid(alpha=0.3)

    fig.suptitle('Durchsatz über SCNAST-Phasen (alle Varianten)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/phase_throughput_comparison.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # --- PLOT 3: Throughput vs Error Rate scatter ---
    fig, ax = plt.subplots(figsize=(10, 7))
    arch_markers = {'faas': 'o', 'microservices': 's', 'monolith': '^'}

    for _, r in best.iterrows():
        ax.scatter(r['avg_rps'], r['error_count'] / r['request_count'] * 100,
                   marker=arch_markers.get(r['architecture'], 'o'),
                   color=AUTH_COLORS_DETAILED.get(r['auth_label'], '#999'),
                   s=80, alpha=0.7,
                   edgecolors='black', linewidths=0.5)

    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    present = best['auth_label'].unique()
    color_legend = [Patch(facecolor=AUTH_COLORS_DETAILED.get(l, '#999'), label=l)
                    for l in AUTH_LABEL_ORDER if l in present]
    marker_legend = [Line2D([0], [0], marker=m, color='gray', markersize=8, linestyle='', label=a)
                     for a, m in arch_markers.items()]
    ax.legend(handles=color_legend + marker_legend, fontsize=7, loc='upper right')

    ax.set_xlabel('Durchschn. Durchsatz (Req/s)')
    ax.set_ylabel('Fehlerrate (%)')
    ax.set_title('Durchsatz vs. Fehlerrate (alle Varianten)', fontweight='bold')
    ax.grid(alpha=0.3)
    plt.tight_layout()
    path = f"{PLOT_DIR}/throughput_vs_errors.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    best.to_csv(f"{PLOT_DIR}/throughput_summary.csv", index=False)
    print(f"Saved: {PLOT_DIR}/throughput_summary.csv")


if __name__ == '__main__':
    main()
