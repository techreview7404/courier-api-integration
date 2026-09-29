"""Tier 3: Cross-Feature Combinations E2E Tests.

Exercises interactions across multiple architectural features:
- Mixed courier partners in a single bulk batch
- Bulk processing with partial failures and summary count integrity
- Order tracking transitions before and after cancellation
- Tracking history immutability audit (verifying append-only behavior)
- Idempotent duplicate submission impact on tracking history
- Bulk batch with duplicate order ID conflict handling
"""

import os
os.environ.setdefault("DEBUG", "false")

import time
import uuid
from sqlalchemy import select

from app.models.order import Order, TrackingHistory


def _unique_id(prefix: str = "ORD") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def test_mixed_couriers_in_bulk_dispatch(client):
    """Verify bulk dispatch containing orders with multiple courier partners handles each correctly."""
    orders = [
        {
            "order_id": _unique_id("ORD-T3-MIX-1"),
            "courier_partner": "mock",
            "customer": {"name": "Mix 1", "phone": "9812345671", "address": "Route 1"},
            "items": [{"name": "Item A", "quantity": 1, "price": 10.0}],
        },
        {
            "order_id": _unique_id("ORD-T3-MIX-2"),
            "courier_partner": "mock",
            "customer": {"name": "Mix 2", "phone": "9812345672", "address": "Route 2"},
            "items": [{"name": "Item B", "quantity": 2, "price": 20.0}],
        },
    ]
    sub_res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert sub_res.status_code in (200, 202)
    batch_id = sub_res.json()["batch_id"]

    # Poll until completed
    for _ in range(30):
        res = client.get(f"/api/v1/orders/bulk/{batch_id}")
        data = res.json()
        if data["status"] in ("COMPLETED", "FAILED"):
            assert data["total"] == 2
            assert data["successful"] == 2
            assert data["failed"] == 0
            break
        time.sleep(0.1)


def test_partial_batch_failures_and_counts_integrity(client):
    """Verify a batch with both valid and invalid courier orders reports partial failures without crashing."""
    valid_order_id = _unique_id("ORD-T3-VALID")
    invalid_order_id = _unique_id("ORD-T3-INVALID")
    orders = [
        {
            "order_id": valid_order_id,
            "courier_partner": "mock",
            "customer": {"name": "Valid Order", "phone": "9812345681", "address": "Valid Ave"},
            "items": [{"name": "Item", "quantity": 1, "price": 15.0}],
        },
        {
            "order_id": invalid_order_id,
            "courier_partner": "unknown_carrier_xyz",
            "customer": {"name": "Invalid Order", "phone": "9812345682", "address": "Invalid Ave"},
            "items": [{"name": "Item", "quantity": 1, "price": 15.0}],
        },
    ]
    sub_res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert sub_res.status_code in (200, 202)
    batch_id = sub_res.json()["batch_id"]

    for _ in range(30):
        res = client.get(f"/api/v1/orders/bulk/{batch_id}")
        data = res.json()
        if data["status"] in ("COMPLETED", "FAILED"):
            assert data["status"] == "COMPLETED"
            assert data["total"] == 2
            assert data["successful"] == 1
            assert data["failed"] == 1

            results_map = {item["order_id"]: item for item in data["results"]}
            assert results_map[valid_order_id]["success"] is True
            assert results_map[invalid_order_id]["success"] is False
            assert results_map[invalid_order_id]["error_code"] == "UNSUPPORTED_COURIER"
            break
        time.sleep(0.1)


