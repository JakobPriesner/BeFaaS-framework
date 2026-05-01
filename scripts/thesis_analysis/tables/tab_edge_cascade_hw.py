#!/usr/bin/env python3
"""Generate edge_cascade_hw_table.tex for tab:edge-cascade-hw."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df
from tables.tex_helpers import write_tex_table

EXPERIMENTS = [
    ('Microservices', 'Edge', 'S (0,25\\,vCPU)', 100),
    ('', 'Edge', 'S (0,25\\,vCPU)', 101),
    ('', 'Edge', 'S (0,25\\,vCPU)', 102),
    ('', 'Edge', 'M (0,5\\,vCPU)', 130),
    ('', 'Edge', 'L (1,0\\,vCPU)', 135),
    ('', 'Edge', 'XL (4,0\\,vCPU)', 189),
    ('Microservices', 'None', 'S (0,25\\,vCPU)', 98),
    ('', 'None', 'M (0,5\\,vCPU)', 180),
    ('', 'None', 'S (0,25\\,vCPU)', 84),
    (r'\ac{FaaS}', 'Edge', '512\\,MB', 44),
    ('Monolith', 'Edge', 'S (0,25\\,vCPU)', 188),
    ('', 'Edge', 'M (0,5\\,vCPU)', 45),
    ('', 'Edge', 'XL (4,0\\,vCPU)', 190),
]


def main():
    exp_ids = [e[3] for e in EXPERIMENTS]
    ids = ','.join(str(x) for x in exp_ids)

    df = query_df(f"""
        SELECT r.experiment_id,
               COUNT(*) FILTER (WHERE r.status_code >= 500) * 100.0 / NULLIF(COUNT(*), 0) AS pct_5xx
        FROM requests r
        WHERE r.experiment_id IN ({ids})
          AND r.phase_name = 'Morning rush'
        GROUP BY r.experiment_id
    """)

    pct_map = dict(zip(df['experiment_id'].astype(int), df['pct_5xx'].astype(float)))

    lines = []
    lines.append(r'\begin{tabular}{@{}llll S[table-format=2.1]@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Architektur} & \textbf{Auth} & \textbf{Hardware} & \textbf{Exp} & {\textbf{5xx (\%)}} \\')
    lines.append(r'\midrule')

    prev_arch = None
    for arch, auth, hw, exp_id in EXPERIMENTS:
        if arch and arch != prev_arch and prev_arch is not None:
            lines.append(r'\midrule')
        prev_arch = arch if arch else prev_arch
        pct = pct_map.get(exp_id, 0)
        lines.append(f"    {arch} & {auth} & {hw} & E{exp_id} & {pct:.1f} \\\\")

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    write_tex_table('edge_cascade_hw_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
