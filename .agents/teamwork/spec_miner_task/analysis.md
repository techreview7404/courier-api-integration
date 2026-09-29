# Comprehensive Task Requirements Specification

## 1. Executive Summary & Specification Sources

This document establishes the exhaustive specification mined from authoritative sources for the **Courier Integration Platform** backend service.

### Authoritative Specification Sources
1. **`task.md`**: Master task specification covering architecture, tech stack, endpoints, domain models, idempotency, retry mechanisms, bulk processing, and project guidelines.
2. **`ORIGINAL_REQUEST.md`**: Core system prompt, architectural guardrails, acceptance criteria, and operational boundaries.
3. **`urbanebolt_doc.json`**: Official Postman collection for the UrbaneBolt UAT Logistics API, defining endpoint URLs, headers, payloads, and response structures.

---

## 2. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | API / Order | Create Order (`POST /api/v1/orders`) | Normalized order creation across any registered courier partner. Validates, checks idempotency, delegates to courier adapter, stores order & initial tracking record. | JSON body with `order_id`, `courier_partner`, `customer` (name, phone, address), and `items` (name, quantity, price) | HTTP 201/200: JSON with `order_id`, `courier_partner`, `courier_order_id`, `awb_number`, `status` (`CREATED`) | Returns `VALIDATION_ERROR` (422/400), `UNSUPPORTED_COURIER` (400), `DUPLICATE_ORDER` (409), `COURIER_ERROR` (502), `COURIER_TIMEOUT` (504), `COURIER_AUTH_ERROR` (502) | `task.md` §5, §6; `ORIGINAL_REQUEST.md` R2 |
| 2 | API / Order | Track Order (`GET /api/v1/orders/{order_id}/track`) | Retrieves live tracking status from courier adapter, updates current order status, appends new event to immutable tracking history. | Path param: `order_id` (string) | HTTP 200: JSON with `order_id`, `status`, `courier_partner`, `awb_number`, latest updates, tracking records | Returns `ORDER_NOT_FOUND` (404), `COURIER_ERROR` (502), `COURIER_TIMEOUT` (504), `COURIER_AUTH_ERROR` (502) | `task.md` §7, §8; `ORIGINAL_REQUEST.md` R2 |
| 3 | API / Order | Cancel Order (`POST /api/v1/orders/{order_id}/cancel`) | Cancels order with underlying courier adapter, updates order status to `CANCELLED`, appends cancellation to tracking history. | Path param: `order_id` (string) | HTTP 200: JSON with `order_id`, `status` (`CANCELLED`) | Returns `ORDER_NOT_FOUND` (404), `COURIER_ERROR` (502), `COURIER_TIMEOUT` (504), `COURIER_AUTH_ERROR` (502) | `task.md` §9; `ORIGINAL_REQUEST.md` R2 |
| 4 | API / Bulk | Submit Bulk Orders (`POST /api/v1/orders/bulk`) | Accepts up to 100 orders (heterogeneous couriers permitted), persists batch record, dispatches in-process concurrent background task, returns batch ID immediately. | JSON body with `orders` list (1 to 100 order objects) | HTTP 202/200: JSON with `batch_id`, `status` (`PROCESSING`) | Returns `VALIDATION_ERROR` (422/400) if orders list is empty or > 100 orders | `task.md` §10; `ORIGINAL_REQUEST.md` R4 |
| 5 | API / Bulk | Poll Bulk Batch Status (`GET /api/v1/orders/bulk/{batch_id}`) | Retrieves current processing status of bulk batch, including summary counts (total, successful, failed) and individual item results. | Path param: `batch_id` (string) | HTTP 200: JSON with `batch_id`, `status` (`PROCESSING`/`COMPLETED`/`FAILED`), `total`, `successful`, `failed`, `results` array | Returns `ORDER_NOT_FOUND` / batch not found (404) | `task.md` §10; `ORIGINAL_REQUEST.md` R4 |
| 6 | Database / Core | Order Storage & Idempotency | Persists order entity with unique constraint on `order_id`. Detects duplicate submissions, preventing duplicate shipment creation and downstream courier calls. | Order entity fields: `order_id`, `courier_partner`, payloads, status, AWB, timestamps | Persisted row in `orders` table | Re-submission returns existing order or `DUPLICATE_ORDER` conflict (409) | `task.md` §11, §17; `ORIGINAL_REQUEST.md` R3 |
| 7 | Database / Core | Immutable Tracking History | Audit log table `tracking_history` recording chronological status transitions and raw courier payloads without overwriting previous events. | `order_id`, `status`, `raw_payload`, `created_at` | Persisted append-only rows in `tracking_history` table | Append failure triggers database exception mapped to `INTERNAL_ERROR` | `task.md` §8, §17; `ORIGINAL_REQUEST.md` R2 |
| 8 | Database / Bulk | Bulk Batch & Result Storage | Tables `batches` and `batch_results` recording batch metadata and item-level execution outcomes (including partial failures). | Batch metadata (`batch_id`, status, counts) and item results (`order_id`, success, error_code, error_message) | Persisted rows in `batches` and `batch_results` tables | Database integrity errors mapped to `INTERNAL_ERROR` | `task.md` §17; `ORIGINAL_REQUEST.md` R4 |
| 9 | Architecture | Adapter Pattern Interface | Abstract base class `CourierAdapter` defining normalized lifecycle methods: `authenticate()`, `create_order()`, `track_order()`, `cancel_order()`. | Domain order model / tracking ID / AWB | Normalized courier response data | Adapter-specific exceptions translated to standardized domain exceptions | `task.md` §3; `ORIGINAL_REQUEST.md` R1 |
| 10 | Architecture | Dynamic Courier Registry | Factory/Registry mapping courier partner strings (e.g. `"urbanebolt"`, `"mock"`) to adapter instances without `if/elif` branching in business logic. | Courier name string (e.g., `"mock"`) | `CourierAdapter` instance | Missing courier throws `UnsupportedCourierError` mapped to `UNSUPPORTED_COURIER` (400) | `task.md` §4; `ORIGINAL_REQUEST.md` R1 |
| 11 | Courier | Mock Courier Adapter | In-memory/offline courier implementation providing deterministic fake data and test simulation modes (success, timeout, 4xx, 5xx, auth failure). | Configured simulation mode or request payload | Standard normalized courier response (`courier_order_id`, `awb_number`, status) | Throws simulated network timeout, 4xx client error, 5xx server error, or 401 auth error based on configuration | `task.md` §16; `ORIGINAL_REQUEST.md` R1 |
| 12 | Courier | UrbaneBolt Courier Adapter | Production adapter integrating with UrbaneBolt UAT APIs: token auth, manifest order creation, tracking-pub, cancel. Maps normalized domain models to UrbaneBolt schemas. | Normalized order schema or tracking AWB | Standard normalized courier response; handles internal auth token caching & headers | HTTP errors translated to domain exceptions (`COURIER_ERROR`, `COURIER_TIMEOUT`, `COURIER_AUTH_ERROR`) | `task.md` §15; `urbanebolt_doc.json` |
| 13 | Resiliency | Exponential Backoff Retry | Automatically retries transient courier network timeouts and 5xx responses using configurable exponential delays (`MAX_RETRIES`, `RETRY_DELAY`, `REQUEST_TIMEOUT`). | Failed network operation (timeout or 5xx) | Successful response on retry | Exhaustion of retries raises `COURIER_TIMEOUT` or `COURIER_ERROR` | `task.md` §13; `ORIGINAL_REQUEST.md` R3 |
| 14 | Resiliency | Automatic 401 Token Refresh | Detects courier 401 Unauthorized, automatically triggers adapter `authenticate()` to renew token, retries original call once. | 401 Unauthorized response from courier | Transparent recovery: returns courier call result using new token | Fails if second attempt also returns 401; raises `COURIER_AUTH_ERROR` | `task.md` §14; `ORIGINAL_REQUEST.md` R3 |
| 15 | Error Handling | Normalized Error Envelope | Standardized response envelope `{ "error": { "code": ..., "message": ..., "request_id": ..., "details": ... } }` across all HTTP error statuses. | Raised application or courier exceptions | Normalized JSON response envelope with appropriate HTTP status code | Catch-all for unhandled exceptions outputs `INTERNAL_ERROR` (500) | `task.md` §12; `ORIGINAL_REQUEST.md` R5 |
| 16 | Concurrency | In-Process Bulk Worker | Concurrent execution of bulk orders via Python `asyncio` (e.g., `asyncio.gather` with concurrency limiter or `ThreadPoolExecutor`) without Redis/Celery. | List of orders associated with `batch_id` | Updated batch summary counts and individual `batch_results` rows | Individual order failures are caught and recorded as partial failures without aborting remaining orders | `task.md` §1, §10; `ORIGINAL_REQUEST.md` R4 |
| 17 | Observability | Structured Operation Logging | Logs each courier operation with `request_id`, `order_id`, `courier_partner`, `operation`, `status`, and sanitized details (no secrets or PII). | Courier operations, request context | Structured log lines (stdout/file) | Masking ensures credentials/PII never leak to log streams | `task.md` §19 |
| 18 | Configuration | Environment-Based Config | Pydantic Settings / BaseSettings loading database URLs, courier credentials, timeouts, retry parameters from environment or `.env`. | `.env` or system environment variables | Strongly typed application settings object | Missing required settings trigger fail-fast configuration error on startup | `task.md` §18; `.env.example` |

