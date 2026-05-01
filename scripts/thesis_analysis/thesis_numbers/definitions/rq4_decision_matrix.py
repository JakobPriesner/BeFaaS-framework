"""RQ4 -- Decision-Matrix Zahlen fuer Sec. 6.7.1.

Die Entscheidungsmatrix (Tab. 6.12 / evaluation.tex:1739+) zitiert die
None-Baseline-P99 und die authentifizierte P99 auf den drei
Vergleichspunkten FaaS/512, MS/L, Mono/L. Dieses Modul liefert beide
Werte, damit die Prosa ('auf FaaS 299 ms Basislatenz ... 37 Prozent',
'5,7-Fache' etc.) reproduzierbar bleibt.
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ms, de_pct, de_ratio


_BASELINE_P99_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      e.auth_strategy,
      percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
          FILTER (WHERE NOT r.is_error) AS p99
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {{EXCLUDE_SQL}}
      AND r.phase_name = 'Baseline'
      AND e.architecture = '{arch}'
      AND {hw_pred}
      AND e.auth_strategy IN ('none', '{auth}')
      AND COALESCE(e.with_cloudfront, false) = false
    GROUP BY e.id, e.auth_strategy
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 500
""")


def _mean_p99(df, strategy: str) -> float:
    vals = df[df.auth_strategy == strategy]["p99"]
    return float(vals.mean()) if not vals.empty else float("nan")


def _ratio(df, strategy: str) -> float:
    auth = _mean_p99(df, strategy)
    none = _mean_p99(df, "none")
    if none > 0 and auth > 0:
        return auth / none
    return float("nan")


def _pct_increase(df, strategy: str) -> float:
    auth = _mean_p99(df, strategy)
    none = _mean_p99(df, "none")
    if none > 0 and auth > 0:
        return (auth - none) / none * 100.0
    return float("nan")


# FaaS 512 MB: None + Cognito baselines
_FAAS_512_SQL = _BASELINE_P99_SQL.format(
    arch="faas", hw_pred="e.ram_in_mb = 512", auth="service-integrated",
)
# MS/L: None + Cognito (autoscaled baseline, cpu=1.0)
_MS_L_SQL = _BASELINE_P99_SQL.format(
    arch="microservices", hw_pred="COALESCE(e.cpu_in_vcpu,0) = 1.0",
    auth="service-integrated",
)
# Mono/L
_MONO_L_SQL = _BASELINE_P99_SQL.format(
    arch="monolith", hw_pred="COALESCE(e.cpu_in_vcpu,0) = 1.0",
    auth="service-integrated",
)


@register
def rq4_dm_none_p99_faas_512() -> Number:
    return Number(
        macro_name="rqFourDecisionMatrixNonePNineNineFaasFiveTwelve",
        group="rq4_decision_matrix",
        description="None-Baseline P99 auf FaaS 512\\,MB, Baseline-Phase, aggregiert.",
        thesis_refs=["evaluation.tex Sec. 6.7.1 (Tab. 6.12)"],
        sql=_FAAS_512_SQL,
        compute=lambda df: _mean_p99(df, "none"),
        format=de_ms,
        unit="ms",
    )


@register
def rq4_dm_cognito_p99_faas_512() -> Number:
    return Number(
        macro_name="rqFourDecisionMatrixCognitoPNineNineFaasFiveTwelve",
        group="rq4_decision_matrix",
        description="Cognito-authentifizierte P99 auf FaaS 512\\,MB, Baseline-Phase.",
        thesis_refs=["evaluation.tex Sec. 6.7.1 (Tab. 6.12)"],
        sql=_FAAS_512_SQL,
        compute=lambda df: _mean_p99(df, "service-integrated"),
        format=de_ms,
        unit="ms",
    )


@register
def rq4_dm_cognito_pct_faas_512() -> Number:
    return Number(
        macro_name="rqFourDecisionMatrixCognitoPctFaasFiveTwelve",
        group="rq4_decision_matrix",
        description=(
            "Relativer P99-Aufschlag von Cognito gegenueber None auf FaaS 512\\,MB."
        ),
        thesis_refs=["evaluation.tex Sec. 6.7.1"],
        sql=_FAAS_512_SQL,
        compute=lambda df: _pct_increase(df, "service-integrated"),
        format=de_pct,
        unit="%",
    )


