"""RQ1 — Welch-t-Konfidenzintervalle für $\\Delta$P99 auf Block-P99-Ebene.

Der Thesis-Anhang (`sec:appendix-significance`) listet für jede
(Architektur, Hardware-Tier, Auth-Strategie)-Kombination den mittleren
$\\Delta$P99 samt 95\\,\\%-Konfidenzintervall des Welch-t-Tests. Dieses
Modul reproduziert die drei Kennzahlen (Mittelwert, CI-unten, CI-oben)
pro Zelle, damit sie im Fließtext mit \\texttt{\\textbackslash macroName}
zitiert werden können.

Die Methodik folgt Abschnitt 6.1 der Thesis: Messungen werden in
60\\,s-Blöcke gruppiert, pro Block das P99 berechnet, und anschließend
über die Blöcke von authentifiziertem und anonymem Traffic
Welch-t-Vergleiche gezogen. „Auth-only" bedeutet: beschränkt auf die
vier geschützten Endpunkte.
"""

from __future__ import annotations

import textwrap

import numpy as np
import pandas as pd
from scipy import stats

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ms_signed


_BLOCK_P99_SQL = textwrap.dedent("""\
    WITH blocks AS (
      SELECT
        e.id AS exp_id,
        e.auth_strategy,
        (r.timestamp_ms / 60000) AS block_id,
        percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
            FILTER (WHERE NOT r.is_error) AS block_p99
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
      GROUP BY e.id, e.auth_strategy, block_id
      HAVING COUNT(*) FILTER (WHERE NOT r.is_error) >= 30
    )
    SELECT exp_id AS id, auth_strategy, block_p99
    FROM blocks
    WHERE block_p99 IS NOT NULL
""")


_HW_FAAS = [
    ("TwoFiveSix",         "e.ram_in_mb = 256",  "256\\,MB"),
    ("FiveTwelve",         "e.ram_in_mb = 512",  "512\\,MB"),
    ("TenTwentyFour",      "e.ram_in_mb = 1024", "1024\\,MB"),
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
]
_ARCHS = [
    ("Faas", "faas", _HW_FAAS),
    ("Ms",   "microservices", _HW_CT),
    ("Mono", "monolith", _HW_CT),
]


def _welch_result(df: pd.DataFrame, strategy: str) -> tuple[float, float, float]:
    """Return (mean_delta, ci_low, ci_high) in milliseconds.

    Welch-t auf Block-P99-Werten: Hypothese ist, dass die Baseline-Tail-Latenz
    der Auth-Variante gleich der None-Variante ist; das CI gibt den plausiblen
    Bereich des $\\Delta$ an.
    """
    auth_vals = df[df.auth_strategy == strategy]["block_p99"].to_numpy(dtype=float)
    none_vals = df[df.auth_strategy == "none"]["block_p99"].to_numpy(dtype=float)
    if len(auth_vals) < 2 or len(none_vals) < 2:
        return (float("nan"), float("nan"), float("nan"))
    t_stat, _ = stats.ttest_ind(auth_vals, none_vals, equal_var=False)
    mean_delta = float(np.mean(auth_vals) - np.mean(none_vals))
    se = float(np.sqrt(np.var(auth_vals, ddof=1) / len(auth_vals)
                       + np.var(none_vals, ddof=1) / len(none_vals)))
    # Welch-Satterthwaite df
    v1 = np.var(auth_vals, ddof=1) / len(auth_vals)
    v2 = np.var(none_vals, ddof=1) / len(none_vals)
    df_val = (v1 + v2) ** 2 / (v1 ** 2 / (len(auth_vals) - 1) + v2 ** 2 / (len(none_vals) - 1))
    t_crit = float(stats.t.ppf(0.975, df=df_val))
    return (mean_delta, mean_delta - t_crit * se, mean_delta + t_crit * se)


def _ci_formatter(which: str):
    """Render one component of the Welch-t triple in signed ms."""
    idx = {"mean": 0, "low": 1, "high": 2}[which]
    def fmt(triple: tuple[float, float, float]) -> str:
        return de_ms_signed(triple[idx])
    return fmt


def _make_welch_number(
    arch_tag: str, arch: str,
    hw_tag: str, hw_pred: str, hw_label: str,
    auth_tag: str, auth: str, algo_pred: str, auth_label: str,
) -> Number:
    sql = _BLOCK_P99_SQL.format(arch=arch, hw_pred=hw_pred, auth=auth, algo_pred=algo_pred)

    def _compute(df, strategy=auth):
        return _welch_result(df, strategy)

    return Number(
        macro_name=f"rqOneWelchMeanDeltaPNineNine{arch_tag}{hw_tag}{auth_tag}",
        group="rq1_welch",
        description=(
            f"Welch-t $\\Delta$P99 ({auth_label} vs. None) auf authentifizierten "
            f"Endpunkten, {arch_tag} {hw_label}, Baseline, Block-P99-Basis. "
            "Der Makroname referenziert den Mittelwert; \\textit{CIlow}/\\textit{CIhigh} die 95\\,\\%-Grenzen."
        ),
        thesis_refs=[
            "evaluation.tex (Welch-t-CI-Zitate)",
            "appendix.tex tab:significance-tests-full",
        ],
        sql=sql,
        compute=_compute,
        format=_ci_formatter("mean"),
        unit="ms",
        extra_macros={
            "CIlow":  _ci_formatter("low"),
            "CIhigh": _ci_formatter("high"),
        },
    )


def _register_matrix() -> None:
    for arch_tag, arch, hw_list in _ARCHS:
        for hw_tag, hw_pred, hw_label in hw_list:
            for auth_tag, auth, algo_pred, auth_label in _AUTHS:
                factory = (lambda arch_tag=arch_tag, arch=arch,
                                  hw_tag=hw_tag, hw_pred=hw_pred, hw_label=hw_label,
                                  auth_tag=auth_tag, auth=auth, algo_pred=algo_pred,
                                  auth_label=auth_label:
                           _make_welch_number(arch_tag, arch, hw_tag, hw_pred, hw_label,
                                              auth_tag, auth, algo_pred, auth_label))
                factory.__name__ = f"rq1_welch_{arch}_{hw_tag}_{auth_tag}"
                register(factory)


_register_matrix()
