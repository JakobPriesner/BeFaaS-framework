#!/usr/bin/env python3
"""Generate edge_selective_cf_overhead.pdf for fig:cf-overhead.

CloudFront overhead isolation for FaaS: compares P99 latency of
None (no CF), None+CF, Edge-Selective (no CF), Edge-Selective+CF
across FaaS RAM tiers.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, EXCLUDED_EXPERIMENTS

MIN_REQUESTS = 50_000
MIN_PHASES = 7


def _discover_ids():
    excl = ','.join(str(x) for x in EXCLUDED_EXPERIMENTS)
    es_df = query_df(f"""
        SELECT e.id, COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, COUNT(r.id) AS n_requests, COUNT(DISTINCT r.phase_name) AS n_phases
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE e.auth_strategy = 'edge-selective' AND e.architecture = 'faas'
              AND e.id NOT IN ({excl})
        GROUP BY e.id, e.with_cloudfront, e.ram_in_mb
    """)
    es_df = es_df[(es_df['n_requests'] > MIN_REQUESTS) & (es_df['n_phases'] >= MIN_PHASES)]
    cf_faas = es_df[es_df['with_cf'] == True]['id'].tolist()
    no_cf_faas = es_df[es_df['with_cf'] == False]['id'].tolist()

    cf_base = query_df(f"""
        SELECT e.id, COUNT(r.id) AS n_requests, COUNT(DISTINCT r.phase_name) AS n_phases
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE e.auth_strategy = 'none' AND e.architecture = 'faas'
              AND COALESCE(e.with_cloudfront, false) = true AND e.id NOT IN ({excl})
        GROUP BY e.id
    """)
    cf_baselines = cf_base[(cf_base['n_requests'] > MIN_REQUESTS) & (cf_base['n_phases'] >= MIN_PHASES)]['id'].tolist()
    return cf_faas, no_cf_faas, cf_baselines


def main():
    cf_faas, no_cf_faas, cf_baselines = _discover_ids()
    cf_groups = {
        'ES + CF': cf_faas, 'ES no CF': no_cf_faas, 'None + CF': cf_baselines,
    }

    cf_rows = []
    for group_name, exp_ids in cf_groups.items():
        if not exp_ids:
            continue
        ids_sql = ','.join(str(x) for x in exp_ids)
        cf_df = query_df(f"""
            SELECT e.id, e.ram_in_mb,
                   COUNT(*) FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS n_success,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                       FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p99
            FROM experiments e JOIN requests r ON r.experiment_id = e.id
            WHERE e.id IN ({ids_sql})
            GROUP BY e.id, e.ram_in_mb
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') > 50
        """)
        if cf_df.empty:
            continue
        cf_df['p99'] = cf_df['p99'].astype(float)
        for _, row in cf_df.iterrows():
            cf_rows.append({
                'group': group_name, 'ram_in_mb': int(row['ram_in_mb']),
                'P99': round(float(row['p99']), 1),
            })

    faas_none_df = query_df(f"""
        SELECT e.ram_in_mb,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = 'faas' AND e.auth_strategy = 'none'
          AND e.ram_in_mb IN (256, 512, 1024) AND r.phase_name = 'Baseline'
          AND NOT r.is_error AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.ram_in_mb HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)
    if not faas_none_df.empty:
        faas_none_df['p99'] = faas_none_df['p99'].astype(float)
        for _, row in faas_none_df.iterrows():
            cf_rows.append({
                'group': 'None no CF', 'ram_in_mb': int(row['ram_in_mb']),
                'P99': round(float(row['p99']), 1),
            })

    cf_result = pd.DataFrame(cf_rows)
    if cf_result.empty:
        print('No CF overhead data'); return

    ram_tiers = sorted(cf_result['ram_in_mb'].unique())
    groups_to_plot = ['None no CF', 'None + CF', 'ES no CF', 'ES + CF']
    group_colors = {
        'None no CF': '#999999', 'None + CF': '#BDBDBD',
        'ES no CF': '#FF9800', 'ES + CF': '#E65100',
    }

    fig, axes = plt.subplots(1, len(ram_tiers), figsize=(6 * len(ram_tiers), 6))
    if len(ram_tiers) == 1:
        axes = [axes]

    for ax, ram in zip(axes, ram_tiers):
        ram_data = cf_result[cf_result['ram_in_mb'] == ram]
        groups_present = [g for g in groups_to_plot if g in ram_data['group'].values]
        x = np.arange(len(groups_present))
        p99_vals = [ram_data[ram_data['group'] == g]['P99'].mean() if not ram_data[ram_data['group'] == g].empty else 0 for g in groups_present]
        colors = [group_colors.get(g, '#999') for g in groups_present]

        bars = ax.bar(x, p99_vals, color=colors, alpha=0.85)
        for bar, val in zip(bars, p99_vals):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                        f'{val:.0f}ms', ha='center', va='bottom', fontsize=9, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(groups_present, fontsize=8, rotation=20, ha='right')
        ax.set_ylabel('P99 Latency (ms)', fontsize=11)
        ax.set_title(f'FaaS {ram}MB', fontweight='bold', fontsize=12)
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('CloudFront Overhead: Edge-Selective With vs Without CloudFront\n'
                 '(FaaS, Baseline phase, P99)', fontsize=13, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/edge_selective_cf_overhead.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
