#!/usr/bin/env python3
"""Generate anova_summary.tex for tab:anova-summary.

Phase-stability table: how many of the 7 SCNAST phases show a significant
auth strategy effect per (architecture, hw) configuration. Uses one-factor
ANOVA with F-test at α=0.05, auth-only endpoints, primary strategies only.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, hw_label_from_row, HW_TIERS_ALL)

ALPHA = 0.05
PROTECTED_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)
SCNAST_PHASES = [
    'Warm-up', 'Baseline', 'Morning rush', 'Stabilization',
    'Flash Crowd', 'Step Down', 'Cool-down',
]
PRIMARY_AUTH_LABELS = ['None', 'Cognito', 'Manual (bcrypt)', 'Edge']


def query_phase_data(phase):
    dfs = []
    for arch, endpoints in [('faas', PROTECTED_FAAS), (None, PROTECTED_CONTAINER)]:
        eps = ','.join(f"'{e}'" for e in endpoints)
        arch_clause = (f"AND e.architecture = '{arch}'" if arch == 'faas'
                       else "AND e.architecture IN ('microservices', 'monolith')")
        df = query_df(f"""
            SELECT e.id, e.architecture, e.auth_strategy,
                   COALESCE(e.password_hash_algorithm, 'default') AS algo,
                   COALESCE(e.with_cloudfront, false) AS with_cf,
                   e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu_in_vcpu,
                   percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                       FILTER (WHERE NOT r.is_error) AS p99
            FROM experiments e
            JOIN requests r ON r.experiment_id = e.id
            WHERE {EXCLUDE_SQL} {arch_clause}
              AND r.phase_name = '{phase}'
              AND r.endpoint IN ({eps})
            GROUP BY e.id, e.architecture, e.auth_strategy,
                     e.password_hash_algorithm, e.with_cloudfront,
                     e.ram_in_mb, e.cpu_in_vcpu
            HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
        """)
        dfs.append(df)
    result = pd.concat(dfs, ignore_index=True)
    if result.empty:
        return result
    result['p99'] = result['p99'].astype(float)
    result['hw'] = result.apply(hw_label_from_row, axis=1)
    result['auth_label'] = result.apply(
        lambda r: auth_label_detailed(
            r['auth_strategy'],
            r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
            bool(r['with_cf']) if r['with_cf'] else False
        ), axis=1)
    return result


def group_for_anova(per_exp_df, arch, hw):
    mask = ((per_exp_df['architecture'] == arch) &
            (per_exp_df['hw'] == hw) &
            (per_exp_df['auth_label'].isin(PRIMARY_AUTH_LABELS)) &
            (~per_exp_df['with_cf']))
    subset = per_exp_df[mask]
    groups = {}
    for label in PRIMARY_AUTH_LABELS:
        vals = subset[subset['auth_label'] == label]['p99'].values
        if len(vals) > 0:
            groups[label] = vals
    return groups


def one_factor_anova(groups):
    labels = list(groups.keys())
    k = len(labels)
    if k < 2:
        return None
    all_values = []
    group_means, group_sizes = {}, {}
    for label in labels:
        vals = np.array(groups[label], dtype=float)
        if len(vals) < 1:
            return None
        group_means[label] = np.mean(vals)
        group_sizes[label] = len(vals)
        all_values.extend(vals)
    all_values = np.array(all_values)
    N = len(all_values)
    if N - k < 1:
        return None
    grand_mean = np.mean(all_values)
    SSA = sum(group_sizes[l] * (group_means[l] - grand_mean) ** 2 for l in labels)
    SSE = sum(np.sum((np.array(groups[l], dtype=float) - group_means[l]) ** 2) for l in labels)
    SST = SSA + SSE
    df_between = k - 1
    df_within = N - k
    MSA = SSA / df_between
    MSE = SSE / df_within if df_within > 0 else np.inf
    F_stat = MSA / MSE if MSE > 0 else np.inf
    F_critical = sp_stats.f.ppf(1 - ALPHA, df_between, df_within)
    return {
        'significant': F_stat > F_critical,
        'SSA_ratio': SSA / SST if SST > 0 else 0,
    }


def main():
    all_anova = []
    for phase in SCNAST_PHASES:
        per_exp = query_phase_data(phase)
        if per_exp.empty:
            continue
        for arch in ['faas', 'microservices', 'monolith']:
            hw_tiers = HW_TIERS_ALL.get(arch, [])
            for _, _, hw_label in hw_tiers:
                groups = group_for_anova(per_exp, arch, hw_label)
                testable = {k: v for k, v in groups.items() if len(v) >= 2}
                if len(testable) < 2:
                    continue
                result = one_factor_anova(testable)
                if result is None:
                    continue
                all_anova.append({
                    'phase': phase, 'architecture': arch, 'hw': hw_label,
                    'significant': result['significant'],
                    'SSA_ratio': result['SSA_ratio'],
                })

    if not all_anova:
        print('No ANOVA results'); return

    anova_df = pd.DataFrame(all_anova)

    lines = []
    lines.append("% ── ANOVA Summary (Phase Stability only) ──")
    lines.append("% Generated by tables/tab_anova_summary.py")
    lines.append("% Hinweis: Die vollständige ANOVA-Detailtabelle (tab:anova-all-phases) und")
    lines.append("% die Kontraste-Detailtabelle (tab:contrasts-all-phases) werden im Anhang")
    lines.append("% eingebunden (plots/anova_detail.tex, plots/anova_contrasts_detail.tex).")
    lines.append("")
    lines.append("% ── Phase Stability Summary ──")
    lines.append(r"\begin{table}[htbp]")
    lines.append(r"\centering")
    lines.append(r"\caption{Phasenstabilit\"at der ANOVA-Signifikanz. Anzahl der Phasen mit "
                 r"signifikantem Strategieeffekt pro Konfiguration ($\alpha = 0{,}05$).}")
    lines.append(r"\label{tab:anova-phase-stability}")
    lines.append(r"\begin{tabular}{@{}llccc@{}}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Architektur} & \textbf{Hardware} & "
                 r"\textbf{Sig./Getestet} & \textbf{SSA/SST (BL)} & \textbf{Bewertung} \\")
    lines.append(r"\midrule")

    stability = anova_df.groupby(['architecture', 'hw']).agg(
        n_phases=('significant', 'count'),
        n_sig=('significant', 'sum'),
    ).reset_index()

    for _, row in stability.iterrows():
        ratio = f"{int(row['n_sig'])}/{int(row['n_phases'])}"
        bl = anova_df[(anova_df['architecture'] == row['architecture']) &
                      (anova_df['hw'] == row['hw']) &
                      (anova_df['phase'] == 'Baseline')]
        bl_ssa = f"{bl.iloc[0]['SSA_ratio']*100:.0f}\\,\\%" if len(bl) > 0 else '---'

        if row['n_sig'] == row['n_phases']:
            label = 'stabil-sig.'
        elif row['n_sig'] == 0:
            label = 'stabil-n.s.'
        elif row['n_sig'] >= row['n_phases'] * 0.5:
            label = 'phasenabh.'
        else:
            label = 'lastabh.'

        lines.append(
            f"  {row['architecture'].capitalize():15s} & {row['hw']:6s} & "
            f"{ratio} & {bl_ssa} & {label} \\\\"
        )

    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")
    lines.append("")

    path = f"{PLOT_DIR}/anova_summary.tex"
    with open(path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"Saved: {path}")


if __name__ == '__main__':
    main()
