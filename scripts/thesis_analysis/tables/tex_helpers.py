"""Shared utilities for table-generation scripts."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_connection import PLOT_DIR


def write_tex_table(filename, content):
    """Write a .tex table fragment to PLOT_DIR."""
    path = os.path.join(PLOT_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Wrote: {path}")
    return path


def fmt_ms(val, decimals=0):
    """Format a millisecond value for LaTeX (German locale uses dot as thousands sep)."""
    if val is None or (isinstance(val, float) and (val != val)):
        return '--'
    if decimals == 0:
        formatted = f"{int(round(val)):,}".replace(',', '\\,')
    else:
        formatted = f"{val:,.{decimals}f}".replace(',', '\\,')
    return formatted


def fmt_pct(val, decimals=1):
    """Format a percentage value."""
    if val is None or (isinstance(val, float) and (val != val)):
        return '--'
    return f"{val:.{decimals}f}\\,\\%"


def fmt_delta(val, decimals=0):
    """Format a delta value with explicit sign."""
    if val is None or (isinstance(val, float) and (val != val)):
        return '--'
    if decimals == 0:
        v = int(round(val))
        return f"+{v}" if v > 0 else str(v)
    else:
        return f"+{val:.{decimals}f}" if val > 0 else f"{val:.{decimals}f}"


def escape_latex(s):
    """Escape LaTeX special characters in a string."""
    replacements = {
        '&': '\\&', '%': '\\%', '$': '\\$', '#': '\\#',
        '_': '\\_', '{': '\\{', '}': '\\}', '~': '\\textasciitilde{}',
        '^': '\\textasciicircum{}',
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s
