#!/usr/bin/env python3
"""Generate sb_baseline_p99_with_ci.pdf for fig:sb-baseline-ci.

3-row panel (FaaS | Microservices | Monolith) showing Baseline P99 latency
per auth strategy and hardware tier, with 95% t-CI error bars from
experiment repetitions.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, hw_label_from_row,
                           AUTH_COLORS_DETAILED)

CONFIDENCE_LEVEL = 0.95


def t_ci(values):
    n = len(values)
    if n < 2:
        return np.mean(values), np.nan, np.nan, n
    mean = np.mean(values)
    se = sp_stats.sem(values)
    ci = sp_stats.t.interval(CONFIDENCE_LEVEL, df=n - 1, loc=mean, scale=se)
    return mean, ci[0], ci[1], n


def main():
    per_exp = query_df(f"""
        SELECT e.id, e.architecture, e.auth_strategy,
               COALESCE(e.password_hash_algorithm, 'default') AS algo,
               COALESCE(e.with_cloudfront, false) AS with_cf,
               e.ram_in_mb, COALESCE(e.cpu_in_vcpu, 0) AS cpu_in_vcpu,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                   FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL} AND r.phase_name = 'Baseline'
        GROUP BY e.id, e.architecture, e.auth_strategy, algo, with_cf,
                 e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 500
    """)
    if per_exp.empty:
        print('No data'); return

    per_exp['p99'] = per_exp['p99'].astype(float)
    per_exp['hw'] = per_exp.apply(hw_label_from_row, axis=1)
    per_exp['auth_label'] = per_exp.apply(
        lambda r: auth_label_detailed(
            r['auth_strategy'],
            r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
            bool(r['with_cf']) if r['with_cf'] else False
        ), axis=1)
    per_exp['config'] = per_exp.apply(
        lambda r: f"{r['architecture']}|{r['auth_strategy']}|{r['algo']}|{r['ram_in_mb']}|{r['cpu_in_vcpu']}|{r['with_cf']}",
        axis=1)

    agg_rows = []
    for config, grp in per_exp.groupby('config'):
        p99_vals = grp['p99'].values
        mean, ci_lo, ci_hi, n = t_ci(p99_vals)
        row = grp.iloc[0]
        agg_rows.append({
            'architecture': row['architecture'], 'auth_strategy': row['auth_strategy'],
            'auth_label': row['auth_label'], 'algo': row['algo'],
            'with_cf': row['with_cf'], 'hw': row['hw'],
            'n_runs': n, 'p99_mean': mean, 'p99_ci_lo': ci_lo, 'p99_ci_hi': ci_hi,
        })

    agg = pd.DataFrame(agg_rows)

    fig, axes = plt.subplots(3, 1, figsize=(12, 15))
    for ax, arch in zip(axes, ['faas', 'microservices', 'monolith']):
        arch_data = agg[(agg['architecture'] == arch) &
                        (~agg['auth_strategy'].isin(['edge-selective'])) &
                        (agg['with_cf'] == False) &
                        (agg['algo'] != 'argon2id')]
        if arch_data.empty:
            ax.set_title(f'{arch} (keine Daten)'); continue

        auth_labels = sorted(arch_data['auth_label'].unique())
        hw_order = {'S': 1, 'M': 2, 'L': 3, 'XL': 4}
        hw_labels = sorted(arch_data['hw'].unique(),
                           key=lambda x: hw_order.get(x, int(x.replace('MB', '')) if 'MB' in x else 0))

        x = np.arange(len(hw_labels))
        width = 0.8 / max(len(auth_labels), 1)

        for i, al in enumerate(auth_labels):
            means, errs_lo, errs_hi, ns = [], [], [], []
            for hw in hw_labels:
                match = arch_data[(arch_data['auth_label'] == al) & (arch_data['hw'] == hw)]
                if not match.empty:
                    r = match.iloc[0]
                    means.append(r['p99_mean'])
                    if r['n_runs'] >= 2 and not np.isnan(r['p99_ci_lo']):
                        errs_lo.append(r['p99_mean'] - r['p99_ci_lo'])
                        errs_hi.append(r['p99_ci_hi'] - r['p99_mean'])
                    else:
                        errs_lo.append(0); errs_hi.append(0)
                    ns.append(r['n_runs'])
                else:
                    means.append(0); errs_lo.append(0); errs_hi.append(0); ns.append(0)

            offset = (i - len(auth_labels) / 2 + 0.5) * width
            color = AUTH_COLORS_DETAILED.get(al, '#999')
            ax.bar(x + offset, means, width, label=al, color=color, alpha=0.85,
                   yerr=[errs_lo, errs_hi], capsize=3, ecolor='black',
                   error_kw={'linewidth': 1})
            for j, (m, n) in enumerate(zip(means, ns)):
                if m > 0 and n >= 2:
                    ax.annotate(f'n={n}', xy=(x[j] + offset, m + errs_hi[j]),
                               xytext=(0, 3), textcoords='offset points',
                               ha='center', fontsize=9, color='gray')

        ax.set_xticks(x)
        ax.set_xticklabels(hw_labels, fontsize=11)
        ax.set_xlabel('Hardware-Tier', fontsize=12)
        ax.set_ylabel('P99-Latenz (ms)', fontsize=12)
        ax.set_title(f'{arch.capitalize()}', fontweight='bold', fontsize=14)
        ax.legend(fontsize=11, loc='upper right')
        ax.grid(axis='y', alpha=0.3)

    fig.suptitle('Baseline P99-Latenz je Architektur und Auth-Strategie\n'
                 '(Mittelwert über Wiederholungen, Fehlerbalken = 95%-KI, t-Verteilung)',
                 fontsize=15, fontweight='bold')
    plt.tight_layout()
    path = f"{PLOT_DIR}/sb_baseline_p99_with_ci.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
