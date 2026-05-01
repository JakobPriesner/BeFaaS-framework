"""Headline dataset numbers — total corpus, coverage, request counts."""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_int, de_millions, de_pct


@register
def num_experiments_total() -> Number:
    return Number(
        macro_name="numExperimentsTotal",
        group="dataset",
        description="Gesamtzahl aller Experimente in der Benchmark-Datenbank (vor Filterung).",
        thesis_refs=["evaluation.tex (Kap. 6 Einleitung)"],
        sql=textwrap.dedent("""\
            -- raw-corpus: intentionally reports pre-filter total
            SELECT COUNT(*) AS n FROM experiments
        """),
        compute=lambda df: int(df.iloc[0]["n"]),
        format=de_int,
        unit="Experimente",
        extract_ids=lambda df: [],
    )


@register
def num_experiments_usable() -> Number:
    return Number(
        macro_name="numExperimentsUsable",
        group="dataset",
        description="Auswertbare Experimente nach Ausschluss von Duplikaten und fehlerhaften Läufen.",
        thesis_refs=["evaluation.tex (Kap. 6 Einleitung)"],
        sql=textwrap.dedent("""\
            SELECT COUNT(DISTINCT e.id) AS n
            FROM experiments e
            WHERE {EXCLUDE_SQL}
        """),
        compute=lambda df: int(df.iloc[0]["n"]),
        format=de_int,
        unit="Experimente",
        extract_ids=lambda df: [],
    )


@register
def num_experiments_excluded() -> Number:
    return Number(
        macro_name="numExperimentsExcluded",
        group="dataset",
        description="Von der Analyse ausgeschlossene Experimente (Duplikat-Importe + Broken-Läufe).",
        thesis_refs=["evaluation.tex (Kap. 6 Einleitung)", "sec:appendix-acm"],
        sql=textwrap.dedent("""\
            -- raw-corpus: diff of raw total vs. filtered total
            SELECT
              (SELECT COUNT(*) FROM experiments)
              - (SELECT COUNT(DISTINCT e.id) FROM experiments e WHERE {EXCLUDE_SQL})
              AS n
        """),
        compute=lambda df: int(df.iloc[0]["n"]),
        format=de_int,
        unit="Experimente",
        extract_ids=lambda df: [],
    )


@register
def num_requests_total() -> Number:
    return Number(
        macro_name="numRequestsTotal",
        group="dataset",
        description="Gesamtzahl der in die Analyse eingehenden Anfragen (alle Phasen, alle Endpunkte).",
        thesis_refs=["evaluation.tex (Kap. 6 Einleitung)"],
        sql=textwrap.dedent("""\
            SELECT COUNT(*) AS n
            FROM requests r JOIN experiments e ON e.id = r.experiment_id
            WHERE {EXCLUDE_SQL}
        """),
        compute=lambda df: int(df.iloc[0]["n"]),
        format=de_millions,
        unit="Anfragen",
        extract_ids=lambda df: [],
    )


@register
def num_requests_baseline() -> Number:
    return Number(
        macro_name="numRequestsBaseline",
        group="dataset",
        description="In die Baseline-Analyse eingehende Anfragen (Baseline-Phase, gefilterte Experimente).",
        thesis_refs=["evaluation.tex (Sec. 6.2)"],
        sql=textwrap.dedent("""\
            SELECT COUNT(*) AS n
            FROM requests r JOIN experiments e ON e.id = r.experiment_id
            WHERE {EXCLUDE_SQL} AND r.phase_name = 'Baseline'
        """),
        compute=lambda df: int(df.iloc[0]["n"]),
        format=de_millions,
        unit="Anfragen",
        extract_ids=lambda df: [],
    )


@register
def traffic_pct_anonymous() -> Number:
    """Gesamt-Anteil anonymer Anfragen über alle Architekturen."""
    return Number(
        macro_name="trafficPctAnonymous",
        group="dataset",
        description=(
            "Anteil anonymer (nicht-authentifizierter) Anfragen am Gesamttraffic, "
            "aggregiert über alle Architekturen."
        ),
        thesis_refs=["evaluation.tex (Sec. 6.3, Einleitung RQ1)"],
        sql=textwrap.dedent("""\
            SELECT
              SUM(CASE WHEN
                ((e.architecture = 'faas'
                   AND r.endpoint IN ('/frontend/setUser', '/frontend/addCartItem',
                                      '/frontend/cart', '/frontend/checkout'))
                 OR (e.architecture <> 'faas'
                   AND r.endpoint IN ('/setUser', '/addCartItem',
                                      '/cart', '/checkout')))
                THEN 0 ELSE 1 END) AS n_anon,
              COUNT(*) AS n_total
            FROM requests r JOIN experiments e ON e.id = r.experiment_id
            WHERE {EXCLUDE_SQL}
        """),
        compute=lambda df: 100.0 * df.iloc[0]["n_anon"] / df.iloc[0]["n_total"],
        format=de_pct,
        unit="%",
        extract_ids=lambda df: [],
    )


@register
def traffic_pct_authenticated() -> Number:
    return Number(
        macro_name="trafficPctAuthenticated",
        group="dataset",
        description="Anteil authentifizierter Anfragen am Gesamttraffic.",
        thesis_refs=["evaluation.tex (Sec. 6.3, Einleitung RQ1)"],
        sql=textwrap.dedent("""\
            SELECT
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
        """),
        compute=lambda df: 100.0 * df.iloc[0]["n_auth"] / df.iloc[0]["n_total"],
        format=de_pct,
        unit="%",
        extract_ids=lambda df: [],
    )
