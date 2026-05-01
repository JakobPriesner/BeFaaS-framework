#!/usr/bin/env python3
"""Generate all-tier cost tables from raw database measurements.

This script intentionally does not read the precomputed ``pricing`` table.
It derives each cost component from the measurement tables used during the
experiments:

* ``requests`` for external request counts, successful requests, error rates,
  API Gateway, CloudFront HTTPS, and Lambda@Edge request counts.
* ``lambda_executions`` for Lambda invocation and GB-second costs.
* ``metrics_ecs`` for Fargate task counts.
* ``metrics_alb`` for an ALB LCU estimate based on observed request volume.
* ``experiments`` for architecture, auth strategy, hardware tier, CloudFront
  configuration, algorithm, and measured pricing duration.

Outputs:

* ``plots/cost_per_request.csv``: one aggregated row per configuration.
* ``plots/cost_auth_overhead.csv``: deltas against the matching None baseline.
* ``plots/cost_per_1m_all_tiers_table.tex``: longtable covering all tiers.
* ``plots/cost_per_1m_table.tex``: compatibility copy used by evaluation.tex.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db_connection import (  # noqa: E402
    EXCLUDE_SQL,
    PLOT_DIR,
    auth_label_detailed,
    hw_label_from_row,
    query_df,
)


@dataclass(frozen=True)
class Pricing:
    """AWS us-east-1 on-demand list prices used for the thesis cost model."""

    lambda_request_per_million: float = 0.20
    lambda_per_gb_second: float = 0.0000166667
    api_gw_rest_per_million: float = 3.50
    fargate_vcpu_per_hour: float = 0.04048
    fargate_memory_gb_per_hour: float = 0.004445
    alb_per_hour: float = 0.0225
    alb_lcu_per_hour: float = 0.008
    redis_per_hour: float = 0.0416
    cognito_per_mau_first_50k: float = 0.0055
    cloudfront_per_10k_https: float = 0.0100
    lambda_edge_request_per_million: float = 0.60
    lambda_edge_per_gb_second: float = 0.00005001


PRICING = Pricing()
COGNITO_MAU = 100
LAMBDA_EDGE_DURATION_SECONDS = 0.005
LAMBDA_EDGE_MEMORY_GB = 128 / 1024

ARCH_ORDER = {"faas": 0, "microservices": 1, "monolith": 2}
AUTH_ORDER = {
    "None": 0,
    "None+CF": 1,
    "Cognito": 2,
    "Cognito+CF": 3,
    "Manual (bcrypt)": 4,
    "Manual (bcrypt)+CF": 5,
    "Manual (argon2id)": 6,
    "Manual (argon2id)+CF": 7,
    "Edge": 8,
    "Edge-Sel.": 9,
}
HW_ORDER = {"256MB": 0, "512MB": 1, "1024MB": 2, "1769MB": 3, "S": 4, "M": 5, "L": 6, "XL": 7}


def tex_escape(value: object) -> str:
    text = str(value)
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def fmt_money(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return r"\multicolumn{1}{c}{--}"
    return f"{float(value):.{digits}f}"


def fmt_int(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "--"
    return f"{int(round(float(value))):,}".replace(",", ".")


def fmt_pct(value: float | int | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return r"\multicolumn{1}{c}{--}"
    return f"{float(value):+.{digits}f}"


def format_arch(arch: str) -> str:
    return {
        "faas": r"\ac{FaaS}",
        "microservices": "Microservices",
        "monolith": "Monolith",
    }.get(arch, tex_escape(arch))


def format_hw(arch: str, hw: str, ram_in_mb: float | int | None = None) -> str:
    if arch == "faas":
        return hw.replace("MB", r"\,MB")
    if ram_in_mb is not None and not pd.isna(ram_in_mb):
        return f"{hw} ({int(ram_in_mb)}\\,MB)"
    return hw


def table_columns(table_name: str) -> set[str]:
    cols = query_df(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :table_name
        """,
        params={"table_name": table_name},
    )
    return set(cols["column_name"].tolist())


