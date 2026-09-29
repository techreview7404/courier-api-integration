"""Pydantic schemas for bulk order processing requests and responses."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.order import OrderCreateRequest


class BulkStatus(str, Enum):
    """Lifecycle status of a bulk order processing batch."""

    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BulkOrderRequest(BaseModel):
    """Request payload for bulk order submission (up to 100 orders)."""

    orders: list[OrderCreateRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of orders to process (between 1 and 100)",
    )


class BulkSubmitResponse(BaseModel):
    """Response returned immediately after submitting bulk orders."""

    batch_id: str
    status: str = "PROCESSING"

    model_config = ConfigDict(from_attributes=True)


class BatchItemResult(BaseModel):
    """Execution result for an individual order in a bulk batch."""

    order_id: str
    success: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BulkStatusResponse(BaseModel):
    """Polling response reflecting the current status and results of a bulk batch."""

    batch_id: str
    status: str
    total: int
    successful: int
    failed: int
    results: list[BatchItemResult] = []

    model_config = ConfigDict(from_attributes=True)
