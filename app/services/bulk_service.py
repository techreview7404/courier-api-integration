"""Service layer for asynchronous in-process bulk order processing."""

import concurrent.futures
import logging
import threading
import time
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.couriers.registry import courier_registry
from app.exceptions import (
    AppError,
    BatchNotFoundError,
    ValidationError,
)
from app.models.batch import Batch, BatchResult
from app.models.order import Order, TrackingHistory
from app.schemas.bulk import (
    BatchItemResult,
    BulkOrderRequest,
    BulkStatus,
    BulkStatusResponse,
    BulkSubmitResponse,
)
from app.schemas.order import OrderCreateRequest

logger = logging.getLogger("courier_platform.services.bulk")

# Global re-entrant lock for thread-safe SQLite operations
_db_write_lock = threading.RLock()


class BulkService:
    """Service managing bulk batch lifecycle, concurrent worker dispatch, and progress querying."""

    @classmethod
    def submit_bulk(cls, db: Session, bulk_in: BulkOrderRequest) -> BulkSubmitResponse:
        """Submit a batch of up to 100 orders for asynchronous in-process processing."""
        if not bulk_in.orders:
            raise ValidationError(
                message="Bulk order list cannot be empty",
                details={"min_length": 1},
            )
        if len(bulk_in.orders) > 100:
            raise ValidationError(
                message=f"Bulk order list exceeds limit of 100 (received {len(bulk_in.orders)})",
                details={"max_length": 100, "actual_count": len(bulk_in.orders)},
            )

        batch_id = f"BATCH-{uuid.uuid4().hex[:12].upper()}"

        batch = Batch(
            batch_id=batch_id,
            status=BulkStatus.PROCESSING.value,
            total=len(bulk_in.orders),
            successful=0,
            failed=0,
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        logger.info("Created bulk batch '%s' with %d orders", batch_id, len(bulk_in.orders))

        orders_dump = [
            order.model_dump() if hasattr(order, "model_dump") else dict(order)
            for order in bulk_in.orders
        ]

        target_bind = db.get_bind()
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=target_bind)

        # Dispatch in-process background worker thread
        worker_thread = threading.Thread(
            target=cls._process_bulk_batch,
            args=(batch_id, orders_dump, session_factory),
            daemon=True,
            name=f"BulkWorker-{batch_id}",
        )
        worker_thread.start()

        return BulkSubmitResponse(
            batch_id=batch_id,
            status=BulkStatus.PROCESSING.value,
        )

    @classmethod
    def get_bulk_status(cls, db: Session, batch_id: str) -> BulkStatusResponse:
        """Retrieve progress and itemized results for a batch."""
        clean_batch_id = str(batch_id).strip()
        db.expire_all()

        batch = db.execute(
            select(Batch).where(Batch.batch_id == clean_batch_id)
        ).scalars().first()

        if batch is None:
            raise BatchNotFoundError(
                batch_id=clean_batch_id,
                message=f"Batch '{clean_batch_id}' was not found",
            )

        # Retrieve all batch results in deterministic order
        results = db.execute(
            select(BatchResult)
            .where(BatchResult.batch_id == clean_batch_id)
            .order_by(BatchResult.id.asc())
        ).scalars().all()

        return BulkStatusResponse(
            batch_id=batch.batch_id,
            status=batch.status,
            total=batch.total,
            successful=batch.successful,
            failed=batch.failed,
            results=[
                BatchItemResult(
                    order_id=r.order_id,
                    success=r.success,
                    error_code=r.error_code,
                    error_message=r.error_message,
                )
                for r in results
            ],
        )

    @classmethod
    def _call_courier_single(cls, order_dict: dict[str, Any]) -> dict[str, Any]:
        """Execute courier call concurrently outside of database transactions."""
        order_id = str(order_dict.get("order_id", "UNKNOWN"))
        try:
            order_in = OrderCreateRequest.model_validate(order_dict)
            clean_order_id = str(order_in.order_id).strip()
            courier_partner_key = str(order_in.courier_partner).strip().lower()

            adapter = courier_registry.get(courier_partner_key)
            courier_res = adapter.create_order(order_in)

            return {
                "order_id": clean_order_id,
                "courier_partner": courier_partner_key,
                "courier_order_id": courier_res.courier_order_id,
                "awb_number": courier_res.awb_number,
                "status": (
                    courier_res.status.value
                    if hasattr(courier_res.status, "value")
                    else str(courier_res.status)
                ),
                "request_payload": order_in.model_dump(),
                "response_payload": (
                    courier_res.raw_response
                    if hasattr(courier_res, "raw_response")
                    else {}
                ),
                "success": True,
                "error_code": None,
                "error_message": None,
            }
        except AppError as exc:
            return {
                "order_id": order_id,
                "success": False,
                "error_code": exc.code,
                "error_message": exc.message,
            }
        except Exception as exc:
            return {
                "order_id": order_id,
                "success": False,
                "error_code": "VALIDATION_ERROR" if "pydantic" in str(type(exc)).lower() else "INTERNAL_ERROR",
                "error_message": str(exc),
            }

    @classmethod
    def _process_bulk_batch(
        cls,
        batch_id: str,
        orders_data: list[dict[str, Any]],
        session_factory: sessionmaker,
    ) -> None:
        """Process bulk orders: concurrent courier calls followed by single atomic persistence."""
        max_workers = min(10, max(1, len(orders_data)))
        logger.info("Processing bulk batch '%s' with %d concurrent workers", batch_id, max_workers)

        # 1. Execute courier shipments concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(cls._call_courier_single, orders_data))

        # 2. Atomic persistence of orders, history, batch items, and status update
        with _db_write_lock:
            try:
                with session_factory() as db:
                    successful_count = 0
                    failed_count = 0

                    for item in results:
                        order_id = item["order_id"]

                        if item["success"]:
                            # Check idempotency: does order already exist in DB?
                            existing = db.execute(
                                select(Order).where(Order.order_id == order_id)
                            ).scalars().first()

                            if existing is not None:
                                item["success"] = False
                                item["error_code"] = "DUPLICATE_ORDER"
                                item["error_message"] = f"Order '{order_id}' already exists"
                                failed_count += 1
                            else:
                                db_order = Order(
                                    order_id=order_id,
                                    courier_partner=item["courier_partner"],
                                    courier_order_id=item["courier_order_id"],
                                    awb_number=item["awb_number"],
                                    status=item["status"],
                                    request_payload=item["request_payload"],
                                    response_payload=item["response_payload"],
                                )
                                db.add(db_order)
                                db.flush()

                                initial_history = TrackingHistory(
                                    order_id=order_id,
                                    status=item["status"],
                                    raw_payload=item["response_payload"],
                                )
                                db.add(initial_history)
                                successful_count += 1
                        else:
                            failed_count += 1

                        db_result = BatchResult(
                            batch_id=batch_id,
                            order_id=order_id,
                            success=item["success"],
                            error_code=item["error_code"],
                            error_message=item["error_message"],
                        )
                        db.add(db_result)

                    batch = db.execute(
                        select(Batch).where(Batch.batch_id == batch_id)
                    ).scalars().first()

                    if batch:
                        batch.successful = successful_count
                        batch.failed = failed_count
                        batch.status = BulkStatus.COMPLETED.value

                    db.commit()
                    logger.info(
                        "Batch '%s' completed: total=%d, successful=%d, failed=%d",
                        batch_id,
                        len(orders_data),
                        successful_count,
                        failed_count,
                    )
            except Exception as exc:
                logger.warning(
                    "Batch '%s' database persistence stopped or connection closed: %s",
                    batch_id,
                    exc,
                )


bulk_service = BulkService()
