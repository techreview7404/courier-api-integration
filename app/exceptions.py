"""Application custom exception hierarchy for normalized error handling."""

from typing import Any, Optional


class AppError(Exception):
    """Base application exception with standardized code and status code."""

    code: str = "INTERNAL_ERROR"
    message: str = "An internal error occurred"
    status_code: int = 500
    details: Any = None

    def __init__(
        self,
        message: Optional[str] = None,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Any = None,
    ):
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details if details is not None else {}
        super().__init__(self.message)


class ValidationError(AppError):
    """Raised when request payload or parameters fail domain validation."""

    code = "VALIDATION_ERROR"
    message = "Invalid request payload"
    status_code = 400


class EntityNotFoundError(AppError):
    """Raised when a requested resource is not found."""

    code = "ORDER_NOT_FOUND"
    message = "Resource not found"
    status_code = 404


class OrderNotFoundError(EntityNotFoundError):
    """Raised specifically when an order is not found by ID."""

    code = "ORDER_NOT_FOUND"
    status_code = 404

    def __init__(
        self,
        order_id: Optional[str] = None,
        message: Optional[str] = None,
        details: Any = None,
    ):
        msg = message or (f"Order '{order_id}' not found" if order_id else "Order not found")
        super().__init__(message=msg, code=self.code, status_code=self.status_code, details=details)


class BatchNotFoundError(EntityNotFoundError):
    """Raised specifically when a bulk batch is not found by ID."""

    code = "ORDER_NOT_FOUND"
    status_code = 404

    def __init__(
        self,
        batch_id: Optional[str] = None,
        message: Optional[str] = None,
        details: Any = None,
    ):
        msg = message or (f"Batch '{batch_id}' not found" if batch_id else "Batch not found")
        super().__init__(message=msg, code=self.code, status_code=self.status_code, details=details)


class DuplicateEntityError(AppError):
    """Raised when attempting to create an entity that already exists."""

    code = "DUPLICATE_ORDER"
    message = "Duplicate entity detected"
    status_code = 409


class DuplicateOrderError(DuplicateEntityError):
    """Raised when an order_id already exists in the database."""

    code = "DUPLICATE_ORDER"
    status_code = 409

    def __init__(
        self,
        order_id: Optional[str] = None,
        message: Optional[str] = None,
        details: Any = None,
    ):
        msg = message or (f"Order '{order_id}' already exists" if order_id else "Order already exists")
        super().__init__(message=msg, code=self.code, status_code=self.status_code, details=details)


class UnsupportedCourierError(AppError):
    """Raised when a requested courier partner is not registered."""

    code = "UNSUPPORTED_COURIER"
    status_code = 400

    def __init__(
        self,
        courier_partner: Optional[str] = None,
        message: Optional[str] = None,
        details: Any = None,
    ):
        msg = message or (
            f"Courier partner '{courier_partner}' is not supported"
            if courier_partner
            else "Unsupported courier partner"
        )
        super().__init__(message=msg, code=self.code, status_code=self.status_code, details=details)


class CourierError(AppError):
    """Base exception for downstream courier API errors."""

    code = "COURIER_ERROR"
    message = "Downstream courier error occurred"
    status_code = 502


class CourierTimeoutError(CourierError):
    """Raised when downstream courier request times out after retries."""

    code = "COURIER_TIMEOUT"
    message = "Courier request timed out"
    status_code = 504


class CourierAuthError(CourierError):
    """Raised when downstream courier authentication fails after retry."""

    code = "COURIER_AUTH_ERROR"
    message = "Courier authentication failed"
    status_code = 502


class InternalServerError(AppError):
    """Unexpected internal server error."""

    code = "INTERNAL_ERROR"
    message = "An internal server error occurred"
    status_code = 500
