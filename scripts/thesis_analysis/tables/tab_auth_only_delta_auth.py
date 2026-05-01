#!/usr/bin/env python3
"""Generate auth_only_delta_auth_table.tex for tab:auth-only-delta-auth."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, auth_label_detailed, hw_label_from_row, HW_TIERS_ALL
from tables.tex_helpers import write_tex_table, fmt_ms, fmt_delta

AUTH_ENDPOINTS_FAAS = ("'/frontend/setUser'", "'/frontend/addCartItem'", "'/frontend/cart'", "'/frontend/checkout'")
AUTH_ENDPOINTS_CONTAINER = ("'/setUser'", "'/addCartItem'", "'/cart'", "'/checkout'")
ARCH_ORDER = ['faas', 'microservices', 'monolith']
ARCH_LABELS = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}
AUTH_ORDER = ['Cognito', 'Manual (bcrypt)', 'Manual (argon2id)', 'Edge', 'Edge-Sel.']


def main():
    df = query_df(f"""
        SELECT e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, e.cpu_in_vcpu,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p50,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p99
        FROM requests r
        JOIN experiments e ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND (
            (e.architecture = 'faas' AND r.endpoint IN ({','.join(AUTH_ENDPOINTS_FAAS)}))
            OR
            (e.architecture != 'faas' AND r.endpoint IN ({','.join(AUTH_ENDPOINTS_CONTAINER)}))
          )
        GROUP BY e.id, e.architecture, e.auth_strategy, e.password_hash_algorithm,
                 e.with_cloudfront, e.ram_in_mb, e.cpu_in_vcpu
    """)

    df['auth_label'] = df.apply(lambda r: auth_label_detailed(r['auth_strategy'], r['algo'], r['with_cf']), axis=1)
    df['hw_label'] = df.apply(lambda r: hw_label_from_row(r), axis=1)

    none_df = df[df['auth_label'].isin(['None', 'None+CF'])].copy()
    none_baselines = none_df.groupby(['architecture', 'hw_label']).agg(
        none_p50=('p50', 'median'), none_p99=('p99', 'median'),
    ).reset_index()

    auth_df = df[~df['auth_label'].isin(['None', 'None+CF'])].copy()
    auth_agg = auth_df.groupby(['architecture', 'auth_label', 'hw_label']).agg(
        p50=('p50', 'median'), p99=('p99', 'median'), n=('p50', 'count'),
    ).reset_index()

    merged = auth_agg.merge(none_baselines, on=['architecture', 'hw_label'], how='left')
    merged['delta_p50'] = merged['p50'] - merged['none_p50']
    merged['delta_p99'] = merged['p99'] - merged['none_p99']

    lines = []
    lines.append(r'\begin{longtable}{@{}ll rr rr r@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Architektur/HW} & \textbf{Strategie} & \textbf{P50} & \textbf{$\Delta$P50} & \textbf{P99} & \textbf{$\Delta$P99} & \textbf{$n$} \\')
    lines.append(r'\midrule')
    lines.append(r'\endfirsthead')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Architektur/HW} & \textbf{Strategie} & \textbf{P50} & \textbf{$\Delta$P50} & \textbf{P99} & \textbf{$\Delta$P99} & \textbf{$n$} \\')
    lines.append(r'\midrule')
    lines.append(r'\endhead')

    for arch in ARCH_ORDER:
        hw_tiers = HW_TIERS_ALL[arch]
        for ram, cpu, hw_lbl in hw_tiers:
            first_row = True
            for auth in AUTH_ORDER:
                row = merged[(merged['architecture'] == arch) & (merged['hw_label'] == hw_lbl) & (merged['auth_label'] == auth)]
                if row.empty:
                    continue
                r = row.iloc[0]
                prefix = f"{ARCH_LABELS[arch]}/{hw_lbl}" if first_row else ""
                lines.append(f"    {prefix} & {auth} & {fmt_ms(r['p50'])} & {fmt_delta(r['delta_p50'])} & {fmt_ms(r['p99'])} & {fmt_delta(r['delta_p99'])} & {int(r['n'])} \\\\")
                first_row = False
        lines.append(r'\addlinespace')

    lines.append(r'\bottomrule')
    lines.append(r'\end{longtable}')
    write_tex_table('auth_only_delta_auth_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
