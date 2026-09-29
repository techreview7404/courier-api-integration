"""Services package providing business logic for orders and shipments."""

from app.services.order_service import OrderService, order_service

__all__ = ["OrderService", "order_service"]
