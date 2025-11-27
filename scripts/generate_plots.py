#!/usr/bin/env python3
"""
Generate analysis plots from BeFaaS experiment dump.json
"""

import json
import sys
from datetime import datetime
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np

def parse_datetime(dt_dict):
    """Parse datetime from dict format"""
    if isinstance(dt_dict, dict) and '__datetime__' in dt_dict:
        return datetime.fromisoformat(dt_dict['__datetime__'])
    return None

def analyze_response_times(data):
    """Analyze response times from logs"""
    response_times = []
    function_times = defaultdict(list)

    # Track start marks to match with end marks
    start_marks = {}  # key: (contextId, mark_id) -> timestamp

    for entry in data:
        if '__logentry__' not in entry:
            continue

        log = entry['__logentry__']
        event_data = log.get('data', {}).get('event', {})
        timestamp_data = log.get('data', {}).get('now', 0)

        # Look for performance marks
        if 'perf' in event_data:
            perf = event_data['perf']
            mark = perf.get('mark', '')
            context_id = event_data.get('contextId', '')

            # Handle measure marks with explicit duration
            if mark.startswith('measure:') and perf.get('duration', 0) > 0:
                duration_ms = perf['duration']
                response_times.append(duration_ms)

                # Extract endpoint/function name from mark
                parts = mark.split(':')
                if len(parts) >= 2:
                    func_name = ':'.join(parts[1:])  # e.g., "post:/setUser"
                    function_times[func_name].append(duration_ms)

            # Handle start/end mark pairs for RPC calls
            elif mark.startswith('start:rpcOut:') or mark.startswith('start:rpcIn:'):
                # Store start timestamp
                mark_id = mark.replace('start:', '')
                start_marks[(context_id, mark_id)] = timestamp_data

            elif mark.startswith('end:rpcOut:') or mark.startswith('end:rpcIn:'):
                # Match with start and calculate duration
                mark_id = mark.replace('end:', '')
                key = (context_id, mark_id)

                if key in start_marks:
                    duration_ms = timestamp_data - start_marks[key]

                    if duration_ms > 0:
                        response_times.append(duration_ms)

                        # Extract function name from mark (e.g., "rpcOut:listproducts:...")
                        parts = mark_id.split(':')
                        if len(parts) >= 2:
                            func_name = parts[1]  # e.g., "listproducts"
                            function_times[func_name].append(duration_ms)

                    # Clean up
                    del start_marks[key]

            # Handle start/end for regular endpoints
            elif mark.startswith('start:get:') or mark.startswith('start:post:'):
                mark_id = mark.replace('start:', '')
                start_marks[(context_id, mark_id)] = timestamp_data

            elif mark.startswith('end:get:') or mark.startswith('end:post:'):
                mark_id = mark.replace('end:', '')
                key = (context_id, mark_id)

                if key in start_marks:
                    duration_ms = timestamp_data - start_marks[key]

                    if duration_ms > 0:
                        response_times.append(duration_ms)
                        function_times[mark_id].append(duration_ms)

                    del start_marks[key]

    return response_times, function_times

def analyze_function_calls(data):
    """Count function invocations"""
    function_calls = defaultdict(int)
    coldstarts = defaultdict(int)
    rpc_calls = defaultdict(int)
    endpoint_calls = defaultdict(int)

    for entry in data:
        if '__logentry__' not in entry:
            continue

        log = entry['__logentry__']
        event_data = log.get('data', {}).get('event', {})
        fn_data = log.get('data', {}).get('fn', {})

        fn_name = fn_data.get('name', 'unknown')

        # Count invocations
        if 'contextId' in event_data:
            function_calls[fn_name] += 1

        # Count coldstarts
        if event_data.get('coldstart'):
            coldstarts[fn_name] += 1

        # Count RPC calls and endpoints from performance marks
        if 'perf' in event_data:
            perf = event_data['perf']
            mark = perf.get('mark', '')

            # Count RPC out calls
            if mark.startswith('start:rpcOut:'):
                parts = mark.split(':')
                if len(parts) >= 3:
                    rpc_func = parts[2]
                    rpc_calls[rpc_func] += 1

            # Count endpoint calls
            elif mark.startswith('start:get:') or mark.startswith('start:post:'):
                endpoint = mark.replace('start:', '')
                endpoint_calls[endpoint] += 1

    return function_calls, coldstarts, rpc_calls, endpoint_calls

