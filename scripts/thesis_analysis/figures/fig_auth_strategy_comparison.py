#!/usr/bin/env python3
"""Generate auth_strategy_comparison.pdf for fig:auth-strategy-comparison.

Compares E14 (Manual) vs E17 (Cognito) pre-calibration timeseries,
showing P95 latency per 60s window with 10s timeout line.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR

WINDOW_MS = 60000

PHASE_BOUNDARIES = [
    (0, 5, 'Aufwärmphase'),
    (5, 10, 'Baseline'),
    (10, 20, 'Morgenansturm'),
    (20, 40, 'Stabilisierung'),
    (40, 42, 'Lastspitze'),
    (42, 44, 'Lastabsenkung'),
    (44, 57, 'Abkühlphase'),
]


def load_timeseries(exp_id):
    return query_df(f"""
        SELECT
            FLOOR(r.relative_time_ms / {WINDOW_MS}) AS time_window,
            COUNT(*) AS throughput,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95
        FROM requests r
        WHERE r.experiment_id = {exp_id}
        GROUP BY FLOOR(r.relative_time_ms / {WINDOW_MS})
        ORDER BY time_window
    """)


def main():
    df17 = load_timeseries(17)
    df14 = load_timeseries(14)

    for df in [df17, df14]:
        df['minute'] = df['time_window'].astype(float) * WINDOW_MS / 60000
        df['p95'] = pd.to_numeric(df['p95'], errors='coerce')

    fig, ax = plt.subplots(figsize=(12, 5))

    shade_colors = ['#f5f5f5', '#ebebeb']
    for i, (start, end, name) in enumerate(PHASE_BOUNDARIES):
        ax.axvspan(start, end, alpha=0.4, color=shade_colors[i % 2], zorder=0)
    for start, _, _ in PHASE_BOUNDARIES[1:]:
        ax.axvline(x=start, color='#888888', linestyle=':', linewidth=0.7, alpha=0.7)

    trans = ax.get_xaxis_transform()
    for start, end, name in PHASE_BOUNDARIES:
        ax.text((start + end) / 2, 1.02, name, transform=trans,
                ha='center', va='bottom', fontsize=8, color='#444444')

    ax.plot(df17['minute'], df17['p95'], color='#2196F3', linewidth=1.5,
            label='E17 (Cognito)', marker='o', markersize=3)
    ax.plot(df14['minute'], df14['p95'], color='#F44336', linewidth=1.5,
            label='E14 (Manual)', marker='s', markersize=3)

    ax.axhline(y=10000, color='black', linestyle='--', linewidth=1, alpha=0.7,
               label='10s Timeout')

    ax.set_yscale('log')
    ax.set_xlabel('Zeit (Minuten)')
    ax.set_ylabel('P95 Latenz (ms)')
    ax.set_xlim(0, 57)
    ax.legend(loc='upper right')
    ax.set_title('Vor-Kalibrierung: Cognito vs. Manual (Microservices/L)')

    plt.tight_layout()
    path = f"{PLOT_DIR}/auth_strategy_comparison.pdf"
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    print(f"Saved: {path}")


if __name__ == '__main__':
    main()
