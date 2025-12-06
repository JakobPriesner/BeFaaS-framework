"""
Authentication analysis plots for BeFaaS analysis.
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from scipy import stats

from .utils import parse_datetime, is_auth_endpoint
from .constants import AUTH_REQUIRED_FUNCTIONS, FUNCTION_CALL_GRAPH
from .data_extraction import extract_detailed_request_data, analyze_auth_requests


def get_auth_endpoint_data(data):
    """Extract auth endpoint timing data"""
    auth_endpoints = {
        'register': [],
        'setUser': [],
        'login': [],
        'logout': [],
        'auth': [],
        'token': [],
        'verify': []
    }

    requests = {}
    for entry in data:
        if '__logentry__' not in entry:
            continue
        log = entry['__logentry__']
        event = log.get('data', {}).get('event', {})

        if 'contextId' not in event:
            continue

        ctx_id = event['contextId']
        ts = log.get('data', {}).get('timestamp', 0)
        req_type = event.get('type', '')
        url = event.get('url', '')

        if ctx_id not in requests:
            requests[ctx_id] = {}

        if req_type == 'before':
            requests[ctx_id]['before'] = ts
            requests[ctx_id]['url'] = url
        elif req_type == 'after':
            requests[ctx_id]['after'] = ts

    for ctx_id, req in requests.items():
        if 'before' in req and 'after' in req:
            duration = req['after'] - req['before']
            if duration > 0 and duration < 60000:
                url = req.get('url', '').lower()
                for auth_ep in auth_endpoints.keys():
                    if auth_ep.lower() in url:
                        auth_endpoints[auth_ep].append(duration)
                        break

    return {k: v for k, v in auth_endpoints.items() if len(v) >= 5}


def plot_auth_boxplot(auth_times, output_path):
    """Create auth vs non-auth box plot comparison"""
    if not auth_times or 'auth' not in auth_times:
        print("No authentication data found")
        return

    auth_data = auth_times.get('auth', [])
    non_auth_data = auth_times.get('non-auth', [])

    if len(auth_data) < 5:
        print("Not enough authentication requests for analysis")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    bp = ax.boxplot([auth_data, non_auth_data],
                    tick_labels=['Auth Endpoints', 'Non-Auth Endpoints'],
                    patch_artist=True)
    bp['boxes'][0].set_facecolor('#9b59b6')
    bp['boxes'][1].set_facecolor('#3498db')
    for patch in bp['boxes']:
        patch.set_alpha(0.7)
    ax.set_ylabel('Response Time (ms)')
    ax.set_title('Authentication vs Non-Authentication Endpoints')
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved auth box plot to {output_path}")
    plt.close()


def plot_auth_metrics_comparison(auth_times, output_path):
    """Create auth vs non-auth metrics comparison"""
    if not auth_times or 'auth' not in auth_times:
        print("No authentication data found")
        return

    auth_data = auth_times.get('auth', [])
    non_auth_data = auth_times.get('non-auth', [])

    if len(auth_data) < 5 or len(non_auth_data) < 5:
        print("Not enough data for auth metrics comparison")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    metrics = ['Mean', 'Median', 'P95', 'P99']
    auth_values = [np.mean(auth_data), np.median(auth_data),
                  np.percentile(auth_data, 95), np.percentile(auth_data, 99)]
    non_auth_values = [np.mean(non_auth_data), np.median(non_auth_data),
                      np.percentile(non_auth_data, 95), np.percentile(non_auth_data, 99)]

    x = np.arange(len(metrics))
    width = 0.35

    ax.bar(x - width/2, auth_values, width, label='Auth', color='#9b59b6', alpha=0.8)
    ax.bar(x + width/2, non_auth_values, width, label='Non-Auth', color='#3498db', alpha=0.8)

    ax.set_xlabel('Metric')
    ax.set_ylabel('Response Time (ms)')
    ax.set_title('Auth vs Non-Auth Response Time Metrics')
    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved auth metrics comparison to {output_path}")
    plt.close()


def plot_auth_histogram(auth_times, output_path):
    """Create auth vs non-auth histogram comparison"""
    if not auth_times or 'auth' not in auth_times:
        print("No authentication data found")
        return

    auth_data = auth_times.get('auth', [])
    non_auth_data = auth_times.get('non-auth', [])

    if len(auth_data) < 5 or len(non_auth_data) < 5:
        print("Not enough data for auth histogram")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    bins = np.linspace(0, max(max(auth_data), max(non_auth_data)), 40)
    ax.hist(auth_data, bins=bins, alpha=0.6, label='Auth', color='#9b59b6')
    ax.hist(non_auth_data, bins=bins, alpha=0.6, label='Non-Auth', color='#3498db')
    ax.set_xlabel('Response Time (ms)')
    ax.set_ylabel('Frequency')
    ax.set_title('Auth vs Non-Auth Response Time Distribution')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved auth histogram to {output_path}")
    plt.close()


def plot_auth_endpoint_boxplot(data, output_path):
    """Create auth endpoints box plot"""
    filtered = get_auth_endpoint_data(data)

    if not filtered:
        print("Not enough auth endpoint data for box plot")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    endpoints = list(filtered.keys())
    data_to_plot = [filtered[ep] for ep in endpoints]
    bp = ax.boxplot(data_to_plot, tick_labels=endpoints, patch_artist=True)
    colors = plt.cm.Purples(np.linspace(0.3, 0.8, len(endpoints)))
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.8)
    ax.set_xlabel('Auth Endpoint')
    ax.set_ylabel('Response Time (ms)')
    ax.set_title('Response Time by Auth Endpoint')
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved auth endpoint box plot to {output_path}")
    plt.close()


def plot_auth_delay_per_function(function_times, output_path):
    """Plot auth delay for each individual function call"""
    if not function_times:
        print("No function timing data for auth delay plot")
        return

    auth_times = {k: v for k, v in function_times.items()
                  if k.lower() in {f.lower() for f in AUTH_REQUIRED_FUNCTIONS} and len(v) >= 5}

    if not auth_times:
        print("No auth function timing data available")
        return

    sorted_funcs = sorted(auth_times.items(), key=lambda x: np.mean(x[1]))

    fig, ax = plt.subplots(figsize=(14, max(6, len(sorted_funcs) * 0.8)))

    labels = [f[0] for f in sorted_funcs]
    data_to_plot = [f[1] for f in sorted_funcs]

    bp = ax.boxplot(data_to_plot, tick_labels=labels, vert=False, patch_artist=True)

    colors = plt.cm.Reds(np.linspace(0.3, 0.8, len(labels)))
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.8)

    ax.set_xlabel('Response Time (ms)', fontsize=12)
    ax.set_ylabel('Auth-Required Function', fontsize=12)
    ax.set_title('Authentication Delay per Function\n(Functions requiring JWT verification)',
                fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='x')

    for i, (name, times) in enumerate(sorted_funcs):
        mean_val = np.mean(times)
        ax.text(max(times) + 10, i + 1, f'u={mean_val:.0f}ms (n={len(times)})',
               va='center', fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved auth delay per function to {output_path}")
    plt.close()


def plot_combined_auth_analysis(function_times, output_path):
    """Create a combined view of auth analysis: bar chart comparing auth vs non-auth functions"""
    if not function_times:
        print("No function timing data for combined auth analysis")
        return

    auth_funcs = {}
    non_auth_funcs = {}

    for func, times in function_times.items():
        if len(times) < 5:
            continue
        func_lower = func.lower()
        if func_lower in {f.lower() for f in AUTH_REQUIRED_FUNCTIONS}:
            auth_funcs[func] = times
        else:
            non_auth_funcs[func] = times

    if not auth_funcs or not non_auth_funcs:
        print("Not enough data for combined auth analysis")
        return

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))

    ax1 = axes[0]

    all_funcs = list(auth_funcs.keys()) + list(non_auth_funcs.keys())
    means = [np.mean(auth_funcs.get(f, non_auth_funcs.get(f, []))) for f in all_funcs]
    colors = ['#E91E63' if f.lower() in {af.lower() for af in AUTH_REQUIRED_FUNCTIONS} else '#3498db'
              for f in all_funcs]

    sorted_indices = np.argsort(means)[::-1][:15]
    sorted_funcs = [all_funcs[i] for i in sorted_indices]
    sorted_means = [means[i] for i in sorted_indices]
    sorted_colors = [colors[i] for i in sorted_indices]

    y = np.arange(len(sorted_funcs))
    ax1.barh(y, sorted_means, color=sorted_colors, alpha=0.8)
    ax1.set_yticks(y)
    ax1.set_yticklabels(sorted_funcs)
    ax1.set_xlabel('Mean Response Time (ms)')
    ax1.set_title('Mean Response Time by Function')
    ax1.grid(True, alpha=0.3, axis='x')

    auth_patch = mpatches.Patch(color='#E91E63', label='Auth Required', alpha=0.8)
    non_auth_patch = mpatches.Patch(color='#3498db', label='No Auth Required', alpha=0.8)
    ax1.legend(handles=[auth_patch, non_auth_patch], loc='lower right')

    ax2 = axes[1]

    auth_all_times = [t for times in auth_funcs.values() for t in times]
    non_auth_all_times = [t for times in non_auth_funcs.values() for t in times]

    if auth_all_times and non_auth_all_times:
        metrics = ['Mean', 'Median', 'P95', 'P99']
        auth_vals = [np.mean(auth_all_times), np.median(auth_all_times),
                    np.percentile(auth_all_times, 95), np.percentile(auth_all_times, 99)]
        non_auth_vals = [np.mean(non_auth_all_times), np.median(non_auth_all_times),
                        np.percentile(non_auth_all_times, 95), np.percentile(non_auth_all_times, 99)]

        x = np.arange(len(metrics))
        width = 0.35

        ax2.bar(x - width/2, auth_vals, width, label='Auth Functions', color='#E91E63', alpha=0.8)
        ax2.bar(x + width/2, non_auth_vals, width, label='Non-Auth Functions', color='#3498db', alpha=0.8)

        ax2.set_ylabel('Response Time (ms)')
        ax2.set_title('Auth vs Non-Auth Function Performance')
        ax2.set_xticks(x)
        ax2.set_xticklabels(metrics)
        ax2.legend()
        ax2.grid(True, alpha=0.3, axis='y')

        overhead = np.mean(auth_all_times) - np.mean(non_auth_all_times)
        overhead_pct = (overhead / np.mean(non_auth_all_times)) * 100 if np.mean(non_auth_all_times) > 0 else 0
        ax2.text(0.5, 0.98, f'Auth overhead: {overhead:+.0f}ms ({overhead_pct:+.1f}%)',
                transform=ax2.transAxes, ha='center', va='top', fontsize=11,
                bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.5))

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved combined auth analysis to {output_path}")
    plt.close()


def generate_auth_plots(data, auth_times, function_times, output_dir):
    """Generate all authentication analysis plots"""
    print("\n--- Generating Authentication Analysis Plots ---")

    if auth_times:
        plot_auth_boxplot(auth_times, os.path.join(output_dir, "auth_boxplot.png"))
        plot_auth_metrics_comparison(auth_times, os.path.join(output_dir, "auth_metrics_comparison.png"))
        plot_auth_histogram(auth_times, os.path.join(output_dir, "auth_histogram.png"))

    plot_auth_endpoint_boxplot(data, os.path.join(output_dir, "auth_endpoint_boxplot.png"))

    if function_times:
        plot_auth_delay_per_function(function_times, os.path.join(output_dir, "auth_delay_per_function.png"))
        plot_combined_auth_analysis(function_times, os.path.join(output_dir, "auth_combined_analysis.png"))