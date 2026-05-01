#!/usr/bin/env python3
"""
Diagnostic: Edge-Selective fairness check
- How many experiments are aggregated per group?
- What are the experiment durations?
- Per-endpoint-type latency (auth vs anonymous)?
- Throughput (requests/min) comparison?
- Error rates?
"""

import sys
import pandas as pd
sys.path.insert(0, '.')
from db_connection import query_df, EXCLUDE_SQL, EXCLUDED_EXPERIMENTS

# Discover edge-selective experiment IDs dynamically from the database
_excl = ','.join(str(x) for x in EXCLUDED_EXPERIMENTS)
_es_df = query_df(f"""
    SELECT DISTINCT e.id FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE e.auth_strategy = 'edge-selective'
      AND e.id NOT IN ({_excl})
    GROUP BY e.id HAVING COUNT(r.id) > 50000
    ORDER BY e.id
""")
EDGE_SELECTIVE_IDS = _es_df['id'].tolist()
es_ids_sql = ','.join(str(x) for x in EDGE_SELECTIVE_IDS)

print("=" * 80)
print("DIAGNOSTIC: Edge-Selective Experiment Fairness")
print("=" * 80)

# ── 1. How many experiments per comparison group? ──
print("\n--- 1. EXPERIMENT COUNTS PER GROUP ---")
print("\nEdge-Selective experiments (145-162):")
es_overview = query_df(f"""
    SELECT e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu,
           MIN(r.timestamp_ms) AS start_ts, MAX(r.timestamp_ms) AS end_ts,
           (MAX(r.timestamp_ms) - MIN(r.timestamp_ms))/60000.0 AS duration_min,
           COUNT(*) AS total_reqs,
           COUNT(*) FILTER (WHERE NOT r.is_error) AS n_success,
           COUNT(*) FILTER (WHERE r.is_error) AS n_error,
           COUNT(*) FILTER (WHERE r.phase_name = 'Baseline') AS n_baseline,
           COUNT(*) FILTER (WHERE r.phase_name = 'Baseline' AND NOT r.is_error) AS n_baseline_ok
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE e.id IN ({es_ids_sql})
    GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu
    ORDER BY e.id
""")
for _, r in es_overview.iterrows():
    err_pct = r['n_error'] / r['total_reqs'] * 100 if r['total_reqs'] > 0 else 0
    print(f"  Exp {r['id']:>3.0f}: {r['architecture']:>14s} {r['auth_strategy']:>16s} "
          f"RAM={r['ram_in_mb']:>5.0f}  dur={r['duration_min']:>5.1f}min  "
          f"total={r['total_reqs']:>6,.0f}  baseline_ok={r['n_baseline_ok']:>6,.0f}  err={err_pct:.1f}%")

print("\nReference full-edge experiments used in script 31:")
ref_edge = query_df(f"""
    SELECT e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu,
           (MAX(r.timestamp_ms) - MIN(r.timestamp_ms))/60000.0 AS duration_min,
           COUNT(*) AS total_reqs,
           COUNT(*) FILTER (WHERE r.phase_name = 'Baseline' AND NOT r.is_error) AS n_baseline_ok
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND e.auth_strategy = 'edge'
      AND e.architecture IN ('faas', 'microservices', 'monolith')
      AND e.ram_in_mb IN (256, 512, 1024, 2048)
      AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
    GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu
    ORDER BY e.architecture, e.ram_in_mb, e.id
""")
for _, r in ref_edge.iterrows():
    print(f"  Exp {r['id']:>3.0f}: {r['architecture']:>14s} edge  "
          f"RAM={r['ram_in_mb']:>5.0f}  dur={r['duration_min']:>5.1f}min  "
          f"total={r['total_reqs']:>6,.0f}  baseline_ok={r['n_baseline_ok']:>6,.0f}")

print("\nReference none experiments used in script 31:")
ref_none = query_df(f"""
    SELECT e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu,
           (MAX(r.timestamp_ms) - MIN(r.timestamp_ms))/60000.0 AS duration_min,
           COUNT(*) AS total_reqs,
           COUNT(*) FILTER (WHERE r.phase_name = 'Baseline' AND NOT r.is_error) AS n_baseline_ok
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND e.auth_strategy = 'none'
      AND e.architecture IN ('faas', 'microservices', 'monolith')
      AND e.ram_in_mb IN (256, 512, 1024, 2048)
      AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
    GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb, e.cpu_in_vcpu
    ORDER BY e.architecture, e.ram_in_mb, e.id
""")
for _, r in ref_none.iterrows():
    print(f"  Exp {r['id']:>3.0f}: {r['architecture']:>14s} none  "
          f"RAM={r['ram_in_mb']:>5.0f}  dur={r['duration_min']:>5.1f}min  "
          f"total={r['total_reqs']:>6,.0f}  baseline_ok={r['n_baseline_ok']:>6,.0f}")


