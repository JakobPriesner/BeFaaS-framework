"""Scan the thesis prose for hardcoded numbers that match a known macro.

The catalog knows each number's rendered form (e.g. `+150\\,ms`). This helper
reads every macro's `rendered` from `plots/numbers_lookup.csv` and searches
the `.tex` sources of the thesis for occurrences of that literal. The output
is a candidate list — file path, line number, snippet — that the author can
review and replace manually.

No automatic substitution: `+150\\,ms` or `18{,}4\\,\\%` could be ambiguous,
and a production retrofit benefits from eyeballing each case.

Usage:
    python -m thesis_numbers.retrofit_helper          # print candidates
    python -m thesis_numbers.retrofit_helper --check  # CI mode: fail if any
                                                      #   known literal still
                                                      #   appears in prose
    python -m thesis_numbers.retrofit_helper --unused # list macros that are
                                                      #   defined but never
                                                      #   referenced
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


THESIS_ROOT = Path("/Users/jakob/Downloads/thesisV2")
LOOKUP_CSV = THESIS_ROOT / "plots" / "numbers_lookup.csv"

# Files to scan. Excludes `numbers.tex` (contains the macros themselves) and
# `acm_appendix.tex` (full literal prose dump of values is intentional).
PROSE_FILES = [
    "introduction.tex",
    "background.tex",
    "relatedwork.tex",
    "approach.tex",
    "implementierung/implementation.tex",
    "implementierung/experiment_orchestration.tex",
    "implementierung/datenpersistierung.tex",
    "implementierung/auth_services.tex",
    "implementierung/scaling_config.tex",
    "evaluation.tex",
    "conclusion.tex",
]


def _load_lookup() -> list[dict]:
    with LOOKUP_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _existing_prose_paths() -> list[Path]:
    out = []
    for rel in PROSE_FILES:
        p = THESIS_ROOT / rel
        if p.exists():
            out.append(p)
    return out


def _scan_candidates(rows: list[dict]) -> list[dict]:
    """Find literal occurrences of rendered values in prose files."""
    candidates = []
    for path in _existing_prose_paths():
        text = path.read_text(encoding="utf-8", errors="replace")
        for row in rows:
            rendered = row["rendered"]
            if not rendered or len(rendered) < 3:
                continue
            # Skip values that are too short/generic to match cleanly
            # (e.g. plain integers can collide with IDs, years, section numbers).
            if re.fullmatch(r"\d+", rendered.replace("\\,", "").replace("{,}", ".")):
                continue
            for m in re.finditer(re.escape(rendered), text):
                start = m.start()
                line_no = text.count("\n", 0, start) + 1
                # Extract the surrounding line for context
                line_start = text.rfind("\n", 0, start) + 1
                line_end = text.find("\n", start)
                if line_end < 0:
                    line_end = len(text)
                snippet = text[line_start:line_end].strip()
                candidates.append({
                    "file": str(path.relative_to(THESIS_ROOT)),
                    "line": line_no,
                    "macro": row["macro_name"],
                    "rendered": rendered,
                    "snippet": snippet[:160],
                })
    return candidates


def _scan_unused_macros(rows: list[dict]) -> list[str]:
    """Return macro names that are never referenced in any prose file."""
    all_text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in _existing_prose_paths()
    )
    unused = []
    for row in rows:
        macro = row["macro_name"]
        if f"\\{macro}" not in all_text:
            unused.append(macro)
    return unused


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="CI mode: exit non-zero if any hardcoded literal still present.")
    parser.add_argument("--unused", action="store_true",
                        help="List macros that are defined but never referenced.")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max candidates to print in default mode (default 50).")
    args = parser.parse_args()

    if not LOOKUP_CSV.exists():
        print(f"{LOOKUP_CSV} not found — run `python -m thesis_numbers.generate` first.",
              file=sys.stderr)
        return 2

    rows = _load_lookup()
    print(f"Loaded {len(rows)} macros from {LOOKUP_CSV.name}.")

    if args.unused:
        unused = _scan_unused_macros(rows)
        if not unused:
            print("All macros are referenced at least once.")
            return 0
        print(f"\n{len(unused)} macros defined but never referenced:")
        for m in unused:
            print(f"  \\{m}")
        return 0

    candidates = _scan_candidates(rows)
    if not candidates:
        print("No hardcoded matches found. Retrofit complete.")
        return 0

    if args.check:
        print(f"\n[CHECK] {len(candidates)} hardcoded occurrences still present.",
              file=sys.stderr)
        for c in candidates[:20]:
            print(f"  {c['file']}:{c['line']}  \\{c['macro']} = {c['rendered']}",
                  file=sys.stderr)
        return 1

    print(f"\nFound {len(candidates)} candidate occurrences. Showing up to {args.limit}:\n")
    for c in candidates[:args.limit]:
        print(f"{c['file']}:{c['line']}")
        print(f"  candidate macro: \\{c['macro']}  (= {c['rendered']})")
        print(f"  snippet: {c['snippet']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
