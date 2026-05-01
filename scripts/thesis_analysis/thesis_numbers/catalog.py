"""Core data model for cited numbers.

A `Number` bundles everything required to (a) reproduce the value from the
database and (b) justify it in a reproducibility appendix. It owns its SQL,
post-processing, LaTeX formatter and a list of thesis reference tags.

The `@register` decorator collects factory functions at import time. The
catalog is assembled lazily: calling `all_numbers()` triggers each factory,
which may in turn run SQL and compute the value, so importing the package
never touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import pandas as pd


Formatter = Callable[[Any], str]
Computer = Callable[[pd.DataFrame], Any]
IdExtractor = Callable[[pd.DataFrame], list[int]]


@dataclass
class Number:
    """A single cited value with full provenance."""

    macro_name: str
    """CamelCase name, no digits, no underscores. Emitted as \\{macro_name}."""

    group: str
    """Group key, matches a `definitions/<group>.py` filename stem."""

    description: str
    """One-sentence human description for the appendix table."""

    thesis_refs: list[str]
    """File references like `evaluation.tex:508` or `Sec. 6.3.1, Befund 1`."""

    sql: str
    """Self-contained SQL. Must reference `{EXCLUDE_SQL}` via .format()."""

    compute: Computer
    """Takes the SQL result dataframe, returns the raw value (or tuple)."""

    format: Formatter
    """Takes the raw value, returns a LaTeX-safe string (e.g. '+14{,}3\\,ms')."""

    unit: str | None = None
    """Human-readable unit for the appendix table ('ms', '%', '-')."""

    extract_ids: IdExtractor | None = None
    """Pulls the experiment IDs that fed into the value out of the dataframe.
    Defaults to `df['id'].unique()` when the query returns an `id` column."""

    extra_macros: dict[str, Formatter] | None = None
    """Optional secondary macros derived from the same result (e.g. CI bounds).
    Keys are macro suffixes, values are formatters that receive the raw value."""

    # Populated by generate.py after SQL runs ───────────────────────────────
    raw_value: Any = field(default=None, init=False, repr=False)
    rendered: str = field(default="", init=False, repr=False)
    experiment_ids: list[int] = field(default_factory=list, init=False, repr=False)
    rendered_extra: dict[str, str] = field(default_factory=dict, init=False, repr=False)


_REGISTRY: list[Callable[[], Number]] = []


def register(factory: Callable[[], Number]) -> Callable[[], Number]:
    """Decorator: registers a `Number` factory for batch evaluation."""
    _REGISTRY.append(factory)
    return factory


def all_numbers() -> Iterable[Number]:
    """Instantiate every registered factory. Import-side-effects handle SQL."""
    for factory in _REGISTRY:
        yield factory()


def registry_size() -> int:
    return len(_REGISTRY)
