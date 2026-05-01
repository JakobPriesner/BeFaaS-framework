#!/usr/bin/env python3
"""
41 — ANOVA & Method of Contrasts (nach Kounev, Kapitel 5)

Implements the statistical methodology from the Systems Benchmarking lecture:
1. Descriptive statistics: mean ± StdDev across experiment runs
2. One-factor ANOVA (F-test): Are there significant differences among auth strategies?
3. Method of Contrasts: Which specific pairs differ?
4. All using Student-t distribution (n < 30)

**Runs the analysis separately for each SCNAST phase**, following the lecture
recommendation: "Phases with different characteristics should be analyzed separately."

Reference: Kounev, S., Lange, K.-D., von Kistowski, J. (2025).
"Systems Benchmarking - For Scientists and Engineers", 2nd Ed.,
Springer, Chapter 5.

Outputs:
  - anova_results_all_phases.csv           (ANOVA F-test results per phase × group)
  - contrasts_results_all_phases.csv       (Method of Contrasts per phase)
  - descriptive_stats_all_phases.csv       (Descriptive stats per phase × group)
  - anova_summary.tex                      (LaTeX table fragments — all phases)
  - anova_overview_heatmap.pdf             (Significance heatmap: config × phase)
  - contrasts_forest_plot.pdf              (Forest plot of significant contrasts, all phases)
  - descriptive_stats_barplots_<phase>.pdf (Bar charts per phase)
"""

import sys
import os
import warnings
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from scipy import stats as sp_stats
from itertools import combinations

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, hw_label_from_row,
                           AUTH_COLORS_DETAILED, HW_TIERS_ALL)

# ── Constants ──
CONFIDENCE_LEVEL = 0.95
ALPHA = 1 - CONFIDENCE_LEVEL

# Auth-only endpoints (token verification required)
PROTECTED_ENDPOINTS_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_ENDPOINTS_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)

# Phases to analyze
SCNAST_PHASES = [
    'Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
    'Flash Crowd', 'Step Down', 'Cool-down'
]

# Short labels for plots/tables
PHASE_SHORT = {
    'Warm-up': 'WU', 'Baseline': 'BL', 'Morning rush': 'MR',
    'Stabilization': 'ST', 'Flash Crowd': 'FC',
    'Step Down': 'SD', 'Cool-down': 'CD'
}

# Primary auth strategies for ANOVA (exclude edge-selective, CF variants, argon2id)
PRIMARY_AUTH_STRATEGIES = ['none', 'service-integrated', 'service-integrated-manual', 'edge']
PRIMARY_AUTH_LABELS = ['None', 'Cognito', 'Manual (bcrypt)', 'Edge']


def get_protected_endpoints(arch):
    return PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER


# ══════════════════════════════════════════════════════════════════════
# STATISTICAL FUNCTIONS (Kounev Chapter 5)
# ══════════════════════════════════════════════════════════════════════

def descriptive_stats(values):
    """Compute descriptive statistics for a group of measurements."""
    n = len(values)
    if n == 0:
        return {'n': 0, 'mean': np.nan, 'std': np.nan, 'min': np.nan,
                'max': np.nan, 'ci_lo': np.nan, 'ci_hi': np.nan}
    mean = np.mean(values)
    if n == 1:
        return {'n': 1, 'mean': mean, 'std': 0.0, 'min': mean,
                'max': mean, 'ci_lo': np.nan, 'ci_hi': np.nan}
    std = np.std(values, ddof=1)
    se = std / np.sqrt(n)
    t_crit = sp_stats.t.ppf(1 - ALPHA / 2, df=n - 1)
    ci_lo = mean - t_crit * se
    ci_hi = mean + t_crit * se
    return {'n': n, 'mean': mean, 'std': std, 'min': np.min(values),
            'max': np.max(values), 'ci_lo': ci_lo, 'ci_hi': ci_hi}


def one_factor_anova(groups):
    """
    One-factor ANOVA (Kounev Chapter 5, Folien 19-28).

    SST = SSA + SSE
    F = MSA / MSE = [SSA/(k-1)] / [SSE/(N-k)]

    Parameters:
        groups: dict {label: np.array of measurements}
                Each group must have n >= 1; at least 2 groups with n >= 2 needed.

    Returns dict with:
        k, N, SSA, SSE, SST, MSA, MSE, F_stat, F_critical, p_value,
        significant, SSA_ratio (= SSA/SST, proportion explained by factor)
    """
    labels = list(groups.keys())
    k = len(labels)

    # Need at least 2 groups
    if k < 2:
        return None

    # Get group sizes and overall stats
    all_values = []
    group_means = {}
    group_sizes = {}

    for label in labels:
        vals = np.array(groups[label], dtype=float)
        if len(vals) < 1:
            return None
        group_means[label] = np.mean(vals)
        group_sizes[label] = len(vals)
        all_values.extend(vals)

    all_values = np.array(all_values)
    N = len(all_values)
    grand_mean = np.mean(all_values)

    # Need enough df for error term
    if N - k < 1:
        return None

    # SSA: variation between groups (Folie 22)
    SSA = sum(group_sizes[l] * (group_means[l] - grand_mean) ** 2 for l in labels)

    # SSE: variation within groups (Folie 22)
    SSE = 0
    for label in labels:
        vals = np.array(groups[label], dtype=float)
        SSE += np.sum((vals - group_means[label]) ** 2)

    SST = SSA + SSE

    # Mean squares
    df_between = k - 1
    df_within = N - k
    MSA = SSA / df_between
    MSE = SSE / df_within if df_within > 0 else np.inf

    # F-statistic (Folie 24)
    F_stat = MSA / MSE if MSE > 0 else np.inf

    # Critical value and p-value from F-distribution
    F_critical = sp_stats.f.ppf(1 - ALPHA, df_between, df_within)
    p_value = 1 - sp_stats.f.cdf(F_stat, df_between, df_within)

    significant = F_stat > F_critical

    return {
        'k': k, 'N': N,
        'df_between': df_between, 'df_within': df_within,
        'SSA': SSA, 'SSE': SSE, 'SST': SST,
        'MSA': MSA, 'MSE': MSE,
        'F_stat': F_stat, 'F_critical': F_critical,
        'p_value': p_value,
        'significant': significant,
        'SSA_ratio': SSA / SST if SST > 0 else 0,
    }


