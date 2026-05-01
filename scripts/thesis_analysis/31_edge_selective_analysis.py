#!/usr/bin/env python3
"""
31 -- Edge-Selective Auth Analysis
Analyzes experiments using auth_strategy='edge-selective' where only
relevant endpoints get Edge authentication (not all endpoints).
Compares edge-selective vs full-edge vs none for same hardware configs.
Isolates CloudFront overhead for FaaS.

Edge-selective experiment IDs: 145-162
  EXCLUDED: 150 (incomplete, only 14 min), 154 (duplicate of 149)
  These experiments do NOT have handler_events, only requests.

Hardware mappings:
  FaaS: 256MB (147,159), 512MB (146,160), 1024MB (145,161)
  MS: S=512/0.25 (149), L=2048/1.0 (148)
  Mono: S=512/0.25 (157), M=1024/0.5 (156), L=2048/1.0 (155)

  CloudFront baselines: 158 (faas none+CF 256MB), 162 (faas none+CF 1024MB)
  With CF: 159, 160, 161 (FaaS edge-selective + CF)
  Without CF: 145, 146, 147 (FaaS edge-selective, no CF)

Outputs: edge_selective_analysis.csv, edge_selective_comparison.pdf,
         edge_selective_cf_overhead.pdf
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, EXCLUDED_EXPERIMENTS, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge',
    'edge-selective': 'Edge-Sel.',
}


MIN_REQUESTS = 50_000
MIN_PHASES = 7


def _filter_with_warning(df, label):
    """Apply the (requests, phases) completeness thresholds and warn about drops."""
    dropped = df[(df['n_requests'] <= MIN_REQUESTS) | (df['n_phases'] < MIN_PHASES)]
    for _, row in dropped.iterrows():
        print(f"  WARN: dropping {label} experiment {int(row['id'])} — "
              f"{int(row['n_requests']):,} requests, {int(row['n_phases'])} phases "
              f"(need >{MIN_REQUESTS:,} and ≥{MIN_PHASES})")
    return df[(df['n_requests'] > MIN_REQUESTS) & (df['n_phases'] >= MIN_PHASES)]


def _discover_edge_selective_ids():
    """Discover edge-selective and related CF-baseline experiment IDs from the DB."""
    excl = ','.join(str(x) for x in EXCLUDED_EXPERIMENTS)
    df = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu,
               COUNT(r.id) AS n_requests,
               COUNT(DISTINCT r.phase_name) AS n_phases
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE e.auth_strategy = 'edge-selective'
          AND e.id NOT IN ({excl})
        GROUP BY e.id, e.architecture, e.auth_strategy, e.with_cloudfront,
                 e.ram_in_mb, e.cpu_in_vcpu
        ORDER BY e.id
    """)
    df = _filter_with_warning(df, 'edge-selective')
    all_ids = df['id'].tolist()

    # FaaS edge-selective WITH CloudFront
    cf_faas = df[(df['architecture'] == 'faas') & (df['with_cf'] == True)]['id'].tolist()
    # FaaS edge-selective WITHOUT CloudFront
    no_cf_faas = df[(df['architecture'] == 'faas') & (df['with_cf'] == False)]['id'].tolist()

    # CloudFront baselines: faas/none with CF (discovered dynamically)
    cf_df = query_df(f"""
        SELECT e.id,
               COUNT(r.id) AS n_requests,
               COUNT(DISTINCT r.phase_name) AS n_phases
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE e.auth_strategy = 'none'
          AND e.architecture = 'faas'
          AND COALESCE(e.with_cloudfront, false) = true
          AND e.id NOT IN ({excl})
        GROUP BY e.id
        ORDER BY e.id
    """)
    cf_baselines = _filter_with_warning(cf_df, 'CF-baseline (faas/none+CF)')['id'].tolist()

    return all_ids, cf_faas, no_cf_faas, cf_baselines


# Lazy-loaded: populated in main()
EDGE_SELECTIVE_IDS = []
CF_FAAS_ES = []
NO_CF_FAAS_ES = []
CF_BASELINES = []


