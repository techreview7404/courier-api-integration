"""Abstract base class and strongly-typed DTOs for the Courier Adapter pattern."""

from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.order import OrderCreateRequest
from app.schemas.tracking import OrderStatus


class AwaitableDTO(BaseModel):
    """Base DTO providing dual synchronous and asynchronous (awaitable) compatibility.

    Allows callers to either use the returned result directly:
        result = adapter.create_order(payload)
    or await it in an async context:
        result = await adapter.create_order(payload)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    def __await__(self):
        async def _identity():
            return self

        return _identity().__await__()


class CourierOrderResult(AwaitableDTO):
    """Normalized result returned from courier order creation / manifest API."""

    courier_order_id: str = Field(..., description="Courier partner order identifier")
    awb_number: str = Field(..., description="Air Waybill tracking number")
    status: OrderStatus = Field(default=OrderStatus.CREATED, description="Initial order lifecycle status")
    raw_response: dict[str, Any] = Field(default_factory=dict, description="Raw response payload from courier")


class CourierTrackingResult(AwaitableDTO):
    """Normalized result returned from courier tracking API."""

    status: OrderStatus = Field(..., description="Current normalized order lifecycle status")
    awb_number: str = Field(..., description="Air Waybill tracking number")
    raw_response: dict[str, Any] = Field(default_factory=dict, description="Raw response payload from courier")
    tracking_events: list[dict[str, Any]] = Field(
        default_factory=list, description="Chronological milestone scans/events from courier"
    )


class CourierCancelResult(AwaitableDTO):
    """Normalized result returned from courier order cancellation API."""

    status: OrderStatus = Field(default=OrderStatus.CANCELLED, description="Final normalized status")
    success: bool = Field(default=True, description="Whether cancellation succeeded")
    raw_response: dict[str, Any] = Field(default_factory=dict, description="Raw response payload from courier")
    message: Optional[str] = Field(default=None, description="Descriptive status message from courier")


class CourierAdapter(ABC):
    """Abstract interface contract for all downstream shipping partner adapters."""

    @property
    @abstractmethod
    def partner_name(self) -> str:
        """Return the canonical lowercase name of the courier partner (e.g. 'mock', 'urbanebolt')."""
        pass

    @abstractmethod
    def authenticate(self) -> None:
        """Authenticate with the courier partner API and cache credentials/tokens."""
        pass

    @abstractmethod
    def create_order(self, order: OrderCreateRequest | dict[str, Any]) -> CourierOrderResult:
        """Transform normalized order payload into courier-specific format, manifest shipment, and return DTO."""
        pass

    @abstractmethod
    def track_order(self, tracking_id: str) -> CourierTrackingResult:
        """Query courier tracking API using AWB or tracking ID, normalize status, and return DTO."""
        pass

    @abstractmethod
    def cancel_order(self, tracking_id: str) -> CourierCancelResult:
        """Invoke courier cancellation API for the given AWB/tracking ID and return DTO."""
        pass
