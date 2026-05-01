#!/usr/bin/env python3
"""Generate auth_amplification.pdf for fig:auth-amplification.

Reads auth_amplification_factor.csv (produced by script 16), renders a
multi-row broken-axis horizontal bar chart comparing Baseline vs Flash Crowd
ΔAuth P99 across architectures and hardware tiers.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from db_connection import PLOT_DIR

AMP_SEGMENTS = {
    'faas':          [(-1100, 1400)],
    'microservices': [(-1600, 1600), (2400, 20000)],
    'monolith':      [(-100, 900), (2000, 12500)],
}

AMP_CLIP_LO = {'microservices': -1600}

HW_PICKS = {
    'faas':          ['256MB', '1769MB'],
    'microservices': ['S', 'XL'],
    'monolith':      ['S', 'XL'],
}

ARCH_DISPLAY = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}


def _de(n):
    return f'{int(n):,}'.replace(',', '.')


def _draw_break_marks(ax_left, ax_right):
    d = 0.015
    kwargs = dict(transform=ax_left.transAxes, color='black', clip_on=False, linewidth=1)
    ax_left.plot((1 - d, 1 + d), (-d, +d), **kwargs)
    ax_left.plot((1 - d, 1 + d), (1 - d, 1 + d), **kwargs)
    kwargs = dict(transform=ax_right.transAxes, color='black', clip_on=False, linewidth=1)
    ax_right.plot((-d, +d), (-d, +d), **kwargs)
    ax_right.plot((-d, +d), (1 - d, 1 + d), **kwargs)


def _to_hw_label(row):
    if row['architecture'] == 'faas':
        return f"{int(row['ram_in_mb'])}MB"
    return {512: 'S', 1024: 'M', 2048: 'L', 8192: 'XL'}.get(
        int(row['ram_in_mb']), str(int(row['ram_in_mb'])))


def _plot_amp_row(fig, gs_row, arch, amp_fc):
    arch_amp = amp_fc[amp_fc['architecture'] == arch].copy()
    if arch_amp.empty:
        return
    arch_amp['hw'] = arch_amp.apply(_to_hw_label, axis=1)
    arch_amp = arch_amp[arch_amp['hw'].isin(HW_PICKS[arch])]

    auths = ['Cognito', 'Manual', 'Edge']
    labels, bl_vals, fc_vals = [], [], []
    for hw in HW_PICKS[arch]:
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
    widths = [hi - lo for lo, hi in segments]
    sub_gs = gs_row.subgridspec(1, len(segments), width_ratios=widths, wspace=0.05)

    axes = []
    for k in range(len(segments)):
        ax = fig.add_subplot(sub_gs[0, k], sharey=axes[0] if axes else None)
        axes.append(ax)

    y = np.arange(len(labels))
    height = 0.35
    clip_lo = AMP_CLIP_LO.get(arch)

    for ax, (lo, hi) in zip(axes, segments):
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

    for k in range(len(axes) - 1):
        axes[k].spines['right'].set_visible(False)
        axes[k + 1].spines['left'].set_visible(False)
        axes[k + 1].tick_params(left=False, labelleft=False)
        _draw_break_marks(axes[k], axes[k + 1])

    axes[0].set_yticks(y)
    axes[0].set_yticklabels(labels, fontsize=9)
    axes[0].invert_yaxis()
    if arch == 'faas':
        axes[-1].legend(fontsize=9, loc='upper right',
                        bbox_to_anchor=(1.0, 1.22),
                        ncol=2, framealpha=0.9)

    axes[0].set_title(ARCH_DISPLAY[arch], fontweight='bold', fontsize=12, loc='left')

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
            axes[0].set_xlabel(label, fontsize=9,
                               x=0.5 * sum(widths) / widths[0])


def main():
    amp_df = pd.read_csv(f"{PLOT_DIR}/auth_amplification_factor.csv")
    amp_fc = amp_df[amp_df['load_phase'] == 'Flash Crowd'].copy()
    amp_fc = amp_fc[amp_fc['ram_in_mb'] != 1796]

    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(3, 1, hspace=0.7)

    for i, arch in enumerate(['faas', 'microservices', 'monolith']):
        _plot_amp_row(fig, gs[i, 0], arch, amp_fc)

    fig.suptitle('Auth-Overhead: Baseline vs. Flash Crowd\n'
                 r'($\Delta_{\text{Auth}}$ P99 in ms, kleinste und größte '
                 'Hardware-Stufe; Achsenbrüche trennen Hauptcluster von Extremwerten)',
                 fontsize=13, fontweight='bold', y=0.995)
    plt.tight_layout(rect=(0, 0.01, 1, 0.95))
    path = f"{PLOT_DIR}/auth_amplification.pdf"
    fig.savefig(path, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
