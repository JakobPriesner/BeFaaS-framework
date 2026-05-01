"""RQ1 — Aggregierter ΔAuth über alle Endpunkte.

Die Zahlen in dieser Gruppe speisen Tabelle 6.1 und die umgebende Prosa:
Die ΔP99-Differenzen einer Auth-Strategie gegenüber der None-Baseline pro
Architektur/Hardware-Tier, über alle Endpunkte (auch anonyme) hinweg.

Die Matrix-Konstruktion erzeugt pro (Architektur, Hardware-Tier,
Auth-Strategie) ein Number; sie vermeidet Boilerplate und sorgt dafür, dass
alle im Text zitierten Zellen konsistent hergeleitet werden.
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ms_signed


_BASELINE_P99_SQL = textwrap.dedent("""\
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
      {algo_pred}
    GROUP BY e.id, e.auth_strategy, e.password_hash_algorithm
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 500
""")


# ── Matrix definition ────────────────────────────────────────────────────
# Each entry: (arch_tag, arch, hw_tag, hw_pred, auth_tag, auth_strategy, algo)
# auth_tag is the human-readable short label used in descriptions.
# algo_pred narrows Manual to either bcrypt or argon2id.

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
    # (tag, auth_strategy, algo_pred, human)
    ("Cognito",       "service-integrated",        "",                                                                 "Cognito"),
    ("Edge",          "edge",                      "",                                                                 "Edge"),
    ("ManualBcrypt",  "service-integrated-manual", "AND COALESCE(e.password_hash_algorithm,'default') IN ('default','bcrypt')", "Manual bcrypt/HS256"),
    ("ManualArgon",   "service-integrated-manual", "AND e.password_hash_algorithm = 'argon2id'",                       "Manual argon2id/EdDSA"),
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

    def _delta(df, strategy=auth):
        auth_vals = df[df.auth_strategy == strategy]["p99" if metric == "p99" else "p50"]
        none_vals = df[df.auth_strategy == "none"]["p99" if metric == "p99" else "p50"]
        if auth_vals.empty or none_vals.empty:
            return float("nan")
        return float(auth_vals.mean() - none_vals.mean())

    return Number(
        macro_name=f"rqOneAggDelta{metric_tag}{arch_tag}{hw_tag}{auth_tag}",
        group="rq1_aggregate",
        description=(
            f"Aggregierter {metric_label} ({auth_label} vs. None) auf "
            f"{arch_tag} {hw_label}, Baseline-Phase, aggregiert über alle Endpunkte."
        ),
        thesis_refs=["evaluation.tex Tab. 6.1", f"RQ1, {arch} {hw_tag}, {auth_label}"],
        sql=_BASELINE_P99_SQL.format(
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
                # Skip Argon on FaaS at the smallest tier (not studied) + some
                # combinations that don't exist — the HAVING clause will filter
                # if the data isn't there, so we register all.
                for metric in ("p99", "p50"):
                    factory = (lambda metric=metric, arch_tag=arch_tag, arch=arch,
                                      hw_tag=hw_tag, hw_pred=hw_pred, hw_label=hw_label,
                                      auth_tag=auth_tag, auth=auth, algo_pred=algo_pred,
                                      auth_label=auth_label:
                               _make(metric, arch_tag, arch, hw_tag, hw_pred, hw_label,
                                     auth_tag, auth, algo_pred, auth_label))
                    factory.__name__ = f"rq1_agg_{metric}_{arch}_{hw_tag}_{auth_tag}"
                    register(factory)


_register_matrix()
