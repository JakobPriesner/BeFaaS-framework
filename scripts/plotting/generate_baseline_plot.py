"""
Baseline/overall response time plots for BeFaaS analysis.
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .utils import add_warmup_excluded_indicator
from .data_extraction import filter_warmup_from_response_times


def plot_response_time_histogram(response_times, output_path, data=None, exclude_warmup=True):
    """Create response time histogram (with optional warmup exclusion)"""
    if data is not None and exclude_warmup:
        response_times, excluded = filter_warmup_from_response_times(data)
        warmup_filtered = excluded > 0
    else:
        warmup_filtered = False

    if not response_times:
        print("No response time data found")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(response_times, bins=50, edgecolor='black', alpha=0.7, color='steelblue')
    ax.axvline(np.mean(response_times), color='red', linestyle='--', label=f'Mean: {np.mean(response_times):.0f}ms')
    ax.axvline(np.median(response_times), color='green', linestyle='--', label=f'Median: {np.median(response_times):.0f}ms')
    ax.set_xlabel('Response Time (ms)')
    ax.set_ylabel('Frequency')
    ax.set_title('Response Time Distribution')
    ax.legend()
    ax.grid(True, alpha=0.3)

    if warmup_filtered:
        add_warmup_excluded_indicator(ax)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved response time histogram to {output_path}")
    plt.close()


def plot_response_time_boxplot(response_times, output_path, data=None, exclude_warmup=True):
    """Create response time box plot (with optional warmup exclusion)"""
    if data is not None and exclude_warmup:
        response_times, excluded = filter_warmup_from_response_times(data)
        warmup_filtered = excluded > 0
    else:
        warmup_filtered = False

    if not response_times:
        print("No response time data found")
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    bp = ax.boxplot(response_times, vert=True, patch_artist=True)
    bp['boxes'][0].set_facecolor('lightblue')
    bp['boxes'][0].set_alpha(0.7)
    ax.set_ylabel('Response Time (ms)')
    ax.set_title('Response Time Box Plot')
    ax.set_xticklabels(['All Requests'])
    ax.grid(True, alpha=0.3)

    stats_text = f'Mean: {np.mean(response_times):.2f}ms\n'
    stats_text += f'Median: {np.median(response_times):.2f}ms\n'
    stats_text += f'P95: {np.percentile(response_times, 95):.2f}ms\n'
    stats_text += f'P99: {np.percentile(response_times, 99):.2f}ms'
    ax.text(1.3, np.median(response_times), stats_text,
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    if warmup_filtered:
        add_warmup_excluded_indicator(ax)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved response time box plot to {output_path}")
    plt.close()


def plot_violin(response_times, output_path, data=None, exclude_warmup=True):
    """Create response time violin plot (with optional warmup exclusion)"""
    if data is not None and exclude_warmup:
        response_times, excluded = filter_warmup_from_response_times(data)
        warmup_filtered = excluded > 0
    else:
        warmup_filtered = False

    if not response_times:
        print("No response time data found")
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    parts = ax.violinplot(response_times, positions=[1], showmeans=True, showmedians=True)
    parts['bodies'][0].set_facecolor('lightblue')
    parts['bodies'][0].set_alpha(0.7)
    ax.set_ylabel('Response Time (ms)')
    ax.set_title('Response Time Violin Plot')
    ax.set_xticklabels(['All Requests'])
    ax.grid(True, alpha=0.3)

    if warmup_filtered:
        add_warmup_excluded_indicator(ax)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved violin plot to {output_path}")
    plt.close()


def plot_cdf(response_times, output_path, data=None, exclude_warmup=True):
    """Create cumulative distribution function plot (with optional warmup exclusion)"""
    if data is not None and exclude_warmup:
        response_times, excluded = filter_warmup_from_response_times(data)
        warmup_filtered = excluded > 0
    else:
        warmup_filtered = False

    if not response_times:
        print("No response time data found")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    sorted_times = np.sort(response_times)
    cdf = np.arange(1, len(sorted_times) + 1) / len(sorted_times)
    ax.plot(sorted_times, cdf, linewidth=2, color='steelblue')
    ax.axhline(0.5, color='gray', linestyle='--', alpha=0.5, label='P50')
    ax.axhline(0.95, color='orange', linestyle='--', alpha=0.5, label='P95')
    ax.axhline(0.99, color='red', linestyle='--', alpha=0.5, label='P99')
    ax.set_xlabel('Response Time (ms)')
    ax.set_ylabel('Cumulative Probability')
    ax.set_title('Cumulative Distribution Function (CDF)')
    ax.legend()
    ax.grid(True, alpha=0.3)

    if warmup_filtered:
        add_warmup_excluded_indicator(ax)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved CDF plot to {output_path}")
    plt.close()


def plot_percentiles(response_times, output_path, data=None, exclude_warmup=True):
    """Create response time percentiles bar chart (with optional warmup exclusion)"""
    if data is not None and exclude_warmup:
        response_times, excluded = filter_warmup_from_response_times(data)
        warmup_filtered = excluded > 0
    else:
        warmup_filtered = False

    if not response_times:
        print("No response time data found")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    percentiles = [50, 75, 90, 95, 99]
    perc_values = [np.percentile(response_times, p) for p in percentiles]
    colors = ['green', 'yellowgreen', 'gold', 'orange', 'red']
    bars = ax.bar([f'P{p}' for p in percentiles], perc_values, color=colors, alpha=0.8)
    ax.set_xlabel('Percentile')
    ax.set_ylabel('Response Time (ms)')
    ax.set_title('Response Time Percentiles')
    ax.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, perc_values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val:.0f}', ha='center', va='bottom', fontsize=10, fontweight='bold')

    if warmup_filtered:
        add_warmup_excluded_indicator(ax)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved percentiles plot to {output_path}")
    plt.close()


def plot_log_distribution(response_times, output_path, data=None, exclude_warmup=True):
    """Create log-scale response time distribution"""
    if data is not None and exclude_warmup:
        response_times, excluded = filter_warmup_from_response_times(data)

    if not response_times:
        print("No response time data found")
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    log_times = np.log10(np.array(response_times) + 1)
    ax.hist(log_times, bins=50, alpha=0.7, color='purple', edgecolor='black')
    ax.set_xlabel('log10(Response Time + 1)')
    ax.set_ylabel('Frequency')
    ax.set_title('Log-Scale Response Time Distribution')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved log distribution plot to {output_path}")
    plt.close()


def plot_response_time_buckets(response_times, output_path, data=None, exclude_warmup=True):
    """Create response time buckets plot"""
    if data is not None and exclude_warmup:
        response_times, excluded = filter_warmup_from_response_times(data)

    if not response_times:
        print("No response time data found")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    buckets = [0, 100, 200, 300, 500, 1000, 2000, 5000, float('inf')]
    bucket_labels = ['<100ms', '100-200ms', '200-300ms', '300-500ms',
                    '500ms-1s', '1-2s', '2-5s', '>5s']
    bucket_counts = []
    for i in range(len(buckets) - 1):
        count = sum(1 for t in response_times if buckets[i] <= t < buckets[i+1])
        bucket_counts.append(count)

    bucket_colors = ['#27ae60', '#2ecc71', '#f1c40f', '#f39c12',
                    '#e67e22', '#e74c3c', '#c0392b', '#8e44ad']
    bars = ax.bar(bucket_labels, bucket_counts, color=bucket_colors, alpha=0.8, edgecolor='black')
    ax.set_xlabel('Response Time Bucket')
    ax.set_ylabel('Number of Requests')
    ax.set_title('Response Time Distribution by Bucket')
    ax.grid(True, alpha=0.3, axis='y')
    for bar, count in zip(bars, bucket_counts):
        pct = count / len(response_times) * 100
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{count}\n({pct:.1f}%)', ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved response time buckets plot to {output_path}")
    plt.close()


def generate_baseline_plots(response_times, output_dir, data=None, exclude_warmup=True):
    """Generate all baseline/overall performance plots"""
    print("\n--- Generating Baseline Performance Plots ---")

    if not response_times:
        print("No response time data available")
        return

    plot_response_time_histogram(response_times, os.path.join(output_dir, "response_time_histogram.png"), data=data, exclude_warmup=exclude_warmup)
    plot_response_time_boxplot(response_times, os.path.join(output_dir, "response_time_boxplot.png"), data=data, exclude_warmup=exclude_warmup)
    plot_violin(response_times, os.path.join(output_dir, "response_time_violin.png"), data=data, exclude_warmup=exclude_warmup)
    plot_cdf(response_times, os.path.join(output_dir, "response_time_cdf.png"), data=data, exclude_warmup=exclude_warmup)
    plot_percentiles(response_times, os.path.join(output_dir, "response_time_percentiles.png"), data=data, exclude_warmup=exclude_warmup)
    plot_log_distribution(response_times, os.path.join(output_dir, "response_time_log.png"), data=data, exclude_warmup=exclude_warmup)
    plot_response_time_buckets(response_times, os.path.join(output_dir, "response_time_buckets.png"), data=data, exclude_warmup=exclude_warmup)