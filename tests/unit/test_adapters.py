"""Unit tests for CourierAdapter ABC, CourierRegistry, and UrbaneboltAdapter mapping logic."""

import ast
import inspect
from unittest.mock import MagicMock
import pytest

from app.couriers.base import (
    CourierAdapter,
    CourierCancelResult,
    CourierOrderResult,
    CourierTrackingResult,
)
from app.couriers.client import ResilientHttpClient
from app.couriers.mock import MockCourierAdapter
from app.couriers.registry import CourierRegistry, courier_registry
from app.couriers.urbanebolt import UrbaneboltAdapter
from app.exceptions import (
    CourierAuthError,
    CourierError,
    DuplicateOrderError,
    OrderNotFoundError,
    UnsupportedCourierError,
    ValidationError,
)
from app.schemas.order import Customer, OrderCreateRequest, OrderItem
from app.schemas.tracking import OrderStatus


# ============================================================================
# 1. CourierAdapter ABC Tests
# ============================================================================


def test_courier_adapter_abc_cannot_be_instantiated():
    """Verify that CourierAdapter is an ABC and cannot be directly instantiated."""
    with pytest.raises(TypeError) as exc_info:
        CourierAdapter()  # type: ignore
    assert "Can't instantiate abstract class" in str(exc_info.value)


def test_courier_dto_awaitable():
    """Verify that all courier DTOs support both sync and async await expressions."""
    order_result = CourierOrderResult(
        courier_order_id="TEST-1",
        awb_number="AWB-1",
        status=OrderStatus.CREATED,
    )
    # Sync access
    assert order_result.courier_order_id == "TEST-1"
    assert order_result.status == OrderStatus.CREATED

    tracking_result = CourierTrackingResult(
        status=OrderStatus.DELIVERED,
        awb_number="AWB-1",
    )
    assert tracking_result.status == OrderStatus.DELIVERED

    cancel_result = CourierCancelResult(
        status=OrderStatus.CANCELLED,
        success=True,
    )
    assert cancel_result.success is True


@pytest.mark.asyncio
async def test_courier_dto_async_await():
    """Verify that courier DTOs can be awaited in coroutines."""
    order_result = CourierOrderResult(
        courier_order_id="ASYNC-1",
        awb_number="AWB-ASYNC",
        status=OrderStatus.CREATED,
    )
    res = await order_result
    assert res.courier_order_id == "ASYNC-1"


# ============================================================================
# 2. CourierRegistry Tests
# ============================================================================


def test_courier_registry_register_and_get():
    """Verify registry registers and retrieves adapters case-insensitively."""
    registry = CourierRegistry()
    mock_adapter = MockCourierAdapter()
    registry.register("TestCourier", mock_adapter)

    assert registry.get("testcourier") is mock_adapter
    assert registry.get("TESTCOURIER") is mock_adapter
    assert registry.get("  testcourier  ") is mock_adapter


def test_courier_registry_unsupported_raises_error():
    """Verify looking up an unregistered courier raises UnsupportedCourierError."""
    registry = CourierRegistry()
    with pytest.raises(UnsupportedCourierError) as exc_info:
        registry.get("non_existent_courier")

    err = exc_info.value
    assert err.code == "UNSUPPORTED_COURIER"
    assert err.status_code == 400
    assert "non_existent_courier" in err.message


def test_courier_registry_list_supported_and_unregister():
    """Verify list_supported returns sorted list and unregister removes adapter."""
    registry = CourierRegistry()
    m1 = MockCourierAdapter()
    m2 = MockCourierAdapter()
    registry.register("courier_b", m1)
    registry.register("courier_a", m2)

    assert registry.list_supported() == ["courier_a", "courier_b"]

    removed = registry.unregister("courier_a")
    assert removed is m2
    assert registry.list_supported() == ["courier_b"]


