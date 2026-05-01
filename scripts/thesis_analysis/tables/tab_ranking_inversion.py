#!/usr/bin/env python3
"""Generate ranking_inversion_table.tex for tab:ranking-inversion."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df, EXCLUDE_SQL
from tables.tex_helpers import write_tex_table, fmt_delta

CONFIGS = {
    'faas_512': ('faas', 512, None),
    'ms_l': ('microservices', 2048, 1.0),
    'mono_l': ('monolith', 2048, 1.0),
}
STRATS = [
    ('Manual', "e.auth_strategy = 'service-integrated-manual' AND COALESCE(e.password_hash_algorithm,'bcrypt') = 'bcrypt'"),
    ('Cognito', "e.auth_strategy = 'service-integrated'"),
    ('Edge', "e.auth_strategy = 'edge'"),
]
PHASES = ['Baseline', 'Flash Crowd']
PHASE_DE = {'Baseline': 'Baseline', 'Flash Crowd': 'Flash Crowd'}


def get_delta_p99(arch, ram, cpu, auth_cond, phase):
    cpu_cond = f"AND e.cpu_in_vcpu = {cpu}" if cpu else ""
    auth_df = query_df(f"""
        SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p99
        FROM requests r JOIN experiments e ON r.experiment_id = e.id
        WHERE e.architecture = '{arch}' AND e.ram_in_mb = {ram} {cpu_cond}
          AND {auth_cond} AND {EXCLUDE_SQL}
          AND r.phase_name = '{phase}'
          AND r.endpoint IN ('/frontend/setUser','/frontend/addCartItem','/frontend/cart','/frontend/checkout',
                             '/setUser','/addCartItem','/cart','/checkout')
        GROUP BY e.id
    """)
    none_df = query_df(f"""
        SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p99
        FROM requests r JOIN experiments e ON r.experiment_id = e.id
        WHERE e.architecture = '{arch}' AND e.ram_in_mb = {ram} {cpu_cond}
          AND e.auth_strategy = 'none' AND {EXCLUDE_SQL}
          AND r.phase_name = '{phase}'
          AND r.endpoint IN ('/frontend/setUser','/frontend/addCartItem','/frontend/cart','/frontend/checkout',
                             '/setUser','/addCartItem','/cart','/checkout')
        GROUP BY e.id
    """)
    if auth_df.empty or none_df.empty:
        return None
    return float(auth_df['p99'].median()) - float(none_df['p99'].median())


def main():
    lines = []
    lines.append(r'\begin{tabular}{@{}ll S[table-format=+4.0] S[table-format=+4.0] S[table-format=+4.0]@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Phase} & \textbf{Strategie} & {\textbf{\ac{FaaS}}} & {\textbf{MS/L}} & {\textbf{Mono/L}} \\')
    lines.append(r'\midrule')

    for phase in PHASES:
        first = True
        for strat_label, strat_cond in STRATS:
            vals = []
            for key in ['faas_512', 'ms_l', 'mono_l']:
                arch, ram, cpu = CONFIGS[key]
                d = get_delta_p99(arch, ram, cpu, strat_cond, phase)
                vals.append(f"{int(round(d)):+d}" if d is not None else '--')
            phase_col = PHASE_DE[phase] if first else ''
            first = False
            lines.append(f"    {phase_col} & {strat_label} & {vals[0]} & {vals[1]} & {vals[2]} \\\\")
        if phase != PHASES[-1]:
            lines.append(r'\midrule')

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    write_tex_table('ranking_inversion_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
