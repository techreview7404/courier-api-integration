"""Top-level tests for bulk order submission and background processing as required by task.md."""

import time
import uuid
import pytest
from fastapi.testclient import TestClient

from app.schemas.order import OrderCreateRequest


def _unique_id(prefix: str = "ORD-BULK") -> str:
    """Generate a unique order ID for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def test_bulk_submission_immediate_acceptance(client: TestClient):
    """Verify POST /api/v1/orders/bulk immediately accepts orders and returns 202 with batch_id."""
    order_id = _unique_id("ORD-B-IMM")
    payload = {
        "orders": [
            {
                "order_id": order_id,
                "courier_partner": "mock",
                "customer": {"name": "Immediate User", "phone": "9998887771", "address": "123 Quick Way"},
                "items": [{"name": "Quick Item", "quantity": 1, "price": 25.0}],
            }
        ]
    }
    response = client.post("/api/v1/orders/bulk", json=payload)
    assert response.status_code in (200, 202)
    data = response.json()
    assert "batch_id" in data
    assert data["status"] in ("PROCESSING", "COMPLETED")
    assert len(data["batch_id"]) > 0


def test_bulk_multiple_couriers_heterogeneous(client: TestClient):
    """Verify batch containing multiple different courier partners processes successfully."""
    o1 = _unique_id("ORD-B-MOCK1")
    o2 = _unique_id("ORD-B-MOCK2")

    payload = {
        "orders": [
            {
                "order_id": o1,
                "courier_partner": "mock",
                "customer": {"name": "User One", "phone": "9998887772", "address": "Bay 1"},
                "items": [{"name": "Part 1", "quantity": 2, "price": 15.0}],
            },
            {
                "order_id": o2,
                "courier_partner": "mock",
                "customer": {"name": "User Two", "phone": "9998887773", "address": "Bay 2"},
                "items": [{"name": "Part 2", "quantity": 1, "price": 45.0}],
            },
        ]
    }
    sub_res = client.post("/api/v1/orders/bulk", json=payload)
    assert sub_res.status_code in (200, 202)
    batch_id = sub_res.json()["batch_id"]

    # Poll until completed
    completed = False
    for _ in range(40):
        poll = client.get(f"/api/v1/orders/bulk/{batch_id}")
        assert poll.status_code == 200
        if poll.json()["status"] == "COMPLETED":
            data = poll.json()
            assert data["total"] == 2
            assert data["successful"] == 2
            assert data["failed"] == 0
            assert len(data["results"]) == 2
            completed = True
            break
        time.sleep(0.1)

    assert completed, f"Batch {batch_id} did not complete in time"


def test_bulk_partial_failure_unsupported_courier(client: TestClient):
    """Verify partial failure handling: failing items record error_code without stopping valid orders."""
    valid_id = _unique_id("ORD-B-VALID")
    invalid_id = _unique_id("ORD-B-INVALID")

    payload = {
        "orders": [
            {
                "order_id": valid_id,
                "courier_partner": "mock",
                "customer": {"name": "Valid Buyer", "phone": "9991112221", "address": "Valid Road"},
                "items": [{"name": "Valid Widget", "quantity": 1, "price": 10.0}],
            },
            {
                "order_id": invalid_id,
                "courier_partner": "non_existent_unsupported_courier_xyz",
                "customer": {"name": "Invalid Buyer", "phone": "9991112222", "address": "Invalid Road"},
                "items": [{"name": "Invalid Widget", "quantity": 1, "price": 10.0}],
            },
        ]
    }
    sub_res = client.post("/api/v1/orders/bulk", json=payload)
    assert sub_res.status_code in (200, 202)
    batch_id = sub_res.json()["batch_id"]

    completed = False
    for _ in range(40):
        poll = client.get(f"/api/v1/orders/bulk/{batch_id}")
        assert poll.status_code == 200
        if poll.json()["status"] in ("COMPLETED", "FAILED"):
            data = poll.json()
            assert data["total"] == 2
            assert data["successful"] == 1
            assert data["failed"] == 1

            results = {r["order_id"]: r for r in data["results"]}
            assert results[valid_id]["success"] is True
            assert results[invalid_id]["success"] is False
            assert results[invalid_id]["error_code"] == "UNSUPPORTED_COURIER"
            completed = True
            break
        time.sleep(0.1)

    assert completed, f"Batch {batch_id} did not finish processing"


def test_bulk_100_orders_concurrent_execution(client: TestClient):
    """Verify submitting exactly 100 orders processes concurrently to completion."""
    orders = [
        {
            "order_id": _unique_id(f"ORD-B100-{i}"),
            "courier_partner": "mock",
            "customer": {
                "name": f"Bulk Shopper {i}",
                "phone": f"987000{i:04d}",
                "address": f"Warehouse Zone {i % 5}, Dock {i % 20}",
            },
            "items": [{"name": f"SKU-{i}", "quantity": (i % 2) + 1, "price": 12.50}],
        }
        for i in range(100)
    ]

    start_time = time.time()
    sub_res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    elapsed_submit = time.time() - start_time

    assert sub_res.status_code in (200, 202)
    assert elapsed_submit < 5.0, "Bulk submission exceeded acceptable response time"
    batch_id = sub_res.json()["batch_id"]

    # Poll batch until completion
    completed = False
    final_data = None
    for _ in range(60):
        poll = client.get(f"/api/v1/orders/bulk/{batch_id}")
        assert poll.status_code == 200
        data = poll.json()
        if data["status"] in ("COMPLETED", "FAILED"):
            completed = True
            final_data = data
            break
        time.sleep(0.1)

    assert completed, f"100-order batch {batch_id} did not complete within timeout"
    assert final_data["total"] == 100
    assert final_data["successful"] == 100
    assert final_data["failed"] == 0
    assert len(final_data["results"]) == 100

    # Verify a random sample can be tracked individually via GET /orders/{order_id}/track
    sample_ids = [orders[0]["order_id"], orders[49]["order_id"], orders[99]["order_id"]]
    for sid in sample_ids:
        track_res = client.get(f"/api/v1/orders/{sid}/track")
        assert track_res.status_code == 200
        assert track_res.json()["order_id"] == sid
        assert track_res.json()["status"] == "CREATED"


def test_bulk_validation_empty_array(client: TestClient):
    """Verify empty orders array rejects with VALIDATION_ERROR."""
    res = client.post("/api/v1/orders/bulk", json={"orders": []})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_bulk_validation_exceeds_100_limit(client: TestClient):
    """Verify submitting 101 orders rejects with VALIDATION_ERROR."""
    orders = [
        {
            "order_id": _unique_id(f"ORD-OV-{i}"),
            "courier_partner": "mock",
            "customer": {"name": f"User {i}", "phone": "9990001111", "address": "Over Ave"},
            "items": [{"name": "Item", "quantity": 1, "price": 5.0}],
        }
        for i in range(101)
    ]
    res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_bulk_poll_non_existent_batch_404(client: TestClient):
    """Verify polling non-existent batch_id returns 404 with normalized error."""
    res = client.get("/api/v1/orders/bulk/BATCH-DOES-NOT-EXIST-404")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ORDER_NOT_FOUND"
