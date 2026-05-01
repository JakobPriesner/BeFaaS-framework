"""Shared database connection for thesis analysis scripts."""

import psycopg2
import pandas as pd
import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

DB_CONFIG = {
    'host': '192.168.178.22',
    'port': 5437,
    'database': 'postgres',
    'user': 'postgres',
    'password': 'jxmEaRj^R5@5wF1@SQvCPi4&eqdG7B3y',
    'gssencmode': 'disable',
}

PLOT_DIR = '/Users/jakob/Downloads/thesisV2/plots'
os.makedirs(PLOT_DIR, exist_ok=True)

# Experiments that must be excluded from analysis fall into two buckets:
#
# 1. Duplicate imports (same benchmark_start_ms, 100% x_pair overlap) —
#    marked in-place with `experiments.import_failure` by
#    `db_import/migrations/cleanup_duplicate_benchmarks.py`. Row stays in the
#    database for audit, but analyses filter it out via `import_failure IS NULL`.
#
# 2. Truly broken experiments that are NOT caused by duplicate import.
#    Load-induced failures (high error rates, <7 phases due to system
#    saturation) are NOT excluded — they represent valid system behavior.
#
#    Exp 3:   edge auth config bug (33% error rate constant across ALL phases
#             including Baseline)
#    Exp 85:  docker build error mid-run, only 4 phases, Stabilization P50=10.8s
#    Exp 179, 191, 192: benchmark misconfiguration — ram_in_mb set to 1796
#             instead of the intended FaaS max of 1769 MB. Not a dataset typo
#             but a runtime misconfiguration, so these runs use a hardware
#             tier outside the defined sweep and must be excluded.
BROKEN_EXPERIMENTS = [3, 85, 179, 191, 192]

# SQL fragment used by all analysis scripts. Joins on experiments `e` are
# required. Filters out both buckets.
EXCLUDE_SQL = (
    "e.import_failure IS NULL"
    + (f" AND e.id NOT IN ({','.join(str(x) for x in BROKEN_EXPERIMENTS)})"
       if BROKEN_EXPERIMENTS else "")
)

# Variant for queries that only touch a child table (e.g. requests) and do NOT
# join the experiments table. Uses a subquery so neither `e.id` nor
# `e.import_failure` needs to be resolved at the outer level.
EXCLUDE_SQL_BY_EXP_ID = (
    "experiment_id NOT IN ("
    "SELECT id FROM experiments WHERE import_failure IS NOT NULL"
    + (f" OR id IN ({','.join(str(x) for x in BROKEN_EXPERIMENTS)})"
       if BROKEN_EXPERIMENTS else "")
    + ")"
)


def get_excluded_experiment_ids():
    """Return the full list of excluded experiment IDs (duplicates + broken).

    Duplicates are looked up from the database (`import_failure IS NOT NULL`)
    so the list always matches whatever was marked by the cleanup migration.
    Broken experiments are appended from the static BROKEN_EXPERIMENTS list.
    """
    try:
        df = query_df(
            "SELECT id FROM experiments WHERE import_failure IS NOT NULL"
        )
        dup_ids = df['id'].tolist()
    except Exception:
        # Column may not exist yet before the migration has been run.
        dup_ids = []
    return sorted(set(dup_ids) | set(BROKEN_EXPERIMENTS))


def __getattr__(name):
    """Lazy compatibility: `EXCLUDED_EXPERIMENTS` still works for legacy callers."""
    if name == 'EXCLUDED_EXPERIMENTS':
        return get_excluded_experiment_ids()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        c = DB_CONFIG
        _engine = create_engine(
            f"postgresql+psycopg2://{quote_plus(c['user'])}:{quote_plus(c['password'])}@{c['host']}:{c['port']}/{c['database']}",
            connect_args={'gssencmode': c['gssencmode']},
        )
    return _engine


def get_connection():
    """Return a raw psycopg2 connection (for callers that use it directly)."""
    return psycopg2.connect(**DB_CONFIG)


def query_df(sql, params=None):
    with _get_engine().connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params)


# ── Shared auth-label helpers ──

def auth_label_detailed(auth_strategy, algo=None, with_cf=None):
    """Generate a detailed auth label that differentiates algorithm and CloudFront.

    Examples:
        'none', None, False  → 'None'
        'none', None, True   → 'None+CF'
        'service-integrated', None, False → 'Cognito'
        'service-integrated', None, True  → 'Cognito+CF'
        'service-integrated-manual', 'bcrypt', False → 'Manual (bcrypt)'
        'service-integrated-manual', 'argon2id', True → 'Manual (argon2id)+CF'
        'edge', None, True → 'Edge+CF'
    """
    base_map = {
        'none': 'None',
        'service-integrated': 'Cognito',
        'edge': 'Edge',
        'edge-selective': 'Edge-Sel.',
    }

    if auth_strategy == 'service-integrated-manual':
        algo_str = algo if algo and algo not in ('default', 'N/A') else 'bcrypt'
        label = f"Manual ({algo_str})"
    else:
        label = base_map.get(auth_strategy, auth_strategy)

    # Edge and Edge-Selective always use CloudFront (Lambda@Edge runs on CF),
    # so +CF is redundant and should not be appended.
    if with_cf is True and auth_strategy not in ('edge', 'edge-selective'):
        label += '+CF'

    return label


