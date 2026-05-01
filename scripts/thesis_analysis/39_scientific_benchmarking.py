#!/usr/bin/env python3
"""
39 — Scientific Benchmarking Analysis (nach Kounev, Kapitel 4)

Implements proper statistical methodology from Systems Benchmarking lecture:
- Mean as point estimator with 95% CI using t-distribution (n < 30 → Student t)
- Welch t-test for ΔAuth significance (CI does not include 0 → significant)
- Error bars on all plots
- Paired comparison where applicable

Reference: Kounev, S., Lange, K.-D., von Kistowski, J. (2025).
"Systems Benchmarking - For Scientists and Engineers", 2nd Ed.,
Springer, ISBN: 978-3-031-85633-4, Chapter 4.

Outputs:
  - sb_baseline_p99_with_ci.pdf        (Baseline P99 with error bars)
  - sb_delta_auth_with_ci.pdf           (ΔAuth with CI and significance)
  - sb_hardware_scaling_with_ci.pdf     (Hardware scaling with CI)
  - sb_delta_auth_significance.csv      (Significance table)
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
                           AUTH_COLORS_DETAILED, ARCH_COLORS)

# ── Constants ──
CONFIDENCE_LEVEL = 0.95
ALPHA = 1 - CONFIDENCE_LEVEL

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}


def t_ci(values, confidence=CONFIDENCE_LEVEL):
    """Compute mean and CI using t-distribution (Kounev Folie 30).

    For n < 30: exact CI via t_{α/2; n-1}
    CI = x̄ ± t_{α/2; n-1} × s/√n

    Returns: (mean, ci_lower, ci_upper, n, se)
    """
    n = len(values)
    if n < 2:
        return np.mean(values), np.nan, np.nan, n, np.nan
    mean = np.mean(values)
    se = sp_stats.sem(values)  # s / √n
    ci = sp_stats.t.interval(confidence, df=n - 1, loc=mean, scale=se)
    return mean, ci[0], ci[1], n, se


def welch_t_ci_diff(vals1, vals2, confidence=CONFIDENCE_LEVEL):
    """Welch t-test CI for difference of means (Kounev Folie 50).

    For non-corresponding measurements with n1, n2 < 30:
    CI = (x̄₁ - x̄₂) ± t_{α/2; n_df} × s_x̄
    where s_x̄ = √(s₁²/n₁ + s₂²/n₂)
    and n_df via Welch-Satterthwaite approximation.

    Significance: CI does not include 0 (Folie 49 step 5).

    Returns: (diff, ci_lower, ci_upper, n_df, significant, t_stat, p_value)
    """
    n1, n2 = len(vals1), len(vals2)
    mean_diff = np.mean(vals1) - np.mean(vals2)

    if n1 < 2 or n2 < 2:
        return mean_diff, np.nan, np.nan, np.nan, None, np.nan, np.nan

    s1_sq = np.var(vals1, ddof=1)
    s2_sq = np.var(vals2, ddof=1)

    se_diff = np.sqrt(s1_sq / n1 + s2_sq / n2)

    if se_diff == 0:
        return mean_diff, mean_diff, mean_diff, np.nan, None, np.nan, np.nan

    # Welch-Satterthwaite degrees of freedom (Folie 50)
    n_df = (s1_sq / n1 + s2_sq / n2) ** 2 / (
        (s1_sq / n1) ** 2 / (n1 - 1) + (s2_sq / n2) ** 2 / (n2 - 1))

    t_crit = sp_stats.t.ppf(1 - ALPHA / 2, n_df)
    ci_lower = mean_diff - t_crit * se_diff
    ci_upper = mean_diff + t_crit * se_diff

    # t-statistic and p-value
    t_stat = mean_diff / se_diff
    p_value = 2 * (1 - sp_stats.t.cdf(abs(t_stat), n_df))

    # Significant if CI does not include 0 (Folie 49)
    significant = ci_lower > 0 or ci_upper < 0

    return mean_diff, ci_lower, ci_upper, n_df, significant, t_stat, p_value


def main():
    print("=" * 70)
    print("39 — SCIENTIFIC BENCHMARKING ANALYSIS")
    print("     (nach Kounev, Systems Benchmarking, Kapitel 4)")
    print("=" * 70)

    # ═══════════════════════════════════════════════════════════════════
    # 1. QUERY PER-EXPERIMENT BASELINE PERCENTILES
    # ═══════════════════════════════════════════════════════════════════
    print("\n--- Querying per-experiment baseline metrics ---")

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
            AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_lat
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL} AND r.phase_name = 'Baseline'
        GROUP BY e.id, e.architecture, e.auth_strategy, algo, with_cf,
                 e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 500
    """)

    for col in ['p50', 'p95', 'p99', 'mean_lat']:
        per_exp[col] = per_exp[col].astype(float)
    per_exp['hw'] = per_exp.apply(hw_label_from_row, axis=1)
    per_exp['auth_label'] = per_exp.apply(
        lambda r: auth_label_detailed(
            r['auth_strategy'],
            r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
            bool(r['with_cf']) if r['with_cf'] else False
        ), axis=1)

    # Config grouping key
    per_exp['config'] = per_exp.apply(
        lambda r: f"{r['architecture']}|{r['auth_strategy']}|{r['algo']}|{r['ram_in_mb']}|{r['cpu_in_vcpu']}|{r['with_cf']}",
        axis=1)

    print(f"  Loaded {len(per_exp)} experiment records")
    print(f"  Unique configs: {per_exp['config'].nunique()}")

    # ═══════════════════════════════════════════════════════════════════
    # 2. AGGREGATE OVER REPETITIONS WITH t-CI
    # ═══════════════════════════════════════════════════════════════════
    print("\n--- Aggregating over repetitions with 95% t-CI ---")

    agg_rows = []
    for config, grp in per_exp.groupby('config'):
        p50_vals = grp['p50'].values
        p95_vals = grp['p95'].values
        p99_vals = grp['p99'].values
        mean_vals = grp['mean_lat'].values

        p50_mean, p50_lo, p50_hi, n, _ = t_ci(p50_vals)
        p95_mean, p95_lo, p95_hi, _, _ = t_ci(p95_vals)
        p99_mean, p99_lo, p99_hi, _, p99_se = t_ci(p99_vals)
        mean_mean, mean_lo, mean_hi, _, _ = t_ci(mean_vals)

        row = grp.iloc[0]
        agg_rows.append({
            'config': config,
            'architecture': row['architecture'],
            'auth_strategy': row['auth_strategy'],
            'auth_label': row['auth_label'],
            'algo': row['algo'],
            'with_cf': row['with_cf'],
            'hw': row['hw'],
            'ram_in_mb': row['ram_in_mb'],
            'cpu_in_vcpu': row['cpu_in_vcpu'],
            'n_runs': n,
            'exp_ids': sorted(grp['id'].tolist()),
            # P50
            'p50_mean': p50_mean, 'p50_ci_lo': p50_lo, 'p50_ci_hi': p50_hi,
            # P95
            'p95_mean': p95_mean, 'p95_ci_lo': p95_lo, 'p95_ci_hi': p95_hi,
            # P99
            'p99_mean': p99_mean, 'p99_ci_lo': p99_lo, 'p99_ci_hi': p99_hi,
            'p99_se': p99_se,
            # Mean latency
            'mean_mean': mean_mean, 'mean_ci_lo': mean_lo, 'mean_ci_hi': mean_hi,
        })

    agg = pd.DataFrame(agg_rows)
    print(f"  Aggregated to {len(agg)} config groups")
    print(f"  Runs per config: min={agg['n_runs'].min()}, median={agg['n_runs'].median():.0f}, "
          f"max={agg['n_runs'].max()}")

    # Show CI widths
    agg['ci_width_pct'] = np.where(
        agg['p99_mean'] > 0,
        (agg['p99_ci_hi'] - agg['p99_ci_lo']) / agg['p99_mean'] * 100,
        0)
    multi_run = agg[agg['n_runs'] >= 2]
    if not multi_run.empty:
        print(f"\n  95% CI width (P99) for configs with n≥2:")
        print(f"    Median CI width: ±{multi_run['ci_width_pct'].median():.1f}% of mean")
        print(f"    Max CI width:    ±{multi_run['ci_width_pct'].max():.1f}% of mean")

    # ═══════════════════════════════════════════════════════════════════
    # 2b. SAMPLE SIZE CALCULATION (Kounev Kap. 4, Folie ~38)
    # ═══════════════════════════════════════════════════════════════════
    # n_required = (z_{α/2} × s / (x̄ × e))²
    # where e = desired relative error (e.g., 5% or 10%)
    print("\n--- Sample Size Analysis (Kounev Kap. 4) ---")
    print(f"  Formel: n = (z_{{α/2}} × s / (x̄ × e))²")

    z_alpha2 = sp_stats.norm.ppf(1 - ALPHA / 2)  # 1.96 for 95%
    DESIRED_ERRORS = [0.05, 0.10]  # 5% and 10% relative error

    sample_size_rows = []
    for _, row in agg[agg['n_runs'] >= 2].iterrows():
        for e_rel in DESIRED_ERRORS:
            if row['p99_mean'] > 0 and row['p99_se'] > 0 and not np.isnan(row['p99_se']):
                s = row['p99_se'] * np.sqrt(row['n_runs'])  # recover s from se
                n_req = (z_alpha2 * s / (row['p99_mean'] * e_rel)) ** 2
                n_req = int(np.ceil(n_req))
                sample_size_rows.append({
                    'architecture': row['architecture'],
                    'auth_label': row['auth_label'],
                    'hw': row['hw'],
                    'n_actual': row['n_runs'],
                    'p99_mean': row['p99_mean'],
                    'p99_std': s,
                    'desired_error': f"{e_rel*100:.0f}%",
                    'n_required': n_req,
                    'sufficient': row['n_runs'] >= n_req,
                })

    if sample_size_rows:
        ss_df = pd.DataFrame(sample_size_rows)
        ss_df.to_csv(f"{PLOT_DIR}/sb_sample_size_analysis.csv", index=False)
        print(f"  Saved: {PLOT_DIR}/sb_sample_size_analysis.csv")

        for e_rel in DESIRED_ERRORS:
            subset = ss_df[ss_df['desired_error'] == f"{e_rel*100:.0f}%"]
            n_sufficient = subset['sufficient'].sum()
            n_total = len(subset)
            median_req = subset['n_required'].median()
            max_req = subset['n_required'].max()
            print(f"\n  Für ±{e_rel*100:.0f}% relative Genauigkeit (95%-KI):")
            print(f"    Benötigt: Median n={median_req:.0f}, Max n={max_req}")
            print(f"    Ausreichend mit aktuellem n: {n_sufficient}/{n_total}")

        # Show worst cases
        worst = ss_df[(ss_df['desired_error'] == '10%') & (~ss_df['sufficient'])].sort_values(
            'n_required', ascending=False).head(5)
        if not worst.empty:
            print(f"\n  Konfigurationen mit höchstem Bedarf (für ±10%):")
            for _, w in worst.iterrows():
                print(f"    {w['architecture']}/{w['hw']}/{w['auth_label']}: "
                      f"n_ist={w['n_actual']}, n_soll={w['n_required']}, "
                      f"CV={w['p99_std']/w['p99_mean']*100:.1f}%")

    # ═══════════════════════════════════════════════════════════════════
    # 3. PLOT 1: BASELINE P99 WITH t-CI ERROR BARS
    # ═══════════════════════════════════════════════════════════════════
    print("\n--- Plot 1: Baseline P99 with 95% t-CI ---")

    fig, axes = plt.subplots(3, 1, figsize=(12, 15))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = agg[(agg['architecture'] == arch) &
                        (~agg['auth_strategy'].isin(['edge-selective'])) &
                        (agg['with_cf'] == False)]
        if arch_data.empty:
            ax.set_title(f'{arch} (keine Daten)')
            continue

        # Exclude argon2id for cleaner plot
        arch_data = arch_data[arch_data['algo'] != 'argon2id']

        auth_labels = sorted(arch_data['auth_label'].unique())
        hw_order = {'S': 1, 'M': 2, 'L': 3, 'XL': 4}
        hw_labels = sorted(arch_data['hw'].unique(),
                           key=lambda x: hw_order.get(x, int(x.replace('MB', '')) if 'MB' in x else 0))

        x = np.arange(len(hw_labels))
        width = 0.8 / max(len(auth_labels), 1)

        missing_slots = []
        for i, auth_l in enumerate(auth_labels):
            means = []
            errs_lo = []
            errs_hi = []
            ns = []
            present = []
            for hw in hw_labels:
                match = arch_data[(arch_data['auth_label'] == auth_l) & (arch_data['hw'] == hw)]
                if not match.empty:
                    r = match.iloc[0]
                    means.append(r['p99_mean'])
                    if r['n_runs'] >= 2 and not np.isnan(r['p99_ci_lo']):
                        errs_lo.append(r['p99_mean'] - r['p99_ci_lo'])
                        errs_hi.append(r['p99_ci_hi'] - r['p99_mean'])
                    else:
                        errs_lo.append(0)
                        errs_hi.append(0)
                    ns.append(r['n_runs'])
                    present.append(True)
                else:
                    means.append(0)
                    errs_lo.append(0)
                    errs_hi.append(0)
                    ns.append(0)
                    present.append(False)

            offset = (i - len(auth_labels) / 2 + 0.5) * width
            color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
            bars = ax.bar(x + offset, means, width, label=auth_l,
                         color=color, alpha=0.85,
                         yerr=[errs_lo, errs_hi],
                         capsize=3, ecolor='black', error_kw={'linewidth': 1})

            for j, p in enumerate(present):
                if not p:
                    missing_slots.append(x[j] + offset)

            # Annotate n
            for j, (m, n) in enumerate(zip(means, ns)):
                if m > 0 and n >= 2:
                    ax.annotate(f'n={n}', xy=(x[j] + offset, m + errs_hi[j]),
                               xytext=(0, 3), textcoords='offset points',
                               ha='center', fontsize=9, color='gray')

        # Mark missing data slots
        y_hi = ax.get_ylim()[1]
        for xm in missing_slots:
            ax.text(xm, y_hi * 0.02, '–',
                    ha='center', va='bottom', fontsize=9,
                    color='#999', fontweight='bold')

        ax.set_xticks(x)
        ax.set_xticklabels(hw_labels, fontsize=11)
        ax.tick_params(axis='y', labelsize=11)
        ax.set_xlabel('Hardware-Tier', fontsize=12)
        ax.set_ylabel('P99-Latenz (ms)', fontsize=12)
        ax.set_title(f'{arch.capitalize()}', fontweight='bold', fontsize=14)
        ax.legend(fontsize=11, loc='upper right')
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('Baseline P99-Latenz je Architektur und Auth-Strategie\n'
                 '(Mittelwert über Wiederholungen, Fehlerbalken = 95%-KI, t-Verteilung)',
                 fontsize=15, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/sb_baseline_p99_with_ci.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"  Saved: {path}")
    plt.close()

    # ═══════════════════════════════════════════════════════════════════
    # 4. COMPUTE ΔAuth WITH WELCH t-TEST
    # ═══════════════════════════════════════════════════════════════════
    print("\n--- Computing ΔAuth with Welch t-test (Kounev Folie 49-55) ---")

    delta_rows = []
    for (arch, ram, with_cf), grp in per_exp.groupby(['architecture', 'ram_in_mb', 'with_cf']):
        none_exps = grp[grp['auth_strategy'] == 'none']
        if none_exps.empty:
            none_exps = per_exp[(per_exp['architecture'] == arch) &
                                (per_exp['ram_in_mb'] == ram) &
                                (per_exp['auth_strategy'] == 'none')]
        if none_exps.empty:
            continue

        none_p99 = none_exps['p99'].values
        none_p50 = none_exps['p50'].values

        for auth in ['service-integrated', 'service-integrated-manual', 'edge', 'edge-selective']:
            auth_exps = grp[grp['auth_strategy'] == auth]
            if auth_exps.empty:
                continue

            for algo, algo_grp in auth_exps.groupby('algo'):
                auth_p99 = algo_grp['p99'].values
                auth_p50 = algo_grp['p50'].values
                n_auth = len(auth_p99)
                n_none = len(none_p99)

                # Welch t-test for P99 difference
                diff_p99, ci_lo_p99, ci_hi_p99, df_w, sig_p99, t_stat, p_val = \
                    welch_t_ci_diff(auth_p99, none_p99)

                # Same for P50
                diff_p50, ci_lo_p50, ci_hi_p50, _, sig_p50, _, _ = \
                    welch_t_ci_diff(auth_p50, none_p50)

                # Point estimates for reference
                none_p99_mean = np.mean(none_p99)
                auth_p99_mean = np.mean(auth_p99)
                pct_p99 = (diff_p99 / none_p99_mean * 100) if none_p99_mean > 0 else 0

                cf_bool = bool(with_cf) if with_cf is not None else False
                label = auth_label_detailed(
                    auth, algo if auth == 'service-integrated-manual' else None, cf_bool)
                hw = hw_label_from_row({'architecture': arch, 'ram_in_mb': ram,
                                        'cpu_in_vcpu': algo_grp.iloc[0]['cpu_in_vcpu']})

                delta_rows.append({
                    'architecture': arch,
                    'hw': hw,
                    'ram_in_mb': ram,
                    'auth_strategy': auth,
                    'auth_label': label,
                    'algo': algo,
                    'with_cf': cf_bool,
                    'n_none': n_none,
                    'n_auth': n_auth,
                    'none_p99_mean': none_p99_mean,
                    'auth_p99_mean': auth_p99_mean,
                    'delta_p99': diff_p99,
                    'ci_lo_p99': ci_lo_p99,
                    'ci_hi_p99': ci_hi_p99,
                    'pct_p99': pct_p99,
                    'delta_p50': diff_p50,
                    'ci_lo_p50': ci_lo_p50,
                    'ci_hi_p50': ci_hi_p50,
                    'df_welch': df_w,
                    't_statistic': t_stat,
                    'p_value': p_val,
                    'significant': sig_p99,
                    'sig_level': '***' if (p_val is not None and not np.isnan(p_val) and p_val < 0.001) else
                                 '**' if (p_val is not None and not np.isnan(p_val) and p_val < 0.01) else
                                 '*' if (p_val is not None and not np.isnan(p_val) and p_val < 0.05) else 'n.s.',
                })

    delta = pd.DataFrame(delta_rows).sort_values(
        ['architecture', 'ram_in_mb', 'auth_strategy', 'algo', 'with_cf'])

    # ── Testbare Vergleiche zählen ──
    testable = delta['p_value'].apply(
        lambda x: x is not None and isinstance(x, (int, float, np.floating)) and not np.isnan(x))
    m = testable.sum()
    print(f"  Testbare Vergleiche (n≥2 beide Seiten): {m}")
    # NOTE: Multiple-comparison correction for between-experiment analysis
    # is handled via ANOVA + Method of Contrasts (script 41, Kounev Ch. 5).
    # This script reports individual Welch-t CIs as supplementary evidence.

    delta.to_csv(f"{PLOT_DIR}/sb_delta_auth_significance.csv", index=False)
    print(f"  Saved: {PLOT_DIR}/sb_delta_auth_significance.csv")

    # Print significance table (Welch-t CI-based)
    print(f"\n  {'Arch':>6s} | {'HW':>6s} | {'Auth':>25s} | {'n':>5s} | "
          f"{'ΔP99':>8s} | {'95%-KI':>22s} | {'p':>8s} | Sig")
    print(f"  {'-'*6} | {'-'*6} | {'-'*25} | {'-'*5} | {'-'*8} | {'-'*22} | {'-'*8} | ---")
    for _, r in delta.iterrows():
        ci_str = f"[{r['ci_lo_p99']:.0f}, {r['ci_hi_p99']:.0f}]" \
            if not np.isnan(r['ci_lo_p99']) else 'N/A (n<2)'
        p_str = f"{r['p_value']:.4f}" if not np.isnan(r['p_value']) else 'N/A'
        print(f"  {r['architecture'][:6]:>6s} | {r['hw']:>6s} | {r['auth_label']:>25s} | "
              f"{r['n_none']}+{r['n_auth']:>2d} | {r['delta_p99']:>+7.0f}ms | {ci_str:>22s} | "
              f"{p_str:>8s} | {r['sig_level']}")

    n_sig_raw = delta['significant'].sum()
    n_total = len(delta[delta['significant'].notna()])
    if n_total > 0:
        print(f"\n  Signifikante Vergleiche (Welch-t, KI schließt 0 nicht ein): {n_sig_raw}/{n_total} "
              f"({n_sig_raw / n_total * 100:.0f}%)")
        print(f"  Hinweis: Multiple-Comparison-Kontrolle via ANOVA + Kontraste (Skript 41)")

    # ── Log: Welche Konfigurationen fehlen für statistische Tests? ──
    untestable = delta[~testable & (~delta['auth_strategy'].isin(['edge-selective']))]
    if not untestable.empty:
        print(f"\n  ⚠ {len(untestable)} Vergleiche NICHT testbar (n<2 auf mindestens einer Seite):")
        print(f"    {'Arch':>6s} | {'HW':>6s} | {'Auth':>25s} | n_none | n_auth | Fehlend")
        print(f"    {'-'*6} | {'-'*6} | {'-'*25} | {'-'*6} | {'-'*6} | -------")
        for _, r in untestable.sort_values(['architecture', 'ram_in_mb', 'auth_label']).iterrows():
            n_n = int(r['n_none'])
            n_a = int(r['n_auth'])
            missing = []
            if n_n < 2:
                missing.append(f"+{2-n_n} none")
            if n_a < 2:
                missing.append(f"+{2-n_a} auth")
            print(f"    {r['architecture'][:6]:>6s} | {r['hw']:>6s} | {r['auth_label']:>25s} | "
                  f"{n_n:>6d} | {n_a:>6d} | {', '.join(missing)}")

        # Summary: which configs would benefit most from additional runs
        need_one_more = untestable[(untestable['n_none'] == 1) | (untestable['n_auth'] == 1)]
        print(f"\n  → {len(need_one_more)} Vergleiche bräuchten nur 1 zusätzlichen Benchmark-Run")

    # ═══════════════════════════════════════════════════════════════════
    # 5. PLOT 2: ΔAuth P99 WITH CI ERROR BARS AND SIGNIFICANCE
    # ═══════════════════════════════════════════════════════════════════
    print("\n--- Plot 2: ΔAuth P99 with 95% Welch-t-CI ---")

    fig, axes = plt.subplots(1, 3, figsize=(20, 8))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = delta[(delta['architecture'] == arch) &
                          (~delta['auth_strategy'].isin(['edge-selective'])) &
                          (delta['with_cf'] == False)]
        if arch_data.empty:
            ax.set_title(f'{arch} (keine Daten)')
            continue

        auth_labels = sorted(arch_data['auth_label'].unique())
        hw_order = {'S': 1, 'M': 2, 'L': 3, 'XL': 4}
        hw_labels = sorted(arch_data['hw'].unique(),
                           key=lambda x: hw_order.get(x, int(x.replace('MB', '')) if 'MB' in x else 0))

        x = np.arange(len(hw_labels))
        width = 0.8 / max(len(auth_labels), 1)

        for i, auth_l in enumerate(auth_labels):
            means = []
            errs_lo = []
            errs_hi = []
            sigs = []
            for hw in hw_labels:
                match = arch_data[(arch_data['auth_label'] == auth_l) & (arch_data['hw'] == hw)]
                if not match.empty:
                    r = match.iloc[0]
                    means.append(r['delta_p99'])
                    if not np.isnan(r['ci_lo_p99']):
                        errs_lo.append(r['delta_p99'] - r['ci_lo_p99'])
                        errs_hi.append(r['ci_hi_p99'] - r['delta_p99'])
                    else:
                        errs_lo.append(0)
                        errs_hi.append(0)
                    sigs.append(r['sig_level'])
                else:
                    means.append(0)
                    errs_lo.append(0)
                    errs_hi.append(0)
                    sigs.append('')

            offset = (i - len(auth_labels) / 2 + 0.5) * width
            color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
            bars = ax.bar(x + offset, means, width, label=auth_l,
                         color=color, alpha=0.85,
                         yerr=[errs_lo, errs_hi],
                         capsize=3, ecolor='black', error_kw={'linewidth': 1})

            # Mark significance (Welch-t-Test)
            for j, (m, sig) in enumerate(zip(means, sigs)):
                if sig and sig not in ('n.s.', 'N/A', '') and m != 0:
                    y_pos = m + errs_hi[j] if m > 0 else m - errs_lo[j]
                    ax.annotate(sig, xy=(x[j] + offset, y_pos),
                               xytext=(0, 3 if m > 0 else -10),
                               textcoords='offset points',
                               ha='center', fontsize=7, fontweight='bold', color='darkgreen')
                elif sig == 'n.s.' and m != 0:
                    y_pos = m + errs_hi[j] if m > 0 else m - errs_lo[j]
                    ax.annotate('n.s.', xy=(x[j] + offset, y_pos),
                               xytext=(0, 3 if m > 0 else -10),
                               textcoords='offset points',
                               ha='center', fontsize=5, color='gray')

        ax.set_xticks(x)
        ax.set_xticklabels(hw_labels)
        ax.set_xlabel('Hardware-Tier')
        ax.set_ylabel('$\\Delta_{Auth}$ P99 (ms)')
        ax.set_title(f'{arch.capitalize()}', fontweight='bold')
        ax.legend(fontsize=6, loc='upper left')
        ax.grid(axis='y', alpha=0.3)
        ax.axhline(y=0, color='black', linewidth=0.8)

    fig.suptitle('Authentifizierungs-Overhead $\\Delta_{Auth}$ (P99) mit 95%-Konfidenzintervall\n'
                 '(Welch-t-Test, * p<0,05 ** p<0,01 *** p<0,001)',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/sb_delta_auth_with_ci.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"  Saved: {path}")
    plt.close()

    # ═══════════════════════════════════════════════════════════════════
    # 6. PLOT 3: HARDWARE SCALING WITH CI (Line plot)
    # ═══════════════════════════════════════════════════════════════════
    print("\n--- Plot 3: Hardware Scaling with 95% t-CI ---")

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_agg = agg[(agg['architecture'] == arch) &
                       (~agg['auth_strategy'].isin(['edge-selective'])) &
                       (agg['with_cf'] == False) &
                       (agg['algo'] != 'argon2id')]
        if arch_agg.empty:
            ax.set_title(f'{arch} (keine Daten)')
            continue

        def hw_numeric(hw_str):
            mapping = {'S': 256, 'M': 512, 'L': 1024, 'XL': 4096}
            if 'MB' in hw_str:
                return int(hw_str.replace('MB', ''))
            return mapping.get(hw_str, 0)

        for auth_l in sorted(arch_agg['auth_label'].unique()):
            subset = arch_agg[arch_agg['auth_label'] == auth_l].copy()
            subset['hw_num'] = subset['hw'].apply(hw_numeric)
            subset = subset.sort_values('hw_num')

            color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
            ax.errorbar(subset['hw_num'], subset['p99_mean'],
                       yerr=[subset['p99_mean'] - subset['p99_ci_lo'].fillna(subset['p99_mean']),
                             subset['p99_ci_hi'].fillna(subset['p99_mean']) - subset['p99_mean']],
                       fmt='o-', label=auth_l, color=color,
                       linewidth=2, markersize=6, capsize=4)

        if arch == 'faas':
            ax.set_xlabel('Speicher (MB)')
            ticks = sorted(arch_agg['hw'].apply(hw_numeric).unique())
            ax.set_xticks(ticks)
            ax.set_xticklabels([f'{t}MB' for t in ticks], fontsize=8)
        else:
            ax.set_xlabel('Hardware-Tier')
            ticks = sorted(arch_agg['hw'].apply(hw_numeric).unique())
            ax.set_xticks(ticks)
            labels_map = {256: 'S', 512: 'M', 1024: 'L', 4096: 'XL'}
            ax.set_xticklabels([labels_map.get(t, str(t)) for t in ticks])

        ax.set_ylabel('P99-Latenz (ms)')
        ax.set_title(f'{arch.capitalize()}', fontweight='bold')
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
        ax.set_yscale('log')

    fig.suptitle('Hardware-Skalierung: P99-Latenz vs. Ressourcenallokation\n'
                 '(Mittelwert über Wiederholungen, Fehlerbalken = 95%-KI, t-Verteilung)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/sb_hardware_scaling_with_ci.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"  Saved: {path}")
    plt.close()

    # ═══════════════════════════════════════════════════════════════════
    # 7. PLOT 4: Forest plot of ΔAuth CIs (all comparisons)
    # ═══════════════════════════════════════════════════════════════════
    print("\n--- Plot 4: Forest Plot aller ΔAuth-Vergleiche ---")

    # Only configs with proper CIs (n>=2 both sides)
    forest_data = delta[(~delta['auth_strategy'].isin(['edge-selective'])) &
                        (delta['with_cf'] == False) &
                        (~delta['ci_lo_p99'].isna())].copy()

    if not forest_data.empty:
        forest_data['label'] = forest_data.apply(
            lambda r: f"{r['architecture'][:3].upper()}/{r['auth_label']}/{r['hw']}", axis=1)
        forest_data = forest_data.sort_values('delta_p99')

        fig, ax = plt.subplots(figsize=(12, max(6, len(forest_data) * 0.35)))
        y_pos = np.arange(len(forest_data))

        colors = []
        for _, r in forest_data.iterrows():
            sig = r['significant']
            if sig is not None and not (isinstance(sig, float) and np.isnan(sig)):
                if bool(sig):
                    colors.append('darkgreen' if r['delta_p99'] > 0 else 'darkred')
                else:
                    colors.append('gray')
            else:
                colors.append('orange')

        # Add significance markers to labels
        labels_with_sig = []
        for _, r in forest_data.iterrows():
            base = f"{r['architecture'][:3].upper()}/{r['auth_label']}/{r['hw']}"
            sig_marker = r['sig_level'] if r['sig_level'] not in ('N/A', None) else ''
            labels_with_sig.append(f"{base}  {sig_marker}" if sig_marker else base)

        ax.barh(y_pos, forest_data['delta_p99'],
               xerr=[forest_data['delta_p99'] - forest_data['ci_lo_p99'],
                     forest_data['ci_hi_p99'] - forest_data['delta_p99']],
               color=colors, alpha=0.7, capsize=3, ecolor='black', height=0.6)

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels_with_sig, fontsize=6)
        ax.set_xlabel('$\\Delta_{Auth}$ P99 (ms) mit 95%-KI')
        ax.axvline(x=0, color='red', linewidth=1.5, linestyle='--',
                   label='Null-Hypothese: kein Unterschied')
        ax.set_title('Forest-Plot: $\\Delta_{Auth}$ P99 mit 95%-Konfidenzintervall (Welch-t)\n'
                     'Grün = signifikant (KI schließt 0 nicht ein), Rot = signifikant negativ, '
                     'Grau = nicht signifikant',
                     fontweight='bold', fontsize=11)
        ax.legend(fontsize=8)
        ax.grid(axis='x', alpha=0.3)

        plt.tight_layout()
        path = f"{PLOT_DIR}/sb_forest_plot_delta_auth.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"  Saved: {path}")
        plt.close()

    # ═══════════════════════════════════════════════════════════════════
    # 8. SUMMARY TABLE FOR THESIS
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("ZUSAMMENFASSUNG DER STATISTISCHEN ANALYSE")
    print("=" * 70)

    print(f"""
Methodik (nach Kounev et al., Kap. 4 & 5):
  • Punktschätzer: arithmetisches Mittel über n Wiederholungen
  • Konfidenzintervall: 95%-KI mittels t-Verteilung (df = n−1)
    Formel: x̄ ± t_{{α/2; n-1}} × s/√n
  • Signifikanztest (ergänzend): Welch-t-Test für ΔAuth (non-corresponding measurements)
    Signifikant, wenn 95%-KI die Null nicht einschließt
  • Freiheitsgrade: Welch-Satterthwaite-Approximation
  • Multiple-Comparison-Kontrolle: ANOVA + Methode der Kontraste (Skript 41, Kounev Kap. 5)

Ergebnisse:
  • {len(agg)} Konfigurationen analysiert
  • {len(agg[agg['n_runs'] >= 2])} davon mit ≥2 Wiederholungen (CI berechenbar)
  • {len(agg[agg['n_runs'] >= 3])} davon mit ≥3 Wiederholungen
  • {n_sig_raw}/{n_total} ΔAuth-Vergleiche signifikant (Welch-t, KI schließt 0 nicht ein)

WICHTIG: Bei n=3 hat die t-Verteilung df=2, t_{{0.025,2}} = 4.303.
  Das resultierende KI ist ~2.5× breiter als bei Normalverteilungsannahme.
  Dies spiegelt die erhöhte Unsicherheit bei kleiner Stichprobe korrekt wider.

Begründung der Methodik:
  • Primär: Einfaktorielle ANOVA als Omnibus-Test (Kounev, Kap. 5, Folien 19-28),
    gefolgt von der Methode der Kontraste für spezifische Paare (Folien 29-35).
    → Siehe Skript 41 (41_anova_contrasts.py).
  • Ergänzend: Welch-t-Test (Kounev, Kap. 4, Folien 49-55) als Robustheitscheck
    bei ungleichen Varianzen (Levene-Test). Die Experimente wurden zu unterschiedlichen
    Zeitpunkten auf unabhängiger Infrastruktur durchgeführt → non-corresponding
    measurements.
""")

    # Compact results table
    agg.to_csv(f"{PLOT_DIR}/sb_aggregated_with_ci.csv", index=False)
    print(f"Saved: {PLOT_DIR}/sb_aggregated_with_ci.csv")


if __name__ == '__main__':
    main()