def query_raw_cost_inputs() -> pd.DataFrame:
    """Load one raw-cost row per experiment from the database."""

    experiment_cols = table_columns("experiments")
    if "with_cf" in experiment_cols:
        with_cf_expr = "COALESCE(e.with_cf, FALSE)"
    elif "cloudfront_enabled" in experiment_cols:
        with_cf_expr = "COALESCE(e.cloudfront_enabled, FALSE)"
    elif "use_cloudfront" in experiment_cols:
        with_cf_expr = "COALESCE(e.use_cloudfront, FALSE)"
    elif "name" in experiment_cols:
        with_cf_expr = (
            "lower(COALESCE(e.name, '')) LIKE '%cloudfront%' "
            "OR lower(COALESCE(e.name, '')) LIKE '%+cf%' "
            "OR lower(COALESCE(e.name, '')) LIKE '% cf%'"
        )
    else:
        with_cf_expr = "FALSE"

    if "pricing_duration_hours" in experiment_cols:
        pricing_duration_expr = "NULLIF(e.pricing_duration_hours, 0)"
    else:
        pricing_duration_expr = "NULL::numeric"

    if "password_hash_algorithm" in experiment_cols:
        hash_expr = "COALESCE(e.password_hash_algorithm, 'bcrypt')"
    elif "hash_algo" in experiment_cols:
        hash_expr = "COALESCE(e.hash_algo, 'bcrypt')"
    else:
        hash_expr = "'bcrypt'"

    sql = f"""
    WITH request_stats AS (
        SELECT
            r.experiment_id,
            COUNT(*) AS total_requests,
            COUNT(*) FILTER (WHERE NOT r.is_error) AS successful_requests,
            COUNT(*) FILTER (WHERE r.is_error) AS error_requests,
            COUNT(*) FILTER (
                WHERE COALESCE(r.auth_type, '') <> 'anonymous'
                   OR lower(COALESCE(r.endpoint, '')) ~ '(setuser|addcartitem|cart|checkout)'
            ) AS protected_requests
        FROM requests r
        GROUP BY r.experiment_id
    ),
    lambda_stats AS (
        SELECT
            le.experiment_id,
            COUNT(*) AS lambda_invocations,
            SUM(le.duration_ms) AS lambda_duration_ms,
            (MAX(le.timestamp_ms) - MIN(le.timestamp_ms)) / 3600000.0 AS lambda_duration_hours
        FROM lambda_executions le
        GROUP BY le.experiment_id
    ),
    ecs_service_stats AS (
        SELECT
            me.experiment_id,
            me.service_name,
            AVG(me.running_tasks) AS avg_running_tasks
        FROM metrics_ecs me
        GROUP BY me.experiment_id, me.service_name
    ),
    ecs_stats AS (
        SELECT
            experiment_id,
            SUM(avg_running_tasks) AS sum_avg_running_tasks
        FROM ecs_service_stats
        GROUP BY experiment_id
    ),
    ecs_span AS (
        SELECT
            me.experiment_id,
            EXTRACT(EPOCH FROM (MAX(me.timestamp) - MIN(me.timestamp))) / 3600.0 AS ecs_duration_hours
        FROM metrics_ecs me
        GROUP BY me.experiment_id
    ),
    alb_stats AS (
        SELECT
            ma.experiment_id,
            SUM(ma.request_count) AS alb_requests
        FROM metrics_alb ma
        GROUP BY ma.experiment_id
    )
    SELECT
        e.id,
        e.architecture,
        e.auth_strategy,
        {hash_expr} AS password_hash_algorithm,
        e.ram_in_mb,
        COALESCE(e.cpu_in_vcpu, 0) AS cpu_in_vcpu,
        ({with_cf_expr}) AS with_cf,
        {pricing_duration_expr} AS pricing_duration_hours,
        rs.total_requests,
        rs.successful_requests,
        rs.error_requests,
        rs.protected_requests,
        NULL::numeric AS p50,
        NULL::numeric AS p99,
        COALESCE(ls.lambda_invocations, 0) AS lambda_invocations,
        COALESCE(ls.lambda_duration_ms, 0) AS lambda_duration_ms,
        ls.lambda_duration_hours,
        COALESCE(es.sum_avg_running_tasks, 0) AS sum_avg_running_tasks,
        esp.ecs_duration_hours,
        COALESCE(alb.alb_requests, 0) AS alb_requests
    FROM experiments e
    JOIN request_stats rs ON rs.experiment_id = e.id
    LEFT JOIN lambda_stats ls ON ls.experiment_id = e.id
    LEFT JOIN ecs_stats es ON es.experiment_id = e.id
    LEFT JOIN ecs_span esp ON esp.experiment_id = e.id
    LEFT JOIN alb_stats alb ON alb.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND rs.total_requests > 50000
      AND rs.successful_requests > 0
    """
    return query_df(sql)


