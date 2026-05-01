#!/usr/bin/env python3
"""
45 — Broken-Axis Re-Plot of Forest-Plots (6.2–6.4) and Amplification (6.54)

Regenerates four figures from the CSVs already produced by scripts 34 and 16.
Uses a horizontal broken axis (left: main cluster, right: extreme values) so
that the zero reference line (for the forest plots) and negative values (for
the amplification plot) stay representable while extreme outliers do not
compress the main cluster into a thin strip.

Reads:
  - bootstrap_ci_delta_auth.csv         (script 34)
  - auth_amplification_factor.csv       (script 16)

Writes (overwrites existing PDFs referenced by evaluation.tex):
  - bootstrap_ci_forest_plot_faas.pdf
  - bootstrap_ci_forest_plot_microservices.pdf
  - bootstrap_ci_forest_plot_monolith.pdf
  - auth_amplification.pdf

Does not touch the DB.
"""

import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats as sp_stats

sys.path.insert(0, '.')
from db_connection import PLOT_DIR, AUTH_COLORS_DETAILED, AUTH_COLORS

ALPHA = 0.05


def _pool_group(grp: pd.DataFrame) -> pd.Series:
    """Inverse-variance pooling across within-experiment Welch estimates.

    Uses Student-t with df = k - 1 (k = number of contributing pairs), matching
    the small-sample rule from the evaluation chapter (eq:t-ci). Mirrors the
    pooling in 34_bootstrap_ci_delta_auth.py so the replotted forest plots stay
    numerically consistent with bootstrap_ci_delta_auth.csv.
    """
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
    return pd.Series({
        'pooled_mean': pooled_mean,
        'ci_low': ci_low,
        'ci_high': ci_high,
    })


def _draw_break_marks(ax_left, ax_right):
    """Draw the classic // break marks on the shared edge of two subplots."""
    d = 0.015
    kwargs = dict(transform=ax_left.transAxes, color='black', clip_on=False, linewidth=1)
    ax_left.plot((1 - d, 1 + d), (-d, +d), **kwargs)
    ax_left.plot((1 - d, 1 + d), (1 - d, 1 + d), **kwargs)
    kwargs = dict(transform=ax_right.transAxes, color='black', clip_on=False, linewidth=1)
    ax_right.plot((-d, +d), (-d, +d), **kwargs)
    ax_right.plot((-d, +d), (1 - d, 1 + d), **kwargs)


# ─────────────────────────────────────────────────────────────
# Forest plots (figures 6.2–6.4)
# ─────────────────────────────────────────────────────────────

# (x_min_left, x_max_left, x_min_right, x_max_right, width_ratio_left)
# Chosen so that > 80 % of entries fall into the left (main) panel.
FOREST_AXIS = {
    'faas':          (-50,   400,  1100,  3100,  3.0),
    'microservices': (-50,   800,  2000, 26000,  3.0),
    'monolith':      (-50,   700,  1600,  8100,  3.0),
}

ARCH_DISPLAY = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}


def plot_forest(arch: str, summary: pd.DataFrame) -> None:
    arch_summary = summary[summary['architecture'] == arch]
    if arch_summary.empty:
        return

    x_left_lo, x_left_hi, x_right_lo, x_right_hi, wr_left = FOREST_AXIS[arch]
    n_rows = len(arch_summary)

    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=(12, max(4, n_rows * 0.55)),
        sharey=True,
        gridspec_kw={'width_ratios': [wr_left, 1.0], 'wspace': 0.04},
    )

    y_labels = []
    for i, (_, r) in enumerate(arch_summary.iterrows()):
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
                             ((x_left_lo, x_left_hi), (x_right_lo, x_right_hi))):
        ax.set_xlim(lo, hi)
        ax.grid(axis='x', alpha=0.3)
        ax.tick_params(axis='x', labelsize=9)

    ax_left.axvline(x=0, color='black', linestyle='--', linewidth=0.8, alpha=0.5)
    ax_left.set_yticks(np.arange(n_rows))
    ax_left.set_yticklabels(y_labels, fontsize=9)
    ax_left.invert_yaxis()

    # Hide the inner spines and the right-side y-tick column to build the break
    ax_left.spines['right'].set_visible(False)
    ax_right.spines['left'].set_visible(False)
    ax_right.tick_params(left=False)

    _draw_break_marks(ax_left, ax_right)

    def de_num(n: int) -> str:
        return f'{n:,}'.replace(',', '.')

    fig.suptitle(f'95%-KI: Authentifizierungs-Overhead ({ARCH_DISPLAY[arch]})',
                 fontweight='bold', fontsize=12, y=0.995)
    fig.supxlabel(
        f'ΔAuth P99 (ms) — Auth-Only, Baseline  '
        f'(Achsenbruch zwischen {de_num(x_left_hi)} ms und {de_num(x_right_lo)} ms)',
        fontsize=10,
    )

    plt.tight_layout(rect=(0, 0.03, 1, 0.98))
    path = f"{PLOT_DIR}/bootstrap_ci_forest_plot_{arch}.pdf"
    fig.savefig(path, bbox_inches='tight', dpi=300)
    print(f"Saved: {path}")
    plt.close()