# ── 2. Throughput comparison (requests per minute in Baseline) ──
print("\n\n--- 2. THROUGHPUT (requests/min in Baseline phase) ---")

# Edge-selective throughput
es_throughput = query_df(f"""
    SELECT e.id, e.architecture, e.auth_strategy, e.ram_in_mb,
           COUNT(*) FILTER (WHERE r.phase_name = 'Baseline' AND NOT r.is_error) AS n_ok,
           (MAX(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline')
                   - MIN(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline'))/60000.0 AS baseline_dur_min,
           CASE WHEN (MAX(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline')
                   - MIN(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline')) > 0
                THEN COUNT(*) FILTER (WHERE r.phase_name = 'Baseline' AND NOT r.is_error) /
                     ((MAX(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline')
                     - MIN(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline'))/60000.0)
                ELSE 0 END AS reqs_per_min
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE e.id IN ({es_ids_sql}) AND e.auth_strategy = 'edge-selective'
    GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb
    ORDER BY e.architecture, e.ram_in_mb
""")
print("\nEdge-Selective:")
for _, r in es_throughput.iterrows():
    print(f"  Exp {r['id']:>3.0f}: {r['architecture']:>14s} RAM={r['ram_in_mb']:>5.0f}  "
          f"baseline_dur={r['baseline_dur_min']:.1f}min  n_ok={r['n_ok']:>6,.0f}  "
          f"throughput={r['reqs_per_min']:.0f} req/min")

# Reference edge throughput
ref_edge_tp = query_df(f"""
    SELECT e.id, e.architecture, e.auth_strategy, e.ram_in_mb,
           COUNT(*) FILTER (WHERE r.phase_name = 'Baseline' AND NOT r.is_error) AS n_ok,
           (MAX(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline')
                   - MIN(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline'))/60000.0 AS baseline_dur_min,
           CASE WHEN (MAX(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline')
                   - MIN(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline')) > 0
                THEN COUNT(*) FILTER (WHERE r.phase_name = 'Baseline' AND NOT r.is_error) /
                     ((MAX(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline')
                     - MIN(r.timestamp_ms) FILTER (WHERE r.phase_name = 'Baseline'))/60000.0)
                ELSE 0 END AS reqs_per_min
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND e.auth_strategy = 'edge'
      AND e.architecture IN ('faas', 'microservices', 'monolith')
      AND e.ram_in_mb IN (256, 512, 1024, 2048)
      AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
    GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb
    ORDER BY e.architecture, e.ram_in_mb
""")
print("\nFull-Edge reference:")
for _, r in ref_edge_tp.iterrows():
    print(f"  Exp {r['id']:>3.0f}: {r['architecture']:>14s} RAM={r['ram_in_mb']:>5.0f}  "
          f"baseline_dur={r['baseline_dur_min']:.1f}min  n_ok={r['n_ok']:>6,.0f}  "
          f"throughput={r['reqs_per_min']:.0f} req/min")


# ── 3. Per-endpoint-type latency (auth-protected vs anonymous) ──
print("\n\n--- 3. PER-ENDPOINT-TYPE LATENCY ---")
print("(Checking if auth-only endpoints show expected pattern)")

# First, find which endpoints are auth-protected
# In BeFaaS, typical auth endpoints: login, register, cart, checkout, payment
# Anonymous: browse, search, product, home, etc.
# Let's check what endpoints exist
endpoints = query_df(f"""
    SELECT DISTINCT r.endpoint
    FROM requests r
    JOIN experiments e ON r.experiment_id = e.id
    WHERE e.id IN ({es_ids_sql})
    ORDER BY r.endpoint
""")
print(f"\nEndpoints in edge-selective experiments: {', '.join(endpoints['endpoint_name'].tolist())}")

# Compare per-endpoint: edge-selective vs full-edge for a representative config
# Use FaaS 512MB as example
print("\nPer-endpoint comparison: FaaS 512MB, Baseline phase")

