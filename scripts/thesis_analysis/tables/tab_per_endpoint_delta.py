#!/usr/bin/env python3
"""Generate per_endpoint_delta_table.tex for tab:per-endpoint-delta."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df, EXCLUDE_SQL
from tables.tex_helpers import write_tex_table

K_EFF = {'addCartItem': 2, 'cart': 2, 'checkout': 6}
DELTA_SINGLE = 18

CONFIGS = [
    ('FaaS 512', 'faas', 512, None, [('E87', 'none', 87), ('E10', 'service-integrated', 10)]),
    ('FaaS 1024', 'faas', 1024, None, [('E42', 'none', 42), ('E120', 'service-integrated', 120)]),
    ('MS/L\\textsubscript{stat}', 'microservices', 2048, 1.0, [('E142', 'none', 142), ('E143', 'service-integrated', 143)]),
    ('MS/XL', 'microservices', 8192, 4.0, [('E64', 'none', 64), ('E65', 'service-integrated', 65)]),
    ('Mono/L', 'monolith', 2048, 1.0, [('E30', 'none', 30), ('E36', 'service-integrated', 36)]),
    ('Mono/XL', 'monolith', 8192, 4.0, [('E62', 'none', 62), ('E70', 'service-integrated', 70)]),
]

ENDPOINTS = ['addCartItem', 'cart', 'checkout']
ENDPOINT_DE = {'addCartItem': 'addCartItem', 'cart': 'Warenkorb', 'checkout': 'Checkout'}


def get_p50(exp_id, arch, endpoint):
    prefix = '/frontend/' if arch == 'faas' else '/'
    df = query_df(f"""
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
            FILTER (WHERE NOT is_error AND phase_name = 'Baseline') AS p50
        FROM requests WHERE experiment_id = {exp_id}
          AND endpoint = '{prefix}{endpoint}'
    """)
    return float(df['p50'].iloc[0]) if not df.empty and df['p50'].iloc[0] is not None else None


def main():
    lines = []
    lines.append(r'\resizebox{\textwidth}{!}{%')
    lines.append(r'\begin{tabular}{@{}l r rr rr rr rr rr rr@{}}')
    lines.append(r'\toprule')
    header2 = ' & '.join(f"\\multicolumn{{2}}{{c}}{{\\textbf{{{c[0]}}}}}" for c in CONFIGS)
    lines.append(f" & & {header2} \\\\")
    cmidrules = ' '.join(f"\\cmidrule(lr){{{3+i*2}-{4+i*2}}}" for i in range(len(CONFIGS)))
    lines.append(cmidrules)
    sub = ' & '.join(['{$\\Delta$} & {Abw.}'] * len(CONFIGS))
    lines.append(f"\\textbf{{Endpunkt}} & $\\boldsymbol{{k_{{\\text{{eff}}}}}}$ & {sub} \\\\")
    lines.append(r'\midrule')

    for ep in ENDPOINTS:
        k = K_EFF[ep]
        predicted = k * DELTA_SINGLE
        vals = []
        for config_label, arch, ram, cpu, pairs in CONFIGS:
            none_id = [p[2] for p in pairs if p[1] == 'none'][0]
            auth_id = [p[2] for p in pairs if p[1] == 'service-integrated'][0]
            none_p50 = get_p50(none_id, arch, ep)
            auth_p50 = get_p50(auth_id, arch, ep)
            if none_p50 is not None and auth_p50 is not None:
                delta = auth_p50 - none_p50
                deviation = (delta - predicted) / predicted * 100
                vals.append(f"{int(round(delta)):+d} & ${int(round(deviation)):+d}\\,\\%$")
            else:
                vals.append('-- & --')
        lines.append(f"    {ENDPOINT_DE[ep]} & {k} & {' & '.join(vals)} \\\\")

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}}')
    write_tex_table('per_endpoint_delta_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
