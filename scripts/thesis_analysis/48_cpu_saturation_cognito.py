#!/usr/bin/env python3
"""
48 -- CPU Saturation Under Cognito Load (Flash Crowd)

Companion to script 44, but for the service-integrated (Cognito) auth
strategy instead of Manual (bcrypt/argon2id). The question this answers:

  Is the additional overhead on containers under Cognito auth driven by
  CPU contention on the verifying component (frontend-service for MS,
  monolith process for Mono), or does the CPU stay cool and point to a
  different bottleneck (outbound connection pool, external API)?

Focus: Flash Crowd phase, since that is where ΔAuth amplifies 10-16x on
small container tiers. For each container experiment, we aggregate
metrics_ecs.cpu_percent per service inside the Flash Crowd window and
compare None vs Cognito at matching hardware tiers.

Outputs (in PLOT_DIR):
  - cpu_saturation_cognito_raw.csv         per-exp/per-service aggregates
  - cpu_saturation_cognito_table.csv       summary per (arch, hw, auth, service)
  - cpu_saturation_cognito_ms.pdf          grouped bars, MS frontend-service
  - cpu_saturation_cognito_monolith.pdf    grouped bars, monolith
  - cpu_saturation_cognito_combined.pdf    2-panel side-by-side figure
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

HW_ORDER = ['S', 'M', 'L', 'XL']
HW_LABEL = {
    ('microservices', 0.25): 'S', ('microservices', 0.5): 'M',
    ('microservices', 1.0): 'L', ('microservices', 4.0): 'XL',
    ('monolith', 0.25): 'S', ('monolith', 0.5): 'M',
    ('monolith', 1.0): 'L', ('monolith', 4.0): 'XL',
}

AUTH_ORDER = ['None', 'Cognito']
AUTH_COLOR = {
    'None':    AUTH_COLORS_DETAILED['None'],
    'Cognito': AUTH_COLORS_DETAILED['Cognito'],
}


def load_raw():
    """Flash Crowd CPU samples for container experiments (None vs Cognito)."""
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
           e.cpu_in_vcpu,
           e.ram_in_mb,
           pb.phase_name,
           m.service_name,
           m.cpu_percent
    FROM experiments e
    JOIN phase_bounds pb ON pb.experiment_id = e.id
    JOIN metrics_ecs  m  ON m.experiment_id = e.id
                        AND m.timestamp BETWEEN pb.ph_start AND pb.ph_end
    WHERE {EXCLUDE_SQL}
      AND e.architecture IN ('microservices','monolith')
      AND e.auth_strategy IN ('none', 'service-integrated')
      AND m.cpu_percent IS NOT NULL
      AND pb.phase_name = 'Flash Crowd'
    """
    df = query_df(sql)
    df['auth_label'] = df['auth_strategy'].map(
        {'none': 'None', 'service-integrated': 'Cognito'}
    )
    df['hw'] = df.apply(
        lambda r: HW_LABEL.get((r['architecture'], float(r['cpu_in_vcpu'])),
                               f"{r['cpu_in_vcpu']}vCPU"),
        axis=1,
    )
    return df


