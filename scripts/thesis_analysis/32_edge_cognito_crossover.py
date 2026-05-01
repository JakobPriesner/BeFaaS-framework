"""Script 32: Fine-grained percentile crossover analysis — Edge vs Cognito.

Computes ΔAuth at 5-percentile increments (P50-P99) to identify the exact
crossover point where Edge becomes worse than Cognito.
Also breaks down per-endpoint to understand WHY Edge is faster at low percentiles.
Now runs for ALL hardware configurations per architecture.
"""

import sys
sys.path.insert(0, '/Users/jakob/WebstormProjects/BeFaaS-framework2/scripts/thesis_analysis')

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from db_connection import (query_df, EXCLUDE_SQL, PLOT_DIR,
                           JWKS_MODE_COLORS, JWKS_MODE_LABELS)

# All hardware configurations
ALL_CONFIGS = [
    ('faas', 256, 0, 'FaaS 256MB'),
    ('faas', 512, 0, 'FaaS 512MB'),
    ('faas', 1024, 0, 'FaaS 1024MB'),
    ('faas', 1769, 0, 'FaaS 1769MB'),
    ('microservices', 512, 0.25, 'MS S'),
    ('microservices', 1024, 0.5, 'MS M'),
    ('microservices', 1769, 1.0, 'MS 1769'),
    ('microservices', 2048, 1.0, 'MS L'),
    ('microservices', 8192, 4.0, 'MS XL'),
    ('monolith', 512, 0.25, 'Mono S'),
    ('monolith', 1024, 0.5, 'Mono M'),
    ('monolith', 2048, 1.0, 'Mono L'),
    ('monolith', 8192, 4.0, 'Mono XL'),
]

ARCH_ORDER = ['faas', 'microservices', 'monolith']
ARCH_DISPLAY = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}

PROTECTED_ENDPOINTS_CONTAINER = ("'/setUser'", "'/addCartItem'", "'/cart'", "'/checkout'")
PROTECTED_ENDPOINTS_FAAS = ("'/frontend/setUser'", "'/frontend/addCartItem'", "'/frontend/cart'", "'/frontend/checkout'")

# Fine-grained percentiles: every 5% from P50 to P95, then P97, P99
PERCENTILES = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.97, 0.99]

def build_percentile_sql(percentiles):
    """Build SQL percentile expressions."""
    parts = []
    for p in percentiles:
        label = f"p{int(p*100)}"
        parts.append(
            f"percentile_cont({p}) WITHIN GROUP (ORDER BY r.latency_ms) "
            f"FILTER (WHERE NOT r.is_error) AS {label}"
        )
    return ',\n        '.join(parts)


def query_percentiles(arch, ram, cpu, label, jwks_mode=None):
    """Query fine-grained percentiles per auth strategy, auth-only endpoints.

    jwks_mode: None = all Edge experiments, 'buildtime'/'runtime' = filter Edge
    experiments by JWKS mode. Non-Edge strategies are always unfiltered.
    """
    eps = PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER
    eps_sql = ','.join(eps)
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

    jwks_clause = ""
    if jwks_mode:
        jwks_clause = (
            f"AND (e.auth_strategy NOT IN ('edge','edge-selective') "
            f"OR e.jwks_mode = '{jwks_mode}')"
        )

    pct_sql = build_percentile_sql(PERCENTILES)

    sql = f"""
    SELECT
        e.id AS experiment_id,
        e.auth_strategy,
        COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
        {pct_sql}
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND e.architecture = '{arch}'
      AND e.ram_in_mb = {ram}
      {cpu_clause}
      AND r.phase_name = 'Baseline'
      AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
      AND r.endpoint IN ({eps_sql})
      {jwks_clause}
    GROUP BY e.id, e.auth_strategy
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    ORDER BY e.auth_strategy, e.id
    """
    df = query_df(sql)
    df['config'] = label
    return df


def query_per_endpoint(arch, ram, cpu, label):
    """Query P50/P75/P90/P99 per endpoint per auth strategy."""
    eps = PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER
    eps_sql = ','.join(eps)
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

    sql = f"""
    SELECT
        e.auth_strategy,
        r.endpoint,
        COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p75,
        percentile_cont(0.90) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p90,
        percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p99
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND e.architecture = '{arch}'
      AND e.ram_in_mb = {ram}
      {cpu_clause}
      AND r.phase_name = 'Baseline'
      AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
      AND r.endpoint IN ({eps_sql})
    GROUP BY e.auth_strategy, r.endpoint
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    ORDER BY e.auth_strategy, r.endpoint
    """
    df = query_df(sql)
    df['config'] = label
    return df


