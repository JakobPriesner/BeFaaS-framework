#!/usr/bin/env python3
"""
14 — Extended analysis: original BeFaaS comparison, scaling rules,
     auth effect on container scaling & timeouts.
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats as sp_stats
from db_connection import get_connection, query_df, PLOT_DIR, EXCLUDE_SQL

# ── helpers ──────────────────────────────────────────────────────────
def save(fig, name):
    fig.savefig(f'{PLOT_DIR}/{name}', bbox_inches='tight', dpi=200)
    plt.close(fig)
    print(f'  -> saved {name}')


# =====================================================================
# PART 1 — Original BeFaaS (exp 37) vs Framework2 FaaS/None
# =====================================================================
def part1_original_befaas_comparison():
    print('\n=== Part 1: Original BeFaaS vs Framework2 comparison ===')
    conn = get_connection()

    # Exp 37 = original BeFaaS (unmodified), 256 MB, constant load
    # Exp 5  = framework2 faas/none/256 MB, SCNAST workload
    # Compare during exp 5's Baseline phase (similar constant load)

    # Normalise endpoint names: exp 37 uses /dev/frontend/... → strip /dev
    df37 = pd.read_sql_query("""
        SELECT REPLACE(endpoint, '/dev/', '/') AS endpoint, latency_ms,
               is_error, is_timeout
        FROM requests WHERE experiment_id = 37
    """, conn)
    df37['source'] = 'Original BeFaaS'

    df5 = pd.read_sql_query("""
        SELECT endpoint, latency_ms, is_error, is_timeout
        FROM requests WHERE experiment_id = 5 AND phase_name = 'Baseline'
    """, conn)
    df5['source'] = 'Framework2 Baseline'

    conn.close()

    # ── per-endpoint comparison table ──
    rows = []
    endpoints = sorted(set(df37['endpoint'].unique()) & set(df5['endpoint'].unique()))
    for ep in endpoints:
        a = df37.loc[df37['endpoint'] == ep, 'latency_ms']
        b = df5.loc[df5['endpoint'] == ep, 'latency_ms']
        u_stat, u_p = sp_stats.mannwhitneyu(a, b, alternative='two-sided')
        rows.append({
            'endpoint': ep,
            'orig_n': len(a), 'orig_p50': a.median(), 'orig_p95': a.quantile(.95), 'orig_p99': a.quantile(.99),
            'fw2_n': len(b), 'fw2_p50': b.median(), 'fw2_p95': b.quantile(.95), 'fw2_p99': b.quantile(.99),
            'p50_diff_pct': (b.median() - a.median()) / a.median() * 100 if a.median() > 0 else 0,
            'mannwhitney_p': u_p,
        })
    cmp = pd.DataFrame(rows)
    cmp.to_csv(f'{PLOT_DIR}/original_befaas_comparison.csv', index=False)
    print(cmp.to_string(index=False))

    # ── box plot side-by-side ──
    combined = pd.concat([df37, df5], ignore_index=True)
    fig, axes = plt.subplots(2, 4, figsize=(18, 8))
    for i, ep in enumerate(endpoints):
        ax = axes[i // 4][i % 4]
        data = []
        labels = []
        for src in ['Original BeFaaS', 'Framework2 Baseline']:
            subset = combined.loc[(combined['endpoint'] == ep) & (combined['source'] == src), 'latency_ms']
            data.append(subset.values)
            labels.append(src.replace('Framework2 ', 'FW2\n'))
        bp = ax.boxplot(data, tick_labels=labels, showfliers=False, patch_artist=True)
        bp['boxes'][0].set_facecolor('#2196F3')
        bp['boxes'][1].set_facecolor('#FF9800')
        short = ep.split('/')[-1] or 'homepage'
        ax.set_title(short, fontsize=9)
        ax.set_ylabel('Latency (ms)')
    fig.suptitle('Original BeFaaS vs Framework2 — Per-Endpoint Latency (Baseline Phase)', fontsize=12)
    fig.tight_layout()
    save(fig, 'original_vs_fw2_boxplot.pdf')

    # ── CDF overlay for overall latency ──
    fig, ax = plt.subplots(figsize=(8, 5))
    for src, df, color in [('Original BeFaaS', df37, '#2196F3'), ('Framework2 Baseline', df5, '#FF9800')]:
        vals = np.sort(df['latency_ms'].values)
        cdf = np.arange(1, len(vals)+1) / len(vals)
        ax.plot(vals, cdf, label=f'{src} (n={len(vals):,})', color=color, linewidth=1.5)
    ax.set_xlabel('Latency (ms)')
    ax.set_ylabel('CDF')
    ax.set_title('Latency CDF — Original BeFaaS vs Framework2 (Baseline)')
    ax.set_xlim(0, 1200)
    ax.legend()
    ax.grid(True, alpha=.3)
    save(fig, 'original_vs_fw2_cdf.pdf')

    # ── summary statistics ──
    print(f'\n  Original BeFaaS: n={len(df37):,}, p50={df37["latency_ms"].median():.0f}ms, '
          f'p95={df37["latency_ms"].quantile(.95):.0f}ms, p99={df37["latency_ms"].quantile(.99):.0f}ms')
    print(f'  Framework2 BL:   n={len(df5):,}, p50={df5["latency_ms"].median():.0f}ms, '
          f'p95={df5["latency_ms"].quantile(.95):.0f}ms, p99={df5["latency_ms"].quantile(.99):.0f}ms')
    p50_diff = abs(df5['latency_ms'].median() - df37['latency_ms'].median())
    print(f'  P50 difference: {p50_diff:.0f}ms ({p50_diff/df37["latency_ms"].median()*100:.1f}%)')


# =====================================================================
# PART 2 — Auth effect on container scaling (task count)
# =====================================================================
def part2_auth_scaling_effect():
    print('\n=== Part 2: Auth effect on ECS container scaling ===')
    conn = get_connection()

    # Get max running tasks per experiment, grouped by arch/auth/hw
    df = pd.read_sql_query(f"""
        SELECT me.experiment_id, e.architecture, e.auth_strategy, e.ram_in_mb,
               me.service_name,
               MAX(me.running_tasks) as max_tasks,
               AVG(me.running_tasks) as avg_tasks,
               MAX(me.cpu_percent) as max_cpu,
               AVG(me.cpu_percent) as avg_cpu
        FROM metrics_ecs me
        JOIN experiments e ON e.id = me.experiment_id
        WHERE {EXCLUDE_SQL}
        GROUP BY me.experiment_id, e.architecture, e.auth_strategy, e.ram_in_mb, me.service_name
    """, conn)
    conn.close()

    # Focus on frontend-service (MS) and monolith — the bottleneck services
    frontend = df[df['service_name'].isin(['frontend-service', 'monolith'])].copy()

    # Group by arch + hw, compare auth strategies
    summary_rows = []
    for (arch, ram), grp in frontend.groupby(['architecture', 'ram_in_mb']):
        for auth in grp['auth_strategy'].unique():
            sub = grp[grp['auth_strategy'] == auth]
            summary_rows.append({
                'architecture': arch, 'ram_mb': ram, 'auth_strategy': auth,
                'n_experiments': sub['experiment_id'].nunique(),
                'avg_max_tasks': sub['max_tasks'].mean(),
                'avg_avg_tasks': sub['avg_tasks'].mean(),
                'avg_max_cpu': sub['max_cpu'].mean(),
                'avg_avg_cpu': sub['avg_cpu'].mean(),
            })

    summary = pd.DataFrame(summary_rows).sort_values(['architecture', 'ram_mb', 'auth_strategy'])
    summary.to_csv(f'{PLOT_DIR}/auth_scaling_effect.csv', index=False)
    print(summary.to_string(index=False))

    # ── grouped bar chart: max tasks by auth strategy ──
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for i, arch in enumerate(['microservices', 'monolith']):
        ax = axes[i]
        sub = summary[summary['architecture'] == arch].copy()
        hw_tiers = sorted(sub['ram_mb'].unique())
        auths = sorted(sub['auth_strategy'].unique())
        colors = {'none': '#4CAF50', 'service-integrated': '#2196F3',
                  'service-integrated-manual': '#FF9800', 'edge': '#9C27B0'}
        x = np.arange(len(hw_tiers))
        width = 0.18
        for j, auth in enumerate(auths):
            vals = []
            for hw in hw_tiers:
                match = sub[(sub['ram_mb'] == hw) & (sub['auth_strategy'] == auth)]
                vals.append(match['avg_max_tasks'].values[0] if len(match) > 0 else 0)
            ax.bar(x + j * width, vals, width, label=auth, color=colors.get(auth, '#999'))
        ax.set_xticks(x + width * (len(auths)-1) / 2)
        ax.set_xticklabels([f'{hw}MB' for hw in hw_tiers], fontsize=8)
        ax.set_ylabel('Max Running Tasks')
        ax.set_title(f'{arch.capitalize()} — Peak Task Count by Auth')
        ax.legend(fontsize=7)
        ax.grid(True, alpha=.3, axis='y')
    fig.suptitle('Auth Effect on Container Scaling — Peak Task Count', fontsize=13)
    fig.tight_layout()
    save(fig, 'auth_scaling_task_count.pdf')

    # ── CPU comparison: auth vs none at same hardware ──
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for i, arch in enumerate(['microservices', 'monolith']):
        ax = axes[i]
        sub = summary[summary['architecture'] == arch].copy()
        hw_tiers = sorted(sub['ram_mb'].unique())
        auths = sorted(sub['auth_strategy'].unique())
        x = np.arange(len(hw_tiers))
        width = 0.18
        for j, auth in enumerate(auths):
            vals = []
            for hw in hw_tiers:
                match = sub[(sub['ram_mb'] == hw) & (sub['auth_strategy'] == auth)]
                vals.append(match['avg_max_cpu'].values[0] if len(match) > 0 else 0)
            ax.bar(x + j * width, vals, width, label=auth, color=colors.get(auth, '#999'))
        ax.set_xticks(x + width * (len(auths)-1) / 2)
        ax.set_xticklabels([f'{hw}MB' for hw in hw_tiers], fontsize=8)
        ax.set_ylabel('Peak CPU (%)')
        ax.set_title(f'{arch.capitalize()} — Peak CPU by Auth')
        ax.legend(fontsize=7)
        ax.grid(True, alpha=.3, axis='y')
    fig.suptitle('Auth Effect on CPU Utilization — Peak Values', fontsize=13)
    fig.tight_layout()
    save(fig, 'auth_scaling_cpu.pdf')


# =====================================================================
# PART 3 — Scaling rules comparison (old vs new, latency vs CPU)
# =====================================================================
def part3_scaling_rules():
    print('\n=== Part 3: Scaling rules effect on latency ===')
    conn = get_connection()

    # Identify experiments with different scaling configs at same arch/auth/hw
    df = pd.read_sql_query(f"""
        WITH exp_rules AS (
            SELECT sr.experiment_id,
                   MAX(sr.max_capacity) AS max_cap,
                   MAX(sr.scale_out_cooldown_sec) AS out_cd,
                   string_agg(DISTINCT sr.rule_type, ',' ORDER BY sr.rule_type) AS rules
            FROM scaling_rules sr
            GROUP BY sr.experiment_id
        )
        SELECT e.id, e.architecture, e.auth_strategy, e.ram_in_mb,
               er.rules, er.max_cap, er.out_cd
        FROM experiments e
        JOIN exp_rules er ON er.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
        AND e.architecture IN ('microservices', 'monolith')
        ORDER BY e.architecture, e.auth_strategy, e.ram_in_mb
    """, conn)

    # Classify: old config (max>=100, out_cd>=45) vs new config (max<=30, out_cd<=30)
    df['config'] = df.apply(lambda r: 'old (max={}, cd={}s)'.format(r['max_cap'], r['out_cd'])
                            if r['max_cap'] >= 100 else
                            ('latency-based' if 'latency' in str(r['rules']) else
                             'new (max={}, cd={}s)'.format(r['max_cap'], r['out_cd'])), axis=1)

    # Get latency stats for these experiments
    latency = pd.read_sql_query(f"""
        SELECT r.experiment_id,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.latency_ms) AS p50,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY r.latency_ms) AS p95,
               PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY r.latency_ms) AS p99,
               AVG(r.latency_ms) AS avg_lat,
               COUNT(*) AS n_reqs,
               SUM(CASE WHEN r.is_error THEN 1 ELSE 0 END) AS errors,
               SUM(CASE WHEN r.is_timeout THEN 1 ELSE 0 END) AS timeouts
        FROM requests r
        JOIN experiments e ON e.id = r.experiment_id
        WHERE {EXCLUDE_SQL}
        AND e.architecture IN ('microservices', 'monolith')
        GROUP BY r.experiment_id
    """, conn)
    conn.close()

    merged = df.merge(latency, left_on='id', right_on='experiment_id', how='inner')
    for col in ['p50', 'p95', 'p99', 'avg_lat']:
        merged[col] = merged[col].astype(float)

    # Find pairs with same arch/auth/hw but different scaling config
    pairs = []
    for (arch, auth, ram), grp in merged.groupby(['architecture', 'auth_strategy', 'ram_in_mb']):
        configs = grp['config'].unique()
        if len(configs) >= 2:
            for cfg in configs:
                sub = grp[grp['config'] == cfg]
                pairs.append({
                    'architecture': arch, 'auth': auth, 'ram_mb': ram,
                    'config': cfg,
                    'n_experiments': len(sub),
                    'avg_p50': sub['p50'].mean(),
                    'avg_p95': sub['p95'].mean(),
                    'avg_p99': sub['p99'].mean(),
                    'avg_errors': sub['errors'].mean(),
                    'avg_timeouts': sub['timeouts'].mean(),
                })

    if pairs:
        pair_df = pd.DataFrame(pairs).sort_values(['architecture', 'auth', 'ram_mb', 'config'])
        pair_df.to_csv(f'{PLOT_DIR}/scaling_rules_comparison.csv', index=False)
        print(pair_df.to_string(index=False))
    else:
        print('  No scaling rule pairs found with same arch/auth/hw.')

    # ── Special comparison: latency-based (exp 82,90) vs request_count-based ──
    lat_based = merged[merged['config'] == 'latency-based']
    if not lat_based.empty:
        print('\n  Latency-based scaling experiments:')
        for _, r in lat_based.iterrows():
            # Find matching request_count experiment
            match = merged[(merged['architecture'] == r['architecture']) &
                           (merged['auth_strategy'] == r['auth_strategy']) &
                           (merged['ram_in_mb'] == r['ram_in_mb']) &
                           (merged['config'] != 'latency-based')]
            match_str = ', '.join(str(int(m)) for m in match['id'].values) if not match.empty else 'none'
            print(f'    exp {int(r["id"])}: {r["architecture"]}/{r["auth_strategy"]} '
                  f'{r["ram_in_mb"]}MB p50={r["p50"]:.0f} p95={r["p95"]:.0f} p99={r["p99"]:.0f} '
                  f'err={int(r["errors"])} | matches: {match_str}')
            if not match.empty:
                for _, m in match.iterrows():
                    print(f'      vs exp {int(m["id"])}: p50={m["p50"]:.0f} p95={m["p95"]:.0f} '
                          f'p99={m["p99"]:.0f} err={int(m["errors"])} config={m["config"]}')

    # ── old vs new config summary ──
    print('\n  Old vs New scaling config summary:')
    for cfg_type in merged['config'].unique():
        sub = merged[merged['config'] == cfg_type]
        print(f'    {cfg_type}: n={len(sub)} experiments, '
              f'avg_p50={sub["p50"].mean():.0f}ms, avg_p95={sub["p95"].mean():.0f}ms')


# =====================================================================
# PART 4 — Auth effect on timeouts
# =====================================================================
def part4_auth_timeouts():
    print('\n=== Part 4: Auth effect on timeouts ===')
    conn = get_connection()

    df = pd.read_sql_query(f"""
        SELECT e.architecture, e.auth_strategy, e.ram_in_mb,
               r.phase_name,
               COUNT(*) AS total,
               SUM(CASE WHEN r.is_timeout THEN 1 ELSE 0 END) AS timeouts,
               SUM(CASE WHEN r.is_error THEN 1 ELSE 0 END) AS errors
        FROM requests r
        JOIN experiments e ON e.id = r.experiment_id
        WHERE {EXCLUDE_SQL}
        AND r.phase_name IS NOT NULL
        GROUP BY e.architecture, e.auth_strategy, e.ram_in_mb, r.phase_name
    """, conn)
    conn.close()

    df['timeout_pct'] = df['timeouts'] / df['total'] * 100
    df['error_pct'] = df['errors'] / df['total'] * 100

    # Summary: timeout % by arch × auth × phase
    phase_order = ['Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
                   'Flash Crowd', 'Step Down', 'Cool-down']
    pivot = df.groupby(['architecture', 'auth_strategy', 'phase_name']).agg(
        total=('total', 'sum'), timeouts=('timeouts', 'sum'), errors=('errors', 'sum')
    ).reset_index()
    pivot['timeout_pct'] = pivot['timeouts'] / pivot['total'] * 100
    pivot['error_pct'] = pivot['errors'] / pivot['total'] * 100

    # ── heatmap: timeout % by auth × phase for each architecture ──
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    for i, arch in enumerate(['faas', 'microservices', 'monolith']):
        ax = axes[i]
        sub = pivot[pivot['architecture'] == arch].copy()
        auths = sorted(sub['auth_strategy'].unique())
        phases_present = [p for p in phase_order if p in sub['phase_name'].values]
        matrix = np.zeros((len(auths), len(phases_present)))
        for ai, auth in enumerate(auths):
            for pi, phase in enumerate(phases_present):
                match = sub[(sub['auth_strategy'] == auth) & (sub['phase_name'] == phase)]
                if not match.empty:
                    matrix[ai, pi] = match['timeout_pct'].values[0]
        im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto', vmin=0)
        ax.set_xticks(range(len(phases_present)))
        ax.set_xticklabels([p[:8] for p in phases_present], rotation=45, ha='right', fontsize=7)
        ax.set_yticks(range(len(auths)))
        ax.set_yticklabels(auths, fontsize=8)
        for ai in range(len(auths)):
            for pi in range(len(phases_present)):
                ax.text(pi, ai, f'{matrix[ai, pi]:.1f}%', ha='center', va='center', fontsize=7,
                        color='white' if matrix[ai, pi] > 5 else 'black')
        ax.set_title(f'{arch} — Timeout %')
        fig.colorbar(im, ax=ax, shrink=.8)
    fig.suptitle('Timeout Rate by Auth Strategy and Phase', fontsize=13)
    fig.tight_layout()
    save(fig, 'auth_timeout_heatmap.pdf')

    # Print key findings
    high_timeout = pivot[pivot['timeout_pct'] > 1].sort_values('timeout_pct', ascending=False)
    if not high_timeout.empty:
        print('\n  High timeout combinations (>1%):')
        for _, r in high_timeout.head(15).iterrows():
            print(f'    {r["architecture"]}/{r["auth_strategy"]} phase={r["phase_name"]}: '
                  f'{r["timeout_pct"]:.1f}% ({int(r["timeouts"])}/{int(r["total"])})')


# =====================================================================
# PART 5 — Auth overhead linearity: single-function vs multi-function
# =====================================================================
def part5_auth_linearity_deep():
    print('\n=== Part 5: Auth overhead linearity — function call depth ===')
    conn = get_connection()

    # For FaaS: compare endpoints with different internal call depths
    # /frontend/setUser      → 1 function (login only)
    # /frontend/addCartItem  → ~2 functions (frontend → addcartitem)
    # /frontend/checkout     → ~3-4 functions (frontend → checkout → payment, getcart)
    # /frontend              → ~2-3 functions (frontend → getproducts)

    endpoints_depth = {
        '/frontend/setUser': 1,
        '/frontend/addCartItem': 2,
        '/frontend/cart': 2,
        '/frontend': 3,        # frontend calls getproducts + product
        '/frontend/checkout': 4,  # frontend → checkout → payment, getcart, emptycart
    }

    df = pd.read_sql_query(f"""
        SELECT e.id, e.auth_strategy, r.endpoint,
               AVG(r.latency_ms) AS avg_lat,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.latency_ms) AS p50,
               COUNT(*) AS n
        FROM requests r
        JOIN experiments e ON e.id = r.experiment_id
        WHERE {EXCLUDE_SQL}
        AND e.architecture = 'faas' AND e.ram_in_mb = 256
        AND r.phase_name = 'Baseline'
        AND r.endpoint IN ('/frontend/setUser', '/frontend/addCartItem', '/frontend/cart',
                            '/frontend', '/frontend/checkout')
        GROUP BY e.id, e.auth_strategy, r.endpoint
    """, conn)
    conn.close()

    if df.empty:
        print('  No data found.')
        return

    df['p50'] = df['p50'].astype(float)
    df['avg_lat'] = df['avg_lat'].astype(float)
    df['depth'] = df['endpoint'].map(endpoints_depth)

    # Compute DeltaAuth per endpoint
    rows = []
    for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
        auth_data = df[df['auth_strategy'] == auth]
        none_data = df[df['auth_strategy'] == 'none']
        for ep in endpoints_depth:
            a_ep = auth_data[auth_data['endpoint'] == ep]
            n_ep = none_data[none_data['endpoint'] == ep]
            if not a_ep.empty and not n_ep.empty:
                delta = a_ep['p50'].mean() - n_ep['p50'].mean()
                rows.append({
                    'auth': auth, 'endpoint': ep.split('/')[-1] or 'homepage',
                    'depth': endpoints_depth[ep],
                    'delta_p50': delta,
                    'auth_p50': a_ep['p50'].mean(),
                    'none_p50': n_ep['p50'].mean(),
                })

    if not rows:
        print('  Not enough data for linearity analysis.')
        return

    result = pd.DataFrame(rows)
    result.to_csv(f'{PLOT_DIR}/auth_linearity_depth.csv', index=False)
    print(result.to_string(index=False))

    # Plot: DeltaAuth vs function call depth
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = {'service-integrated': '#2196F3', 'service-integrated-manual': '#FF9800', 'edge': '#9C27B0'}
    for auth in result['auth'].unique():
        sub = result[result['auth'] == auth].sort_values('depth')
        ax.plot(sub['depth'], sub['delta_p50'], 'o-', label=auth, color=colors.get(auth, '#999'), markersize=8)
        for _, r in sub.iterrows():
            ax.annotate(r['endpoint'], (r['depth'], r['delta_p50']),
                        textcoords='offset points', xytext=(5, 5), fontsize=7)
    ax.set_xlabel('Function Call Depth')
    ax.set_ylabel('DeltaAuth P50 (ms)')
    ax.set_title('Auth Overhead vs Function Call Depth (FaaS 256MB, Baseline)')
    ax.legend()
    ax.grid(True, alpha=.3)
    save(fig, 'auth_linearity_depth.pdf')

    # Check linearity: if auth overhead is linear with depth, slope ~ constant per depth
    for auth in result['auth'].unique():
        sub = result[result['auth'] == auth].sort_values('depth')
        if len(sub) >= 3:
            slope, intercept, r_val, p_val, std_err = sp_stats.linregress(sub['depth'], sub['delta_p50'])
            print(f'  {auth}: slope={slope:.1f}ms/depth, R²={r_val**2:.3f}, p={p_val:.4f}')


# =====================================================================
# PART 6 — Cross-architecture DeltaAuth at comparable hardware
# =====================================================================
def part6_cross_arch_delta():
    print('\n=== Part 6: Cross-architecture DeltaAuth comparison ===')
    conn = get_connection()

    df = pd.read_sql_query(f"""
        SELECT e.architecture, e.auth_strategy, e.ram_in_mb,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.latency_ms) AS p50,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY r.latency_ms) AS p95,
               COUNT(*) AS n
        FROM requests r
        JOIN experiments e ON e.id = r.experiment_id
        WHERE {EXCLUDE_SQL}
        AND r.phase_name = 'Baseline'
        GROUP BY e.architecture, e.auth_strategy, e.ram_in_mb
    """, conn)
    conn.close()

    df['p50'] = df['p50'].astype(float)
    df['p95'] = df['p95'].astype(float)

    # Compute DeltaAuth per arch/hw
    rows = []
    for (arch, ram), grp in df.groupby(['architecture', 'ram_in_mb']):
        none_row = grp[grp['auth_strategy'] == 'none']
        if none_row.empty:
            continue
        none_p50 = none_row['p50'].values[0]
        none_p95 = none_row['p95'].values[0]
        for _, row in grp.iterrows():
            if row['auth_strategy'] != 'none':
                rows.append({
                    'architecture': arch, 'ram_mb': ram, 'auth': row['auth_strategy'],
                    'none_p50': none_p50, 'auth_p50': row['p50'],
                    'delta_p50': row['p50'] - none_p50,
                    'delta_p95': row['p95'] - none_p95,
                    'overhead_pct': (row['p50'] - none_p50) / none_p50 * 100 if none_p50 > 0 else 0,
                })

    result = pd.DataFrame(rows)
    result.to_csv(f'{PLOT_DIR}/cross_arch_delta_auth.csv', index=False)
    print(result.to_string(index=False))

    # ── plot: DeltaAuth P50 across architectures at same auth ──
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    for i, auth in enumerate(['service-integrated', 'service-integrated-manual', 'edge']):
        ax = axes[i]
        sub = result[result['auth'] == auth]
        arch_colors = {'faas': '#4CAF50', 'microservices': '#2196F3', 'monolith': '#FF9800'}
        for arch in ['faas', 'microservices', 'monolith']:
            asub = sub[sub['architecture'] == arch].sort_values('ram_mb')
            if not asub.empty:
                ax.plot(asub['ram_mb'], asub['delta_p50'], 'o-', label=arch,
                        color=arch_colors[arch], markersize=7)
        ax.set_xlabel('RAM (MB)')
        ax.set_ylabel('DeltaAuth P50 (ms)')
        ax.set_title(auth.replace('service-', 's-'), fontsize=10)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=.3)
        ax.set_xscale('log')
    fig.suptitle('DeltaAuth by Architecture and Hardware Tier (Baseline Phase)', fontsize=12)
    fig.tight_layout()
    save(fig, 'cross_arch_delta_by_hw.pdf')


# =====================================================================
# PART 7 — Benchmark consistency: repeated runs
# =====================================================================
def part7_benchmark_consistency():
    print('\n=== Part 7: Benchmark consistency (repeated runs) ===')
    conn = get_connection()

    # Find groups of repeated experiments (same arch/auth/hw)
    df = pd.read_sql_query(f"""
        SELECT e.id, e.architecture, e.auth_strategy, e.ram_in_mb,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               COUNT(r.id) AS n_reqs,
               AVG(r.latency_ms) AS avg_lat,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.latency_ms) AS p50,
               PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY r.latency_ms) AS p95,
               PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY r.latency_ms) AS p99,
               SUM(CASE WHEN r.is_error THEN 1 ELSE 0 END) AS errors
        FROM requests r
        JOIN experiments e ON e.id = r.experiment_id
        WHERE {EXCLUDE_SQL}
        AND r.phase_name = 'Baseline'
        GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.password_hash_algorithm
        HAVING COUNT(r.id) > 100
    """, conn)
    conn.close()

    for col in ['avg_lat', 'p50', 'p95', 'p99']:
        df[col] = df[col].astype(float)

    # Group by config
    rows = []
    for (arch, auth, ram, algo), grp in df.groupby(['architecture', 'auth_strategy', 'ram_in_mb', 'algo']):
        if len(grp) < 2:
            continue
        cv_p50 = grp['p50'].std() / grp['p50'].mean() * 100 if grp['p50'].mean() > 0 else 0
        cv_p95 = grp['p95'].std() / grp['p95'].mean() * 100 if grp['p95'].mean() > 0 else 0
        cv_p99 = grp['p99'].std() / grp['p99'].mean() * 100 if grp['p99'].mean() > 0 else 0
        rows.append({
            'architecture': arch, 'auth': auth, 'ram_mb': ram, 'algo': algo,
            'n_runs': len(grp),
            'experiments': ','.join(str(int(x)) for x in grp['id'].values),
            'mean_p50': grp['p50'].mean(), 'std_p50': grp['p50'].std(), 'cv_p50': cv_p50,
            'mean_p95': grp['p95'].mean(), 'std_p95': grp['p95'].std(), 'cv_p95': cv_p95,
            'mean_p99': grp['p99'].mean(), 'std_p99': grp['p99'].std(), 'cv_p99': cv_p99,
        })

    if not rows:
        print('  No repeated-run groups found with >=2 experiments.')
        return

    result = pd.DataFrame(rows).sort_values('cv_p50')
    result.to_csv(f'{PLOT_DIR}/benchmark_consistency.csv', index=False)

    print(f'  Found {len(result)} config groups with repeated runs:')
    for _, r in result.iterrows():
        print(f'    {r["architecture"]}/{r["auth"]}/{r["ram_mb"]}MB ({r["algo"]}): '
              f'{int(r["n_runs"])} runs, CV_p50={r["cv_p50"]:.1f}%, CV_p95={r["cv_p95"]:.1f}%, '
              f'CV_p99={r["cv_p99"]:.1f}% | exps: {r["experiments"]}')

    # ── box plot of CV values by architecture ──
    fig, ax = plt.subplots(figsize=(8, 5))
    arch_data = {}
    for _, r in result.iterrows():
        arch_data.setdefault(r['architecture'], []).append(r['cv_p50'])
    positions = []
    data = []
    labels = []
    for i, (arch, vals) in enumerate(sorted(arch_data.items())):
        positions.append(i)
        data.append(vals)
        labels.append(arch)
    bp = ax.boxplot(data, positions=positions, tick_labels=labels, showfliers=True, patch_artist=True)
    colors = ['#4CAF50', '#2196F3', '#FF9800']
    for j, box in enumerate(bp['boxes']):
        box.set_facecolor(colors[j % len(colors)])
    ax.set_ylabel('CV of P50 (%)')
    ax.set_title('Benchmark Repeatability — CV of P50 (Baseline Phase)')
    ax.grid(True, alpha=.3, axis='y')
    ax.axhline(y=10, color='red', linestyle='--', alpha=.5, label='10% threshold')
    ax.legend()
    save(fig, 'benchmark_consistency_cv.pdf')


# =====================================================================
# PART 8 — Comprehensive DeltaAuth table with confidence intervals
# =====================================================================
def part8_delta_auth_with_ci():
    print('\n=== Part 8: DeltaAuth table with 95% CI ===')
    conn = get_connection()

    # Per-experiment baseline P50 for CI computation
    df = pd.read_sql_query(f"""
        SELECT e.id, e.architecture, e.auth_strategy, e.ram_in_mb,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.latency_ms) AS p50
        FROM requests r
        JOIN experiments e ON e.id = r.experiment_id
        WHERE {EXCLUDE_SQL}
        AND r.phase_name = 'Baseline'
        GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.password_hash_algorithm
        HAVING COUNT(r.id) > 100
    """, conn)
    conn.close()

    df['p50'] = df['p50'].astype(float)

    # Build DeltaAuth with CI where multiple runs exist
    rows = []
    for (arch, ram, algo), grp in df.groupby(['architecture', 'ram_in_mb', 'algo']):
        none_runs = grp[grp['auth_strategy'] == 'none']['p50'].values
        if len(none_runs) == 0:
            continue
        none_mean = none_runs.mean()
        for auth in grp['auth_strategy'].unique():
            if auth == 'none':
                continue
            auth_runs = grp[grp['auth_strategy'] == auth]['p50'].values
            delta_mean = auth_runs.mean() - none_mean
            # CI: if multiple runs, use t-distribution
            n_auth = len(auth_runs)
            n_none = len(none_runs)
            if n_auth >= 2 and n_none >= 2:
                # Welch's t-test-style CI for difference of means
                se = np.sqrt(auth_runs.var()/n_auth + none_runs.var()/n_none)
                df_welch = (auth_runs.var()/n_auth + none_runs.var()/n_none)**2 / (
                    (auth_runs.var()/n_auth)**2/(n_auth-1) + (none_runs.var()/n_none)**2/(n_none-1))
                if df_welch > 0 and se > 0:
                    t_crit = sp_stats.t.ppf(0.975, df_welch)
                    ci_low = delta_mean - t_crit * se
                    ci_high = delta_mean + t_crit * se
                else:
                    ci_low = ci_high = delta_mean
            else:
                ci_low = ci_high = delta_mean  # single run, no CI

            rows.append({
                'architecture': arch, 'ram_mb': ram, 'algo': algo, 'auth': auth,
                'n_none': n_none, 'n_auth': n_auth,
                'none_p50': none_mean, 'auth_p50': auth_runs.mean(),
                'delta_p50': delta_mean,
                'ci_low': ci_low, 'ci_high': ci_high,
                'overhead_pct': delta_mean / none_mean * 100 if none_mean > 0 else 0,
            })

    result = pd.DataFrame(rows).sort_values(['architecture', 'ram_mb', 'auth'])
    result.to_csv(f'{PLOT_DIR}/delta_auth_with_ci.csv', index=False)
    print(result.to_string(index=False, float_format='{:.1f}'.format))


def main():
    part1_original_befaas_comparison()
    part2_auth_scaling_effect()
    part3_scaling_rules()
    part4_auth_timeouts()
    part5_auth_linearity_deep()
    part6_cross_arch_delta()
    part7_benchmark_consistency()
    part8_delta_auth_with_ci()
    print('\n=== Script 14 complete ===')


if __name__ == '__main__':
    main()