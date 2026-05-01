#!/usr/bin/env python3
"""
05 - Hardware Scaling Analysis (RQ2)
How does auth overhead change with different hardware tiers?
Tests whether DeltaAuth is constant or varies with resources.
Outputs: hardware_scaling_latency.pdf, hardware_scaling_delta.pdf
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}

def main():
    print("=" * 70)
    print("05 - HARDWARE SCALING ANALYSIS")
    print("=" * 70)

    # Get baseline latency for all experiments
    df = query_df(f"""
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
            AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_ms
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name = 'Baseline'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.auth_strategy,
                 e.password_hash_algorithm, e.jwt_sign_algorithm,
                 e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) > 1000
        ORDER BY e.architecture, e.ram_in_mb
    """)

    df['error_rate'] = (df['error_count'] / df['request_count'] * 100).round(2)
    df['algo'] = df.apply(lambda r: f"{r['hash_algo']}/{r['jwt_algo']}" if r['hash_algo'] else 'N/A', axis=1)

    # Numeric hw value for sorting (MB for faas, mapped for Fargate)
    def hw_numeric(row):
        if row['architecture'] == 'faas':
            return row['ram_in_mb']
        cpu = row['cpu_in_vcpu']
        if cpu == 0.25: return 256
        elif cpu == 0.5: return 512
        elif cpu == 1.0: return 1024
        elif cpu == 4.0: return 4096
        return row['ram_in_mb']

    def hw_label(row):
        if row['architecture'] == 'faas':
            return f"{row['ram_in_mb']}MB"
        cpu = row['cpu_in_vcpu']
        if cpu == 4.0: return 'XL'
        elif cpu == 1.0: return 'L'
        elif cpu == 0.5: return 'M'
        elif cpu == 0.25: return 'S'
        return f"{cpu}vCPU"

    df['hw_num'] = df.apply(hw_numeric, axis=1)
    df['hw'] = df.apply(hw_label, axis=1)

    # Keep best experiment per config
    best = df.sort_values('request_count', ascending=False).drop_duplicates(
        subset=['architecture', 'auth_strategy', 'hw', 'algo'], keep='first')

    # --- PLOT 1: P99 vs Hardware for each architecture ---
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = best[best['architecture'] == arch].sort_values('hw_num')
        if arch_data.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
            # Group by algo too for manual
            for algo in arch_data['algo'].unique():
                subset = arch_data[(arch_data['auth_strategy'] == auth) & (arch_data['algo'] == algo)]
                if subset.empty:
                    continue
                label = AUTH_SHORT.get(auth, auth)
                if auth == 'service-integrated-manual' and algo != 'N/A':
                    label = f"Manual ({algo.split('/')[0]})"
                ax.plot(subset['hw_num'], subset['p99'], 'o-',
                       label=label, linewidth=2, markersize=8)

                # Annotate error rates if high
                for _, r in subset.iterrows():
                    if r['error_rate'] > 10:
                        ax.annotate(f"{r['error_rate']:.0f}%err",
                                   (r['hw_num'], r['p99']),
                                   textcoords="offset points", xytext=(0, 10),
                                   fontsize=7, color='red', ha='center')

        if arch == 'faas':
            ax.set_xlabel('Memory (MB)')
            ax.set_xticks([256, 512, 1024, 1769])
            ax.set_xticklabels(['256', '512', '1024', '1769'])
        else:
            ax.set_xlabel('Hardware Tier')
            ticks = sorted(arch_data['hw_num'].unique())
            ax.set_xticks(ticks)
            labels_map = {256: 'S', 512: 'M', 1024: 'L', 4096: 'XL'}
            ax.set_xticklabels([labels_map.get(t, str(t)) for t in ticks])

        ax.set_ylabel('P99 Latency (ms)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        ax.set_yscale('log')

    fig.suptitle('Hardware Scaling: Baseline P99 Latency vs Resource Allocation',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/hardware_scaling_p99.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"\nSaved: {path}")
    plt.close()

    # --- PLOT 2: DeltaAuth vs Hardware ---
    delta_rows = []
    for arch in ['faas', 'microservices', 'monolith']:
        arch_best = best[best['architecture'] == arch]
        none_data = arch_best[arch_best['auth_strategy'] == 'none']

        for _, none_row in none_data.iterrows():
            hw = none_row['hw']
            hw_num = none_row['hw_num']

            for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                auth_data = arch_best[(arch_best['auth_strategy'] == auth) & (arch_best['hw'] == hw)]
                for _, auth_row in auth_data.iterrows():
                    delta_rows.append({
                        'architecture': arch,
                        'auth_strategy': auth,
                        'algo': auth_row['algo'],
                        'hw': hw,
                        'hw_num': hw_num,
                        'none_p99': none_row['p99'],
                        'auth_p99': auth_row['p99'],
                        'delta_p99': auth_row['p99'] - none_row['p99'],
                        'pct_overhead': (auth_row['p99'] - none_row['p99']) / none_row['p99'] * 100 if none_row['p99'] > 0 else 0,
                        'auth_error_rate': auth_row['error_rate'],
                    })

    delta_df = pd.DataFrame(delta_rows)
    if not delta_df.empty:
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
            arch_delta = delta_df[delta_df['architecture'] == arch].sort_values('hw_num')
            if arch_delta.empty:
                ax.set_title(f'{arch} (no data)')
                continue

            for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                for algo in arch_delta['algo'].unique():
                    subset = arch_delta[(arch_delta['auth_strategy'] == auth) & (arch_delta['algo'] == algo)]
                    if subset.empty:
                        continue
                    label = AUTH_SHORT.get(auth, auth)
                    if auth == 'service-integrated-manual' and algo != 'N/A':
                        label = f"Manual ({algo.split('/')[0]})"
                    ax.plot(subset['hw_num'], subset['delta_p99'], 'o-',
                           label=label, linewidth=2, markersize=8)

            ax.axhline(y=0, color='black', linewidth=0.5, linestyle='--')

            if arch == 'faas':
                ax.set_xlabel('Memory (MB)')
                ticks = sorted(arch_delta['hw_num'].unique())
                ax.set_xticks(ticks)
            else:
                ax.set_xlabel('Hardware Tier')
                ticks = sorted(arch_delta['hw_num'].unique())
                ax.set_xticks(ticks)
                labels_map = {256: 'S', 512: 'M', 1024: 'L', 4096: 'XL'}
                ax.set_xticklabels([labels_map.get(t, str(t)) for t in ticks])

            ax.set_ylabel('$\\Delta_{Auth}$ P99 (ms)')
            ax.set_title(f'{arch}', fontweight='bold')
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)

        fig.suptitle('$\\Delta_{Auth}$ vs Hardware: How Auth Overhead Scales with Resources',
                     fontsize=14, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/hardware_scaling_delta.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

        delta_df.to_csv(f"{PLOT_DIR}/hardware_scaling_delta.csv", index=False)
        print(f"Saved: {PLOT_DIR}/hardware_scaling_delta.csv")

    # --- Print: scaling efficiency ---
    print("\n--- SCALING EFFICIENCY ---")
    print("How much does doubling resources reduce P99?")
    for arch in ['faas', 'microservices', 'monolith']:
        arch_best = best[(best['architecture'] == arch)].sort_values(['auth_strategy', 'hw_num'])
        if arch_best.empty:
            continue
        print(f"\n{arch.upper()}:")
        for auth in arch_best['auth_strategy'].unique():
            auth_data = arch_best[arch_best['auth_strategy'] == auth].sort_values('hw_num')
            if len(auth_data) < 2:
                continue
            print(f"  {auth}:")
            prev = None
            for _, r in auth_data.iterrows():
                if prev is not None:
                    speedup = prev['p99'] / r['p99'] if r['p99'] > 0 else 0
                    print(f"    {prev['hw']} -> {r['hw']}: P99 {prev['p99']:.0f} -> {r['p99']:.0f} ms "
                          f"({speedup:.2f}x speedup)")
                prev = r


if __name__ == '__main__':
    main()
