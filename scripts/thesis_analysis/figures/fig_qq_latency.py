#!/usr/bin/env python3
"""Generate qq_latency.pdf for fig:qq-latency.

Combined QQ-plot panel (1x3): FaaS/512 None, FaaS/512 Cognito, MS/L Cognito.
Assesses normality of auth-only endpoint latencies during Baseline phase.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as sp_stats
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
}

PROTECTED_FAAS = ('/frontend/setUser', '/frontend/addCartItem',
                  '/frontend/cart', '/frontend/checkout')
PROTECTED_CONTAINER = ('/setUser', '/addCartItem', '/cart', '/checkout')


def get_protected_sql(arch):
    eps = PROTECTED_FAAS if arch == 'faas' else PROTECTED_CONTAINER
    return ','.join(f"'{e}'" for e in eps)


def find_experiment(arch, ram, cpu, auth_strategy):
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"
    df = query_df(f"""
        SELECT e.id FROM experiments e
        WHERE {EXCLUDE_SQL} AND e.architecture = '{arch}'
          AND e.ram_in_mb = {ram} {cpu_clause}
          AND e.auth_strategy = '{auth_strategy}'
        ORDER BY e.id
    """)
    if df.empty:
        return None
    for _, row in df.iterrows():
        eid = row['id']
        count = query_df(f"SELECT COUNT(*) AS n FROM requests WHERE experiment_id = {eid}")
        if not count.empty and count.iloc[0]['n'] > 1000:
            return eid
    return df.iloc[0]['id']


def load_latencies(experiment_id, arch, max_n=5000):
    eps = get_protected_sql(arch)
    df = query_df(f"""
        SELECT r.latency_ms FROM requests r
        WHERE r.experiment_id = {experiment_id} AND NOT r.is_error
          AND r.endpoint IN ({eps}) AND r.phase_name = 'Baseline'
        ORDER BY RANDOM() LIMIT {max_n}
    """)
    return df


def main():
    qq_configs = [
        ('faas', 512, 0, 'none', 'FaaS/512 None'),
        ('faas', 512, 0, 'service-integrated', 'FaaS/512 Cognito'),
        ('microservices', 2048, 1.0, 'service-integrated', 'MS/L Cognito'),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(18, 7))

    for ax, (arch, ram, cpu, auth, title) in zip(axes, qq_configs):
        eid = find_experiment(arch, ram, cpu, auth)
        if eid is None:
            ax.set_title(f'{title} — no data')
            continue
        df = load_latencies(eid, arch)
        if df.empty:
            continue
        lat = df['latency_ms'].values
        (osm, osr), (slope, intercept, r) = sp_stats.probplot(lat, dist='norm')
        auth_short = AUTH_SHORT.get(auth, auth)
        scatter_color = AUTH_COLORS.get(auth_short, '#3498db')
        ax.scatter(osm, osr, s=3, alpha=0.5, color=scatter_color)
        x_line = np.array([osm.min(), osm.max()])
        ax.plot(x_line, slope * x_line + intercept, 'r-', linewidth=1.5,
                label=f'R² = {r**2:.3f}')
        subsample = np.random.default_rng(42).choice(lat, size=min(5000, len(lat)), replace=False)
        _, sw_p = sp_stats.shapiro(subsample)
        ax.set_xlabel('Theoretische Quantile (Normal)', fontsize=11)
        ax.set_ylabel('Stichproben-Quantile (ms)', fontsize=11)
        ax.set_title(f'{title}\nShapiro-Wilk p = {sw_p:.2e}', fontsize=12)
        ax.legend(fontsize=10)
        ax.tick_params(labelsize=9)
        ax.grid(alpha=0.3)

    fig.suptitle('QQ-Plots: Latenzverteilung vs. Normalverteilung (Auth-Only, Baseline)',
                 fontweight='bold', fontsize=13)
    plt.tight_layout()
    path = f"{PLOT_DIR}/qq_latency.pdf"
    fig.savefig(path, bbox_inches='tight', dpi=300)
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
