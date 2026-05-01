#!/usr/bin/env python3
"""Generate bootstrap_ci_forest_plot_faas.pdf for fig:sb-forest-faas.

Reads bootstrap_ci_delta_auth.csv (produced by script 34), pools per
(hw, auth_label) via inverse-variance weighting with t-distribution,
and renders a broken-axis forest plot for the FaaS architecture.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from db_connection import PLOT_DIR, AUTH_COLORS_DETAILED

ALPHA = 0.05
ARCH = 'faas'
X_LEFT_LO, X_LEFT_HI = -50, 400
X_RIGHT_LO, X_RIGHT_HI = 1100, 3100
WR_LEFT = 3.0


def _pool_group(grp):
    deltas = grp['boot_mean'].to_numpy(dtype=float)
    ses = grp['boot_std'].to_numpy(dtype=float)
    valid = ses > 0
    k_valid = int(valid.sum())
    if k_valid >= 2:
        w = 1.0 / (ses[valid] ** 2)
        pooled_mean = float(np.sum(w * deltas[valid]) / np.sum(w))
        pooled_se = float(np.sqrt(1.0 / np.sum(w)))
        t_crit = float(sp_stats.t.ppf(1 - ALPHA / 2, df=k_valid - 1))
        ci_low = pooled_mean - t_crit * pooled_se
        ci_high = pooled_mean + t_crit * pooled_se
    elif k_valid == 1:
        idx = np.flatnonzero(valid)[0]
        pooled_mean = float(deltas[idx])
        ci_low = float(grp['ci_low'].to_numpy()[idx])
        ci_high = float(grp['ci_high'].to_numpy()[idx])
    else:
        pooled_mean = float(np.mean(deltas))
        ci_low = ci_high = pooled_mean
    return pd.Series({'pooled_mean': pooled_mean, 'ci_low': ci_low, 'ci_high': ci_high})


def _draw_break_marks(ax_left, ax_right):
    d = 0.015
    kwargs = dict(transform=ax_left.transAxes, color='black', clip_on=False, linewidth=1)
    ax_left.plot((1 - d, 1 + d), (-d, +d), **kwargs)
    ax_left.plot((1 - d, 1 + d), (1 - d, 1 + d), **kwargs)
    kwargs = dict(transform=ax_right.transAxes, color='black', clip_on=False, linewidth=1)
    ax_right.plot((-d, +d), (-d, +d), **kwargs)
    ax_right.plot((-d, +d), (1 - d, 1 + d), **kwargs)


def main():
    df = pd.read_csv(f"{PLOT_DIR}/bootstrap_ci_delta_auth.csv")
    p99 = df[(df['percentile'] == 'P99') & (df['architecture'] == ARCH)].copy()

    rows = []
    for keys, grp in p99.groupby(['hw', 'auth_label']):
        pooled = _pool_group(grp)
        rows.append({'hw': keys[0], 'auth_label': keys[1], **pooled.to_dict()})
    summary = pd.DataFrame(rows)
    if summary.empty:
        print('No FaaS data')
        return

    n_rows = len(summary)
    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=(12, max(4, n_rows * 0.55)),
        sharey=True,
        gridspec_kw={'width_ratios': [WR_LEFT, 1.0], 'wspace': 0.04},
    )

    y_labels = []
    for i, (_, r) in enumerate(summary.iterrows()):
        y_labels.append(f"{r['hw']} / {r['auth_label']}")
        color = AUTH_COLORS_DETAILED.get(r['auth_label'], '#999')
        is_sig = r['ci_low'] > 0 or r['ci_high'] < 0
        for ax in (ax_left, ax_right):
            ax.errorbar(
                r['pooled_mean'], i,
                xerr=[[r['pooled_mean'] - r['ci_low']],
                      [r['ci_high'] - r['pooled_mean']]],
                fmt='o', color=color, capsize=5, markersize=8, linewidth=2,
                alpha=1.0 if is_sig else 0.5,
            )

    for ax, (lo, hi) in zip((ax_left, ax_right),
                             ((X_LEFT_LO, X_LEFT_HI), (X_RIGHT_LO, X_RIGHT_HI))):
        ax.set_xlim(lo, hi)
        ax.grid(axis='x', alpha=0.3)
        ax.tick_params(axis='x', labelsize=9)

    ax_left.axvline(x=0, color='black', linestyle='--', linewidth=0.8, alpha=0.5)
    ax_left.set_yticks(np.arange(n_rows))
    ax_left.set_yticklabels(y_labels, fontsize=9)
    ax_left.invert_yaxis()

    ax_left.spines['right'].set_visible(False)
    ax_right.spines['left'].set_visible(False)
    ax_right.tick_params(left=False)

    _draw_break_marks(ax_left, ax_right)

    def de_num(n):
        return f'{n:,}'.replace(',', '.')

    fig.suptitle('95%-KI: Authentifizierungs-Overhead (FaaS)',
                 fontweight='bold', fontsize=12, y=0.995)
    fig.supxlabel(
        f'ΔAuth P99 (ms) — Auth-Only, Baseline  '
        f'(Achsenbruch zwischen {de_num(X_LEFT_HI)} ms und {de_num(X_RIGHT_LO)} ms)',
        fontsize=10,
    )

    plt.tight_layout(rect=(0, 0.03, 1, 0.98))
    path = f"{PLOT_DIR}/bootstrap_ci_forest_plot_faas.pdf"
    fig.savefig(path, bbox_inches='tight', dpi=300)
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
