#!/usr/bin/env python3
"""
Validate HTTP responses from BeFaaS experiment logs
Extracts status codes and categorizes them as success (2xx/3xx) or error (4xx/5xx)
"""

import sys
import re
import json
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def parse_artillery_log(log_file):
    """Parse Artillery log file to extract HTTP status codes"""

    status_codes = defaultdict(int)
    response_times_by_status = defaultdict(list)

    with open(log_file, 'r') as f:
        content = f.read()

    # Remove ANSI color codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    content = ansi_escape.sub('', content)

    # Find the summary report section - extract a large chunk after "Summary report"
    summary_idx = content.find('Summary report')
    if summary_idx == -1:
        print("Warning: Could not find Artillery summary report")
        return status_codes, response_times_by_status

    # Extract ~10KB after Summary report to ensure we get all stats
    summary = content[summary_idx:summary_idx + 10000]

    # Extract HTTP status codes
    # Pattern: http.codes.XXX: ... number
    # Handle terraform remote-exec prefix
    code_pattern = r'http\.codes\.(\d+):.*?(\d+)\s*$'

    for match in re.finditer(code_pattern, summary, re.MULTILINE):
        code = int(match.group(1))
        count = int(match.group(2))
        status_codes[code] = count

    # Debug: if no codes found, try extracting lines manually
    if not status_codes:
        for line in summary.split('\n'):
            if 'http.codes.' in line:
                # Extract code and count from lines like:
                # "http.codes.302: ................................... 1380"
                parts = line.split('http.codes.')
                if len(parts) > 1:
                    code_part = parts[1].split(':')[0].strip()
                    if code_part.isdigit():
                        # Find the last number in the line
                        numbers = re.findall(r'\d+', line)
                        if len(numbers) >= 2:  # At least status code + count
                            status_codes[int(code_part)] = int(numbers[-1])

    # Extract response time stats by status class
    # Pattern: http.response_time.Xxx: (followed by stats)
    time_patterns = {
        '2xx': r'http\.response_time\.2xx:.*?median:.*?(\d+\.?\d*)',
        '3xx': r'http\.response_time\.3xx:.*?median:.*?(\d+\.?\d*)',
        '4xx': r'http\.response_time\.4xx:.*?median:.*?(\d+\.?\d*)',
        '5xx': r'http\.response_time\.5xx:.*?median:.*?(\d+\.?\d*)',
    }

    for status_class, pattern in time_patterns.items():
        match = re.search(pattern, summary, re.DOTALL)
        if match:
            median_time = float(match.group(1))
            response_times_by_status[status_class] = median_time

    return status_codes, response_times_by_status

def categorize_status_codes(status_codes):
    """Categorize status codes into success and error groups"""

    categories = {
        'success': {},  # 2xx and 3xx
        'client_error': {},  # 4xx
        'server_error': {},  # 5xx
        'other': {}  # 1xx or unknown
    }

    for code, count in status_codes.items():
        if 200 <= code < 300:
            categories['success'][code] = count
        elif 300 <= code < 400:
            categories['success'][code] = count  # Redirects usually indicate success
        elif 400 <= code < 500:
            categories['client_error'][code] = count
        elif 500 <= code < 600:
            categories['server_error'][code] = count
        else:
            categories['other'][code] = count

    return categories

def plot_status_code_distribution(status_codes, output_path):
    """Create a bar chart of HTTP status code distribution"""

    if not status_codes:
        print("No status codes to plot")
        return

    # Sort by status code
    codes = sorted(status_codes.keys())
    counts = [status_codes[code] for code in codes]

    # Color codes: green for 2xx/3xx, yellow for 4xx, red for 5xx
    colors = []
    for code in codes:
        if 200 <= code < 400:
            colors.append('green')
        elif 400 <= code < 500:
            colors.append('orange')
        else:
            colors.append('red')

    fig, ax = plt.subplots(figsize=(12, 6))

    bars = ax.bar([str(c) for c in codes], counts, color=colors, alpha=0.7, edgecolor='black')

    # Add value labels on bars
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}',
                ha='center', va='bottom', fontsize=10)

    ax.set_xlabel('HTTP Status Code', fontsize=12)
    ax.set_ylabel('Number of Responses', fontsize=12)
    ax.set_title('HTTP Response Status Code Distribution', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')

    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='green', alpha=0.7, label='Success (2xx/3xx)'),
        Patch(facecolor='orange', alpha=0.7, label='Client Error (4xx)'),
        Patch(facecolor='red', alpha=0.7, label='Server Error (5xx)')
    ]
    ax.legend(handles=legend_elements, loc='upper right')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved status code distribution to {output_path}")
    plt.close()

