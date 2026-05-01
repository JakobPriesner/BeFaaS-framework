#!/usr/bin/env python3
"""Generate lambda_phase_comparison_table.tex for tab:lambda-phase-comparison."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db_connection import query_df
from tables.tex_helpers import write_tex_table, fmt_ms

E_FAAS = 10
E_MS = 17

PHASE_ORDER = [
    ('Warm-up', r'Aufw\"armphase'),
    ('Baseline', 'Baseline'),
    ('Morning rush', 'Morgenansturm'),
    ('Stabilization', r'Stabilisierung$\dagger$'),
    ('Flash Crowd', r'Lastspitze$\dagger$'),
    ('Step Down', r'Lastabsenkung$\dagger$'),
    ('Cool-down', r'Abk\"uhlphase'),
]


def main():
    exp_ids = f'{E_FAAS},{E_MS}'
    df = query_df(f'''
        SELECT r.experiment_id, r.phase_name,
               COUNT(*) AS total,
               SUM(CASE WHEN r.status_code = 401 THEN 1 ELSE 0 END) AS soft_fails,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p95
        FROM requests r
        WHERE r.experiment_id IN ({exp_ids})
        GROUP BY r.experiment_id, r.phase_name
    ''')
    lookup = {}
    for _, row in df.iterrows():
        lookup[(int(row['experiment_id']), row['phase_name'])] = row

    L = []
    L.append(r'\resizebox{\textwidth}{!}{%')
    L.append(r'\begin{tabular}{@{}lrrrrrr@{}}')
    L.append(r'\toprule')
    L.append(r' & \multicolumn{3}{c}{\textbf{FaaS/Cognito 512\,MB (E10)}} & \multicolumn{3}{c}{\textbf{MS/Cognito L (E17, Vor-Kalibr.)}} \\')
    L.append(r'\cmidrule(lr){2-4} \cmidrule(lr){5-7}')
    L.append(r'\textbf{Phase} & \textbf{Anfr.} & \textbf{Soft-F.} & \textbf{P95} & \textbf{Anfr.} & \textbf{Soft-F.} & \textbf{P95} \\')
    L.append(r'\midrule')

    faas_total, faas_sf = 0, 0
    ms_total, ms_sf = 0, 0

    for phase_en, phase_de in PHASE_ORDER:
        f_row = lookup.get((E_FAAS, phase_en))
        m_row = lookup.get((E_MS, phase_en))

        def fmt_row(row):
            if row is None:
                return '--', '--', '--'
            t = int(row['total'])
            sf = int(row['soft_fails'])
            p = fmt_ms(row['p95']) + '~ms'
            return fmt_ms(t), fmt_ms(sf), p

        ft, fsf, fp = fmt_row(f_row)
        mt, msf, mp = fmt_row(m_row)

        if f_row is not None:
            faas_total += int(f_row['total'])
            faas_sf += int(f_row['soft_fails'])
        if m_row is not None:
            ms_total += int(m_row['total'])
            ms_sf += int(m_row['soft_fails'])

        if phase_en in ('Stabilization', 'Flash Crowd', 'Step Down') and m_row is not None:
            msf = r'\textbf{' + msf + '}'

        L.append(f'{phase_de} & {ft} & {fsf} & {fp} & {mt} & {msf} & {mp} \\\\')

    L.append(r'\midrule')
    L.append(r'\textbf{Gesamt} & \textbf{' + fmt_ms(faas_total)
             + r'} & \textbf{' + fmt_ms(faas_sf)
             + r'} & & \textbf{' + fmt_ms(ms_total)
             + r'} & \textbf{' + fmt_ms(ms_sf) + r'} & \\')
    L.append(r'\bottomrule')
    L.append(r'\end{tabular}}')
    write_tex_table('lambda_phase_comparison_table.tex', '\n'.join(L) + '\n')


if __name__ == '__main__':
    main()
