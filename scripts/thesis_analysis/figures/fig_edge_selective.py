#!/usr/bin/env python3
"""Generate edge_selective_comparison.pdf for fig:edge-selective.

Grouped bar chart comparing P99 latency of Edge-Selective vs Full-Edge vs
None, grouped by architecture and hardware tier.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, EXCLUDED_EXPERIMENTS, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
    'edge-selective': 'Edge-Sel.',
}
MIN_REQUESTS = 50_000
MIN_PHASES = 7


def _discover_edge_selective_ids():
    excl = ','.join(str(x) for x in EXCLUDED_EXPERIMENTS)
    df = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
               COUNT(r.id) AS n_requests,
               COUNT(DISTINCT r.phase_name) AS n_phases
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE e.auth_strategy = 'edge-selective'
          AND e.id NOT IN ({excl})
        GROUP BY e.id, e.architecture, e.auth_strategy, e.with_cloudfront,
                 e.ram_in_mb, e.cpu_in_vcpu
        ORDER BY e.id
    """)
    return df[(df['n_requests'] > MIN_REQUESTS) & (df['n_phases'] >= MIN_PHASES)]


def main():
    es_df = _discover_edge_selective_ids()
    if es_df.empty:
        print('No edge-selective experiments'); return
    es_ids_sql = ','.join(str(x) for x in es_df['id'].tolist())

    hw_configs = es_df[['architecture', 'ram_in_mb', 'cpu']].drop_duplicates()
    comparison_rows = []

    for _, hw in hw_configs.iterrows():
        arch = hw['architecture']
        ram = int(hw['ram_in_mb'])
        cpu = hw['cpu']
        cpu_clause = "AND e.cpu_in_vcpu IS NULL" if pd.isna(cpu) or cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

        if arch == 'faas':
            hlabel = f"{ram}MB"
        else:
            hlabel = {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(float(cpu) if pd.notna(cpu) else 0, f"{cpu}vCPU")

        es_q = query_df(f"""
            SELECT 'edge-selective' AS auth_strategy,
                   COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                       FILTER (WHERE NOT r.is_error) AS p99
            FROM experiments e JOIN requests r ON r.experiment_id = e.id
            WHERE e.id IN ({es_ids_sql})
              AND e.architecture = '{arch}' AND e.ram_in_mb = {ram} {cpu_clause}
              AND e.auth_strategy = 'edge-selective' AND r.phase_name = 'Baseline'
            GROUP BY 1 HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)
        ref_q = query_df(f"""
            SELECT e.auth_strategy,
                   COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                       FILTER (WHERE NOT r.is_error) AS p99
            FROM experiments e JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL}
              AND e.architecture = '{arch}' AND e.ram_in_mb = {ram} {cpu_clause}
              AND e.auth_strategy IN ('none', 'edge') AND r.phase_name = 'Baseline'
              AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
            GROUP BY e.auth_strategy HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)
        combined = pd.concat([es_q, ref_q], ignore_index=True)
        if combined.empty:
            continue
        combined['p99'] = combined['p99'].astype(float)
        for _, row in combined.iterrows():
            comparison_rows.append({
                'architecture': arch, 'hw_tier': hlabel,
                'auth_strategy': row['auth_strategy'],
                'auth_label': AUTH_SHORT.get(row['auth_strategy'], row['auth_strategy']),
                'P99': round(float(row['p99']), 1),
            })

    comparison_df = pd.DataFrame(comparison_rows)
    if comparison_df.empty:
        print('No comparison data'); return

    archs_with_data = comparison_df['architecture'].unique()
    n_archs = len(archs_with_data)
    fig, axes = plt.subplots(1, max(n_archs, 1), figsize=(6 * max(n_archs, 1), 6))
    if n_archs == 1:
        axes = [axes]

    for ax, arch in zip(axes, archs_with_data):
        arch_data = comparison_df[comparison_df['architecture'] == arch]
        hw_tiers = sorted(arch_data['hw_tier'].unique(),
                          key=lambda x: {'S': 1, 'M': 2, 'L': 3, 'XL': 4}.get(
                              x, int(x.replace('MB', '')) if 'MB' in x else 0))
        auth_strategies = ['none', 'edge-selective', 'edge']
        auth_present = [a for a in auth_strategies if a in arch_data['auth_strategy'].values]
        x = np.arange(len(hw_tiers))
        width = 0.8 / max(len(auth_present), 1)

        for i, auth in enumerate(auth_present):
            vals = []
            for hw in hw_tiers:
                match = arch_data[(arch_data['auth_strategy'] == auth) & (arch_data['hw_tier'] == hw)]
                vals.append(match.iloc[0]['P99'] if not match.empty else 0)
            offset = (i - len(auth_present) / 2 + 0.5) * width
            label = AUTH_SHORT.get(auth, auth)
            color = AUTH_COLORS.get(label, '#999999')
            bars = ax.bar(x + offset, vals, width, label=label, color=color, alpha=0.85)
            for bar, val in zip(bars, vals):
                if val > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                            f'{val:.0f}', ha='center', va='bottom', fontsize=7)

        ax.set_xticks(x)
        ax.set_xticklabels(hw_tiers, fontsize=10)
        ax.set_ylabel('P99 Latency (ms)', fontsize=11)
        ax.set_title(f'{arch.capitalize()}', fontweight='bold', fontsize=12)
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('Edge-Selective vs Full-Edge vs None: P99 Latency Comparison\n'
                 '(Baseline phase, all endpoints)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/edge_selective_comparison.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
