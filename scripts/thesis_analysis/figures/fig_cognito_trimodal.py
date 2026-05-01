#!/usr/bin/env python3
"""Generate cognito_trimodal.pdf for fig:cognito-trimodal.

FaaS/512 Cognito: Tri-modal distribution of token verification latency.
Left panel: Histogram + KDE with mode region annotations.
Right panel: CDF with mode boundaries.
Also outputs cognito_trimodal_shares.csv for reproducibility.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

PROTECTED_FAAS = ('/frontend/setUser', '/frontend/addCartItem',
                  '/frontend/cart', '/frontend/checkout')


def find_experiment():
    df = query_df(f"""
        SELECT e.id FROM experiments e
        WHERE {EXCLUDE_SQL} AND e.architecture = 'faas'
          AND e.ram_in_mb = 512 AND e.auth_strategy = 'service-integrated'
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


def main():
    eid = find_experiment()
    if not eid:
        print('No FaaS/512 Cognito experiment')
        return

    eps = ','.join(f"'{e}'" for e in PROTECTED_FAAS)
    df = query_df(f"""
        SELECT r.latency_ms FROM requests r
        WHERE r.experiment_id = {eid} AND NOT r.is_error
          AND r.endpoint IN ({eps}) AND r.phase_name = 'Baseline'
        ORDER BY RANDOM() LIMIT 50000
    """)
    if df.empty:
        print('No data')
        return

    lat = df['latency_ms'].values

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    lat_clipped = lat[(lat > 0) & (lat < 1000)]
    ax = axes[0]
    ax.hist(lat_clipped, bins=100, density=True, alpha=0.5, color='#3498db',
            edgecolor='none', label='Histogram')

    kde = gaussian_kde(lat_clipped, bw_method=0.03)
    x_kde = np.linspace(0, 800, 500)
    ax.plot(x_kde, kde(x_kde), color='#e74c3c', linewidth=2, label='KDE')

    mode_bands = [
        (50, 100, 'Cached (gecacht)', '#2ecc71'),
        (100, 200, 'Warm (Revalidierung)', '#f39c12'),
        (200, 500, 'Cold (JWKS-Abruf)', '#e74c3c'),
    ]
    mode_shares = []
    for lo, hi, label, color in mode_bands:
        pct = float(np.mean((lat >= lo) & (lat < hi)) * 100.0)
        mode_shares.append({
            'mode': label, 'lo_ms': lo, 'hi_ms': hi,
            'share_pct': round(pct, 1),
            'n_requests': int(np.sum((lat >= lo) & (lat < hi))),
            'n_total': int(len(lat)),
        })

    for (lo, hi, label, color), share in zip(mode_bands, mode_shares):
        ax.axvspan(lo, hi, alpha=0.1, color=color)
        ax.text((lo + hi) / 2, ax.get_ylim()[1] * 0.9,
                f"{label}\n({share['share_pct']:.1f}%)",
                ha='center', fontsize=8, color=color, fontweight='bold')

    ax.set_xlabel('Latency (ms)')
    ax.set_ylabel('Density')
    ax.set_title('Cognito Token Verification: Tri-Modal Distribution')
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    ax2 = axes[1]
    lat_sorted = np.sort(lat_clipped)
    cdf = np.arange(1, len(lat_sorted) + 1) / len(lat_sorted)
    ax2.plot(lat_sorted, cdf, color='#3498db', linewidth=1.5)
    for (lo, hi, label, color), share in zip(mode_bands, mode_shares):
        ax2.axvspan(lo, hi, alpha=0.1, color=color)
        ax2.text((lo + hi) / 2, 0.05, f"{share['share_pct']:.1f}%",
                 ha='center', fontsize=9, color=color, fontweight='bold')

    ax2.set_xlabel('Latency (ms)')
    ax2.set_ylabel('CDF')
    ax2.set_title('CDF with Verification Mode Regions')
    ax2.grid(alpha=0.3)

    fig.suptitle('FaaS/512 Cognito — Auth-Only Endpoints, Baseline Phase',
                 fontweight='bold', fontsize=12)
    plt.tight_layout()
    path = f"{PLOT_DIR}/cognito_trimodal.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    shares_df = pd.DataFrame(mode_shares)
    shares_csv = f"{PLOT_DIR}/cognito_trimodal_shares.csv"
    shares_df.to_csv(shares_csv, index=False)
    print(f"Saved: {shares_csv}")


if __name__ == '__main__':
    main()