---

## 3. Edge Cases & Boundary Conditions

| # | Feature | Input / Condition | Expected / Required Behavior |
|---|---------|-------------------|-----------------------------|
| 1 | Idempotency | Duplicate `order_id` submitted concurrently in two parallel requests | First request successfully persists; second request hits database UNIQUE constraint or pre-check lock, returning existing order details or HTTP 409 `DUPLICATE_ORDER`. Under NO circumstance should a second courier API call be triggered. |
| 2 | Idempotency | Re-submitting existing `order_id` with changed customer or items | System recognizes existing `order_id` via unique constraint; rejects modification or returns existing order snapshot without modifying original order or re-calling courier. |
| 3 | Bulk Processing | Bulk request with 0 orders (`[]`) | Rejected at validation boundary with HTTP 422/400 `VALIDATION_ERROR` (min items: 1). |
| 4 | Bulk Processing | Bulk request with 101 orders | Rejected at validation boundary with HTTP 422/400 `VALIDATION_ERROR` (max items: 100). |
| 5 | Bulk Processing | Bulk batch where orders target different couriers (e.g., 50 "mock", 50 "urbanebolt") | Processed concurrently; registry correctly resolves each courier adapter independently per item without cross-contamination. |
| 6 | Bulk Processing | Bulk batch with partial failures (e.g. 5 orders fail due to invalid courier or timeout, 95 succeed) | Batch status transitions to `COMPLETED`; summary counts reflect `total=100, successful=95, failed=5`; `batch_results` records specific `error_code` for failed orders and `success=True` for successful orders. Batch does not abort. |
| 7 | Bulk Processing | Polling `GET /api/v1/orders/bulk/{batch_id}` while still processing | Returns HTTP 200 with `status="PROCESSING"`, current progress counts, and any partial results recorded so far. |
| 8 | Bulk Processing | Polling `GET /api/v1/orders/bulk/{batch_id}` with non-existent `batch_id` | Returns HTTP 404 with normalized error envelope and `code="ORDER_NOT_FOUND"` (or `BATCH_NOT_FOUND`). |
| 9 | Retry & Resiliency | Courier returns HTTP 500/503 during `create_order` | Exponential backoff triggers up to `MAX_RETRIES` with delays ($1\text{s}, 2\text{s}, \dots$). If all retries fail, converts to `COURIER_ERROR` (502). |
| 10 | Retry & Resiliency | Courier times out after `REQUEST_TIMEOUT` seconds | Retries up to `MAX_RETRIES`. If all attempts time out, raises `COURIER_TIMEOUT` (504). |
| 11 | Retry & Resiliency | Courier returns HTTP 400 Bad Request | Non-retryable error; immediately fails and maps to `COURIER_ERROR` (502) without wasting retries. |
| 12 | Auth Refresh | Courier returns HTTP 401 on initial order creation | Adapter catches 401, invokes `authenticate()` to fetch fresh token, re-executes original request once. If second attempt succeeds, flow proceeds normally. |
| 13 | Auth Refresh | Courier returns HTTP 401 on second attempt after re-authenticating | Re-auth loop terminated (single retry only); raises `COURIER_AUTH_ERROR` (502). |
| 14 | Tracking History | Multiple successive `track` requests on same order | Each call fetches status and appends a new record to `tracking_history` with current timestamp and raw payload. Prior records remain untouched (audit trail preserved). |
| 15 | Tracking History | Tracking order with invalid or unassigned AWB | Adapter detects missing/invalid AWB; returns appropriate `COURIER_ERROR` or `VALIDATION_ERROR` without corrupting history. |
| 16 | Cancellation | Cancelling an already delivered or cancelled order | Adapter attempts cancellation with courier; if courier rejects (e.g. already delivered), courier error is normalized into `COURIER_ERROR` or domain rejection without corrupting order state. |
| 17 | Cancellation | Cancelling non-existent order | Returns HTTP 404 with `code="ORDER_NOT_FOUND"`. |
| 18 | Registry | Request specifies unregistered courier partner (e.g. `"fedex"`) | Fast failure at service layer: raises `UNSUPPORTED_COURIER` (HTTP 400). |
| 19 | Error Envelope | Unhandled runtime exception (e.g. DB connection dropped) | Global FastAPI exception handler catches exception, logs stack trace privately, generates `request_id`, returns HTTP 500 with `code="INTERNAL_ERROR"`. |
| 20 | UrbaneBolt Payload | Order items missing dimensions or weight | Adapter applies sensible default values (e.g. length: 10, width: 10, height: 10, weight: 0.5) to satisfy strict UrbaneBolt manifest schema without exposing fields to public API. |

