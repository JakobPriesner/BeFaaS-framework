#!/usr/bin/env python3
"""
12 - Automated Insights Finder
Scans the data for notable patterns, anomalies, and findings.
Outputs: insights_report.txt
"""

import sys
import pandas as pd
import numpy as np

sys.path.insert(0, '.')
from db_connection import query_df, PLOT_DIR, EXCLUDE_SQL

AUTH_SHORT = {
    'none': 'None', 'service-integrated': 'Cognito',
    'service-integrated-manual': 'Manual', 'edge': 'Edge'
}


def main():
    print("=" * 70)
    print("12 - AUTOMATED INSIGHTS FINDER")
    print("=" * 70)

    findings = []

    def finding(category, title, detail, severity='info'):
        findings.append({'category': category, 'title': title, 'detail': detail, 'severity': severity})
        icon = {'critical': '[!]', 'important': '[*]', 'info': '[-]'}[severity]
        print(f"\n{icon} {category}: {title}")
        print(f"    {detail}")

    # 1. Overall statistics
    stats = query_df(f"""
        SELECT
            COUNT(DISTINCT e.id) AS experiments,
            COUNT(*) AS total_requests,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS total_errors,
            COUNT(CASE WHEN r.status_code = 401 THEN 1 END) AS total_401s,
            COUNT(CASE WHEN r.is_timeout THEN 1 END) AS total_timeouts
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE {EXCLUDE_SQL}
    """).iloc[0]

    finding('overview', 'Dataset Size',
            f"{stats['experiments']} experiments, {stats['total_requests']:,} requests, "
            f"{stats['total_errors']:,} errors ({stats['total_401s']:,} soft-fails, "
            f"{stats['total_timeouts']:,} timeouts)")

    # 2. Argon2id high error rate detection
    argon2_errors = query_df(f"""
        SELECT
            e.id, e.architecture, e.ram_in_mb, e.cpu_in_vcpu,
            COUNT(*) AS total,
            COUNT(CASE WHEN r.is_error THEN 1 END) AS errors
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE e.password_hash_algorithm = 'argon2id'
          AND {EXCLUDE_SQL}
        GROUP BY e.id, e.architecture, e.ram_in_mb, e.cpu_in_vcpu
        HAVING COUNT(*) > 1000
    """)
    if not argon2_errors.empty:
        argon2_errors['error_pct'] = (argon2_errors['errors'] / argon2_errors['total'] * 100).round(1)
        high_err = argon2_errors[argon2_errors['error_pct'] > 50]
        if not high_err.empty:
            for _, r in high_err.iterrows():
                finding('argon2id', f'Exp {r["id"]}: {r["error_pct"]}% errors',
                        f'{r["architecture"]} with {r["ram_in_mb"]}MB/{r["cpu_in_vcpu"] or "N/A"}vCPU — '
                        f'argon2id causes massive timeouts on small hardware',
                        severity='critical')

    # 3. Lambda vs Fargate latency comparison
    arch_latency = query_df(f"""
        SELECT
            e.architecture,
            e.auth_strategy,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p50,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99,
            COUNT(*) AS n
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name = 'Baseline' AND NOT r.is_error
          AND {EXCLUDE_SQL}
        GROUP BY e.architecture, e.auth_strategy
        HAVING COUNT(*) > 5000
    """)

    for auth in arch_latency['auth_strategy'].unique():
        auth_data = arch_latency[arch_latency['auth_strategy'] == auth]
        faas = auth_data[auth_data['architecture'] == 'faas']
        ms = auth_data[auth_data['architecture'] == 'microservices']
        mono = auth_data[auth_data['architecture'] == 'monolith']

        if not faas.empty and not ms.empty:
            ratio = faas.iloc[0]['p99'] / ms.iloc[0]['p99'] if ms.iloc[0]['p99'] > 0 else 0
            finding('cross-arch', f'FaaS vs MS P99 ratio ({auth})',
                    f'FaaS P99={faas.iloc[0]["p99"]:.0f}ms, MS P99={ms.iloc[0]["p99"]:.0f}ms, '
                    f'ratio={ratio:.2f}x',
                    severity='important' if abs(ratio - 1) > 0.5 else 'info')

    # 4. Cold start correlation with auth
    cs_analysis = query_df(f"""
        SELECT
            e.auth_strategy,
            COUNT(*) AS total_invocations,
            COUNT(CASE WHEN l.is_cold_start THEN 1 END) AS cold_starts,
            AVG(l.init_duration_ms) FILTER (WHERE l.is_cold_start) AS avg_init_ms
        FROM experiments e
        JOIN lambda_executions l ON l.experiment_id = e.id
        WHERE e.architecture = 'faas'
          AND {EXCLUDE_SQL}
        GROUP BY e.auth_strategy
    """)

    if not cs_analysis.empty:
        for _, r in cs_analysis.iterrows():
            cs_pct = r['cold_starts'] / r['total_invocations'] * 100
            finding('cold-start', f'Cold start rate ({r["auth_strategy"]})',
                    f'{cs_pct:.2f}% cold starts ({r["cold_starts"]:,.0f}/{r["total_invocations"]:,.0f}), '
                    f'avg init={r["avg_init_ms"]:.1f}ms')

    # 5. Survivor bias: phases where auth significantly reduces request count
    phase_reqs = query_df(f"""
        SELECT
            e.architecture,
            e.auth_strategy,
            r.phase_name,
            SUM(CASE WHEN NOT r.is_error THEN 1 ELSE 0 END)::float /
                NULLIF(COUNT(*), 0) * 100 AS success_rate,
            COUNT(*) AS requests
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name IN ('Stabilization', 'Flash Crowd', 'Step Down')
          AND {EXCLUDE_SQL}
        GROUP BY e.architecture, e.auth_strategy, r.phase_name
    """)

    if not phase_reqs.empty:
        for phase in ['Stabilization', 'Flash Crowd', 'Step Down']:
            phase_data = phase_reqs[phase_reqs['phase_name'] == phase]
            for arch in phase_data['architecture'].unique():
                none_data = phase_data[(phase_data['architecture'] == arch) &
                                     (phase_data['auth_strategy'] == 'none')]
                if none_data.empty:
                    continue
                none_sr = none_data.iloc[0]['success_rate']
                for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                    auth_data = phase_data[(phase_data['architecture'] == arch) &
                                         (phase_data['auth_strategy'] == auth)]
                    if auth_data.empty:
                        continue
                    auth_sr = auth_data.iloc[0]['success_rate']
                    if none_sr - auth_sr > 10:
                        finding('survivorship', f'{arch}/{phase}: success rate drop',
                                f'{AUTH_SHORT.get(auth, auth)}: {auth_sr:.1f}% vs none: {none_sr:.1f}% '
                                f'(delta={none_sr - auth_sr:.1f}pp)',
                                severity='important')

    # 6. Edge auth latency advantage
    edge_vs_integ = query_df(f"""
        SELECT
            e.architecture,
            e.auth_strategy,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                FILTER (WHERE NOT r.is_error) AS p99
        FROM experiments e
        JOIN requests r ON r.experiment_id = e.id
        WHERE r.phase_name = 'Baseline'
          AND e.auth_strategy IN ('edge', 'service-integrated')
          AND {EXCLUDE_SQL}
        GROUP BY e.architecture, e.auth_strategy
        HAVING COUNT(*) > 5000
    """)

    for arch in edge_vs_integ['architecture'].unique():
        edge = edge_vs_integ[(edge_vs_integ['architecture'] == arch) &
                            (edge_vs_integ['auth_strategy'] == 'edge')]
        integ = edge_vs_integ[(edge_vs_integ['architecture'] == arch) &
                             (edge_vs_integ['auth_strategy'] == 'service-integrated')]
        if not edge.empty and not integ.empty:
            diff = integ.iloc[0]['p99'] - edge.iloc[0]['p99']
            finding('edge-auth', f'{arch}: edge vs integrated P99',
                    f'Edge P99={edge.iloc[0]["p99"]:.0f}ms, Integrated={integ.iloc[0]["p99"]:.0f}ms, '
                    f'edge saves {diff:.0f}ms',
                    severity='important' if diff > 50 else 'info')

    # 7. Handler duration: auth function overhead
    handler_overhead = query_df(f"""
        SELECT
            e.architecture,
            e.auth_strategy,
            h.is_protected_endpoint,
            AVG(h.duration_ms) AS avg_handler_ms,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY h.duration_ms) AS p50_handler
        FROM experiments e
        JOIN handler_events h ON h.experiment_id = e.id
        WHERE h.phase_name = 'Baseline' AND h.duration_ms > 0 AND h.duration_ms < 10000
          AND {EXCLUDE_SQL}
        GROUP BY e.architecture, e.auth_strategy, h.is_protected_endpoint
        HAVING COUNT(*) > 1000
    """)

    if not handler_overhead.empty:
        for arch in handler_overhead['architecture'].unique():
            for auth in ['service-integrated', 'service-integrated-manual']:
                auth_data = handler_overhead[(handler_overhead['architecture'] == arch) &
                                           (handler_overhead['auth_strategy'] == auth)]
                prot = auth_data[auth_data['is_protected_endpoint'] == True]
                unprot = auth_data[auth_data['is_protected_endpoint'] == False]
                if not prot.empty and not unprot.empty:
                    diff = prot.iloc[0]['p50_handler'] - unprot.iloc[0]['p50_handler']
                    finding('handler', f'{arch}/{AUTH_SHORT.get(auth, auth)}: protected vs unprotected',
                            f'Protected P50={prot.iloc[0]["p50_handler"]:.1f}ms, '
                            f'Unprotected={unprot.iloc[0]["p50_handler"]:.1f}ms, '
                            f'auth overhead={diff:.1f}ms per handler',
                            severity='important' if diff > 5 else 'info')

    # 8. RPC call overhead with auth
    rpc_stats = query_df(f"""
        SELECT
            e.architecture,
            e.auth_strategy,
            COUNT(*) AS rpc_count,
            AVG(rc.duration_ms) FILTER (WHERE rc.duration_ms > 0) AS avg_rpc_ms,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY rc.duration_ms)
                FILTER (WHERE rc.duration_ms > 0 AND rc.duration_ms < 10000) AS p95_rpc
        FROM experiments e
        JOIN rpc_calls rc ON rc.experiment_id = e.id
        WHERE rc.phase_name = 'Baseline'
          AND {EXCLUDE_SQL}
        GROUP BY e.architecture, e.auth_strategy
        HAVING COUNT(*) > 1000
    """)

    if not rpc_stats.empty:
        for arch in rpc_stats['architecture'].unique():
            none_rpc = rpc_stats[(rpc_stats['architecture'] == arch) &
                                (rpc_stats['auth_strategy'] == 'none')]
            for auth in ['service-integrated', 'service-integrated-manual', 'edge']:
                auth_rpc = rpc_stats[(rpc_stats['architecture'] == arch) &
                                   (rpc_stats['auth_strategy'] == auth)]
                if not none_rpc.empty and not auth_rpc.empty:
                    diff = auth_rpc.iloc[0]['avg_rpc_ms'] - none_rpc.iloc[0]['avg_rpc_ms']
                    finding('rpc', f'{arch}: RPC overhead with {AUTH_SHORT.get(auth, auth)}',
                            f'None avg={none_rpc.iloc[0]["avg_rpc_ms"]:.1f}ms, '
                            f'{AUTH_SHORT.get(auth, auth)}={auth_rpc.iloc[0]["avg_rpc_ms"]:.1f}ms, '
                            f'delta={diff:+.1f}ms')

    # Save report
    report_path = f"{PLOT_DIR}/insights_report.txt"
    with open(report_path, 'w') as f:
        f.write("BeFaaS Thesis Analysis — Automated Insights Report\n")
        f.write("=" * 60 + "\n\n")
        for finding_item in findings:
            icon = {'critical': '[CRITICAL]', 'important': '[IMPORTANT]', 'info': '[INFO]'}[finding_item['severity']]
            f.write(f"{icon} [{finding_item['category']}] {finding_item['title']}\n")
            f.write(f"  {finding_item['detail']}\n\n")
        f.write(f"\nTotal findings: {len(findings)}\n")
        f.write(f"Critical: {sum(1 for f in findings if f['severity'] == 'critical')}\n")
        f.write(f"Important: {sum(1 for f in findings if f['severity'] == 'important')}\n")
        f.write(f"Info: {sum(1 for f in findings if f['severity'] == 'info')}\n")

    print(f"\n\nSaved: {report_path}")
    print(f"Total findings: {len(findings)} "
          f"(critical: {sum(1 for f in findings if f['severity'] == 'critical')}, "
          f"important: {sum(1 for f in findings if f['severity'] == 'important')}, "
          f"info: {sum(1 for f in findings if f['severity'] == 'info')})")


if __name__ == '__main__':
    main()
