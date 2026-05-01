#!/usr/bin/env python3
"""
47 — Multiplication-Model Ratio CI (RQ2, Befund 9 / Tab. 7.25)

Reproduces the ratio

    R = ΔAuth(Checkout) / ΔAuth(addCartItem)    (Cognito, Baseline, P50)

across the six configurations listed in the thesis footnote at evaluation.tex
line 1656 (FaaS 512, FaaS 1024, MS/L_static, MS/XL, Mono/L, Mono/XL). Reports
mean, standard deviation, coefficient of variation, and the 95 %
Student-t confidence interval over the six Ratios.

The existing script 20 (multiplication_model_validation) computes per-endpoint
Δ only for FaaS and does not emit the R summary. This script adds the missing
reproducible link between the data and the value cited in Befund 9 and
Tab. 7.25 ('R = 3.19 ± 0.15, CV = 4.8%').

Outputs:
  multiplication_ratio_ci.csv
  multiplication_ratio_summary.tex
"""

import sys
import pandas as pd
import numpy as np
from scipy import stats as sp_stats

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

# Configurations and the exact experiment pairs named in the thesis footnote
# (evaluation.tex line 1656).  Each pair is (architecture_key, config_label,
# none_experiment_id, cognito_experiment_id, addCartItem_endpoint,
# checkout_endpoint).
#
# Endpoint names differ between FaaS and Container deployments:
#   FaaS:      /frontend/addCartItem, /frontend/checkout
#   Container: /addCartItem,          /checkout
CONFIGS = [
    # (arch_label, none_exp, cognito_exp, addcart_ep,           checkout_ep)
    ('FaaS 512',        87,  10,  '/frontend/addCartItem', '/frontend/checkout'),
    ('FaaS 1024',       42, 120,  '/frontend/addCartItem', '/frontend/checkout'),
    ('MS/L (static)',  142, 143,  '/addCartItem',          '/checkout'),
    ('MS/XL',           64,  65,  '/addCartItem',          '/checkout'),
    ('Mono/L',          30,  36,  '/addCartItem',          '/checkout'),
    ('Mono/XL',         62,  70,  '/addCartItem',          '/checkout'),
]


def _endpoint_p50(experiment_id: int, endpoint: str) -> float:
    """Return Baseline-phase P50 of successful requests to `endpoint`.

    Returns NaN when the experiment / endpoint is absent or has too few
    successful requests.
    """
    df = query_df(f"""
        SELECT percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p50,
               COUNT(*) FILTER (WHERE NOT r.is_error) AS n_ok
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE e.id = {experiment_id}
          AND {EXCLUDE_SQL}
          AND r.phase_name = 'Baseline'
          AND r.endpoint = '{endpoint}'
    """)
    if df.empty:
        return float('nan')
    row = df.iloc[0]
    if pd.isna(row['n_ok']) or int(row['n_ok']) < 50:
        return float('nan')
    return float(row['p50'])


def main():
    print('=' * 70)
    print('47 — MULTIPLICATION-MODEL RATIO CI (Befund 9, Tab. 7.25)')
    print('=' * 70)

    rows = []
    for label, none_eid, cog_eid, addcart_ep, checkout_ep in CONFIGS:
        none_add = _endpoint_p50(none_eid, addcart_ep)
        cog_add = _endpoint_p50(cog_eid, addcart_ep)
        none_co = _endpoint_p50(none_eid, checkout_ep)
        cog_co = _endpoint_p50(cog_eid, checkout_ep)

        delta_add = cog_add - none_add
        delta_co = cog_co - none_co
        ratio = delta_co / delta_add if delta_add > 0 else float('nan')

        rows.append({
            'configuration': label,
            'none_exp': none_eid,
            'cognito_exp': cog_eid,
            'none_p50_addCartItem': none_add,
            'cog_p50_addCartItem': cog_add,
            'delta_addCartItem': delta_add,
            'none_p50_checkout': none_co,
            'cog_p50_checkout': cog_co,
            'delta_checkout': delta_co,
            'ratio': ratio,
        })

    df = pd.DataFrame(rows)
    csv_path = f'{PLOT_DIR}/multiplication_ratio_ci.csv'
    df.to_csv(csv_path, index=False)
    print(f'Saved: {csv_path}\n')

    print(f'{"Configuration":<18s} {"Δ addCart":>10s} {"Δ Checkout":>12s} {"Ratio":>8s}')
    for _, r in df.iterrows():
        if pd.isna(r['ratio']):
            print(f'  {r["configuration"]:<16s} {r["delta_addCartItem"]:>10.1f} '
                  f'{r["delta_checkout"]:>12.1f} {"n/a":>8s}')
        else:
            print(f'  {r["configuration"]:<16s} {r["delta_addCartItem"]:>10.1f} '
                  f'{r["delta_checkout"]:>12.1f} {r["ratio"]:>8.2f}')

    ratios = df['ratio'].dropna().to_numpy(dtype=float)
    n = len(ratios)
    if n < 2:
        print('\nInsufficient valid pairs for a CI (need >= 2).')
        return

    mean = float(np.mean(ratios))
    std = float(np.std(ratios, ddof=1))
    cv = std / mean if mean != 0 else float('nan')
    se = std / np.sqrt(n)
    t_crit = float(sp_stats.t.ppf(0.975, df=n - 1))
    ci_low = mean - t_crit * se
    ci_high = mean + t_crit * se

    print('\n--- SUMMARY ---')
    print(f'  n         = {n}')
    print(f'  mean R    = {mean:.2f}')
    print(f'  std       = {std:.2f}')
    print(f'  CV        = {cv * 100:.1f}%')
    print(f'  t_{{0.025;{n-1}}} = {t_crit:.3f}')
    print(f'  95%-t-CI  = [{ci_low:.2f}, {ci_high:.2f}]')

    # Emit a one-line LaTeX macro bundle so the thesis number can be \input{}
    tex_path = f'{PLOT_DIR}/multiplication_ratio_summary.tex'
    with open(tex_path, 'w') as f:
        f.write('% Auto-generated by 47_multiplication_ratio_ci.py — do not edit.\n')
        f.write(f'\\newcommand{{\\RatioMean}}{{{mean:.2f}}}\n')
        f.write(f'\\newcommand{{\\RatioStd}}{{{std:.2f}}}\n')
        f.write(f'\\newcommand{{\\RatioCV}}{{{cv * 100:.1f}\\%}}\n')
        f.write(f'\\newcommand{{\\RatioN}}{{{n}}}\n')
        f.write(f'\\newcommand{{\\RatioCIlow}}{{{ci_low:.2f}}}\n')
        f.write(f'\\newcommand{{\\RatioCIhigh}}{{{ci_high:.2f}}}\n')
    print(f'\nSaved: {tex_path}')


if __name__ == '__main__':
    main()
