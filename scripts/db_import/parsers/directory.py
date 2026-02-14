"""
Parser for extracting metadata from experiment directory names.

Directory format: {architecture}_{auth_strategy}_{hardware_spec}_{timestamp}
Examples:
- faas_none_512MB_minimal_2026-01-09T22-48-43-424Z
- microservices_service-integrated_1024cpu_2048MB_2026-01-30T08-52-51-228Z
- monolith_none_1024cpu_2048MB_2026-01-30T11-27-16-884Z
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class DirectoryMetadata:
    """Metadata extracted from directory name."""
    name: str
    architecture: str
    auth_strategy: str
    ram_in_mb: int
    cpu_in_vcpu: Optional[float]
    run_timestamp: Optional[datetime]


def parse_directory_name(path: Path) -> DirectoryMetadata:
    """
    Parse experiment directory name to extract metadata.

    Args:
        path: Path to experiment directory

    Returns:
        DirectoryMetadata with extracted values
    """
    name = path.name

    # Pattern to match directory name
    # Format: {architecture}_{auth_strategy}_{hardware}_{timestamp}
    # Hardware can be: 512MB, 256MB (FaaS) or 1024cpu_2048MB (ECS)

    # Extract timestamp (always at the end)
    timestamp_pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z)$'
    timestamp_match = re.search(timestamp_pattern, name)

    run_timestamp = None
    if timestamp_match:
        ts_str = timestamp_match.group(1)
        # Convert from 2026-01-09T22-48-43-424Z to datetime
        try:
            # Replace dashes in time portion with colons
            ts_normalized = ts_str.replace('T', ' ').replace('Z', '')
            parts = ts_normalized.split(' ')
            date_part = parts[0]
            time_parts = parts[1].split('-')
            if len(time_parts) >= 3:
                time_str = f"{time_parts[0]}:{time_parts[1]}:{time_parts[2]}"
                ms = time_parts[3] if len(time_parts) > 3 else "000"
                run_timestamp = datetime.strptime(f"{date_part} {time_str}.{ms}", "%Y-%m-%d %H:%M:%S.%f")
        except (ValueError, IndexError):
            pass

    # Remove timestamp for further parsing
    name_without_ts = re.sub(timestamp_pattern, '', name).rstrip('_')

    # Parse architecture (first part)
    parts = name_without_ts.split('_')
    architecture = parts[0] if parts else "unknown"

    # Parse auth strategy
    # Known auth strategies: none, service-integrated, service-integrated-manual
    auth_strategy = "unknown"
    if '_none_' in name_without_ts:
        auth_strategy = "none"
    elif '_service-integrated-manual_' in name_without_ts:
        auth_strategy = "service-integrated-manual"
    elif '_service-integrated_' in name_without_ts:
        auth_strategy = "service-integrated"

    # Parse hardware: RAM and CPU
    ram_in_mb = 0
    cpu_in_vcpu = None

    # Look for RAM pattern (e.g., 512MB, 2048MB)
    ram_match = re.search(r'(\d+)MB', name_without_ts)
    if ram_match:
        ram_in_mb = int(ram_match.group(1))

    # Look for CPU pattern (e.g., 1024cpu)
    cpu_match = re.search(r'(\d+)cpu', name_without_ts)
    if cpu_match:
        cpu_units = int(cpu_match.group(1))
        cpu_in_vcpu = cpu_units / 1024.0

    return DirectoryMetadata(
        name=path.name,
        architecture=architecture,
        auth_strategy=auth_strategy,
        ram_in_mb=ram_in_mb,
        cpu_in_vcpu=cpu_in_vcpu,
        run_timestamp=run_timestamp,
    )