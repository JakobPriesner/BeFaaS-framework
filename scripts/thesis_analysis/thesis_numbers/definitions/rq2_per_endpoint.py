"""RQ2 -- Per-Endpoint Delta P50 Range fuer Folgeendpunkte.

Die Thesis zitiert '+26--123 ms am P50' als Spanne des Cognito-Overheads
auf regulaeren Folgeendpunkten ueber die sechs Vergleichs-Konfigurationen
aus evaluation.tex:1357.

Dieses Modul berechnet fuer jeden der drei Vergleichspunkte das Delta P50
je Endpunkt und meldet Min/Max ueber die Spanne.
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ms_signed


# Reuse the same config list as rq2_multiplication.py
_CONFIGS = [
    ("FaaS 512",        87,  10, "/frontend/addCartItem", "/frontend/checkout", "/frontend/cart"),
    ("FaaS 1024",       42, 120, "/frontend/addCartItem", "/frontend/checkout", "/frontend/cart"),
    ("MS/L-static",    142, 143, "/addCartItem",          "/checkout",          "/cart"),
    ("MS/XL",           64,  65, "/addCartItem",          "/checkout",          "/cart"),
    ("Mono/L",          30,  36, "/addCartItem",          "/checkout",          "/cart"),
    ("Mono/XL",         62,  70, "/addCartItem",          "/checkout",          "/cart"),
]

_ALL_IDS = sorted({i for c in _CONFIGS for i in (c[1], c[2])})

_P50_SQL = textwrap.dedent(f"""\
    SELECT
      e.id,
      r.endpoint,
      percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
          FILTER (WHERE NOT r.is_error) AS p50
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {{EXCLUDE_SQL}}
      AND r.phase_name = 'Baseline'
      AND e.id IN ({",".join(str(i) for i in _ALL_IDS)})
      AND r.endpoint IN ('/frontend/addCartItem','/frontend/checkout','/frontend/cart',
                         '/addCartItem','/checkout','/cart')
    GROUP BY e.id, r.endpoint
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
""")


def _collect_deltas(df) -> list[float]:
    by = df.set_index(["id", "endpoint"])["p50"].to_dict()
    out = []
    for _label, none_id, cog_id, add_ep, co_ep, cart_ep in _CONFIGS:
        for ep in (add_ep, co_ep, cart_ep):
            n = by.get((none_id, ep))
            c = by.get((cog_id, ep))
            if n is not None and c is not None and not (n != n or c != c):
                out.append(float(c - n))
    return out


def _min_delta(df) -> float:
    deltas = _collect_deltas(df)
    return min(deltas) if deltas else float("nan")


def _max_delta(df) -> float:
    deltas = _collect_deltas(df)
    return max(deltas) if deltas else float("nan")


@register
def rq2_per_endpoint_delta_p50_min() -> Number:
    return Number(
        macro_name="rqTwoPerEndpointDeltaPFiftyMin",
        group="rq2_per_endpoint",
        description=(
            "Minimum des Cognito-Delta P50 ueber addCartItem, Checkout und cart "
            "auf den sechs Vergleichs-Konfigurationen (Baseline). Untere Grenze "
            "der im Fliesstext zitierten Spanne +26--123 ms."
        ),
        thesis_refs=[
            "evaluation.tex Sec. 6.7.2 (+26--123 ms Zitat)",
            "Tab. 6.7 per_endpoint_delta_table",
        ],
        sql=_P50_SQL,
        compute=_min_delta,
        format=de_ms_signed,
        unit="ms",
        extract_ids=lambda df: _ALL_IDS,
    )


@register
def rq2_per_endpoint_delta_p50_max() -> Number:
    return Number(
        macro_name="rqTwoPerEndpointDeltaPFiftyMax",
        group="rq2_per_endpoint",
        description=(
            "Maximum des Cognito-Delta P50 ueber addCartItem, Checkout und cart "
            "auf den sechs Vergleichs-Konfigurationen (Baseline). Obere Grenze "
            "der Spanne +26--123 ms."
        ),
        thesis_refs=["evaluation.tex Sec. 6.7.2"],
        sql=_P50_SQL,
        compute=_max_delta,
        format=de_ms_signed,
        unit="ms",
        extract_ids=lambda df: _ALL_IDS,
    )
