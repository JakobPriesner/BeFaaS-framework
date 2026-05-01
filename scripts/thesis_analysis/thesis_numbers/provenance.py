"""Render the ACM-style reproducibility appendix.

Produces one LaTeX file (`acm_appendix.tex`) that documents, for every cited
number, the SQL, the experiments it consumed, its value and the code location
that defined it.
"""

from __future__ import annotations

import textwrap
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from thesis_numbers.catalog import Number


GROUP_TITLES: dict[str, str] = {
    "dataset": "Datenbasis (Gesamtkorpus, Abdeckung, Filter)",
    "rq1_aggregate": "RQ1 — Aggregierter $\\Delta$Auth (alle Endpunkte)",
    "rq1_auth_only": "RQ1 — $\\Delta$Auth auf authentifizierten Endpunkten",
    "rq1_login_exclusion": "RQ1 — Manual-Overhead ohne Login-Endpunkt",
    "rq1_arch_ratios": "RQ1 — Architektur-Verh\\\"altnisse (Faktor langsamste/schnellste)",
    "rq1_welch": "RQ1 — Welch-t-Konfidenzintervalle (Block-P99, authentifizierte Endpunkte)",
    "rq1_phase": "RQ1 — Phasenzerlegung und Anteile",
    "rq2_multiplication": "RQ2 — Multiplikationsmodell (Ratio $R$, $k_{\\text{eff}}$)",
    "rq2_per_endpoint": "RQ2 — $\\Delta$P50 pro Endpunkt (addCartItem, Checkout, cart)",
    "rq2_scaling": "RQ2 — Skalierungsverhalten allgemein",
    "rq2_cascading": "RQ2 — Kaskadenversagen Lambda@Edge + Microservices",
    "rq3_exposure": "RQ3 — Token-Exposition und Replay-Fenster",
    "rq3_security": "RQ3 — Weitere Sicherheitsmetriken",
    "rq4_algorithm_impact": "RQ4 — Algorithmus-Auswirkung (argon2id-Fehlerraten)",
    "rq4_decision_matrix": "RQ4 — Entscheidungsmatrix (None/Cognito/Manual-P99 je Architektur)",
    "rq4_equalizing": "RQ4 — Architekturübergreifender Angleichungseffekt",
    "rq4_framework": "RQ4 — Entscheidungsrahmen, Kosten",
    "calibration": "Vorvalidierung — Edge-Sel.-FaaS-Kalibrierung, CPU-Sättigung",
    "threats": "Gültigkeit — Socket-Pool, Argon2id-Fehlerraten, Störgrößen",
}


def _header(n_total: int, n_usable: int, n_requests: float) -> str:
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return textwrap.dedent(f"""\
        %!TEX root = thesis.tex
        % ============================================================
        %  acm_appendix.tex — AUTO-GENERATED — do not edit manually
        %  Generator: scripts/thesis_analysis/thesis_numbers/generate.py
        %  Generated: {now}
        %  Source:    PostgreSQL benchmarks, {n_total} Experimente gesamt,
        %             {n_usable} auswertbar ({n_requests / 1e6:.1f}\\,Mio. Anfragen)
        % ============================================================

        \\section{{Reproduzierbarkeit der berichteten Zahlen}}
        \\label{{sec:acm-appendix}}

        Dieser Anhang dokumentiert die vollständige Herkunft aller im Fließtext
        zitierten numerischen Werte. Für jeden Wert werden (a)~der zugehörige
        LaTeX-Makroname, (b)~die zugrundeliegende SQL-Abfrage, (c)~die in die
        Berechnung eingehenden Experimente~(ID), (d)~die nachgelagerte
        Python-Aggregation sowie~(e)~der genaue Pfad zum erzeugenden
        Quellcode genannt. Alle Ausschlüsse (Duplikat-Importe,
        Broken-Experimente \\texttt{{3, 85, 179, 191, 192}}) sind über das
        zentrale SQL-Fragment \\texttt{{EXCLUDE\\_SQL}}
        (\\path{{scripts/thesis_analysis/db_connection.py}}) einheitlich
        gefiltert. Die Neuerzeugung dieses Anhangs und der referenzierten
        Makros erfolgt durch einen einzigen Aufruf
        \\texttt{{python -m thesis\\_numbers.generate}}; beide Dateien werden
        deterministisch aus der Datenbank abgeleitet.
        """)


