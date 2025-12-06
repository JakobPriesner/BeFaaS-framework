"""
Utility functions for BeFaaS plotting.
"""

from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
import matplotlib.pyplot as plt

from .constants import WARMUP_SECONDS, ENDPOINT_CATEGORIES, CATEGORY_COLORS


def parse_datetime(dt_dict):
    """Parse datetime from dict format"""
    if isinstance(dt_dict, dict) and '__datetime__' in dt_dict:
        return datetime.fromisoformat(dt_dict['__datetime__'])
    return None


def categorize_endpoint(endpoint):
    """Categorize an endpoint into a functional group"""
    endpoint_lower = endpoint.lower()
    for category, endpoints in ENDPOINT_CATEGORIES.items():
        for ep in endpoints:
            if ep.lower() in endpoint_lower:
                return category
    return 'Other'


def is_auth_endpoint(endpoint):
    """Check if endpoint is authentication-related"""
    auth_endpoints = ['register', 'setuser', 'login', 'logout', 'auth', 'token', 'verify']
    return any(auth_ep in endpoint.lower() for auth_ep in auth_endpoints)


def is_write_operation(endpoint, url=''):
    """Determine if endpoint is a write operation"""
    write_endpoints = ['register', 'setuser', 'addcartitem', 'checkout', 'updatecart',
                       'removecartitem', 'login', 'logout', 'post', 'create', 'update', 'delete']
    return any(w in endpoint.lower() for w in write_endpoints)


def add_warmup_excluded_indicator(ax, warmup_seconds=WARMUP_SECONDS):
    """
    Add a red circle indicator to a plot showing warmup period was excluded.
    Places indicator in upper-right corner of the plot.
    """
    circle = plt.Circle((0.92, 0.92), 0.04, transform=ax.transAxes,
                        facecolor='#e74c3c', edgecolor='darkred', linewidth=2,
                        alpha=0.9, zorder=10)
    ax.add_patch(circle)
    ax.text(0.92, 0.92, f'{warmup_seconds}s', transform=ax.transAxes,
            ha='center', va='center', fontsize=8, fontweight='bold',
            color='white', zorder=11)
    ax.text(0.92, 0.85, 'warmup\nexcluded', transform=ax.transAxes,
            ha='center', va='top', fontsize=7, color='#e74c3c',
            fontweight='bold', zorder=11)


def filter_warmup_from_detailed_requests(requests, warmup_seconds=WARMUP_SECONDS):
    """
    Filter out requests from the warmup period.
    Returns filtered list of request dicts.
    """
    if not requests:
        return []

    timed_requests = [r for r in requests if r.get('start_time')]
    if not timed_requests:
        return requests

    sorted_reqs = sorted(timed_requests, key=lambda x: x['start_time'])
    start_time = sorted_reqs[0]['start_time']
    warmup_end = start_time + timedelta(seconds=warmup_seconds)

    filtered = [r for r in requests
                if not r.get('start_time') or r['start_time'] >= warmup_end]

    excluded_count = len(requests) - len(filtered)
    if excluded_count > 0:
        print(f"    (Excluded {excluded_count} requests from {warmup_seconds}s warmup period)")

    return filtered


def get_category_colors():
    """Return the category color mapping"""
    return CATEGORY_COLORS.copy()