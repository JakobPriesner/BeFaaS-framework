#!/usr/bin/env python3
"""Generate model_fit.pdf for fig:model-fit.

ΔAuth P50 vs function call depth for FaaS endpoints, with linear
regression per auth strategy. Validates the k(arch) multiplication model.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
}

ENDPOINT_DEPTH = {
    '/frontend/setUser': ('login', 1),
    '/frontend/addCartItem': ('addCartItem', 2),
    '/frontend/cart': ('cart', 2),
    '/frontend': ('homepage', 3),
    '/frontend/checkout': ('checkout', 6),
}


def main():
    endpoints_sql = ','.join(f"'{e}'" for e in ENDPOINT_DEPTH.keys())
    e2e = query_df(f"""
        SELECT
            e.auth_strategy,
            r.endpoint,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = 'faas'
          AND r.phase_name = 'Baseline'
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND r.endpoint IN ({endpoints_sql})
        GROUP BY e.auth_strategy, r.endpoint
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)
    if e2e.empty:
        print('No data'); return

    e2e['p50'] = e2e['p50'].astype(float)

    rows = []
    for ep, (name, depth) in ENDPOINT_DEPTH.items():
        none_data = e2e[(e2e['auth_strategy'] == 'none') & (e2e['endpoint'] == ep)]
        if none_data.empty:
            continue
        none_p50 = none_data['p50'].mean()

        for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
            auth_data = e2e[(e2e['auth_strategy'] == auth) & (e2e['endpoint'] == ep)]
            if auth_data.empty:
                continue
            delta = auth_data['p50'].mean() - none_p50
            rows.append({
                'endpoint': name, 'depth': depth,
                'auth': AUTH_SHORT.get(auth, auth),
                'delta_p50': delta,
            })

    if not rows:
        print('No paired data'); return
    e2e_df = pd.DataFrame(rows)

    colors = {'Cognito': '#3498db', 'Manual': '#e74c3c', 'Edge': '#2ecc71'}

    fig, ax = plt.subplots(figsize=(10, 7))
    for auth in e2e_df['auth'].unique():
        auth_data = e2e_df[e2e_df['auth'] == auth].sort_values('depth')
        ax.plot(auth_data['depth'], auth_data['delta_p50'], 'o-',
                label=auth, color=colors.get(auth, '#999'),
                linewidth=2, markersize=10)

        for _, r in auth_data.iterrows():
            ax.annotate(f"{r['endpoint']}\n({r['delta_p50']:+.0f}ms)",
                        (r['depth'], r['delta_p50']),
                        textcoords='offset points', xytext=(8, 5), fontsize=7)

        if len(auth_data) >= 3:
            slope, intercept, r_val, p_val, _ = sp_stats.linregress(
                auth_data['depth'], auth_data['delta_p50'])
            x_fit = np.linspace(auth_data['depth'].min(), auth_data['depth'].max(), 100)
            ax.plot(x_fit, slope * x_fit + intercept, '--',
                    color=colors.get(auth, '#999'), alpha=0.4)
            ax.text(auth_data['depth'].max() + 0.1,
                    slope * auth_data['depth'].max() + intercept,
                    f'R²={r_val**2:.2f}\nslope={slope:.0f}ms/depth',
                    fontsize=7, color=colors.get(auth, '#999'))

    ax.set_xlabel('Function Call Depth (number of functions in chain)')
    ax.set_ylabel('ΔAuth P50 (ms)')
    ax.set_title('Multiplication Model Validation: ΔAuth vs Call Depth\n'
                 '(FaaS, Baseline phase, excluding argon2id)',
                 fontweight='bold')
    ax.legend()
    ax.grid(alpha=0.3)
    ax.axhline(y=0, color='black', linewidth=0.5)

    plt.tight_layout()
    path = f"{PLOT_DIR}/model_fit.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
