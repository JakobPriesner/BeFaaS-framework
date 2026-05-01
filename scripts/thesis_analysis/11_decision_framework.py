#!/usr/bin/env python3
"""
11 - Decision Framework (RQ4)
Combines performance and security dimensions into a recommendation matrix.
Generates the decision framework table and visualization for the thesis.
Outputs: decision_framework.pdf, decision_matrix.csv, radar_chart.pdf
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}


def main():
    print("=" * 70)
    print("11 - DECISION FRAMEWORK (RQ4)")
    print("=" * 70)

    # 1. Collect all baseline metrics
    baseline = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.auth_strategy,
            e.password_hash_algorithm AS hash_algo,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            COUNT(*) AS baseline_requests,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS baseline_errors,
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
        GROUP BY e.id, e.architecture, e.auth_strategy, e.password_hash_algorithm,
                 e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) > 1000
    """)

    # Total throughput
    totals = query_df(f"""
        SELECT
            e.id AS experiment_id,
            COUNT(*) AS total_requests,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS total_errors
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name IS NOT NULL AND r.phase_name != 'None'
          AND {EXCLUDE_SQL}
        GROUP BY e.id
    """)

    df = baseline.merge(totals, on='experiment_id', how='left')
    df['error_rate'] = (df['total_errors'] / df['total_requests'] * 100).round(2)

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

    # Keep best per config
    best = df.sort_values('total_requests', ascending=False).drop_duplicates(
        subset=['architecture', 'auth_strategy', 'hw'], keep='first')

    # 2. Compute DeltaAuth for each combo
    decision_rows = []
    for arch in ['faas', 'microservices', 'monolith']:
        arch_best = best[best['architecture'] == arch]
        none_data = arch_best[arch_best['auth_strategy'] == 'none']

        for _, none_row in none_data.iterrows():
            hw = none_row['hw']
            # Add none baseline row
            decision_rows.append({
                'architecture': arch,
                'auth_strategy': 'none',
                'hw': hw,
                'p50': none_row['p50'],
                'p95': none_row['p95'],
                'p99': none_row['p99'],
                'delta_p99': 0,
                'total_requests': none_row['total_requests'],
                'error_rate': none_row['error_rate'],
                'security_score': 0,  # No auth
                'token_exposure_components': 0,
            })

            for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                auth_rows = arch_best[(arch_best['auth_strategy'] == auth) & (arch_best['hw'] == hw)]
                if auth_rows.empty:
                    continue
                auth_row = auth_rows.iloc[0]

                # Security scoring (qualitative)
                if auth == 'edge':
                    security_score = 4  # Best: single verification point
                    if arch == 'faas':
                        token_components = 1  # Only edge verifies
                    elif arch == 'microservices':
                        token_components = 1
                    else:
                        token_components = 1
                elif auth == 'service-integrated':
                    security_score = 3  # Good: Cognito-backed
                    if arch == 'faas':
                        token_components = 6  # All functions verify
                    elif arch == 'microservices':
                        token_components = 5  # All services verify
                    else:
                        token_components = 1
                elif auth == 'service-integrated-manual':
                    security_score = 2  # Moderate: manual implementation
                    if arch == 'faas':
                        token_components = 6
                    elif arch == 'microservices':
                        token_components = 5
                    else:
                        token_components = 1

                decision_rows.append({
                    'architecture': arch,
                    'auth_strategy': auth,
                    'hw': hw,
                    'p50': auth_row['p50'],
                    'p95': auth_row['p95'],
                    'p99': auth_row['p99'],
                    'delta_p99': auth_row['p99'] - none_row['p99'],
                    'total_requests': auth_row['total_requests'],
                    'error_rate': auth_row['error_rate'],
                    'security_score': security_score,
                    'token_exposure_components': token_components,
                })

    decision_df = pd.DataFrame(decision_rows)

    if decision_df.empty:
        print("No data for decision framework")
        return

    decision_df.to_csv(f"{PLOT_DIR}/decision_matrix.csv", index=False)
    print(f"Saved: {PLOT_DIR}/decision_matrix.csv")

    # 3. Print decision matrix
    print("\n--- DECISION MATRIX ---")
    print(f"{'Arch':>15s} {'Auth':>20s} {'HW':>6s} {'P99':>8s} {'dP99':>8s} "
          f"{'Err%':>6s} {'SecScore':>8s} {'TokComp':>7s} {'TotalReqs':>10s}")
    for _, r in decision_df.sort_values(['architecture', 'hw', 'auth_strategy']).iterrows():
        print(f"{r['architecture']:>15s} {AUTH_SHORT.get(r['auth_strategy'], r['auth_strategy']):>20s} "
              f"{r['hw']:>6s} {r['p99']:>8.1f} {r['delta_p99']:>+8.1f} "
              f"{r['error_rate']:>5.1f}% {r['security_score']:>8.0f} {r['token_exposure_components']:>7.0f} "
              f"{r['total_requests']:>10,}")

    # --- PLOT 1: Performance vs Security tradeoff ---
    fig, ax = plt.subplots(figsize=(12, 8))
    arch_markers = {'faas': 'o', 'microservices': 's', 'monolith': '^'}
    auth_colors_map = {
        'none': '#95a5a6', 'service-integrated': '#3498db',
        'service-integrated-manual': '#e74c3c', 'edge': '#2ecc71'
    }

    # Filter to auth strategies only (not none)
    auth_only = decision_df[decision_df['auth_strategy'] != 'none']
    for _, r in auth_only.iterrows():
        ax.scatter(
            r['delta_p99'],
            r['security_score'],
            marker=arch_markers.get(r['architecture'], 'o'),
            color=auth_colors_map.get(r['auth_strategy'], '#999'),
            s=max(50, min(300, r['total_requests'] / 1000)),
            alpha=0.7, edgecolors='black', linewidths=0.5
        )
        ax.annotate(f"{r['architecture'][:3]}/{r['hw']}",
                   (r['delta_p99'], r['security_score']),
                   textcoords="offset points", xytext=(5, 5), fontsize=7)

    ax.set_xlabel('$\\Delta_{Auth}$ P99 (ms) — lower is better', fontsize=12)
    ax.set_ylabel('Security Score — higher is better', fontsize=12)
    ax.set_title('Performance-Security Tradeoff\n(bubble size = total requests processed)',
                 fontsize=14, fontweight='bold')
    ax.set_yticks([1, 2, 3, 4])
    ax.set_yticklabels(['1: Low', '2: Moderate', '3: Good', '4: Best'])
    ax.axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    ax.grid(alpha=0.3)

    # Highlight ideal quadrant
    ax.axhspan(3, 4.5, xmin=0, xmax=0.5, alpha=0.05, color='green')
    ax.text(ax.get_xlim()[0] + 10, 3.8, 'Ideal: low overhead,\nhigh security',
            fontsize=9, style='italic', color='green')

    # Legend
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    color_legend = [Patch(facecolor=c, label=AUTH_SHORT.get(a, a))
                   for a, c in auth_colors_map.items() if a != 'none']
    marker_legend = [Line2D([0], [0], marker=m, color='gray', markersize=8, linestyle='', label=a)
                    for a, m in arch_markers.items()]
    ax.legend(handles=color_legend + marker_legend, fontsize=9, loc='lower right')

    plt.tight_layout()
    path = f"{PLOT_DIR}/decision_framework_scatter.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"\nSaved: {path}")
    plt.close()

    # --- PLOT 2: Grouped comparison table visualization ---
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = decision_df[decision_df['architecture'] == arch]
        if arch_data.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        # Group by hw tier, show delta_p99 for each auth strategy
        hw_tiers = sorted(arch_data['hw'].unique(),
                         key=lambda x: int(x.replace('MB', '')) if 'MB' in x else
                         {'S': 1, 'M': 2, 'L': 3, 'XL': 4}.get(x, 0))

        x = np.arange(len(hw_tiers))
        width = 0.25
        auth_list = [a for a in ['service-integrated', 'service-integrated-manual', 'edge']
                    if a in arch_data['auth_strategy'].values]

        for i, auth in enumerate(auth_list):
            vals = []
            for hw in hw_tiers:
                match = arch_data[(arch_data['auth_strategy'] == auth) & (arch_data['hw'] == hw)]
                vals.append(match.iloc[0]['delta_p99'] if not match.empty else 0)
            offset = (i - len(auth_list) / 2 + 0.5) * width
            ax.bar(x + offset, vals, width,
                  label=AUTH_SHORT.get(auth, auth),
                  color=auth_colors_map.get(auth, '#999'), alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels(hw_tiers, fontsize=9)
        ax.set_xlabel('Hardware Tier')
        ax.set_ylabel('$\\Delta_{Auth}$ P99 (ms)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.axhline(y=0, color='black', linewidth=0.5)
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('Decision Framework: Auth Overhead per Configuration',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/decision_framework_bars.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # --- Summary recommendations ---
    print("\n--- RECOMMENDATIONS ---")
    for arch in ['faas', 'microservices', 'monolith']:
        arch_auth = auth_only[auth_only['architecture'] == arch]
        if arch_auth.empty:
            continue

        # Find best balance: low overhead + high security
        arch_auth = arch_auth.copy()
        arch_auth['score'] = arch_auth['security_score'] * 100 - abs(arch_auth['delta_p99'])
        best_combo = arch_auth.sort_values('score', ascending=False).iloc[0]
        print(f"\n{arch.upper()}:")
        print(f"  Recommended: {AUTH_SHORT.get(best_combo['auth_strategy'], best_combo['auth_strategy'])} "
              f"({best_combo['hw']})")
        print(f"  DeltaAuth P99: {best_combo['delta_p99']:+.1f}ms, "
              f"Security: {best_combo['security_score']:.0f}/4, "
              f"Error rate: {best_combo['error_rate']:.1f}%")


if __name__ == '__main__':
    main()