---

## 4. API Endpoints & Request/Response Schemas

### 4.1 POST `/api/v1/orders` (Order Creation)
- **Method**: `POST`
- **Path**: `/api/v1/orders`
- **Request Headers**:
  - `Content-Type: application/json`
  - `X-Request-ID: <uuid>` (optional; generated if absent)
- **Request Body Schema**:
  ```json
  {
    "order_id": "ORD-001",
    "courier_partner": "mock",
    "customer": {
      "name": "John Doe",
      "phone": "9999999999",
      "address": "Mumbai, India"
    },
    "items": [
      {
        "name": "Product A",
        "quantity": 1,
        "price": 500
      }
    ]
  }
  ```
- **Validation Rules**:
  - `order_id`: String, required, non-empty, max length 64.
  - `courier_partner`: String, required, must be present in registry (`mock`, `urbanebolt`).
  - `customer`: Object, required.
    - `name`: String, required, min length 1.
    - `phone`: String, required, valid phone format.
    - `address`: String, required, min length 1.
  - `items`: List of objects, required, min items: 1.
    - `name`: String, required.
    - `quantity`: Integer, required, minimum 1.
    - `price`: Numeric (float or decimal), required, minimum 0.
- **Success Response (HTTP 201 Created or 200 OK)**:
  ```json
  {
    "order_id": "ORD-001",
    "courier_partner": "mock",
    "courier_order_id": "MOCK-123",
    "awb_number": "AWB-123",
    "status": "CREATED"
  }
  ```

