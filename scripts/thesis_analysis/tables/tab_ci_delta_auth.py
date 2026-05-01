#!/usr/bin/env python3
"""Generate ci_delta_auth_table.tex for tab:ci-delta-auth.

Statistical method (thesis §6.1.7):
- Within-experiment CI: 60s-block P99 values per experiment, paired delta
  (auth blocks − none blocks), one-sample t-test against 0,
  CI = mean ± t_{α/2, n-1} · SE  (Eq. 6.4)
- Between-experiment CI: median block-P99 per independent run, then
  Welch-t CI for the difference of means with Welch-Satterthwaite df
  (Eq. 6.6 / 6.7)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
from scipy import stats
from db_connection import query_df, EXCLUDE_SQL
from tables.tex_helpers import write_tex_table

WINDOW_MS = 60000

AUTH_ENDPOINTS = """
    r.endpoint IN ('/frontend/setUser', '/frontend/addCartItem',
                   '/frontend/cart', '/frontend/checkout',
                   '/setUser', '/addCartItem', '/cart', '/checkout')
"""

CONFIGS = [
    ('faas', 512, 'service-integrated', None, r'\ac{FaaS} 512\,MB', 'Cognito'),
    ('faas', 512, 'service-integrated-manual', 'bcrypt', r'', 'Manual'),
    ('faas', 512, 'edge', None, r'', 'Edge'),
    ('microservices', 2048, 'service-integrated', None, r'MS L', 'Cognito'),
    ('microservices', 2048, 'service-integrated-manual', 'bcrypt', r'', 'Manual'),
    ('monolith', 2048, 'service-integrated', None, r'Monolith L', 'Cognito'),
    ('monolith', 2048, 'service-integrated-manual', 'bcrypt', r'', r'Manual'),
    ('monolith', 2048, 'edge', None, r'', 'Edge'),
]


def get_all_block_p99(arch, ram, auth_strat, algo, phase='Baseline'):
    """Get block-P99 arrays for ALL experiments matching the config.

    Returns dict {exp_id: np.array of block P99 values}.
    Only includes experiments with ≥3 blocks.
    """
    algo_cond = f"AND e.password_hash_algorithm = '{algo}'" if algo else ""
    df = query_df(f"""
        SELECT e.id AS exp_id,
               FLOOR(r.relative_time_ms / {WINDOW_MS}) AS block,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99
        FROM requests r
        JOIN experiments e ON r.experiment_id = e.id
        WHERE e.architecture = '{arch}' AND e.ram_in_mb = {ram}
          AND e.auth_strategy = '{auth_strat}' {algo_cond}
          AND {EXCLUDE_SQL}
          AND r.phase_name = '{phase}'
          AND {AUTH_ENDPOINTS}
        GROUP BY e.id, block
        HAVING COUNT(*) > 5
        ORDER BY e.id, block
    """)
    result = {}
    if df.empty:
        return result
    for eid, grp in df.groupby('exp_id'):
        vals = grp['p99'].dropna().values
        if len(vals) >= 3:
            result[int(eid)] = vals
    return result


def main():
    lines = []
    lines.append(r'\begin{tabular}{@{}ll S[table-format=+3.0] r l l@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Konfiguration} & \textbf{Auth} & {$\boldsymbol{\Delta}$\textbf{P99}} & \textbf{95\,\%-KI (within)} & \textbf{$p$} & \textbf{95\,\%-KI (between)} \\')
    lines.append(r'\midrule')

    prev_config_label = None
    for arch, ram, auth_strat, algo, config_label, auth_label in CONFIGS:
        auth_blocks_map = get_all_block_p99(arch, ram, auth_strat, algo)
        none_blocks_map = get_all_block_p99(arch, ram, 'none', None)

        if not auth_blocks_map or not none_blocks_map:
            continue

        # --- Within-experiment CI ---
        # Pick experiment pair with most overlapping blocks
        best_within = None
        for a_id, a_blocks in auth_blocks_map.items():
            for n_id, n_blocks in none_blocks_map.items():
                overlap = min(len(a_blocks), len(n_blocks))
                if overlap >= 3 and (best_within is None or overlap > best_within[0]):
                    best_within = (overlap, a_blocks, n_blocks)

        if best_within is None:
            continue

        min_len, auth_blocks, none_blocks = best_within
        delta_blocks = auth_blocks[:min_len] - none_blocks[:min_len]
        mean_delta = np.mean(delta_blocks)
        se = np.std(delta_blocks, ddof=1) / np.sqrt(min_len)
        t_stat, p_val = stats.ttest_1samp(delta_blocks, 0)
        t_crit_within = stats.t.ppf(0.975, min_len - 1)
        ci_low = mean_delta - t_crit_within * se
        ci_high = mean_delta + t_crit_within * se

        # --- Between-experiment CI ---
        auth_p99s = [np.median(blocks) for blocks in auth_blocks_map.values()]
        none_p99s = [np.median(blocks) for blocks in none_blocks_map.values()]

        between_ci = 'n.\\,b.'
        if len(auth_p99s) >= 2 and len(none_p99s) >= 2:
            auth_arr = np.array(auth_p99s)
            none_arr = np.array(none_p99s)
            diff = np.mean(auth_arr) - np.mean(none_arr)
            se_b = np.sqrt(np.var(auth_arr, ddof=1)/len(auth_arr) + np.var(none_arr, ddof=1)/len(none_arr))
            # Welch-Satterthwaite degrees of freedom (thesis Eq. 6.7)
            df_welch = (np.var(auth_arr, ddof=1)/len(auth_arr) + np.var(none_arr, ddof=1)/len(none_arr))**2 / (
                (np.var(auth_arr, ddof=1)/len(auth_arr))**2/(len(auth_arr)-1) +
                (np.var(none_arr, ddof=1)/len(none_arr))**2/(len(none_arr)-1)
            )
            t_crit = stats.t.ppf(0.975, df_welch)
            b_low = diff - t_crit * se_b
            b_high = diff + t_crit * se_b
            star = ''
            if b_low <= 0 <= b_high:
                star = r'\textsuperscript{*}'
            between_ci = f"$[{int(round(b_low)):+d},\\, {int(round(b_high)):+d}]${star}"

        if config_label and config_label != prev_config_label:
            if prev_config_label is not None:
                lines.append(r'\midrule')
            cl = config_label
            prev_config_label = config_label
        else:
            cl = ''

        p_str = '$<$0{,}001' if p_val < 0.001 else f'{p_val:.3f}'.replace('.', '{,}')
        within_ci = f"$[{int(round(ci_low)):+d},\\, {int(round(ci_high)):+d}]$"
        lines.append(f"    {cl} & {auth_label} & {int(round(mean_delta))} & {within_ci} & {p_str} & {between_ci} \\\\")

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    write_tex_table('ci_delta_auth_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