def compute_delta_auth(df, percentiles):
    """Compute ΔAuth = auth - mean(none) at each percentile."""
    pct_cols = [f'p{int(p*100)}' for p in percentiles]

    grouped = df.groupby('auth_strategy')[pct_cols].mean()

    if 'none' not in grouped.index:
        print("  WARNING: No 'none' baseline found!")
        return None

    none_vals = grouped.loc['none']

    results = {}
    for strat in grouped.index:
        if strat == 'none':
            continue
        delta = grouped.loc[strat] - none_vals
        results[strat] = delta

    return pd.DataFrame(results), none_vals, grouped


def plot_crossover_per_arch(arch, arch_configs, all_delta_data, percentiles):
    """Plot ΔAuth crossover for all HW tiers of one architecture."""
    arch_display = ARCH_DISPLAY[arch]
    pct_labels = [f'P{int(p*100)}' for p in percentiles]

    valid_configs = [(label, data) for label, data in all_delta_data if data is not None]
    if not valid_configs:
        print(f"  No crossover data for {arch_display}")
        return

    n_hw = len(arch_configs)
    fig, axes = plt.subplots(1, n_hw, figsize=(6 * n_hw, 5), sharey=False)
    if n_hw == 1:
        axes = [axes]

    strategy_names = {
        'service-integrated': 'Cognito',
        'service-integrated-manual': 'Manual (bcrypt)',
        'edge': 'Edge',
    }
    colors = {
        'service-integrated': '#2196F3',
        'service-integrated-manual': '#F44336',
        'edge': '#4CAF50',
    }

    config_to_delta = {label: data for label, data in all_delta_data}
    x_positions = np.array([p * 100 for p in percentiles])

    for ax, (_, ram, cpu, hw_label) in zip(axes, arch_configs):
        delta_df = config_to_delta.get(hw_label)
        if delta_df is None:
            ax.set_title(f'{hw_label}\n(no data)', fontsize=10)
            ax.text(0.5, 0.5, 'No data', ha='center', va='center',
                    transform=ax.transAxes, fontsize=12, color='gray')
            continue

        for strat in delta_df.columns:
            vals = delta_df[strat].values
            name = strategy_names.get(strat, strat)
            color = colors.get(strat, '#999999')
            ax.plot(x_positions, vals, 'o-', label=name, color=color,
                    linewidth=1.8, markersize=5)

        # Find crossover point
        if 'edge' in delta_df.columns and 'service-integrated' in delta_df.columns:
            edge_vals = delta_df['edge'].values
            cog_vals = delta_df['service-integrated'].values
            diff = edge_vals - cog_vals

            for i in range(len(diff) - 1):
                if diff[i] <= 0 and diff[i+1] > 0:
                    frac = -diff[i] / (diff[i+1] - diff[i])
                    crossover_pct = percentiles[i] + frac * (percentiles[i+1] - percentiles[i])
                    crossover_x = x_positions[i] + frac * (x_positions[i+1] - x_positions[i])
                    crossover_y = edge_vals[i] + frac * (edge_vals[i+1] - edge_vals[i])
                    ax.axvline(x=crossover_x, color='gray', linestyle='--', alpha=0.7, linewidth=1)
                    ax.annotate(f'Crossover: P{int(crossover_pct*100)}',
                               xy=(crossover_x, crossover_y),
                               xytext=(crossover_x + 3, crossover_y - 20),
                               arrowprops=dict(arrowstyle='->', color='gray'),
                               fontsize=8, color='gray')
                    print(f"  {hw_label}: CROSSOVER at ~P{crossover_pct*100:.0f}")
                    break

        ax.set_xticks(x_positions)
        ax.set_xticklabels(pct_labels, rotation=45, fontsize=8)
        ax.set_ylabel('ΔAuth (ms)', fontsize=9)
        ax.set_xlabel('Percentile', fontsize=9)
        ax.set_xlim(47, 102)
        ax.set_title(hw_label, fontsize=10, fontweight='bold')
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='black', linewidth=0.5)

    fig.suptitle(f'{arch_display}: ΔAuth Crossover — Edge vs Cognito\n'
                 '(Auth-only endpoints, Baseline phase, excl. argon2id)',
                 fontsize=12, fontweight='bold')
    plt.tight_layout()
    fname = f"edge_cognito_crossover_{arch}.pdf"
    plt.savefig(f"{PLOT_DIR}/{fname}", bbox_inches='tight', dpi=300)
    plt.close()
    print(f"  Saved: {fname}")
    return fname