_UNICODE_TO_TEX = {
    "Δ": r"$\Delta$",
    "α": r"$\alpha$",
    "β": r"$\beta$",
    "σ": r"$\sigma$",
    "μ": r"$\mu$",
    "≥": r"$\geq$",
    "≤": r"$\leq$",
    "×": r"$\times$",
    "→": r"$\to$",
}


def _latex_escape(s: str) -> str:
    """Replace ambiguous Unicode glyphs and LaTeX-reserved characters.

    Only escape characters that are not already escaped. We use a lookbehind
    regex for the LaTeX specials to avoid double-escaping e.g. `\\#`.
    """
    import re
    for uni, tex in _UNICODE_TO_TEX.items():
        s = s.replace(uni, tex)
    s = re.sub(r"(?<!\\)&", r"\\&", s)
    s = re.sub(r"(?<!\\)%", r"\\%", s)
    s = re.sub(r"(?<!\\)#", r"\\#", s)
    return s


def _macro_index_table(numbers: list[Number]) -> str:
    rows = []
    for n in sorted(numbers, key=lambda x: (x.group, x.macro_name)):
        desc = _latex_escape(n.description)
        rows.append(
            f"  \\texttt{{\\textbackslash {n.macro_name}}} & {desc} & {n.rendered} \\\\"
        )
    body = "\n".join(rows)
    return textwrap.dedent("""\
        \\subsection{Verzeichnis aller zitierten Zahlen}
        \\label{subsec:acm-macro-index}

        Tabelle~\\ref{tab:acm-macro-index} listet jeden im Fließtext
        referenzierten Makronamen mit Kurzbeschreibung und berechnetem Wert
        auf. Die Gruppierungen in den folgenden Unterabschnitten geben
        jeweils die SQL- und Aggregationsschritte wieder, die zu den
        Werten geführt haben.

        {\\footnotesize
        \\begin{longtable}{@{}p{5.5cm}p{7cm}r@{}}
        \\caption{Verzeichnis der zitierten Makros mit Beschreibung und
        Wert. Die Reihenfolge folgt der inhaltlichen Gruppierung in
        Abschnitt~\\ref{subsec:acm-groups}.}
        \\label{tab:acm-macro-index} \\\\
        \\toprule
        \\textbf{Makro} & \\textbf{Beschreibung} & \\textbf{Wert} \\\\
        \\midrule
        \\endfirsthead
        \\toprule
        \\textbf{Makro} & \\textbf{Beschreibung} & \\textbf{Wert} \\\\
        \\midrule
        \\endhead
        \\midrule
        \\multicolumn{3}{r@{}}{\\textit{Fortsetzung auf nächster Seite}}\\\\
        \\endfoot
        \\bottomrule
        \\endlastfoot
        """) + body + "\n\\end{longtable}\n}\n"


def _excluded_experiments_table() -> str:
    return textwrap.dedent("""\
        \\subsection{Ausgeschlossene Experimente}
        \\label{subsec:acm-excluded}

        Die folgenden Experimente werden von sämtlichen Katalog-Abfragen
        ausgeschlossen. Die Liste ist in \\path{db_connection.py} hinterlegt
        und wird von allen registrierten Zahlen konsistent verwendet.

        \\begin{table}[htbp]
        \\centering
        \\small
        \\begin{tabular}{@{}rl@{}}
        \\toprule
        \\textbf{Exp.\\,ID} & \\textbf{Begründung} \\\\
        \\midrule
        3   & Edge-Auth-Konfigurationsfehler, 33\\,\\% Fehlerrate in allen Phasen inkl.\\ Baseline \\\\
        85  & Docker-Build-Fehler zur Laufzeit, nur vier Phasen, Stabilisierungs-P50 $= 10{,}8$\\,s \\\\
        179 & Fehlkonfiguration \\texttt{ram\\_in\\_mb}$=1796$ (Intended: 1769~MB) \\\\
        191 & Fehlkonfiguration \\texttt{ram\\_in\\_mb}$=1796$ (Intended: 1769~MB) \\\\
        192 & Fehlkonfiguration \\texttt{ram\\_in\\_mb}$=1796$ (Intended: 1769~MB) \\\\
        \\addlinespace
        \\multicolumn{2}{@{}l}{\\textit{Zusätzlich: alle Zeilen mit
        \\texttt{experiments.import\\_failure IS NOT NULL} (Duplikat-Importe)}} \\\\
        \\bottomrule
        \\end{tabular}
        \\caption{Vollständig ausgeschlossene Experimente. Die Filterung
        erfolgt über das Fragment \\texttt{EXCLUDE\\_SQL} in
        \\texttt{scripts/thesis\\_analysis/db\\_connection.py}.}
        \\label{tab:acm-excluded}
        \\end{table}
        """)


