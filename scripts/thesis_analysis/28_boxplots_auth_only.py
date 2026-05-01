#!/usr/bin/env python3
"""
28 -- Auth-Only Boxplots: Latency Distributions at Protected Endpoints
Shows boxplots of raw latency distributions at auth-only (protected)
endpoints for each architecture at ALL hardware tiers.

Now differentiates:
  - Manual (bcrypt) vs Manual (argon2id) as separate boxes
  - CloudFront (+CF) variants where data exists

Outputs: boxplot_auth_only_{arch}.pdf (one per architecture, with HW subplots)
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, AUTH_COLORS_DETAILED, HW_TIERS_ALL)

PROTECTED_ENDPOINTS_FAAS = (
    '/frontend/setUser',
    '/frontend/addCartItem',
    '/frontend/cart',
    '/frontend/checkout',
)
PROTECTED_ENDPOINTS_CONTAINER = (
    '/setUser',
    '/addCartItem',
    '/cart',
    '/checkout',
)

ARCH_ORDER = ['faas', 'microservices', 'monolith']
ARCH_DISPLAY = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}

# Consistent label order
AUTH_LABEL_ORDER = [
    'None', 'None+CF', 'Cognito', 'Cognito+CF',
    'Manual (bcrypt)', 'Manual (bcrypt)+CF',
    'Manual (argon2id)', 'Manual (argon2id)+CF',
    'Edge', 'Edge+CF',
]


def get_protected_endpoints(arch):
    return PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER


def main():
    print("=" * 70)
    print("28 -- AUTH-ONLY BOXPLOTS — FULL DIFFERENTIATION")
    print("=" * 70)

    for arch in ARCH_ORDER:
        arch_configs = HW_TIERS_ALL[arch]
        arch_display = ARCH_DISPLAY[arch]
        n_hw = len(arch_configs)

        print(f"\n{'='*50}")
        print(f"  {arch_display}")
        print(f"{'='*50}")

        fig, axes = plt.subplots(1, n_hw, figsize=(6 * n_hw, 7), sharey=False)
        if n_hw == 1:
            axes = [axes]

        has_any_data = False

        for ax, (ram, cpu, hw_label) in zip(axes, arch_configs):
            print(f"\n--- {hw_label} ---")

            protected = get_protected_endpoints(arch)
            eps_sql = ','.join(f"'{e}'" for e in protected)
            cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

            df = query_df(f"""
                SELECT
                    e.auth_strategy,
                    COALESCE(e.password_hash_algorithm, 'default') AS algo,
                    COALESCE(e.with_cloudfront, false) AS with_cf,
                    r.latency_ms
                FROM experiments e
                JOIN requests r ON r.experiment_id = e.id
                WHERE {EXCLUDE_SQL}
                  AND e.architecture = '{arch}'
                  AND e.ram_in_mb = {ram}
                  {cpu_clause}
                  AND r.phase_name = 'Baseline'
                  AND NOT r.is_error
                  AND r.endpoint IN ({eps_sql})
                ORDER BY RANDOM()
                LIMIT 200000
            """)

            if df.empty:
                print(f"  No data for {hw_label}")
                ax.set_title(f'{hw_label}\n(no data)', fontsize=10)
                ax.text(0.5, 0.5, 'No data', ha='center', va='center',
                        transform=ax.transAxes, fontsize=12, color='gray')
                continue

            df['latency_ms'] = df['latency_ms'].astype(float)
            has_any_data = True

            # Create detailed labels
            df['auth_label'] = df.apply(
                lambda r: auth_label_detailed(
                    r['auth_strategy'],
                    r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
                    bool(r['with_cf'])),
                axis=1)

            box_data = []
            box_labels = []
            box_colors = []
            annotations = []

            for label in AUTH_LABEL_ORDER:
                subset = df[df['auth_label'] == label]['latency_ms'].values
                if len(subset) < 10:
                    continue
                box_data.append(subset)
                box_labels.append(label)
                box_colors.append(AUTH_COLORS_DETAILED.get(label, '#999999'))
                med = np.median(subset)
                annotations.append({'n': len(subset), 'med': med})
                print(f"  {label:>28s}: n={len(subset):,}, median={med:.1f}ms, "
                      f"P75={np.percentile(subset, 75):.1f}ms, "
                      f"P99={np.percentile(subset, 99):.1f}ms")

            if not box_data:
                ax.set_title(f'{hw_label}\n(insufficient data)', fontsize=10)
                continue

            bp = ax.boxplot(
                box_data,
                labels=box_labels,
                patch_artist=True,
                showfliers=False,
                whiskerprops=dict(linewidth=1.2),
                capprops=dict(linewidth=1.2),
                medianprops=dict(color='black', linewidth=2),
                boxprops=dict(linewidth=1.2),
            )

            for patch, color in zip(bp['boxes'], box_colors):
                patch.set_facecolor(color)
                patch.set_alpha(0.75)

            for i, ann in enumerate(annotations):
                y_top = np.percentile(box_data[i], 75) + 1.5 * (
                    np.percentile(box_data[i], 75) - np.percentile(box_data[i], 25))
                whisker_top = min(y_top, np.max(box_data[i]))
                ax.text(i + 1, whisker_top * 1.02,
                        f"n={ann['n']:,}\nmed={ann['med']:.0f}ms",
                        ha='center', va='bottom', fontsize=6, fontweight='bold',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                                  edgecolor='gray', alpha=0.8))

            ax.set_ylabel('Latency (ms)', fontsize=10)
            ax.set_title(hw_label, fontweight='bold', fontsize=10)
            ax.grid(axis='y', alpha=0.3)
            ax.tick_params(axis='x', rotation=45, labelsize=7)

        if has_any_data:
            fig.suptitle(f'{arch_display}: Auth-Only Endpoint Latency Distribution\n'
                         '(Baseline phase, protected endpoints, all auth variants, whiskers = 1.5 IQR)',
                         fontweight='bold', fontsize=12)
            plt.tight_layout()
            path = f"{PLOT_DIR}/boxplot_auth_only_{arch}.pdf"
            fig.savefig(path, dpi=300, bbox_inches='tight')
            print(f"  Saved: {path}")
        else:
            print(f"  No data at all for {arch_display}")
        plt.close()

    print("\nDone.")


if __name__ == '__main__':
    main()
