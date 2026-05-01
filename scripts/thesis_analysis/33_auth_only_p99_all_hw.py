#!/usr/bin/env python3
"""
33 -- Auth-Only P99 Across All HW Tiers (Combined Plots)
Generates two thesis-referenced plots:
  1. auth_only_p99_all_hw_shared.pdf — absolute P99 latency (grouped bars)
  2. auth_only_delta_p99_all_hw.pdf — ΔAuth P99 (auth minus none baseline)

Now differentiates:
  - Manual (bcrypt) vs Manual (argon2id) as separate bar groups
  - CloudFront (+CF) variants where data exists
"""

import sys
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed, AUTH_COLORS_DETAILED, HW_TIERS_ALL)

PROTECTED_ENDPOINTS_FAAS = (
    '/frontend/setUser', '/frontend/addCartItem',
    '/frontend/cart', '/frontend/checkout',
)
PROTECTED_ENDPOINTS_CONTAINER = (
    '/setUser', '/addCartItem', '/cart', '/checkout',
)


def get_protected_endpoints(arch):
    return PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER


def compute_auth_only_p99(arch, ram, cpu):
    """Compute auth-only P99 per auth_strategy/algo/CF at a given hardware config."""
    protected = get_protected_endpoints(arch)
    eps_sql = ','.join(f"'{e}'" for e in protected)
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

    return query_df(f"""
        SELECT
            e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            COALESCE(e.with_cloudfront, false) AS with_cf,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = '{arch}'
          AND e.ram_in_mb = {ram}
          {cpu_clause}
          AND r.phase_name = 'Baseline'
          AND r.endpoint IN ({eps_sql})
        GROUP BY e.auth_strategy, algo, with_cf
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)


def main():
    print("=" * 70)
    print("33 -- AUTH-ONLY P99 ACROSS ALL HW TIERS — FULL DIFFERENTIATION")
    print("=" * 70)

    # Collect data for all configs
    all_rows = []
    for arch in ['faas', 'microservices', 'monolith']:
        for ram, cpu, hw_label in HW_TIERS_ALL[arch]:
            df = compute_auth_only_p99(arch, ram, cpu)
            if df.empty:
                continue
            df['p99'] = df['p99'].astype(float)

            # Find none baselines per CF status
            none_p99_map = {}
            for _, row in df.iterrows():
                if row['auth_strategy'] == 'none':
                    none_p99_map[bool(row['with_cf'])] = row['p99']

            # Default none baseline (prefer non-CF)
            default_none = none_p99_map.get(False, none_p99_map.get(True))

            for _, row in df.iterrows():
                cf_bool = bool(row['with_cf'])
                none_p99 = none_p99_map.get(cf_bool, default_none)
                delta = row['p99'] - none_p99 if none_p99 is not None else None

                label = auth_label_detailed(
                    row['auth_strategy'],
                    row['algo'] if row['auth_strategy'] == 'service-integrated-manual' else None,
                    cf_bool)

                all_rows.append({
                    'architecture': arch,
                    'hw': hw_label,
                    'ram_in_mb': ram,
                    'auth_strategy': row['auth_strategy'],
                    'auth_label': label,
                    'algo': row['algo'],
                    'with_cf': cf_bool,
                    'p99': row['p99'],
                    'none_p99': none_p99,
                    'delta_p99': delta,
                    'n_success': int(row['n_success']),
                })

    result_df = pd.DataFrame(all_rows)
    if result_df.empty:
        print("No data found.")
        return

    print(f"\nCollected {len(result_df)} data points")

    # Determine auth label order for consistent plotting
    auth_label_order = [
        'None', 'None+CF', 'Cognito', 'Cognito+CF',
        'Manual (bcrypt)', 'Manual (bcrypt)+CF',
        'Manual (argon2id)', 'Manual (argon2id)+CF',
        'Edge',  # Edge always uses CF, so no separate "Edge+CF"
    ]

    # ── Shared helpers for broken-axis plots ──
    import matplotlib.gridspec as gridspec
    from matplotlib.patches import FancyBboxPatch

    def draw_break_lines(ax_top, ax_bot):
        """Draw solid horizontal break lines (like Abbildung 4.2 reference style)."""
        # Solid line at bottom of upper panel
        ax_top.axhline(y=ax_top.get_ylim()[0], color='black', linewidth=1.5,
                        clip_on=False, zorder=10)
        # Solid line at top of lower panel
        ax_bot.axhline(y=ax_bot.get_ylim()[1], color='black', linewidth=1.5,
                        clip_on=False, zorder=10)

    def smart_label_bars(ax, bars_with_vals, break_lo, is_top_panel, fmt='{:.0f}',
                         fontsize=7, min_spacing_pts=10):
        """Place value labels on bars with overlap avoidance.

        Strategy: label ALL bars, but use collision detection to stagger
        overlapping labels upward with increasing offsets. Labels are placed
        from tallest to shortest bar, so the tallest always gets the closest
        position.
        """
        if not bars_with_vals:
            return

        # Collect candidate labels in correct panel
        candidates = []
        for bar, val in bars_with_vals:
            if val == 0:
                continue
            if is_top_panel and val <= break_lo:
                continue
            if not is_top_panel and val > break_lo:
                continue

            x_center = bar.get_x() + bar.get_width() / 2
            y_base = abs(bar.get_height()) if val >= 0 else bar.get_height()
            text = fmt.format(val)
            candidates.append({'x': x_center, 'y': y_base, 'text': text,
                               'val': val, 'bar': bar})

        if not candidates:
            return

        # Convert min_spacing from points to data coords
        fig = ax.get_figure()
        renderer = fig.canvas.get_renderer()
        bbox = ax.get_window_extent(renderer)
        y_range = ax.get_ylim()[1] - ax.get_ylim()[0]
        pts_per_data = bbox.height / y_range if y_range > 0 else 1
        min_spacing_data = min_spacing_pts / pts_per_data if pts_per_data > 0 else 0
        base_offset = y_range * 0.018

        # Sort: place tallest bars first (they get the closest label position)
        pos_candidates = [c for c in candidates if c['val'] >= 0]
        neg_candidates = [c for c in candidates if c['val'] < 0]

        # --- Positive values: label above bars ---
        pos_candidates.sort(key=lambda c: -c['y'])  # tallest first
        placed = []  # (x, y_label) of already placed labels

        for c in pos_candidates:
            y_label = c['y'] + base_offset

            # Resolve collisions with already-placed labels
            max_iterations = 15
            for _ in range(max_iterations):
                collision = False
                for px, py in placed:
                    if abs(c['x'] - px) < 0.12:  # close enough to potentially overlap
                        if abs(y_label - py) < min_spacing_data:
                            y_label = py + min_spacing_data
                            collision = True
                if not collision:
                    break

            # Clip to axis limits
            y_max = ax.get_ylim()[1]
            if y_label > y_max * 0.95:
                y_label = y_max * 0.95

            placed.append((c['x'], y_label))
            ax.text(c['x'], y_label, c['text'], ha='center', va='bottom',
                    fontsize=fontsize, zorder=5)

        # --- Negative values: label below bars ---
        for c in neg_candidates:
            y_label = c['y'] - base_offset
            ax.text(c['x'], y_label, c['text'], ha='center', va='top',
                    fontsize=fontsize, zorder=5)

    # ── PLOT 1: Absolute P99 — per-architecture with broken y-axis ──
    arch_display = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}

    for arch in ['faas', 'microservices', 'monolith']:
        arch_data = result_df[result_df['architecture'] == arch]
        if arch_data.empty:
            continue

        hw_labels = [t[2] for t in HW_TIERS_ALL[arch]]
        hw_labels = [hw for hw in hw_labels if not arch_data[arch_data['hw'] == hw].empty]
        present_labels = [l for l in auth_label_order if l in arch_data['auth_label'].values]
        x = np.arange(len(hw_labels))
        n_auth = len(present_labels)
        if n_auth == 0:
            continue
        width = 0.8 / n_auth

        arch_p99 = arch_data['p99'].values
        needs_break = max(arch_p99) > 2500

        if needs_break:
            P1_BREAK_LO = 2000
            P1_BREAK_HI = 3000
            p1_y_max = max(arch_p99) * 1.12
            p1_height_ratio = 0.25

            fig1 = plt.figure(figsize=(10, 8))
            gs = gridspec.GridSpecFromSubplotSpec(
                2, 1, subplot_spec=gridspec.GridSpec(1, 1, figure=fig1)[0],
                height_ratios=[p1_height_ratio, 1], hspace=0.06)
            ax_top = fig1.add_subplot(gs[0])
            ax_bot = fig1.add_subplot(gs[1])

            all_bars_per_hw = {hw: [] for hw in hw_labels}
            missing_slots_p1 = []

            for ax in (ax_top, ax_bot):
                for i, auth_l in enumerate(present_labels):
                    vals = []
                    present = []
                    for hw in hw_labels:
                        match = arch_data[(arch_data['hw'] == hw) & (arch_data['auth_label'] == auth_l)]
                        if not match.empty:
                            vals.append(match.iloc[0]['p99'])
                            present.append(True)
                        else:
                            vals.append(0)
                            present.append(False)
                    offset = (i - n_auth / 2 + 0.5) * width
                    color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
                    bars = ax.bar(x + offset, vals, width, label=auth_l, color=color, alpha=0.85)
                    if ax is ax_bot:
                        for j, (bar, val) in enumerate(zip(bars, vals)):
                            all_bars_per_hw[hw_labels[j]].append((bar, val))
                        for j, p in enumerate(present):
                            if not p:
                                missing_slots_p1.append(x[j] + offset)
                ax.set_xticks(x)
                ax.grid(axis='y', alpha=0.3)

            ax_top.set_ylim(P1_BREAK_HI, p1_y_max)
            ax_bot.set_ylim(0, P1_BREAK_LO)
            ax_top.spines['bottom'].set_visible(False)
            ax_bot.spines['top'].set_visible(False)
            ax_top.tick_params(bottom=False, labelbottom=False)
            draw_break_lines(ax_top, ax_bot)

            p1_top_ticks = [P1_BREAK_HI]
            tick = 5000
            while tick < p1_y_max:
                p1_top_ticks.append(tick)
                tick += 5000
            ax_top.set_yticks(p1_top_ticks)
            ax_top.set_yticklabels([f'{int(t):,}'.replace(',', '.') for t in p1_top_ticks],
                                   fontsize=10)

            ax_bot.set_xticklabels(hw_labels, fontsize=11)
            ax_bot.set_xlabel('Hardware-Tier', fontsize=12)
            ax_bot.set_ylabel('Auth-Only P99 Latenz (ms)', fontsize=12)
            ax_bot.tick_params(labelsize=10)

            for hw in hw_labels:
                bv = all_bars_per_hw[hw]
                smart_label_bars(ax_bot, bv, P1_BREAK_LO, is_top_panel=False, fontsize=8)

            for i, auth_l in enumerate(present_labels):
                vals = []
                for hw in hw_labels:
                    match = arch_data[(arch_data['hw'] == hw) & (arch_data['auth_label'] == auth_l)]
                    vals.append(match.iloc[0]['p99'] if not match.empty else 0)
                offset = (i - n_auth / 2 + 0.5) * width
                for j, val in enumerate(vals):
                    if val > P1_BREAK_LO:
                        x_pos = x[j] + offset
                        ax_top.text(x_pos, val + (p1_y_max - P1_BREAK_HI) * 0.02,
                                    f'{val:.0f}', ha='center', va='bottom',
                                    fontsize=8, fontweight='bold')

            # Mark missing data points in lower panel
            for xm in missing_slots_p1:
                ax_bot.text(xm, P1_BREAK_LO * 0.03, '–',
                            ha='center', va='bottom', fontsize=9,
                            color='#999', fontweight='bold')

            ax_top.legend(fontsize=9, loc='upper left')
            ax_top.set_title(f'{arch_display[arch]}: Auth-Only P99 Latenz',
                             fontweight='bold', fontsize=13)
        else:
            fig1, ax_bot = plt.subplots(figsize=(10, 7))
            missing_slots = []
            for i, auth_l in enumerate(present_labels):
                vals = []
                present = []
                for hw in hw_labels:
                    match = arch_data[(arch_data['hw'] == hw) & (arch_data['auth_label'] == auth_l)]
                    if not match.empty:
                        vals.append(match.iloc[0]['p99'])
                        present.append(True)
                    else:
                        vals.append(0)
                        present.append(False)
                offset = (i - n_auth / 2 + 0.5) * width
                color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
                bars = ax_bot.bar(x + offset, vals, width, label=auth_l, color=color, alpha=0.85)
                for bar, val in zip(bars, vals):
                    if val > 0:
                        ax_bot.text(bar.get_x() + bar.get_width() / 2,
                                    bar.get_height() + 2,
                                    f'{val:.0f}', ha='center', va='bottom', fontsize=8)
                for j, p in enumerate(present):
                    if not p:
                        missing_slots.append(x[j] + offset)
            # Mark missing data points
            y_lo, y_hi = ax_bot.get_ylim()
            for xm in missing_slots:
                ax_bot.text(xm, y_hi * 0.02, '–',
                            ha='center', va='bottom', fontsize=9,
                            color='#999', fontweight='bold')
            ax_bot.set_xticks(x)
            ax_bot.set_xticklabels(hw_labels, fontsize=11)
            ax_bot.set_xlabel('Hardware-Tier', fontsize=12)
            ax_bot.set_ylabel('Auth-Only P99 Latenz (ms)', fontsize=12)
            ax_bot.set_title(f'{arch_display[arch]}: Auth-Only P99 Latenz',
                             fontweight='bold', fontsize=13)
            ax_bot.legend(fontsize=9, loc='upper right')
            ax_bot.grid(axis='y', alpha=0.3)
            ax_bot.tick_params(labelsize=10)

        plt.tight_layout()
        path = f"{PLOT_DIR}/auth_only_p99_all_hw_{arch}.pdf"
        fig1.savefig(path, dpi=300, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close(fig1)

    # ── PLOT 2: Delta P99 — per-architecture with broken y-axis ──
    delta_df = result_df[(result_df['auth_strategy'] != 'none') &
                         (~result_df['auth_label'].str.startswith('None'))].copy()
    delta_df = delta_df.dropna(subset=['delta_p99'])

    for arch in ['faas', 'microservices', 'monolith']:
        arch_data = delta_df[delta_df['architecture'] == arch]
        if arch_data.empty:
            continue

        hw_labels = [t[2] for t in HW_TIERS_ALL[arch]]
        hw_labels = [hw for hw in hw_labels if not arch_data[arch_data['hw'] == hw].empty]
        present_labels = [l for l in auth_label_order
                          if l in arch_data['auth_label'].values and not l.startswith('None')]
        x = np.arange(len(hw_labels))
        n_auth = len(present_labels)
        if n_auth == 0:
            continue
        width = 0.8 / n_auth

        arch_deltas = arch_data['delta_p99'].values
        needs_break = max(arch_deltas) > 2500

        if needs_break:
            BREAK_LO = 2000
            BREAK_HI = 3000
            y_max_upper = max(arch_deltas) * 1.12
            y_min_lower = min(min(arch_deltas) * 1.1, -100)
            height_ratio = 0.25

            fig = plt.figure(figsize=(10, 8))
            gs = gridspec.GridSpecFromSubplotSpec(
                2, 1, subplot_spec=gridspec.GridSpec(1, 1, figure=fig)[0],
                height_ratios=[height_ratio, 1], hspace=0.06)
            ax_top = fig.add_subplot(gs[0])
            ax_bot = fig.add_subplot(gs[1])

            all_bars_per_hw = {hw: [] for hw in hw_labels}
            missing_slots_d = []

            for ax in (ax_top, ax_bot):
                for i, auth_l in enumerate(present_labels):
                    vals = []
                    present = []
                    for hw in hw_labels:
                        match = arch_data[(arch_data['hw'] == hw) & (arch_data['auth_label'] == auth_l)]
                        if not match.empty:
                            vals.append(match.iloc[0]['delta_p99'])
                            present.append(True)
                        else:
                            vals.append(0)
                            present.append(False)
                    offset = (i - n_auth / 2 + 0.5) * width
                    color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
                    bars = ax.bar(x + offset, vals, width, label=auth_l, color=color, alpha=0.85)
                    if ax is ax_bot:
                        for j, (bar, val) in enumerate(zip(bars, vals)):
                            all_bars_per_hw[hw_labels[j]].append((bar, val))
                        for j, p in enumerate(present):
                            if not p:
                                missing_slots_d.append(x[j] + offset)
                ax.axhline(y=0, color='black', linewidth=0.5, linestyle='--')
                ax.set_xticks(x)
                ax.grid(axis='y', alpha=0.3)

            ax_top.set_ylim(BREAK_HI, y_max_upper)
            ax_bot.set_ylim(y_min_lower, BREAK_LO)
            ax_top.spines['bottom'].set_visible(False)
            ax_bot.spines['top'].set_visible(False)
            ax_top.tick_params(bottom=False, labelbottom=False)
            draw_break_lines(ax_top, ax_bot)

            d_top_ticks = [BREAK_HI]
            tick = 5000
            while tick < y_max_upper:
                d_top_ticks.append(tick)
                tick += 5000
            ax_top.set_yticks(d_top_ticks)
            ax_top.set_yticklabels([f'{int(t):,}'.replace(',', '.') for t in d_top_ticks],
                                   fontsize=10)

            ax_bot.set_xticklabels(hw_labels, fontsize=11)
            ax_bot.set_xlabel('Hardware-Tier', fontsize=12)
            ax_bot.set_ylabel('$\\Delta_{Auth}$ P99 (ms)', fontsize=12)
            ax_bot.tick_params(labelsize=10)

            for hw in hw_labels:
                bv = all_bars_per_hw[hw]
                smart_label_bars(ax_bot, bv, BREAK_LO, is_top_panel=False,
                                 fmt='{:+.0f}', fontsize=8)

            for i, auth_l in enumerate(present_labels):
                vals = []
                for hw in hw_labels:
                    match = arch_data[(arch_data['hw'] == hw) & (arch_data['auth_label'] == auth_l)]
                    vals.append(match.iloc[0]['delta_p99'] if not match.empty else 0)
                offset = (i - n_auth / 2 + 0.5) * width
                for j, val in enumerate(vals):
                    if val > BREAK_LO:
                        x_pos = x[j] + offset
                        ax_top.text(x_pos, val + (y_max_upper - BREAK_HI) * 0.02,
                                    f'{val:+.0f}', ha='center', va='bottom',
                                    fontsize=8, fontweight='bold')

            # Mark missing data slots at zero line
            for xm in missing_slots_d:
                ax_bot.text(xm, 0, '–',
                            ha='center', va='bottom', fontsize=9,
                            color='#999', fontweight='bold')

            ax_top.legend(fontsize=9, loc='upper left')
            ax_top.set_title(f'{arch_display[arch]}: Auth-Only $\\Delta_{{Auth}}$ P99',
                             fontweight='bold', fontsize=13)
        else:
            fig, ax_bot = plt.subplots(figsize=(10, 7))
            missing_slots = []
            for i, auth_l in enumerate(present_labels):
                vals = []
                present = []
                for hw in hw_labels:
                    match = arch_data[(arch_data['hw'] == hw) & (arch_data['auth_label'] == auth_l)]
                    if not match.empty:
                        vals.append(match.iloc[0]['delta_p99'])
                        present.append(True)
                    else:
                        vals.append(0)
                        present.append(False)
                offset = (i - n_auth / 2 + 0.5) * width
                color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
                bars = ax_bot.bar(x + offset, vals, width, label=auth_l, color=color, alpha=0.85)
                for bar, val in zip(bars, vals):
                    if val != 0:
                        ax_bot.text(bar.get_x() + bar.get_width() / 2,
                                    bar.get_height() + 2 if val >= 0 else bar.get_height() - 2,
                                    f'{val:+.0f}', ha='center',
                                    va='bottom' if val >= 0 else 'top', fontsize=8)
                for j, p in enumerate(present):
                    if not p:
                        missing_slots.append(x[j] + offset)
            # Mark missing data slots at zero line
            for xm in missing_slots:
                ax_bot.text(xm, 0, '–',
                            ha='center', va='bottom', fontsize=9,
                            color='#999', fontweight='bold')
            ax_bot.axhline(y=0, color='black', linewidth=0.5, linestyle='--')
            ax_bot.set_xticks(x)
            ax_bot.set_xticklabels(hw_labels, fontsize=11)
            ax_bot.set_xlabel('Hardware-Tier', fontsize=12)
            ax_bot.set_ylabel('$\\Delta_{Auth}$ P99 (ms)', fontsize=12)
            ax_bot.set_title(f'{arch_display[arch]}: Auth-Only $\\Delta_{{Auth}}$ P99',
                             fontweight='bold', fontsize=13)
            ax_bot.legend(fontsize=9, loc='upper right')
            ax_bot.grid(axis='y', alpha=0.3)
            ax_bot.tick_params(labelsize=10)

        plt.tight_layout()
        path = f"{PLOT_DIR}/auth_only_delta_p99_all_hw_{arch}.pdf"
        fig.savefig(path, dpi=300, bbox_inches='tight')
        print(f"Saved: {path}")
        plt.close(fig)

    # Print summary
    print("\n--- SUMMARY ---")
    for arch in ['faas', 'microservices', 'monolith']:
        arch_data = delta_df[delta_df['architecture'] == arch]
        if arch_data.empty:
            continue
        print(f"\n  {arch.upper()}:")
        for auth_l in auth_label_order:
            label_data = arch_data[arch_data['auth_label'] == auth_l]
            if label_data.empty:
                continue
            deltas = label_data['delta_p99'].values
            print(f"    {auth_l:>28s}: ΔP99 range [{min(deltas):+.1f}, {max(deltas):+.1f}]ms")


if __name__ == '__main__':
    main()