def method_of_contrasts(groups, label_a, label_b, MSE, df_within):
    """
    Method of Contrasts (Kounev Chapter 5, Folien 29-35).

    Contrast: c = w_a * x̄_a + w_b * x̄_b  (with w_a=1, w_b=-1 → c = x̄_a - x̄_b)
    Variance: s_c² = MSE * (w_a²/n_a + w_b²/n_b)
    CI = c ± t_{α/2; df_within} * s_c

    If CI excludes 0: the contrast is statistically significant.

    Returns dict with:
        contrast, se, ci_lo, ci_hi, t_stat, p_value, significant
    """
    vals_a = np.array(groups[label_a], dtype=float)
    vals_b = np.array(groups[label_b], dtype=float)
    n_a, n_b = len(vals_a), len(vals_b)

    if n_a < 1 or n_b < 1 or df_within < 1:
        return None

    mean_a = np.mean(vals_a)
    mean_b = np.mean(vals_b)

    # Weights: w_a = 1, w_b = -1 (compare A vs B)
    contrast = mean_a - mean_b

    # Standard error of contrast (Folie 32)
    s_c_sq = MSE * (1.0 / n_a + 1.0 / n_b)
    if s_c_sq <= 0:
        return None
    s_c = np.sqrt(s_c_sq)

    # t-critical from Student-t distribution (Folie 33)
    t_crit = sp_stats.t.ppf(1 - ALPHA / 2, df_within)
    ci_lo = contrast - t_crit * s_c
    ci_hi = contrast + t_crit * s_c

    # t-statistic and p-value
    t_stat = contrast / s_c
    p_value = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df_within))

    # Significant if CI does not include 0
    significant = ci_lo > 0 or ci_hi < 0

    return {
        'contrast': contrast,
        'se': s_c,
        'ci_lo': ci_lo, 'ci_hi': ci_hi,
        't_stat': t_stat, 'p_value': p_value,
        'significant': significant,
        'mean_a': mean_a, 'mean_b': mean_b,
        'n_a': n_a, 'n_b': n_b,
    }


def levene_test(groups):
    """Levene's test for equality of variances (ANOVA assumption check)."""
    group_arrays = [np.array(v, dtype=float) for v in groups.values() if len(v) >= 2]
    if len(group_arrays) < 2:
        return None
    stat, p_value = sp_stats.levene(*group_arrays)
    return {'W_stat': stat, 'p_value': p_value, 'equal_var': p_value > ALPHA}


# ══════════════════════════════════════════════════════════════════════
# DATA QUERY
# ══════════════════════════════════════════════════════════════════════

