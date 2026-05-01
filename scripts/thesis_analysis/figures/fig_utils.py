"""Shared utilities for figure wrapper scripts."""
import importlib
import os
import sys

_SCRIPT_DIR = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, _SCRIPT_DIR)

from db_connection import PLOT_DIR


def run_existing_script(script_num, target_pdf):
    """Run an existing numbered script's main() and verify target_pdf was produced.

    Args:
        script_num: int, e.g. 37 for '37_distribution_visualization.py'
        target_pdf: str, filename like 'qq_latency.pdf'
    """
    pattern = f"{script_num:02d}_"
    candidates = [
        f for f in os.listdir(_SCRIPT_DIR)
        if f.startswith(pattern) and f.endswith('.py')
    ]
    if not candidates:
        raise FileNotFoundError(f"No script matching {pattern}*.py in {_SCRIPT_DIR}")

    module_name = candidates[0][:-3]

    old_cwd = os.getcwd()
    os.chdir(_SCRIPT_DIR)
    try:
        mod = importlib.import_module(module_name)
        mod.main()
    finally:
        os.chdir(old_cwd)

    out_path = os.path.join(PLOT_DIR, target_pdf)
    if not os.path.exists(out_path):
        raise FileNotFoundError(f"Expected output not found: {out_path}")
    print(f"Verified: {out_path}")
