#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db_connection import query_df
from tables.tex_helpers import write_tex_table, fmt_ms

EXP_ID = 17
PHASES = [
    ('Baseline', 'Baseline'),
    ('Morning rush', 'Morgenansturm'),
    ('Stabilization', 'Stabilisierung'),
]


def _interpret(abort_rate):
    if abort_rate < 1.0:
        return 'Valide Messung'
    if abort_rate < 50.0:
        return 'Eingeschr\\"ankt valide'
    return 'Nicht aussagekr\\"aftig'


def main():
    df = query_df(f'''
        SELECT r.phase_name, COUNT(*) AS total,
               SUM(CASE WHEN r.is_timeout THEN 1 ELSE 0 END) AS timeouts,
               PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99
        FROM requests r
        WHERE r.experiment_id = {EXP_ID}
          AND r.phase_name IN ('Baseline', 'Morning rush', 'Stabilization')
        GROUP BY r.phase_name
    ''')
    phase_data = {row['phase_name']: row for _, row in df.iterrows()}

    L = []
    L.append(r'\begin{tabular}{@{}lrrr@{}}')
    L.append(r'\toprule')
    L.append(r'\textbf{Phase} & \textbf{P99 Latenz} & '
             r'\textbf{Szenario-Abbruchrate} & \textbf{Interpretation} \\')
    L.append(r'\midrule')

    for phase_en, phase_de in PHASES:
        row = phase_data.get(phase_en)
        if row is None:
            continue
        p99 = row['p99']
        total = int(row['total'])
        timeouts = int(row['timeouts'])
        abort_rate = (timeouts / total * 100) if total > 0 else 0.0
        interp = _interpret(abort_rate)

        p99_str = fmt_ms(p99) + '~ms'
        if abort_rate < 0.5:
            rate_str = r'0\%'
        else:
            rate_str = f'{abort_rate:.1f}'.replace('.', '{,}') + r'\,\%'
            if abort_rate > 50:
                rate_str = r'\textbf{' + rate_str + '}'

        L.append(f'{phase_de} & {p99_str} & {rate_str} & {interp} \\\\')

    L.append(r'\bottomrule')
    L.append(r'\end{tabular}')
    write_tex_table('latency_comparison_limitation_table.tex',
                    '\n'.join(L) + '\n')


if __name__ == '__main__':
    main()
