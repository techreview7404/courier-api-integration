"""Repository pattern abstractions for Orders, Tracking History, and Batches."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.batch import Batch, BatchResult
from app.models.order import Order, TrackingHistory


class OrderRepository:
    """Repository handling database operations for Orders and Tracking History."""

    @staticmethod
    def get_by_order_id(db: Session, order_id: str) -> Optional[Order]:
        """Fetch order by business order_id."""
        return db.execute(
            select(Order).where(Order.order_id == str(order_id).strip())
        ).scalars().first()

    @staticmethod
    def create(
        db: Session,
        order: Order,
        initial_history: Optional[TrackingHistory] = None,
    ) -> Order:
        """Create a new order and optional initial tracking history record."""
        db.add(order)
        db.flush()  # Ensure foreign key exists for tracking history
        if initial_history is not None:
            db.add(initial_history)
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def get_tracking_history(db: Session, order_id: str) -> List[TrackingHistory]:
        """Retrieve chronological tracking history for an order."""
        return list(
            db.execute(
                select(TrackingHistory)
                .where(TrackingHistory.order_id == str(order_id).strip())
                .order_by(TrackingHistory.created_at.asc())
            ).scalars().all()
        )

    @staticmethod
    def add_tracking_history(db: Session, history: TrackingHistory) -> TrackingHistory:
        """Append a new tracking history event."""
        db.add(history)
        db.commit()
        db.refresh(history)
        return history


class BatchRepository:
    """Repository handling database operations for Batches and Batch Results."""

    @staticmethod
    def get_by_batch_id(db: Session, batch_id: str) -> Optional[Batch]:
        """Fetch batch by UUID batch_id."""
        return db.execute(
            select(Batch).where(Batch.batch_id == str(batch_id).strip())
        ).scalars().first()

    @staticmethod
    def get_batch_results(db: Session, batch_id: str) -> List[BatchResult]:
        """Retrieve all batch item results."""
        return list(
            db.execute(
                select(BatchResult)
                .where(BatchResult.batch_id == str(batch_id).strip())
                .order_by(BatchResult.id.asc())
            ).scalars().all()
        )


__all__ = ["OrderRepository", "BatchRepository"]
