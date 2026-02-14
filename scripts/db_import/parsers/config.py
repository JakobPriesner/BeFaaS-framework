"""
Parsers for configuration files.

Handles:
- hardware_config.json
- benchmark_configuration.json
- experiment_start_time.txt
- error_description.md
"""

import json
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field


@dataclass
class HardwareConfig:
    """Hardware configuration from hardware_config.json."""
    architecture: Optional[str] = None
    ram_in_mb: int = 0
    cpu_in_vcpu: Optional[float] = None
    bundle_mode: Optional[str] = None
    datetime_str: Optional[str] = None
    password_hash_algorithm: Optional[str] = None
    jwt_sign_algorithm: Optional[str] = None
    # Per-service scaling rules (list of ScalingRuleData)
    scaling_rules: list = field(default_factory=list)


@dataclass
class ScalingRuleData:
    """Per-service scaling rule configuration."""
    service_name: str
    rule_type: str
    target_value: int
    min_capacity: Optional[int] = None
    max_capacity: Optional[int] = None
    cpu_units: Optional[int] = None
    memory_mb: Optional[int] = None
    scale_in_cooldown_sec: Optional[int] = None
    scale_out_cooldown_sec: Optional[int] = None


def _parse_rule(rule_data: dict, rule_type: str) -> dict:
    """Extract common fields from a scaling rule dict."""
    # Handle both naming conventions (Terraform output uses _sec, legacy uses _seconds)
    return {
        'target_value': rule_data.get('target_value', 0) or rule_data.get('target_percent', 0) or rule_data.get('target_requests_per_minute', 0),
        'scale_in_cooldown_sec': rule_data.get('scale_in_cooldown_sec') or rule_data.get('scale_in_cooldown_seconds'),
        'scale_out_cooldown_sec': rule_data.get('scale_out_cooldown_sec') or rule_data.get('scale_out_cooldown_seconds') or rule_data.get('scalde_out_cooldown_seconds'),
    }


def parse_hardware_config(path: Path) -> Optional[HardwareConfig]:
    """
    Parse hardware_config.json file.

    Supports two formats:

    New format (per-service, from Terraform output):
        {
            "services": {
                "monolith": {
                    "cpu_units": 512, "memory_mb": 1024,
                    "min_capacity": 2, "max_capacity": 30,
                    "scaling_rules": {
                        "request_count": { "target_value": 1800, ... }
                    }
                }
            }
        }

    Legacy format (per-experiment):
        {
            "scaling_rules": {
                "cpu": { "target_percent": 70, ... },
                "request_count": { "target_requests_per_minute": 2500, ... }
            }
        }

    Args:
        path: Path to hardware_config.json

    Returns:
        HardwareConfig or None if file doesn't exist
    """
    if not path.exists():
        return None

    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    config = HardwareConfig(
        architecture=data.get('architecture'),
        ram_in_mb=data.get('ram_in_mb', 0),
        cpu_in_vcpu=data.get('cpu_in_vcpu'),
        bundle_mode=data.get('bundle_mode'),
        datetime_str=data.get('datetime'),
        password_hash_algorithm=data.get('password_hash_algorithm'),
        jwt_sign_algorithm=data.get('jwt_sign_algorithm'),
    )

    # New format: per-service scaling rules under "services" key
    services_data = data.get('services', {})
    if services_data:
        for service_name, svc in services_data.items():
            svc_cpu = svc.get('cpu_units')
            svc_mem = svc.get('memory_mb')
            svc_min = svc.get('min_capacity')
            svc_max = svc.get('max_capacity')

            rules = svc.get('scaling_rules', {})
            for rule_type, rule_data in rules.items():
                parsed = _parse_rule(rule_data, rule_type)
                config.scaling_rules.append(ScalingRuleData(
                    service_name=service_name,
                    rule_type=rule_type,
                    target_value=parsed['target_value'],
                    min_capacity=svc_min,
                    max_capacity=svc_max,
                    cpu_units=svc_cpu,
                    memory_mb=svc_mem,
                    scale_in_cooldown_sec=parsed['scale_in_cooldown_sec'],
                    scale_out_cooldown_sec=parsed['scale_out_cooldown_sec'],
                ))
        return config

    # Legacy format: flat scaling_rules (per-experiment, no service_name)
    # Infer service_name from architecture
    scaling_rules_data = data.get('scaling_rules', {})
    if scaling_rules_data:
        arch = data.get('architecture', '')
        service_name = 'monolith' if arch == 'monolith' else 'unknown'
        min_cap = data.get('min_capacity')
        max_cap = data.get('max_capacity')

        for rule_type in ('cpu', 'request_count'):
            if rule_type in scaling_rules_data:
                parsed = _parse_rule(scaling_rules_data[rule_type], rule_type)
                config.scaling_rules.append(ScalingRuleData(
                    service_name=service_name,
                    rule_type=rule_type,
                    target_value=parsed['target_value'],
                    min_capacity=min_cap,
                    max_capacity=max_cap,
                    scale_in_cooldown_sec=parsed['scale_in_cooldown_sec'],
                    scale_out_cooldown_sec=parsed['scale_out_cooldown_sec'],
                ))

    return config


@dataclass
class BenchmarkConfig:
    """Benchmark configuration from benchmark_configuration.json."""
    http_timeout_seconds: Optional[int] = None


def parse_benchmark_config(path: Path) -> Optional[BenchmarkConfig]:
    """
    Parse benchmark_configuration.json file.

    Args:
        path: Path to benchmark_configuration.json

    Returns:
        BenchmarkConfig or None if file doesn't exist
    """
    if not path.exists():
        return None

    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    return BenchmarkConfig(
        http_timeout_seconds=data.get('http_timeout_in_seconds'),
    )


@dataclass
class ExperimentStartTime:
    """Experiment start time data."""
    timestamp_ms: int
    iso_string: Optional[str] = None


def parse_experiment_start_time(path: Path) -> Optional[ExperimentStartTime]:
    """
    Parse experiment_start_time.txt file.

    File format:
        1768079649130
        2026-01-10T21:14:09.130Z

    Args:
        path: Path to experiment_start_time.txt

    Returns:
        ExperimentStartTime or None if file doesn't exist
    """
    if not path.exists():
        return None

    try:
        with open(path, 'r') as f:
            lines = f.readlines()
    except IOError:
        return None

    if not lines:
        return None

    try:
        timestamp_ms = int(lines[0].strip())
        iso_string = lines[1].strip() if len(lines) > 1 else None
        return ExperimentStartTime(timestamp_ms=timestamp_ms, iso_string=iso_string)
    except (ValueError, IndexError):
        return None


def parse_error_description(path: Path) -> Optional[str]:
    """
    Parse error_description.md file.

    Args:
        path: Path to error_description.md

    Returns:
        Error description text or None if file doesn't exist or is empty
    """
    if not path.exists():
        return None

    try:
        with open(path, 'r') as f:
            content = f.read().strip()
        return content if content else None
    except IOError:
        return None