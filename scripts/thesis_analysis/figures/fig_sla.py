#!/usr/bin/env python3
"""Generate sla_compliance.pdf for fig:sla.

1×3 bar chart showing SLA compliance (% requests under 500ms) per
architecture and auth strategy for Baseline, Flash Crowd, and Step Down
phases. Reference lines at 99% and 95%. Excludes argon2id.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
}
SLA_TARGET = 500


def main():
    sla_data = query_df(f"""
        SELECT
            e.architecture, e.auth_strategy,
            r.phase_name,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS total,
            COUNT(*) FILTER (WHERE NOT r.is_error AND r.latency_ms < {SLA_TARGET}) AS under_sla
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.phase_name IN ('Baseline', 'Flash Crowd', 'Step Down')
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.architecture, e.auth_strategy, r.phase_name
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 1000
    """)
    if sla_data.empty:
        print('No data'); return

    sla_data['pct'] = sla_data['under_sla'] / sla_data['total'] * 100

    archs = ['faas', 'microservices', 'monolith']
    auth_order = ['none', 'service-integrated', 'edge']

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, phase in zip(axes, ['Baseline', 'Flash Crowd', 'Step Down']):
        phase_data = sla_data[sla_data['phase_name'] == phase]
        x = np.arange(len(archs))
        width = 0.25

        for j, auth in enumerate(auth_order):
            vals = []
            for arch in archs:
                match = phase_data[(phase_data['architecture'] == arch) &
                                   (phase_data['auth_strategy'] == auth)]
                vals.append(match.iloc[0]['pct'] if not match.empty else 0)
            offset = (j - 1) * width
            ax.bar(x + offset, vals, width, label=AUTH_SHORT.get(auth, auth), alpha=0.85)

        ax.set_xticks(x)
        ax.set_xticklabels(archs)
        ax.set_ylabel(f'% Requests < {SLA_TARGET}ms')
        ax.set_title(f'{phase}', fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)
        ax.set_ylim(0, 105)
        ax.axhline(y=99, color='green', linestyle='--', alpha=0.3)
        ax.axhline(y=95, color='orange', linestyle='--', alpha=0.3)

    fig.suptitle(f'SLA Compliance: % Requests Under {SLA_TARGET}ms by Phase\n'
                 f'(Green: 99%, Orange: 95%)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/sla_compliance.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