### 4.2 GET `/api/v1/orders/{order_id}/track` (Order Tracking)
- **Method**: `GET`
- **Path**: `/api/v1/orders/{order_id}/track`
- **Path Parameters**:
  - `order_id`: String (required)
- **Success Response (HTTP 200 OK)**:
  ```json
  {
    "order_id": "ORD-001",
    "courier_partner": "mock",
    "awb_number": "AWB-123",
    "status": "IN_TRANSIT",
    "history": [
      {
        "status": "CREATED",
        "timestamp": "2026-09-28T14:00:00Z"
      },
      {
        "status": "PICKED_UP",
        "timestamp": "2026-09-28T14:15:00Z"
      },
      {
        "status": "IN_TRANSIT",
        "timestamp": "2026-09-28T14:30:00Z"
      }
    ]
  }
  ```
- **Normalized Status Enum Values**:
  - `CREATED`
  - `PICKED_UP`
  - `IN_TRANSIT`
  - `DELIVERED`
  - `CANCELLED`
  - `FAILED`

### 4.3 POST `/api/v1/orders/{order_id}/cancel` (Order Cancellation)
- **Method**: `POST`
- **Path**: `/api/v1/orders/{order_id}/cancel`
- **Path Parameters**:
  - `order_id`: String (required)
- **Success Response (HTTP 200 OK)**:
  ```json
  {
    "order_id": "ORD-001",
    "status": "CANCELLED"
  }
  ```

