#!/usr/bin/env python3
"""
43 -- Architecture Ratio Compression ("Equalizing Effect")
Quantifies how each auth configuration changes the architecture performance gap.

For each (auth_strategy × HW_tier) we compute:
  ratio = P99(FaaS) / P99(fastest container arch at same-tier equivalent)
and compare to the None-baseline ratio.

A ratio of 18× shrinking to 3× means strong compression (nivellierung).
A ratio inverting (containers slower) means the hierarchy flips.

Outputs:
  arch_ratio_compression.csv    — raw ratio data
  arch_ratio_compression.pdf    — main visualization
  arch_ratio_compression_detail.pdf — per-endpoint breakdown
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL, DETAILED_AUTH_SQL,
                           auth_label_detailed, AUTH_COLORS_DETAILED)

# HW tier equivalence mapping:
# FaaS 256MB ↔ Container S (0.25 vCPU / 512MB)
# FaaS 512MB ↔ Container S (0.25 vCPU / 512MB)
# FaaS 1024MB ↔ Container M (0.5 vCPU / 1024MB)
# FaaS 1769MB ↔ Container L (1.0 vCPU / 2048MB)
# For simplicity we use two representative tiers:
#   "Small": FaaS 512MB vs MS S vs Mono S
#   "Large": FaaS 1024MB vs MS L vs Mono L
HW_TIER_GROUPS = [
    {
        'label': 'Small (FaaS 512 / Container S)',
        'short': 'Small',
        'faas': {'ram': 512},
        'microservices': {'ram': 512, 'cpu': 0.25},
        'monolith': {'ram': 512, 'cpu': 0.25},
    },
    {
        'label': 'Large (FaaS 1024 / Container L)',
        'short': 'Large',
        'faas': {'ram': 1024},
        'microservices': {'ram': 2048, 'cpu': 1.0},
        'monolith': {'ram': 2048, 'cpu': 1.0},
    },
]

# Edge-selective experiments are discovered via auth_strategy='edge-selective'
# and filtered by EXCLUDE_SQL — no hardcoded IDs needed.


def query_p99_by_config(arch, ram, cpu=None, auth_strategies=None, include_es=False):
    """Query P99 for a given architecture/HW, grouped by detailed auth config."""
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu is None else f"AND e.cpu_in_vcpu = {cpu}"

    auth_filter = ""
    if auth_strategies:
        auth_list = ','.join(f"'{a}'" for a in auth_strategies)
        auth_filter = f"AND e.auth_strategy IN ({auth_list})"

    # Main query (non-edge-selective)
    df = query_df(f"""
        SELECT
            e.auth_strategy,
            {DETAILED_AUTH_SQL},
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = '{arch}'
          AND e.ram_in_mb = {ram}
          {cpu_clause}
          AND e.auth_strategy != 'edge-selective'
          {auth_filter}
          AND r.phase_name = 'Baseline'
        GROUP BY e.auth_strategy, algo, with_cf
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)

    # Edge-selective query (separate experiment pool)
    if include_es:
        es_df = query_df(f"""
            SELECT
                e.auth_strategy,
                COALESCE(e.password_hash_algorithm, 'default') AS algo,
                COALESCE(e.with_cloudfront, false) AS with_cf,
                COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p50,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p99
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL}
              AND e.architecture = '{arch}'
              AND e.ram_in_mb = {ram}
              {cpu_clause}
              AND e.auth_strategy = 'edge-selective'
              AND r.phase_name = 'Baseline'
            GROUP BY e.auth_strategy, algo, with_cf
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)
        if not es_df.empty:
            df = pd.concat([df, es_df], ignore_index=True)

    if df.empty:
        return df

    for col in ['p50', 'p99']:
        df[col] = df[col].astype(float)

    df['auth_label'] = df.apply(
        lambda r: auth_label_detailed(r['auth_strategy'], r['algo'], r['with_cf']), axis=1)

    return df


def main():
    print("=" * 70)
    print("43 -- ARCHITECTURE RATIO COMPRESSION (EQUALIZING EFFECT)")
    print("=" * 70)

    all_rows = []

    for tier in HW_TIER_GROUPS:
        print(f"\n{'─' * 60}")
        print(f"  HW Tier: {tier['label']}")
        print(f"{'─' * 60}")

        # Query each architecture
        arch_data = {}
        for arch_name in ['faas', 'microservices', 'monolith']:
            cfg = tier[arch_name]
            cpu = cfg.get('cpu', None)
            df = query_p99_by_config(arch_name, cfg['ram'], cpu, include_es=True)
            if not df.empty:
                arch_data[arch_name] = df
                print(f"\n  {arch_name.upper()} ({cfg['ram']}MB"
                      f"{f', {cpu}vCPU' if cpu else ''}):")
                for _, row in df.iterrows():
                    print(f"    {row['auth_label']:>22s}: P50={row['p50']:>7.1f}ms  "
                          f"P99={row['p99']:>7.1f}ms  (n={row['n_success']:>6,d})")

        if len(arch_data) < 2:
            print("  ⚠ Not enough architectures for comparison")
            continue

        # Compute ratios: for each auth_label present in ALL architectures,
        # compute FaaS P99 / min(container P99)
        # Also compute max/min ratio across all archs
        faas_labels = set(arch_data.get('faas', pd.DataFrame()).get('auth_label', []))
        ms_labels = set(arch_data.get('microservices', pd.DataFrame()).get('auth_label', []))
        mono_labels = set(arch_data.get('monolith', pd.DataFrame()).get('auth_label', []))

        # Find labels present in at least FaaS + one container arch
        container_labels = ms_labels | mono_labels
        common_labels = faas_labels & container_labels

        # Also include labels present in both container archs (even without FaaS)
        all_labels = faas_labels | ms_labels | mono_labels

        # First pass: compute all ratios and find None baseline
        label_ratios = {}
        for label in sorted(all_labels):
            p99s = {}
            for arch_name, df in arch_data.items():
                match = df[df['auth_label'] == label]
                if not match.empty:
                    p99s[arch_name] = match.iloc[0]['p99']

            if len(p99s) < 2:
                continue

            max_p99 = max(p99s.values())
            min_p99 = min(p99s.values())
            ratio = max_p99 / min_p99 if min_p99 > 0 else float('inf')
            slowest = max(p99s, key=p99s.get)
            fastest = min(p99s, key=p99s.get)
            label_ratios[label] = {
                'p99s': p99s, 'ratio': ratio, 'slowest': slowest, 'fastest': fastest,
                'max_p99': max_p99, 'min_p99': min_p99,
            }

        none_ratio = label_ratios.get('None', {}).get('ratio')

        print(f"\n  Ratios (P99: slowest arch / fastest arch):")
        print(f"  {'Auth Config':>22s} | {'FaaS':>8s} | {'MS':>8s} | {'Mono':>8s} | "
              f"{'Ratio':>6s} | {'vs None':>12s}")
        print(f"  {'-'*22} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*6} | {'-'*12}")

        for label in sorted(label_ratios.keys()):
            info = label_ratios[label]
            p99s = info['p99s']
            ratio = info['ratio']

            compression = ''
            if none_ratio and label != 'None':
                compression = f"{none_ratio:.1f}×→{ratio:.1f}×"

            faas_str = f"{p99s.get('faas', 0):>7.0f}ms" if 'faas' in p99s else '     N/A'
            ms_str = f"{p99s.get('microservices', 0):>7.0f}ms" if 'microservices' in p99s else '     N/A'
            mono_str = f"{p99s.get('monolith', 0):>7.0f}ms" if 'monolith' in p99s else '     N/A'

            print(f"  {label:>22s} | {faas_str} | {ms_str} | {mono_str} | "
                  f"{ratio:>5.1f}× | {compression:>12s}")

            cf = none_ratio / ratio if none_ratio and ratio > 0 else None
            all_rows.append({
                'hw_tier': tier['short'],
                'hw_label': tier['label'],
                'auth_label': label,
                'faas_p99': p99s.get('faas'),
                'ms_p99': p99s.get('microservices'),
                'mono_p99': p99s.get('monolith'),
                'max_p99': info['max_p99'],
                'min_p99': info['min_p99'],
                'ratio': ratio,
                'slowest_arch': info['slowest'],
                'fastest_arch': info['fastest'],
                'none_ratio': none_ratio,
                'compression_factor': cf,
            })

    result_df = pd.DataFrame(all_rows)
    if result_df.empty:
        print("\nNo data to plot!")
        return

    csv_path = f"{PLOT_DIR}/arch_ratio_compression.csv"
    result_df.to_csv(csv_path, index=False)
    print(f"\nSaved: {csv_path}")

    # ── Shared config for thesis-quality plots ──
    auth_order = [
        'None', 'None+CF',
        'Cognito', 'Cognito+CF',
        'Manual (bcrypt)', 'Manual (bcrypt)+CF',
        'Manual (argon2id)', 'Manual (argon2id)+CF',
        'Edge',       # Edge always uses CF, no separate +CF variant
        'Edge-Sel.',  # Edge-Selective always uses CF
    ]
    # German labels for thesis
    auth_labels_de = {
        'None': 'Ohne Auth',
        'None+CF': 'Ohne Auth\n+CF',
        'Cognito': 'Cognito',
        'Cognito+CF': 'Cognito\n+CF',
        'Manual (bcrypt)': 'Manuell\n(bcrypt)',
        'Manual (bcrypt)+CF': 'Manuell\n(bcrypt)+CF',
        'Manual (argon2id)': 'Manuell\n(argon2id)',
        'Manual (argon2id)+CF': 'Manuell\n(argon2id)+CF',
        'Edge': 'Edge',
        'Edge-Sel.': 'Edge-\nSelektiv',
    }
    present_labels = [l for l in auth_order if l in result_df['auth_label'].values]
    hw_tiers = result_df['hw_tier'].unique()

    # Arch name abbreviations for annotations
    arch_short = {'faas': 'FaaS', 'microservices': 'MS', 'monolith': 'Mono'}

    # Tier labels in German
    tier_labels_de = {'Small': 'Klein (FaaS 512 / Container S)',
                      'Large': 'Groß (FaaS 1024 / Container L)'}

    # ── PLOT 1: Architecture Ratio by Auth Config (Thesis quality) ──
    plt.rcParams.update({
        'font.size': 11,
        'axes.labelsize': 12,
        'axes.titlesize': 13,
        'xtick.labelsize': 9,
        'ytick.labelsize': 10,
        'legend.fontsize': 9,
        'font.family': 'serif',
    })

    fig, ax = plt.subplots(figsize=(14, 7.5))

    n_tiers = len(hw_tiers)
    x = np.arange(len(present_labels))
    width = 0.35

    tier_colors = {'Small': '#4A90D9', 'Large': '#E8913A'}
    tier_edge_colors = {'Small': '#2C5A8C', 'Large': '#A8601A'}

    for i, tier in enumerate(hw_tiers):
        tier_data = result_df[result_df['hw_tier'] == tier]
        vals = []
        inverted = []
        fastest_archs = []
        slowest_archs = []

        for label in present_labels:
            match = tier_data[tier_data['auth_label'] == label]
            if not match.empty:
                row = match.iloc[0]
                vals.append(row['ratio'])
                inverted.append(row['fastest_arch'] == 'faas' and label != 'None')
                fastest_archs.append(arch_short.get(row['fastest_arch'], ''))
                slowest_archs.append(arch_short.get(row['slowest_arch'], ''))
            else:
                vals.append(0)
                inverted.append(False)
                fastest_archs.append('')
                slowest_archs.append('')

        offset = (i - n_tiers / 2 + 0.5) * width
        bars = ax.bar(x + offset, vals, width,
                      label=tier_labels_de.get(tier, tier),
                      color=tier_colors.get(tier, f'C{i}'),
                      edgecolor=tier_edge_colors.get(tier, 'black'),
                      linewidth=0.8, alpha=0.9)

        for j, (bar, val) in enumerate(zip(bars, vals)):
            if val <= 0:
                continue

            # Main ratio label
            y_pos = bar.get_height() + 0.2
            label_text = f'{val:.1f}×'

            if inverted[j]:
                # Inverted case: red hatching + special annotation
                bar.set_hatch('///')
                bar.set_edgecolor('#B71C1C')
                bar.set_linewidth(1.2)
                ax.text(bar.get_x() + bar.get_width() / 2, y_pos,
                        label_text, ha='center', va='bottom', fontsize=8.5,
                        fontweight='bold', color='#B71C1C')
                # Inversion arrow annotation
                ax.annotate('INVERTIERT\n(FaaS schnellste)',
                            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(bar.get_x() + bar.get_width() / 2 + 0.6,
                                    bar.get_height() - 2),
                            fontsize=7.5, color='#B71C1C', fontweight='bold',
                            ha='center',
                            arrowprops=dict(arrowstyle='->', color='#B71C1C',
                                            lw=1.5, connectionstyle='arc3,rad=-0.2'))
            else:
                ax.text(bar.get_x() + bar.get_width() / 2, y_pos,
                        label_text, ha='center', va='bottom', fontsize=8.5,
                        fontweight='bold',
                        color=tier_edge_colors.get(tier, 'black'))

            # Fastest/slowest arch annotation below bar
            if fastest_archs[j] and val > 0:
                arch_text = f'{fastest_archs[j]}→{slowest_archs[j]}'
                ax.text(bar.get_x() + bar.get_width() / 2, -0.65,
                        arch_text, ha='center', va='top', fontsize=6.5,
                        color='#555555', rotation=0,
                        fontstyle='italic')

    # Reference lines for None baseline ratios
    for tier in hw_tiers:
        tier_data = result_df[result_df['hw_tier'] == tier]
        none_row = tier_data[tier_data['auth_label'] == 'None']
        if not none_row.empty:
            ratio = none_row.iloc[0]['ratio']
            color = tier_edge_colors.get(tier, 'gray')
            ax.axhline(y=ratio, color=color, linewidth=1.5, linestyle='--', alpha=0.4,
                        label=f'Baseline ohne Auth ({tier_labels_de.get(tier, tier).split(" (")[0]}: '
                              f'{ratio:.1f}×)')

    # Ratio = 1 reference line
    ax.axhline(y=1, color='#2E7D32', linewidth=1.0, linestyle=':', alpha=0.5)
    ax.text(len(present_labels) - 0.3, 1.3, 'Kein Unterschied (1×)', fontsize=7.5,
            color='#2E7D32', alpha=0.7, ha='right', fontstyle='italic')

    # Zone shading
    ax.axhspan(0, 2, alpha=0.04, color='green')
    ax.axhspan(2, 5, alpha=0.03, color='yellow')
    ax.axhspan(5, 20, alpha=0.03, color='red')

    # Zone labels on right
    ax2 = ax.twinx()
    ax2.set_ylim(ax.get_ylim())
    ax2.set_yticks([1, 3.5, 12])
    ax2.set_yticklabels(['Stark\nnivelliert', 'Moderat\nnivelliert', 'Große\nUnterschiede'],
                        fontsize=8, color='#666666')
    ax2.tick_params(axis='y', length=0)

    ax.set_xticks(x)
    ax.set_xticklabels([auth_labels_de.get(l, l) for l in present_labels],
                        fontsize=9, ha='center')
    ax.set_ylabel('Architekturverhältnis\n(P99 langsamste / P99 schnellste Architektur)',
                  fontsize=11)
    ax.set_xlabel('Authentifizierungskonfiguration', fontsize=11)
    ax.set_title('Nivellierung der Architekturleistungsunterschiede\nnach Auth-Konfiguration'
                 ' (Baseline-Phase, P99)',
                 fontsize=13, fontweight='bold', pad=15)
    ax.legend(fontsize=9, loc='upper left', framealpha=0.9)
    ax.grid(axis='y', alpha=0.2, linewidth=0.5)
    ax.set_ylim(bottom=-1.2, top=max(result_df['ratio'].max() + 1.5, 20))
    ax.set_xlim(-0.6, len(present_labels) - 0.4)

    plt.tight_layout()
    path = f"{PLOT_DIR}/arch_ratio_compression.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()

    # ── PLOT 2: Compression factor heatmap (Thesis quality) ──
    # Build pivot with ratio, compression factor, and fastest arch for annotation
    pivot_ratio = result_df.pivot_table(
        index='auth_label', columns='hw_tier', values='ratio')
    pivot_cf = result_df.pivot_table(
        index='auth_label', columns='hw_tier', values='compression_factor')
    pivot_fastest = result_df.pivot_table(
        index='auth_label', columns='hw_tier', values='fastest_arch', aggfunc='first')

    # Reorder
    ordered_labels = [l for l in auth_order if l in pivot_cf.index]
    tier_cols = [t for t in ['Small', 'Large'] if t in pivot_cf.columns]
    pivot_ratio = pivot_ratio.reindex(ordered_labels)[tier_cols]
    pivot_cf = pivot_cf.reindex(ordered_labels)[tier_cols]
    pivot_fastest = pivot_fastest.reindex(ordered_labels)[tier_cols]

    if not pivot_cf.empty and pivot_cf.notna().any().any():
        fig, ax = plt.subplots(figsize=(9, max(6, len(pivot_cf) * 0.7 + 1)))

        # Use diverging colormap centered at 1 (no change)
        from matplotlib.colors import TwoSlopeNorm
        max_val = min(pivot_cf.max().max() * 1.05, 16)
        norm = TwoSlopeNorm(vmin=0, vcenter=1, vmax=max_val)

        im = ax.imshow(pivot_cf.values, cmap='RdYlGn', aspect='auto', norm=norm)

        ax.set_xticks(range(len(tier_cols)))
        ax.set_xticklabels([tier_labels_de.get(t, t) for t in tier_cols],
                            fontsize=10, fontweight='bold')
        ax.set_yticks(range(len(ordered_labels)))
        ax.set_yticklabels([auth_labels_de.get(l, l).replace('\n', ' ')
                            for l in ordered_labels], fontsize=10)

        # Annotate cells with ratio + compression + arch info
        for i in range(len(ordered_labels)):
            for j in range(len(tier_cols)):
                cf_val = pivot_cf.iloc[i, j]
                ratio_val = pivot_ratio.iloc[i, j]
                fastest = pivot_fastest.iloc[i, j]

                if pd.notna(cf_val) and pd.notna(ratio_val):
                    # Main text: compression factor
                    is_inverted = fastest == 'faas' and ordered_labels[i] != 'None'
                    is_baseline = ordered_labels[i] == 'None'

                    if is_baseline:
                        main_text = f'Baseline\n({ratio_val:.1f}×)'
                        color = 'white'
                        fontsize = 10
                    elif is_inverted:
                        main_text = f'{cf_val:.1f}× Kompression\n({ratio_val:.1f}× Ratio)\n⚠ INVERTIERT'
                        color = 'white'
                        fontsize = 9
                    elif cf_val >= 5:
                        main_text = f'{cf_val:.1f}× Kompr.\n({ratio_val:.1f}× Ratio)'
                        color = 'white'
                        fontsize = 10
                    else:
                        main_text = f'{cf_val:.1f}× Kompr.\n({ratio_val:.1f}× Ratio)'
                        color = 'black' if cf_val > 0.8 else 'white'
                        fontsize = 10

                    ax.text(j, i, main_text, ha='center', va='center',
                            fontsize=fontsize, fontweight='bold', color=color,
                            linespacing=1.3)
                else:
                    ax.text(j, i, 'Keine\nDaten', ha='center', va='center',
                            fontsize=9, color='gray', fontstyle='italic')

        cbar = plt.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
        cbar.set_label('Kompressionsfaktor\n(>1 = Lücke schrumpft, <1 = Lücke wächst)',
                        fontsize=10)
        cbar.ax.axhline(y=1, color='black', linewidth=2)

        ax.set_title('Kompression des Architekturleistungsabstands\nnach Auth-Konfiguration'
                     ' (Baseline-Ratio ÷ Config-Ratio)',
                     fontsize=12, fontweight='bold', pad=15)

        # Add subtle grid lines between cells
        for i in range(len(ordered_labels) + 1):
            ax.axhline(y=i - 0.5, color='white', linewidth=2)
        for j in range(len(tier_cols) + 1):
            ax.axvline(x=j - 0.5, color='white', linewidth=2)

        plt.tight_layout()
        path = f"{PLOT_DIR}/arch_ratio_compression_detail.pdf"
        fig.savefig(path, dpi=300, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # ── Summary ──
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)

    for tier in hw_tiers:
        tier_data = result_df[result_df['hw_tier'] == tier].sort_values('ratio')
        none_row = tier_data[tier_data['auth_label'] == 'None']
        if none_row.empty:
            continue
        baseline = none_row.iloc[0]['ratio']
        print(f"\n  {tier} tier (None baseline: {baseline:.1f}×):")
        for _, row in tier_data.iterrows():
            if row['auth_label'] == 'None':
                continue
            direction = '↓' if row['ratio'] < baseline else '↑'
            cf = row.get('compression_factor')
            cf_str = f" ({cf:.1f}× compression)" if pd.notna(cf) and cf > 1 else \
                     f" ({1/cf:.1f}× expansion)" if pd.notna(cf) and cf < 1 else ""
            inverted = " ⚠ INVERTED" if row['fastest_arch'] == 'faas' else ""
            print(f"    {row['auth_label']:>22s}: {row['ratio']:>5.1f}× {direction}{cf_str}"
                  f"  [fastest={row['fastest_arch']}, slowest={row['slowest_arch']}]{inverted}")

    print()


if __name__ == '__main__':
    main()
