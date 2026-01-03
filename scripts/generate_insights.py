#!/usr/bin/env python3
"""
Generate insights.json from dump.json

This script analyzes the performance data from dump.json and generates
comprehensive metrics including response times, auth times, throughput,
correlations, and call chain breakdowns.
"""

import json
import sys
import os
from datetime import datetime, timezone
from collections import defaultdict
import numpy as np

def load_dump(dump_path):
    """Load dump.json file with error handling for malformed JSON"""
    print(f"Loading data from {dump_path}...")
    try:
        with open(dump_path, 'r') as f:
            data = json.load(f)
        print(f"  Loaded {len(data)} log entries")
        return data
    except json.JSONDecodeError as e:
        print(f"  Warning: JSON decode error at position {e.pos}: {e.msg}")
        print(f"  Attempting to recover partial data...")

        # Try to recover by reading as much valid JSON as possible
        with open(dump_path, 'r') as f:
            content = f.read()

        recovered_data = []

        # Strategy 1: Check if array is truncated (missing closing ])
        # Find the last complete JSON object by looking for },{ pattern
        if content.startswith('['):
            try:
                # Find last complete object ending with }}
                # The pattern is },{"__logentry__": or end of array }]
                last_complete = -1

                # Search backwards for the last complete entry
                # Each entry ends with }}, so find the last }},{ or }}]
                pos = len(content) - 1
                brace_count = 0
                in_string = False
                escape_next = False

                # First, try adding just ] to see if array is simply missing closure
                try:
                    test_content = content.rstrip() + ']'
                    recovered_data = json.loads(test_content)
                    print(f"  Recovered {len(recovered_data)} log entries by adding missing ]")
                    return recovered_data
                except:
                    pass

                # Find the last complete }},{ pattern
                pattern = '}},{"__logentry__"'
                last_entry_pos = content.rfind(pattern)
                if last_entry_pos > 0:
                    # Include up to and including the }}
                    truncated = content[:last_entry_pos + 2] + ']'
                    try:
                        recovered_data = json.loads(truncated)
                        print(f"  Recovered {len(recovered_data)} log entries by truncating at last complete entry")
                        return recovered_data
                    except json.JSONDecodeError as inner_e:
                        print(f"  First recovery attempt failed: {inner_e.msg}")

                # Try more aggressive truncation - find last }}
                last_double_brace = content.rfind('}}')
                if last_double_brace > 0:
                    truncated = content[:last_double_brace + 2] + ']'
                    try:
                        recovered_data = json.loads(truncated)
                        print(f"  Recovered {len(recovered_data)} log entries by truncating at last }}")
                        return recovered_data
                    except:
                        pass

            except Exception as recovery_error:
                print(f"  Array recovery failed: {recovery_error}")

        # Strategy 2: Try to parse individual JSON objects (newline-delimited)
        if not recovered_data:
            try:
                for line in content.split('\n'):
                    line = line.strip()
                    if line.startswith('{') and line.endswith('}'):
                        try:
                            recovered_data.append(json.loads(line))
                        except:
                            pass
                if recovered_data:
                    print(f"  Recovered {len(recovered_data)} log entries from line-by-line parsing")
            except Exception as line_error:
                print(f"  Line-by-line recovery failed: {line_error}")

        if not recovered_data:
            print(f"  Unable to recover any data, returning empty dataset")
            return []

        return recovered_data

