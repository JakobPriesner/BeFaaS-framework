#!/usr/bin/env python3
"""
01 - Experiment Overview & Quality Assessment
Generates a full inventory of experiments with quality metrics.
Outputs: experiment_overview.csv, experiment_quality_matrix.pdf
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDED_EXPERIMENTS

def main():
    print("=" * 70)
    print("01 - EXPERIMENT OVERVIEW & QUALITY ASSESSMENT")
    print("=" * 70)

    # 1. Get all experiments with request counts and phase counts
    df = query_df("""
        SELECT
            e.id,
            e.architecture,
            e.auth_strategy,
            e.password_hash_algorithm AS hash_algo,
            e.jwt_sign_algorithm AS jwt_algo,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            COALESCE(e.with_cloudfront, false) AS with_cf,
            COUNT(r.id) AS total_requests,
            SUM(CASE WHEN r.is_error THEN 1 ELSE 0 END) AS total_errors,
            COUNT(DISTINCT r.phase_name) AS phase_count,
            SUM(CASE WHEN r.status_code = 401 THEN 1 ELSE 0 END) AS soft_fails,
            SUM(CASE WHEN r.status_code >= 500 THEN 1 ELSE 0 END) AS server_errors,
            SUM(CASE WHEN r.is_timeout THEN 1 ELSE 0 END) AS timeouts
        FROM experiments e
        LEFT JOIN requests r ON r.experiment_id = e.id
        GROUP BY e.id, e.architecture, e.auth_strategy,
                 e.password_hash_algorithm, e.jwt_sign_algorithm,
                 e.ram_in_mb, e.cpu_in_vcpu, e.with_cloudfront
        ORDER BY e.id
    """)

    # Hardware label
    def hw_label(row):
        if row['architecture'] == 'faas':
            return f"{row['ram_in_mb']}MB"
        else:
            cpu = row['cpu_in_vcpu']
            ram = row['ram_in_mb']
            if cpu == 4.0:
                return 'XL'
            elif cpu == 1.0:
                return 'L'
            elif cpu == 0.5:
                return 'M'
            elif cpu == 0.25:
                return 'S'
            return f"{cpu}vCPU/{ram}MB"

    df['hw_label'] = df.apply(hw_label, axis=1)
    df['algo'] = df.apply(lambda r: f"{r['hash_algo']}/{r['jwt_algo']}" if r['hash_algo'] else 'N/A', axis=1)
    df['excluded'] = df['id'].isin(EXCLUDED_EXPERIMENTS)
    df['usable'] = (df['total_requests'] > 10000) & (~df['excluded'])
    df['full_scnast'] = df['usable'] & (df['phase_count'] >= 7)
    df['error_rate'] = (df['total_errors'] / df['total_requests'] * 100).round(2)

    print(f"\nTotal experiments: {len(df)}")
    print(f"Excluded experiments (duplicates/broken): {df['excluded'].sum()}")
    print(f"Usable experiments (>10k reqs, not excluded): {df['usable'].sum()}")
    print(f"  of which full SCNAST (7 phases): {df['full_scnast'].sum()}")
    print(f"Total requests across all experiments: {df['total_requests'].sum():,}")

    # 2. Print grouped summary
    print("\n--- EXPERIMENT MATRIX ---")
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = df[df['architecture'] == arch]
        print(f"\n{arch.upper()} ({len(arch_df)} experiments, {arch_df['usable'].sum()} usable):")
        for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
            auth_df = arch_df[arch_df['auth_strategy'] == auth]
            if len(auth_df) == 0:
                continue
            usable = auth_df[auth_df['usable']]
            print(f"  {auth:30s}: {len(auth_df):3d} total, {len(usable):3d} usable")
            for _, row in usable.iterrows():
                print(f"    Exp {row['id']:3d}: {row['hw_label']:8s} {row['algo']:20s} "
                      f"reqs={row['total_requests']:>10,} err={row['error_rate']:5.1f}%")

    # 3. Save CSV
    csv_path = f"{PLOT_DIR}/experiment_overview.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nSaved overview CSV: {csv_path}")

    # 4. Quality matrix plot
    fig, axes = plt.subplots(1, 3, figsize=(18, 8))
    archs = ['faas', 'microservices', 'monolith']
    auth_order = ['none', 'service-integrated', 'service-integrated-manual', 'edge']

    for ax, arch in zip(axes, archs):
        arch_df = df[(df['architecture'] == arch) & df['usable']].copy()

        # Build a matrix: hw_label × auth_strategy → count of usable experiments
        def hw_sort_key(x):
            hw_map = {'S': 1, 'M': 2, 'L': 3, 'XL': 4}
            if x in hw_map:
                return hw_map[x]
            try:
                return int(x.replace('MB', ''))
            except ValueError:
                return 0
        hw_labels = sorted(arch_df['hw_label'].unique(), key=hw_sort_key)
        matrix = []
        for hw in hw_labels:
            row = []
            for auth in auth_order:
                count = len(arch_df[(arch_df['hw_label'] == hw) & (arch_df['auth_strategy'] == auth)])
                row.append(count)
            matrix.append(row)

        if not matrix:
            ax.set_title(f'{arch}\n(no usable experiments)')
            continue

        matrix = np.array(matrix)
        im = ax.imshow(matrix, cmap='YlGn', aspect='auto', vmin=0, vmax=max(3, matrix.max()))

        ax.set_xticks(range(len(auth_order)))
        ax.set_xticklabels(['none', 'integrated', 'manual', 'edge'], rotation=45, ha='right', fontsize=8)
        ax.set_yticks(range(len(hw_labels)))
        ax.set_yticklabels(hw_labels, fontsize=8)
        ax.set_title(f'{arch}', fontweight='bold')
        ax.set_xlabel('Auth Strategy')
        ax.set_ylabel('Hardware')

        for i in range(len(hw_labels)):
            for j in range(len(auth_order)):
                ax.text(j, i, str(matrix[i, j]), ha='center', va='center',
                        color='white' if matrix[i, j] >= 2 else 'black', fontsize=10, fontweight='bold')

    fig.suptitle('Experiment Coverage Matrix (usable experiments per config)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/experiment_quality_matrix.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # 5. Request volume per experiment bar chart
    usable = df[df['usable']].sort_values('total_requests', ascending=True)
    fig, ax = plt.subplots(figsize=(12, max(6, len(usable) * 0.25)))
    colors = {'faas': '#3498db', 'microservices': '#e74c3c', 'monolith': '#2ecc71'}
    ax.barh(
        [f"Exp {r['id']} ({r['architecture'][:3]}/{r['auth_strategy'][:4]}/{r['hw_label']})"
         for _, r in usable.iterrows()],
        usable['total_requests'],
        color=[colors[r['architecture']] for _, r in usable.iterrows()],
        alpha=0.8
    )
    ax.set_xlabel('Total Requests')
    ax.set_title('Request Volume per Usable Experiment')
    ax.axvline(x=100000, color='red', linestyle='--', alpha=0.5, label='100k threshold')

    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=c, label=a) for a, c in colors.items()]
    ax.legend(handles=legend_elements, loc='lower right')
    plt.tight_layout()
    path = f"{PLOT_DIR}/experiment_request_volume.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
