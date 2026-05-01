#!/usr/bin/env python3
"""Generate decision_matrix_table.tex for tab:decision-matrix.

Decision matrix at comparable hardware (FaaS 512MB, Container L) showing
P50, P99, ΔP99, token exposure, and error rate per auth strategy.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

AUTH_ORDER = [
    ('none', 'None'),
    ('service-integrated', 'Cognito'),
    ('service-integrated-manual', r'Manual~(bcrypt/HS256)'),
    ('edge', 'Edge'),
]

TOKEN_EXPOSURE = {
    ('faas', 'none'): 0,
    ('faas', 'service-integrated'): 17,
    ('faas', 'service-integrated-manual'): 17,
    ('faas', 'edge'): 1,
    ('microservices', 'none'): 0,
    ('microservices', 'service-integrated'): 2,
    ('microservices', 'service-integrated-manual'): 2,
    ('microservices', 'edge'): 1,
    ('monolith', 'none'): 0,
    ('monolith', 'service-integrated'): 1,
    ('monolith', 'service-integrated-manual'): 1,
    ('monolith', 'edge'): 1,
}

ARCH_CONFIGS = [
    ('faas', 512, None, r'\ac{FaaS}'),
    ('microservices', 2048, 1.0, 'MS'),
    ('monolith', 2048, 1.0, 'Mono'),
]


def main():
    latency = query_df(f"""
        SELECT
            e.architecture, e.auth_strategy,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE r.is_error) AS n_errors,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.phase_name = 'Baseline'
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.architecture, e.auth_strategy, e.ram_in_mb, cpu
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 1000
    """)
    if latency.empty:
        print('No data'); return

    for col in ['p50', 'p99']:
        latency[col] = latency[col].astype(float)
    latency['error_rate'] = latency['n_errors'] / latency['total'] * 100

    lines = []
    lines.append(r"\begin{table}[htbp]")
    lines.append(r"\centering")
    lines.append(r"\caption{Entscheidungsmatrix bei vergleichbarer Hardware "
                 r"(FaaS~512\,MB, Container~L). Eingangsgrößen siehe "
                 r"Tabellen~\ref{tab:token-exposure} und~\ref{tab:security-properties}.}")
    lines.append(r"\label{tab:decision-matrix}")
    lines.append(r"\small")
    lines.append(r"\begin{tabular}{@{}l l S[table-format=3.0] S[table-format=3.0] "
                 r"S[table-format=3.0] S[table-format=2.0] S[table-format=2.2]@{}}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Architektur} & \textbf{Auth} & {\textbf{P50\,(ms)}} "
                 r"& {\textbf{P99\,(ms)}} & {\textbf{$\Delta$P99\,(ms)}} "
                 r"& {\textbf{Tok.-Exp.}} & {\textbf{Fehler\,(\%)}} \\")
    lines.append(r"\midrule")

    first_arch = True
    for arch, ram, cpu, tex_arch in ARCH_CONFIGS:
        if not first_arch:
            lines.append(r"\midrule")
        first_arch = False

        cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu is None else f"AND COALESCE(e.cpu_in_vcpu, 0) = {cpu}"
        sub = latency[(latency['architecture'] == arch) & (latency['ram_in_mb'] == ram)]
        if cpu is not None:
            sub = sub[sub['cpu'] == cpu]

        none_p99 = 0
        none_row = sub[sub['auth_strategy'] == 'none']
        if not none_row.empty:
            none_p99 = none_row.iloc[0]['p99']

        for auth_db, auth_tex in AUTH_ORDER:
            match = sub[sub['auth_strategy'] == auth_db]
            if match.empty:
                continue
            r = match.iloc[0]
            delta = r['p99'] - none_p99 if auth_db != 'none' else 0
            tok = TOKEN_EXPOSURE.get((arch, auth_db), 0)
            lines.append(
                f"{tex_arch} & {auth_tex} & {r['p50']:.0f} & {r['p99']:.0f} "
                f"& {delta:.0f} & {tok} & {r['error_rate']:.2f} \\\\"
            )

    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")

    path = f"{PLOT_DIR}/decision_matrix_table.tex"
    with open(path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"Saved: {path}")


if __name__ == '__main__':
    main()
