#!/usr/bin/env python3
"""
37 — Distribution Visualizations
Demonstrates non-normality of latency data and visualizes distribution shapes.
Supports the methodological choice of non-parametric tests (Script 35).

Plots:
  1. Auth-Only CDFs: auth vs none comparison (log-x scale)
  2. Violin plots per SCNAST phase
  3. QQ-plot: normality assessment
  4. Cognito tri-modal KDE: cached/warm/cold verification modes

Outputs: cdf_auth_comparison.pdf, violin_phases.pdf, qq_latency.pdf,
         cognito_trimodal.pdf
"""

import sys
import warnings
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as sp_stats

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

warnings.filterwarnings('ignore', category=FutureWarning)

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}

PROTECTED_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)

PHASE_ORDER = ['Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
               'Flash Crowd', 'Step Down', 'Cool-down']


def get_protected_sql(arch):
    eps = PROTECTED_FAAS if arch == 'faas' else PROTECTED_CONTAINER
    return ','.join(f"'{e}'" for e in eps)


def load_latencies(experiment_id, arch, auth_only=True, phase=None, max_n=100000):
    """Load request-level latencies."""
    endpoint_clause = ""
    if auth_only:
        eps = get_protected_sql(arch)
        endpoint_clause = f"AND r.endpoint IN ({eps})"

    phase_clause = ""
    if phase:
        phase_clause = f"AND r.phase_name = '{phase}'"

    df = query_df(f"""
        SELECT r.latency_ms, r.phase_name
        FROM requests r
        WHERE r.experiment_id = {experiment_id}
          AND NOT r.is_error
          {endpoint_clause}
          {phase_clause}
        ORDER BY RANDOM()
        LIMIT {max_n}
    """)
    return df


def find_experiment(arch, ram, cpu, auth_strategy, algo='default'):
    """Find a representative experiment ID that has data."""
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"
    algo_clause = ""
    if algo != 'default':
        algo_clause = f"AND e.password_hash_algorithm = '{algo}'"

    df = query_df(f"""
        SELECT e.id FROM experiments e
        WHERE {EXCLUDE_SQL}
          AND e.architecture = '{arch}'
          AND e.ram_in_mb = {ram}
          {cpu_clause}
          AND e.auth_strategy = '{auth_strategy}'
          {algo_clause}
        ORDER BY e.id
    """)
    if df.empty:
        return None

    # Try each candidate until we find one with data
    for _, row in df.iterrows():
        eid = row['id']
        count = query_df(f"SELECT COUNT(*) AS n FROM requests WHERE experiment_id = {eid}")
        if not count.empty and count.iloc[0]['n'] > 1000:
            return eid

    return df.iloc[0]['id']