def add_cost_components(raw: pd.DataFrame) -> pd.DataFrame:
    """Calculate per-experiment costs from raw measurement columns."""

    df = raw.copy()
    numeric_cols = [
        "ram_in_mb",
        "cpu_in_vcpu",
        "pricing_duration_hours",
        "total_requests",
        "successful_requests",
        "error_requests",
        "protected_requests",
        "p50",
        "p99",
        "lambda_invocations",
        "lambda_duration_ms",
        "lambda_duration_hours",
        "sum_avg_running_tasks",
        "ecs_duration_hours",
        "alb_requests",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    has_lambda_metrics = (df["architecture"] == "faas") & (df["lambda_invocations"] > 0)
    has_container_metrics = (df["architecture"] != "faas") & (df["sum_avg_running_tasks"] > 0)
    df = df[has_lambda_metrics | has_container_metrics].copy()

    df["duration_hours"] = df["pricing_duration_hours"]
    df.loc[df["duration_hours"].isna() & (df["architecture"] == "faas"), "duration_hours"] = df["lambda_duration_hours"]
    df.loc[df["duration_hours"].isna() & (df["architecture"] != "faas"), "duration_hours"] = df["ecs_duration_hours"]
    df["duration_hours"] = df["duration_hours"].fillna(1.2)

    df["hw"] = df.apply(lambda r: hw_label_from_row(r), axis=1)
    df["auth_label"] = df.apply(
        lambda r: auth_label_detailed(
            r["auth_strategy"],
            r["password_hash_algorithm"],
            bool(r["with_cf"]),
        ),
        axis=1,
    )

    memory_gb = df["ram_in_mb"] / 1024.0
    lambda_gb_seconds = df["lambda_duration_ms"] / 1000.0 * memory_gb

    is_faas = df["architecture"] == "faas"
    is_container = ~is_faas
    uses_cognito = df["auth_strategy"].isin(["service-integrated", "edge", "edge-selective"])
    uses_cloudfront = df["with_cf"] | df["auth_strategy"].isin(["edge", "edge-selective"])
    is_edge_full = df["auth_strategy"] == "edge"
    is_edge_selective = df["auth_strategy"] == "edge-selective"

    df["lambda_cost"] = np.where(
        is_faas,
        df["lambda_invocations"] * PRICING.lambda_request_per_million / 1_000_000
        + lambda_gb_seconds * PRICING.lambda_per_gb_second,
        0.0,
    )

    df["apigw_cost"] = np.where(
        is_faas,
        df["total_requests"] * PRICING.api_gw_rest_per_million / 1_000_000,
        0.0,
    )

    df["fargate_cost"] = np.where(
        is_container,
        df["sum_avg_running_tasks"]
        * df["duration_hours"]
        * (
            df["cpu_in_vcpu"] * PRICING.fargate_vcpu_per_hour
            + memory_gb * PRICING.fargate_memory_gb_per_hour
        ),
        0.0,
    )

    req_per_second = df["alb_requests"] / (df["duration_hours"] * 3600.0)
    alb_lcu = np.maximum(1.0, req_per_second / 25.0)
    alb_lcu = np.where(df["alb_requests"] > 0, alb_lcu, 0.0)
    df["alb_cost"] = np.where(
        is_container,
        df["duration_hours"] * PRICING.alb_per_hour
        + alb_lcu * df["duration_hours"] * PRICING.alb_lcu_per_hour,
        0.0,
    )

    df["redis_cost"] = df["duration_hours"] * PRICING.redis_per_hour
    df["cognito_cost"] = np.where(
        uses_cognito,
        COGNITO_MAU * PRICING.cognito_per_mau_first_50k,
        0.0,
    )

    df["cloudfront_https_cost"] = np.where(
        uses_cloudfront,
        df["total_requests"] * PRICING.cloudfront_per_10k_https / 10_000,
        0.0,
    )
    df["lambda_edge_invocations"] = np.select(
        [is_edge_full, is_edge_selective],
        [df["total_requests"], df["protected_requests"]],
        default=0,
    )
    lambda_edge_gb_seconds = (
        df["lambda_edge_invocations"]
        * LAMBDA_EDGE_DURATION_SECONDS
        * LAMBDA_EDGE_MEMORY_GB
    )
    df["lambda_edge_cost"] = (
        df["lambda_edge_invocations"] * PRICING.lambda_edge_request_per_million / 1_000_000
        + lambda_edge_gb_seconds * PRICING.lambda_edge_per_gb_second
    )
    df["edge_cost"] = df["cloudfront_https_cost"] + df["lambda_edge_cost"]

    cost_cols = [
        "lambda_cost",
        "apigw_cost",
        "fargate_cost",
        "alb_cost",
        "redis_cost",
        "cognito_cost",
        "cloudfront_https_cost",
        "lambda_edge_cost",
        "edge_cost",
    ]
    df["total_cost"] = df[
        [
            "lambda_cost",
            "apigw_cost",
            "fargate_cost",
            "alb_cost",
            "redis_cost",
            "cognito_cost",
            "edge_cost",
        ]
    ].sum(axis=1)
    df["cost_per_1M_successful"] = df["total_cost"] / df["successful_requests"] * 1_000_000
    df["error_rate_pct"] = df["error_requests"] / df["total_requests"] * 100

    return df[
        [
            "id",
            "architecture",
            "hw",
            "ram_in_mb",
            "cpu_in_vcpu",
            "auth_strategy",
            "auth_label",
            "password_hash_algorithm",
            "with_cf",
            "duration_hours",
            "total_requests",
            "successful_requests",
            "error_requests",
            "error_rate_pct",
            "protected_requests",
            "lambda_edge_invocations",
            "p50",
            "p99",
            *cost_cols,
            "total_cost",
            "cost_per_1M_successful",
            "sum_avg_running_tasks",
        ]
    ]


def aggregate_costs(per_experiment: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["architecture", "hw", "auth_strategy", "auth_label", "ram_in_mb", "cpu_in_vcpu"]
    mean_cols = [
        "duration_hours",
        "total_requests",
        "successful_requests",
        "error_rate_pct",
        "protected_requests",
        "lambda_edge_invocations",
        "p50",
        "p99",
        "lambda_cost",
        "apigw_cost",
        "fargate_cost",
        "alb_cost",
        "redis_cost",
        "cognito_cost",
        "cloudfront_https_cost",
        "lambda_edge_cost",
        "edge_cost",
        "total_cost",
        "cost_per_1M_successful",
        "sum_avg_running_tasks",
    ]
    agg = (
        per_experiment.groupby(group_cols, dropna=False)
        .agg(
            n_experiments=("id", "nunique"),
            experiment_ids=("id", lambda s: ",".join(str(int(x)) for x in sorted(s))),
            **{f"mean_{col}": (col, "mean") for col in mean_cols},
        )
        .reset_index()
    )
    return agg


def add_delta_columns(cost_avg: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add deltas against matching None baselines and return delta rows."""

    df = cost_avg.copy()
    baseline_lookup: dict[tuple[str, str, float, float, str], pd.Series] = {}
    for _, row in df.iterrows():
        if row["auth_label"] in ("None", "None+CF"):
            key = (
                row["architecture"],
                row["hw"],
                float(row["ram_in_mb"]),
                float(row["cpu_in_vcpu"]),
                row["auth_label"],
            )
            baseline_lookup[key] = row

    delta_rows = []
    for idx, row in df.iterrows():
        if row["auth_label"] in ("None", "None+CF"):
            continue

        wants_cf = row["auth_label"].endswith("+CF") or row["auth_strategy"] in ("edge", "edge-selective")
        preferred = "None+CF" if wants_cf else "None"
        fallback = "None"
        base_key = (
            row["architecture"],
            row["hw"],
            float(row["ram_in_mb"]),
            float(row["cpu_in_vcpu"]),
            preferred,
        )
        baseline = baseline_lookup.get(base_key)
        baseline_label = preferred
        if baseline is None and preferred != fallback:
            fallback_key = (
                row["architecture"],
                row["hw"],
                float(row["ram_in_mb"]),
                float(row["cpu_in_vcpu"]),
                fallback,
            )
            baseline = baseline_lookup.get(fallback_key)
            baseline_label = fallback
        if baseline is None:
            continue

        none_cost = float(baseline["mean_cost_per_1M_successful"])
        auth_cost = float(row["mean_cost_per_1M_successful"])
        delta = auth_cost - none_cost
        pct = delta / none_cost * 100 if none_cost > 0 else np.nan

        df.loc[idx, "baseline_label"] = baseline_label
        df.loc[idx, "delta_cost_per_1M_successful"] = delta
        df.loc[idx, "pct_cost_delta"] = pct
        delta_rows.append(
            {
                "architecture": row["architecture"],
                "hw": row["hw"],
                "auth_label": row["auth_label"],
                "baseline_label": baseline_label,
                "baseline_cost_per_1M_successful": none_cost,
                "auth_cost_per_1M_successful": auth_cost,
                "delta_cost_per_1M_successful": delta,
                "pct_cost_delta": pct,
                "baseline_experiment_ids": baseline["experiment_ids"],
                "auth_experiment_ids": row["experiment_ids"],
            }
        )

    delta_df = pd.DataFrame(delta_rows)
    return df, delta_df


def sort_costs(df: pd.DataFrame) -> pd.DataFrame:
    sorted_df = df.copy()
    sorted_df["_arch_order"] = sorted_df["architecture"].map(ARCH_ORDER).fillna(99)
    sorted_df["_hw_order"] = sorted_df["hw"].map(HW_ORDER).fillna(99)
    sorted_df["_auth_order"] = sorted_df["auth_label"].map(AUTH_ORDER).fillna(99)
    sorted_df["_ram_order"] = sorted_df["ram_in_mb"].astype(float)
    sorted_df["_cpu_order"] = sorted_df["cpu_in_vcpu"].astype(float)
    return (
        sorted_df.sort_values(["_arch_order", "_hw_order", "_cpu_order", "_ram_order", "_auth_order", "auth_label"])
        .drop(columns=["_arch_order", "_hw_order", "_cpu_order", "_ram_order", "_auth_order"])
        .reset_index(drop=True)
    )


def write_longtable(cost_avg: pd.DataFrame, filename: str) -> str:
    data = sort_costs(cost_avg)
    lines: list[str] = [
        "% Auto-generated by scripts/thesis_analysis/tables/tab_cost_per_1m.py.",
        r"\begingroup",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{2pt}",
        r"\renewcommand{\arraystretch}{1.08}",
        r"\begin{longtable}{@{}lllrr"
        r"S[table-format=2.1]"
        r"S[table-format=2.2]S[table-format=+4.1]@{}}",
        r"\caption{Kosten pro 1\,Million erfolgreicher Anfragen über alle Hardware-Tiers "
        r"(USD, Region \texttt{us-east-1}). $\Delta_\text{Kosten}$ bezieht sich auf die "
        r"passende None-Baseline derselben Architektur und Hardwarestufe; für "
        r"CloudFront-Konfigurationen wird, sofern vorhanden, None+CF verwendet.}"
        r"\label{tab:cost-per-1M}\\",
        r"\toprule",
        r"\textbf{Architektur} & \textbf{Tier} & \textbf{Strategie} & \textbf{$n$} "
        r"& {\textbf{Erfolgreich}} & {\textbf{Fehler\,\%}} "
        r"& {\textbf{USD/1M}} & {\textbf{$\Delta$\,\%}} \\",
        r"\midrule",
        r"\endfirsthead",
        r"\caption[]{Kosten pro 1\,Million erfolgreicher Anfragen über alle Hardware-Tiers (Fortsetzung).}\\",
        r"\toprule",
        r"\textbf{Architektur} & \textbf{Tier} & \textbf{Strategie} & \textbf{$n$} "
        r"& {\textbf{Erfolgreich}} & {\textbf{Fehler\,\%}} "
        r"& {\textbf{USD/1M}} & {\textbf{$\Delta$\,\%}} \\",
        r"\midrule",
        r"\endhead",
        r"\midrule",
        r"\multicolumn{8}{r}{\footnotesize Fortsetzung auf der nächsten Seite}\\",
        r"\endfoot",
        r"\bottomrule",
        r"\endlastfoot",
    ]

    previous_arch = None
    previous_hw = None
    for _, row in data.iterrows():
        arch = row["architecture"]
        hw = row["hw"]
        if previous_arch is not None and (arch != previous_arch or hw != previous_hw):
            lines.append(r"\addlinespace[2pt]")
        previous_arch = arch
        previous_hw = hw

        lines.append(
            f"{format_arch(arch)} & {format_hw(arch, hw, row['ram_in_mb'])} & {tex_escape(row['auth_label'])} "
            f"& {int(row['n_experiments'])} "
            f"& {fmt_int(row['mean_successful_requests'])} "
            f"& {fmt_money(row['mean_error_rate_pct'], 1)} "
            f"& {fmt_money(row['mean_cost_per_1M_successful'])} "
            f"& {fmt_pct(row.get('pct_cost_delta'))} \\\\"
        )

    lines.append(r"\end{longtable}")
    lines.append(r"\endgroup")

    path = os.path.join(PLOT_DIR, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Saved: {path}")
    return path


def main() -> None:
    raw = query_raw_cost_inputs()
    if raw.empty:
        raise SystemExit("No experiment rows returned from database.")

    per_experiment = add_cost_components(raw)
    cost_avg = aggregate_costs(per_experiment)
    cost_avg, cost_delta = add_delta_columns(cost_avg)
    cost_avg = sort_costs(cost_avg)

    per_experiment_path = os.path.join(PLOT_DIR, "cost_per_experiment.csv")
    per_experiment.to_csv(per_experiment_path, index=False)
    print(f"Saved: {per_experiment_path}")

    avg_path = os.path.join(PLOT_DIR, "cost_per_request.csv")
    cost_avg.to_csv(avg_path, index=False)
    print(f"Saved: {avg_path}")

    delta_path = os.path.join(PLOT_DIR, "cost_auth_overhead.csv")
    cost_delta.to_csv(delta_path, index=False)
    print(f"Saved: {delta_path}")

    write_longtable(cost_avg, "cost_per_1m_all_tiers_table.tex")
    write_longtable(cost_avg, "cost_per_1m_table.tex")

    print("\nCost configurations by architecture:")
    summary = cost_avg.groupby("architecture")["auth_label"].count()
    for arch, count in summary.items():
        print(f"  {arch}: {count} rows")


if __name__ == "__main__":
    main()
