"""
Parser for pricing/pricing.json files.

Handles both FaaS (Lambda) and ECS (Fargate) pricing structures.
"""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field


@dataclass
class PricingMeta:
    """Pricing metadata."""
    region: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: Optional[float] = None
    duration_hours: Optional[float] = None
    collected_at: Optional[datetime] = None


@dataclass
class LambdaPricing:
    """Lambda pricing totals."""
    total_invocations: Optional[int] = None
    total_duration_ms: Optional[float] = None
    total_gb_seconds: Optional[float] = None
    memory_gb: Optional[float] = None
    request_cost: Optional[Decimal] = None
    compute_cost: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None


@dataclass
class LambdaFunctionPricing:
    """Per-function Lambda pricing."""
    function_name: str
    invocations: Optional[int] = None
    duration_ms: Optional[float] = None
    gb_seconds: Optional[float] = None
    request_cost: Optional[Decimal] = None
    compute_cost: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None


@dataclass
class ApiGatewayPricing:
    """API Gateway pricing."""
    total_requests: Optional[int] = None
    cost: Optional[Decimal] = None
    rate_per_million: Optional[Decimal] = None


@dataclass
class FargatePricing:
    """Fargate totals."""
    task_cpu: Optional[int] = None
    task_memory_mb: Optional[int] = None
    total_cost: Optional[Decimal] = None
    rate_vcpu_per_hour: Optional[Decimal] = None
    rate_memory_gb_per_hour: Optional[Decimal] = None


@dataclass
class FargateServicePricing:
    """Per-service Fargate pricing."""
    service_name: str
    task_cpu: Optional[int] = None
    task_memory_mb: Optional[int] = None
    avg_running_tasks: Optional[float] = None
    vcpu_hours: Optional[float] = None
    memory_gb_hours: Optional[float] = None
    vcpu_cost: Optional[Decimal] = None
    memory_cost: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None


@dataclass
class AlbPricing:
    """ALB pricing."""
    duration_hours: Optional[float] = None
    hourly_cost: Optional[Decimal] = None
    estimated_lcu: Optional[float] = None
    lcu_cost: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None
    rate_hourly: Optional[Decimal] = None
    rate_lcu_per_hour: Optional[Decimal] = None


@dataclass
class RedisPricing:
    """Redis pricing."""
    instance_type: Optional[str] = None
    duration_hours: Optional[float] = None
    hourly_rate: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None


@dataclass
class CognitoPricing:
    """Cognito pricing."""
    mau: Optional[int] = None
    cost: Optional[Decimal] = None
    rate_first_50k: Optional[Decimal] = None
    rate_next_50k: Optional[Decimal] = None
    rate_next_900k: Optional[Decimal] = None
    rate_over_1m: Optional[Decimal] = None
    note: Optional[str] = None


@dataclass
class PricingData:
    """Complete pricing data from pricing.json."""
    meta: PricingMeta = field(default_factory=PricingMeta)
    lambda_pricing: Optional[LambdaPricing] = None
    lambda_functions: List[LambdaFunctionPricing] = field(default_factory=list)
    api_gateway: Optional[ApiGatewayPricing] = None
    fargate: Optional[FargatePricing] = None
    fargate_services: List[FargateServicePricing] = field(default_factory=list)
    alb: Optional[AlbPricing] = None
    redis: Optional[RedisPricing] = None
    cognito: Optional[CognitoPricing] = None