def hw_label_from_row(row):
    """Compute hardware label from a row/dict with architecture, ram_in_mb, cpu_in_vcpu."""
    arch = row.get('architecture', row.get('arch', ''))
    if arch == 'faas':
        return f"{row['ram_in_mb']}MB"
    cpu = row.get('cpu_in_vcpu', row.get('cpu', 0))
    mapping = {0.25: 'S', 0.5: 'M', 1.0: 'L', 4.0: 'XL'}
    return mapping.get(float(cpu), f"{cpu}vCPU")


# ── Shared color maps ──

AUTH_COLORS_DETAILED = {
    'None':               '#95a5a6',
    'None+CF':            '#b0bec5',
    'Cognito':            '#2196F3',
    'Cognito+CF':         '#64B5F6',
    'Manual (bcrypt)':    '#F44336',
    'Manual (bcrypt)+CF': '#EF9A9A',
    'Manual (argon2id)':  '#E91E63',
    'Manual (argon2id)+CF': '#F48FB1',
    'Edge':               '#4CAF50',  # Edge always uses CF, no separate +CF variant
    'Edge-Sel.':          '#FF9800',  # Edge-Selective always uses CF, no separate +CF variant
}

# Marker styles for line plots
AUTH_MARKERS_DETAILED = {
    'Cognito': 'o', 'Cognito+CF': 'o',
    'Manual (bcrypt)': 's', 'Manual (bcrypt)+CF': 's',
    'Manual (argon2id)': 'D', 'Manual (argon2id)+CF': 'D',
    'Edge': '^',
    'Edge-Sel.': 'v',
}

# Linestyles: solid for non-CF, dashed for CF (Edge/Edge-Sel. always solid — CF is implicit)
AUTH_LINESTYLES = {k: ('--' if '+CF' in k else '-') for k in AUTH_COLORS_DETAILED}

# Simplified auth colors (for scripts using short labels: None/Cognito/Manual/Edge)
# Derived from AUTH_COLORS_DETAILED to maintain visual consistency across all plots.
AUTH_COLORS = {
    'None':      AUTH_COLORS_DETAILED['None'],             # '#95a5a6'
    'Cognito':   AUTH_COLORS_DETAILED['Cognito'],          # '#2196F3'
    'Manual':    AUTH_COLORS_DETAILED['Manual (bcrypt)'],   # '#F44336'
    'Edge':      AUTH_COLORS_DETAILED['Edge'],              # '#4CAF50'
    'Edge-Sel.': AUTH_COLORS_DETAILED['Edge-Sel.'],        # '#FF9800'
}

# Architecture colors (consistent across all plots)
ARCH_COLORS = {
    'faas':            '#3498db',
    'microservices':   '#e74c3c',
    'monolith':        '#2ecc71',
}

# Hardware tiers per architecture
HW_TIERS_ALL = {
    'faas': [
        (256, 0, '256MB'),
        (512, 0, '512MB'),
        (1024, 0, '1024MB'),
        (1769, 0, '1769MB'),
    ],
    'microservices': [
        (512, 0.25, 'S'),
        (1024, 0.5, 'M'),
        (2048, 1.0, 'L'),
        (8192, 4.0, 'XL'),
    ],
    'monolith': [
        (512, 0.25, 'S'),
        (1024, 0.5, 'M'),
        (2048, 1.0, 'L'),
        (8192, 4.0, 'XL'),
    ],
}


# Standard SQL fragment for detailed auth queries (includes algo and CF)
DETAILED_AUTH_SQL = """
    COALESCE(e.password_hash_algorithm, 'default') AS algo,
    COALESCE(e.with_cloudfront, false) AS with_cf
"""

# JWKS mode filter fragments (for Edge buildtime/runtime comparison)
JWKS_BUILDTIME_SQL = "e.jwks_mode = 'buildtime'"
JWKS_RUNTIME_SQL = "e.jwks_mode = 'runtime'"

JWKS_MODE_COLORS = {
    'buildtime': '#81C784',   # lighter green (v1, legacy)
    'runtime':   '#2E7D32',   # darker green (v2, production-faithful)
}

JWKS_MODE_LABELS = {
    'buildtime': 'Build-Time-JWKS (v1)',
    'runtime':   'Laufzeit-JWKS (v2)',
}