#!/usr/bin/env python3
"""
Parse BEFAAS log entries from artillery.log and generate dump.json
This bypasses the befaas/analysis Docker container when Docker is unresponsive.
"""

import json
import sys
import os
from datetime import datetime

def parse_befaas_line(line):
    """Parse a BEFAAS log line and return the JSON data."""
    if not line.startswith('BEFAAS'):
        return None

    try:
        json_str = line[6:]  # Remove 'BEFAAS' prefix
        data = json.loads(json_str)

        # Convert to befaas dump format
        timestamp_ms = data.get('timestamp', 0)
        timestamp_dt = datetime.utcfromtimestamp(timestamp_ms / 1000.0)

        return {
            "__logentry__": {
                "timestamp": {"__datetime__": timestamp_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]},
                "data": data,
                "platform": "artillery"
            }
        }
    except json.JSONDecodeError:
        return None

def parse_logs(logs_dir, output_dir):
    """Parse all log files in logs_dir and write dump.json to output_dir."""
    os.makedirs(output_dir, exist_ok=True)

    entries = []
    artillery_log = os.path.join(logs_dir, 'artillery.log')

    if not os.path.exists(artillery_log):
        print(f"Error: {artillery_log} not found")
        return

    print(f"Parsing {artillery_log}...")
    line_count = 0
    entry_count = 0

    with open(artillery_log, 'r') as f:
        for line in f:
            line_count += 1
            if line_count % 100000 == 0:
                print(f"  Processed {line_count} lines, found {entry_count} entries...")

            entry = parse_befaas_line(line.strip())
            if entry:
                entries.append(entry)
                entry_count += 1

    print(f"Parsed {entry_count} BEFAAS entries from {line_count} lines")

    output_file = os.path.join(output_dir, 'dump.json')
    print(f"Writing to {output_file}...")

    with open(output_file, 'w') as f:
        json.dump(entries, f)

    print(f"Done! Created {output_file} with {len(entries)} entries")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python parse_befaas_logs.py <logs_dir> <output_dir>")
        sys.exit(1)

    logs_dir = sys.argv[1]
    output_dir = sys.argv[2]
    parse_logs(logs_dir, output_dir)
