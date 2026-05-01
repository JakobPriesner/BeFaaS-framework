"""Render outputs from whatever is in the cache — no DB, no factories run.

Use when you have a partial cache and want to regenerate numbers.tex /
acm_appendix.tex immediately. Numbers missing from the cache are simply not
emitted; their absence will show up in latexmk as Undefined control sequence
warnings, which is informative.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db_connection import EXCLUDE_SQL  # noqa: E402

# We still need the Number metadata (group, description, sql) for the appendix.
# Import the definitions so the registry is populated; we then skip compute().
from thesis_numbers import definitions  # noqa: F401, E402
from thesis_numbers.catalog import Number, all_numbers  # noqa: E402
from thesis_numbers.provenance import render_appendix  # noqa: E402


THESIS_ROOT = Path("/Users/jakob/Downloads/thesisV2")
NUMBERS_TEX = THESIS_ROOT / "numbers.tex"
APPENDIX_TEX = THESIS_ROOT / "acm_appendix.tex"
LOOKUP_CSV = THESIS_ROOT / "plots" / "numbers_lookup.csv"
CACHE_JSON = Path(__file__).resolve().parent / "_cache.json"


def main() -> int:
    cache = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(cache)} cached values.")

    numbers: list[Number] = []
    missing = []
    nan_skipped = []
    for n in all_numbers():
        entry = cache.get(n.macro_name)
        if entry is None:
            missing.append(n.macro_name)
            continue
        rendered = entry["rendered"]
        if "nan" in rendered.lower():
            nan_skipped.append(n.macro_name)
            continue
        n.rendered = rendered
        n.experiment_ids = [int(i) for i in entry.get("experiment_ids", [])]
        n.rendered_extra = dict(entry.get("rendered_extra", {}))
        numbers.append(n)
    print(f"Rendering {len(numbers)} (missing: {len(missing)}, NaN: {len(nan_skipped)}).")
    if missing[:3]:
        print(f"  First 3 missing: {missing[:3]}")

    # Meta from dataset numbers
    by_name = {n.macro_name: n.rendered for n in numbers}
    def _int_from_rendered(s):
        s = s.replace("\\,", "").replace("{,}", ".").strip()
        if s.endswith("Mio."):
            return int(float(s[:-4]) * 1e6)
        return int(float(s))
    meta = {
        "n_total": _int_from_rendered(by_name.get("numExperimentsTotal", "0")),
        "n_usable": _int_from_rendered(by_name.get("numExperimentsUsable", "0")),
        "n_requests": _int_from_rendered(by_name.get("numRequestsTotal", "0")),
    }

    # numbers.tex
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    import textwrap
    header = textwrap.dedent(f"""\
        %!TEX root = thesis.tex
        % ============================================================
        %  numbers.tex — AUTO-GENERATED — do not edit manually
        %  Generator:  scripts/thesis_analysis/thesis_numbers/render_only.py
        %  Generated:  {now}
        % ============================================================

        """)
    chunks = [header]
    last_group = None
    for n in sorted(numbers, key=lambda x: (x.group, x.macro_name)):
        if n.group != last_group:
            chunks.append(f"\n% {'-' * 60}\n% {n.group}\n% {'-' * 60}\n")
            last_group = n.group
        chunks.append(f"\\newcommand{{\\{n.macro_name}}}{{{n.rendered}}}\n")
        for suffix, rendered in n.rendered_extra.items():
            chunks.append(f"\\newcommand{{\\{n.macro_name}{suffix}}}{{{rendered}}}\n")
    NUMBERS_TEX.write_text("".join(chunks), encoding="utf-8")
    print(f"Wrote {NUMBERS_TEX} ({len(numbers)} macros)")

    APPENDIX_TEX.write_text(
        render_appendix(numbers, meta, EXCLUDE_SQL), encoding="utf-8"
    )
    print(f"Wrote {APPENDIX_TEX}")

    LOOKUP_CSV.parent.mkdir(parents=True, exist_ok=True)
    with LOOKUP_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["macro_name", "group", "description", "rendered", "unit", "n_exps"])
        for n in sorted(numbers, key=lambda x: (x.group, x.macro_name)):
            w.writerow([n.macro_name, n.group, n.description, n.rendered,
                        n.unit or "", len(n.experiment_ids)])
    print(f"Wrote {LOOKUP_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
