"""Unit tests for Pydantic schemas, validation, and error envelopes."""

from datetime import datetime
import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.bulk import (
    BatchItemResult,
    BulkOrderRequest,
    BulkStatus,
    BulkStatusResponse,
    BulkSubmitResponse,
)
from app.schemas.common import ErrorDetail, ErrorResponse
from app.schemas.order import (
    Customer,
    OrderCancelResponse,
    OrderCreateRequest,
    OrderItem,
    OrderResponse,
)
from app.schemas.tracking import (
    OrderStatus,
    OrderTrackingResponse,
    TrackingEvent,
)


def test_customer_validation():
    """Verify Customer schema validation rules."""
    valid_customer = Customer(
        name="John Doe",
        phone="9876543210",
        address="123 Street, City",
    )
    assert valid_customer.name == "John Doe"
    assert valid_customer.phone == "9876543210"
    assert valid_customer.address == "123 Street, City"

    # Missing required field
    with pytest.raises(PydanticValidationError):
        Customer(name="John Doe", phone="9876543210")  # address missing

    # Empty string on min_length=1
    with pytest.raises(PydanticValidationError):
        Customer(name="", phone="9876543210", address="123 Street")


def test_order_item_validation():
    """Verify OrderItem schema validation rules."""
    item = OrderItem(name="Keyboard", quantity=2, price=49.99)
    assert item.name == "Keyboard"
    assert item.quantity == 2
    assert item.price == 49.99

    # Quantity < 1
    with pytest.raises(PydanticValidationError):
        OrderItem(name="Keyboard", quantity=0, price=49.99)

    # Price < 0
    with pytest.raises(PydanticValidationError):
        OrderItem(name="Keyboard", quantity=1, price=-5.0)


def test_order_create_request_validation():
    """Verify OrderCreateRequest schema validation rules."""
    valid_req = OrderCreateRequest(
        order_id="ORD-001",
        courier_partner="mock",
        customer=Customer(name="Jane", phone="9999999999", address="456 Avenue"),
        items=[OrderItem(name="Mouse", quantity=1, price=25.0)],
    )
    assert valid_req.order_id == "ORD-001"
    assert len(valid_req.items) == 1

    # Empty items list
    with pytest.raises(PydanticValidationError):
        OrderCreateRequest(
            order_id="ORD-001",
            courier_partner="mock",
            customer=Customer(name="Jane", phone="9999999999", address="456 Avenue"),
            items=[],
        )

    # Missing order_id
    with pytest.raises(PydanticValidationError):
        OrderCreateRequest(
            order_id="",
            courier_partner="mock",
            customer=Customer(name="Jane", phone="9999999999", address="456 Avenue"),
            items=[OrderItem(name="Mouse", quantity=1, price=25.0)],
        )


def test_order_response_serialization():
    """Verify OrderResponse serialization."""
    now = datetime.now()
    resp = OrderResponse(
        order_id="ORD-001",
        courier_partner="mock",
        courier_order_id="MOCK-123",
        awb_number="AWB-123",
        status="CREATED",
        created_at=now,
    )
    data = resp.model_dump()
    assert data["order_id"] == "ORD-001"
    assert data["courier_partner"] == "mock"
    assert data["courier_order_id"] == "MOCK-123"
    assert data["awb_number"] == "AWB-123"
    assert data["status"] == "CREATED"

    cancel_resp = OrderCancelResponse(order_id="ORD-001", status="CANCELLED")
    assert cancel_resp.order_id == "ORD-001"
    assert cancel_resp.status == "CANCELLED"


def test_order_status_enum():
    """Verify OrderStatus enum values."""
    assert OrderStatus.CREATED == "CREATED"
    assert OrderStatus.PICKED_UP == "PICKED_UP"
    assert OrderStatus.IN_TRANSIT == "IN_TRANSIT"
    assert OrderStatus.DELIVERED == "DELIVERED"
    assert OrderStatus.CANCELLED == "CANCELLED"
    assert OrderStatus.FAILED == "FAILED"


def test_order_tracking_response():
    """Verify OrderTrackingResponse and TrackingEvent serialization."""
    now = datetime.now()
    evt = TrackingEvent(status="CREATED", created_at=now, raw_payload={"info": "ok"})
    tracking_resp = OrderTrackingResponse(
        order_id="ORD-001",
        courier_partner="mock",
        awb_number="AWB-123",
        status="CREATED",
        history=[evt],
    )
    assert tracking_resp.order_id == "ORD-001"
    assert len(tracking_resp.history) == 1
    assert tracking_resp.history[0].status == "CREATED"


def test_bulk_order_request_boundary():
    """Verify BulkOrderRequest constraints (1 to 100 items)."""
    item = OrderItem(name="Book", quantity=1, price=10.0)
    cust = Customer(name="A", phone="1234567890", address="X")

    def make_order(idx: int):
        return OrderCreateRequest(
            order_id=f"ORD-{idx}",
            courier_partner="mock",
            customer=cust,
            items=[item],
        )

    # Empty list (0 items) fails
    with pytest.raises(PydanticValidationError):
        BulkOrderRequest(orders=[])

    # Exactly 1 item succeeds
    valid_one = BulkOrderRequest(orders=[make_order(1)])
    assert len(valid_one.orders) == 1

    # Exactly 100 items succeeds
    valid_hundred = BulkOrderRequest(orders=[make_order(i) for i in range(100)])
    assert len(valid_hundred.orders) == 100

    # 101 items fails validation
    with pytest.raises(PydanticValidationError):
        BulkOrderRequest(orders=[make_order(i) for i in range(101)])


def test_bulk_status_response():
    """Verify BulkStatusResponse and BatchItemResult serialization."""
    item_res = BatchItemResult(
        order_id="ORD-1",
        success=True,
    )
    status_resp = BulkStatusResponse(
        batch_id="BATCH-001",
        status=BulkStatus.COMPLETED,
        total=1,
        successful=1,
        failed=0,
        results=[item_res],
    )
    assert status_resp.batch_id == "BATCH-001"
    assert status_resp.status == "COMPLETED"
    assert status_resp.total == 1
    assert status_resp.results[0].success is True

    submit_resp = BulkSubmitResponse(batch_id="BATCH-001", status="PROCESSING")
    assert submit_resp.batch_id == "BATCH-001"
    assert submit_resp.status == "PROCESSING"


def test_error_envelope_schema():
    """Verify ErrorResponse and ErrorDetail schema structure."""
    detail = ErrorDetail(
        code="VALIDATION_ERROR",
        message="Field missing",
        request_id="req-test-123",
        details={"fields": [{"field": "order_id", "message": "Field required"}]},
    )
    envelope = ErrorResponse(error=detail)
    data = envelope.model_dump()

    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["message"] == "Field missing"
    assert data["error"]["request_id"] == "req-test-123"
    assert data["error"]["details"]["fields"][0]["field"] == "order_id"
