#!/usr/bin/env python3
"""Generate algo_scaling_hw.pdf for fig:algo-scaling.

1×3 line plot per architecture showing P99 vs hardware tier for
bcrypt/HS256 vs argon2id/EdDSA. Y-axis clipped at 7000ms with
arrow annotations for values above the clip threshold.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

Y_CLIP = 7000


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    return {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(float(cpu), f"{cpu}vCPU")


def main():
    manual_df = query_df(f"""
        SELECT
            e.architecture,
            e.password_hash_algorithm AS hash_algo,
            e.jwt_sign_algorithm AS jwt_algo,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.auth_strategy = 'service-integrated-manual'
          AND e.password_hash_algorithm IS NOT NULL
          AND r.phase_name = 'Baseline'
        GROUP BY e.architecture, e.password_hash_algorithm, e.jwt_sign_algorithm,
                 e.ram_in_mb, cpu
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)

    none_df = query_df(f"""
        SELECT
            e.architecture, e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.auth_strategy = 'none'
          AND r.phase_name = 'Baseline'
        GROUP BY e.architecture, e.ram_in_mb, cpu
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 200
    """)

    if manual_df.empty:
        print('No data'); return

    for d in [manual_df, none_df]:
        d['p99'] = d['p99'].astype(float)
    manual_df['algo_label'] = manual_df['hash_algo'] + '/' + manual_df['jwt_algo']
    manual_df['hw'] = manual_df.apply(lambda r: hw_label(r['architecture'], r['ram_in_mb'], r['cpu']), axis=1)

    bl_avg = manual_df.groupby(['architecture', 'ram_in_mb', 'hw', 'algo_label']).agg(
        p99=('p99', 'mean')
    ).reset_index()

    none_avg = none_df.groupby(['architecture', 'ram_in_mb']).agg(
        none_p99=('p99', 'mean')
    ).reset_index()

    bl_avg = bl_avg.merge(none_avg, on=['architecture', 'ram_in_mb'], how='left')
    bl_avg['delta_p99'] = bl_avg['p99'] - bl_avg['none_p99']

    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        for algo in ['bcrypt/HS256', 'argon2id/EdDSA']:
            algo_data = bl_avg[(bl_avg['architecture'] == arch) &
                               (bl_avg['algo_label'] == algo)].copy()
            if algo_data.empty:
                continue
            algo_data = algo_data.sort_values('ram_in_mb')
            marker = 'o' if 'bcrypt' in algo else 's'
            color = '#3498db' if 'bcrypt' in algo else '#e74c3c'

            hw_labels = algo_data['hw'].values
            x_pos = np.arange(len(hw_labels))
            y_vals = algo_data['p99'].values.copy()
            y_plot = np.minimum(y_vals, Y_CLIP)
            ax.plot(x_pos, y_plot, f'{marker}-', label=algo, color=color,
                    linewidth=2, markersize=8)

            for idx, (_, r) in enumerate(algo_data.iterrows()):
                if r['p99'] > Y_CLIP:
                    ax.annotate(f'{r["p99"]:.0f}ms\n(Δ{r["delta_p99"]:+.0f})',
                                (idx, Y_CLIP), textcoords='offset points',
                                xytext=(0, 8), fontsize=7, color=color,
                                ha='center', fontweight='bold',
                                arrowprops=dict(arrowstyle='wedge,tail_width=0.5',
                                                color=color, alpha=0.3))
                elif pd.notna(r['delta_p99']):
                    ax.annotate(f'Δ{r["delta_p99"]:+.0f}ms',
                                (idx, r['p99']),
                                textcoords='offset points', xytext=(5, 8),
                                fontsize=7, color=color)
            ax.set_xticks(x_pos)
            ax.set_xticklabels(hw_labels, fontsize=9)

        ax.set_xlabel('Hardware Tier')
        ax.set_ylabel('P99 Latency (ms)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

    axes[0].set_ylim(0, Y_CLIP * 1.05)
    fig.suptitle('Algorithm P99 Scaling with Hardware Resources\n'
                 '(Manual auth, Baseline phase)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/algo_scaling_hw.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
