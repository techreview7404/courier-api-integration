"""Resilient HTTP client with configurable exponential backoff and transparent token refresh."""

import logging
import time
from typing import Any, Callable, Optional
import httpx

from app.config import settings
from app.exceptions import (
    CourierAuthError,
    CourierError,
    CourierTimeoutError,
)

logger = logging.getLogger("courier_platform.client")


class ResilientHttpClient:
    """HTTP client wrapper providing exponential backoff retries and self-healing auth refresh."""

    def __init__(
        self,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
        request_timeout: Optional[float] = None,
        backoff_factor: float = 2.0,
        verify_ssl: bool = True,
        auth_refresh_callback: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.max_retries = max_retries if max_retries is not None else settings.MAX_RETRIES
        self.retry_delay = retry_delay if retry_delay is not None else settings.RETRY_DELAY
        self.request_timeout = (
            request_timeout if request_timeout is not None else settings.REQUEST_TIMEOUT
        )
        self.backoff_factor = backoff_factor
        self.verify_ssl = verify_ssl
        self.auth_refresh_callback = auth_refresh_callback

    def request(
        self,
        method: str,
        url: str,
        auth_refreshed: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute HTTP request with exponential backoff for timeouts/5xx and transparent 401 retry."""
        attempt = 0
        last_exception: Optional[Exception] = None
        last_response: Optional[httpx.Response] = None

        while attempt <= self.max_retries:
            try:
                # Use standard httpx.Client context manager
                with httpx.Client(timeout=self.request_timeout, verify=self.verify_ssl) as client:
                    upper_method = method.upper()
                    if upper_method == "POST":
                        response = client.post(url, **kwargs)
                    elif upper_method == "GET":
                        response = client.get(url, **kwargs)
                    elif upper_method == "PUT":
                        response = client.put(url, **kwargs)
                    elif upper_method == "DELETE":
                        response = client.delete(url, **kwargs)
                    else:
                        response = client.request(method, url, **kwargs)

                # Check 401 Unauthorized for transparent auth refresh
                if response.status_code == 401:
                    logger.warning(
                        "Received HTTP 401 Unauthorized from %s. Attempting token refresh...", url
                    )
                    if not auth_refreshed and self.auth_refresh_callback is not None:
                        new_token = self.auth_refresh_callback()
                        if new_token:
                            headers = kwargs.get("headers", {})
                            if isinstance(headers, dict):
                                headers["Authorization"] = f"Bearer {new_token}"
                                kwargs["headers"] = headers
                        # Retry once with refreshed token
                        return self.request(method, url, auth_refreshed=True, **kwargs)
                    # If already refreshed or no refresh callback, fail fast with CourierAuthError
                    raise CourierAuthError(
                        message=f"Courier authentication failed (401 Unauthorized) for {url}",
                        details={"status_code": 401, "body": response.text},
                    )

                # Check 5xx Server Errors (retryable with backoff)
                if response.status_code >= 500:
                    last_response = response
                    logger.warning(
                        "Received HTTP %d from %s (attempt %d/%d).",
                        response.status_code,
                        url,
                        attempt + 1,
                        self.max_retries + 1,
                    )
                    if attempt < self.max_retries:
                        delay = self.retry_delay * (self.backoff_factor**attempt)
                        if delay > 0:
                            time.sleep(delay)
                        attempt += 1
                        continue
                    else:
                        break

                # 2xx / 3xx / non-401 4xx: Return response immediately (fail-fast on 4xx)
                return response

            except (httpx.TimeoutException, CourierTimeoutError) as exc:
                last_exception = exc
                logger.warning(
                    "Timeout connecting to %s (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                if attempt < self.max_retries:
                    delay = self.retry_delay * (self.backoff_factor**attempt)
                    if delay > 0:
                        time.sleep(delay)
                    attempt += 1
                    continue
                else:
                    break

            except (httpx.ConnectError, httpx.NetworkError) as exc:
                last_exception = exc
                logger.warning(
                    "Network connection error to %s (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                if attempt < self.max_retries:
                    delay = self.retry_delay * (self.backoff_factor**attempt)
                    if delay > 0:
                        time.sleep(delay)
                    attempt += 1
                    continue
                else:
                    break

            except CourierAuthError:
                # Do not retry auth errors further
                raise

        # Retries exhausted
        if isinstance(last_exception, (httpx.TimeoutException, CourierTimeoutError)):
            raise CourierTimeoutError(
                message=f"Courier operation timed out after {self.max_retries} retries: {last_exception}",
                details={"url": url, "retries": self.max_retries},
            )
        if last_response is not None and last_response.status_code >= 500:
            raise CourierError(
                message=f"Downstream courier error (HTTP {last_response.status_code}) after {self.max_retries} retries",
                details={"status_code": last_response.status_code, "body": last_response.text},
            )
        if last_exception is not None:
            raise CourierError(
                message=f"Courier network failure after {self.max_retries} retries: {last_exception}",
                details={"url": url, "error": str(last_exception)},
            )

        raise CourierError(f"Courier request to {url} failed after {self.max_retries} retries")

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute GET request with resiliency."""
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute POST request with resiliency."""
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute PUT request with resiliency."""
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Execute DELETE request with resiliency."""
        return self.request("DELETE", url, **kwargs)
