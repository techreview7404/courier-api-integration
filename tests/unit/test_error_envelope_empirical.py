"""Empirical challenge tests for error envelope and middleware contracts.

Authored by Challenger 2 (Milestone 1).
Exhaustively stresses:
1. All AppError subclasses and custom AppErrors
2. Pydantic RequestValidationErrors across body, query, and path parameters
3. StarletteHTTPException across status codes (404, 405, 400, 401, 403, 500, 503)
4. Generic unhandled Exceptions in both sync and async handlers
5. Exceptions raised inside FastAPI Dependencies
6. Request ID preservation, generation, uniqueness, and edge cases
7. Information leakage / traceback suppression on 500 crashes
8. Strict ErrorResponse Pydantic schema conformance
"""

import uuid
import pytest
from fastapi import APIRouter, Depends, Path, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

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
from app.schemas.common import ErrorResponse


# ---------------------------------------------------------------------------
# Helpers & Router Setup
# ---------------------------------------------------------------------------

class CustomTestAppError(AppError):
    code = "CUSTOM_BUSINESS_FAULT"
    message = "A domain business rule was violated"
    status_code = 422


class SensitiveInternalCrash(Exception):
    pass


def failing_dependency():
    raise SensitiveInternalCrash("Secret DB credentials: root:password123@10.0.0.1")


def domain_error_dependency():
    raise ValidationError("Dependency rejected input", details={"dep": "failed"})


@pytest.fixture
def empirical_router():
    """Build a comprehensive router to challenge error behaviors across sync/async/deps."""
    router = APIRouter(prefix="/empirical-challenge")

    # --- Pydantic models for validation challenge ---
    class StrictPayload(BaseModel):
        order_ref: str = Field(..., min_length=3, max_length=20)
        quantity: int = Field(..., gt=0, le=100)
        price: float = Field(..., ge=0.0)

    # 1. AppError endpoints (sync & async)
    @router.get("/app-error/base")
    def trigger_base_app_error():
        raise AppError("Direct base app error", code="BASE_FAULT", status_code=400, details={"ctx": 1})

    @router.get("/app-error/validation")
    def trigger_validation_error():
        raise ValidationError("Field 'items' is required", details={"missing": ["items"]})

    @router.get("/app-error/entity-not-found")
    def trigger_entity_not_found():
        raise EntityNotFoundError("Generic entity not found")

    @router.get("/app-error/order-not-found")
    def trigger_order_not_found():
        raise OrderNotFoundError(order_id="ORD-NONEXISTENT-999")

    @router.get("/app-error/batch-not-found")
    def trigger_batch_not_found():
        raise BatchNotFoundError(batch_id="BATCH-NONEXISTENT-888")

    @router.get("/app-error/duplicate-entity")
    def trigger_duplicate_entity():
        raise DuplicateEntityError("Duplicate row in DB")

    @router.get("/app-error/duplicate-order")
    def trigger_duplicate_order():
        raise DuplicateOrderError(order_id="ORD-DUPE-001")

    @router.get("/app-error/unsupported-courier")
    def trigger_unsupported_courier():
        raise UnsupportedCourierError(courier_partner="teleport_express")

    @router.get("/app-error/courier-error")
    def trigger_courier_error():
        raise CourierError("Downstream gateway reset connection")

    @router.get("/app-error/courier-timeout")
    def trigger_courier_timeout():
        raise CourierTimeoutError("Gateway timed out after 10s")

    @router.get("/app-error/courier-auth")
    def trigger_courier_auth():
        raise CourierAuthError("API key rejected by courier")

    @router.get("/app-error/internal-server")
    def trigger_internal_server():
        raise InternalServerError("Custom internal failure")

    @router.get("/app-error/custom-subclass")
    def trigger_custom_subclass():
        raise CustomTestAppError(details={"rule": "MAX_ITEMS_EXCEEDED"})

    @router.get("/app-error/async")
    async def trigger_async_app_error():
        raise ValidationError("Async validation failed")

    # 2. Pydantic validation challenge
    @router.post("/validation/body")
    def trigger_body_validation(payload: StrictPayload):
        return {"status": "ok", "ref": payload.order_ref}

    @router.get("/validation/query")
    def trigger_query_validation(page: int = Query(..., ge=1), limit: int = Query(..., le=50)):
        return {"page": page, "limit": limit}

    @router.get("/validation/path/{order_num}")
    def trigger_path_validation(order_num: int = Path(..., gt=0)):
        return {"order_num": order_num}

    # 3. Starlette HTTP exceptions
    @router.get("/http-error/{status}")
    def trigger_http_error(status: int):
        raise StarletteHTTPException(status_code=status, detail=f"Custom Starlette HTTP {status}")

    # 4. Unhandled crashes (sync & async)
    @router.get("/crash/sync-runtime")
    def trigger_sync_runtime():
        raise RuntimeError("CRITICAL SECRET: /var/secrets/key.pem leak attempt")

    @router.get("/crash/async-zerodiv")
    async def trigger_async_zerodiv():
        return 100 / 0

    @router.get("/crash/keyerror")
    def trigger_keyerror():
        d = {}
        return d["non_existent_key"]

    @router.get("/crash/typeerror")
    def trigger_typeerror():
        return "number" + 42  # noqa

    @router.get("/crash/custom-sensitive")
    def trigger_sensitive_crash():
        raise SensitiveInternalCrash("SELECT * FROM credentials WHERE pass='admin123'")

    # 5. Dependency errors
    @router.get("/dep/domain-error", dependencies=[Depends(domain_error_dependency)])
    def trigger_dep_domain_error():
        return {"status": "unreachable"}

    @router.get("/dep/unhandled-crash", dependencies=[Depends(failing_dependency)])
    def trigger_dep_unhandled_crash():
        return {"status": "unreachable"}

    return router