def parse_entries(data):
    """Parse log entries into structured data"""
    entries = {
        'requests': [],           # Artillery requests (endpoint level)
        'function_calls': [],     # Function-level timing (rpcIn, rpcOut)
        'auth_checks': [],        # Auth timing events
        'coldstarts': [],         # Coldstart events
    }

    # First pass: collect before/after events to calculate response times
    before_events = {}  # xPair -> {timestamp, url, contextId}

    for entry in data:
        if not isinstance(entry, dict) or '__logentry__' not in entry:
            continue

        log_entry = entry['__logentry__']
        event_data = log_entry.get('data', {})
        timestamp = log_entry.get('timestamp', {})

        # Extract timestamp
        ts = None
        ts_ms = None
        if isinstance(timestamp, dict) and '__datetime__' in timestamp:
            ts = timestamp['__datetime__']
        # Also get millisecond timestamp from data
        ts_ms = event_data.get('timestamp') or event_data.get('now')

        event = event_data.get('event', {})

        # Artillery request entries (have url and type before/after)
        if 'url' in event and 'type' in event:
            x_pair = event.get('xPair', '')

            if event.get('type') == 'before':
                before_events[x_pair] = {
                    'timestamp': ts,
                    'timestamp_ms': ts_ms,
                    'url': event.get('url', ''),
                    'context_id': event.get('contextId', ''),
                }
            elif event.get('type') == 'after':
                # Calculate response time from before event
                if x_pair in before_events:
                    before = before_events[x_pair]
                    # Calculate response time from now values (high-res timer)
                    response_time = 0
                    if ts_ms and before.get('timestamp_ms'):
                        response_time = ts_ms - before['timestamp_ms']

                    # Get status code if available, default to 200
                    status_code = event.get('statusCode', 200)

                    entries['requests'].append({
                        'timestamp': ts,
                        'url': before.get('url', event.get('url', '')),
                        'response_time_ms': response_time,
                        'status_code': status_code,
                        'context_id': before.get('context_id', event.get('contextId', '')),
                        'x_pair': x_pair,
                    })

        # Function timing entries (have perf data)
        if 'perf' in event:
            perf = event['perf']
            fn_name = event_data.get('fn', {}).get('name', '')
            context_id = event.get('contextId', '')
            x_pair = event.get('xPair', '')

            if perf.get('entryType') == 'measure' and perf.get('duration', 0) > 0:
                mark = perf.get('mark', '')
                entries['function_calls'].append({
                    'timestamp': ts,
                    'function': fn_name,
                    'mark': mark,
                    'duration_ms': perf.get('duration', 0),
                    'context_id': context_id,
                    'x_pair': x_pair,
                })

        # Auth check entries
        if 'authCheck' in event:
            auth = event['authCheck']
            fn_name = event_data.get('fn', {}).get('name', '')
            context_id = event.get('contextId', '')
            x_pair = event.get('xPair', '')
            entries['auth_checks'].append({
                'timestamp': ts,
                'function': fn_name,
                'duration_ms': auth.get('durationMs', 0),
                'success': auth.get('success', False),
                'context_id': context_id,
                'x_pair': x_pair,
            })

        # Coldstart entries
        if event.get('coldstart'):
            fn_name = event_data.get('fn', {}).get('name', '')
            entries['coldstarts'].append({
                'timestamp': ts,
                'function': fn_name,
            })

    print(f"  Parsed: {len(entries['requests'])} requests, {len(entries['function_calls'])} function calls, {len(entries['auth_checks'])} auth checks, {len(entries['coldstarts'])} coldstarts")
    return entries

def extract_endpoint(url):
    """Extract endpoint pattern from URL"""
    if not url:
        return 'unknown'

    # Remove query params
    url = url.split('?')[0]

    # Extract path after the base URL
    parts = url.split('/')

    # Find the path starting from 'frontend' or similar
    path_parts = []
    capture = False
    for part in parts:
        if part in ['frontend', 'api', 'dev', 'prod']:
            capture = True
        if capture and part:
            path_parts.append(part)

    if not path_parts:
        return '/unknown'

    # Normalize dynamic parts (product IDs, etc.)
    normalized = []
    for part in path_parts:
        # Check if it looks like an ID (alphanumeric, longer than 5 chars)
        if len(part) > 5 and part.isalnum() and not part.isalpha():
            normalized.append(':id')
        else:
            normalized.append(part)

    return '/' + '/'.join(normalized)

def calculate_percentiles(values):
    """Calculate statistical metrics for a list of values"""
    if not values:
        return None

    arr = np.array(values)
    return {
        'mean_ms': round(float(np.mean(arr)), 2),
        'median_ms': round(float(np.median(arr)), 2),
        'p75_ms': round(float(np.percentile(arr, 75)), 2),
        'p90_ms': round(float(np.percentile(arr, 90)), 2),
        'p95_ms': round(float(np.percentile(arr, 95)), 2),
        'p99_ms': round(float(np.percentile(arr, 99)), 2),
    }