def aggregate(df):
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
    """For MS, report the frontend-service (where Cognito verification runs).
    For Monolith, there is only one service."""
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
    bar_w = 0.35
    x = np.arange(len(hws_present))

    for i, auth in enumerate(AUTH_ORDER):
        means, p95s = [], []
        for hw in hws_present:
            row = sub[(sub['hw'] == hw) & (sub['auth_label'] == auth)]
            means.append(row['cpu_mean'].iloc[0] if len(row) else np.nan)
            p95s.append(row['cpu_p95'].iloc[0] if len(row) else np.nan)
        pos = x + (i - (n_auth - 1) / 2) * bar_w
        bars = ax.bar(pos, means, bar_w, label=auth, color=AUTH_COLOR[auth],
                      edgecolor='black', linewidth=0.4)
        ax.scatter(pos, p95s, marker='_', color='black', s=90, linewidths=1.5,
                   zorder=4)
        for rect, m in zip(bars, means):
            if np.isnan(m):
                continue
            ax.text(rect.get_x() + rect.get_width() / 2, m + 1.5,
                    f"{m:.0f}", ha='center', va='bottom', fontsize=8)

    ax.axhline(100, color='gray', linestyle=':', linewidth=0.8, alpha=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(hws_present)
    ax.set_xlabel('Hardware-Tier')
    ax.set_ylabel('CPU-Auslastung (%) während Flash Crowd')
    ax.set_ylim(0, 110)
    ax.set_title(title)
    ax.legend(loc='upper right', fontsize=9, framealpha=0.9)
    ax.grid(axis='y', alpha=0.3)

    fig.text(0.01, 0.01,
             'Balken = Mittelwert · schwarzer Strich = p95 · Phase = Flash Crowd',
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
        bar_w = 0.35
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
            ax.scatter(pos, p95s, marker='_', color='black', s=90,
                       linewidths=1.5, zorder=4)
            for xi, m in zip(pos, means):
                if np.isnan(m):
                    continue
                ax.text(xi, m + 1.5, f"{m:.0f}", ha='center', va='bottom',
                        fontsize=8)

        ax.axhline(100, color='gray', linestyle=':', linewidth=0.8, alpha=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(hws_present)
        ax.set_xlabel('Hardware-Tier')
        ax.set_ylim(0, 110)
        ax.set_title(titles[arch])
        ax.grid(axis='y', alpha=0.3)

    axes[0].set_ylabel('CPU-Auslastung (%) während Flash Crowd')
    axes[0].legend(loc='upper right', fontsize=9, framealpha=0.9)
    fig.suptitle('CPU-Konkurrenz durch Cognito-Verifikation (Mittelwert · schwarzer Strich = p95)',
                 fontsize=11)
    plt.tight_layout(rect=(0, 0.02, 1, 0.96))
    plt.savefig(out_path, bbox_inches='tight')
    plt.close()


def main():
    print("[48] Loading Flash Crowd CPU samples (None vs Cognito, containers)...")
    raw = load_raw()
    print(f"    rows: {len(raw):,} | experiments: {raw['exp_id'].nunique()}")

    per_exp_svc = aggregate(raw)
    per_exp_svc.to_csv(f"{PLOT_DIR}/cpu_saturation_cognito_raw.csv", index=False)
    print(f"    wrote cpu_saturation_cognito_raw.csv ({len(per_exp_svc)} rows)")

    summary = summarise(per_exp_svc)
    summary_sorted = summary.sort_values(
        ['architecture', 'hw', 'auth_label'],
        key=lambda col: col.map({**{h: i for i, h in enumerate(HW_ORDER)},
                                 **{a: i for i, a in enumerate(AUTH_ORDER)}}).fillna(col)
    )
    summary_sorted.to_csv(f"{PLOT_DIR}/cpu_saturation_cognito_table.csv", index=False)
    print(f"    wrote cpu_saturation_cognito_table.csv ({len(summary)} rows)")
    print("\n" + summary_sorted.to_string(index=False))

    plot_arch(summary, 'microservices',
              'Microservices — frontend-service CPU-Auslastung (None vs Cognito)',
              f"{PLOT_DIR}/cpu_saturation_cognito_ms.pdf")
    plot_arch(summary, 'monolith',
              'Monolith — CPU-Auslastung (None vs Cognito)',
              f"{PLOT_DIR}/cpu_saturation_cognito_monolith.pdf")
    plot_combined(summary, f"{PLOT_DIR}/cpu_saturation_cognito_combined.pdf")
    print(f"\n    wrote cpu_saturation_cognito_{{ms,monolith,combined}}.pdf")


if __name__ == '__main__':
    main()