# Pick first edge-selective FaaS 512MB experiment dynamically
_es_512 = query_df(f"""
    SELECT e.id FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE e.auth_strategy = 'edge-selective' AND e.architecture = 'faas'
      AND e.ram_in_mb = 512 AND e.id NOT IN ({_excl})
    GROUP BY e.id HAVING COUNT(r.id) > 50000
    ORDER BY e.id LIMIT 1
""")
_es_512_id = int(_es_512.iloc[0]['id']) if not _es_512.empty else None
print(f"  Using edge-selective FaaS 512MB experiment: E{_es_512_id}")

per_ep_es = query_df(f"""
    SELECT r.endpoint,
           COUNT(*) FILTER (WHERE NOT r.is_error) AS n_ok,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
               FILTER (WHERE NOT r.is_error) AS p50,
           percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
               FILTER (WHERE NOT r.is_error) AS p99
    FROM requests r
    WHERE r.experiment_id = {_es_512_id}
      AND r.phase_name = 'Baseline'
    GROUP BY r.endpoint
    ORDER BY r.endpoint
""") if _es_512_id else pd.DataFrame()

# Full-edge reference for FaaS 512MB
per_ep_edge = query_df(f"""
    SELECT r.endpoint,
           COUNT(*) FILTER (WHERE NOT r.is_error) AS n_ok,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
               FILTER (WHERE NOT r.is_error) AS p50,
           percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
               FILTER (WHERE NOT r.is_error) AS p99
    FROM requests r
    JOIN experiments e ON r.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND e.auth_strategy = 'edge'
      AND e.architecture = 'faas'
      AND e.ram_in_mb = 512
      AND r.phase_name = 'Baseline'
      AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
    GROUP BY r.endpoint
    ORDER BY r.endpoint
""")

print(f"\n  {'Endpoint':<20s} | {'Edge-Sel P50':>10s} {'P99':>8s} {'n':>7s} | "
      f"{'Full-Edge P50':>12s} {'P99':>8s} {'n':>7s} | {'ΔP50':>6s} {'ΔP99':>8s}")
print(f"  {'-'*20} | {'-'*10} {'-'*8} {'-'*7} | {'-'*12} {'-'*8} {'-'*7} | {'-'*6} {'-'*8}")

if not per_ep_es.empty and not per_ep_edge.empty:
    all_eps = sorted(set(per_ep_es['endpoint_name'].tolist()) | set(per_ep_edge['endpoint_name'].tolist()))
    for ep in all_eps:
        es_row = per_ep_es[per_ep_es['endpoint_name'] == ep]
        edge_row = per_ep_edge[per_ep_edge['endpoint_name'] == ep]

        es_p50 = float(es_row.iloc[0]['p50']) if not es_row.empty else None
        es_p99 = float(es_row.iloc[0]['p99']) if not es_row.empty else None
        es_n = int(es_row.iloc[0]['n_ok']) if not es_row.empty else 0

        edge_p50 = float(edge_row.iloc[0]['p50']) if not edge_row.empty else None
        edge_p99 = float(edge_row.iloc[0]['p99']) if not edge_row.empty else None
        edge_n = int(edge_row.iloc[0]['n_ok']) if not edge_row.empty else 0

        dp50 = f"{es_p50 - edge_p50:+.0f}" if es_p50 is not None and edge_p50 is not None else "N/A"
        dp99 = f"{es_p99 - edge_p99:+.0f}" if es_p99 is not None and edge_p99 is not None else "N/A"

        es_p50_s = f"{es_p50:.0f}" if es_p50 is not None else "N/A"
        es_p99_s = f"{es_p99:.0f}" if es_p99 is not None else "N/A"
        edge_p50_s = f"{edge_p50:.0f}" if edge_p50 is not None else "N/A"
        edge_p99_s = f"{edge_p99:.0f}" if edge_p99 is not None else "N/A"

        print(f"  {ep:<20s} | {es_p50_s:>10s} {es_p99_s:>8s} {es_n:>7,d} | "
              f"{edge_p50_s:>12s} {edge_p99_s:>8s} {edge_n:>7,d} | {dp50:>6s} {dp99:>8s}")


# ── 4. Check if reference "edge" aggregates multiple experiments ──
print("\n\n--- 4. EXPERIMENT AGGREGATION CHECK ---")
print("How many experiments does each reference group aggregate?")

