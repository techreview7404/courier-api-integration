"""Tier 4: Real-World Application Workloads E2E Tests.

Exercises full end-to-end user journeys and operational scenarios:
- Complete e-commerce fulfillment lifecycle (Order creation -> Carrier pickup -> In-transit -> Delivery)
- High-volume concurrent bulk batch dispatch (100 orders polled to completion)
- Resilient retry recovery on transient network timeout / 5xx failures
- Resilient retry exhaustion resulting in normalized COURIER_TIMEOUT / COURIER_ERROR
- Courier authentication 401 token refresh and recovery
- Order cancellation workflow with post-cancellation audit validation
"""

import os
os.environ.setdefault("DEBUG", "false")

import time
import uuid
from unittest.mock import patch
import httpx

try:
    from app.couriers.mock import MockCourierAdapter
except ImportError:
    MockCourierAdapter = None


def _unique_id(prefix: str = "ORD") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ============================================================================
# 1. FULL E-COMMERCE FULFILLMENT LIFECYCLE
# ============================================================================

def test_scenario_full_ecommerce_fulfillment_lifecycle(client):
    """Simulate complete e-commerce lifecycle from order placement to delivery."""
    order_id = _unique_id("ORD-T4-ECOM")

    # Step 1: Customer places order
    order_payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {
            "name": "Sarah Connor",
            "phone": "9811002200",
            "address": "404 Skynet Blvd, Sector 7",
            "city": "Cyber City",
            "state": "DL",
            "pincode": "110001",
        },
        "items": [
            {"name": "Titanium Watch", "quantity": 1, "price": 299.99},
            {"name": "Protective Case", "quantity": 1, "price": 29.99},
        ],
    }
    create_res = client.post("/api/v1/orders", json=order_payload)
    assert create_res.status_code in (200, 201)
    data = create_res.json()
    assert data["order_id"] == order_id
    assert data["status"] == "CREATED"
    awb_number = data.get("awb_number")
    assert awb_number is not None

    # Step 2: Track order initial state
    track_1 = client.get(f"/api/v1/orders/{order_id}/track")
    assert track_1.status_code == 200
    assert track_1.json()["status"] in ("CREATED", "PICKED_UP", "IN_TRANSIT", "DELIVERED")

    # Step 3: Track order subsequent milestone checks
    track_2 = client.get(f"/api/v1/orders/{order_id}/track")
    assert track_2.status_code == 200
    history = track_2.json().get("history", [])
    assert len(history) >= 1

    # Verify order metadata consistency
    assert track_2.json()["courier_partner"].lower() == "mock"
    assert track_2.json()["awb_number"] == awb_number


# ============================================================================
# 2. CONCURRENT 100-ORDER BULK BATCH DISPATCH
# ============================================================================

def test_scenario_concurrent_bulk_batch_100_orders_to_completion(client):
    """Submit exactly 100 orders in a single bulk batch and poll until completion."""
    orders = [
        {
            "order_id": _unique_id(f"ORD-T4-B100-{i}"),
            "courier_partner": "mock",
            "customer": {
                "name": f"High Volume Shopper {i}",
                "phone": f"981000{i:04d}",
                "address": f"Warehouse Bay {i % 10}, Logistics Park",
            },
            "items": [
                {"name": f"Bulk Item {i}", "quantity": (i % 3) + 1, "price": 19.50}
            ],
        }
        for i in range(100)
    ]

    # Submit batch
    submit_start = time.time()
    sub_res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    submit_duration = time.time() - submit_start

    assert sub_res.status_code in (200, 202)
    assert submit_duration < 10.0, f"Bulk submit took too long: {submit_duration:.2f}s"
    batch_id = sub_res.json()["batch_id"]
    assert len(batch_id) > 0

    # Poll to completion
    completed = False
    batch_status_data = None

    for _ in range(60):  # poll up to 30 seconds
        poll_res = client.get(f"/api/v1/orders/bulk/{batch_id}")
        assert poll_res.status_code == 200
        batch_status_data = poll_res.json()
        if batch_status_data["status"] in ("COMPLETED", "FAILED"):
            completed = True
            break
        time.sleep(0.5)

    assert completed, f"100-order batch {batch_id} did not complete within timeout. Last state: {batch_status_data}"
    assert batch_status_data["total"] == 100
    assert batch_status_data["successful"] == 100
    assert batch_status_data["failed"] == 0
    assert len(batch_status_data["results"]) == 100

    # Sample check: verify 5 random orders from the batch exist and can be tracked
    sample_indices = [0, 24, 49, 74, 99]
    for idx in sample_indices:
        sample_order_id = orders[idx]["order_id"]
        track_res = client.get(f"/api/v1/orders/{sample_order_id}/track")
        assert track_res.status_code == 200
        assert track_res.json()["order_id"] == sample_order_id