def plot_response_time_distribution(response_times, output_path):
    """Create response time distribution plot"""
    if not response_times:
        print("No response time data found")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Histogram
    ax1.hist(response_times, bins=50, edgecolor='black', alpha=0.7)
    ax1.set_xlabel('Response Time (ms)')
    ax1.set_ylabel('Frequency')
    ax1.set_title('Response Time Distribution')
    ax1.grid(True, alpha=0.3)

    # Box plot
    ax2.boxplot(response_times, vert=True)
    ax2.set_ylabel('Response Time (ms)')
    ax2.set_title('Response Time Box Plot')
    ax2.grid(True, alpha=0.3)

    # Add statistics text
    stats_text = f'Mean: {np.mean(response_times):.2f}ms\n'
    stats_text += f'Median: {np.median(response_times):.2f}ms\n'
    stats_text += f'P95: {np.percentile(response_times, 95):.2f}ms\n'
    stats_text += f'P99: {np.percentile(response_times, 99):.2f}ms'
    ax2.text(1.5, np.median(response_times), stats_text,
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved response time distribution to {output_path}")
    plt.close()

def plot_function_times(function_times, output_path):
    """Create per-function response time plot"""
    if not function_times:
        print("No function timing data found")
        return

    # Filter out functions with very few calls
    filtered_times = {k: v for k, v in function_times.items() if len(v) >= 5}

    if not filtered_times:
        print("Not enough data for function timing plot")
        return

    fig, ax = plt.subplots(figsize=(12, 6))

    # Prepare data for box plot
    labels = []
    data_to_plot = []
    for func_name, times in sorted(filtered_times.items(),
                                   key=lambda x: np.median(x[1])):
        labels.append(func_name.replace('rpcOut:', ''))
        data_to_plot.append(times)

    bp = ax.boxplot(data_to_plot, labels=labels, vert=False, patch_artist=True)

    # Color the boxes
    for patch in bp['boxes']:
        patch.set_facecolor('lightblue')
        patch.set_alpha(0.7)

    ax.set_xlabel('Response Time (ms)')
    ax.set_ylabel('Function')
    ax.set_title('Response Time by Function')
    ax.grid(True, alpha=0.3, axis='x')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved function timing plot to {output_path}")
    plt.close()

def plot_function_calls(function_calls, coldstarts, output_path):
    """Create function invocation count plot"""
    if not function_calls:
        print("No function call data found")
        return

    # Sort by call count
    sorted_funcs = sorted(function_calls.items(), key=lambda x: x[1], reverse=True)
    funcs = [f[0] for f in sorted_funcs[:15]]  # Top 15
    counts = [f[1] for f in sorted_funcs[:15]]
    cold_counts = [coldstarts.get(f, 0) for f in funcs]

    fig, ax = plt.subplots(figsize=(12, 6))

    x = np.arange(len(funcs))
    width = 0.35

    bars1 = ax.bar(x - width/2, counts, width, label='Total Calls', alpha=0.8)
    bars2 = ax.bar(x + width/2, cold_counts, width, label='Cold Starts', alpha=0.8)

    ax.set_xlabel('Function')
    ax.set_ylabel('Count')
    ax.set_title('Function Invocations and Cold Starts')
    ax.set_xticks(x)
    ax.set_xticklabels(funcs, rotation=45, ha='right')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved function calls plot to {output_path}")
    plt.close()

def plot_timeline(data, output_path):
    """Create timeline of events"""
    timestamps = []
    event_types = []

    for entry in data[:1000]:  # Sample first 1000 events
        if '__logentry__' not in entry:
            continue

        log = entry['__logentry__']
        ts = parse_datetime(log.get('timestamp'))
        if ts:
            timestamps.append(ts)
            event_data = log.get('data', {}).get('event', {})
            if 'coldstart' in event_data:
                event_types.append('coldstart')
            elif 'perf' in event_data:
                event_types.append('perf')
            else:
                event_types.append('other')

    if not timestamps:
        print("No timeline data found")
        return

    fig, ax = plt.subplots(figsize=(14, 4))

    # Convert to relative time in seconds
    start_time = min(timestamps)
    relative_times = [(t - start_time).total_seconds() for t in timestamps]

    colors = {'coldstart': 'red', 'perf': 'blue', 'other': 'gray'}
    for i, (t, et) in enumerate(zip(relative_times, event_types)):
        ax.scatter(t, 0, c=colors.get(et, 'gray'), alpha=0.5, s=10)

    ax.set_xlabel('Time (seconds)')
    ax.set_yticks([])
    ax.set_title('Event Timeline')
    ax.grid(True, alpha=0.3, axis='x')

    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=c, label=l)
                      for l, c in colors.items()]
    ax.legend(handles=legend_elements, loc='upper right')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved timeline plot to {output_path}")
    plt.close()

