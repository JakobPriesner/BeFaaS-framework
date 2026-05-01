#!/usr/bin/env python3
"""
36 — Fine-Grained Time-Series Latency Plots
Visualizes latency, throughput, and error rate over the full 57-minute SCNAST
protocol using 60-second windows. Shows phase boundaries and P50/P95/P99 bands.

Plots generated:
  1. FaaS/512: Auth strategy comparison (None vs Cognito vs Manual vs Edge)
  2. MS/L: Auth strategy comparison
  3. MS/S Edge: Cascading failure (error rate + latency)
  4. FaaS Cognito: HW tier comparison (256/512/1024/1769MB)
  5. Algorithm comparison: FaaS/512 bcrypt vs argon2id
  6. Cross-architecture: FaaS/512 vs MS/L vs Mono/L (Cognito)

Outputs: timeseries_*.pdf
"""

import sys
import warnings
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS, ARCH_COLORS

warnings.filterwarnings('ignore', category=FutureWarning)

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}

# SCNAST phase boundaries (cumulative minutes from start)
PHASE_BOUNDARIES = [
    (0, 5, 'Warm-up'),
    (5, 10, 'Baseline'),
    (10, 20, 'Morning Rush'),
    (20, 40, 'Stabilization'),
    (40, 42, 'Flash Crowd'),
    (42, 44, 'Step Down'),
    (44, 57, 'Cool-down'),
]

WINDOW_SIZE_MS = 60000  # 60s windows


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    mapping = {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}
    return mapping.get(float(cpu), f"{cpu}vCPU")


def load_timeseries(experiment_id, window_ms=WINDOW_SIZE_MS):
    """Load per-window metrics for an experiment."""
    df = query_df(f"""
        SELECT
            FLOOR(r.relative_time_ms / {window_ms}) AS time_window,
            COUNT(*) AS throughput,
            COUNT(*) FILTER (WHERE r.is_error) AS n_errors,
            COUNT(*) FILTER (WHERE r.is_error) * 100.0 / NULLIF(COUNT(*), 0) AS error_pct,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM requests r
        WHERE r.experiment_id = {experiment_id}
        GROUP BY FLOOR(r.relative_time_ms / {window_ms})
        ORDER BY time_window
    """)
    if not df.empty:
        df['minute'] = df['time_window'].astype(float) * window_ms / 60000
        for col in ['p50', 'p95', 'p99', 'error_pct']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def add_phase_boundaries(ax, show_labels=False):
    """Add phase boundary shading and vertical lines; optionally label phases on top."""
    shade_colors = ['#f5f5f5', '#ebebeb']
    for i, (start, end, _name) in enumerate(PHASE_BOUNDARIES):
        ax.axvspan(start, end, alpha=0.4, color=shade_colors[i % 2], zorder=0)
    for start, _, _ in PHASE_BOUNDARIES[1:]:
        ax.axvline(x=start, color='#888888', linestyle=':', linewidth=0.7, alpha=0.7, zorder=1)

    if show_labels:
        # Horizontal phase labels above the axis
        trans = ax.get_xaxis_transform()  # x in data, y in axes fraction
        for start, end, name in PHASE_BOUNDARIES:
            ax.text((start + end) / 2, 1.02, name, transform=trans,
                    ha='center', va='bottom', fontsize=9, color='#444444')


def plot_latency_comparison(datasets, title, filename, y_max=None, show_error_rate=False):
    """Readable three-panel layout: P50 (top), P99 (middle, log), error rate (bottom).

    Each strategy is drawn as a single line per panel (no shaded bands), which
    keeps individual curves visible even during load spikes.

    datasets: list of (label, color, timeseries_df) tuples
    """
    n_axes = 3 if show_error_rate else 2
    height_ratios = [2, 2, 1] if show_error_rate else [1, 1]
    fig, axes = plt.subplots(n_axes, 1, figsize=(13, 4 + 2.2 * n_axes),
                             sharex=True,
                             gridspec_kw={'height_ratios': height_ratios})

    ax_p50, ax_p99 = axes[0], axes[1]
    ax_err = axes[2] if show_error_rate else None

    for label, color, ts in datasets:
        if ts.empty:
            continue
        minutes = ts['minute'].values
        ax_p50.plot(minutes, ts['p50'].values, label=label,
                    color=color, linewidth=2.2, alpha=0.9)
        ax_p99.plot(minutes, ts['p99'].values, label=label,
                    color=color, linewidth=2.2, alpha=0.9)

    # ── P50 panel ──
    add_phase_boundaries(ax_p50, show_labels=True)
    ax_p50.set_ylabel('P50 Latency (ms)', fontsize=11)
    ax_p50.grid(axis='y', alpha=0.35, linestyle='--', linewidth=0.5)
    ax_p50.tick_params(labelsize=10)
    if y_max is not None:
        ax_p50.set_ylim(0, y_max)
    ax_p50.set_title(title, fontweight='bold', fontsize=12, pad=24)
    ax_p50.legend(fontsize=10, loc='upper left',
                  ncol=min(4, len(datasets)), framealpha=0.9)

    # ── P99 panel (log scale to show baseline + spikes together) ──
    add_phase_boundaries(ax_p99, show_labels=False)
    ax_p99.set_ylabel('P99 Latency (ms, log)', fontsize=11)
    ax_p99.set_yscale('log')
    ax_p99.grid(axis='y', alpha=0.35, which='both', linestyle='--', linewidth=0.5)
    ax_p99.tick_params(labelsize=10)

    # ── Error rate panel (optional) ──
    if ax_err is not None:
        for label, color, ts in datasets:
            if ts.empty:
                continue
            ax_err.plot(ts['minute'].values, ts['error_pct'].values,
                        label=label, color=color, linewidth=1.8, alpha=0.9)
        add_phase_boundaries(ax_err, show_labels=False)
        ax_err.set_ylabel('Errors (%)', fontsize=11)
        ax_err.set_xlabel('Time (minutes)', fontsize=11)
        ax_err.set_ylim(0, min(100, max(5, ax_err.get_ylim()[1] * 1.1)))
        ax_err.grid(axis='y', alpha=0.35, linestyle='--', linewidth=0.5)
        ax_err.tick_params(labelsize=10)
    else:
        ax_p99.set_xlabel('Time (minutes)', fontsize=11)

    plt.tight_layout()
    path = f"{PLOT_DIR}/{filename}"
    fig.savefig(path, bbox_inches='tight')
    print(f"  Saved: {path}")
    plt.close()


