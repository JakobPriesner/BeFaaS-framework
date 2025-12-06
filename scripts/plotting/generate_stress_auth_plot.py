"""
Stress test authentication-specific plots for BeFaaS analysis.
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .data_extraction import analyze_load_over_time


def plot_stress_auth_response_vs_load(data, output_dir):
    """
    Plot authentication-specific response time metrics vs concurrent request rate.
    Key plot for stress-auth workload focusing on auth endpoints.
    """
    windows = analyze_load_over_time(data, time_window_seconds=5)

    if not windows:
        print("No time window data for auth response vs load plot")
        return

    auth_windows = [w for w in windows if w['auth_request_count'] >= 3]
    if len(auth_windows) < 5:
        print("Not enough auth data for auth response vs load plot")
        return

    rps = [w['requests_per_second'] for w in auth_windows]
    auth_mean = [w['auth_mean_ms'] for w in auth_windows]
    auth_p95 = [w['auth_p95_ms'] for w in auth_windows]
    times = [w['window_start'] for w in auth_windows]

    # Plot 1: Auth mean response time vs RPS
    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(rps, auth_mean, c=times, cmap='Purples', alpha=0.7, s=60)
    ax.set_xlabel('Requests per Second', fontsize=12)
    ax.set_ylabel('Auth Mean Response Time (ms)', fontsize=12)
    ax.set_title('Auth Mean Response Time vs Load', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    cbar = plt.colorbar(scatter, ax=ax)
    cbar.set_label('Time (seconds)')

    if len(rps) > 5:
        z = np.polyfit(rps, auth_mean, 2)
        p = np.poly1d(z)
        x_line = np.linspace(min(rps), max(rps), 100)
        ax.plot(x_line, p(x_line), 'r--', alpha=0.8, linewidth=2, label='Trend')
        ax.legend()

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_auth_mean_vs_load.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_auth_mean_vs_load.png")
    plt.close()

    # Plot 2: Auth P95 response time vs RPS
    fig, ax = plt.subplots(figsize=(10, 8))
    scatter2 = ax.scatter(rps, auth_p95, c=times, cmap='Purples', alpha=0.7, s=60)
    ax.set_xlabel('Requests per Second', fontsize=12)
    ax.set_ylabel('Auth P95 Response Time (ms)', fontsize=12)
    ax.set_title('Auth P95 Response Time vs Load', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    cbar2 = plt.colorbar(scatter2, ax=ax)
    cbar2.set_label('Time (seconds)')

    if len(rps) > 5:
        z = np.polyfit(rps, auth_p95, 2)
        p = np.poly1d(z)
        ax.plot(x_line, p(x_line), 'r--', alpha=0.8, linewidth=2, label='Trend')
        ax.legend()

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_auth_p95_vs_load.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_auth_p95_vs_load.png")
    plt.close()

    # Plot 3: Combined auth plot
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    ax1 = axes[0]
    scatter = ax1.scatter(rps, auth_mean, c=times, cmap='Purples', alpha=0.7, s=60)
    ax1.set_xlabel('Requests per Second', fontsize=12)
    ax1.set_ylabel('Auth Mean Response Time (ms)', fontsize=12)
    ax1.set_title('Auth Mean Response Time vs Load', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    cbar = plt.colorbar(scatter, ax=ax1)
    cbar.set_label('Time (seconds)')

    if len(rps) > 5:
        z = np.polyfit(rps, auth_mean, 2)
        p = np.poly1d(z)
        ax1.plot(x_line, p(x_line), 'r--', alpha=0.8, linewidth=2, label='Trend')
        ax1.legend()

    ax2 = axes[1]
    scatter2 = ax2.scatter(rps, auth_p95, c=times, cmap='Purples', alpha=0.7, s=60)
    ax2.set_xlabel('Requests per Second', fontsize=12)
    ax2.set_ylabel('Auth P95 Response Time (ms)', fontsize=12)
    ax2.set_title('Auth P95 Response Time vs Load', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    cbar2 = plt.colorbar(scatter2, ax=ax2)
    cbar2.set_label('Time (seconds)')

    if len(rps) > 5:
        z = np.polyfit(rps, auth_p95, 2)
        p = np.poly1d(z)
        ax2.plot(x_line, p(x_line), 'r--', alpha=0.8, linewidth=2, label='Trend')
        ax2.legend()

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "stress_auth_response_vs_load.png"), dpi=150, bbox_inches='tight')
    print(f"  Saved stress_auth_response_vs_load.png")
    plt.close()


def plot_stress_auth_timeline(data, output_path):
    """
    Plot authentication response times over the duration of the stress test.
    """
    windows = analyze_load_over_time(data, time_window_seconds=5)

    if not windows:
        print("No time window data for auth timeline plot")
        return

    auth_windows = [w for w in windows if w['auth_request_count'] >= 1]
    if len(auth_windows) < 5:
        print("Not enough auth data for auth timeline plot")
        return

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))

    times = [w['window_start'] for w in auth_windows]
    auth_mean = [w['auth_mean_ms'] for w in auth_windows]
    auth_p95 = [w['auth_p95_ms'] for w in auth_windows]
    auth_counts = [w['auth_request_count'] for w in auth_windows]

    # Plot 1: Auth response times over time
    ax1 = axes[0]
    ax1.plot(times, auth_mean, label='Auth Mean', color='#9b59b6', linewidth=2)
    ax1.plot(times, auth_p95, label='Auth P95', color='#e74c3c', linewidth=2)
    ax1.fill_between(times, auth_mean, alpha=0.2, color='#9b59b6')
    ax1.set_xlabel('Time (seconds)', fontsize=12)
    ax1.set_ylabel('Response Time (ms)', fontsize=12)
    ax1.set_title('Auth Response Time Over Time', fontsize=14, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Plot 2: Auth request count over time
    ax2 = axes[1]
    ax2.bar(times, auth_counts, width=4, color='#9b59b6', alpha=0.7)
    ax2.set_xlabel('Time (seconds)', fontsize=12)
    ax2.set_ylabel('Auth Requests per Window', fontsize=12)
    ax2.set_title('Auth Request Volume Over Time', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved stress auth timeline to {output_path}")
    plt.close()


def plot_stress_auth_vs_nonauth(data, output_path):
    """
    Compare auth vs non-auth response times during stress test.
    """
    windows = analyze_load_over_time(data, time_window_seconds=5)

    if not windows:
        print("No time window data for auth vs nonauth plot")
        return

    auth_windows = [w for w in windows if w['auth_request_count'] >= 3]
    if len(auth_windows) < 5:
        print("Not enough auth data for auth vs nonauth plot")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    times = [w['window_start'] for w in auth_windows]
    auth_mean = [w['auth_mean_ms'] for w in auth_windows]
    overall_mean = [w['mean_ms'] for w in auth_windows]
    rps = [w['requests_per_second'] for w in auth_windows]

    # Plot 1: Auth vs Overall mean over time
    ax1 = axes[0]
    ax1.plot(times, auth_mean, label='Auth Mean', color='#9b59b6', linewidth=2)
    ax1.plot(times, overall_mean, label='Overall Mean', color='#3498db', linewidth=2)
    ax1.fill_between(times, auth_mean, overall_mean, alpha=0.2, color='#e74c3c', label='Auth Overhead')
    ax1.set_xlabel('Time (seconds)', fontsize=12)
    ax1.set_ylabel('Response Time (ms)', fontsize=12)
    ax1.set_title('Auth vs Overall Response Time', fontsize=14, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Plot 2: Auth overhead vs load
    ax2 = axes[1]
    overhead = [a - o for a, o in zip(auth_mean, overall_mean)]
    scatter = ax2.scatter(rps, overhead, c=times, cmap='coolwarm', alpha=0.7, s=60)
    ax2.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax2.set_xlabel('Requests per Second', fontsize=12)
    ax2.set_ylabel('Auth Overhead (ms)', fontsize=12)
    ax2.set_title('Auth Overhead vs Load', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    cbar = plt.colorbar(scatter, ax=ax2)
    cbar.set_label('Time (seconds)')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved stress auth vs nonauth to {output_path}")
    plt.close()


def generate_stress_auth_plots(data, output_dir):
    """Generate all stress test authentication-specific plots"""
    print("\n--- Generating Stress Test Auth Plots ---")

    plot_stress_auth_response_vs_load(data, output_dir)
    plot_stress_auth_timeline(data, os.path.join(output_dir, "stress_auth_timeline.png"))
    plot_stress_auth_vs_nonauth(data, os.path.join(output_dir, "stress_auth_vs_nonauth.png"))