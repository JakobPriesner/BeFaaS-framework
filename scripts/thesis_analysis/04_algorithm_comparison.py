#!/usr/bin/env python3
"""
04 - Algorithm Comparison: bcrypt/HS256 vs argon2id/EdDSA
Compares the two manual auth algorithm variants across architectures.
Outputs: algorithm_comparison.pdf, algorithm_overhead.csv
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

ALGO_COLORS = {
    'bcrypt/HS256': '#3498db',
    'argon2id/EdDSA': '#e74c3c',
}
ALGO_SHORT = {'bcrypt/HS256': 'bcrypt/HS256', 'argon2id/EdDSA': 'argon2id/EdDSA'}


def main():
    print("=" * 70)
    print("04 - ALGORITHM COMPARISON: bcrypt/HS256 vs argon2id/EdDSA")
    print("=" * 70)

    # Get manual auth experiments with both algorithms
    df = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.auth_strategy,
            e.password_hash_algorithm || '/' || e.jwt_sign_algorithm AS algo,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            r.phase_name,
            COUNT(*) AS request_count,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS error_count,
            COUNT(CASE WHEN r.status_code = 401 THEN 1 END) AS soft_fails,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99,
            AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_ms
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE e.auth_strategy = 'service-integrated-manual'
          AND e.password_hash_algorithm IS NOT NULL
          AND r.phase_name IS NOT NULL AND r.phase_name != 'None'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.auth_strategy,
                 e.password_hash_algorithm, e.jwt_sign_algorithm,
                 e.ram_in_mb, e.cpu_in_vcpu, r.phase_name
        HAVING COUNT(*) > 100
        ORDER BY e.architecture, e.id, r.phase_name
    """)

    df['error_rate'] = (df['error_count'] / df['request_count'] * 100).round(2)

    def hw_label(row):
        if row['architecture'] == 'faas':
            return f"{row['ram_in_mb']}MB"
        cpu = row['cpu_in_vcpu']
        if cpu == 4.0: return 'XL'
        elif cpu == 1.0: return 'L'
        elif cpu == 0.5: return 'M'
        elif cpu == 0.25: return 'S'
        return f"{cpu}vCPU"
    df['hw'] = df.apply(hw_label, axis=1)

    print(f"\nManual auth phase records: {len(df)}")
    algos_found = df['algo'].unique()
    print(f"Algorithms found: {', '.join(algos_found)}")

    # --- Summary table ---
    print("\n--- ALGORITHM COMPARISON (Baseline Phase) ---")
    baseline = df[df['phase_name'] == 'Baseline']
    print(f"\n{'Arch':>15s} {'HW':>6s} {'Algorithm':>16s} {'Exp':>4s} "
          f"{'P50':>8s} {'P95':>8s} {'P99':>8s} {'Reqs':>8s} {'Err%':>6s}")
    for _, r in baseline.sort_values(['architecture', 'hw', 'algo']).iterrows():
        print(f"{r['architecture']:>15s} {r['hw']:>6s} {r['algo']:>16s} {r['experiment_id']:>4.0f} "
              f"{r['p50']:>8.1f} {r['p95']:>8.1f} {r['p99']:>8.1f} {r['request_count']:>8,} {r['error_rate']:>5.1f}%")

    # --- PLOT 1: Side-by-side comparison across architectures ---
    baseline_best = baseline.sort_values('request_count', ascending=False).drop_duplicates(
        subset=['architecture', 'hw', 'algo'], keep='first')

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = baseline_best[baseline_best['architecture'] == arch]
        if arch_data.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        hw_tiers = sorted(arch_data['hw'].unique(),
                         key=lambda x: int(x.replace('MB', '')) if 'MB' in x else
                         {'S': 1, 'M': 2, 'L': 3, 'XL': 4}.get(x, 0))
        x = np.arange(len(hw_tiers))
        width = 0.35

        for i, algo in enumerate(['bcrypt/HS256', 'argon2id/EdDSA']):
            algo_data = arch_data[arch_data['algo'] == algo]
            vals = []
            for hw in hw_tiers:
                match = algo_data[algo_data['hw'] == hw]
                vals.append(match.iloc[0]['p99'] if not match.empty else 0)
            offset = (i - 0.5) * width
            bars = ax.bar(x + offset, vals, width, label=algo,
                         color=ALGO_COLORS.get(algo, '#999'), alpha=0.85)
            # Add error rate annotations
            for j, hw in enumerate(hw_tiers):
                match = algo_data[algo_data['hw'] == hw]
                if not match.empty:
                    err = match.iloc[0]['error_rate']
                    if err > 5:
                        ax.text(j + offset, vals[j] + 10, f'{err:.0f}%err',
                               ha='center', va='bottom', fontsize=7, color='red')

        ax.set_xticks(x)
        ax.set_xticklabels(hw_tiers, fontsize=9)
        ax.set_xlabel('Hardware Tier')
        ax.set_ylabel('P99 Latency (ms)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('Algorithm Comparison: Baseline P99 Latency\nbcrypt/HS256 vs argon2id/EdDSA',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/algorithm_comparison_baseline.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"\nSaved: {path}")
    plt.close()

    # --- PLOT 2: Error rate comparison (argon2id on small hardware) ---
    print("\n--- ERROR RATE BY ALGORITHM & HARDWARE ---")
    phase_order = ['Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
                   'Flash Crowd', 'Step Down', 'Cool-down']

    # Find experiments with high error rates
    exp_totals = df.groupby(['experiment_id', 'architecture', 'algo', 'hw']).agg({
        'request_count': 'sum',
        'error_count': 'sum'
    }).reset_index()
    exp_totals['total_error_rate'] = (exp_totals['error_count'] / exp_totals['request_count'] * 100).round(2)

    high_error = exp_totals[exp_totals['total_error_rate'] > 10]
    if not high_error.empty:
        print("\nHigh error rate experiments (>10%):")
        for _, r in high_error.sort_values('total_error_rate', ascending=False).iterrows():
            print(f"  Exp {r['experiment_id']:.0f}: {r['architecture']} {r['algo']} {r['hw']} "
                  f"-> {r['total_error_rate']:.1f}% errors ({r['error_count']:.0f}/{r['request_count']:.0f})")

    # --- PLOT 3: Phase-by-phase algorithm comparison ---
    for arch in df['architecture'].unique():
        arch_df = df[df['architecture'] == arch]
        hw_tiers = arch_df['hw'].unique()

        for hw in hw_tiers:
            hw_df = arch_df[arch_df['hw'] == hw]
            algos_present = hw_df['algo'].unique()
            if len(algos_present) < 2:
                continue

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [2, 1]})

            for algo in algos_present:
                algo_data = hw_df[hw_df['algo'] == algo]
                # Average across experiments
                phase_avg = algo_data.groupby('phase_name')[['p99', 'error_rate', 'request_count']].mean()
                phases_present = [p for p in phase_order if p in phase_avg.index]
                if not phases_present:
                    continue
                phase_avg = phase_avg.loc[phases_present]

                ax1.plot(range(len(phases_present)), phase_avg['p99'], 'o-',
                        label=f"{algo} (P99)",
                        color=ALGO_COLORS.get(algo, '#999'), linewidth=2, markersize=6)
                ax2.plot(range(len(phases_present)), phase_avg['error_rate'], 's-',
                        label=f"{algo}",
                        color=ALGO_COLORS.get(algo, '#999'), linewidth=2, markersize=6)

            ax1.set_xticks(range(len(phase_order)))
            ax1.set_xticklabels(phase_order, rotation=30, ha='right', fontsize=9)
            ax1.set_ylabel('P99 Latency (ms)')
            ax1.set_title(f'{arch} ({hw}) — Algorithm Comparison by Phase', fontweight='bold')
            ax1.legend(fontsize=9)
            ax1.grid(alpha=0.3)

            ax2.set_xticks(range(len(phase_order)))
            ax2.set_xticklabels(phase_order, rotation=30, ha='right', fontsize=9)
            ax2.set_ylabel('Error Rate (%)')
            ax2.set_title('Error Rate per Phase')
            ax2.legend(fontsize=9)
            ax2.grid(alpha=0.3)

            plt.tight_layout()
            path = f"{PLOT_DIR}/algo_phase_{arch}_{hw}.pdf"
            fig.savefig(path, bbox_inches='tight')
            print(f"Saved: {path}")
            plt.close()

    # Save comparison data
    baseline.to_csv(f"{PLOT_DIR}/algorithm_comparison.csv", index=False)
    print(f"Saved: {PLOT_DIR}/algorithm_comparison.csv")


if __name__ == '__main__':
    main()