agg_check = query_df(f"""
    SELECT e.architecture, e.ram_in_mb, e.auth_strategy,
           COUNT(DISTINCT e.id) AS n_experiments,
           array_agg(DISTINCT e.id ORDER BY e.id) AS experiment_ids,
           SUM(CASE WHEN r.phase_name = 'Baseline' AND NOT r.is_error THEN 1 ELSE 0 END) AS total_baseline_ok
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND e.auth_strategy IN ('none', 'edge')
      AND e.architecture IN ('faas', 'microservices', 'monolith')
      AND e.ram_in_mb IN (256, 512, 1024, 2048)
      AND e.password_hash_algorithm IS DISTINCT FROM 'argon2id'
    GROUP BY e.architecture, e.ram_in_mb, e.auth_strategy
    ORDER BY e.architecture, e.ram_in_mb, e.auth_strategy
""")
for _, r in agg_check.iterrows():
    print(f"  {r['architecture']:>14s} RAM={r['ram_in_mb']:>5.0f} {r['auth_strategy']:>6s}: "
          f"{r['n_experiments']} exps {r['experiment_ids']}  baseline_ok={r['total_baseline_ok']:>7,d}")

# Edge-selective aggregation
es_agg = query_df(f"""
    SELECT e.architecture, e.ram_in_mb, e.auth_strategy,
           COUNT(DISTINCT e.id) AS n_experiments,
           array_agg(DISTINCT e.id ORDER BY e.id) AS experiment_ids,
           SUM(CASE WHEN r.phase_name = 'Baseline' AND NOT r.is_error THEN 1 ELSE 0 END) AS total_baseline_ok
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE e.id IN ({es_ids_sql})
      AND e.auth_strategy = 'edge-selective'
    GROUP BY e.architecture, e.ram_in_mb, e.auth_strategy
    ORDER BY e.architecture, e.ram_in_mb
""")
print("\nEdge-Selective aggregation:")
for _, r in es_agg.iterrows():
    print(f"  {r['architecture']:>14s} RAM={r['ram_in_mb']:>5.0f} edge-sel: "
          f"{r['n_experiments']} exps {r['experiment_ids']}  baseline_ok={r['total_baseline_ok']:>7,d}")


# ── 5. Latency distribution shape check ──
print("\n\n--- 5. LATENCY DISTRIBUTION SHAPE (bimodality check) ---")
print("Edge-selective should have bimodal distribution: fast anonymous + slow auth")

for exp_id, label in [(146, "ES FaaS 512"), (148, "ES MS L"), (155, "ES Mono L")]:
    dist = query_df(f"""
        SELECT
            width_bucket(r.latency_ms, 0, 600, 30) AS bucket,
            COUNT(*) AS cnt
        FROM requests r
        WHERE r.experiment_id = {exp_id}
          AND r.phase_name = 'Baseline'
          AND NOT r.is_error
        GROUP BY 1
        ORDER BY 1
    """)
    if not dist.empty:
        total = dist['cnt'].sum()
        print(f"\n  Exp {exp_id} ({label}): total={total}")
        # Show buckets with >1% of requests
        for _, row in dist.iterrows():
            pct = row['cnt'] / total * 100
            if pct > 1:
                lo = (row['bucket'] - 1) * 20
                hi = row['bucket'] * 20
                bar = '#' * int(pct)
                print(f"    {lo:>4.0f}-{hi:>4.0f}ms: {row['cnt']:>5,d} ({pct:>5.1f}%) {bar}")


# ── 6. Error rate comparison ──
print("\n\n--- 6. ERROR RATES (Baseline phase) ---")
err_check = query_df(f"""
    SELECT e.id, e.architecture, e.auth_strategy, e.ram_in_mb,
           COUNT(*) FILTER (WHERE r.phase_name = 'Baseline') AS n_baseline,
           COUNT(*) FILTER (WHERE r.phase_name = 'Baseline' AND r.is_error) AS n_baseline_err,
           ROUND(100.0 * COUNT(*) FILTER (WHERE r.phase_name = 'Baseline' AND r.is_error) /
                 NULLIF(COUNT(*) FILTER (WHERE r.phase_name = 'Baseline'), 0), 1) AS err_pct
    FROM experiments e
    JOIN requests r ON r.experiment_id = e.id
    WHERE e.id IN ({es_ids_sql}) AND e.auth_strategy = 'edge-selective'
    GROUP BY e.id, e.architecture, e.auth_strategy, e.ram_in_mb
    ORDER BY e.architecture, e.ram_in_mb
""")
for _, r in err_check.iterrows():
    print(f"  Exp {r['id']:>3.0f}: {r['architecture']:>14s} RAM={r['ram_in_mb']:>5.0f}  "
          f"baseline={r['n_baseline']:>6,d}  errors={r['n_baseline_err']:>5,d}  err={r['err_pct']:.1f}%")

print("\n" + "=" * 80)
print("END DIAGNOSTIC")
print("=" * 80)
