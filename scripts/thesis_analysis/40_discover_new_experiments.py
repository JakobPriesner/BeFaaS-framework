#!/usr/bin/env python3
"""
40 — Experiment Discovery & Inventory

Dynamically queries ALL experiments from the database, classifies them
by quality (usable, partial, broken), and reports the full inventory.
No hard-coded experiment IDs — automatically discovers new experiments.

Outputs:
  - experiment_inventory.csv          (full inventory with classification)
  - experiment_inventory_summary.txt  (human-readable summary)
"""

import sys
import pandas as pd

sys.path.insert(0, '.')
from db_connection import (query_df, PLOT_DIR, EXCLUDE_SQL, EXCLUDED_EXPERIMENTS,
                           auth_label_detailed, hw_label_from_row)


def main():
    print("=" * 70)
    print("40 — EXPERIMENT DISCOVERY & INVENTORY")
    print("=" * 70)

    # ── Query all experiments with summary stats ──
    df = query_df("""
        SELECT
            e.id,
            e.architecture,
            e.auth_strategy,
            COALESCE(e.password_hash_algorithm, 'default') AS algo,
            COALESCE(e.jwt_sign_algorithm, 'default') AS jwt_algo,
            e.ram_in_mb,
            COALESCE(e.cpu_in_vcpu, 0) AS cpu_in_vcpu,
            COALESCE(e.with_cloudfront, false) AS with_cf,
            -- COALESCE(e.scaling_config, 'unknown') AS scaling_config,
            COUNT(r.id) AS total_requests,
            COUNT(r.id) FILTER (WHERE r.is_error) AS total_errors,
            COUNT(DISTINCT r.phase_name) AS phase_count,
            COUNT(r.id) FILTER (WHERE r.status_code >= 500) AS server_errors
        FROM experiments e
        LEFT JOIN requests r ON r.experiment_id = e.id
        GROUP BY e.id, e.architecture, e.auth_strategy,
                 e.password_hash_algorithm, e.jwt_sign_algorithm,
                 e.ram_in_mb, e.cpu_in_vcpu, e.with_cloudfront
        ORDER BY e.id
    """)

    df['error_rate'] = (df['total_errors'] / df['total_requests'].replace(0, 1) * 100).round(2)
    df['server_error_rate'] = (df['server_errors'] / df['total_requests'].replace(0, 1) * 100).round(2)
    df['hw'] = df.apply(hw_label_from_row, axis=1)
    df['auth_label'] = df.apply(
        lambda r: auth_label_detailed(
            r['auth_strategy'],
            r['algo'] if r['auth_strategy'] == 'service-integrated-manual' else None,
            bool(r['with_cf']) if r['with_cf'] else False
        ), axis=1)

    # ── Classify experiments ──
    df['excluded'] = df['id'].isin(EXCLUDED_EXPERIMENTS)
    df['usable'] = (
        (df['total_requests'] > 100000) &
        (df['phase_count'] >= 7) &
        (~df['excluded'])
    )

    # Config key for grouping
    df['config_key'] = df.apply(
        lambda r: f"{r['architecture']}|{r['auth_label']}|{r['hw']}", axis=1)

    # ── Summary ──
    print(f"\nTotal experiments in DB:     {len(df)}")
    print(f"Excluded (broken/duplicate): {df['excluded'].sum()}")
    print(f"Usable (>100k, 7 phases):    {df['usable'].sum()}")
    print(f"Total requests:              {df['total_requests'].sum():,}")

    # ── Per-architecture summary ──
    for arch in ['faas', 'microservices', 'monolith']:
        arch_df = df[(df['architecture'] == arch) & df['usable']]
        print(f"\n{'─'*50}")
        print(f"{arch.upper()} — {len(arch_df)} usable experiments")
        print(f"{'─'*50}")

        for auth_label in sorted(arch_df['auth_label'].unique()):
            auth_df = arch_df[arch_df['auth_label'] == auth_label]
            print(f"\n  {auth_label}:")
            for hw in sorted(auth_df['hw'].unique(), key=lambda x: auth_df[auth_df['hw'] == x]['ram_in_mb'].iloc[0]):
                hw_df = auth_df[auth_df['hw'] == hw]
                ids = sorted(hw_df['id'].tolist())
                reqs = hw_df['total_requests'].sum()
                err = hw_df['error_rate'].mean()
                print(f"    {hw:8s} n={len(hw_df)} | IDs: {ids} | "
                      f"{reqs:>10,} reqs | err={err:.1f}%")

    # ── Configs with n >= 2 (sufficient for statistical tests) ──
    config_counts = df[df['usable']].groupby('config_key').size().reset_index(name='n_runs')
    testable = config_counts[config_counts['n_runs'] >= 2]
    untestable = config_counts[config_counts['n_runs'] < 2]

    print(f"\n{'='*50}")
    print(f"STATISTICAL TESTABILITY")
    print(f"{'='*50}")
    print(f"Configs with n >= 2 (testable):   {len(testable)}")
    print(f"Configs with n = 1 (untestable):  {len(untestable)}")

    if len(untestable) > 0:
        print(f"\n  Untestable configs (need more runs):")
        for _, row in untestable.iterrows():
            parts = row['config_key'].split('|')
            print(f"    {parts[0]:15s} {parts[1]:25s} {parts[2]:8s} — n={row['n_runs']}")

    # ── Save ──
    csv_path = f"{PLOT_DIR}/experiment_inventory.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nSaved: {csv_path}")

    # Save summary text
    summary_path = f"{PLOT_DIR}/experiment_inventory_summary.txt"
    with open(summary_path, 'w') as f:
        f.write(f"Experiment Inventory — {len(df)} total, {df['usable'].sum()} usable\n")
        f.write(f"Total requests: {df['total_requests'].sum():,}\n\n")
        for arch in ['faas', 'microservices', 'monolith']:
            usable = df[(df['architecture'] == arch) & df['usable']]
            f.write(f"{arch}: {len(usable)} usable experiments\n")
            for _, row in usable.sort_values(['auth_label', 'ram_in_mb']).iterrows():
                f.write(f"  E{row['id']:3d} {row['auth_label']:25s} {row['hw']:8s} "
                        f"{row['total_requests']:>10,} reqs  {row['error_rate']:5.1f}% err\n")
            f.write("\n")
    print(f"Saved: {summary_path}")


if __name__ == '__main__':
    main()
