"""Dataset -- per-architecture traffic split (authenticated vs anonymous).

Die Thesis zitiert an mehreren Stellen den Anteil authentifizierter vs.
anonymer Anfragen nicht aggregiert, sondern je Architektur. Dieses Modul
berechnet pro Architektur min/max der Anteile authentifizierter Anfragen.
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_pct


_TRAFFIC_BY_EXP_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      e.architecture,
      SUM(CASE WHEN
        ((e.architecture = 'faas'
           AND r.endpoint IN ('/frontend/setUser', '/frontend/addCartItem',
                              '/frontend/cart', '/frontend/checkout'))
         OR (e.architecture <> 'faas'
           AND r.endpoint IN ('/setUser', '/addCartItem',
                              '/cart', '/checkout')))
        THEN 1 ELSE 0 END) AS n_auth,
      COUNT(*) AS n_total
    FROM requests r JOIN experiments e ON e.id = r.experiment_id
    WHERE {EXCLUDE_SQL}
      AND e.auth_strategy <> 'none'
      AND e.auth_strategy <> 'edge-selective'
    GROUP BY e.id, e.architecture
    HAVING COUNT(*) > 1000
""")


def _pct_auth_min(df) -> float:
    if df.empty:
        return float("nan")
    rates = (df["n_auth"] / df["n_total"] * 100.0).astype(float)
    return float(rates.min())


def _pct_auth_max(df) -> float:
    if df.empty:
        return float("nan")
    rates = (df["n_auth"] / df["n_total"] * 100.0).astype(float)
    return float(rates.max())


def _pct_anon_min(df) -> float:
    if df.empty:
        return float("nan")
    rates = (1.0 - df["n_auth"] / df["n_total"]).astype(float) * 100.0
    return float(rates.min())


def _pct_anon_max(df) -> float:
    if df.empty:
        return float("nan")
    rates = (1.0 - df["n_auth"] / df["n_total"]).astype(float) * 100.0
    return float(rates.max())


@register
def traffic_pct_auth_min_all() -> Number:
    return Number(
        macro_name="trafficPctAuthMinAll",
        group="dataset",
        description=(
            "Minimaler Anteil authentifizierter Anfragen je Experiment ueber "
            "den gesamten Korpus (untere Grenze des im Fliesstext zitierten Bereichs)."
        ),
        thesis_refs=["evaluation.tex Kap. 6 Einleitung (16--23 Prozent-Zitat)"],
        sql=_TRAFFIC_BY_EXP_SQL,
        compute=_pct_auth_min,
        format=de_pct,
        unit="%",
    )


@register
def traffic_pct_auth_max_all() -> Number:
    return Number(
        macro_name="trafficPctAuthMaxAll",
        group="dataset",
        description=(
            "Maximaler Anteil authentifizierter Anfragen je Experiment (obere "
            "Grenze des Bereichs 16--23 Prozent)."
        ),
        thesis_refs=["evaluation.tex Kap. 6 Einleitung"],
        sql=_TRAFFIC_BY_EXP_SQL,
        compute=_pct_auth_max,
        format=de_pct,
        unit="%",
    )


@register
def traffic_pct_anon_min_all() -> Number:
    return Number(
        macro_name="trafficPctAnonMinAll",
        group="dataset",
        description="Minimaler Anteil anonymer Anfragen je Experiment (Komplement zum Auth-Anteil).",
        thesis_refs=["evaluation.tex Sec. 6.3.1 (77,3--83,8 Prozent anonym)"],
        sql=_TRAFFIC_BY_EXP_SQL,
        compute=_pct_anon_min,
        format=de_pct,
        unit="%",
    )


@register
def traffic_pct_anon_max_all() -> Number:
    return Number(
        macro_name="trafficPctAnonMaxAll",
        group="dataset",
        description="Maximaler Anteil anonymer Anfragen je Experiment.",
        thesis_refs=["evaluation.tex Sec. 6.3.1 (77,3--83,8 Prozent anonym)"],
        sql=_TRAFFIC_BY_EXP_SQL,
        compute=_pct_anon_max,
        format=de_pct,
        unit="%",
    )
