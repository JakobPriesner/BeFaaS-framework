#!/usr/bin/env python3
"""Generate ratio_analysis_table.tex for tab:ratio-analysis."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
from db_connection import query_df
from tables.tex_helpers import write_tex_table

CONFIGS = [
    (r'\ac{FaaS}', '512\\,MB', 'faas', [87, 10]),
    (r'\ac{FaaS}', '1.024\\,MB', 'faas', [42, 120]),
    ('Microservices', 'L (statisch)', 'microservices', [142, 143]),
    ('Microservices', 'XL', 'microservices', [64, 65]),
    ('Monolith', 'L', 'monolith', [30, 36]),
    ('Monolith', 'XL', 'monolith', [62, 70]),
]


def get_delta_p50(none_id, auth_id, arch, endpoint):
    prefix = '/frontend/' if arch == 'faas' else '/'
    for exp_id in [none_id, auth_id]:
        pass
    none_df = query_df(f"""
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
            FILTER (WHERE NOT is_error AND phase_name = 'Baseline') AS p50
        FROM requests WHERE experiment_id = {none_id} AND endpoint = '{prefix}{endpoint}'
    """)
    auth_df = query_df(f"""
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
            FILTER (WHERE NOT is_error AND phase_name = 'Baseline') AS p50
        FROM requests WHERE experiment_id = {auth_id} AND endpoint = '{prefix}{endpoint}'
    """)
    if none_df.empty or auth_df.empty:
        return None
    n = none_df['p50'].iloc[0]
    a = auth_df['p50'].iloc[0]
    if n is None or a is None:
        return None
    return float(a) - float(n)


def main():
    lines = []
    lines.append(r'\begin{tabular}{@{}ll S[table-format=+3.0] S[table-format=+2.0] S[table-format=1.2]@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Architektur} & \textbf{Hardware} & {$\boldsymbol{\Delta}$\textbf{P50 Checkout}} & {$\boldsymbol{\Delta}$\textbf{P50 addCartItem}} & {\textbf{Ratio}} \\')
    lines.append(r'\midrule')

    ratios = []
    for arch_label, hw_label, arch, exp_ids in CONFIGS:
        none_id, auth_id = exp_ids[0], exp_ids[1]
        d_checkout = get_delta_p50(none_id, auth_id, arch, 'checkout')
        d_addcart = get_delta_p50(none_id, auth_id, arch, 'addCartItem')
        if d_checkout is not None and d_addcart is not None and abs(d_addcart) > 0:
            ratio = d_checkout / d_addcart
            ratios.append(ratio)
            lines.append(f"    {arch_label} & {hw_label} & {int(round(d_checkout)):+d} & {int(round(d_addcart)):+d} & {ratio:.2f} \\\\")

    if ratios:
        mean_r = np.mean(ratios)
        std_r = np.std(ratios, ddof=1)
        cv_r = std_r / mean_r * 100
        lines.append(r'\midrule')
        lines.append(f"    \\multicolumn{{4}}{{@{{}}l}}{{\\textbf{{Mittelwert}} ($n = {len(ratios)}$)}} & \\textbf{{{mean_r:.2f}}} \\\\")
        lines.append(f"    \\multicolumn{{4}}{{@{{}}l}}{{Standardabweichung}} & {std_r:.2f} \\\\")
        lines.append(f"    \\multicolumn{{4}}{{@{{}}l}}{{Variationskoeffizient}} & {cv_r:.1f}\\,\\% \\\\")

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    write_tex_table('ratio_analysis_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
