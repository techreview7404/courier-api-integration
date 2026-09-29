"""Error handling middleware and exception handlers for normalized error envelope."""

import logging
import uuid
from typing import Any
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.exceptions import AppError

logger = logging.getLogger("courier_platform")


def get_request_id(request: Request) -> str:
    """Extract or generate a unique request trace ID."""
    req_id = getattr(request.state, "request_id", None)
    if not req_id:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id
    return req_id


def build_error_response(
    code: str,
    message: str,
    request_id: str,
    status_code: int,
    details: Any = None,
) -> JSONResponse:
    """Construct a standardized error JSON response."""
    payload = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details if details is not None else {},
        }
    }
    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers={"X-Request-ID": request_id},
    )


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware ensuring every request has a tracking request_id and X-Request-ID header."""

    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id
        try:
            response = await call_next(request)
        except AppError as exc:
            return await app_error_handler(request, exc)
        except Exception as exc:
            return await unhandled_exception_handler(request, exc)

        response.headers["X-Request-ID"] = req_id
        return response


def _format_validation_errors(errors: list) -> dict:
    """Format FastAPI / Pydantic validation errors into clean field summaries."""
    fields = []
    for err in errors:
        loc = " -> ".join(str(part) for part in err.get("loc", []))
        fields.append(
            {
                "field": loc,
                "message": err.get("msg", "Validation error"),
                "type": err.get("type", "value_error"),
            }
        )
    return {"fields": fields}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handle custom application AppError domain exceptions."""
    req_id = get_request_id(request)
    logger.warning(
        f"Domain error [{exc.code}] on {request.method} {request.url.path} (request_id={req_id}): {exc.message}"
    )
    return build_error_response(
        code=exc.code,
        message=exc.message,
        request_id=req_id,
        status_code=exc.status_code,
        details=exc.details,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic request validation exceptions with normalized error envelope."""
    req_id = get_request_id(request)
    formatted_details = _format_validation_errors(exc.errors())
    logger.info(
        f"Validation error on {request.method} {request.url.path} (request_id={req_id}): {formatted_details}"
    )
    return build_error_response(
        code="VALIDATION_ERROR",
        message="Invalid request payload or parameters",
        request_id=req_id,
        status_code=400,
        details=formatted_details,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle standard HTTP exceptions (404, 405, etc.)."""
    req_id = get_request_id(request)
    code = "ORDER_NOT_FOUND" if exc.status_code == 404 else f"HTTP_{exc.status_code}"
    return build_error_response(
        code=code,
        message=str(exc.detail),
        request_id=req_id,
        status_code=exc.status_code,
        details={},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected internal exceptions."""
    req_id = get_request_id(request)
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path} (request_id={req_id}): {exc}",
        exc_info=True,
    )
    return build_error_response(
        code="INTERNAL_ERROR",
        message="An unexpected internal server error occurred",
        request_id=req_id,
        status_code=500,
        details={},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all global exception handlers on the FastAPI application."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
