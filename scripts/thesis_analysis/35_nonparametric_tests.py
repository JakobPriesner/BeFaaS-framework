#!/usr/bin/env python3
"""
35 — Parametric Significance Tests (ZGS + t-Verteilung)

Applies the Central Limit Theorem (ZGS) approach from the Systems Benchmarking
lecture (Kounev, Chapter 4-5): Group individual requests into 60-second time
blocks, compute P99 per block, then apply parametric tests on block-level
aggregates:
  - Welch-t-Test for pairwise comparisons (auth vs none) on block-level P99
  - One-factor ANOVA for multi-group comparisons (all auth strategies per arch/hw)
  - Method of Contrasts for post-hoc pairwise comparisons (Kounev Kap. 5)
  - SSA/SST as effect size measure (proportion of variance explained)
  - Practical significance threshold: 10ms

Methodology: Kounev, Kapitel 4 (CI, t-Test) und Kapitel 5 (ANOVA, Kontraste).
Multiple-comparison control via ANOVA gatekeeper (contrasts only if F > F_crit).

Now differentiates:
  - Manual (bcrypt) vs Manual (argon2id) tested SEPARATELY
  - CloudFront (+CF) vs non-CF variants tested SEPARATELY
  - Includes new experiments (194-196)

Outputs: significance_tests.csv, effect_sizes.csv, anova_block_level.csv,
         significance_summary.tex
"""

import sys
import warnings
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import numpy as np
from scipy import stats as sp_stats
from itertools import combinations

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed)

warnings.filterwarnings('ignore', category=FutureWarning)

PROTECTED_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)

PRACTICAL_THRESHOLD_MS = 10
BLOCK_SIZE_MS = 60000        # 60-second blocks (ZGS grouping)
MIN_REQUESTS_PER_BLOCK = 10  # Minimum requests for a block to be valid
CONFIDENCE_LEVEL = 0.95
ALPHA = 1 - CONFIDENCE_LEVEL


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    mapping = {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}
    return mapping.get(float(cpu), f"{cpu}vCPU")


def get_protected_sql(arch):
    eps = PROTECTED_FAAS if arch == 'faas' else PROTECTED_CONTAINER
    return ','.join(f"'{e}'" for e in eps)


def load_baseline_latencies_with_time(experiment_id, arch, auth_only=True):
    """Load baseline latencies with relative_time_ms for block grouping."""
    endpoint_clause = ""
    if auth_only:
        eps = get_protected_sql(arch)
        endpoint_clause = f"AND r.endpoint IN ({eps})"

    df = query_df(f"""
        SELECT r.latency_ms, r.relative_time_ms
        FROM requests r
        WHERE r.experiment_id = {experiment_id}
          AND r.phase_name = 'Baseline'
          AND NOT r.is_error
          {endpoint_clause}
        ORDER BY r.relative_time_ms
    """)
    return df


def compute_block_p99(df, block_size_ms=BLOCK_SIZE_MS):
    """Group requests into time blocks and compute P99 per block (ZGS).

    Returns array of per-block P99 values.
    """
    if df.empty:
        return np.array([])

    latencies = df['latency_ms'].values
    times = df['relative_time_ms'].values
    block_ids = (times // block_size_ms).astype(int)
    unique_blocks = np.unique(block_ids)

    block_p99s = []
    for b in unique_blocks:
        mask = block_ids == b
        block_lats = latencies[mask]
        if len(block_lats) >= MIN_REQUESTS_PER_BLOCK:
            block_p99s.append(np.percentile(block_lats, 99))

    return np.array(block_p99s)


def welch_t_ci(group1, group2, confidence=CONFIDENCE_LEVEL):
    """Welch t-test CI for difference of means (Kounev Kap. 4, Folie 49-55).

    Non-corresponding measurements with potentially unequal variances.
    CI = (x̄₁ - x̄₂) ± t_{α/2; ν*} × √(s₁²/n₁ + s₂²/n₂)
    where ν* = Welch-Satterthwaite approximation.

    Returns: (diff, ci_lo, ci_hi, df, significant, t_stat, p_value)
    """
    n1, n2 = len(group1), len(group2)
    if n1 < 2 or n2 < 2:
        diff = np.mean(group1) - np.mean(group2)
        return diff, np.nan, np.nan, np.nan, None, np.nan, np.nan

    s1_sq = np.var(group1, ddof=1)
    s2_sq = np.var(group2, ddof=1)
    se = np.sqrt(s1_sq / n1 + s2_sq / n2)
    if se == 0:
        diff = np.mean(group1) - np.mean(group2)
        return diff, diff, diff, np.nan, None, np.nan, np.nan

    diff = np.mean(group1) - np.mean(group2)

    # Welch-Satterthwaite degrees of freedom
    df = (s1_sq / n1 + s2_sq / n2) ** 2 / (
        (s1_sq / n1) ** 2 / (n1 - 1) + (s2_sq / n2) ** 2 / (n2 - 1))

    alpha = 1 - confidence
    t_crit = sp_stats.t.ppf(1 - alpha / 2, df)
    ci_lo = diff - t_crit * se
    ci_hi = diff + t_crit * se

    t_stat = diff / se
    p_value = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df))

    # Significant if CI does not include 0 (Kounev Folie 49)
    significant = ci_lo > 0 or ci_hi < 0

    return diff, ci_lo, ci_hi, df, significant, t_stat, p_value