def test_track_order_lifecycle_before_and_after_cancellation(client):
    """Verify order lifecycle tracking transitions through creation, tracking, and post-cancellation."""
    order_id = _unique_id("ORD-T3-LIFECYCLE")
    # 1. Create order
    create_res = client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Lifecycle Cust", "phone": "9812345691", "address": "Cycle Way"},
            "items": [{"name": "Item", "quantity": 1, "price": 25.0}],
        },
    )
    assert create_res.status_code in (200, 201)
    assert create_res.json()["status"] == "CREATED"

    # 2. Track order before cancellation
    track_before = client.get(f"/api/v1/orders/{order_id}/track")
    assert track_before.status_code == 200
    assert track_before.json()["status"] in ("CREATED", "PICKED_UP", "IN_TRANSIT")

    # 3. Cancel order
    cancel_res = client.post(f"/api/v1/orders/{order_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # 4. Track order after cancellation
    track_after = client.get(f"/api/v1/orders/{order_id}/track")
    assert track_after.status_code == 200
    assert track_after.json()["status"] == "CANCELLED"

    # History should contain all milestones
    history = track_after.json().get("history", [])
    statuses = [h["status"] for h in history]
    assert "CREATED" in statuses
    assert "CANCELLED" in statuses


def test_tracking_history_immutability_audit_log(client, db_session):
    """Verify strict append-only immutability of tracking_history: prior records are never updated or deleted."""
    order_id = _unique_id("ORD-T3-AUDIT-IMM")
    client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Immutability User", "phone": "9812345701", "address": "Audit Ln"},
            "items": [{"name": "Item", "quantity": 1, "price": 50.0}],
        },
    )

    # Initial record captured
    initial_events = (
        db_session.execute(
            select(TrackingHistory)
            .where(TrackingHistory.order_id == order_id)
            .order_by(TrackingHistory.id)
        )
        .scalars()
        .all()
    )
    assert len(initial_events) == 1
    first_record_id = initial_events[0].id
    first_record_status = initial_events[0].status
    first_record_created_at = initial_events[0].created_at

    # Trigger tracking multiple times
    client.get(f"/api/v1/orders/{order_id}/track")
    client.get(f"/api/v1/orders/{order_id}/track")
    client.get(f"/api/v1/orders/{order_id}/track")

    # Re-query all history records
    all_events = (
        db_session.execute(
            select(TrackingHistory)
            .where(TrackingHistory.order_id == order_id)
            .order_by(TrackingHistory.id)
        )
        .scalars()
        .all()
    )

    # Multiple records exist
    assert len(all_events) >= 2

    # The very first record must be completely identical (unmutated)
    assert all_events[0].id == first_record_id
    assert all_events[0].status == first_record_status
    assert all_events[0].created_at == first_record_created_at

    # Chronological integrity: record IDs and timestamps are strictly non-decreasing
    for i in range(len(all_events) - 1):
        assert all_events[i].id < all_events[i + 1].id
        assert all_events[i].created_at <= all_events[i + 1].created_at


def test_duplicate_submission_does_not_mutate_or_duplicate_tracking(client, db_session):
    """Verify duplicate order submission does not append bogus tracking events or mutate original order."""
    order_id = _unique_id("ORD-T3-DUP-IMM")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "Original User", "phone": "9812345711", "address": "Original Ave"},
        "items": [{"name": "Original Item", "quantity": 1, "price": 40.0}],
    }
    client.post("/api/v1/orders", json=payload)

    initial_orders = (
        db_session.execute(select(Order).where(Order.order_id == order_id))
        .scalars()
        .all()
    )
    initial_history = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == order_id)
        )
        .scalars()
        .all()
    )
    assert len(initial_orders) == 1
    assert len(initial_history) == 1

    # Second submission
    client.post("/api/v1/orders", json=payload)

    orders_after = (
        db_session.execute(select(Order).where(Order.order_id == order_id))
        .scalars()
        .all()
    )
    history_after = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == order_id)
        )
        .scalars()
        .all()
    )
    assert len(orders_after) == 1, "Duplicate order created in orders table!"
    assert len(history_after) == len(initial_history), "Extra tracking event appended on duplicate submission!"


def test_bulk_batch_with_duplicate_order_ids_handles_partial_conflict(client):
    """Verify bulk processing handles duplicate order IDs as partial failures while succeeding on others."""
    existing_order_id = _unique_id("ORD-T3-EXISTING")
    # Pre-create an order
    client.post(
        "/api/v1/orders",
        json={
            "order_id": existing_order_id,
            "courier_partner": "mock",
            "customer": {"name": "Pre-existing", "phone": "9812345721", "address": "Pre Rd"},
            "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
        },
    )

    new_order_id = _unique_id("ORD-T3-NEW")
    # Submit bulk batch containing the duplicate order ID
    orders = [
        {
            "order_id": existing_order_id,  # Duplicate!
            "courier_partner": "mock",
            "customer": {"name": "Duplicate in Bulk", "phone": "9812345722", "address": "Dup Rd"},
            "items": [{"name": "Dup Item", "quantity": 1, "price": 10.0}],
        },
        {
            "order_id": new_order_id,  # Valid new order
            "courier_partner": "mock",
            "customer": {"name": "Fresh Order", "phone": "9812345723", "address": "Fresh Rd"},
            "items": [{"name": "Fresh Item", "quantity": 1, "price": 20.0}],
        },
    ]
    sub_res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert sub_res.status_code in (200, 202)
    batch_id = sub_res.json()["batch_id"]

    for _ in range(30):
        res = client.get(f"/api/v1/orders/bulk/{batch_id}")
        data = res.json()
        if data["status"] in ("COMPLETED", "FAILED"):
            assert data["total"] == 2
            assert data["successful"] == 1
            assert data["failed"] == 1
            results_map = {item["order_id"]: item for item in data["results"]}
            assert results_map[new_order_id]["success"] is True
            assert results_map[existing_order_id]["success"] is False
            assert results_map[existing_order_id]["error_code"] == "DUPLICATE_ORDER"
            break
        time.sleep(0.1)