def plot_success_vs_error_pie(categories, output_path):
    """Create a pie chart showing success vs error rates"""

    total_success = sum(categories['success'].values())
    total_client_error = sum(categories['client_error'].values())
    total_server_error = sum(categories['server_error'].values())
    total_other = sum(categories['other'].values())

    # Combine all errors
    total_error = total_client_error + total_server_error + total_other

    if total_success + total_error == 0:
        print("No data for success/error pie chart")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Overall success vs error
    labels = ['Success\n(2xx/3xx)', 'Errors\n(4xx/5xx)']
    sizes = [total_success, total_error]
    colors = ['green', 'red']
    explode = (0.05, 0.05)

    ax1.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%',
            shadow=True, startangle=90, textprops={'fontsize': 12, 'weight': 'bold'})
    ax1.set_title('Success vs Error Rate', fontsize=14, fontweight='bold')

    # Detailed breakdown
    detail_labels = []
    detail_sizes = []
    detail_colors = []

    if total_success > 0:
        detail_labels.append(f'Success\n({total_success})')
        detail_sizes.append(total_success)
        detail_colors.append('green')

    if total_client_error > 0:
        detail_labels.append(f'4xx Client Error\n({total_client_error})')
        detail_sizes.append(total_client_error)
        detail_colors.append('orange')

    if total_server_error > 0:
        detail_labels.append(f'5xx Server Error\n({total_server_error})')
        detail_sizes.append(total_server_error)
        detail_colors.append('red')

    if total_other > 0:
        detail_labels.append(f'Other\n({total_other})')
        detail_sizes.append(total_other)
        detail_colors.append('gray')

    ax2.pie(detail_sizes, labels=detail_labels, colors=detail_colors, autopct='%1.1f%%',
            shadow=True, startangle=90, textprops={'fontsize': 11})
    ax2.set_title('Detailed Status Breakdown', fontsize=14, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved success/error pie chart to {output_path}")
    plt.close()

def generate_validation_report(status_codes, categories, response_times, output_file):
    """Generate a detailed text report of validation results"""

    total_requests = sum(status_codes.values())
    total_success = sum(categories['success'].values())
    total_client_error = sum(categories['client_error'].values())
    total_server_error = sum(categories['server_error'].values())
    total_error = total_client_error + total_server_error

    success_rate = (total_success / total_requests * 100) if total_requests > 0 else 0
    error_rate = (total_error / total_requests * 100) if total_requests > 0 else 0

    report = []
    report.append("=" * 70)
    report.append("HTTP RESPONSE VALIDATION REPORT")
    report.append("=" * 70)
    report.append("")

    report.append("OVERALL SUMMARY")
    report.append("-" * 70)
    report.append(f"Total Requests:          {total_requests:>10,}")
    report.append(f"Successful (2xx/3xx):    {total_success:>10,}  ({success_rate:>6.2f}%)")
    report.append(f"Client Errors (4xx):     {total_client_error:>10,}  ({total_client_error/total_requests*100:>6.2f}%)")
    report.append(f"Server Errors (5xx):     {total_server_error:>10,}  ({total_server_error/total_requests*100:>6.2f}%)")
    report.append(f"Total Errors:            {total_error:>10,}  ({error_rate:>6.2f}%)")
    report.append("")

    # Status verdict
    if error_rate == 0:
        report.append("✓ STATUS: EXCELLENT - All requests succeeded!")
    elif error_rate < 1:
        report.append("✓ STATUS: GOOD - Less than 1% error rate")
    elif error_rate < 5:
        report.append("⚠ STATUS: WARNING - Elevated error rate (1-5%)")
    elif error_rate < 50:
        report.append("✗ STATUS: POOR - High error rate (5-50%)")
    else:
        report.append("✗✗ STATUS: CRITICAL - Majority of requests failing (>50%)")

    report.append("")

    # Detailed status code breakdown
    report.append("DETAILED STATUS CODE BREAKDOWN")
    report.append("-" * 70)

    if categories['success']:
        report.append("\nSuccessful Responses (2xx/3xx):")
        for code in sorted(categories['success'].keys()):
            count = categories['success'][code]
            pct = count / total_requests * 100
            status_name = get_status_name(code)
            report.append(f"  {code} {status_name:30s}: {count:>8,}  ({pct:>6.2f}%)")

    if categories['client_error']:
        report.append("\nClient Errors (4xx):")
        for code in sorted(categories['client_error'].keys()):
            count = categories['client_error'][code]
            pct = count / total_requests * 100
            status_name = get_status_name(code)
            report.append(f"  {code} {status_name:30s}: {count:>8,}  ({pct:>6.2f}%)")

    if categories['server_error']:
        report.append("\nServer Errors (5xx):")
        for code in sorted(categories['server_error'].keys()):
            count = categories['server_error'][code]
            pct = count / total_requests * 100
            status_name = get_status_name(code)
            report.append(f"  {code} {status_name:30s}: {count:>8,}  ({pct:>6.2f}%)")

    # Response times
    if response_times:
        report.append("")
        report.append("RESPONSE TIMES BY STATUS CLASS")
        report.append("-" * 70)
        for status_class, median_time in sorted(response_times.items()):
            report.append(f"  {status_class:5s} median response time: {median_time:>8.1f} ms")

    report.append("")
    report.append("=" * 70)

    report_text = "\n".join(report)

    # Write to file
    with open(output_file, 'w') as f:
        f.write(report_text)

    print(f"✓ Saved validation report to {output_file}")

    return report_text

def get_status_name(code):
    """Get human-readable name for HTTP status code"""
    status_names = {
        200: "OK",
        201: "Created",
        202: "Accepted",
        204: "No Content",
        301: "Moved Permanently",
        302: "Found (Redirect)",
        304: "Not Modified",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        408: "Request Timeout",
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
        504: "Gateway Timeout",
    }
    return status_names.get(code, "Unknown")

def main(log_file, output_dir):
    """Main validation function"""

    print(f"Parsing Artillery log file: {log_file}")

    status_codes, response_times = parse_artillery_log(log_file)

    if not status_codes:
        print("✗ No HTTP status codes found in log file")
        print("  Make sure the log file contains Artillery summary report")
        return 1

    print(f"Found {len(status_codes)} different status codes")
    print(f"Total requests: {sum(status_codes.values())}")

    # Categorize status codes
    categories = categorize_status_codes(status_codes)

    # Generate visualizations
    print("\nGenerating validation plots...")

    plot_status_code_distribution(
        status_codes,
        f"{output_dir}/http_status_codes.png"
    )

    plot_success_vs_error_pie(
        categories,
        f"{output_dir}/success_vs_error.png"
    )

    # Generate text report
    print("\nGenerating validation report...")
    report_text = generate_validation_report(
        status_codes,
        categories,
        response_times,
        f"{output_dir}/validation_report.txt"
    )

    # Print summary to console
    print("\n" + report_text)

    print("\n✓ Validation complete!")

    # Return exit code based on error rate
    total_requests = sum(status_codes.values())
    total_error = sum(categories['client_error'].values()) + sum(categories['server_error'].values())
    error_rate = (total_error / total_requests * 100) if total_requests > 0 else 0

    if error_rate > 50:
        return 2  # Critical
    elif error_rate > 5:
        return 1  # Warning
    else:
        return 0  # Success

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <artillery_log_file> <output_directory>")
        sys.exit(1)

    exit_code = main(sys.argv[1], sys.argv[2])
    sys.exit(exit_code)
