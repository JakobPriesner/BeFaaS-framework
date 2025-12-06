"""
Data extraction and analysis functions for BeFaaS plotting.
"""

from datetime import timedelta
from collections import defaultdict
import numpy as np

from .constants import WARMUP_SECONDS
from .utils import parse_datetime, categorize_endpoint, is_auth_endpoint


def extract_detailed_request_data(data):
    """Extract detailed request data with timestamps for advanced analysis"""
    requests = {}
    coldstart_contexts = set()

    for entry in data:
        if '__logentry__' not in entry:
            continue
        log = entry['__logentry__']
        event = log.get('data', {}).get('event', {})

        if event.get('coldstart'):
            ctx = event.get('contextId', '')
            if ctx:
                coldstart_contexts.add(ctx)

        if 'contextId' not in event:
            continue

        ctx_id = event['contextId']
        ts = log.get('data', {}).get('timestamp', 0)
        req_type = event.get('type', '')
        url = event.get('url', '')
        xpair = event.get('xPair', '')
        log_ts = parse_datetime(log.get('timestamp'))

        if ctx_id not in requests:
            requests[ctx_id] = {'xpair': xpair}

        if req_type == 'before':
            requests[ctx_id]['before'] = ts
            requests[ctx_id]['url'] = url
            requests[ctx_id]['start_time'] = log_ts
        elif req_type == 'after':
            requests[ctx_id]['after'] = ts
            requests[ctx_id]['end_time'] = log_ts

    processed = []
    for ctx_id, req in requests.items():
        if 'before' in req and 'after' in req:
            duration = req['after'] - req['before']
            if duration > 0 and duration < 60000:
                url = req.get('url', '')
                parts = url.rstrip('/').split('/')
                endpoint = parts[-1] if parts else 'unknown'

                processed.append({
                    'context_id': ctx_id,
                    'duration': duration,
                    'url': url,
                    'endpoint': endpoint,
                    'start_time': req.get('start_time'),
                    'end_time': req.get('end_time'),
                    'is_coldstart': ctx_id in coldstart_contexts,
                    'xpair': req.get('xpair', ''),
                    'is_auth': is_auth_endpoint(endpoint)
                })

    return processed


def filter_warmup_from_endpoint_times(data, endpoint_times, warmup_seconds=WARMUP_SECONDS):
    """
    Filter endpoint_times dict to exclude warmup period.
    Returns new dict with filtered times per endpoint.
    """
    requests = extract_detailed_request_data(data)
    if not requests:
        return endpoint_times

    timed_requests = [r for r in requests if r.get('start_time')]
    if not timed_requests:
        return endpoint_times

    sorted_reqs = sorted(timed_requests, key=lambda x: x['start_time'])
    start_time = sorted_reqs[0]['start_time']
    warmup_end = start_time + timedelta(seconds=warmup_seconds)

    filtered_endpoint_times = defaultdict(list)
    for req in requests:
        if req.get('start_time') and req['start_time'] >= warmup_end:
            endpoint = req['endpoint']
            filtered_endpoint_times[endpoint].append(req['duration'])

    return dict(filtered_endpoint_times)


def filter_warmup_from_response_times(data, warmup_seconds=WARMUP_SECONDS):
    """
    Filter response times to exclude warmup period.
    Returns tuple: (filtered_times, excluded_count)
    """
    requests = extract_detailed_request_data(data)
    if not requests:
        return [], 0

    timed_requests = [r for r in requests if r.get('start_time')]
    if not timed_requests:
        return [r['duration'] for r in requests], 0

    sorted_reqs = sorted(timed_requests, key=lambda x: x['start_time'])
    start_time = sorted_reqs[0]['start_time']
    warmup_end = start_time + timedelta(seconds=warmup_seconds)

    warm_requests = [r for r in requests
                     if r.get('start_time') and r['start_time'] >= warmup_end]

    excluded_count = len(requests) - len(warm_requests)
    return [r['duration'] for r in warm_requests], excluded_count


def analyze_response_times_from_pairs(data):
    """Analyze response times by matching before/after request pairs"""
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

    response_times = []
    endpoint_times = defaultdict(list)
    category_times = defaultdict(list)

    for ctx_id, req in requests.items():
        if 'before' in req and 'after' in req:
            duration = req['after'] - req['before']
            if duration > 0 and duration < 60000:
                response_times.append(duration)

                url = req.get('url', '')
                parts = url.rstrip('/').split('/')
                endpoint = parts[-1] if parts else 'unknown'

                if len(parts) >= 2 and parts[-2] == 'product':
                    endpoint = parts[-1]

                endpoint_times[endpoint].append(duration)

                category = categorize_endpoint(endpoint)
                category_times[category].append(duration)

    return response_times, endpoint_times, category_times


