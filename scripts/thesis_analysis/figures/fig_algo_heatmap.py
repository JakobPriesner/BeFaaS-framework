#!/usr/bin/env python3
"""Generate algo_comparison_heatmap.pdf for fig:algo-heatmap.

1×2 heatmap showing Baseline P99 latency for bcrypt/HS256 vs argon2id/EdDSA
across architectures and hardware tiers.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    return {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(float(cpu), f"{cpu}vCPU")


def main():
    df = query_df(f"""
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
    if df.empty:
        print('No data'); return

    df['p99'] = df['p99'].astype(float)
    df['algo_label'] = df['hash_algo'] + '/' + df['jwt_algo']
    df['hw'] = df.apply(lambda r: hw_label(r['architecture'], r['ram_in_mb'], r['cpu']), axis=1)

    bl_avg = df.groupby(['architecture', 'hw', 'ram_in_mb', 'algo_label']).agg(
        p99=('p99', 'mean')
    ).reset_index()

    archs = ['faas', 'microservices', 'monolith']
    hw_labels = sorted(bl_avg['hw'].unique(),
                       key=lambda x: {'S': 1, 'M': 2, 'L': 3, 'XL': 4}.get(x,
                           int(x.replace('MB', '')) if 'MB' in x else 0))

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for ax, algo in zip(axes, ['bcrypt/HS256', 'argon2id/EdDSA']):
        algo_data = bl_avg[bl_avg['algo_label'] == algo]
        if algo_data.empty:
            ax.set_title(f'{algo} (no data)'); continue

        matrix = np.full((len(archs), len(hw_labels)), np.nan)
        for i, arch in enumerate(archs):
            for j, hw in enumerate(hw_labels):
                match = algo_data[(algo_data['architecture'] == arch) & (algo_data['hw'] == hw)]
                if not match.empty:
                    matrix[i, j] = match.iloc[0]['p99']

        im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto',
                       vmin=0, vmax=min(3000, np.nanmax(matrix)))
        ax.set_xticks(range(len(hw_labels)))
        ax.set_xticklabels(hw_labels, fontsize=9)
        ax.set_yticks(range(len(archs)))
        ax.set_yticklabels(archs, fontsize=9)
        ax.set_title(f'{algo}', fontweight='bold', fontsize=12)
        ax.set_xlabel('Hardware Tier')

        for i in range(len(archs)):
            for j in range(len(hw_labels)):
                if not np.isnan(matrix[i, j]):
                    val = matrix[i, j]
                    color = 'white' if val > 1000 else 'black'
                    ax.text(j, i, f'{val:.0f}ms', ha='center', va='center',
                            fontsize=8, fontweight='bold', color=color)

        fig.colorbar(im, ax=ax, shrink=0.8, label='P99 Latency (ms)')

    fig.suptitle('Baseline P99 Latency: bcrypt/HS256 vs argon2id/EdDSA\n'
                 '(Manual auth, all architectures and hardware tiers)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/algo_comparison_heatmap.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