### 4.4 POST `/api/v1/orders/bulk` (Bulk Order Creation)
- **Method**: `POST`
- **Path**: `/api/v1/orders/bulk`
- **Request Body Schema**:
  ```json
  {
    "orders": [
      {
        "order_id": "ORD-001",
        "courier_partner": "mock",
        "customer": {
          "name": "Alice",
          "phone": "9999999991",
          "address": "Delhi, India"
        },
        "items": [
          { "name": "Item 1", "quantity": 1, "price": 100 }
        ]
      },
      {
        "order_id": "ORD-002",
        "courier_partner": "urbanebolt",
        "customer": {
          "name": "Bob",
          "phone": "9999999992",
          "address": "Surat, India"
        },
        "items": [
          { "name": "Item 2", "quantity": 2, "price": 250 }
        ]
      }
    ]
  }
  ```
- **Validation Rules**:
  - `orders`: Array of Order Creation payloads.
  - Length constraint: $1 \le \text{len}(orders) \le 100$.
- **Success Response (HTTP 202 Accepted)**:
  ```json
  {
    "batch_id": "BATCH-001",
    "status": "PROCESSING"
  }
  ```

### 4.5 GET `/api/v1/orders/bulk/{batch_id}` (Bulk Batch Status & Polling)
- **Method**: `GET`
- **Path**: `/api/v1/orders/bulk/{batch_id}`
- **Path Parameters**:
  - `batch_id`: String (required)
- **Success Response (HTTP 200 OK)**:
  ```json
  {
    "batch_id": "BATCH-001",
    "status": "COMPLETED",
    "total": 100,
    "successful": 95,
    "failed": 5,
    "results": [
      {
        "order_id": "ORD-001",
        "success": true
      },
      {
        "order_id": "ORD-002",
        "success": false,
        "error_code": "COURIER_TIMEOUT"
      }
    ]
  }
  ```

---

## 5. Domain Models, Database Schemas & Data Constraints

The database uses SQLite via SQLAlchemy.

### 5.1 `orders` Table
```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id VARCHAR(64) NOT NULL UNIQUE,
    courier_partner VARCHAR(32) NOT NULL,
    courier_order_id VARCHAR(128),
    awb_number VARCHAR(128),
    status VARCHAR(32) NOT NULL,
    request_payload JSON NOT NULL,
    response_payload JSON,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX ix_orders_order_id ON orders(order_id);
```
- **Key Constraints**:
  - `order_id` is globally UNIQUE. Re-inserting the same `order_id` fails with integrity constraint.
  - `status` tracks the normalized lifecycle state.
  - `request_payload` and `response_payload` preserve raw input and courier output for auditability.

### 5.2 `tracking_history` Table
```sql
CREATE TABLE tracking_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    raw_payload JSON,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(order_id) REFERENCES orders(order_id)
);
CREATE INDEX ix_tracking_history_order_id ON tracking_history(order_id);
```
- **Immutability Invariant**:
  - Rows are append-only.
  - No `UPDATE` or `DELETE` operations are ever executed against `tracking_history`.
  - Every order creation appends `CREATED`. Every tracking poll appends the latest state. Every cancellation appends `CANCELLED`.

### 5.3 `batches` Table
```sql
CREATE TABLE batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL, -- PROCESSING, COMPLETED, FAILED
    total INTEGER NOT NULL,
    successful INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX ix_batches_batch_id ON batches(batch_id);
```

### 5.4 `batch_results` Table
```sql
CREATE TABLE batch_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(64) NOT NULL,
    success BOOLEAN NOT NULL,
    error_code VARCHAR(64),
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(batch_id) REFERENCES batches(batch_id)
);
CREATE INDEX ix_batch_results_batch_id ON batch_results(batch_id);
```

