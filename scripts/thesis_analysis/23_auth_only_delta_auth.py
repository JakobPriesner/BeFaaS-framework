#!/usr/bin/env python3
"""
23 — Auth-Only vs Aggregate ΔAuth Analysis
Compares authentication overhead measured on all endpoints (aggregate)
vs only authenticated endpoints (auth-only). Demonstrates the "dilution
artifact": anonymous traffic (~64%) masks the true auth overhead at P50.

Now differentiates:
  - Manual (bcrypt) vs Manual (argon2id) as separate entries
  - CloudFront (+CF) vs non-CF variants
  - Includes new experiments (194-196)

Outputs: auth_only_delta_auth.csv, traffic_split.csv
"""

import sys
import pandas as pd
import numpy as np

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL,
                           auth_label_detailed)

# Endpoints that require authentication (token verification)
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

def get_protected_endpoints(arch):
    return PROTECTED_ENDPOINTS_FAAS if arch == 'faas' else PROTECTED_ENDPOINTS_CONTAINER

# Representative configs: FaaS 512MB, MS L, Mono L
REPRESENTATIVE_CONFIGS = [
    ('faas', 512, 0),
    ('microservices', 2048, 1.0),
    ('monolith', 2048, 1.0),
]


def hw_label(arch, ram, cpu):
    if arch == 'faas':
        return f"{ram}MB"
    mapping = {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}
    return mapping.get(float(cpu), f"{cpu}vCPU")


