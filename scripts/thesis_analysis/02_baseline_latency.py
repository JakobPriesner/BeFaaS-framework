#!/usr/bin/env python3
"""
02 - Baseline Latency Analysis (RQ1 Core)
Computes P50/P95/P99 for baseline phase across all configurations.
Computes DeltaAuth = T_auth - T_none for each architecture × hardware combo.
Outputs: baseline_latency_comparison.pdf, delta_auth_table.pdf, latency_cdf_comparison.pdf
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL


def get_baseline_percentiles():
    """Get latency percentiles for baseline phase of each experiment."""
    return query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.auth_strategy,
            e.password_hash_algorithm AS hash_algo,
            e.jwt_sign_algorithm AS jwt_algo,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            COUNT(*) AS request_count,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS error_count,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99,
            AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_ms,
            STDDEV(r.latency_ms) FILTER (WHERE NOT r.is_error) AS stddev_ms
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name = 'Baseline'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.auth_strategy,
                 e.password_hash_algorithm, e.jwt_sign_algorithm,
                 e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) > 1000
        ORDER BY e.architecture, e.auth_strategy, e.ram_in_mb
    """)


def hw_label(row):
    if row['architecture'] == 'faas':
        return f"{row['ram_in_mb']}MB"
    cpu = row['cpu_in_vcpu']
    if cpu == 4.0: return 'XL'
    elif cpu == 1.0: return 'L'
    elif cpu == 0.5: return 'M'
    elif cpu == 0.25: return 'S'
    return f"{cpu}vCPU"


def algo_label(row):
    if row['hash_algo'] and row['jwt_algo']:
        return f"{row['hash_algo']}/{row['jwt_algo']}"
    return 'N/A'


