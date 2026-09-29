"""Pydantic schemas and enums for order tracking and lifecycle statuses."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class OrderStatus(str, Enum):
    """Normalized order lifecycle status."""

    CREATED = "CREATED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TrackingEvent(BaseModel):
    """An individual tracking event entry in the audit history."""

    status: str
    timestamp: Optional[datetime] = Field(None, alias="created_at")
    raw_payload: Optional[Any] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrderTrackingResponse(BaseModel):
    """Response returned for tracking queries."""

    order_id: str
    courier_partner: Optional[str] = None
    awb_number: Optional[str] = None
    status: str
    history: list[TrackingEvent] = []

    model_config = ConfigDict(from_attributes=True)