### 5.5 Idempotency Architecture
1. **Pre-check**: Look up `order_id` in repository.
   - If present: return existing record or HTTP 409 `DUPLICATE_ORDER` without contacting courier.
2. **Database Unique Constraint**: Guarantees that concurrent submissions of the same `order_id` cannot create duplicate rows; the second insert raises an `IntegrityError`.
3. **Courier Call Safety**: Downstream courier calls only occur after validation and during uncommitted/guarded order creation.

---

## 6. Courier Abstraction Layer & Registry

### 6.1 `CourierAdapter` Base Interface (`app/couriers/base.py`)
```python
from abc import ABC, abstractmethod
from typing import Any, Dict

class CourierAdapter(ABC):
    @abstractmethod
    def authenticate(self) -> Dict[str, Any]:
        """Authenticate with the courier API and acquire auth tokens/credentials."""
        pass

    @abstractmethod
    def create_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert internal order to courier payload, dispatch creation, normalize response.
        Returns: {courier_order_id, awb_number, status, raw_response}
        """
        pass

    @abstractmethod
    def track_order(self, awb_number: str) -> Dict[str, Any]:
        """Query live tracking status from courier and normalize response.
        Returns: {status, raw_response, tracking_events}
        """
        pass

    @abstractmethod
    def cancel_order(self, awb_number: str) -> Dict[str, Any]:
        """Send cancellation request to courier and normalize response.
        Returns: {status, raw_response}
        """
        pass
```

### 6.2 `CourierRegistry` Factory (`app/couriers/registry.py`)
- Maps courier partner identifiers to adapter instances.
- Pattern:
  ```python
  class CourierRegistry:
      def __init__(self):
          self._adapters: dict[str, CourierAdapter] = {}

      def register(self, name: str, adapter: CourierAdapter) -> None:
          self._adapters[name.lower()] = adapter

      def get(self, name: str) -> CourierAdapter:
          adapter = self._adapters.get(name.lower())
          if not adapter:
              raise UnsupportedCourierError(f"Courier '{name}' is not supported")
          return adapter
  ```
- Adding a new courier requires:
  1. Creating `<courier_name>_adapter.py` implementing `CourierAdapter`.
  2. Registering in registry: `courier_registry.register("<courier_name>", MyNewAdapter(config))`.
  3. No changes to controllers, `OrderService`, or existing adapters.

### 6.3 `MockCourierAdapter` Specification (`app/couriers/mock.py`)
- Designed for unit, integration, and load testing without external network access.
- Generated mock outputs:
  - `courier_order_id`: `"MOCK-ORD-" + order_id`
  - `awb_number`: `"MOCK-AWB-" + random_digits`
  - `status`: `"CREATED"`
- Configurable simulation modes:
  - `MODE_SUCCESS`: Standard happy path.
  - `MODE_TIMEOUT`: Simulates network timeouts (raises `httpx.TimeoutException`).
  - `MODE_4XX`: Simulates HTTP 400 Bad Request.
  - `MODE_5XX`: Simulates HTTP 500 / 503 Internal Server Error.
  - `MODE_AUTH_FAILURE`: Simulates HTTP 401 Unauthorized (can test 1st attempt 401 followed by success on refresh).

### 6.4 `UrbaneboltAdapter` Integration Specification (`app/couriers/urbanebolt.py`)
Mined from `urbanebolt_doc.json`:
1. **Authentication API**:
   - `POST https://uat.urbanebolt.in/api/v1/auth/getToken/`
   - Request: `{"username": "<user>", "password": "<password>"}`
   - Header: `Content-Type: application/json`
   - Response: Returns token (Bearer token string or token object).
   - Cache: Token cached in memory in adapter instance; re-fetched on 401.
