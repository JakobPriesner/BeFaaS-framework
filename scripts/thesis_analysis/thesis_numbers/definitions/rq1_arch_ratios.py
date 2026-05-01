"""RQ1 -- Architektur-Verhaeltnisse (Faktor zwischen schnellster und langsamster).

Die Thesis zitiert 'Ohne Authentifizierung liegt das Verhaeltnis zwischen
langsamster und schnellster Architektur bei 13,2x auf kleiner und 17,1x
auf grosser Hardware'. Auf Cognito sinkt es auf 1,3x bzw. 3,1x. Dieses
Modul rechnet die Verhaeltnisse pro Hardware-Gruppe aus der DB nach.

Kleine Hardware ~= FaaS/256 + MS/S + Mono/S (0,25 vCPU).
Grosse Hardware ~= FaaS/1024 + MS/L + Mono/L (1,0 vCPU).
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ratio_times


_BASELINE_P99_SQL = textwrap.dedent("""\
    SELECT
      architecture,
      AVG(p99) AS mean_p99
    FROM (
      SELECT e.id, e.architecture,
             percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
                 FILTER (WHERE NOT r.is_error) AS p99
      FROM experiments e JOIN requests r ON r.experiment_id = e.id
      WHERE {{EXCLUDE_SQL}}
        AND r.phase_name = 'Baseline'
        AND e.auth_strategy = '{auth}'
        AND COALESCE(e.with_cloudfront, false) = false
        AND {hw_pred}
        {algo_pred}
      GROUP BY e.id, e.architecture
      HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 500
    ) sub
    GROUP BY architecture
""")


_HW_SMALL = ("((e.architecture = 'faas' AND e.ram_in_mb = 256) "
             "OR (e.architecture <> 'faas' AND COALESCE(e.cpu_in_vcpu, 0) = 0.25))")
_HW_LARGE = ("((e.architecture = 'faas' AND e.ram_in_mb = 1024) "
             "OR (e.architecture <> 'faas' AND COALESCE(e.cpu_in_vcpu, 0) = 1.0))")


def _max_over_min(df) -> float:
    if df.empty or len(df) < 2:
        return float("nan")
    vals = df["mean_p99"].astype(float)
    lo, hi = float(vals.min()), float(vals.max())
    return hi / lo if lo > 0 else float("nan")


@register
def rq1_arch_ratio_none_small() -> Number:
    return Number(
        macro_name="rqOneArchRatioNoneSmall",
        group="rq1_arch_ratios",
        description=(
            "Verhaeltnis P99 langsamste/schnellste Architektur auf kleiner Hardware "
            "(FaaS 256 MB, Containers S) ohne Authentifizierung, Baseline-Phase."
        ),
        thesis_refs=["evaluation.tex Sec. 6.3.1 (13,2x Zitat)"],
        sql=_BASELINE_P99_SQL.format(
            auth="none", hw_pred=_HW_SMALL, algo_pred="",
        ),
        compute=_max_over_min,
        format=de_ratio_times,
        unit="x",
        extract_ids=lambda df: [],
    )


@register
def rq1_arch_ratio_none_large() -> Number:
    return Number(
        macro_name="rqOneArchRatioNoneLarge",
        group="rq1_arch_ratios",
        description=(
            "Verhaeltnis P99 langsamste/schnellste Architektur auf grosser Hardware "
            "(FaaS 1024 MB, Containers L) ohne Authentifizierung, Baseline-Phase."
        ),
        thesis_refs=["evaluation.tex Sec. 6.3.1 (17,1x Zitat)"],
        sql=_BASELINE_P99_SQL.format(
            auth="none", hw_pred=_HW_LARGE, algo_pred="",
        ),
        compute=_max_over_min,
        format=de_ratio_times,
        unit="x",
        extract_ids=lambda df: [],
    )


@register
def rq1_arch_ratio_cognito_small() -> Number:
    return Number(
        macro_name="rqOneArchRatioCognitoSmall",
        group="rq1_arch_ratios",
        description=(
            "Verhaeltnis P99 langsamste/schnellste Architektur auf kleiner Hardware "
            "unter Cognito, Baseline-Phase. Demonstriert den Angleichungseffekt."
        ),
        thesis_refs=["evaluation.tex Sec. 6.3.1 (1,3x Zitat)"],
        sql=_BASELINE_P99_SQL.format(
            auth="service-integrated", hw_pred=_HW_SMALL, algo_pred="",
        ),
        compute=_max_over_min,
        format=de_ratio_times,
        unit="x",
        extract_ids=lambda df: [],
    )


@register
def rq1_arch_ratio_cognito_large() -> Number:
    return Number(
        macro_name="rqOneArchRatioCognitoLarge",
        group="rq1_arch_ratios",
        description=(
            "Verhaeltnis P99 langsamste/schnellste Architektur auf grosser Hardware "
            "unter Cognito, Baseline-Phase."
        ),
        thesis_refs=["evaluation.tex Sec. 6.3.1 (3,1x Zitat)"],
        sql=_BASELINE_P99_SQL.format(
            auth="service-integrated", hw_pred=_HW_LARGE, algo_pred="",
        ),
        compute=_max_over_min,
        format=de_ratio_times,
        unit="x",
        extract_ids=lambda df: [],
    )
