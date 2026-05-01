#!/usr/bin/env python3
"""
03 - Phase-by-Phase Analysis (RQ2)
Analyzes how auth overhead changes across SCNAST phases.
Shows DeltaAuth per phase to test multiplication model under load.
Outputs: phase_latency_heatmap.pdf, phase_delta_auth.pdf, phase_throughput.pdf
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

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}

def main():
    print("=" * 70)
    print("03 - PHASE-BY-PHASE ANALYSIS")
    print("=" * 70)

    # Get per-phase latency percentiles for all experiments
    df = query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.architecture,
            e.auth_strategy,
            e.password_hash_algorithm AS hash_algo,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            r.phase_name,
            r.phase_index,
            COUNT(*) AS request_count,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS error_count,
            COUNT(CASE WHEN r.status_code = 401 THEN 1 END) AS soft_fails,
            COUNT(CASE WHEN r.is_timeout THEN 1 END) AS timeouts,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99,
            AVG(r.latency_ms) FILTER (WHERE NOT r.is_error) AS mean_ms
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name IS NOT NULL AND r.phase_name != 'None'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.auth_strategy,
                 e.password_hash_algorithm, e.ram_in_mb, e.cpu_in_vcpu,
                 r.phase_name, r.phase_index
        HAVING COUNT(*) > 100
        ORDER BY e.id, r.phase_index
    """)

    df['error_rate'] = (df['error_count'] / df['request_count'] * 100).round(2)
    df['soft_fail_rate'] = (df['soft_fails'] / df['request_count'] * 100).round(2)

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

    print(f"\nPhase-level records: {len(df)}")

    # --- PLOT 1: Phase latency heatmaps per architecture ---
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = df[df['architecture'] == arch]
        if arch_df.empty:
            continue

        # Pick best experiment per auth×hw (most total requests)
        totals = arch_df.groupby(['experiment_id', 'auth_strategy', 'hw'])['request_count'].sum()
        best_exps = totals.reset_index().sort_values('request_count', ascending=False)
        best_exps = best_exps.drop_duplicates(subset=['auth_strategy', 'hw'], keep='first')

        # Filter to a single representative hw tier
        hw_counts = best_exps.groupby('hw').size()
        if hw_counts.empty:
            continue
        best_hw = hw_counts.idxmax()
        hw_exps = best_exps[best_exps['hw'] == best_hw]['experiment_id'].tolist()
        plot_df = arch_df[arch_df['experiment_id'].isin(hw_exps)]

        fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [2, 1]})

        # Top: P99 latency per phase per auth strategy
        ax = axes[0]
        for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
            auth_data = plot_df[plot_df['auth_strategy'] == auth]
            if auth_data.empty:
                continue
            # Average across experiments if multiple
            phase_avg = auth_data.groupby('phase_name')[['p99', 'p50', 'p95']].mean()
            phase_order_present = [p for p in PHASE_ORDER if p in phase_avg.index]
            if not phase_order_present:
                continue
            phase_avg = phase_avg.loc[phase_order_present]
            ax.plot(range(len(phase_order_present)), phase_avg['p99'], 'o-',
                   label=f"{AUTH_SHORT.get(auth, auth)} (P99)",
                   color=AUTH_COLORS.get(AUTH_SHORT.get(auth, auth), '#999'), linewidth=2, markersize=6)

        ax.set_xticks(range(len(PHASE_ORDER)))
        ax.set_xticklabels(PHASE_ORDER, rotation=30, ha='right', fontsize=9)
        ax.set_ylabel('P99 Latency (ms)')
        ax.set_title(f'{arch} — P99 Latency by Phase ({best_hw})', fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

        # Bottom: Request count and error rate per phase
        ax2 = axes[1]
        auth_order = ['none', 'service-integrated', 'service-integrated-manual', 'edge']
        for idx, auth in enumerate(auth_order):
            auth_data = plot_df[plot_df['auth_strategy'] == auth]
            if auth_data.empty:
                continue
            phase_sum = auth_data.groupby('phase_name')['request_count'].sum()
            phase_order_present = [p for p in PHASE_ORDER if p in phase_sum.index]
            if not phase_order_present:
                continue
            phase_sum = phase_sum.loc[phase_order_present]
            short_label = AUTH_SHORT.get(auth, auth)
            ax2.bar(np.arange(len(phase_order_present)) + idx * 0.2 - 0.3,
                   phase_sum.values, width=0.2,
                   label=short_label,
                   color=AUTH_COLORS.get(short_label, '#999'), alpha=0.7)

        ax2.set_xticks(range(len(PHASE_ORDER)))
        ax2.set_xticklabels(PHASE_ORDER, rotation=30, ha='right', fontsize=9)
        ax2.set_ylabel('Request Count')
        ax2.set_title('Requests per Phase', fontweight='bold')
        ax2.legend(fontsize=8)
        ax2.grid(axis='y', alpha=0.3)

        plt.tight_layout()
        path = f"{PLOT_DIR}/phase_latency_{arch}_{best_hw}.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # --- PLOT 2: DeltaAuth per phase ---
    print("\n--- DELTA_AUTH PER PHASE ---")
    delta_rows = []
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = df[df['architecture'] == arch]
        none_df = arch_df[arch_df['auth_strategy'] == 'none']
        if none_df.empty:
            continue

        # Get unique hw tiers with none baseline
        hw_tiers = none_df['hw'].unique()
        for hw in hw_tiers:
            none_hw = none_df[none_df['hw'] == hw]
            # Average across experiments for this baseline
            none_phase_avg = none_hw.groupby('phase_name')[['p50', 'p95', 'p99']].mean()

            for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                auth_hw = arch_df[(arch_df['auth_strategy'] == auth) & (arch_df['hw'] == hw)]
                if auth_hw.empty:
                    continue
                auth_phase_avg = auth_hw.groupby('phase_name')[['p50', 'p95', 'p99']].mean()

                for phase in PHASE_ORDER:
                    if phase in none_phase_avg.index and phase in auth_phase_avg.index:
                        delta_rows.append({
                            'architecture': arch,
                            'auth_strategy': auth,
                            'hw': hw,
                            'phase': phase,
                            'delta_p50': auth_phase_avg.loc[phase, 'p50'] - none_phase_avg.loc[phase, 'p50'],
                            'delta_p95': auth_phase_avg.loc[phase, 'p95'] - none_phase_avg.loc[phase, 'p95'],
                            'delta_p99': auth_phase_avg.loc[phase, 'p99'] - none_phase_avg.loc[phase, 'p99'],
                        })

    delta_phase = pd.DataFrame(delta_rows)
    if not delta_phase.empty:
        delta_phase.to_csv(f"{PLOT_DIR}/delta_auth_per_phase.csv", index=False)
        print(f"Saved: {PLOT_DIR}/delta_auth_per_phase.csv")

        # Plot DeltaAuth per phase for each architecture
        for arch in delta_phase['architecture'].unique():
            arch_delta = delta_phase[delta_phase['architecture'] == arch]
            fig, ax = plt.subplots(figsize=(12, 6))

            for _, group_key in arch_delta.groupby(['auth_strategy', 'hw']).size().reset_index().iterrows():
                auth = group_key['auth_strategy']
                hw = group_key['hw']
                subset = arch_delta[(arch_delta['auth_strategy'] == auth) & (arch_delta['hw'] == hw)]
                phase_order_present = [p for p in PHASE_ORDER if p in subset['phase'].values]
                if not phase_order_present:
                    continue
                subset_ordered = subset.set_index('phase').loc[phase_order_present]
                ax.plot(range(len(phase_order_present)), subset_ordered['delta_p99'], 'o-',
                       label=f"{AUTH_SHORT.get(auth, auth)} ({hw})",
                       linewidth=2, markersize=6)

            ax.set_xticks(range(len(PHASE_ORDER)))
            ax.set_xticklabels(PHASE_ORDER, rotation=30, ha='right', fontsize=9)
            ax.set_ylabel('$\\Delta_{Auth}$ P99 (ms)')
            ax.set_title(f'{arch} — Auth Overhead per SCNAST Phase', fontweight='bold')
            ax.axhline(y=0, color='black', linewidth=0.5, linestyle='--')
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            plt.tight_layout()
            path = f"{PLOT_DIR}/delta_auth_per_phase_{arch}.pdf"
            fig.savefig(path, bbox_inches='tight')
            print(f"Saved: {path}")
            plt.close()

    # --- PRINT: Phase summary table ---
    print("\n--- PHASE SUMMARY TABLE (selected experiments) ---")
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = df[df['architecture'] == arch]
        if arch_df.empty:
            continue
        print(f"\n{arch.upper()}:")
        # Pick one representative per auth strategy
        totals = arch_df.groupby('experiment_id')['request_count'].sum()
        for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
            auth_exps = arch_df[arch_df['auth_strategy'] == auth]['experiment_id'].unique()
            if len(auth_exps) == 0:
                continue
            # Best by total requests
            best_exp = totals.loc[totals.index.isin(auth_exps)].idxmax()
            exp_data = arch_df[arch_df['experiment_id'] == best_exp]
            print(f"\n  Exp {best_exp} ({auth}, {exp_data.iloc[0]['hw']}):")
            print(f"    {'Phase':>20s} {'Reqs':>8s} {'P50':>8s} {'P95':>8s} {'P99':>8s} {'Err%':>6s} {'SF%':>6s}")
            for phase in PHASE_ORDER:
                pdata = exp_data[exp_data['phase_name'] == phase]
                if pdata.empty:
                    continue
                r = pdata.iloc[0]
                print(f"    {phase:>20s} {r['request_count']:>8,} {r['p50']:>8.1f} {r['p95']:>8.1f} "
                      f"{r['p99']:>8.1f} {r['error_rate']:>5.1f}% {r['soft_fail_rate']:>5.1f}%")


if __name__ == '__main__':
    main()