#!/usr/bin/env python3
"""Generate arch_overhead_exemplary_table.tex for tab:arch-overhead-exemplary."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL
from tables.tex_helpers import write_tex_table, fmt_ms, fmt_delta


def main():
    df = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               e.ram_in_mb, e.cpu_in_vcpu,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p50,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p99
        FROM requests r
        JOIN experiments e ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.endpoint IN ('/frontend/setUser', '/frontend/addCartItem', '/frontend/cart', '/frontend/checkout',
                             '/setUser', '/addCartItem', '/cart', '/checkout')
        GROUP BY e.id, e.architecture, e.auth_strategy, e.password_hash_algorithm,
                 e.ram_in_mb, e.cpu_in_vcpu
    """)

    lines = []
    lines.append(r'\begin{tabular}{@{}llll rrrr@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Arch.} & \textbf{Auth} & \textbf{HW} & \textbf{Exp.} & \textbf{P50} & \textbf{P99} & \textbf{$\Delta$P50} & \textbf{$\Delta$P99} \\')
    lines.append(r'\midrule')

    exemplary = [
        ('faas', 'service-integrated', 512, 'Cognito', '512\\,MB'),
        ('microservices', 'service-integrated', 2048, 'Cognito', 'L'),
        ('monolith', 'service-integrated', 2048, 'Cognito', 'L'),
    ]

    for arch, auth, ram, auth_label, hw_label in exemplary:
        none_rows = df[(df['architecture'] == arch) & (df['auth_strategy'] == 'none') & (df['ram_in_mb'] == ram)]
        auth_rows = df[(df['architecture'] == arch) & (df['auth_strategy'] == auth) & (df['ram_in_mb'] == ram)]
        if none_rows.empty or auth_rows.empty:
            continue
        none_p50 = none_rows['p50'].median()
        none_p99 = none_rows['p99'].median()
        auth_p50 = auth_rows['p50'].median()
        auth_p99 = auth_rows['p99'].median()
        arch_label = {'faas': 'FaaS', 'microservices': 'MS', 'monolith': 'Mono'}[arch]
        lines.append(f"    {arch_label} & {auth_label} & {hw_label} & -- & {fmt_ms(auth_p50)} & {fmt_ms(auth_p99)} & {fmt_delta(auth_p50 - none_p50)} & {fmt_delta(auth_p99 - none_p99)} \\\\")

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    write_tex_table('arch_overhead_exemplary_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