@register
def rq4_dm_none_p99_ms_l() -> Number:
    return Number(
        macro_name="rqFourDecisionMatrixNonePNineNineMsL",
        group="rq4_decision_matrix",
        description="None-Baseline P99 auf Microservices L-Tier (1\\,vCPU), Baseline-Phase.",
        thesis_refs=["evaluation.tex Sec. 6.7.1"],
        sql=_MS_L_SQL,
        compute=lambda df: _mean_p99(df, "none"),
        format=de_ms,
        unit="ms",
    )


@register
def rq4_dm_cognito_p99_ms_l() -> Number:
    return Number(
        macro_name="rqFourDecisionMatrixCognitoPNineNineMsL",
        group="rq4_decision_matrix",
        description="Cognito-P99 auf Microservices L-Tier, Baseline-Phase.",
        thesis_refs=["evaluation.tex Sec. 6.7.1"],
        sql=_MS_L_SQL,
        compute=lambda df: _mean_p99(df, "service-integrated"),
        format=de_ms,
        unit="ms",
    )


@register
def rq4_dm_cognito_ratio_ms_l() -> Number:
    return Number(
        macro_name="rqFourDecisionMatrixCognitoRatioMsL",
        group="rq4_decision_matrix",
        description=(
            "Multiplikativer Faktor Cognito-P99/None-P99 auf Microservices L. "
            "Beispiel: Faktor 5,7 = 5,7-fache Latenz."
        ),
        thesis_refs=["evaluation.tex Sec. 6.7.1 (5,7-Fache-Zitat)"],
        sql=_MS_L_SQL,
        compute=lambda df: _ratio(df, "service-integrated"),
        format=de_ratio,
        unit="-",
    )


@register
def rq4_dm_none_p99_mono_l() -> Number:
    return Number(
        macro_name="rqFourDecisionMatrixNonePNineNineMonoL",
        group="rq4_decision_matrix",
        description="None-Baseline P99 auf Monolith L-Tier, Baseline-Phase.",
        thesis_refs=["evaluation.tex Sec. 6.7.1"],
        sql=_MONO_L_SQL,
        compute=lambda df: _mean_p99(df, "none"),
        format=de_ms,
        unit="ms",
    )


@register
def rq4_dm_cognito_p99_mono_l() -> Number:
    return Number(
        macro_name="rqFourDecisionMatrixCognitoPNineNineMonoL",
        group="rq4_decision_matrix",
        description="Cognito-P99 auf Monolith L-Tier, Baseline-Phase.",
        thesis_refs=["evaluation.tex Sec. 6.7.1"],
        sql=_MONO_L_SQL,
        compute=lambda df: _mean_p99(df, "service-integrated"),
        format=de_ms,
        unit="ms",
    )


# Manual bcrypt on Mono/L for the "niedrigste authentifizierte Latenz"
_MONO_L_MANUAL_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      e.auth_strategy,
      percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
          FILTER (WHERE NOT r.is_error) AS p99
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND r.phase_name = 'Baseline'
      AND e.architecture = 'monolith'
      AND COALESCE(e.cpu_in_vcpu, 0) = 1.0
      AND e.auth_strategy = 'service-integrated-manual'
      AND COALESCE(e.password_hash_algorithm, 'default') IN ('default','bcrypt')
      AND COALESCE(e.with_cloudfront, false) = false
    GROUP BY e.id, e.auth_strategy
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 500
""")


@register
def rq4_dm_manual_p99_mono_l() -> Number:
    return Number(
        macro_name="rqFourDecisionMatrixManualBcryptPNineNineMonoL",
        group="rq4_decision_matrix",
        description=(
            "Manual (bcrypt/HS256) authentifizierte P99 auf Monolith L, "
            "Baseline. Zitiert in Sec. 6.7 als niedrigste authentifizierte "
            "P99-Latenz."
        ),
        thesis_refs=["evaluation.tex Sec. 6.7.1 (98 ms Zitat)"],
        sql=_MONO_L_MANUAL_SQL,
        compute=lambda df: _mean_p99(df, "service-integrated-manual"),
        format=de_ms,
        unit="ms",
    )
