#!/usr/bin/env python3
"""
24 — Pure Cognito Verification Time (Handler-Level Isolation)
Isolates the pure Cognito token verification overhead by comparing
handler_events duration at leaf functions between 'none' and
'service-integrated' auth strategies. The delta = pure verification time.

Key insight: handler_events record per-function execution times in FaaS
(each function = separate Lambda). For containers (MS/Mono), handler_events
only record 'frontend-service' or 'unknown', so per-function isolation
is only possible on FaaS.

Leaf functions (no downstream calls, verified via rpc_calls call graph):
  payment, cartkvstorage, listrecommendations, currency, email, getads,
  getproduct, listproducts, shipmentquote, shiporder, supportedcurrencies
Excluded: frontend (entry point), login (bcrypt overhead confounds)

Outputs:
  cognito_pure_verification_time.csv
  cognito_pure_verification_time_all_ram.csv
  cognito_pure_verification_time.pdf
"""

import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

# Leaf functions: no downstream calls (verified via rpc_calls call graph).
# Excluding 'frontend' (entry point) and 'login' (bcrypt overhead confounds).
LEAF_FUNCTIONS = (
    'payment', 'cartkvstorage', 'listrecommendations',
    'currency', 'email', 'getads', 'getproduct',
    'listproducts', 'shipmentquote', 'shiporder', 'supportedcurrencies',
)

# Pretty display names
FUNC_DISPLAY = {
    'payment': 'Payment',
    'cartkvstorage': 'CartKVStorage',
    'listrecommendations': 'ListRecommend.',
    'currency': 'Currency',
    'email': 'Email',
    'getads': 'GetAds',
    'getproduct': 'GetProduct',
    'listproducts': 'ListProducts',
    'shipmentquote': 'ShipmentQuote',
    'shiporder': 'ShipOrder',
    'supportedcurrencies': 'SupportedCurr.',
}

PCTL_LABELS = ['P50', 'P75', 'P90', 'P99']


