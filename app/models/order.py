"""SQLAlchemy models for Order and TrackingHistory."""

from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Order(Base):
    """Normalized Order model tracking shipment state across courier partners."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    courier_partner: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    courier_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    awb_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    request_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    response_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    tracking_history: Mapped[list["TrackingHistory"]] = relationship(
        "TrackingHistory",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="TrackingHistory.id",
    )


class TrackingHistory(Base):
    """Immutable append-only audit trail of order tracking status updates."""

    __tablename__ = "tracking_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("orders.order_id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    order: Mapped["Order"] = relationship("Order", back_populates="tracking_history")
