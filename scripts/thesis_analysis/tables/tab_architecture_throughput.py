#!/usr/bin/env python3
"""Generate architecture_throughput_table.tex for tab:architecture-throughput-comparison."""
import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db_connection import query_df
from tables.tex_helpers import write_tex_table, fmt_ms

EXPERIMENTS = [
    (9,  'FaaS (Cognito)',  '256~MB'),
    (10, 'FaaS (Cognito)',  '512~MB'),
    (8,  'FaaS (Manual)',   '512~MB'),
    (11, 'MS (None)',       'L (1~vCPU)'),
    (17, 'MS (Cognito)',    'L (1~vCPU)'),
    (14, 'MS (Manual)',     'L (1~vCPU)'),
]


def main():
    exp_ids = [e[0] for e in EXPERIMENTS]
    id_list = ','.join(str(i) for i in exp_ids)
    df = query_df(f'''
        SELECT r.experiment_id,
               COUNT(*) AS total,
               SUM(CASE WHEN r.status_code = 401 THEN 1 ELSE 0 END) AS soft_fails
        FROM requests r
        WHERE r.experiment_id IN ({id_list})
        GROUP BY r.experiment_id
    ''')
    data = {int(row['experiment_id']): row for _, row in df.iterrows()}

    faas_ids = [9, 10, 8]
    faas_totals = [int(data[i]['total']) for i in faas_ids if i in data]
    faas_mean = np.mean(faas_totals) if faas_totals else 1.0

    L = []
    L.append(r'\begin{tabular}{@{}rllrrr@{}}')
    L.append(r'\toprule')
    L.append(r'\textbf{Exp.} & \textbf{Architektur} & '
             r'\textbf{Konfiguration} & \textbf{Anfragen} & '
             r'\textbf{Soft-Fails} & \textbf{Faktor} \\')
    L.append(r'\midrule')

    prev_arch = None
    for exp_id, arch_label, config_label in EXPERIMENTS:
        row = data.get(exp_id)
        if row is None:
            continue
        total = int(row['total'])
        sf = int(row['soft_fails'])
        factor = total / faas_mean

        if 'MS' in arch_label and (prev_arch is None or 'FaaS' in prev_arch):
            L.append(r'\addlinespace')
        prev_arch = arch_label

        factor_str = f'{factor:.2f}'.replace('.', '{,}') + r'$\times$'

        L.append(f'E{exp_id} & {arch_label} & {config_label} & '
                 f'{fmt_ms(total)} & {fmt_ms(sf)} & {factor_str} \\\\')

    L.append(r'\bottomrule')
    L.append(r'\end{tabular}')
    write_tex_table('architecture_throughput_table.tex',
                    '\n'.join(L) + '\n')


if __name__ == '__main__':
    main()