def analyze_response_times(data):
    """Analyze response times from logs (performance marks)"""
    response_times = []
    function_times = defaultdict(list)

    start_marks = {}

    for entry in data:
        if '__logentry__' not in entry:
            continue

        log = entry['__logentry__']
        event_data = log.get('data', {}).get('event', {})
        timestamp_data = log.get('data', {}).get('now', 0)

        if 'perf' in event_data:
            perf = event_data['perf']
            mark = perf.get('mark', '')
            context_id = event_data.get('contextId', '')

            if mark.startswith('measure:') and perf.get('duration', 0) > 0:
                duration_ms = perf['duration']
                response_times.append(duration_ms)

                parts = mark.split(':')
                if len(parts) >= 2:
                    func_name = ':'.join(parts[1:])
                    function_times[func_name].append(duration_ms)

            elif mark.startswith('start:rpcOut:') or mark.startswith('start:rpcIn:'):
                mark_id = mark.replace('start:', '')
                start_marks[(context_id, mark_id)] = timestamp_data

            elif mark.startswith('end:rpcOut:') or mark.startswith('end:rpcIn:'):
                mark_id = mark.replace('end:', '')
                key = (context_id, mark_id)

                if key in start_marks:
                    duration_ms = timestamp_data - start_marks[key]

                    if duration_ms > 0:
                        response_times.append(duration_ms)

                        parts = mark_id.split(':')
                        if len(parts) >= 2:
                            func_name = parts[1]
                            function_times[func_name].append(duration_ms)

                    del start_marks[key]

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

        if 'contextId' in event_data:
            function_calls[fn_name] += 1

        if event_data.get('coldstart'):
            coldstarts[fn_name] += 1

        if 'perf' in event_data:
            perf = event_data['perf']
            mark = perf.get('mark', '')

            if mark.startswith('start:rpcOut:'):
                parts = mark.split(':')
                if len(parts) >= 3:
                    rpc_func = parts[2]
                    rpc_calls[rpc_func] += 1

            elif mark.startswith('start:get:') or mark.startswith('start:post:'):
                endpoint = mark.replace('start:', '')
                endpoint_calls[endpoint] += 1

    return function_calls, coldstarts, rpc_calls, endpoint_calls


def analyze_auth_requests(data):
    """Analyze authentication-related requests"""
    auth_endpoints = ['register', 'setUser', 'login', 'logout', 'auth', 'token', 'verify']
    auth_times = defaultdict(list)

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
                url = req.get('url', '')
                endpoint = url.rstrip('/').split('/')[-1].lower()

                is_auth = any(auth_ep in endpoint for auth_ep in auth_endpoints)
                if is_auth:
                    auth_times['auth'].append(duration)
                else:
                    auth_times['non-auth'].append(duration)

    return auth_times


def analyze_function_auth_delays(data):
    """
    Analyze auth delays per function from RPC call data.
    Returns dict mapping function name to list of measured delays.
    """
    function_times = defaultdict(list)

    start_marks = {}

    for entry in data:
        if '__logentry__' not in entry:
            continue

        log = entry['__logentry__']
        event_data = log.get('data', {}).get('event', {})
        timestamp = log.get('data', {}).get('now', 0)

        if 'perf' in event_data:
            perf = event_data['perf']
            mark = perf.get('mark', '')
            context_id = event_data.get('contextId', '')

            if mark.startswith('start:rpcOut:'):
                parts = mark.split(':')
                if len(parts) >= 3:
                    call_target = parts[2]
                    start_marks[(context_id, call_target)] = timestamp

            elif mark.startswith('end:rpcOut:'):
                parts = mark.split(':')
                if len(parts) >= 3:
                    call_target = parts[2]
                    key = (context_id, call_target)
                    if key in start_marks:
                        duration = timestamp - start_marks[key]
                        if duration > 0:
                            function_times[call_target].append(duration)
                        del start_marks[key]

            elif mark.startswith('measure:') and perf.get('duration', 0) > 0:
                duration = perf['duration']
                parts = mark.split(':')
                if len(parts) >= 2:
                    func_part = parts[1]
                    if '/' in func_part:
                        func_name = func_part.split('/')[-1]
                    else:
                        func_name = func_part
                    function_times[func_name].append(duration)

    return function_times


def analyze_load_over_time(data, time_window_seconds=5):
    """
    Analyze request rate and response times over time windows.
    Returns list of dicts with: window_start, request_count, mean_ms, p50_ms, p95_ms, p99_ms
    """
    requests = extract_detailed_request_data(data)

    if not requests:
        return []

    timed_requests = [r for r in requests if r['start_time']]
    if not timed_requests:
        return []

    timed_requests.sort(key=lambda x: x['start_time'])

    start_time = timed_requests[0]['start_time']
    end_time = timed_requests[-1]['start_time']

    windows = []
    current_window_start = start_time

    while current_window_start < end_time:
        window_end = current_window_start + timedelta(seconds=time_window_seconds)

        window_requests = [r for r in timed_requests
                         if current_window_start <= r['start_time'] < window_end]

        if window_requests:
            durations = [r['duration'] for r in window_requests]
            auth_requests = [r for r in window_requests if r['is_auth']]
            auth_durations = [r['duration'] for r in auth_requests]

            window_data = {
                'window_start': (current_window_start - start_time).total_seconds(),
                'window_end': (window_end - start_time).total_seconds(),
                'request_count': len(window_requests),
                'requests_per_second': len(window_requests) / time_window_seconds,
                'mean_ms': np.mean(durations),
                'median_ms': np.median(durations),
                'p50_ms': np.percentile(durations, 50),
                'p75_ms': np.percentile(durations, 75),
                'p90_ms': np.percentile(durations, 90),
                'p95_ms': np.percentile(durations, 95),
                'p99_ms': np.percentile(durations, 99),
                'std_ms': np.std(durations),
                'min_ms': np.min(durations),
                'max_ms': np.max(durations),
                'auth_request_count': len(auth_requests),
                'auth_mean_ms': np.mean(auth_durations) if auth_durations else 0,
                'auth_p95_ms': np.percentile(auth_durations, 95) if len(auth_durations) >= 5 else 0,
            }
            windows.append(window_data)

        current_window_start = window_end

    return windows