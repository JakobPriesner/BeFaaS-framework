"""
BeFaaS Benchmark Database Import Package

This package provides tools for importing BeFaaS benchmark results into a database.

Usage:
    # As a module
    python -m db_import init
    python -m db_import import-all scripts/results/webservice

    # As a library
    from db_import.schema import Experiment, Request
    from db_import.importer import import_experiment
"""

from .schema import (
    Base,
    Experiment,
    ScalingRule,
    Phase,
    Request,
    LambdaExecution,
    HandlerEvent,
    ContainerStart,
    RpcCall,
    Pricing,
    PricingComponent,
    MetricsEcs,
    MetricsAlb,
    create_tables,
    drop_tables,
)
from .importer import (
    import_experiment,
    import_all_experiments,
    init_database,
)

__version__ = "1.0.0"

__all__ = [
    # Schema
    "Base",
    "Experiment",
    "ScalingRule",
    "Phase",
    "Request",
    "LambdaExecution",
    "HandlerEvent",
    "ContainerStart",
    "RpcCall",
    "Pricing",
    "PricingComponent",
    "MetricsEcs",
    "MetricsAlb",
    "create_tables",
    "drop_tables",
    # Importer
    "import_experiment",
    "import_all_experiments",
    "init_database",
]