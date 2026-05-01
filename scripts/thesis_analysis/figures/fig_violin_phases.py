#!/usr/bin/env python3
"""Generate violin_phases.pdf for fig:violin-phases.

Violin plots showing latency distribution per SCNAST phase for
FaaS/512 None and FaaS/512 Cognito (auth-only endpoints).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

PROTECTED_FAAS = ('/frontend/setUser', '/frontend/addCartItem',
                  '/frontend/cart', '/frontend/checkout')

PHASE_ORDER = ['Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
               'Flash Crowd', 'Step Down', 'Cool-down']


def find_experiment(auth_strategy):
    df = query_df(f"""
        SELECT e.id FROM experiments e
        WHERE {EXCLUDE_SQL} AND e.architecture = 'faas'
          AND e.ram_in_mb = 512 AND e.auth_strategy = '{auth_strategy}'
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


def load_latencies(experiment_id, phase, max_n=20000):
    eps = ','.join(f"'{e}'" for e in PROTECTED_FAAS)
    df = query_df(f"""
        SELECT r.latency_ms FROM requests r
        WHERE r.experiment_id = {experiment_id} AND NOT r.is_error
          AND r.endpoint IN ({eps}) AND r.phase_name = '{phase}'
        ORDER BY RANDOM() LIMIT {max_n}
    """)
    return df


def main():
    eid_none = find_experiment('none')
    eid_cognito = find_experiment('service-integrated')

    if not eid_none or not eid_cognito:
        print('Missing experiments for violin plot')
        return

    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

    for ax, eid, title in [
        (axes[0], eid_none, 'FaaS/512 — None'),
        (axes[1], eid_cognito, 'FaaS/512 — Cognito'),
    ]:
        phase_data = []
        phase_labels = []
        for phase in PHASE_ORDER:
            df = load_latencies(eid, phase)
            if not df.empty:
                lat = df['latency_ms'].values
                if len(lat) < 10:
                    continue
                clipped = lat[lat < np.percentile(lat, 99.5)]
                if len(clipped) > 0:
                    phase_data.append(clipped)
                    phase_labels.append(phase)

        if phase_data:
            parts = ax.violinplot(phase_data, positions=range(len(phase_data)),
                                  showmedians=True, showextrema=False)
            for pc in parts['bodies']:
                pc.set_alpha(0.6)
            parts['cmedians'].set_color('red')
            ax.set_xticks(range(len(phase_labels)))
            ax.set_xticklabels(phase_labels, rotation=30, ha='right', fontsize=9)
            ax.set_ylabel('Latency (ms)')
            ax.set_title(title, fontweight='bold')
            ax.grid(axis='y', alpha=0.3)

    fig.suptitle('Latency Distribution per SCNAST Phase — Auth-Only Endpoints',
                 fontweight='bold', fontsize=12)
    plt.tight_layout()
    path = f"{PLOT_DIR}/violin_phases.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
