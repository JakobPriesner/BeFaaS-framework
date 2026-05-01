#!/usr/bin/env python3
"""Generate arch_ratio_compression.pdf for fig:arch-ratio-compression.

Grouped bar chart showing architecture performance ratio (P99 slowest / P99
fastest) per auth config. Compares Small and Large HW tiers. Demonstrates
the equalizing effect where auth overhead compresses the architecture gap.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL, DETAILED_AUTH_SQL,
                           auth_label_detailed, AUTH_COLORS_DETAILED)

HW_TIER_GROUPS = [
    {'label': 'Small (FaaS 512 / Container S)', 'short': 'Small',
     'faas': {'ram': 512}, 'microservices': {'ram': 512, 'cpu': 0.25},
     'monolith': {'ram': 512, 'cpu': 0.25}},
    {'label': 'Large (FaaS 1024 / Container L)', 'short': 'Large',
     'faas': {'ram': 1024}, 'microservices': {'ram': 2048, 'cpu': 1.0},
     'monolith': {'ram': 2048, 'cpu': 1.0}},
]


def query_p99_by_config(arch, ram, cpu=None, include_es=False):
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu is None else f"AND e.cpu_in_vcpu = {cpu}"
    df = query_df(f"""
        SELECT e.auth_strategy, {DETAILED_AUTH_SQL},
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL} AND e.architecture = '{arch}'
          AND e.ram_in_mb = {ram} {cpu_clause}
          AND e.auth_strategy != 'edge-selective' AND r.phase_name = 'Baseline'
        GROUP BY e.auth_strategy, algo, with_cf
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)
    if include_es:
        es_df = query_df(f"""
            SELECT e.auth_strategy,
                   COALESCE(e.password_hash_algorithm, 'default') AS algo,
                   COALESCE(e.with_cloudfront, false) AS with_cf,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                       FILTER (WHERE NOT r.is_error) AS p99
            FROM experiments e JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL} AND e.architecture = '{arch}'
              AND e.ram_in_mb = {ram} {cpu_clause}
              AND e.auth_strategy = 'edge-selective' AND r.phase_name = 'Baseline'
            GROUP BY e.auth_strategy, algo, with_cf
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)
        if not es_df.empty:
            df = pd.concat([df, es_df], ignore_index=True)
    if df.empty:
        return df
    df['p99'] = df['p99'].astype(float)
    df['auth_label'] = df.apply(
        lambda r: auth_label_detailed(r['auth_strategy'], r['algo'], r['with_cf']), axis=1)
    return df


def main():
    all_rows = []
    for tier in HW_TIER_GROUPS:
        arch_data = {}
        for arch_name in ['faas', 'microservices', 'monolith']:
            cfg = tier[arch_name]
            df = query_p99_by_config(arch_name, cfg['ram'], cfg.get('cpu'), include_es=True)
            if not df.empty:
                arch_data[arch_name] = df
        if len(arch_data) < 2:
            continue

        all_labels = set()
        for df in arch_data.values():
            all_labels.update(df['auth_label'].tolist())

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
            label_ratios[label] = {
                'p99s': p99s, 'ratio': ratio,
                'slowest': max(p99s, key=p99s.get),
                'fastest': min(p99s, key=p99s.get),
            }

        none_ratio = label_ratios.get('None', {}).get('ratio')
        for label, info in label_ratios.items():
            cf = none_ratio / info['ratio'] if none_ratio and info['ratio'] > 0 else None
            all_rows.append({
                'hw_tier': tier['short'], 'auth_label': label,
                'ratio': info['ratio'], 'fastest_arch': info['fastest'],
                'slowest_arch': info['slowest'], 'none_ratio': none_ratio,
                'compression_factor': cf,
            })

    result_df = pd.DataFrame(all_rows)
    if result_df.empty:
        print('No data'); return

    auth_order = ['None', 'None+CF', 'Cognito', 'Cognito+CF',
                  'Manual (bcrypt)', 'Manual (bcrypt)+CF',
                  'Manual (argon2id)', 'Manual (argon2id)+CF',
                  'Edge', 'Edge-Sel.']
    auth_labels_de = {
        'None': 'Ohne Auth', 'None+CF': 'Ohne Auth\n+CF',
        'Cognito': 'Cognito', 'Cognito+CF': 'Cognito\n+CF',
        'Manual (bcrypt)': 'Manuell\n(bcrypt)', 'Manual (bcrypt)+CF': 'Manuell\n(bcrypt)+CF',
        'Manual (argon2id)': 'Manuell\n(argon2id)', 'Manual (argon2id)+CF': 'Manuell\n(argon2id)+CF',
        'Edge': 'Edge', 'Edge-Sel.': 'Edge-\nSelektiv',
    }
    present_labels = [l for l in auth_order if l in result_df['auth_label'].values]
    hw_tiers = result_df['hw_tier'].unique()
    arch_short = {'faas': 'FaaS', 'microservices': 'MS', 'monolith': 'Mono'}
    tier_labels_de = {'Small': 'Klein (FaaS 512 / Container S)',
                      'Large': 'Groß (FaaS 1024 / Container L)'}

    plt.rcParams.update({'font.size': 11, 'axes.labelsize': 12, 'axes.titlesize': 13,
                         'xtick.labelsize': 9, 'ytick.labelsize': 10,
                         'legend.fontsize': 9, 'font.family': 'serif'})

    fig, ax = plt.subplots(figsize=(14, 7.5))
    n_tiers = len(hw_tiers)
    x = np.arange(len(present_labels))
    width = 0.35
    tier_colors = {'Small': '#4A90D9', 'Large': '#E8913A'}
    tier_edge_colors = {'Small': '#2C5A8C', 'Large': '#A8601A'}

    for i, tier in enumerate(hw_tiers):
        tier_data = result_df[result_df['hw_tier'] == tier]
        vals, inverted, fastest_archs, slowest_archs = [], [], [], []
        for label in present_labels:
            match = tier_data[tier_data['auth_label'] == label]
            if not match.empty:
                row = match.iloc[0]
                vals.append(row['ratio'])
                inverted.append(row['fastest_arch'] == 'faas' and label != 'None')
                fastest_archs.append(arch_short.get(row['fastest_arch'], ''))
                slowest_archs.append(arch_short.get(row['slowest_arch'], ''))
            else:
                vals.append(0); inverted.append(False)
                fastest_archs.append(''); slowest_archs.append('')

        offset = (i - n_tiers / 2 + 0.5) * width
        bars = ax.bar(x + offset, vals, width,
                      label=tier_labels_de.get(tier, tier),
                      color=tier_colors.get(tier, f'C{i}'),
                      edgecolor=tier_edge_colors.get(tier, 'black'),
                      linewidth=0.8, alpha=0.9)

        for j, (bar, val) in enumerate(zip(bars, vals)):
            if val <= 0:
                continue
            y_pos = bar.get_height() + 0.2
            if inverted[j]:
                bar.set_hatch('///')
                bar.set_edgecolor('#B71C1C')
                bar.set_linewidth(1.2)
                ax.text(bar.get_x() + bar.get_width() / 2, y_pos,
                        f'{val:.1f}×', ha='center', va='bottom', fontsize=8.5,
                        fontweight='bold', color='#B71C1C')
                ax.annotate('INVERTIERT\n(FaaS schnellste)',
                            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(bar.get_x() + bar.get_width() / 2 + 0.6,
                                    bar.get_height() - 2),
                            fontsize=7.5, color='#B71C1C', fontweight='bold', ha='center',
                            arrowprops=dict(arrowstyle='->', color='#B71C1C',
                                            lw=1.5, connectionstyle='arc3,rad=-0.2'))
            else:
                ax.text(bar.get_x() + bar.get_width() / 2, y_pos,
                        f'{val:.1f}×', ha='center', va='bottom', fontsize=8.5,
                        fontweight='bold', color=tier_edge_colors.get(tier, 'black'))
            if fastest_archs[j]:
                ax.text(bar.get_x() + bar.get_width() / 2, -0.65,
                        f'{fastest_archs[j]}→{slowest_archs[j]}',
                        ha='center', va='top', fontsize=6.5, color='#555555',
                        fontstyle='italic')

    for tier in hw_tiers:
        td = result_df[result_df['hw_tier'] == tier]
        nr = td[td['auth_label'] == 'None']
        if not nr.empty:
            r = nr.iloc[0]['ratio']
            ax.axhline(y=r, color=tier_edge_colors.get(tier, 'gray'),
                       linewidth=1.5, linestyle='--', alpha=0.4,
                       label=f'Baseline ohne Auth ({tier_labels_de.get(tier, tier).split(" (")[0]}: {r:.1f}×)')

    ax.axhline(y=1, color='#2E7D32', linewidth=1.0, linestyle=':', alpha=0.5)
    ax.text(len(present_labels) - 0.3, 1.3, 'Kein Unterschied (1×)',
            fontsize=7.5, color='#2E7D32', alpha=0.7, ha='right', fontstyle='italic')
    ax.axhspan(0, 2, alpha=0.04, color='green')
    ax.axhspan(2, 5, alpha=0.03, color='yellow')
    ax.axhspan(5, 20, alpha=0.03, color='red')

    ax2 = ax.twinx()
    ax2.set_ylim(ax.get_ylim())
    ax2.set_yticks([1, 3.5, 12])
    ax2.set_yticklabels(['Stark\nnivelliert', 'Moderat\nnivelliert', 'Große\nUnterschiede'],
                        fontsize=8, color='#666666')
    ax2.tick_params(axis='y', length=0)

    ax.set_xticks(x)
    ax.set_xticklabels([auth_labels_de.get(l, l) for l in present_labels], fontsize=9, ha='center')
    ax.set_ylabel('Architekturverhältnis\n(P99 langsamste / P99 schnellste Architektur)', fontsize=11)
    ax.set_xlabel('Authentifizierungskonfiguration', fontsize=11)
    ax.set_title('Nivellierung der Architekturleistungsunterschiede\nnach Auth-Konfiguration'
                 ' (Baseline-Phase, P99)', fontsize=13, fontweight='bold', pad=15)
    ax.legend(fontsize=9, loc='upper left', framealpha=0.9)
    ax.grid(axis='y', alpha=0.2, linewidth=0.5)
    ax.set_ylim(bottom=-1.2, top=max(result_df['ratio'].max() + 1.5, 20))
    ax.set_xlim(-0.6, len(present_labels) - 0.4)
    plt.tight_layout()
    path = f"{PLOT_DIR}/arch_ratio_compression.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