def compute_percentiles(arch, ram, cpu, endpoint_filter=None):
    """Query per-experiment percentiles with algo and CF differentiation."""
    protected = get_protected_endpoints(arch)
    endpoint_clause = ""
    if endpoint_filter == 'protected':
        eps = ','.join(f"'{e}'" for e in protected)
        endpoint_clause = f"AND r.endpoint IN ({eps})"
    elif endpoint_filter == 'anonymous':
        eps = ','.join(f"'{e}'" for e in protected)
        endpoint_clause = f"AND r.endpoint NOT IN ({eps})"

    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"

    return query_df(f"""
        SELECT
            e.id, e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            COALESCE(e.with_cloudfront, false) AS with_cf,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p75,
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
          AND r.phase_name = 'Baseline'
          {endpoint_clause}
        GROUP BY e.id, e.auth_strategy, algo, with_cf
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)


def compute_traffic_split(arch, ram, cpu):
    """Compute % of requests hitting protected vs anonymous endpoints."""
    cpu_clause = "AND e.cpu_in_vcpu IS NULL" if cpu == 0 else f"AND e.cpu_in_vcpu = {cpu}"
    protected = get_protected_endpoints(arch)
    eps = ','.join(f"'{e}'" for e in protected)

    return query_df(f"""
        SELECT
            e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            COALESCE(e.with_cloudfront, false) AS with_cf,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE r.endpoint IN ({eps})) AS n_protected,
            COUNT(*) FILTER (WHERE r.endpoint NOT IN ({eps})) AS n_anonymous,
            COUNT(*) FILTER (WHERE r.is_error) AS n_error
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND e.architecture = '{arch}'
          AND e.ram_in_mb = {ram}
          {cpu_clause}
          AND r.phase_name = 'Baseline'
        GROUP BY e.auth_strategy, algo, with_cf
    """)


def main():
    print("=" * 70)
    print("23 — AUTH-ONLY vs AGGREGATE ΔAuth — FULL DIFFERENTIATION")
    print("=" * 70)

    # ── 1. Traffic split ──
    print("\n--- TRAFFIC SPLIT ---")
    split_rows = []
    for arch, ram, cpu in REPRESENTATIVE_CONFIGS:
        hw = hw_label(arch, ram, cpu)
        split_df = compute_traffic_split(arch, ram, cpu)
        for _, row in split_df.iterrows():
            total = row['total']
            pct_prot = row['n_protected'] / total * 100 if total > 0 else 0
            pct_anon = row['n_anonymous'] / total * 100 if total > 0 else 0
            pct_err = row['n_error'] / total * 100 if total > 0 else 0
            label = auth_label_detailed(
                row['auth_strategy'],
                row['algo'] if row['auth_strategy'] == 'service-integrated-manual' else None,
                row['with_cf'])
            print(f"  {arch}/{hw}/{label}: {pct_anon:.1f}% anon, "
                  f"{pct_prot:.1f}% protected, {pct_err:.1f}% error (n={total:,})")
            split_rows.append({
                'architecture': arch, 'hw': hw, 'auth': label,
                'total': total, 'n_protected': row['n_protected'],
                'n_anonymous': row['n_anonymous'], 'n_error': row['n_error'],
                'pct_protected': round(pct_prot, 1),
                'pct_anonymous': round(pct_anon, 1),
                'pct_error': round(pct_err, 1),
            })

    split_out = pd.DataFrame(split_rows)
    split_out.to_csv(f"{PLOT_DIR}/traffic_split.csv", index=False)
    print(f"Saved: {PLOT_DIR}/traffic_split.csv")

    # ── 2. Auth-only vs aggregate ΔAuth ──
    print("\n--- AUTH-ONLY vs AGGREGATE ΔAuth ---")
    result_rows = []

    for arch, ram, cpu in REPRESENTATIVE_CONFIGS:
        hw = hw_label(arch, ram, cpu)
        print(f"\n  {arch.upper()} ({hw}):")

        agg_df = compute_percentiles(arch, ram, cpu, endpoint_filter=None)
        ao_df = compute_percentiles(arch, ram, cpu, endpoint_filter='protected')

        if agg_df.empty or ao_df.empty:
            print(f"    No data for {arch}/{hw}")
            continue

        for pctl_col in ['p50', 'p75', 'p95', 'p99']:
            agg_df[pctl_col] = agg_df[pctl_col].astype(float)
            ao_df[pctl_col] = ao_df[pctl_col].astype(float)

        # Group baselines by CF status
        for with_cf in agg_df['with_cf'].unique():
            agg_cf = agg_df[agg_df['with_cf'] == with_cf]
            ao_cf = ao_df[ao_df['with_cf'] == with_cf]

            agg_none = agg_cf[agg_cf['auth_strategy'] == 'none']
            ao_none = ao_cf[ao_cf['auth_strategy'] == 'none']

            if agg_none.empty or ao_none.empty:
                # Fall back to any 'none' baseline
                agg_none = agg_df[agg_df['auth_strategy'] == 'none']
                ao_none = ao_df[ao_df['auth_strategy'] == 'none']
            if agg_none.empty or ao_none.empty:
                continue

            agg_none_p50 = agg_none['p50'].mean()
            agg_none_p99 = agg_none['p99'].mean()
            ao_none_p50 = ao_none['p50'].mean()
            ao_none_p99 = ao_none['p99'].mean()

            for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                auth_cf = agg_cf[agg_cf['auth_strategy'] == auth]
                if auth_cf.empty:
                    continue

                # Group by algo for manual
                for (algo,), algo_grp in auth_cf.groupby(['algo']):
                    cf_bool = bool(with_cf)
                    label = auth_label_detailed(
                        auth, algo if auth == 'service-integrated-manual' else None, cf_bool)

                    agg_auth_p50 = algo_grp['p50'].mean()
                    agg_auth_p99 = algo_grp['p99'].mean()

                    ao_auth_grp = ao_cf[(ao_cf['auth_strategy'] == auth) & (ao_cf['algo'] == algo)]
                    if ao_auth_grp.empty:
                        continue
                    ao_auth_p50 = ao_auth_grp['p50'].mean()
                    ao_auth_p99 = ao_auth_grp['p99'].mean()

                    ao_delta_p50 = ao_auth_p50 - ao_none_p50
                    agg_delta_p50 = agg_auth_p50 - agg_none_p50

                    row = {
                        'architecture': arch,
                        'hw': hw,
                        'auth_strategy': auth,
                        'auth_label': label,
                        'with_cf': cf_bool,
                        'ao_none_p50': round(ao_none_p50, 1),
                        'ao_auth_p50': round(ao_auth_p50, 1),
                        'ao_delta_p50': round(ao_delta_p50, 1),
                        'ao_none_p99': round(ao_none_p99, 1),
                        'ao_auth_p99': round(ao_auth_p99, 1),
                        'ao_delta_p99': round(ao_auth_p99 - ao_none_p99, 1),
                        'agg_none_p50': round(agg_none_p50, 1),
                        'agg_auth_p50': round(agg_auth_p50, 1),
                        'agg_delta_p50': round(agg_delta_p50, 1),
                        'agg_none_p99': round(agg_none_p99, 1),
                        'agg_auth_p99': round(agg_auth_p99, 1),
                        'agg_delta_p99': round(agg_auth_p99 - agg_none_p99, 1),
                        'dilution_factor_p50': round(
                            ao_delta_p50 / max(agg_delta_p50, 0.1), 1) if agg_delta_p50 != 0 else 0,
                    }
                    result_rows.append(row)

                    print(f"    {label:>28s}: AO ΔP50={row['ao_delta_p50']:+.1f}ms  "
                          f"Agg ΔP50={row['agg_delta_p50']:+.1f}ms  "
                          f"AO ΔP99={row['ao_delta_p99']:+.1f}ms  "
                          f"Agg ΔP99={row['agg_delta_p99']:+.1f}ms  "
                          f"(dilution {row['dilution_factor_p50']:.0f}×)")

    result_df = pd.DataFrame(result_rows)
    result_df.to_csv(f"{PLOT_DIR}/auth_only_delta_auth.csv", index=False)
    print(f"\nSaved: {PLOT_DIR}/auth_only_delta_auth.csv")


if __name__ == '__main__':
    main()
