#!/usr/bin/env python3
"""
43 — Zahlen für das Evaluation-Kapitel (Version 2026-04-21, Post-Cleanup).

Zieht via SQL aus der DB die exakten Werte, die im Kapitel 6 der Thesis
referenziert werden. Dieses Skript ersetzt die veraltete Memory-Datei
evaluation_data.md als autoritative Quelle für die Kapitel-Zahlen.

Gruppen:
  A) Traffic-Split (anonym vs. authentifiziert)
  B) Aggregierter ΔAuth (Tab. 6.1)
  C) Auth-only ΔAuth (Tab. 6.2)
  D) Nivellierender Effekt (Architekturverhältnis)
  E) Baseline-Streuung pro Architektur (für "variieren um Faktor")
  F) Gesamtdurchsatz pro SCNAST-Durchlauf (Tab. 3.x / Durchsatzanalyse)
  G) Datenabdeckung: n pro Konfiguration

Output: CSV-Dateien in plots/chapter_data_*.csv + stdout-Report für den Autor.
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

PROTECTED_FAAS = "('/frontend/setUser','/frontend/addCartItem','/frontend/cart','/frontend/checkout')"
PROTECTED_CT = "('/setUser','/addCartItem','/cart','/checkout')"


def hw(row):
    if row['architecture'] == 'faas':
        return f"{int(row['ram_norm'])}MB"
    m = {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}
    return m.get(float(row['cpu']), f"{row['cpu']}v")


def lbl(auth, algo, with_cf):
    base = {'none': 'None', 'service-integrated': 'Cognito',
            'edge': 'Edge', 'edge-selective': 'Edge-Sel.'}
    if auth == 'service-integrated-manual':
        a = algo if algo not in ('default', 'N/A') else 'bcrypt'
        label = f'Manual({a})'
    else:
        label = base.get(auth, auth)
    if with_cf and auth not in ('edge', 'edge-selective'):
        label += '+CF'
    return label


# ── A) Traffic-Split ───────────────────────────────────────────────────
def traffic_split():
    df = query_df(f"""
        SELECT
          e.architecture,
          COUNT(*) AS total,
          SUM(CASE WHEN (e.architecture='faas' AND r.endpoint IN {PROTECTED_FAAS})
                    OR (e.architecture!='faas' AND r.endpoint IN {PROTECTED_CT})
                   THEN 1 ELSE 0 END) AS n_auth,
          SUM(CASE WHEN r.is_error THEN 1 ELSE 0 END) AS n_err
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
        GROUP BY e.architecture
    """)
    df['pct_auth'] = (df['n_auth'] / df['total'] * 100).round(1)
    df['pct_anon'] = (100 - df['pct_auth']).round(1)
    df['pct_err'] = (df['n_err'] / df['total'] * 100).round(2)
    return df[['architecture', 'total', 'pct_anon', 'pct_auth', 'pct_err']]


# ── B) Aggregated ΔAuth (Tab. 6.1) ─────────────────────────────────────
def agg_delta():
    df = query_df(f"""
        SELECT
          e.id, e.architecture,
          e.ram_in_mb AS ram_norm,
          COALESCE(e.cpu_in_vcpu, 0) AS cpu,
          e.auth_strategy,
          COALESCE(e.password_hash_algorithm, 'default') AS algo,
          COALESCE(e.with_cloudfront, false) AS with_cf,
          percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
              FILTER (WHERE NOT r.is_error) AS p50,
          percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
              FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL} AND r.phase_name = 'Baseline'
          AND e.ram_in_mb != 1796
        GROUP BY e.id, e.architecture, ram_norm, e.cpu_in_vcpu,
                 e.auth_strategy, e.password_hash_algorithm, e.with_cloudfront
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 500
    """)
    df['hw'] = df.apply(hw, axis=1)
    df.loc[~df['auth_strategy'].isin(['service-integrated-manual']), 'algo'] = 'n/a'
    df['label'] = df.apply(lambda r: lbl(r['auth_strategy'], r['algo'], r['with_cf']), axis=1)

    agg = df.groupby(['architecture', 'hw', 'auth_strategy', 'algo', 'with_cf', 'label']).agg(
        n=('id', 'count'), p50=('p50', 'mean'), p99=('p99', 'mean')
    ).reset_index()

    rows = []
    for _, r in agg.iterrows():
        if r['auth_strategy'] == 'none':
            continue
        base = agg[(agg['architecture'] == r['architecture']) &
                   (agg['hw'] == r['hw']) &
                   (agg['auth_strategy'] == 'none') &
                   (agg['with_cf'] == r['with_cf'])]
        if base.empty:
            base = agg[(agg['architecture'] == r['architecture']) &
                       (agg['hw'] == r['hw']) & (agg['auth_strategy'] == 'none')]
        if base.empty:
            continue
        rows.append({
            'arch': r['architecture'], 'hw': r['hw'], 'label': r['label'], 'n': int(r['n']),
            'none_p99': round(base['p99'].mean()),
            'auth_p99': round(r['p99']),
            'delta_p99': round(r['p99'] - base['p99'].mean()),
            'delta_p50': round(r['p50'] - base['p50'].mean(), 1),
        })
    return pd.DataFrame(rows).sort_values(['arch', 'hw', 'label'])


# ── C) Auth-only ΔAuth (Tab. 6.2) ──────────────────────────────────────
def auth_only_delta():
    df = query_df(f"""
        SELECT
          e.id, e.architecture,
          e.ram_in_mb AS ram_norm,
          COALESCE(e.cpu_in_vcpu, 0) AS cpu,
          e.auth_strategy,
          COALESCE(e.password_hash_algorithm, 'default') AS algo,
          COALESCE(e.with_cloudfront, false) AS with_cf,
          percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
              FILTER (WHERE NOT r.is_error) AS ao_p50,
          percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
              FILTER (WHERE NOT r.is_error) AS ao_p99
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
          AND r.phase_name = 'Baseline'
          AND e.ram_in_mb != 1796
          AND ( (e.architecture='faas' AND r.endpoint IN {PROTECTED_FAAS})
             OR (e.architecture!='faas' AND r.endpoint IN {PROTECTED_CT}) )
        GROUP BY e.id, e.architecture, ram_norm, e.cpu_in_vcpu,
                 e.auth_strategy, e.password_hash_algorithm, e.with_cloudfront
        HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
    """)
    df['hw'] = df.apply(hw, axis=1)
    df.loc[~df['auth_strategy'].isin(['service-integrated-manual']), 'algo'] = 'n/a'
    df['label'] = df.apply(lambda r: lbl(r['auth_strategy'], r['algo'], r['with_cf']), axis=1)

    agg = df.groupby(['architecture', 'hw', 'auth_strategy', 'algo', 'with_cf', 'label']).agg(
        n=('id', 'count'), ao_p50=('ao_p50', 'mean'), ao_p99=('ao_p99', 'mean')
    ).reset_index()

    rows = []
    for _, r in agg.iterrows():
        if r['auth_strategy'] == 'none':
            continue
        base = agg[(agg['architecture'] == r['architecture']) &
                   (agg['hw'] == r['hw']) &
                   (agg['auth_strategy'] == 'none') &
                   (agg['with_cf'] == r['with_cf'])]
        if base.empty:
            base = agg[(agg['architecture'] == r['architecture']) &
                       (agg['hw'] == r['hw']) & (agg['auth_strategy'] == 'none')]
        if base.empty:
            continue
        rows.append({
            'arch': r['architecture'], 'hw': r['hw'], 'label': r['label'], 'n': int(r['n']),
            'ao_none_p99': round(base['ao_p99'].mean()),
            'ao_auth_p99': round(r['ao_p99']),
            'ao_delta_p99': round(r['ao_p99'] - base['ao_p99'].mean()),
            'ao_delta_p50': round(r['ao_p50'] - base['ao_p50'].mean(), 1),
        })
    return pd.DataFrame(rows).sort_values(['arch', 'hw', 'label'])


# ── D) Architecture ratio compression ──────────────────────────────────
def arch_ratio(agg_df):
    """Aggregate ΔAuth-only: compute ratio fastest vs slowest arch per strategy."""
    # Use auth_p99 (absolute) to compute ratio
    rows = []
    # Compare comparable configs: FaaS/512 vs MS/L vs Mono/L (medium tier)
    # and FaaS/256 vs MS/S vs Mono/S (small tier)
    for strat in ['None', 'Cognito', 'Edge', 'Manual(bcrypt)', 'Manual(argon2id)']:
        for tier_label, configs in [
            ('Medium', [('faas', '512MB'), ('microservices', 'L'), ('monolith', 'L')]),
            ('Large',  [('faas', '1024MB'), ('microservices', 'XL'), ('monolith', 'XL')]),
        ]:
            vals = {}
            for arch, hw_ in configs:
                if strat == 'None':
                    match = agg_df[(agg_df['arch'] == arch) & (agg_df['hw'] == hw_)]
                    if not match.empty:
                        vals[arch] = match.iloc[0]['none_p99']
                else:
                    match = agg_df[(agg_df['arch'] == arch) & (agg_df['hw'] == hw_) &
                                   (agg_df['label'] == strat)]
                    if not match.empty:
                        vals[arch] = match.iloc[0]['auth_p99']
            if len(vals) >= 2:
                rows.append({
                    'strategy': strat, 'tier': tier_label,
                    'faas': vals.get('faas'), 'ms': vals.get('microservices'),
                    'mono': vals.get('monolith'),
                    'ratio_slow_fast': round(max(vals.values()) / min(vals.values()), 1) if min(vals.values(), default=0) > 0 else None,
                })
    return pd.DataFrame(rows)


# ── E) None-Baseline-Streuung ──────────────────────────────────────────
def baseline_range(agg_df):
    """Range of None-P99 baseline across architectures."""
    none_vals = agg_df.drop_duplicates(subset=['arch', 'hw', 'none_p99'])[['arch', 'hw', 'none_p99']]
    return none_vals.sort_values(['arch', 'none_p99'])


# ── F) Gesamtdurchsatz pro SCNAST-Durchlauf ───────────────────────────
def total_throughput():
    df = query_df(f"""
        SELECT
          e.architecture,
          COALESCE(e.with_cloudfront, false) AS with_cf,
          e.auth_strategy,
          e.id,
          COUNT(*) FILTER (WHERE r.phase_name IS NOT NULL AND r.phase_name <> 'None') AS n_reqs,
          COUNT(*) FILTER (WHERE r.is_error AND r.phase_name IS NOT NULL AND r.phase_name <> 'None') AS n_err
        FROM experiments e JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
        GROUP BY e.architecture, with_cf, e.auth_strategy, e.id
    """)
    summary = df.groupby('architecture').agg(
        n_exps=('id', 'count'),
        mean_reqs=('n_reqs', 'mean'),
        min_reqs=('n_reqs', 'min'),
        max_reqs=('n_reqs', 'max'),
        mean_err_pct=('n_err', lambda s: (s.sum() / df.loc[s.index, 'n_reqs'].sum() * 100)),
    ).reset_index()
    summary['mean_reqs'] = summary['mean_reqs'].astype(int)
    summary['min_reqs'] = summary['min_reqs'].astype(int)
    summary['max_reqs'] = summary['max_reqs'].astype(int)
    summary['mean_err_pct'] = summary['mean_err_pct'].round(2)
    return summary


# ── G) Coverage: n pro Konfiguration ───────────────────────────────────
def coverage():
    df = query_df(f"""
        SELECT
          e.architecture,
          e.ram_in_mb AS ram_norm,
          COALESCE(e.cpu_in_vcpu, 0) AS cpu,
          e.auth_strategy,
          COALESCE(e.password_hash_algorithm, 'default') AS algo,
          COALESCE(e.with_cloudfront, false) AS with_cf,
          COUNT(DISTINCT e.id) AS n
        FROM experiments e
        WHERE {EXCLUDE_SQL}
          AND e.ram_in_mb != 1796
        GROUP BY e.architecture, ram_norm, e.cpu_in_vcpu,
                 e.auth_strategy, e.password_hash_algorithm, e.with_cloudfront
    """)
    df['hw'] = df.apply(hw, axis=1)
    df.loc[~df['auth_strategy'].isin(['service-integrated-manual']), 'algo'] = 'n/a'
    df['label'] = df.apply(lambda r: lbl(r['auth_strategy'], r['algo'], r['with_cf']), axis=1)
    df = df.groupby(['architecture', 'hw', 'label']).agg(n=('n', 'sum')).reset_index()
    return df.sort_values(['architecture', 'hw', 'label'])


def main():
    print("=" * 70)
    print("43 — ZAHLEN FÜR EVALUATION-KAPITEL (POST-CLEANUP 2026-04-21)")
    print("=" * 70)

    print("\n=== A) TRAFFIC-SPLIT ===")
    ts = traffic_split()
    print(ts.to_string(index=False))
    ts.to_csv(f"{PLOT_DIR}/chapter_data_traffic_split.csv", index=False)

    print("\n\n=== B) AGGREGIERTER ΔAuth (Tab. 6.1) ===")
    agg = agg_delta()
    print(agg.to_string(index=False))
    agg.to_csv(f"{PLOT_DIR}/chapter_data_agg_delta_auth.csv", index=False)

    print("\n\n=== C) AUTH-ONLY ΔAuth (Tab. 6.2) ===")
    ao = auth_only_delta()
    print(ao.to_string(index=False))
    ao.to_csv(f"{PLOT_DIR}/chapter_data_auth_only_delta_auth.csv", index=False)

    print("\n\n=== D) ARCHITEKTUR-VERHÄLTNIS ===")
    ar = arch_ratio(agg)
    print(ar.to_string(index=False))
    ar.to_csv(f"{PLOT_DIR}/chapter_data_arch_ratio.csv", index=False)

    print("\n\n=== E) NONE-BASELINE-STREUUNG ===")
    br = baseline_range(agg)
    print(br.to_string(index=False))
    br.to_csv(f"{PLOT_DIR}/chapter_data_baseline_range.csv", index=False)

    print("\n\n=== F) GESAMTDURCHSATZ PRO DURCHLAUF ===")
    tp = total_throughput()
    print(tp.to_string(index=False))
    tp.to_csv(f"{PLOT_DIR}/chapter_data_total_throughput.csv", index=False)

    print("\n\n=== G) COVERAGE (n pro Konfiguration) ===")
    cov = coverage()
    # Show only missing (n=0) and n=1
    low = cov[cov['n'] <= 1]
    print(low.to_string(index=False))
    cov.to_csv(f"{PLOT_DIR}/chapter_data_coverage.csv", index=False)

    print(f"\n\nAlle CSVs in {PLOT_DIR}/chapter_data_*.csv")


if __name__ == '__main__':
    main()
