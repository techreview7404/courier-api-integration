"""Unit tests for OrderService verifying business logic, idempotency, and audit trail."""

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from unittest.mock import MagicMock, patch

from app.couriers.mock import MockCourierAdapter, MockSimulationMode
from app.couriers.registry import courier_registry
from app.exceptions import (
    CourierAuthError,
    CourierError,
    CourierTimeoutError,
    DuplicateOrderError,
    OrderNotFoundError,
    UnsupportedCourierError,
    ValidationError,
)
from app.models.order import Order, TrackingHistory
from app.schemas.order import Customer, OrderCreateRequest, OrderItem
from app.schemas.tracking import OrderStatus
from app.services.order_service import OrderService, order_service


def _make_order_request(
    order_id: str | None = None,
    courier: str = "mock",
    customer_name: str = "Unit Test Customer",
) -> OrderCreateRequest:
    """Helper to generate a valid OrderCreateRequest."""
    oid = order_id or f"ORD-UNIT-{uuid.uuid4().hex[:8].upper()}"
    return OrderCreateRequest(
        order_id=oid,
        courier_partner=courier,
        customer=Customer(
            name=customer_name,
            phone="9876543210",
            address="100 Service Lane",
            city="Tech City",
            state="CA",
            pincode="94016",
            email="unit@example.com",
        ),
        items=[
            OrderItem(name="Item Alpha", quantity=2, price=29.99),
            OrderItem(name="Item Beta", quantity=1, price=49.99),
        ],
    )


# ============================================================================
# 1. Order Creation Tests
# ============================================================================


def test_create_order_success(db_session):
    """Verify order creation with valid payload persists Order and initial TrackingHistory."""
    req = _make_order_request()
    response = OrderService.create_order(db=db_session, order_in=req)

    assert response.order_id == req.order_id
    assert response.courier_partner == "mock"
    assert response.status == "CREATED"
    assert response.awb_number is not None
    assert response.courier_order_id is not None
    assert response.created_at is not None

    # Verify Order in DB
    db_order = db_session.execute(
        select(Order).where(Order.order_id == req.order_id)
    ).scalar_one_or_none()

    assert db_order is not None
    assert db_order.order_id == req.order_id
    assert db_order.courier_partner == "mock"
    assert db_order.status == "CREATED"
    assert db_order.request_payload["order_id"] == req.order_id
    assert db_order.response_payload["status"] == "Success"

    # Verify initial TrackingHistory record
    events = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == req.order_id)
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].status == "CREATED"
    assert events[0].order_id == req.order_id
    assert events[0].raw_payload is not None


def test_create_order_from_dict_payload(db_session):
    """Verify create_order accepts raw dictionary payload and parses it accurately."""
    oid = f"ORD-DICT-{uuid.uuid4().hex[:8].upper()}"
    raw_dict = {
        "order_id": oid,
        "courier_partner": "MOCK",
        "customer": {
            "name": "Dict Customer",
            "phone": "9998887777",
            "address": "200 Dict Ave",
        },
        "items": [{"name": "Dict Item", "quantity": 1, "price": 10.0}],
    }
    response = OrderService.create_order(db=db_session, order_in=raw_dict)
    assert response.order_id == oid
    assert response.courier_partner == "mock"


