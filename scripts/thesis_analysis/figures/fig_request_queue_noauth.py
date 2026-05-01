#!/usr/bin/env python3
"""Generate request_queue_real_data_exp11.pdf for fig:request-queue-noauth.

Same two-panel queue model visualization as fig_request_queue_real.py
but for E11 (Microservices, None, L, pre-calibration).
Shows that saturation occurs even without authentication.
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

EXP_ID = 11


def main():
    df = query_df(f"""
        SELECT
            FLOOR(r.relative_time_ms / {WINDOW_MS}) AS time_window,
            COUNT(*) AS throughput,
            COUNT(*) FILTER (WHERE r.is_error) * 100.0 / NULLIF(COUNT(*), 0) AS error_pct,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95
        FROM requests r
        WHERE r.experiment_id = {EXP_ID}
        GROUP BY FLOOR(r.relative_time_ms / {WINDOW_MS})
        ORDER BY time_window
    """)
    df['minute'] = df['time_window'].astype(float) * WINDOW_MS / 60000
    df['arrival_rate'] = pd.to_numeric(df['throughput'], errors='coerce') / 60.0
    df['p95'] = pd.to_numeric(df['p95'], errors='coerce')

    baseline = df[(df['minute'] >= 5) & (df['minute'] < 10)]
    c_mu = baseline['arrival_rate'].mean()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                    gridspec_kw={'height_ratios': [1, 1]})

    for ax in [ax1, ax2]:
        shade_colors = ['#f5f5f5', '#ebebeb']
        for i, (start, end, _) in enumerate(PHASE_BOUNDARIES):
            ax.axvspan(start, end, alpha=0.3, color=shade_colors[i % 2], zorder=0)
        for start, _, _ in PHASE_BOUNDARIES[1:]:
            ax.axvline(x=start, color='#888888', linestyle=':', linewidth=0.7, alpha=0.5)

    trans = ax1.get_xaxis_transform()
    for start, end, name in PHASE_BOUNDARIES:
        ax1.text((start + end) / 2, 1.02, name, transform=trans,
                 ha='center', va='bottom', fontsize=8, color='#444444')

    ax1.fill_between(df['minute'], df['arrival_rate'], alpha=0.4, color='#2196F3', label='Ankunftsrate λ')
    ax1.plot(df['minute'], df['arrival_rate'], color='#2196F3', linewidth=1)
    ax1.axhline(y=c_mu, color='#4CAF50', linestyle='--', linewidth=1.5,
                label=f'Kapazität cμ ≈ {c_mu:.0f} Req/s')

    saturated = df[df['arrival_rate'] > c_mu]
    if not saturated.empty:
        for _, row in saturated.iterrows():
            ax1.axvspan(row['minute'] - 0.5, row['minute'] + 0.5,
                        alpha=0.15, color='red', zorder=0)

    ax1.set_ylabel('Anfragen/s')
    ax1.legend(loc='upper left')

    ax2.plot(df['minute'], df['p95'], color='#F44336', linewidth=1.5)
    ax2.set_yscale('log')
    ax2.set_ylabel('P95 Latenz (ms)')
    ax2.set_xlabel('Zeit (Minuten)')
    ax2.set_xlim(0, 57)

    fig.suptitle(f'E{EXP_ID} (Microservices, None, L, Vor-Kalibrierung)', fontsize=11, y=1.0)
    plt.tight_layout()
    path = f"{PLOT_DIR}/request_queue_real_data_exp{EXP_ID}.pdf"
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    print(f"Saved: {path}")


if __name__ == '__main__':
    main()
