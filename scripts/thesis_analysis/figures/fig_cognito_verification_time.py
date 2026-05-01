#!/usr/bin/env python3
"""Generate cognito_pure_verification_time.pdf for fig:cognito-verification-time.

Grouped bar chart showing ΔHandler duration (Cognito − None) at leaf
functions in FaaS 512MB Baseline phase. Only functions with P50 > 0.1ms
are plotted (sub-millisecond functions are below measurement resolution).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

LEAF_FUNCTIONS = (
    'payment', 'cartkvstorage', 'listrecommendations',
    'currency', 'email', 'getads', 'getproduct',
    'listproducts', 'shipmentquote', 'shiporder', 'supportedcurrencies',
)
FUNC_DISPLAY = {
    'payment': 'Payment', 'cartkvstorage': 'CartKVStorage',
    'listrecommendations': 'ListRecommend.', 'currency': 'Currency',
    'email': 'Email', 'getads': 'GetAds', 'getproduct': 'GetProduct',
    'listproducts': 'ListProducts', 'shipmentquote': 'ShipmentQuote',
    'shiporder': 'ShipOrder', 'supportedcurrencies': 'SupportedCurr.',
}
PCTL_LABELS = ['P50', 'P75', 'P90', 'P99']


def main():
    funcs_sql = ','.join(f"'{f}'" for f in LEAF_FUNCTIONS)
    df = query_df(f"""
        SELECT e.id AS experiment_id, e.auth_strategy,
               h.function_name, h.duration_ms
        FROM experiments e
        JOIN handler_events h ON h.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = 'faas'
          AND e.ram_in_mb = 512
          AND e.auth_strategy IN ('none', 'service-integrated')
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND h.function_name IN ({funcs_sql})
          AND h.duration_ms IS NOT NULL
          AND h.phase_name = 'Baseline'
    """)
    if df.empty:
        print('No handler_events data'); return

    rows = []
    for func in LEAF_FUNCTIONS:
        fd = df[df['function_name'] == func]
        none_d = fd[fd['auth_strategy'] == 'none']['duration_ms']
        cog_d = fd[fd['auth_strategy'] == 'service-integrated']['duration_ms']
        if len(none_d) < 20 or len(cog_d) < 20:
            continue
        row = {'function': func, 'display_name': FUNC_DISPLAY.get(func, func)}
        for pctl, label in zip([0.50, 0.75, 0.90, 0.99], ['delta_p50', 'delta_p75', 'delta_p90', 'delta_p99']):
            row[label] = cog_d.quantile(pctl) - none_d.quantile(pctl)
        row['none_p50'] = none_d.quantile(0.50)
        row['cognito_p50'] = cog_d.quantile(0.50)
        rows.append(row)

    result_df = pd.DataFrame(rows)
    measurable = result_df[
        (result_df['none_p50'] > 0.1) | (result_df['cognito_p50'] > 0.1)
    ]
    if measurable.empty:
        print('No measurable functions'); return

    m_df = measurable.sort_values('delta_p50', ascending=False)
    m_funcs = m_df['display_name'].tolist()
    n_m = len(m_funcs)
    n_pctls = len(PCTL_LABELS)
    x = np.arange(n_m)
    width = 0.8 / n_pctls
    pctl_colors = ['#90CAF9', '#42A5F5', '#1E88E5', '#0D47A1']

    fig, ax = plt.subplots(figsize=(10, 7))
    for i, (pctl_col, pctl_label, color) in enumerate(
            zip(['delta_p50', 'delta_p75', 'delta_p90', 'delta_p99'],
                PCTL_LABELS, pctl_colors)):
        vals = m_df[pctl_col].values
        offset = (i - n_pctls / 2 + 0.5) * width
        bars = ax.bar(x + offset, vals, width, label=pctl_label, color=color, alpha=0.9)
        for bar, val in zip(bars, vals):
            ypos = bar.get_height() + 0.5 if val >= 0 else bar.get_height() - 0.5
            va = 'bottom' if val >= 0 else 'top'
            ax.text(bar.get_x() + bar.get_width() / 2, ypos,
                    f'{val:+.1f}', ha='center', va=va, fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(m_funcs, fontsize=11, rotation=30, ha='right')
    ax.set_ylabel('Delta Handler Duration (ms)\nCognito − None', fontsize=12)
    ax.set_title('Pure Cognito Verification Overhead at Leaf Functions\n'
                 '(FaaS 512MB, Baseline, nur Funktionen mit P50 > 0,1 ms)',
                 fontsize=13, fontweight='bold')
    ax.legend(title='Percentile', fontsize=9, title_fontsize=10, loc='upper right')
    ax.grid(axis='y', alpha=0.3)
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.tick_params(labelsize=10)
    plt.tight_layout()
    path = f"{PLOT_DIR}/cognito_pure_verification_time.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