def _render_sql(sql: str, exclude_sql: str) -> str:
    """Resolve {EXCLUDE_SQL} and lightly pretty-print for listings."""
    rendered = sql.format(EXCLUDE_SQL=exclude_sql).rstrip()
    # Listings treats leading spaces literally; we emit the SQL flush left.
    return "\n".join(line.rstrip() for line in rendered.splitlines())


def _group_section(group: str, members: list[Number], exclude_sql: str) -> str:
    # LaTeX-safe fallback: underscores would be interpreted as subscript.
    title = GROUP_TITLES.get(group, group.replace("_", "\\_"))
    macros_list = ", ".join(f"\\texttt{{\\textbackslash {n.macro_name}}}" for n in members)

    # De-duplicate SQL: identical queries get folded into one listing.
    sql_to_members: dict[str, list[Number]] = defaultdict(list)
    for n in members:
        sql_to_members[n.sql.strip()].append(n)

    sql_blocks = []
    for sql, group_members in sql_to_members.items():
        macro_names = ", ".join(n.macro_name for n in group_members)
        all_ids = sorted({i for n in group_members for i in n.experiment_ids})
        if not all_ids:
            id_fragment = "(keine experimentspezifischen IDs — aggregierte Abfrage)"
        elif len(all_ids) <= 60:
            id_fragment = ", ".join(str(i) for i in all_ids)
        else:
            id_fragment = (
                ", ".join(str(i) for i in all_ids[:60])
                + f", \\ldots\\,({len(all_ids)} IDs gesamt)"
            )

        rendered_sql = _render_sql(sql, exclude_sql)
        sql_blocks.append(
            f"\\paragraph{{Abfrage für \\texttt{{{macro_names}}}}}\\leavevmode\n\n"
            f"Eingehende Experiment-IDs: {id_fragment}.\n\n"
            "\\begin{lstlisting}[language=SQL,basicstyle=\\footnotesize\\ttfamily,"
            "breaklines=true,frame=single]\n"
            f"{rendered_sql}\n"
            "\\end{lstlisting}\n\n"
            "Python-Definition: "
            f"\\path{{scripts/thesis_analysis/thesis_numbers/definitions/{group}.py}}\n"
        )

    body = "\n".join(sql_blocks)
    heading = (
        f"\n\\subsection{{{title}}}\n"
        f"\\label{{subsec:acm-group-{group.replace('_', '-')}}}\n\n"
        f"Enthaltene Makros: {macros_list}.\n\n"
    )
    return heading + body


def render_appendix(numbers: list[Number], meta: dict, exclude_sql: str) -> str:
    """Top-level: header + macro index + excluded exps + per-group sections."""
    head = _header(meta["n_total"], meta["n_usable"], meta["n_requests"])

    groups: dict[str, list[Number]] = defaultdict(list)
    for n in numbers:
        groups[n.group].append(n)

    group_order = list(GROUP_TITLES.keys())
    ordered_groups = [g for g in group_order if g in groups] + [
        g for g in groups if g not in group_order
    ]

    group_sections = "\n".join(
        _group_section(g, groups[g], exclude_sql) for g in ordered_groups
    )

    return (
        head
        + "\n"
        + _macro_index_table(numbers)
        + "\n"
        + _excluded_experiments_table()
        + "\n\\subsection*{Gruppenweise Provenance}\n\\label{subsec:acm-groups}\n"
        + group_sections
    )
