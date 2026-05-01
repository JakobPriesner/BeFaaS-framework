#!/usr/bin/env python3
"""Generate cpu_saturation_combined.pdf for fig:cpu-saturation.

2-panel side-by-side: Microservices frontend-service | Monolith.
Grouped bars (mean CPU%) with p95 cap markers for None vs Manual (bcrypt)
vs Manual (argon2id) during active load phases.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import warnings
warnings.filterwarnings('ignore')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS_DETAILED

ACTIVE_PHASES = ('Morning rush', 'Stabilization', 'Flash Crowd')
HW_ORDER = ['S', 'M', 'L', 'XL']
HW_LABEL = {
    ('microservices', 0.25): 'S', ('microservices', 0.5): 'M',
    ('microservices', 1.0): 'L', ('microservices', 4.0): 'XL',
    ('monolith', 0.25): 'S', ('monolith', 0.5): 'M',
    ('monolith', 1.0): 'L', ('monolith', 4.0): 'XL',
}
AUTH_ORDER = ['None', 'Manual (bcrypt)', 'Manual (argon2id)']
AUTH_COLOR = {
    'None': AUTH_COLORS_DETAILED['None'],
    'Manual (bcrypt)': AUTH_COLORS_DETAILED['Manual (bcrypt)'],
    'Manual (argon2id)': AUTH_COLORS_DETAILED['Manual (argon2id)'],
}


def load_raw():
    phases_sql = ','.join(f"'{p}'" for p in ACTIVE_PHASES)
    sql = f"""
    WITH phase_bounds AS (
        SELECT experiment_id, phase_name,
               to_timestamp(MIN(timestamp_ms)/1000.0) AS ph_start,
               to_timestamp(MAX(timestamp_ms)/1000.0) AS ph_end
        FROM requests
        GROUP BY experiment_id, phase_name
    )
    SELECT e.id AS exp_id,
           e.architecture,
           e.auth_strategy,
           COALESCE(e.password_hash_algorithm, 'default') AS algo,
           e.cpu_in_vcpu,
           m.service_name,
           m.cpu_percent
    FROM experiments e
    JOIN phase_bounds pb ON pb.experiment_id = e.id
    JOIN metrics_ecs  m  ON m.experiment_id = e.id
                        AND m.timestamp BETWEEN pb.ph_start AND pb.ph_end
    WHERE {EXCLUDE_SQL}
      AND e.architecture IN ('microservices','monolith')
      AND e.auth_strategy IN ('none', 'service-integrated-manual')
      AND m.cpu_percent IS NOT NULL
      AND pb.phase_name IN ({phases_sql})
    """
    df = query_df(sql)
    df['auth_label'] = df.apply(
        lambda r: 'None' if r['auth_strategy'] == 'none'
        else f"Manual ({r['algo']})", axis=1)
    df['hw'] = df.apply(
        lambda r: HW_LABEL.get((r['architecture'], float(r['cpu_in_vcpu'])),
                               f"{r['cpu_in_vcpu']}vCPU"), axis=1)
    return df


def aggregate(df):
    return df.groupby(
        ['exp_id', 'architecture', 'auth_label', 'hw', 'service_name']
    ).agg(
        cpu_mean=('cpu_percent', 'mean'),
        cpu_p95=('cpu_percent', lambda x: x.quantile(0.95)),
        cpu_max=('cpu_percent', 'max'),
    ).reset_index()


def summarise(per_exp_svc):
    ms = per_exp_svc[(per_exp_svc['architecture'] == 'microservices') &
                     (per_exp_svc['service_name'] == 'frontend-service')].copy()
    mono = per_exp_svc[per_exp_svc['architecture'] == 'monolith'].copy()

    def agg(block):
        return block.groupby(['architecture', 'hw', 'auth_label']).agg(
            cpu_mean=('cpu_mean', 'mean'),
            cpu_p95=('cpu_p95', 'mean'),
            cpu_max=('cpu_max', 'mean'),
            n_exp=('exp_id', 'nunique'),
        ).round(1).reset_index()

    return pd.concat([agg(ms), agg(mono)], ignore_index=True)


def main():
    raw = load_raw()
    if raw.empty:
        print('No CPU saturation data'); return
    per_exp_svc = aggregate(raw)
    summary = summarise(per_exp_svc)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    titles = {
        'microservices': 'Microservices — frontend-service',
        'monolith':      'Monolith',
    }
    for ax, arch in zip(axes, ['microservices', 'monolith']):
        sub = summary[summary['architecture'] == arch]
        hws_present = [h for h in HW_ORDER if h in sub['hw'].unique()]
        n_auth = len(AUTH_ORDER)
        bar_w = 0.25
        x = np.arange(len(hws_present))
        for i, auth in enumerate(AUTH_ORDER):
            means, p95s = [], []
            for hw in hws_present:
                row = sub[(sub['hw'] == hw) & (sub['auth_label'] == auth)]
                means.append(row['cpu_mean'].iloc[0] if len(row) else np.nan)
                p95s.append(row['cpu_p95'].iloc[0] if len(row) else np.nan)
            pos = x + (i - (n_auth - 1) / 2) * bar_w
            ax.bar(pos, means, bar_w, label=auth, color=AUTH_COLOR[auth],
                   edgecolor='black', linewidth=0.4)
            ax.scatter(pos, p95s, marker='_', color='black', s=80,
                       linewidths=1.5, zorder=4)
            for xi, m in zip(pos, means):
                if np.isnan(m):
                    continue
                ax.text(xi, m + 1.5, f"{m:.0f}", ha='center', va='bottom',
                        fontsize=7)

        ax.axhline(100, color='gray', linestyle=':', linewidth=0.8, alpha=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(hws_present)
        ax.set_xlabel('Hardware-Tier')
        ax.set_ylim(0, 110)
        ax.set_title(titles[arch])
        ax.grid(axis='y', alpha=0.3)

    axes[0].set_ylabel('CPU-Auslastung (%) während Lastphasen')
    axes[0].legend(loc='upper right', fontsize=8, framealpha=0.9)
    fig.suptitle('CPU-Konkurrenz durch Passwort-Hashing (Mittelwert · schwarzer Strich = p95)',
                 fontsize=11)
    plt.tight_layout(rect=(0, 0.02, 1, 0.96))
    path = f"{PLOT_DIR}/cpu_saturation_combined.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
