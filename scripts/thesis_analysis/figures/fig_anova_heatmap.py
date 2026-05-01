#!/usr/bin/env python3
"""Generate anova_overview_heatmap.pdf for fig:anova-heatmap.

Combined heatmap: rows = (arch, hw), columns = SCNAST phases.
Cell color = SSA/SST (%), annotation = significance.
Runs one-factor ANOVA per (arch, hw, phase) on auth-only P99.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, hw_label_from_row,
                           AUTH_COLORS_DETAILED, HW_TIERS_ALL)

ALPHA = 0.05
PRIMARY_AUTH_LABELS = ['None', 'Cognito', 'Manual (bcrypt)', 'Edge']

PROTECTED_ENDPOINTS_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_ENDPOINTS_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)

SCNAST_PHASES = [
    'Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
    'Flash Crowd', 'Step Down', 'Cool-down',
]


def query_auth_only_p99(phase):
    dfs = []
    for arch, endpoints in [('faas', PROTECTED_ENDPOINTS_FAAS),
                            (None, PROTECTED_ENDPOINTS_CONTAINER)]:
        eps = ','.join(f"'{e}'" for e in endpoints)
        arch_clause = f"AND e.architecture = '{arch}'" if arch == 'faas' else \
                      "AND e.architecture IN ('microservices', 'monolith')"
        df = query_df(f"""
            SELECT e.id AS experiment_id, e.architecture, e.auth_strategy,
                   COALESCE(e.password_hash_algorithm, 'default') AS algo,
                   COALESCE(e.with_cloudfront, false) AS with_cf,
                   e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu_in_vcpu,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                       FILTER (WHERE NOT r.is_error) AS p99
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL} {arch_clause}
              AND r.phase_name = '{phase}' AND r.endpoint IN ({eps})
            GROUP BY e.id, e.architecture, e.auth_strategy,
                     e.password_hash_algorithm, e.with_cloudfront,
                     e.ram_in_mb, e.cpu_in_vcpu
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)
        dfs.append(df)
    result = pd.concat(dfs, ignore_index=True)
    result['p99'] = result['p99'].astype(float)
    result['hw'] = result.apply(hw_label_from_row, axis=1)
    result['auth_label'] = result.apply(
        lambda r: auth_label_detailed(
            r['auth_strategy'],
            r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
            bool(r['with_cf']) if r['with_cf'] else False), axis=1)
    return result


def one_factor_anova(groups):
    labels = list(groups.keys())
    k = len(labels)
    if k < 2:
        return None
    all_values = []
    group_means, group_sizes = {}, {}
    for label in labels:
        vals = np.array(groups[label], dtype=float)
        if len(vals) < 1:
            return None
        group_means[label] = np.mean(vals)
        group_sizes[label] = len(vals)
        all_values.extend(vals)
    all_values = np.array(all_values)
    N = len(all_values)
    if N - k < 1:
        return None
    grand_mean = np.mean(all_values)
    SSA = sum(group_sizes[l] * (group_means[l] - grand_mean) ** 2 for l in labels)
    SSE = sum(np.sum((np.array(groups[l], dtype=float) - group_means[l]) ** 2) for l in labels)
    SST = SSA + SSE
    MSA = SSA / (k - 1)
    MSE = SSE / (N - k) if (N - k) > 0 else np.inf
    F_stat = MSA / MSE if MSE > 0 else np.inf
    F_critical = sp_stats.f.ppf(1 - ALPHA, k - 1, N - k)
    return {
        'k': k, 'N': N, 'F_stat': F_stat, 'F_critical': F_critical,
        'significant': F_stat > F_critical,
        'SSA_ratio': SSA / SST if SST > 0 else 0,
    }


def main():
    all_results = []
    for phase in SCNAST_PHASES:
        per_exp = query_auth_only_p99(phase)
        if per_exp.empty:
            continue
        for arch in ['faas', 'microservices', 'monolith']:
            for _, _, hw_label in HW_TIERS_ALL.get(arch, []):
                mask = (
                    (per_exp['architecture'] == arch) &
                    (per_exp['hw'] == hw_label) &
                    (per_exp['auth_label'].isin(PRIMARY_AUTH_LABELS)) &
                    (~per_exp['with_cf'])
                )
                subset = per_exp[mask]
                groups = {}
                for label in PRIMARY_AUTH_LABELS:
                    vals = subset[subset['auth_label'] == label]['p99'].values
                    if len(vals) >= 2:
                        groups[label] = vals
                if len(groups) < 2:
                    continue
                result = one_factor_anova(groups)
                if result is None:
                    continue
                result['phase'] = phase
                result['config'] = f"{arch.capitalize()}/{hw_label}"
                all_results.append(result)

    if not all_results:
        print('No ANOVA results')
        return

    df = pd.DataFrame(all_results)
    configs = []
    for arch in ['faas', 'microservices', 'monolith']:
        for _, _, hw_label in HW_TIERS_ALL.get(arch, []):
            cfg = f"{arch.capitalize()}/{hw_label}"
            if cfg in df['config'].values and cfg not in configs:
                configs.append(cfg)

    matrix = np.full((len(configs), len(SCNAST_PHASES)), np.nan)
    sig_matrix = np.full((len(configs), len(SCNAST_PHASES)), False)
    for i, config in enumerate(configs):
        for j, phase in enumerate(SCNAST_PHASES):
            row = df[(df['config'] == config) & (df['phase'] == phase)]
            if len(row) > 0:
                matrix[i, j] = row.iloc[0]['SSA_ratio'] * 100
                sig_matrix[i, j] = row.iloc[0]['significant']

    fig, ax = plt.subplots(figsize=(14, max(4, len(configs) * 0.55)))
    cmap = plt.cm.RdYlGn.copy()
    cmap.set_bad(color='#f0f0f0')
    masked = np.ma.masked_invalid(matrix)
    im = ax.imshow(masked, cmap=cmap, aspect='auto', vmin=0, vmax=100)

    for i in range(len(configs)):
        for j in range(len(SCNAST_PHASES)):
            if not np.isnan(matrix[i, j]):
                sig = '**' if sig_matrix[i, j] else ''
                val = matrix[i, j]
                ax.text(j, i, f"{val:.0f}%{sig}", ha='center', va='center',
                        fontsize=8, fontweight='bold' if sig_matrix[i, j] else 'normal',
                        color='white' if val > 70 or val < 30 else 'black')

    ax.set_xticks(range(len(SCNAST_PHASES)))
    ax.set_xticklabels([p.replace(' ', '\n') for p in SCNAST_PHASES], fontsize=9)
    ax.set_yticks(range(len(configs)))
    ax.set_yticklabels(configs, fontsize=9)
    ax.set_title('ANOVA SSA/SST (%) pro SCNAST-Phase\n(** = signifikant bei α = 0.05)',
                 fontsize=12, fontweight='bold')
    plt.colorbar(im, ax=ax, label='SSA/SST (%)', shrink=0.8)
    plt.tight_layout()
    path = f"{PLOT_DIR}/anova_overview_heatmap.pdf"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
