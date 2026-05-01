#!/usr/bin/env python3
"""Generate equalizing_table.tex for tab:equalizing."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df, EXCLUDE_SQL
from tables.tex_helpers import write_tex_table

FAAS_NONE = 42
FAAS_COG = 120
MONO_NONE = 30
MONO_COG = 36

ENDPOINTS = [
    ('Checkout', 6, 'checkout'),
    ('Homepage', 0, 'homepage'),
]


def get_p99(exp_id, arch, endpoint):
    if endpoint == 'homepage':
        ep_sql = "r.endpoint IN ('/', '/frontend/', '/frontend/index', '/index')"
    else:
        prefix = '/frontend/' if arch == 'faas' else '/'
        ep_sql = f"r.endpoint = '{prefix}{endpoint}'"
    df = query_df(f"""
        SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p99
        FROM requests r WHERE r.experiment_id = {exp_id} AND {ep_sql}
    """)
    if df.empty or df['p99'].iloc[0] is None:
        return None
    return float(df['p99'].iloc[0])


def main():
    lines = []
    lines.append(r'\begin{tabular}{@{}l S[table-format=2.0] S[table-format=3.0] S[table-format=3.0] S[table-format=2.1] S[table-format=2.1] S[table-format=2.1]@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Endpunkt} & {\textbf{$k$}} & {\textbf{FaaS P99}} & {\textbf{Mono P99}} & {\textbf{Faktor (None)}} & {\textbf{Faktor (Cog.)}} & {\textbf{Kompr.}} \\')
    lines.append(r'\midrule')

    for ep_label, k, ep_key in ENDPOINTS:
        fn = get_p99(FAAS_NONE, 'faas', ep_key)
        fc = get_p99(FAAS_COG, 'faas', ep_key)
        mn = get_p99(MONO_NONE, 'monolith', ep_key)
        mc = get_p99(MONO_COG, 'monolith', ep_key)
        if any(v is None for v in [fn, fc, mn, mc]):
            continue
        factor_none = fn / mn if mn > 0 else 0
        factor_cog = fc / mc if mc > 0 else 0
        compression = factor_none / factor_cog if factor_cog > 0 else 0
        k_str = str(k) if k > 0 else '{--}'
        lines.append(f"    {ep_label} & {k_str} & {{{int(round(fn))}}} & {{{int(round(mn))}}} & {factor_none:.1f} & {factor_cog:.1f} & {compression:.1f} \\\\")

    # Gesamt
    fn_all = get_p99(FAAS_NONE, 'faas', 'all')
    fc_all = get_p99(FAAS_COG, 'faas', 'all')
    mn_all = get_p99(MONO_NONE, 'monolith', 'all')
    mc_all = get_p99(MONO_COG, 'monolith', 'all')

    lines.append(r'\midrule')
    if all(v is not None for v in [fn_all, fc_all, mn_all, mc_all]):
        f_none = fn_all / mn_all if mn_all > 0 else 0
        f_cog = fc_all / mc_all if mc_all > 0 else 0
        compr = f_none / f_cog if f_cog > 0 else 0
        lines.append(f"    Gesamt & {{--}} & {{{int(round(fn_all))}}} & {{{int(round(mn_all))}}} & {f_none:.1f} & {f_cog:.1f} & {compr:.1f} \\\\")

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    write_tex_table('equalizing_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