def main(dump_file, output_dir):
    """Main analysis function"""
    print(f"Loading data from {dump_file}...")
    with open(dump_file, 'r') as f:
        data = json.load(f)

    print(f"Loaded {len(data)} log entries")

    # Analyze data
    print("\nAnalyzing response times...")
    response_times, function_times = analyze_response_times(data)
    print(f"  Found {len(response_times)} response time measurements")

    print("\nAnalyzing function calls...")
    function_calls, coldstarts, rpc_calls, endpoint_calls = analyze_function_calls(data)
    print(f"  Found {sum(function_calls.values())} total function calls")
    print(f"  Found {sum(coldstarts.values())} cold starts")
    print(f"  Found {sum(rpc_calls.values())} RPC calls")
    print(f"  Found {sum(endpoint_calls.values())} endpoint calls")

    # Generate plots
    print("\nGenerating plots...")

    if response_times:
        plot_response_time_distribution(
            response_times,
            f"{output_dir}/response_time_distribution.png"
        )

    if function_times:
        plot_function_times(
            function_times,
            f"{output_dir}/function_response_times.png"
        )

    if function_calls:
        plot_function_calls(
            function_calls,
            coldstarts,
            f"{output_dir}/function_invocations.png"
        )

    if rpc_calls:
        plot_function_calls(
            rpc_calls,
            {},
            f"{output_dir}/rpc_call_counts.png"
        )

    plot_timeline(data, f"{output_dir}/event_timeline.png")

    # Print summary statistics
    print("\n" + "="*60)
    print("SUMMARY STATISTICS")
    print("="*60)

    if response_times:
        print(f"\nResponse Times:")
        print(f"  Total measurements: {len(response_times)}")
        print(f"  Mean: {np.mean(response_times):.2f}ms")
        print(f"  Median: {np.median(response_times):.2f}ms")
        print(f"  P95: {np.percentile(response_times, 95):.2f}ms")
        print(f"  P99: {np.percentile(response_times, 99):.2f}ms")
        print(f"  Min: {np.min(response_times):.2f}ms")
        print(f"  Max: {np.max(response_times):.2f}ms")

    if function_calls:
        print(f"\nTop 10 Most Called Functions:")
        for func, count in sorted(function_calls.items(),
                                  key=lambda x: x[1], reverse=True)[:10]:
            cold = coldstarts.get(func, 0)
            cold_pct = (cold / count * 100) if count > 0 else 0
            print(f"  {func:30s}: {count:6d} calls ({cold:4d} cold starts, {cold_pct:.1f}%)")

    if rpc_calls:
        print(f"\nTop 10 Most Called RPC Functions:")
        for func, count in sorted(rpc_calls.items(),
                                  key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {func:30s}: {count:6d} calls")

    if endpoint_calls:
        print(f"\nTop 10 Most Called Endpoints:")
        for endpoint, count in sorted(endpoint_calls.items(),
                                     key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {endpoint:40s}: {count:6d} calls")

    print(f"\nNote: Only {len(function_times)} functions have timing data.")
    print(f"      RPC functions have call counts but no timing measurements in this dataset.")

    print("\n✓ Analysis complete!")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <dump.json> <output_directory>")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])