def find_experiment(configs, arch, ram, cpu, auth_strategy, algo='default'):
    """Find a representative experiment ID that has data."""
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

    # Prefer experiments that cover the full SCNAST protocol (~57 minutes).
    # A truncated run with only a few thousand requests would otherwise be
    # picked up and render as a two-minute line that is unreadable against
    # the 57-minute x-axis.
    for _, row in matches.iterrows():
        eid = row['id']
        stats = query_df(
            f"SELECT COUNT(*) AS n, "
            f"       COALESCE(MAX(relative_time_ms), 0) / 60000.0 AS duration_min "
            f"FROM requests WHERE experiment_id = {eid}"
        )
        if stats.empty:
            continue
        n = int(stats.iloc[0]['n'])
        duration_min = float(stats.iloc[0]['duration_min'])
        if n > 100000 and duration_min >= 50:
            return eid

    # Fallback: any run with at least a full baseline phase
    for _, row in matches.iterrows():
        eid = row['id']
        count = query_df(f"SELECT COUNT(*) AS n FROM requests WHERE experiment_id = {eid}")
        if not count.empty and count.iloc[0]['n'] > 1000:
            return eid

    return matches.iloc[0]['id']


def main():
    print("=" * 70)
    print("36 — TIME-SERIES LATENCY PLOTS")
    print("=" * 70)

    # ── 1. Get experiment configurations ──
    configs = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu
        FROM experiments e
        WHERE {EXCLUDE_SQL}
        ORDER BY e.architecture, e.ram_in_mb, e.auth_strategy
    """)

    # ── Plot 1: FaaS/512 Auth Strategy Comparison ──
    print("\n1. FaaS/512 Auth Strategy Comparison")
    datasets = []
    for auth, color_key in [('none', 'None'), ('service-integrated', 'Cognito'),
                             ('service-integrated-manual', 'Manual'), ('edge', 'Edge')]:
        eid = find_experiment(configs, 'faas', 512, 0, auth)
        if eid is not None:
            ts = load_timeseries(eid)
            datasets.append((AUTH_SHORT.get(auth, auth), AUTH_COLORS[color_key], ts))
            print(f"  Loaded E{eid} ({auth}): {len(ts)} windows")

    if datasets:
        plot_latency_comparison(
            datasets,
            'FaaS (512 MB): Authentication Strategy Comparison — SCNAST Protocol',
            'timeseries_faas512_auth_comparison.pdf',
            show_error_rate=True
        )

    # ── Plot 2: MS/L Auth Strategy Comparison ──
    print("\n2. MS/L Auth Strategy Comparison")
    datasets = []
    for auth, color_key in [('none', 'None'), ('service-integrated', 'Cognito'),
                             ('service-integrated-manual', 'Manual'), ('edge', 'Edge')]:
        eid = find_experiment(configs, 'microservices', 2048, 1.0, auth)
        if eid is not None:
            ts = load_timeseries(eid)
            datasets.append((AUTH_SHORT.get(auth, auth), AUTH_COLORS[color_key], ts))
            print(f"  Loaded E{eid} ({auth}): {len(ts)} windows")

    if datasets:
        plot_latency_comparison(
            datasets,
            'Microservices (L / 1.0 vCPU): Authentication Strategy Comparison',
            'timeseries_ms_l_auth_comparison.pdf',
            show_error_rate=True
        )

    # ── Plot 3: MS/S Edge Cascade ──
    print("\n3. MS/S Edge Cascading Failure")
    datasets = []
    for auth, color_key in [('none', 'None'), ('edge', 'Edge')]:
        eid = find_experiment(configs, 'microservices', 512, 0.25, auth)
        if eid is not None:
            ts = load_timeseries(eid)
            datasets.append((AUTH_SHORT.get(auth, auth), AUTH_COLORS[color_key], ts))
            print(f"  Loaded E{eid} ({auth}): {len(ts)} windows")

    if datasets:
        plot_latency_comparison(
            datasets,
            'Microservices (S / 0.25 vCPU): Lambda@Edge Cascading Failure',
            'timeseries_ms_s_edge_cascade.pdf',
            y_max=5000,
            show_error_rate=True
        )

    # ── Plot 4: FaaS Cognito HW Tier Comparison ──
    print("\n4. FaaS Cognito HW Tier Comparison")
    datasets = []
    hw_colors = {256: '#e74c3c', 512: '#3498db', 1024: '#2ecc71', 1769: '#9b59b6'}
    for ram in [256, 512, 1024, 1769]:
        eid = find_experiment(configs, 'faas', ram, 0, 'service-integrated')
        if eid is not None:
            ts = load_timeseries(eid)
            datasets.append((f'{ram}MB', hw_colors.get(ram, '#999'), ts))
            print(f"  Loaded E{eid} ({ram}MB): {len(ts)} windows")

    if datasets:
        plot_latency_comparison(
            datasets,
            'FaaS + Cognito: Hardware Tier Comparison — SCNAST Protocol',
            'timeseries_faas_cognito_hw.pdf',
        )

    # ── Plot 5: Algorithm Comparison (FaaS/512) ──
    print("\n5. FaaS/512 Algorithm Comparison (bcrypt vs argon2id)")
    datasets = []
    eid_bcrypt = find_experiment(configs, 'faas', 512, 0, 'service-integrated-manual', 'bcrypt')
    eid_argon = find_experiment(configs, 'faas', 512, 0, 'service-integrated-manual', 'argon2id')
    eid_none = find_experiment(configs, 'faas', 512, 0, 'none')

    if eid_none is not None:
        ts = load_timeseries(eid_none)
        datasets.append(('None', '#95a5a6', ts))
        print(f"  Loaded E{eid_none} (none): {len(ts)} windows")
    if eid_bcrypt is not None:
        ts = load_timeseries(eid_bcrypt)
        datasets.append(('Manual (bcrypt)', '#e74c3c', ts))
        print(f"  Loaded E{eid_bcrypt} (bcrypt): {len(ts)} windows")
    if eid_argon is not None:
        ts = load_timeseries(eid_argon)
        datasets.append(('Manual (argon2id)', '#8e44ad', ts))
        print(f"  Loaded E{eid_argon} (argon2id): {len(ts)} windows")

    if datasets:
        plot_latency_comparison(
            datasets,
            'FaaS (512 MB): Hash Algorithm Impact — bcrypt/HS256 vs argon2id/EdDSA',
            'timeseries_faas512_algo_comparison.pdf',
            y_max=5000,
            show_error_rate=True
        )

    # ── Plot 6: Cross-Architecture (Cognito) ──
    print("\n6. Cross-Architecture Comparison (Cognito)")
    datasets = []
    arch_configs = [
        ('faas', 512, 0, 'FaaS/512MB'),
        ('microservices', 2048, 1.0, 'MS/L'),
        ('monolith', 2048, 1.0, 'Mono/L'),
    ]
    for arch, ram, cpu, label in arch_configs:
        eid = find_experiment(configs, arch, ram, cpu, 'service-integrated')
        if eid is not None:
            ts = load_timeseries(eid)
            datasets.append((label, ARCH_COLORS[arch], ts))
            print(f"  Loaded E{eid} ({label}): {len(ts)} windows")

    if datasets:
        plot_latency_comparison(
            datasets,
            'Cross-Architecture Comparison with Cognito — SCNAST Protocol',
            'timeseries_cross_arch_cognito.pdf',
            show_error_rate=True
        )

    # ── Plot 7: Throughput comparison (FaaS/512) ──
    print("\n7. FaaS/512 Throughput Over Time")
    fig, ax = plt.subplots(figsize=(14, 5))
    for auth, color_key in [('none', 'None'), ('service-integrated', 'Cognito'),
                             ('service-integrated-manual', 'Manual'), ('edge', 'Edge')]:
        eid = find_experiment(configs, 'faas', 512, 0, auth)
        if eid is not None:
            ts = load_timeseries(eid)
            if not ts.empty:
                ax.plot(ts['minute'].values, ts['throughput'].values,
                       label=AUTH_SHORT.get(auth, auth),
                       color=AUTH_COLORS[color_key], linewidth=1.2)

    add_phase_boundaries(ax)
    ax.set_ylabel('Requests per Minute')
    ax.set_xlabel('Time (minutes)')
    ax.set_title('FaaS (512 MB): Throughput Over Time — SCNAST Protocol', fontweight='bold')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    path = f"{PLOT_DIR}/timeseries_faas512_throughput.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"  Saved: {path}")
    plt.close()

    print("\n" + "=" * 70)
    print("DONE — Script 36")
    print("=" * 70)


if __name__ == '__main__':
    main()