def main():
    print("=" * 70)
    print("24 — PURE COGNITO VERIFICATION TIME (HANDLER-LEVEL)")
    print("=" * 70)
    print("\nNOTE: Handler-level per-function isolation is only possible for FaaS.")
    print("  Containers record handler_events as 'frontend-service' or 'unknown'.")

    funcs_sql = ','.join(f"'{f}'" for f in LEAF_FUNCTIONS)

    # ── Part 1: FaaS 512MB, Baseline phase (primary comparison) ──
    print("\n--- Part 1: FaaS 512MB, Baseline phase ---")

    df = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.auth_strategy,
            e.ram_in_mb,
            h.function_name,
            h.duration_ms
        FROM experiments e
        JOIN handler_events h ON h.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = 'faas'
          AND e.ram_in_mb = 512
          AND e.auth_strategy IN ('none', 'service-integrated')
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND h.function_name IN ({funcs_sql})
          AND h.duration_ms IS NOT NULL
          AND h.phase_name = 'Baseline'
    """)

    if df.empty:
        print("ERROR: No handler_events data found for FaaS 512MB Baseline.")
        return

    print(f"  Loaded {len(df):,} individual handler events")
    print(f"  Experiments: {sorted(df['experiment_id'].unique())}")
    print(f"  Auth strategies: {sorted(df['auth_strategy'].unique())}")

    # Compute per-function percentiles grouped by auth_strategy
    result_rows = []
    for func in LEAF_FUNCTIONS:
        func_data = df[df['function_name'] == func]
        none_data = func_data[func_data['auth_strategy'] == 'none']['duration_ms']
        cog_data = func_data[func_data['auth_strategy'] == 'service-integrated']['duration_ms']

        if len(none_data) < 20 or len(cog_data) < 20:
            print(f"  WARNING: Skipping {func} — insufficient data "
                  f"(none={len(none_data)}, cognito={len(cog_data)})")
            continue

        row = {
            'function': func,
            'display_name': FUNC_DISPLAY.get(func, func),
            'n_none': len(none_data),
            'n_cognito': len(cog_data),
        }
        for pctl, label in zip([0.50, 0.75, 0.90, 0.99], ['p50', 'p75', 'p90', 'p99']):
            n_val = none_data.quantile(pctl)
            c_val = cog_data.quantile(pctl)
            row[f'none_{label}'] = round(n_val, 3)
            row[f'cognito_{label}'] = round(c_val, 3)
            row[f'delta_{label}'] = round(c_val - n_val, 3)

        result_rows.append(row)

    result_df = pd.DataFrame(result_rows)
    csv_path = f"{PLOT_DIR}/cognito_pure_verification_time.csv"
    result_df.to_csv(csv_path, index=False)
    print(f"  Saved: {csv_path}")

    # Print summary table
    print(f"\n  {'Function':>16s} | {'ΔP50':>9s} | {'ΔP90':>9s} | {'ΔP99':>9s} | "
          f"{'None P50':>9s} | {'Cog P50':>9s} | {'n_none':>7s} | {'n_cog':>7s}")
    print(f"  {'-'*16}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*7}-+-{'-'*7}")
    for _, r in result_df.iterrows():
        print(f"  {r['display_name']:>16s} | {r['delta_p50']:>+8.2f}ms | {r['delta_p90']:>+8.2f}ms | "
              f"{r['delta_p99']:>+8.2f}ms | {r['none_p50']:>8.2f}ms | {r['cognito_p50']:>8.2f}ms | "
              f"{r['n_none']:>7,} | {r['n_cognito']:>7,}")

    # Separate functions with measurable durations (>0.1ms at P50 for either auth)
    measurable = result_df[
        (result_df['none_p50'] > 0.1) | (result_df['cognito_p50'] > 0.1)
    ]
    submilli = result_df[
        (result_df['none_p50'] <= 0.1) & (result_df['cognito_p50'] <= 0.1)
    ]

    if not measurable.empty:
        print(f"\n  --- Functions with measurable handler duration (P50 > 0.1ms) ---")
        avg_m = {
            'P50': measurable['delta_p50'].mean(),
            'P90': measurable['delta_p90'].mean(),
            'P99': measurable['delta_p99'].mean(),
        }
        for pctl, val in avg_m.items():
            print(f"    Average {pctl}: {val:+.2f}ms")
        print(f"    Functions: {', '.join(measurable['display_name'].tolist())}")

    if not submilli.empty:
        print(f"\n  --- Sub-millisecond functions (P50 <= 0.1ms, overhead below resolution) ---")
        avg_s = {
            'P50': submilli['delta_p50'].mean(),
            'P90': submilli['delta_p90'].mean(),
            'P99': submilli['delta_p99'].mean(),
        }
        for pctl, val in avg_s.items():
            print(f"    Average {pctl}: {val:+.3f}ms")
        print(f"    Functions ({len(submilli)}): {', '.join(submilli['display_name'].tolist())}")

    # Overall average
    avg_all = {
        'P50': result_df['delta_p50'].mean(),
        'P75': result_df['delta_p75'].mean(),
        'P90': result_df['delta_p90'].mean(),
        'P99': result_df['delta_p99'].mean(),
    }
    print(f"\n  OVERALL AVERAGE across all {len(result_df)} leaf functions:")
    for pctl, val in avg_all.items():
        print(f"    {pctl}: {val:+.2f}ms")

    # ── Part 2: FaaS all RAM sizes, all phases ──
    print("\n\n--- Part 2: FaaS all RAM sizes, all phases ---")

    df_all = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.auth_strategy,
            e.ram_in_mb,
            h.function_name,
            h.duration_ms
        FROM experiments e
        JOIN handler_events h ON h.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = 'faas'
          AND e.auth_strategy IN ('none', 'service-integrated')
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND h.function_name IN ({funcs_sql})
          AND h.duration_ms IS NOT NULL
          AND h.phase_name IS NOT NULL
    """)

    if not df_all.empty:
        print(f"  Loaded {len(df_all):,} handler events across all FaaS experiments")
        print(f"  Experiments: {sorted(df_all['experiment_id'].unique())}")
        print(f"  RAM sizes: {sorted(df_all['ram_in_mb'].unique())}")

        # Focus on the measurable functions for cross-RAM analysis
        measurable_funcs = measurable['function'].tolist() if not measurable.empty else []
        if measurable_funcs:
            ram_rows = []
            for ram in sorted(df_all['ram_in_mb'].unique()):
                ram_data = df_all[
                    (df_all['ram_in_mb'] == ram) &
                    (df_all['function_name'].isin(measurable_funcs))
                ]
                none_data = ram_data[ram_data['auth_strategy'] == 'none']['duration_ms']
                cog_data = ram_data[ram_data['auth_strategy'] == 'service-integrated']['duration_ms']

                if len(none_data) < 50 or len(cog_data) < 50:
                    print(f"  RAM {ram}MB: Skipping — insufficient data "
                          f"(none={len(none_data)}, cognito={len(cog_data)})")
                    continue

                row = {'ram_mb': ram, 'n_none': len(none_data), 'n_cognito': len(cog_data)}
                for pctl, label in zip([0.50, 0.75, 0.90, 0.99], ['p50', 'p75', 'p90', 'p99']):
                    row[f'none_{label}'] = round(none_data.quantile(pctl), 3)
                    row[f'cognito_{label}'] = round(cog_data.quantile(pctl), 3)
                    row[f'delta_{label}'] = round(cog_data.quantile(pctl) - none_data.quantile(pctl), 3)
                ram_rows.append(row)

            if ram_rows:
                ram_df = pd.DataFrame(ram_rows)
                csv_path2 = f"{PLOT_DIR}/cognito_pure_verification_time_all_ram.csv"
                ram_df.to_csv(csv_path2, index=False)
                print(f"  Saved: {csv_path2}")

                print(f"\n  Measurable leaf functions ({', '.join(FUNC_DISPLAY[f] for f in measurable_funcs)}) by RAM:")
                print(f"  {'RAM':>8s} | {'ΔP50':>9s} | {'ΔP90':>9s} | {'ΔP99':>9s} | "
                      f"{'None P50':>9s} | {'Cog P50':>9s}")
                print(f"  {'-'*8}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}")
                for _, r in ram_df.iterrows():
                    print(f"  {int(r['ram_mb']):>6d}MB | {r['delta_p50']:>+8.2f}ms | "
                          f"{r['delta_p90']:>+8.2f}ms | {r['delta_p99']:>+8.2f}ms | "
                          f"{r['none_p50']:>8.2f}ms | {r['cognito_p50']:>8.2f}ms")

    # ── Plot: grouped bar chart for FaaS 512MB Baseline (measurable functions only) ──
    # Only functions with P50 > 0.1ms are shown; the remaining sub-millisecond
    # functions show ΔP50 ≈ 0ms (below measurement resolution).
    if measurable.empty:
        print("\n  No measurable functions to plot.")
    else:
        m_df = measurable.sort_values('delta_p50', ascending=False)
        m_funcs = m_df['display_name'].tolist()
        n_m = len(m_funcs)
        n_pctls = len(PCTL_LABELS)
        x = np.arange(n_m)
        width = 0.8 / n_pctls
        pctl_colors = ['#90CAF9', '#42A5F5', '#1E88E5', '#0D47A1']

        fig, ax = plt.subplots(figsize=(10, 7))

        for i, (pctl_col, pctl_label, color) in enumerate(
                zip(['delta_p50', 'delta_p75', 'delta_p90', 'delta_p99'],
                    PCTL_LABELS, pctl_colors)):
            vals = m_df[pctl_col].values
            offset = (i - n_pctls / 2 + 0.5) * width
            bars = ax.bar(x + offset, vals, width, label=pctl_label, color=color, alpha=0.9)
            for bar, val in zip(bars, vals):
                ypos = bar.get_height() + 0.5 if val >= 0 else bar.get_height() - 0.5
                va = 'bottom' if val >= 0 else 'top'
                ax.text(bar.get_x() + bar.get_width() / 2, ypos,
                        f'{val:+.1f}', ha='center', va=va, fontsize=8)

        ax.set_xticks(x)
        ax.set_xticklabels(m_funcs, fontsize=11, rotation=30, ha='right')
        ax.set_ylabel('Delta Handler Duration (ms)\nCognito − None', fontsize=12)
        ax.set_title('Pure Cognito Verification Overhead at Leaf Functions\n'
                     '(FaaS 512MB, Baseline, nur Funktionen mit P50 > 0,1\u2009ms)',
                     fontsize=13, fontweight='bold')
        ax.legend(title='Percentile', fontsize=9, title_fontsize=10, loc='upper right')
        ax.grid(axis='y', alpha=0.3)
        ax.axhline(y=0, color='black', linewidth=0.5)
        ax.tick_params(labelsize=10)

        plt.tight_layout()
        pdf_path = f"{PLOT_DIR}/cognito_pure_verification_time.pdf"
        fig.savefig(pdf_path, dpi=300, bbox_inches='tight')
        print(f"\n  Saved: {pdf_path}")
        plt.close()

    # ── Key Findings ──
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    if not measurable.empty:
        avg_m = {
            'P50': measurable['delta_p50'].mean(),
            'P90': measurable['delta_p90'].mean(),
            'P99': measurable['delta_p99'].mean(),
        }
        print(f"  1. Measurable leaf functions ({len(measurable)}):")
        print(f"     Average ΔP50 = {avg_m['P50']:+.1f}ms, ΔP90 = {avg_m['P90']:+.1f}ms, "
              f"ΔP99 = {avg_m['P99']:+.1f}ms")
        print(f"     => This is the pure Cognito JWT/JWKS verification cost.")
    print(f"  2. Sub-millisecond functions ({len(submilli)}) show ~0ms delta:")
    print(f"     Handler overhead below measurement resolution for fast functions.")
    print(f"  3. Overall average across all {len(result_df)} leaf functions:")
    print(f"     ΔP50 = {avg_all['P50']:+.2f}ms, ΔP99 = {avg_all['P99']:+.2f}ms")
    print("=" * 70)


if __name__ == '__main__':
    main()
