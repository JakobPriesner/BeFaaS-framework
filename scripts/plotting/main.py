#!/usr/bin/env python3
"""
Main entry point for BeFaaS plot generation.

Usage:
    python -m plotting.main <data_path> <output_path> [options]

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

import os
import sys
import argparse
import json

from .data_extraction import (
    analyze_response_times_from_pairs,
    analyze_auth_requests,
    analyze_function_auth_delays,
    extract_detailed_request_data
)
from .generate_baseline_plot import generate_baseline_plots
from .generate_endpoint_plots import generate_endpoint_plots
from .generate_category_plots import generate_category_plots
from .generate_auth_plots import generate_auth_plots
from .generate_pricing_plots import generate_pricing_plots
from .generate_callgraph_plots import generate_callgraph_plots
from .generate_stress_ramp_plot import generate_stress_ramp_plots
from .generate_stress_auth_plot import generate_stress_auth_plots


def load_data(data_path):
    """Load JSON data from file"""
    print(f"Loading data from {data_path}...")
    with open(data_path, 'r') as f:
        data = json.load(f)
    print(f"  Loaded {len(data)} entries")
    return data


def generate_all_plots(data_path, output_dir, options=None):
    """Generate all plots for a given data file"""
    if options is None:
        options = {
            'baseline': True,
            'endpoint': True,
            'category': True,
            'auth': True,
            'pricing': True,
            'callgraph': True,
            'stress_ramp': True,
            'stress_auth': True,
            'exclude_warmup': True,
        }

    os.makedirs(output_dir, exist_ok=True)

    data = load_data(data_path)

    print("\n--- Analyzing Data ---")
    response_times, endpoint_times, category_times = analyze_response_times_from_pairs(data)
    auth_times = analyze_auth_requests(data)
    function_times = analyze_function_auth_delays(data)

    print(f"  Total response times: {len(response_times)}")
    print(f"  Endpoints found: {len(endpoint_times)}")
    print(f"  Categories found: {len(category_times)}")

    if options.get('baseline', True):
        generate_baseline_plots(response_times, output_dir, data=data, exclude_warmup=options.get('exclude_warmup', True))

    if options.get('endpoint', True):
        generate_endpoint_plots(endpoint_times, output_dir)

    if options.get('category', True):
        generate_category_plots(category_times, output_dir)

    if options.get('auth', True):
        generate_auth_plots(data, auth_times, function_times, output_dir)

    if options.get('pricing', True):
        generate_pricing_plots(data, endpoint_times, output_dir)

    if options.get('callgraph', True):
        generate_callgraph_plots(output_dir)

    if options.get('stress_ramp', True):
        generate_stress_ramp_plots(data, output_dir)

    if options.get('stress_auth', True):
        generate_stress_auth_plots(data, output_dir)

    print(f"\n=== All plots saved to {output_dir} ===")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description='Generate BeFaaS analysis plots')
    parser.add_argument('data_path', help='Path to JSON data file')
    parser.add_argument('output_dir', help='Output directory for plots')
    parser.add_argument('--baseline', action='store_true', help='Generate baseline plots')
    parser.add_argument('--endpoint', action='store_true', help='Generate endpoint plots')
    parser.add_argument('--category', action='store_true', help='Generate category plots')
    parser.add_argument('--auth', action='store_true', help='Generate auth plots')
    parser.add_argument('--pricing', action='store_true', help='Generate pricing plots')
    parser.add_argument('--callgraph', action='store_true', help='Generate call graph plots')
    parser.add_argument('--stress-ramp', action='store_true', help='Generate stress ramp plots')
    parser.add_argument('--stress-auth', action='store_true', help='Generate stress auth plots')
    parser.add_argument('--all', action='store_true', help='Generate all plots (default)')
    parser.add_argument('--exclude-warmup', action='store_true', default=True, help='Exclude warmup period (default)')
    parser.add_argument('--include-warmup', action='store_true', help='Include warmup period')

    args = parser.parse_args()

    specific_selected = any([
        args.baseline, args.endpoint, args.category, args.auth,
        args.pricing, args.callgraph, args.stress_ramp, args.stress_auth
    ])

    if args.all or not specific_selected:
        options = {
            'baseline': True,
            'endpoint': True,
            'category': True,
            'auth': True,
            'pricing': True,
            'callgraph': True,
            'stress_ramp': True,
            'stress_auth': True,
            'exclude_warmup': not args.include_warmup,
        }
    else:
        options = {
            'baseline': args.baseline,
            'endpoint': args.endpoint,
            'category': args.category,
            'auth': args.auth,
            'pricing': args.pricing,
            'callgraph': args.callgraph,
            'stress_ramp': args.stress_ramp,
            'stress_auth': args.stress_auth,
            'exclude_warmup': not args.include_warmup,
        }

    generate_all_plots(args.data_path, args.output_dir, options)


if __name__ == '__main__':
    main()