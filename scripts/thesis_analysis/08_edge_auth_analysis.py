#!/usr/bin/env python3
"""
08 - Edge Auth Analysis
Compares edge-based authentication vs service-integrated and manual.
Analyzes the unique latency profile of edge auth (request rejection at gateway).
Outputs: edge_comparison.pdf, edge_vs_integrated.pdf
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
PHASE_ORDER = ['Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
               'Flash Crowd', 'Step Down', 'Cool-down']


def main():
    print("=" * 70)
    print("08 - EDGE AUTH ANALYSIS")
    print("=" * 70)

    # 1. Edge experiments overview
    edge_overview = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            COUNT(*) AS total_requests,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS total_errors,
            COUNT(CASE WHEN r.status_code = 401 THEN 1 END) AS soft_fails,
            COUNT(CASE WHEN r.is_timeout THEN 1 END) AS timeouts,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE e.auth_strategy = 'edge'
          AND r.phase_name = 'Baseline'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) > 500
        ORDER BY e.architecture, e.id
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
    edge_overview['hw'] = edge_overview.apply(hw_label, axis=1)
    edge_overview['error_rate'] = (edge_overview['total_errors'] / edge_overview['total_requests'] * 100).round(2)

    print(f"\nEdge auth experiments with baseline data: {len(edge_overview)}")
    print(f"\n{'Exp':>4s} {'Arch':>15s} {'HW':>6s} {'P50':>8s} {'P95':>8s} {'P99':>8s} "
          f"{'Reqs':>8s} {'Err%':>6s}")
    for _, r in edge_overview.iterrows():
        print(f"{r['experiment_id']:>4.0f} {r['architecture']:>15s} {r['hw']:>6s} "
              f"{r['p50']:>8.1f} {r['p95']:>8.1f} {r['p99']:>8.1f} "
              f"{r['total_requests']:>8,} {r['error_rate']:>5.1f}%")

    # 2. Compare all auth strategies side by side (baseline)
    all_baseline = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.auth_strategy,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            COUNT(*) AS request_count,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS error_count,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name = 'Baseline'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) > 1000
        ORDER BY e.architecture, e.auth_strategy
    """)
    all_baseline['hw'] = all_baseline.apply(hw_label, axis=1)

    # Keep best per config
    best = all_baseline.sort_values('request_count', ascending=False).drop_duplicates(
        subset=['architecture', 'auth_strategy', 'hw'], keep='first')

    # --- PLOT 1: Edge vs Others, per architecture ---
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    auth_order = ['none', 'service-integrated', 'service-integrated-manual', 'edge']

    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = best[best['architecture'] == arch]
        if arch_data.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        # Find hw tiers that have edge data
        edge_hws = arch_data[arch_data['auth_strategy'] == 'edge']['hw'].values
        if len(edge_hws) == 0:
            ax.set_title(f'{arch} (no edge data)')
            continue

        # For each hw with edge data, compare all strategies
        for hw in edge_hws:
            hw_data = arch_data[arch_data['hw'] == hw]
            auths = [a for a in auth_order if a in hw_data['auth_strategy'].values]
            if not auths:
                continue

            x = np.arange(len(auths))
            p99_vals = [hw_data[hw_data['auth_strategy'] == a].iloc[0]['p99'] if a in hw_data['auth_strategy'].values else 0 for a in auths]
            p50_vals = [hw_data[hw_data['auth_strategy'] == a].iloc[0]['p50'] if a in hw_data['auth_strategy'].values else 0 for a in auths]

            colors = [AUTH_COLORS.get(a, '#999') for a in auths]
            bars = ax.bar(x, p99_vals, 0.6, color=colors, alpha=0.8, label=f'{hw}')

            # Add P50 markers
            ax.scatter(x, p50_vals, color='black', zorder=5, s=30, marker='_', linewidths=2)

            ax.set_xticks(x)
            ax.set_xticklabels([AUTH_SHORT.get(a, a) for a in auths], fontsize=9, rotation=20, ha='right')

        ax.set_ylabel('Latency (ms)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.grid(axis='y', alpha=0.3)
        # Add annotation
        ax.text(0.95, 0.95, 'bars=P99, markers=P50', transform=ax.transAxes,
               fontsize=7, va='top', ha='right', style='italic')

    fig.suptitle('Auth Strategy Comparison (Baseline): Edge vs Service-Integrated',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/edge_vs_integrated_baseline.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"\nSaved: {path}")
    plt.close()

    # --- PLOT 2: Edge auth phase behavior ---
    edge_phases = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            r.phase_name,
            COUNT(*) AS request_count,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS errors,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE e.auth_strategy = 'edge'
          AND r.phase_name IS NOT NULL AND r.phase_name != 'None'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.ram_in_mb, e.cpu_in_vcpu, r.phase_name
        HAVING COUNT(*) > 50
        ORDER BY e.id, r.phase_name
    """)
    edge_phases['hw'] = edge_phases.apply(hw_label, axis=1)

    if not edge_phases.empty:
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
            arch_data = edge_phases[edge_phases['architecture'] == arch]
            if arch_data.empty:
                ax.set_title(f'{arch} (no edge data)')
                continue

            for exp_id in arch_data['experiment_id'].unique():
                exp_data = arch_data[arch_data['experiment_id'] == exp_id]
                hw = exp_data.iloc[0]['hw']
                phases = [p for p in PHASE_ORDER if p in exp_data['phase_name'].values]
                if len(phases) < 3:
                    continue
                exp_ordered = exp_data.set_index('phase_name').loc[phases]
                ax.plot(range(len(phases)), exp_ordered['p99'], 'o-',
                       label=f"Exp {exp_id:.0f} ({hw})", linewidth=2, markersize=5)

            ax.set_xticks(range(len(PHASE_ORDER)))
            ax.set_xticklabels(PHASE_ORDER, rotation=35, ha='right', fontsize=8)
            ax.set_ylabel('P99 Latency (ms)')
            ax.set_title(f'{arch} — Edge Auth', fontweight='bold')
            ax.legend(fontsize=7)
            ax.grid(alpha=0.3)

        fig.suptitle('Edge Auth: P99 Latency Across SCNAST Phases', fontsize=14, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/edge_auth_phases.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # 3. Protected vs unprotected endpoint comparison under edge auth
    print("\n--- EDGE AUTH: PROTECTED vs UNPROTECTED ENDPOINTS ---")
    endpoint_comp = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            h.is_protected_endpoint,
            COUNT(*) AS handler_count,
            AVG(h.duration_ms) AS avg_handler_ms,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY h.duration_ms) AS p95_handler_ms
        FROM experiments e
        JOIN handler_events h ON h.experiment_id = e.id
        WHERE e.auth_strategy = 'edge'
          AND h.phase_name = 'Baseline'
          AND {EXCLUDE_SQL}
          AND h.duration_ms > 0
        GROUP BY e.id, e.architecture, h.is_protected_endpoint
        HAVING COUNT(*) > 100
        ORDER BY e.id
    """)

    if not endpoint_comp.empty:
        print(f"\n{'Exp':>4s} {'Arch':>15s} {'Protected':>10s} {'Count':>8s} {'Avg(ms)':>8s} {'P95(ms)':>8s}")
        for _, r in endpoint_comp.iterrows():
            prot = "Yes" if r['is_protected_endpoint'] else "No"
            print(f"{r['experiment_id']:>4.0f} {r['architecture']:>15s} {prot:>10s} "
                  f"{r['handler_count']:>8,} {r['avg_handler_ms']:>8.1f} {r['p95_handler_ms']:>8.1f}")


if __name__ == '__main__':
    main()
