#!/usr/bin/env python3
"""
19 — Cost-Performance Analysis (RQ4)
Computes cost per 1M requests, cost efficiency, and cost-latency trade-offs
for each architecture × auth configuration.
Outputs: cost_per_request.csv, cost_latency_tradeoff.pdf,
         cost_comparison_bars.pdf, cost_auth_overhead.csv
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
AUTH_MARKERS = {'None': 'o', 'Cognito': 's', 'Manual': '^', 'Edge': 'D'}


def main():
    print("=" * 70)
    print("19 — COST-PERFORMANCE ANALYSIS (RQ4)")
    print("=" * 70)

    # ── 1. Get pricing data joined with experiment info ──
    pricing = query_df(f"""
        SELECT
            e.id, e.architecture, e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            p.lambda_total_cost,
            p.api_gw_cost,
            p.fargate_total_cost,
            p.alb_total_cost,
            p.redis_total_cost,
            p.cognito_cost,
            COALESCE(p.lambda_total_cost, 0) +
            COALESCE(p.api_gw_cost, 0) +
            COALESCE(p.fargate_total_cost, 0) +
            COALESCE(p.alb_total_cost, 0) +
            COALESCE(p.redis_total_cost, 0) +
            COALESCE(p.cognito_cost, 0) AS total_cost
        FROM experiments e
        JOIN pricing p ON p.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
    """)

    # Get request counts and latency for each experiment
    perf = query_df(f"""
        SELECT
            e.id,
            COUNT(*) AS total_requests,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS successful_requests,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.id
        HAVING COUNT(*) > 50000
    """)

    for col in ['p50', 'p99']:
        perf[col] = perf[col].astype(float)

    merged = pricing.merge(perf, on='id', how='inner')
    merged['total_cost'] = merged['total_cost'].astype(float)

    # Cost per 1M successful requests (normalized to 1h benchmark)
    merged['cost_per_1M'] = (merged['total_cost'] / merged['successful_requests'] * 1_000_000)
    merged['cost_per_1M'] = merged['cost_per_1M'].replace([np.inf, -np.inf], np.nan)

    # ── 2. Aggregate by config ──
    def hw_label(row):
        if row['architecture'] == 'faas':
            return f"{row['ram_in_mb']}MB"
        return {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(float(row['cpu']), f"{row['cpu']}v")

    merged = merged[merged['ram_in_mb'] != 1796]
    merged['hw'] = merged.apply(hw_label, axis=1)
    merged['auth_label'] = merged['auth_strategy'].map(AUTH_SHORT)

    cost_avg = merged.groupby(['architecture', 'auth_strategy', 'auth_label', 'hw', 'ram_in_mb']).agg(
        mean_total_cost=('total_cost', 'mean'),
        mean_cost_per_1M=('cost_per_1M', 'mean'),
        mean_p50=('p50', 'mean'),
        mean_p99=('p99', 'mean'),
        mean_requests=('successful_requests', 'mean'),
        n_experiments=('id', 'nunique'),
        lambda_cost=('lambda_total_cost', lambda x: x.dropna().mean()),
        fargate_cost=('fargate_total_cost', lambda x: x.dropna().mean()),
        alb_cost=('alb_total_cost', lambda x: x.dropna().mean()),
        apigw_cost=('api_gw_cost', lambda x: x.dropna().mean()),
        redis_cost=('redis_total_cost', lambda x: x.dropna().mean()),
    ).reset_index()

    cost_avg.to_csv(f"{PLOT_DIR}/cost_per_request.csv", index=False)
    print(f"Saved: {PLOT_DIR}/cost_per_request.csv")

    print("\n--- COST PER 1M REQUESTS ---")
    for arch in ['faas', 'microservices', 'monolith']:
        arch_data = cost_avg[cost_avg['architecture'] == arch]
        if arch_data.empty:
            continue
        print(f"\n  {arch.upper()}:")
        for _, r in arch_data.sort_values(['hw', 'auth_label']).iterrows():
            print(f"    {r['hw']:>5s} / {r['auth_label']:>8s}: "
                  f"${r['mean_cost_per_1M']:.2f}/1M reqs, "
                  f"total=${r['mean_total_cost']:.2f}, "
                  f"P99={r['mean_p99']:.0f}ms, "
                  f"{r['mean_requests']:,.0f} reqs")

    # ── 3. Cost-latency scatter (Pareto frontier) ──
    from matplotlib.lines import Line2D

    # Exclude extreme outliers (S-tier containers with >5000ms P99)
    # so the useful region is visible
    X_CLIP = 8000  # ms
    plot_data = cost_avg[cost_avg['mean_p99'] <= X_CLIP].copy()
    n_excluded = len(cost_avg) - len(plot_data)

    fig, ax = plt.subplots(figsize=(12, 7))

    for _, r in plot_data.iterrows():
        color = ARCH_COLORS.get(r['architecture'], '#999')
        marker = AUTH_MARKERS.get(r['auth_label'], 'o')
        ax.scatter(r['mean_p99'], r['mean_cost_per_1M'],
                   c=color, marker=marker, s=120, alpha=0.85,
                   edgecolors='black', linewidths=0.5)

    # Pareto frontier (on clipped data)
    points = plot_data[['mean_p99', 'mean_cost_per_1M']].dropna().values
    if len(points) > 0:
        pareto = []
        for i, (lat, cost) in enumerate(points):
            dominated = False
            for j, (lat2, cost2) in enumerate(points):
                if i != j and lat2 <= lat and cost2 <= cost and (lat2 < lat or cost2 < cost):
                    dominated = True
                    break
            if not dominated:
                pareto.append(i)

        if pareto:
            pareto_points = points[pareto]
            pareto_sorted = pareto_points[pareto_points[:, 0].argsort()]
            ax.plot(pareto_sorted[:, 0], pareto_sorted[:, 1], 'k--', alpha=0.4,
                    linewidth=1.5, label='Pareto frontier')

    # Legend
    legend_elements = []
    for arch, color in ARCH_COLORS.items():
        legend_elements.append(Line2D([0], [0], marker='o', color='w',
                                       markerfacecolor=color, markersize=10, label=arch))
    for auth, marker in AUTH_MARKERS.items():
        legend_elements.append(Line2D([0], [0], marker=marker, color='w',
                                       markerfacecolor='gray', markersize=10, label=auth))
    legend_elements.append(Line2D([0], [0], linestyle='--', color='black',
                                   alpha=0.4, label='Pareto frontier'))
    ax.legend(handles=legend_elements, loc='upper right', fontsize=9)

    ax.set_xlabel('P99 Latency (ms)')
    ax.set_ylabel('Cost per 1M Requests ($)')
    excluded_note = f'\n({n_excluded} configs with P99 > {X_CLIP}ms excluded)' if n_excluded else ''
    ax.set_title(f'Cost-Latency Trade-off (Pareto Analysis)\n'
                 f'Lower-left is better{excluded_note}', fontweight='bold')
    ax.grid(alpha=0.3)
    ax.set_xlim(left=-50)

    plt.tight_layout()
    path = f"{PLOT_DIR}/cost_latency_tradeoff.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"\nSaved: {path}")
    plt.close()

    # ── 4. Cost comparison bars ──
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = cost_avg[cost_avg['architecture'] == arch].sort_values('mean_cost_per_1M')
        if arch_data.empty:
            ax.set_title(f'{arch} (no pricing data)')
            continue

        labels = [f"{r['auth_label']}\n{r['hw']}" for _, r in arch_data.iterrows()]
        values = arch_data['mean_cost_per_1M'].values
        colors = [ARCH_COLORS[arch]] * len(values)

        bars = ax.barh(labels, values, color=colors, alpha=0.85)
        ax.set_xlabel('Cost per 1M Requests ($)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.grid(axis='x', alpha=0.3)

        for bar, val in zip(bars, values):
            ax.text(bar.get_width() + max(values) * 0.02, bar.get_y() + bar.get_height()/2,
                    f'${val:.2f}', va='center', fontsize=8)

    fig.suptitle('Cost per 1M Successful Requests by Configuration\n'
                 '(excluding argon2id)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/cost_comparison_bars.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # ── 5. Auth cost overhead: ΔCost per auth strategy ──
    cost_delta_rows = []
    for (arch, hw), grp in cost_avg.groupby(['architecture', 'hw']):
        none_row = grp[grp['auth_strategy'] == 'none']
        if none_row.empty:
            continue
        none_cost = none_row.iloc[0]['mean_cost_per_1M']
        none_total = none_row.iloc[0]['mean_total_cost']
        for _, r in grp.iterrows():
            if r['auth_strategy'] == 'none':
                continue
            cost_delta_rows.append({
                'architecture': arch,
                'hw': hw,
                'auth': r['auth_label'],
                'none_cost_per_1M': none_cost,
                'auth_cost_per_1M': r['mean_cost_per_1M'],
                'delta_cost_per_1M': r['mean_cost_per_1M'] - none_cost,
                'pct_cost_increase': (r['mean_cost_per_1M'] - none_cost) / none_cost * 100 if none_cost > 0 else 0,
                'none_total': none_total,
                'auth_total': r['mean_total_cost'],
                'delta_total': r['mean_total_cost'] - none_total,
            })

    if cost_delta_rows:
        cost_delta = pd.DataFrame(cost_delta_rows)
        cost_delta.to_csv(f"{PLOT_DIR}/cost_auth_overhead.csv", index=False)
        print(f"\nSaved: {PLOT_DIR}/cost_auth_overhead.csv")

        print("\n--- AUTH COST OVERHEAD ---")
        for _, r in cost_delta.sort_values('delta_cost_per_1M').iterrows():
            print(f"  {r['architecture']:>14s}/{r['hw']:>4s}/{r['auth']:>8s}: "
                  f"ΔCost = ${r['delta_cost_per_1M']:+.2f}/1M reqs ({r['pct_cost_increase']:+.1f}%) "
                  f"[total: ${r['none_total']:.2f} → ${r['auth_total']:.2f}]")

    # ── 6. Cost breakdown by component ──
    print("\n--- COST BREAKDOWN (avg per experiment) ---")
    for arch in ['faas', 'microservices', 'monolith']:
        arch_data = cost_avg[cost_avg['architecture'] == arch]
        if arch_data.empty:
            continue
        print(f"\n  {arch.upper()}:")
        for _, r in arch_data.iterrows():
            components = []
            if pd.notna(r['lambda_cost']) and r['lambda_cost'] > 0:
                components.append(f"Lambda=${r['lambda_cost']:.3f}")
            if pd.notna(r['fargate_cost']) and r['fargate_cost'] > 0:
                components.append(f"Fargate=${r['fargate_cost']:.2f}")
            if pd.notna(r['alb_cost']) and r['alb_cost'] > 0:
                components.append(f"ALB=${r['alb_cost']:.2f}")
            if pd.notna(r['apigw_cost']) and r['apigw_cost'] > 0:
                components.append(f"APIGW=${r['apigw_cost']:.3f}")
            if pd.notna(r['redis_cost']) and r['redis_cost'] > 0:
                components.append(f"Redis=${r['redis_cost']:.2f}")
            print(f"    {r['auth_label']:>8s}/{r['hw']:>4s}: "
                  f"total=${r['mean_total_cost']:.2f} ({', '.join(components)})")

    # ── 7. Key findings ──
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)

    if not cost_avg.empty:
        cheapest = cost_avg.loc[cost_avg['mean_cost_per_1M'].idxmin()]
        most_expensive = cost_avg.loc[cost_avg['mean_cost_per_1M'].idxmax()]
        print(f"  Cheapest:       {cheapest['architecture']}/{cheapest['auth_label']}/{cheapest['hw']} "
              f"at ${cheapest['mean_cost_per_1M']:.2f}/1M reqs")
        print(f"  Most expensive: {most_expensive['architecture']}/{most_expensive['auth_label']}/{most_expensive['hw']} "
              f"at ${most_expensive['mean_cost_per_1M']:.2f}/1M reqs")
        print(f"  Cost range:     {most_expensive['mean_cost_per_1M']/cheapest['mean_cost_per_1M']:.1f}×")

    if cost_delta_rows:
        print(f"\n  Auth cost overhead range:")
        print(f"    Min: {cost_delta['pct_cost_increase'].min():+.1f}%")
        print(f"    Max: {cost_delta['pct_cost_increase'].max():+.1f}%")
        print(f"    Median: {cost_delta['pct_cost_increase'].median():+.1f}%")


if __name__ == '__main__':
    main()