def filter_coldstarts(entries, warmup_seconds=60):
    """Filter out requests during warmup period"""
    if not entries['requests']:
        return entries, 0

    # Find the earliest timestamp
    timestamps = []
    for req in entries['requests']:
        if req['timestamp']:
            try:
                ts = datetime.fromisoformat(req['timestamp'].replace('Z', '+00:00'))
                timestamps.append(ts)
            except:
                pass

    if not timestamps:
        return entries, 0

    min_ts = min(timestamps)
    cutoff_ts = min_ts.timestamp() + warmup_seconds

    filtered = {
        'requests': [],
        'function_calls': [],
        'auth_checks': [],
        'coldstarts': entries['coldstarts'],
    }

    removed_count = 0

    for req in entries['requests']:
        if req['timestamp']:
            try:
                ts = datetime.fromisoformat(req['timestamp'].replace('Z', '+00:00'))
                if ts.timestamp() >= cutoff_ts:
                    filtered['requests'].append(req)
                else:
                    removed_count += 1
            except:
                filtered['requests'].append(req)
        else:
            filtered['requests'].append(req)

    for call in entries['function_calls']:
        if call['timestamp']:
            try:
                ts = datetime.fromisoformat(call['timestamp'].replace('Z', '+00:00'))
                if ts.timestamp() >= cutoff_ts:
                    filtered['function_calls'].append(call)
            except:
                filtered['function_calls'].append(call)
        else:
            filtered['function_calls'].append(call)

    for auth in entries['auth_checks']:
        if auth['timestamp']:
            try:
                ts = datetime.fromisoformat(auth['timestamp'].replace('Z', '+00:00'))
                if ts.timestamp() >= cutoff_ts:
                    filtered['auth_checks'].append(auth)
            except:
                filtered['auth_checks'].append(auth)
        else:
            filtered['auth_checks'].append(auth)

    return filtered, removed_count

def analyze_http_status(requests):
    """Analyze HTTP status code distribution and response times"""
    status_counts = defaultdict(int)
    status_times = defaultdict(list)

    for req in requests:
        status = str(req.get('status_code', 200))
        status_counts[status] += 1
        if req.get('response_time_ms'):
            status_times[status].append(req['response_time_ms'])

    distribution = dict(sorted(status_counts.items()))

    response_times_by_status = {}
    for status, times in status_times.items():
        if times:
            stats = calculate_percentiles(times)
            if stats:
                stats['count'] = len(times)
                response_times_by_status[status] = stats

    return {
        'distribution': distribution,
        'response_times_by_status': response_times_by_status,
    }

def analyze_endpoints(requests):
    """Analyze per-endpoint metrics"""
    endpoint_counts = defaultdict(int)
    endpoint_times = defaultdict(list)

    for req in requests:
        endpoint = extract_endpoint(req.get('url', ''))
        endpoint_counts[endpoint] += 1
        if req.get('response_time_ms'):
            endpoint_times[endpoint].append(req['response_time_ms'])

    request_count = dict(sorted(endpoint_counts.items(), key=lambda x: -x[1]))

    response_times = {}
    for endpoint, times in endpoint_times.items():
        stats = calculate_percentiles(times)
        if stats:
            response_times[endpoint] = stats

    return {
        'request_count': request_count,
        'response_times': response_times,
    }

def analyze_endpoint_auth(requests, auth_checks):
    """Analyze auth times per endpoint by matching context IDs"""
    # Map context_id to endpoint
    context_to_endpoint = {}
    for req in requests:
        ctx = req.get('context_id')
        if ctx:
            context_to_endpoint[ctx] = extract_endpoint(req.get('url', ''))

    # Group auth times by endpoint
    endpoint_auth_times = defaultdict(list)
    for auth in auth_checks:
        ctx = auth.get('context_id')
        if ctx in context_to_endpoint:
            endpoint = context_to_endpoint[ctx]
            if auth.get('duration_ms'):
                endpoint_auth_times[endpoint].append(auth['duration_ms'])

    auth_times = {}
    for endpoint, times in endpoint_auth_times.items():
        stats = calculate_percentiles(times)
        if stats:
            auth_times[endpoint] = stats

    return auth_times

