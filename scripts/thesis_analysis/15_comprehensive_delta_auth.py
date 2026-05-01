#!/usr/bin/env python3
"""
15 — Comprehensive DeltaAuth Analysis (RQ1 Core Result)
Produces the central thesis results: ΔAuth at P50/P95/P99 for all
architecture × auth strategy × hardware × algorithm × CloudFront combinations.
Includes Mann-Whitney U significance tests and effect sizes.

Now differentiates:
  - Manual (bcrypt) vs Manual (argon2id) as separate entries
  - CloudFront (+CF) vs non-CF variants where data exists

Outputs: delta_auth_comprehensive.csv, delta_auth_p99.pdf,
         delta_auth_percentage.pdf, delta_auth_summary_table.csv
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as sp_stats

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, hw_label_from_row,
                           AUTH_COLORS_DETAILED)


def main():
    print("=" * 70)
    print("15 — COMPREHENSIVE ΔAuth ANALYSIS (RQ1) — FULL DIFFERENTIATION")
    print("=" * 70)

    # ── 1. Per-experiment baseline percentiles (with algo + CF) ──
    per_exp = query_df(f"""
        SELECT
            e.id, e.architecture, e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            COALESCE(e.with_cloudfront, false) AS with_cf,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu_in_vcpu,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99,
            AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_lat,
            STDDEV(r.latency_ms) FILTER (WHERE NOT r.is_error) AS std_lat
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL} AND r.phase_name = 'Baseline'
        GROUP BY e.id, e.architecture, e.auth_strategy, algo, with_cf,
                 e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 500
    """)

    for col in ['p50', 'p95', 'p99', 'mean_lat', 'std_lat']:
        per_exp[col] = per_exp[col].astype(float)
    per_exp['hw'] = per_exp.apply(hw_label_from_row, axis=1)

    # ── 2. Compute ΔAuth per detailed config group ──
    rows = []
    for (arch, ram, with_cf), grp in per_exp.groupby(['architecture', 'ram_in_mb', 'with_cf']):
        # Baseline: 'none' experiments at same arch/hw/CF
        none_exps = grp[grp['auth_strategy'] == 'none']
        if none_exps.empty:
            # Fall back to 'none' without CF filter at same arch/hw
            none_exps = per_exp[(per_exp['architecture'] == arch) &
                                (per_exp['ram_in_mb'] == ram) &
                                (per_exp['auth_strategy'] == 'none')]
        if none_exps.empty:
            continue

        none_p50_mean = none_exps['p50'].mean()
        none_p95_mean = none_exps['p95'].mean()
        none_p99_mean = none_exps['p99'].mean()
        none_n = len(none_exps)

        for auth in ['service-integrated', 'service-integrated-manual', 'edge', 'edge-selective']:
            auth_exps = grp[grp['auth_strategy'] == auth]
            if auth_exps.empty:
                continue

            # Group by algorithm for manual, single group for others
            algo_groups = auth_exps.groupby('algo')
            for algo, algo_grp in algo_groups:
                auth_p50s = algo_grp['p50'].values
                auth_p95s = algo_grp['p95'].values
                auth_p99s = algo_grp['p99'].values
                n_auth = len(algo_grp)

                delta_p50 = np.mean(auth_p50s) - none_p50_mean
                delta_p95 = np.mean(auth_p95s) - none_p95_mean
                delta_p99 = np.mean(auth_p99s) - none_p99_mean

                pct_p50 = (delta_p50 / none_p50_mean * 100) if none_p50_mean > 0 else 0
                pct_p99 = (delta_p99 / none_p99_mean * 100) if none_p99_mean > 0 else 0

                # Mann-Whitney U test on P99
                mw_p = None
                if n_auth >= 1 and none_n >= 1:
                    try:
                        _, mw_p = sp_stats.mannwhitneyu(
                            auth_p99s, none_exps['p99'].values, alternative='two-sided')
                    except ValueError:
                        pass

                # 95% CI for delta (Welch-style if multiple runs)
                ci_low = ci_high = delta_p99
                if n_auth >= 2 and none_n >= 2:
                    se = np.sqrt(np.var(auth_p99s, ddof=1)/n_auth +
                                 np.var(none_exps['p99'].values, ddof=1)/none_n)
                    if se > 0:
                        df_w = (np.var(auth_p99s, ddof=1)/n_auth +
                                np.var(none_exps['p99'].values, ddof=1)/none_n)**2 / (
                            (np.var(auth_p99s, ddof=1)/n_auth)**2/(n_auth-1) +
                            (np.var(none_exps['p99'].values, ddof=1)/none_n)**2/(none_n-1))
                        if df_w > 0:
                            t_crit = sp_stats.t.ppf(0.975, df_w)
                            ci_low = delta_p99 - t_crit * se
                            ci_high = delta_p99 + t_crit * se

                hw = hw_label_from_row({'architecture': arch, 'ram_in_mb': ram,
                                        'cpu_in_vcpu': algo_grp.iloc[0]['cpu_in_vcpu']})

                cf_bool = bool(with_cf) if with_cf is not None else False
                label = auth_label_detailed(auth, algo if auth == 'service-integrated-manual' else None, cf_bool)

                rows.append({
                    'architecture': arch,
                    'hw': hw,
                    'ram_in_mb': ram,
                    'auth_strategy': auth,
                    'auth_label': label,
                    'algo': algo,
                    'with_cf': cf_bool,
                    'n_none': none_n,
                    'n_auth': n_auth,
                    'none_p50': none_p50_mean,
                    'none_p95': none_p95_mean,
                    'none_p99': none_p99_mean,
                    'auth_p50': np.mean(auth_p50s),
                    'auth_p95': np.mean(auth_p95s),
                    'auth_p99': np.mean(auth_p99s),
                    'delta_p50': delta_p50,
                    'delta_p95': delta_p95,
                    'delta_p99': delta_p99,
                    'pct_p50': pct_p50,
                    'pct_p99': pct_p99,
                    'ci_low_p99': ci_low,
                    'ci_high_p99': ci_high,
                    'mannwhitney_p': mw_p,
                    'significant': mw_p is not None and mw_p < 0.05,
                })

    result = pd.DataFrame(rows).sort_values(['architecture', 'ram_in_mb', 'auth_strategy', 'algo', 'with_cf'])
    result.to_csv(f"{PLOT_DIR}/delta_auth_comprehensive.csv", index=False)
    print(f"Saved: {PLOT_DIR}/delta_auth_comprehensive.csv")

    # ── 3. Print summary table ──
    print("\n--- ΔAuth SUMMARY (P99, Baseline) ---")
    for arch in ['faas', 'microservices', 'monolith']:
        arch_data = result[result['architecture'] == arch]
        if arch_data.empty:
            continue
        print(f"\n  {arch.upper()}:")
        print(f"  {'HW':>6s} | {'Auth':>28s} | {'None P99':>9s} | {'Auth P99':>9s} | "
              f"{'ΔP99':>8s} | {'%OH':>7s} | {'95%CI':>20s} | {'Sig?':>4s}")
        print(f"  {'-'*6} | {'-'*28} | {'-'*9} | {'-'*9} | {'-'*8} | {'-'*7} | {'-'*20} | {'-'*4}")
        for _, r in arch_data.iterrows():
            sig = '***' if r['significant'] else ''
            ci_str = f"[{r['ci_low_p99']:.0f}, {r['ci_high_p99']:.0f}]" if r['n_auth'] >= 2 and r['n_none'] >= 2 else 'N/A'
            print(f"  {r['hw']:>6s} | {r['auth_label']:>28s} | {r['none_p99']:>8.0f}ms | "
                  f"{r['auth_p99']:>8.0f}ms | {r['delta_p99']:>+7.0f}ms | {r['pct_p99']:>+6.1f}% | "
                  f"{ci_str:>20s} | {sig:>4s}")

    # ── 4. ΔAuth P99 bar chart — ALL auth variants including argon2id ──
    fig, axes = plt.subplots(1, 3, figsize=(20, 8))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = result[(result['architecture'] == arch) &
                           (~result['auth_strategy'].isin(['none', 'edge-selective']))]
        if arch_data.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        auth_labels = sorted(arch_data['auth_label'].unique())
        hw_labels = sorted(arch_data['hw'].unique(),
                           key=lambda x: {'S':1,'M':2,'L':3,'XL':4}.get(x, int(x.replace('MB','')) if 'MB' in x else 0))

        x = np.arange(len(hw_labels))
        width = 0.8 / max(len(auth_labels), 1)

        for i, auth_l in enumerate(auth_labels):
            vals = []
            for hw in hw_labels:
                match = arch_data[(arch_data['auth_label'] == auth_l) & (arch_data['hw'] == hw)]
                vals.append(match['delta_p99'].values[0] if not match.empty else 0)
            offset = (i - len(auth_labels)/2 + 0.5) * width
            color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
            ax.bar(x + offset, vals, width, label=auth_l, color=color, alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels(hw_labels)
        ax.set_ylabel('ΔAuth P99 (ms)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.legend(fontsize=6, loc='upper left')
        ax.grid(axis='y', alpha=0.3)
        ax.axhline(y=0, color='black', linewidth=0.5)

    fig.suptitle('Authentication Overhead ΔAuth P99 by Architecture and Hardware\n'
                 '(Baseline phase, all auth variants incl. algorithm & CloudFront)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/delta_auth_p99.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # ── 5. Percentage overhead chart ──
    fig, axes = plt.subplots(1, 3, figsize=(20, 8))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = result[(result['architecture'] == arch) &
                           (~result['auth_strategy'].isin(['none', 'edge-selective']))]
        if arch_data.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        auth_labels = sorted(arch_data['auth_label'].unique())
        hw_labels = sorted(arch_data['hw'].unique(),
                           key=lambda x: {'S':1,'M':2,'L':3,'XL':4}.get(x, int(x.replace('MB','')) if 'MB' in x else 0))

        x = np.arange(len(hw_labels))
        width = 0.8 / max(len(auth_labels), 1)

        for i, auth_l in enumerate(auth_labels):
            vals = []
            for hw in hw_labels:
                match = arch_data[(arch_data['auth_label'] == auth_l) & (arch_data['hw'] == hw)]
                vals.append(match['pct_p99'].values[0] if not match.empty else 0)
            offset = (i - len(auth_labels)/2 + 0.5) * width
            color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
            ax.bar(x + offset, vals, width, label=auth_l, color=color, alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels(hw_labels)
        ax.set_ylabel('Overhead (%)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.legend(fontsize=6, loc='upper left')
        ax.grid(axis='y', alpha=0.3)
        ax.axhline(y=0, color='black', linewidth=0.5)

    fig.suptitle('Authentication Overhead as Percentage of Baseline P99\n'
                 '(Baseline phase, all auth variants incl. algorithm & CloudFront)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/delta_auth_percentage.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # ── 6. Summary table for thesis (LaTeX-ready) — representative HW ──
    summary_rows = []
    for arch, hw_filter in [('faas', '512MB'), ('microservices', 'L'), ('monolith', 'L')]:
        arch_data = result[(result['architecture'] == arch) & (result['hw'] == hw_filter)]
        for _, r in arch_data.iterrows():
            summary_rows.append({
                'Architecture': arch.capitalize(),
                'HW': r['hw'],
                'Auth': r['auth_label'],
                'None_P50': f"{r['none_p50']:.0f}",
                'Auth_P50': f"{r['auth_p50']:.0f}",
                'ΔP50': f"{r['delta_p50']:+.0f}",
                'None_P99': f"{r['none_p99']:.0f}",
                'Auth_P99': f"{r['auth_p99']:.0f}",
                'ΔP99': f"{r['delta_p99']:+.0f}",
                'OH%': f"{r['pct_p99']:+.1f}%",
            })

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(f"{PLOT_DIR}/delta_auth_summary_table.csv", index=False)
    print(f"\nSaved: {PLOT_DIR}/delta_auth_summary_table.csv")
    print(summary_df.to_string(index=False))

    # ── 7. Key findings ──
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)

    for arch in ['faas', 'microservices', 'monolith']:
        arch_data = result[(result['architecture'] == arch) &
                           (~result['auth_strategy'].isin(['none', 'edge-selective']))]
        if arch_data.empty:
            continue
        cheapest = arch_data.loc[arch_data['delta_p99'].abs().idxmin()]
        most_expensive = arch_data.loc[arch_data['delta_p99'].idxmax()]
        print(f"\n  {arch.upper()}:")
        print(f"    Cheapest auth:   {cheapest['auth_label']} @ {cheapest['hw']} "
              f"(ΔP99 = {cheapest['delta_p99']:+.0f}ms, {cheapest['pct_p99']:+.1f}%)")
        print(f"    Most expensive:  {most_expensive['auth_label']} @ {most_expensive['hw']} "
              f"(ΔP99 = {most_expensive['delta_p99']:+.0f}ms, {most_expensive['pct_p99']:+.1f}%)")

    # Cognito overhead consistency
    cognito_data = result[result['auth_strategy'] == 'service-integrated']
    if not cognito_data.empty:
        print(f"\n  COGNITO OVERHEAD RANGE:")
        print(f"    Min ΔP99: {cognito_data['delta_p99'].min():+.0f}ms "
              f"({cognito_data.loc[cognito_data['delta_p99'].idxmin(), 'auth_label']} @ "
              f"{cognito_data.loc[cognito_data['delta_p99'].idxmin(), 'architecture']}/"
              f"{cognito_data.loc[cognito_data['delta_p99'].idxmin(), 'hw']})")
        print(f"    Max ΔP99: {cognito_data['delta_p99'].max():+.0f}ms "
              f"({cognito_data.loc[cognito_data['delta_p99'].idxmax(), 'auth_label']} @ "
              f"{cognito_data.loc[cognito_data['delta_p99'].idxmax(), 'architecture']}/"
              f"{cognito_data.loc[cognito_data['delta_p99'].idxmax(), 'hw']})")


if __name__ == '__main__':
    main()
