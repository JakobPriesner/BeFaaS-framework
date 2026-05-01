"""RQ1 — Manual-Overhead ohne Login-Endpunkt (Critical Finding #2).

Der Kernbefund der Manual-Zerlegung: 100\\,\\% des Manual-Overheads
konzentrieren sich auf den Login-Endpunkt (bcrypt-Hashing). Wenn Login
aus der Aggregation ausgeschlossen wird, bleibt $\\Delta$P99 = $-$1{,}3\\,ms
übrig — effektiv kein Overhead.

Diese Number rechnet den Wert für eine repräsentative Monolith-L-
Konfiguration nach (bcrypt/HS256, E33 vs. None-Baseline E30).
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_ms_signed


_EXCL_LOGIN_SQL = textwrap.dedent("""\
    SELECT
      e.id,
      e.auth_strategy,
      percentile_cont(0.99) WITHIN GROUP (ORDER BY r.latency_ms)
          FILTER (WHERE NOT r.is_error) AS p99
    FROM experiments e JOIN requests r ON r.experiment_id = e.id
    WHERE {EXCLUDE_SQL}
      AND r.phase_name = 'Baseline'
      AND e.architecture = 'monolith'
      AND COALESCE(e.cpu_in_vcpu, 0) = 1.0
      AND e.auth_strategy IN ('none', 'service-integrated-manual')
      AND COALESCE(e.password_hash_algorithm, 'default') IN ('default', 'bcrypt')
      AND COALESCE(e.with_cloudfront, false) = false
      AND r.endpoint NOT IN ('/login', '/frontend/login', '/register', '/frontend/register',
                             '/setUser', '/frontend/setUser')
    GROUP BY e.id, e.auth_strategy
    HAVING COUNT(*) FILTER (WHERE NOT r.is_error) > 500
""")


def _delta_p99(df) -> float:
    auth = df[df.auth_strategy == "service-integrated-manual"]["p99"]
    none = df[df.auth_strategy == "none"]["p99"]
    if auth.empty or none.empty:
        return float("nan")
    return float(auth.mean() - none.mean())


@register
def rq1_manual_delta_p99_excl_login_mono_l() -> Number:
    return Number(
        macro_name="rqOneManualDeltaPNineNineExclLoginMonoL",
        group="rq1_login_exclusion",
        description=(
            "$\\Delta$P99 für Manual (bcrypt/HS256) auf Monolith Tier~L, Baseline, "
            "\\emph{ohne} den Login-/Registrierungs-/setUser-Pfad. Zeigt, dass der "
            "Manual-Overhead sich vollständig auf den Login-Endpunkt konzentriert "
            "(Critical Finding~\\#2, evaluation.tex Sec. 6.3.3)."
        ),
        thesis_refs=[
            "evaluation.tex Sec. 6.3.3 (overhead_excl_login)",
            "Critical Finding #2 im Memory",
        ],
        sql=_EXCL_LOGIN_SQL,
        compute=_delta_p99,
        format=de_ms_signed,
        unit="ms",
    )
