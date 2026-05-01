#!/usr/bin/env python3
"""Generate bootstrap_ci_forest_plot.pdf for fig:bootstrap-forest.

Combined forest plot showing 95% CIs for ΔAuth P99 across all
(architecture, hw, auth_label) combinations. Uses ZGS + t-distribution
on 60-second block aggregates with Welch-Satterthwaite df and
inverse-variance pooling across experiment pairs.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, AUTH_COLORS_DETAILED)

PROTECTED_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)
BLOCK_SIZE_MS = 60000
CONFIDENCE_LEVEL = 0.95
ALPHA = 1 - CONFIDENCE_LEVEL
MIN_REQUESTS_PER_BLOCK = 10


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    return {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(float(cpu), f"{cpu}vCPU")


def get_protected_sql(arch):
    eps = PROTECTED_FAAS if arch == 'faas' else PROTECTED_CONTAINER
    return ','.join(f"'{e}'" for e in eps)


def load_request_latencies(experiment_id, arch):
    eps = get_protected_sql(arch)
    return query_df(f"""
        SELECT r.latency_ms, r.relative_time_ms
        FROM requests r
        WHERE r.experiment_id = {experiment_id}
          AND r.phase_name = 'Baseline' AND NOT r.is_error
          AND r.endpoint IN ({eps})
        ORDER BY r.relative_time_ms
    """)


def compute_block_percentiles(data, percentile):
    latencies = data['latency_ms'].values
    times = data['relative_time_ms'].values
    block_ids = (times // BLOCK_SIZE_MS).astype(int)
    unique_blocks = np.unique(block_ids)
    block_pctls = []
    for b in unique_blocks:
        block_lats = latencies[block_ids == b]
        if len(block_lats) >= MIN_REQUESTS_PER_BLOCK:
            block_pctls.append(np.percentile(block_lats, percentile * 100))
    return np.array(block_pctls)


def compute_within_experiment_ci(auth_exp_id, none_exp_id, arch, percentile=0.99):
    auth_data = load_request_latencies(auth_exp_id, arch)
    none_data = load_request_latencies(none_exp_id, arch)
    if len(auth_data) < 50 or len(none_data) < 50:
        return None

    auth_pctl = np.percentile(auth_data['latency_ms'].values, percentile * 100)
    none_pctl = np.percentile(none_data['latency_ms'].values, percentile * 100)

    auth_block = compute_block_percentiles(auth_data, percentile)
    none_block = compute_block_percentiles(none_data, percentile)

    if len(auth_block) < 2 or len(none_block) < 2:
        return None

    delta_mean = np.mean(auth_block) - np.mean(none_block)
    s1_sq = np.var(auth_block, ddof=1)
    s2_sq = np.var(none_block, ddof=1)
    se_diff = np.sqrt(s1_sq / len(auth_block) + s2_sq / len(none_block))

    if se_diff == 0:
        return {'delta': auth_pctl - none_pctl, 'ci_low': delta_mean,
                'ci_high': delta_mean, 'block_mean': delta_mean, 'block_se': 0.0,
                'n_auth_blocks': len(auth_block), 'n_none_blocks': len(none_block)}

    df_welch = (s1_sq / len(auth_block) + s2_sq / len(none_block)) ** 2 / (
        (s1_sq / len(auth_block)) ** 2 / (len(auth_block) - 1) +
        (s2_sq / len(none_block)) ** 2 / (len(none_block) - 1))
    t_crit = sp_stats.t.ppf(1 - ALPHA / 2, df_welch)

    return {
        'delta': auth_pctl - none_pctl,
        'ci_low': delta_mean - t_crit * se_diff,
        'ci_high': delta_mean + t_crit * se_diff,
        'block_mean': delta_mean, 'block_se': se_diff,
        'n_auth_blocks': len(auth_block), 'n_none_blocks': len(none_block),
    }


def main():
    configs = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu
        FROM experiments e WHERE {EXCLUDE_SQL}
        ORDER BY e.architecture, e.ram_in_mb, e.auth_strategy
    """)

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
                        ci = compute_within_experiment_ci(auth_id, none_id, arch, 0.99)
                        if ci is None:
                            continue
                        results.append({
                            'architecture': arch, 'hw': hw, 'auth_label': label,
                            'delta': ci['delta'], 'ci_low': ci['ci_low'],
                            'ci_high': ci['ci_high'],
                            'boot_mean': ci['block_mean'], 'boot_std': ci['block_se'],
                        })

    result_df = pd.DataFrame(results)
    if result_df.empty:
        print('No CI results'); return

    def pool_group(grp):
        deltas = grp['boot_mean'].to_numpy(dtype=float)
        ses = grp['boot_std'].to_numpy(dtype=float)
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
            idx = np.flatnonzero(valid)[0]
            pooled_mean = float(deltas[idx])
            ci_low = float(grp['ci_low'].to_numpy()[idx])
            ci_high = float(grp['ci_high'].to_numpy()[idx])
        else:
            pooled_mean = float(np.mean(deltas))
            ci_low = ci_high = pooled_mean
        return pd.Series({'pooled_mean': pooled_mean, 'ci_low': ci_low, 'ci_high': ci_high})

    summary = (
        result_df.groupby(['architecture', 'hw', 'auth_label'], as_index=False, group_keys=False)
        .apply(pool_group).reset_index(drop=True)
    )

    fig, ax = plt.subplots(figsize=(14, max(8, len(summary) * 0.45)))
    y_labels = []
    for i, (_, r) in enumerate(summary.iterrows()):
        label = f"{r['architecture']}/{r['hw']}/{r['auth_label']}"
        y_labels.append(label)
        color = AUTH_COLORS_DETAILED.get(r['auth_label'], '#999')
        ax.errorbar(r['pooled_mean'], i,
                     xerr=[[r['pooled_mean'] - r['ci_low']],
                            [r['ci_high'] - r['pooled_mean']]],
                     fmt='o', color=color, capsize=4, markersize=6, linewidth=1.5)

    ax.axvline(x=0, color='black', linestyle='--', linewidth=0.8, alpha=0.5)
    ax.set_yticks(range(len(y_labels)))
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


if __name__ == '__main__':
    main()
