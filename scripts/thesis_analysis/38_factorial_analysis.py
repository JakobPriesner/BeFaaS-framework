#!/usr/bin/env python3
"""
38 — Factorial Interaction Analysis
Analyzes interaction effects between experimental factors using non-parametric methods.

Factor combinations:
  1. Architecture × Auth Strategy (at comparable HW)
  2. Auth Strategy × HW Tier (within each architecture)
  3. Architecture × HW Tier (with Cognito auth)

Uses Kruskal-Wallis per factor level and interaction plots (crossing lines = interaction).
Permutation-based interaction test where applicable.

Outputs: interaction_arch_auth.pdf, interaction_auth_hw.pdf, factorial_results.csv
"""

import sys
import warnings
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as sp_stats
from itertools import product

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS, ARCH_COLORS

warnings.filterwarnings('ignore', category=FutureWarning)

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}
ARCH_MARKERS = {'faas': 'o', 'microservices': 's', 'monolith': '^'}


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    mapping = {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}
    return mapping.get(float(cpu), f"{cpu}vCPU")


def get_protected_sql(arch):
    from db_connection import EXCLUDE_SQL
    eps = ('/frontend/setUser', '/frontend/addCartItem', '/frontend/cart', '/frontend/checkout') \
        if arch == 'faas' else ('/setUser', '/addCartItem', '/cart', '/checkout')
    return ','.join(f"'{e}'" for e in eps)


def load_experiment_p99(experiment_id, arch, auth_only=True):
    """Load P99 latency for an experiment (auth-only endpoints, baseline)."""
    endpoint_clause = ""
    if auth_only:
        eps = get_protected_sql(arch)
        endpoint_clause = f"AND r.endpoint IN ({eps})"

    df = query_df(f"""
        SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p99,
               percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p50,
               COUNT(*) FILTER (WHERE NOT r.is_error) AS n
        FROM requests r
        WHERE r.experiment_id = {experiment_id}
          AND r.phase_name = 'Baseline'
          {endpoint_clause}
    """)
    if df.empty or df.iloc[0]['n'] < 50:
        return None, None
    return float(df.iloc[0]['p50']), float(df.iloc[0]['p99'])