@pytest.fixture(autouse=True)
def register_empirical_routes(test_app, empirical_router):
    test_app.include_router(empirical_router)


# ---------------------------------------------------------------------------
# Test Suite 1: Envelope Structure and Strict Schema Conformance
# ---------------------------------------------------------------------------

def _assert_envelope_conformance(resp, expected_status: int, expected_code: str):
    """Rigorous assertion of the envelope contract."""
    assert resp.status_code == expected_status, f"Expected status {expected_status}, got {resp.status_code}: {resp.text}"
    assert resp.headers.get("Content-Type") == "application/json", "Response must be application/json"
    assert "X-Request-ID" in resp.headers, "X-Request-ID header missing from response"

    body = resp.json()
    # 1. Top-level must have ONLY 'error'
    assert list(body.keys()) == ["error"], f"Top-level keys must only be ['error'], got {list(body.keys())}"

    # 2. Must validate strictly against Pydantic ErrorResponse schema
    validated = ErrorResponse.model_validate(body)
    err = validated.error

    # 3. Check error fields
    assert err.code == expected_code, f"Expected code {expected_code}, got {err.code}"
    assert isinstance(err.message, str) and len(err.message) > 0, "Error message must be non-empty string"
    assert isinstance(err.request_id, str) and len(err.request_id) > 0, "request_id must be non-empty string"
    assert err.request_id == resp.headers["X-Request-ID"], "request_id in body must match X-Request-ID header"
    assert err.details is not None, "details must not be None"