def query_auth_only_p99_per_experiment(phase='Baseline'):
    """
    Query auth-only P99 per experiment for a given phase.
    Dynamically includes all valid experiments.
    Returns DataFrame with one row per experiment.
    """
    # We need separate queries for FaaS (different endpoint paths) and containers
    dfs = []

    for arch, endpoints in [('faas', PROTECTED_ENDPOINTS_FAAS),
                            (None, PROTECTED_ENDPOINTS_CONTAINER)]:
        eps = ','.join(f"'{e}'" for e in endpoints)
        arch_clause = f"AND e.architecture = '{arch}'" if arch == 'faas' else \
                      "AND e.architecture IN ('microservices', 'monolith')"

        df = query_df(f"""
            SELECT
                e.id AS experiment_id,
                e.architecture,
                e.auth_strategy,
                COALESCE(e.password_hash_algorithm, 'default') AS algo,
                COALESCE(e.with_cloudfront, false) AS with_cf,
                e.ram_in_mb,
                COALESCE(e.cpu_in_vcpu, 0) AS cpu_in_vcpu,
                COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p50,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p99,
                AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_lat
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL}
                {arch_clause}
                AND r.phase_name = '{phase}'
                AND r.endpoint IN ({eps})
            GROUP BY e.id, e.architecture, e.auth_strategy,
                     e.password_hash_algorithm, e.with_cloudfront,
                     e.ram_in_mb, e.cpu_in_vcpu
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)
        dfs.append(df)

    result = pd.concat(dfs, ignore_index=True)

    for col in ['p50', 'p99', 'mean_lat']:
        result[col] = result[col].astype(float)

    result['hw'] = result.apply(hw_label_from_row, axis=1)
    result['auth_label'] = result.apply(
        lambda r: auth_label_detailed(
            r['auth_strategy'],
            r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
            bool(r['with_cf']) if r['with_cf'] else False
        ), axis=1)

    return result


def group_for_anova(per_exp_df, arch, hw, metric='p99'):
    """
    Group experiment data for ANOVA: {auth_label: [values across runs]}.
    Only includes primary auth strategies (no CF variants, no argon2id, no edge-selective).
    """
    mask = (
        (per_exp_df['architecture'] == arch) &
        (per_exp_df['hw'] == hw) &
        (per_exp_df['auth_label'].isin(PRIMARY_AUTH_LABELS)) &
        (~per_exp_df['with_cf'])
    )
    subset = per_exp_df[mask]

    groups = {}
    for label in PRIMARY_AUTH_LABELS:
        vals = subset[subset['auth_label'] == label][metric].values
        if len(vals) > 0:
            groups[label] = vals

    return groups


# ══════════════════════════════════════════════════════════════════════
# VISUALIZATION
# ══════════════════════════════════════════════════════════════════════

def plot_descriptive_barplots(per_exp_df, phase='Baseline'):
    """Bar charts showing mean ± StdDev per auth strategy — one PDF per architecture."""
    archs = ['faas', 'microservices', 'monolith']
    arch_titles = {
        'faas': 'FaaS (Lambda)',
        'microservices': 'Microservices (Fargate)',
        'monolith': 'Monolith (Fargate)',
    }
    phase_slug = phase.lower().replace(' ', '_')

    for arch in archs:
        title = arch_titles[arch]
        hw_tiers = HW_TIERS_ALL.get(arch, [])
        hw_labels = [t[2] for t in hw_tiers]

        plot_data = []
        for hw_label in hw_labels:
            groups = group_for_anova(per_exp_df, arch, hw_label)
            for auth_label in PRIMARY_AUTH_LABELS:
                if auth_label in groups:
                    stats = descriptive_stats(groups[auth_label])
                    plot_data.append({
                        'hw': hw_label, 'auth': auth_label,
                        'mean': stats['mean'], 'std': stats['std'],
                        'n': stats['n']
                    })

        if not plot_data:
            continue

        pdf = pd.DataFrame(plot_data)
        hws_present = [h for h in hw_labels if h in pdf['hw'].values]
        n_hw = len(hws_present)
        n_auth = len(PRIMARY_AUTH_LABELS)

        if n_hw == 0:
            continue

        fig, ax = plt.subplots(figsize=(10, 7))
        bar_width = 0.8 / n_auth
        x = np.arange(n_hw)

        for i, auth_label in enumerate(PRIMARY_AUTH_LABELS):
            auth_data = pdf[pdf['auth'] == auth_label]
            means, stds, ns = [], [], []
            for hw in hws_present:
                hw_row = auth_data[auth_data['hw'] == hw]
                if len(hw_row) > 0:
                    means.append(hw_row['mean'].iloc[0])
                    stds.append(hw_row['std'].iloc[0] if hw_row['std'].iloc[0] > 0 else 0)
                    ns.append(int(hw_row['n'].iloc[0]))
                else:
                    means.append(0)
                    stds.append(0)
                    ns.append(0)

            color = AUTH_COLORS_DETAILED.get(auth_label, '#999999')
            bars = ax.bar(x + i * bar_width, means, bar_width,
                         yerr=stds, capsize=4,
                         label=auth_label, color=color, edgecolor='white',
                         error_kw={'linewidth': 1.2})

            for j, (bar, n) in enumerate(zip(bars, ns)):
                if n > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2,
                           bar.get_height() + stds[j] + 5,
                           f'n={n}', ha='center', va='bottom', fontsize=8, color='#555')

        ax.set_xticks(x + bar_width * (n_auth - 1) / 2)
        ax.set_xticklabels(hws_present, fontsize=11)
        ax.set_title(f'{title}: Auth-only P99 ({phase})', fontsize=13, fontweight='bold')
        ax.set_xlabel('Hardware-Tier', fontsize=12)
        ax.set_ylabel('Auth-only P99 (ms)', fontsize=12)
        ax.legend(fontsize=9, loc='upper right')
        ax.grid(axis='y', alpha=0.3)
        ax.tick_params(labelsize=10)

        plt.tight_layout()
        path = f"{PLOT_DIR}/descriptive_stats_barplots_{phase_slug}_{arch}.pdf"
        fig.savefig(path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"  Saved: {path}")


def plot_anova_phase_heatmap(all_anova_results):
    """
    Combined heatmap: rows = (arch, hw), columns = phases.
    Cell color = SSA/SST, annotation = significance.
    """
    if not all_anova_results:
        print("  No ANOVA results to plot.")
        return

    df = pd.DataFrame(all_anova_results)

    # Build config list (ordered)
    configs = []
    for arch in ['faas', 'microservices', 'monolith']:
        hw_tiers = HW_TIERS_ALL.get(arch, [])
        for _, _, hw_label in hw_tiers:
            cfg = f"{arch.capitalize()}/{hw_label}"
            if cfg in df['config'].values:
                configs.append(cfg)

    # Deduplicate while preserving order
    seen = set()
    config_list = []
    for c in configs:
        if c not in seen:
            seen.add(c)
            config_list.append(c)

    phases = SCNAST_PHASES

    # Create matrices
    matrix = np.full((len(config_list), len(phases)), np.nan)
    sig_matrix = np.full((len(config_list), len(phases)), False)

    for i, config in enumerate(config_list):
        for j, phase in enumerate(phases):
            row = df[(df['config'] == config) & (df['phase'] == phase)]
            if len(row) > 0:
                matrix[i, j] = row.iloc[0]['SSA_ratio'] * 100
                sig_matrix[i, j] = row.iloc[0]['significant']

    fig, ax = plt.subplots(figsize=(14, max(4, len(config_list) * 0.55)))

    cmap = plt.cm.RdYlGn.copy()
    cmap.set_bad(color='#f0f0f0')

    masked = np.ma.masked_invalid(matrix)
    im = ax.imshow(masked, cmap=cmap, aspect='auto', vmin=0, vmax=100)

    # Annotate cells
    for i in range(len(config_list)):
        for j in range(len(phases)):
            if not np.isnan(matrix[i, j]):
                sig = '**' if sig_matrix[i, j] else ''
                val = matrix[i, j]
                ax.text(j, i, f"{val:.0f}%{sig}",
                       ha='center', va='center', fontsize=8,
                       fontweight='bold' if sig_matrix[i, j] else 'normal',
                       color='white' if val > 70 or val < 30 else 'black')

    ax.set_xticks(range(len(phases)))
    ax.set_xticklabels([p.replace(' ', '\n') for p in phases], fontsize=9)
    ax.set_yticks(range(len(config_list)))
    ax.set_yticklabels(config_list, fontsize=9)
    ax.set_title('ANOVA SSA/SST (%) pro SCNAST-Phase\n(** = signifikant bei α = 0.05)',
                fontsize=12, fontweight='bold')

    plt.colorbar(im, ax=ax, label='SSA/SST (%)', shrink=0.8)
    plt.tight_layout()

    path = f"{PLOT_DIR}/anova_overview_heatmap.pdf"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path}")


def plot_anova_pairwise_heatmap_appendix(all_contrasts):
    """
    Appendix heatmap: rows = (Arch/HW × contrast-vs-None), cols = SCNAST phases.
    Cell color = ΔP99 (ms), annotation = Δ-value; '**' marks contrasts whose
    95%-CI excludes 0 (method-of-contrasts significance).

    Uses 'None' as the fixed reference; shows three contrasts per (arch, hw):
    Cognito−None, Manual (bcrypt)−None, Edge−None.
    """
    if not all_contrasts:
        print("  No contrast results to plot (appendix heatmap).")
        return

    df = pd.DataFrame(all_contrasts)
    ref = 'None'
    # Keep only contrasts that compare against the reference (as label_a or label_b)
    df = df[(df['label_a'] == ref) | (df['label_b'] == ref)].copy()
    if len(df) == 0:
        print("  No contrasts against reference; skipping appendix heatmap.")
        return

    # Normalize direction: always report (other − None), so positive = overhead
    def _normalize(row):
        if row['label_b'] == ref:
            return pd.Series({
                'other': row['label_a'],
                'delta': row['contrast'],
                'ci_lo': row['ci_lo'], 'ci_hi': row['ci_hi'],
                'sig': row['significant'],
            })
        return pd.Series({
            'other': row['label_b'],
            'delta': -row['contrast'],
            'ci_lo': -row['ci_hi'], 'ci_hi': -row['ci_lo'],
            'sig': row['significant'],
        })

    df[['other', 'delta', 'ci_lo', 'ci_hi', 'sig']] = df.apply(_normalize, axis=1)

    # Row ordering: Arch × HW (outer) × contrast strategy (inner)
    contrast_order = ['Cognito', 'Manual (bcrypt)', 'Edge']
    row_keys = []
    row_labels = []
    for arch in ['faas', 'microservices', 'monolith']:
        hw_tiers = HW_TIERS_ALL.get(arch, [])
        for _, _, hw_label in hw_tiers:
            present = df[(df['architecture'] == arch) & (df['hw'] == hw_label)]
            if len(present) == 0:
                continue
            for other in contrast_order:
                if other in present['other'].values:
                    row_keys.append((arch, hw_label, other))
                    row_labels.append(f"{arch.capitalize()}/{hw_label}: {other} − {ref}")

    if not row_keys:
        print("  No rows for appendix heatmap.")
        return

    phases = SCNAST_PHASES
    delta_matrix = np.full((len(row_keys), len(phases)), np.nan)
    sig_matrix = np.full((len(row_keys), len(phases)), False)

    for i, (arch, hw_label, other) in enumerate(row_keys):
        for j, phase in enumerate(phases):
            r = df[(df['architecture'] == arch) & (df['hw'] == hw_label) &
                   (df['other'] == other) & (df['phase'] == phase)]
            if len(r) > 0:
                delta_matrix[i, j] = r.iloc[0]['delta']
                sig_matrix[i, j] = bool(r.iloc[0]['sig'])

    fig, ax = plt.subplots(figsize=(14, max(6, len(row_keys) * 0.32)))

    # Diverging colormap centered at 0; symmetric limits from robust percentile
    finite = delta_matrix[np.isfinite(delta_matrix)]
    if len(finite) == 0:
        print("  No finite deltas; skipping appendix heatmap.")
        plt.close(fig)
        return
    vmax = np.nanpercentile(np.abs(finite), 95)
    if not np.isfinite(vmax) or vmax <= 0:
        vmax = float(np.nanmax(np.abs(finite))) or 1.0

    cmap = plt.cm.RdBu_r.copy()
    cmap.set_bad(color='#f0f0f0')
    masked = np.ma.masked_invalid(delta_matrix)
    im = ax.imshow(masked, cmap=cmap, aspect='auto', vmin=-vmax, vmax=vmax)

    for i in range(len(row_keys)):
        for j in range(len(phases)):
            val = delta_matrix[i, j]
            if np.isnan(val):
                continue
            sig = '**' if sig_matrix[i, j] else ''
            text = f"{val:+.0f}{sig}"
            # Contrast against background
            intensity = abs(val) / vmax if vmax > 0 else 0
            color = 'white' if intensity > 0.6 else 'black'
            ax.text(j, i, text, ha='center', va='center', fontsize=7.5,
                    fontweight='bold' if sig_matrix[i, j] else 'normal',
                    color=color)

    ax.set_xticks(range(len(phases)))
    ax.set_xticklabels([p.replace(' ', '\n') for p in phases], fontsize=9)
    ax.set_yticks(range(len(row_keys)))
    ax.set_yticklabels(row_labels, fontsize=8)

    # Separator lines between Arch/HW blocks for readability
    prev_block = None
    for i, (arch, hw_label, _) in enumerate(row_keys):
        block = (arch, hw_label)
        if prev_block is not None and block != prev_block:
            ax.axhline(i - 0.5, color='black', linewidth=0.6, alpha=0.4)
        prev_block = block

    ax.set_title('Paarweise ΔP99 gegenüber "Keine Auth" pro SCNAST-Phase\n'
                 '(** = 95 %-KI schließt 0 nicht ein)',
                 fontsize=12, fontweight='bold')
    plt.colorbar(im, ax=ax, label='ΔP99 (ms, Strategie − Keine)', shrink=0.8)
    plt.tight_layout()

    path = f"{PLOT_DIR}/anova_pairwise_heatmap_appendix.pdf"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path}")


def plot_contrasts_forest(all_contrasts, phase_filter=None):
    """Forest plot of contrast results, optionally filtered to one phase."""
    if not all_contrasts:
        print("  No contrast results to plot.")
        return

    df = pd.DataFrame(all_contrasts)
    if phase_filter:
        df = df[df['phase'] == phase_filter]
        suffix = f"_{phase_filter.lower().replace(' ', '_')}"
        title_phase = f"({phase_filter}-Phase)"
    else:
        suffix = ""
        title_phase = "(alle Phasen)"

    if len(df) == 0:
        print(f"  No contrasts for {phase_filter or 'any phase'}.")
        return

    # Sort by phase then effect size
    phase_order = {p: i for i, p in enumerate(SCNAST_PHASES)}
    df['phase_idx'] = df['phase'].map(phase_order)
    df = df.sort_values(['phase_idx', 'contrast'], ascending=[True, True])

    fig, ax = plt.subplots(figsize=(12, max(6, len(df) * 0.3)))

    y_pos = np.arange(len(df))

    for i, (_, row) in enumerate(df.iterrows()):
        color = '#4CAF50' if row['significant'] else '#999999'
        ax.errorbar(row['contrast'], i,
                   xerr=[[row['contrast'] - row['ci_lo']], [row['ci_hi'] - row['contrast']]],
                   fmt='o', color='black', ecolor=color, elinewidth=2, capsize=4,
                   markersize=5)

    ax.axvline(x=0, color='red', linestyle='--', linewidth=1, alpha=0.7)

    labels = [f"[{PHASE_SHORT.get(r['phase'], r['phase'])}] "
              f"{r['architecture'].capitalize()}/{r['hw']}: "
              f"{r['label_a']} vs {r['label_b']}"
              for _, r in df.iterrows()]
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel('Kontrast (ΔP99 in ms)')
    ax.set_title(f'Methode der Kontraste: Paarweise Vergleiche {title_phase}',
                fontsize=12, fontweight='bold')

    sig_patch = mpatches.Patch(color='#4CAF50', label='Signifikant (KI schließt 0 nicht ein)')
    ns_patch = mpatches.Patch(color='#999999', label='Nicht signifikant')
    ax.legend(handles=[sig_patch, ns_patch], loc='lower right', fontsize=9)

    ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    path = f"{PLOT_DIR}/contrasts_forest_plot{suffix}.pdf"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path}")


# ══════════════════════════════════════════════════════════════════════
# LATEX OUTPUT
# ══════════════════════════════════════════════════════════════════════

def generate_latex_tables(all_anova_results, all_contrasts_results):
    """Generate LaTeX table fragments for all phases.

    Writes three files:
      - anova_detail.tex            — full per-phase ANOVA table (appendix)
      - anova_contrasts_detail.tex  — full significant-contrasts table (appendix)
      - anova_summary.tex           — phase-stability table only (chapter)
    """
    detail_lines = []

    # ── ANOVA detail table (all phases, grouped by phase) ──
    detail_lines.append("% ── ANOVA Results (All Phases, Auth-only P99) ──")
    detail_lines.append("% Generated by 41_anova_contrasts.py")
    detail_lines.append("")
    detail_lines.append(r"\begin{longtable}{@{}lllrrrrrl@{}}")
    lines = detail_lines
    lines.append(r"\caption{Einfaktorielle ANOVA (Faktor: Authentifizierungsstrategie) pro "
                 r"Architektur, Hardware-Tier und \ac{SCNAST}-Phase (P99 der authentifizierten Endpunkte). "
                 r"$k$ = Anzahl der Strategien, $N$ = Gesamtanzahl der Experimente. "
                 r"SSA/SST gibt den Anteil der durch die Strategiewahl erkl\"arten Variation an. "
                 r"Phasen-K\"urzel: WU = Warm-up, BL = Baseline, MR = Morning Rush, "
                 r"ST = Stabilization, FC = Flash Crowd, SD = Step Down, CD = Cool-down.}")
    lines.append(r"\label{tab:anova-all-phases} \\")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Phase} & \textbf{Architektur} & \textbf{Hardware} & $k$ & $N$ & "
                 r"\textbf{F} & \textbf{F\textsubscript{krit}} & "
                 r"\textbf{SSA/SST} & \textbf{Sig.} \\")
    lines.append(r"\midrule")
    lines.append(r"\endfirsthead")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Phase} & \textbf{Architektur} & \textbf{Hardware} & $k$ & $N$ & "
                 r"\textbf{F} & \textbf{F\textsubscript{krit}} & "
                 r"\textbf{SSA/SST} & \textbf{Sig.} \\")
    lines.append(r"\midrule")
    lines.append(r"\endhead")
    lines.append(r"\midrule \multicolumn{9}{r}{\textit{Fortsetzung auf n\"achster Seite}} \\")
    lines.append(r"\endfoot")
    lines.append(r"\bottomrule")
    lines.append(r"\endlastfoot")

    prev_phase = None
    for r in all_anova_results:
        if r['phase'] != prev_phase and prev_phase is not None:
            lines.append(r"\midrule")
        prev_phase = r['phase']

        sig = r'\checkmark' if r['significant'] else '---'
        phase_short = PHASE_SHORT.get(r['phase'], r['phase'])
        lines.append(
            f"  {phase_short:5s} & {r['architecture'].capitalize():15s} & {r['hw']:6s} & "
            f"{r['k']} & {r['N']} & "
            f"{r['F_stat']:.1f} & {r['F_critical']:.2f} & "
            f"{r['SSA_ratio']*100:.1f}\\,\\% & {sig} \\\\"
        )

    lines.append(r"\end{longtable}")
    lines.append("")

    # ── Switch to summary file (chapter: phase-stability only) ──
    summary_lines = []
    summary_lines.append("% ── ANOVA Summary (Phase Stability only) ──")
    summary_lines.append("% Generated by 41_anova_contrasts.py")
    summary_lines.append("% Hinweis: Die vollständige ANOVA-Detailtabelle (tab:anova-all-phases) und")
    summary_lines.append("% die Kontraste-Detailtabelle (tab:contrasts-all-phases) werden im Anhang")
    summary_lines.append("% eingebunden (plots/anova_detail.tex, plots/anova_contrasts_detail.tex).")
    summary_lines.append("")
    lines = summary_lines

    # ── Phase stability summary table ──
    lines.append("% ── Phase Stability Summary ──")
    lines.append(r"\begin{table}[htbp]")
    lines.append(r"\centering")
    lines.append(r"\caption{Phasenstabilit\"at der ANOVA-Signifikanz. Anzahl der Phasen mit "
                 r"signifikantem Strategieeffekt pro Konfiguration ($\alpha = 0{,}05$).}")
    lines.append(r"\label{tab:anova-phase-stability}")
    lines.append(r"\begin{tabular}{@{}llccc@{}}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Architektur} & \textbf{Hardware} & "
                 r"\textbf{Sig./Getestet} & \textbf{SSA/SST (BL)} & \textbf{Bewertung} \\")
    lines.append(r"\midrule")

    # Group results by config
    anova_df = pd.DataFrame(all_anova_results)
    if len(anova_df) > 0:
        stability = anova_df.groupby(['architecture', 'hw']).agg(
            n_phases=('significant', 'count'),
            n_sig=('significant', 'sum'),
        ).reset_index()

        for _, row in stability.iterrows():
            ratio = f"{int(row['n_sig'])}/{int(row['n_phases'])}"
            # Get Baseline SSA/SST
            bl = anova_df[(anova_df['architecture'] == row['architecture']) &
                          (anova_df['hw'] == row['hw']) &
                          (anova_df['phase'] == 'Baseline')]
            bl_ssa = f"{bl.iloc[0]['SSA_ratio']*100:.0f}\\,\\%" if len(bl) > 0 else '---'

            if row['n_sig'] == row['n_phases']:
                label = 'stabil-sig.'
            elif row['n_sig'] == 0:
                label = 'stabil-n.s.'
            elif row['n_sig'] >= row['n_phases'] * 0.5:
                label = 'phasenabh.'
            else:
                label = 'lastabh.'

            lines.append(
                f"  {row['architecture'].capitalize():15s} & {row['hw']:6s} & "
                f"{ratio} & {bl_ssa} & {label} \\\\"
            )

    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")
    lines.append("")

    # ── Switch to contrasts detail file (appendix) ──
    contrasts_lines = []

    # ── Contrasts table (significant post-hoc after significant omnibus) ──
    sig_contrasts = [c for c in all_contrasts_results
                     if c['significant'] and c.get('anova_sig', True)]
    if sig_contrasts:
        lines = contrasts_lines
        lines.append("% ── Significant Contrasts (All Phases) ──")
        lines.append(r"\begin{longtable}{@{}lllrrrr@{}}")
        lines.append(r"\caption{Methode der Kontraste: Signifikante paarweise Vergleiche "
                     r"(P99 der authentifizierten Endpunkte, alle \ac{SCNAST}-Phasen). "
                     r"KI = 95\,\%-Konfidenzintervall basierend auf der Student-$t$-Verteilung. "
                     r"Phasen-K\"urzel vgl.\ Tabelle~\ref{tab:anova-all-phases}.}")
        lines.append(r"\label{tab:contrasts-all-phases} \\")
        lines.append(r"\toprule")
        lines.append(r"\textbf{Phase} & \textbf{Konfiguration} & \textbf{Vergleich} & "
                     r"\textbf{$\Delta$ (ms)} & \textbf{KI\textsubscript{u}} & "
                     r"\textbf{KI\textsubscript{o}} & $p$ \\")
        lines.append(r"\midrule")
        lines.append(r"\endfirsthead")
        lines.append(r"\toprule")
        lines.append(r"\textbf{Phase} & \textbf{Konfiguration} & \textbf{Vergleich} & "
                     r"\textbf{$\Delta$ (ms)} & \textbf{KI\textsubscript{u}} & "
                     r"\textbf{KI\textsubscript{o}} & $p$ \\")
        lines.append(r"\midrule")
        lines.append(r"\endhead")
        lines.append(r"\midrule \multicolumn{7}{r}{\textit{Fortsetzung auf n\"achster Seite}} \\")
        lines.append(r"\endfoot")
        lines.append(r"\bottomrule")
        lines.append(r"\endlastfoot")

        prev_phase = None
        for c in sig_contrasts:
            if c['phase'] != prev_phase and prev_phase is not None:
                lines.append(r"\midrule")
            prev_phase = c['phase']

            phase_short = PHASE_SHORT.get(c['phase'], c['phase'])
            lines.append(
                f"  {phase_short:5s} & {c['architecture'].capitalize()}/{c['hw']} & "
                f"{c['label_a']} vs. {c['label_b']} & "
                f"{c['contrast']:+.0f} & {c['ci_lo']:.0f} & {c['ci_hi']:.0f} & "
                f"{c['p_value']:.3f} \\\\"
            )

        lines.append(r"\end{longtable}")

    detail_path = f"{PLOT_DIR}/anova_detail.tex"
    with open(detail_path, 'w') as f:
        f.write('\n'.join(detail_lines))
    print(f"  Saved: {detail_path}")

    contrasts_path = f"{PLOT_DIR}/anova_contrasts_detail.tex"
    with open(contrasts_path, 'w') as f:
        f.write('\n'.join(contrasts_lines))
    print(f"  Saved: {contrasts_path}")

    summary_path = f"{PLOT_DIR}/anova_summary.tex"
    with open(summary_path, 'w') as f:
        f.write('\n'.join(summary_lines))
    print(f"  Saved: {summary_path}")


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("41 — ANOVA & METHOD OF CONTRASTS (ALL PHASES)")
    print("     (nach Kounev, Systems Benchmarking, Kapitel 5)")
    print("     Separate Analyse pro SCNAST-Phase")
    print("=" * 70)

    all_anova_results = []
    all_contrasts_results = []
    all_desc_rows = []

    # ── Per-phase analysis ──
    for phase in SCNAST_PHASES:
        print(f"\n{'━'*60}")
        print(f"  Phase: {phase}")
        print(f"{'━'*60}")

        # Query data
        per_exp = query_auth_only_p99_per_experiment(phase=phase)
        print(f"  {len(per_exp)} experiment rows retrieved")

        if len(per_exp) == 0:
            print("  SKIP: no data")
            continue

        # ── Descriptive statistics ──
        for arch in ['faas', 'microservices', 'monolith']:
            hw_tiers = HW_TIERS_ALL.get(arch, [])
            for _, _, hw_label in hw_tiers:
                groups = group_for_anova(per_exp, arch, hw_label)
                for auth_label, vals in groups.items():
                    stats = descriptive_stats(vals)
                    all_desc_rows.append({
                        'phase': phase, 'architecture': arch, 'hw': hw_label,
                        'auth_label': auth_label,
                        **stats
                    })

        # ── Barplots for this phase ──
        plot_descriptive_barplots(per_exp, phase=phase)

        # ── ANOVA per (arch, hw) ──
        phase_anova_count = 0
        for arch in ['faas', 'microservices', 'monolith']:
            hw_tiers = HW_TIERS_ALL.get(arch, [])
            for _, _, hw_label in hw_tiers:
                groups = group_for_anova(per_exp, arch, hw_label)
                testable_groups = {k: v for k, v in groups.items() if len(v) >= 2}

                if len(testable_groups) < 2:
                    continue

                # Levene's test
                levene = levene_test(testable_groups)
                levene_ok = levene['equal_var'] if levene else None

                # ANOVA
                result = one_factor_anova(testable_groups)
                if result is None:
                    continue

                result['phase'] = phase
                result['architecture'] = arch
                result['hw'] = hw_label
                result['config'] = f"{arch.capitalize()}/{hw_label}"
                result['levene_ok'] = levene_ok

                sig_str = "SIG" if result['significant'] else "n.s."
                print(f"  {arch:15s} {hw_label:6s}: F({result['df_between']},{result['df_within']}) = "
                      f"{result['F_stat']:.1f}, SSA/SST={result['SSA_ratio']*100:.0f}% → {sig_str}")

                all_anova_results.append(result)
                phase_anova_count += 1

                # ── Contrasts (always compute for detail heatmap; LaTeX filters by sig) ──
                for label_a, label_b in combinations(testable_groups.keys(), 2):
                    c = method_of_contrasts(testable_groups, label_a, label_b,
                                            result['MSE'], result['df_within'])
                    if c is None:
                        continue
                    c['phase'] = phase
                    c['architecture'] = arch
                    c['hw'] = hw_label
                    c['label_a'] = label_a
                    c['label_b'] = label_b
                    c['anova_sig'] = result['significant']
                    all_contrasts_results.append(c)

        print(f"  → {phase_anova_count} ANOVA tests in this phase")

    # ── Save CSVs ──
    print(f"\n{'='*60}")
    print("SAVING RESULTS")
    print(f"{'='*60}")

    anova_df = pd.DataFrame(all_anova_results)
    anova_df.to_csv(f"{PLOT_DIR}/anova_results_all_phases.csv", index=False)
    print(f"  Saved: {PLOT_DIR}/anova_results_all_phases.csv")

    contrasts_df = pd.DataFrame(all_contrasts_results)
    contrasts_df.to_csv(f"{PLOT_DIR}/contrasts_results_all_phases.csv", index=False)
    print(f"  Saved: {PLOT_DIR}/contrasts_results_all_phases.csv")

    desc_df = pd.DataFrame(all_desc_rows)
    desc_df.to_csv(f"{PLOT_DIR}/descriptive_stats_all_phases.csv", index=False)
    print(f"  Saved: {PLOT_DIR}/descriptive_stats_all_phases.csv")

    # ── Combined heatmap (config × phase) ──
    print("\n--- Plotting combined ANOVA heatmap ---")
    plot_anova_phase_heatmap(all_anova_results)

    # ── Appendix detail heatmap (pairwise vs. None, per phase) ──
    print("\n--- Plotting pairwise contrast heatmap (appendix) ---")
    plot_anova_pairwise_heatmap_appendix(all_contrasts_results)

    # ── Forest plots ──
    print("\n--- Plotting contrasts forest plots ---")
    # One combined forest plot (all phases, only significant)
    plot_contrasts_forest([c for c in all_contrasts_results if c['significant']])
    # Per-phase forest plots for Baseline and Flash Crowd
    for phase in ['Baseline', 'Flash Crowd']:
        plot_contrasts_forest(all_contrasts_results, phase_filter=phase)

    # ── LaTeX tables ──
    print("\n--- Generating LaTeX tables ---")
    generate_latex_tables(all_anova_results, all_contrasts_results)

    # ── Phase stability summary ──
    print(f"\n{'='*60}")
    print("PHASE STABILITY SUMMARY")
    print(f"{'='*60}")

    if len(anova_df) > 0:
        stability = anova_df.groupby(['architecture', 'hw']).agg(
            n_phases=('significant', 'count'),
            n_sig=('significant', 'sum'),
        ).reset_index()

        for _, row in stability.iterrows():
            status = 'stabil-sig' if row['n_sig'] == row['n_phases'] \
                else 'stabil-n.s.' if row['n_sig'] == 0 \
                else 'phasenabhängig'
            print(f"  {row['architecture']:15s} {row['hw']:6s}: "
                  f"{int(row['n_sig'])}/{int(row['n_phases'])} phases sig → {status}")

    # ── Final summary ──
    n_sig_anova = sum(1 for r in all_anova_results if r['significant'])
    n_sig_contrasts = sum(1 for c in all_contrasts_results if c['significant'])
    print(f"\n{'='*60}")
    print(f"FINAL SUMMARY")
    print(f"  Phases analyzed:    {len(SCNAST_PHASES)}")
    print(f"  ANOVA tests:        {len(all_anova_results)} ({n_sig_anova} significant)")
    print(f"  Contrast tests:     {len(all_contrasts_results)} ({n_sig_contrasts} significant)")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
