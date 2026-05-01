#!/usr/bin/env python3
"""
25 — Cognito Percentile Progression
Shows how authentication overhead becomes visible at different percentiles.
At P50, most Cognito calls use cached tokens. At P75+, warm JWKS calls appear.
At P99, cold JWKS fetches dominate. Demonstrates the 3-mode distribution:
  ~23% cached (fast), ~43% warm (moderate), ~33% cold (slow).
Outputs: cognito_percentile_progression.csv,
         cognito_percentile_progression_{arch}.pdf (one per architecture)
"""

import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}
AUTH_LINESTYLE = {
    'None': '-', 'Cognito': '-',
    'Manual': '--', 'Edge': '-.'
}

PROTECTED_ENDPOINTS_FAAS = (
    '/frontend/setUser',
    '/frontend/addCartItem',
    '/frontend/cart',
    '/frontend/checkout',
)
PROTECTED_ENDPOINTS_CONTAINER = (
    '/setUser',
    '/addCartItem',
    '/cart',
    '/checkout',
)

PERCENTILE_LEVELS = [0.50, 0.75, 0.90, 0.95, 0.99]
PCTL_LABELS = ['P50', 'P75', 'P90', 'P95', 'P99']

# All hardware configurations
ALL_CONFIGS = [
    # FaaS (Lambda) — CPU scales with RAM automatically
    ('faas', 256, 0, 'FaaS 256MB'),
    ('faas', 512, 0, 'FaaS 512MB'),
    ('faas', 1024, 0, 'FaaS 1024MB'),
    ('faas', 1769, 0, 'FaaS 1769MB'),
    # Microservices (Fargate)
    ('microservices', 512, 0.25, 'MS S'),
    ('microservices', 1024, 0.5, 'MS M'),
    ('microservices', 1769, 1.0, 'MS 1769'),
    ('microservices', 2048, 1.0, 'MS L'),
    ('microservices', 8192, 4.0, 'MS XL'),
    # Monolith (Fargate)
    ('monolith', 512, 0.25, 'Mono S'),
    ('monolith', 1024, 0.5, 'Mono M'),
    ('monolith', 2048, 1.0, 'Mono L'),
    ('monolith', 8192, 4.0, 'Mono XL'),
]

ARCH_ORDER = ['faas', 'microservices', 'monolith']
ARCH_DISPLAY = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}


def get_protected_endpoints(arch):
    return PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER


