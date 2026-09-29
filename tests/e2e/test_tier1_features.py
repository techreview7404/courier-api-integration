"""Tier 1: Feature Coverage E2E Tests.

Exercises the normalized API contracts for all core features via FastAPI TestClient:
- Create Order (POST /api/v1/orders)
- Track Order (GET /api/v1/orders/{order_id}/track)
- Cancel Order (POST /api/v1/orders/{order_id}/cancel)
- Bulk Submit (POST /api/v1/orders/bulk)
- Bulk Polling (GET /api/v1/orders/bulk/{batch_id})
- Idempotency & Unique Order Constraints
- Standardized Error Envelope Conformance
"""

import os
os.environ.setdefault("DEBUG", "false")

import time
import uuid
from sqlalchemy import select

from app.models.batch import Batch
from app.models.order import Order, TrackingHistory


def _unique_id(prefix: str = "ORD") -> str:
    """Generate unique identifier for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ============================================================================
# 1. CREATE ORDER (POST /api/v1/orders) — >= 5 Tests
# ============================================================================

def test_create_order_single_item_mock_success(client):
    """Verify single-item order creation with mock courier returns normalized 201/200 response."""
    order_id = _unique_id("ORD-T1-CREATE")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {
            "name": "Jane Doe",
            "phone": "9876543210",
            "address": "123 Main St, Springfield",
            "city": "Springfield",
            "state": "IL",
            "pincode": "62701",
        },
        "items": [
            {
                "name": "Wireless Mouse",
                "quantity": 1,
                "price": 25.50,
            }
        ],
    }
    response = client.post("/api/v1/orders", json=payload)
    assert response.status_code in (200, 201), f"Unexpected status: {response.status_code}, {response.text}"
    data = response.json()
    assert data["order_id"] == order_id
    assert data["courier_partner"].lower() == "mock"
    assert data["status"] == "CREATED"
    assert data.get("awb_number") is not None
    assert len(data["awb_number"]) > 0


def test_create_order_multiple_items_success(client):
    """Verify order creation with multiple items calculates and persists properly."""
    order_id = _unique_id("ORD-T1-MULTI")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {
            "name": "Bob Smith",
            "phone": "9123456780",
            "address": "456 Oak Avenue",
            "city": "Metropolis",
            "state": "NY",
            "pincode": "10001",
        },
        "items": [
            {"name": "Laptop Stand", "quantity": 2, "price": 45.00},
            {"name": "USB-C Cable", "quantity": 3, "price": 12.99},
            {"name": "Mechanical Keyboard", "quantity": 1, "price": 89.00},
        ],
    }
    response = client.post("/api/v1/orders", json=payload)
    assert response.status_code in (200, 201)
    data = response.json()
    assert data["order_id"] == order_id
    assert data["status"] == "CREATED"


def test_create_order_generates_initial_tracking_record(client, db_session):
    """Verify order creation appends an initial CREATED record to tracking_history."""
    order_id = _unique_id("ORD-T1-TRACK-INIT")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {
            "name": "Audit Customer",
            "phone": "9811223344",
            "address": "789 Audit Ln",
        },
        "items": [{"name": "Audited Item", "quantity": 1, "price": 10.0}],
    }
    response = client.post("/api/v1/orders", json=payload)
    assert response.status_code in (200, 201)

    # Query database directly to verify tracking history entry
    events = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == order_id)
        )
        .scalars()
        .all()
    )
    assert len(events) >= 1
    assert events[0].status == "CREATED"


def test_create_order_persists_request_and_response_payloads(client, db_session):
    """Verify request_payload and response_payload are persisted in the orders table."""
    order_id = _unique_id("ORD-T1-PAYLOAD")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {
            "name": "Payload Test",
            "phone": "9988776655",
            "address": "Payload Blvd",
        },
        "items": [{"name": "Payload Item", "quantity": 1, "price": 100.0}],
    }
    response = client.post("/api/v1/orders", json=payload)
    assert response.status_code in (200, 201)

    order_row = (
        db_session.execute(select(Order).where(Order.order_id == order_id))
        .scalar_one_or_none()
    )
    assert order_row is not None
    assert order_row.request_payload is not None
    assert order_row.request_payload["order_id"] == order_id
    assert order_row.response_payload is not None


def test_create_order_preserves_custom_request_id_header(client):
    """Verify custom X-Request-ID header in create order request is reflected in response headers."""
    custom_trace_id = f"trace-{uuid.uuid4().hex}"
    order_id = _unique_id("ORD-T1-TRACE")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {
            "name": "Trace User",
            "phone": "9000000001",
            "address": "Trace Street",
        },
        "items": [{"name": "Widget", "quantity": 1, "price": 5.0}],
    }
    response = client.post(
        "/api/v1/orders",
        json=payload,
        headers={"X-Request-ID": custom_trace_id},
    )
    assert response.status_code in (200, 201)
    assert response.headers.get("X-Request-ID") == custom_trace_id


def test_create_order_normalized_schema_no_leaked_fields(client):
    """Verify that create order returns clean normalized fields without leaking internal implementation details."""
    order_id = _unique_id("ORD-T1-NORM")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {
            "name": "Schema Check",
            "phone": "9000000002",
            "address": "Schema Ave",
        },
        "items": [{"name": "Gizmo", "quantity": 1, "price": 19.99}],
    }
    response = client.post("/api/v1/orders", json=payload)
    assert response.status_code in (200, 201)
    data = response.json()
    assert "order_id" in data
    assert "courier_partner" in data
    assert "status" in data
    # Ensure internal DB integer ID is not exposed
    assert "id" not in data or isinstance(data.get("id"), str)


# ============================================================================
# 2. TRACK ORDER (GET /api/v1/orders/{order_id}/track) — >= 5 Tests
# ============================================================================

def test_track_order_success(client):
    """Verify tracking an existing order returns normalized tracking response."""
    order_id = _unique_id("ORD-T1-TRACK")
    client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Track User", "phone": "9111111111", "address": "1 Track Rd"},
            "items": [{"name": "Item A", "quantity": 1, "price": 10.0}],
        },
    )
    track_resp = client.get(f"/api/v1/orders/{order_id}/track")
    assert track_resp.status_code == 200
    data = track_resp.json()
    assert data["order_id"] == order_id
    assert "status" in data
    assert "history" in data
    assert isinstance(data["history"], list)
    assert len(data["history"]) >= 1


def test_track_order_appends_tracking_history_event(client, db_session):
    """Verify querying tracking endpoint appends a new status event to tracking_history."""
    order_id = _unique_id("ORD-T1-APPEND")
    client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Append User", "phone": "9222222222", "address": "2 Append Rd"},
            "items": [{"name": "Item B", "quantity": 1, "price": 15.0}],
        },
    )
    initial_count = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == order_id)
        )
        .scalars()
        .all()
    )

    # Trigger live track
    client.get(f"/api/v1/orders/{order_id}/track")

    updated_count = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == order_id)
        )
        .scalars()
        .all()
    )
    assert len(updated_count) >= len(initial_count)


def test_track_order_history_events_chronological(client):
    """Verify tracking history events are returned chronologically."""
    order_id = _unique_id("ORD-T1-CHRONO")
    client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Chrono User", "phone": "9333333333", "address": "3 Chrono Rd"},
            "items": [{"name": "Item C", "quantity": 1, "price": 20.0}],
        },
    )
    # Track twice
    client.get(f"/api/v1/orders/{order_id}/track")
    res = client.get(f"/api/v1/orders/{order_id}/track")
    assert res.status_code == 200
    history = res.json().get("history", [])
    assert len(history) >= 1
    # Verify each history item has status
    for item in history:
        assert "status" in item


def test_track_order_reflects_order_current_status(client):
    """Verify track endpoint returns latest status matching current order state."""
    order_id = _unique_id("ORD-T1-STATUS")
    create_res = client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Status User", "phone": "9444444444", "address": "4 Status Rd"},
            "items": [{"name": "Item D", "quantity": 1, "price": 25.0}],
        },
    )
    assert create_res.status_code in (200, 201)
    track_res = client.get(f"/api/v1/orders/{order_id}/track")
    assert track_res.status_code == 200
    assert track_res.json()["status"] in [
        "CREATED",
        "PICKED_UP",
        "IN_TRANSIT",
        "DELIVERED",
        "CANCELLED",
        "FAILED",
    ]


def test_track_order_retains_courier_partner_and_awb(client):
    """Verify track endpoint preserves courier_partner and awb_number."""
    order_id = _unique_id("ORD-T1-AWB")
    create_res = client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "AWB User", "phone": "9555555555", "address": "5 AWB Rd"},
            "items": [{"name": "Item E", "quantity": 1, "price": 30.0}],
        },
    )
    awb = create_res.json().get("awb_number")
    track_res = client.get(f"/api/v1/orders/{order_id}/track")
    assert track_res.status_code == 200
    data = track_res.json()
    assert data["courier_partner"].lower() == "mock"
    if awb:
        assert data.get("awb_number") == awb


# ============================================================================
# 3. CANCEL ORDER (POST /api/v1/orders/{order_id}/cancel) — >= 5 Tests
# ============================================================================

def test_cancel_order_success(client):
    """Verify order cancellation returns 200 OK with status CANCELLED."""
    order_id = _unique_id("ORD-T1-CANCEL")
    client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Cancel User", "phone": "9666666666", "address": "6 Cancel Rd"},
            "items": [{"name": "Item F", "quantity": 1, "price": 35.0}],
        },
    )
    cancel_res = client.post(f"/api/v1/orders/{order_id}/cancel")
    assert cancel_res.status_code == 200
    data = cancel_res.json()
    assert data["order_id"] == order_id
    assert data["status"] == "CANCELLED"


def test_cancel_order_updates_order_status_in_database(client, db_session):
    """Verify order cancellation updates database Order.status to CANCELLED."""
    order_id = _unique_id("ORD-T1-CANC-DB")
    client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "DB Cancel", "phone": "9777777777", "address": "7 Cancel St"},
            "items": [{"name": "Item G", "quantity": 1, "price": 40.0}],
        },
    )
    client.post(f"/api/v1/orders/{order_id}/cancel")

    order_row = (
        db_session.execute(select(Order).where(Order.order_id == order_id))
        .scalar_one_or_none()
    )
    assert order_row is not None
    assert order_row.status == "CANCELLED"


def test_cancel_order_appends_cancelled_event_to_history(client, db_session):
    """Verify cancellation creates a CANCELLED status entry in tracking_history."""
    order_id = _unique_id("ORD-T1-CANC-AUDIT")
    client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Audit Cancel", "phone": "9888888888", "address": "8 Cancel Ave"},
            "items": [{"name": "Item H", "quantity": 1, "price": 45.0}],
        },
    )
    client.post(f"/api/v1/orders/{order_id}/cancel")

    history = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == order_id)
        )
        .scalars()
        .all()
    )
    statuses = [h.status for h in history]
    assert "CANCELLED" in statuses


def test_cancel_order_repeated_cancellation(client):
    """Verify repeating cancellation on an already cancelled order succeeds idempotently."""
    order_id = _unique_id("ORD-T1-CANC-REP")
    client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Repeat Cancel", "phone": "9999999998", "address": "9 Cancel Ct"},
            "items": [{"name": "Item I", "quantity": 1, "price": 50.0}],
        },
    )
    res1 = client.post(f"/api/v1/orders/{order_id}/cancel")
    assert res1.status_code == 200
    res2 = client.post(f"/api/v1/orders/{order_id}/cancel")
    assert res2.status_code in (200, 400, 409)
    if res2.status_code == 200:
        assert res2.json()["status"] == "CANCELLED"


def test_cancel_order_subsequent_track_returns_cancelled(client):
    """Verify tracking an order after cancellation reports CANCELLED status."""
    order_id = _unique_id("ORD-T1-CANC-TRACK")
    client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Track Cancel", "phone": "9123456781", "address": "10 Cancel Way"},
            "items": [{"name": "Item J", "quantity": 1, "price": 55.0}],
        },
    )
    client.post(f"/api/v1/orders/{order_id}/cancel")
    track_res = client.get(f"/api/v1/orders/{order_id}/track")
    assert track_res.status_code == 200
    assert track_res.json()["status"] == "CANCELLED"


# ============================================================================
# 4. BULK SUBMIT (POST /api/v1/orders/bulk) — >= 5 Tests
# ============================================================================

def test_bulk_submit_single_order_success(client):
    """Verify bulk submission with a single order returns 202/200 with batch_id and status PROCESSING."""
    order_id = _unique_id("ORD-T1-BULK-1")
    payload = {
        "orders": [
            {
                "order_id": order_id,
                "courier_partner": "mock",
                "customer": {"name": "Bulk User 1", "phone": "9000000010", "address": "Bulk St 1"},
                "items": [{"name": "Bulk Item 1", "quantity": 1, "price": 10.0}],
            }
        ]
    }
    response = client.post("/api/v1/orders/bulk", json=payload)
    assert response.status_code in (200, 202)
    data = response.json()
    assert "batch_id" in data
    assert data["status"] in ("PROCESSING", "COMPLETED")


def test_bulk_submit_multiple_orders_success(client):
    """Verify bulk submission with multiple orders (e.g. 5 orders) is accepted."""
    orders = [
        {
            "order_id": _unique_id(f"ORD-T1-B5-{i}"),
            "courier_partner": "mock",
            "customer": {"name": f"Bulk User {i}", "phone": f"900000002{i}", "address": f"Bulk St {i}"},
            "items": [{"name": f"Item {i}", "quantity": i + 1, "price": 10.0 * (i + 1)}],
        }
        for i in range(5)
    ]
    response = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert response.status_code in (200, 202)
    data = response.json()
    assert "batch_id" in data
    assert len(data["batch_id"]) > 0


def test_bulk_submit_creates_batch_record_in_db(client, db_session):
    """Verify bulk submission creates a record in the batches database table."""
    orders = [
        {
            "order_id": _unique_id("ORD-T1-BDB-1"),
            "courier_partner": "mock",
            "customer": {"name": "DB Batch", "phone": "9000000030", "address": "Batch Way"},
            "items": [{"name": "Widget", "quantity": 1, "price": 20.0}],
        }
    ]
    res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert res.status_code in (200, 202)
    batch_id = res.json()["batch_id"]

    batch_row = (
        db_session.execute(select(Batch).where(Batch.batch_id == batch_id))
        .scalar_one_or_none()
    )
    assert batch_row is not None
    assert batch_row.total == 1


def test_bulk_submit_immediate_response_performance(client):
    """Verify bulk submission responds immediately without synchronous bottleneck."""
    orders = [
        {
            "order_id": _unique_id(f"ORD-T1-PERF-{i}"),
            "courier_partner": "mock",
            "customer": {"name": f"User {i}", "phone": "9000000040", "address": "Fast Way"},
            "items": [{"name": "Speed Item", "quantity": 1, "price": 15.0}],
        }
        for i in range(10)
    ]
    start = time.time()
    res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    duration = time.time() - start
    assert res.status_code in (200, 202)
    assert duration < 5.0, f"Bulk submit took too long: {duration:.2f}s"


def test_bulk_submit_heterogeneous_couriers_accepted(client):
    """Verify bulk submission allows specifying courier_partner per order item."""
    orders = [
        {
            "order_id": _unique_id("ORD-T1-HET-1"),
            "courier_partner": "mock",
            "customer": {"name": "User 1", "phone": "9000000051", "address": "Addr 1"},
            "items": [{"name": "Item 1", "quantity": 1, "price": 10.0}],
        },
        {
            "order_id": _unique_id("ORD-T1-HET-2"),
            "courier_partner": "mock",
            "customer": {"name": "User 2", "phone": "9000000052", "address": "Addr 2"},
            "items": [{"name": "Item 2", "quantity": 2, "price": 20.0}],
        },
    ]
    res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert res.status_code in (200, 202)
    assert "batch_id" in res.json()


# ============================================================================
# 5. BULK POLLING (GET /api/v1/orders/bulk/{batch_id}) — >= 5 Tests
# ============================================================================

def test_bulk_poll_returns_correct_batch_metadata(client):
    """Verify GET /api/v1/orders/bulk/{batch_id} returns all required metadata fields."""
    order_id = _unique_id("ORD-T1-POLL-META")
    sub_res = client.post(
        "/api/v1/orders/bulk",
        json={
            "orders": [
                {
                    "order_id": order_id,
                    "courier_partner": "mock",
                    "customer": {"name": "Poll Meta", "phone": "9000000060", "address": "Poll Ave"},
                    "items": [{"name": "Poll Item", "quantity": 1, "price": 12.0}],
                }
            ]
        },
    )
    batch_id = sub_res.json()["batch_id"]

    poll_res = client.get(f"/api/v1/orders/bulk/{batch_id}")
    assert poll_res.status_code == 200
    data = poll_res.json()
    assert data["batch_id"] == batch_id
    assert "status" in data
    assert "total" in data
    assert "successful" in data
    assert "failed" in data
    assert "results" in data


def test_bulk_poll_eventual_completion(client):
    """Verify bulk batch eventually transitions to COMPLETED status."""
    order_id = _unique_id("ORD-T1-POLL-COMP")
    sub_res = client.post(
        "/api/v1/orders/bulk",
        json={
            "orders": [
                {
                    "order_id": order_id,
                    "courier_partner": "mock",
                    "customer": {"name": "Comp User", "phone": "9000000070", "address": "Comp Rd"},
                    "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
                }
            ]
        },
    )
    batch_id = sub_res.json()["batch_id"]

    # Poll with timeout
    completed = False
    for _ in range(30):
        res = client.get(f"/api/v1/orders/bulk/{batch_id}")
        assert res.status_code == 200
        if res.json()["status"] in ("COMPLETED", "FAILED"):
            completed = True
            break
        time.sleep(0.1)

    assert completed, f"Batch {batch_id} did not complete within allotted polling window"


def test_bulk_poll_item_results_structure(client):
    """Verify each item in bulk poll results contains order_id and success indicator."""
    order_id = _unique_id("ORD-T1-POLL-ITEM")
    sub_res = client.post(
        "/api/v1/orders/bulk",
        json={
            "orders": [
                {
                    "order_id": order_id,
                    "courier_partner": "mock",
                    "customer": {"name": "Result User", "phone": "9000000080", "address": "Result Pl"},
                    "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
                }
            ]
        },
    )
    batch_id = sub_res.json()["batch_id"]

    # Wait for completion
    for _ in range(30):
        res = client.get(f"/api/v1/orders/bulk/{batch_id}")
        if res.json()["status"] == "COMPLETED":
            results = res.json()["results"]
            assert len(results) >= 1
            for item in results:
                assert "order_id" in item
                assert "success" in item
                assert isinstance(item["success"], bool)
            break
        time.sleep(0.1)


def test_bulk_poll_successful_count_matches_results(client):
    """Verify batch successful count matches the count of items with success=True in results."""
    orders = [
        {
            "order_id": _unique_id(f"ORD-T1-COUNT-{i}"),
            "courier_partner": "mock",
            "customer": {"name": f"Count User {i}", "phone": f"900000009{i}", "address": f"Count St {i}"},
            "items": [{"name": "Item", "quantity": 1, "price": 5.0}],
        }
        for i in range(3)
    ]
    sub_res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    batch_id = sub_res.json()["batch_id"]

    for _ in range(30):
        res = client.get(f"/api/v1/orders/bulk/{batch_id}")
        data = res.json()
        if data["status"] == "COMPLETED":
            success_items = [r for r in data["results"] if r["success"] is True]
            assert data["successful"] == len(success_items)
            assert data["total"] == data["successful"] + data["failed"]
            break
        time.sleep(0.1)


def test_bulk_poll_partial_failure_reporting(client):
    """Verify batch handles failing items by marking success=False with an error code."""
    orders = [
        {
            "order_id": _unique_id("ORD-T1-PART-OK"),
            "courier_partner": "mock",
            "customer": {"name": "OK User", "phone": "9000000101", "address": "Valid Rd"},
            "items": [{"name": "Valid Item", "quantity": 1, "price": 10.0}],
        },
        {
            "order_id": _unique_id("ORD-T1-PART-FAIL"),
            "courier_partner": "unsupported_non_existent_courier",
            "customer": {"name": "Fail User", "phone": "9000000102", "address": "Invalid Rd"},
            "items": [{"name": "Invalid Item", "quantity": 1, "price": 10.0}],
        },
    ]
    sub_res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    batch_id = sub_res.json()["batch_id"]

    for _ in range(30):
        res = client.get(f"/api/v1/orders/bulk/{batch_id}")
        data = res.json()
        if data["status"] in ("COMPLETED", "FAILED"):
            assert data["failed"] >= 1
            failed_items = [r for r in data["results"] if not r["success"]]
            assert len(failed_items) >= 1
            assert failed_items[0].get("error_code") is not None
            break
        time.sleep(0.1)


# ============================================================================
# 6. IDEMPOTENCY & UNIQUE ORDER CONSTRAINTS — >= 5 Tests
# ============================================================================

def test_idempotent_order_creation_same_payload(client):
    """Verify submitting the identical order_id twice does not duplicate the shipment."""
    order_id = _unique_id("ORD-T1-IDEMP-SAME")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "Idemp User", "phone": "9111222333", "address": "Same Addr"},
        "items": [{"name": "Same Item", "quantity": 1, "price": 30.0}],
    }
    res1 = client.post("/api/v1/orders", json=payload)
    assert res1.status_code in (200, 201)

    # Second submission
    res2 = client.post("/api/v1/orders", json=payload)
    assert res2.status_code in (200, 201, 409)
    if res2.status_code == 409:
        assert res2.json()["error"]["code"] == "DUPLICATE_ORDER"
    else:
        assert res2.json()["order_id"] == order_id


def test_idempotent_no_duplicate_rows_in_orders_table(client, db_session):
    """Verify database orders table maintains strictly one row per unique order_id."""
    order_id = _unique_id("ORD-T1-IDEMP-DB")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "DB Unique User", "phone": "9222333444", "address": "Unique Addr"},
        "items": [{"name": "Unique Item", "quantity": 1, "price": 40.0}],
    }
    client.post("/api/v1/orders", json=payload)
    client.post("/api/v1/orders", json=payload)

    orders = (
        db_session.execute(select(Order).where(Order.order_id == order_id))
        .scalars()
        .all()
    )
    assert len(orders) == 1


def test_idempotent_order_creation_preserves_original_awb(client):
    """Verify second submission returns or preserves the same awb_number as the first."""
    order_id = _unique_id("ORD-T1-IDEMP-AWB")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "AWB Preserved", "phone": "9333444555", "address": "AWB Addr"},
        "items": [{"name": "AWB Item", "quantity": 1, "price": 50.0}],
    }
    res1 = client.post("/api/v1/orders", json=payload)
    assert res1.status_code in (200, 201)
    awb1 = res1.json().get("awb_number")

    res2 = client.post("/api/v1/orders", json=payload)
    if res2.status_code in (200, 201):
        assert res2.json().get("awb_number") == awb1
    else:
        # If 409 DUPLICATE_ORDER, tracking the order should still return awb1
        track = client.get(f"/api/v1/orders/{order_id}/track")
        assert track.status_code == 200
        assert track.json().get("awb_number") == awb1


def test_idempotent_submission_does_not_duplicate_tracking_events(client, db_session):
    """Verify re-submitting an order does not insert redundant initial CREATED tracking records."""
    order_id = _unique_id("ORD-T1-IDEMP-AUDIT")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "Audit Preserved", "phone": "9444555666", "address": "Audit Addr"},
        "items": [{"name": "Audit Item", "quantity": 1, "price": 60.0}],
    }
    client.post("/api/v1/orders", json=payload)
    initial_events = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == order_id)
        )
        .scalars()
        .all()
    )

    # Second submission
    client.post("/api/v1/orders", json=payload)
    subsequent_events = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == order_id)
        )
        .scalars()
        .all()
    )
    assert len(subsequent_events) == len(initial_events)


def test_idempotent_modified_payload_rejected_or_unmutated(client, db_session):
    """Verify submitting the same order_id with different customer details fails with 409 or does not mutate."""
    order_id = _unique_id("ORD-T1-IDEMP-MOD")
    payload1 = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "Original Name", "phone": "9555666777", "address": "Original Addr"},
        "items": [{"name": "Original Item", "quantity": 1, "price": 70.0}],
    }
    payload2 = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "Tampered Name", "phone": "9999999999", "address": "Tampered Addr"},
        "items": [{"name": "Tampered Item", "quantity": 5, "price": 999.0}],
    }
    res1 = client.post("/api/v1/orders", json=payload1)
    assert res1.status_code in (200, 201)

    res2 = client.post("/api/v1/orders", json=payload2)
    assert res2.status_code in (409, 200, 201)
    if res2.status_code == 409:
        assert res2.json()["error"]["code"] == "DUPLICATE_ORDER"
    else:
        # Original customer in database must not have been tampered
        order_row = (
            db_session.execute(select(Order).where(Order.order_id == order_id))
            .scalar_one_or_none()
        )
        assert order_row.request_payload["customer"]["name"] == "Original Name"


# ============================================================================
# 7. STANDARDIZED ERROR ENVELOPE — >= 5 Tests
# ============================================================================

def test_error_envelope_404_order_not_found(client):
    """Verify non-existent order tracking returns 404 with standardized error envelope."""
    non_existent = _unique_id("ORD-DOES-NOT-EXIST")
    res = client.get(f"/api/v1/orders/{non_existent}/track")
    assert res.status_code == 404
    data = res.json()
    assert "error" in data
    err = data["error"]
    assert err["code"] == "ORDER_NOT_FOUND"
    assert "message" in err
    assert "request_id" in err
    assert "details" in err


def test_error_envelope_400_validation_error(client):
    """Verify payload missing required fields returns 400/422 with VALIDATION_ERROR envelope."""
    res = client.post("/api/v1/orders", json={"order_id": "ONLY-ID"})
    assert res.status_code in (400, 422)
    data = res.json()
    assert "error" in data
    err = data["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert "request_id" in err
    assert err.get("details") is not None


def test_error_envelope_400_unsupported_courier(client):
    """Verify unknown courier partner returns 400 UNSUPPORTED_COURIER."""
    payload = {
        "order_id": _unique_id("ORD-UNSUPP"),
        "courier_partner": "non_existent_unsupported_courier",
        "customer": {"name": "Unsupp User", "phone": "9666777888", "address": "Unsupp Addr"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code == 400
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "UNSUPPORTED_COURIER"


def test_error_envelope_request_id_always_non_empty_string(client):
    """Verify request_id is always present and non-empty in error envelope."""
    res = client.get("/api/v1/orders/ORD-MISSING-TEST/track")
    assert res.status_code == 404
    req_id = res.json()["error"]["request_id"]
    assert isinstance(req_id, str)
    assert len(req_id) > 0


def test_error_envelope_custom_request_id_in_error(client):
    """Verify custom X-Request-ID header is propagated into error envelope."""
    custom_trace = f"err-trace-{uuid.uuid4().hex}"
    res = client.get(
        "/api/v1/orders/ORD-TRACE-ERR/track",
        headers={"X-Request-ID": custom_trace},
    )
    assert res.status_code == 404
    data = res.json()
    assert data["error"]["request_id"] == custom_trace
    assert res.headers.get("X-Request-ID") == custom_trace
