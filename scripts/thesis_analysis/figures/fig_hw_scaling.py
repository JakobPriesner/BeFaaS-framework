#!/usr/bin/env python3
"""Generate delta_auth_hw_scaling_combined_log.pdf for fig:hw-scaling.

1×3 panel (FaaS | Microservices | Monolith) with symlog y-axis showing
auth-only ΔAuth P99 across all hardware tiers. Differentiates Manual
(bcrypt) vs Manual (argon2id) and CloudFront (+CF) variants as separate
lines with distinct markers and linestyles.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, AUTH_COLORS_DETAILED,
                           AUTH_MARKERS_DETAILED, AUTH_LINESTYLES, HW_TIERS_ALL)

PROTECTED_ENDPOINTS_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_ENDPOINTS_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)


def get_protected_endpoints(arch):
    return PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER


def compute_auth_only_p99(arch, ram, cpu):
    protected = get_protected_endpoints(arch)
    eps_sql = ','.join(f"'{e}'" for e in protected)
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"
    return query_df(f"""
        SELECT
            e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            COALESCE(e.with_cloudfront, false) AS with_cf,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = '{arch}'
          AND e.ram_in_mb = {ram}
          {cpu_clause}
          AND r.phase_name = 'Baseline'
          AND r.endpoint IN ({eps_sql})
        GROUP BY e.auth_strategy, algo, with_cf
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)


def main():
    arch_delta_data = {}

    for arch in ['faas', 'microservices', 'monolith']:
        tiers = HW_TIERS_ALL[arch]
        tier_data = {}
        for ram, cpu, hw_lbl in tiers:
            df = compute_auth_only_p99(arch, ram, cpu)
            if df.empty:
                continue
            df['p99'] = df['p99'].astype(float)
            tier_data[hw_lbl] = {}
            for _, row in df.iterrows():
                cf_bool = bool(row['with_cf'])
                label = auth_label_detailed(
                    row['auth_strategy'],
                    row['algo'] if row['auth_strategy'] == 'service-integrated-manual' else None,
                    cf_bool)
                tier_data[hw_lbl][label] = row['p99']

        delta_data = {}
        for hw_lbl in [t[2] for t in tiers]:
            if hw_lbl not in tier_data:
                continue
            none_p99 = tier_data[hw_lbl].get('None')
            none_cf_p99 = tier_data[hw_lbl].get('None+CF')
            for label, p99_val in tier_data[hw_lbl].items():
                if label.startswith('None'):
                    continue
                baseline = none_cf_p99 if ('+CF' in label and none_cf_p99 is not None) else none_p99
                if baseline is None:
                    continue
                delta = p99_val - baseline
                if label not in delta_data:
                    delta_data[label] = []
                delta_data[label].append((hw_lbl, delta))

        arch_delta_data[arch] = delta_data

    fig, axes = plt.subplots(1, 3, figsize=(20, 7), sharey=True)
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        delta_data = arch_delta_data.get(arch, {})
        tiers = HW_TIERS_ALL[arch]
        hw_labels = [t[2] for t in tiers]
        x_positions = {label: i for i, label in enumerate(hw_labels)}

        for label, points in sorted(delta_data.items()):
            if not points:
                continue
            xs = [x_positions[hw] for hw, _ in points]
            ys = [delta for _, delta in points]
            color = AUTH_COLORS_DETAILED.get(label, '#999')
            marker = AUTH_MARKERS_DETAILED.get(label, 'o')
            ls = AUTH_LINESTYLES.get(label, '-')
            ax.plot(xs, ys, marker=marker, color=color, linestyle=ls,
                    label=label, linewidth=2.2, markersize=8)

        ax.axhline(y=0, color='black', linewidth=0.5, linestyle='--')
        ax.set_yscale('symlog', linthresh=10)
        ax.set_xticks(range(len(hw_labels)))
        ax.set_xticklabels(hw_labels, fontsize=11)
        ax.set_xlabel('Hardware-Tier', fontsize=12)
        ax.set_title(f'{arch.capitalize()}', fontweight='bold', fontsize=13)
        ax.legend(fontsize=9, loc='upper right')
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=10)

    axes[0].set_ylabel('$\\Delta_{Auth}$ P99 (ms, symlog)', fontsize=12)
    fig.suptitle('Auth-Only $\\Delta_{Auth}$ P99 über Hardware-Tiers\n'
                 '(Baseline, authentifizierte Endpunkte, dashed=+CF)',
                 fontweight='bold', fontsize=13)
    fig.tight_layout()
    path = f"{PLOT_DIR}/delta_auth_hw_scaling_combined_log.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
