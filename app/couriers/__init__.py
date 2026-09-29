"""Courier Abstraction Layer package.

Exports:
- CourierAdapter: Abstract base class interface
- CourierOrderResult, CourierTrackingResult, CourierCancelResult: Standardized DTOs
- CourierRegistry: Dynamic registry class
- courier_registry: Default singleton registry instance
- MockCourierAdapter: Offline deterministic test courier adapter
- UrbaneboltAdapter: Real UrbaneBolt logistics adapter
- ResilientHttpClient: Resilient HTTP client with retry and token refresh
"""

from app.couriers.base import (
    AwaitableDTO,
    CourierAdapter,
    CourierCancelResult,
    CourierOrderResult,
    CourierTrackingResult,
)
from app.couriers.client import ResilientHttpClient
from app.couriers.mock import MockCourierAdapter, MockSimulationMode
from app.couriers.registry import (
    CourierRegistry,
    courier_registry,
    register_default_couriers,
)
from app.couriers.urbanebolt import UrbaneboltAdapter

__all__ = [
    "AwaitableDTO",
    "CourierAdapter",
    "CourierCancelResult",
    "CourierOrderResult",
    "CourierRegistry",
    "CourierTrackingResult",
    "MockCourierAdapter",
    "MockSimulationMode",
    "ResilientHttpClient",
    "UrbaneboltAdapter",
    "courier_registry",
    "register_default_couriers",
]
