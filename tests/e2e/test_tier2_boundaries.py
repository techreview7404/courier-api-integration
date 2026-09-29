"""Tier 2: Boundary & Corner Cases E2E Tests.

Exercises boundary conditions and edge cases:
- Empty Bulk submissions (0 orders, empty payload, null)
- Bulk payload exceeding 100 orders limit (101, 105, 150, 200 orders)
- Missing required fields (order_id, customer details, items)
- Zero and negative prices / quantities
- Non-existent entities (tracking, cancellation, bulk batch polling)
- Unassigned / unsupported courier partners
"""

import os
os.environ.setdefault("DEBUG", "false")

import uuid


def _unique_id(prefix: str = "ORD") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ============================================================================
# 1. EMPTY BULK SUBMISSION — >= 5 Tests
# ============================================================================

def test_boundary_bulk_empty_orders_array(client):
    """Verify POST /api/v1/orders/bulk with empty orders list rejects with VALIDATION_ERROR."""
    res = client.post("/api/v1/orders/bulk", json={"orders": []})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_bulk_missing_orders_key(client):
    """Verify POST /api/v1/orders/bulk with empty JSON object rejects with VALIDATION_ERROR."""
    res = client.post("/api/v1/orders/bulk", json={})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_bulk_null_orders(client):
    """Verify POST /api/v1/orders/bulk with orders: null rejects with VALIDATION_ERROR."""
    res = client.post("/api/v1/orders/bulk", json={"orders": None})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_bulk_orders_as_string(client):
    """Verify POST /api/v1/orders/bulk with orders: 'string' rejects with VALIDATION_ERROR."""
    res = client.post("/api/v1/orders/bulk", json={"orders": "not_a_list"})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_bulk_orders_as_dict(client):
    """Verify POST /api/v1/orders/bulk with orders as a dict instead of list rejects with VALIDATION_ERROR."""
    res = client.post("/api/v1/orders/bulk", json={"orders": {"order_id": "ORD-1"}})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


# ============================================================================
# 2. BULK EXCEEDING 100 ORDERS LIMIT — >= 5 Tests
# ============================================================================

def _generate_dummy_orders(count: int) -> list[dict]:
    """Helper to generate a list of N valid order payloads."""
    return [
        {
            "order_id": _unique_id(f"ORD-BND-{i}"),
            "courier_partner": "mock",
            "customer": {"name": f"User {i}", "phone": "9999999999", "address": "Boundary Way"},
            "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
        }
        for i in range(count)
    ]


def test_boundary_bulk_exact_101_orders(client):
    """Verify submitting exactly 101 orders in a bulk batch is rejected with VALIDATION_ERROR."""
    orders = _generate_dummy_orders(101)
    res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_bulk_105_orders(client):
    """Verify submitting 105 orders in bulk batch is rejected with VALIDATION_ERROR."""
    orders = _generate_dummy_orders(105)
    res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_bulk_150_orders(client):
    """Verify submitting 150 orders in bulk batch is rejected with VALIDATION_ERROR."""
    orders = _generate_dummy_orders(150)
    res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_bulk_200_orders(client):
    """Verify submitting 200 orders in bulk batch is rejected with VALIDATION_ERROR."""
    orders = _generate_dummy_orders(200)
    res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_bulk_exact_100_orders_allowed(client):
    """Verify boundary condition: exactly 100 orders is accepted, contrasting with 101 rejected."""
    orders = _generate_dummy_orders(100)
    res = client.post("/api/v1/orders/bulk", json={"orders": orders})
    assert res.status_code in (200, 202)
    assert "batch_id" in res.json()


# ============================================================================
# 3. MISSING REQUIRED FIELDS — >= 5 Tests
# ============================================================================