def analyze_functions(function_calls):
    """Analyze per-function metrics"""
    function_counts = defaultdict(int)
    function_times = defaultdict(list)

    for call in function_calls:
        fn = call.get('function', 'unknown')
        mark = call.get('mark', '')

        # Count rpcIn as a function invocation
        if 'rpcIn' in mark:
            function_counts[fn] += 1

        # Collect timing for rpcIn (function's own processing time)
        if 'rpcIn' in mark and call.get('duration_ms'):
            function_times[fn].append(call['duration_ms'])

    request_count = dict(sorted(function_counts.items(), key=lambda x: -x[1]))

    response_times = {}
    for fn, times in function_times.items():
        stats = calculate_percentiles(times)
        if stats:
            response_times[fn] = stats

    return {
        'request_count': request_count,
        'response_times': response_times,
    }

def analyze_function_auth(auth_checks):
    """Analyze auth times per function"""
    function_auth_times = defaultdict(list)

    for auth in auth_checks:
        fn = auth.get('function', 'unknown')
        if auth.get('duration_ms'):
            function_auth_times[fn].append(auth['duration_ms'])

    auth_times = {}
    for fn, times in function_auth_times.items():
        stats = calculate_percentiles(times)
        if stats:
            auth_times[fn] = stats

    return auth_times

def analyze_throughput(requests, auth_checks):
    """Analyze requests and auth operations per minute"""
    # Group by minute
    minute_requests = defaultdict(int)
    minute_auth = defaultdict(int)

    for req in requests:
        if req.get('timestamp'):
            try:
                ts = datetime.fromisoformat(req['timestamp'].replace('Z', '+00:00'))
                minute_key = ts.strftime('%Y-%m-%dT%H:%M:00.000Z')
                minute_requests[minute_key] += 1
            except:
                pass

    for auth in auth_checks:
        if auth.get('timestamp'):
            try:
                ts = datetime.fromisoformat(auth['timestamp'].replace('Z', '+00:00'))
                minute_key = ts.strftime('%Y-%m-%dT%H:%M:00.000Z')
                minute_auth[minute_key] += 1
            except:
                pass

    # Create timeline
    all_minutes = sorted(set(minute_requests.keys()) | set(minute_auth.keys()))
    timeline = []
    for i, minute in enumerate(all_minutes):
        timeline.append({
            'timestamp': minute,
            'minute': i,
            'requests_per_minute': minute_requests.get(minute, 0),
            'auth_ops_per_minute': minute_auth.get(minute, 0),
        })

    # Calculate summary
    req_values = list(minute_requests.values()) if minute_requests else [0]
    auth_values = list(minute_auth.values()) if minute_auth else [0]

    return {
        'timeline': timeline,
        'summary': {
            'requests': {
                'min_per_minute': min(req_values),
                'max_per_minute': max(req_values),
                'mean_per_minute': round(np.mean(req_values), 2),
                'median_per_minute': round(np.median(req_values), 2),
            },
            'auth_operations': {
                'min_per_minute': min(auth_values),
                'max_per_minute': max(auth_values),
                'mean_per_minute': round(np.mean(auth_values), 2),
                'median_per_minute': round(np.median(auth_values), 2),
            },
        },
    }

