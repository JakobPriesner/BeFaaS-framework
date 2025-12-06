"""
Category-based performance plots for BeFaaS analysis.
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .utils import get_category_colors


def plot_category_boxplot(category_times, output_path):
    """Create box plot comparison by category"""
    if not category_times:
        print("No category timing data found")
        return

    filtered = {k: v for k, v in category_times.items() if len(v) >= 5}
    if not filtered:
        print("Not enough data for category box plot")
        return

    categories = list(filtered.keys())
    category_colors = get_category_colors()

    fig, ax = plt.subplots(figsize=(12, 6))
    data_to_plot = [filtered[cat] for cat in categories]
    bp = ax.boxplot(data_to_plot, tick_labels=categories, patch_artist=True)
    for patch, cat in zip(bp['boxes'], categories):
        patch.set_facecolor(category_colors.get(cat, '#95a5a6'))
        patch.set_alpha(0.7)
    ax.set_xlabel('Category')
    ax.set_ylabel('Response Time (ms)')
    ax.set_title('Response Time by Category')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved category box plot to {output_path}")
    plt.close()


def plot_category_mean(category_times, output_path):
    """Create mean response time by category"""
    if not category_times:
        print("No category timing data found")
        return

    filtered = {k: v for k, v in category_times.items() if len(v) >= 5}
    if not filtered:
        print("Not enough data for category mean plot")
        return

    categories = list(filtered.keys())
    category_colors = get_category_colors()

    fig, ax = plt.subplots(figsize=(12, 6))
    means = [np.mean(filtered[cat]) for cat in categories]
    colors = [category_colors.get(cat, '#95a5a6') for cat in categories]
    bars = ax.bar(categories, means, color=colors, alpha=0.8)
    ax.set_xlabel('Category')
    ax.set_ylabel('Mean Response Time (ms)')
    ax.set_title('Mean Response Time by Category')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val:.0f}', ha='center', va='bottom', fontsize=10)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved category mean plot to {output_path}")
    plt.close()


def plot_category_p95(category_times, output_path):
    """Create P95 response time by category"""
    if not category_times:
        print("No category timing data found")
        return

    filtered = {k: v for k, v in category_times.items() if len(v) >= 5}
    if not filtered:
        print("Not enough data for category P95 plot")
        return

    categories = list(filtered.keys())
    category_colors = get_category_colors()

    fig, ax = plt.subplots(figsize=(12, 6))
    p95s = [np.percentile(filtered[cat], 95) for cat in categories]
    colors = [category_colors.get(cat, '#95a5a6') for cat in categories]
    bars = ax.bar(categories, p95s, color=colors, alpha=0.8)
    ax.set_xlabel('Category')
    ax.set_ylabel('P95 Response Time (ms)')
    ax.set_title('95th Percentile Response Time by Category')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, p95s):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val:.0f}', ha='center', va='bottom', fontsize=10)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved category P95 plot to {output_path}")
    plt.close()


def plot_category_volume(category_times, output_path):
    """Create request volume by category"""
    if not category_times:
        print("No category timing data found")
        return

    filtered = {k: v for k, v in category_times.items() if len(v) >= 5}
    if not filtered:
        print("Not enough data for category volume plot")
        return

    categories = list(filtered.keys())
    category_colors = get_category_colors()

    fig, ax = plt.subplots(figsize=(12, 6))
    counts = [len(filtered[cat]) for cat in categories]
    colors = [category_colors.get(cat, '#95a5a6') for cat in categories]
    bars = ax.bar(categories, counts, color=colors, alpha=0.8)
    ax.set_xlabel('Category')
    ax.set_ylabel('Number of Requests')
    ax.set_title('Request Volume by Category')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val}', ha='center', va='bottom', fontsize=10)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved category volume plot to {output_path}")
    plt.close()


def generate_category_plots(category_times, output_dir):
    """Generate all category performance plots"""
    print("\n--- Generating Category Performance Plots ---")

    if not category_times:
        print("No category timing data available")
        return

    plot_category_boxplot(category_times, os.path.join(output_dir, "category_boxplot.png"))
    plot_category_mean(category_times, os.path.join(output_dir, "category_mean.png"))
    plot_category_p95(category_times, os.path.join(output_dir, "category_p95.png"))
    plot_category_volume(category_times, os.path.join(output_dir, "category_volume.png"))