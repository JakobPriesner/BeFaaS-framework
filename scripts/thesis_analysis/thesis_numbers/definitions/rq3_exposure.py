"""RQ3 -- Token-Exposure und Replay-Fenster.

Die meisten RQ3-Zahlen sind strukturell, nicht datenbankgetrieben:
Token-Expositionszahlen (17/2/1) folgen aus der Architektur-Implementation,
nicht aus einer Messung. Sie werden trotzdem als Number registriert, damit
sie im Provenance-Appendix zusammen mit ihrer Herleitung dokumentiert
werden. Die SQL-Abfragen sind daher einfache Konstanten-Selects mit dem
Marker `-- raw-structural` (analog zu `-- raw-corpus` in dataset.py).

Die Token-TTL-Werte (45 s Edge, 60 min Cognito) sind ebenfalls strukturell:
Sie spiegeln die Implementierungs-Konfiguration wider (vgl. Definition
token-transform und Cognito-Konfiguration).
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ratio, de_ratio_times


@register
def rq3_exposure_faas_dienstintegriert() -> Number:
    return Number(
        macro_name="rqThreeExposureFaasDienstintegriert",
        group="rq3_exposure",
        description=(
            "Anzahl Komponenten mit produktiver Token-Sicht bei "
            "dienstintegrierter Authentifizierung auf FaaS. Jede Lambda-Funktion "
            "verifiziert das Token eigenstaendig gegen die Cognito-API."
        ),
        thesis_refs=["evaluation.tex Tab. 6.11 token_exposure", "Befund 14"],
        sql=textwrap.dedent("""\
            -- raw-structural: token exposure count derived from architecture
            SELECT 17 AS n
        """),
        compute=lambda df: int(df.iloc[0]["n"]),
        format=lambda n: str(int(n)),
        unit="Komponenten",
        extract_ids=lambda df: [],
    )


@register
def rq3_exposure_ms_dienstintegriert() -> Number:
    return Number(
        macro_name="rqThreeExposureMsDienstintegriert",
        group="rq3_exposure",
        description=(
            "Token-Exposition auf Microservices mit dienstintegrierter "
            "Authentifizierung. Zwei ECS-Dienste (Cart, Order) verifizieren Tokens."
        ),
        thesis_refs=["evaluation.tex Tab. 6.11", "Befund 14"],
        sql=textwrap.dedent("""\
            -- raw-structural
            SELECT 2 AS n
        """),
        compute=lambda df: int(df.iloc[0]["n"]),
        format=lambda n: str(int(n)),
        unit="Komponenten",
        extract_ids=lambda df: [],
    )


@register
def rq3_exposure_mono_dienstintegriert() -> Number:
    return Number(
        macro_name="rqThreeExposureMonoDienstintegriert",
        group="rq3_exposure",
        description=(
            "Token-Exposition auf Monolith mit dienstintegrierter "
            "Authentifizierung. Ein einzelner Prozess verifiziert Tokens."
        ),
        thesis_refs=["evaluation.tex Tab. 6.11", "Befund 14"],
        sql=textwrap.dedent("""\
            -- raw-structural
            SELECT 1 AS n
        """),
        compute=lambda df: int(df.iloc[0]["n"]),
        format=lambda n: str(int(n)),
        unit="Komponenten",
        extract_ids=lambda df: [],
    )


@register
def rq3_exposure_edge_all() -> Number:
    return Number(
        macro_name="rqThreeExposureEdgeAll",
        group="rq3_exposure",
        description=(
            "Token-Exposition bei Edge-Authentifizierung, architekturunabhaengig. "
            "Nur die Lambda@Edge-Funktion sieht das externe Token; Backend-Komponenten "
            "verarbeiten nur das transformierte interne Token."
        ),
        thesis_refs=["evaluation.tex Tab. 6.11", "Befund 14"],
        sql=textwrap.dedent("""\
            -- raw-structural
            SELECT 1 AS n
        """),
        compute=lambda df: int(df.iloc[0]["n"]),
        format=lambda n: str(int(n)),
        unit="Komponenten",
        extract_ids=lambda df: [],
    )


@register
def rq3_exposure_ratio_faas_edge() -> Number:
    return Number(
        macro_name="rqThreeExposureRatioFaasEdge",
        group="rq3_exposure",
        description=(
            "Reduktionsfaktor der Token-Exposition bei Wechsel von "
            "dienstintegrierter Cognito/Manual (17 Komponenten) zu Edge (1 Komponente) "
            "auf FaaS. Zitiert in Befund 14 als 17-fache Reduktion."
        ),
        thesis_refs=["evaluation.tex Sec. 6.5.2 (Befund 14)"],
        sql=textwrap.dedent("""\
            -- raw-structural: exposure reduction factor
            SELECT 17.0 AS ratio
        """),
        compute=lambda df: float(df.iloc[0]["ratio"]),
        format=de_ratio_times,
        unit="x",
        extract_ids=lambda df: [],
    )


@register
def rq3_replay_window_ratio() -> Number:
    return Number(
        macro_name="rqThreeReplayWindowRatio",
        group="rq3_exposure",
        description=(
            "Verhaeltnis Cognito-Replay-Fenster (60 min = 3600 s) zu "
            "Edge-Replay-Fenster (\\texttt{delta\\_int} = 45 s) aus Definition token-transform. "
            "Zitiert in Befund 14 als 80-fach kuerzeres Replay-Fenster."
        ),
        thesis_refs=["evaluation.tex Sec. 6.5.2 (Proposition P2)"],
        sql=textwrap.dedent("""\
            -- raw-structural: replay-window ratio derived from impl. config
            SELECT (3600.0 / 45.0) AS ratio
        """),
        compute=lambda df: float(df.iloc[0]["ratio"]),
        format=lambda v: f"{int(round(v))}",
        unit="-",
        extract_ids=lambda df: [],
    )