def _to_decimal(value) -> Optional[Decimal]:
    """Convert value to Decimal safely."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return None


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    """Parse ISO datetime string."""
    if not value:
        return None
    try:
        # Handle various ISO formats
        value = value.replace('Z', '+00:00')
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_pricing(path: Path) -> Optional[PricingData]:
    """
    Parse pricing/pricing.json file.

    Args:
        path: Path to pricing.json

    Returns:
        PricingData or None if file doesn't exist
    """
    if not path.exists():
        return None

    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    result = PricingData()

    # Parse metadata
    meta = data.get('meta', {})
    result.meta = PricingMeta(
        region=meta.get('region'),
        start_time=_parse_iso_datetime(meta.get('start_time')),
        end_time=_parse_iso_datetime(meta.get('end_time')),
        duration_minutes=meta.get('duration_minutes'),
        duration_hours=meta.get('duration_hours'),
        collected_at=_parse_iso_datetime(meta.get('collected_at')),
    )

    resources = data.get('resources', {})

    # Parse Lambda pricing
    if 'lambda' in resources:
        lam = resources['lambda']
        result.lambda_pricing = LambdaPricing(
            total_invocations=lam.get('total_invocations'),
            total_duration_ms=lam.get('total_duration_ms'),
            total_gb_seconds=lam.get('gb_seconds'),
            memory_gb=lam.get('memory_gb'),
            request_cost=_to_decimal(lam.get('request_cost')),
            compute_cost=_to_decimal(lam.get('compute_cost')),
            total_cost=_to_decimal(lam.get('total_cost')),
        )

        # Parse per-function pricing
        per_function = lam.get('per_function', {})
        for fn_name, fn_data in per_function.items():
            result.lambda_functions.append(LambdaFunctionPricing(
                function_name=fn_name,
                invocations=fn_data.get('invocations'),
                duration_ms=fn_data.get('duration_ms'),
                gb_seconds=fn_data.get('gb_seconds'),
                request_cost=_to_decimal(fn_data.get('request_cost')),
                compute_cost=_to_decimal(fn_data.get('compute_cost')),
                total_cost=_to_decimal(fn_data.get('total_cost')),
            ))

    # Parse API Gateway pricing
    if 'api_gateway' in resources:
        api = resources['api_gateway']
        pricing_used = api.get('pricing_used', {})
        result.api_gateway = ApiGatewayPricing(
            total_requests=api.get('total_requests'),
            cost=_to_decimal(api.get('cost')),
            rate_per_million=_to_decimal(pricing_used.get('perMillionRequests')),
        )

    # Parse Fargate pricing
    if 'fargate' in resources:
        fg = resources['fargate']
        pricing_used = fg.get('pricing_used', {})
        result.fargate = FargatePricing(
            task_cpu=fg.get('task_cpu'),
            task_memory_mb=fg.get('task_memory_mb'),
            total_cost=_to_decimal(fg.get('total_cost')),
            rate_vcpu_per_hour=_to_decimal(pricing_used.get('vCpuPerHour')),
            rate_memory_gb_per_hour=_to_decimal(pricing_used.get('memoryGBPerHour')),
        )

        # Parse per-service pricing
        per_service = fg.get('per_service', {})
        for svc_name, svc_data in per_service.items():
            result.fargate_services.append(FargateServicePricing(
                service_name=svc_name,
                task_cpu=svc_data.get('task_cpu'),
                task_memory_mb=svc_data.get('task_memory_mb'),
                avg_running_tasks=svc_data.get('avg_running_tasks'),
                vcpu_hours=svc_data.get('vcpu_hours'),
                memory_gb_hours=svc_data.get('memory_gb_hours'),
                vcpu_cost=_to_decimal(svc_data.get('vcpu_cost')),
                memory_cost=_to_decimal(svc_data.get('memory_cost')),
                total_cost=_to_decimal(svc_data.get('total_cost')),
            ))

    # Parse ALB pricing
    if 'alb' in resources:
        alb = resources['alb']
        pricing_used = alb.get('pricing_used', {})
        result.alb = AlbPricing(
            duration_hours=alb.get('duration_hours'),
            hourly_cost=_to_decimal(alb.get('hourly_cost')),
            estimated_lcu=alb.get('estimated_lcu'),
            lcu_cost=_to_decimal(alb.get('lcu_cost')),
            total_cost=_to_decimal(alb.get('total_cost')),
            rate_hourly=_to_decimal(pricing_used.get('hourlyRate')),
            rate_lcu_per_hour=_to_decimal(pricing_used.get('lcuPerHour')),
        )

    # Parse Redis pricing
    if 'redis' in resources:
        redis = resources['redis']
        result.redis = RedisPricing(
            instance_type=redis.get('instance_type'),
            duration_hours=redis.get('duration_hours'),
            hourly_rate=_to_decimal(redis.get('hourly_rate')),
            total_cost=_to_decimal(redis.get('total_cost')),
        )

    # Parse Cognito pricing
    if 'cognito' in resources:
        cog = resources['cognito']
        pricing_used = cog.get('pricing_used', {})
        result.cognito = CognitoPricing(
            mau=cog.get('mau'),
            cost=_to_decimal(cog.get('cost')),
            rate_first_50k=_to_decimal(pricing_used.get('mauFirst50k')),
            rate_next_50k=_to_decimal(pricing_used.get('mauNext50k')),
            rate_next_900k=_to_decimal(pricing_used.get('mauNext900k')),
            rate_over_1m=_to_decimal(pricing_used.get('mauOver1m')),
            note=cog.get('note'),
        )

    return result