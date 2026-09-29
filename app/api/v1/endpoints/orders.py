"""Endpoints for Order creation, live tracking, and cancellation."""

import logging
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.bulk import BulkOrderRequest, BulkStatusResponse, BulkSubmitResponse
from app.schemas.order import (
    OrderCancelResponse,
    OrderCreateRequest,
    OrderResponse,
)
from app.schemas.tracking import OrderTrackingResponse
from app.services.bulk_service import BulkService
from app.services.order_service import OrderService

logger = logging.getLogger("courier_platform.api.v1.orders")

router = APIRouter()


@router.post(
    "/bulk",
    response_model=BulkSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit bulk shipment orders",
    description="Asynchronously process up to 100 orders concurrently in background.",
)
def submit_bulk_orders(
    bulk_in: BulkOrderRequest,
    db: Session = Depends(get_db),
) -> BulkSubmitResponse:
    """Submit up to 100 orders for concurrent background processing."""
    return BulkService.submit_bulk(db=db, bulk_in=bulk_in)


@router.get(
    "/bulk/{batch_id}",
    response_model=BulkStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll bulk processing batch status",
    description="Retrieve execution progress and itemized outcomes for a bulk batch.",
)
def get_bulk_status(
    batch_id: str,
    db: Session = Depends(get_db),
) -> BulkStatusResponse:
    """Retrieve current processing status and item-level results for a batch."""
    return BulkService.get_bulk_status(db=db, batch_id=batch_id)


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a shipment order",
    description="Idempotent order creation across supported courier partners.",
)
def create_order(
    order_in: OrderCreateRequest,
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Create a new order shipment and return normalized order details."""
    return OrderService.create_order(db=db, order_in=order_in)


@router.get(
    "/{order_id}/track",
    response_model=OrderTrackingResponse,
    status_code=status.HTTP_200_OK,
    summary="Track order status and history",
    description="Fetch live courier tracking, update status, and append to immutable history.",
)
def track_order(
    order_id: str,
    db: Session = Depends(get_db),
) -> OrderTrackingResponse:
    """Retrieve tracking details and chronological event history."""
    return OrderService.track_order(db=db, order_id=order_id)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel order shipment",
    description="Cancel shipment with courier partner and record cancellation in history.",
)
def cancel_order(
    order_id: str,
    db: Session = Depends(get_db),
) -> OrderCancelResponse:
    """Cancel the order and return updated cancellation status."""
    return OrderService.cancel_order(db=db, order_id=order_id)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Get order details",
    description="Retrieve order by internal order_id without downstream courier query.",
)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
) -> OrderResponse:
    """Retrieve persisted order record."""
    return OrderService.get_order(db=db, order_id=order_id)
