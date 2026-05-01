#!/usr/bin/env python3
"""Generate contrasts_forest_plot_baseline.pdf for fig:contrasts-forest.

Forest plot of method-of-contrasts results for Baseline phase.
Uses one-factor ANOVA + pairwise contrasts on auth-only P99.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from itertools import combinations
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


def query_auth_only_p99(phase='Baseline'):
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


def main():
    per_exp = query_auth_only_p99('Baseline')
    if per_exp.empty:
        print('No Baseline data')
        return

    all_contrasts = []
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

            labels = list(groups.keys())
            k = len(labels)
            all_values = np.concatenate(list(groups.values()))
            N = len(all_values)
            if N - k < 1:
                continue
            grand_mean = np.mean(all_values)
            SSA = sum(len(groups[l]) * (np.mean(groups[l]) - grand_mean) ** 2 for l in labels)
            SSE = sum(np.sum((np.array(groups[l]) - np.mean(groups[l])) ** 2) for l in labels)
            SST = SSA + SSE
            MSE = SSE / (N - k)
            F_stat = (SSA / (k - 1)) / MSE if MSE > 0 else np.inf
            F_critical = sp_stats.f.ppf(1 - ALPHA, k - 1, N - k)
            anova_sig = F_stat > F_critical

            for label_a, label_b in combinations(groups.keys(), 2):
                vals_a = np.array(groups[label_a], dtype=float)
                vals_b = np.array(groups[label_b], dtype=float)
                n_a, n_b = len(vals_a), len(vals_b)
                contrast = np.mean(vals_a) - np.mean(vals_b)
                s_c = np.sqrt(MSE * (1.0 / n_a + 1.0 / n_b))
                if s_c <= 0:
                    continue
                t_crit = sp_stats.t.ppf(1 - ALPHA / 2, N - k)
                ci_lo = contrast - t_crit * s_c
                ci_hi = contrast + t_crit * s_c
                significant = ci_lo > 0 or ci_hi < 0
                if significant:
                    all_contrasts.append({
                        'architecture': arch, 'hw': hw_label,
                        'label_a': label_a, 'label_b': label_b,
                        'contrast': contrast, 'ci_lo': ci_lo, 'ci_hi': ci_hi,
                        'p_value': 2 * (1 - sp_stats.t.cdf(abs(contrast / s_c), N - k)),
                        'significant': significant,
                    })

    if not all_contrasts:
        print('No significant contrasts in Baseline')
        return

    df = pd.DataFrame(all_contrasts)
    df = df.sort_values('contrast', ascending=True)

    fig, ax = plt.subplots(figsize=(12, max(6, len(df) * 0.3)))
    y_pos = np.arange(len(df))

    for i, (_, row) in enumerate(df.iterrows()):
        color = '#4CAF50' if row['significant'] else '#999999'
        ax.errorbar(row['contrast'], i,
                    xerr=[[row['contrast'] - row['ci_lo']], [row['ci_hi'] - row['contrast']]],
                    fmt='o', color='black', ecolor=color, elinewidth=2, capsize=4, markersize=5)

    ax.axvline(x=0, color='red', linestyle='--', linewidth=1, alpha=0.7)
    labels = [f"{r['architecture'].capitalize()}/{r['hw']}: "
              f"{r['label_a']} vs {r['label_b']}" for _, r in df.iterrows()]
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel('Kontrast (ΔP99 in ms)')
    ax.set_title('Methode der Kontraste: Paarweise Vergleiche (Baseline-Phase)',
                 fontsize=12, fontweight='bold')

    sig_patch = mpatches.Patch(color='#4CAF50', label='Signifikant (KI schließt 0 nicht ein)')
    ns_patch = mpatches.Patch(color='#999999', label='Nicht signifikant')
    ax.legend(handles=[sig_patch, ns_patch], loc='lower right', fontsize=9)
    ax.grid(axis='x', alpha=0.3)

    plt.tight_layout()
    path = f"{PLOT_DIR}/contrasts_forest_plot_baseline.pdf"
    fig.savefig(path, dpi=150, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
