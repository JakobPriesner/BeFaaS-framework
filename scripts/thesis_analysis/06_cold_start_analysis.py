#!/usr/bin/env python3
"""
06 - Cold Start Analysis (FaaS-specific)
Analyzes Lambda cold start frequency, duration, and impact on auth overhead.
Outputs: cold_start_analysis.pdf, cold_start_impact.pdf
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
    print("06 - COLD START ANALYSIS")
    print("=" * 70)

    # 1. Cold start overview per experiment
    cs_overview = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.auth_strategy,
            e.ram_in_mb,
            e.password_hash_algorithm AS hash_algo,
            COUNT(*) AS total_invocations,
            COUNT(CASE WHEN l.is_cold_start THEN 1 END) AS cold_starts,
            AVG(l.init_duration_ms) FILTER (WHERE l.is_cold_start) AS avg_init_ms,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY l.init_duration_ms)
                FILTER (WHERE l.is_cold_start) AS p50_init_ms,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY l.init_duration_ms)
                FILTER (WHERE l.is_cold_start) AS p95_init_ms,
            AVG(l.duration_ms) FILTER (WHERE l.is_cold_start) AS avg_cold_duration_ms,
            AVG(l.duration_ms) FILTER (WHERE NOT l.is_cold_start) AS avg_warm_duration_ms
        FROM experiments e
        JOIN lambda_executions l ON l.experiment_id = e.id
        WHERE e.architecture = 'faas'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.auth_strategy, e.ram_in_mb, e.password_hash_algorithm
        HAVING COUNT(*) > 1000
        ORDER BY e.id
    """)

    cs_overview['cold_pct'] = (cs_overview['cold_starts'] / cs_overview['total_invocations'] * 100).round(2)
    cs_overview['cold_overhead'] = cs_overview['avg_cold_duration_ms'] - cs_overview['avg_warm_duration_ms']
    cs_overview['algo'] = cs_overview['hash_algo'].fillna('N/A')

    print(f"\nFaaS experiments with cold start data: {len(cs_overview)}")
    print(f"\n{'Exp':>4s} {'Auth':>25s} {'RAM':>6s} {'Algo':>10s} "
          f"{'Total':>10s} {'Cold':>6s} {'%':>6s} {'InitP50':>8s} {'InitP95':>8s} {'ColdDur':>8s} {'WarmDur':>8s}")
    for _, r in cs_overview.iterrows():
        print(f"{r['experiment_id']:>4.0f} {r['auth_strategy']:>25s} {r['ram_in_mb']:>6.0f} {r['algo']:>10s} "
              f"{r['total_invocations']:>10,} {r['cold_starts']:>6.0f} {r['cold_pct']:>5.1f}% "
              f"{r['p50_init_ms']:>8.1f} {r['p95_init_ms']:>8.1f} "
              f"{r['avg_cold_duration_ms']:>8.1f} {r['avg_warm_duration_ms']:>8.1f}")

    # 2. Cold start per function
    cs_func = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.auth_strategy,
            e.ram_in_mb,
            l.function_name,
            COUNT(*) AS invocations,
            COUNT(CASE WHEN l.is_cold_start THEN 1 END) AS cold_starts,
            AVG(l.init_duration_ms) FILTER (WHERE l.is_cold_start) AS avg_init_ms,
            AVG(l.duration_ms) FILTER (WHERE l.is_cold_start) AS avg_cold_dur,
            AVG(l.duration_ms) FILTER (WHERE NOT l.is_cold_start) AS avg_warm_dur,
            AVG(l.max_memory_used_mb) AS avg_mem_used
        FROM experiments e
        JOIN lambda_executions l ON l.experiment_id = e.id
        WHERE e.architecture = 'faas'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.auth_strategy, e.ram_in_mb, l.function_name
        HAVING COUNT(CASE WHEN l.is_cold_start THEN 1 END) > 0
        ORDER BY e.id, l.function_name
    """)

    # --- PLOT 1: Cold start init duration by auth strategy ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Left: Init duration distribution
    for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
        subset = cs_overview[cs_overview['auth_strategy'] == auth]
        if subset.empty:
            continue
        hw_tiers = sorted(subset['ram_in_mb'].unique())
        ax1.plot(hw_tiers, [subset[subset['ram_in_mb'] == h]['p50_init_ms'].mean() for h in hw_tiers],
                'o-', label=f"{AUTH_SHORT.get(auth, auth)} (P50 init)",
                color=AUTH_COLORS.get(auth, '#999'), linewidth=2)

    ax1.set_xlabel('Lambda Memory (MB)')
    ax1.set_ylabel('Cold Start Init Duration (ms)')
    ax1.set_title('Cold Start Init Duration by Auth Strategy', fontweight='bold')
    ax1.legend(fontsize=9)
    ax1.grid(alpha=0.3)

    # Right: Cold vs Warm duration comparison
    for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
        subset = cs_overview[cs_overview['auth_strategy'] == auth]
        if subset.empty:
            continue
        hw_tiers = sorted(subset['ram_in_mb'].unique())
        cold_vals = [subset[subset['ram_in_mb'] == h]['avg_cold_duration_ms'].mean() for h in hw_tiers]
        warm_vals = [subset[subset['ram_in_mb'] == h]['avg_warm_duration_ms'].mean() for h in hw_tiers]
        ax2.plot(hw_tiers, cold_vals, 'o--',
                label=f"{AUTH_SHORT.get(auth, auth)} (cold)",
                color=AUTH_COLORS.get(auth, '#999'), linewidth=2)
        ax2.plot(hw_tiers, warm_vals, 's-',
                label=f"{AUTH_SHORT.get(auth, auth)} (warm)",
                color=AUTH_COLORS.get(auth, '#999'), linewidth=1.5, alpha=0.6)

    ax2.set_xlabel('Lambda Memory (MB)')
    ax2.set_ylabel('Handler Duration (ms)')
    ax2.set_title('Cold vs Warm Handler Duration', fontweight='bold')
    ax2.legend(fontsize=7, ncol=2)
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    path = f"{PLOT_DIR}/cold_start_analysis.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"\nSaved: {path}")
    plt.close()

    # --- PLOT 2: Per-function cold start breakdown ---
    if not cs_func.empty:
        # Pick a representative experiment (e.g., 512MB, none auth)
        rep_exp = cs_overview[
            (cs_overview['ram_in_mb'] == 512) & (cs_overview['auth_strategy'] == 'none')
        ]
        if rep_exp.empty:
            rep_exp = cs_overview.head(1)
        rep_id = rep_exp.iloc[0]['experiment_id']

        func_data = cs_func[cs_func['experiment_id'] == rep_id].sort_values('cold_starts', ascending=True)

        if not func_data.empty:
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, max(4, len(func_data) * 0.3)))

            ax1.barh(func_data['function_name'], func_data['cold_starts'], color='#e74c3c', alpha=0.7)
            ax1.set_xlabel('Cold Start Count')
            ax1.set_title(f'Cold Starts per Function (Exp {rep_id:.0f})')
            ax1.grid(axis='x', alpha=0.3)

            ax2.barh(func_data['function_name'], func_data['avg_init_ms'], color='#3498db', alpha=0.7)
            ax2.set_xlabel('Avg Init Duration (ms)')
            ax2.set_title('Avg Cold Start Init Duration')
            ax2.grid(axis='x', alpha=0.3)

            plt.tight_layout()
            path = f"{PLOT_DIR}/cold_start_per_function.pdf"
            fig.savefig(path, bbox_inches='tight')
            print(f"Saved: {path}")
            plt.close()

    # --- PLOT 3: Cold start impact on auth endpoints ---
    print("\n--- AUTH IMPACT ON COLD STARTS ---")
    auth_funcs = ['checkout', 'getcart', 'addcartitem', 'emptycart', 'payment', 'cartkvstorage']
    noauth_funcs = ['frontend', 'listproducts', 'getproduct', 'currency', 'getads']

    for _, row in cs_overview.iterrows():
        exp_id = row['experiment_id']
        exp_func = cs_func[cs_func['experiment_id'] == exp_id]
        if exp_func.empty:
            continue

        auth_init = exp_func[exp_func['function_name'].isin(auth_funcs)]['avg_init_ms'].mean()
        noauth_init = exp_func[exp_func['function_name'].isin(noauth_funcs)]['avg_init_ms'].mean()
        diff = auth_init - noauth_init if not (np.isnan(auth_init) or np.isnan(noauth_init)) else 0

        if abs(diff) > 10:
            print(f"  Exp {exp_id:.0f} ({row['auth_strategy']}, {row['ram_in_mb']:.0f}MB): "
                  f"auth_funcs init={auth_init:.1f}ms, other={noauth_init:.1f}ms, diff={diff:+.1f}ms")

    cs_overview.to_csv(f"{PLOT_DIR}/cold_start_overview.csv", index=False)
    print(f"\nSaved: {PLOT_DIR}/cold_start_overview.csv")


if __name__ == '__main__':
    main()
