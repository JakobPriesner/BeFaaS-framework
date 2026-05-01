#!/usr/bin/env python3
"""
07 - Error Analysis
Analyzes error patterns: expected 401s vs unexpected errors, timeouts, phase-specific failures.
Identifies survivorship bias candidates.
Outputs: error_analysis.pdf, error_timeline.pdf, survivorship_bias.csv
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

PHASE_ORDER = ['Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
               'Flash Crowd', 'Step Down', 'Cool-down']


def main():
    print("=" * 70)
    print("07 - ERROR ANALYSIS")
    print("=" * 70)

    # 1. Error breakdown per experiment per phase
    df = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.auth_strategy,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            r.phase_name,
            COUNT(*) AS total_requests,
            COUNT(CASE WHEN r.status_code = 401 THEN 1 END) AS soft_fails_401,
            COUNT(CASE WHEN r.status_code >= 500 THEN 1 END) AS server_errors,
            COUNT(CASE WHEN r.is_timeout THEN 1 END) AS timeouts,
            COUNT(CASE WHEN r.is_error AND r.status_code != 401 THEN 1 END) AS hard_errors,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS total_errors
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name IS NOT NULL AND r.phase_name != 'None'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu, r.phase_name
        ORDER BY e.id, r.phase_name
    """)

    df['soft_fail_rate'] = (df['soft_fails_401'] / df['total_requests'] * 100).round(2)
    df['hard_error_rate'] = (df['hard_errors'] / df['total_requests'] * 100).round(2)
    df['timeout_rate'] = (df['timeouts'] / df['total_requests'] * 100).round(2)

    def hw_label(row):
        if row['architecture'] == 'faas':
            return f"{row['ram_in_mb']}MB"
        cpu = row['cpu_in_vcpu']
        if cpu == 4.0: return 'XL'
        elif cpu == 1.0: return 'L'
        elif cpu == 0.5: return 'M'
        elif cpu == 0.25: return 'S'
        return f"{cpu}vCPU"
    df['hw'] = df.apply(hw_label, axis=1)

    # 2. Identify experiments with unexpected errors
    exp_totals = df.groupby(['experiment_id', 'architecture', 'auth_strategy', 'hw']).agg({
        'total_requests': 'sum',
        'soft_fails_401': 'sum',
        'hard_errors': 'sum',
        'timeouts': 'sum',
        'server_errors': 'sum',
    }).reset_index()
    exp_totals['hard_error_rate'] = (exp_totals['hard_errors'] / exp_totals['total_requests'] * 100).round(2)

    print("\n--- EXPERIMENTS WITH HARD ERRORS (>0.5%) ---")
    hard_err_exps = exp_totals[exp_totals['hard_error_rate'] > 0.5].sort_values('hard_error_rate', ascending=False)
    for _, r in hard_err_exps.iterrows():
        print(f"  Exp {r['experiment_id']:.0f}: {r['architecture']} {r['auth_strategy']} {r['hw']} "
              f"-> {r['hard_error_rate']:.1f}% hard errors "
              f"({r['hard_errors']:.0f} hard, {r['timeouts']:.0f} timeouts, {r['server_errors']:.0f} 5xx)")

    print("\n--- EXPECTED SOFT FAILS (401s are expected in auth experiments) ---")
    for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
        subset = exp_totals[exp_totals['auth_strategy'] == auth]
        if subset.empty:
            continue
        avg_sf_rate = (subset['soft_fails_401'].sum() / subset['total_requests'].sum() * 100)
        print(f"  {auth:30s}: avg soft-fail rate = {avg_sf_rate:.2f}% "
              f"(total 401s: {subset['soft_fails_401'].sum():,})")

    # --- PLOT 1: Error type breakdown per architecture ---
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_totals = exp_totals[exp_totals['architecture'] == arch]
        if arch_totals.empty:
            ax.set_title(f'{arch} (no data)')
            continue

        # Aggregate by auth strategy
        auth_agg = arch_totals.groupby('auth_strategy').agg({
            'total_requests': 'sum',
            'soft_fails_401': 'sum',
            'hard_errors': 'sum',
            'timeouts': 'sum',
        }).reindex(['none', 'service-integrated', 'service-integrated-manual', 'edge']).dropna()

        if auth_agg.empty:
            continue

        x = np.arange(len(auth_agg))
        width = 0.25
        ax.bar(x - width, auth_agg['soft_fails_401'] / auth_agg['total_requests'] * 100,
               width, label='401 (expected)', color='#f39c12', alpha=0.8)
        ax.bar(x, auth_agg['timeouts'] / auth_agg['total_requests'] * 100,
               width, label='Timeouts', color='#e74c3c', alpha=0.8)
        ax.bar(x + width, (auth_agg['hard_errors'] - auth_agg['timeouts']).clip(0) / auth_agg['total_requests'] * 100,
               width, label='Other errors', color='#9b59b6', alpha=0.8)

        ax.set_xticks(x)
        ax.set_xticklabels(['None', 'Cognito', 'Manual', 'Edge'][:len(auth_agg)],
                          fontsize=9, rotation=20, ha='right')
        ax.set_ylabel('Error Rate (%)')
        ax.set_title(f'{arch}', fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('Error Type Breakdown by Architecture & Auth Strategy', fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/error_type_breakdown.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"\nSaved: {path}")
    plt.close()

    # --- PLOT 2: Survivorship bias detection ---
    # Compare request count with/without auth in same phase
    print("\n--- SURVIVORSHIP BIAS DETECTION ---")
    print("Phases where auth experiments have significantly fewer requests than none baseline:")

    bias_rows = []
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = df[df['architecture'] == arch]
        none_phases = arch_df[arch_df['auth_strategy'] == 'none'].groupby('phase_name')['total_requests'].mean()

        for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
            auth_phases = arch_df[arch_df['auth_strategy'] == auth].groupby('phase_name')['total_requests'].mean()

            for phase in PHASE_ORDER:
                if phase in none_phases.index and phase in auth_phases.index:
                    none_req = none_phases[phase]
                    auth_req = auth_phases[phase]
                    dropout = (1 - auth_req / none_req) * 100 if none_req > 0 else 0
                    bias_rows.append({
                        'architecture': arch,
                        'auth_strategy': auth,
                        'phase': phase,
                        'none_requests': none_req,
                        'auth_requests': auth_req,
                        'dropout_pct': dropout,
                    })
                    if dropout > 20:
                        print(f"  {arch}/{auth}/{phase}: {dropout:.1f}% fewer requests "
                              f"(none: {none_req:,.0f}, auth: {auth_req:,.0f})")

    bias_df = pd.DataFrame(bias_rows)
    if not bias_df.empty:
        bias_df.to_csv(f"{PLOT_DIR}/survivorship_bias.csv", index=False)

        # Plot dropout rates
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))
        for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
            arch_bias = bias_df[bias_df['architecture'] == arch]
            if arch_bias.empty:
                ax.set_title(f'{arch} (no data)')
                continue

            for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                subset = arch_bias[arch_bias['auth_strategy'] == auth]
                if subset.empty:
                    continue
                phases = [p for p in PHASE_ORDER if p in subset['phase'].values]
                if not phases:
                    continue
                vals = [subset[subset['phase'] == p]['dropout_pct'].values[0] for p in phases]
                ax.plot(range(len(phases)), vals, 'o-',
                       label=auth.replace('service-integrated', 'Cognito').replace('-manual', ' Manual'),
                       color=AUTH_COLORS.get(auth, '#999'), linewidth=2)

            ax.set_xticks(range(len(PHASE_ORDER)))
            ax.set_xticklabels(PHASE_ORDER, rotation=35, ha='right', fontsize=8)
            ax.set_ylabel('Request Dropout (%)')
            ax.set_title(f'{arch}', fontweight='bold')
            ax.axhline(y=0, color='black', linewidth=0.5)
            ax.axhline(y=20, color='red', linewidth=0.5, linestyle='--', alpha=0.5)
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)

        fig.suptitle('Survivorship Bias: Request Dropout vs None Baseline per Phase',
                     fontsize=14, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/survivorship_bias.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # --- PLOT 3: Error timeline for specific experiments ---
    # Get time-bucketed error rates for representative experiments
    for arch in ['microservices', 'monolith']:
        # Pick an experiment with visible error patterns
        candidates = exp_totals[(exp_totals['architecture'] == arch) &
                               (exp_totals['auth_strategy'] == 'service-integrated') &
                               (exp_totals['hard_error_rate'] > 1)]
        if candidates.empty:
            continue
        exp_id = int(candidates.iloc[0]['experiment_id'])

        timeline = query_df(f"""
            SELECT
                (r.relative_time_ms / 30000)::int * 30 AS time_bucket_s,
                COUNT(*) AS requests,
                COUNT(CASE WHEN r.is_error THEN 1 END) AS errors,
                COUNT(CASE WHEN r.is_timeout THEN 1 END) AS timeouts,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p95
            FROM requests r
            WHERE r.experiment_id = {exp_id}
              AND r.relative_time_ms IS NOT NULL
            GROUP BY time_bucket_s
            ORDER BY time_bucket_s
        """)

        if timeline.empty:
            continue

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
        t = timeline['time_bucket_s'] / 60  # minutes

        ax1.plot(t, timeline['requests'], '-', color='#3498db', label='Total requests', linewidth=1.5)
        ax1.fill_between(t, 0, timeline['errors'], color='#e74c3c', alpha=0.3, label='Errors')
        ax1.fill_between(t, 0, timeline['timeouts'], color='#f39c12', alpha=0.3, label='Timeouts')
        ax1.set_ylabel('Request Count (per 30s)')
        ax1.set_title(f'Error Timeline — Exp {exp_id} ({arch}, service-integrated)', fontweight='bold')
        ax1.legend(fontsize=9)
        ax1.grid(alpha=0.3)

        ax2.plot(t, timeline['p95'], '-', color='#e74c3c', linewidth=1.5)
        ax2.set_ylabel('P95 Latency (ms)')
        ax2.set_xlabel('Time (minutes)')
        ax2.grid(alpha=0.3)

        plt.tight_layout()
        path = f"{PLOT_DIR}/error_timeline_exp{exp_id}.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()


if __name__ == '__main__':
    main()
