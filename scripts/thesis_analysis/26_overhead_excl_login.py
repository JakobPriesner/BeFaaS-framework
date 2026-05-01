#!/usr/bin/env python3
"""
26 — Auth Overhead Excluding Login (setUser)
Demonstrates that Manual (bcrypt) overhead is entirely concentrated in the
login/register endpoint (setUser). When excluding setUser, Manual has
essentially zero overhead — bcrypt cost only matters at authentication time,
not for subsequent authorized requests.
Outputs: delta_auth_excl_login.csv,
         delta_auth_excl_login_{arch}.pdf (one per architecture)
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

# Protected endpoints INCLUDING login
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

# Protected endpoints EXCLUDING login (setUser)
PROTECTED_EXCL_LOGIN_FAAS = (
    '/frontend/addCartItem',
    '/frontend/cart',
    '/frontend/checkout',
)
PROTECTED_EXCL_LOGIN_CONTAINER = (
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


def compute_percentiles(arch, ram, cpu, endpoints):
    """Query per-experiment percentiles for given endpoints."""
    eps_sql = ','.join(f"'{e}'" for e in endpoints)
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

    return query_df(f"""
        SELECT
            e.id AS experiment_id,
            e.auth_strategy,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
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
          AND r.phase_name = 'Baseline'
          AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
          AND r.endpoint IN ({eps_sql})
        GROUP BY e.id, e.auth_strategy
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 30
    """)


def main():
    print("=" * 70)
    print("26 — AUTH OVERHEAD EXCLUDING LOGIN (ALL HW CONFIGS)")
    print("=" * 70)

    result_rows = []

    for arch, ram, cpu, arch_label in ALL_CONFIGS:
        if arch == 'faas':
            eps_with_login = PROTECTED_ENDPOINTS_FAAS
            eps_without_login = PROTECTED_EXCL_LOGIN_FAAS
        else:
            eps_with_login = PROTECTED_ENDPOINTS_CONTAINER
            eps_without_login = PROTECTED_EXCL_LOGIN_CONTAINER

        df_with = compute_percentiles(arch, ram, cpu, eps_with_login)
        df_without = compute_percentiles(arch, ram, cpu, eps_without_login)

        if df_with.empty or df_without.empty:
            print(f"  WARNING: No data for {arch_label}")
            continue

        for col in ['p50', 'p75', 'p99']:
            df_with[col] = df_with[col].astype(float)
            df_without[col] = df_without[col].astype(float)

        for auth in ['none', 'service-integrated', 'service-integrated-manual', 'edge']:
            auth_label = AUTH_SHORT.get(auth, auth)

            with_none = df_with[df_with['auth_strategy'] == 'none']
            with_auth = df_with[df_with['auth_strategy'] == auth]
            wo_none = df_without[df_without['auth_strategy'] == 'none']
            wo_auth = df_without[df_without['auth_strategy'] == auth]

            if with_none.empty or wo_none.empty:
                continue
            if auth == 'none':
                result_rows.append({
                    'architecture': arch,
                    'arch_label': arch_label,
                    'auth_strategy': auth,
                    'auth_label': auth_label,
                    'with_login_p50': round(with_none['p50'].mean(), 1),
                    'with_login_p99': round(with_none['p99'].mean(), 1),
                    'excl_login_p50': round(wo_none['p50'].mean(), 1),
                    'excl_login_p99': round(wo_none['p99'].mean(), 1),
                    'delta_p50_with': 0.0,
                    'delta_p99_with': 0.0,
                    'delta_p50_excl': 0.0,
                    'delta_p99_excl': 0.0,
                })
                continue

            if with_auth.empty or wo_auth.empty:
                continue

            delta_p50_with = with_auth['p50'].mean() - with_none['p50'].mean()
            delta_p99_with = with_auth['p99'].mean() - with_none['p99'].mean()
            delta_p50_excl = wo_auth['p50'].mean() - wo_none['p50'].mean()
            delta_p99_excl = wo_auth['p99'].mean() - wo_none['p99'].mean()

            result_rows.append({
                'architecture': arch,
                'arch_label': arch_label,
                'auth_strategy': auth,
                'auth_label': auth_label,
                'with_login_p50': round(with_auth['p50'].mean(), 1),
                'with_login_p99': round(with_auth['p99'].mean(), 1),
                'excl_login_p50': round(wo_auth['p50'].mean(), 1),
                'excl_login_p99': round(wo_auth['p99'].mean(), 1),
                'delta_p50_with': round(delta_p50_with, 1),
                'delta_p99_with': round(delta_p99_with, 1),
                'delta_p50_excl': round(delta_p50_excl, 1),
                'delta_p99_excl': round(delta_p99_excl, 1),
            })

    result_df = pd.DataFrame(result_rows)
    csv_path = f"{PLOT_DIR}/delta_auth_excl_login.csv"
    result_df.to_csv(csv_path, index=False)
    print(f"\nSaved: {csv_path}")

    # Print comparison
    print("\n--- ΔAuth P99: WITH LOGIN vs EXCLUDING LOGIN ---")
    auth_only = result_df[result_df['auth_strategy'] != 'none']
    for arch_label in auth_only['arch_label'].unique():
        ad = auth_only[auth_only['arch_label'] == arch_label]
        print(f"\n  {arch_label}:")
        print(f"  {'Auth':>10s} | {'ΔP99 with login':>16s} | {'ΔP99 excl login':>16s} | {'Reduction':>10s}")
        print(f"  {'-'*10} | {'-'*16} | {'-'*16} | {'-'*10}")
        for _, r in ad.iterrows():
            reduction = r['delta_p99_with'] - r['delta_p99_excl']
            print(f"  {r['auth_label']:>10s} | {r['delta_p99_with']:>+15.1f}ms | "
                  f"{r['delta_p99_excl']:>+15.1f}ms | {reduction:>+9.1f}ms")

    # ── Plot: one PDF per architecture, subplots per HW tier ──
    auth_strategies = ['Cognito', 'Manual', 'Edge']

    for arch in ARCH_ORDER:
        arch_configs = [c for c in ALL_CONFIGS if c[0] == arch]
        arch_display = ARCH_DISPLAY[arch]
        arch_auth = auth_only[auth_only['architecture'] == arch]

        if arch_auth.empty:
            print(f"  No auth data for {arch_display} — skipping plot")
            continue

        n_hw = len(arch_configs)
        fig, axes = plt.subplots(1, n_hw, figsize=(5 * n_hw, 6), sharey=False)
        if n_hw == 1:
            axes = [axes]

        for ax, (_, ram, cpu, hw_label) in zip(axes, arch_configs):
            ad = arch_auth[arch_auth['arch_label'] == hw_label]
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

            vals_with = []
            vals_excl = []
            colors = []
            for al in auths_present:
                row = ad[ad['auth_label'] == al].iloc[0]
                vals_with.append(row['delta_p99_with'])
                vals_excl.append(row['delta_p99_excl'])
                colors.append(AUTH_COLORS.get(al, '#999999'))

            bars1 = ax.bar(x - width / 2, vals_with, width, label='With login',
                           color=colors, alpha=0.85, edgecolor='black', linewidth=0.5)
            bars2 = ax.bar(x + width / 2, vals_excl, width, label='Excl. login',
                           color=colors, alpha=0.45, edgecolor='black', linewidth=0.5,
                           hatch='///')

            for bar, val in zip(bars1, vals_with):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f'{val:+.0f}', ha='center', va='bottom', fontsize=7, fontweight='bold')
            for bar, val in zip(bars2, vals_excl):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f'{val:+.0f}', ha='center', va='bottom', fontsize=7, fontweight='bold')

            ax.set_xticks(x)
            ax.set_xticklabels(auths_present, fontsize=9)
            ax.set_ylabel('ΔAuth P99 (ms)', fontsize=9)
            ax.set_title(hw_label, fontsize=10, fontweight='bold')
            ax.legend(fontsize=7)
            ax.grid(axis='y', alpha=0.3)
            ax.axhline(y=0, color='black', linewidth=0.5)

        fig.suptitle(f'{arch_display}: Auth Overhead With vs Excluding Login\n'
                     '(ΔP99, Baseline phase, excl. argon2id)',
                     fontsize=12, fontweight='bold')
        plt.tight_layout()
        pdf_path = f"{PLOT_DIR}/delta_auth_excl_login_{arch}.pdf"
        fig.savefig(pdf_path, dpi=300, bbox_inches='tight')
        print(f"\nSaved: {pdf_path}")
        plt.close()

    # Key finding
    print("\n" + "=" * 70)
    print("KEY FINDING:")
    print("=" * 70)
    manual_data = auth_only[auth_only['auth_label'] == 'Manual']
    if not manual_data.empty:
        for _, r in manual_data.iterrows():
            print(f"  {r['arch_label']}: Manual ΔP99 with login = {r['delta_p99_with']:+.1f}ms, "
                  f"excl. login = {r['delta_p99_excl']:+.1f}ms")
        print(f"\n  Manual (bcrypt) overhead is concentrated entirely in login (setUser).")
        print(f"  Excluding login, Manual has near-zero overhead because subsequent")
        print(f"  requests only verify HS256 JWT tokens — which is extremely fast.")
    else:
        print("  No Manual (bcrypt) data found in results.")


if __name__ == '__main__':
    main()
