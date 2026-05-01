"""Entry point: evaluate every registered Number and emit outputs.

Outputs written to `/Users/jakob/Downloads/thesisV2/`:
  - numbers.tex          — \\newcommand bundle for the prose
  - acm_appendix.tex     — provenance appendix (SQL, IDs, paths)
  - plots/numbers_lookup.csv — retrofit helper (rendered values for grep)

Run:
    cd scripts/thesis_analysis
    python -m thesis_numbers.generate [--verify] [--only GROUP]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

# Allow `python -m thesis_numbers.generate` from thesis_analysis/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db_connection import query_df, EXCLUDE_SQL, PLOT_DIR  # noqa: E402

from thesis_numbers import definitions  # noqa: F401, E402  # triggers @register
from thesis_numbers.catalog import Number, all_numbers, registry_size  # noqa: E402
from thesis_numbers.provenance import render_appendix  # noqa: E402


THESIS_ROOT = Path("/Users/jakob/Downloads/thesisV2")
NUMBERS_TEX = THESIS_ROOT / "numbers.tex"
APPENDIX_TEX = THESIS_ROOT / "acm_appendix.tex"
LOOKUP_CSV = THESIS_ROOT / "plots" / "numbers_lookup.csv"
CACHE_JSON = Path(__file__).resolve().parent / "_cache.json"


_SQL_RESULT_CACHE: dict[str, object] = {}


def _run_sql(sql: str):
    """Execute SQL with in-process deduplication (important for matrix defs)."""
    if sql in _SQL_RESULT_CACHE:
        return _SQL_RESULT_CACHE[sql]
    df = query_df(sql)
    _SQL_RESULT_CACHE[sql] = df
    return df


def _evaluate(n: Number) -> Number:
    """Run SQL, compute value, format it, store provenance."""
    sql = n.sql.format(EXCLUDE_SQL=EXCLUDE_SQL)
    df = _run_sql(sql)
    raw = n.compute(df)
    n.raw_value = raw
    n.rendered = n.format(raw)
    if n.extract_ids is not None:
        n.experiment_ids = sorted({int(i) for i in n.extract_ids(df)})
    elif "id" in df.columns:
        n.experiment_ids = sorted({int(i) for i in df["id"].unique()})
    else:
        n.experiment_ids = []
    if n.extra_macros:
        n.rendered_extra = {suffix: fmt(raw) for suffix, fmt in n.extra_macros.items()}
    return n


def _cache_dump(numbers: list[Number]) -> None:
    """Persist primitive fields so re-rendering doesn't re-query the DB."""
    payload = {
        n.macro_name: {
            "rendered": n.rendered,
            "experiment_ids": n.experiment_ids,
            "rendered_extra": n.rendered_extra,
        }
        for n in numbers
    }
    CACHE_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _cache_load_into(n: Number, cached: dict) -> bool:
    """Populate a freshly-built Number from the cache; return True on hit."""
    entry = cached.get(n.macro_name)
    if entry is None:
        return False
    n.rendered = entry["rendered"]
    n.experiment_ids = [int(i) for i in entry["experiment_ids"]]
    n.rendered_extra = dict(entry.get("rendered_extra", {}))
    return True


def _int_from_rendered(s: str) -> int:
    """Back-out an int from a rendered macro (e.g. '111{,}3\\,Mio.' → 111_300_000)."""
    s = s.replace("\\,", "").replace("{,}", ".").strip()
    if s.endswith("Mio."):
        return int(float(s[:-4]) * 1e6)
    if s.endswith("Tsd."):
        return int(float(s[:-4]) * 1e3)
    # Plain integer, possibly with thousands separators already removed.
    return int(float(s))


def _dataset_meta(numbers: list[Number]) -> dict:
    """Reuse already-evaluated dataset Numbers to avoid a redundant 110M-row scan."""
    by_name = {n.macro_name: n for n in numbers}
    def get_raw(name: str) -> int:
        n = by_name.get(name)
        if n is None:
            return 0
        # raw_value is set by live eval; on cache reload we back it out from rendered.
        if n.raw_value is not None:
            return int(n.raw_value)
        return _int_from_rendered(n.rendered) if n.rendered else 0
    return {
        "n_total": get_raw("numExperimentsTotal"),
        "n_usable": get_raw("numExperimentsUsable"),
        "n_requests": get_raw("numRequestsTotal"),
    }


