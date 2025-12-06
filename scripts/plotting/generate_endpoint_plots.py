"""
Endpoint performance plots for BeFaaS analysis.
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from collections import defaultdict

from .utils import categorize_endpoint, get_category_colors


def plot_endpoint_response_times(endpoint_times, output_path):
    """Create horizontal box plot showing response times per endpoint"""
    if not endpoint_times:
        print("No endpoint timing data found")
        return

    filtered = {k: v for k, v in endpoint_times.items() if len(v) >= 10}

    if not filtered:
        print("Not enough data for endpoint timing plot")
        return

    sorted_endpoints = sorted(filtered.items(), key=lambda x: np.median(x[1]))

    fig, ax = plt.subplots(figsize=(14, max(6, len(sorted_endpoints) * 0.5)))

    labels = [ep for ep, _ in sorted_endpoints]
    data_to_plot = [times for _, times in sorted_endpoints]

    bp = ax.boxplot(data_to_plot, tick_labels=labels, vert=False, patch_artist=True)

    category_colors = get_category_colors()

    for i, (patch, endpoint) in enumerate(zip(bp['boxes'], labels)):
        category = categorize_endpoint(endpoint)
        patch.set_facecolor(category_colors.get(category, '#95a5a6'))
        patch.set_alpha(0.7)

    ax.set_xlabel('Response Time (ms)', fontsize=12)
    ax.set_ylabel('Endpoint', fontsize=12)
    ax.set_title('Response Time by Endpoint', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='x')

    legend_patches = [mpatches.Patch(color=c, label=cat, alpha=0.7)
                     for cat, c in category_colors.items()]
    ax.legend(handles=legend_patches, loc='lower right', fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved endpoint response times to {output_path}")
    plt.close()


def plot_endpoint_mean(endpoint_times, output_path):
    """Create bar chart showing mean response time per endpoint"""
    if not endpoint_times:
        print("No endpoint timing data found")
        return

    filtered = {k: v for k, v in endpoint_times.items() if len(v) >= 10}
    if not filtered:
        print("Not enough data for endpoint mean plot")
        return

    sorted_endpoints = sorted(filtered.items(), key=lambda x: -len(x[1]))[:12]
    endpoints = [ep for ep, _ in sorted_endpoints]
    means = [np.mean(times) for _, times in sorted_endpoints]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(endpoints))
    bars = ax.bar(x, means, color='steelblue', alpha=0.8)
    ax.set_xlabel('Endpoint')
    ax.set_ylabel('Mean Response Time (ms)')
    ax.set_title('Mean Response Time by Endpoint')
    ax.set_xticks(x)
    ax.set_xticklabels(endpoints, rotation=45, ha='right')
    ax.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val:.0f}', ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved endpoint mean plot to {output_path}")
    plt.close()


def plot_endpoint_median(endpoint_times, output_path):
    """Create bar chart showing median response time per endpoint"""
    if not endpoint_times:
        print("No endpoint timing data found")
        return

    filtered = {k: v for k, v in endpoint_times.items() if len(v) >= 10}
    if not filtered:
        print("Not enough data for endpoint median plot")
        return

    sorted_endpoints = sorted(filtered.items(), key=lambda x: -len(x[1]))[:12]
    endpoints = [ep for ep, _ in sorted_endpoints]
    medians = [np.median(times) for _, times in sorted_endpoints]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(endpoints))
    bars = ax.bar(x, medians, color='forestgreen', alpha=0.8)
    ax.set_xlabel('Endpoint')
    ax.set_ylabel('Median Response Time (ms)')
    ax.set_title('Median (P50) Response Time by Endpoint')
    ax.set_xticks(x)
    ax.set_xticklabels(endpoints, rotation=45, ha='right')
    ax.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, medians):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val:.0f}', ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved endpoint median plot to {output_path}")
    plt.close()


def plot_endpoint_p95(endpoint_times, output_path):
    """Create bar chart showing P95 response time per endpoint"""
    if not endpoint_times:
        print("No endpoint timing data found")
        return

    filtered = {k: v for k, v in endpoint_times.items() if len(v) >= 10}
    if not filtered:
        print("Not enough data for endpoint P95 plot")
        return

    sorted_endpoints = sorted(filtered.items(), key=lambda x: -len(x[1]))[:12]
    endpoints = [ep for ep, _ in sorted_endpoints]
    p95s = [np.percentile(times, 95) for _, times in sorted_endpoints]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(endpoints))
    bars = ax.bar(x, p95s, color='darkorange', alpha=0.8)
    ax.set_xlabel('Endpoint')
    ax.set_ylabel('P95 Response Time (ms)')
    ax.set_title('95th Percentile Response Time by Endpoint')
    ax.set_xticks(x)
    ax.set_xticklabels(endpoints, rotation=45, ha='right')
    ax.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, p95s):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val:.0f}', ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved endpoint P95 plot to {output_path}")
    plt.close()


def plot_endpoint_p99(endpoint_times, output_path):
    """Create bar chart showing P99 response time per endpoint"""
    if not endpoint_times:
        print("No endpoint timing data found")
        return

    filtered = {k: v for k, v in endpoint_times.items() if len(v) >= 10}
    if not filtered:
        print("Not enough data for endpoint P99 plot")
        return

    sorted_endpoints = sorted(filtered.items(), key=lambda x: -len(x[1]))[:12]
    endpoints = [ep for ep, _ in sorted_endpoints]
    p99s = [np.percentile(times, 99) for _, times in sorted_endpoints]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(endpoints))
    bars = ax.bar(x, p99s, color='crimson', alpha=0.8)
    ax.set_xlabel('Endpoint')
    ax.set_ylabel('P99 Response Time (ms)')
    ax.set_title('99th Percentile Response Time by Endpoint')
    ax.set_xticks(x)
    ax.set_xticklabels(endpoints, rotation=45, ha='right')
    ax.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, p99s):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val:.0f}', ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved endpoint P99 plot to {output_path}")
    plt.close()


def plot_endpoint_request_count(endpoint_times, output_path):
    """Create bar chart showing request count by endpoint"""
    if not endpoint_times:
        print("No endpoint timing data found")
        return

    sorted_endpoints = sorted(endpoint_times.items(), key=lambda x: -len(x[1]))
    endpoints = [ep for ep, _ in sorted_endpoints[:15]]
    counts = [len(times) for _, times in sorted_endpoints[:15]]

    category_colors = get_category_colors()
    colors = [category_colors.get(categorize_endpoint(ep), '#95a5a6') for ep in endpoints]

    fig, ax = plt.subplots(figsize=(12, 8))
    bars = ax.barh(endpoints[::-1], counts[::-1], color=colors[::-1], alpha=0.8)
    ax.set_xlabel('Number of Requests', fontsize=12)
    ax.set_ylabel('Endpoint', fontsize=12)
    ax.set_title('Request Count by Endpoint', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='x')

    for bar, count in zip(bars, counts[::-1]):
        ax.text(bar.get_width() + 5, bar.get_y() + bar.get_height()/2,
                f'{count}', va='center', fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved endpoint request count to {output_path}")
    plt.close()


def plot_category_pie(endpoint_times, output_path):
    """Create pie chart showing requests by category"""
    if not endpoint_times:
        print("No endpoint timing data found")
        return

    category_colors = get_category_colors()

    category_counts = defaultdict(int)
    for ep, times in endpoint_times.items():
        cat = categorize_endpoint(ep)
        category_counts[cat] += len(times)

    cats = list(category_counts.keys())
    cat_counts = [category_counts[c] for c in cats]
    cat_colors = [category_colors.get(c, '#95a5a6') for c in cats]

    fig, ax = plt.subplots(figsize=(10, 8))
    wedges, texts, autotexts = ax.pie(cat_counts, labels=cats, colors=cat_colors,
                                       autopct='%1.1f%%', startangle=90,
                                       textprops={'fontsize': 11})
    ax.set_title('Requests by Category', fontsize=14, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved category pie chart to {output_path}")
    plt.close()


def generate_endpoint_plots(endpoint_times, output_dir):
    """Generate all endpoint performance plots"""
    print("\n--- Generating Endpoint Performance Plots ---")

    if not endpoint_times:
        print("No endpoint timing data available")
        return

    plot_endpoint_response_times(endpoint_times, os.path.join(output_dir, "endpoint_response_times.png"))
    plot_endpoint_mean(endpoint_times, os.path.join(output_dir, "endpoint_mean.png"))
    plot_endpoint_median(endpoint_times, os.path.join(output_dir, "endpoint_median.png"))
    plot_endpoint_p95(endpoint_times, os.path.join(output_dir, "endpoint_p95.png"))
    plot_endpoint_p99(endpoint_times, os.path.join(output_dir, "endpoint_p99.png"))
    plot_endpoint_request_count(endpoint_times, os.path.join(output_dir, "endpoint_request_count.png"))
    plot_category_pie(endpoint_times, os.path.join(output_dir, "category_pie.png"))