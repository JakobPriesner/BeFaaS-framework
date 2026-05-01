#!/usr/bin/env python3
"""
17 — Algorithm Impact Analysis: bcrypt/HS256 vs argon2id/EdDSA
Investigates how the choice of password hashing and JWT signing algorithm
affects performance across architectures and hardware tiers.
Outputs: algo_comparison_heatmap.pdf, algo_scaling_hw.pdf,
         algo_error_rates.pdf, algo_impact.csv
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, ARCH_COLORS


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    return {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(float(cpu), f"{cpu}vCPU")


def main():
    print("=" * 70)
    print("17 — ALGORITHM IMPACT ANALYSIS (bcrypt/HS256 vs argon2id/EdDSA)")
    print("=" * 70)

    # ── 1. Get manual auth experiments with algo info ──
    df = query_df(f"""
        SELECT
            e.id, e.architecture, e.auth_strategy,
            e.password_hash_algorithm AS hash_algo,
            e.jwt_sign_algorithm AS jwt_algo,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            r.phase_name,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            COUNT(*) FILTER (WHERE r.is_error) AS n_errors,
            COUNT(*) FILTER (WHERE r.status_code >= 500) AS n_5xx,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.auth_strategy = 'service-integrated-manual'
          AND e.password_hash_algorithm IS NOT NULL
          AND r.phase_name IS NOT NULL
        GROUP BY e.id, e.architecture, e.auth_strategy,
                 e.password_hash_algorithm, e.jwt_sign_algorithm,
                 e.ram_in_mb, cpu, r.phase_name
        HAVING COUNT(*) > 50
    """)

    for col in ['p50', 'p95', 'p99']:
        df[col] = df[col].astype(float)
    df['error_rate'] = df['n_errors'] / df['total'] * 100
    df['_5xx_rate'] = df['n_5xx'] / df['total'] * 100
    df['algo_label'] = df['hash_algo'] + '/' + df['jwt_algo']
    df['hw'] = df.apply(lambda r: hw_label(r['architecture'], r['ram_in_mb'], r['cpu']), axis=1)

    # Also get none-auth baselines for delta computation
    none_df = query_df(f"""
        SELECT
            e.architecture, e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            r.phase_name,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.auth_strategy = 'none'
          AND r.phase_name IS NOT NULL
        GROUP BY e.architecture, e.ram_in_mb, cpu, r.phase_name
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 200
    """)
    for col in ['p50', 'p99']:
        none_df[col] = none_df[col].astype(float)

    # ── 2. Baseline comparison: bcrypt vs argon2id ──
    baseline = df[df['phase_name'] == 'Baseline'].copy()

    # Average across experiments of same config
    bl_avg = baseline.groupby(['architecture', 'ram_in_mb', 'hw', 'algo_label']).agg(
        p50=('p50', 'mean'), p95=('p95', 'mean'), p99=('p99', 'mean'),
        error_rate=('error_rate', 'mean'),
        _5xx_rate=('_5xx_rate', 'mean'),
        n_experiments=('id', 'nunique')
    ).reset_index()

    print("\n--- BASELINE COMPARISON ---")
    impact_rows = []
    for (arch, ram), grp in bl_avg.groupby(['architecture', 'ram_in_mb']):
        bcrypt_row = grp[grp['algo_label'] == 'bcrypt/HS256']
        argon_row = grp[grp['algo_label'] == 'argon2id/EdDSA']

        hw = grp.iloc[0]['hw']
        # Get none baseline
        none_match = none_df[(none_df['architecture'] == arch) &
                             (none_df['ram_in_mb'] == ram) &
                             (none_df['phase_name'] == 'Baseline')]
        none_p99 = none_match['p99'].mean() if not none_match.empty else 0

        for algo_label, arow in [('bcrypt/HS256', bcrypt_row), ('argon2id/EdDSA', argon_row)]:
            if arow.empty:
                continue
            r = arow.iloc[0]
            delta = r['p99'] - none_p99 if none_p99 > 0 else None
            impact_rows.append({
                'architecture': arch, 'hw': hw, 'ram_in_mb': ram,
                'algorithm': algo_label,
                'p50': r['p50'], 'p95': r['p95'], 'p99': r['p99'],
                'error_rate': r['error_rate'], '_5xx_rate': r['_5xx_rate'],
                'none_p99': none_p99,
                'delta_p99': delta,
                'n_experiments': r['n_experiments'],
            })

    impact_df = pd.DataFrame(impact_rows).sort_values(['architecture', 'ram_in_mb', 'algorithm'])
    impact_df.to_csv(f"{PLOT_DIR}/algo_impact.csv", index=False)
    print(impact_df.to_string(index=False, float_format='{:.1f}'.format))

    # ── 3. Heatmap: P99 by algo × arch × hw ──
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for ax, algo in zip(axes, ['bcrypt/HS256', 'argon2id/EdDSA']):
        algo_data = impact_df[impact_df['algorithm'] == algo]
        if algo_data.empty:
            ax.set_title(f'{algo} (no data)')
            continue

        archs = ['faas', 'microservices', 'monolith']
        hw_labels = sorted(algo_data['hw'].unique(),
                           key=lambda x: {'S':1,'M':2,'L':3,'XL':4}.get(x,
                               int(x.replace('MB','')) if 'MB' in x else 0))

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
                    txt = f'{val:.0f}ms'
                    color = 'white' if val > 1000 else 'black'
                    ax.text(j, i, txt, ha='center', va='center',
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

    # ── 4. Hardware scaling: how algo cost scales with CPU ──
    # Clip y-axis to make bcrypt visible when argon2id has extreme outliers
    Y_CLIP = 7000  # ms — values above this are annotated with arrows
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        for algo in ['bcrypt/HS256', 'argon2id/EdDSA']:
            algo_data = impact_df[(impact_df['architecture'] == arch) &
                                  (impact_df['algorithm'] == algo)].copy()
            if algo_data.empty:
                continue
            algo_data = algo_data.sort_values('ram_in_mb')
            marker = 'o' if 'bcrypt' in algo else 's'
            color = '#3498db' if 'bcrypt' in algo else '#e74c3c'

            hw_labels = algo_data['hw'].values
            x_pos = np.arange(len(hw_labels))
            y_vals = algo_data['p99'].values.copy()
            # Clip for plotting, annotate clipped points
            y_plot = np.minimum(y_vals, Y_CLIP)
            ax.plot(x_pos, y_plot,
                    f'{marker}-', label=algo, color=color, linewidth=2, markersize=8)
            for idx, (_, r) in enumerate(algo_data.iterrows()):
                if r['p99'] > Y_CLIP:
                    # Show actual value above clip line with arrow
                    ax.annotate(f'{r["p99"]:.0f}ms\n(Δ{r["delta_p99"]:+.0f})',
                                (idx, Y_CLIP), textcoords='offset points',
                                xytext=(0, 8), fontsize=7, color=color,
                                ha='center', fontweight='bold',
                                arrowprops=dict(arrowstyle='wedge,tail_width=0.5',
                                                color=color, alpha=0.3))
                elif r['delta_p99'] is not None:
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

    # ── 5. Error rates under load by algo ──
    load_phases = ['Baseline', 'Morning rush', 'Flash Crowd', 'Step Down']
    load_data = df[df['phase_name'].isin(load_phases)].copy()

    # Average error rate per config × phase
    load_avg = load_data.groupby(['architecture', 'ram_in_mb', 'hw', 'algo_label', 'phase_name']).agg(
        error_rate=('error_rate', 'mean'),
        _5xx_rate=('_5xx_rate', 'mean'),
        total=('total', 'sum'),
    ).reset_index()

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = load_avg[load_avg['architecture'] == arch]
        if arch_data.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        # Pick largest hw tier for clearest comparison
        ram = arch_data['ram_in_mb'].max()
        sub = arch_data[arch_data['ram_in_mb'] == ram]

        x = np.arange(len(load_phases))
        width = 0.35
        for i, algo in enumerate(['bcrypt/HS256', 'argon2id/EdDSA']):
            vals = []
            for phase in load_phases:
                match = sub[(sub['algo_label'] == algo) & (sub['phase_name'] == phase)]
                vals.append(match.iloc[0]['error_rate'] if not match.empty else 0)
            color = '#3498db' if 'bcrypt' in algo else '#e74c3c'
            offset = (i - 0.5) * width
            ax.bar(x + offset, vals, width, label=algo, color=color, alpha=0.85)

        hw = sub.iloc[0]['hw'] if not sub.empty else ''
        ax.set_xticks(x)
        ax.set_xticklabels(load_phases, rotation=20, ha='right', fontsize=9)
        ax.set_ylabel('Error Rate (%)')
        ax.set_title(f'{arch} ({hw})', fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('Error Rate by Algorithm Under Load\n'
                 '(Manual auth, largest hardware tier per architecture)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/algo_error_rates.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # ── 6. Key findings ──
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)

    # Compare bcrypt vs argon2id at same hw
    for arch in ['faas', 'microservices', 'monolith']:
        arch_impact = impact_df[impact_df['architecture'] == arch]
        for ram in sorted(arch_impact['ram_in_mb'].unique()):
            bcrypt = arch_impact[(arch_impact['ram_in_mb'] == ram) &
                                 (arch_impact['algorithm'] == 'bcrypt/HS256')]
            argon = arch_impact[(arch_impact['ram_in_mb'] == ram) &
                                (arch_impact['algorithm'] == 'argon2id/EdDSA')]
            if not bcrypt.empty and not argon.empty:
                ratio = argon.iloc[0]['p99'] / bcrypt.iloc[0]['p99'] if bcrypt.iloc[0]['p99'] > 0 else 0
                print(f"  {arch}/{bcrypt.iloc[0]['hw']}: argon2id P99 = {ratio:.1f}× bcrypt P99 "
                      f"({argon.iloc[0]['p99']:.0f}ms vs {bcrypt.iloc[0]['p99']:.0f}ms)")

    # Argon2id scaling efficiency
    print("\n  ARGON2ID SCALING WITH HARDWARE:")
    for arch in ['faas', 'microservices', 'monolith']:
        argon = impact_df[(impact_df['architecture'] == arch) &
                          (impact_df['algorithm'] == 'argon2id/EdDSA')]
        if len(argon) >= 2:
            argon = argon.sort_values('ram_in_mb')
            smallest = argon.iloc[0]
            largest = argon.iloc[-1]
            hw_ratio = largest['ram_in_mb'] / smallest['ram_in_mb']
            perf_ratio = smallest['p99'] / largest['p99'] if largest['p99'] > 0 else 0
            print(f"    {arch}: {smallest['hw']}→{largest['hw']} ({hw_ratio:.0f}× resources): "
                  f"P99 {smallest['p99']:.0f}ms → {largest['p99']:.0f}ms ({perf_ratio:.1f}× faster)")

    # FaaS resilience
    faas_bcrypt = impact_df[(impact_df['architecture'] == 'faas') &
                            (impact_df['algorithm'] == 'bcrypt/HS256')]
    faas_argon = impact_df[(impact_df['architecture'] == 'faas') &
                           (impact_df['algorithm'] == 'argon2id/EdDSA')]
    if not faas_argon.empty:
        print(f"\n  FAAS RESILIENCE: argon2id error rate = {faas_argon['error_rate'].mean():.1f}% "
              f"(FaaS isolates CPU-bound work)")
    ms_argon = impact_df[(impact_df['architecture'] == 'microservices') &
                         (impact_df['algorithm'] == 'argon2id/EdDSA')]
    if not ms_argon.empty:
        print(f"  MS VULNERABILITY:  argon2id error rate = {ms_argon['error_rate'].mean():.1f}% "
              f"(shared event loop blocks)")


if __name__ == '__main__':
    main()
