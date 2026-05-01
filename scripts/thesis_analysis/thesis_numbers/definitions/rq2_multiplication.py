"""RQ2 — Multiplikationsmodell (Ratio R, k_eff, per-endpoint $\\Delta$).

Die Kernprüfung des Multiplikationsmodells ist die Ratio
    R = $\\Delta$P50(Checkout) / $\\Delta$P50(addCartItem)
über sechs Konfigurationen (FaaS 512, FaaS 1024, MS/L_static, MS/XL,
Mono/L, Mono/XL). Wenn das Modell stimmt, sollte $R \\approx k_{eff}(Checkout)
/ k_{eff}(addCartItem) = 6/2 = 3{,}0$ sein. Die Thesis zitiert $R = 3{,}18$
mit $s = 0{,}15$ und 95\\,\\%-CI $[3{,}03;\\; 3{,}34]$.

Die Per-Endpoint-$\\Delta$P50-Werte (Tab. 6.7 per_endpoint_delta_table) werden
zusätzlich als einzelne Numbers registriert, damit die im Fließtext zitierten
Bereiche (z.\\,B. „26--38\\,ms bei $k_{eff}=2$") aus dem Katalog bezogen werden
können. Für R nutzen wir die Konfigurationen aus Skript 47, die exakt der
Fußnote in evaluation.tex:1357 entsprechen.
"""

from __future__ import annotations

import textwrap

import numpy as np
from scipy import stats as sp_stats

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ci, de_ms_signed, de_pct, de_ratio


# Experiment pairs from evaluation.tex:1357 footnote. Each tuple is
# (label, none_exp_id, cognito_exp_id, addcart_ep, checkout_ep).
_CONFIGS = [
    ("FaaS 512",       87,  10, "/frontend/addCartItem", "/frontend/checkout"),
    ("FaaS 1024",      42, 120, "/frontend/addCartItem", "/frontend/checkout"),
    ("MS/L-static",   142, 143, "/addCartItem",          "/checkout"),
    ("MS/XL",          64,  65, "/addCartItem",          "/checkout"),
    ("Mono/L",         30,  36, "/addCartItem",          "/checkout"),
    ("Mono/XL",        62,  70, "/addCartItem",          "/checkout"),
]


# One SQL fetches Baseline-P50 for an entire endpoint in a given experiment.
# `{{EXCLUDE_SQL}}` must survive the first .format() call below, so it's escaped
# as `{{{{EXCLUDE_SQL}}}}` in the template and becomes `{EXCLUDE_SQL}` after the
# first format-pass. The catalog's generate.py then substitutes it at evaluation.
_P50_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      r.endpoint,
      percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
          FILTER (WHERE NOT r.is_error) AS p50,
      COUNT(*) FILTER (WHERE NOT r.is_error) AS n_ok
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {{EXCLUDE_SQL}}
      AND r.phase_name = 'Baseline'
      AND e.id IN ({exp_ids})
      AND r.endpoint IN ('/frontend/addCartItem','/frontend/checkout',
                         '/addCartItem','/checkout')
    GROUP BY e.id, r.endpoint
