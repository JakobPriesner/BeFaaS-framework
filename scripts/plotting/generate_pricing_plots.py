"""
Cloud pricing analysis plots for BeFaaS analysis.
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from .constants import (
    AWS_LAMBDA_PRICING, AWS_API_GATEWAY_PRICING,
    GCP_CLOUD_FUNCTIONS_PRICING, AZURE_FUNCTIONS_PRICING
)
from .utils import is_auth_endpoint
from .data_extraction import extract_detailed_request_data


def calculate_pricing_data(data, endpoint_times, memory_mb=256):
    """Calculate pricing estimates for different cloud providers"""
    requests = extract_detailed_request_data(data)
    if not requests:
        return None

    total_requests = len(requests)
    total_duration_ms = sum(r['duration'] for r in requests)
    total_duration_s = total_duration_ms / 1000
    memory_gb = memory_mb / 1024
    gb_seconds = total_duration_s * memory_gb

    auth_requests = [r for r in requests if r['is_auth']]
    non_auth_requests = [r for r in requests if not r['is_auth']]
    auth_duration_ms = sum(r['duration'] for r in auth_requests)
    non_auth_duration_ms = sum(r['duration'] for r in non_auth_requests)

    endpoint_costs = {}
    for endpoint, times in endpoint_times.items():
        ep_gb_seconds = (sum(times) / 1000) * memory_gb
        aws_cost = len(times) * AWS_LAMBDA_PRICING['request_cost'] + ep_gb_seconds * AWS_LAMBDA_PRICING['duration_cost_per_gb_second']
        endpoint_costs[endpoint] = {
            'requests': len(times),
            'duration_ms': sum(times),
            'mean_duration_ms': np.mean(times),
            'gb_seconds': ep_gb_seconds,
            'aws_cost': aws_cost,
            'is_auth': is_auth_endpoint(endpoint)
        }

    aws_request_cost = total_requests * AWS_LAMBDA_PRICING['request_cost']
    aws_compute_cost = gb_seconds * AWS_LAMBDA_PRICING['duration_cost_per_gb_second']
    api_gw_cost = (total_requests / 1_000_000) * AWS_API_GATEWAY_PRICING['rest_api_per_million']

    gcp_invocation_cost = (total_requests / 1_000_000) * GCP_CLOUD_FUNCTIONS_PRICING['invocations_per_million']
    gcp_compute_cost = (total_duration_ms / 100) * GCP_CLOUD_FUNCTIONS_PRICING['compute_per_100ms_128mb'] * (memory_mb / 128)

    azure_execution_cost = (total_requests / 1_000_000) * AZURE_FUNCTIONS_PRICING['executions_per_million']
    azure_compute_cost = gb_seconds * AZURE_FUNCTIONS_PRICING['gb_seconds']

    return {
        'total_requests': total_requests,
        'total_duration_ms': total_duration_ms,
        'total_duration_s': total_duration_s,
        'gb_seconds': gb_seconds,
        'memory_mb': memory_mb,
        'auth_requests': len(auth_requests),
        'non_auth_requests': len(non_auth_requests),
        'auth_duration_ms': auth_duration_ms,
        'non_auth_duration_ms': non_auth_duration_ms,
        'endpoint_costs': endpoint_costs,
        'aws': {
            'request_cost': aws_request_cost,
            'compute_cost': aws_compute_cost,
            'total': aws_request_cost + aws_compute_cost,
            'api_gateway': api_gw_cost,
            'total_with_api_gw': aws_request_cost + aws_compute_cost + api_gw_cost
        },
        'gcp': {
            'invocation_cost': gcp_invocation_cost,
            'compute_cost': gcp_compute_cost,
            'total': gcp_invocation_cost + gcp_compute_cost
        },
        'azure': {
            'execution_cost': azure_execution_cost,
            'compute_cost': azure_compute_cost,
            'total': azure_execution_cost + azure_compute_cost
        }
    }


def plot_cloud_cost_comparison(pricing_data, output_path):
    """Compare costs across cloud providers"""
    if not pricing_data:
        print("No pricing data available")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    providers = ['AWS Lambda', 'AWS Lambda\n+ API GW', 'GCP Cloud\nFunctions', 'Azure\nFunctions']
    costs = [pricing_data['aws']['total'], pricing_data['aws']['total_with_api_gw'],
             pricing_data['gcp']['total'], pricing_data['azure']['total']]
    colors = ['#FF9900', '#FF9900', '#4285F4', '#0078D4']
    bars = ax.bar(providers, costs, color=colors, alpha=0.8, edgecolor='black')

    ax.set_ylabel('Estimated Cost ($)')
    ax.set_title(f'Cloud Provider Cost Comparison\n({pricing_data["total_requests"]:,} requests, {pricing_data["memory_mb"]}MB memory)')
    ax.grid(True, alpha=0.3, axis='y')

    for bar, cost in zip(bars, costs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'${cost:.4f}', ha='center', va='bottom', fontsize=11, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved cloud cost comparison to {output_path}")
    plt.close()


def plot_cost_breakdown(pricing_data, output_path):
    """Plot cost breakdown by component"""
    if not pricing_data:
        print("No pricing data available")
        return

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    ax1 = axes[0]
    aws_vals = [pricing_data['aws']['request_cost'], pricing_data['aws']['compute_cost'], pricing_data['aws']['api_gateway']]
    ax1.bar(['Request', 'Compute', 'API GW'], aws_vals, color=['#FF9900', '#FF6600', '#CC5500'], alpha=0.8)
    ax1.set_title('AWS Lambda Cost Breakdown')
    ax1.set_ylabel('Cost ($)')
    for i, v in enumerate(aws_vals):
        ax1.text(i, v, f'${v:.5f}', ha='center', va='bottom', fontsize=9)

    ax2 = axes[1]
    gcp_vals = [pricing_data['gcp']['invocation_cost'], pricing_data['gcp']['compute_cost']]
    ax2.bar(['Invocation', 'Compute'], gcp_vals, color=['#4285F4', '#34A853'], alpha=0.8)
    ax2.set_title('GCP Cloud Functions Breakdown')
    ax2.set_ylabel('Cost ($)')
    for i, v in enumerate(gcp_vals):
        ax2.text(i, v, f'${v:.5f}', ha='center', va='bottom', fontsize=9)

    ax3 = axes[2]
    azure_vals = [pricing_data['azure']['execution_cost'], pricing_data['azure']['compute_cost']]
    ax3.bar(['Execution', 'Compute'], azure_vals, color=['#0078D4', '#00BCF2'], alpha=0.8)
    ax3.set_title('Azure Functions Breakdown')
    ax3.set_ylabel('Cost ($)')
    for i, v in enumerate(azure_vals):
        ax3.text(i, v, f'${v:.5f}', ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved cost breakdown to {output_path}")
    plt.close()


def plot_endpoint_cost(pricing_data, output_path):
    """Plot cost per endpoint"""
    if not pricing_data or not pricing_data.get('endpoint_costs'):
        print("No endpoint cost data available")
        return

    sorted_endpoints = sorted(pricing_data['endpoint_costs'].items(), key=lambda x: -x[1]['aws_cost'])[:15]
    if not sorted_endpoints:
        return

    fig, ax = plt.subplots(figsize=(14, 8))
    endpoints = [ep for ep, _ in sorted_endpoints]
    costs = [data['aws_cost'] for _, data in sorted_endpoints]
    colors = ['#9b59b6' if data['is_auth'] else '#3498db' for _, data in sorted_endpoints]

    y = np.arange(len(endpoints))
    bars = ax.barh(y, costs, color=colors, alpha=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(endpoints)
    ax.set_xlabel('AWS Lambda Cost ($)')
    ax.set_title('Cost by Endpoint (AWS Lambda)')
    ax.grid(True, alpha=0.3, axis='x')

    for bar, cost in zip(bars, costs):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height()/2, f'${cost:.6f}', va='center', fontsize=9)

    auth_patch = mpatches.Patch(color='#9b59b6', label='Auth Endpoint', alpha=0.8)
    non_auth_patch = mpatches.Patch(color='#3498db', label='Non-Auth Endpoint', alpha=0.8)
    ax.legend(handles=[auth_patch, non_auth_patch], loc='lower right')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved endpoint cost to {output_path}")
    plt.close()


def plot_auth_cost_overhead(pricing_data, output_path):
    """Plot authentication cost overhead"""
    if not pricing_data:
        print("No pricing data available")
        return

    memory_gb = pricing_data['memory_mb'] / 1024
    auth_gb_s = (pricing_data['auth_duration_ms'] / 1000) * memory_gb
    non_auth_gb_s = (pricing_data['non_auth_duration_ms'] / 1000) * memory_gb

    auth_total = pricing_data['auth_requests'] * AWS_LAMBDA_PRICING['request_cost'] + auth_gb_s * AWS_LAMBDA_PRICING['duration_cost_per_gb_second']
    non_auth_total = pricing_data['non_auth_requests'] * AWS_LAMBDA_PRICING['request_cost'] + non_auth_gb_s * AWS_LAMBDA_PRICING['duration_cost_per_gb_second']

    auth_per_1k = (auth_total / pricing_data['auth_requests'] * 1000) if pricing_data['auth_requests'] > 0 else 0
    non_auth_per_1k = (non_auth_total / pricing_data['non_auth_requests'] * 1000) if pricing_data['non_auth_requests'] > 0 else 0

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    ax1 = axes[0]
    bars1 = ax1.bar(['Auth', 'Non-Auth'], [auth_total, non_auth_total], color=['#9b59b6', '#3498db'], alpha=0.8)
    ax1.set_ylabel('Total Cost ($)')
    ax1.set_title('Total Cost: Auth vs Non-Auth')
    for bar, cost in zip(bars1, [auth_total, non_auth_total]):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f'${cost:.5f}', ha='center', va='bottom', fontweight='bold')

    ax2 = axes[1]
    bars2 = ax2.bar(['Auth', 'Non-Auth'], [auth_per_1k, non_auth_per_1k], color=['#9b59b6', '#3498db'], alpha=0.8)
    ax2.set_ylabel('Cost per 1000 Requests ($)')
    ax2.set_title('Cost per 1000 Requests')
    for bar, cost in zip(bars2, [auth_per_1k, non_auth_per_1k]):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f'${cost:.5f}', ha='center', va='bottom', fontweight='bold')

    if non_auth_per_1k > 0:
        overhead = ((auth_per_1k - non_auth_per_1k) / non_auth_per_1k) * 100
        ax2.text(0.5, 0.95, f'Auth overhead: {overhead:+.1f}%', transform=ax2.transAxes, ha='center',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved auth cost overhead to {output_path}")
    plt.close()


def plot_cost_scaling(pricing_data, output_path):
    """Plot cost scaling with request volume"""
    if not pricing_data:
        return

    avg_duration_ms = pricing_data['total_duration_ms'] / pricing_data['total_requests']
    memory_gb = pricing_data['memory_mb'] / 1024
    scales = [1000, 10000, 100000, 1000000, 10000000]
    scale_labels = ['1K', '10K', '100K', '1M', '10M']

    aws_costs, gcp_costs, azure_costs = [], [], []
    for scale in scales:
        gb_s = (scale * avg_duration_ms / 1000) * memory_gb
        aws_costs.append(scale * AWS_LAMBDA_PRICING['request_cost'] + gb_s * AWS_LAMBDA_PRICING['duration_cost_per_gb_second'])
        gcp_costs.append((scale / 1e6) * GCP_CLOUD_FUNCTIONS_PRICING['invocations_per_million'] +
                        (scale * avg_duration_ms / 100) * GCP_CLOUD_FUNCTIONS_PRICING['compute_per_100ms_128mb'] * (pricing_data['memory_mb'] / 128))
        azure_costs.append((scale / 1e6) * AZURE_FUNCTIONS_PRICING['executions_per_million'] + gb_s * AZURE_FUNCTIONS_PRICING['gb_seconds'])

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(scales))
    width = 0.25
    ax.bar(x - width, aws_costs, width, label='AWS Lambda', color='#FF9900', alpha=0.8)
    ax.bar(x, gcp_costs, width, label='GCP', color='#4285F4', alpha=0.8)
    ax.bar(x + width, azure_costs, width, label='Azure', color='#0078D4', alpha=0.8)
    ax.set_xlabel('Number of Requests')
    ax.set_ylabel('Estimated Cost ($)')
    ax.set_title(f'Cost Scaling (avg: {avg_duration_ms:.0f}ms, {pricing_data["memory_mb"]}MB)')
    ax.set_xticks(x)
    ax.set_xticklabels(scale_labels)
    ax.legend()
    ax.set_yscale('log')
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  Saved cost scaling to {output_path}")
    plt.close()


def generate_cost_summary(pricing_data, output_path):
    """Generate text summary of pricing"""
    if not pricing_data:
        return

    lines = [
        "=" * 60, "PRICING ANALYSIS SUMMARY", "=" * 60, "",
        "WORKLOAD", "-" * 40,
        f"Total Requests:     {pricing_data['total_requests']:,}",
        f"Total Duration:     {pricing_data['total_duration_s']:.2f}s",
        f"GB-Seconds:         {pricing_data['gb_seconds']:.4f}",
        f"Memory:             {pricing_data['memory_mb']}MB",
        f"Auth Requests:      {pricing_data['auth_requests']:,} ({pricing_data['auth_requests']/pricing_data['total_requests']*100:.1f}%)", "",
        "COSTS (USD)", "-" * 40,
        f"AWS Lambda:         ${pricing_data['aws']['total']:.6f}",
        f"AWS + API GW:       ${pricing_data['aws']['total_with_api_gw']:.6f}",
        f"GCP Cloud Func:     ${pricing_data['gcp']['total']:.6f}",
        f"Azure Functions:    ${pricing_data['azure']['total']:.6f}", "",
        "COST PER 1000 REQUESTS", "-" * 40,
        f"AWS:                ${(pricing_data['aws']['total']/pricing_data['total_requests']*1000):.6f}",
        f"GCP:                ${(pricing_data['gcp']['total']/pricing_data['total_requests']*1000):.6f}",
        f"Azure:              ${(pricing_data['azure']['total']/pricing_data['total_requests']*1000):.6f}",
        "=" * 60
    ]

    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"  Saved pricing summary to {output_path}")


def generate_pricing_plots(data, endpoint_times, output_dir, memory_mb=256):
    """Generate all pricing analysis plots"""
    print("\n--- Generating Pricing Analysis Plots ---")

    pricing_data = calculate_pricing_data(data, endpoint_times, memory_mb=memory_mb)

    if not pricing_data:
        print("No pricing data available")
        return None

    plot_cloud_cost_comparison(pricing_data, os.path.join(output_dir, "pricing_cloud_comparison.png"))
    plot_cost_breakdown(pricing_data, os.path.join(output_dir, "pricing_cost_breakdown.png"))
    plot_endpoint_cost(pricing_data, os.path.join(output_dir, "pricing_endpoint_cost.png"))
    plot_auth_cost_overhead(pricing_data, os.path.join(output_dir, "pricing_auth_overhead.png"))
    plot_cost_scaling(pricing_data, os.path.join(output_dir, "pricing_cost_scaling.png"))
    generate_cost_summary(pricing_data, os.path.join(output_dir, "pricing_summary.txt"))

    return pricing_data