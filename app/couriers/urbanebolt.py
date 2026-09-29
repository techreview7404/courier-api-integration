"""UrbaneBolt logistics courier adapter for live UAT and production integration."""

from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, Optional

from app.config import settings
from app.couriers.base import (
    CourierAdapter,
    CourierCancelResult,
    CourierOrderResult,
    CourierTrackingResult,
)
from app.couriers.client import ResilientHttpClient
from app.exceptions import (
    CourierAuthError,
    CourierError,
    DuplicateOrderError,
    OrderNotFoundError,
    ValidationError,
)
from app.schemas.order import OrderCreateRequest
from app.schemas.tracking import OrderStatus

logger = logging.getLogger("courier_platform.couriers.urbanebolt")


class UrbaneboltAdapter(CourierAdapter):
    """Adapter integrating with UrbaneBolt UAT and production logistics APIs."""

    # Canonical status mapping from UrbaneBolt status codes to internal OrderStatus
    STATUS_MAP: dict[str, OrderStatus] = {
        "MAN": OrderStatus.CREATED,
        "PKD": OrderStatus.PICKED_UP,
        "RDC": OrderStatus.IN_TRANSIT,
        "DDS": OrderStatus.IN_TRANSIT,
        "OFD": OrderStatus.IN_TRANSIT,
        "DDL": OrderStatus.DELIVERED,
        "CAN": OrderStatus.CANCELLED,
        "RTL": OrderStatus.FAILED,
        "UDD": OrderStatus.FAILED,
    }

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        customer_code: Optional[str] = None,
        http_client: Optional[ResilientHttpClient] = None,
    ):
        self.base_url = (base_url or settings.URBANEBOLT_BASE_URL).rstrip("/")
        self.username = username or settings.URBANEBOLT_USERNAME
        self.password = password or settings.URBANEBOLT_PASSWORD
        self.customer_code = customer_code or settings.URBANEBOLT_CUSTOMER_CODE

        # In-memory cached token and expiration
        self._token: Optional[str] = None
        self._token_expiry: Optional[float] = None

        # Resilient client configured with auth refresh callback and UAT SSL compatibility
        self.http_client = http_client or ResilientHttpClient(
            verify_ssl=False,
            auth_refresh_callback=self._refresh_token,
        )

    @property
    def partner_name(self) -> str:
        return "urbanebolt"

    def _refresh_token(self) -> Optional[str]:
        """Force re-authentication callback invoked on 401 Unauthorized."""
        logger.info("UrbaneBolt cached token invalidated or expired. Re-authenticating...")
        self._token = None
        self._token_expiry = None
        self.authenticate()
        return self._token

    def _ensure_authenticated(self) -> str:
        """Return valid Bearer token, refreshing if not present or nearing expiry."""
        now = time.time()
        if not self._token or (self._token_expiry and now >= self._token_expiry):
            self.authenticate()
        if not self._token:
            raise CourierAuthError("Failed to obtain UrbaneBolt access token")
        return self._token

    def authenticate(self) -> None:
        """Authenticate with UrbaneBolt /api/v1/auth/getToken/ and cache bearer token."""
        url = f"{self.base_url}/api/v1/auth/getToken/"
        payload = {
            "username": self.username,
            "password": self.password,
        }
        headers = {"Content-Type": "application/json"}

        # Direct HTTP POST without recursion to prevent auth loops
        response = self.http_client.post(url, json=payload, headers=headers)

        try:
            data = response.json()
        except Exception as exc:
            raise CourierAuthError(
                f"UrbaneBolt auth response parse error: {exc}",
                details={"status_code": response.status_code, "body": response.text},
            )

        if data.get("status") == "Failed":
            msg = data.get("message", "Incorrect username/password!")
            logger.error("UrbaneBolt authentication failed: %s", msg)
            raise CourierAuthError(
                f"UrbaneBolt authentication failed: {msg}",
                details=data,
            )

        token = data.get("access_token")
        if not token:
            raise CourierAuthError(
                "UrbaneBolt authentication response missing access_token",
                details=data,
            )

        self._token = token
        expires_in = float(data.get("expires_in", 86400))
        # 300 second safety buffer before expiry
        self._token_expiry = time.time() + max(expires_in - 300, 60)
        logger.info("UrbaneBolt token acquired successfully, expires in %ds", expires_in)

    def create_order(self, order: OrderCreateRequest | dict[str, Any]) -> CourierOrderResult:
        """Transform normalized order to UrbaneBolt manifest payload and execute manifest API."""
        token = self._ensure_authenticated()

        # Extract fields from order object or dict
        if isinstance(order, dict):
            order_id = str(order["order_id"])
            customer = order.get("customer", {})
            customer_name = customer.get("name", "")
            customer_phone = str(customer.get("phone", ""))
            customer_address = customer.get("address", "")
            customer_city = customer.get("city")
            customer_state = customer.get("state")
            customer_pincode = customer.get("pincode")
            customer_email = customer.get("email")
            items = order.get("items", [])
        else:
            order_id = order.order_id
            customer_name = order.customer.name
            customer_phone = order.customer.phone
            customer_address = order.customer.address
            customer_city = order.customer.city
            customer_state = order.customer.state
            customer_pincode = order.customer.pincode
            customer_email = order.customer.email
            items = order.items

        # Sanitize phone to digits
        phone_digits = re.sub(r"\D", "", customer_phone) or "9999999999"

        # UrbaneBolt constraint: consignee and shipper address >= 10 chars
        clean_cons_address = customer_address.strip()
        if len(clean_cons_address) < 10:
            clean_cons_address = f"{clean_cons_address} (Delivery Location)"

        # Parse pincode safely
        cons_pincode = 122001
        if customer_pincode:
            pin_digits = re.sub(r"\D", "", str(customer_pincode))
            if len(pin_digits) == 6:
                cons_pincode = int(pin_digits)

        # Calculate items aggregations
        item_names = []
        total_quantity = 0
        total_value = 0.0
        for item in items:
            if isinstance(item, dict):
                name = item.get("name", "Item")
                qty = int(item.get("quantity", 1))
                price = float(item.get("price", 0.0))
            else:
                name = item.name
                qty = item.quantity
                price = item.price
            item_names.append(name)
            total_quantity += qty
            total_value += qty * price

        item_desc = ", ".join(item_names) or "General Merchandise"
        total_quantity = max(total_quantity, 1)
        total_value = max(total_value, 100.0)

        # Build UrbaneBolt single manifest shipment object
        manifest_item = {
            "customerCode": self.customer_code,
            "orderNumber": order_id,
            # Consignee
            "consName": customer_name,
            "consMobile": phone_digits,
            "consAddress": clean_cons_address,
            "consAddressType": "Home",
            "consCity": customer_city or "Gurgaon",
            "consState": customer_state or "HARYANA",
            "consPincode": cons_pincode,
            "consCountry": "INDIA",
            "consEmail": customer_email or "customer@example.com",
            # Shipper
            "shprName": settings.SHIPPER_NAME,
            "shprAddress": settings.SHIPPER_ADDRESS,
            "shprAddressType": "Seller",
            "shprCity": settings.SHIPPER_CITY,
            "shprState": settings.SHIPPER_STATE,
            "shprPincode": int(settings.SHIPPER_PINCODE),
            "shprMobile": int(settings.SHIPPER_MOBILE),
            "shprCountry": "INDIA",
            "shprEmail": settings.SHIPPER_EMAIL,
            # Return details (mirror shipper)
            "rtnName": settings.SHIPPER_NAME,
            "rtnAddress": settings.SHIPPER_ADDRESS,
            "rtnAddressType": "Seller",
            "rtnCity": settings.SHIPPER_CITY,
            "rtnState": settings.SHIPPER_STATE,
            "rtnPincode": int(settings.SHIPPER_PINCODE),
            "rtnMobile": int(settings.SHIPPER_MOBILE),
            "rtnCountry": "INDIA",
            "rtnEmail": settings.SHIPPER_EMAIL,
            # Parcel details
            "itemDescription": item_desc,
            "itemQuantity": total_quantity,
            "declaredValue": total_value,
            "invoiceValue": total_value,
            "invoiceNumber": f"INV-{order_id}",
            "invoiceDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "payMode": "PPD",
            "collectableValue": 0,
            "serviceType": "SDD",
            "pieces": 1,
            "weight": 0.5,
            "length": 10,
            "breadth": 10,
            "height": 10,
        }

        url = f"{self.base_url}/api/v1/services/manifest/"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # Send manifest array: [manifest_item]
        response = self.http_client.post(url, json=[manifest_item], headers=headers)

        try:
            res_json = response.json()
        except Exception as exc:
            raise CourierError(
                f"UrbaneBolt manifest returned unparseable JSON: {exc}",
                details={"status_code": response.status_code, "body": response.text},
            )

        # Inspect errorResponse
        error_response = res_json.get("errorResponse") or []
        if error_response:
            err = error_response[0] if isinstance(error_response, list) else error_response
            msg = err.get("message", "UrbaneBolt manifest rejected") if isinstance(err, dict) else str(err)

            if "already shipped" in msg.lower() or "already exist" in msg.lower():
                raise DuplicateOrderError(
                    order_id=order_id,
                    message=f"UrbaneBolt order {order_id} already exists: {msg}",
                    details=res_json,
                )
            if any(
                keyword in msg.lower()
                for keyword in ("not serviceable", "should not be less than", "servicetype", "invalid", "not provided")
            ):
                raise ValidationError(
                    message=f"UrbaneBolt manifest validation error: {msg}",
                    details=res_json,
                )
            raise CourierError(
                message=f"UrbaneBolt manifest error: {msg}",
                details=res_json,
            )

        if res_json.get("status") == "Failed":
            msg = res_json.get("message", "Manifest failed")
            raise CourierError(
                message=f"UrbaneBolt manifest failed: {msg}",
                details=res_json,
            )

        success_response = res_json.get("successResponse") or []
        if not success_response:
            raise CourierError(
                message="UrbaneBolt manifest response missing successResponse",
                details=res_json,
            )

        success_entry = success_response[0]
        awb_number = str(success_entry.get("awbNumber", ""))
        courier_order_id = str(success_entry.get("orderNumber", order_id))

        return CourierOrderResult(
            courier_order_id=courier_order_id,
            awb_number=awb_number,
            status=OrderStatus.CREATED,
            raw_response=res_json,
        )

    def track_order(self, tracking_id: str) -> CourierTrackingResult:
        """Query UrbaneBolt /api/v1/services/tracking-pub/ and normalize tracking status."""
        token = self._ensure_authenticated()

        url = f"{self.base_url}/api/v1/services/tracking-pub/?awb={tracking_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        response = self.http_client.get(url, headers=headers)

        try:
            res_json = response.json()
        except Exception as exc:
            raise CourierError(
                f"UrbaneBolt tracking returned unparseable JSON: {exc}",
                details={"status_code": response.status_code, "body": response.text},
            )

        msg = str(res_json.get("message", "")).lower()
        if res_json.get("status") == "Failed" or "data not found" in msg or "invalid tracking" in msg:
            raise OrderNotFoundError(
                message=f"UrbaneBolt shipment '{tracking_id}' not found",
                details=res_json,
            )

        data = res_json.get("data")
        if not data or not isinstance(data, dict):
            raise OrderNotFoundError(
                message=f"UrbaneBolt tracking data empty for '{tracking_id}'",
                details=res_json,
            )

        # Normalize status code
        raw_code = str(data.get("currentStatusCode", "")).upper()
        normalized_status = self.STATUS_MAP.get(raw_code, OrderStatus.FAILED)

        awb_number = str(data.get("awbNumber", tracking_id))
        scans = data.get("scans") or []

        return CourierTrackingResult(
            status=normalized_status,
            awb_number=awb_number,
            raw_response=res_json,
            tracking_events=scans,
        )

    def cancel_order(self, tracking_id: str) -> CourierCancelResult:
        """Invoke UrbaneBolt /api/v1/services/cancel/ and normalize cancellation response."""
        token = self._ensure_authenticated()

        url = f"{self.base_url}/api/v1/services/cancel/"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {"awbs": str(tracking_id)}

        response = self.http_client.post(url, json=payload, headers=headers)

        try:
            res_json = response.json()
        except Exception as exc:
            raise CourierError(
                f"UrbaneBolt cancel returned unparseable JSON: {exc}",
                details={"status_code": response.status_code, "body": response.text},
            )

        # Check failureResponse
        failure_response = res_json.get("failureResponse") or []
        if failure_response:
            fail_entry = failure_response[0] if isinstance(failure_response, list) else failure_response
            msg = fail_entry.get("message", "") if isinstance(fail_entry, dict) else str(fail_entry)

            # Idempotent: already cancelled is considered successful cancellation
            if "already cancelled" in msg.lower():
                return CourierCancelResult(
                    status=OrderStatus.CANCELLED,
                    success=True,
                    raw_response=res_json,
                    message="Shipment already cancelled",
                )

            if "not found" in msg.lower() or "not belong" in msg.lower():
                raise OrderNotFoundError(
                    message=f"UrbaneBolt shipment '{tracking_id}' not found for cancellation",
                    details=res_json,
                )

            raise CourierError(
                message=f"UrbaneBolt cancellation rejected: {msg}",
                details=res_json,
            )

        # Check successResponse
        success_response = res_json.get("successResponse") or []
        if success_response:
            return CourierCancelResult(
                status=OrderStatus.CANCELLED,
                success=True,
                raw_response=res_json,
                message="Shipment successfully cancelled",
            )

        if res_json.get("status") == "Failed":
            msg = res_json.get("message", "Cancellation failed")
            raise CourierError(
                message=f"UrbaneBolt cancel failed: {msg}",
                details=res_json,
            )

        return CourierCancelResult(
            status=OrderStatus.CANCELLED,
            success=True,
            raw_response=res_json,
            message="Shipment cancelled",
        )
