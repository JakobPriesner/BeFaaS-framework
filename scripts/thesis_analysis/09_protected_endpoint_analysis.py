#!/usr/bin/env python3
"""
09 - Protected vs Unprotected Endpoint Analysis
Compares handler durations for protected (auth-required) vs unprotected endpoints.
Tests the multiplication model: k(arch) * delta_single.
Outputs: endpoint_auth_overhead.pdf, multiplication_model.pdf
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
    print("09 - PROTECTED vs UNPROTECTED ENDPOINT ANALYSIS")
    print("=" * 70)

    # 1. Handler duration: protected vs unprotected
    handler_df = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.auth_strategy,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            h.is_protected_endpoint,
            h.function_name,
            COUNT(*) AS handler_count,
            AVG(h.duration_ms) AS avg_duration,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY h.duration_ms) AS p50_handler,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY h.duration_ms) AS p95_handler,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY h.duration_ms) AS p99_handler
        FROM experiments e
        JOIN handler_events h ON h.experiment_id = e.id
        WHERE h.phase_name = 'Baseline'
          AND h.duration_ms > 0 AND h.duration_ms < 30000
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu,
                 h.is_protected_endpoint, h.function_name
        HAVING COUNT(*) > 50
        ORDER BY e.architecture, e.auth_strategy, h.function_name
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
    handler_df['hw'] = handler_df.apply(hw_label, axis=1)

    # 2. Compute delta_single: overhead per verification
    print("\n--- PER-FUNCTION AUTH OVERHEAD (delta_single) ---")
    print("Comparing handler duration: auth vs none for same function")

    delta_func_rows = []
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = handler_df[handler_df['architecture'] == arch]
        none_df = arch_df[arch_df['auth_strategy'] == 'none']

        for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
            auth_df = arch_df[arch_df['auth_strategy'] == auth]
            if auth_df.empty:
                continue

            # Match by function name and hw tier
            for hw in none_df['hw'].unique():
                none_hw = none_df[none_df['hw'] == hw]
                auth_hw = auth_df[auth_df['hw'] == hw]
                if auth_hw.empty:
                    continue

                for func in none_hw['function_name'].unique():
                    none_func = none_hw[none_hw['function_name'] == func]
                    auth_func = auth_hw[auth_hw['function_name'] == func]
                    if none_func.empty or auth_func.empty:
                        continue

                    # Average across experiments
                    none_avg = none_func['p50_handler'].mean()
                    auth_avg = auth_func['p50_handler'].mean()
                    is_protected = auth_func.iloc[0]['is_protected_endpoint']

                    delta_func_rows.append({
                        'architecture': arch,
                        'auth_strategy': auth,
                        'hw': hw,
                        'function_name': func,
                        'is_protected': is_protected,
                        'none_p50': none_avg,
                        'auth_p50': auth_avg,
                        'delta_p50': auth_avg - none_avg,
                    })

    delta_func = pd.DataFrame(delta_func_rows)
    if not delta_func.empty:
        # Print protected functions
        protected = delta_func[delta_func['is_protected']]
        unprotected = delta_func[~delta_func['is_protected']]

        print(f"\nProtected functions ({len(protected)} records):")
        if not protected.empty:
            print(f"  Avg delta_single (P50): {protected['delta_p50'].mean():.2f} ms")
            print(f"  Median delta_single:    {protected['delta_p50'].median():.2f} ms")

        print(f"\nUnprotected functions ({len(unprotected)} records):")
        if not unprotected.empty:
            print(f"  Avg delta (P50):  {unprotected['delta_p50'].mean():.2f} ms")
            print(f"  Median delta:     {unprotected['delta_p50'].median():.2f} ms")

        # --- PLOT 1: Per-function overhead ---
        for arch in delta_func['architecture'].unique():
            for auth in delta_func[delta_func['architecture'] == arch]['auth_strategy'].unique():
                subset = delta_func[(delta_func['architecture'] == arch) &
                                   (delta_func['auth_strategy'] == auth)]
                if len(subset) < 3:
                    continue

                # Pick one hw tier
                hw = subset['hw'].value_counts().idxmax()
                hw_data = subset[subset['hw'] == hw].sort_values('delta_p50', ascending=True)

                fig, ax = plt.subplots(figsize=(10, max(4, len(hw_data) * 0.35)))
                colors = ['#e74c3c' if r['is_protected'] else '#3498db' for _, r in hw_data.iterrows()]
                ax.barh(hw_data['function_name'], hw_data['delta_p50'], color=colors, alpha=0.8)
                ax.axvline(x=0, color='black', linewidth=0.5)
                ax.set_xlabel('$\\Delta$ Handler Duration P50 (ms)')
                ax.set_title(f'{arch} / {AUTH_SHORT.get(auth, auth)} ({hw})\n'
                            f'Per-Function Auth Overhead (red=protected, blue=unprotected)',
                            fontweight='bold')
                ax.grid(axis='x', alpha=0.3)
                plt.tight_layout()
                path = f"{PLOT_DIR}/func_overhead_{arch}_{auth.replace('-', '_')}_{hw}.pdf"
                fig.savefig(path, bbox_inches='tight')
                print(f"Saved: {path}")
                plt.close()

        delta_func.to_csv(f"{PLOT_DIR}/per_function_overhead.csv", index=False)

    # 3. Multiplication model validation
    print("\n--- MULTIPLICATION MODEL VALIDATION ---")
    print("k(monolith)=1, k(microservices)=d (service boundaries), k(faas)=n (functions)")

    # For checkout flow: frontend -> checkout -> getcart, getproduct, currency, payment, ...
    # FaaS: each function verifies independently -> k = number of functions in chain
    # Microservices: each service boundary -> k = number of service hops
    # Monolith: single entry point -> k = 1

    # Compute end-to-end latency delta for complex operations (checkout)
    e2e_df = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.auth_strategy,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            r.endpoint,
            COUNT(*) AS request_count,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name = 'Baseline'
          AND r.endpoint IN ('checkout', 'addCartItem', 'cart', 'frontend', 'login')
          AND NOT r.is_error
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu, r.endpoint
        HAVING COUNT(*) > 20
        ORDER BY e.architecture, e.auth_strategy, r.endpoint
    """)
    e2e_df['hw'] = e2e_df.apply(hw_label, axis=1)

    if not e2e_df.empty:
        print("\n--- CHECKOUT ENDPOINT: End-to-End DeltaAuth ---")
        for arch in ['faas', 'microservices', 'monolith']:
            arch_e2e = e2e_df[e2e_df['architecture'] == arch]
            none_checkout = arch_e2e[(arch_e2e['auth_strategy'] == 'none') & (arch_e2e['endpoint'] == 'checkout')]
            if none_checkout.empty:
                continue

            for _, none_row in none_checkout.iterrows():
                hw = none_row['hw']
                for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                    auth_checkout = arch_e2e[(arch_e2e['auth_strategy'] == auth) &
                                            (arch_e2e['endpoint'] == 'checkout') &
                                            (arch_e2e['hw'] == hw)]
                    if auth_checkout.empty:
                        continue
                    delta = auth_checkout.iloc[0]['p50'] - none_row['p50']
                    print(f"  {arch} {auth} ({hw}): checkout DeltaAuth P50 = {delta:+.1f} ms")

        # Endpoint comparison plot
        fig, axes = plt.subplots(1, 3, figsize=(18, 7))
        endpoints = ['frontend', 'cart', 'checkout']
        for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
            arch_e2e = e2e_df[e2e_df['architecture'] == arch]
            if arch_e2e.empty:
                ax.set_title(f'{arch} (no data)')
                continue

            # Best per config
            arch_best = arch_e2e.sort_values('request_count', ascending=False).drop_duplicates(
                subset=['auth_strategy', 'hw', 'endpoint'], keep='first')

            # Find common hw
            common_hw = arch_best.groupby('hw')['auth_strategy'].nunique().idxmax()
            hw_data = arch_best[arch_best['hw'] == common_hw]

            x = np.arange(len(endpoints))
            width = 0.2
            auth_list = [a for a in ['none', 'service-integrated', 'service-integrated-manual', 'edge']
                        if a in hw_data['auth_strategy'].values]

            for i, auth in enumerate(auth_list):
                vals = []
                for ep in endpoints:
                    match = hw_data[(hw_data['auth_strategy'] == auth) & (hw_data['endpoint'] == ep)]
                    vals.append(match.iloc[0]['p50'] if not match.empty else 0)
                offset = (i - len(auth_list) / 2 + 0.5) * width
                ax.bar(x + offset, vals, width, label=AUTH_SHORT.get(auth, auth),
                      alpha=0.85)

            ax.set_xticks(x)
            ax.set_xticklabels(endpoints, fontsize=10)
            ax.set_ylabel('P50 Latency (ms)')
            ax.set_title(f'{arch} ({common_hw})', fontweight='bold')
            ax.legend(fontsize=8)
            ax.grid(axis='y', alpha=0.3)

        fig.suptitle('Per-Endpoint P50 Latency: Multiplication Model Test\n'
                     '(checkout has most verifications, frontend has fewest)',
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/endpoint_multiplication_model.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()


if __name__ == '__main__':
    main()
