import pytest
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.exceptions import (
    AppError,
    BatchNotFoundError,
    CourierAuthError,
    CourierError,
    CourierTimeoutError,
    DuplicateEntityError,
    DuplicateOrderError,
    EntityNotFoundError,
    InternalServerError,
    OrderNotFoundError,
    UnsupportedCourierError,
    ValidationError,
)


def test_exception_hierarchy_attributes():
    """Verify default error codes and HTTP status codes across the exception hierarchy."""
    # Base AppError
    base = AppError("Something went wrong", code="CUSTOM_CODE", status_code=418, details={"k": "v"})
    assert base.code == "CUSTOM_CODE"
    assert base.status_code == 418
    assert base.message == "Something went wrong"
    assert base.details == {"k": "v"}

    # ValidationError
    val_err = ValidationError("Bad input")
    assert val_err.code == "VALIDATION_ERROR"
    assert val_err.status_code == 400

    # EntityNotFoundError & OrderNotFoundError
    ord_err = OrderNotFoundError(order_id="ORD-999")
    assert ord_err.code == "ORDER_NOT_FOUND"
    assert ord_err.status_code == 404
    assert "ORD-999" in ord_err.message
    assert isinstance(ord_err, EntityNotFoundError)

    batch_err = BatchNotFoundError(batch_id="BATCH-999")
    assert batch_err.code == "ORDER_NOT_FOUND"
    assert batch_err.status_code == 404
    assert "BATCH-999" in batch_err.message
    assert isinstance(batch_err, EntityNotFoundError)

    # DuplicateEntityError & DuplicateOrderError
    dup_err = DuplicateOrderError(order_id="ORD-123")
    assert dup_err.code == "DUPLICATE_ORDER"
    assert dup_err.status_code == 409
    assert "ORD-123" in dup_err.message
    assert isinstance(dup_err, DuplicateEntityError)

    # UnsupportedCourierError
    unsupp_err = UnsupportedCourierError(courier_partner="dhl")
    assert unsupp_err.code == "UNSUPPORTED_COURIER"
    assert unsupp_err.status_code == 400
    assert "dhl" in unsupp_err.message

    # CourierError, CourierTimeoutError, CourierAuthError
    cour_err = CourierError("Courier gateway failed")
    assert cour_err.code == "COURIER_ERROR"
    assert cour_err.status_code == 502

    timeout_err = CourierTimeoutError()
    assert timeout_err.code == "COURIER_TIMEOUT"
    assert timeout_err.status_code == 504

    auth_err = CourierAuthError()
    assert auth_err.code == "COURIER_AUTH_ERROR"
    assert auth_err.status_code == 502

    # InternalServerError
    int_err = InternalServerError()
    assert int_err.code == "INTERNAL_ERROR"
    assert int_err.status_code == 500


def test_health_endpoints(client):
    """Verify root and api v1 health check endpoints."""
    res1 = client.get("/health")
    assert res1.status_code == 200
    assert res1.json()["status"] == "ok"
    assert "X-Request-ID" in res1.headers

    res2 = client.get("/api/v1/health")
    assert res2.status_code == 200
    assert res2.json()["status"] == "ok"


def test_app_error_middleware_handling(test_app, client):
    """Verify that domain AppError exceptions are transformed into the standardized envelope."""
    router = APIRouter(prefix="/test-errors")

    @router.get("/validation")
    def trigger_validation():
        raise ValidationError("Invalid order parameters", details={"field": "items"})

    @router.get("/not-found")
    def trigger_not_found():
        raise OrderNotFoundError(order_id="ORD-NOTFOUND")

    @router.get("/duplicate")
    def trigger_duplicate():
        raise DuplicateOrderError(order_id="ORD-EXISTING")

    @router.get("/unsupported-courier")
    def trigger_unsupported():
        raise UnsupportedCourierError(courier_partner="unknown_carrier")

    @router.get("/courier-timeout")
    def trigger_timeout():
        raise CourierTimeoutError("Mock timeout exceeded")

    @router.get("/courier-auth")
    def trigger_auth():
        raise CourierAuthError("Invalid bearer token")

    test_app.include_router(router)

    # 1. ValidationError
    resp = client.get("/test-errors/validation")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Invalid order parameters"
    assert body["error"]["details"] == {"field": "items"}
    assert "request_id" in body["error"]
    assert resp.headers["X-Request-ID"] == body["error"]["request_id"]

    # 2. OrderNotFoundError
    resp = client.get("/test-errors/not-found")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "ORDER_NOT_FOUND"
    assert "ORD-NOTFOUND" in body["error"]["message"]

    # 3. DuplicateOrderError
    resp = client.get("/test-errors/duplicate")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "DUPLICATE_ORDER"

    # 4. UnsupportedCourierError
    resp = client.get("/test-errors/unsupported-courier")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "UNSUPPORTED_COURIER"

    # 5. CourierTimeoutError
    resp = client.get("/test-errors/courier-timeout")
    assert resp.status_code == 504
    body = resp.json()
    assert body["error"]["code"] == "COURIER_TIMEOUT"

    # 6. CourierAuthError
    resp = client.get("/test-errors/courier-auth")
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "COURIER_AUTH_ERROR"


def test_request_validation_error_envelope(test_app, client):
    """Verify that FastAPI / Pydantic validation errors return standardized VALIDATION_ERROR envelope."""
    router = APIRouter(prefix="/test-pydantic")

    class SimpleReq(BaseModel):
        name: str = Field(..., min_length=2)
        count: int = Field(..., ge=1)

    @router.post("/validate")
    def sample_endpoint(payload: SimpleReq):
        return {"received": payload.name}

    test_app.include_router(router)

    # Send missing body
    resp = client.post("/test-pydantic/validate", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "fields" in body["error"]["details"]
    assert len(body["error"]["details"]["fields"]) >= 2

    # Send invalid field values
    resp2 = client.post("/test-pydantic/validate", json={"name": "a", "count": 0})
    assert resp2.status_code == 400
    body2 = resp2.json()
    assert body2["error"]["code"] == "VALIDATION_ERROR"


def test_unhandled_exception_handling(test_app, client):
    """Verify unhandled exceptions trigger HTTP 500 INTERNAL_ERROR without leaking raw tracebacks."""
    router = APIRouter(prefix="/test-crash")

    @router.get("/fail")
    def fail_endpoint():
        raise RuntimeError("Secret internal failure detail that must not leak")

    test_app.include_router(router)

    resp = client.get("/test-crash/fail")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "internal server error" in body["error"]["message"].lower()
    assert "Secret internal failure" not in body["error"]["message"]
    assert "request_id" in body["error"]


def test_request_id_propagation(client):
    """Verify that custom X-Request-ID provided in request headers is preserved in error responses."""
    custom_id = "trace-custom-uuid-12345"
    resp = client.get("/non-existent-endpoint", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["request_id"] == custom_id
    assert resp.headers["X-Request-ID"] == custom_id


def test_method_not_allowed_error_envelope(client):
    """Verify standard error envelope on HTTP 405 Method Not Allowed."""
    resp = client.post("/health")  # /health only accepts GET
    assert resp.status_code == 405
    body = resp.json()
    assert body["error"]["code"] == "HTTP_405"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_async_client_health(async_client):
    """Verify that async_client works properly with health endpoint."""
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "X-Request-ID" in resp.headers


def test_config_get_settings():
    """Verify get_settings returns Settings instance with defaults."""
    from app.config import Settings, get_settings

    cfg = get_settings()
    assert isinstance(cfg, Settings)
    assert cfg.APP_NAME == "Courier Integration Platform"