def generate_forest_plots() -> None:
    df = pd.read_csv(f"{PLOT_DIR}/bootstrap_ci_delta_auth.csv")
    p99 = df[df['percentile'] == 'P99'].copy()

    rows = []
    for keys, grp in p99.groupby(['architecture', 'hw', 'auth_label']):
        pooled = _pool_group(grp)
        rows.append({
            'architecture': keys[0],
            'hw': keys[1],
            'auth_label': keys[2],
            **pooled.to_dict(),
        })
    summary = pd.DataFrame(rows)

    for arch in ['faas', 'microservices', 'monolith']:
        plot_forest(arch, summary)


# ─────────────────────────────────────────────────────────────
# Amplification plot (figure 6.54)
# ─────────────────────────────────────────────────────────────

# Per-architecture horizontal segmentation. Each architecture renders as one row of
# linked panels. A list of (x_lo, x_hi) pairs; len == 1 means no break, 2 means one
# break, 3 means two breaks (used for MS where values span -13 k … +19 k).
AMP_SEGMENTS = {
    'faas':          [(-1100,  1400)],
    'microservices': [(-1600, 1600), (2400, 20000)],
    'monolith':      [(-100,   900), (2000, 12500)],
}

# Values below these thresholds are replaced by a clipped-bar annotation in the
# leftmost panel, because a dedicated negative-extreme panel would waste horizontal
# space and the data point mostly reflects survivorship-bias-driven latency collapse
# (see Tabelle 6.5 im Evaluierungskapitel).
AMP_CLIP_LO = {'microservices': -1600}


def _de(n) -> str:
    return f'{int(n):,}'.replace(',', '.')


