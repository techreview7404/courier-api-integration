"""Top-level tests for Order lifecycle endpoints and tracking history immutability.

Covers:
- POST /api/v1/orders and POST /orders
- GET /api/v1/orders/{order_id}/track and GET /orders/{order_id}/track
- POST /api/v1/orders/{order_id}/cancel and POST /orders/{order_id}/cancel
- Immutable append-only tracking history
- Normalized error envelopes across invalid requests, unknown couriers, and downstream failures
"""

import uuid
import pytest
from sqlalchemy import select

from app.models.order import Order, TrackingHistory


def _unique_order_id(prefix: str = "ORD-TEST") -> str:
    """Generate unique order ID for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _sample_payload(order_id: str, courier: str = "mock", **kwargs) -> dict:
    """Construct sample order payload."""
    payload = {
        "order_id": order_id,
        "courier_partner": courier,
        "customer": {
            "name": kwargs.get("customer_name", "Jane Logistic"),
            "phone": "9876543210",
            "address": "42 Delivery Crescent",
            "city": "Mumbai",
            "state": "MH",
            "pincode": "400001",
        },
        "items": [
            {"name": "Item One", "quantity": 1, "price": 450.0},
            {"name": "Item Two", "quantity": 2, "price": 120.0},
        ],
    }
    return payload


# ============================================================================
# 1. POST /orders and POST /api/v1/orders (Creation)
# ============================================================================


def test_post_orders_api_v1_success(client):
    """Verify standard order creation via /api/v1/orders returns 201 with normalized schema."""
    oid = _unique_order_id("ORD-V1-CREATE")
    payload = _sample_payload(oid)

    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (200, 201)
    data = res.json()
    assert data["order_id"] == oid
    assert data["courier_partner"].lower() == "mock"
    assert data["status"] == "CREATED"
    assert data["awb_number"] is not None
    assert data["courier_order_id"] is not None


def test_post_orders_direct_path_success(client):
    """Verify order creation via direct /orders path functions identically."""
    oid = _unique_order_id("ORD-DIR-CREATE")
    payload = _sample_payload(oid)

    res = client.post("/orders", json=payload)
    assert res.status_code in (200, 201)
    data = res.json()
    assert data["order_id"] == oid
    assert data["courier_partner"].lower() == "mock"


def test_post_orders_creates_initial_tracking_history(client, db_session):
    """Verify order creation appends initial CREATED event to tracking_history."""
    oid = _unique_order_id("ORD-INIT-TRACK")
    payload = _sample_payload(oid)

    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (200, 201)

    events = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == oid)
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].status == "CREATED"
    assert events[0].raw_payload is not None


def test_post_orders_validation_error_missing_fields(client):
    """Verify request with missing mandatory fields returns 400 VALIDATION_ERROR envelope."""
    res = client.post("/api/v1/orders", json={"order_id": "ORD-BAD"})
    assert res.status_code == 400
    err = res.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert "request_id" in err


def test_post_orders_validation_error_empty_items(client):
    """Verify order with empty items list returns 400 VALIDATION_ERROR envelope."""
    payload = {
        "order_id": _unique_order_id("ORD-NO-ITEMS"),
        "courier_partner": "mock",
        "customer": {"name": "Test", "phone": "1234567890", "address": "Addr"},
        "items": [],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_post_orders_unsupported_courier(client):
    """Verify order specifying unknown courier returns 400 UNSUPPORTED_COURIER."""
    oid = _unique_order_id("ORD-UNKNOWN-COURIER")
    payload = _sample_payload(oid, courier="speedy_unknown_express")

    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code == 400
    err = res.json()["error"]
    assert err["code"] == "UNSUPPORTED_COURIER"


def test_post_orders_simulated_courier_timeout(client):
    """Verify courier timeout simulation returns 504 COURIER_TIMEOUT envelope."""
    oid = _unique_order_id("ORD-TO")
    payload = _sample_payload(oid, customer_name="SIMULATE_TIMEOUT")

    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code == 504
    err = res.json()["error"]
    assert err["code"] == "COURIER_TIMEOUT"


def test_post_orders_simulated_courier_5xx(client):
    """Verify courier 5xx simulation returns 502 COURIER_ERROR envelope."""
    oid = _unique_order_id("ORD-5XX")
    payload = _sample_payload(oid, customer_name="SIMULATE_5XX")

    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code == 502
    err = res.json()["error"]
    assert err["code"] == "COURIER_ERROR"


# ============================================================================
# 2. GET /orders/{order_id}/track (Tracking & Immutability)
# ============================================================================


def test_track_order_success(client):
    """Verify tracking returns status, courier details, and history list."""
    oid = _unique_order_id("ORD-TRACK-OK")
    client.post("/api/v1/orders", json=_sample_payload(oid))

    res = client.get(f"/api/v1/orders/{oid}/track")
    assert res.status_code == 200
    data = res.json()
    assert data["order_id"] == oid
    assert data["status"] in [
        "CREATED",
        "PICKED_UP",
        "IN_TRANSIT",
        "DELIVERED",
        "CANCELLED",
        "FAILED",
    ]
    assert "history" in data
    assert len(data["history"]) >= 1


def test_track_order_direct_path(client):
    """Verify tracking via direct /orders/{id}/track path works identically."""
    oid = _unique_order_id("ORD-TRACK-DIR")
    client.post("/orders", json=_sample_payload(oid))

    res = client.get(f"/orders/{oid}/track")
    assert res.status_code == 200
    assert res.json()["order_id"] == oid


def test_track_order_nonexistent_returns_404(client):
    """Verify tracking a non-existent order returns 404 ORDER_NOT_FOUND envelope."""
    res = client.get("/api/v1/orders/ORD-NONEXISTENT-9999/track")
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "ORDER_NOT_FOUND"


def test_tracking_history_immutability(client, db_session):
    """Verify tracking history is strictly append-only and preserves previous records unchanged."""
    oid = _unique_order_id("ORD-TRACK-IMMUTABLE")
    client.post("/api/v1/orders", json=_sample_payload(oid))

    initial_events = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == oid).order_by(TrackingHistory.id)
        )
        .scalars()
        .all()
    )
    assert len(initial_events) == 1
    first_id = initial_events[0].id
    first_status = initial_events[0].status
    first_timestamp = initial_events[0].created_at

    # Track 3 times
    client.get(f"/api/v1/orders/{oid}/track")
    client.get(f"/api/v1/orders/{oid}/track")
    client.get(f"/api/v1/orders/{oid}/track")

    all_events = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == oid).order_by(TrackingHistory.id)
        )
        .scalars()
        .all()
    )

    # Historical entries accumulated without overwriting
    assert len(all_events) >= 2
    # The first event remains completely unmutated
    assert all_events[0].id == first_id
    assert all_events[0].status == first_status
    assert all_events[0].created_at == first_timestamp

    # Verify strictly monotonic IDs and non-decreasing timestamps
    for i in range(len(all_events) - 1):
        assert all_events[i].id < all_events[i + 1].id
        assert all_events[i].created_at <= all_events[i + 1].created_at


# ============================================================================
# 3. POST /orders/{order_id}/cancel (Cancellation)
# ============================================================================


def test_cancel_order_success(client, db_session):
    """Verify order cancellation transitions status to CANCELLED and adds to history."""
    oid = _unique_order_id("ORD-CANCEL-OK")
    client.post("/api/v1/orders", json=_sample_payload(oid))

    res = client.post(f"/api/v1/orders/{oid}/cancel")
    assert res.status_code == 200
    data = res.json()
    assert data["order_id"] == oid
    assert data["status"] == "CANCELLED"

    # Verify DB order state
    order = db_session.execute(
        select(Order).where(Order.order_id == oid)
    ).scalar_one()
    assert order.status == "CANCELLED"

    # Verify tracking history contains CANCELLED
    history = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == oid)
        )
        .scalars()
        .all()
    )
    statuses = [h.status for h in history]
    assert "CANCELLED" in statuses


def test_cancel_order_direct_path(client):
    """Verify cancellation via direct /orders/{id}/cancel path works identically."""
    oid = _unique_order_id("ORD-CANCEL-DIR")
    client.post("/orders", json=_sample_payload(oid))

    res = client.post(f"/orders/{oid}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "CANCELLED"


def test_cancel_order_repeated_cancellation(client):
    """Verify repeated cancellation call succeeds idempotently without error."""
    oid = _unique_order_id("ORD-CANCEL-REP")
    client.post("/api/v1/orders", json=_sample_payload(oid))

    res1 = client.post(f"/api/v1/orders/{oid}/cancel")
    assert res1.status_code == 200
    assert res1.json()["status"] == "CANCELLED"

    res2 = client.post(f"/api/v1/orders/{oid}/cancel")
    assert res2.status_code == 200
    assert res2.json()["status"] == "CANCELLED"


def test_cancel_order_nonexistent_returns_404(client):
    """Verify cancelling non-existent order returns 404 ORDER_NOT_FOUND envelope."""
    res = client.post("/api/v1/orders/ORD-GHOST-CANCEL-999/cancel")
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "ORDER_NOT_FOUND"


def test_cancel_order_subsequent_tracking_returns_cancelled(client):
    """Verify tracking an order after cancellation reports CANCELLED status."""
    oid = _unique_order_id("ORD-CANCEL-TRACK")
    client.post("/api/v1/orders", json=_sample_payload(oid))
    client.post(f"/api/v1/orders/{oid}/cancel")

    track_res = client.get(f"/api/v1/orders/{oid}/track")
    assert track_res.status_code == 200
    assert track_res.json()["status"] == "CANCELLED"


# ============================================================================
# 4. GET /orders/{order_id} (Direct Order Retrieval)
# ============================================================================


def test_get_order_by_id_success(client):
    """Verify GET /api/v1/orders/{order_id} returns order details."""
    oid = _unique_order_id("ORD-GET-OK")
    client.post("/api/v1/orders", json=_sample_payload(oid))

    res = client.get(f"/api/v1/orders/{oid}")
    assert res.status_code == 200
    data = res.json()
    assert data["order_id"] == oid
    assert data["courier_partner"] == "mock"
    assert data["status"] == "CREATED"


def test_get_order_by_id_nonexistent(client):
    """Verify GET /api/v1/orders/{order_id} returns 404 for missing order."""
    res = client.get("/api/v1/orders/ORD-NONEXISTENT-GET")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ORDER_NOT_FOUND"