def test_courier_registry_zero_if_elif_branching():
    """Verify structural integrity: CourierRegistry.get must not contain if/elif branches on courier names."""
    import textwrap

    src = textwrap.dedent(inspect.getsource(CourierRegistry.get))
    tree = ast.parse(src)

    # Count If nodes in get method
    if_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.If)]
    # There should only be one check: checking if adapter is None in dictionary lookup
    assert len(if_nodes) <= 1

    # Verify no string literals for courier partners in the function AST
    string_constants = [
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert "mock" not in string_constants
    assert "urbanebolt" not in string_constants


def test_default_courier_registry_populated():
    """Verify that the singleton courier_registry has mock and urbanebolt registered."""
    supported = courier_registry.list_supported()
    assert "mock" in supported
    assert "urbanebolt" in supported
    assert isinstance(courier_registry.get("mock"), MockCourierAdapter)
    assert isinstance(courier_registry.get("urbanebolt"), UrbaneboltAdapter)


# ============================================================================
# 3. UrbaneboltAdapter Mapping Tests
# ============================================================================


@pytest.fixture
def mock_http_client():
    """Create a mock ResilientHttpClient."""
    return MagicMock(spec=ResilientHttpClient)


@pytest.fixture
def sample_order():
    """Create a standard normalized OrderCreateRequest."""
    return OrderCreateRequest(
        order_id="ORD-UB-001",
        courier_partner="urbanebolt",
        customer=Customer(
            name="Alice Wonder",
            phone="9876543210",
            address="Plot 42, Sector 14, Commercial District",
            city="Surat",
            state="GUJARAT",
            pincode="395007",
            email="alice@example.com",
        ),
        items=[
            OrderItem(name="Mechanical Watch", quantity=1, price=1500.0),
            OrderItem(name="Leather Strap", quantity=2, price=250.0),
        ],
    )


def test_urbanebolt_authenticate_success(mock_http_client):
    """Verify authenticate calls auth endpoint and caches token with expiry."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "access_token": "TEST_JWT_TOKEN_12345",
        "expires_in": 86400,
        "token_type": "Bearer",
    }
    mock_http_client.post.return_value = mock_resp

    adapter = UrbaneboltAdapter(
        base_url="https://uat.urbanebolt.in",
        username="testuser",
        password="testpassword",
        http_client=mock_http_client,
    )

    adapter.authenticate()
    assert adapter._token == "TEST_JWT_TOKEN_12345"
    assert adapter._token_expiry is not None

    mock_http_client.post.assert_called_once_with(
        "https://uat.urbanebolt.in/api/v1/auth/getToken/",
        json={"username": "testuser", "password": "testpassword"},
        headers={"Content-Type": "application/json"},
    )


def test_urbanebolt_authenticate_failure_raises_auth_error(mock_http_client):
    """Verify authenticate raises CourierAuthError when courier returns Failed status."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Failed",
        "message": "Incorrect username/password!",
    }
    mock_http_client.post.return_value = mock_resp

    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    with pytest.raises(CourierAuthError) as exc_info:
        adapter.authenticate()

    assert "Incorrect username/password!" in exc_info.value.message


def test_urbanebolt_create_order_manifest_mapping(mock_http_client, sample_order):
    """Verify internal order payload correctly transforms into UrbaneBolt manifest schema."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_manifest_resp = MagicMock()
    mock_manifest_resp.status_code = 200
    mock_manifest_resp.json.return_value = {
        "status": "Success",
        "successResponse": [
            {
                "status": "Success",
                "orderNumber": "ORD-UB-001",
                "awbNumber": 200000008888,
                "routeCode": "SUR/GUJ",
                "customerCode": "UEBCUS0008",
            }
        ],
        "errorResponse": [],
    }
    mock_http_client.post.return_value = mock_manifest_resp

    result = adapter.create_order(sample_order)

    assert result.courier_order_id == "ORD-UB-001"
    assert result.awb_number == "200000008888"
    assert result.status == OrderStatus.CREATED

    # Verify manifest JSON sent to UrbaneBolt
    call_args = mock_http_client.post.call_args
    assert call_args[0][0] == "https://uat.urbanebolt.in/api/v1/services/manifest/"
    json_body = call_args[1]["json"]
    assert isinstance(json_body, list)
    assert len(json_body) == 1
    manifest = json_body[0]

    assert manifest["orderNumber"] == "ORD-UB-001"
    assert manifest["consName"] == "Alice Wonder"
    assert manifest["consMobile"] == "9876543210"
    assert manifest["consPincode"] == 395007
    assert manifest["itemQuantity"] == 3
    assert manifest["declaredValue"] == 2000.0  # 1500 + 2*250
    assert manifest["payMode"] == "PPD"
    assert manifest["serviceType"] == "SDD"
    assert manifest["pieces"] == 1


def test_urbanebolt_create_order_duplicate_raises_duplicate_error(mock_http_client, sample_order):
    """Verify duplicate orderNumber in errorResponse translates to DuplicateOrderError."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "successResponse": [],
        "errorResponse": [
            {
                "orderNumber": "ORD-UB-001",
                "customerCode": "UEBCUS0008",
                "status": "Failed",
                "message": "orderNumber already shipped!",
            }
        ],
    }
    mock_http_client.post.return_value = mock_resp

    with pytest.raises(DuplicateOrderError) as exc_info:
        adapter.create_order(sample_order)

    assert exc_info.value.code == "DUPLICATE_ORDER"
    assert "already exists" in exc_info.value.message