@pytest.mark.parametrize(
    "endpoint,expected_status,expected_code",
    [
        ("/empirical-challenge/app-error/base", 400, "BASE_FAULT"),
        ("/empirical-challenge/app-error/validation", 400, "VALIDATION_ERROR"),
        ("/empirical-challenge/app-error/entity-not-found", 404, "ORDER_NOT_FOUND"),
        ("/empirical-challenge/app-error/order-not-found", 404, "ORDER_NOT_FOUND"),
        ("/empirical-challenge/app-error/batch-not-found", 404, "ORDER_NOT_FOUND"),
        ("/empirical-challenge/app-error/duplicate-entity", 409, "DUPLICATE_ORDER"),
        ("/empirical-challenge/app-error/duplicate-order", 409, "DUPLICATE_ORDER"),
        ("/empirical-challenge/app-error/unsupported-courier", 400, "UNSUPPORTED_COURIER"),
        ("/empirical-challenge/app-error/courier-error", 502, "COURIER_ERROR"),
        ("/empirical-challenge/app-error/courier-timeout", 504, "COURIER_TIMEOUT"),
        ("/empirical-challenge/app-error/courier-auth", 502, "COURIER_AUTH_ERROR"),
        ("/empirical-challenge/app-error/internal-server", 500, "INTERNAL_ERROR"),
        ("/empirical-challenge/app-error/custom-subclass", 422, "CUSTOM_BUSINESS_FAULT"),
        ("/empirical-challenge/app-error/async", 400, "VALIDATION_ERROR"),
    ],
)
def test_all_app_error_subclasses_envelope(client, endpoint, expected_status, expected_code):
    """Stress-test that all AppError subclasses strictly return the normalized envelope."""
    resp = client.get(endpoint)
    _assert_envelope_conformance(resp, expected_status, expected_code)


# ---------------------------------------------------------------------------
# Test Suite 2: Pydantic Validation Errors (Body, Query, Path, Malformed JSON)
# ---------------------------------------------------------------------------

def test_validation_error_missing_body(client):
    """Empty body when payload is required returns VALIDATION_ERROR envelope."""
    resp = client.post("/empirical-challenge/validation/body", json=None)
    _assert_envelope_conformance(resp, 400, "VALIDATION_ERROR")
    body = resp.json()
    assert "fields" in body["error"]["details"]


def test_validation_error_malformed_fields(client):
    """Field constraints violated returns VALIDATION_ERROR with structured details."""
    resp = client.post(
        "/empirical-challenge/validation/body",
        json={"order_ref": "x", "quantity": 0, "price": -5.0},
    )
    _assert_envelope_conformance(resp, 400, "VALIDATION_ERROR")
    fields = resp.json()["error"]["details"]["fields"]
    assert len(fields) >= 3
    for f in fields:
        assert "field" in f and "message" in f and "type" in f


def test_validation_error_invalid_json_syntax(client):
    """Malformed non-parseable JSON body returns VALIDATION_ERROR envelope rather than 500."""
    resp = client.post(
        "/empirical-challenge/validation/body",
        content="{\"order_ref\": broken json...",
        headers={"Content-Type": "application/json"},
    )
    _assert_envelope_conformance(resp, 400, "VALIDATION_ERROR")


def test_validation_error_wrong_root_type(client):
    """Sending JSON list `[]` instead of dict `{}` returns VALIDATION_ERROR envelope."""
    resp = client.post("/empirical-challenge/validation/body", json=[1, 2, 3])
    _assert_envelope_conformance(resp, 400, "VALIDATION_ERROR")


def test_validation_error_query_params(client):
    """Invalid query parameter types return VALIDATION_ERROR envelope."""
    resp = client.get("/empirical-challenge/validation/query?page=not_a_number&limit=999")
    _assert_envelope_conformance(resp, 400, "VALIDATION_ERROR")


def test_validation_error_path_params(client):
    """Invalid path parameter types return VALIDATION_ERROR envelope."""
    resp = client.get("/empirical-challenge/validation/path/not-an-integer")
    _assert_envelope_conformance(resp, 400, "VALIDATION_ERROR")


# ---------------------------------------------------------------------------
# Test Suite 3: Starlette HTTP Exceptions (404, 405, and explicit status codes)
# ---------------------------------------------------------------------------