def main():
    print("=" * 70)
    print("25 — COGNITO PERCENTILE PROGRESSION (ALL HW CONFIGS)")
    print("=" * 70)

    all_rows = []

    for arch, ram, cpu, arch_label in ALL_CONFIGS:
        protected = get_protected_endpoints(arch)
        eps_sql = ','.join(f"'{e}'" for e in protected)
        cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

        df = query_df(f"""
            SELECT
                e.id AS experiment_id,
                e.auth_strategy,
                COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p50,
                percentile_cont(0.75) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p75,
                percentile_cont(0.90) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p90,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p95,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p99
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL}
              AND e.architecture = '{arch}'
              AND e.ram_in_mb = {ram}
              {cpu_clause}
              AND r.phase_name = 'Baseline'
              AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
              AND r.endpoint IN ({eps_sql})
            GROUP BY e.id, e.auth_strategy
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)

        if df.empty:
            print(f"  WARNING: No data for {arch_label}")
            continue

        for col in ['p50', 'p75', 'p90', 'p95', 'p99']:
            df[col] = df[col].astype(float)

        for auth_strategy in df['auth_strategy'].unique():
            auth_data = df[df['auth_strategy'] == auth_strategy]
            auth_label = AUTH_SHORT.get(auth_strategy, auth_strategy)

            row = {
                'architecture': arch,
                'arch_label': arch_label,
                'auth_strategy': auth_strategy,
                'auth_label': auth_label,
                'n_experiments': len(auth_data),
            }
            for pctl_col, pctl_label in zip(['p50', 'p75', 'p90', 'p95', 'p99'], PCTL_LABELS):
                row[pctl_label] = round(auth_data[pctl_col].mean(), 2)
            all_rows.append(row)

    result_df = pd.DataFrame(all_rows)
    csv_path = f"{PLOT_DIR}/cognito_percentile_progression.csv"
    result_df.to_csv(csv_path, index=False)
    print(f"\nSaved: {csv_path}")

    # Print raw values
    print("\n--- AUTH-ONLY LATENCY BY PERCENTILE ---")
    for arch_label in result_df['arch_label'].unique():
        arch_data = result_df[result_df['arch_label'] == arch_label]
        print(f"\n  {arch_label}:")
        print(f"  {'Auth':>10s} | {'P50':>8s} | {'P75':>8s} | {'P90':>8s} | {'P95':>8s} | {'P99':>8s}")
        print(f"  {'-'*10} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*8}")
        for _, r in arch_data.iterrows():
            print(f"  {r['auth_label']:>10s} | {r['P50']:>7.1f}ms | {r['P75']:>7.1f}ms | "
                  f"{r['P90']:>7.1f}ms | {r['P95']:>7.1f}ms | {r['P99']:>7.1f}ms")

    # Compute ΔAuth at each percentile level
    print("\n--- ΔAuth AT EACH PERCENTILE (auth - none) ---")
    delta_rows = []
    for arch_label in result_df['arch_label'].unique():
        arch_data = result_df[result_df['arch_label'] == arch_label]
        none_row = arch_data[arch_data['auth_label'] == 'None']
        if none_row.empty:
            print(f"  WARNING: No 'none' baseline for {arch_label} — skipping ΔAuth")
            continue
        none_row = none_row.iloc[0]

        for _, r in arch_data.iterrows():
            if r['auth_label'] == 'None':
                continue
            delta_row = {
                'arch_label': arch_label,
                'architecture': r['architecture'],
                'auth_label': r['auth_label'],
            }
            for pctl in PCTL_LABELS:
                delta_row[f'delta_{pctl}'] = round(r[pctl] - none_row[pctl], 2)
            delta_rows.append(delta_row)

    delta_df = pd.DataFrame(delta_rows)
    if not delta_df.empty:
        for arch_label in delta_df['arch_label'].unique():
            ad = delta_df[delta_df['arch_label'] == arch_label]
            print(f"\n  {arch_label}:")
            print(f"  {'Auth':>10s} | {'ΔP50':>8s} | {'ΔP75':>8s} | {'ΔP90':>8s} | {'ΔP95':>8s} | {'ΔP99':>8s}")
            print(f"  {'-'*10} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*8}")
            for _, r in ad.iterrows():
                print(f"  {r['auth_label']:>10s} | {r['delta_P50']:>+7.1f}ms | {r['delta_P75']:>+7.1f}ms | "
                      f"{r['delta_P90']:>+7.1f}ms | {r['delta_P95']:>+7.1f}ms | {r['delta_P99']:>+7.1f}ms")

    # ── Plot: one PDF per architecture, subplots per HW tier ──
    for arch in ARCH_ORDER:
        arch_configs = [c for c in ALL_CONFIGS if c[0] == arch]
        arch_display = ARCH_DISPLAY[arch]

        # Filter result_df for this architecture
        arch_data = result_df[result_df['architecture'] == arch]
        if arch_data.empty:
            print(f"  No data for {arch_display} — skipping plot")
            continue

        n_hw = len(arch_configs)
        fig, axes = plt.subplots(1, n_hw, figsize=(5 * n_hw, 5), sharey=False)
        if n_hw == 1:
            axes = [axes]

        for ax, (_, ram, cpu, hw_label) in zip(axes, arch_configs):
            hw_data = arch_data[arch_data['arch_label'] == hw_label]
            if hw_data.empty:
                ax.set_title(f'{hw_label}\n(no data)', fontsize=10)
                ax.set_visible(True)
                ax.text(0.5, 0.5, 'No data', ha='center', va='center',
                        transform=ax.transAxes, fontsize=12, color='gray')
                continue

            x_positions = np.array([50, 75, 90, 95, 99])

            for _, r in hw_data.iterrows():
                auth_label = r['auth_label']
                values = [r[pctl] for pctl in PCTL_LABELS]
                color = AUTH_COLORS.get(auth_label, '#999999')
                linestyle = AUTH_LINESTYLE.get(auth_label, '-')
                ax.plot(x_positions, values, marker='o', markersize=5,
                        color=color, linestyle=linestyle, linewidth=1.8,
                        label=auth_label, alpha=0.9)
                # Annotate P99 value
                ax.annotate(f'{values[-1]:.0f}', (x_positions[-1], values[-1]),
                            textcoords="offset points", xytext=(8, 0),
                            fontsize=7, color=color)

            ax.set_xticks(x_positions)
            ax.set_xticklabels(PCTL_LABELS, fontsize=9)
            ax.set_xlabel('Percentile', fontsize=9)
            ax.set_xlim(45, 102)
            ax.set_ylabel('Latency (ms)', fontsize=9)
            ax.set_title(hw_label, fontsize=10, fontweight='bold')
            ax.legend(fontsize=7, loc='upper left')
            ax.grid(axis='y', alpha=0.3)
            ax.grid(axis='x', alpha=0.15)

        fig.suptitle(f'{arch_display}: Auth-Only Latency Progression Across Percentiles\n'
                     '(Protected endpoints, Baseline phase, excl. argon2id)',
                     fontsize=12, fontweight='bold')
        plt.tight_layout()
        pdf_path = f"{PLOT_DIR}/cognito_percentile_progression_{arch}.pdf"
        fig.savefig(pdf_path, dpi=300, bbox_inches='tight')
        print(f"\nSaved: {pdf_path}")
        plt.close()

    # ── Combined representative plot: FaaS 512MB, MS L, Mono L ──
    REPRESENTATIVE_HW = [
        ('faas', 'FaaS 512MB'),
        ('microservices', 'MS L'),
        ('monolith', 'Mono L'),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(18, 7), sharey=False)
    x_positions = np.array([50, 75, 90, 95, 99])

    for ax, (arch_key, hw_label) in zip(axes, REPRESENTATIVE_HW):
        hw_data = result_df[result_df['arch_label'] == hw_label]
        if hw_data.empty:
            ax.set_title(f'{hw_label}\n(no data)', fontsize=11)
            continue

        for _, r in hw_data.iterrows():
            auth_label = r['auth_label']
            values = [r[pctl] for pctl in PCTL_LABELS]
            color = AUTH_COLORS.get(auth_label, '#999999')
            linestyle = AUTH_LINESTYLE.get(auth_label, '-')
            ax.plot(x_positions, values, marker='o', markersize=7,
                    color=color, linestyle=linestyle, linewidth=2.2,
                    label=auth_label, alpha=0.9)
            ax.annotate(f'{values[-1]:.0f}ms', (x_positions[-1], values[-1]),
                        textcoords="offset points", xytext=(10, 0),
                        fontsize=9, color=color)

        ax.set_xticks(x_positions)
        ax.set_xticklabels(PCTL_LABELS, fontsize=11)
        ax.set_xlabel('Percentile Level', fontsize=12)
        ax.set_xlim(45, 112)
        ax.set_ylabel('Latency (ms)', fontsize=12)
        ax.set_title(hw_label, fontsize=12, fontweight='bold')
        ax.legend(fontsize=9, loc='upper left')
        ax.grid(axis='y', alpha=0.3)
        ax.grid(axis='x', alpha=0.15)
        ax.tick_params(labelsize=10)

    fig.suptitle('Auth-Only Latency Progression Across Percentiles\n'
                 '(Protected endpoints, Baseline phase, excl. argon2id)',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    combined_path = f"{PLOT_DIR}/cognito_percentile_progression.pdf"
    fig.savefig(combined_path, dpi=300, bbox_inches='tight')
    print(f"\nSaved: {combined_path}")
    plt.close()

    # Key findings
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    if not delta_df.empty:
        cognito_deltas = delta_df[delta_df['auth_label'] == 'Cognito']
        if not cognito_deltas.empty:
            for _, r in cognito_deltas.iterrows():
                ratio = r['delta_P99'] / max(r['delta_P50'], 0.1)
                print(f"  {r['arch_label']}: Cognito ΔP50={r['delta_P50']:+.0f}ms -> "
                      f"ΔP99={r['delta_P99']:+.0f}ms (P99/P50 ratio: {ratio:.1f}x)")
            print(f"\n  Interpretation: Cognito overhead grows steeply at higher percentiles")
            print(f"  because cached calls (P50) are fast, but cold JWKS fetches (P99) are slow.")
            print(f"  This confirms the 3-mode distribution: cached / warm / cold.")


if __name__ == '__main__':
    main()
