#!/usr/bin/env python3
"""
44 -- CPU Saturation Under Auth Load

Quantifies the CPU-contention hypothesis: password hashing (bcrypt / argon2id)
competes with regular request handling for the limited CPU capacity of
container tasks. On small tiers this leads to saturation, which in turn
explains the high error rates observed for argon2id on MS/S (93%).

For each container experiment (microservices, monolith):
  - Determine the active-phase window (Morning rush + Stabilization + Flash
    Crowd) from the requests table.
  - Aggregate metrics_ecs.cpu_percent per service inside that window.
  - Compare None vs Manual (bcrypt) vs Manual (argon2id) per hardware tier.

Outputs (in PLOT_DIR):
  - cpu_saturation_table.csv       — aggregated mean/p95/max per (arch, hw, auth)
  - cpu_saturation_raw.csv         — per-experiment per-service aggregates
  - cpu_saturation_ms.pdf          — grouped bar chart for microservices frontend-service
  - cpu_saturation_monolith.pdf    — grouped bar chart for monolith
  - cpu_saturation_combined.pdf    — 2-panel side-by-side figure
"""

import sys
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, '.')
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
    """Join metrics_ecs with active-phase windows computed from requests.

    Phase boundaries are derived from timestamp_ms per (experiment, phase).
    Comparison in SQL uses to_timestamp() so the tz-aware timestamp column
    aligns correctly with the epoch-millis stored in requests.
    """
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
           e.ram_in_mb,
           pb.phase_name,
           m.service_name,
           m.cpu_percent,
           m.memory_percent,
           m.running_tasks
    FROM experiments e
    JOIN phase_bounds pb ON pb.experiment_id = e.id
    JOIN metrics_ecs  m  ON m.experiment_id = e.id
                        AND m.timestamp BETWEEN pb.ph_start AND pb.ph_end
    WHERE {EXCLUDE_SQL}
      AND e.architecture IN ('microservices','monolith')
      AND e.auth_strategy IN ('none', 'service-integrated-manual')
      AND m.cpu_percent IS NOT NULL
      AND pb.phase_name IN ('Morning rush','Stabilization','Flash Crowd')
    """
    df = query_df(sql)
    df['auth_label'] = df.apply(
        lambda r: 'None' if r['auth_strategy'] == 'none'
        else f"Manual ({r['algo']})",
        axis=1
    )
    df['hw'] = df.apply(lambda r: HW_LABEL.get((r['architecture'], float(r['cpu_in_vcpu'])),
                                                f"{r['cpu_in_vcpu']}vCPU"), axis=1)
    return df


def aggregate(df):
    """Per-experiment, per-service CPU mean / p95 / max during active phases."""
    per_exp_svc = df.groupby(
        ['exp_id', 'architecture', 'auth_label', 'hw', 'service_name']
    ).agg(
        cpu_mean=('cpu_percent', 'mean'),
        cpu_p95=('cpu_percent', lambda x: x.quantile(0.95)),
        cpu_max=('cpu_percent', 'max'),
        n_samples=('cpu_percent', 'count'),
    ).reset_index()
    return per_exp_svc


def summarise(per_exp_svc):
    """Aggregate over experiments to one row per (arch, hw, auth).

    For microservices, the auth pipeline lives in the frontend-service, so we
    report that service. For monolith there is only one service.
    """
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


def plot_arch(summary, arch, title, out_path):
    sub = summary[summary['architecture'] == arch].copy()
    hws_present = [h for h in HW_ORDER if h in sub['hw'].unique()]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    n_auth = len(AUTH_ORDER)
    bar_w = 0.25
    x = np.arange(len(hws_present))

    for i, auth in enumerate(AUTH_ORDER):
        means = []
        p95s = []
        for hw in hws_present:
            row = sub[(sub['hw'] == hw) & (sub['auth_label'] == auth)]
            means.append(row['cpu_mean'].iloc[0] if len(row) else np.nan)
            p95s.append(row['cpu_p95'].iloc[0] if len(row) else np.nan)
        pos = x + (i - (n_auth - 1) / 2) * bar_w
        bars = ax.bar(pos, means, bar_w, label=auth, color=AUTH_COLOR[auth],
                      edgecolor='black', linewidth=0.4)
        # Overlay p95 as a black cap marker
        ax.scatter(pos, p95s, marker='_', color='black', s=80, linewidths=1.5,
                   zorder=4)
        for rect, m, p in zip(bars, means, p95s):
            if np.isnan(m):
                continue
            ax.text(rect.get_x() + rect.get_width() / 2, m + 1.5,
                    f"{m:.0f}", ha='center', va='bottom', fontsize=7)

    ax.axhline(100, color='gray', linestyle=':', linewidth=0.8, alpha=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(hws_present)
    ax.set_xlabel('Hardware-Tier')
    ax.set_ylabel('CPU-Auslastung (%) während Lastphasen')
    ax.set_ylim(0, 110)
    ax.set_title(title)
    ax.legend(loc='upper right', fontsize=8, framealpha=0.9)
    ax.grid(axis='y', alpha=0.3)

    # Footnote explaining the black tick
    fig.text(0.01, 0.01,
             'Balken = Mittelwert · schwarzer Strich = p95 · Lastphasen = Morning rush + Stabilization + Flash Crowd',
             fontsize=7, color='#555')

    plt.tight_layout(rect=(0, 0.03, 1, 1))
    plt.savefig(out_path, bbox_inches='tight')
    plt.close()


def plot_combined(summary, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    titles = {
        'microservices': 'Microservices — frontend-service',
        'monolith':      'Monolith',
    }
    for ax, arch in zip(axes, ['microservices', 'monolith']):
        sub = summary[summary['architecture'] == arch].copy()
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
    plt.savefig(out_path, bbox_inches='tight')
    plt.close()


def main():
    print("[44] Loading metrics_ecs joined with active-phase windows...")
    raw = load_raw()
    print(f"    rows: {len(raw):,} | experiments: {raw['exp_id'].nunique()}")

    per_exp_svc = aggregate(raw)
    per_exp_svc.to_csv(f"{PLOT_DIR}/cpu_saturation_raw.csv", index=False)
    print(f"    wrote cpu_saturation_raw.csv ({len(per_exp_svc)} rows)")

    summary = summarise(per_exp_svc)
    summary_sorted = summary.sort_values(
        ['architecture', 'hw', 'auth_label'],
        key=lambda col: col.map({**{h: i for i, h in enumerate(HW_ORDER)},
                                 **{a: i for i, a in enumerate(AUTH_ORDER)}}).fillna(col)
    )
    summary_sorted.to_csv(f"{PLOT_DIR}/cpu_saturation_table.csv", index=False)
    print(f"    wrote cpu_saturation_table.csv ({len(summary)} rows)")
    print("\n" + summary_sorted.to_string(index=False))

    plot_arch(summary, 'microservices',
              'Microservices — frontend-service CPU-Auslastung',
              f"{PLOT_DIR}/cpu_saturation_ms.pdf")
    plot_arch(summary, 'monolith',
              'Monolith — CPU-Auslastung',
              f"{PLOT_DIR}/cpu_saturation_monolith.pdf")
    plot_combined(summary, f"{PLOT_DIR}/cpu_saturation_combined.pdf")
    print(f"\n    wrote cpu_saturation_{{ms,monolith,combined}}.pdf")


if __name__ == '__main__':
    main()
