#!/usr/bin/env python3
"""Generate exp_ms_table.tex for tab:exp-ms."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df, EXCLUDE_SQL
from tables.tex_helpers import write_tex_table

STRATEGY_ORDER = [
    'None', 'Cognito', 'Manual (bcrypt/HS256)', 'Manual (argon2id/EdDSA)',
    'Edge (Lambda@Edge)', 'Edge-Selective', 'None + CloudFront',
    'Cognito + CloudFront',
]
HW_COLUMNS = [0.25, 0.5, 1.0, 4.0]
HW_HEADERS = ['S', 'M', 'L', 'XL']


def _strategy_label(row):
    """Map a DB row to the display label used in the table."""
    auth, algo = row['auth_strategy'], row.get('algo', '')
    with_cf = row.get('with_cf', False)
    if auth == 'none' and with_cf:
        return 'None + CloudFront'
    if auth == 'none':
        return 'None'
    if auth == 'service-integrated' and not with_cf:
        return 'Cognito'
    if auth == 'service-integrated' and with_cf:
        return 'Cognito + CloudFront'
    if auth == 'service-integrated-manual':
        if with_cf:
            if algo and 'argon2id' in str(algo):
                return 'Manual (argon2id/EdDSA) + CF'
            return 'Manual (bcrypt/HS256) + CF'
        return ('Manual (argon2id/EdDSA)' if algo and 'argon2id' in str(algo)
                else 'Manual (bcrypt/HS256)')
    if auth == 'edge':
        return 'Edge (Lambda@Edge)'
    if auth == 'edge-selective':
        return 'Edge-Selective'
    return auth


def main():
    df = query_df(f"""
        SELECT e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               COALESCE(e.cpu_in_vcpu, 0) AS cpu,
               COUNT(*) AS n
        FROM experiments e
        WHERE e.architecture = 'microservices' AND {EXCLUDE_SQL}
        GROUP BY e.auth_strategy, algo, with_cf, cpu
    """)
    counts = {}
    for _, row in df.iterrows():
        label = _strategy_label(row)
        hw_val = float(row['cpu'])
        counts[(label, hw_val)] = counts.get(
            (label, hw_val), 0) + int(row['n'])

    L = []
    L.append(r'\begin{tabular}{@{}l rrrr r@{}}')
    L.append(r'\toprule')
    hw_hdr = ' & '.join(f'\\textbf{{{h}}}' for h in HW_HEADERS)
    L.append(f'\\textbf{{Strategie}} & {hw_hdr} & \\textbf{{Summe}} \\\\')
    L.append(r'\midrule')
    grand = {r: 0 for r in HW_COLUMNS}
    gs = 0
    for strat in STRATEGY_ORDER:
        cells, rs = [], 0
        for hw in HW_COLUMNS:
            n = counts.get((strat, hw), 0)
            cells.append('--' if n == 0 else str(n))
            rs += n
            grand[hw] += n
        gs += rs
        L.append(f'{strat:30s} & {" & ".join(cells)} & {rs} \\\\')
    L.append(r'\midrule')
    tots = ' & '.join(str(grand[r]) for r in HW_COLUMNS)
    L.append(f'\\textbf{{Summe}} & {tots} & \\textbf{{{gs}}} \\\\')
    L.append(r'\bottomrule')
    L.append(r'\end{tabular}')
    write_tex_table('exp_ms_table.tex', '\n'.join(L) + '\n')


if __name__ == '__main__':
    main()
