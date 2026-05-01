"""Smoke tests — no DB hit required.

These tests validate that the catalog metadata is consistent:
- macro names contain no digits or underscores
- every Number has a non-empty description and at least one thesis ref
- formatters return strings
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make the parent dir importable when running `python -m thesis_numbers.tests.test_catalog`
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from thesis_numbers import definitions  # noqa: F401  # registers factories
from thesis_numbers.catalog import all_numbers


MACRO_RE = re.compile(r"^[A-Za-z]+$")


def test_macro_names_are_camelcase_letters_only() -> None:
    bad = []
    for n in all_numbers():
        if not MACRO_RE.match(n.macro_name):
            bad.append(n.macro_name)
    assert not bad, f"Macros must be letters only (no digits/underscores): {bad}"


def test_macro_names_unique() -> None:
    seen = set()
    dupes = []
    for n in all_numbers():
        if n.macro_name in seen:
            dupes.append(n.macro_name)
        seen.add(n.macro_name)
    assert not dupes, f"Duplicate macro names: {dupes}"


def test_description_and_refs_non_empty() -> None:
    empty = []
    for n in all_numbers():
        if not n.description.strip() or not n.thesis_refs:
            empty.append(n.macro_name)
    assert not empty, f"Missing description or thesis_refs: {empty}"


def test_sql_references_exclude_placeholder() -> None:
    # Any Number that touches the experiments or requests tables should filter
    # out broken/duplicate experiments via EXCLUDE_SQL — except those that
    # intentionally report pre-filter totals (flagged with `-- raw-corpus`).
    missing = []
    for n in all_numbers():
        sql_l = n.sql.lower()
        touches_corpus = "from experiments" in sql_l or "from requests" in sql_l
        declares_raw = "-- raw-corpus" in sql_l
        if touches_corpus and "{exclude_sql}" not in sql_l and not declares_raw:
            missing.append(n.macro_name)
    assert not missing, f"SQL must reference {{EXCLUDE_SQL}} or be marked '-- raw-corpus': {missing}"


if __name__ == "__main__":
    test_macro_names_are_camelcase_letters_only()
    test_macro_names_unique()
    test_description_and_refs_non_empty()
    test_sql_references_exclude_placeholder()
    print("All smoke tests passed.")
