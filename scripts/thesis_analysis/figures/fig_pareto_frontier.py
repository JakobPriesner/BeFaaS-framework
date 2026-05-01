#!/usr/bin/env python3
"""Generate pareto_frontier.pdf for fig:pareto-frontier.

2-panel multi-objective decision space: (1) ΔAuth P99 vs Security Score,
(2) ΔAuth P99 vs Token Exposure. Colors = architecture, markers = auth.
Excludes argon2id.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, ARCH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
}
AUTH_MARKERS = {'Cognito': 's', 'Manual': '^', 'Edge': 'D'}

SECURITY_SCORES = {
    'none': 0, 'edge': 3,
    'service-integrated': 4, 'service-integrated-manual': 4,
}
TOKEN_EXPOSURE = {
    'none': 0, 'edge': 1,
    'service-integrated': {'faas': 6, 'microservices': 5, 'monolith': 1},
    'service-integrated-manual': {'faas': 6, 'microservices': 5, 'monolith': 1},
}


def main():
    latency = query_df(f"""
        SELECT
            e.architecture, e.auth_strategy,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.phase_name = 'Baseline'
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.architecture, e.auth_strategy, e.ram_in_mb, cpu
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 1000
    """)
    if latency.empty:
        print('No data'); return

    latency['p99'] = latency['p99'].astype(float)

    rows = []
    for (arch, ram), grp in latency.groupby(['architecture', 'ram_in_mb']):
        none_data = grp[grp['auth_strategy'] == 'none']
        if none_data.empty:
            continue
        none_p99 = none_data['p99'].mean()

        for _, r in grp.iterrows():
            if r['auth_strategy'] == 'none':
                continue
            auth_label = AUTH_SHORT.get(r['auth_strategy'], r['auth_strategy'])
            delta_p99 = r['p99'] - none_p99
            security = SECURITY_SCORES.get(r['auth_strategy'], 0)
            exposure = TOKEN_EXPOSURE.get(r['auth_strategy'], 0)
            if isinstance(exposure, dict):
                exposure = exposure.get(arch, 3)

            rows.append({
                'architecture': arch, 'auth': auth_label,
                'delta_p99': delta_p99,
                'security_score': security,
                'token_exposure': exposure,
            })

    if not rows:
        print('No auth data'); return
    auth_configs = pd.DataFrame(rows)

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    ax = axes[0]
    for _, r in auth_configs.iterrows():
        color = ARCH_COLORS.get(r['architecture'], '#999')
        marker = AUTH_MARKERS.get(r['auth'], 'o')
        ax.scatter(r['delta_p99'], r['security_score'] + np.random.uniform(-0.15, 0.15),
                   c=color, marker=marker, s=100, alpha=0.75,
                   edgecolors='black', linewidths=0.5)
    ax.set_xlabel('ΔAuth P99 (ms) — lower is better →')
    ax.set_ylabel('Security Score — higher is better →')
    ax.set_title('Auth Overhead vs Security', fontweight='bold')
    ax.set_yticks([0, 1, 2, 3, 4])
    ax.set_yticklabels(['0 (None)', '1', '2', '3 (Edge)', '4 (Cognito/Manual)'])
    ax.grid(alpha=0.3)
    ax.axvline(x=0, color='black', linewidth=0.5, alpha=0.3)

    ax = axes[1]
    for _, r in auth_configs.iterrows():
        color = ARCH_COLORS.get(r['architecture'], '#999')
        marker = AUTH_MARKERS.get(r['auth'], 'o')
        ax.scatter(r['delta_p99'], r['token_exposure'] + np.random.uniform(-0.15, 0.15),
                   c=color, marker=marker, s=100, alpha=0.75,
                   edgecolors='black', linewidths=0.5)
    ax.set_xlabel('ΔAuth P99 (ms) — lower is better →')
    ax.set_ylabel('Token Exposure (components) — lower is better →')
    ax.set_title('Auth Overhead vs Token Exposure', fontweight='bold')
    ax.grid(alpha=0.3)
    ax.axvline(x=0, color='black', linewidth=0.5, alpha=0.3)

    arch_legend = [Line2D([0], [0], marker='o', color='w', markerfacecolor=c,
                          markersize=10, label=a) for a, c in ARCH_COLORS.items()]
    auth_legend = [Line2D([0], [0], marker=m, color='w', markerfacecolor='gray',
                          markersize=10, label=a) for a, m in AUTH_MARKERS.items()]
    for a in axes:
        a.legend(handles=arch_legend + auth_legend, fontsize=8, ncol=2)

    fig.suptitle('Multi-Objective Decision Space\n'
                 '(Ideal: low overhead, high security/low exposure)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/pareto_frontier.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
