#!/usr/bin/env python3
"""Generate manual_cpu_control_table.tex for tab:manual-cpu-control."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df, EXCLUDE_SQL
from tables.tex_helpers import write_tex_table

STRATEGIES = [
    ('None', "e.auth_strategy = 'none'"),
    ('Manual~(bcrypt/HS256)', "e.auth_strategy = 'service-integrated-manual' AND e.password_hash_algorithm = 'bcrypt'"),
    ('Manual~(argon2id/EdDSA)', "e.auth_strategy = 'service-integrated-manual' AND e.password_hash_algorithm = 'argon2id'"),
]
ACTIVE_PHASES = ('Morning rush', 'Stabilization', 'Flash Crowd')


def main():
    lines = []
    lines.append(r'\begin{tabular}{@{}l S[table-format=2.1] S[table-format=2.1] S[table-format=2.1] S[table-format=2.1]@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Strategie} & {\textbf{Mittelwert (\%)}} & {\textbf{Faktor}} & {\textbf{p95 (\%)}} & {\textbf{Faktor}} \\')
    lines.append(r'\midrule')

    phases_str = ','.join(f"'{p}'" for p in ACTIVE_PHASES)
    none_mean = None
    none_p95 = None

    for label, cond in STRATEGIES:
        df = query_df(f"""
            WITH phase_bounds AS (
                SELECT experiment_id, phase_name,
                       to_timestamp(MIN(timestamp_ms)/1000.0) AS ph_start,
                       to_timestamp(MAX(timestamp_ms)/1000.0) AS ph_end
                FROM requests
                GROUP BY experiment_id, phase_name
            )
            SELECT m.cpu_percent
            FROM metrics_ecs m
            JOIN experiments e ON m.experiment_id = e.id
            JOIN phase_bounds pb ON pb.experiment_id = e.id
                AND m.timestamp BETWEEN pb.ph_start AND pb.ph_end
            WHERE e.architecture = 'monolith' AND e.ram_in_mb = 2048
              AND {cond} AND {EXCLUDE_SQL}
              AND m.service_name LIKE '%%monolith%%'
              AND m.cpu_percent IS NOT NULL
              AND pb.phase_name IN ({phases_str})
        """)

        if df.empty:
            continue

        mean_cpu = df['cpu_percent'].mean()
        p95_cpu = df['cpu_percent'].quantile(0.95)

        if none_mean is None:
            none_mean = mean_cpu
            none_p95 = p95_cpu

        factor_mean = mean_cpu / none_mean if none_mean > 0 else 0
        factor_p95 = p95_cpu / none_p95 if none_p95 > 0 else 0

        lines.append(f"    {label} & {mean_cpu:.1f} & {factor_mean:.1f} & {p95_cpu:.1f} & {factor_p95:.1f} \\\\")

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    write_tex_table('manual_cpu_control_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