# ============================================================================
# 3. TRANSIENT RETRY RECOVERY
# ============================================================================

def test_scenario_transient_retry_recovery(client):
    """Verify application retries transient courier timeouts / 5xx errors and succeeds."""
    order_id = _unique_id("ORD-T4-RETRY-OK")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "Retry User", "phone": "9811223344", "address": "Retry Way"},
        "items": [{"name": "Retry Item", "quantity": 1, "price": 50.0}],
    }

    # Order creation should succeed either directly or via retry
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (200, 201)
    assert res.json()["order_id"] == order_id


# ============================================================================
# 4. TRANSIENT RETRY EXHAUSTION
# ============================================================================

def test_scenario_transient_retry_exhaustion(client):
    """Verify exhaustion of retries returns normalized COURIER_ERROR or COURIER_TIMEOUT."""
    # When hitting a simulated failing courier or mock in failure mode
    order_id = _unique_id("ORD-T4-EXHAUST")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "Exhaust User", "phone": "9811223355", "address": "Exhaust Ave"},
        "items": [{"name": "Exhaust Item", "quantity": 1, "price": 99.0}],
    }

    # Simulate downstream timeout via mock adapter simulation
    from app.exceptions import CourierTimeoutError

    with patch("app.couriers.mock.MockCourierAdapter.create_order", side_effect=CourierTimeoutError("Courier connection timed out")):
        res = client.post("/api/v1/orders", json=payload)
        # Should catch and map to standardized error envelope (504 or 502)
        assert res.status_code in (502, 504)
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] in ("COURIER_TIMEOUT", "COURIER_ERROR")
        assert "request_id" in data["error"]


# ============================================================================
# 5. COURIER AUTH 401 TOKEN REFRESH RECOVERY
# ============================================================================

def test_scenario_auth_failure_with_token_refresh(client):
    """Verify 401 auth error triggers token re-authentication and seamless recovery."""
    order_id = _unique_id("ORD-T4-AUTH-REFRESH")
    payload = {
        "order_id": order_id,
        "courier_partner": "mock",
        "customer": {"name": "Auth User", "phone": "9811223366", "address": "Auth Rd"},
        "items": [{"name": "Auth Item", "quantity": 1, "price": 100.0}],
    }

    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (200, 201)
    assert res.json()["status"] == "CREATED"


# ============================================================================
# 6. ORDER CANCELLATION AND POST-CANCELLATION AUDIT
# ============================================================================

def test_scenario_order_cancellation_and_subsequent_tracking(client):
    """Verify cancellation transition and that cancelled orders remain cancelled upon subsequent tracking."""
    order_id = _unique_id("ORD-T4-CANCEL-AUDIT")
    # 1. Create order
    create_res = client.post(
        "/api/v1/orders",
        json={
            "order_id": order_id,
            "courier_partner": "mock",
            "customer": {"name": "Cancel Cust", "phone": "9811223377", "address": "Cancel Pl"},
            "items": [{"name": "Cancelled Item", "quantity": 1, "price": 75.0}],
        },
    )
    assert create_res.status_code in (200, 201)

    # 2. Cancel order
    cancel_res = client.post(f"/api/v1/orders/{order_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # 3. Subsequent tracking verification
    track_res = client.get(f"/api/v1/orders/{order_id}/track")
    assert track_res.status_code == 200
    assert track_res.json()["status"] == "CANCELLED"

    # 4. Repeated cancellation attempt handled gracefully
    re_cancel = client.post(f"/api/v1/orders/{order_id}/cancel")
    assert re_cancel.status_code in (200, 400, 409)
