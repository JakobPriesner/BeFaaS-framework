"""RQ2 -- Kaskadenversagen Lambda@Edge + Microservices.

Befund 13: Edge-Authentifizierung auf unterdimensionierten (S-Tier,
0,25 vCPU) Microservices erzeugt 5xx-Fehlerraten von 13--24 Prozent
waehrend der Morning-Rush-Phase. Der Effekt verschwindet bei M-Tier
(<= 1,1 Prozent), L-Tier (~0,7 Prozent) und FaaS/Mono (<1 Prozent).

Dieses Modul rechnet die zentralen Fehlerraten aus der Datenbank nach.
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_pct


_FIVEXX_PHASE_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      e.architecture,
      COALESCE(e.cpu_in_vcpu, 0) AS cpu,
      e.auth_strategy,
      COUNT(*) FILTER (WHERE r.status_code >= 500 AND r.status_code < 600) AS n_5xx,
      COUNT(*) AS n_total
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {{EXCLUDE_SQL}}
      AND e.architecture = '{arch}'
      AND {hw_pred}
      AND e.auth_strategy = '{auth}'
      AND COALESCE(e.with_cloudfront, false) = false
      AND r.phase_name = '{phase}'
    GROUP BY e.id, e.architecture, e.cpu_in_vcpu, e.auth_strategy
    HAVING COUNT(*) > 1000
""")


def _mean_5xx_pct(df) -> float:
    if df.empty:
        return float("nan")
    rates = (df["n_5xx"] / df["n_total"] * 100.0).astype(float)
    return float(rates.mean())


def _max_5xx_pct(df) -> float:
    if df.empty:
        return float("nan")
    rates = (df["n_5xx"] / df["n_total"] * 100.0).astype(float)
    return float(rates.max())


def _min_5xx_pct(df) -> float:
    if df.empty:
        return float("nan")
    rates = (df["n_5xx"] / df["n_total"] * 100.0).astype(float)
    return float(rates.min())


@register
def rq2_cascade_mean_ms_edge_s_morning() -> Number:
    return Number(
        macro_name="rqTwoCascadeMeanMsEdgeSMorning",
        group="rq2_cascading",
        description=(
            "Mittlere 5xx-Fehlerrate waehrend der Morning-Rush-Phase auf "
            "Microservices/Edge/S-Tier ueber alle Wiederholungen."
        ),
        thesis_refs=["evaluation.tex Sec. 6.4.3 (Befund 13)", "Tab. 6.9 edge_cascade_hw_table"],
        sql=_FIVEXX_PHASE_SQL.format(
            arch="microservices",
            hw_pred="COALESCE(e.cpu_in_vcpu, 0) = 0.25",
            auth="edge",
            phase="Morning rush",
        ),
        compute=_mean_5xx_pct,
        format=de_pct,
        unit="%",
    )


@register
def rq2_cascade_min_ms_edge_s_morning() -> Number:
    return Number(
        macro_name="rqTwoCascadeMinMsEdgeSMorning",
        group="rq2_cascading",
        description=(
            "Minimale 5xx-Fehlerrate Morning Rush auf Microservices/Edge/S-Tier. "
            "Bildet die untere Grenze des im Fliesstext zitierten Bereichs 13--24 Prozent."
        ),
        thesis_refs=["evaluation.tex Sec. 6.4.3 (Befund 13)"],
        sql=_FIVEXX_PHASE_SQL.format(
            arch="microservices",
            hw_pred="COALESCE(e.cpu_in_vcpu, 0) = 0.25",
            auth="edge",
            phase="Morning rush",
        ),
        compute=_min_5xx_pct,
        format=de_pct,
        unit="%",
    )


@register
def rq2_cascade_max_ms_edge_s_morning() -> Number:
    return Number(
        macro_name="rqTwoCascadeMaxMsEdgeSMorning",
        group="rq2_cascading",
        description=(
            "Maximale 5xx-Fehlerrate Morning Rush auf Microservices/Edge/S-Tier. "
            "Obere Grenze des Bereichs 13--24 Prozent."
        ),
        thesis_refs=["evaluation.tex Sec. 6.4.3 (Befund 13)"],
        sql=_FIVEXX_PHASE_SQL.format(
            arch="microservices",
            hw_pred="COALESCE(e.cpu_in_vcpu, 0) = 0.25",
            auth="edge",
            phase="Morning rush",
        ),
        compute=_max_5xx_pct,
        format=de_pct,
        unit="%",
    )


@register
def rq2_cascade_mean_ms_edge_m_morning() -> Number:
    return Number(
        macro_name="rqTwoCascadeMeanMsEdgeMMorning",
        group="rq2_cascading",
        description=(
            "Mittlere 5xx-Fehlerrate Morning Rush auf Microservices/Edge/M-Tier. "
            "Im Fliesstext als ca. 1,1 Prozent zitiert; Kaskaden-Befund verschwindet ab M."
        ),
        thesis_refs=["evaluation.tex Sec. 6.4.3 (Befund 13)"],
        sql=_FIVEXX_PHASE_SQL.format(
            arch="microservices",
            hw_pred="COALESCE(e.cpu_in_vcpu, 0) = 0.5",
            auth="edge",
            phase="Morning rush",
        ),
        compute=_mean_5xx_pct,
        format=de_pct,
        unit="%",
    )


@register
def rq2_cascade_mean_ms_edge_l_morning() -> Number:
    return Number(
        macro_name="rqTwoCascadeMeanMsEdgeLMorning",
        group="rq2_cascading",
        description=(
            "Mittlere 5xx-Fehlerrate Morning Rush auf Microservices/Edge/L-Tier. "
            "Im Fliesstext als ca. 0,7 Prozent zitiert."
        ),
        thesis_refs=["evaluation.tex Sec. 6.4.3 (Befund 13)"],
        sql=_FIVEXX_PHASE_SQL.format(
            arch="microservices",
            hw_pred="COALESCE(e.cpu_in_vcpu, 0) = 1.0",
            auth="edge",
            phase="Morning rush",
        ),
        compute=_mean_5xx_pct,
        format=de_pct,
        unit="%",
    )


@register
def rq2_cascade_mean_ms_none_s_morning() -> Number:
    return Number(
        macro_name="rqTwoCascadeMeanMsNoneSMorning",
        group="rq2_cascading",
        description=(
            "Kontrollbedingung: Microservices/None/S-Tier Morning Rush. "
            "Im Fliesstext zitiert als unter 1,2 Prozent (zeigt, dass der Kaskadeneffekt Edge-spezifisch ist)."
        ),
        thesis_refs=["evaluation.tex Sec. 6.4.3 (Befund 13)"],
        sql=_FIVEXX_PHASE_SQL.format(
            arch="microservices",
            hw_pred="COALESCE(e.cpu_in_vcpu, 0) = 0.25",
            auth="none",
            phase="Morning rush",
        ),
        compute=_mean_5xx_pct,
        format=de_pct,
        unit="%",
    )
