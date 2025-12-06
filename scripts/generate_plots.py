#!/usr/bin/env python3
"""
BeFaaS Plot Generation Script

This script has been refactored into modular components.
The plotting functionality is now organized in the `plotting/` package:

- plotting/constants.py          - Shared constants and configuration
- plotting/utils.py              - Utility functions
- plotting/data_extraction.py    - Data analysis functions
- plotting/generate_baseline_plot.py     - Overall response time plots
- plotting/generate_endpoint_plots.py    - Per-endpoint performance plots
- plotting/generate_category_plots.py    - Category-based plots
- plotting/generate_auth_plots.py        - Authentication analysis plots
- plotting/generate_pricing_plots.py     - Cloud pricing analysis
- plotting/generate_callgraph_plots.py   - Function call graph visualization
- plotting/generate_stress_ramp_plot.py  - Stress test ramp/scaling plots
- plotting/generate_stress_auth_plot.py  - Stress test auth-specific plots
- plotting/main.py                       - Main CLI entry point

Usage:
    python generate_plots.py <data_path> <output_path> [options]

Options:
    --baseline      Generate baseline/overall response time plots
    --endpoint      Generate endpoint performance plots
    --category      Generate category-based plots
    --auth          Generate authentication analysis plots
    --pricing       Generate pricing analysis plots
    --callgraph     Generate function call graph plots
    --stress-ramp   Generate stress test ramp/scaling plots
    --stress-auth   Generate stress test auth-specific plots
    --all           Generate all plots (default)
    --exclude-warmup    Exclude warmup period from pure performance plots (default)
    --include-warmup    Include warmup period in all plots
"""

import sys
import os

# Add the scripts directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from plotting.main import main, generate_all_plots

# Re-export key functions for backward compatibility
from plotting.constants import *
from plotting.utils import *
from plotting.data_extraction import *
from plotting.generate_baseline_plot import (
    plot_response_time_histogram,
    plot_response_time_boxplot,
    plot_violin,
    plot_cdf,
    plot_percentiles,
    generate_baseline_plots
)
from plotting.generate_endpoint_plots import (
    plot_endpoint_response_times,
    plot_endpoint_request_count,
    generate_endpoint_plots
)
from plotting.generate_category_plots import (
    plot_category_boxplot,
    generate_category_plots
)
from plotting.generate_auth_plots import (
    plot_auth_boxplot,
    generate_auth_plots
)
from plotting.generate_pricing_plots import (
    calculate_pricing_data,
    generate_pricing_plots
)
from plotting.generate_callgraph_plots import (
    plot_function_call_graph,
    generate_callgraph_plots
)
from plotting.generate_stress_ramp_plot import (
    plot_stress_response_vs_load,
    plot_stress_scaling_timeline,
    generate_stress_ramp_plots
)
from plotting.generate_stress_auth_plot import (
    plot_stress_auth_response_vs_load,
    generate_stress_auth_plots
)

if __name__ == '__main__':
    main()