2. **Manifest API (Create Order)**:
   - `POST https://uat.urbanebolt.in/api/v1/services/manifest/`
   - Header: `Authorization: Bearer <token>`, `Content-Type: application/json`
   - Body: JSON array with 1 order item:
     - `orderNumber`: mapped from `order_id`
     - `customerCode`: from config (e.g. `UEBCUS0008`)
     - `declaredValue`, `collectableValue`, `itemQuantity`, `invoiceValue`
     - `itemDescription`: compiled from item names
     - `serviceType`: `"SDD"` or `"NDD"` (default `"SDD"`)
     - `payMode`: `"COD"` or `"PPD"` (default `"COD"`)
     - Consignee details (`consName`, `consMobile`, `consAddress`, `consCity`, `consState`, `consPincode`, `consCountry`: `"INDIA"`, `consAddressType`: `"Home"`)
     - Shipper/Return details (`shprName`, `shprMobile`, `shprAddress`, `shprCity`, `shprState`, `shprPincode`, `shprCountry`: `"INDIA"`, `shprAddressType`: `"Seller"`)
     - Package defaults: `length`: 10, `breadth`: 10, `height`: 10, `weight`: 1.0, `pieces`: 1
   - Response mapping: extracts generated `awb` or tracking number and order status.
3. **Tracking API**:
   - `GET https://uat.urbanebolt.in/api/v1/services/tracking-pub/?awb={awb}`
   - Header: `Authorization: Bearer <token>`
   - Status normalization: maps UrbaneBolt statuses to normalized domain enums.
4. **Cancellation API**:
   - `POST https://uat.urbanebolt.in/api/v1/services/cancel/`
   - Header: `Authorization: Bearer <token>`, `Content-Type: application/json`
   - Body: `{"awbs": "{awb}"}`
   - Normalization: maps response to `CANCELLED`.

---

## 7. Error Handling Envelope & Error Code Mappings

### 7.1 Unified Error JSON Schema
All error responses from any endpoint must strictly follow:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request payload",
    "request_id": "req-9b8417c8-...",
    "details": {}
  }
}
```

### 7.2 Standard Error Codes & HTTP Status Codes

| Error Code | HTTP Status | Description & Trigger Conditions |
|------------|-------------|----------------------------------|
| `VALIDATION_ERROR` | 422 / 400 | Invalid payload, missing fields, batch size > 100 or == 0 |
| `UNSUPPORTED_COURIER` | 400 | Requested courier not registered in `CourierRegistry` |
| `ORDER_NOT_FOUND` | 404 | `order_id` not found in `orders` table |
| `DUPLICATE_ORDER` | 409 | Duplicate `order_id` submitted (idempotency violation) |
| `COURIER_ERROR` | 502 | Downstream courier returned client or server failure after retries |
| `COURIER_TIMEOUT` | 504 | Downstream courier network timeout exhausted all retry attempts |
| `COURIER_AUTH_ERROR` | 502 | Downstream courier authentication failed (even after re-auth retry) |
| `INTERNAL_ERROR` | 500 | Unhandled service exception or internal unexpected failure |

---

## 8. Bulk Processing Asynchronous Execution Architecture

### 8.1 In-Process Concurrency Mechanism
- **Requirement**: No Redis, Kafka, or Celery. Processing must run in-process.
- **Approach**:
  - FastAPI `BackgroundTasks` or `asyncio.create_task` running an async worker routine.
  - Concurrency control: `asyncio.Semaphore(concurrency_limit)` (e.g. 5 to 10 concurrent requests) to avoid overwhelming SQLite or downstream APIs.
- **Execution Flow**:
  1. `POST /api/v1/orders/bulk` receives up to 100 orders.
  2. Generates `batch_id` (e.g., `BATCH-<uuid4>[:8]`).
  3. Creates record in `batches` table with status `PROCESSING`, `total=len(orders)`, `successful=0`, `failed=0`.
  4. Dispatches background worker task.
  5. Returns HTTP 202 with `batch_id` and `status="PROCESSING"` immediately.
  6. Worker loops over items concurrently:
     - Each order is processed via `OrderService.create_order` in its own database session.
     - If successful: record `batch_results` (`success=True`), increment `successful`.
     - If failed: catch exception, extract `error_code` and `error_message`, record `batch_results` (`success=False`, `error_code=...`), increment `failed`.
  7. Upon completion of all orders, batch status transitions to `COMPLETED`.

---

## 9. Retry, Resiliency & Token Refresh Logic

### 9.1 Transient Error Detection & Exponential Backoff
- **Parameters**:
  - `REQUEST_TIMEOUT`: Default 10 seconds.
  - `MAX_RETRIES`: Default 2 or 3 retries.
  - `RETRY_DELAY`: Base delay 1.0 second.
- **Backoff Formula**:
  $$\text{delay} = \text{RETRY\_DELAY} \times 2^{\text{attempt}}$$
  - Attempt 0: initial attempt.
  - If fails with 5xx or timeout:
    - Attempt 1: wait $1.0 \times 2^0 = 1.0$s
    - Attempt 2: wait $1.0 \times 2^1 = 2.0$s
    - Exhaustion: raise `COURIER_TIMEOUT` or `COURIER_ERROR`.
- **Exclusion**: HTTP 4xx (except 401) is non-transient and must NOT be retried.

### 9.2 Courier 401 Token Refresh Logic
- When a courier API call returns HTTP 401 Unauthorized:
  1. Catch 401 exception in adapter.
  2. Invoke `authenticate()` to obtain a fresh token.
  3. Re-execute the failed operation with the newly acquired token.
  4. If the retry also fails with 401, terminate retry cycle and raise `COURIER_AUTH_ERROR`.

---

## 10. Configuration, Environment & Security

### 10.1 Environment Variables
Managed via `app/config.py` using `pydantic-settings`:
- `DATABASE_URL`: default `sqlite:///./app.db`
- `URBANEBOLT_BASE_URL`: default `https://uat.urbanebolt.in`
- `URBANEBOLT_USERNAME`: UrbaneBolt username
- `URBANEBOLT_PASSWORD`: UrbaneBolt password
- `URBANEBOLT_API_KEY`: API key if needed
- `REQUEST_TIMEOUT`: default `10`
- `MAX_RETRIES`: default `2`
- `RETRY_DELAY`: default `1.0`
- `BULK_CONCURRENCY`: default `10`

