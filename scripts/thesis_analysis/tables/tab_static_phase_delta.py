#!/usr/bin/env python3
"""Generate static_phase_delta_table.tex for tab:static-phase-delta."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df
from tables.tex_helpers import write_tex_table, fmt_ms, fmt_delta

E_NONE = 142
E_COGNITO = 143
E_ARGON2ID = 144
PHASES = [
    ('Warm-up', 'Aufwärmphase'),
    ('Baseline', 'Baseline'),
    ('Morning rush', 'Morgenansturm'),
    ('Stabilization', 'Stabilisierung'),
    ('Flash Crowd', 'Lastspitze'),
    ('Step Down', 'Lastabsenkung'),
    ('Cool-down', 'Abkühlphase'),
]


def get_phase_stats(exp_id):
    return query_df(f"""
        SELECT r.phase_name,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.latency_ms) FILTER (WHERE NOT r.is_error) AS p50,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms) FILTER (WHERE NOT r.is_error) AS p99
        FROM requests r
        WHERE r.experiment_id = {exp_id}
        GROUP BY r.phase_name
    """)


def main():
    none = get_phase_stats(E_NONE)
    cog = get_phase_stats(E_COGNITO)
    arg = get_phase_stats(E_ARGON2ID)

    lines = []
    lines.append(r'\resizebox{\textwidth}{!}{%')
    lines.append(r'\begin{tabular}{@{}l S[table-format=3.0] S[table-format=+2.0] S[table-format=+2.0] S[table-format=3.0] S[table-format=+3.0] S[table-format=+3.0]@{}}')
    lines.append(r'\toprule')
    lines.append(r' & {\textbf{None P50}} & {$\boldsymbol{\Delta}$\textbf{Cog.\,P50}} & {$\boldsymbol{\Delta}$\textbf{Man.\,P50}} & {\textbf{None P99}} & {$\boldsymbol{\Delta}$\textbf{Cog.\,P99}} & {$\boldsymbol{\Delta}$\textbf{Man.\,P99}} \\')
    lines.append(r'\midrule')

    for phase_en, phase_de in PHASES:
        n_row = none[none['phase_name'] == phase_en]
        c_row = cog[cog['phase_name'] == phase_en]
        a_row = arg[arg['phase_name'] == phase_en]
        if n_row.empty:
            continue
        np50 = float(n_row['p50'].iloc[0])
        np99 = float(n_row['p99'].iloc[0])
        cp50 = float(c_row['p50'].iloc[0]) if not c_row.empty else np50
        cp99 = float(c_row['p99'].iloc[0]) if not c_row.empty else np99
        ap50 = float(a_row['p50'].iloc[0]) if not a_row.empty else np50
        ap99 = float(a_row['p99'].iloc[0]) if not a_row.empty else np99

        lines.append(f"    {phase_de} & {int(round(np50))} & {int(round(cp50-np50)):+d} & {int(round(ap50-np50)):+d} & {int(round(np99))} & {int(round(cp99-np99)):+d} & {int(round(ap99-np99)):+d} \\\\")

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}}')
    write_tex_table('static_phase_delta_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
