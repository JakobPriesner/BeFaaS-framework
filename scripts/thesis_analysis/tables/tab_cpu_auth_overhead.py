#!/usr/bin/env python3
"""Generate cpu_auth_overhead_table.tex for tab:cpu-auth-overhead.

Queries metrics_ecs during active SCNAST phases (Morning Rush, Stabilization,
Flash Crowd) for container architectures. Reports mean and max CPU per
(arch, hw, auth) with delta vs None baseline.

Uses CTE to determine phase boundaries from requests timestamps, since
metrics_ecs has no phase_name column.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import pandas as pd
from db_connection import query_df, EXCLUDE_SQL, AUTH_COLORS_DETAILED
from tables.tex_helpers import write_tex_table

HW_ORDER = ['S', 'M', 'L', 'XL']
HW_LABEL = {
    ('microservices', 0.25): 'S', ('microservices', 0.5): 'M',
    ('microservices', 1.0): 'L', ('microservices', 4.0): 'XL',
    ('monolith', 0.25): 'S', ('monolith', 0.5): 'M',
    ('monolith', 1.0): 'L', ('monolith', 4.0): 'XL',
}

AUTH_ORDER = ['None', 'Cognito', 'Manual (bcrypt)', 'Manual (argon2id)']
AUTH_LABEL_MAP = {
    ('none', 'default'): 'None',
    ('service-integrated', 'default'): 'Cognito',
    ('service-integrated-manual', 'bcrypt'): 'Manual (bcrypt)',
    ('service-integrated-manual', 'argon2id'): 'Manual (argon2id)',
}
AUTH_TEX = {
    'None': 'None',
    'Cognito': 'Cognito',
    'Manual (bcrypt)': 'Manual (bcrypt/HS256)',
    'Manual (argon2id)': 'Manual (argon2id/EdDSA)',
}


def load_data():
    sql = f"""
    WITH phase_bounds AS (
        SELECT experiment_id, phase_name,
               to_timestamp(MIN(timestamp_ms)/1000.0) AS ph_start,
               to_timestamp(MAX(timestamp_ms)/1000.0) AS ph_end
        FROM requests
        GROUP BY experiment_id, phase_name
    )
    SELECT e.id AS exp_id,
           e.architecture,
           e.auth_strategy,
           COALESCE(e.password_hash_algorithm, 'default') AS algo,
           e.cpu_in_vcpu,
           pb.phase_name,
           m.service_name,
           m.cpu_percent
    FROM experiments e
    JOIN phase_bounds pb ON pb.experiment_id = e.id
    JOIN metrics_ecs  m  ON m.experiment_id = e.id
                        AND m.timestamp BETWEEN pb.ph_start AND pb.ph_end
    WHERE {EXCLUDE_SQL}
      AND e.architecture IN ('microservices','monolith')
      AND e.auth_strategy IN ('none','service-integrated','service-integrated-manual')
      AND m.cpu_percent IS NOT NULL
      AND pb.phase_name IN ('Morning rush','Stabilization','Flash Crowd')
    """
    df = query_df(sql)
    df['auth_label'] = df.apply(
        lambda r: AUTH_LABEL_MAP.get((r['auth_strategy'], r['algo']),
                                     f"{r['auth_strategy']}/{r['algo']}"),
        axis=1)
    df['hw'] = df.apply(
        lambda r: HW_LABEL.get((r['architecture'], float(r['cpu_in_vcpu'])),
                                f"{r['cpu_in_vcpu']}vCPU"), axis=1)
    return df


def aggregate(df):
    per_exp = df.groupby(
        ['exp_id', 'architecture', 'auth_label', 'hw', 'service_name']
    ).agg(
        cpu_mean=('cpu_percent', 'mean'),
        cpu_max=('cpu_percent', 'max'),
    ).reset_index()

    ms = per_exp[(per_exp['architecture'] == 'microservices') &
                 (per_exp['service_name'] == 'frontend-service')].copy()
    mono = per_exp[per_exp['architecture'] == 'monolith'].copy()

    def agg(block):
        return block.groupby(['architecture', 'hw', 'auth_label']).agg(
            cpu_mean=('cpu_mean', 'mean'),
            cpu_max=('cpu_max', 'mean'),
            n_exp=('exp_id', 'nunique'),
        ).round(1).reset_index()

    return pd.concat([agg(ms), agg(mono)], ignore_index=True)


def main():
    raw = load_data()
    if raw.empty:
        print('No metrics_ecs data found')
        return

    summary = aggregate(raw)

    lines = []
    lines.append(r'\scriptsize')
    lines.append(r'\begin{tabular}{lp{3.2cm}crrr}')
    lines.append(r'\toprule')
    lines.append(r'\textbf{Architektur} & \textbf{Auth} & \textbf{Hardware} & \textbf{avg CPU} & \textbf{max CPU} & \textbf{$\Delta_{\text{CPU}}$ avg} \\')
    lines.append(r'\midrule')

    arch_labels = {'microservices': 'MS', 'monolith': 'Mono'}
    arch_display = {'microservices': 'Microservices', 'monolith': 'Monolith'}

    for arch in ['microservices', 'monolith']:
        arch_data = summary[summary['architecture'] == arch]
        if arch_data.empty:
            continue
        lines.append(f"\\multicolumn{{6}}{{@{{}}l}}{{\\textit{{{arch_display[arch]}}}}} \\\\")
        hws = [h for h in HW_ORDER if h in arch_data['hw'].values]
        for hw in hws:
            hw_data = arch_data[arch_data['hw'] == hw]
            none_row = hw_data[hw_data['auth_label'] == 'None']
            none_mean = float(none_row['cpu_mean'].iloc[0]) if not none_row.empty else None

            for auth in AUTH_ORDER:
                row = hw_data[hw_data['auth_label'] == auth]
                if row.empty:
                    continue
                r = row.iloc[0]
                mean_val = float(r['cpu_mean'])
                max_val = float(r['cpu_max'])

                mean_str = f"{mean_val:.1f}".replace('.', ',') + r'\,\%'
                max_str = f"{max_val:.1f}".replace('.', ',') + r'\,\%'

                if auth == 'None' or none_mean is None:
                    delta_str = '---'
                else:
                    delta = mean_val - none_mean
                    d_str = f"{delta:+.1f}".replace('.', ',')
                    delta_str = f"${'+'if delta>=0 else ''}{d_str.lstrip('+')}$" if delta >= 0 else f"${d_str}$"
                    if delta < -5:
                        delta_str += r'\textsuperscript{*}'

                lines.append(f"{arch_labels[arch]} & {AUTH_TEX.get(auth, auth)} & {hw} & {mean_str} & {max_str} & {delta_str} \\\\")

        if arch != 'monolith':
            lines.append(r'\addlinespace')

    lines.append(r'\bottomrule')
    lines.append(r'\end{tabular}')
    lines.append(r'\par\smallskip')
    lines.append(r'\footnotesize S = 0{,}25\,vCPU, M = 0{,}5\,vCPU, L = 1{,}0\,vCPU.\\')
    lines.append(r'\textsuperscript{*}~Artefakt: Hohe Fehlerraten reduzieren die effektive Last und damit die gemessene CPU-Auslastung.')
    write_tex_table('cpu_auth_overhead_table.tex', '\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
