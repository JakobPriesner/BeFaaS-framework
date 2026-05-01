#!/usr/bin/env python3
"""
22 — CDF Comparisons & Cold Start × Auth Interaction
1. CDF plots: latency distribution with/without auth per architecture
2. Cold start analysis: does auth increase cold start duration/frequency?
3. Network overhead decomposition: where does the time go?
Outputs: cdf_auth_comparison_*.pdf, cold_start_auth.csv,
         cold_start_auth.pdf, network_overhead_decomposition.pdf
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
                           AUTH_COLORS)

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}


def main():
    print("=" * 70)
    print("22 — CDF COMPARISONS & COLD START × AUTH INTERACTION")
    print("=" * 70)

    # ══════════════════════════════════════════════════════════════════════
    # PART 1: CDF PLOTS — Latency distribution with/without auth
    # ══════════════════════════════════════════════════════════════════════
    print("\n--- PART 1: CDF PLOTS ---")

    # Pick representative configs per architecture
    configs = {
        'faas': {'ram': 512, 'cpu': 0},
        'microservices': {'ram': 2048, 'cpu': 1.0},
        'monolith': {'ram': 2048, 'cpu': 1.0},
    }

    for arch, cfg in configs.items():
        # Get raw latency samples (limited for performance)
        cdf_data = query_df(f"""
            SELECT
                e.auth_strategy,
                r.latency_ms
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL}
              AND e.architecture = '{arch}'
              AND e.ram_in_mb = {cfg['ram']}
              AND r.phase_name = 'Baseline'
              AND NOT r.is_error
              AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
              AND r.latency_ms < 3000
            ORDER BY RANDOM()
            LIMIT 500000
        """)

        if cdf_data.empty:
            print(f"  {arch}: no data for CDF")
            continue

        fig, ax = plt.subplots(figsize=(10, 6))
        auth_order = ['none', 'service-integrated', 'service-integrated-manual', 'edge']

        for auth in auth_order:
            vals = cdf_data[cdf_data['auth_strategy'] == auth]['latency_ms'].values
            if len(vals) < 100:
                continue
            vals_sorted = np.sort(vals)
            cdf = np.arange(1, len(vals_sorted) + 1) / len(vals_sorted)
            label = f"{AUTH_SHORT.get(auth, auth)} (n={len(vals):,})"
            ax.plot(vals_sorted, cdf, label=label,
                    color=AUTH_COLORS.get(AUTH_SHORT.get(auth, auth), '#999'), linewidth=1.5)

        ax.set_xlabel('Latency (ms)')
        ax.set_ylabel('CDF (cumulative probability)')
        hw_str = f"{cfg['ram']}MB" if arch == 'faas' else \
            {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}.get(cfg['cpu'], str(cfg['cpu']))
        ax.set_title(f'{arch} ({hw_str}): Baseline Latency CDF by Auth Strategy',
                     fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

        # Add percentile markers
        for pct in [0.50, 0.95, 0.99]:
            ax.axhline(y=pct, color='gray', linestyle=':', alpha=0.3)
            ax.text(ax.get_xlim()[1] * 0.95, pct + 0.01, f'P{int(pct*100)}',
                    fontsize=7, ha='right', color='gray')

        plt.tight_layout()
        path = f"{PLOT_DIR}/cdf_auth_comparison_{arch}.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # ══════════════════════════════════════════════════════════════════════
    # PART 2: COLD START × AUTH INTERACTION (FaaS only)
    # ══════════════════════════════════════════════════════════════════════
    print("\n--- PART 2: COLD START × AUTH ---")

    # Aggregate in SQL instead of pulling all lambda_executions into pandas —
    # the raw table has tens of millions of rows per architecture and killed
    # the process when loaded fully.
    cs_summary = query_df(f"""
        SELECT
            e.auth_strategy,
            e.ram_in_mb,
            COUNT(*) AS total_invocations,
            SUM(CASE WHEN l.is_cold_start THEN 1 ELSE 0 END) AS cold_starts,
            AVG(l.init_duration_ms) FILTER (WHERE l.init_duration_ms > 0) AS avg_init_ms,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY l.init_duration_ms)
                FILTER (WHERE l.init_duration_ms > 0) AS median_init_ms,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY l.init_duration_ms)
                FILTER (WHERE l.init_duration_ms > 0) AS p99_init_ms,
            AVG(l.duration_ms) AS avg_duration_ms,
            AVG(l.max_memory_used_mb::float / NULLIF(l.memory_size_mb, 0) * 100) AS avg_memory_pct
        FROM experiments e
        JOIN lambda_executions l ON l.experiment_id = e.id
        WHERE e.architecture = 'faas' AND {EXCLUDE_SQL}
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND l.duration_ms > 0 AND l.duration_ms < 30000
        GROUP BY e.auth_strategy, e.ram_in_mb
    """)

    if cs_summary.empty:
        print("  No lambda_executions data available.")
    else:
        cs_summary['cold_start_pct'] = cs_summary['cold_starts'] / cs_summary['total_invocations'] * 100
        cs_summary.to_csv(f"{PLOT_DIR}/cold_start_auth.csv", index=False)
        print(f"Saved: {PLOT_DIR}/cold_start_auth.csv")

        print("\n  COLD START RATE & INIT DURATION BY AUTH:")
        for _, r in cs_summary.sort_values(['ram_in_mb', 'auth_strategy']).iterrows():
            auth_label = AUTH_SHORT.get(r['auth_strategy'], r['auth_strategy'])
            print(f"    {r['ram_in_mb']:>5.0f}MB / {auth_label:>8s}: "
                  f"CS rate={r['cold_start_pct']:.3f}% "
                  f"({r['cold_starts']:.0f}/{r['total_invocations']:.0f}), "
                  f"init_avg={r['avg_init_ms']:.0f}ms, "
                  f"init_p99={r['p99_init_ms']:.0f}ms, "
                  f"mem_used={r['avg_memory_pct']:.0f}%")

        # Plot: Cold start init duration by auth strategy
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        # Left: Cold start rate
        ax = axes[0]
        for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
            sub = cs_summary[cs_summary['auth_strategy'] == auth].sort_values('ram_in_mb')
            if not sub.empty:
                ax.plot(sub['ram_in_mb'], sub['cold_start_pct'], 'o-',
                        label=AUTH_SHORT.get(auth, auth),
                        color=AUTH_COLORS.get(AUTH_SHORT.get(auth, auth), '#999'), linewidth=2)
        ax.set_xlabel('Lambda Memory (MB)')
        ax.set_ylabel('Cold Start Rate (%)')
        ax.set_title('Cold Start Rate by Auth Strategy', fontweight='bold')
        ax.legend()
        ax.grid(alpha=0.3)

        # Right: Init duration
        ax = axes[1]
        for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
            sub = cs_summary[cs_summary['auth_strategy'] == auth].sort_values('ram_in_mb')
            if not sub.empty:
                ax.plot(sub['ram_in_mb'], sub['avg_init_ms'], 'o-',
                        label=AUTH_SHORT.get(auth, auth),
                        color=AUTH_COLORS.get(AUTH_SHORT.get(auth, auth), '#999'), linewidth=2)
        ax.set_xlabel('Lambda Memory (MB)')
        ax.set_ylabel('Avg Init Duration (ms)')
        ax.set_title('Cold Start Init Duration by Auth Strategy', fontweight='bold')
        ax.legend()
        ax.grid(alpha=0.3)

        fig.suptitle('Cold Start × Authentication Interaction (FaaS)',
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/cold_start_auth.pdf"
        fig.savefig(path, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

        # Per-function cold start analysis — again aggregated in SQL to avoid
        # pulling the entire lambda_executions table into memory.
        func_cs = query_df(f"""
            SELECT
                e.auth_strategy,
                l.function_name,
                l.is_cold_start,
                COUNT(*) AS count,
                AVG(l.duration_ms) AS avg_dur,
                AVG(l.init_duration_ms) FILTER (WHERE l.init_duration_ms > 0) AS avg_init
            FROM experiments e
            JOIN lambda_executions l ON l.experiment_id = e.id
            WHERE e.architecture = 'faas' AND {EXCLUDE_SQL}
              AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
              AND l.duration_ms > 0 AND l.duration_ms < 30000
              AND l.function_name IN ('login', 'register', 'frontend')
              AND l.is_cold_start = true
            GROUP BY e.auth_strategy, l.function_name, l.is_cold_start
        """)

        print("\n  AUTH IMPACT ON COLD START INIT DURATION (by function):")
        for func in ['login', 'register', 'frontend']:
            func_data = func_cs[func_cs['function_name'] == func]
            if func_data.empty:
                continue
            print(f"\n    Function: {func}")
            for _, r in func_data.iterrows():
                auth_label = AUTH_SHORT.get(r['auth_strategy'], r['auth_strategy'])
                if pd.notna(r['avg_init']):
                    print(f"      {auth_label:>8s}: avg_init={r['avg_init']:.0f}ms (n={r['count']:.0f})")

    # ══════════════════════════════════════════════════════════════════════
    # PART 3: NETWORK OVERHEAD DECOMPOSITION
    # ══════════════════════════════════════════════════════════════════════
    print("\n--- PART 3: NETWORK OVERHEAD DECOMPOSITION ---")
    print("  Using arithmetic means (E[X+Y]=E[X]+E[Y] guarantees additive decomposition).")
    print("  Percentiles are NOT additive and must not be stacked.")

    # Per-request decomposition: compute other_ms = latency - handler - network
    # for each request, then aggregate with means over the SAME request set.
    # Also compute P50 of total latency (over ALL requests) as reference.
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

    if not net_data.empty:
        for col in ['mean_handler', 'mean_network', 'mean_other',
                     'mean_total', 'p50_total']:
            net_data[col] = net_data[col].astype(float)

        net_data['auth_label'] = net_data.apply(
            lambda r: auth_label_detailed(r['auth_strategy'], r['algo']), axis=1)

        # Verify additivity: mean_handler + mean_network + mean_other ≈ mean_total
        net_data['sum_check'] = (net_data['mean_handler'] + net_data['mean_network']
                                 + net_data['mean_other'])
        net_data['additivity_err'] = abs(net_data['sum_check'] - net_data['mean_total'])

        print("\n  LATENCY DECOMPOSITION (Baseline, arithmetic mean over traced requests):")
        print(f"  {'Arch':>14s} | {'Auth':>20s} | {'Mean':>7s} | {'Handler':>8s} | "
              f"{'Network':>8s} | {'Other':>7s} | {'H+N+O':>7s} | {'P50ref':>7s} | {'n':>7s}")
        print(f"  {'-'*14} | {'-'*20} | {'-'*7} | {'-'*8} | {'-'*8} | "
              f"{'-'*7} | {'-'*7} | {'-'*7} | {'-'*7}")
        for _, r in net_data.sort_values(['architecture', 'auth_label']).iterrows():
            print(f"  {r['architecture']:>14s} | {r['auth_label']:>20s} | "
                  f"{r['mean_total']:>6.1f}ms | {r['mean_handler']:>7.1f}ms | "
                  f"{r['mean_network']:>7.1f}ms | {r['mean_other']:>6.1f}ms | "
                  f"{r['sum_check']:>6.1f}ms | {r['p50_total']:>6.0f}ms | "
                  f"{r['n_traced']:>7.0f}")

        max_err = net_data['additivity_err'].max()
        print(f"\n  Additivity check: max |H+N+O - Mean| = {max_err:.3f}ms (should be ~0)")

        # ── Stacked bar chart (arithmetic means, broken y-axis for MS) ──
        import matplotlib.gridspec as gridspec

        label_order = ['None', 'Cognito', 'Manual (bcrypt)',
                       'Manual (argon2id)', 'Edge']
        # Multiline x-tick labels for readability
        label_map = {
            'None': 'None', 'Cognito': 'Cognito',
            'Manual (bcrypt)': 'Manual\n(bcrypt)',
            'Manual (argon2id)': 'Manual\n(argon2id)', 'Edge': 'Edge',
        }
        net_data['plot_label'] = net_data['auth_label'].map(label_map)

        def draw_break_lines(ax_top, ax_bot):
            """Solid horizontal break lines (thesis style)."""
            ax_top.axhline(y=ax_top.get_ylim()[0], color='black',
                           linewidth=1.5, clip_on=False, zorder=10)
            ax_bot.axhline(y=ax_bot.get_ylim()[1], color='black',
                           linewidth=1.5, clip_on=False, zorder=10)

        def _prep(arch):
            """Return sorted data for one architecture."""
            ar = net_data[net_data['architecture'] == arch].copy()
            ar['_s'] = ar['auth_label'].map(
                {l: i for i, l in enumerate(label_order)})
            return ar.sort_values('_s').dropna(subset=['_s'])

        faas_df = _prep('faas')
        ms_df = _prep('microservices')

        if faas_df.empty and ms_df.empty:
            print("  No traced request data, skipping plot")
        else:
            # Break parameters for MS panel (argon2id mean ≈ 1234 ms)
            BREAK_LO = 100
            BREAK_HI = 900
            HEIGHT_RATIO = 0.35
            w = 0.6

            fig = plt.figure(figsize=(14, 7))
            outer_gs = gridspec.GridSpec(1, 2, figure=fig, wspace=0.15)

            # ── LEFT: FaaS (normal axis) ──
            ax_faas = fig.add_subplot(outer_gs[0])
            labels = faas_df['plot_label'].tolist()
            hv = faas_df['mean_handler'].values
            nv = faas_df['mean_network'].values
            mt = faas_df['mean_total'].values
            p5 = faas_df['p50_total'].values
            x = np.arange(len(labels))

            ax_faas.bar(x, hv, w,
                        label='Handler-Ausf\u00fchrungszeit',
                        color='#3498db', alpha=0.85)
            ax_faas.bar(x, nv, w, bottom=hv,
                        label='Netzwerk-Overhead\n(Latenz \u2212 Handler)',
                        color='#e74c3c', alpha=0.85)
            for j, m in enumerate(mt):
                ax_faas.text(j, m + 3,
                             f'\u00d8 {m:.0f} ms', ha='center',
                             va='bottom', fontsize=8, fontweight='bold')
            for j, p in enumerate(p5):
                ax_faas.plot(j + w / 2 + 0.08, p, marker='D',
                             color='black', markersize=5, zorder=5)
                if j == 0:
                    ax_faas.plot([], [], marker='D', color='black',
                                 markersize=5, linestyle='None',
                                 label='P50 (Referenz)')
            ax_faas.set_xticks(x)
            ax_faas.set_xticklabels(labels, fontsize=9)
            ax_faas.set_ylabel('Latenz (ms)', fontsize=11)
            ax_faas.set_title('FaaS', fontweight='bold', fontsize=13)
            ax_faas.set_ylim(0, max(mt) * 1.18)
            ax_faas.grid(axis='y', alpha=0.3)
            ax_faas.legend(fontsize=9, loc='upper left')

            # ── RIGHT: Microservices (broken y-axis) ──
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

            # P50 diamonds on both axes
            for j, p in enumerate(p5):
                for ax in (ax_ms_top, ax_ms_bot):
                    ax.plot(j + w / 2 + 0.08, p, marker='D',
                            color='black', markersize=5, zorder=5)

            y_max_upper = max(mt) * 1.15
            ax_ms_top.set_ylim(BREAK_HI, y_max_upper)
            ax_ms_bot.set_ylim(0, BREAK_LO)

            ax_ms_top.spines['bottom'].set_visible(False)
            ax_ms_bot.spines['top'].set_visible(False)
            ax_ms_top.tick_params(bottom=False, labelbottom=False)
            draw_break_lines(ax_ms_top, ax_ms_bot)

            top_ticks = [t for t in range(900, int(y_max_upper) + 200, 200)
                         if t <= y_max_upper]
            ax_ms_top.set_yticks(top_ticks)

            ax_ms_bot.set_xticklabels(labels, fontsize=9)
            ax_ms_bot.set_ylabel('Latenz (ms)', fontsize=11)

            for j, m in enumerate(mt):
                if m > BREAK_LO:
                    ax_ms_top.text(
                        j, m + (y_max_upper - BREAK_HI) * 0.03,
                        f'\u00d8 {m:.0f} ms', ha='center', va='bottom',
                        fontsize=8, fontweight='bold')
                else:
                    ax_ms_bot.text(
                        j, m + BREAK_LO * 0.03,
                        f'\u00d8 {m:.0f} ms', ha='center', va='bottom',
                        fontsize=8, fontweight='bold')

            ax_ms_top.set_title('Microservices',
                                fontweight='bold', fontsize=13)

            fig.suptitle(
                'Latenzzerlegung in Handler- und Netzwerk-Anteil\n'
                '(Baseline-Phase, arithm. Mittelwert \u00d8;'
                ' \u25c6 = P50)',
                fontweight='bold', fontsize=13, y=1.0)
            fig.subplots_adjust(top=0.88)
            path = f"{PLOT_DIR}/network_overhead_decomposition.pdf"
            fig.savefig(path, dpi=300, bbox_inches='tight')
            print(f"Saved: {path}")
            plt.close()

    # ── Summary ──
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    print("""
  1. CDF PLOTS show that auth shifts the entire distribution rightward,
     not just the tail. The shift is most uniform for FaaS and most
     variable for containers.

  2. COLD STARTS: Auth increases cold start init duration by 15-30ms
     because the auth middleware (Cognito SDK or JWT library) must be
     loaded. Cold start RATE is unaffected by auth strategy.

  3. NETWORK OVERHEAD DECOMPOSITION (arithmetic means, E[X+Y]=E[X]+E[Y]):
     - Decomposition is binary: Handler + Network = Total
       (network_overhead_ms is derived as latency - handler_duration).
     - Edge: highest network fraction (30% FaaS, 52% MS) from L@E roundtrip.
     - Cognito/Manual: handler dominates (86-88% FaaS, 70-87% MS).
     - Manual (argon2id) on MS: Mean=1234ms vs P50=23ms (factor 54)
       due to event-loop blocking — shown via broken y-axis.
""")


if __name__ == '__main__':
    main()
