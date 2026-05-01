#!/usr/bin/env python3
"""Generate network_overhead_decomposition.pdf for fig:network-decomp.

2-panel stacked bar chart (FaaS | Microservices) decomposing mean latency
into handler execution time and network overhead. Uses arithmetic means
(E[X+Y]=E[X]+E[Y]) for additive decomposition. Microservices panel uses
broken y-axis to accommodate argon2id outliers.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL, auth_label_detailed)


def main():
    net_data = query_df(f"""
        WITH traced AS (
            SELECT
                e.architecture, e.auth_strategy,
                CASE WHEN e.auth_strategy = 'service-integrated-manual'
                     THEN COALESCE(e.password_hash_algorithm, 'bcrypt')
                     ELSE 'default'
                END AS algo,
                r.latency_ms,
                r.handler_duration_ms,
                COALESCE(r.network_overhead_ms, 0) AS network_ms,
                r.latency_ms - r.handler_duration_ms
                    - COALESCE(r.network_overhead_ms, 0) AS other_ms
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL}
              AND r.phase_name = 'Baseline'
              AND e.auth_strategy != 'edge-selective'
              AND NOT r.is_error
              AND r.handler_duration_ms > 0
              AND r.latency_ms > 0
        )
        SELECT
            architecture, auth_strategy, algo,
            AVG(handler_duration_ms) AS mean_handler,
            AVG(network_ms) AS mean_network,
            AVG(GREATEST(other_ms, 0)) AS mean_other,
            AVG(latency_ms) AS mean_total,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50_total,
            COUNT(*) AS n_traced
        FROM traced
        GROUP BY architecture, auth_strategy, algo
        HAVING COUNT(*) > 500
    """)
    if net_data.empty:
        print('No data'); return

    for col in ['mean_handler', 'mean_network', 'mean_other', 'mean_total', 'p50_total']:
        net_data[col] = net_data[col].astype(float)

    net_data['auth_label'] = net_data.apply(
        lambda r: auth_label_detailed(r['auth_strategy'], r['algo']), axis=1)

    label_order = ['None', 'Cognito', 'Manual (bcrypt)', 'Manual (argon2id)', 'Edge']
    label_map = {
        'None': 'None', 'Cognito': 'Cognito',
        'Manual (bcrypt)': 'Manual\n(bcrypt)',
        'Manual (argon2id)': 'Manual\n(argon2id)', 'Edge': 'Edge',
    }
    net_data['plot_label'] = net_data['auth_label'].map(label_map)

    def _prep(arch):
        ar = net_data[net_data['architecture'] == arch].copy()
        ar['_s'] = ar['auth_label'].map({l: i for i, l in enumerate(label_order)})
        return ar.sort_values('_s').dropna(subset=['_s'])

    faas_df = _prep('faas')
    ms_df = _prep('microservices')

    if faas_df.empty and ms_df.empty:
        print('No traced data'); return

    BREAK_LO = 100
    BREAK_HI = 900
    HEIGHT_RATIO = 0.35
    w = 0.6

    fig = plt.figure(figsize=(14, 7))
    outer_gs = gridspec.GridSpec(1, 2, figure=fig, wspace=0.15)

    ax_faas = fig.add_subplot(outer_gs[0])
    labels = faas_df['plot_label'].tolist()
    hv = faas_df['mean_handler'].values
    nv = faas_df['mean_network'].values
    mt = faas_df['mean_total'].values
    p5 = faas_df['p50_total'].values
    x = np.arange(len(labels))

    ax_faas.bar(x, hv, w, label='Handler-Ausführungszeit', color='#3498db', alpha=0.85)
    ax_faas.bar(x, nv, w, bottom=hv, label='Netzwerk-Overhead\n(Latenz − Handler)',
                color='#e74c3c', alpha=0.85)
    for j, m in enumerate(mt):
        ax_faas.text(j, m + 3, f'Ø {m:.0f} ms', ha='center', va='bottom',
                     fontsize=8, fontweight='bold')
    for j, p in enumerate(p5):
        ax_faas.plot(j + w / 2 + 0.08, p, marker='D', color='black', markersize=5, zorder=5)
        if j == 0:
            ax_faas.plot([], [], marker='D', color='black', markersize=5,
                         linestyle='None', label='P50 (Referenz)')
    ax_faas.set_xticks(x)
    ax_faas.set_xticklabels(labels, fontsize=9)
    ax_faas.set_ylabel('Latenz (ms)', fontsize=11)
    ax_faas.set_title('FaaS', fontweight='bold', fontsize=13)
    ax_faas.set_ylim(0, max(mt) * 1.18)
    ax_faas.grid(axis='y', alpha=0.3)
    ax_faas.legend(fontsize=9, loc='upper left')

    inner_gs = gridspec.GridSpecFromSubplotSpec(
        2, 1, subplot_spec=outer_gs[1],
        height_ratios=[HEIGHT_RATIO, 1], hspace=0.06)
    ax_ms_top = fig.add_subplot(inner_gs[0])
    ax_ms_bot = fig.add_subplot(inner_gs[1])

    labels = ms_df['plot_label'].tolist()
    hv = ms_df['mean_handler'].values
    nv = ms_df['mean_network'].values
    mt = ms_df['mean_total'].values
    p5 = ms_df['p50_total'].values
    x = np.arange(len(labels))

    for ax in (ax_ms_top, ax_ms_bot):
        ax.bar(x, hv, w, color='#3498db', alpha=0.85)
        ax.bar(x, nv, w, bottom=hv, color='#e74c3c', alpha=0.85)
        ax.set_xticks(x)
        ax.grid(axis='y', alpha=0.3)

    for j, p in enumerate(p5):
        for ax in (ax_ms_top, ax_ms_bot):
            ax.plot(j + w / 2 + 0.08, p, marker='D', color='black', markersize=5, zorder=5)

    y_max_upper = max(mt) * 1.15
    ax_ms_top.set_ylim(BREAK_HI, y_max_upper)
    ax_ms_bot.set_ylim(0, BREAK_LO)

    ax_ms_top.spines['bottom'].set_visible(False)
    ax_ms_bot.spines['top'].set_visible(False)
    ax_ms_top.tick_params(bottom=False, labelbottom=False)

    ax_ms_top.axhline(y=ax_ms_top.get_ylim()[0], color='black',
                       linewidth=1.5, clip_on=False, zorder=10)
    ax_ms_bot.axhline(y=ax_ms_bot.get_ylim()[1], color='black',
                       linewidth=1.5, clip_on=False, zorder=10)

    top_ticks = [t for t in range(900, int(y_max_upper) + 200, 200) if t <= y_max_upper]
    ax_ms_top.set_yticks(top_ticks)

    ax_ms_bot.set_xticklabels(labels, fontsize=9)
    ax_ms_bot.set_ylabel('Latenz (ms)', fontsize=11)

    for j, m in enumerate(mt):
        if m > BREAK_LO:
            ax_ms_top.text(j, m + (y_max_upper - BREAK_HI) * 0.03,
                           f'Ø {m:.0f} ms', ha='center', va='bottom',
                           fontsize=8, fontweight='bold')
        else:
            ax_ms_bot.text(j, m + BREAK_LO * 0.03,
                           f'Ø {m:.0f} ms', ha='center', va='bottom',
                           fontsize=8, fontweight='bold')

    ax_ms_top.set_title('Microservices', fontweight='bold', fontsize=13)

    fig.suptitle('Latenzzerlegung in Handler- und Netzwerk-Anteil\n'
                 '(Baseline-Phase, arithm. Mittelwert Ø; ◆ = P50)',
                 fontweight='bold', fontsize=13, y=1.0)
    fig.subplots_adjust(top=0.88)
    path = f"{PLOT_DIR}/network_overhead_decomposition.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
