"""Consolidated API schemas re-exported for convenience."""

from app.schemas.order import (
    AddressSchema,
    OrderCancelResponse,
    OrderCreateRequest,
    OrderItemSchema,
    OrderResponse,
    PackageDetailsSchema,
)
from app.schemas.tracking import (
    OrderStatus,
    OrderTrackingResponse,
    TrackingEvent,
)
from app.schemas.bulk import (
    BatchItemResult,
    BatchResponse,
    BatchStatus,
    BulkOrderRequest,
    BulkOrderResponse,
)
from app.schemas.common import (
    ErrorDetail,
    ErrorEnvelope,
)

__all__ = [
    "AddressSchema",
    "OrderItemSchema",
    "PackageDetailsSchema",
    "OrderCreateRequest",
    "OrderResponse",
    "OrderCancelResponse",
    "OrderStatus",
    "OrderTrackingResponse",
    "TrackingEvent",
    "BulkOrderRequest",
    "BulkOrderResponse",
    "BatchResponse",
    "BatchStatus",
    "BatchItemResult",
    "ErrorDetail",
    "ErrorEnvelope",
]