def test_urbanebolt_create_order_validation_failure(mock_http_client, sample_order):
    """Verify courier validation rejection in errorResponse translates to ValidationError."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "successResponse": [],
        "errorResponse": [
            {
                "orderNumber": "ORD-UB-001",
                "message": "Pickup Pincode (999999) is not serviceable",
            }
        ],
    }
    mock_http_client.post.return_value = mock_resp

    with pytest.raises(ValidationError) as exc_info:
        adapter.create_order(sample_order)

    assert exc_info.value.code == "VALIDATION_ERROR"
    assert "not serviceable" in exc_info.value.message


@pytest.mark.parametrize(
    "raw_status, expected_status",
    [
        ("MAN", OrderStatus.CREATED),
        ("PKD", OrderStatus.PICKED_UP),
        ("RDC", OrderStatus.IN_TRANSIT),
        ("DDS", OrderStatus.IN_TRANSIT),
        ("OFD", OrderStatus.IN_TRANSIT),
        ("DDL", OrderStatus.DELIVERED),
        ("CAN", OrderStatus.CANCELLED),
        ("RTL", OrderStatus.FAILED),
        ("UDD", OrderStatus.FAILED),
        ("UNKNOWN_STATUS", OrderStatus.FAILED),
    ],
)
def test_urbanebolt_tracking_status_normalization(mock_http_client, raw_status, expected_status):
    """Verify all UrbaneBolt status codes map to canonical OrderStatus."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "message": "Tracking",
        "data": {
            "awbNumber": 200000008888,
            "orderNumber": "ORD-UB-001",
            "currentStatusCode": raw_status,
            "currentStatusCodeDescription": f"Description for {raw_status}",
            "scans": [{"statusCode": raw_status, "statusDateTime": "2026-09-28 10:00"}],
        },
    }
    mock_http_client.get.return_value = mock_resp

    res = adapter.track_order("200000008888")
    assert res.status == expected_status
    assert res.awb_number == "200000008888"
    assert len(res.tracking_events) == 1


def test_urbanebolt_tracking_not_found(mock_http_client):
    """Verify non-existent AWB tracking returns OrderNotFoundError."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Failed",
        "message": "Data Not Found",
        "data": [],
    }
    mock_http_client.get.return_value = mock_resp

    with pytest.raises(OrderNotFoundError):
        adapter.track_order("999999999999")


def test_urbanebolt_cancel_order_success(mock_http_client):
    """Verify order cancellation parses successResponse correctly."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "message": "Cancellation Proccess",
        "successResponse": [{"orderNumber": "ORD-UB-001", "awb": "200000008888", "message": "Cancelled"}],
        "failureResponse": [],
    }
    mock_http_client.post.return_value = mock_resp

    res = adapter.cancel_order("200000008888")
    assert res.status == OrderStatus.CANCELLED
    assert res.success is True


def test_urbanebolt_cancel_order_already_cancelled_idempotent(mock_http_client):
    """Verify already cancelled shipment in failureResponse is treated idempotently as success."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "message": "Cancellation Proccess",
        "successResponse": [],
        "failureResponse": [{"orderNumber": "ORD-UB-001", "awb": "200000008888", "message": "Shipment already cancelled!"}],
    }
    mock_http_client.post.return_value = mock_resp

    res = adapter.cancel_order("200000008888")
    assert res.status == OrderStatus.CANCELLED
    assert res.success is True


def test_urbanebolt_cancel_order_not_found(mock_http_client):
    """Verify non-existent AWB in cancellation raises OrderNotFoundError."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "message": "Cancellation Proccess",
        "successResponse": [],
        "failureResponse": [{"orderNumber": "", "awb": "999999999999", "message": "Requested AWB not found"}],
    }
    mock_http_client.post.return_value = mock_resp

    with pytest.raises(OrderNotFoundError):
        adapter.cancel_order("999999999999")


def test_urbanebolt_create_order_generic_courier_error(mock_http_client, sample_order):
    """Verify generic error response in manifest raises CourierError."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Failed",
        "message": "Gateway manifest pipeline failure",
        "errorResponse": [{"orderNumber": "ORD-UB-001", "message": "Downstream timeout"}],
    }
    mock_http_client.post.return_value = mock_resp

    with pytest.raises(CourierError) as exc_info:
        adapter.create_order(sample_order)

    assert exc_info.value.code == "COURIER_ERROR"


def test_urbanebolt_create_order_dict_payload(mock_http_client):
    """Verify create_order supports dict payload as alternative to OrderCreateRequest."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "successResponse": [{"orderNumber": "ORD-DICT-1", "awbNumber": 200000009999}],
        "errorResponse": [],
    }
    mock_http_client.post.return_value = mock_resp

    dict_order = {
        "order_id": "ORD-DICT-1",
        "courier_partner": "urbanebolt",
        "customer": {
            "name": "Dict Customer",
            "phone": "9811223344",
            "address": "Short St",  # Short address to verify padding
            "city": "Gurgaon",
            "pincode": "122001",
        },
        "items": [{"name": "Item 1", "quantity": 2, "price": 100.0}],
    }

    result = adapter.create_order(dict_order)
    assert result.courier_order_id == "ORD-DICT-1"
    assert result.awb_number == "200000009999"

    # Verify address was padded to >= 10 chars
    sent_manifest = mock_http_client.post.call_args[1]["json"][0]
    assert len(sent_manifest["consAddress"]) >= 10


