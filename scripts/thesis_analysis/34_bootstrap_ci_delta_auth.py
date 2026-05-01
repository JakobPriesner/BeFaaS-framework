#!/usr/bin/env python3
"""
34 — Confidence Intervals for ΔAuth (Request-Level, ZGS + t-Verteilung)

Applies the Central Limit Theorem (ZGS) approach from the Systems Benchmarking
lecture (Kounev, Chapter 4): Group individual requests into 60-second time blocks,
compute the P99 per block, then treat the block-level P99 values as approximately
normally distributed (ZGS). Confidence intervals use the Student-t distribution
(appropriate for small block counts < 30).

Replaces the previous Block-Bootstrap approach with the parametric method
recommended by the lecture.

Now differentiates:
  - Manual (bcrypt) vs Manual (argon2id) separately
  - CloudFront (+CF) vs non-CF variants
  - Includes new experiments (194-196)

Outputs: bootstrap_ci_delta_auth.csv, bootstrap_ci_forest_plot.pdf
"""

import sys
import warnings
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as sp_stats

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, AUTH_COLORS_DETAILED)

warnings.filterwarnings('ignore', category=FutureWarning)

PROTECTED_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)

BLOCK_SIZE_MS = 60000        # 60-second blocks (ZGS grouping)
CONFIDENCE_LEVEL = 0.95
ALPHA = 1 - CONFIDENCE_LEVEL
MIN_REQUESTS_PER_BLOCK = 10  # Minimum requests for a block to be valid


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    mapping = {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}
    return mapping.get(float(cpu), f"{cpu}vCPU")


def get_protected_sql(arch):
    eps = PROTECTED_FAAS if arch == 'faas' else PROTECTED_CONTAINER
    return ','.join(f"'{e}'" for e in eps)


def load_request_latencies(experiment_id, arch, auth_only=True):
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


