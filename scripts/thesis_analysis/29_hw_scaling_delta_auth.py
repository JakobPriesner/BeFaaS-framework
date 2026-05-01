#!/usr/bin/env python3
"""
29 -- Hardware Scaling DeltaAuth: How ΔAuth Changes Across HW Tiers
Line plots showing auth-only ΔAuth P99 across all hardware tiers per
architecture.

Now differentiates:
  - Manual (bcrypt) vs Manual (argon2id) as separate lines
  - CloudFront (+CF) variants (dashed lines)

Outputs: delta_auth_hw_scaling_combined.pdf,
         delta_auth_hw_scaling_{arch}.pdf, delta_auth_hw_scaling.csv
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '.')
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
    """Compute auth-only P99 per auth_strategy/algo/CF."""
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
    print("=" * 70)
    print("29 -- HARDWARE SCALING ΔAuth — FULL DIFFERENTIATION")
    print("=" * 70)

    all_rows = []
    arch_delta_data = {}

    for arch in ['faas', 'microservices', 'monolith']:
        print(f"\n{'='*50}")
        print(f"  {arch.upper()}")
        print(f"{'='*50}")

        tiers = HW_TIERS_ALL[arch]
        tier_data = {}

        for ram, cpu, hw_lbl in tiers:
            df = compute_auth_only_p99(arch, ram, cpu)
            if df.empty:
                print(f"  {hw_lbl}: no data")
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
                print(f"  {hw_lbl} / {label:>28s}: P99={row['p99']:.1f}ms (n={row['n_success']:,.0f})")

        print(f"\n  --- ΔAuth P99 ---")
        delta_data = {}

        for hw_lbl in [t[2] for t in tiers]:
            if hw_lbl not in tier_data:
                continue

            # Find None baseline (prefer matching CF, fall back to non-CF)
            none_p99 = tier_data[hw_lbl].get('None')
            none_cf_p99 = tier_data[hw_lbl].get('None+CF')

            for label, p99_val in tier_data[hw_lbl].items():
                if label.startswith('None'):
                    continue

                # Use CF baseline for +CF auth, non-CF baseline otherwise
                baseline = none_cf_p99 if ('+CF' in label and none_cf_p99 is not None) else none_p99
                if baseline is None:
                    continue

                delta = p99_val - baseline
                if label not in delta_data:
                    delta_data[label] = []
                delta_data[label].append((hw_lbl, delta))

                all_rows.append({
                    'architecture': arch,
                    'hw_tier': hw_lbl,
                    'auth_label': label,
                    'none_p99': round(baseline, 1),
                    'auth_p99': round(p99_val, 1),
                    'delta_auth_p99': round(delta, 1),
                })

                print(f"  {hw_lbl} / {label:>28s}: ΔAuth P99 = {delta:+.1f}ms")

        arch_delta_data[arch] = delta_data

    # --- Combined figure ---
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), sharey=True)
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
                    label=label, linewidth=2, markersize=7)

        ax.axhline(y=0, color='black', linewidth=0.5, linestyle='--')
        ax.set_xticks(range(len(hw_labels)))
        ax.set_xticklabels(hw_labels, fontsize=10)
        ax.set_xlabel('Hardware Tier', fontsize=11)
        if ax == axes[0]:
            ax.set_ylabel('$\\Delta_{Auth}$ P99 (ms)', fontsize=12)
        ax.set_title(f'{arch.capitalize()}', fontweight='bold', fontsize=12)
        ax.legend(fontsize=7, loc='upper left')
        ax.grid(alpha=0.3)

    fig.suptitle('Auth-Only $\\Delta_{Auth}$ P99 Across Hardware Tiers\n'
                 '(Baseline phase, protected endpoints, all auth variants, dashed=+CF)',
                 fontweight='bold', fontsize=12)
    plt.tight_layout()

    path = f"{PLOT_DIR}/delta_auth_hw_scaling_combined.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"  Saved: {path}")

    # Individual plots per architecture (log scale)
    for arch in ['faas', 'microservices', 'monolith']:
        delta_data = arch_delta_data.get(arch, {})
        tiers = HW_TIERS_ALL[arch]
        hw_labels = [t[2] for t in tiers]
        x_positions = {label: i for i, label in enumerate(hw_labels)}

        fig2, ax2 = plt.subplots(figsize=(10, 6))
        for label, points in sorted(delta_data.items()):
            if not points:
                continue
            xs = [x_positions[hw] for hw, _ in points]
            ys = [delta for _, delta in points]
            color = AUTH_COLORS_DETAILED.get(label, '#999')
            marker = AUTH_MARKERS_DETAILED.get(label, 'o')
            ls = AUTH_LINESTYLES.get(label, '-')
            ax2.plot(xs, ys, marker=marker, color=color, linestyle=ls,
                     label=label, linewidth=2, markersize=8)

        ax2.axhline(y=0, color='black', linewidth=0.5, linestyle='--')
        ax2.set_yscale('symlog', linthresh=10)
        ax2.set_xticks(range(len(hw_labels)))
        ax2.set_xticklabels(hw_labels, fontsize=11)
        ax2.set_xlabel('Hardware Tier', fontsize=12)
        ax2.set_ylabel('$\\Delta_{Auth}$ P99 (ms)', fontsize=12)
        ax2.set_title(f'{arch.capitalize()}: Auth-Only $\\Delta_{{Auth}}$ P99\n'
                      f'(Baseline phase, all auth variants, dashed=+CF)',
                      fontweight='bold', fontsize=11)
        ax2.legend(fontsize=9)
        ax2.grid(alpha=0.3)
        plt.tight_layout()
        path = f"{PLOT_DIR}/delta_auth_hw_scaling_{arch}.pdf"
        fig2.savefig(path, dpi=300, bbox_inches='tight')
        print(f"  Saved: {path}")
        plt.close(fig2)

    # ── Combined 1×3 figure with log scale (for thesis) ──
    fig3, axes3 = plt.subplots(1, 3, figsize=(20, 7), sharey=True)
    for ax, arch in zip(axes3, ['faas', 'microservices', 'monolith']):
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

    axes3[0].set_ylabel('$\\Delta_{Auth}$ P99 (ms, symlog)', fontsize=12)
    fig3.suptitle('Auth-Only $\\Delta_{Auth}$ P99 über Hardware-Tiers\n'
                  '(Baseline, authentifizierte Endpunkte, dashed=+CF)',
                  fontweight='bold', fontsize=13)
    fig3.tight_layout()
    path = f"{PLOT_DIR}/delta_auth_hw_scaling_combined_log.pdf"
    fig3.savefig(path, dpi=300, bbox_inches='tight')
    print(f"  Saved: {path}")
    plt.close(fig3)

    plt.close('all')

    result_df = pd.DataFrame(all_rows)
    if not result_df.empty:
        result_df.to_csv(f"{PLOT_DIR}/delta_auth_hw_scaling.csv", index=False)
        print(f"\nSaved: {PLOT_DIR}/delta_auth_hw_scaling.csv")

    # Summary
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    if not result_df.empty:
        for label in sorted(result_df['auth_label'].unique()):
            data = result_df[result_df['auth_label'] == label]
            deltas = data['delta_auth_p99'].values
            print(f"  {label:>28s}: ΔAuth P99 range = [{min(deltas):+.1f}, {max(deltas):+.1f}]ms, "
                  f"std = {np.std(deltas):.1f}ms")
    print()


if __name__ == '__main__':
    main()