def test_urbanebolt_authenticate_unparseable_json(mock_http_client):
    """Verify authenticate handles JSON decode errors by raising CourierAuthError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_resp.text = "Bad Gateway"
    mock_resp.json.side_effect = ValueError("Invalid JSON")
    mock_http_client.post.return_value = mock_resp

    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    with pytest.raises(CourierAuthError):
        adapter.authenticate()


def test_urbanebolt_authenticate_missing_token_field(mock_http_client):
    """Verify authenticate raises CourierAuthError when access_token field is missing."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "Success"}  # No access_token
    mock_http_client.post.return_value = mock_resp

    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    with pytest.raises(CourierAuthError) as exc_info:
        adapter.authenticate()
    assert "missing access_token" in exc_info.value.message


def test_urbanebolt_track_order_unparseable_json(mock_http_client):
    """Verify track_order raises CourierError when response is unparseable."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_resp.json.side_effect = ValueError("Invalid JSON")
    mock_http_client.get.return_value = mock_resp

    with pytest.raises(CourierError):
        adapter.track_order("AWB-TEST")


def test_urbanebolt_cancel_order_unparseable_json(mock_http_client):
    """Verify cancel_order raises CourierError when response is unparseable."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Server Error"
    mock_resp.json.side_effect = ValueError("Invalid JSON")
    mock_http_client.post.return_value = mock_resp

    with pytest.raises(CourierError):
        adapter.cancel_order("AWB-TEST")


def test_urbanebolt_cancel_order_generic_failure(mock_http_client):
    """Verify cancel_order raises CourierError on non-cancellable rejection."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "message": "Cancellation Proccess",
        "successResponse": [],
        "failureResponse": [{"orderNumber": "ORD-1", "awb": "AWB-1", "message": "Cannot cancel shipment after dispatch"}],
    }
    mock_http_client.post.return_value = mock_resp

    with pytest.raises(CourierError) as exc_info:
        adapter.cancel_order("AWB-1")
    assert "Cannot cancel shipment after dispatch" in exc_info.value.message


def test_courier_registry_clear():
    """Verify registry clear empties all registered adapters."""
    registry = CourierRegistry()
    registry.register("mock", MockCourierAdapter())
    assert len(registry.list_supported()) == 1
    registry.clear()
    assert len(registry.list_supported()) == 0


def test_urbanebolt_token_auto_refresh_when_expired(mock_http_client):
    """Verify _ensure_authenticated calls authenticate if token is expired."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "EXPIRED_TOKEN"
    adapter._token_expiry = 100.0  # Far in past

    auth_resp = MagicMock()
    auth_resp.status_code = 200
    auth_resp.json.return_value = {
        "status": "Success",
        "access_token": "FRESH_TOKEN",
        "expires_in": 86400,
    }
    mock_http_client.post.return_value = auth_resp

    token = adapter._ensure_authenticated()
    assert token == "FRESH_TOKEN"
    assert adapter._token == "FRESH_TOKEN"


def test_urbanebolt_manifest_missing_success_response(mock_http_client, sample_order):
    """Verify manifest raises CourierError when successResponse key is missing or empty."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Success",
        "successResponse": [],  # empty
        "errorResponse": [],
    }
    mock_http_client.post.return_value = mock_resp

    with pytest.raises(CourierError) as exc_info:
        adapter.create_order(sample_order)
    assert "missing successResponse" in exc_info.value.message


def test_urbanebolt_cancel_failed_status(mock_http_client):
    """Verify cancel_order raises CourierError when status is Failed."""
    adapter = UrbaneboltAdapter(http_client=mock_http_client)
    adapter._token = "VALID_TOKEN"
    adapter._token_expiry = 9999999999.0

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "Failed",
        "message": "Gateway error during cancellation",
    }
    mock_http_client.post.return_value = mock_resp

    with pytest.raises(CourierError) as exc_info:
        adapter.cancel_order("AWB-FAIL")
    assert "cancel failed" in exc_info.value.message


