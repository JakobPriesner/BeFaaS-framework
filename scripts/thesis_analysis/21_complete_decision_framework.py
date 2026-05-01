#!/usr/bin/env python3
"""
21 — Complete Decision Framework (RQ4)
Synthesizes performance (ΔAuth, throughput), predictability (CoV, tail ratio),
error resilience, and cost into a multi-dimensional decision matrix.
Produces Pareto-optimal configurations and scenario-based recommendations.
Outputs: decision_matrix_complete.csv, pareto_frontier.pdf,
         scenario_recommendations.csv, radar_comparison.pdf
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


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    return {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(float(cpu), f"{cpu}v")


def main():
    print("=" * 70)
    print("21 — COMPLETE DECISION FRAMEWORK (RQ4)")
    print("=" * 70)

    # ── 1. Gather all metrics per configuration ──
    # Latency (Baseline P50, P99)
    latency = query_df(f"""
        SELECT
            e.architecture, e.auth_strategy,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE r.is_error) AS n_errors,
            COUNT(*) FILTER (WHERE r.status_code >= 500) AS n_5xx,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99,
            AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_lat,
            STDDEV(r.latency_ms) FILTER (WHERE NOT r.is_error) AS std_lat
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.phase_name = 'Baseline'
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.architecture, e.auth_strategy, e.ram_in_mb, cpu
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 1000
    """)

    for col in ['p50', 'p99', 'mean_lat', 'std_lat']:
        latency[col] = latency[col].astype(float)

    latency['hw'] = latency.apply(lambda r: hw_label(r['architecture'], r['ram_in_mb'], r['cpu']), axis=1)
    latency['error_rate'] = latency['n_errors'] / latency['total'] * 100
    latency['_5xx_rate'] = latency['n_5xx'] / latency['total'] * 100
    latency['cov'] = latency['std_lat'] / latency['mean_lat'] * 100

    # ΔAuth (delta vs none)
    config_rows = []
    for (arch, ram), grp in latency.groupby(['architecture', 'ram_in_mb']):
        none_data = grp[grp['auth_strategy'] == 'none']
        if none_data.empty:
            continue
        none_p50 = none_data['p50'].mean()
        none_p99 = none_data['p99'].mean()
        none_cov = none_data['cov'].mean()

        for _, r in grp.iterrows():
            auth_label = AUTH_SHORT.get(r['auth_strategy'], r['auth_strategy'])
            delta_p99 = r['p99'] - none_p99 if r['auth_strategy'] != 'none' else 0

            # Security score (qualitative, based on thesis security model)
            # Higher = more secure
            security_scores = {
                'none': 0,
                'edge': 3,           # Single verification point, minimal token exposure
                'service-integrated': 4,  # Per-service verification, defense in depth
                'service-integrated-manual': 4,  # Same as integrated but no external dependency
            }
            security = security_scores.get(r['auth_strategy'], 0)

            # Token exposure score (lower = better)
            # Based on number of components processing tokens
            token_exposure = {
                'none': 0,
                'edge': 1,            # Only edge function sees token
                'service-integrated': {'faas': 6, 'microservices': 5, 'monolith': 1}.get(arch, 3),
                'service-integrated-manual': {'faas': 6, 'microservices': 5, 'monolith': 1}.get(arch, 3),
            }
            exposure = token_exposure.get(r['auth_strategy'], 0)
            if isinstance(exposure, dict):
                exposure = exposure.get(arch, 3)

            config_rows.append({
                'architecture': arch,
                'hw': r['hw'],
                'ram_in_mb': ram,
                'auth': auth_label,
                'auth_strategy': r['auth_strategy'],
                'p50': r['p50'],
                'p99': r['p99'],
                'delta_p99': delta_p99,
                'cov': r['cov'],
                'error_rate': r['error_rate'],
                '_5xx_rate': r['_5xx_rate'],
                'security_score': security,
                'token_exposure': exposure,
                'n_success': r['n_success'],
            })

    config_df = pd.DataFrame(config_rows)

    # Add throughput from full experiment
    throughput = query_df(f"""
        SELECT
            e.architecture, e.auth_strategy, e.ram_in_mb,
            COUNT(*) AS total_reqs,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS successful_reqs
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.architecture, e.auth_strategy, e.ram_in_mb
    """)
    throughput_avg = throughput.groupby(['architecture', 'auth_strategy', 'ram_in_mb']).agg(
        total_throughput=('total_reqs', 'mean'),
        successful_throughput=('successful_reqs', 'mean')
    ).reset_index()

    config_df = config_df.merge(
        throughput_avg, on=['architecture', 'auth_strategy', 'ram_in_mb'], how='left')

    # Add cost data if available
    cost = query_df(f"""
        SELECT
            e.architecture, e.auth_strategy, e.ram_in_mb,
            COALESCE(p.lambda_total_cost, 0) +
            COALESCE(p.api_gw_cost, 0) +
            COALESCE(p.fargate_total_cost, 0) +
            COALESCE(p.alb_total_cost, 0) +
            COALESCE(p.redis_total_cost, 0) AS total_cost
        FROM experiments e
        JOIN pricing p ON p.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
    """)
    if not cost.empty:
        cost['total_cost'] = cost['total_cost'].astype(float)
        cost_avg = cost.groupby(['architecture', 'auth_strategy', 'ram_in_mb']).agg(
            avg_cost=('total_cost', 'mean')).reset_index()
        config_df = config_df.merge(cost_avg, on=['architecture', 'auth_strategy', 'ram_in_mb'], how='left')
    else:
        config_df['avg_cost'] = np.nan

    # Cost per 1M successful requests
    config_df['cost_per_1M'] = np.where(
        config_df['successful_throughput'] > 0,
        config_df['avg_cost'] / config_df['successful_throughput'] * 1_000_000,
        np.nan
    )

    config_df.to_csv(f"{PLOT_DIR}/decision_matrix_complete.csv", index=False)
    print(f"Saved: {PLOT_DIR}/decision_matrix_complete.csv")

    # ── 2. Print decision matrix ──
    print("\n--- DECISION MATRIX (representative HW per architecture) ---")
    # Pick representative HW: FaaS 512MB, MS L, Mono L
    for arch, hw_pick in [('faas', '512MB'), ('microservices', 'L'), ('monolith', 'L')]:
        sub = config_df[(config_df['architecture'] == arch) & (config_df['hw'] == hw_pick)]
        if sub.empty:
            # Fallback to largest available
            sub = config_df[config_df['architecture'] == arch]
            if sub.empty:
                continue
            hw_pick = sub['hw'].iloc[0]
            sub = config_df[(config_df['architecture'] == arch) & (config_df['hw'] == hw_pick)]

        print(f"\n  {arch.upper()} ({hw_pick}):")
        print(f"  {'Auth':>8s} | {'P50':>7s} | {'P99':>7s} | {'ΔP99':>7s} | "
              f"{'CoV':>5s} | {'Err%':>5s} | {'SecScore':>8s} | {'TokenExp':>8s} | {'Cost/1M':>8s}")
        print(f"  {'-'*8} | {'-'*7} | {'-'*7} | {'-'*7} | "
              f"{'-'*5} | {'-'*5} | {'-'*8} | {'-'*8} | {'-'*8}")
        for _, r in sub.sort_values('p99').iterrows():
            cost_str = f"${r['cost_per_1M']:.2f}" if pd.notna(r['cost_per_1M']) else 'N/A'
            print(f"  {r['auth']:>8s} | {r['p50']:>6.0f}ms | {r['p99']:>6.0f}ms | {r['delta_p99']:>+6.0f}ms | "
                  f"{r['cov']:>4.0f}% | {r['error_rate']:>4.1f}% | {r['security_score']:>8d} | "
                  f"{r['token_exposure']:>8d} | {cost_str:>8s}")

    # ── 3. Multi-objective Pareto analysis ──
    # Minimize: P99 latency, cost. Maximize: security, throughput.
    # Only include auth != none
    auth_configs = config_df[config_df['auth_strategy'] != 'none'].copy()

    if not auth_configs.empty:
        from matplotlib.lines import Line2D

        AUTH_MARKERS_P = {'Cognito': 's', 'Manual': '^', 'Edge': 'D'}
        # Use ΔP99 (auth overhead) instead of absolute P99 for clearer comparison
        fig, axes = plt.subplots(1, 2, figsize=(16, 7))

        # Plot 1: ΔP99 vs Security Score (grouped bar-like scatter)
        ax = axes[0]
        for _, r in auth_configs.iterrows():
            color = ARCH_COLORS.get(r['architecture'], '#999')
            marker = AUTH_MARKERS_P.get(r['auth'], 'o')
            ax.scatter(r['delta_p99'], r['security_score'] + np.random.uniform(-0.15, 0.15),
                       c=color, marker=marker, s=100, alpha=0.75,
                       edgecolors='black', linewidths=0.5)

        ax.set_xlabel('ΔAuth P99 (ms) — lower is better →')
        ax.set_ylabel('Security Score — higher is better →')
        ax.set_title('Auth Overhead vs Security', fontweight='bold')
        ax.set_yticks([0, 1, 2, 3, 4])
        ax.set_yticklabels(['0 (None)', '1', '2', '3 (Edge)', '4 (Cognito/Manual)'])
        ax.grid(alpha=0.3)
        ax.axvline(x=0, color='black', linewidth=0.5, alpha=0.3)

        # Plot 2: ΔP99 vs Token Exposure
        ax = axes[1]
        for _, r in auth_configs.iterrows():
            color = ARCH_COLORS.get(r['architecture'], '#999')
            marker = AUTH_MARKERS_P.get(r['auth'], 'o')
            ax.scatter(r['delta_p99'], r['token_exposure'] + np.random.uniform(-0.15, 0.15),
                       c=color, marker=marker, s=100, alpha=0.75,
                       edgecolors='black', linewidths=0.5)

        ax.set_xlabel('ΔAuth P99 (ms) — lower is better →')
        ax.set_ylabel('Token Exposure (components) — lower is better →')
        ax.set_title('Auth Overhead vs Token Exposure', fontweight='bold')
        ax.grid(alpha=0.3)
        ax.axvline(x=0, color='black', linewidth=0.5, alpha=0.3)

        # Combined legend: colors for architecture, markers for auth
        arch_legend = [Line2D([0], [0], marker='o', color='w', markerfacecolor=c,
                              markersize=10, label=a) for a, c in ARCH_COLORS.items()]
        auth_legend = [Line2D([0], [0], marker=m, color='w', markerfacecolor='gray',
                              markersize=10, label=a) for a, m in AUTH_MARKERS_P.items()]
        for a in axes:
            a.legend(handles=arch_legend + auth_legend, fontsize=8, ncol=2)

        fig.suptitle('Multi-Objective Decision Space\n'
                     '(Ideal: low overhead, high security/low exposure)',
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/pareto_frontier.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"\nSaved: {path}")
        plt.close()

    # ── 4. Radar chart comparison ──
    # Compare representative configs across dimensions
    radar_configs = []
    for arch, hw_pick in [('faas', '512MB'), ('microservices', 'L'), ('monolith', 'L')]:
        for auth in ['Cognito', 'Edge']:
            match = config_df[(config_df['architecture'] == arch) &
                              (config_df['hw'] == hw_pick) &
                              (config_df['auth'] == auth)]
            if not match.empty:
                radar_configs.append(match.iloc[0])

    if len(radar_configs) >= 2:
        dimensions = ['Latency (inv)', 'Throughput', 'Security', 'Predictability (inv CoV)', 'Error Resilience']
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        angles = np.linspace(0, 2 * np.pi, len(dimensions), endpoint=False).tolist()
        angles += angles[:1]

        for cfg in radar_configs:
            # Normalize each dimension to 0-1 (higher = better)
            max_p99 = config_df['p99'].max()
            max_throughput = config_df['successful_throughput'].max()
            max_cov = config_df['cov'].max()

            values = [
                1 - cfg['p99'] / max_p99 if max_p99 > 0 else 0,  # Inverted latency
                cfg['successful_throughput'] / max_throughput if max_throughput > 0 else 0,
                cfg['security_score'] / 5,
                1 - cfg['cov'] / max_cov if max_cov > 0 else 0,  # Inverted CoV
                1 - cfg['error_rate'] / 100,
            ]
            values += values[:1]

            color = ARCH_COLORS.get(cfg['architecture'], '#999')
            label = f"{cfg['architecture']}/{cfg['auth']}/{cfg['hw']}"
            ax.plot(angles, values, 'o-', label=label, color=color, linewidth=2, alpha=0.7)
            ax.fill(angles, values, color=color, alpha=0.1)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(dimensions, fontsize=9)
        ax.set_ylim(0, 1)
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=7)
        ax.set_title('Multi-Dimensional Configuration Comparison\n(higher = better)',
                      fontweight='bold', pad=20)

        plt.tight_layout()
        path = f"{PLOT_DIR}/radar_comparison.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # ── 5. Scenario-based recommendations ──
    print("\n" + "=" * 70)
    print("SCENARIO-BASED RECOMMENDATIONS:")
    print("=" * 70)

    auth_only = config_df[config_df['auth_strategy'] != 'none']

    scenarios = {
        'Latency-critical (<200ms P99)': lambda df: df[df['p99'] < 200].sort_values('p99'),
        'Security-critical (max security)': lambda df: df.sort_values('security_score', ascending=False),
        'Cost-effective (min cost/1M)': lambda df: df.dropna(subset=['cost_per_1M']).sort_values('cost_per_1M'),
        'Predictable (min CoV)': lambda df: df.sort_values('cov'),
        'Resilient (min error rate)': lambda df: df.sort_values('error_rate'),
        'High throughput': lambda df: df.sort_values('successful_throughput', ascending=False),
    }

    rec_rows = []
    for scenario, selector in scenarios.items():
        selected = selector(auth_only)
        if selected.empty:
            print(f"\n  {scenario}: No configurations match")
            continue

        best = selected.iloc[0]
        print(f"\n  {scenario}:")
        print(f"    → {best['architecture']}/{best['auth']}/{best['hw']} "
              f"(P99={best['p99']:.0f}ms, Security={best['security_score']}, "
              f"CoV={best['cov']:.0f}%, Err={best['error_rate']:.1f}%)")

        rec_rows.append({
            'scenario': scenario,
            'architecture': best['architecture'],
            'auth': best['auth'],
            'hw': best['hw'],
            'p99': best['p99'],
            'security_score': best['security_score'],
            'cov': best['cov'],
            'error_rate': best['error_rate'],
        })

    if rec_rows:
        rec_df = pd.DataFrame(rec_rows)
        rec_df.to_csv(f"{PLOT_DIR}/scenario_recommendations.csv", index=False)
        print(f"\nSaved: {PLOT_DIR}/scenario_recommendations.csv")


if __name__ == '__main__':
    main()
