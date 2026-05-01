#!/usr/bin/env python3
"""
30 -- Edge vs Cognito: k=1 Call Depth Comparison (All HW Configs)
Direct comparison showing that Edge auth is strictly worse than Cognito
when call depth k=1 (monolith). Also compares FaaS and MS for reference.
Outputs: edge_vs_cognito_monolith.csv,
         edge_vs_cognito_{arch}.pdf (one per architecture)
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}

PROTECTED_ENDPOINTS_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_ENDPOINTS_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)

# All hardware configurations
ALL_CONFIGS = [
    ('faas', 256, 0, 'FaaS 256MB'),
    ('faas', 512, 0, 'FaaS 512MB'),
    ('faas', 1024, 0, 'FaaS 1024MB'),
    ('faas', 1769, 0, 'FaaS 1769MB'),
    ('microservices', 512, 0.25, 'MS S'),
    ('microservices', 1024, 0.5, 'MS M'),
    ('microservices', 1769, 1.0, 'MS 1769'),
    ('microservices', 2048, 1.0, 'MS L'),
    ('microservices', 8192, 4.0, 'MS XL'),
    ('monolith', 512, 0.25, 'Mono S'),
    ('monolith', 1024, 0.5, 'Mono M'),
    ('monolith', 2048, 1.0, 'Mono L'),
    ('monolith', 8192, 4.0, 'Mono XL'),
]

ARCH_ORDER = ['faas', 'microservices', 'monolith']
ARCH_DISPLAY = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}

PERCENTILES = [0.50, 0.75, 0.90, 0.95, 0.99]
PCTL_LABELS = ['P50', 'P75', 'P90', 'P95', 'P99']


def get_protected_endpoints(arch):
    return PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER


def compute_percentiles(arch, ram, cpu):
    """Compute auth-only percentiles for none, Cognito, and Edge."""
    protected = get_protected_endpoints(arch)
    eps_sql = ','.join(f"'{e}'" for e in protected)
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

    pctl_selects = []
    for p in PERCENTILES:
        pctl_selects.append(
            f"percentile_cont({p}) WITHIN GROUP (ORDER BY r.latency_ms) "
            f"FILTER (WHERE NOT r.is_error) AS p{int(p*100)}"
        )
    pctl_sql = ',\n            '.join(pctl_selects)

    return query_df(f"""
        SELECT
            e.auth_strategy,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            {pctl_sql}
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = '{arch}'
          AND e.ram_in_mb = {ram}
          {cpu_clause}
          AND r.phase_name = 'Baseline'
          AND NOT r.is_error
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND r.endpoint IN ({eps_sql})
        GROUP BY e.auth_strategy
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)