def _plot_amp_row(fig, gs_row, arch, amp_fc, hw_picks, to_hw_label):
    """Render one architecture as a row of linked panels (axes share y)."""
    arch_amp = amp_fc[amp_fc['architecture'] == arch].copy()
    if arch_amp.empty:
        return
    arch_amp['hw'] = arch_amp.apply(to_hw_label, axis=1)
    arch_amp = arch_amp[arch_amp['hw'].isin(hw_picks[arch])]

    auths = ['Cognito', 'Manual', 'Edge']
    labels, bl_vals, fc_vals = [], [], []
    for hw in hw_picks[arch]:
        for auth in auths:
            m = arch_amp[(arch_amp['hw'] == hw) & (arch_amp['auth'] == auth)]
            if not m.empty:
                r = m.iloc[0]
                labels.append(f'{auth} ({hw})')
                bl_vals.append(r['baseline_delta_p99'])
                fc_vals.append(r['load_delta_p99'])
    if not labels:
        return

    segments = AMP_SEGMENTS[arch]
    # Width ratio proportional to segment span.
    widths = [hi - lo for lo, hi in segments]
    sub_gs = gs_row.subgridspec(1, len(segments), width_ratios=widths, wspace=0.05)

    axes = []
    for k in range(len(segments)):
        ax = fig.add_subplot(sub_gs[0, k], sharey=axes[0] if axes else None)
        axes.append(ax)

    y = np.arange(len(labels))
    height = 0.35

    clip_lo = AMP_CLIP_LO.get(arch)

    def _clip(vals, lo, hi):
        # Bars are drawn from 0 to val. Clip the visible part to the panel range so
        # that out-of-range values don't render as oversized rectangles spanning the
        # axis. A bar with start==end is not rendered.
        return [max(lo, min(hi, v)) if (lo <= 0 <= hi) or (lo <= v <= hi) else
                (hi if v > hi else lo) if (lo <= 0 <= hi)
                else None
                for v in vals]

    for ax, (lo, hi) in zip(axes, segments):
        # For a panel that contains 0, clipping is simple: just clamp to [lo, hi].
        # For a panel that does NOT contain 0, draw only bars whose value lies inside
        # the panel range (others would visually start at the left edge instead of 0).
        def _vis(vals):
            out = []
            for v in vals:
                if lo <= 0 <= hi:
                    out.append(max(lo, min(hi, v)))
                else:
                    out.append(v if lo <= v <= hi else 0)
            return out

        ax.barh(y - height / 2, _vis(bl_vals), height, color='#3498db', alpha=0.85,
                label='Baseline' if ax is axes[0] else None)
        ax.barh(y + height / 2, _vis(fc_vals), height, color='#e74c3c', alpha=0.85,
                label='Flash Crowd' if ax is axes[0] else None)
        for vals, color in [(bl_vals, '#2980b9'), (fc_vals, '#c0392b')]:
            for yi, v in zip(y, vals):
                if not (lo <= v <= hi):
                    # Annotate only in the leftmost panel when a clip threshold applies
                    if clip_lo is not None and v < clip_lo and ax is axes[0]:
                        pad = 0.015 * (hi - lo)
                        y_off = -height / 2 if color == '#2980b9' else height / 2
                        ax.annotate(
                            f'{v:+.0f} ms →',
                            xy=(lo, yi + y_off), xytext=(lo + pad, yi + y_off),
                            va='center', ha='left', fontsize=8, color=color,
                            arrowprops=dict(arrowstyle='-[', color=color, lw=1),
                        )
                    continue
                pad = 0.015 * (hi - lo)
                x_pos = v + pad if v >= 0 else v - pad
                ha = 'left' if v >= 0 else 'right'
                y_off = -height / 2 if color == '#2980b9' else height / 2
                ax.text(x_pos, yi + y_off, f'{v:+.0f} ms', va='center', ha=ha,
                        fontsize=8, color=color)
        ax.axvline(x=0, color='black', linewidth=0.5)
        ax.grid(axis='x', alpha=0.3)
        ax.set_xlim(lo, hi)

    # Draw break marks between adjacent panels
    for k in range(len(axes) - 1):
        axes[k].spines['right'].set_visible(False)
        axes[k + 1].spines['left'].set_visible(False)
        axes[k + 1].tick_params(left=False, labelleft=False)
        _draw_break_marks(axes[k], axes[k + 1])

    axes[0].set_yticks(y)
    axes[0].set_yticklabels(labels, fontsize=9)
    axes[0].invert_yaxis()
    # Legend on the first row only (FaaS), anchored above the plotting area so it
    # does not overlap any bar. MS/Mono inherit the same color mapping.
    if arch == 'faas':
        axes[-1].legend(fontsize=9, loc='upper right',
                        bbox_to_anchor=(1.0, 1.22),
                        ncol=2, framealpha=0.9)

    arch_display = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}
    axes[0].set_title(arch_display[arch], fontweight='bold', fontsize=12, loc='left')

    # X label on the middle (or only) panel, with break annotation if applicable
    if len(segments) == 1:
        axes[0].set_xlabel(r'$\Delta_{\text{Auth}}$ P99 (ms)', fontsize=10)
    else:
        breaks = [f'{_de(segments[k][1])} und {_de(segments[k + 1][0])} ms'
                  for k in range(len(segments) - 1)]
        keyword = 'Achsenbrüche' if len(breaks) > 1 else 'Achsenbruch'
        label = (r'$\Delta_{\text{Auth}}$ P99 (ms) — '
                 f'{keyword} zwischen ' + '; '.join(breaks))
        if len(axes) == 3:
            axes[1].set_xlabel(label, fontsize=9)
        else:
            # Use supxlabel-style: place on the axis whose center is closest to overall center
            axes[0].set_xlabel(label, fontsize=9,
                               x=0.5 * sum(widths) / widths[0])


def generate_amplification_plot() -> None:
    amp_df = pd.read_csv(f"{PLOT_DIR}/auth_amplification_factor.csv")
    amp_fc = amp_df[amp_df['load_phase'] == 'Flash Crowd'].copy()
    amp_fc = amp_fc[amp_fc['ram_in_mb'] != 1796]

    def to_hw_label(row):
        if row['architecture'] == 'faas':
            return f"{int(row['ram_in_mb'])}MB"
        return {512: 'S', 1024: 'M', 2048: 'L', 8192: 'XL'}.get(
            int(row['ram_in_mb']), str(int(row['ram_in_mb'])))

    hw_picks = {
        'faas':          ['256MB', '1769MB'],
        'microservices': ['S', 'XL'],
        'monolith':      ['S', 'XL'],
    }

    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 1, hspace=0.7)

    for i, arch in enumerate(['faas', 'microservices', 'monolith']):
        _plot_amp_row(fig, gs[i, 0], arch, amp_fc, hw_picks, to_hw_label)

    fig.suptitle('Auth-Overhead: Baseline vs. Flash Crowd\n'
                 r'($\Delta_{\text{Auth}}$ P99 in ms, kleinste und größte '
                 'Hardware-Stufe; Achsenbrüche trennen Hauptcluster von Extremwerten)',
                 fontsize=13, fontweight='bold', y=0.995)
    plt.tight_layout(rect=(0, 0.01, 1, 0.95))
    path = f"{PLOT_DIR}/auth_amplification.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


def main() -> None:
    print("=" * 70)
    print("45 — Broken-Axis Re-Plot (Forest 6.2-6.4 + Amplification 6.54)")
    print("=" * 70)
    generate_forest_plots()
    generate_amplification_plot()


if __name__ == '__main__':
    main()
