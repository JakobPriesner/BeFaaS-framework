"""
Stress test ramp/scaling plots for BeFaaS analysis.
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .data_extraction import analyze_load_over_time


def plot_stress_response_vs_load(data, output_dir):
    """
    Plot response time metrics (mean, p95, p99) vs concurrent request rate.
    Outputs individual plots for each metric.
    """
    windows = analyze_load_over_time(data, time_window_seconds=5)

    if not windows:
        print("No time window data for response vs load plot")
        return

    rps = [w['requests_per_second'] for w in windows]
    mean_ms = [w['mean_ms'] for w in windows]
    p95_ms = [w['p95_ms'] for w in windows]
    p99_ms = [w['p99_ms'] for w in windows]
    times = [w['window_start'] for w in windows]

    x_line = np.linspace(min(rps), max(rps), 100) if len(rps) > 5 else None

    # Plot 1: Mean response time vs RPS
    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(rps, mean_ms, c=times, cmap='viridis', alpha=0.7, s=50)
    ax.set_xlabel('Requests per Second', fontsize=12)
    ax.set_ylabel('Mean Response Time (ms)', fontsize=12)
    ax.set_title('Mean Response Time vs Load', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Time (seconds)')
    if x_line is not None:
        z = np.polyfit(rps, mean_ms, 2)
        p = np.poly1d(z)
        ax.plot(x_line, p(x_line), 'r--', alpha=0.8, linewidth=2, label='Trend')
        ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_mean_vs_load.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_mean_vs_load.png")
    plt.close()

    # Plot 2: P95 response time vs RPS
    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(rps, p95_ms, c=times, cmap='viridis', alpha=0.7, s=50)
    ax.set_xlabel('Requests per Second', fontsize=12)
    ax.set_ylabel('P95 Response Time (ms)', fontsize=12)
    ax.set_title('P95 Response Time vs Load', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Time (seconds)')
    if x_line is not None:
        z = np.polyfit(rps, p95_ms, 2)
        p = np.poly1d(z)
        ax.plot(x_line, p(x_line), 'r--', alpha=0.8, linewidth=2, label='Trend')
        ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_p95_vs_load.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_p95_vs_load.png")
    plt.close()

    # Plot 3: P99 response time vs RPS
    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(rps, p99_ms, c=times, cmap='viridis', alpha=0.7, s=50)
    ax.set_xlabel('Requests per Second', fontsize=12)
    ax.set_ylabel('P99 Response Time (ms)', fontsize=12)
    ax.set_title('P99 Response Time vs Load', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Time (seconds)')
    if x_line is not None:
        z = np.polyfit(rps, p99_ms, 2)
        p = np.poly1d(z)
        ax.plot(x_line, p(x_line), 'r--', alpha=0.8, linewidth=2, label='Trend')
        ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_p99_vs_load.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_p99_vs_load.png")
    plt.close()

    # Plot 4: All metrics combined
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.scatter(rps, mean_ms, alpha=0.6, s=30, label='Mean', color='#3498db')
    ax.scatter(rps, p95_ms, alpha=0.6, s=30, label='P95', color='#e74c3c')
    ax.scatter(rps, p99_ms, alpha=0.6, s=30, label='P99', color='#9b59b6')
    ax.set_xlabel('Requests per Second', fontsize=12)
    ax.set_ylabel('Response Time (ms)', fontsize=12)
    ax.set_title('All Metrics vs Load', fontsize=14, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_all_metrics_vs_load.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_all_metrics_vs_load.png")
    plt.close()


def plot_stress_scaling_timeline(data, output_dir):
    """
    Plot scaling behavior over time - shows how system scales with increasing load.
    Outputs individual plots for load profile, response time, and efficiency.
    """
    windows = analyze_load_over_time(data, time_window_seconds=5)

    if not windows:
        print("No time window data for scaling timeline plot")
        return

    times = [w['window_start'] for w in windows]
    rps = [w['requests_per_second'] for w in windows]
    mean_ms = [w['mean_ms'] for w in windows]
    p95_ms = [w['p95_ms'] for w in windows]
    p99_ms = [w['p99_ms'] for w in windows]
    max_time = max(times)

    # Plot 1: Request rate over time (load profile)
    fig, ax = plt.subplots(figsize=(14, 8))
    ax.fill_between(times, rps, alpha=0.3, color='#3498db')
    ax.plot(times, rps, color='#3498db', linewidth=2)
    ax.set_xlabel('Time (seconds)', fontsize=12)
    ax.set_ylabel('Requests per Second', fontsize=12)
    ax.set_title('Load Profile Over Time', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    # Add phase annotations
    phase_boundaries = [60, 180, 300, max_time]
    phase_names = ['Warm-up', 'Ramp 1', 'Ramp 2', 'Sustained']
    colors = ['#95a5a6', '#f39c12', '#e74c3c', '#c0392b']
    prev_boundary = 0
    for i, boundary in enumerate(phase_boundaries):
        if boundary <= max_time:
            ax.axvspan(prev_boundary, min(boundary, max_time), alpha=0.1, color=colors[i])
            mid_point = (prev_boundary + min(boundary, max_time)) / 2
            ax.text(mid_point, max(rps) * 0.9, phase_names[i], ha='center', fontsize=10, fontweight='bold')
        prev_boundary = boundary
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_load_profile.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_load_profile.png")
    plt.close()

    # Plot 2: Response time over time
    fig, ax = plt.subplots(figsize=(14, 8))
    ax.plot(times, mean_ms, label='Mean', color='#3498db', linewidth=2)
    ax.plot(times, p95_ms, label='P95', color='#e74c3c', linewidth=2)
    ax.plot(times, p99_ms, label='P99', color='#9b59b6', linewidth=2)
    ax.set_xlabel('Time (seconds)', fontsize=12)
    ax.set_ylabel('Response Time (ms)', fontsize=12)
    ax.set_title('Response Time Over Time', fontsize=14, fontweight='bold')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_response_time_timeline.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_response_time_timeline.png")
    plt.close()

    # Plot 3: Response time normalized by request rate (efficiency)
    fig, ax = plt.subplots(figsize=(14, 8))
    efficiency = [m / r if r > 0 else 0 for m, r in zip(mean_ms, rps)]
    ax.plot(times, efficiency, color='#27ae60', linewidth=2)
    ax.fill_between(times, efficiency, alpha=0.3, color='#27ae60')
    ax.set_xlabel('Time (seconds)', fontsize=12)
    ax.set_ylabel('ms per Request/sec', fontsize=12)
    ax.set_title('Scaling Efficiency (Lower = Better Scaling)', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_scaling_efficiency.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_scaling_efficiency.png")
    plt.close()


def plot_stress_latency_buckets_vs_load(data, output_path):
    """
    Show distribution of response times at different load levels.
    Useful for understanding latency degradation patterns.
    """
    windows = analyze_load_over_time(data, time_window_seconds=10)

    if not windows:
        print("No time window data for latency buckets plot")
        return

    load_levels = {
        'Low (0-50 RPS)': [w for w in windows if w['requests_per_second'] <= 50],
        'Medium (50-150 RPS)': [w for w in windows if 50 < w['requests_per_second'] <= 150],
        'High (150-300 RPS)': [w for w in windows if 150 < w['requests_per_second'] <= 300],
        'Very High (300+ RPS)': [w for w in windows if w['requests_per_second'] > 300],
    }

    load_levels = {k: v for k, v in load_levels.items() if len(v) >= 3}

    if len(load_levels) < 2:
        print("Not enough load variation for latency buckets plot")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    ax1 = axes[0]
    labels = list(load_levels.keys())
    data_to_plot = [[w['mean_ms'] for w in windows] for windows in load_levels.values()]

    bp = ax1.boxplot(data_to_plot, tick_labels=labels, patch_artist=True)
    colors = ['#27ae60', '#f39c12', '#e74c3c', '#8e44ad']
    for patch, color in zip(bp['boxes'], colors[:len(bp['boxes'])]):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax1.set_ylabel('Mean Response Time (ms)', fontsize=12)
    ax1.set_title('Response Time Distribution by Load Level', fontsize=14, fontweight='bold')
    ax1.tick_params(axis='x', rotation=15)
    ax1.grid(True, alpha=0.3, axis='y')

    ax2 = axes[1]
    x = np.arange(len(labels))
    width = 0.2

    metrics = ['p50_ms', 'p90_ms', 'p95_ms', 'p99_ms']
    metric_labels = ['P50', 'P90', 'P95', 'P99']
    metric_colors = ['#3498db', '#f39c12', '#e74c3c', '#9b59b6']

    for i, (metric, label, color) in enumerate(zip(metrics, metric_labels, metric_colors)):
        values = [np.mean([w[metric] for w in windows]) for windows in load_levels.values()]
        ax2.bar(x + i * width, values, width, label=label, color=color, alpha=0.8)

    ax2.set_ylabel('Response Time (ms)', fontsize=12)
    ax2.set_title('Percentiles at Different Load Levels', fontsize=14, fontweight='bold')
    ax2.set_xticks(x + width * 1.5)
    ax2.set_xticklabels(labels, rotation=15)
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved stress latency buckets to {output_path}")
    plt.close()


def plot_stress_throughput_vs_latency(data, output_path):
    """
    Classic throughput vs latency plot showing breaking point.
    """
    windows = analyze_load_over_time(data, time_window_seconds=5)

    if not windows:
        print("No time window data for throughput vs latency plot")
        return

    fig, ax = plt.subplots(figsize=(12, 8))

    rps = [w['requests_per_second'] for w in windows]
    mean_ms = [w['mean_ms'] for w in windows]
    times = [w['window_start'] for w in windows]

    scatter = ax.scatter(rps, mean_ms, c=times, cmap='coolwarm', alpha=0.7, s=80)
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Time (seconds)')

    ax.set_xlabel('Throughput (Requests per Second)', fontsize=14)
    ax.set_ylabel('Mean Latency (ms)', fontsize=14)
    ax.set_title('Throughput vs Latency (Scaling Behavior)', fontsize=16, fontweight='bold')
    ax.grid(True, alpha=0.3)

    if len(rps) > 10:
        slopes = []
        for i in range(1, len(rps)):
            if rps[i] != rps[i-1]:
                slope = (mean_ms[i] - mean_ms[i-1]) / (rps[i] - rps[i-1])
                slopes.append((rps[i], mean_ms[i], slope))

        if slopes:
            max_slope_point = max(slopes, key=lambda x: x[2])
            ax.annotate(f'Potential Breaking Point\n({max_slope_point[0]:.0f} RPS, {max_slope_point[1]:.0f}ms)',
                       xy=(max_slope_point[0], max_slope_point[1]),
                       xytext=(max_slope_point[0] - 30, max_slope_point[1] + 100),
                       fontsize=10, ha='center',
                       arrowprops=dict(arrowstyle='->', color='red'),
                       bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))

    if len(rps) > 5:
        z = np.polyfit(rps, mean_ms, 2)
        p = np.poly1d(z)
        x_line = np.linspace(min(rps), max(rps), 100)
        ax.plot(x_line, p(x_line), 'r--', alpha=0.8, linewidth=2, label='Quadratic Fit')
        ax.legend()

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved stress throughput vs latency to {output_path}")
    plt.close()


def plot_stress_summary(data, output_path):
    """
    Summary plot with key stress test metrics.
    """
    windows = analyze_load_over_time(data, time_window_seconds=5)

    if not windows:
        print("No time window data for stress summary plot")
        return

    fig, axes = plt.subplots(2, 3, figsize=(18, 12))

    times = [w['window_start'] for w in windows]
    rps = [w['requests_per_second'] for w in windows]
    mean_ms = [w['mean_ms'] for w in windows]
    p95_ms = [w['p95_ms'] for w in windows]
    p99_ms = [w['p99_ms'] for w in windows]
    std_ms = [w['std_ms'] for w in windows]

    ax1 = axes[0, 0]
    ax1.fill_between(times, rps, alpha=0.3, color='#3498db')
    ax1.plot(times, rps, color='#3498db', linewidth=2)
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('RPS')
    ax1.set_title('Load Profile')
    ax1.grid(True, alpha=0.3)

    ax2 = axes[0, 1]
    ax2.plot(times, mean_ms, color='#2ecc71', linewidth=2)
    ax2.fill_between(times, mean_ms, alpha=0.3, color='#2ecc71')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Mean (ms)')
    ax2.set_title('Mean Latency Over Time')
    ax2.grid(True, alpha=0.3)

    ax3 = axes[0, 2]
    ax3.plot(times, p95_ms, label='P95', color='#e74c3c', linewidth=2)
    ax3.plot(times, p99_ms, label='P99', color='#9b59b6', linewidth=2)
    ax3.set_xlabel('Time (s)')
    ax3.set_ylabel('Latency (ms)')
    ax3.set_title('Tail Latencies Over Time')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    ax4 = axes[1, 0]
    ax4.scatter(rps, mean_ms, c=times, cmap='viridis', alpha=0.7, s=40)
    ax4.set_xlabel('RPS')
    ax4.set_ylabel('Mean (ms)')
    ax4.set_title('Mean Latency vs Load')
    ax4.grid(True, alpha=0.3)

    ax5 = axes[1, 1]
    ax5.scatter(rps, p95_ms, c=times, cmap='viridis', alpha=0.7, s=40)
    ax5.set_xlabel('RPS')
    ax5.set_ylabel('P95 (ms)')
    ax5.set_title('P95 Latency vs Load')
    ax5.grid(True, alpha=0.3)

    ax6 = axes[1, 2]
    ax6.plot(times, std_ms, color='#e67e22', linewidth=2)
    ax6.fill_between(times, std_ms, alpha=0.3, color='#e67e22')
    ax6.set_xlabel('Time (s)')
    ax6.set_ylabel('Std Dev (ms)')
    ax6.set_title('Latency Variance Over Time')
    ax6.grid(True, alpha=0.3)

    fig.text(0.5, 0.01,
             f'Max RPS: {max(rps):.0f} | Min Mean: {min(mean_ms):.0f}ms | Max Mean: {max(mean_ms):.0f}ms | Max P99: {max(p99_ms):.0f}ms',
             ha='center', fontsize=12, style='italic')

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved stress summary to {output_path}")
    plt.close()


def generate_stress_ramp_plots(data, output_dir):
    """Generate all stress test ramp/scaling plots"""
    print("\n--- Generating Stress Test Ramp Plots ---")

    plot_stress_response_vs_load(data, output_dir)
    plot_stress_scaling_timeline(data, output_dir)
    plot_stress_latency_buckets_vs_load(data, os.path.join(output_dir, "stress_latency_buckets.png"))
    plot_stress_throughput_vs_latency(data, os.path.join(output_dir, "stress_throughput_vs_latency.png"))
    plot_stress_summary(data, os.path.join(output_dir, "stress_summary.png"))