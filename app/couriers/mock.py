"""Mock Courier Adapter for offline development and deterministic simulation."""

from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Optional
import uuid

from app.couriers.base import (
    CourierAdapter,
    CourierCancelResult,
    CourierOrderResult,
    CourierTrackingResult,
)
from app.exceptions import (
    CourierAuthError,
    CourierError,
    CourierTimeoutError,
    OrderNotFoundError,
    ValidationError,
)
from app.schemas.order import OrderCreateRequest
from app.schemas.tracking import OrderStatus

logger = logging.getLogger("courier_platform.couriers.mock")


class MockSimulationMode(str, Enum):
    """Simulated failure modes supported by MockCourierAdapter."""

    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    SERVER_ERROR = "SERVER_ERROR"
    CLIENT_ERROR = "CLIENT_ERROR"
    AUTH_FAILURE = "AUTH_FAILURE"


class MockCourierAdapter(CourierAdapter):
    """Simulated courier adapter supporting deterministic error injection and offline lifecycle testing."""

    def __init__(
        self,
        mode: MockSimulationMode = MockSimulationMode.SUCCESS,
        auto_progress: bool = False,
    ):
        self._mode = mode
        self._auto_progress = auto_progress
        self._authenticated = False
        self._auth_call_count = 0
        self._reauthenticated = False
        self._permanent_auth_failure = False

        # In-memory persistence maintaining real state
        self._orders: dict[str, dict[str, Any]] = {}
        self._awb_to_order_id: dict[str, str] = {}

    @property
    def partner_name(self) -> str:
        return "mock"

    @property
    def simulation_mode(self) -> MockSimulationMode:
        return self._mode

    @simulation_mode.setter
    def simulation_mode(self, mode: MockSimulationMode | str) -> None:
        if isinstance(mode, str):
            self._mode = MockSimulationMode(mode)
        else:
            self._mode = mode

    def set_simulation_mode(self, mode: MockSimulationMode | str) -> None:
        """Set the global simulation mode for subsequent operations."""
        self.simulation_mode = mode

    def set_permanent_auth_failure(self, permanent: bool) -> None:
        """Configure whether auth failure persists across re-authentication attempts."""
        self._permanent_auth_failure = permanent

    def reset(self) -> None:
        """Reset internal state, mock store, and simulation modes."""
        self._mode = MockSimulationMode.SUCCESS
        self._authenticated = False
        self._auth_call_count = 0
        self._reauthenticated = False
        self._permanent_auth_failure = False
        self._orders.clear()
        self._awb_to_order_id.clear()

    def authenticate(self) -> None:
        """Authenticate with simulated mock backend and reset one-time auth failure flag."""
        self._auth_call_count += 1
        if not self._permanent_auth_failure:
            self._authenticated = True
            self._reauthenticated = True
            logger.info("Mock courier authenticated successfully (call %d)", self._auth_call_count)
        else:
            logger.warning("Mock courier permanent authentication failure simulated")

    def _check_simulation(
        self,
        order_id: Optional[str] = None,
        customer_name: Optional[str] = None,
        operation: str = "create_order",
    ) -> None:
        """Evaluate global simulation mode and per-order outcome flags."""
        combined_text = f"{order_id or ''} {customer_name or ''}".upper()

        # 1. Per-order or global TIMEOUT simulation
        if self._mode == MockSimulationMode.TIMEOUT or "SIMULATE_TIMEOUT" in combined_text:
            logger.info("Mock courier triggering simulated timeout for %s (%s)", order_id, operation)
            raise CourierTimeoutError(f"Mock courier connection timed out during {operation}")

        # 2. Per-order or global 5xx SERVER_ERROR simulation
        if (
            self._mode == MockSimulationMode.SERVER_ERROR
            or "SIMULATE_5XX" in combined_text
            or "SIMULATE_SERVER_ERROR" in combined_text
        ):
            logger.info("Mock courier triggering simulated 5xx error for %s (%s)", order_id, operation)
            raise CourierError(
                f"Mock courier upstream internal error (HTTP 500) during {operation}",
                details={"status_code": 500, "operation": operation},
            )

        # 3. Per-order or global 4xx CLIENT_ERROR simulation
        if (
            self._mode == MockSimulationMode.CLIENT_ERROR
            or "SIMULATE_4XX" in combined_text
            or "SIMULATE_CLIENT_ERROR" in combined_text
        ):
            logger.info("Mock courier triggering simulated 4xx error for %s (%s)", order_id, operation)
            raise ValidationError(
                f"Mock courier client error (HTTP 400) during {operation}",
                details={"status_code": 400, "operation": operation},
            )

        # 4. Per-order or global 401 AUTH_FAILURE simulation
        if (
            self._mode == MockSimulationMode.AUTH_FAILURE
            or "SIMULATE_AUTH_FAIL" in combined_text
        ):
            if not self._reauthenticated or self._permanent_auth_failure:
                logger.info(
                    "Mock courier triggering simulated 401 auth failure for %s (%s)", order_id, operation
                )
                raise CourierAuthError(
                    f"Mock courier authentication failed (HTTP 401) during {operation}",
                    details={"status_code": 401, "operation": operation},
                )

    def create_order(self, order: OrderCreateRequest | dict[str, Any]) -> CourierOrderResult:
        """Create mock order, generating synthetic identifiers and persisting state."""
        # Normalize order input
        if isinstance(order, dict):
            order_id = order.get("order_id", f"ORD-{uuid.uuid4().hex[:8].upper()}")
            customer = order.get("customer", {})
            customer_name = customer.get("name", "") if isinstance(customer, dict) else getattr(customer, "name", "")
            items = order.get("items", [])
        else:
            order_id = order.order_id
            customer = order.customer
            customer_name = order.customer.name
            items = order.items

        # Check simulation triggers
        self._check_simulation(order_id=order_id, customer_name=customer_name, operation="create_order")

        # Determine initial status based on per-order flags
        combined_text = f"{order_id} {customer_name}".upper()
        if "SIMULATE_PICKED_UP" in combined_text:
            status = OrderStatus.PICKED_UP
        elif "SIMULATE_IN_TRANSIT" in combined_text:
            status = OrderStatus.IN_TRANSIT
        elif "SIMULATE_DELIVERED" in combined_text:
            status = OrderStatus.DELIVERED
        elif "SIMULATE_FAILED" in combined_text:
            status = OrderStatus.FAILED
        else:
            status = OrderStatus.CREATED

        courier_order_id = f"MOCK-{order_id}"
        awb_number = f"AWB-MOCK-{order_id.replace('ORD-', '')}"

        now_iso = datetime.now(timezone.utc).isoformat()
        initial_event = {
            "status": status.value,
            "timestamp": now_iso,
            "current_location": "Mock Logistics Hub",
            "message": f"Order {order_id} manifested with Mock courier",
        }

        raw_response = {
            "courier": "mock",
            "status": "Success",
            "order_number": courier_order_id,
            "awb_number": awb_number,
            "created_at": now_iso,
        }

        # Save order in mock state
        self._orders[order_id] = {
            "order_id": order_id,
            "courier_order_id": courier_order_id,
            "awb_number": awb_number,
            "status": status,
            "customer": customer,
            "items": items,
            "history": [initial_event],
            "raw_response": raw_response,
        }
        self._awb_to_order_id[awb_number] = order_id

        return CourierOrderResult(
            courier_order_id=courier_order_id,
            awb_number=awb_number,
            status=status,
            raw_response=raw_response,
        )

    def track_order(self, tracking_id: str) -> CourierTrackingResult:
        """Query tracking status from mock store, advancing status if auto_progress is enabled."""
        # Resolve order
        order_id = self._awb_to_order_id.get(tracking_id, tracking_id)
        order_data = self._orders.get(order_id)

        # Check simulation triggers based on tracking_id or stored customer name
        customer_name = ""
        if order_data:
            cust = order_data.get("customer")
            customer_name = cust.get("name", "") if isinstance(cust, dict) else getattr(cust, "name", "")

        self._check_simulation(order_id=order_id, customer_name=customer_name, operation="track_order")

        if not order_data:
            raise OrderNotFoundError(
                message=f"Mock tracking record not found for '{tracking_id}'",
                details={"tracking_id": tracking_id},
            )

        current_status = order_data["status"]

        # If auto_progress is enabled and not already terminal, advance lifecycle
        if self._auto_progress and current_status not in (
            OrderStatus.DELIVERED,
            OrderStatus.CANCELLED,
            OrderStatus.FAILED,
        ):
            progression = {
                OrderStatus.CREATED: OrderStatus.PICKED_UP,
                OrderStatus.PICKED_UP: OrderStatus.IN_TRANSIT,
                OrderStatus.IN_TRANSIT: OrderStatus.DELIVERED,
            }
            new_status = progression.get(current_status, current_status)
            if new_status != current_status:
                order_data["status"] = new_status
                order_data["history"].append(
                    {
                        "status": new_status.value,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "current_location": "En Route Hub",
                        "message": f"Status progressed to {new_status.value}",
                    }
                )
                current_status = new_status

        raw_response = {
            "courier": "mock",
            "awb_number": order_data["awb_number"],
            "order_number": order_data["courier_order_id"],
            "status": current_status.value,
            "scans": list(order_data["history"]),
        }

        return CourierTrackingResult(
            status=current_status,
            awb_number=order_data["awb_number"],
            raw_response=raw_response,
            tracking_events=list(order_data["history"]),
        )

    def cancel_order(self, tracking_id: str) -> CourierCancelResult:
        """Cancel mock order, transition status to CANCELLED and append audit scan."""
        order_id = self._awb_to_order_id.get(tracking_id, tracking_id)
        order_data = self._orders.get(order_id)

        customer_name = ""
        if order_data:
            cust = order_data.get("customer")
            customer_name = cust.get("name", "") if isinstance(cust, dict) else getattr(cust, "name", "")

        self._check_simulation(order_id=order_id, customer_name=customer_name, operation="cancel_order")

        if not order_data:
            raise OrderNotFoundError(
                message=f"Mock order not found for cancellation with tracking ID '{tracking_id}'",
                details={"tracking_id": tracking_id},
            )

        # Transition status
        order_data["status"] = OrderStatus.CANCELLED
        cancel_event = {
            "status": OrderStatus.CANCELLED.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "current_location": "Mock Operations Center",
            "message": "Order cancelled by client",
        }
        order_data["history"].append(cancel_event)

        raw_response = {
            "courier": "mock",
            "awb_number": order_data["awb_number"],
            "status": "CANCELLED",
            "message": "Order successfully cancelled",
        }

        return CourierCancelResult(
            status=OrderStatus.CANCELLED,
            success=True,
            raw_response=raw_response,
            message="Order successfully cancelled",
        )