def main():
    global EDGE_SELECTIVE_IDS, CF_FAAS_ES, NO_CF_FAAS_ES, CF_BASELINES
    print("=" * 70)
    print("31 -- EDGE-SELECTIVE AUTH ANALYSIS")
    print("=" * 70)

    # Discover experiment IDs from DB instead of hardcoding
    EDGE_SELECTIVE_IDS, CF_FAAS_ES, NO_CF_FAAS_ES, CF_BASELINES = _discover_edge_selective_ids()
    print(f"  Discovered {len(EDGE_SELECTIVE_IDS)} edge-selective experiments: {EDGE_SELECTIVE_IDS}")
    print(f"  CF FaaS ES: {CF_FAAS_ES}, No-CF FaaS ES: {NO_CF_FAAS_ES}, CF baselines: {CF_BASELINES}")

    if not EDGE_SELECTIVE_IDS:
        print("  No edge-selective experiments found in DB!")
        return

    # ── 1. Overview of all edge-selective experiments ──
    print("\n--- PART 1: Edge-Selective Experiment Overview ---")

    es_ids_sql = ','.join(str(x) for x in EDGE_SELECTIVE_IDS)
    overview = query_df(f"""
        SELECT
            e.id,
            e.architecture,
            e.auth_strategy,
            e.ram_in_mb,
            e.cpu_in_vcpu,
            COUNT(*) AS total_requests,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            COUNT(*) FILTER (WHERE r.is_error) AS n_error,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p50,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE e.id IN ({es_ids_sql})
        GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu
        ORDER BY e.id
    """)

    if overview.empty:
        print("  No edge-selective experiments found!")
        return

    for col in ['p50', 'p99']:
        overview[col] = overview[col].astype(float)

    print(f"\n  {'ID':>4s} | {'Arch':>14s} | {'Auth':>16s} | {'RAM':>6s} | {'CPU':>5s} | "
          f"{'N_total':>8s} | {'N_ok':>8s} | {'Err%':>5s} | {'P50':>7s} | {'P99':>8s}")
    print(f"  {'-'*4} | {'-'*14} | {'-'*16} | {'-'*6} | {'-'*5} | "
          f"{'-'*8} | {'-'*8} | {'-'*5} | {'-'*7} | {'-'*8}")
    for _, r in overview.iterrows():
        err_pct = r['n_error'] / r['total_requests'] * 100 if r['total_requests'] > 0 else 0
        cpu_str = f"{r['cpu_in_vcpu']:.2f}" if pd.notna(r['cpu_in_vcpu']) else 'N/A'
        print(f"  {r['id']:>4.0f} | {r['architecture']:>14s} | {r['auth_strategy']:>16s} | "
              f"{r['ram_in_mb']:>5.0f}M | {cpu_str:>5s} | {r['total_requests']:>8,.0f} | "
              f"{r['n_success']:>8,.0f} | {err_pct:>4.1f}% | {r['p50']:>6.1f}ms | {r['p99']:>7.1f}ms")

    # ── 2. Compare edge-selective vs full-edge vs none ──
    print("\n--- PART 2: Edge-Selective vs Full-Edge vs None ---")

    # Build a mapping: (architecture, ram, cpu) -> list of auth strategies
    # We need to query full-edge and none experiments for matching hardware

    # Determine unique hardware configs from edge-selective experiments
    hw_configs = overview[['architecture', 'ram_in_mb', 'cpu_in_vcpu']].drop_duplicates()

    comparison_rows = []

    for _, hw in hw_configs.iterrows():
        arch = hw['architecture']
        ram = int(hw['ram_in_mb'])
        cpu = hw['cpu_in_vcpu']
        cpu_clause = "AND e.cpu_in_vcpu IS NULL" if pd.isna(cpu) or cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

        def hw_label(a, r, c):
            if a == 'faas':
                return f"{r}MB"
            mapping = {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}
            return mapping.get(float(c) if pd.notna(c) else 0, f"{c}vCPU")

        hlabel = hw_label(arch, ram, cpu)

        # Query edge-selective for this config
        es_df = query_df(f"""
            SELECT
                'edge-selective' AS auth_strategy,
                COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p50,
                percentile_cont(0.75) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p75,
                percentile_cont(0.90) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p90,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p95,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p99
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE e.id IN ({es_ids_sql})
              AND e.architecture = '{arch}'
              AND e.ram_in_mb = {ram}
              {cpu_clause}
              AND e.auth_strategy = 'edge-selective'
              AND r.phase_name = 'Baseline'
            GROUP BY 1
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)

        # Query full-edge and none for same hardware
        ref_df = query_df(f"""
            SELECT
                e.auth_strategy,
                COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p50,
                percentile_cont(0.75) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p75,
                percentile_cont(0.90) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p90,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p95,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error) AS p99
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL}
              AND e.architecture = '{arch}'
              AND e.ram_in_mb = {ram}
              {cpu_clause}
              AND e.auth_strategy IN ('none', 'edge')
              AND r.phase_name = 'Baseline'
              AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
            GROUP BY e.auth_strategy
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)

        combined = pd.concat([es_df, ref_df], ignore_index=True)
        if combined.empty:
            continue

        for col in ['p50', 'p75', 'p90', 'p95', 'p99']:
            combined[col] = combined[col].astype(float)

        print(f"\n  {arch.upper()} / {hlabel}:")
        for _, row in combined.iterrows():
            auth = row['auth_strategy']
            print(f"    {AUTH_SHORT.get(auth, auth):>12s}: P50={row['p50']:.1f}  "
                  f"P75={row['p75']:.1f}  P99={row['p99']:.1f}  (n={row['n_success']:,.0f})")

            comparison_rows.append({
                'architecture': arch,
                'hw_tier': hlabel,
                'ram_in_mb': ram,
                'cpu_in_vcpu': cpu if pd.notna(cpu) else None,
                'auth_strategy': auth,
                'auth_label': AUTH_SHORT.get(auth, auth),
                'n_success': int(row['n_success']),
                'P50': round(float(row['p50']), 1),
                'P75': round(float(row['p75']), 1),
                'P90': round(float(row['p90']), 1),
                'P95': round(float(row['p95']), 1),
                'P99': round(float(row['p99']), 1),
            })

    comparison_df = pd.DataFrame(comparison_rows)
    if not comparison_df.empty:
        comparison_df.to_csv(f"{PLOT_DIR}/edge_selective_analysis.csv", index=False)
        print(f"\nSaved: {PLOT_DIR}/edge_selective_analysis.csv")

    # --- PLOT 1: Comparison bar chart (P99) ---
    if not comparison_df.empty:
        # Group by architecture
        archs_with_data = comparison_df['architecture'].unique()
        n_archs = len(archs_with_data)
        fig, axes = plt.subplots(1, max(n_archs, 1), figsize=(6 * max(n_archs, 1), 6))
        if n_archs == 1:
            axes = [axes]

        for ax, arch in zip(axes, archs_with_data):
            arch_data = comparison_df[comparison_df['architecture'] == arch]
            hw_tiers = sorted(arch_data['hw_tier'].unique(),
                              key=lambda x: {'S': 1, 'M': 2, 'L': 3, 'XL': 4}.get(
                                  x, int(x.replace('MB', '')) if 'MB' in x else 0))

            auth_strategies = ['none', 'edge-selective', 'edge']
            auth_present = [a for a in auth_strategies if a in arch_data['auth_strategy'].values]

            x = np.arange(len(hw_tiers))
            width = 0.8 / max(len(auth_present), 1)

            for i, auth in enumerate(auth_present):
                vals = []
                for hw in hw_tiers:
                    match = arch_data[(arch_data['auth_strategy'] == auth) &
                                     (arch_data['hw_tier'] == hw)]
                    vals.append(match.iloc[0]['P99'] if not match.empty else 0)
                offset = (i - len(auth_present) / 2 + 0.5) * width
                label = AUTH_SHORT.get(auth, auth)
                color = AUTH_COLORS.get(label, '#999999')
                bars = ax.bar(x + offset, vals, width, label=label, color=color, alpha=0.85)

                for bar, val in zip(bars, vals):
                    if val > 0:
                        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                                f'{val:.0f}', ha='center', va='bottom', fontsize=7)

            ax.set_xticks(x)
            ax.set_xticklabels(hw_tiers, fontsize=10)
            ax.set_ylabel('P99 Latency (ms)', fontsize=11)
            ax.set_title(f'{arch.capitalize()}', fontweight='bold', fontsize=12)
            ax.legend(fontsize=9)
            ax.grid(axis='y', alpha=0.3)

        fig.suptitle('Edge-Selective vs Full-Edge vs None: P99 Latency Comparison\n'
                     '(Baseline phase, all endpoints)',
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/edge_selective_comparison.pdf"
        fig.savefig(path, dpi=300, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # --- PLOT 1b: ΔAuth comparison (P99 overhead vs None) ---
    if not comparison_df.empty:
        archs_with_data = comparison_df['architecture'].unique()
        n_archs = len(archs_with_data)
        fig, axes = plt.subplots(1, max(n_archs, 1), figsize=(6 * max(n_archs, 1), 6))
        if n_archs == 1:
            axes = [axes]

        for ax, arch in zip(axes, archs_with_data):
            arch_data = comparison_df[comparison_df['architecture'] == arch]
            hw_tiers = sorted(arch_data['hw_tier'].unique(),
                              key=lambda x: {'S': 1, 'M': 2, 'L': 3, 'XL': 4}.get(
                                  x, int(x.replace('MB', '')) if 'MB' in x else 0))

            auth_strategies = ['edge-selective', 'edge']
            auth_present = [a for a in auth_strategies if a in arch_data['auth_strategy'].values]

            x = np.arange(len(hw_tiers))
            width = 0.8 / max(len(auth_present), 1)

            for i, auth in enumerate(auth_present):
                vals = []
                for hw in hw_tiers:
                    # Get auth P99
                    auth_match = arch_data[(arch_data['auth_strategy'] == auth) &
                                          (arch_data['hw_tier'] == hw)]
                    none_match = arch_data[(arch_data['auth_strategy'] == 'none') &
                                          (arch_data['hw_tier'] == hw)]
                    if not auth_match.empty and not none_match.empty:
                        delta = auth_match.iloc[0]['P99'] - none_match.iloc[0]['P99']
                        vals.append(delta)
                    else:
                        vals.append(0)
                offset = (i - len(auth_present) / 2 + 0.5) * width
                label = AUTH_SHORT.get(auth, auth)
                color = AUTH_COLORS.get(label, '#999999')
                bars = ax.bar(x + offset, vals, width, label=label, color=color, alpha=0.85)

                for bar, val in zip(bars, vals):
                    if val != 0:
                        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                                f'{val:+.0f}', ha='center', va='bottom', fontsize=7)

            ax.set_xticks(x)
            ax.set_xticklabels(hw_tiers, fontsize=10)
            ax.set_ylabel('ΔAuth P99 (ms)', fontsize=11)
            ax.set_title(f'{arch.capitalize()}', fontweight='bold', fontsize=12)
            ax.legend(fontsize=9)
            ax.grid(axis='y', alpha=0.3)
            ax.axhline(y=0, color='black', linewidth=0.8, linestyle='-')

        fig.suptitle('Edge-Selective vs Full-Edge: ΔAuth P99 Overhead\n'
                     '(Baseline phase, auth-only endpoints, relative to None)',
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/edge_selective_delta_comparison.pdf"
        fig.savefig(path, dpi=300, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # ── 3. CloudFront overhead isolation (FaaS only) ──
    print("\n--- PART 3: CloudFront Overhead Isolation (FaaS) ---")

    # Compare: edge-selective WITH CF (159,160,161) vs WITHOUT CF (145,146,147)
    # Also CF baselines (158, 162): none + CloudFront
    cf_groups = {
        'ES + CF': CF_FAAS_ES,
        'ES no CF': NO_CF_FAAS_ES,
        'None + CF': CF_BASELINES,
    }

    cf_rows = []
    for group_name, exp_ids in cf_groups.items():
        ids_sql = ','.join(str(x) for x in exp_ids)
        cf_df = query_df(f"""
            SELECT
                e.id,
                e.ram_in_mb,
                COUNT(*) FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS n_success,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p50,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                    FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') AS p99
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE e.id IN ({ids_sql})
            GROUP BY e.id, e.ram_in_mb
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error AND r.phase_name = 'Baseline') > 50
        """)

        if cf_df.empty:
            print(f"  {group_name}: no data")
            continue

        for col in ['p50', 'p99']:
            cf_df[col] = cf_df[col].astype(float)

        for _, row in cf_df.iterrows():
            print(f"  {group_name} (exp {row['id']:.0f}, {row['ram_in_mb']:.0f}MB): "
                  f"P50={row['p50']:.1f}ms, P99={row['p99']:.1f}ms (n={row['n_success']:,.0f})")
            cf_rows.append({
                'group': group_name,
                'experiment_id': int(row['id']),
                'ram_in_mb': int(row['ram_in_mb']),
                'n_success': int(row['n_success']),
                'P50': round(float(row['p50']), 1),
                'P99': round(float(row['p99']), 1),
            })

    # Also add FaaS none (no CF) for baseline reference
    faas_none_df = query_df(f"""
        SELECT
            e.ram_in_mb,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = 'faas'
          AND e.auth_strategy = 'none'
          AND e.ram_in_mb IN (256, 512, 1024)
          AND r.phase_name = 'Baseline'
          AND NOT r.is_error
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
        GROUP BY e.ram_in_mb
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)

    if not faas_none_df.empty:
        for col in ['p50', 'p99']:
            faas_none_df[col] = faas_none_df[col].astype(float)
        for _, row in faas_none_df.iterrows():
            cf_rows.append({
                'group': 'None no CF',
                'experiment_id': None,
                'ram_in_mb': int(row['ram_in_mb']),
                'n_success': int(row['n_success']),
                'P50': round(float(row['p50']), 1),
                'P99': round(float(row['p99']), 1),
            })

    cf_result = pd.DataFrame(cf_rows)

    # --- PLOT 2: CloudFront overhead ---
    if not cf_result.empty:
        ram_tiers = sorted(cf_result['ram_in_mb'].unique())
        groups_to_plot = ['None no CF', 'None + CF', 'ES no CF', 'ES + CF']
        group_colors = {
            'None no CF': '#999999', 'None + CF': '#BDBDBD',
            'ES no CF': '#FF9800', 'ES + CF': '#E65100',
        }

        fig, axes = plt.subplots(1, len(ram_tiers), figsize=(6 * len(ram_tiers), 6))
        if len(ram_tiers) == 1:
            axes = [axes]

        for ax, ram in zip(axes, ram_tiers):
            ram_data = cf_result[cf_result['ram_in_mb'] == ram]
            groups_present = [g for g in groups_to_plot if g in ram_data['group'].values]

            x = np.arange(len(groups_present))
            p99_vals = []
            colors = []
            labels = []

            for group in groups_present:
                match = ram_data[ram_data['group'] == group]
                if not match.empty:
                    # Average if multiple experiments
                    p99_vals.append(match['P99'].mean())
                else:
                    p99_vals.append(0)
                colors.append(group_colors.get(group, '#999'))
                labels.append(group)

            bars = ax.bar(x, p99_vals, color=colors, alpha=0.85)

            for bar, val in zip(bars, p99_vals):
                if val > 0:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                            f'{val:.0f}ms', ha='center', va='bottom', fontsize=9,
                            fontweight='bold')

            ax.set_xticks(x)
            ax.set_xticklabels(labels, fontsize=8, rotation=20, ha='right')
            ax.set_ylabel('P99 Latency (ms)', fontsize=11)
            ax.set_title(f'FaaS {ram}MB', fontweight='bold', fontsize=12)
            ax.grid(axis='y', alpha=0.3)

        fig.suptitle('CloudFront Overhead: Edge-Selective With vs Without CloudFront\n'
                     '(FaaS, Baseline phase, P99)',
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        path = f"{PLOT_DIR}/edge_selective_cf_overhead.pdf"
        fig.savefig(path, dpi=300, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close()

    # ── 4. Summary ──
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)

    # Compare edge-selective vs full-edge
    if not comparison_df.empty:
        for arch in comparison_df['architecture'].unique():
            arch_data = comparison_df[comparison_df['architecture'] == arch]
            for hw in arch_data['hw_tier'].unique():
                hw_data = arch_data[arch_data['hw_tier'] == hw]
                es_row = hw_data[hw_data['auth_strategy'] == 'edge-selective']
                edge_row = hw_data[hw_data['auth_strategy'] == 'edge']
                none_row = hw_data[hw_data['auth_strategy'] == 'none']

                if not es_row.empty and not edge_row.empty:
                    es_p99 = es_row.iloc[0]['P99']
                    edge_p99 = edge_row.iloc[0]['P99']
                    diff = es_p99 - edge_p99
                    print(f"  {arch}/{hw}: Edge-Selective P99={es_p99:.0f}ms vs "
                          f"Full-Edge P99={edge_p99:.0f}ms (diff={diff:+.0f}ms)")
                elif not es_row.empty and not none_row.empty:
                    es_p99 = es_row.iloc[0]['P99']
                    none_p99 = none_row.iloc[0]['P99']
                    diff = es_p99 - none_p99
                    print(f"  {arch}/{hw}: Edge-Selective P99={es_p99:.0f}ms vs "
                          f"None P99={none_p99:.0f}ms (diff={diff:+.0f}ms)")

    # CloudFront overhead
    if not cf_result.empty:
        print("\n  CloudFront overhead (FaaS):")
        for ram in sorted(cf_result['ram_in_mb'].unique()):
            with_cf = cf_result[(cf_result['ram_in_mb'] == ram) & (cf_result['group'] == 'ES + CF')]
            without_cf = cf_result[(cf_result['ram_in_mb'] == ram) & (cf_result['group'] == 'ES no CF')]
            if not with_cf.empty and not without_cf.empty:
                diff = with_cf['P99'].mean() - without_cf['P99'].mean()
                print(f"    {ram}MB: CF adds {diff:+.0f}ms P99 overhead")

    print()


if __name__ == '__main__':
    main()
