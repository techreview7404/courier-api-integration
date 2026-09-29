"""Empirical stress-testing and verification suite for MockCourierAdapter.

Authored by Challenger 1 (Milestone 2).
Exhaustively stresses and validates:
1. State persistence across order creation, tracking updates, and cancellation.
2. All global simulation modes (SUCCESS, TIMEOUT, SERVER_ERROR, CLIENT_ERROR, AUTH_FAILURE).
3. Per-order outcome flags in order_id, customer name, and tracking_id across cases.
4. Concurrent operations against MockCourierAdapter without race conditions or memory corruption.
5. Dual synchronous and asynchronous (AwaitableDTO) execution compatibility.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# ============================================================================
# Helpers & Fixtures
# ============================================================================


def make_order(
    order_id: str = "ORD-EMPIRICAL-001",
    customer_name: str = "Empirical Test User",
    items_count: int = 1,
) -> OrderCreateRequest:
    """Construct a strongly-typed OrderCreateRequest for empirical testing."""
    return OrderCreateRequest(
        order_id=order_id,
        courier_partner="mock",
        customer=Customer(
            name=customer_name,
            phone="9876543210",
            address="123 Empirical Blvd, Suite 400",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
        ),
        items=[
            OrderItem(name=f"Item {i}", quantity=1, price=100.0)
            for i in range(1, items_count + 1)
        ],
    )


@pytest.fixture
def fresh_mock():
    """Provide a pristine MockCourierAdapter instance per test."""
    adapter = MockCourierAdapter()
    adapter.reset()
    return adapter


# ============================================================================
# 1. State Persistence Across Lifecycle
# ============================================================================


class TestMockCourierStatePersistence:
    """Verify state persistence across creation, tracking updates, and cancellation."""

    def test_multiple_orders_independent_persistence(self, fresh_mock):
        """Verify multiple created orders maintain distinct isolated state in mock store."""
        order_1 = make_order("ORD-STATE-001", "Alice Alpha")
        order_2 = make_order("ORD-STATE-002", "Bob Beta")
        order_3 = make_order("ORD-STATE-003", "Charlie Gamma")

        res_1 = fresh_mock.create_order(order_1)
        res_2 = fresh_mock.create_order(order_2)
        res_3 = fresh_mock.create_order(order_3)

        assert res_1.awb_number != res_2.awb_number != res_3.awb_number
        assert res_1.courier_order_id != res_2.courier_order_id != res_3.courier_order_id

        # Verify tracking each independently by AWB
        track_1 = fresh_mock.track_order(res_1.awb_number)
        track_2 = fresh_mock.track_order(res_2.awb_number)
        track_3 = fresh_mock.track_order(res_3.awb_number)

        assert track_1.awb_number == res_1.awb_number
        assert track_2.awb_number == res_2.awb_number
        assert track_3.awb_number == res_3.awb_number

        # Verify tracking by internal order_id
        track_by_id_1 = fresh_mock.track_order("ORD-STATE-001")
        assert track_by_id_1.awb_number == res_1.awb_number

    def test_order_creation_from_dict_payload(self, fresh_mock):
        """Verify create_order seamlessly accepts plain dictionary payloads."""
        payload = {
            "order_id": "ORD-DICT-999",
            "courier_partner": "mock",
            "customer": {"name": "Dict Customer", "phone": "9999999999"},
            "items": [{"name": "Widget", "quantity": 2, "price": 49.99}],
        }
        res = fresh_mock.create_order(payload)
        assert res.courier_order_id == "MOCK-ORD-DICT-999"
        assert res.status == OrderStatus.CREATED

        track = fresh_mock.track_order(res.awb_number)
        assert track.status == OrderStatus.CREATED

    def test_tracking_auto_progress_full_chain(self):
        """Verify auto_progress transitions through CREATED -> PICKED_UP -> IN_TRANSIT -> DELIVERED."""
        adapter = MockCourierAdapter(auto_progress=True)
        order = make_order("ORD-CHAIN-001", "Chain User")
        res = adapter.create_order(order)
        awb = res.awb_number

        # 1st track -> PICKED_UP
        t1 = adapter.track_order(awb)
        assert t1.status == OrderStatus.PICKED_UP
        assert len(t1.tracking_events) == 2

        # 2nd track -> IN_TRANSIT
        t2 = adapter.track_order(awb)
        assert t2.status == OrderStatus.IN_TRANSIT
        assert len(t2.tracking_events) == 3

        # 3rd track -> DELIVERED
        t3 = adapter.track_order(awb)
        assert t3.status == OrderStatus.DELIVERED
        assert len(t3.tracking_events) == 4

        # 4th & 5th track -> terminal state DELIVERED, no duplicate events
        t4 = adapter.track_order(awb)
        t5 = adapter.track_order(awb)
        assert t4.status == OrderStatus.DELIVERED
        assert t5.status == OrderStatus.DELIVERED
        assert len(t5.tracking_events) == 4

    def test_tracking_auto_progress_disabled_by_default(self, fresh_mock):
        """Verify default auto_progress=False preserves static status across repeated track calls."""
        order = make_order("ORD-STATIC-001", "Static User")
        res = fresh_mock.create_order(order)

        for _ in range(5):
            track = fresh_mock.track_order(res.awb_number)
            assert track.status == OrderStatus.CREATED
            assert len(track.tracking_events) == 1

    def test_cancellation_lifecycle_and_idempotency(self, fresh_mock):
        """Verify order cancellation transitions status, appends audit, and is idempotent."""
        order = make_order("ORD-CANCEL-001", "Cancel User")
        res = fresh_mock.create_order(order)
        awb = res.awb_number

        # Initial track is CREATED
        assert fresh_mock.track_order(awb).status == OrderStatus.CREATED

        # First cancellation
        c1 = fresh_mock.cancel_order(awb)
        assert c1.status == OrderStatus.CANCELLED
        assert c1.success is True

        # Track reflects CANCELLED
        t1 = fresh_mock.track_order(awb)
        assert t1.status == OrderStatus.CANCELLED
        assert len(t1.tracking_events) == 2
        assert t1.tracking_events[-1]["status"] == "CANCELLED"
        assert "cancelled by client" in t1.tracking_events[-1]["message"].lower()

        # Second cancellation is safe and maintains CANCELLED
        c2 = fresh_mock.cancel_order(awb)
        assert c2.status == OrderStatus.CANCELLED
        assert c2.success is True

    def test_cancelled_order_does_not_auto_progress(self):
        """Verify an order cancelled prior to auto_progress never progresses."""
        adapter = MockCourierAdapter(auto_progress=True)
        order = make_order("ORD-CANCEL-PROG", "Cancel Progress User")
        res = adapter.create_order(order)
        adapter.cancel_order(res.awb_number)

        # Subsequent tracking attempts must stay CANCELLED
        for _ in range(3):
            track = adapter.track_order(res.awb_number)
            assert track.status == OrderStatus.CANCELLED

    def test_track_and_cancel_nonexistent_order_raises(self, fresh_mock):
        """Verify tracking or cancelling an unknown tracking ID raises OrderNotFoundError (404)."""
        with pytest.raises(OrderNotFoundError) as exc_track:
            fresh_mock.track_order("AWB-NONEXISTENT-XYZ")
        assert exc_track.value.code == "ORDER_NOT_FOUND"
        assert exc_track.value.status_code == 404

        with pytest.raises(OrderNotFoundError) as exc_cancel:
            fresh_mock.cancel_order("AWB-NONEXISTENT-XYZ")
        assert exc_cancel.value.code == "ORDER_NOT_FOUND"
        assert exc_cancel.value.status_code == 404

    def test_reset_clears_all_state(self, fresh_mock):
        """Verify reset() purges all stored orders, mappings, and reverts simulation modes."""
        order = make_order("ORD-RESET-001", "Reset User")
        res = fresh_mock.create_order(order)
        awb = res.awb_number

        fresh_mock.set_simulation_mode(MockSimulationMode.TIMEOUT)
        fresh_mock.set_permanent_auth_failure(True)

        # Execute reset
        fresh_mock.reset()

        assert fresh_mock.simulation_mode == MockSimulationMode.SUCCESS
        assert len(fresh_mock._orders) == 0
        assert len(fresh_mock._awb_to_order_id) == 0

        # Former order no longer exists
        with pytest.raises(OrderNotFoundError):
            fresh_mock.track_order(awb)


# ============================================================================
# 2. Global Simulation Modes
# ============================================================================


class TestMockCourierGlobalSimulationModes:
    """Verify all global simulation modes across create, track, and cancel operations."""

    def test_global_timeout_simulation(self, fresh_mock):
        """Verify TIMEOUT mode raises CourierTimeoutError (504) across all operations."""
        fresh_mock.set_simulation_mode(MockSimulationMode.TIMEOUT)

        # create_order
        with pytest.raises(CourierTimeoutError) as exc_create:
            fresh_mock.create_order(make_order("ORD-T1"))
        assert exc_create.value.code == "COURIER_TIMEOUT"
        assert exc_create.value.status_code == 504

        # track_order
        with pytest.raises(CourierTimeoutError) as exc_track:
            fresh_mock.track_order("AWB-ANY")
        assert exc_track.value.code == "COURIER_TIMEOUT"
        assert exc_track.value.status_code == 504

        # cancel_order
        with pytest.raises(CourierTimeoutError) as exc_cancel:
            fresh_mock.cancel_order("AWB-ANY")
        assert exc_cancel.value.code == "COURIER_TIMEOUT"
        assert exc_cancel.value.status_code == 504

    def test_global_server_error_simulation(self, fresh_mock):
        """Verify SERVER_ERROR mode raises CourierError (502) with 500 status details."""
        fresh_mock.set_simulation_mode(MockSimulationMode.SERVER_ERROR)

        # create_order
        with pytest.raises(CourierError) as exc_create:
            fresh_mock.create_order(make_order("ORD-5XX"))
        assert exc_create.value.code == "COURIER_ERROR"
        assert exc_create.value.status_code == 502
        assert exc_create.value.details.get("status_code") == 500

        # track_order
        with pytest.raises(CourierError) as exc_track:
            fresh_mock.track_order("AWB-ANY")
        assert exc_track.value.status_code == 502
        assert exc_track.value.details.get("status_code") == 500

        # cancel_order
        with pytest.raises(CourierError) as exc_cancel:
            fresh_mock.cancel_order("AWB-ANY")
        assert exc_cancel.value.status_code == 502
        assert exc_cancel.value.details.get("status_code") == 500

    def test_global_client_error_simulation(self, fresh_mock):
        """Verify CLIENT_ERROR mode raises ValidationError (400) across all operations."""
        fresh_mock.set_simulation_mode(MockSimulationMode.CLIENT_ERROR)

        # create_order
        with pytest.raises(ValidationError) as exc_create:
            fresh_mock.create_order(make_order("ORD-4XX"))
        assert exc_create.value.code == "VALIDATION_ERROR"
        assert exc_create.value.status_code == 400
        assert exc_create.value.details.get("status_code") == 400

        # track_order
        with pytest.raises(ValidationError) as exc_track:
            fresh_mock.track_order("AWB-ANY")
        assert exc_track.value.status_code == 400

        # cancel_order
        with pytest.raises(ValidationError) as exc_cancel:
            fresh_mock.cancel_order("AWB-ANY")
        assert exc_cancel.value.status_code == 400

    def test_global_auth_failure_and_healing(self, fresh_mock):
        """Verify AUTH_FAILURE mode raises CourierAuthError (502) and recovers on authenticate()."""
        fresh_mock.set_simulation_mode(MockSimulationMode.AUTH_FAILURE)

        # 1. Initial attempt fails with 401 CourierAuthError
        with pytest.raises(CourierAuthError) as exc_auth:
            fresh_mock.create_order(make_order("ORD-AUTH-1"))
        assert exc_auth.value.code == "COURIER_AUTH_ERROR"
        assert exc_auth.value.status_code == 502
        assert exc_auth.value.details.get("status_code") == 401

        # 2. Call authenticate() to heal
        fresh_mock.authenticate()
        assert fresh_mock._auth_call_count == 1

        # 3. Subsequent call succeeds
        res = fresh_mock.create_order(make_order("ORD-AUTH-1"))
        assert res.status == OrderStatus.CREATED

    def test_global_permanent_auth_failure(self, fresh_mock):
        """Verify permanent auth failure mode persists even after repeated authenticate() calls."""
        fresh_mock.set_simulation_mode(MockSimulationMode.AUTH_FAILURE)
        fresh_mock.set_permanent_auth_failure(True)

        for _ in range(3):
            with pytest.raises(CourierAuthError):
                fresh_mock.create_order(make_order("ORD-PERM-AUTH"))
            fresh_mock.authenticate()

    def test_simulation_mode_setter_supports_string_and_enum(self, fresh_mock):
        """Verify set_simulation_mode and property setter accept both str and MockSimulationMode."""
        assert fresh_mock.partner_name == "mock"

        fresh_mock.set_simulation_mode("TIMEOUT")
        assert fresh_mock.simulation_mode == MockSimulationMode.TIMEOUT

        fresh_mock.set_simulation_mode(MockSimulationMode.SUCCESS)
        assert fresh_mock.simulation_mode == MockSimulationMode.SUCCESS

        fresh_mock.simulation_mode = "SERVER_ERROR"
        assert fresh_mock.simulation_mode == MockSimulationMode.SERVER_ERROR

        fresh_mock.simulation_mode = MockSimulationMode.CLIENT_ERROR
        assert fresh_mock.simulation_mode == MockSimulationMode.CLIENT_ERROR

        with pytest.raises(ValueError):
            fresh_mock.simulation_mode = "INVALID_MODE"


# ============================================================================
# 3. Per-Order Outcome Flags
# ============================================================================


class TestMockCourierPerOrderFlags:
    """Verify per-order outcome flags in order_id and customer.name."""

    @pytest.mark.parametrize(
        "flag,expected_exception,expected_code,expected_status",
        [
            ("SIMULATE_TIMEOUT", CourierTimeoutError, "COURIER_TIMEOUT", 504),
            ("SIMULATE_5XX", CourierError, "COURIER_ERROR", 502),
            ("SIMULATE_SERVER_ERROR", CourierError, "COURIER_ERROR", 502),
            ("SIMULATE_4XX", ValidationError, "VALIDATION_ERROR", 400),
            ("SIMULATE_CLIENT_ERROR", ValidationError, "VALIDATION_ERROR", 400),
            ("SIMULATE_AUTH_FAIL", CourierAuthError, "COURIER_AUTH_ERROR", 502),
        ],
    )
    def test_per_order_failure_flags_in_order_id(
        self, fresh_mock, flag, expected_exception, expected_code, expected_status
    ):
        """Verify failure simulation flags in order_id trigger expected exceptions."""
        order = make_order(f"ORD-{flag}-123", "Standard User")
        with pytest.raises(expected_exception) as exc_info:
            fresh_mock.create_order(order)
        assert exc_info.value.code == expected_code
        assert exc_info.value.status_code == expected_status

    @pytest.mark.parametrize(
        "flag,expected_exception,expected_code,expected_status",
        [
            ("SIMULATE_TIMEOUT", CourierTimeoutError, "COURIER_TIMEOUT", 504),
            ("SIMULATE_5XX", CourierError, "COURIER_ERROR", 502),
            ("SIMULATE_SERVER_ERROR", CourierError, "COURIER_ERROR", 502),
            ("SIMULATE_4XX", ValidationError, "VALIDATION_ERROR", 400),
            ("SIMULATE_CLIENT_ERROR", ValidationError, "VALIDATION_ERROR", 400),
            ("SIMULATE_AUTH_FAIL", CourierAuthError, "COURIER_AUTH_ERROR", 502),
        ],
    )
    def test_per_order_failure_flags_in_customer_name(
        self, fresh_mock, flag, expected_exception, expected_code, expected_status
    ):
        """Verify failure simulation flags in customer name trigger expected exceptions."""
        order = make_order("ORD-NORMAL-ID", f"Jane {flag} Doe")
        with pytest.raises(expected_exception) as exc_info:
            fresh_mock.create_order(order)
        assert exc_info.value.code == expected_code
        assert exc_info.value.status_code == expected_status

    def test_per_order_flags_case_insensitivity(self, fresh_mock):
        """Verify per-order flags are case-insensitive."""
        order_timeout_lower = make_order("ORD-001", "User simulate_timeout")
        with pytest.raises(CourierTimeoutError):
            fresh_mock.create_order(order_timeout_lower)

        order_5xx_mixed = make_order("ord-simulate_5xx-002", "User Normal")
        with pytest.raises(CourierError):
            fresh_mock.create_order(order_5xx_mixed)

        order_4xx_lower = make_order("ORD-003", "User simulate_client_error")
        with pytest.raises(ValidationError):
            fresh_mock.create_order(order_4xx_lower)

    @pytest.mark.parametrize(
        "flag,expected_status",
        [
            ("SIMULATE_PICKED_UP", OrderStatus.PICKED_UP),
            ("SIMULATE_IN_TRANSIT", OrderStatus.IN_TRANSIT),
            ("SIMULATE_DELIVERED", OrderStatus.DELIVERED),
            ("SIMULATE_FAILED", OrderStatus.FAILED),
        ],
    )
    def test_per_order_status_flags_in_order_id_and_customer(
        self, fresh_mock, flag, expected_status
    ):
        """Verify status simulation flags configure initial lifecycle status."""
        # Flag in order_id
        res_by_id = fresh_mock.create_order(make_order(f"ORD-{flag}-1", "Normal Name"))
        assert res_by_id.status == expected_status

        # Flag in customer name
        res_by_name = fresh_mock.create_order(make_order(f"ORD-TEST-{flag}-2", f"Cust {flag}"))
        assert res_by_name.status == expected_status

    def test_per_order_flags_do_not_leak_across_orders(self, fresh_mock):
        """Verify that an order with a failure flag does not contaminate subsequent orders."""
        failing_order = make_order("ORD-FAIL-1", "User SIMULATE_TIMEOUT")
        with pytest.raises(CourierTimeoutError):
            fresh_mock.create_order(failing_order)

        # Subsequent standard order must succeed completely
        normal_order = make_order("ORD-OK-2", "Normal Customer")
        res = fresh_mock.create_order(normal_order)
        assert res.status == OrderStatus.CREATED
        assert res.courier_order_id == "MOCK-ORD-OK-2"

        # Subsequent status check must be CREATED
        track = fresh_mock.track_order(res.awb_number)
        assert track.status == OrderStatus.CREATED

    def test_per_order_failure_flags_in_tracking_and_cancel_calls(self, fresh_mock):
        """Verify failure flags embedded in tracking ID trigger simulations on track/cancel."""
        with pytest.raises(CourierTimeoutError):
            fresh_mock.track_order("AWB-SIMULATE_TIMEOUT-99")

        with pytest.raises(CourierError):
            fresh_mock.cancel_order("AWB-SIMULATE_5XX-99")

        with pytest.raises(ValidationError):
            fresh_mock.track_order("AWB-SIMULATE_4XX-99")


# ============================================================================
# 4. Concurrency & Stress Testing
# ============================================================================


class TestMockCourierConcurrencyAndStress:
    """Stress test MockCourierAdapter under multithreaded and asynchronous concurrency."""

    def test_concurrent_order_creation_100_threads(self, fresh_mock):
        """Empirically stress 100 concurrent threads creating orders against single mock adapter."""
        total_orders = 100

        def create_single_order(idx: int) -> tuple[str, str]:
            order = make_order(f"ORD-CONCUR-{idx:04d}", f"Customer {idx}")
            result = fresh_mock.create_order(order)
            return order.order_id, result.awb_number

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(create_single_order, i) for i in range(total_orders)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == total_orders

        # Verify all 100 orders are persisted without loss or memory corruption
        assert len(fresh_mock._orders) == total_orders
        assert len(fresh_mock._awb_to_order_id) == total_orders

        # Verify all 100 orders can be retrieved concurrently
        def verify_tracking(order_id: str, awb: str) -> bool:
            track = fresh_mock.track_order(awb)
            return track.status == OrderStatus.CREATED and track.awb_number == awb

        with ThreadPoolExecutor(max_workers=20) as executor:
            verify_futures = [executor.submit(verify_tracking, oid, awb) for oid, awb in results]
            assert all(f.result() for f in as_completed(verify_futures))

    def test_concurrent_tracking_auto_progress(self):
        """Verify concurrent track calls on a single order with auto_progress advance to terminal DELIVERED."""
        adapter = MockCourierAdapter(auto_progress=True)
        order = make_order("ORD-CONCUR-PROG", "Concurrent Progress User")
        res = adapter.create_order(order)
        awb = res.awb_number

        def call_track():
            return adapter.track_order(awb)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(call_track) for _ in range(30)]
            track_results = [f.result() for f in as_completed(futures)]

        # Terminal state must be DELIVERED
        final_track = adapter.track_order(awb)
        assert final_track.status == OrderStatus.DELIVERED

        # All results should have a valid OrderStatus
        for tr in track_results:
            assert tr.status in {
                OrderStatus.CREATED,
                OrderStatus.PICKED_UP,
                OrderStatus.IN_TRANSIT,
                OrderStatus.DELIVERED,
            }

    def test_concurrent_mixed_operations(self, fresh_mock):
        """Stress concurrent mixed operations: create, track, cancel, and simulate errors."""
        order_count = 50

        # Pre-create some orders
        for i in range(20):
            fresh_mock.create_order(make_order(f"ORD-MIX-{i:03d}"))

        def worker_task(idx: int):
            if idx % 4 == 0:
                # Create normal order
                return fresh_mock.create_order(make_order(f"ORD-MIX-NEW-{idx}")).status
            elif idx % 4 == 1:
                # Track existing order
                awb = f"AWB-MOCK-MIX-{idx % 20:03d}"
                return fresh_mock.track_order(awb).status
            elif idx % 4 == 2:
                # Cancel existing order
                awb = f"AWB-MOCK-MIX-{idx % 20:03d}"
                return fresh_mock.cancel_order(awb).status
            else:
                # Trigger simulated failure
                try:
                    fresh_mock.create_order(make_order(f"ORD-MIX-FAIL-{idx}", "SIMULATE_TIMEOUT"))
                except CourierTimeoutError:
                    return "TIMEOUT_HANDLED"
                return "UNEXPECTED"

        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(worker_task, i) for i in range(order_count)]
            outcomes = [f.result() for f in as_completed(futures)]

        assert len(outcomes) == order_count
        assert "TIMEOUT_HANDLED" in outcomes

    @pytest.mark.asyncio
    async def test_async_awaitable_dto_concurrency(self, fresh_mock):
        """Verify AwaitableDTO allows 50 concurrent async coroutines to await mock adapter methods."""
        async def async_worker(idx: int):
            order = make_order(f"ORD-ASYNC-{idx}")
            # Test 'await adapter.create_order()'
            created = await fresh_mock.create_order(order)
            assert created.status == OrderStatus.CREATED

            # Test 'await adapter.track_order()'
            tracked = await fresh_mock.track_order(created.awb_number)
            assert tracked.status == OrderStatus.CREATED

            # Test 'await adapter.cancel_order()'
            cancelled = await fresh_mock.cancel_order(created.awb_number)
            assert cancelled.status == OrderStatus.CANCELLED
            return True

        tasks = [async_worker(i) for i in range(50)]
        results = await asyncio.gather(*tasks)
        assert all(results)
        assert len(fresh_mock._orders) == 50