def main():
    print("=" * 70)
    print("02 - BASELINE LATENCY ANALYSIS")
    print("=" * 70)

    df = get_baseline_percentiles()
    df['hw'] = df.apply(hw_label, axis=1)
    df['algo'] = df.apply(algo_label, axis=1)
    df['error_rate'] = (df['error_count'] / df['request_count'] * 100).round(2)

    print(f"\nExperiments with baseline data: {len(df)}")

    # Print summary table
    print("\n--- BASELINE LATENCY SUMMARY (P50 / P95 / P99 ms) ---")
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = df[df['architecture'] == arch]
        if arch_df.empty:
            continue
        print(f"\n{arch.upper()}:")
        print(f"  {'Exp':>4s} {'Auth':>25s} {'HW':>6s} {'Algo':>16s} "
              f"{'P50':>8s} {'P95':>8s} {'P99':>8s} {'Reqs':>8s} {'Err%':>6s}")
        for _, r in arch_df.iterrows():
            print(f"  {r['experiment_id']:4.0f} {r['auth_strategy']:>25s} {r['hw']:>6s} {r['algo']:>16s} "
                  f"{r['p50']:8.1f} {r['p95']:8.1f} {r['p99']:8.1f} {r['request_count']:>8,} {r['error_rate']:5.1f}%")

    # --- PLOT 1: Grouped bar chart of P50/P95/P99 per architecture ---
    fig, axes = plt.subplots(1, 3, figsize=(20, 7), sharey=False)
    auth_colors = {
        'none': '#95a5a6',
        'service-integrated': '#3498db',
        'service-integrated-manual': '#e74c3c',
        'edge': '#2ecc71'
    }
    auth_short = {
        'none': 'None',
        'service-integrated': 'Cognito',
        'service-integrated-manual': 'Manual',
        'edge': 'Edge'
    }

    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_df = df[df['architecture'] == arch].copy()
        if arch_df.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        # For each hw tier, pick the best experiment per auth strategy (highest request count)
        best = arch_df.sort_values('request_count', ascending=False).drop_duplicates(
            subset=['auth_strategy', 'hw', 'algo'], keep='first')

        # Group by hw label
        hw_groups = sorted(best['hw'].unique(),
                          key=lambda x: int(x.replace('MB', '')) if 'MB' in x else
                          {'S': 1, 'M': 2, 'L': 3, 'XL': 4}.get(x, 0))

        x = np.arange(len(hw_groups))
        width = 0.2
        auth_list = [a for a in ['none', 'service-integrated', 'service-integrated-manual', 'edge']
                     if a in best['auth_strategy'].values]

        for i, auth in enumerate(auth_list):
            auth_data = best[best['auth_strategy'] == auth]
            p99_vals = []
            for hw in hw_groups:
                match = auth_data[auth_data['hw'] == hw]
                if not match.empty:
                    p99_vals.append(match.iloc[0]['p99'])
                else:
                    p99_vals.append(0)
            offset = (i - len(auth_list) / 2 + 0.5) * width
            bars = ax.bar(x + offset, p99_vals, width, label=auth_short.get(auth, auth),
                         color=auth_colors.get(auth, '#999'), alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels(hw_groups, fontsize=9)
        ax.set_xlabel('Hardware Tier')
        ax.set_ylabel('P99 Latency (ms)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('Baseline P99 Latency by Architecture, Auth Strategy & Hardware', fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/baseline_p99_comparison.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"\nSaved: {path}")
    plt.close()

    # --- PLOT 2: DeltaAuth computation ---
    print("\n--- DELTA_AUTH COMPUTATION ---")
    print("DeltaAuth = P99(auth) - P99(none), same architecture & hardware")

    delta_rows = []
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = df[df['architecture'] == arch]
        # Get baseline (none) for each hw tier
        none_df = arch_df[arch_df['auth_strategy'] == 'none']
        for _, none_row in none_df.iterrows():
            hw = none_row['hw']
            # Find matching auth experiments
            for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                auth_rows = arch_df[(arch_df['auth_strategy'] == auth) & (arch_df['hw'] == hw)]
                for _, auth_row in auth_rows.iterrows():
                    delta_rows.append({
                        'architecture': arch,
                        'auth_strategy': auth,
                        'hw': hw,
                        'algo': auth_row['algo'],
                        'none_exp': int(none_row['experiment_id']),
                        'auth_exp': int(auth_row['experiment_id']),
                        'none_p50': none_row['p50'],
                        'auth_p50': auth_row['p50'],
                        'delta_p50': auth_row['p50'] - none_row['p50'],
                        'none_p95': none_row['p95'],
                        'auth_p95': auth_row['p95'],
                        'delta_p95': auth_row['p95'] - none_row['p95'],
                        'none_p99': none_row['p99'],
                        'auth_p99': auth_row['p99'],
                        'delta_p99': auth_row['p99'] - none_row['p99'],
                        'pct_overhead_p99': ((auth_row['p99'] - none_row['p99']) / none_row['p99'] * 100)
                            if none_row['p99'] > 0 else 0,
                    })

    delta_df = pd.DataFrame(delta_rows)
    if not delta_df.empty:
        print(f"\nDeltaAuth pairs found: {len(delta_df)}")
        print(f"\n{'Arch':>15s} {'Auth':>25s} {'HW':>6s} {'Algo':>16s} "
              f"{'dP50':>8s} {'dP95':>8s} {'dP99':>8s} {'%OH(P99)':>8s}")
        for _, r in delta_df.iterrows():
            print(f"{r['architecture']:>15s} {r['auth_strategy']:>25s} {r['hw']:>6s} {r['algo']:>16s} "
                  f"{r['delta_p50']:+8.1f} {r['delta_p95']:+8.1f} {r['delta_p99']:+8.1f} "
                  f"{r['pct_overhead_p99']:+7.1f}%")

        delta_df.to_csv(f"{PLOT_DIR}/delta_auth_table.csv", index=False)
        print(f"\nSaved: {PLOT_DIR}/delta_auth_table.csv")

        # DeltaAuth bar plot
        fig, ax = plt.subplots(figsize=(14, 7))
        delta_sorted = delta_df.sort_values('delta_p99')
        labels = [f"{r['architecture'][:3]}/{auth_short.get(r['auth_strategy'], r['auth_strategy'])}/{r['hw']}"
                  for _, r in delta_sorted.iterrows()]
        colors_list = [auth_colors.get(r['auth_strategy'], '#999') for _, r in delta_sorted.iterrows()]

        bars = ax.barh(range(len(delta_sorted)), delta_sorted['delta_p99'], color=colors_list, alpha=0.85)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_xlabel('$\\Delta_{Auth}$ P99 (ms)')
        ax.set_title('Authentication Overhead ($\\Delta_{Auth}$) at P99 — Baseline Phase', fontweight='bold')
        ax.axvline(x=0, color='black', linewidth=0.5)
        ax.grid(axis='x', alpha=0.3)
        plt.tight_layout()
        path = f"{PLOT_DIR}/delta_auth_p99.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # --- PLOT 3: CDF comparison for selected experiments ---
    print("\n--- GENERATING LATENCY CDF PLOTS ---")
    # Pick representative experiments: for each arch, none vs best auth at same hw
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = df[df['architecture'] == arch]
        if arch_df.empty:
            continue

        # Find the hw tier with most auth variants
        hw_counts = arch_df.groupby('hw')['auth_strategy'].nunique()
        if hw_counts.empty:
            continue
        best_hw = hw_counts.idxmax()
        hw_df = arch_df[arch_df['hw'] == best_hw].sort_values('request_count', ascending=False)
        exp_ids = hw_df.drop_duplicates('auth_strategy')['experiment_id'].tolist()

        if len(exp_ids) < 2:
            continue

        # Query raw latency for CDF (sample if too many)
        exp_id_str = ','.join(str(int(x)) for x in exp_ids)
        cdf_data = query_df(f"""
            SELECT e.auth_strategy, r.latency_ms
            FROM requests r
            JOIN experiments e ON r.experiment_id = e.id
            WHERE r.experiment_id IN ({exp_id_str})
              AND r.phase_name = 'Baseline'
              AND NOT r.is_error
              AND r.latency_ms < 10000
            ORDER BY RANDOM()
            LIMIT 500000
        """)

        if cdf_data.empty:
            continue

        fig, ax = plt.subplots(figsize=(10, 6))
        for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
            subset = cdf_data[cdf_data['auth_strategy'] == auth]['latency_ms'].sort_values()
            if len(subset) < 10:
                continue
            cdf_y = np.arange(1, len(subset) + 1) / len(subset)
            ax.plot(subset, cdf_y, label=auth_short.get(auth, auth),
                   color=auth_colors.get(auth, '#999'), linewidth=1.5)

        ax.set_xlabel('Latency (ms)')
        ax.set_ylabel('CDF')
        ax.set_title(f'Latency CDF — {arch} ({best_hw}, Baseline Phase)', fontweight='bold')
        ax.legend()
        ax.grid(alpha=0.3)
        ax.set_xlim(left=0)
        plt.tight_layout()
        path = f"{PLOT_DIR}/latency_cdf_{arch}_{best_hw}.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()


if __name__ == '__main__':
    main()