"""Top-level tests for order creation idempotency and uniqueness constraints.

Mandatory requirements from task.md §2, §11, §20:
- duplicate order_id submission
- database UNIQUE constraint enforcement
- consistent response or 409 conflict
- zero duplicate courier calls
- preservation of original order details across replay attempts
- concurrent multi-threaded duplicate submissions
"""

from concurrent.futures import ThreadPoolExecutor
import uuid
from unittest.mock import patch
import pytest
from sqlalchemy import select

from app.couriers.registry import courier_registry
from app.models.order import Order, TrackingHistory


def _unique_order_id(prefix: str = "ORD-IDEMP") -> str:
    """Generate unique order ID for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _make_payload(
    order_id: str,
    customer_name: str = "Original Consignee",
    phone: str = "9876543210",
    item_price: float = 100.0,
) -> dict:
    """Build standardized order payload."""
    return {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {
            "name": customer_name,
            "phone": phone,
            "address": "123 Idempotent Way",
            "city": "Bengaluru",
            "state": "KA",
            "pincode": "560001",
        },
        "items": [
            {
                "name": "Widget A",
                "quantity": 1,
                "price": item_price,
            }
        ],
    }


# ============================================================================
# 1. Duplicate Submission Rejection / Response
# ============================================================================


def test_duplicate_order_id_submission_returns_409_duplicate_order(client):
    """Verify submitting the same order_id twice returns 409 DUPLICATE_ORDER or consistent response."""
    oid = _unique_order_id()
    payload = _make_payload(oid)

    # First submission -> 200 or 201
    res1 = client.post("/api/v1/orders", json=payload)
    assert res1.status_code in (200, 201)
    data1 = res1.json()
    assert data1["order_id"] == oid

    # Second submission -> 409 DUPLICATE_ORDER or consistent 200/201
    res2 = client.post("/api/v1/orders", json=payload)
    assert res2.status_code in (409, 200, 201)
    if res2.status_code == 409:
        err = res2.json()["error"]
        assert err["code"] == "DUPLICATE_ORDER"
        assert oid in err["message"]
    else:
        assert res2.json()["order_id"] == oid


def test_duplicate_submission_causes_zero_duplicate_courier_calls(client):
    """Verify courier adapter create_order is invoked EXACTLY ONCE despite repeated submissions."""
    oid = _unique_order_id("ORD-ZERO-CALLS")
    payload = _make_payload(oid)

    mock_adapter = courier_registry.get("mock")
    original_create_order = mock_adapter.create_order
    call_counter = {"count": 0}

    def _spy_create_order(*args, **kwargs):
        call_counter["count"] += 1
        return original_create_order(*args, **kwargs)

    with patch.object(mock_adapter, "create_order", side_effect=_spy_create_order):
        # First submission
        res1 = client.post("/api/v1/orders", json=payload)
        assert res1.status_code in (200, 201)
        assert call_counter["count"] == 1

        # Second submission
        client.post("/api/v1/orders", json=payload)
        # Third submission
        client.post("/api/v1/orders", json=payload)

        # Counter must remain strictly 1 — zero duplicate courier calls!
        assert call_counter["count"] == 1


def test_database_orders_table_has_strictly_one_row_per_order_id(client, db_session):
    """Verify database orders table maintains strictly one row for duplicate order_id submissions."""
    oid = _unique_order_id("ORD-ONE-ROW")
    payload = _make_payload(oid)

    client.post("/api/v1/orders", json=payload)
    client.post("/api/v1/orders", json=payload)
    client.post("/api/v1/orders", json=payload)

    orders = (
        db_session.execute(select(Order).where(Order.order_id == oid))
        .scalars()
        .all()
    )
    assert len(orders) == 1
    assert orders[0].order_id == oid


def test_duplicate_submission_does_not_duplicate_tracking_events(client, db_session):
    """Verify re-submitting an order does not insert redundant initial CREATED tracking history records."""
    oid = _unique_order_id("ORD-NO-EXTRA-EVENTS")
    payload = _make_payload(oid)

    client.post("/api/v1/orders", json=payload)
    initial_events = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == oid)
        )
        .scalars()
        .all()
    )
    assert len(initial_events) == 1

    # Second submission
    client.post("/api/v1/orders", json=payload)
    after_events = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == oid)
        )
        .scalars()
        .all()
    )
    assert len(after_events) == len(initial_events)


def test_tampered_payload_rejected_and_original_unmutated(client, db_session):
    """Verify re-submitting with modified customer or items does not mutate the original order."""
    oid = _unique_order_id("ORD-TAMPER")
    original_payload = _make_payload(oid, customer_name="Alice Legit", item_price=50.0)
    tampered_payload = _make_payload(oid, customer_name="Mallory Hacker", item_price=9999.0)

    # First submission
    res1 = client.post("/api/v1/orders", json=original_payload)
    assert res1.status_code in (200, 201)

    # Second submission with tampered payload
    res2 = client.post("/api/v1/orders", json=tampered_payload)
    assert res2.status_code in (409, 200, 201)

    # Verify database has original data intact
    db_order = (
        db_session.execute(select(Order).where(Order.order_id == oid))
        .scalar_one_or_none()
    )
    assert db_order is not None
    assert db_order.request_payload["customer"]["name"] == "Alice Legit"
    assert db_order.request_payload["items"][0]["price"] == 50.0


# ============================================================================
# 2. Concurrent Multi-Threaded Duplicate Submissions
# ============================================================================


def test_concurrent_duplicate_order_id_race_condition(engine):
    """Verify concurrent parallel submissions of identical order_id result in exactly 1 persisted row."""
    import threading
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.database import get_db
    from app.main import create_app

    app = create_app()
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _get_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db

    oid = _unique_order_id("ORD-RACE")
    payload = _make_payload(oid)
    num_threads = 10
    barrier = threading.Barrier(num_threads)
    responses = []
    lock = threading.Lock()

    def _submit():
        barrier.wait()  # Launch all requests at the exact same instant
        with TestClient(app) as tc:
            resp = tc.post("/api/v1/orders", json=payload)
            with lock:
                responses.append((resp.status_code, resp.json()))

    threads = [threading.Thread(target=_submit) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Count successful 201/200 vs 409 conflicts
    success_count = sum(1 for status_code, _ in responses if status_code in (200, 201))
    conflict_count = sum(1 for status_code, _ in responses if status_code == 409)

    # Exactly 1 request succeeds in creating the order, remaining are rejected with 409 DUPLICATE_ORDER
    assert success_count == 1
    assert conflict_count == num_threads - 1

    for status_code, body in responses:
        if status_code == 409:
            assert body["error"]["code"] == "DUPLICATE_ORDER"
            assert oid in body["error"]["message"]

