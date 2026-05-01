#!/usr/bin/env python3
"""
27 — Baseline vs Flash Crowd Auth Overhead
Compares authentication overhead under normal load (Baseline phase) versus
stress load (Flash Crowd phase). Determines whether auth overhead amplifies
under high traffic, stays constant, or compresses.
Outputs: delta_auth_baseline_vs_flashcrowd.csv,
         delta_auth_baseline_vs_flashcrowd_{arch}.pdf (one per architecture)
"""

import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL, AUTH_COLORS

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}

PROTECTED_ENDPOINTS_FAAS = (
    '/frontend/setUser',
    '/frontend/addCartItem',
    '/frontend/cart',
    '/frontend/checkout',
)
PROTECTED_ENDPOINTS_CONTAINER = (
    '/setUser',
    '/addCartItem',
    '/cart',
    '/checkout',
)

# All hardware configurations
ALL_CONFIGS = [
    ('faas', 256, 0, 'FaaS 256MB'),
    ('faas', 512, 0, 'FaaS 512MB'),
    ('faas', 1024, 0, 'FaaS 1024MB'),
    ('faas', 1769, 0, 'FaaS 1769MB'),
    ('microservices', 512, 0.25, 'MS S'),
    ('microservices', 1024, 0.5, 'MS M'),
    ('microservices', 1769, 1.0, 'MS 1769'),
    ('microservices', 2048, 1.0, 'MS L'),
    ('microservices', 8192, 4.0, 'MS XL'),
    ('monolith', 512, 0.25, 'Mono S'),
    ('monolith', 1024, 0.5, 'Mono M'),
    ('monolith', 2048, 1.0, 'Mono L'),
    ('monolith', 8192, 4.0, 'Mono XL'),
]

ARCH_ORDER = ['faas', 'microservices', 'monolith']
ARCH_DISPLAY = {'faas': 'FaaS', 'microservices': 'Microservices', 'monolith': 'Monolith'}


def get_protected_endpoints(arch):
    return PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER


