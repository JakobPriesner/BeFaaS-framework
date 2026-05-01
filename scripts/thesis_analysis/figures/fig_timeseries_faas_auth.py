#!/usr/bin/env python3
"""Generate timeseries_faas512_auth_comparison.pdf for fig:timeseries-faas-auth.

FaaS/512 MB: Auth strategy comparison (None vs Cognito vs Manual vs Edge)
over the full 57-minute SCNAST protocol using 60-second windows.
Three-panel layout: P50 (top), P99 log (middle), error rate (bottom).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
}

PHASE_BOUNDARIES = [
    (0, 5, 'Warm-up'), (5, 10, 'Baseline'), (10, 20, 'Morning Rush'),
    (20, 40, 'Stabilization'), (40, 42, 'Flash Crowd'),
    (42, 44, 'Step Down'), (44, 57, 'Cool-down'),
]

WINDOW_SIZE_MS = 60000


def load_timeseries(experiment_id):
    df = query_df(f"""
        SELECT
            FLOOR(r.relative_time_ms / {WINDOW_SIZE_MS}) AS time_window,
            COUNT(*) AS throughput,
            COUNT(*) FILTER (WHERE r.is_error) * 100.0 / NULLIF(COUNT(*), 0) AS error_pct,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM requests r
        WHERE r.experiment_id = {experiment_id}
        GROUP BY FLOOR(r.relative_time_ms / {WINDOW_SIZE_MS})
        ORDER BY time_window
    """)
    if not df.empty:
        df['minute'] = df['time_window'].astype(float) * WINDOW_SIZE_MS / 60000
        for col in ['p50', 'p95', 'p99', 'error_pct']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def add_phase_boundaries(ax, show_labels=False):
    shade_colors = ['#f5f5f5', '#ebebeb']
    for i, (start, end, _name) in enumerate(PHASE_BOUNDARIES):
        ax.axvspan(start, end, alpha=0.4, color=shade_colors[i % 2], zorder=0)
    for start, _, _ in PHASE_BOUNDARIES[1:]:
        ax.axvline(x=start, color='#888888', linestyle=':', linewidth=0.7, alpha=0.7, zorder=1)
    if show_labels:
        trans = ax.get_xaxis_transform()
        for start, end, name in PHASE_BOUNDARIES:
            ax.text((start + end) / 2, 1.02, name, transform=trans,
                    ha='center', va='bottom', fontsize=9, color='#444444')


def find_experiment(configs, arch, ram, cpu, auth_strategy, algo='default'):
    mask = (
        (configs['architecture'] == arch) &
        (configs['ram_in_mb'] == ram) &
        (configs['auth_strategy'] == auth_strategy)
    )
    if cpu > 0:
        mask = mask & (configs['cpu'] == cpu)
    if algo != 'default':
        mask = mask & (configs['algo'] == algo)
    matches = configs[mask]
    if matches.empty:
        return None
    for _, row in matches.iterrows():
        eid = row['id']
        stats = query_df(
            f"SELECT COUNT(*) AS n, "
            f"       COALESCE(MAX(relative_time_ms), 0) / 60000.0 AS duration_min "
            f"FROM requests WHERE experiment_id = {eid}"
        )
        if stats.empty:
            continue
        if int(stats.iloc[0]['n']) > 100000 and float(stats.iloc[0]['duration_min']) >= 50:
            return eid
    for _, row in matches.iterrows():
        eid = row['id']
        count = query_df(f"SELECT COUNT(*) AS n FROM requests WHERE experiment_id = {eid}")
        if not count.empty and count.iloc[0]['n'] > 1000:
            return eid
    return matches.iloc[0]['id']


def main():
    configs = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu
        FROM experiments e
        WHERE {EXCLUDE_SQL}
        ORDER BY e.architecture, e.ram_in_mb, e.auth_strategy
    """)

    datasets = []
    for auth, color_key in [('none', 'None'), ('service-integrated', 'Cognito'),
                             ('service-integrated-manual', 'Manual'), ('edge', 'Edge')]:
        eid = find_experiment(configs, 'faas', 512, 0, auth)
        if eid is not None:
            ts = load_timeseries(eid)
            datasets.append((AUTH_SHORT.get(auth, auth), AUTH_COLORS[color_key], ts))

    if not datasets:
        print('No FaaS/512 data')
        return

    fig, axes = plt.subplots(3, 1, figsize=(13, 10.6), sharex=True,
                             gridspec_kw={'height_ratios': [2, 2, 1]})
    ax_p50, ax_p99, ax_err = axes

    for label, color, ts in datasets:
        if ts.empty:
            continue
        ax_p50.plot(ts['minute'].values, ts['p50'].values, label=label,
                    color=color, linewidth=2.2, alpha=0.9)
        ax_p99.plot(ts['minute'].values, ts['p99'].values, label=label,
                    color=color, linewidth=2.2, alpha=0.9)

    add_phase_boundaries(ax_p50, show_labels=True)
    ax_p50.set_ylabel('P50 Latency (ms)', fontsize=11)
    ax_p50.grid(axis='y', alpha=0.35, linestyle='--', linewidth=0.5)
    ax_p50.tick_params(labelsize=10)
    ax_p50.set_title('FaaS (512 MB): Authentication Strategy Comparison — SCNAST Protocol',
                     fontweight='bold', fontsize=12, pad=24)
    ax_p50.legend(fontsize=10, loc='upper left', ncol=4, framealpha=0.9)

    add_phase_boundaries(ax_p99)
    ax_p99.set_ylabel('P99 Latency (ms, log)', fontsize=11)
    ax_p99.set_yscale('log')
    ax_p99.grid(axis='y', alpha=0.35, which='both', linestyle='--', linewidth=0.5)
    ax_p99.tick_params(labelsize=10)

    for label, color, ts in datasets:
        if ts.empty:
            continue
        ax_err.plot(ts['minute'].values, ts['error_pct'].values,
                    label=label, color=color, linewidth=1.8, alpha=0.9)
    add_phase_boundaries(ax_err)
    ax_err.set_ylabel('Errors (%)', fontsize=11)
    ax_err.set_xlabel('Time (minutes)', fontsize=11)
    ax_err.set_ylim(0, min(100, max(5, ax_err.get_ylim()[1] * 1.1)))
    ax_err.grid(axis='y', alpha=0.35, linestyle='--', linewidth=0.5)
    ax_err.tick_params(labelsize=10)

    plt.tight_layout()
    path = f"{PLOT_DIR}/timeseries_faas512_auth_comparison.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
