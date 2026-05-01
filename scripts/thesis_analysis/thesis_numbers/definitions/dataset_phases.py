"""Dataset -- phase-coverage counts for Kap. 6 Einleitung.

Die Thesis zitiert 'Davon absolvierten 172 die vollstaendigen sieben
Phasen [...]. Die uebrigen 16 brachen [...] nach 4--6 Phasen ab.'
Dieses Modul reproduziert die Zaehlungen aus der Datenbank, damit sie
mit dem aktuellen Korpus im Einklang bleiben.
"""

from __future__ import annotations

import textwrap

from thesis_numbers.catalog import Number, register
from thesis_numbers.formatters import de_int


_PHASE_COUNT_SQL = textwrap.dedent("""\
    WITH phase_counts AS (
      SELECT
        e.id,
        COUNT(DISTINCT r.phase_name)
          FILTER (WHERE r.phase_name IS NOT NULL AND r.phase_name <> 'None') AS pc
      FROM experiments e JOIN requests r ON r.experiment_id = e.id
      WHERE {EXCLUDE_SQL}
      GROUP BY e.id
    )
    SELECT pc, COUNT(*) AS n FROM phase_counts GROUP BY pc ORDER BY pc
""")


def _full_7(df) -> int:
    sub = df[df.pc >= 7]
    return int(sub["n"].sum()) if not sub.empty else 0


def _partial_4_6(df) -> int:
    sub = df[(df.pc >= 4) & (df.pc <= 6)]
    return int(sub["n"].sum()) if not sub.empty else 0


@register
def num_experiments_full_phases() -> Number:
    return Number(
        macro_name="numExperimentsFullPhases",
        group="dataset",
        description=(
            "Anzahl Experimente, die alle sieben Phasen des SCNAST-Protokolls "
            "vollstaendig durchlaufen haben."
        ),
        thesis_refs=["evaluation.tex Sec. 6.2 (Chapter-Einleitung)"],
        sql=_PHASE_COUNT_SQL,
        compute=_full_7,
        format=de_int,
        unit="Experimente",
        extract_ids=lambda df: [],
    )


@register
def num_experiments_partial_phases() -> Number:
    return Number(
        macro_name="numExperimentsPartialPhases",
        group="dataset",
        description=(
            "Anzahl Experimente, die aufgrund von Systemsaettigung nur "
            "4--6 Phasen des SCNAST-Protokolls durchlaufen haben."
        ),
        thesis_refs=["evaluation.tex Sec. 6.2"],
        sql=_PHASE_COUNT_SQL,
        compute=_partial_4_6,
        format=de_int,
        unit="Experimente",
        extract_ids=lambda df: [],
    )
