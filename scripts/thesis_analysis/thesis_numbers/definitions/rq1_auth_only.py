"""RQ1 — $\\Delta$Auth auf authentifizierten Endpunkten.

Diese Gruppe beschränkt die Perzentile auf die vier geschützten Endpunkte
(`setUser`, `addCartItem`, `cart`, `checkout`). Ohne diese Isolation
verdünnt der hohe Anteil anonymen Traffics den sichtbaren $\\Delta$Auth.

Die Matrixdefinition ist spiegelsymmetrisch zu `rq1_aggregate`: sie erzeugt
dieselben (Architektur, Hardware, Auth)-Kombinationen, rechnet aber mit
einem zusätzlichen Endpunkt-Prädikat.
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ms_signed


_AUTH_ONLY_P99_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      e.auth_strategy,
      COALESCE(e.password_hash_algorithm, 'default') AS algo,
      percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
          FILTER (WHERE NOT r.is_error) AS p99,
      percentile_cont(0.50) WITHIN GROUP (ORDER BY r.latency_ms)
          FILTER (WHERE NOT r.is_error) AS p50
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {{EXCLUDE_SQL}}
      AND r.phase_name = 'Baseline'
      AND e.architecture = '{arch}'
      AND {hw_pred}
      AND e.auth_strategy IN ('none', '{auth}')
      AND COALESCE(e.with_cloudfront, false) = false
      AND (
        (e.architecture = 'faas'
          AND r.endpoint IN ('/frontend/setUser','/frontend/addCartItem',
                             '/frontend/cart','/frontend/checkout'))
        OR
        (e.architecture <> 'faas'
          AND r.endpoint IN ('/setUser','/addCartItem','/cart','/checkout'))
      )
      {algo_pred}
    GROUP BY e.id, e.auth_strategy, e.password_hash_algorithm
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 50
""")


_HW_FAAS = [
    ("TwoFiveSix",    "e.ram_in_mb = 256",  "256\\,MB"),
    ("FiveTwelve",    "e.ram_in_mb = 512",  "512\\,MB"),
    ("TenTwentyFour", "e.ram_in_mb = 1024", "1024\\,MB"),
    ("SeventeenSixtyNine", "e.ram_in_mb = 1769", "1769\\,MB"),
]

_HW_CT = [
    ("S",  "COALESCE(e.cpu_in_vcpu,0) = 0.25", "Tier~S"),
    ("M",  "COALESCE(e.cpu_in_vcpu,0) = 0.5",  "Tier~M"),
    ("L",  "COALESCE(e.cpu_in_vcpu,0) = 1.0",  "Tier~L"),
    ("XL", "COALESCE(e.cpu_in_vcpu,0) = 4.0",  "Tier~XL"),
]

_AUTHS = [
    ("Cognito",      "service-integrated",        "",                                                                         "Cognito"),
    ("Edge",         "edge",                      "",                                                                         "Edge"),
    ("ManualBcrypt", "service-integrated-manual", "AND COALESCE(e.password_hash_algorithm,'default') IN ('default','bcrypt')", "Manual bcrypt/HS256"),
    ("ManualArgon",  "service-integrated-manual", "AND e.password_hash_algorithm = 'argon2id'",                               "Manual argon2id/EdDSA"),
]

_ARCHS = [
    ("Faas", "faas", _HW_FAAS),
    ("Ms",   "microservices", _HW_CT),
    ("Mono", "monolith", _HW_CT),
]


def _make(
    metric: str,
    arch_tag: str, arch: str,
    hw_tag: str, hw_pred: str, hw_label: str,
    auth_tag: str, auth: str, algo_pred: str, auth_label: str,
) -> Number:
    metric_tag = {"p99": "PNineNine", "p50": "PFifty"}[metric]
    metric_label = {"p99": "$\\Delta$P99", "p50": "$\\Delta$P50"}[metric]
    col = "p99" if metric == "p99" else "p50"

    def _delta(df, strategy=auth, col=col):
        auth_vals = df[df.auth_strategy == strategy][col]
        none_vals = df[df.auth_strategy == "none"][col]
        if auth_vals.empty or none_vals.empty:
            return float("nan")
        return float(auth_vals.mean() - none_vals.mean())

    return Number(
        macro_name=f"rqOneAuthOnlyDelta{metric_tag}{arch_tag}{hw_tag}{auth_tag}",
        group="rq1_auth_only",
        description=(
            f"{metric_label} ({auth_label} vs. None) auf authentifizierten "
            f"Endpunkten, {arch_tag} {hw_label}, Baseline-Phase."
        ),
        thesis_refs=["evaluation.tex Tab. 6.2", f"RQ1 (isoliert), {arch} {hw_tag}, {auth_label}"],
        sql=_AUTH_ONLY_P99_SQL.format(
            arch=arch, hw_pred=hw_pred, auth=auth, algo_pred=algo_pred,
        ),
        compute=_delta,
        format=de_ms_signed,
        unit="ms",
    )


def _register_matrix() -> None:
    for arch_tag, arch, hw_list in _ARCHS:
        for hw_tag, hw_pred, hw_label in hw_list:
            for auth_tag, auth, algo_pred, auth_label in _AUTHS:
                for metric in ("p99", "p50"):
                    factory = (lambda metric=metric, arch_tag=arch_tag, arch=arch,
                                      hw_tag=hw_tag, hw_pred=hw_pred, hw_label=hw_label,
                                      auth_tag=auth_tag, auth=auth, algo_pred=algo_pred,
                                      auth_label=auth_label:
                               _make(metric, arch_tag, arch, hw_tag, hw_pred, hw_label,
                                     auth_tag, auth, algo_pred, auth_label))
                    factory.__name__ = f"rq1_auth_only_{metric}_{arch}_{hw_tag}_{auth_tag}"
                    register(factory)


_register_matrix()
