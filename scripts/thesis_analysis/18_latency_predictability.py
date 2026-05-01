#!/usr/bin/env python3
"""
18 — Latency Predictability & Variance Analysis
Analyzes latency variance (CoV), tail latency ratios (P99/P50),
and SLA compliance rates across architectures and auth strategies.
Key insight: FaaS provides more predictable latency than containers.
Outputs: latency_cov_comparison.pdf, tail_ratio_comparison.pdf,
         sla_compliance.pdf, predictability_summary.csv
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, ARCH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}


def main():
    print("=" * 70)
    print("18 — LATENCY PREDICTABILITY & VARIANCE ANALYSIS")
    print("=" * 70)

    # ── 1. Per-experiment per-phase variance metrics ──
    df = query_df(f"""
        SELECT
            e.id, e.architecture, e.auth_strategy,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            r.phase_name,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_lat,
            STDDEV(r.latency_ms) FILTER (WHERE NOT r.is_error) AS std_lat,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.phase_name IS NOT NULL
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.id, e.architecture, e.auth_strategy,
                 e.ram_in_mb, cpu, r.phase_name
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 200
    """)

    for col in ['mean_lat', 'std_lat', 'p50', 'p95', 'p99']:
        df[col] = df[col].astype(float)

    df['cov'] = (df['std_lat'] / df['mean_lat'] * 100).where(df['mean_lat'] > 0, 0)
    df['tail_ratio'] = (df['p99'] / df['p50']).where(df['p50'] > 0, 0)
    df['p95_p50_ratio'] = (df['p95'] / df['p50']).where(df['p50'] > 0, 0)

    # ── 2. Average CoV by arch × auth × phase ──
    cov_avg = df.groupby(['architecture', 'auth_strategy', 'phase_name']).agg(
        cov_mean=('cov', 'mean'),
        cov_median=('cov', 'median'),
        tail_ratio_mean=('tail_ratio', 'mean'),
        tail_ratio_median=('tail_ratio', 'median'),
        n=('id', 'nunique')
    ).reset_index()

    # ── 3. CoV comparison plot ──
    phase_order = ['Baseline', 'Morning rush', 'Stabilization', 'Flash Crowd', 'Step Down', 'Cool-down']
    auth_order = ['none', 'service-integrated', 'edge']

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    # Row 1: CoV by phase for each architecture
    for i, arch in enumerate(['faas', 'microservices', 'monolith']):
        ax = axes[0][i]
        arch_data = cov_avg[cov_avg['architecture'] == arch]
        x = np.arange(len(phase_order))
        width = 0.25

        for j, auth in enumerate(auth_order):
            auth_data = arch_data[arch_data['auth_strategy'] == auth]
            vals = []
            for phase in phase_order:
                match = auth_data[auth_data['phase_name'] == phase]
                vals.append(match.iloc[0]['cov_mean'] if not match.empty else 0)
            offset = (j - 1) * width
            label = AUTH_SHORT.get(auth, auth)
            ax.bar(x + offset, vals, width, label=label, alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels([p[:8] for p in phase_order], rotation=30, ha='right', fontsize=8)
        ax.set_ylabel('CoV (%)')
        ax.set_title(f'{arch} — Latency CoV', fontweight='bold')
        ax.legend(fontsize=7)
        ax.grid(axis='y', alpha=0.3)

    # Row 2: Tail ratio (P99/P50) by phase for each architecture
    for i, arch in enumerate(['faas', 'microservices', 'monolith']):
        ax = axes[1][i]
        arch_data = cov_avg[cov_avg['architecture'] == arch]
        x = np.arange(len(phase_order))
        width = 0.25

        for j, auth in enumerate(auth_order):
            auth_data = arch_data[arch_data['auth_strategy'] == auth]
            vals = []
            for phase in phase_order:
                match = auth_data[auth_data['phase_name'] == phase]
                vals.append(match.iloc[0]['tail_ratio_mean'] if not match.empty else 0)
            offset = (j - 1) * width
            label = AUTH_SHORT.get(auth, auth)
            ax.bar(x + offset, vals, width, label=label, alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels([p[:8] for p in phase_order], rotation=30, ha='right', fontsize=8)
        ax.set_ylabel('P99/P50 Ratio')
        ax.set_title(f'{arch} — Tail Latency Ratio', fontweight='bold')
        ax.legend(fontsize=7)
        ax.grid(axis='y', alpha=0.3)
        ax.axhline(y=5, color='red', linestyle='--', alpha=0.3, label='5× threshold')

    fig.suptitle('Latency Predictability: CoV and Tail Ratio by Architecture\n'
                 '(excluding argon2id)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/latency_cov_comparison.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # ── 4. SLA compliance: % requests under threshold ──
    sla_thresholds = [100, 200, 500, 1000]

    sla_data = query_df(f"""
        SELECT
            e.architecture, e.auth_strategy,
            r.phase_name,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS total,
            COUNT(*) FILTER (WHERE NOT r.is_error AND r.latency_ms < 100) AS under_100,
            COUNT(*) FILTER (WHERE NOT r.is_error AND r.latency_ms < 200) AS under_200,
            COUNT(*) FILTER (WHERE NOT r.is_error AND r.latency_ms < 500) AS under_500,
            COUNT(*) FILTER (WHERE NOT r.is_error AND r.latency_ms < 1000) AS under_1000
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.phase_name IN ('Baseline', 'Flash Crowd', 'Step Down')
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.architecture, e.auth_strategy, r.phase_name
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 1000
    """)

    for t in sla_thresholds:
        sla_data[f'pct_{t}'] = sla_data[f'under_{t}'] / sla_data['total'] * 100

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    sla_target = 500  # 500ms SLA threshold

    for ax, phase in zip(axes, ['Baseline', 'Flash Crowd', 'Step Down']):
        phase_data = sla_data[sla_data['phase_name'] == phase]
        archs = ['faas', 'microservices', 'monolith']
        auth_order_sla = ['none', 'service-integrated', 'edge']
        x = np.arange(len(archs))
        width = 0.25

        for j, auth in enumerate(auth_order_sla):
            vals = []
            for arch in archs:
                match = phase_data[(phase_data['architecture'] == arch) &
                                   (phase_data['auth_strategy'] == auth)]
                vals.append(match.iloc[0][f'pct_{sla_target}'] if not match.empty else 0)
            offset = (j - 1) * width
            ax.bar(x + offset, vals, width, label=AUTH_SHORT.get(auth, auth), alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels(archs)
        ax.set_ylabel(f'% Requests < {sla_target}ms')
        ax.set_title(f'{phase}', fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)
        ax.set_ylim(0, 105)
        ax.axhline(y=99, color='green', linestyle='--', alpha=0.3)
        ax.axhline(y=95, color='orange', linestyle='--', alpha=0.3)

    fig.suptitle(f'SLA Compliance: % Requests Under {sla_target}ms by Phase\n'
                 f'(Green: 99%, Orange: 95%)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/sla_compliance.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # ── 5. Summary table ──
    summary_rows = []
    for arch in ['faas', 'microservices', 'monolith']:
        for auth in ['none', 'service-integrated', 'edge']:
            for phase in ['Baseline', 'Flash Crowd']:
                match = df[(df['architecture'] == arch) &
                          (df['auth_strategy'] == auth) &
                          (df['phase_name'] == phase)]
                sla_match = sla_data[(sla_data['architecture'] == arch) &
                                     (sla_data['auth_strategy'] == auth) &
                                     (sla_data['phase_name'] == phase)]
                if not match.empty:
                    summary_rows.append({
                        'architecture': arch,
                        'auth': AUTH_SHORT.get(auth, auth),
                        'phase': phase,
                        'mean_cov': match['cov'].mean(),
                        'mean_tail_ratio': match['tail_ratio'].mean(),
                        'mean_p50': match['p50'].mean(),
                        'mean_p99': match['p99'].mean(),
                        'sla_500ms': sla_match.iloc[0]['pct_500'] if not sla_match.empty else None,
                        'sla_1000ms': sla_match.iloc[0]['pct_1000'] if not sla_match.empty else None,
                    })

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(f"{PLOT_DIR}/predictability_summary.csv", index=False)
    print(f"\nSaved: {PLOT_DIR}/predictability_summary.csv")

    # ── 6. Print key findings ──
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)

    bl = summary[summary['phase'] == 'Baseline']
    fc = summary[summary['phase'] == 'Flash Crowd']

    print("\n  BASELINE CoV (lower = more predictable):")
    for _, r in bl.sort_values('mean_cov').iterrows():
        print(f"    {r['architecture']:>14s} / {r['auth']:>8s}: CoV = {r['mean_cov']:.0f}%, "
              f"P99/P50 = {r['mean_tail_ratio']:.1f}×, "
              f"SLA<500ms = {r['sla_500ms']:.1f}%" if r['sla_500ms'] else "")

    print("\n  FLASH CROWD CoV:")
    for _, r in fc.sort_values('mean_cov').iterrows():
        print(f"    {r['architecture']:>14s} / {r['auth']:>8s}: CoV = {r['mean_cov']:.0f}%, "
              f"P99/P50 = {r['mean_tail_ratio']:.1f}×, "
              f"SLA<500ms = {r['sla_500ms']:.1f}%" if r['sla_500ms'] else "")

    # Compare FaaS vs containers
    faas_bl = bl[bl['architecture'] == 'faas']['mean_cov'].mean()
    ms_bl = bl[bl['architecture'] == 'microservices']['mean_cov'].mean()
    mono_bl = bl[bl['architecture'] == 'monolith']['mean_cov'].mean()
    print(f"\n  ARCHITECTURE PREDICTABILITY RATIO (Baseline):")
    print(f"    FaaS avg CoV:          {faas_bl:.0f}%")
    print(f"    Microservices avg CoV: {ms_bl:.0f}% ({ms_bl/faas_bl:.1f}× less predictable)")
    print(f"    Monolith avg CoV:      {mono_bl:.0f}% ({mono_bl/faas_bl:.1f}× less predictable)")

    # Auth impact on predictability
    print(f"\n  AUTH IMPACT ON PREDICTABILITY (Baseline):")
    for arch in ['faas', 'microservices', 'monolith']:
        none_cov = bl[(bl['architecture'] == arch) & (bl['auth'] == 'None')]['mean_cov'].values
        cognito_cov = bl[(bl['architecture'] == arch) & (bl['auth'] == 'Cognito')]['mean_cov'].values
        if len(none_cov) > 0 and len(cognito_cov) > 0:
            delta_cov = cognito_cov[0] - none_cov[0]
            print(f"    {arch}: None CoV={none_cov[0]:.0f}% → Cognito CoV={cognito_cov[0]:.0f}% "
                  f"(Δ={delta_cov:+.0f}pp)")


if __name__ == '__main__':
    main()
