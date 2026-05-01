#!/usr/bin/env python3
"""
16 — Phase-wise Auth Overhead Evolution (RQ2)
Analyzes how ΔAuth changes across SCNAST phases (Baseline → Flash Crowd → Step Down).
Key question: Does auth overhead amplify under load, or remain constant?
Outputs: delta_auth_per_phase.csv, delta_auth_per_phase_*.pdf,
         auth_amplification_factor.csv, auth_amplification.pdf
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}
PHASE_ORDER = ['Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
               'Flash Crowd', 'Step Down', 'Cool-down']


def main():
    print("=" * 70)
    print("16 — PHASE-WISE AUTH OVERHEAD EVOLUTION (RQ2)")
    print("=" * 70)

    # ── 1. Get per-phase percentiles per experiment ──
    df = query_df(f"""
        SELECT
            e.id, e.architecture, e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
            r.phase_name,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            COUNT(*) FILTER (WHERE r.is_error) AS n_errors,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.phase_name IS NOT NULL
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.id, e.architecture, e.auth_strategy, algo,
                 e.ram_in_mb, cpu, r.phase_name
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 100
    """)

    for col in ['p50', 'p95', 'p99']:
        df[col] = df[col].astype(float)

    df['success_rate'] = df['n_success'] / df['total'] * 100

    # ── 2. Compute per-phase ΔAuth ──
    # Average across experiments with same arch/auth/hw/phase
    avg = df.groupby(['architecture', 'auth_strategy', 'ram_in_mb', 'phase_name']).agg(
        p50=('p50', 'mean'), p95=('p95', 'mean'), p99=('p99', 'mean'),
        success_rate=('success_rate', 'mean'),
        n_experiments=('id', 'nunique')
    ).reset_index()

    phase_delta_rows = []
    for (arch, ram, phase), grp in avg.groupby(['architecture', 'ram_in_mb', 'phase_name']):
        none_row = grp[grp['auth_strategy'] == 'none']
        if none_row.empty:
            continue
        none_p50 = none_row.iloc[0]['p50']
        none_p95 = none_row.iloc[0]['p95']
        none_p99 = none_row.iloc[0]['p99']
        none_sr = none_row.iloc[0]['success_rate']

        for _, r in grp.iterrows():
            if r['auth_strategy'] == 'none':
                continue
            phase_delta_rows.append({
                'architecture': arch,
                'ram_in_mb': ram,
                'auth': AUTH_SHORT.get(r['auth_strategy'], r['auth_strategy']),
                'phase': phase,
                'none_p50': none_p50,
                'none_p99': none_p99,
                'auth_p50': r['p50'],
                'auth_p99': r['p99'],
                'delta_p50': r['p50'] - none_p50,
                'delta_p99': r['p99'] - none_p99,
                'none_success_rate': none_sr,
                'auth_success_rate': r['success_rate'],
                'success_rate_drop': none_sr - r['success_rate'],
            })

    phase_delta = pd.DataFrame(phase_delta_rows)
    phase_delta.to_csv(f"{PLOT_DIR}/delta_auth_per_phase.csv", index=False)
    print(f"Saved: {PLOT_DIR}/delta_auth_per_phase.csv")

    # ── 3. Phase evolution plots per architecture ──
    # Use largest hw tier per arch for clearest signal
    hw_picks = {'faas': None, 'microservices': None, 'monolith': None}
    for arch in hw_picks:
        arch_data = phase_delta[phase_delta['architecture'] == arch]
        if not arch_data.empty:
            hw_picks[arch] = arch_data['ram_in_mb'].max()

    for arch in ['faas', 'microservices', 'monolith']:
        ram = hw_picks.get(arch)
        if ram is None:
            continue

        arch_data = phase_delta[(phase_delta['architecture'] == arch) &
                                (phase_delta['ram_in_mb'] == ram)]
        if arch_data.empty:
            continue

        fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [2, 1]})

        # Top: ΔAuth P99 per phase
        ax = axes[0]
        for auth in ['Cognito', 'Manual', 'Edge']:
            auth_data = arch_data[arch_data['auth'] == auth]
            if auth_data.empty:
                continue
            # Order by SCNAST phase
            phase_vals = []
            phase_labels = []
            for phase in PHASE_ORDER:
                match = auth_data[auth_data['phase'] == phase]
                if not match.empty:
                    phase_vals.append(match.iloc[0]['delta_p99'])
                    phase_labels.append(phase)

            if phase_vals:
                ax.plot(range(len(phase_vals)), phase_vals, 'o-',
                        label=auth, color=AUTH_COLORS.get(auth, '#999'),
                        linewidth=2, markersize=8)

        ax.set_xticks(range(len(phase_labels)))
        ax.set_xticklabels(phase_labels, rotation=30, ha='right', fontsize=9)
        ax.set_ylabel('ΔAuth P99 (ms)')

        hw_str = f"{ram}MB" if arch == 'faas' else \
            {'512': 'S', '1024': 'M', '2048': 'L', '8192': 'XL'}.get(str(ram), str(ram))
        ax.set_title(f'{arch}: Auth Overhead Evolution Across SCNAST Phases ({hw_str})',
                     fontweight='bold')
        ax.legend()
        ax.grid(alpha=0.3)
        ax.axhline(y=0, color='black', linewidth=0.5)

        # Bottom: Success rate per phase
        ax2 = axes[1]
        for auth_strat in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
            auth_label = AUTH_SHORT.get(auth_strat, auth_strat)
            sr_vals = []
            sr_labels = []
            auth_avg = avg[(avg['architecture'] == arch) &
                           (avg['ram_in_mb'] == ram) &
                           (avg['auth_strategy'] == auth_strat)]
            for phase in PHASE_ORDER:
                match = auth_avg[auth_avg['phase_name'] == phase]
                if not match.empty:
                    sr_vals.append(match.iloc[0]['success_rate'])
                    sr_labels.append(phase)
            if sr_vals:
                color = AUTH_COLORS.get(auth_label, '#95a5a6')
                ax2.plot(range(len(sr_vals)), sr_vals, 's--',
                         label=auth_label, color=color, markersize=6, alpha=0.8)

        ax2.set_xticks(range(len(sr_labels)))
        ax2.set_xticklabels(sr_labels, rotation=30, ha='right', fontsize=9)
        ax2.set_ylabel('Success Rate (%)')
        ax2.set_ylim(0, 105)
        ax2.legend(fontsize=7)
        ax2.grid(alpha=0.3)
        ax2.axhline(y=90, color='red', linestyle='--', alpha=0.3, label='90% threshold')

        plt.tight_layout()
        path = f"{PLOT_DIR}/delta_auth_per_phase_{arch}.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # ── 4. Auth amplification factor ──
    # Compare ΔAuth at Baseline vs Flash Crowd / Step Down
    print("\n--- AUTH AMPLIFICATION FACTOR ---")
    print("  (ΔAuth at high-load phase / ΔAuth at Baseline)")

    amp_rows = []
    for _, r in phase_delta.iterrows():
        if r['phase'] == 'Baseline':
            # Find corresponding Flash Crowd and Step Down
            for load_phase in ['Flash Crowd', 'Step Down', 'Morning rush']:
                match = phase_delta[(phase_delta['architecture'] == r['architecture']) &
                                    (phase_delta['ram_in_mb'] == r['ram_in_mb']) &
                                    (phase_delta['auth'] == r['auth']) &
                                    (phase_delta['phase'] == load_phase)]
                if not match.empty and abs(r['delta_p99']) > 1:
                    amp = match.iloc[0]['delta_p99'] / r['delta_p99']
                    amp_rows.append({
                        'architecture': r['architecture'],
                        'ram_in_mb': r['ram_in_mb'],
                        'auth': r['auth'],
                        'baseline_delta_p99': r['delta_p99'],
                        'load_phase': load_phase,
                        'load_delta_p99': match.iloc[0]['delta_p99'],
                        'amplification': amp,
                        'baseline_sr': r['auth_success_rate'],
                        'load_sr': match.iloc[0]['auth_success_rate'],
                    })

    if amp_rows:
        amp_df = pd.DataFrame(amp_rows)
        amp_df.to_csv(f"{PLOT_DIR}/auth_amplification_factor.csv", index=False)
        print(f"Saved: {PLOT_DIR}/auth_amplification_factor.csv")

        # Plot: ΔAuth at Baseline vs Flash Crowd (absolute ms, side-by-side)
        # Use largest HW tier per arch for clearest signal
        amp_fc = amp_df[amp_df['load_phase'] == 'Flash Crowd'].copy()
        amp_fc = amp_fc[amp_fc['ram_in_mb'] != 1796]

        def to_hw_label(row):
            if row['architecture'] == 'faas':
                return f"{int(row['ram_in_mb'])}MB"
            return {512: 'S', 1024: 'M', 2048: 'L', 8192: 'XL'}.get(
                int(row['ram_in_mb']), str(int(row['ram_in_mb'])))
        amp_fc['hw'] = amp_fc.apply(to_hw_label, axis=1)

        # Pick 2 HW tiers per architecture: smallest and largest
        hw_picks = {
            'faas': ['256MB', '1769MB'],
            'microservices': ['S', 'XL'],
            'monolith': ['S', 'XL'],
        }

        fig, axes = plt.subplots(1, 3, figsize=(18, 7))
        for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
            arch_amp = amp_fc[amp_fc['architecture'] == arch]
            if arch_amp.empty:
                ax.set_title(f'{arch} (no data)')
                continue

            picks = hw_picks[arch]
            arch_amp = arch_amp[arch_amp['hw'].isin(picks)]

            # Build grouped horizontal bars: auth × hw, paired BL/FC
            auths = ['Cognito', 'Manual', 'Edge']
            labels = []
            bl_vals = []
            fc_vals = []

            for hw in picks:
                for auth in auths:
                    match = arch_amp[(arch_amp['hw'] == hw) & (arch_amp['auth'] == auth)]
                    if not match.empty:
                        r = match.iloc[0]
                        labels.append(f'{auth}\n({hw})')
                        bl_vals.append(r['baseline_delta_p99'])
                        fc_vals.append(r['load_delta_p99'])

            if not labels:
                ax.set_title(f'{arch} (no data)')
                continue

            y = np.arange(len(labels))
            height = 0.35
            bars_bl = ax.barh(y - height/2, bl_vals, height, label='Baseline',
                              color='#3498db', alpha=0.85)
            bars_fc = ax.barh(y + height/2, fc_vals, height, label='Flash Crowd',
                              color='#e74c3c', alpha=0.85)

            # Add value labels
            for bar, val in zip(bars_bl, bl_vals):
                x_pos = bar.get_width() + 10 if val >= 0 else bar.get_width() - 10
                ha = 'left' if val >= 0 else 'right'
                ax.text(x_pos, bar.get_y() + bar.get_height()/2,
                        f'{val:+.0f}ms', va='center', ha=ha, fontsize=8, color='#2980b9')
            for bar, val in zip(bars_fc, fc_vals):
                x_pos = bar.get_width() + 10 if val >= 0 else bar.get_width() - 10
                ha = 'left' if val >= 0 else 'right'
                ax.text(x_pos, bar.get_y() + bar.get_height()/2,
                        f'{val:+.0f}ms', va='center', ha=ha, fontsize=8, color='#c0392b')

            ax.set_yticks(y)
            ax.set_yticklabels(labels, fontsize=9)
            ax.set_xlabel('ΔAuth P99 (ms)')
            ax.set_title(f'{arch}', fontweight='bold', fontsize=12)
            ax.axvline(x=0, color='black', linewidth=0.5)
            ax.legend(fontsize=9)
            ax.grid(axis='x', alpha=0.3)

        fig.suptitle('Auth Overhead: Baseline vs Flash Crowd\n'
                     '(ΔAuth P99 in ms, smallest and largest HW tier)',
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/auth_amplification.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

        # Print summary
        print("\n  Key amplification findings:")
        for arch in ['faas', 'microservices', 'monolith']:
            fc = amp_df[(amp_df['architecture'] == arch) & (amp_df['load_phase'] == 'Flash Crowd')]
            if not fc.empty:
                print(f"\n  {arch.upper()} (Flash Crowd vs Baseline):")
                for _, r in fc.iterrows():
                    direction = "AMPLIFIES" if r['amplification'] > 1.5 else \
                                "STABLE" if 0.5 < r['amplification'] < 1.5 else "SHRINKS"
                    print(f"    {r['auth']:>8s} @ {r['ram_in_mb']}MB: "
                          f"×{r['amplification']:.2f} ({direction}) "
                          f"[BL: {r['baseline_delta_p99']:+.0f}ms → FC: {r['load_delta_p99']:+.0f}ms] "
                          f"SR: {r['baseline_sr']:.0f}% → {r['load_sr']:.0f}%")

    # ── 5. Summary insight ──
    print("\n" + "=" * 70)
    print("SUMMARY:")
    print("=" * 70)
    print("""
  The auth overhead behavior under load differs fundamentally by architecture:

  - FaaS: Auth overhead remains relatively CONSTANT across phases because
    each request gets dedicated resources. ΔAuth is additive and predictable.

  - Microservices: Auth overhead AMPLIFIES under load because auth
    verification competes for CPU with request handling on shared containers.
    The amplification is strongest for CPU-intensive auth (manual bcrypt).

  - Monolith: Auth overhead can SHRINK under extreme load due to survivorship
    bias — only fast requests survive the timeout, creating artificially
    low ΔAuth values.
""")


if __name__ == '__main__':
    main()