### 10.2 Logging & Sanitization
- Every courier operation logs:
  - `request_id`, `order_id`, `courier_partner`, `operation`, `status`, `duration_ms`.
- Secrets filtering: Passwords, tokens, and PII are redacted/masked.

---

## 11. Testing Requirements

Pytest test suite organized as follows:
- `tests/test_orders.py`:
  - `test_create_order_success`
  - `test_create_order_validation_failure`
  - `test_create_order_unsupported_courier`
  - `test_track_order_success`
  - `test_track_order_not_found`
  - `test_cancel_order_success`
  - `test_cancel_order_not_found`
  - `test_tracking_history_immutability`
- `tests/test_idempotency.py`:
  - `test_duplicate_order_id_rejection`
  - `test_concurrent_duplicate_submission`
- `tests/test_mock_courier.py`:
  - `test_mock_courier_success`
  - `test_mock_courier_timeout_simulation`
  - `test_mock_courier_5xx_simulation`
  - `test_mock_courier_4xx_simulation`
  - `test_mock_courier_auth_failure_and_refresh`
- `tests/test_bulk.py`:
  - `test_bulk_submission_and_batch_polling`
  - `test_bulk_max_100_orders_limit`
  - `test_bulk_heterogeneous_couriers`
  - `test_bulk_partial_failure_handling`
  - `test_bulk_background_execution`

---

## 12. Documentation Deliverables

### 12.1 `README.md`
- Overview and key capabilities.
- Architecture diagram and folder breakdown.
- Prerequisites (Python 3.12+).
- Setup and installation instructions (`pip install -r requirements.txt`).
- Environment variable configuration (`.env.example`).
- Running locally (`uvicorn app.main:app --reload`).
- Running tests (`pytest -v`).
- Complete `curl` / API examples for all endpoints.
- Step-by-step guide for adding a new courier.

### 12.2 `DESIGN.md`
- High-level architecture and layered design.
- Adapter Pattern & CourierRegistry decoupling.
- Request flow sequence diagrams (Order creation, Tracking, Cancellation, Bulk).
- Database schema design, indices, and audit immutability.
- In-process bulk processing architecture and concurrency management.
- Retry strategy, exponential backoff, and 401 token refresh mechanism.
- Idempotency guarantees and race condition protections.
- Unified error handling envelope.
- Architectural trade-offs and future scaling paths.