def main():
    print("=" * 70)
    print("30 -- EDGE vs COGNITO (ALL HW CONFIGS)")
    print("=" * 70)

    all_rows = []

    for arch, ram, cpu, config_label in ALL_CONFIGS:
        print(f"\n--- {config_label} ---")

        df = compute_percentiles(arch, ram, cpu)
        if df.empty:
            print(f"  No data for {config_label}")
            continue

        for col in ['p50', 'p75', 'p90', 'p95', 'p99']:
            df[col] = df[col].astype(float)

        for _, row in df.iterrows():
            auth = row['auth_strategy']
            auth_label = AUTH_SHORT.get(auth, auth)
            r = {
                'config': config_label,
                'architecture': arch,
                'auth_strategy': auth,
                'auth_label': auth_label,
                'n_success': int(row['n_success']),
            }
            for p, plabel in zip(['p50', 'p75', 'p90', 'p95', 'p99'], PCTL_LABELS):
                r[plabel] = round(float(row[p]), 1)
            all_rows.append(r)

            print(f"  {auth_label:>8s}: P50={r['P50']:.1f}  P75={r['P75']:.1f}  "
                  f"P90={r['P90']:.1f}  P95={r['P95']:.1f}  P99={r['P99']:.1f}  "
                  f"(n={r['n_success']:,})")

    result_df = pd.DataFrame(all_rows)
    if result_df.empty:
        print("\nNo data found. Exiting.")
        return

    result_df.to_csv(f"{PLOT_DIR}/edge_vs_cognito_monolith.csv", index=False)
    print(f"\nSaved: {PLOT_DIR}/edge_vs_cognito_monolith.csv")

    # Print key comparisons per architecture
    for arch in ARCH_ORDER:
        arch_data = result_df[result_df['architecture'] == arch]
        if arch_data.empty:
            continue
        print(f"\n--- KEY COMPARISON: {ARCH_DISPLAY[arch]} ---")
        for config_label in arch_data['config'].unique():
            cfg_data = arch_data[arch_data['config'] == config_label]
            cognito_row = cfg_data[cfg_data['auth_strategy'] == 'service-integrated']
            edge_row = cfg_data[cfg_data['auth_strategy'] == 'edge']
            none_row = cfg_data[cfg_data['auth_strategy'] == 'none']

            if not cognito_row.empty and not edge_row.empty:
                cog_p99 = cognito_row.iloc[0]['P99']
                edge_p99 = edge_row.iloc[0]['P99']
                diff = edge_p99 - cog_p99
                print(f"  {config_label}: Edge P99={edge_p99:.1f}ms, "
                      f"Cognito P99={cog_p99:.1f}ms -> Edge is {diff:+.1f}ms")

            if not none_row.empty and not cognito_row.empty and not edge_row.empty:
                none_p99 = none_row.iloc[0]['P99']
                cog_delta = cognito_row.iloc[0]['P99'] - none_p99
                edge_delta = edge_row.iloc[0]['P99'] - none_p99
                if cog_delta > 0:
                    print(f"    ΔAuth P99: Cognito={cog_delta:+.1f}ms, Edge={edge_delta:+.1f}ms, "
                          f"ratio={edge_delta/cog_delta:.2f}x")

    # ── Plot: one PDF per architecture with 2×N grid for better readability ──
    pctl_cols_to_plot = ['P50', 'P75', 'P99']
    auth_strategies_to_plot = ['none', 'service-integrated', 'edge']

    for arch in ARCH_ORDER:
        arch_configs = [c for c in ALL_CONFIGS if c[0] == arch]
        arch_display = ARCH_DISPLAY[arch]
        arch_data = result_df[result_df['architecture'] == arch]

        if arch_data.empty:
            print(f"  No data for {arch_display} — skipping plot")
            continue

        n_hw = len(arch_configs)
        # Use 2×ceil(n/2) grid for ≥ 3 HW tiers, otherwise 1×n
        if n_hw >= 3:
            ncols = (n_hw + 1) // 2
            nrows = 2
        else:
            ncols = n_hw
            nrows = 1

        fig, axes_flat = plt.subplots(nrows, ncols, figsize=(6 * ncols, 6 * nrows),
                                       sharey=True)
        if nrows == 1 and ncols == 1:
            axes_flat = np.array([axes_flat])
        axes_list = axes_flat.flatten()

        for idx, (_, ram, cpu, hw_label) in enumerate(arch_configs):
            ax = axes_list[idx]
            config_data = arch_data[arch_data['config'] == hw_label]
            if config_data.empty:
                ax.set_title(f'{hw_label}\n(no data)', fontsize=11)
                ax.text(0.5, 0.5, 'No data', ha='center', va='center',
                        transform=ax.transAxes, fontsize=12, color='gray')
                continue

            x = np.arange(len(pctl_cols_to_plot))
            width = 0.25

            for i, auth in enumerate(auth_strategies_to_plot):
                row = config_data[config_data['auth_strategy'] == auth]
                if row.empty:
                    continue
                row = row.iloc[0]
                vals = [row[p] for p in pctl_cols_to_plot]
                label = AUTH_SHORT.get(auth, auth)
                color = AUTH_COLORS.get(AUTH_SHORT.get(auth, auth), '#999999')
                offset = (i - len(auth_strategies_to_plot) / 2 + 0.5) * width
                bars = ax.bar(x + offset, vals, width, label=label, color=color, alpha=0.85)

                for bar, val in zip(bars, vals):
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                            f'{val:.0f}', ha='center', va='bottom', fontsize=9,
                            fontweight='bold')

            ax.set_xticks(x)
            ax.set_xticklabels(pctl_cols_to_plot, fontsize=11)
            ax.set_ylabel('Latency (ms)', fontsize=11)

            if arch == 'monolith':
                ax.set_title(f'{hw_label} (k=1)', fontweight='bold', fontsize=12,
                             color='#D32F2F')
            else:
                k_hint = 'k=n' if arch == 'faas' else 'k=d'
                ax.set_title(f'{hw_label} ({k_hint})', fontweight='bold', fontsize=12)

            ax.legend(fontsize=9)
            ax.grid(axis='y', alpha=0.3)
            ax.tick_params(labelsize=10)

        # Hide unused axes
        for idx in range(len(arch_configs), len(axes_list)):
            axes_list[idx].set_visible(False)

        fig.suptitle(f'{arch_display}: Edge vs Cognito — Auth-Only Latency by Call Depth\n'
                     '(Baseline phase, excl. argon2id)',
                     fontsize=14, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/edge_vs_cognito_{arch}.pdf"
        fig.savefig(path, dpi=300, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # Summary
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    print("  1. At k=1 (Monolith), Edge auth adds an extra network hop via")
    print("     Lambda@Edge that Cognito does not require, making Edge strictly worse.")
    print("  2. At k>1 (FaaS, Microservices), Edge saves per-function Cognito")
    print("     verification, which can offset the extra network hop.")
    print("  3. The break-even depends on the number of auth verification points (k).")
    print()


if __name__ == '__main__':
    main()
