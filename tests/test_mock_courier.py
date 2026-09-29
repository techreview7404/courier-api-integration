"""Top-level tests for MockCourierAdapter verifying all simulated failure modes and lifecycle behavior."""

import pytest

from app.couriers.mock import MockCourierAdapter, MockSimulationMode
from app.exceptions import (
    CourierAuthError,
    CourierError,
    CourierTimeoutError,
    OrderNotFoundError,
    ValidationError,
)
from app.schemas.order import Customer, OrderCreateRequest, OrderItem
from app.schemas.tracking import OrderStatus


@pytest.fixture
def mock_courier():
    """Provide a fresh MockCourierAdapter instance per test."""
    adapter = MockCourierAdapter()
    adapter.reset()
    return adapter


def _make_order(order_id: str = "ORD-MOCK-001", customer_name: str = "Test Customer") -> OrderCreateRequest:
    """Helper to create a standard valid OrderCreateRequest."""
    return OrderCreateRequest(
        order_id=order_id,
        courier_partner="mock",
        customer=Customer(
            name=customer_name,
            phone="9876543210",
            address="123 Test Street, Mock City",
            city="Mock City",
            state="Mock State",
            pincode="123456",
        ),
        items=[OrderItem(name="Test Item", quantity=1, price=50.0)],
    )


# ============================================================================
# 1. Normal Success Lifecycle
# ============================================================================


def test_mock_courier_success_lifecycle(mock_courier):
    """Verify full end-to-end lifecycle with Mock courier: create, track, cancel, re-track."""
    order = _make_order("ORD-NORM-100", "Alice Normal")

    # 1. Create order
    create_res = mock_courier.create_order(order)
    assert create_res.courier_order_id.startswith("MOCK-ORD-")
    assert create_res.awb_number.startswith("AWB-MOCK-")
    assert create_res.status == OrderStatus.CREATED
    assert create_res.raw_response["status"] == "Success"

    awb = create_res.awb_number

    # 2. Track order by AWB
    track_res = mock_courier.track_order(awb)
    assert track_res.awb_number == awb
    assert track_res.status == OrderStatus.CREATED
    assert len(track_res.tracking_events) >= 1

    # 3. Track order by internal order_id
    track_res_by_id = mock_courier.track_order("ORD-NORM-100")
    assert track_res_by_id.awb_number == awb
    assert track_res_by_id.status == OrderStatus.CREATED

    # 4. Cancel order
    cancel_res = mock_courier.cancel_order(awb)
    assert cancel_res.status == OrderStatus.CANCELLED
    assert cancel_res.success is True

    # 5. Subsequent track must reflect CANCELLED
    track_after_cancel = mock_courier.track_order(awb)
    assert track_after_cancel.status == OrderStatus.CANCELLED


# ============================================================================
# 2. Simulation Mode: TIMEOUT
# ============================================================================


def test_mock_courier_simulation_mode_timeout(mock_courier):
    """Verify TIMEOUT simulation mode raises CourierTimeoutError across all operations."""
    mock_courier.set_simulation_mode(MockSimulationMode.TIMEOUT)
    order = _make_order("ORD-TIMEOUT-001")

    # create_order times out
    with pytest.raises(CourierTimeoutError) as exc_info:
        mock_courier.create_order(order)
    assert exc_info.value.code == "COURIER_TIMEOUT"
    assert exc_info.value.status_code == 504

    # track_order times out
    with pytest.raises(CourierTimeoutError):
        mock_courier.track_order("AWB-ANY")

    # cancel_order times out
    with pytest.raises(CourierTimeoutError):
        mock_courier.cancel_order("AWB-ANY")


# ============================================================================
# 3. Simulation Mode: SERVER_ERROR (5xx)
# ============================================================================


def test_mock_courier_simulation_mode_server_error(mock_courier):
    """Verify SERVER_ERROR simulation mode raises CourierError with status 502."""
    mock_courier.set_simulation_mode(MockSimulationMode.SERVER_ERROR)
    order = _make_order("ORD-5XX-001")

    with pytest.raises(CourierError) as exc_info:
        mock_courier.create_order(order)
    assert exc_info.value.code == "COURIER_ERROR"
    assert exc_info.value.status_code == 502
    assert "HTTP 500" in exc_info.value.message

    with pytest.raises(CourierError):
        mock_courier.track_order("AWB-ANY")

    with pytest.raises(CourierError):
        mock_courier.cancel_order("AWB-ANY")


# ============================================================================
# 4. Simulation Mode: CLIENT_ERROR (4xx)
# ============================================================================


def test_mock_courier_simulation_mode_client_error(mock_courier):
    """Verify CLIENT_ERROR simulation mode raises ValidationError with status 400."""
    mock_courier.set_simulation_mode(MockSimulationMode.CLIENT_ERROR)
    order = _make_order("ORD-4XX-001")

    with pytest.raises(ValidationError) as exc_info:
        mock_courier.create_order(order)
    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.status_code == 400
    assert "HTTP 400" in exc_info.value.message


# ============================================================================
# 5. Simulation Mode: AUTH_FAILURE & Self-Healing Re-Authentication
# ============================================================================