def main():
    print("=" * 70)
    print("37 — DISTRIBUTION VISUALIZATIONS")
    print("=" * 70)

    # ── Plot 1: Auth-Only CDFs ──
    print("\n1. Auth-Only CDF Comparison (FaaS/512, Baseline)")
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for ax, (scale, title_suffix) in zip(axes, [('linear', 'Linear Scale'),
                                                  ('log', 'Log Scale')]):
        for auth, color_key in [('none', 'None'), ('service-integrated', 'Cognito'),
                                 ('service-integrated-manual', 'Manual'), ('edge', 'Edge')]:
            eid = find_experiment('faas', 512, 0, auth)
            if eid is None:
                continue

            df = load_latencies(eid, 'faas', auth_only=True, phase='Baseline')
            if df.empty:
                continue

            lat = np.sort(df['latency_ms'].values)
            cdf = np.arange(1, len(lat) + 1) / len(lat)

            label = AUTH_SHORT.get(auth, auth)
            ax.plot(lat, cdf, label=f'{label} (n={len(lat):,})',
                   color=AUTH_COLORS[color_key], linewidth=1.5)

        ax.set_xlabel('Latency (ms)')
        ax.set_ylabel('CDF')
        ax.set_title(f'Auth-Only Endpoint Latency CDF — {title_suffix}')
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        if scale == 'log':
            ax.set_xscale('log')
        ax.set_ylim(0, 1.02)

    fig.suptitle('FaaS (512 MB), Baseline Phase: Latency Distribution by Auth Strategy',
                 fontweight='bold', fontsize=12)
    plt.tight_layout()
    path = f"{PLOT_DIR}/cdf_auth_comparison.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"  Saved: {path}")
    plt.close()

    # ── Plot 2: Violin Plots per Phase ──
    print("\n2. Violin Plots per SCNAST Phase")
    eid_cognito = find_experiment('faas', 512, 0, 'service-integrated')
    eid_none = find_experiment('faas', 512, 0, 'none')

    if eid_cognito and eid_none:
        fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

        for ax, eid, title, use_auth_only in [
            (axes[0], eid_none, 'FaaS/512 — None', True),
            (axes[1], eid_cognito, 'FaaS/512 — Cognito', True),
        ]:
            phase_data = []
            phase_labels = []
            for phase in PHASE_ORDER:
                df = load_latencies(eid, 'faas', auth_only=use_auth_only, phase=phase, max_n=20000)
                if not df.empty:
                    lat = df['latency_ms'].values
                    if len(lat) < 10:
                        continue
                    # Clip outliers for visualization (keep data, just limit view)
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
        print(f"  Saved: {path}")
        plt.close()

    # ── Plot 3: QQ-Plots (Normality Assessment) — individual + combined ──
    print("\n3. QQ-Plots (Normality Assessment)")

    qq_configs = [
        ('faas', 512, 0, 'none', 'FaaS/512 None', 'qq_latency_faas512_none.pdf'),
        ('faas', 512, 0, 'service-integrated', 'FaaS/512 Cognito', 'qq_latency_faas512_cognito.pdf'),
        ('microservices', 2048, 1.0, 'service-integrated', 'MS/L Cognito', 'qq_latency_ms_l_cognito.pdf'),
    ]

    def _plot_qq(ax, arch, ram, cpu, auth, title, fontscale=1.0):
        """Plot a single QQ-plot on the given axes. Returns True if data was plotted."""
        eid = find_experiment(arch, ram, cpu, auth)
        if eid is None:
            ax.set_title(f'{title} — no data')
            return False
        df_qq = load_latencies(eid, arch, auth_only=True, phase='Baseline', max_n=5000)
        if df_qq.empty:
            return False
        lat = df_qq['latency_ms'].values
        (osm, osr), (slope, intercept, r) = sp_stats.probplot(lat, dist='norm')
        auth_short = AUTH_SHORT.get(auth, auth)
        scatter_color = AUTH_COLORS.get(auth_short, '#3498db')
        ax.scatter(osm, osr, s=3 * fontscale, alpha=0.5, color=scatter_color)
        x_line = np.array([osm.min(), osm.max()])
        ax.plot(x_line, slope * x_line + intercept, 'r-', linewidth=1.5,
                label=f'R² = {r**2:.3f}')
        subsample = np.random.default_rng(42).choice(lat, size=min(5000, len(lat)), replace=False)
        _, sw_p = sp_stats.shapiro(subsample)
        ax.set_xlabel('Theoretische Quantile (Normal)', fontsize=int(11 * fontscale))
        ax.set_ylabel('Stichproben-Quantile (ms)', fontsize=int(11 * fontscale))
        ax.set_title(f'{title}\nShapiro-Wilk p = {sw_p:.2e}', fontsize=int(12 * fontscale))
        ax.legend(fontsize=int(10 * fontscale))
        ax.tick_params(labelsize=int(9 * fontscale))
        ax.grid(alpha=0.3)
        return True

    # 3a: Individual QQ-plots (one per config, larger)
    for arch, ram, cpu, auth, title, filename in qq_configs:
        fig, ax = plt.subplots(figsize=(7, 6))
        _plot_qq(ax, arch, ram, cpu, auth, title, fontscale=1.2)
        plt.tight_layout()
        path = f"{PLOT_DIR}/{filename}"
        fig.savefig(path, bbox_inches='tight', dpi=300)
        print(f"  Saved: {path}")
        plt.close()

    # 3b: Combined QQ-plot (enlarged)
    fig, axes = plt.subplots(1, 3, figsize=(18, 7))
    for ax, (arch, ram, cpu, auth, title, _) in zip(axes, qq_configs):
        _plot_qq(ax, arch, ram, cpu, auth, title, fontscale=1.0)
    fig.suptitle('QQ-Plots: Latenzverteilung vs. Normalverteilung (Auth-Only, Baseline)',
                 fontweight='bold', fontsize=13)
    plt.tight_layout()
    path = f"{PLOT_DIR}/qq_latency.pdf"
    fig.savefig(path, bbox_inches='tight', dpi=300)
    print(f"  Saved: {path}")
    plt.close()

    # ── Plot 4: Cognito Tri-Modal Distribution ──
    print("\n4. Cognito Tri-Modal Distribution")
    eid = find_experiment('faas', 512, 0, 'service-integrated')
    if eid:
        df = load_latencies(eid, 'faas', auth_only=True, phase='Baseline', max_n=50000)
        if not df.empty:
            lat = df['latency_ms'].values

            fig, axes = plt.subplots(1, 2, figsize=(14, 6))

            # Histogram + KDE
            ax = axes[0]
            # Clip to reasonable range for visualization
            lat_clipped = lat[(lat > 0) & (lat < 1000)]
            ax.hist(lat_clipped, bins=100, density=True, alpha=0.5, color='#3498db',
                   edgecolor='none', label='Histogram')

            # KDE
            from scipy.stats import gaussian_kde
            kde = gaussian_kde(lat_clipped, bw_method=0.03)
            x_kde = np.linspace(0, 800, 500)
            ax.plot(x_kde, kde(x_kde), color='#e74c3c', linewidth=2, label='KDE')

            # Mode regions (latency bands); shares are computed from the data,
            # not hard-coded. The original labels claimed ~23% / ~43% / ~33%
            # based on an earlier dataset — the values below replace that
            # static text with the observed shares of the loaded experiment.
            mode_bands = [
                (50, 100, 'Cached (gecacht)', '#2ecc71'),
                (100, 200, 'Warm (Revalidierung)', '#f39c12'),
                (200, 500, 'Cold (JWKS-Abruf)', '#e74c3c'),
            ]
            mode_shares = []
            for lo, hi, label, color in mode_bands:
                pct = float(np.mean((lat >= lo) & (lat < hi)) * 100.0)
                mode_shares.append({
                    'mode': label,
                    'lo_ms': lo,
                    'hi_ms': hi,
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

            # CDF with mode boundaries
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
            print(f"  Saved: {path}")
            plt.close()

            # Persist measured shares so the thesis table can cite a
            # reproducible artefact rather than a figure annotation.
            shares_df = pd.DataFrame(mode_shares)
            shares_csv = f"{PLOT_DIR}/cognito_trimodal_shares.csv"
            shares_df.to_csv(shares_csv, index=False)
            print(f"  Saved: {shares_csv}")
            for r in mode_shares:
                print(f"    {r['mode']:<28s} [{r['lo_ms']:>3d},{r['hi_ms']:>3d}) ms: "
                      f"{r['share_pct']:5.1f}%  (n={r['n_requests']}/{r['n_total']})")

    # ── Plot 5: Skewness and Kurtosis Summary ──
    print("\n5. Distribution Statistics Summary")
    stats_rows = []
    for arch, ram, cpu, auth, label in [
        ('faas', 512, 0, 'none', 'FaaS/512/None'),
        ('faas', 512, 0, 'service-integrated', 'FaaS/512/Cognito'),
        ('faas', 512, 0, 'service-integrated-manual', 'FaaS/512/Manual'),
        ('faas', 512, 0, 'edge', 'FaaS/512/Edge'),
        ('microservices', 2048, 1.0, 'none', 'MS/L/None'),
        ('microservices', 2048, 1.0, 'service-integrated', 'MS/L/Cognito'),
        ('monolith', 2048, 1.0, 'none', 'Mono/L/None'),
        ('monolith', 2048, 1.0, 'service-integrated', 'Mono/L/Cognito'),
    ]:
        eid = find_experiment(arch, ram, cpu, auth)
        if eid is None:
            continue
        df = load_latencies(eid, arch, auth_only=True, phase='Baseline', max_n=50000)
        if df.empty:
            continue
        lat = df['latency_ms'].values
        stats_rows.append({
            'config': label,
            'n': len(lat),
            'mean': np.mean(lat),
            'median': np.median(lat),
            'std': np.std(lat),
            'skewness': sp_stats.skew(lat),
            'kurtosis': sp_stats.kurtosis(lat),
            'p5': np.percentile(lat, 5),
            'p50': np.percentile(lat, 50),
            'p95': np.percentile(lat, 95),
            'p99': np.percentile(lat, 99),
            'iqr': np.percentile(lat, 75) - np.percentile(lat, 25),
        })

    if stats_rows:
        stats_df = pd.DataFrame(stats_rows)
        stats_df.to_csv(f"{PLOT_DIR}/distribution_statistics.csv", index=False)
        print(f"  Saved: {PLOT_DIR}/distribution_statistics.csv")

        print("\n  Distribution Statistics (Auth-Only, Baseline):")
        print(f"  {'Config':>25s} | {'Mean':>8s} | {'Median':>8s} | {'Skew':>7s} | {'Kurt':>7s} | {'IQR':>7s}")
        for _, r in stats_df.iterrows():
            print(f"  {r['config']:>25s} | {r['mean']:>7.1f}ms | {r['median']:>7.1f}ms | "
                  f"{r['skewness']:>7.2f} | {r['kurtosis']:>7.2f} | {r['iqr']:>6.1f}ms")

    print("\n" + "=" * 70)
    print("DONE — Script 37")
    print("=" * 70)


if __name__ == '__main__':
    main()