def test_create_order_invalid_dict_raises_validation_error(db_session):
    """Verify invalid dict payload raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        OrderService.create_order(db=db_session, order_in={"bad": "payload"})
    assert exc_info.value.code == "VALIDATION_ERROR"


def test_create_order_duplicate_raises_duplicate_order_error(db_session):
    """Verify re-submitting an existing order_id raises DuplicateOrderError before calling courier."""
    req = _make_order_request()
    OrderService.create_order(db=db_session, order_in=req)

    # Second submission
    with pytest.raises(DuplicateOrderError) as exc_info:
        OrderService.create_order(db=db_session, order_in=req)

    assert exc_info.value.code == "DUPLICATE_ORDER"
    assert exc_info.value.status_code == 409
    assert req.order_id in exc_info.value.message


def test_create_order_integrity_error_handled_as_duplicate(db_session):
    """Verify database race-condition IntegrityError on commit is caught and mapped to DuplicateOrderError."""
    req = _make_order_request()

    # Pre-insert Order manually to simulate concurrent race
    db_session.add(
        Order(
            order_id=req.order_id,
            courier_partner="mock",
            status="CREATED",
        )
    )
    db_session.commit()

    # Mock DB pre-check passing (returning None) but commit failing with IntegrityError
    with patch.object(db_session, "execute") as mock_exec:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_exec.return_value = mock_result

        with pytest.raises(DuplicateOrderError) as exc_info:
            OrderService.create_order(db=db_session, order_in=req)

        assert exc_info.value.code == "DUPLICATE_ORDER"
        assert exc_info.value.status_code == 409


def test_create_order_unsupported_courier(db_session):
    """Verify requesting an unsupported courier partner raises UnsupportedCourierError."""
    req = _make_order_request(courier="nonexistent_partner")
    with pytest.raises(UnsupportedCourierError) as exc_info:
        OrderService.create_order(db=db_session, order_in=req)
    assert exc_info.value.code == "UNSUPPORTED_COURIER"
    assert exc_info.value.status_code == 400


def test_create_order_courier_timeout_propagation(db_session):
    """Verify courier timeout is propagated as CourierTimeoutError and transaction is not committed."""
    oid = f"ORD-TO-{uuid.uuid4().hex[:8].upper()}"
    req = _make_order_request(order_id=oid, customer_name="SIMULATE_TIMEOUT")

    with pytest.raises(CourierTimeoutError) as exc_info:
        OrderService.create_order(db=db_session, order_in=req)
    assert exc_info.value.code == "COURIER_TIMEOUT"

    # Confirm order was NOT persisted
    db_order = db_session.execute(
        select(Order).where(Order.order_id == oid)
    ).scalar_one_or_none()
    assert db_order is None


def test_create_order_courier_5xx_propagation(db_session):
    """Verify courier 5xx is propagated as CourierError and transaction rolled back."""
    oid = f"ORD-5XX-{uuid.uuid4().hex[:8].upper()}"
    req = _make_order_request(order_id=oid, customer_name="SIMULATE_5XX")

    with pytest.raises(CourierError) as exc_info:
        OrderService.create_order(db=db_session, order_in=req)
    assert exc_info.value.code == "COURIER_ERROR"

    db_order = db_session.execute(
        select(Order).where(Order.order_id == oid)
    ).scalar_one_or_none()
    assert db_order is None


# ============================================================================
# 2. Order Tracking Tests
# ============================================================================


def test_track_order_success_and_history_accumulation(db_session):
    """Verify track_order updates status and appends chronological events without mutating prior records."""
    req = _make_order_request()
    OrderService.create_order(db=db_session, order_in=req)

    # Initial history count = 1
    track_res1 = OrderService.track_order(db=db_session, order_id=req.order_id)
    assert track_res1.order_id == req.order_id
    assert track_res1.courier_partner == "mock"
    assert len(track_res1.history) >= 2

    # Track second time
    track_res2 = OrderService.track_order(db=db_session, order_id=req.order_id)
    assert len(track_res2.history) >= 3

    # Verify chronological ordering
    for i in range(len(track_res2.history) - 1):
        evt1 = track_res2.history[i]
        evt2 = track_res2.history[i + 1]
        assert evt1.status is not None
        assert evt2.status is not None
        if evt1.timestamp and evt2.timestamp:
            assert evt1.timestamp <= evt2.timestamp


def test_track_order_nonexistent_raises_not_found(db_session):
    """Verify tracking a non-existent order raises OrderNotFoundError."""
    with pytest.raises(OrderNotFoundError) as exc_info:
        OrderService.track_order(db=db_session, order_id="ORD-NONEXISTENT")
    assert exc_info.value.code == "ORDER_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_track_order_with_status_progression(db_session):
    """Verify tracking reflects simulated status progression."""
    # Use auto_progress adapter temporarily
    prog_adapter = MockCourierAdapter(auto_progress=True)
    courier_registry.register("mock_prog", prog_adapter)

    try:
        req = _make_order_request(courier="mock_prog")
        create_res = OrderService.create_order(db=db_session, order_in=req)
        assert create_res.status == "CREATED"

        # Tracking 1: advances CREATED -> PICKED_UP
        t1 = OrderService.track_order(db=db_session, order_id=req.order_id)
        assert t1.status == "PICKED_UP"

        # Tracking 2: advances PICKED_UP -> IN_TRANSIT
        t2 = OrderService.track_order(db=db_session, order_id=req.order_id)
        assert t2.status == "IN_TRANSIT"

        # Tracking 3: advances IN_TRANSIT -> DELIVERED
        t3 = OrderService.track_order(db=db_session, order_id=req.order_id)
        assert t3.status == "DELIVERED"

        # Check DB Order.status is DELIVERED
        order = db_session.execute(
            select(Order).where(Order.order_id == req.order_id)
        ).scalar_one()
        assert order.status == "DELIVERED"
    finally:
        courier_registry.unregister("mock_prog")


# ============================================================================
# 3. Order Cancellation Tests
# ============================================================================


def test_cancel_order_success(db_session):
    """Verify cancel_order transitions status to CANCELLED and appends to history."""
    req = _make_order_request()
    OrderService.create_order(db=db_session, order_in=req)

    cancel_res = OrderService.cancel_order(db=db_session, order_id=req.order_id)
    assert cancel_res.order_id == req.order_id
    assert cancel_res.status == "CANCELLED"

    # Verify DB status
    order = db_session.execute(
        select(Order).where(Order.order_id == req.order_id)
    ).scalar_one()
    assert order.status == "CANCELLED"

    # Verify CANCELLED in tracking history
    history = (
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == req.order_id)
        )
        .scalars()
        .all()
    )
    statuses = [h.status for h in history]
    assert "CANCELLED" in statuses


def test_cancel_order_idempotent_repetition(db_session):
    """Verify repeated cancellation returns CANCELLED without bloating tracking history."""
    req = _make_order_request()
    OrderService.create_order(db=db_session, order_in=req)

    res1 = OrderService.cancel_order(db=db_session, order_id=req.order_id)
    assert res1.status == "CANCELLED"

    history_count_1 = len(
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == req.order_id)
        )
        .scalars()
        .all()
    )

    # Repeat cancellation
    res2 = OrderService.cancel_order(db=db_session, order_id=req.order_id)
    assert res2.status == "CANCELLED"

    history_count_2 = len(
        db_session.execute(
            select(TrackingHistory).where(TrackingHistory.order_id == req.order_id)
        )
        .scalars()
        .all()
    )
    assert history_count_1 == history_count_2


def test_cancel_order_nonexistent_raises_not_found(db_session):
    """Verify cancelling non-existent order raises OrderNotFoundError."""
    with pytest.raises(OrderNotFoundError) as exc_info:
        OrderService.cancel_order(db=db_session, order_id="ORD-NONEXISTENT")
    assert exc_info.value.code == "ORDER_NOT_FOUND"
    assert exc_info.value.status_code == 404


# ============================================================================
# 4. Helper get_order Tests
# ============================================================================


def test_get_order_success_and_not_found(db_session):
    """Verify get_order returns order details or raises OrderNotFoundError."""
    req = _make_order_request()
    OrderService.create_order(db=db_session, order_in=req)

    found = OrderService.get_order(db=db_session, order_id=req.order_id)
    assert found.order_id == req.order_id
    assert found.courier_partner == "mock"

    with pytest.raises(OrderNotFoundError):
        OrderService.get_order(db=db_session, order_id="ORD-GHOST")


def test_track_order_updates_missing_awb(db_session):
    """Verify track_order updates order.awb_number if originally missing in database."""
    req = _make_order_request()
    OrderService.create_order(db=db_session, order_in=req)

    # Manually clear awb_number in DB
    order = db_session.execute(
        select(Order).where(Order.order_id == req.order_id)
    ).scalar_one()
    order.awb_number = None
    db_session.commit()

    # Track order
    res = OrderService.track_order(db=db_session, order_id=req.order_id)
    assert res.awb_number is not None

    # Check order row now has awb_number restored
    order = db_session.execute(
        select(Order).where(Order.order_id == req.order_id)
    ).scalar_one()
    assert order.awb_number is not None