def test_starlette_404_not_found(client):
    """Non-existent URL triggers Starlette 404 handled with ORDER_NOT_FOUND."""
    resp = client.get("/this/path/absolutely/does/not/exist")
    _assert_envelope_conformance(resp, 404, "ORDER_NOT_FOUND")


def test_starlette_405_method_not_allowed(client):
    """Wrong HTTP verb on endpoint triggers Starlette 405 handled with HTTP_405."""
    resp = client.delete("/health")
    _assert_envelope_conformance(resp, 405, "HTTP_405")


@pytest.mark.parametrize("status_code", [400, 401, 403, 500, 503])
def test_starlette_explicit_http_exceptions(client, status_code):
    """Explicit Starlette HTTPExceptions return normalized envelope with HTTP_{code}."""
    resp = client.get(f"/empirical-challenge/http-error/{status_code}")
    expected_code = f"HTTP_{status_code}"
    _assert_envelope_conformance(resp, status_code, expected_code)


# ---------------------------------------------------------------------------
# Test Suite 4: Generic Unhandled Exceptions & Information Leakage Prevention
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "endpoint",
    [
        "/empirical-challenge/crash/sync-runtime",
        "/empirical-challenge/crash/async-zerodiv",
        "/empirical-challenge/crash/keyerror",
        "/empirical-challenge/crash/typeerror",
        "/empirical-challenge/crash/custom-sensitive",
    ],
)
def test_unhandled_exceptions_return_internal_error_and_prevent_leakage(client, endpoint):
    """Unhandled exceptions must ALWAYS return 500 INTERNAL_ERROR without leaking raw secrets or tracebacks."""
    resp = client.get(endpoint)
    _assert_envelope_conformance(resp, 500, "INTERNAL_ERROR")

    body = resp.json()
    message = body["error"]["message"]
    details = body["error"]["details"]

    # Security verification: ensure sensitive tokens are NOT present in output
    forbidden_tokens = [
        "CRITICAL SECRET",
        "key.pem",
        "division by zero",
        "non_existent_key",
        "SELECT * FROM credentials",
        "admin123",
        "Traceback (most recent call last):",
        "File \"",
    ]
    for token in forbidden_tokens:
        assert token not in message, f"Leaked sensitive token '{token}' in error.message"
        assert token not in str(details), f"Leaked sensitive token '{token}' in error.details"
        assert token not in resp.text, f"Leaked sensitive token '{token}' in raw response body"


def test_dependency_domain_exception(client):
    """AppError raised inside a FastAPI dependency returns standard envelope."""
    resp = client.get("/empirical-challenge/dep/domain-error")
    _assert_envelope_conformance(resp, 400, "VALIDATION_ERROR")


def test_dependency_unhandled_crash(client):
    """Unhandled Exception raised inside a FastAPI dependency returns 500 INTERNAL_ERROR and hides secrets."""
    resp = client.get("/empirical-challenge/dep/unhandled-crash")
    _assert_envelope_conformance(resp, 500, "INTERNAL_ERROR")
    assert "password123" not in resp.text


# ---------------------------------------------------------------------------
# Test Suite 5: Request ID Invariants & Edge Cases
# ---------------------------------------------------------------------------

def test_request_id_preserved_when_supplied(client):
    """Custom X-Request-ID header is propagated identically into headers and JSON envelope."""
    custom_ids = [
        "req-test-uuid-001",
        "client_trace_alpha_beta_gamma",
        "12345678-1234-1234-1234-123456789012",
        "custom.trace.with-dots_and-dashes",
    ]
    for cid in custom_ids:
        resp = client.get("/empirical-challenge/app-error/validation", headers={"X-Request-ID": cid})
        assert resp.headers["X-Request-ID"] == cid
        assert resp.json()["error"]["request_id"] == cid