def test_boundary_order_missing_order_id(client):
    """Verify order creation missing order_id returns VALIDATION_ERROR."""
    payload = {
        "courier_partner": "mock",
        "customer": {"name": "No ID", "phone": "9999999999", "address": "No ID Rd"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_order_missing_courier_partner(client):
    """Verify order creation missing courier_partner returns VALIDATION_ERROR."""
    payload = {
        "order_id": _unique_id("ORD-NO-PARTNER"),
        "customer": {"name": "No Partner", "phone": "9999999999", "address": "No Partner Rd"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_order_missing_customer(client):
    """Verify order creation missing customer object returns VALIDATION_ERROR."""
    payload = {
        "order_id": _unique_id("ORD-NO-CUST"),
        "courier_partner": "mock",
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_order_missing_customer_name(client):
    """Verify order creation with missing customer.name returns VALIDATION_ERROR."""
    payload = {
        "order_id": _unique_id("ORD-NO-NAME"),
        "courier_partner": "mock",
        "customer": {"phone": "9999999999", "address": "Nameless Ave"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_order_missing_customer_phone(client):
    """Verify order creation with missing customer.phone returns VALIDATION_ERROR."""
    payload = {
        "order_id": _unique_id("ORD-NO-PHONE"),
        "courier_partner": "mock",
        "customer": {"name": "Phoneless", "address": "Phoneless Ave"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_order_missing_items_list(client):
    """Verify order creation with missing items or empty items list returns VALIDATION_ERROR."""
    payload = {
        "order_id": _unique_id("ORD-EMPTY-ITEMS"),
        "courier_partner": "mock",
        "customer": {"name": "No Items", "phone": "9999999999", "address": "Empty Rd"},
        "items": [],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


# ============================================================================
# 4. ZERO OR NEGATIVE PRICES AND QUANTITIES — >= 5 Tests
# ============================================================================

def test_boundary_item_negative_price(client):
    """Verify item with negative price (-10.0) returns VALIDATION_ERROR."""
    payload = {
        "order_id": _unique_id("ORD-NEG-PRICE"),
        "courier_partner": "mock",
        "customer": {"name": "Neg Price", "phone": "9999999999", "address": "Neg Rd"},
        "items": [{"name": "Item", "quantity": 1, "price": -10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_item_negative_cents_price(client):
    """Verify item with negative fractional price (-0.01) returns VALIDATION_ERROR."""
    payload = {
        "order_id": _unique_id("ORD-NEG-CENT"),
        "courier_partner": "mock",
        "customer": {"name": "Neg Cent", "phone": "9999999999", "address": "Neg Cent Rd"},
        "items": [{"name": "Item", "quantity": 1, "price": -0.01}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_item_zero_quantity(client):
    """Verify item with quantity 0 returns VALIDATION_ERROR."""
    payload = {
        "order_id": _unique_id("ORD-ZERO-QTY"),
        "courier_partner": "mock",
        "customer": {"name": "Zero Qty", "phone": "9999999999", "address": "Zero Rd"},
        "items": [{"name": "Item", "quantity": 0, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_item_negative_quantity(client):
    """Verify item with negative quantity (-1) returns VALIDATION_ERROR."""
    payload = {
        "order_id": _unique_id("ORD-NEG-QTY"),
        "courier_partner": "mock",
        "customer": {"name": "Neg Qty", "phone": "9999999999", "address": "Neg Qty Rd"},
        "items": [{"name": "Item", "quantity": -1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_boundary_item_zero_price_allowed(client):
    """Verify item with price 0.0 (e.g. free promotional sample) is accepted per spec (price >= 0.0)."""
    payload = {
        "order_id": _unique_id("ORD-FREE-ITEM"),
        "courier_partner": "mock",
        "customer": {"name": "Free Sample", "phone": "9999999999", "address": "Promo Ave"},
        "items": [{"name": "Sample Sticker", "quantity": 1, "price": 0.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (200, 201)
    assert res.json()["status"] == "CREATED"


# ============================================================================
# 5. NON-EXISTENT ENTITIES — >= 5 Tests
# ============================================================================

def test_boundary_track_non_existent_order(client):
    """Verify tracking a non-existent order returns 404 with code ORDER_NOT_FOUND."""
    res = client.get("/api/v1/orders/ORD-NONEXISTENT-TRACK-1/track")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ORDER_NOT_FOUND"


def test_boundary_cancel_non_existent_order(client):
    """Verify cancelling a non-existent order returns 404 with code ORDER_NOT_FOUND."""
    res = client.post("/api/v1/orders/ORD-NONEXISTENT-CANCEL-1/cancel")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ORDER_NOT_FOUND"


def test_boundary_poll_non_existent_batch(client):
    """Verify polling a non-existent batch returns 404 with normalized error envelope."""
    res = client.get("/api/v1/orders/bulk/BATCH-DOES-NOT-EXIST-404")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ORDER_NOT_FOUND"


def test_boundary_track_special_characters_order_id(client):
    """Verify tracking an order ID with URL-encoded special characters returns 404 not found."""
    res = client.get("/api/v1/orders/ORD%21%40%23%24%25/track")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ORDER_NOT_FOUND"


def test_boundary_cancel_non_existent_uuid_order(client):
    """Verify cancelling random generated UUID returns 404 not found."""
    random_id = f"ORD-{uuid.uuid4().hex}"
    res = client.post(f"/api/v1/orders/{random_id}/cancel")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ORDER_NOT_FOUND"


# ============================================================================
# 6. UNASSIGNED OR UNSUPPORTED COURIERS — >= 5 Tests
# ============================================================================

def test_boundary_unsupported_courier_fedex(client):
    """Verify order specifying unregistered courier 'fedex' returns 400 UNSUPPORTED_COURIER."""
    payload = {
        "order_id": _unique_id("ORD-FEDEX"),
        "courier_partner": "fedex",
        "customer": {"name": "Courier User", "phone": "9999999999", "address": "Fedex Rd"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "UNSUPPORTED_COURIER"


def test_boundary_unsupported_courier_dhl(client):
    """Verify order specifying unregistered courier 'dhl' returns 400 UNSUPPORTED_COURIER."""
    payload = {
        "order_id": _unique_id("ORD-DHL"),
        "courier_partner": "dhl",
        "customer": {"name": "Courier User", "phone": "9999999999", "address": "DHL Rd"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "UNSUPPORTED_COURIER"


def test_boundary_unsupported_courier_ups(client):
    """Verify order specifying unregistered courier 'ups' returns 400 UNSUPPORTED_COURIER."""
    payload = {
        "order_id": _unique_id("ORD-UPS"),
        "courier_partner": "ups",
        "customer": {"name": "Courier User", "phone": "9999999999", "address": "UPS Rd"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "UNSUPPORTED_COURIER"


def test_boundary_unsupported_courier_arbitrary_string(client):
    """Verify arbitrary unknown courier partner name returns 400 UNSUPPORTED_COURIER."""
    payload = {
        "order_id": _unique_id("ORD-UNKNOWN"),
        "courier_partner": "random_fake_logistics_corp_123",
        "customer": {"name": "Courier User", "phone": "9999999999", "address": "Random Rd"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "UNSUPPORTED_COURIER"


def test_boundary_empty_courier_partner_string(client):
    """Verify empty courier partner string returns 400/422 VALIDATION_ERROR or UNSUPPORTED_COURIER."""
    payload = {
        "order_id": _unique_id("ORD-EMPTY-PARTNER"),
        "courier_partner": "",
        "customer": {"name": "Courier User", "phone": "9999999999", "address": "Empty Partner Rd"},
        "items": [{"name": "Item", "quantity": 1, "price": 10.0}],
    }
    res = client.post("/api/v1/orders", json=payload)
    assert res.status_code in (400, 422)
    assert res.json()["error"]["code"] in ("VALIDATION_ERROR", "UNSUPPORTED_COURIER")
