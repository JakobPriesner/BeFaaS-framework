"""Reproducible numbers catalog for the thesis.

Every value cited in the thesis prose (evaluation.tex, conclusion.tex, …) is
defined here as a `Number` object that owns its SQL query, post-processing
step, LaTeX formatter and thesis reference. Running `python -m thesis_numbers.generate`
recomputes every value from scratch against the PostgreSQL benchmarks database
and emits

  1. `thesisV2/numbers.tex`        — `\newcommand` bundle for the prose
  2. `thesisV2/acm_appendix.tex`   — full provenance appendix (SQL + exp-IDs)
  3. `thesisV2/plots/numbers_lookup.csv` — retrofit helper (old → macro map)

This module is intentionally separate from the 49 analysis scripts in
`scripts/thesis_analysis/*.py`, which produce plots and `.tex` table fragments.
The catalog has a single responsibility: one number = one cited value =
one macro.
"""

from thesis_numbers.catalog import Number, register, all_numbers  # noqa: F401