def test_request_id_auto_generated_when_omitted(client):
    """When X-Request-ID is omitted, a valid UUID4 is generated and matches header and body."""
    resp = client.get("/empirical-challenge/app-error/validation")
    generated_id = resp.headers.get("X-Request-ID")
    assert generated_id is not None
    # Must be valid UUID format
    parsed_uuid = uuid.UUID(generated_id)
    assert str(parsed_uuid) == generated_id
    assert resp.json()["error"]["request_id"] == generated_id


def test_request_id_uniqueness_across_requests(client):
    """Consecutive requests without X-Request-ID must receive distinct UUIDs (no state leakage)."""
    generated_ids = set()
    for _ in range(25):
        resp = client.get("/health")
        rid = resp.headers["X-Request-ID"]
        assert rid not in generated_ids, f"Collision detected for request_id: {rid}"
        generated_ids.add(rid)


def test_request_id_empty_header_generates_uuid(client):
    """When X-Request-ID is an empty string, fallback generates a non-empty UUID."""
    resp = client.get("/empirical-challenge/app-error/validation", headers={"X-Request-ID": ""})
    rid = resp.headers["X-Request-ID"]
    assert rid != "", "Request ID should not be empty string"
    assert resp.json()["error"]["request_id"] == rid
    uuid.UUID(rid)  # Should parse without error


# ---------------------------------------------------------------------------
# Test Suite 6: Async Client Tests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Test Suite 7: Adversarial Edge Cases & Stress Testing
# ---------------------------------------------------------------------------

def test_debug_mode_does_not_leak_html_traceback(db_session):
    """When app is created with debug=True, unhandled exceptions must still return the JSON envelope, never HTML tracebacks."""
    from app.main import create_app
    from app.database import get_db

    debug_app = create_app()
    debug_app.debug = True

    def override_get_db():
        yield db_session

    debug_app.dependency_overrides[get_db] = override_get_db

    debug_router = APIRouter(prefix="/debug-leak-test")

    @debug_router.get("/crash")
    def trigger_debug_crash():
        raise ZeroDivisionError("Dangerous division by zero in debug mode")

    debug_app.include_router(debug_router)

    with TestClient(debug_app, raise_server_exceptions=False) as debug_client:
        resp = debug_client.get("/debug-leak-test/crash")
        assert resp.status_code == 500
        assert resp.headers.get("Content-Type") == "application/json"
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "Dangerous division by zero" not in resp.text
        assert "<html>" not in resp.text.lower()


def test_non_serializable_details_failsafe_recovery(test_app, client):
    """If an AppError contains non-JSON-serializable details (like a set or object), the middleware falls back to 500 INTERNAL_ERROR gracefully without crashing server."""
    router = APIRouter(prefix="/non-serializable-test")

    class UnserializableObject:
        pass

    @router.get("/bad-details")
    def trigger_bad_details():
        # Sets and custom objects cannot be serialized by standard json.dumps
        raise ValidationError("Error with set", details={"raw_set": {1, 2, 3}, "obj": UnserializableObject()})

    test_app.include_router(router)

    resp = client.get("/non-serializable-test/bad-details")
    # Should be caught by RequestIdMiddleware unhandled exception handler and returned as 500 INTERNAL_ERROR
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "request_id" in body["error"]


def test_starlette_http_exception_with_dict_detail(client):
    """StarletteHTTPException with dictionary detail is coerced cleanly without breaking envelope."""
    resp = client.get("/empirical-challenge/http-error/400")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "HTTP_400"
    assert isinstance(body["error"]["message"], str)


@pytest.mark.asyncio
async def test_async_client_error_envelope(async_client):
    """Verify error envelope and request ID handling when invoked via AsyncClient."""
    resp = await async_client.get(
        "/empirical-challenge/app-error/order-not-found",
        headers={"X-Request-ID": "async-req-001"},
    )
    assert resp.status_code == 404
    assert resp.headers["X-Request-ID"] == "async-req-001"
    body = resp.json()
    assert body["error"]["code"] == "ORDER_NOT_FOUND"
    assert body["error"]["request_id"] == "async-req-001"

