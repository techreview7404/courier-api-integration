"""Retry utilities, backoff helpers, and resilient HTTP client re-exports."""

import time
import logging
from typing import Any, Callable, TypeVar

from app.couriers.client import ResilientHttpClient
from app.config import settings

logger = logging.getLogger("courier_platform.utils.retry")

T = TypeVar("T")


def retry_call(
    func: Callable[..., T],
    max_retries: int = 3,
    delay: float = 0.5,
    backoff_factor: float = 2.0,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute a callable with exponential backoff on specified exceptions."""
    attempt = 0
    current_delay = delay
    while attempt <= max_retries:
        try:
            return func(*args, **kwargs)
        except retry_exceptions as exc:
            attempt += 1
            if attempt > max_retries:
                logger.error("Function '%s' failed after %d retries: %s", func.__name__, max_retries, exc)
                raise
            logger.warning(
                "Function '%s' failed (attempt %d/%d): %s. Retrying in %.2fs",
                func.__name__,
                attempt,
                max_retries,
                exc,
                current_delay,
            )
            time.sleep(current_delay)
            current_delay *= backoff_factor
    raise RuntimeError("Retry loop exited unexpectedly")


__all__ = ["ResilientHttpClient", "retry_call"]