def main():
    print("=" * 70)
    print("35 — PARAMETRIC SIGNIFICANCE TESTS (ZGS + t-Verteilung)")
    print("=" * 70)

    # ── 1. Get experiment configurations (INCLUDING argon2id and CF) ──
    configs = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu
        FROM experiments e
        WHERE {EXCLUDE_SQL}
        ORDER BY e.architecture, e.ram_in_mb, e.auth_strategy
    """)

    # ── 2. Pairwise Welch-t-Test + CI (on block-level P99, Kounev Kap. 4) ──
    print("\n--- PAIRWISE TESTS (auth vs none, block-level P99, Welch-t) ---")
    pairwise_results = []

    for (arch, ram, with_cf), grp in configs.groupby(['architecture', 'ram_in_mb', 'with_cf']):
        none_exps = grp[grp['auth_strategy'] == 'none']['id'].values
        if len(none_exps) == 0:
            none_exps = configs[(configs['architecture'] == arch) &
                                (configs['ram_in_mb'] == ram) &
                                (configs['auth_strategy'] == 'none')]['id'].values
        if len(none_exps) == 0:
            continue

        cpu = grp.iloc[0]['cpu']
        hw = hw_label(arch, ram, cpu)
        cf_bool = bool(with_cf)

        for auth_strategy in ['service-integrated', 'service-integrated-manual', 'edge']:
            auth_grp = grp[grp['auth_strategy'] == auth_strategy]
            if auth_grp.empty:
                continue

            for algo, algo_exps in auth_grp.groupby('algo'):
                label = auth_label_detailed(
                    auth_strategy,
                    algo if auth_strategy == 'service-integrated-manual' else None,
                    cf_bool)

                for auth_id in algo_exps['id'].values:
                    for none_id in none_exps:
                        print(f"  Welch-t: {arch}/{hw}/{label} E{auth_id} vs E{none_id} ...",
                              end=" ", flush=True)

                        auth_df = load_baseline_latencies_with_time(auth_id, arch, auth_only=True)
                        none_df = load_baseline_latencies_with_time(none_id, arch, auth_only=True)

                        if len(auth_df) < 50 or len(none_df) < 50:
                            print("insufficient data")
                            continue

                        # ZGS: compute block-level P99
                        auth_blocks = compute_block_p99(auth_df)
                        none_blocks = compute_block_p99(none_df)

                        if len(auth_blocks) < 2 or len(none_blocks) < 2:
                            print("insufficient blocks")
                            continue

                        # Welch-t-Test with CI on block-level P99 (Kounev Kap. 4)
                        diff, ci_lo, ci_hi, df_w, sig, t_stat, p_val = \
                            welch_t_ci(auth_blocks, none_blocks)

                        # Also compute overall P99 difference for reference
                        auth_p99 = np.percentile(auth_df['latency_ms'].values, 99)
                        none_p99 = np.percentile(none_df['latency_ms'].values, 99)
                        p99_diff = auth_p99 - none_p99

                        practically_sig = abs(diff) >= PRACTICAL_THRESHOLD_MS

                        sig_str = "SIG" if sig else "n.s."
                        print(f"Δ={diff:+.1f}ms, KI=[{ci_lo:+.1f},{ci_hi:+.1f}], "
                              f"p={p_val:.2e} [{sig_str}]")

                        pairwise_results.append({
                            'architecture': arch,
                            'hw': hw,
                            'ram_in_mb': ram,
                            'auth_strategy': auth_strategy,
                            'auth_label': label,
                            'algo': algo,
                            'with_cf': cf_bool,
                            'auth_exp_id': auth_id,
                            'none_exp_id': none_id,
                            'n_auth_requests': len(auth_df),
                            'n_none_requests': len(none_df),
                            'n_auth_blocks': len(auth_blocks),
                            'n_none_blocks': len(none_blocks),
                            'mean_diff_ms': diff,
                            'ci_lo_ms': ci_lo,
                            'ci_hi_ms': ci_hi,
                            'df_welch': df_w,
                            't_statistic': t_stat,
                            'p_value': p_val,
                            'significant': sig,
                            'p99_diff_ms': p99_diff,
                            'auth_p99': auth_p99,
                            'none_p99': none_p99,
                            'practically_significant': practically_sig,
                        })

    pw_df = pd.DataFrame(pairwise_results)

    if not pw_df.empty:
        pw_df.to_csv(f"{PLOT_DIR}/significance_tests.csv", index=False)
        print(f"\nSaved: {PLOT_DIR}/significance_tests.csv")

        # Summary per (arch, hw, auth_label)
        effect_summary = pw_df.groupby(['architecture', 'hw', 'auth_label']).agg(
            mean_diff=('mean_diff_ms', 'mean'),
            mean_p99_diff=('p99_diff_ms', 'mean'),
            n_pairs=('mean_diff_ms', 'count'),
            all_stat_sig=('significant', 'all'),
            all_pract_sig=('practically_significant', 'all'),
        ).reset_index()

        effect_summary.to_csv(f"{PLOT_DIR}/effect_sizes.csv", index=False)
        print(f"Saved: {PLOT_DIR}/effect_sizes.csv")

        print("\n--- SUMMARY ---")
        for _, r in effect_summary.iterrows():
            stat = "SIG" if r['all_stat_sig'] else "n.s."
            pract = "PRACT" if r['all_pract_sig'] else "sub-threshold"
            print(f"  {r['architecture']:>14s}/{r['hw']:>5s}/{r['auth_label']:>28s}: "
                  f"Δ={r['mean_diff']:+.1f}ms, "
                  f"ΔP99={r['mean_p99_diff']:+.1f}ms  [{stat}] [{pract}]")

    # ── 3. One-Factor ANOVA (multi-group, block-level) ──
    print("\n--- ONE-FACTOR ANOVA (all auth strategies per arch/hw, block-level) ---")
    anova_results = []

    for (arch, ram), grp in configs.groupby(['architecture', 'ram_in_mb']):
        cpu = grp.iloc[0]['cpu']
        hw = hw_label(arch, ram, cpu)

        groups = {}
        for _, row in grp.iterrows():
            label = auth_label_detailed(
                row['auth_strategy'],
                row['algo'] if row['auth_strategy'] == 'service-integrated-manual' else None,
                bool(row['with_cf']))

            if label in groups:
                continue

            df = load_baseline_latencies_with_time(int(row['id']), arch, auth_only=True)
            blocks = compute_block_p99(df)
            if len(blocks) >= 2:
                groups[label] = blocks

        if len(groups) < 3:
            continue

        # One-factor ANOVA (Kounev Kap. 5)
        group_arrays = list(groups.values())
        f_stat, anova_p = sp_stats.f_oneway(*group_arrays)

        # SSA/SST calculation
        all_vals = np.concatenate(group_arrays)
        grand_mean = np.mean(all_vals)
        SSA = sum(len(g) * (np.mean(g) - grand_mean) ** 2 for g in group_arrays)
        SST = np.sum((all_vals - grand_mean) ** 2)
        ssa_ratio = SSA / SST if SST > 0 else 0

        k = len(groups)
        N = len(all_vals)
        df_between = k - 1
        df_within = N - k
        f_critical = sp_stats.f.ppf(1 - ALPHA, df_between, df_within)

        print(f"  {arch}/{hw}: F({df_between},{df_within})={f_stat:.1f} "
              f"(F_krit={f_critical:.2f}), p={anova_p:.2e}, "
              f"SSA/SST={ssa_ratio*100:.0f}%, groups={list(groups.keys())}")

        anova_results.append({
            'architecture': arch,
            'hw': hw,
            'n_groups': k,
            'group_names': ','.join(groups.keys()),
            'h_statistic': f_stat,
            'p_value': anova_p,
            'significant': f_stat > f_critical,
            'f_critical': f_critical,
            'ssa_ratio': ssa_ratio,
        })

        # Post-hoc: Method of Contrasts if ANOVA significant (Kounev Kap. 5)
        if f_stat > f_critical:
            MSE = (SST - SSA) / df_within if df_within > 0 else 0
            group_names = list(groups.keys())
            for g1, g2 in combinations(group_names, 2):
                n1, n2 = len(groups[g1]), len(groups[g2])
                contrast = np.mean(groups[g1]) - np.mean(groups[g2])
                se_c = np.sqrt(MSE * (1.0 / n1 + 1.0 / n2)) if MSE > 0 else 0
                if se_c > 0:
                    t_crit = sp_stats.t.ppf(1 - ALPHA / 2, df_within)
                    ci_lo = contrast - t_crit * se_c
                    ci_hi = contrast + t_crit * se_c
                    sig = ci_lo > 0 or ci_hi < 0
                    sig_str = "*" if sig else ""
                    print(f"    {g1} vs {g2}: Δ={contrast:+.1f}ms, "
                          f"KI=[{ci_lo:+.1f}, {ci_hi:+.1f}] {sig_str}")

    if anova_results:
        anova_df = pd.DataFrame(anova_results)
        anova_df.to_csv(f"{PLOT_DIR}/anova_block_level.csv", index=False)
        print(f"\nSaved: {PLOT_DIR}/anova_block_level.csv")

    # ── 4. Generate LaTeX summary table ──
    if not pw_df.empty:
        print("\n--- GENERATING LaTeX TABLE ---")
        latex_data = pw_df.groupby(['architecture', 'hw', 'auth_label']).agg(
            delta_p99=('p99_diff_ms', 'mean'),
            mean_diff=('mean_diff_ms', 'mean'),
            ci_lo=('ci_lo_ms', 'mean'),
            ci_hi=('ci_hi_ms', 'mean'),
            p_val=('p_value', 'min'),
            n_pairs=('mean_diff_ms', 'count'),
        ).reset_index()

        lines = [
            r"\begin{table}[htbp]",
            r"\centering",
            r"\caption{Statistische Signifikanz des Authentifizierungs-Overheads "
            r"(Welch-$t$-Test auf Block-P99 nach ZGS-Gruppierung, Auth-Only Endpoints, "
            r"Baseline-Phase, alle Algorithmus- und CloudFront-Varianten)}",
            r"\label{tab:significance-tests}",
            r"\small",
            r"\begin{tabular}{llrrrr}",
            r"\toprule",
            r"\textbf{Arch.} & \textbf{Auth} & \textbf{Hardware} & "
            r"\textbf{$\Delta$P99 (ms)} & \textbf{95\,\%-KI} & "
            r"\textbf{$p$} \\",
            r"\midrule",
        ]

        for _, r in latex_data.iterrows():
            p_str = f"$<$0.001" if r['p_val'] < 0.001 else f"{r['p_val']:.3f}"
            ci_str = f"[{r['ci_lo']:+.0f}, {r['ci_hi']:+.0f}]"
            auth_tex = r['auth_label'].replace('(', '\\text{(}').replace(')', '\\text{)}')
            lines.append(
                f"  {r['architecture'].capitalize()} & {auth_tex} & {r['hw']} & "
                f"{r['mean_diff']:+.0f} & {ci_str} & "
                f"{p_str} \\\\"
            )

        lines.extend([
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ])

        tex_path = f"{PLOT_DIR}/significance_summary.tex"
        with open(tex_path, 'w') as f:
            f.write('\n'.join(lines))
        print(f"Saved: {tex_path}")

    print("\n" + "=" * 70)
    print("DONE — Script 35")
    print("=" * 70)


if __name__ == '__main__':
    main()
