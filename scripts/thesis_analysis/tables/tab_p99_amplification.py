#!/usr/bin/env python3
"""Generate p99_amplification_table.tex for tab:p99-amplification."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df, EXCLUDE_SQL
from tables.tex_helpers import write_tex_table, fmt_ms

CONFIGS = [
    (r'\ac{FaaS} 512', 'faas', 512, None, [
        ('None', "e.auth_strategy='none'"),
        ('Cognito', "e.auth_strategy='service-integrated'"),
        ('Edge', "e.auth_strategy='edge'"),
        ('argon2id', "e.auth_strategy='service-integrated-manual' AND e.password_hash_algorithm='argon2id'"),
    ]),
    (r'MS/L\textsubscript{stat}', 'microservices', 2048, 1.0, [
        ('None', "e.auth_strategy='none' AND e.id IN (142)"),
        ('Cognito', "e.auth_strategy='service-integrated' AND e.id IN (143)"),
        ('argon2id', "e.auth_strategy='service-integrated-manual' AND e.password_hash_algorithm='argon2id' AND e.id IN (144)"),
    ]),
    (r'Mono/L', 'monolith', 2048, 1.0, [
        ('None', "e.auth_strategy='none'"),
        ('Cognito', "e.auth_strategy='service-integrated'"),
        ('bcrypt', "e.auth_strategy='service-integrated-manual' AND COALESCE(e.password_hash_algorithm,'bcrypt')='bcrypt'"),
    ]),
]


def get_phase_p99(arch, ram, cpu, cond, phase):
    cpu_cond = f"AND e.cpu_in_vcpu = {cpu}" if cpu else ""
    df = query_df(f"""
        SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p99
        FROM requests r JOIN experiments e ON r.experiment_id = e.id
        WHERE e.architecture = '{arch}' AND e.ram_in_mb = {ram} {cpu_cond}
          AND {cond} AND {EXCLUDE_SQL}
          AND r.phase_name = '{phase}'
          AND r.endpoint IN ('/frontend/setUser','/frontend/addCartItem','/frontend/cart','/frontend/checkout',
                             '/setUser','/addCartItem','/cart','/checkout')
        GROUP BY e.id
    """)
    if df.empty:
        return None
    return float(df['p99'].median())


def main():
    lines = []
    lines.append(r'\resizebox{\textwidth}{!}{%')
    lines.append(r'\begin{tabular}{@{}ll S[table-format=4.0] S[table-format=4.0] S[table-format=2.1] S[table-format=5.0] S[table-format=2.1]@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Architektur} & \textbf{Auth} & {\textbf{BL P99 (ms)}} & {\textbf{FC P99 (ms)}} & {$\boldsymbol{A}$\textbf{(FC)}} & {\textbf{SD P99 (ms)}} & {$\boldsymbol{A}$\textbf{(SD)}} \\')
    lines.append(r'\midrule')

    for arch_label, arch, ram, cpu, strats in CONFIGS:
        first = True
        for strat_label, cond in strats:
            bl = get_phase_p99(arch, ram, cpu, cond, 'Baseline')
            fc = get_phase_p99(arch, ram, cpu, cond, 'Flash Crowd')
            sd = get_phase_p99(arch, ram, cpu, cond, 'Step Down')
            if bl is None:
                continue
            a_fc = fc / bl if bl > 0 and fc else 0
            a_sd = sd / bl if bl > 0 and sd else 0
            al = arch_label if first else ''
            first = False
            lines.append(f"    {al} & {strat_label} & {int(round(bl))} & {int(round(fc)) if fc else '--'} & {a_fc:.1f} & {int(round(sd)) if sd else '--'} & {a_sd:.1f} \\\\")
        lines.append(r'\midrule')

    lines[-1] = r'\bottomrule'
    lines.append(r'\end{tabular}}')
    write_tex_table('p99_amplification_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