def analyze_correlations(requests, auth_checks):
    """Analyze correlations between load, latency, and status codes"""
    # Group requests by minute for load analysis
    minute_data = defaultdict(lambda: {'requests': [], 'auth_ops': 0})

    for req in requests:
        if req.get('timestamp'):
            try:
                ts = datetime.fromisoformat(req['timestamp'].replace('Z', '+00:00'))
                minute_key = ts.strftime('%Y-%m-%dT%H:%M:00.000Z')
                minute_data[minute_key]['requests'].append(req)
            except:
                pass

    for auth in auth_checks:
        if auth.get('timestamp'):
            try:
                ts = datetime.fromisoformat(auth['timestamp'].replace('Z', '+00:00'))
                minute_key = ts.strftime('%Y-%m-%dT%H:%M:00.000Z')
                minute_data[minute_key]['auth_ops'] += 1
            except:
                pass

    # Calculate RPM buckets
    rpm_buckets = []
    rpm_values = [len(d['requests']) for d in minute_data.values()]
    if rpm_values:
        max_rpm = max(rpm_values)
        bucket_size = max(100, (max_rpm // 5) + 1)

        for bucket_start in range(0, max_rpm + bucket_size, bucket_size):
            bucket_end = bucket_start + bucket_size
            bucket_requests = []

            for data in minute_data.values():
                rpm = len(data['requests'])
                if bucket_start <= rpm < bucket_end:
                    bucket_requests.extend(data['requests'])

            if bucket_requests:
                status_counts = defaultdict(int)
                times = []
                for req in bucket_requests:
                    status_counts[str(req.get('status_code', 200))] += 1
                    if req.get('response_time_ms'):
                        times.append(req['response_time_ms'])

                total = sum(status_counts.values())
                status_pct = {k: round(v / total * 100, 2) for k, v in status_counts.items()}

                rpm_buckets.append({
                    'requests_per_minute_range': f"{bucket_start}-{bucket_end}",
                    'status_distribution_percent': status_pct,
                    'latency': calculate_percentiles(times) if times else None,
                })

    # Calculate auth ops buckets
    auth_buckets = []
    auth_values = [d['auth_ops'] for d in minute_data.values()]
    if auth_values and max(auth_values) > 0:
        max_auth = max(auth_values)
        bucket_size = max(50, (max_auth // 5) + 1)

        for bucket_start in range(0, max_auth + bucket_size, bucket_size):
            bucket_end = bucket_start + bucket_size
            bucket_requests = []

            for data in minute_data.values():
                auth_ops = data['auth_ops']
                if bucket_start <= auth_ops < bucket_end:
                    bucket_requests.extend(data['requests'])

            if bucket_requests:
                status_counts = defaultdict(int)
                times = []
                for req in bucket_requests:
                    status_counts[str(req.get('status_code', 200))] += 1
                    if req.get('response_time_ms'):
                        times.append(req['response_time_ms'])

                total = sum(status_counts.values())
                status_pct = {k: round(v / total * 100, 2) for k, v in status_counts.items()}

                auth_buckets.append({
                    'auth_ops_per_minute_range': f"{bucket_start}-{bucket_end}",
                    'status_distribution_percent': status_pct,
                    'latency': calculate_percentiles(times) if times else None,
                })

    # Calculate correlation coefficients
    def calc_correlation(x, y):
        if len(x) < 2 or len(y) < 2:
            return 0
        return round(float(np.corrcoef(x, y)[0, 1]), 3) if np.std(x) > 0 and np.std(y) > 0 else 0

    # RPM vs latency correlation
    rpm_list = []
    latency_list = []
    for data in minute_data.values():
        if data['requests']:
            rpm_list.append(len(data['requests']))
            avg_latency = np.mean([r['response_time_ms'] for r in data['requests'] if r.get('response_time_ms')])
            latency_list.append(avg_latency)

    latency_vs_load_corr = calc_correlation(rpm_list, latency_list)

    # RPM vs error rate correlation
    error_rate_list = []
    for data in minute_data.values():
        if data['requests']:
            errors = sum(1 for r in data['requests'] if r.get('status_code', 200) >= 400)
            error_rate_list.append(errors / len(data['requests']) * 100)

    status_vs_load_corr = calc_correlation(rpm_list, error_rate_list) if error_rate_list else 0

    return {
        'status_vs_load': {
            'buckets': [b for b in rpm_buckets if b.get('status_distribution_percent')],
            'correlation_coefficient': -status_vs_load_corr,  # Negative because higher load = more errors
        },
        'latency_vs_load': {
            'buckets': [b for b in rpm_buckets if b.get('latency')],
            'correlation_coefficient': latency_vs_load_corr,
        },
        'latency_vs_auth_load': {
            'buckets': [b for b in auth_buckets if b.get('latency')],
            'correlation_coefficient': 0,  # Would need more data to calculate
        },
        'status_vs_auth_load': {
            'buckets': [b for b in auth_buckets if b.get('status_distribution_percent')],
            'correlation_coefficient': 0,
        },
    }

def analyze_call_chains(requests, function_calls):
    """Analyze time breakdown for call chains per endpoint"""
    # Map context_id to endpoint and x_pair relationships
    context_to_endpoint = {}
    for req in requests:
        ctx = req.get('context_id')
        if ctx:
            context_to_endpoint[ctx] = {
                'endpoint': extract_endpoint(req.get('url', '')),
                'total_time': req.get('response_time_ms', 0),
            }

    # Group function calls by context_id
    context_calls = defaultdict(list)
    for call in function_calls:
        ctx = call.get('context_id')
        if ctx:
            context_calls[ctx].append(call)

    # Analyze call breakdown per endpoint
    endpoint_breakdowns = defaultdict(lambda: {'total_times': [], 'components': defaultdict(list)})

    for ctx, endpoint_data in context_to_endpoint.items():
        endpoint = endpoint_data['endpoint']
        total_time = endpoint_data['total_time']

        if total_time > 0:
            endpoint_breakdowns[endpoint]['total_times'].append(total_time)

        calls = context_calls.get(ctx, [])
        for call in calls:
            fn = call.get('function', 'unknown')
            mark = call.get('mark', '')
            duration = call.get('duration_ms', 0)

            if duration > 0:
                # Parse mark to understand the call type
                if 'rpcIn' in mark:
                    component_name = f"{fn}:self"
                elif 'rpcOut' in mark:
                    # Extract target function from mark
                    parts = mark.split(':')
                    if len(parts) >= 2:
                        target = parts[1] if parts[0] == 'rpcOut' else parts[0]
                        component_name = f"{fn}->{target}"
                    else:
                        component_name = f"{fn}->unknown"
                else:
                    component_name = f"{fn}:{mark}"

                endpoint_breakdowns[endpoint]['components'][component_name].append(duration)

    # Calculate statistics for each endpoint
    result = {}
    for endpoint, data in endpoint_breakdowns.items():
        if data['total_times']:
            total_stats = calculate_percentiles(data['total_times'])
            if total_stats:
                components = {}
                total_mean = total_stats['mean_ms']

                for comp_name, times in data['components'].items():
                    comp_stats = calculate_percentiles(times)
                    if comp_stats and total_mean > 0:
                        comp_stats['percent_of_total'] = round(comp_stats['mean_ms'] / total_mean * 100, 1)
                        components[comp_name] = comp_stats

                result[endpoint] = {
                    'total_time': total_stats,
                    'components': components,
                }

    return {'by_endpoint': result}

def analyze_auth_chains(requests, auth_checks):
    """Analyze auth time breakdown for call chains per endpoint"""
    # Map context_id to endpoint
    context_to_endpoint = {}
    for req in requests:
        ctx = req.get('context_id')
        if ctx:
            context_to_endpoint[ctx] = extract_endpoint(req.get('url', ''))

    # Group auth checks by context_id and function
    endpoint_auth = defaultdict(lambda: {'total_times': [], 'components': defaultdict(list)})

    for auth in auth_checks:
        ctx = auth.get('context_id')
        fn = auth.get('function', 'unknown')
        duration = auth.get('duration_ms', 0)

        if ctx in context_to_endpoint and duration > 0:
            endpoint = context_to_endpoint[ctx]
            endpoint_auth[endpoint]['components'][f"{fn}:auth"].append(duration)

    # Calculate total auth time per context
    context_auth_total = defaultdict(float)
    for auth in auth_checks:
        ctx = auth.get('context_id')
        if ctx and auth.get('duration_ms'):
            context_auth_total[ctx] += auth['duration_ms']

    for ctx, total in context_auth_total.items():
        if ctx in context_to_endpoint:
            endpoint = context_to_endpoint[ctx]
            endpoint_auth[endpoint]['total_times'].append(total)

    # Calculate statistics
    result = {}
    for endpoint, data in endpoint_auth.items():
        if data['total_times']:
            total_stats = calculate_percentiles(data['total_times'])
            if total_stats:
                components = {}
                total_mean = total_stats['mean_ms'] if total_stats['mean_ms'] > 0 else 1

                for comp_name, times in data['components'].items():
                    comp_stats = calculate_percentiles(times)
                    if comp_stats:
                        comp_stats['percent_of_total'] = round(comp_stats['mean_ms'] / total_mean * 100, 1)
                        components[comp_name] = comp_stats

                result[endpoint] = {
                    'total_auth_time': total_stats,
                    'components': components,
                }

    return {'by_endpoint': result}

def generate_insights(entries, warmup_seconds=60):
    """Generate complete insights from parsed entries"""
    # Filter coldstarts
    filtered_entries, removed_count = filter_coldstarts(entries, warmup_seconds)

    # Get time range
    timestamps = []
    for req in entries['requests']:
        if req.get('timestamp'):
            try:
                ts = datetime.fromisoformat(req['timestamp'].replace('Z', '+00:00'))
                timestamps.append(ts)
            except:
                pass

    time_range = {
        'start': min(timestamps).isoformat() if timestamps else None,
        'end': max(timestamps).isoformat() if timestamps else None,
        'duration_seconds': int((max(timestamps) - min(timestamps)).total_seconds()) if len(timestamps) > 1 else 0,
    }

    def analyze_dataset(data_entries, label):
        """Analyze a dataset (all data or filtered)"""
        print(f"\nAnalyzing {label}...")

        requests = data_entries['requests']
        function_calls = data_entries['function_calls']
        auth_checks = data_entries['auth_checks']

        # Get unique endpoints and functions
        endpoints = set(extract_endpoint(r.get('url', '')) for r in requests)
        functions = set(c.get('function', '') for c in function_calls if c.get('function'))

        print(f"  Analyzing HTTP status...")
        http_status = analyze_http_status(requests)

        print(f"  Analyzing endpoints...")
        endpoint_metrics = analyze_endpoints(requests)
        endpoint_auth = analyze_endpoint_auth(requests, auth_checks)
        endpoint_metrics['auth_times'] = endpoint_auth

        print(f"  Analyzing functions...")
        function_metrics = analyze_functions(function_calls)
        function_auth = analyze_function_auth(auth_checks)
        function_metrics['auth_times'] = function_auth

        print(f"  Analyzing throughput...")
        throughput = analyze_throughput(requests, auth_checks)

        print(f"  Analyzing correlations...")
        correlations = analyze_correlations(requests, auth_checks)

        print(f"  Analyzing call chains...")
        call_chains = analyze_call_chains(requests, function_calls)

        print(f"  Analyzing auth chains...")
        auth_chains = analyze_auth_chains(requests, auth_checks)

        return {
            'overview': {
                'total_requests': len(requests),
                'total_auth_operations': len(auth_checks),
                'unique_endpoints': len(endpoints),
                'unique_functions': len(functions),
            },
            'http_status': http_status,
            'endpoints': endpoint_metrics,
            'functions': function_metrics,
            'throughput': throughput,
            'correlations': correlations,
            'call_chain_breakdown': call_chains,
            'auth_chain_breakdown': auth_chains,
        }

    # Analyze both datasets
    all_data = analyze_dataset(entries, "all data")
    without_coldstarts = analyze_dataset(filtered_entries, "data without coldstarts")

    return {
        'meta': {
            'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'total_log_entries': len(entries['requests']) + len(entries['function_calls']) + len(entries['auth_checks']),
            'total_requests': len(entries['requests']),
            'time_range': time_range,
            'coldstart_filtering': {
                'warmup_seconds': warmup_seconds,
                'coldstarts_removed': removed_count,
                'requests_after_filter': len(filtered_entries['requests']),
            },
        },
        'all_data': all_data,
        'without_coldstarts': without_coldstarts,
    }

def main():
    if len(sys.argv) < 3:
        print("Usage: python generate_insights.py <dump.json> <output_dir>")
        sys.exit(1)

    dump_path = sys.argv[1]
    output_dir = sys.argv[2]

    if not os.path.exists(dump_path):
        print(f"Error: {dump_path} not found")
        sys.exit(1)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Load and parse data
    data = load_dump(dump_path)
    entries = parse_entries(data)

    # Generate insights
    print("\nGenerating insights...")
    insights = generate_insights(entries)

    # Write output
    output_path = os.path.join(output_dir, 'insights.json')
    with open(output_path, 'w') as f:
        json.dump(insights, f, indent=2)

    print(f"\nInsights saved to: {output_path}")
    print(f"  Total requests analyzed: {insights['meta']['total_requests']}")
    print(f"  Coldstarts filtered: {insights['meta']['coldstart_filtering']['coldstarts_removed']}")

if __name__ == '__main__':
    main()