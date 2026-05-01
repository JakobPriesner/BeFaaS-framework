"""RQ4 — Algorithmus-Auswirkung: argon2id-Katastrophe auf Containern.

Befund (Memory #7 und evaluation.tex Sec. 6.5/6.6): argon2id
ver\\`ursacht auf Container-Architekturen S bis L Fehlerraten von
67--93\\,\\%, während FaaS die gleiche Algorithmuskombination mit
$\\leq 0{,}6$\\,\\% Fehlerrate verarbeitet. Ursache ist CPU-Kontention
im Event-Loop (Node.js ist single-threaded und blockiert während des
Hashings). Die Numbers hier reproduzieren die Fehlerraten aus der DB.
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_pct


_ARGON_ERROR_RATE_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      e.architecture,
      COALESCE(e.cpu_in_vcpu, 0) AS cpu,
      e.ram_in_mb,
      COUNT(*) AS n_total,
      COUNT(*) FILTER (WHERE r.is_error) AS n_error
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {{EXCLUDE_SQL}}
      AND e.auth_strategy = 'service-integrated-manual'
      AND e.password_hash_algorithm = 'argon2id'
      AND e.architecture = '{arch}'
      AND {hw_pred}
    GROUP BY e.id, e.architecture, e.cpu_in_vcpu, e.ram_in_mb
    HAVING COUNT(*) > 1000
""")


def _mean_error_pct(df) -> float:
    if df.empty:
        return float("nan")
    rates = (df["n_error"] / df["n_total"] * 100.0).astype(float)
    return float(rates.mean())


# Container tiers S/M/L/XL on MS + Mono
_CONTAINER_HW = [
    ("S",  "COALESCE(e.cpu_in_vcpu,0) = 0.25"),
    ("M",  "COALESCE(e.cpu_in_vcpu,0) = 0.5"),
    ("L",  "COALESCE(e.cpu_in_vcpu,0) = 1.0"),
    ("XL", "COALESCE(e.cpu_in_vcpu,0) = 4.0"),
]


def _make(arch_tag: str, arch: str, hw_tag: str, hw_pred: str) -> Number:
    return Number(
        macro_name=f"rqFourArgonErrorRate{arch_tag}{hw_tag}",
        group="rq4_algorithm_impact",
        description=(
            f"Mittlere Fehlerrate über alle Phasen für Manual mit argon2id/EdDSA "
            f"auf {arch_tag} {hw_tag}. Belegt die Event-Loop-Blocking-These aus "
            "evaluation.tex Sec. 6.5 (Befund 18)."
        ),
        thesis_refs=[
            "evaluation.tex Sec. 6.5 (Befund 18)",
            "Critical Finding #7 im Memory",
        ],
        sql=_ARGON_ERROR_RATE_SQL.format(arch=arch, hw_pred=hw_pred),
        compute=_mean_error_pct,
        format=de_pct,
        unit="%",
    )


def _register_matrix() -> None:
    for arch_tag, arch in [("Ms", "microservices"), ("Mono", "monolith")]:
        for hw_tag, hw_pred in _CONTAINER_HW:
            factory = (lambda arch_tag=arch_tag, arch=arch,
                              hw_tag=hw_tag, hw_pred=hw_pred:
                       _make(arch_tag, arch, hw_tag, hw_pred))
            factory.__name__ = f"rq4_argon_error_{arch}_{hw_tag}"
            register(factory)


_register_matrix()


# FaaS counterpart: argon2id on FaaS tiers (reports the ~0.6 % survival rate)
_ARGON_FAAS_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      e.ram_in_mb,
      COUNT(*) AS n_total,
      COUNT(*) FILTER (WHERE r.is_error) AS n_error
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {{EXCLUDE_SQL}}
      AND e.auth_strategy = 'service-integrated-manual'
      AND e.password_hash_algorithm = 'argon2id'
      AND e.architecture = 'faas'
      AND e.ram_in_mb = {ram}
    GROUP BY e.id, e.ram_in_mb
    HAVING COUNT(*) > 1000
""")


_FAAS_RAMS = [
    ("FiveTwelve",         512),
    ("TenTwentyFour",      1024),
    ("SeventeenSixtyNine", 1769),
]


for ram_tag, ram_val in _FAAS_RAMS:
    def _faas_factory(ram_tag=ram_tag, ram_val=ram_val):
        return Number(
            macro_name=f"rqFourArgonErrorFaas{ram_tag}",
            group="rq4_algorithm_impact",
            description=(
                f"Fehlerrate für argon2id/EdDSA auf FaaS {ram_val}\\,MB. "
                "Liegt bei allen FaaS-Tiers unter 1\\,\\%, während Container "
                "mit derselben Konfiguration 67--93\\,\\% Fehler zeigen."
            ),
            thesis_refs=["evaluation.tex Sec. 6.5", "Critical Finding #7"],
            sql=_ARGON_FAAS_SQL.format(ram=ram_val),
            compute=_mean_error_pct,
            format=de_pct,
            unit="%",
        )
    _faas_factory.__name__ = f"rq4_argon_error_faas_{ram_val}"
    register(_faas_factory)