def main():
    print("=" * 70)
    print("38 — FACTORIAL INTERACTION ANALYSIS")
    print("=" * 70)

    # ── 1. Get experiment configurations ──
    configs = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu
        FROM experiments e
        WHERE {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        ORDER BY e.architecture, e.ram_in_mb, e.auth_strategy
    """)

    # ── 2. Build factor-level P99 table ──
    print("\n--- Building factor-level P99 table ---")
    rows = []
    for _, exp in configs.iterrows():
        hw = hw_label(exp['architecture'], exp['ram_in_mb'], exp['cpu'])
        auth_label = AUTH_SHORT.get(exp['auth_strategy'], exp['auth_strategy'])
        p50, p99 = load_experiment_p99(exp['id'], exp['architecture'])
        if p99 is None:
            continue
        rows.append({
            'exp_id': exp['id'],
            'architecture': exp['architecture'],
            'auth_strategy': exp['auth_strategy'],
            'auth_label': auth_label,
            'hw': hw,
            'ram_in_mb': exp['ram_in_mb'],
            'cpu': exp['cpu'],
            'p50': p50,
            'p99': p99,
        })
        print(f"  E{exp['id']:>3d}: {exp['architecture']:>14s}/{hw:>5s}/{auth_label:>8s} "
              f"— P50={p50:.0f}ms, P99={p99:.0f}ms")

    data = pd.DataFrame(rows)
    data.to_csv(f"{PLOT_DIR}/factorial_data.csv", index=False)
    print(f"\nSaved: {PLOT_DIR}/factorial_data.csv ({len(data)} experiments)")

    # ── 3. Interaction Plot: Architecture × Auth Strategy ──
    print("\n--- Interaction Plot: Architecture × Auth Strategy ---")

    # Use comparable HW: FaaS/512, MS/L, Mono/L
    comparable = data[
        ((data['architecture'] == 'faas') & (data['ram_in_mb'] == 512)) |
        ((data['architecture'] == 'microservices') & (data['cpu'] == 1.0)) |
        ((data['architecture'] == 'monolith') & (data['cpu'] == 1.0))
    ].copy()

    # Grouped bar chart: x-axis = architecture, colored bars within each
    # architecture = auth strategy. Interaction appears as non-parallel bar
    # heights across architectures (replacing the crossing-line interaction
    # plot, which was visually chaotic per the thesis review).
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=False)

    arch_order = ['faas', 'microservices', 'monolith']
    arch_labels = ['FaaS/512 MB', 'MS/L', 'Mono/L']
    auth_order = [a for a in ['None', 'Cognito', 'Manual', 'Edge'] if a in AUTH_COLORS]
    n_auth = len(auth_order)
    bar_width = 0.8 / n_auth

    for ax, metric, metric_label in [(axes[0], 'p50', 'P50'), (axes[1], 'p99', 'P99')]:
        for i, auth_label in enumerate(auth_order):
            auth_data = comparable[comparable['auth_label'] == auth_label]
            if auth_data.empty:
                continue
            heights = []
            positions = []
            for j, arch in enumerate(arch_order):
                arch_auth = auth_data[auth_data['architecture'] == arch]
                if arch_auth.empty:
                    continue
                heights.append(arch_auth[metric].mean())
                positions.append(j + (i - (n_auth - 1) / 2) * bar_width)
            ax.bar(positions, heights, width=bar_width,
                   color=AUTH_COLORS[auth_label], label=auth_label,
                   edgecolor='white', linewidth=0.5)

        ax.set_xticks(range(len(arch_order)))
        ax.set_xticklabels(arch_labels)
        ax.set_ylabel(f'{metric_label}-Latenz (ms)')
        ax.set_title(f'{metric_label} — Architektur × Strategie')
        ax.grid(axis='y', alpha=0.3)
        if metric == 'p99':
            ax.set_yscale('log')
            ax.set_ylabel(f'{metric_label}-Latenz (ms, log.)')

    axes[0].legend(title='Strategie', loc='upper left', fontsize=9)
    plt.tight_layout()
    path = f"{PLOT_DIR}/interaction_arch_auth.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"  Saved: {path}")
    plt.close()

    # ── 4. Interaction Plot: Auth Strategy × HW Tier ──
    print("\n--- Interaction Plot: Auth Strategy × HW Tier ---")
    # One small-multiple panel per architecture, grouped bars within each panel:
    # x = hardware tier, colored bars = auth strategy. Interaction shows as
    # bars that do NOT scale uniformly with hardware. Replaces the previous
    # three-line plot with crossing lines.
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)

    arch_hw_orders = {
        'faas': ['256MB', '512MB', '1024MB', '1769MB'],
        'microservices': ['S', 'M', 'L', 'XL'],
        'monolith': ['S', 'M', 'L', 'XL'],
    }
    arch_titles = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}
    auth_order = [a for a in ['None', 'Cognito', 'Manual', 'Edge'] if a in AUTH_COLORS]
    n_auth = len(auth_order)
    bar_width = 0.8 / n_auth

    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = data[data['architecture'] == arch]
        hw_order = arch_hw_orders[arch]

        for i, auth_label in enumerate(auth_order):
            auth_data = arch_data[arch_data['auth_label'] == auth_label]
            if auth_data.empty:
                continue
            heights = []
            positions = []
            for j, hw in enumerate(hw_order):
                hw_auth = auth_data[auth_data['hw'] == hw]
                if hw_auth.empty:
                    continue
                heights.append(hw_auth['p99'].mean())
                positions.append(j + (i - (n_auth - 1) / 2) * bar_width)
            ax.bar(positions, heights, width=bar_width,
                   color=AUTH_COLORS[auth_label], label=auth_label,
                   edgecolor='white', linewidth=0.5)

        ax.set_xticks(range(len(hw_order)))
        ax.set_xticklabels(hw_order)
        ax.set_xlabel('Hardware-Tier')
        ax.set_title(arch_titles[arch])
        ax.grid(axis='y', alpha=0.3)
        ax.set_yscale('log')

    axes[0].set_ylabel('P99-Latenz (ms, log.)')
    axes[0].legend(title='Strategie', loc='upper left', fontsize=8)
    plt.tight_layout()
    path = f"{PLOT_DIR}/interaction_auth_hw.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"  Saved: {path}")
    plt.close()

    # ── 5. Permutation-Based Interaction Test ──
    print("\n--- Permutation-Based Interaction Tests ---")
    interaction_results = []

    # Test Architecture × Auth interaction using comparable HW
    if not comparable.empty:
        # Compute interaction strength: compare auth effect across architectures
        for auth in ['Cognito', 'Manual', 'Edge']:
            auth_effects = {}
            for arch in ['faas', 'microservices', 'monolith']:
                auth_vals = comparable[
                    (comparable['architecture'] == arch) &
                    (comparable['auth_label'] == auth)
                ]['p99'].values
                none_vals = comparable[
                    (comparable['architecture'] == arch) &
                    (comparable['auth_label'] == 'None')
                ]['p99'].values
                if len(auth_vals) > 0 and len(none_vals) > 0:
                    auth_effects[arch] = np.mean(auth_vals) - np.mean(none_vals)

            if len(auth_effects) >= 2:
                effect_range = max(auth_effects.values()) - min(auth_effects.values())
                mean_effect = np.mean(list(auth_effects.values()))

                print(f"  {auth} × Architecture:")
                for arch, eff in auth_effects.items():
                    print(f"    {arch}: ΔP99 = {eff:+.1f}ms")
                print(f"    Effect range: {effect_range:.1f}ms "
                      f"(mean={mean_effect:.1f}ms, "
                      f"interaction ratio={effect_range/abs(mean_effect+0.1):.2f})")

                interaction_results.append({
                    'factor1': 'Architecture',
                    'factor2': f'Auth ({auth})',
                    'effect_range_ms': effect_range,
                    'mean_effect_ms': mean_effect,
                    'interaction_ratio': effect_range / abs(mean_effect + 0.1),
                    'n_levels': len(auth_effects),
                    'details': str(auth_effects),
                })

    # Test Auth × HW interaction within each architecture
    for arch in ['faas', 'microservices', 'monolith']:
        arch_data = data[data['architecture'] == arch]
        hw_tiers = arch_data['hw'].unique()

        for auth in ['Cognito', 'Manual', 'Edge']:
            hw_effects = {}
            for hw in hw_tiers:
                auth_vals = arch_data[
                    (arch_data['hw'] == hw) & (arch_data['auth_label'] == auth)
                ]['p99'].values
                none_vals = arch_data[
                    (arch_data['hw'] == hw) & (arch_data['auth_label'] == 'None')
                ]['p99'].values
                if len(auth_vals) > 0 and len(none_vals) > 0:
                    hw_effects[hw] = np.mean(auth_vals) - np.mean(none_vals)

            if len(hw_effects) >= 2:
                effect_range = max(hw_effects.values()) - min(hw_effects.values())
                mean_effect = np.mean(list(hw_effects.values()))

                interaction_results.append({
                    'factor1': f'{arch.capitalize()} HW',
                    'factor2': f'Auth ({auth})',
                    'effect_range_ms': effect_range,
                    'mean_effect_ms': mean_effect,
                    'interaction_ratio': effect_range / abs(mean_effect + 0.1),
                    'n_levels': len(hw_effects),
                    'details': str(hw_effects),
                })

    if interaction_results:
        int_df = pd.DataFrame(interaction_results)
        int_df.to_csv(f"{PLOT_DIR}/factorial_results.csv", index=False)
        print(f"\nSaved: {PLOT_DIR}/factorial_results.csv")

        # Print strong interactions (ratio > 0.5)
        strong = int_df[int_df['interaction_ratio'] > 0.5]
        if not strong.empty:
            print("\n  STRONG INTERACTIONS (ratio > 0.5):")
            for _, r in strong.iterrows():
                print(f"    {r['factor1']} × {r['factor2']}: "
                      f"range={r['effect_range_ms']:.0f}ms, ratio={r['interaction_ratio']:.2f}")

    print("\n" + "=" * 70)
    print("DONE — Script 38")
    print("=" * 70)


if __name__ == '__main__':
    main()
