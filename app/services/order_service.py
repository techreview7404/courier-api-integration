"""Service layer for Order lifecycle, tracking history, and idempotency management."""

import logging
from typing import Any
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.couriers.registry import courier_registry
from app.exceptions import (
    DuplicateOrderError,
    OrderNotFoundError,
    ValidationError,
)
from app.models.order import Order, TrackingHistory
from app.schemas.order import (
    OrderCancelResponse,
    OrderCreateRequest,
    OrderResponse,
)
from app.schemas.tracking import (
    OrderStatus,
    OrderTrackingResponse,
    TrackingEvent,
)

logger = logging.getLogger("courier_platform.services.order")


class OrderService:
    """Service managing order creation, live tracking, cancellation, and audit history."""

    @classmethod
    def create_order(
        cls,
        db: Session,
        order_in: OrderCreateRequest | dict[str, Any],
    ) -> OrderResponse:
        """Create a new shipment order across courier partners with idempotency enforcement.

        1. Validates input request payload.
        2. Enforces database idempotency check to avoid duplicate courier calls.
        3. Looks up courier adapter dynamically via CourierRegistry.
        4. Calls courier adapter to create shipment.
        5. Persists Order record and initial TrackingHistory audit entry in database.
        """
        # Parse / validate input payload if given as a raw dict
        if isinstance(order_in, dict):
            try:
                order_in = OrderCreateRequest.model_validate(order_in)
            except Exception as exc:
                raise ValidationError(
                    message=f"Invalid order creation payload: {exc}",
                    details={"error": str(exc)},
                )

        order_id = str(order_in.order_id).strip()
        courier_partner_raw = str(order_in.courier_partner).strip()
        courier_partner_key = courier_partner_raw.lower()

        logger.info(
            "Initiating order creation: order_id='%s', courier='%s'",
            order_id,
            courier_partner_key,
        )

        # 1. Pre-check idempotency: prevent duplicate courier calls
        existing = db.execute(
            select(Order).where(Order.order_id == order_id)
        ).scalars().first()

        if existing is not None:
            logger.warning("Duplicate order creation rejected for order_id='%s'", order_id)
            raise DuplicateOrderError(
                order_id=order_id,
                message=f"Order '{order_id}' already exists",
                details={
                    "existing_order_id": existing.order_id,
                    "status": existing.status,
                    "awb_number": existing.awb_number,
                },
            )

        # 2. Dynamic Courier lookup via registry (raises UnsupportedCourierError if unknown)
        adapter = courier_registry.get(courier_partner_key)

        # 3. Call courier adapter (all courier-specific mapping is isolated inside adapter)
        courier_res = adapter.create_order(order_in)

        # 4. Normalize status and payloads
        status_val = (
            courier_res.status.value
            if hasattr(courier_res.status, "value")
            else str(courier_res.status)
        )
        req_payload = (
            order_in.model_dump()
            if hasattr(order_in, "model_dump")
            else dict(order_in)
        )
        res_payload = (
            courier_res.raw_response
            if hasattr(courier_res, "raw_response")
            else {}
        )

        # 5. Persist Order and initial TrackingHistory entry atomically
        db_order = Order(
            order_id=order_id,
            courier_partner=courier_partner_key,
            courier_order_id=courier_res.courier_order_id,
            awb_number=courier_res.awb_number,
            status=status_val,
            request_payload=req_payload,
            response_payload=res_payload,
        )
        db.add(db_order)
        db.flush()

        # Append initial tracking history event (never overwrite)
        initial_history = TrackingHistory(
            order_id=order_id,
            status=status_val,
            raw_payload=res_payload,
        )
        db.add(initial_history)

        try:
            db.commit()
            db.refresh(db_order)
        except IntegrityError as exc:
            db.rollback()
            logger.warning(
                "IntegrityError on order insertion for order_id='%s': %s",
                order_id,
                exc,
            )
            raise DuplicateOrderError(
                order_id=order_id,
                message=f"Order '{order_id}' already exists (database constraint)",
                details={"original_error": str(exc)},
            )

        logger.info(
            "Order successfully created: order_id='%s', awb='%s', status='%s'",
            db_order.order_id,
            db_order.awb_number,
            db_order.status,
        )

        return OrderResponse(
            order_id=db_order.order_id,
            courier_partner=db_order.courier_partner,
            courier_order_id=db_order.courier_order_id,
            awb_number=db_order.awb_number,
            status=db_order.status,
            created_at=db_order.created_at,
            updated_at=db_order.updated_at,
        )

    @classmethod
    def track_order(cls, db: Session, order_id: str) -> OrderTrackingResponse:
        """Fetch live status from courier, update order status, and append to tracking history.

        1. Finds internal order by order_id (raises OrderNotFoundError if missing).
        2. Retrieves courier adapter dynamically.
        3. Calls courier tracking API.
        4. Normalizes status and updates order record.
        5. Appends tracking update event to immutable tracking_history.
        6. Returns full normalized response including chronological history.
        """
        clean_order_id = str(order_id).strip()

        order = db.execute(
            select(Order).where(Order.order_id == clean_order_id)
        ).scalars().first()

        if order is None:
            logger.warning("Tracking query for non-existent order_id='%s'", clean_order_id)
            raise OrderNotFoundError(order_id=clean_order_id)

        adapter = courier_registry.get(order.courier_partner)
        tracking_id = order.awb_number or order.order_id

        track_res = adapter.track_order(tracking_id)

        new_status = (
            track_res.status.value
            if hasattr(track_res.status, "value")
            else str(track_res.status)
        )

        # Update order current status and AWB if newly available
        order.status = new_status
        if track_res.awb_number and not order.awb_number:
            order.awb_number = track_res.awb_number

        # Append new tracking event to immutable tracking_history audit trail
        tracking_event = TrackingHistory(
            order_id=order.order_id,
            status=new_status,
            raw_payload=track_res.raw_response if hasattr(track_res, "raw_response") else {},
        )
        db.add(tracking_event)
        db.commit()
        db.refresh(order)

        # Retrieve full chronological history
        history_rows = (
            db.execute(
                select(TrackingHistory)
                .where(TrackingHistory.order_id == order.order_id)
                .order_by(TrackingHistory.id.asc())
            )
            .scalars()
            .all()
        )

        history_events = [
            TrackingEvent(
                status=h.status,
                created_at=h.created_at,
                raw_payload=h.raw_payload,
            )
            for h in history_rows
        ]

        logger.info(
            "Order tracked successfully: order_id='%s', status='%s', events_count=%d",
            order.order_id,
            order.status,
            len(history_events),
        )

        return OrderTrackingResponse(
            order_id=order.order_id,
            courier_partner=order.courier_partner,
            awb_number=order.awb_number,
            status=order.status,
            history=history_events,
        )

    @classmethod
    def cancel_order(cls, db: Session, order_id: str) -> OrderCancelResponse:
        """Cancel an order with downstream courier and record cancellation event in history.

        1. Finds internal order (raises OrderNotFoundError if missing).
        2. Retrieves courier adapter dynamically.
        3. Calls courier cancel API (if not already cancelled).
        4. Transitions order status to CANCELLED.
        5. Appends CANCELLED record to immutable tracking_history.
        6. Returns normalized cancellation response.
        """
        clean_order_id = str(order_id).strip()

        order = db.execute(
            select(Order).where(Order.order_id == clean_order_id)
        ).scalars().first()

        if order is None:
            logger.warning("Cancellation attempted for non-existent order_id='%s'", clean_order_id)
            raise OrderNotFoundError(order_id=clean_order_id)

        adapter = courier_registry.get(order.courier_partner)
        tracking_id = order.awb_number or order.order_id

        # Idempotent cancellation: if already cancelled, return existing state without duplicate history
        if order.status == OrderStatus.CANCELLED.value:
            logger.info("Order '%s' is already cancelled; returning idempotent response", clean_order_id)
            return OrderCancelResponse(order_id=order.order_id, status=OrderStatus.CANCELLED.value)

        # Call courier cancel API
        cancel_res = adapter.cancel_order(tracking_id)

        order.status = OrderStatus.CANCELLED.value

        # Append CANCELLED event to tracking_history
        raw_res = cancel_res.raw_response if hasattr(cancel_res, "raw_response") else {}
        tracking_entry = TrackingHistory(
            order_id=order.order_id,
            status=OrderStatus.CANCELLED.value,
            raw_payload=raw_res,
        )
        db.add(tracking_entry)
        db.commit()
        db.refresh(order)

        logger.info("Order '%s' successfully cancelled with courier", order.order_id)

        return OrderCancelResponse(
            order_id=order.order_id,
            status=order.status,
        )

    @classmethod
    def get_order(cls, db: Session, order_id: str) -> OrderResponse:
        """Retrieve existing order by ID without querying downstream courier."""
        clean_order_id = str(order_id).strip()
        order = db.execute(
            select(Order).where(Order.order_id == clean_order_id)
        ).scalars().first()


        if order is None:
            raise OrderNotFoundError(order_id=clean_order_id)

        return OrderResponse(
            order_id=order.order_id,
            courier_partner=order.courier_partner,
            courier_order_id=order.courier_order_id,
            awb_number=order.awb_number,
            status=order.status,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )


order_service = OrderService()
