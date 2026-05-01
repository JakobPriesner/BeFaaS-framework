"""RQ4 — Architekturübergreifender Angleichungseffekt (Befund 17).

Der Cognito-Anteil überlagert architekturspezifische Basislatenzen, sobald
mehrere verifizierende Komponenten im Anfragepfad liegen. Am Vergleichspunkt
FaaS 1024\\,MB vs. Mono/L (je $\\approx$ 1 vCPU) sinkt der P99-Faktor
Mono$\\leftrightarrow$FaaS von 16,2$\\times$ (None) auf 3,2$\\times$ (Cognito).

Diese Numbers reproduzieren die beiden Faktoren aus Tab. 6.10
(equalizing_table) direkt aus den Experiment-IDs.
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ratio_times


# Baseline-P99 über alle Endpunkte für eine feste Experiment-ID
_P99_BY_EXP_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
          FILTER (WHERE NOT r.is_error) AS p99
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {{EXCLUDE_SQL}}
      AND r.phase_name = 'Baseline'
      AND e.id IN ({exp_ids})
    GROUP BY e.id
""")


# Representative pairs from evaluation.tex:1357 footnote
_EQUALIZE_PAIRS = {
    # key → (faas_exp_id, mono_exp_id)
    "none":    (42, 30),   # FaaS 1024 None (E42), Mono/L None (E30)
    "cognito": (120, 36),  # FaaS 1024 Cognito (E120), Mono/L Cognito (E36)
}

_ALL_IDS = sorted({i for pair in _EQUALIZE_PAIRS.values() for i in pair})


def _factor(df, faas_id: int, mono_id: int) -> float:
    by_id = df.set_index("id")["p99"].to_dict()
    faas_p99 = by_id.get(faas_id, float("nan"))
    mono_p99 = by_id.get(mono_id, float("nan"))
    if mono_p99 > 0 and faas_p99 > 0:
        return float(faas_p99 / mono_p99)
    return float("nan")


@register
def rq4_equalize_factor_none() -> Number:
    faas_id, mono_id = _EQUALIZE_PAIRS["none"]
    return Number(
        macro_name="rqFourEqualizeFactorNone",
        group="rq4_equalizing",
        description=(
            "P99-Faktor FaaS/Mono (je 1 vCPU) ohne Authentifizierung. "
            "Zitiert in Befund 17 als 16,2$\\times$."
        ),
        thesis_refs=["evaluation.tex Sec. 6.6.3 (Befund 17)", "Tab. 6.10 equalizing_table"],
        sql=_P99_BY_EXP_SQL.format(exp_ids=",".join(str(i) for i in _ALL_IDS)),
        compute=lambda df, fid=faas_id, mid=mono_id: _factor(df, fid, mid),
        format=de_ratio_times,
        unit="x",
        extract_ids=lambda df: _ALL_IDS,
    )


@register
def rq4_equalize_factor_cognito() -> Number:
    faas_id, mono_id = _EQUALIZE_PAIRS["cognito"]
    return Number(
        macro_name="rqFourEqualizeFactorCognito",
        group="rq4_equalizing",
        description=(
            "P99-Faktor FaaS/Mono (je 1 vCPU) mit Cognito. "
            "Zitiert in Befund 17 als 3,2$\\times$ (Kompression gegenüber None)."
        ),
        thesis_refs=["evaluation.tex Sec. 6.6.3 (Befund 17)", "Tab. 6.10 equalizing_table"],
        sql=_P99_BY_EXP_SQL.format(exp_ids=",".join(str(i) for i in _ALL_IDS)),
        compute=lambda df, fid=faas_id, mid=mono_id: _factor(df, fid, mid),
        format=de_ratio_times,
        unit="x",
        extract_ids=lambda df: _ALL_IDS,
    )
