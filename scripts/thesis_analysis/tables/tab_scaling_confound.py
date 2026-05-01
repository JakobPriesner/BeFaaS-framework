#!/usr/bin/env python3
"""Generate scaling_confound_table.tex for tab:scaling-confound."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df
from tables.tex_helpers import write_tex_table

E_STATIC_NONE = 142
E_STATIC_COG = 143
E_AUTO_NONE = 13
E_AUTO_COG = 28
ENDPOINTS = ['addCartItem', 'cart', 'checkout']
ENDPOINT_DE = {'addCartItem': 'addCartItem', 'cart': 'Warenkorb', 'checkout': 'Checkout'}


def get_endpoint_p50(exp_id, endpoint):
    ep_variants = [f"'/frontend/{endpoint}'", f"'/{endpoint}'"]
    ep_sql = ','.join(ep_variants)
    df = query_df(f"""
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p50
        FROM requests r
        WHERE r.experiment_id = {exp_id}
          AND r.endpoint IN ({ep_sql})
    """)
    return float(df['p50'].iloc[0]) if not df.empty and df['p50'].iloc[0] is not None else None


def main():
    lines = []
    lines.append(r'\begin{tabular}{@{}l S[table-format=+3.0] S[table-format=+3.0] r@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Endpunkt} & {\textbf{Statisch $\Delta$}} & {\textbf{Autoskal.\ $\Delta$}} & \textbf{Abweichung} \\')
    lines.append(r'\midrule')

    for ep in ENDPOINTS:
        s_none = get_endpoint_p50(E_STATIC_NONE, ep)
        s_cog = get_endpoint_p50(E_STATIC_COG, ep)
        a_none = get_endpoint_p50(E_AUTO_NONE, ep)
        a_cog = get_endpoint_p50(E_AUTO_COG, ep)
        if any(v is None for v in [s_none, s_cog, a_none, a_cog]):
            continue
        d_static = s_cog - s_none
        d_auto = a_cog - a_none
        deviation = (d_auto - d_static) / abs(d_static) * 100 if abs(d_static) > 0 else 0
        dev_str = f"$+${int(round(deviation))}\\,\\%" if deviation >= 0 else f"${int(round(deviation))}\\,\\%"
        lines.append(f"    {ENDPOINT_DE[ep]} & {int(round(d_static)):+d} & {int(round(d_auto)):+d} & {dev_str} \\\\")

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    write_tex_table('scaling_confound_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
