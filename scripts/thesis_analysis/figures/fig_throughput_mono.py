#!/usr/bin/env python3
"""Generate throughput_comparison_monolith.pdf for fig:throughput-monolith."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL, EXCLUDE_SQL_BY_EXP_ID,
                           auth_label_detailed, hw_label_from_row,
                           AUTH_COLORS_DETAILED, HW_TIERS_ALL)

AUTH_LABEL_ORDER = [
    'None', 'None+CF',
    'Cognito', 'Cognito+CF',
    'Manual (bcrypt)', 'Manual (bcrypt)+CF',
    'Manual (argon2id)', 'Manual (argon2id)+CF',
    'Edge', 'Edge+CF',
    'Edge-Sel.', 'Edge-Sel.+CF',
]


def main():
    df = query_df(f"""
        SELECT
            e.id AS experiment_id, e.architecture, e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            COALESCE(e.with_cloudfront, false) AS with_cf,
            e.ram_in_mb, e.cpu_in_vcpu, r.phase_name,
            COUNT(*) AS request_count,
            COUNT(CASE WHEN NOT r.is_error THEN 1 END) AS success_count,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS error_count,
            (MAX(r.relative_time_ms) - MIN(r.relative_time_ms)) / 1000.0 AS phase_duration_s
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name IS NOT NULL AND r.phase_name != 'None'
          AND {EXCLUDE_SQL} AND e.architecture = 'monolith'
        GROUP BY e.id, e.architecture, e.auth_strategy, e.password_hash_algorithm,
                 e.with_cloudfront, e.ram_in_mb, e.cpu_in_vcpu, r.phase_name
        HAVING COUNT(*) > 50
    """)

    df['phase_duration_s'] = df['phase_duration_s'].clip(lower=1.0)
    df['hw'] = df.apply(lambda r: hw_label_from_row(r), axis=1)
    df['auth_label'] = df.apply(
        lambda r: auth_label_detailed(
            r['auth_strategy'],
            r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
            bool(r['with_cf'])), axis=1)

    totals = df.groupby(['experiment_id', 'architecture', 'auth_strategy', 'auth_label',
                         'hw', 'algo', 'with_cf']).agg({
        'request_count': 'sum', 'success_count': 'sum', 'error_count': 'sum',
    }).reset_index()

    durations = query_df(f"""
        SELECT experiment_id,
               (MAX(relative_time_ms) - MIN(relative_time_ms)) / 1000.0 AS total_duration_s
        FROM requests
        WHERE {EXCLUDE_SQL_BY_EXP_ID}
          AND experiment_id IN (SELECT e.id FROM experiments e WHERE e.architecture = 'monolith' AND {EXCLUDE_SQL})
        GROUP BY experiment_id
        HAVING (MAX(relative_time_ms) - MIN(relative_time_ms)) > 0
    """)
    totals = totals.merge(durations, on='experiment_id', how='left')
    totals['total_duration_s'] = totals['total_duration_s'].clip(lower=1.0)
    totals['avg_rps'] = totals['request_count'] / totals['total_duration_s']

    best = totals.sort_values('request_count', ascending=False).drop_duplicates(
        subset=['architecture', 'auth_label', 'hw'], keep='first')

    arch_data = best[best['architecture'] == 'monolith']
    if arch_data.empty:
        print('No Monolith data')
        return

    hw_tiers = [hw for _, _, hw in HW_TIERS_ALL['monolith'] if hw in arch_data['hw'].values]
    present_labels = [l for l in AUTH_LABEL_ORDER if l in arch_data['auth_label'].values]

    x = np.arange(len(hw_tiers))
    n_auth = len(present_labels)
    width = 0.8 / max(n_auth, 1)

    fig, ax = plt.subplots(figsize=(10, 7))
    has_err_annotation = False
    missing_slots = []

    for i, auth_l in enumerate(present_labels):
        auth_vals, err_vals, present = [], [], []
        for hw in hw_tiers:
            match = arch_data[(arch_data['auth_label'] == auth_l) & (arch_data['hw'] == hw)]
            if not match.empty:
                auth_vals.append(match.iloc[0]['avg_rps'])
                err_vals.append(match.iloc[0]['error_count'] / max(match.iloc[0]['request_count'], 1) * 100)
                present.append(True)
            else:
                auth_vals.append(0); err_vals.append(0); present.append(False)
        offset = (i - n_auth / 2 + 0.5) * width
        color = AUTH_COLORS_DETAILED.get(auth_l, '#999')
        bars = ax.bar(x + offset, auth_vals, width, label=auth_l, color=color, alpha=0.85)
        for j, p in enumerate(present):
            if not p:
                missing_slots.append(x[j] + offset)
        for bar, val, err in zip(bars, auth_vals, err_vals):
            if val > 0:
                bx = bar.get_x() + bar.get_width() / 2
                bh = bar.get_height()
                ax.text(bx, bh + 0.5, f'{val:.0f}', ha='center', va='bottom', fontsize=7)
                if err >= 2:
                    has_err_annotation = True
                    err_str = f'{err:.0f}%' if err >= 10 else f'{err:.1f}%'
                    y_pos = max(bh - 8, bh * 0.5) if bh > 20 else bh + 5
                    ax.text(bx, y_pos, err_str, ha='center', va='top',
                            fontsize=6, fontweight='bold', color='#c62828',
                            bbox=dict(boxstyle='round,pad=0.1', facecolor='white', edgecolor='none', alpha=0.8))

    y_hi = ax.get_ylim()[1]
    for xm in missing_slots:
        ax.text(xm, y_hi * 0.02, '–', ha='center', va='bottom', fontsize=9, color='#999', fontweight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(hw_tiers, fontsize=10)
    ax.set_xlabel('Hardware-Tier', fontsize=11)
    ax.set_ylabel('Durchschn. Durchsatz (Req/s)', fontsize=11)
    ax.set_title('Durchsatz: Monolith', fontweight='bold', fontsize=13)
    ax.tick_params(labelsize=9)
    ax.grid(axis='y', alpha=0.3)

    legend_note = 'Rot = Fehlerrate (nur Werte ≥ 2%)' if has_err_annotation else None
    ax.legend(fontsize=8, title=legend_note, title_fontsize=8,
              loc='upper center', bbox_to_anchor=(0.5, -0.10), ncol=4, framealpha=0.9)

    plt.tight_layout()
    path = f"{PLOT_DIR}/throughput_comparison_monolith.pdf"
    fig.savefig(path, dpi=300, bbox_inches='tight')
    print(f"Saved: {path}")
    plt.close()


if __name__ == '__main__':
    main()
