"""Error utilities and normalized application exceptions."""

from app.exceptions import (
    AppError,
    BatchNotFoundError,
    BulkLimitExceededError,
    CourierAuthError,
    CourierError,
    CourierNotFoundError,
    CourierRateLimitError,
    CourierTimeoutError,
    CourierUnavailableError,
    DuplicateOrderError,
    EntityNotFoundError,
    IdempotencyConflictError,
    InternalServerError,
    OrderAlreadyCancelledError,
    OrderNotFoundError,
    ValidationError,
)

__all__ = [
    "AppError",
    "ValidationError",
    "EntityNotFoundError",
    "OrderNotFoundError",
    "BatchNotFoundError",
    "DuplicateOrderError",
    "IdempotencyConflictError",
    "OrderAlreadyCancelledError",
    "CourierError",
    "CourierNotFoundError",
    "CourierTimeoutError",
    "CourierUnavailableError",
    "CourierAuthError",
    "CourierRateLimitError",
    "BulkLimitExceededError",
    "InternalServerError",
]