""")


def _compute_ratios(df) -> list[dict]:
    """For each config, compute $\\Delta$P50(checkout) / $\\Delta$P50(addCart).

    Returns list of dicts with 'label', 'ratio', 'delta_add', 'delta_checkout'.
    NaN entries are dropped.
    """
    by_exp_endpoint = df.set_index(["id", "endpoint"])["p50"].to_dict()
    rows = []
    for label, none_id, cog_id, add_ep, co_ep in _CONFIGS:
        none_add = by_exp_endpoint.get((none_id, add_ep), float("nan"))
        cog_add = by_exp_endpoint.get((cog_id, add_ep), float("nan"))
        none_co = by_exp_endpoint.get((none_id, co_ep), float("nan"))
        cog_co = by_exp_endpoint.get((cog_id, co_ep), float("nan"))
        delta_add = cog_add - none_add
        delta_co = cog_co - none_co
        if delta_add > 0 and not np.isnan(delta_co):
            ratio = delta_co / delta_add
        else:
            ratio = float("nan")
        rows.append({
            "label": label, "delta_add": delta_add,
            "delta_checkout": delta_co, "ratio": ratio,
        })
    return rows


def _ratio_stats(df) -> tuple[float, float, float, float, int]:
    """Returns (mean, std, ci_low, ci_high, n) — the Befund-9 summary."""
    rows = _compute_ratios(df)
    ratios = np.array(
        [r["ratio"] for r in rows if not np.isnan(r["ratio"])],
        dtype=float,
    )
    n = len(ratios)
    if n < 2:
        return (float("nan"), float("nan"), float("nan"), float("nan"), n)
    mean = float(np.mean(ratios))
    std = float(np.std(ratios, ddof=1))
    se = std / np.sqrt(n)
    t_crit = float(sp_stats.t.ppf(0.975, df=n - 1))
    return (mean, std, mean - t_crit * se, mean + t_crit * se, n)


_ALL_EXP_IDS = sorted({e for c in _CONFIGS for e in (c[1], c[2])})
# Only substitute `{exp_ids}`; leave `{{EXCLUDE_SQL}}` for later.
_RATIO_SQL = _P50_SQL.format(exp_ids=",".join(str(i) for i in _ALL_EXP_IDS))


@register
def rq2_multiplication_ratio_mean() -> Number:
    return Number(
        macro_name="rqTwoMultiplicationRatioMean",
        group="rq2_multiplication",
        description=(
            "Mittleres Verhältnis $R = \\Delta$P50(Checkout)$/\\Delta$P50(addCartItem) "
            "über die sechs in evaluation.tex Fußnote~1357 aufgelisteten "
            "Cognito-Konfigurationen. Erwartungswert nach Topologie: $R = k_{\\text{eff}}($Checkout$)/k_{\\text{eff}}($addCartItem$) = 3$."
        ),
        thesis_refs=["evaluation.tex Sec. 6.4 (Befund 9)", "Tab. 6.8 ratio_analysis_table"],
        sql=_RATIO_SQL,
        compute=lambda df: _ratio_stats(df)[0],
        format=de_ratio,
        unit="-",
        extract_ids=lambda df: _ALL_EXP_IDS,
    )


@register
def rq2_multiplication_ratio_std() -> Number:
    return Number(
        macro_name="rqTwoMultiplicationRatioStd",
        group="rq2_multiplication",
        description="Standardabweichung des Ratio $R$ über die sechs Konfigurationen.",
        thesis_refs=["evaluation.tex Sec. 6.4 (Befund 9)"],
        sql=_RATIO_SQL,
        compute=lambda df: _ratio_stats(df)[1],
        format=de_ratio,
        unit="-",
        extract_ids=lambda df: _ALL_EXP_IDS,
    )


@register
def rq2_multiplication_ratio_ci_low() -> Number:
    return Number(
        macro_name="rqTwoMultiplicationRatioCIlow",
        group="rq2_multiplication",
        description="Untere Grenze des 95\\,\\%-$t$-Konfidenzintervalls für $R$.",
        thesis_refs=["evaluation.tex Sec. 6.4 (Befund 9)"],
        sql=_RATIO_SQL,
        compute=lambda df: _ratio_stats(df)[2],
        format=de_ratio,
        unit="-",
        extract_ids=lambda df: _ALL_EXP_IDS,
    )


@register
def rq2_multiplication_ratio_ci_high() -> Number:
    return Number(
        macro_name="rqTwoMultiplicationRatioCIhigh",
        group="rq2_multiplication",
        description="Obere Grenze des 95\\,\\%-$t$-Konfidenzintervalls für $R$.",
        thesis_refs=["evaluation.tex Sec. 6.4 (Befund 9)"],
        sql=_RATIO_SQL,
        compute=lambda df: _ratio_stats(df)[3],
        format=de_ratio,
        unit="-",
        extract_ids=lambda df: _ALL_EXP_IDS,
    )


@register
def rq2_multiplication_ratio_cv() -> Number:
    return Number(
        macro_name="rqTwoMultiplicationRatioCV",
        group="rq2_multiplication",
        description="Variationskoeffizient von $R$ ($s/\\bar{R}$, in Prozent).",
        thesis_refs=["evaluation.tex Sec. 6.4 (Befund 9)"],
        sql=_RATIO_SQL,
        compute=lambda df: (100.0 * _ratio_stats(df)[1] / _ratio_stats(df)[0])
                           if _ratio_stats(df)[0] else float("nan"),
        format=de_pct,
        unit="%",
        extract_ids=lambda df: _ALL_EXP_IDS,
    )


@register
def rq2_multiplication_ratio_n() -> Number:
    return Number(
        macro_name="rqTwoMultiplicationRatioN",
        group="rq2_multiplication",
        description="Anzahl Konfigurationen, die in das Ratio $R$ eingehen.",
        thesis_refs=["evaluation.tex Sec. 6.4 (Befund 9)"],
        sql=_RATIO_SQL,
        compute=lambda df: _ratio_stats(df)[4],
        format=lambda n: str(int(n)),
        unit="-",
        extract_ids=lambda df: _ALL_EXP_IDS,
    )