def t_ci(values, confidence=CONFIDENCE_LEVEL):
    """Compute mean and CI using t-distribution (Kounev Kap. 4).

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


def compute_block_percentiles(data, time_col, percentile,
                               block_size_ms=BLOCK_SIZE_MS):
    """Group requests into time blocks and compute percentile per block (ZGS).

    Returns array of per-block percentile values.
    """
    latencies = data['latency_ms'].values
    times = data[time_col].values

    block_ids = (times // block_size_ms).astype(int)
    unique_blocks = np.unique(block_ids)

    block_pctls = []
    for b in unique_blocks:
        mask = block_ids == b
        block_lats = latencies[mask]
        if len(block_lats) >= MIN_REQUESTS_PER_BLOCK:
            block_pctls.append(np.percentile(block_lats, percentile * 100))

    return np.array(block_pctls)


def compute_within_experiment_ci(auth_exp_id, none_exp_id, arch, percentile=0.99):
    """Compute ΔAuth CI using ZGS + t-distribution on block-level percentiles."""
    auth_data = load_request_latencies(auth_exp_id, arch, auth_only=True)
    none_data = load_request_latencies(none_exp_id, arch, auth_only=True)

    if len(auth_data) < 50 or len(none_data) < 50:
        return None

    # Overall percentiles (point estimates)
    auth_pctl = np.percentile(auth_data['latency_ms'].values, percentile * 100)
    none_pctl = np.percentile(none_data['latency_ms'].values, percentile * 100)
    observed_delta = auth_pctl - none_pctl

    # ZGS: compute per-block percentiles
    auth_block_pctls = compute_block_percentiles(
        auth_data, 'relative_time_ms', percentile)
    none_block_pctls = compute_block_percentiles(
        none_data, 'relative_time_ms', percentile)

    n_auth_blocks = len(auth_block_pctls)
    n_none_blocks = len(none_block_pctls)

    if n_auth_blocks < 2 or n_none_blocks < 2:
        return None

    # Welch-t-Test for the difference of block-level means (Kounev Kap. 4)
    auth_mean = np.mean(auth_block_pctls)
    none_mean = np.mean(none_block_pctls)
    delta_mean = auth_mean - none_mean

    s1_sq = np.var(auth_block_pctls, ddof=1)
    s2_sq = np.var(none_block_pctls, ddof=1)
    se_diff = np.sqrt(s1_sq / n_auth_blocks + s2_sq / n_none_blocks)

    if se_diff == 0:
        return {
            'observed_delta': observed_delta,
            'ci_low': delta_mean,
            'ci_high': delta_mean,
            'auth_pctl': auth_pctl,
            'none_pctl': none_pctl,
            'n_auth': len(auth_data),
            'n_none': len(none_data),
            'n_auth_blocks': n_auth_blocks,
            'n_none_blocks': n_none_blocks,
            'block_mean': delta_mean,
            'block_se': 0.0,
        }

    # Welch-Satterthwaite degrees of freedom
    df_welch = (s1_sq / n_auth_blocks + s2_sq / n_none_blocks) ** 2 / (
        (s1_sq / n_auth_blocks) ** 2 / (n_auth_blocks - 1) +
        (s2_sq / n_none_blocks) ** 2 / (n_none_blocks - 1))

    t_crit = sp_stats.t.ppf(1 - ALPHA / 2, df_welch)
    ci_low = delta_mean - t_crit * se_diff
    ci_high = delta_mean + t_crit * se_diff

    return {
        'observed_delta': observed_delta,
        'ci_low': ci_low,
        'ci_high': ci_high,
        'auth_pctl': auth_pctl,
        'none_pctl': none_pctl,
        'n_auth': len(auth_data),
        'n_none': len(none_data),
        'n_auth_blocks': n_auth_blocks,
        'n_none_blocks': n_none_blocks,
        'block_mean': delta_mean,
        'block_se': se_diff,
    }


def main():
    print("=" * 70)
    print("34 — t-CIs FOR ΔAuth (ZGS + t-Verteilung, Block-Aggregation)")
    print("=" * 70)

    # ── 1. Get experiment configurations (including argon2id) ──
    configs = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu
        FROM experiments e
        WHERE {EXCLUDE_SQL}
        ORDER BY e.architecture, e.ram_in_mb, e.auth_strategy
    """)

    # ── 2. Within-experiment t-CIs (Block-Level) ──
    print("\n--- WITHIN-EXPERIMENT t-CIs (ZGS, Block-Level) ---")
    results = []

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
                        print(f"  t-CI: {arch}/{hw}/{label} "
                              f"E{auth_id} vs E{none_id} ...", end=" ", flush=True)
                        for pctl_name, pctl_val in [('P50', 0.50), ('P95', 0.95), ('P99', 0.99)]:
                            ci = compute_within_experiment_ci(auth_id, none_id, arch, pctl_val)
                            if ci is None:
                                print(f"({pctl_name}: insufficient data)", end=" ")
                                continue

                            results.append({
                                'architecture': arch,
                                'hw': hw,
                                'ram_in_mb': ram,
                                'auth_strategy': auth_strategy,
                                'auth_label': label,
                                'algo': algo,
                                'with_cf': cf_bool,
                                'percentile': pctl_name,
                                'auth_exp_id': auth_id,
                                'none_exp_id': none_id,
                                'delta': ci['observed_delta'],
                                'ci_low': ci['ci_low'],
                                'ci_high': ci['ci_high'],
                                'n_auth_requests': ci['n_auth'],
                                'n_none_requests': ci['n_none'],
                                'n_auth_blocks': ci['n_auth_blocks'],
                                'n_none_blocks': ci['n_none_blocks'],
                                'boot_mean': ci['block_mean'],
                                'boot_std': ci['block_se'],
                            })
                        print("done")

    result_df = pd.DataFrame(results)
    if result_df.empty:
        print("WARNING: No results generated!")
        return

    result_df.to_csv(f"{PLOT_DIR}/bootstrap_ci_delta_auth.csv", index=False)
    print(f"\nSaved: {PLOT_DIR}/bootstrap_ci_delta_auth.csv")

    # ── 3. Summary table (P99 only) ──
    # Pairs within the same (architecture, hw, auth_label) share configuration
    # and differ only in which `none` baseline they were paired against. Averaging
    # per-pair CI bounds would understate uncertainty and is not a valid pooling
    # operation; instead, combine the per-pair block-level Welch estimates via
    # inverse-variance weighting (standard fixed-effect meta-analysis).
    print("\n--- t-CI SUMMARY (P99, Auth-Only, Baseline) ---")
    p99_df = result_df[result_df['percentile'] == 'P99'].copy()

    # Pooled CI uses Student-t with df = k - 1 (k = number of pooled pairs),
    # matching the small-sample rule stated in the evaluation chapter
    # (eq:t-ci). Using z here would underestimate the quantile for small k
    # (for k=3, t_{0.025;2} = 4.303 vs z_{0.025} = 1.960).
    def pool_group(grp):
        deltas = grp['boot_mean'].to_numpy(dtype=float)
        ses = grp['boot_std'].to_numpy(dtype=float)
        # Only pairs with a non-degenerate SE contribute to the pooled CI.
        valid = ses > 0
        k_valid = int(valid.sum())
        if k_valid >= 2:
            w = 1.0 / (ses[valid] ** 2)
            pooled_mean = float(np.sum(w * deltas[valid]) / np.sum(w))
            pooled_se = float(np.sqrt(1.0 / np.sum(w)))
            t_crit = float(sp_stats.t.ppf(1 - ALPHA / 2, df=k_valid - 1))
            ci_low = pooled_mean - t_crit * pooled_se
            ci_high = pooled_mean + t_crit * pooled_se
        elif k_valid == 1:
            # Single contributing pair — report its own within-experiment CI.
            idx = np.flatnonzero(valid)[0]
            pooled_mean = float(deltas[idx])
            pooled_se = float(ses[idx])
            ci_low = float(grp['ci_low'].to_numpy()[idx])
            ci_high = float(grp['ci_high'].to_numpy()[idx])
        else:
            # All pairs had SE=0 (all identical block P99s) — CI collapses to point.
            pooled_mean = float(np.mean(deltas))
            pooled_se = 0.0
            ci_low = ci_high = pooled_mean
        return pd.Series({
            'delta_mean': float(np.mean(grp['delta'])),
            'pooled_mean': pooled_mean,
            'pooled_se': pooled_se,
            'ci_low': ci_low,
            'ci_high': ci_high,
            'n_pairs': len(grp),
            'n_auth_req': float(np.mean(grp['n_auth_requests'])),
            'n_none_req': float(np.mean(grp['n_none_requests'])),
            'n_auth_blk': float(np.mean(grp['n_auth_blocks'])),
            'n_none_blk': float(np.mean(grp['n_none_blocks'])),
        })

    summary = (
        p99_df
        .groupby(['architecture', 'hw', 'auth_label'], as_index=False, group_keys=False)
        .apply(pool_group)
        .reset_index(drop=True)
    )

    for _, r in summary.iterrows():
        sig = "*" if r['ci_low'] > 0 or r['ci_high'] < 0 else ""
        print(f"  {r['architecture']:>14s}/{r['hw']:>5s}/{r['auth_label']:>28s}: "
              f"ΔP99 = {r['pooled_mean']:+7.1f}ms  "
              f"95%-KI [{r['ci_low']:+7.1f}, {r['ci_high']:+7.1f}]  "
              f"({r['n_pairs']:.0f} pairs, ~{r['n_auth_blk']:.0f}+{r['n_none_blk']:.0f} blocks) {sig}")

    # ── 4. Forest plot (combined) ──
    print("\nGenerating forest plot (combined)...")
    fig, ax = plt.subplots(figsize=(14, max(8, len(summary) * 0.45)))

    y_labels = []
    y_pos = []

    for i, (_, r) in enumerate(summary.iterrows()):
        label = f"{r['architecture']}/{r['hw']}/{r['auth_label']}"
        y_labels.append(label)
        y_pos.append(i)

        color = AUTH_COLORS_DETAILED.get(r['auth_label'], '#999')
        ax.errorbar(r['pooled_mean'], i,
                     xerr=[[r['pooled_mean'] - r['ci_low']],
                            [r['ci_high'] - r['pooled_mean']]],
                     fmt='o', color=color, capsize=4, markersize=6, linewidth=1.5)

    ax.axvline(x=0, color='black', linestyle='--', linewidth=0.8, alpha=0.5)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(y_labels, fontsize=7)
    ax.set_xlabel('ΔAuth P99 (ms) — Auth-Only Endpoints, Baseline Phase')
    ax.set_title('95%-Konfidenzintervalle für Authentifizierungs-Overhead\n'
                 '(ZGS + t-Verteilung, 60s-Block-Aggregation, alle Auth-Varianten)',
                 fontweight='bold')
    ax.grid(axis='x', alpha=0.3)
    ax.invert_yaxis()

    plt.tight_layout()
    path = f"{PLOT_DIR}/bootstrap_ci_forest_plot.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # ── 4b. Per-architecture forest plots ──
    arch_display = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}
    for arch in ['faas', 'microservices', 'monolith']:
        arch_summary = summary[summary['architecture'] == arch]
        if arch_summary.empty:
            continue
        n_rows = len(arch_summary)
        fig, ax = plt.subplots(figsize=(12, max(4, n_rows * 0.55)))

        y_labels_a = []
        y_pos_a = []
        for i, (_, r) in enumerate(arch_summary.iterrows()):
            label = f"{r['hw']} / {r['auth_label']}"
            y_labels_a.append(label)
            y_pos_a.append(i)

            color = AUTH_COLORS_DETAILED.get(r['auth_label'], '#999')
            is_sig = r['ci_low'] > 0 or r['ci_high'] < 0
            ax.errorbar(r['pooled_mean'], i,
                        xerr=[[r['pooled_mean'] - r['ci_low']],
                              [r['ci_high'] - r['pooled_mean']]],
                        fmt='o', color=color, capsize=5, markersize=8, linewidth=2,
                        alpha=1.0 if is_sig else 0.5)

        ax.axvline(x=0, color='black', linestyle='--', linewidth=0.8, alpha=0.5)
        ax.set_yticks(y_pos_a)
        ax.set_yticklabels(y_labels_a, fontsize=9)
        ax.set_xlabel('ΔAuth P99 (ms) — Auth-Only, Baseline', fontsize=11)
        ax.set_title(f'95%-KI: Authentifizierungs-Overhead ({arch_display[arch]})',
                     fontweight='bold', fontsize=12)
        ax.tick_params(axis='x', labelsize=9)
        ax.grid(axis='x', alpha=0.3)
        ax.invert_yaxis()

        plt.tight_layout()
        path = f"{PLOT_DIR}/bootstrap_ci_forest_plot_{arch}.pdf"
        fig.savefig(path, bbox_inches='tight', dpi=300)
        print(f"Saved: {path}")
        plt.close()

    # ── 5. Between-experiment t-CI ──
    print("\n--- BETWEEN-EXPERIMENT t-CI (n=2-5) ---")
    between_results = []

    for (arch, hw, auth_label), grp in p99_df.groupby(['architecture', 'hw', 'auth_label']):
        deltas = grp['delta'].values
        n = len(deltas)
        if n < 2:
            print(f"  {arch}/{hw}/{auth_label}: n={n} — skipping (need ≥2)")
            continue

        mean, ci_lo, ci_hi, n_out, se = t_ci(deltas)

        sig = "SIG" if ci_lo > 0 or ci_hi < 0 else "n.s."
        print(f"  {arch}/{hw}/{auth_label}: n={n}, Δ={mean:+.1f}ms, "
              f"CI [{ci_lo:+.1f}, {ci_hi:+.1f}] {sig}")

        between_results.append({
            'architecture': arch, 'hw': hw, 'auth_label': auth_label,
            'n_experiments': n, 'delta_mean': mean,
            'between_ci_low': ci_lo, 'between_ci_high': ci_hi,
            'significant': sig == 'SIG',
        })

    if between_results:
        between_df = pd.DataFrame(between_results)
        between_df.to_csv(f"{PLOT_DIR}/bootstrap_ci_between_experiment.csv", index=False)
        print(f"Saved: {PLOT_DIR}/bootstrap_ci_between_experiment.csv")

    print("\n" + "=" * 70)
    print("DONE — Script 34")
    print("=" * 70)


if __name__ == '__main__':
    main()
