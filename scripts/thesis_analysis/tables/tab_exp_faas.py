#!/usr/bin/env python3
"""Generate exp_faas_table.tex for tab:exp-faas."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import query_df, EXCLUDE_SQL, auth_label_detailed
from tables.tex_helpers import write_tex_table

RAM_TIERS = [256, 512, 1024, 1769]
STRATEGY_ORDER = [
    'None', 'Cognito', 'Manual (bcrypt)', 'Manual (argon2id)',
    'Edge', 'Edge-Sel.', 'None+CF',
]


def main():
    df = query_df(f"""
        SELECT e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, COUNT(*) AS n
        FROM experiments e
        WHERE e.architecture = 'faas' AND {EXCLUDE_SQL}
        GROUP BY e.auth_strategy, e.password_hash_algorithm, e.with_cloudfront, e.ram_in_mb
    """)
    df['auth_label'] = df.apply(lambda r: auth_label_detailed(r['auth_strategy'], r['algo'], r['with_cf']), axis=1)

    pivot = {}
    for _, row in df.iterrows():
        label = row['auth_label']
        ram = int(row['ram_in_mb'])
        if label not in pivot:
            pivot[label] = {}
        pivot[label][ram] = int(row['n'])

    lines = []
    lines.append(r'\begin{tabular}{@{}l rrrr r@{}}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Strategie} & \textbf{256\,MB} & \textbf{512\,MB} & \textbf{1024\,MB} & \textbf{1769\,MB} & \textbf{Summe} \\')
    lines.append(r'\midrule')

    grand_total = {r: 0 for r in RAM_TIERS}
    for strat in STRATEGY_ORDER:
        if strat not in pivot:
            continue
        vals = []
        row_sum = 0
        for ram in RAM_TIERS:
            n = pivot[strat].get(ram, 0)
            vals.append(str(n) if n > 0 else '--')
            row_sum += n
            grand_total[ram] += n
        lines.append(f"    {strat:30s} & {' & '.join(vals)} & {row_sum} \\\\")

    lines.append(r'\midrule')
    totals = [str(grand_total[r]) for r in RAM_TIERS]
    lines.append(f"    \\textbf{{Summe}} & {' & '.join(totals)} & \\textbf{{{sum(grand_total.values())}}} \\\\")
    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    write_tex_table('exp_faas_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
