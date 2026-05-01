#!/usr/bin/env python3
"""Generate scaling_validation_table.tex for tab:scaling-validation."""
import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db_connection import query_df
from tables.tex_helpers import write_tex_table, fmt_ms

EXPERIMENTS = [
    (42, r'FaaS/None (Referenz)'),
    (12, r'MS/None'),
    (13, r'MS/None'),
    (28, r'MS/Cognito'),
    (15, r'MS/Manual'),
    (16, r'MS/Manual'),
]
REFERENCE_ID = 42
MS_IDS = [12, 13, 28, 15, 16]


def main():
    exp_ids = [e[0] for e in EXPERIMENTS]
    id_list = ','.join(str(i) for i in exp_ids)
    df = query_df(f'''
        SELECT r.experiment_id,
               COUNT(*) AS total,
               SUM(CASE WHEN r.is_timeout THEN 1 ELSE 0 END) AS hard_fails,
               PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p50,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p95,
               PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99
        FROM requests r
        WHERE r.experiment_id IN ({id_list})
        GROUP BY r.experiment_id
    ''')
    data = {int(row['experiment_id']): row for _, row in df.iterrows()}

    L = []
    L.append(r'\begin{tabular}{@{}llrrrrr@{}}')
    L.append(r'\toprule')
    L.append(r'\textbf{Exp.} & \textbf{Strategie} & \textbf{Anfragen} & '
             r'\textbf{Hard-F.} & \textbf{P50} & \textbf{P95} & \textbf{P99} \\')
    L.append(r'\midrule')

    for exp_id, label in EXPERIMENTS:
        row = data.get(exp_id)
        if row is None:
            continue
        total = int(row['total'])
        hf = int(row['hard_fails'])
        p50 = fmt_ms(row['p50']) + r'\,ms'
        p95 = fmt_ms(row['p95']) + r'\,ms'
        p99 = fmt_ms(row['p99']) + r'\,ms'
        if exp_id == REFERENCE_ID:
            L.append(f'E{exp_id} & {label} & {fmt_ms(total)} & '
                     f'{hf} & {p50} & {p95} & {p99} \\\\')
            L.append(r'\addlinespace')
        else:
            L.append(f'E{exp_id} & {label} & {fmt_ms(total)} & '
                     f'{hf} & {p50} & {p95} & {p99} \\\\')

    ms_totals = [int(data[i]['total']) for i in MS_IDS if i in data]
    ms_mean = np.mean(ms_totals)
    ms_std = np.std(ms_totals, ddof=1)
    ms_cv = (ms_std / ms_mean * 100) if ms_mean > 0 else 0
    n = len(ms_totals)

    L.append(r'\midrule')
    L.append(r'\multicolumn{2}{@{}l}{\textbf{MS-Mittelwert ($n = '
             + str(n) + r'$)}} & \textbf{'
             + fmt_ms(ms_mean)
             + r'} & & \multicolumn{3}{l}{$\sigma = '
             + fmt_ms(ms_std)
             + r'$, CV $= '
             + f'{ms_cv:.2f}'.replace('.', '{,}')
             + r'\,\%$} \\')
    L.append(r'\bottomrule')
    L.append(r'\end{tabular}')
    write_tex_table('scaling_validation_table.tex', '\n'.join(L) + '\n')


if __name__ == '__main__':
    main()