def _write_numbers_tex(numbers: list[Number], meta: dict) -> None:
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    header = textwrap.dedent(f"""\
        %!TEX root = thesis.tex
        % ============================================================
        %  numbers.tex — AUTO-GENERATED — do not edit manually
        %  Generator:  scripts/thesis_analysis/thesis_numbers/generate.py
        %  Generated:  {now}
        %  Source:     PostgreSQL benchmarks @ 192.168.178.22:5437
        %  N_exp_tot:  {meta["n_total"]}
        %  N_exp_use:  {meta["n_usable"]}
        %  N_reqs:     {meta["n_requests"]:,}
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


def _write_appendix_tex(numbers: list[Number], meta: dict) -> None:
    APPENDIX_TEX.write_text(
        render_appendix(numbers, meta, EXCLUDE_SQL), encoding="utf-8"
    )


def _write_lookup_csv(numbers: list[Number]) -> None:
    LOOKUP_CSV.parent.mkdir(parents=True, exist_ok=True)
    with LOOKUP_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["macro_name", "group", "description", "rendered", "unit", "n_exps"])
        for n in sorted(numbers, key=lambda x: (x.group, x.macro_name)):
            w.writerow([
                n.macro_name, n.group, n.description, n.rendered, n.unit or "",
                len(n.experiment_ids),
            ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Evaluate only one group (e.g. 'rq1_aggregate').")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print rendered values, do not write files.")
    parser.add_argument("--verify", action="store_true",
                        help="Cross-check subset against 45_chapter_numbers.py output.")
    parser.add_argument("--use-cache", action="store_true",
                        help=f"Reuse values from {CACHE_JSON.name}. Numbers not in the cache still hit the DB.")
    args = parser.parse_args()

    if registry_size() == 0:
        print("No Number definitions registered — import thesis_numbers.definitions.", file=sys.stderr)
        return 2

    cached = {}
    if args.use_cache:
        if not CACHE_JSON.exists():
            print(f"--use-cache given but {CACHE_JSON} does not exist. Run once without it.", file=sys.stderr)
            return 2
        cached = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
        print(f"Using cached values from {CACHE_JSON} ({len(cached)} entries).")

    print(f"Evaluating {registry_size()} registered numbers …")
    t0 = time.time()
    numbers = []
    skipped_nan = []
    last_dump = t0
    for n in all_numbers():
        if args.only and n.group != args.only:
            continue
        if args.use_cache and _cache_load_into(n, cached):
            pass  # no SQL, rendered value already populated
        else:
            try:
                _evaluate(n)
            except Exception as exc:
                print(f"  [FAIL] \\{n.macro_name}: {exc}", file=sys.stderr)
                # Dump partial cache so we don't lose the progress
                if numbers:
                    _cache_dump(numbers)
                    print(f"  partial cache saved to {CACHE_JSON.name}", file=sys.stderr)
                raise
        # Skip Numbers whose raw value is NaN — typically (arch, hw, auth)
        # combinations that have no data (e.g. argon2id on FaaS-256). Handles
        # scalar floats, tuple-valued results (Welch-t triples), and cache
        # reloads (where raw_value is None but rendered contains 'nan').
        def _has_nan(v, rendered: str):
            if isinstance(v, float):
                return math.isnan(v)
            if isinstance(v, tuple):
                return any(isinstance(x, float) and math.isnan(x) for x in v)
            return "nan" in rendered.lower()

        if _has_nan(n.raw_value, n.rendered):
            skipped_nan.append(n.macro_name)
            continue
        numbers.append(n)
        print(f"  \\{n.macro_name:<55s} = {n.rendered}")
        # Incremental cache dump every 60s to survive partial failures.
        if time.time() - last_dump > 60 and not args.use_cache:
            _cache_dump(numbers)
            last_dump = time.time()
    if skipped_nan:
        print(f"Skipped {len(skipped_nan)} numbers with no data (first: {skipped_nan[:3]}).")
    print(f"Done in {time.time() - t0:.1f}s.\n")

    if args.dry_run:
        return 0

    # Always refresh the cache with whatever was computed this run.
    _cache_dump(numbers)

    meta = _dataset_meta(numbers)
    _write_numbers_tex(numbers, meta)
    _write_appendix_tex(numbers, meta)
    _write_lookup_csv(numbers)

    print(f"Wrote {NUMBERS_TEX} ({len(numbers)} macros)")
    print(f"Wrote {APPENDIX_TEX}")
    print(f"Wrote {LOOKUP_CSV}")

    if args.verify:
        from thesis_numbers.verify import cross_check  # lazy
        cross_check(numbers)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