def compute_phase_percentiles(arch, ram, cpu, phase_name):
    """Query auth-only percentiles for a specific phase."""
    protected = get_protected_endpoints(arch)
    eps_sql = ','.join(f"'{e}'" for e in protected)
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

    return query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.auth_strategy,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            COUNT(*) FILTER (WHERE r.is_error) AS n_errors,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p75,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = '{arch}'
          AND e.ram_in_mb = {ram}
          {cpu_clause}
          AND r.phase_name = '{phase_name}'
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND r.endpoint IN ({eps_sql})
        GROUP BY e.id, e.auth_strategy
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 30
    """)


def main():
    print("=" * 70)
    print("27 — BASELINE vs FLASH CROWD AUTH OVERHEAD (ALL HW CONFIGS)")
    print("=" * 70)

    result_rows = []

    for arch, ram, cpu, arch_label in ALL_CONFIGS:
        print(f"\n  Processing {arch_label}...")

        df_baseline = compute_phase_percentiles(arch, ram, cpu, 'Baseline')
        df_flash = compute_phase_percentiles(arch, ram, cpu, 'Flash Crowd')

        if df_baseline.empty:
            print(f"    WARNING: No Baseline data for {arch_label}")
            continue
        if df_flash.empty:
            print(f"    WARNING: No Flash Crowd data for {arch_label}")
            continue

        for col in ['p50', 'p75', 'p99']:
            df_baseline[col] = df_baseline[col].astype(float)
            df_flash[col] = df_flash[col].astype(float)

        base_none = df_baseline[df_baseline['auth_strategy'] == 'none']
        flash_none = df_flash[df_flash['auth_strategy'] == 'none']

        if base_none.empty or flash_none.empty:
            print(f"    WARNING: No 'none' baseline for {arch_label}")
            continue

        base_none_p50 = base_none['p50'].mean()
        base_none_p99 = base_none['p99'].mean()
        flash_none_p50 = flash_none['p50'].mean()
        flash_none_p99 = flash_none['p99'].mean()

        for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
            auth_label = AUTH_SHORT.get(auth, auth)

            base_auth = df_baseline[df_baseline['auth_strategy'] == auth]
            flash_auth = df_flash[df_flash['auth_strategy'] == auth]

            if base_auth.empty or flash_auth.empty:
                print(f"    WARNING: Missing {auth_label} data for {arch_label} "
                      f"(baseline={len(base_auth)}, flash={len(flash_auth)})")
                continue

            delta_p50_base = base_auth['p50'].mean() - base_none_p50
            delta_p99_base = base_auth['p99'].mean() - base_none_p99
            delta_p50_flash = flash_auth['p50'].mean() - flash_none_p50
            delta_p99_flash = flash_auth['p99'].mean() - flash_none_p99

            amp_p50 = delta_p50_flash / delta_p50_base if abs(delta_p50_base) > 0.5 else np.nan
            amp_p99 = delta_p99_flash / delta_p99_base if abs(delta_p99_base) > 0.5 else np.nan

            result_rows.append({
                'architecture': arch,
                'arch_label': arch_label,
                'auth_strategy': auth,
                'auth_label': auth_label,
                'none_p50_baseline': round(base_none_p50, 1),
                'none_p99_baseline': round(base_none_p99, 1),
                'none_p50_flashcrowd': round(flash_none_p50, 1),
                'none_p99_flashcrowd': round(flash_none_p99, 1),
                'auth_p50_baseline': round(base_auth['p50'].mean(), 1),
                'auth_p99_baseline': round(base_auth['p99'].mean(), 1),
                'auth_p50_flashcrowd': round(flash_auth['p50'].mean(), 1),
                'auth_p99_flashcrowd': round(flash_auth['p99'].mean(), 1),
                'delta_p50_baseline': round(delta_p50_base, 1),
                'delta_p99_baseline': round(delta_p99_base, 1),
                'delta_p50_flashcrowd': round(delta_p50_flash, 1),
                'delta_p99_flashcrowd': round(delta_p99_flash, 1),
                'amplification_p50': round(amp_p50, 2) if not np.isnan(amp_p50) else None,
                'amplification_p99': round(amp_p99, 2) if not np.isnan(amp_p99) else None,
                'n_baseline': len(base_auth),
                'n_flashcrowd': len(flash_auth),
            })

    result_df = pd.DataFrame(result_rows)
    csv_path = f"{PLOT_DIR}/delta_auth_baseline_vs_flashcrowd.csv"
    result_df.to_csv(csv_path, index=False)
    print(f"\nSaved: {csv_path}")

    # Print summary
    print("\n--- ΔAuth: BASELINE vs FLASH CROWD ---")
    for arch_label in result_df['arch_label'].unique():
        ad = result_df[result_df['arch_label'] == arch_label]
        print(f"\n  {arch_label}:")
        print(f"  {'Auth':>10s} | {'ΔP99 Baseline':>14s} | {'ΔP99 FlashCrd':>14s} | "
              f"{'Amplification':>14s} | {'ΔP50 Baseline':>14s} | {'ΔP50 FlashCrd':>14s}")
        print(f"  {'-'*10} | {'-'*14} | {'-'*14} | {'-'*14} | {'-'*14} | {'-'*14}")
        for _, r in ad.iterrows():
            amp_str = f"{r['amplification_p99']:.2f}x" if r['amplification_p99'] is not None else 'N/A'
            print(f"  {r['auth_label']:>10s} | {r['delta_p99_baseline']:>+13.1f}ms | "
                  f"{r['delta_p99_flashcrowd']:>+13.1f}ms | {amp_str:>14s} | "
                  f"{r['delta_p50_baseline']:>+13.1f}ms | {r['delta_p50_flashcrowd']:>+13.1f}ms")

    if result_df.empty:
        print("  No data to plot.")
        return

    # ── Plot: one PDF per architecture, subplots per HW tier ──
    auth_strategies = ['Cognito', 'Manual', 'Edge']

    for arch in ARCH_ORDER:
        arch_configs = [c for c in ALL_CONFIGS if c[0] == arch]
        arch_display = ARCH_DISPLAY[arch]
        arch_data = result_df[result_df['architecture'] == arch]

        if arch_data.empty:
            print(f"  No data for {arch_display} — skipping plot")
            continue

        n_hw = len(arch_configs)
        fig, axes = plt.subplots(1, n_hw, figsize=(5 * n_hw, 6), sharey=False)
        if n_hw == 1:
            axes = [axes]

        for ax, (_, ram, cpu, hw_label) in zip(axes, arch_configs):
            ad = arch_data[arch_data['arch_label'] == hw_label]
            if ad.empty:
                ax.set_title(f'{hw_label}\n(no data)', fontsize=10)
                ax.text(0.5, 0.5, 'No data', ha='center', va='center',
                        transform=ax.transAxes, fontsize=12, color='gray')
                continue

            auths_present = [a for a in auth_strategies if a in ad['auth_label'].values]
            n_auths = len(auths_present)
            if n_auths == 0:
                ax.set_title(f'{hw_label}\n(no auth data)', fontsize=10)
                continue

            x = np.arange(n_auths)
            width = 0.35

            vals_baseline = []
            vals_flash = []
            colors = []
            for al in auths_present:
                row = ad[ad['auth_label'] == al].iloc[0]
                vals_baseline.append(row['delta_p99_baseline'])
                vals_flash.append(row['delta_p99_flashcrowd'])
                colors.append(AUTH_COLORS.get(al, '#999999'))

            bars1 = ax.bar(x - width / 2, vals_baseline, width, label='Baseline',
                           color=colors, alpha=0.85, edgecolor='black', linewidth=0.5)
            bars2 = ax.bar(x + width / 2, vals_flash, width, label='Flash Crowd',
                           color=colors, alpha=0.45, edgecolor='black', linewidth=0.5,
                           hatch='///')

            for bar, val in zip(bars1, vals_baseline):
                y_pos = bar.get_height()
                va = 'bottom' if y_pos >= 0 else 'top'
                ax.text(bar.get_x() + bar.get_width() / 2, y_pos + (1 if y_pos >= 0 else -1),
                        f'{val:+.0f}', ha='center', va=va, fontsize=7, fontweight='bold')
            for bar, val in zip(bars2, vals_flash):
                y_pos = bar.get_height()
                va = 'bottom' if y_pos >= 0 else 'top'
                ax.text(bar.get_x() + bar.get_width() / 2, y_pos + (1 if y_pos >= 0 else -1),
                        f'{val:+.0f}', ha='center', va=va, fontsize=7, fontweight='bold')

            # Add amplification annotations
            for i, al in enumerate(auths_present):
                row = ad[ad['auth_label'] == al].iloc[0]
                if row['amplification_p99'] is not None:
                    max_val = max(abs(vals_baseline[i]), abs(vals_flash[i]))
                    y_ann = max_val + 8
                    ax.annotate(f'{row["amplification_p99"]:.1f}x',
                                (x[i], y_ann), ha='center', fontsize=8,
                                color='darkred', fontweight='bold')

            ax.set_xticks(x)
            ax.set_xticklabels(auths_present, fontsize=9)
            ax.set_ylabel('ΔAuth P99 (ms)', fontsize=9)
            ax.set_title(hw_label, fontsize=10, fontweight='bold')
            ax.legend(fontsize=7)
            ax.grid(axis='y', alpha=0.3)
            ax.axhline(y=0, color='black', linewidth=0.5)

        fig.suptitle(f'{arch_display}: Auth Overhead — Baseline vs Flash Crowd\n'
                     '(ΔP99, auth-only endpoints, excl. argon2id)',
                     fontsize=12, fontweight='bold')
        plt.tight_layout()
        pdf_path = f"{PLOT_DIR}/delta_auth_baseline_vs_flashcrowd_{arch}.pdf"
        fig.savefig(pdf_path, dpi=300, bbox_inches='tight')
        print(f"\nSaved: {pdf_path}")
        plt.close()

    # Key findings
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    for _, r in result_df.iterrows():
        amp_str = f"{r['amplification_p99']:.2f}x" if r['amplification_p99'] is not None else 'N/A'
        direction = "amplifies" if r['amplification_p99'] is not None and r['amplification_p99'] > 1.2 \
            else "compresses" if r['amplification_p99'] is not None and r['amplification_p99'] < 0.8 \
            else "stable"
        print(f"  {r['arch_label']:>12s} / {r['auth_label']:>8s}: "
              f"ΔP99 {r['delta_p99_baseline']:+.0f}ms -> {r['delta_p99_flashcrowd']:+.0f}ms "
              f"(amplification: {amp_str}, {direction})")

    valid_amps = result_df.dropna(subset=['amplification_p99'])
    if not valid_amps.empty:
        mean_amp = valid_amps['amplification_p99'].mean()
        print(f"\n  Mean amplification factor: {mean_amp:.2f}x")


if __name__ == '__main__':
    main()