def test_mock_courier_simulation_mode_auth_failure_with_refresh(mock_courier):
    """Verify AUTH_FAILURE triggers 401, then succeeds after calling authenticate()."""
    mock_courier.set_simulation_mode(MockSimulationMode.AUTH_FAILURE)
    order = _make_order("ORD-AUTH-001")

    # First attempt: 401 Auth Error
    with pytest.raises(CourierAuthError) as exc_info:
        mock_courier.create_order(order)
    assert exc_info.value.code == "COURIER_AUTH_ERROR"
    assert exc_info.value.status_code == 502

    # Simulate token refresh by calling authenticate()
    mock_courier.authenticate()

    # Second attempt: succeeds
    res = mock_courier.create_order(order)
    assert res.status == OrderStatus.CREATED
    assert res.courier_order_id.startswith("MOCK-ORD-")


def test_mock_courier_simulation_mode_permanent_auth_failure(mock_courier):
    """Verify permanent auth failure continues to raise CourierAuthError even after authenticate()."""
    mock_courier.set_simulation_mode(MockSimulationMode.AUTH_FAILURE)
    mock_courier.set_permanent_auth_failure(True)
    order = _make_order("ORD-AUTH-PERM")

    with pytest.raises(CourierAuthError):
        mock_courier.create_order(order)

    mock_courier.authenticate()

    with pytest.raises(CourierAuthError):
        mock_courier.create_order(order)


# ============================================================================
# 6. Per-Order Outcome Flags for Granular Bulk Testing
# ============================================================================


def test_mock_courier_per_order_timeout_flag(mock_courier):
    """Verify SIMULATE_TIMEOUT in customer name triggers timeout without changing global mode."""
    order = _make_order("ORD-BULK-1", "John SIMULATE_TIMEOUT Doe")
    with pytest.raises(CourierTimeoutError):
        mock_courier.create_order(order)

    # Next normal order succeeds
    normal_order = _make_order("ORD-BULK-2", "Jane Normal")
    res = mock_courier.create_order(normal_order)
    assert res.status == OrderStatus.CREATED


def test_mock_courier_per_order_5xx_flag(mock_courier):
    """Verify SIMULATE_5XX in customer name triggers 5xx server error."""
    order = _make_order("ORD-BULK-3", "Bob SIMULATE_5XX Smith")
    with pytest.raises(CourierError) as exc_info:
        mock_courier.create_order(order)
    assert exc_info.value.code == "COURIER_ERROR"


def test_mock_courier_per_order_4xx_flag(mock_courier):
    """Verify SIMULATE_4XX in customer name triggers 4xx validation error."""
    order = _make_order("ORD-BULK-4", "Charlie SIMULATE_4XX Davis")
    with pytest.raises(ValidationError) as exc_info:
        mock_courier.create_order(order)
    assert exc_info.value.code == "VALIDATION_ERROR"


def test_mock_courier_per_order_auth_fail_flag(mock_courier):
    """Verify SIMULATE_AUTH_FAIL in customer name triggers 401 auth error until reauthenticated."""
    order = _make_order("ORD-BULK-5", "Eve SIMULATE_AUTH_FAIL")
    with pytest.raises(CourierAuthError):
        mock_courier.create_order(order)

    mock_courier.authenticate()
    res = mock_courier.create_order(order)
    assert res.status == OrderStatus.CREATED


def test_mock_courier_per_order_status_flags(mock_courier):
    """Verify SIMULATE_<STATUS> flags create orders directly in specific statuses."""
    order_picked = _make_order("ORD-ST-1", "User SIMULATE_PICKED_UP")
    res_picked = mock_courier.create_order(order_picked)
    assert res_picked.status == OrderStatus.PICKED_UP

    order_transit = _make_order("ORD-ST-2", "User SIMULATE_IN_TRANSIT")
    res_transit = mock_courier.create_order(order_transit)
    assert res_transit.status == OrderStatus.IN_TRANSIT

    order_delivered = _make_order("ORD-ST-3", "User SIMULATE_DELIVERED")
    res_delivered = mock_courier.create_order(order_delivered)
    assert res_delivered.status == OrderStatus.DELIVERED


# ============================================================================
# 7. Auto-Progression of Tracking States
# ============================================================================


def test_mock_courier_auto_progress_tracking():
    """Verify auto_progress progresses order status across successive track calls."""
    adapter = MockCourierAdapter(auto_progress=True)
    order = _make_order("ORD-PROG-1", "Progress User")

    created = adapter.create_order(order)
    awb = created.awb_number
    assert created.status == OrderStatus.CREATED

    # 1st track: CREATED -> PICKED_UP
    track_1 = adapter.track_order(awb)
    assert track_1.status == OrderStatus.PICKED_UP

    # 2nd track: PICKED_UP -> IN_TRANSIT
    track_2 = adapter.track_order(awb)
    assert track_2.status == OrderStatus.IN_TRANSIT

    # 3rd track: IN_TRANSIT -> DELIVERED
    track_3 = adapter.track_order(awb)
    assert track_3.status == OrderStatus.DELIVERED

    # 4th track: stays DELIVERED (terminal state)
    track_4 = adapter.track_order(awb)
    assert track_4.status == OrderStatus.DELIVERED


# ============================================================================
# 8. Non-Existent Order Tracking
# ============================================================================


def test_mock_courier_track_nonexistent_order_raises_not_found(mock_courier):
    """Verify tracking an unknown ID raises OrderNotFoundError with status 404."""
    with pytest.raises(OrderNotFoundError) as exc_info:
        mock_courier.track_order("AWB-COMPLETELY-UNKNOWN")

    assert exc_info.value.code == "ORDER_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_mock_courier_cancel_nonexistent_order_raises_not_found(mock_courier):
    """Verify cancelling an unknown ID raises OrderNotFoundError."""
    with pytest.raises(OrderNotFoundError):
        mock_courier.cancel_order("AWB-NONEXISTENT")
