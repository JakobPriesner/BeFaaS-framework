#!/usr/bin/env python3
"""Generate cognito_trimodal_table.tex for tab:cognito-trimodal."""
import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db_connection import query_df, EXCLUDE_SQL
from tables.tex_helpers import write_tex_table

MODES = [
    ('Gecachtes Token', 50, 100, 'Lokaler Cache-Hit'),
    ('Warme Revalidierung', 100, 200, 'Bestehende JWKS-Verbindung'),
    ('Kalter JWKS-Abruf', 200, 500, 'Neuer TLS-Handshake + Abruf'),
]


def main():
    faas_cognito_ids = query_df(f'''
        SELECT e.id FROM experiments e
        WHERE e.architecture = 'faas'
          AND e.auth_strategy = 'service-integrated'
          AND e.ram_in_mb = 512
          AND COALESCE(e.with_cloudfront, false) = false
          AND {EXCLUDE_SQL}
    ''')['id'].tolist()

    if not faas_cognito_ids:
        print('No FaaS/512/Cognito experiments found')
        return

    id_list = ','.join(str(i) for i in faas_cognito_ids)
    df = query_df(f'''
        SELECT r.latency_ms
        FROM requests r
        WHERE r.experiment_id IN ({id_list})
          AND r.phase_name = 'Baseline'
          AND r.auth_type = 'auth'
          AND NOT r.is_error
          AND r.endpoint IN (
              '/frontend/setUser', '/frontend/addCartItem',
              '/frontend/cart', '/frontend/checkout')
    ''')

    latencies = df['latency_ms'].values
    total = len(latencies)

    L = []
    L.append(r'\begin{tabular}{@{}l l S[table-format=2.1] l@{}}')
    L.append(r'\toprule')
    L.append(r'\textbf{Modus} & \textbf{Latenzband} & '
             r'{\textbf{Anteil (\%)}} & \textbf{Ursache} \\')
    L.append(r'\midrule')

    for mode_name, lo, hi, cause in MODES:
        count = np.sum((latencies >= lo) & (latencies < hi))
        pct = count / total * 100 if total > 0 else 0.0
        band = f"{lo}--{hi}\\,ms"
        L.append(f"    {mode_name} & {band} & {pct:.1f} & {cause} \\\\")

    L.append(r'\bottomrule')
    L.append(r'\end{tabular}')
    write_tex_table('cognito_trimodal_table.tex', '\n'.join(L) + '\n')


if __name__ == '__main__':
    main()
