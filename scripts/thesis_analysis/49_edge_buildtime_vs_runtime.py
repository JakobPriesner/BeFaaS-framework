"""Script 49: Edge Buildtime vs Runtime JWKS comparison.

Compares end-to-end latency between Edge experiments using Build-Time-JWKS (v1)
and Runtime-JWKS (v2) at matching hardware configurations.

IMPORTANT STRUCTURAL CAVEAT
---------------------------
Early Edge-Container-Experimente (v1) erfassten bare-path Endpunkte
(`/cart`, `/checkout`), während die späteren v2-Experimente das CloudFront-
gerouteten `/frontend/...`-Präfix tragen. Das bedeutet: v1-Container-Messungen
und v2-Container-Messungen erfassen unterschiedliche Request-Pfade durch die
Infrastruktur; sie sind **nicht direkt vergleichbar**.

Nur die FaaS-Konfigurationen verwenden in beiden Messserien `/frontend/...`
und erlauben einen methodisch sauberen v1-vs-v2-Vergleich.

Outputs:
  - edge_buildtime_vs_runtime_comparison.pdf  (FaaS-only comparable bar chart)
  - edge_buildtime_vs_runtime_table.tex       (LaTeX table for thesis, FaaS only)
  - edge_buildtime_vs_runtime_summary.csv     (raw data for all configs)
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

# Configs with overlapping v1/v2 experiments (from DB inspection 2026-04-28)
CONFIGS = [
    # (arch, ram, cpu, label, comparable_flag)
    ('faas',          1024, 0,    'FaaS 1024',       True),
    ('faas',          1769, 0,    'FaaS 1769',       True),
    ('microservices', 1024, 0.5,  'MS 1024/0.5',     False),
    ('microservices', 2048, 1.0,  'MS 2048/1.0',     False),
    ('microservices', 8192, 4.0,  'MS 8192/4.0',     False),
    ('monolith',      1024, 0.25, 'Mono 1024/0.25',  False),
    ('monolith',      1024, 1.0,  'Mono 1024/1.0',   False),
    ('monolith',      1024, 4.0,  'Mono 1024/4.0',   False),
]

# Auth-relevante Endpunkte, beide Pfad-Konventionen
PROTECTED_ALL = (
    "'/frontend/setUser'", "'/frontend/addCartItem'",
    "'/frontend/cart'", "'/frontend/checkout'",
    "'/setUser'", "'/addCartItem'", "'/cart'", "'/checkout'"
)


def query_config(arch, ram, cpu, label):
    eps_sql = ','.join(PROTECTED_ALL)
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

    sql = f"""
    SELECT
        e.id AS experiment_id,
        e.jwks_mode,
        e.auth_strategy,
        COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
        COUNT(*) AS n_total,
        COUNT(*) FILTER (WHERE r.is_error) AS n_errors,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p50,
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
      AND e.auth_strategy IN ('edge', 'edge-selective')
      AND e.jwks_mode IS NOT NULL
      AND r.phase_name = 'Baseline'
      AND r.endpoint IN ({eps_sql})
    GROUP BY e.id, e.jwks_mode, e.auth_strategy
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    ORDER BY e.jwks_mode, e.id
    """
    df = query_df(sql)
    df['config'] = label
    return df


def query_none_baseline(arch, ram, cpu):
    eps_sql = ','.join(PROTECTED_ALL)
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

    sql = f"""
    SELECT
        e.id AS experiment_id,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS p50,
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
      AND e.auth_strategy = 'none'
      AND r.phase_name = 'Baseline'
      AND r.endpoint IN ({eps_sql})
    GROUP BY e.id
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """
    return query_df(sql)


def generate_latex_table(summary_df, output_path):
    """FaaS-only Tabelle: saubere v1-vs-v2-Vergleichbarkeit."""
    lines = []
    lines.append(r'\begin{tabular}{@{}l rr rr rr@{}}')
    lines.append(r'\toprule')
    lines.append(r'& \multicolumn{2}{c}{$\Delta$P50 (ms)} & \multicolumn{2}{c}{$\Delta$P95 (ms)} & \multicolumn{2}{c}{$\Delta$P99 (ms)} \\')
    lines.append(r'\cmidrule(lr){2-3} \cmidrule(lr){4-5} \cmidrule(lr){6-7}')
    lines.append(r'\textbf{Konfiguration} & {v1} & {v2} & {v1} & {v2} & {v1} & {v2} \\')
    lines.append(r'\midrule')

    for _, row in summary_df.iterrows():
        def fmt(v):
            return '--' if pd.isna(v) else f'{v:+.0f}'
        lines.append(
            f"{row['config']} & {fmt(row.get('bt_delta_p50'))} & {fmt(row.get('rt_delta_p50'))} "
            f"& {fmt(row.get('bt_delta_p95'))} & {fmt(row.get('rt_delta_p95'))} "
            f"& {fmt(row.get('bt_delta_p99'))} & {fmt(row.get('rt_delta_p99'))} \\\\"
        )

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')

    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))


def main():
    all_rows = []

    print("=" * 70)
    print("  Edge Buildtime vs Runtime JWKS Comparison")
    print("  Auth-only endpoints, Baseline phase")
    print("=" * 70)
    print("\nNOTE: Container v1 records bare paths, v2 records /frontend/...")
    print("      → Container v1↔v2 NICHT direkt vergleichbar (Pfad-Konfund).")
    print("      → Nur FaaS-Vergleich methodisch sauber.\n")

    for arch, ram, cpu, label, comparable in CONFIGS:
        print(f"\n{'─' * 60}")
        print(f"  {label} ({arch}, {ram}MB, {cpu}vCPU)"
              f"{'  [COMPARABLE]' if comparable else '  [PATH-CONFOUND]'}")
        print(f"{'─' * 60}")

        df = query_config(arch, ram, cpu, label)
        none_df = query_none_baseline(arch, ram, cpu)

        if df.empty:
            print("  Keine Edge-Experimente vorhanden")
            continue
        if none_df.empty:
            print("  Keine None-Baseline — ΔAuth nicht berechenbar")
            continue

        none_mean = none_df[['p50', 'p95', 'p99']].mean()

        for mode in ['buildtime', 'runtime']:
            mode_df = df[df['jwks_mode'] == mode]
            if mode_df.empty:
                print(f"  {mode}: keine Experimente")
                continue

            n_exps = len(mode_df)
            exp_ids = mode_df['experiment_id'].tolist()
            mean_p50 = mode_df['p50'].mean()
            mean_p95 = mode_df['p95'].mean()
            mean_p99 = mode_df['p99'].mean()
            delta_p50 = mean_p50 - none_mean['p50']
            delta_p95 = mean_p95 - none_mean['p95']
            delta_p99 = mean_p99 - none_mean['p99']
            mean_err = mode_df['n_errors'].sum() / mode_df['n_total'].sum() * 100

            print(f"  {mode}: n={n_exps}, IDs={exp_ids}")
            print(f"    Absolut: P50={mean_p50:.1f} P95={mean_p95:.1f} P99={mean_p99:.1f}")
            print(f"    ΔAuth:   P50={delta_p50:+.1f} P95={delta_p95:+.1f} P99={delta_p99:+.1f}")
            print(f"    Fehlerrate: {mean_err:.2f}%")

            all_rows.append({
                'config': label,
                'architecture': arch,
                'ram_in_mb': ram,
                'cpu_in_vcpu': cpu,
                'comparable': comparable,
                'jwks_mode': mode,
                'n_experiments': n_exps,
                'experiment_ids': str(exp_ids),
                'abs_p50': round(mean_p50, 1),
                'abs_p95': round(mean_p95, 1),
                'abs_p99': round(mean_p99, 1),
                'none_p50': round(none_mean['p50'], 1),
                'none_p95': round(none_mean['p95'], 1),
                'none_p99': round(none_mean['p99'], 1),
                'delta_p50': round(delta_p50, 1),
                'delta_p95': round(delta_p95, 1),
                'delta_p99': round(delta_p99, 1),
                'error_rate_pct': round(mean_err, 2),
            })

        bt = [r for r in all_rows if r['config'] == label and r['jwks_mode'] == 'buildtime']
        rt = [r for r in all_rows if r['config'] == label and r['jwks_mode'] == 'runtime']
        if bt and rt:
            bt, rt = bt[-1], rt[-1]
            shift_p50 = rt['delta_p50'] - bt['delta_p50']
            shift_p95 = rt['delta_p95'] - bt['delta_p95']
            shift_p99 = rt['delta_p99'] - bt['delta_p99']
            flag = '' if comparable else '  (⚠ Pfad-Konfund – nicht interpretierbar)'
            print(f"\n  *** v2 − v1 shift: ΔP50={shift_p50:+.1f} ΔP95={shift_p95:+.1f} ΔP99={shift_p99:+.1f} ms ***{flag}")

    if not all_rows:
        print("\nKeine Daten erfasst. Abbruch.")
        return

    results_df = pd.DataFrame(all_rows)
    csv_path = f"{PLOT_DIR}/edge_buildtime_vs_runtime_summary.csv"
    results_df.to_csv(csv_path, index=False)
    print(f"\nGespeichert: {csv_path}")

    # ── LaTeX Tabelle: nur methodisch saubere Vergleiche (FaaS) ──
    comparable_df = results_df[results_df['comparable']]
    summary_rows = []
    for cfg in comparable_df['config'].unique():
        bt = comparable_df[(comparable_df['config'] == cfg) & (comparable_df['jwks_mode'] == 'buildtime')]
        rt = comparable_df[(comparable_df['config'] == cfg) & (comparable_df['jwks_mode'] == 'runtime')]
        row = {'config': cfg}
        if not bt.empty:
            row['bt_delta_p50'] = bt.iloc[0]['delta_p50']
            row['bt_delta_p95'] = bt.iloc[0]['delta_p95']
            row['bt_delta_p99'] = bt.iloc[0]['delta_p99']
        if not rt.empty:
            row['rt_delta_p50'] = rt.iloc[0]['delta_p50']
            row['rt_delta_p95'] = rt.iloc[0]['delta_p95']
            row['rt_delta_p99'] = rt.iloc[0]['delta_p99']
        if len(row) > 1:
            summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    tex_path = f"{PLOT_DIR}/edge_buildtime_vs_runtime_table.tex"
    if not summary_df.empty:
        generate_latex_table(summary_df, tex_path)
        print(f"Gespeichert: {tex_path}")

    # ── Balkendiagramm: FaaS-only (methodisch sauber) ──
    configs_both = comparable_df.groupby('config')['jwks_mode'].nunique()
    configs_both = configs_both[configs_both == 2].index.tolist()
    plot_df = comparable_df[comparable_df['config'].isin(configs_both)].copy()

    if plot_df.empty:
        print("\nKeine Configs mit sauberem v1+v2-Vergleich — überspringe Plot.")
        return

    config_order = [c[3] for c in CONFIGS if c[3] in configs_both]

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    bar_width = 0.35
    x = np.arange(len(config_order))

    for ax, pct, pct_label in zip(axes, ['delta_p50', 'delta_p95', 'delta_p99'],
                                   [r'$\Delta$P50', r'$\Delta$P95', r'$\Delta$P99']):
        bt_vals = []
        rt_vals = []
        for cfg in config_order:
            bt_row = plot_df[(plot_df['config'] == cfg) & (plot_df['jwks_mode'] == 'buildtime')]
            rt_row = plot_df[(plot_df['config'] == cfg) & (plot_df['jwks_mode'] == 'runtime')]
            bt_vals.append(bt_row.iloc[0][pct] if not bt_row.empty else 0)
            rt_vals.append(rt_row.iloc[0][pct] if not rt_row.empty else 0)

        ax.bar(x - bar_width / 2, bt_vals, bar_width,
               label=JWKS_MODE_LABELS['buildtime'],
               color=JWKS_MODE_COLORS['buildtime'], edgecolor='white')
        ax.bar(x + bar_width / 2, rt_vals, bar_width,
               label=JWKS_MODE_LABELS['runtime'],
               color=JWKS_MODE_COLORS['runtime'], edgecolor='white')

        ax.set_xticks(x)
        ax.set_xticklabels(config_order, rotation=0, ha='center', fontsize=9)
        ax.set_ylabel(f'{pct_label} (ms)')
        ax.set_title(pct_label, fontweight='bold')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, axis='y')
        ax.axhline(y=0, color='black', linewidth=0.5)

    fig.suptitle('Edge $\\Delta$Auth: Build-Time-JWKS (v1) vs Laufzeit-JWKS (v2)\n'
                 'Nur FaaS-Konfigurationen (Container: Pfad-Konfund)',
                 fontsize=11, fontweight='bold')
    plt.tight_layout()
    pdf_path = f"{PLOT_DIR}/edge_buildtime_vs_runtime_comparison.pdf"
    plt.savefig(pdf_path, bbox_inches='tight', dpi=300)
    plt.close()
    print(f"Gespeichert: {pdf_path}")

    # ── Übersicht ──
    print("\n" + "=" * 70)
    print("  ZUSAMMENFASSUNG")
    print("=" * 70)

    comp_df = results_df[results_df['comparable']]
    bt_all = comp_df[comp_df['jwks_mode'] == 'buildtime']
    rt_all = comp_df[comp_df['jwks_mode'] == 'runtime']

    if not bt_all.empty and not rt_all.empty:
        shared = set(bt_all['config']) & set(rt_all['config'])
        if shared:
            print(f"\n  Methodisch saubere Configs (FaaS) mit beiden Modi ({len(shared)}):")
            for cfg in sorted(shared):
                bt_row = bt_all[bt_all['config'] == cfg].iloc[0]
                rt_row = rt_all[rt_all['config'] == cfg].iloc[0]
                shift50 = rt_row['delta_p50'] - bt_row['delta_p50']
                shift95 = rt_row['delta_p95'] - bt_row['delta_p95']
                shift99 = rt_row['delta_p99'] - bt_row['delta_p99']
                print(f"    {cfg}: v2-v1 shift ΔP50={shift50:+.1f}ms, ΔP95={shift95:+.1f}ms, ΔP99={shift99:+.1f}ms")

    non_comp = results_df[~results_df['comparable']]
    if not non_comp.empty:
        print(f"\n  Container-Configs mit Pfad-Konfund ({non_comp['config'].nunique()}):")
        print("    Nicht direkt vergleichbar — v1 erfasst bare paths (/cart),")
        print("    v2 erfasst /frontend/cart. Unterschiedliche Request-Pfade.")


if __name__ == '__main__':
    main()
