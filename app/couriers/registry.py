"""Dynamic Courier Registry implementing the Adapter lookup without if/elif branching."""

import logging
from typing import Optional

from app.couriers.base import CourierAdapter
from app.exceptions import UnsupportedCourierError

logger = logging.getLogger("courier_platform.couriers.registry")


class CourierRegistry:
    """Central registry and factory for courier adapters."""

    def __init__(self):
        self._adapters: dict[str, CourierAdapter] = {}

    def register(self, name: str, adapter: CourierAdapter) -> None:
        """Register a courier adapter under a canonical identifier."""
        key = name.lower().strip()
        self._adapters[key] = adapter
        logger.info("Registered courier adapter: %s -> %s", key, adapter.__class__.__name__)

    def get(self, name: str) -> CourierAdapter:
        """Lookup courier adapter by partner string without if/elif branching.

        Raises UnsupportedCourierError if the partner name is not registered.
        """
        key = name.lower().strip()
        adapter = self._adapters.get(key)
        if adapter is None:
            logger.warning("Attempted lookup of unsupported courier: '%s'", name)
            raise UnsupportedCourierError(
                courier_partner=name,
                message=f"Courier partner '{name}' is not supported",
                details={"supported_couriers": self.list_supported()},
            )
        return adapter

    def list_supported(self) -> list[str]:
        """Return list of all registered courier partner names."""
        return sorted(self._adapters.keys())

    def unregister(self, name: str) -> Optional[CourierAdapter]:
        """Unregister and return an adapter by name (useful for testing)."""
        return self._adapters.pop(name.lower().strip(), None)

    def clear(self) -> None:
        """Clear all registered adapters."""
        self._adapters.clear()


# Default global registry instance
courier_registry = CourierRegistry()


def register_default_couriers(registry: CourierRegistry) -> None:
    """Populate registry with standard out-of-the-box adapters."""
    from app.couriers.mock import MockCourierAdapter
    from app.couriers.urbanebolt import UrbaneboltAdapter

    registry.register("mock", MockCourierAdapter())
    registry.register("urbanebolt", UrbaneboltAdapter())


# Initialize default couriers upon module import
register_default_couriers(courier_registry)