def main():
    all_results = []
    all_endpoint_results = []

    # Group configs by architecture for per-arch plotting
    arch_delta_data = {arch: [] for arch in ARCH_ORDER}

    for arch, ram, cpu, label in ALL_CONFIGS:
        print(f"\n{'='*60}")
        print(f"  {label} ({arch}, {ram}MB, {cpu}vCPU)")
        print(f"{'='*60}")

        # ── Fine-grained percentiles ──
        df = query_percentiles(arch, ram, cpu, label)
        if df.empty:
            print(f"  No data for {label}")
            arch_delta_data[arch].append((label, None))
            continue

        print(f"\n  Experiments found:")
        for strat in sorted(df['auth_strategy'].unique()):
            exp_ids = df[df['auth_strategy'] == strat]['experiment_id'].tolist()
            print(f"    {strat}: n={len(exp_ids)}, IDs={exp_ids}")

        result = compute_delta_auth(df, PERCENTILES)
        if result is None:
            arch_delta_data[arch].append((label, None))
            continue
        delta_df, none_vals, grouped = result
        arch_delta_data[arch].append((label, delta_df))

        pct_labels = [f'P{int(p*100)}' for p in PERCENTILES]

        # Print ΔAuth table
        print(f"\n  ΔAuth (auth - none) in ms:")
        print(f"  {'Percentile':<12}", end='')
        for strat in delta_df.columns:
            name = {'service-integrated': 'Cognito', 'edge': 'Edge', 'service-integrated-manual': 'Manual'}.get(strat, strat)
            print(f"  {name:>10}", end='')
        print()

        for i, pct in enumerate(PERCENTILES):
            plabel = f"P{int(pct*100)}"
            col = f'p{int(pct*100)}'
            print(f"  {plabel:<12}", end='')
            for strat in delta_df.columns:
                val = delta_df[strat].iloc[i]
                print(f"  {val:>+10.1f}", end='')
            print()

        # Print absolute values
        print(f"\n  Absolute latencies (ms):")
        print(f"  {'Percentile':<12}", end='')
        for strat in grouped.index:
            name = {'none': 'None', 'service-integrated': 'Cognito', 'edge': 'Edge', 'service-integrated-manual': 'Manual'}.get(strat, strat)
            print(f"  {name:>10}", end='')
        print()

        for i, pct in enumerate(PERCENTILES):
            plabel = f"P{int(pct*100)}"
            col = f'p{int(pct*100)}'
            print(f"  {plabel:<12}", end='')
            for strat in grouped.index:
                val = grouped.loc[strat, col]
                print(f"  {val:>10.1f}", end='')
            print()

        # Save to CSV
        for strat in delta_df.columns:
            name = {'service-integrated': 'Cognito', 'edge': 'Edge', 'service-integrated-manual': 'Manual'}.get(strat, strat)
            for i, pct in enumerate(PERCENTILES):
                col = f'p{int(pct*100)}'
                all_results.append({
                    'config': label,
                    'strategy': name,
                    'percentile': f'P{int(pct*100)}',
                    'delta_auth_ms': round(delta_df[strat].iloc[i], 1),
                    'absolute_ms': round(grouped.loc[strat, col], 1),
                    'none_ms': round(none_vals[col], 1),
                })

        # ── Per-endpoint breakdown ──
        print(f"\n  Per-Endpoint Breakdown:")
        ep_df = query_per_endpoint(arch, ram, cpu, label)

        if not ep_df.empty:
            for strat in sorted(ep_df['auth_strategy'].unique()):
                name = {'none': 'None', 'service-integrated': 'Cognito', 'edge': 'Edge', 'service-integrated-manual': 'Manual'}.get(strat, strat)
                strat_df = ep_df[ep_df['auth_strategy'] == strat]
                print(f"\n    {name}:")
                print(f"    {'Endpoint':<25} {'n':>8} {'P50':>8} {'P75':>8} {'P90':>8} {'P99':>8}")
                for _, row in strat_df.iterrows():
                    ep = row['endpoint'].split('/')[-1]
                    print(f"    {ep:<25} {row['n_success']:>8.0f} {row['p50']:>8.1f} {row['p75']:>8.1f} {row['p90']:>8.1f} {row['p99']:>8.1f}")
                    all_endpoint_results.append({
                        'config': label,
                        'strategy': name,
                        'endpoint': ep,
                        'n_success': int(row['n_success']),
                        'p50': round(row['p50'], 1),
                        'p75': round(row['p75'], 1),
                        'p90': round(row['p90'], 1),
                        'p99': round(row['p99'], 1),
                    })

    # ── Plot: one PDF per architecture ──
    for arch in ARCH_ORDER:
        arch_configs = [c for c in ALL_CONFIGS if c[0] == arch]
        plot_crossover_per_arch(arch, arch_configs, arch_delta_data[arch], PERCENTILES)

    # ── Single-config plots for LaTeX (e.g. Mono L) ──
    single_plots = [
        ('monolith', 'Mono L', 'edge_cognito_crossover_monolith_l.pdf'),
        ('microservices', 'MS L', 'edge_cognito_crossover_microservices_l.pdf'),
        ('faas', 'FaaS 512MB', 'edge_cognito_crossover_faas_512mb.pdf'),
    ]
    strategy_names = {
        'service-integrated': 'Cognito',
        'service-integrated-manual': 'Manual (bcrypt)',
        'edge': 'Edge',
        'edge-selective': 'edge-selective',
    }
    colors = {
        'service-integrated': '#2196F3',
        'service-integrated-manual': '#F44336',
        'edge': '#4CAF50',
        'edge-selective': '#9E9E9E',
    }
    pct_labels = [f'P{int(p*100)}' for p in PERCENTILES]
    x_positions = np.array([p * 100 for p in PERCENTILES])

    for arch_key, hw_label, fname in single_plots:
        delta_data = dict(arch_delta_data[arch_key])
        delta_df = delta_data.get(hw_label)
        if delta_df is None:
            print(f"  No data for {hw_label} — skipping {fname}")
            continue

        fig, ax = plt.subplots(figsize=(7, 5))
        for strat in delta_df.columns:
            vals = delta_df[strat].values
            name = strategy_names.get(strat, strat)
            color = colors.get(strat, '#999999')
            ax.plot(x_positions, vals, 'o-', label=name, color=color,
                    linewidth=1.8, markersize=5)

        # Find crossover
        if 'edge' in delta_df.columns and 'service-integrated' in delta_df.columns:
            edge_vals = delta_df['edge'].values
            cog_vals = delta_df['service-integrated'].values
            diff = edge_vals - cog_vals
            for i in range(len(diff) - 1):
                if diff[i] <= 0 and diff[i+1] > 0:
                    frac = -diff[i] / (diff[i+1] - diff[i])
                    crossover_pct = PERCENTILES[i] + frac * (PERCENTILES[i+1] - PERCENTILES[i])
                    crossover_x = x_positions[i] + frac * (x_positions[i+1] - x_positions[i])
                    crossover_y = edge_vals[i] + frac * (edge_vals[i+1] - edge_vals[i])
                    ax.axvline(x=crossover_x, color='gray', linestyle='--', alpha=0.7, linewidth=1)
                    ax.annotate(f'Crossover: P{int(crossover_pct*100)}',
                               xy=(crossover_x, crossover_y),
                               xytext=(crossover_x + 3, crossover_y - 20),
                               arrowprops=dict(arrowstyle='->', color='gray'),
                               fontsize=8, color='gray')
                    break

        ax.set_xticks(x_positions)
        ax.set_xticklabels(pct_labels, rotation=45, fontsize=8)
        ax.set_ylabel('ΔAuth (ms)', fontsize=10)
        ax.set_xlabel('Percentile', fontsize=10)
        ax.set_xlim(47, 102)
        ax.set_title(f'ΔAuth Crossover: Edge vs Cognito — {hw_label}',
                     fontsize=12, fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='black', linewidth=0.5)
        plt.tight_layout()
        plt.savefig(f"{PLOT_DIR}/{fname}", bbox_inches='tight', dpi=300)
        plt.close()
        print(f"  Saved: {fname}")

    # ── Save CSVs ──
    results_df = pd.DataFrame(all_results)
    results_df.to_csv(f"{PLOT_DIR}/edge_cognito_crossover.csv", index=False)
    print(f"\nSaved: edge_cognito_crossover.csv")

    ep_results_df = pd.DataFrame(all_endpoint_results)
    ep_results_df.to_csv(f"{PLOT_DIR}/edge_cognito_per_endpoint.csv", index=False)
    print(f"Saved: edge_cognito_per_endpoint.csv")


if __name__ == '__main__':
    main()
