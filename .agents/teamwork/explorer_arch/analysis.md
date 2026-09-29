# Architecture and Integration Specification: Courier Integration Platform

**Author**: Architecture and Integration Explorer (`explorer_arch`)  
**Date**: 2026-09-28  
**Project**: Courier Integration Platform Backend Service  
**Repository Root**: `.`

---

## 1. Executive Summary & Architectural Overview

The Courier Integration Platform is a production-grade, unified logistics integration service built with Python 3.14, FastAPI, SQLAlchemy 2.0, and SQLite. The primary goal of the system is to present a single, standardized, courier-agnostic REST API to client applications while abstracting the complexities, disparate schemas, authentication mechanisms, and network failure modes of diverse third-party courier partners (specifically UrbaneBolt and a simulated Mock courier).

### Core Architectural Principles
1. **Coupling Decoupling via Adapter Pattern**: High-level business services (`OrderService`) depend strictly on the abstract `CourierAdapter` interface. They have zero direct knowledge of concrete courier implementations (`UrbaneboltAdapter`, `MockCourierAdapter`).
2. **Dynamic Courier Registry**: Courier adapters are registered dynamically in a centralized `CourierRegistry`. Adding new courier partners requires creating a new adapter class and registering it, with zero modifications to existing controllers or core business logic (Open-Closed Principle).
3. **Normalized Order Lifecycle & Append-Only Audit History**: All internal order statuses conform to a strict 6-state domain lifecycle (`CREATED`, `PICKED_UP`, `IN_TRANSIT`, `DELIVERED`, `CANCELLED`, `FAILED`). The `tracking_history` table operates as an append-only immutable ledger, preserving complete chronological state changes without overwriting prior records.
4. **Idempotency by Design**: Database-level `UNIQUE` constraint on `order_id` combined with service-layer verification guarantees that duplicate submissions do not generate duplicate shipments or redundant external courier API invocations.
5. **Resilient Execution & Self-Healing Authentication**: Exponential backoff retries handle transient network timeouts and courier 5xx server errors, while a dedicated re-authentication wrapper transparently refreshes expired bearer tokens upon receiving 401 Unauthorized responses.
6. **In-Process Concurrent Bulk Processing**: Processes batches of up to 100 orders concurrently using in-process asynchronous task orchestration (`asyncio.create_task` with `asyncio.Semaphore` rate-limiting), avoiding heavy external brokers (Celery/Redis) while delivering resilient partial failure isolation and batch progress polling.
7. **Unified Error Envelope**: All API exceptions, validation failures, and courier errors are intercepted by global exception handlers and translated into a normalized `{ "error": { "code": ..., "message": ..., "request_id": ..., "details": ... } }` schema.

---

## 2. Technology Stack & Runtime Environment Validation

Direct inspection of the local development environment confirms that all required toolchains and dependencies are available:

| Component | Installed Version | Architectural Role & Implementation Details |
|---|---|---|
| **Python** | `3.14.6` | Runtime environment. Modern type hinting (`typing`, `Optional`, `list[str]`), pattern matching, `asyncio` event loop. |
| **FastAPI** | `0.141.1` | Web framework. Async path operations, dependency injection (`Depends`), lifespan management, global exception handlers. |
| **Pydantic** | `2.13.4` | Data validation & serialization. Pydantic v2 `BaseModel`, `Field`, `ConfigDict`, strict validation. |
| **Pydantic-Settings** | `2.14.2` | Configuration management. `BaseSettings` reading environment variables and `.env` file. |
| **SQLAlchemy** | `2.0.51` | ORM & Database toolkit. SQLAlchemy 2.0 declarative mapping (`DeclarativeBase`, `Mapped`, `mapped_column`, `select`). |
| **SQLite / sqlite3** | `3.50.4` | Persistent database storage. Configured with Write-Ahead Logging (WAL) and busy timeout for concurrent access. |
| **httpx** | `0.28.1` | Async HTTP client. `httpx.AsyncClient` with custom timeouts, connection pooling, and error interception. |
| **pytest** | `8.3.3` | Test runner. Fixtures, parameterized tests, assertions. |
| **pytest-asyncio** | `0.24.0` | Async testing harness for FastAPI endpoints and coroutines (`@pytest.mark.asyncio`). |
| **uvicorn** | `0.52.0` | ASGI web server for local development and execution. |

### Dependencies Specification (`requirements.txt`)
```text
fastapi>=0.110.0,<1.0.0
uvicorn>=0.28.0,<1.0.0
sqlalchemy>=2.0.0,<3.0.0
pydantic>=2.6.0,<3.0.0
pydantic-settings>=2.2.0,<3.0.0
httpx>=0.27.0,<1.0.0
pytest>=8.0.0,<9.0.0
pytest-asyncio>=0.23.0,<1.0.0
python-dotenv>=1.0.0,<2.0.0
```

---

## 3. Project Structure & File Layout

Adhering to the modular layered architecture defined in `task.md`, the repository layout organizes concerns cleanly across presentation (API), domain, service, courier adapter, database, and utility layers:

```text
./
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application factory, lifespan, middleware, routers
│   ├── config.py                   # Pydantic BaseSettings loading .env configuration
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes_orders.py        # REST endpoints: POST /orders, GET /orders/{id}/track, POST /cancel, POST/GET /bulk
│   │   └── schemas.py              # Pydantic v2 request/response schemas, DTOs, standard error envelope
│   │
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models.py               # SQLAlchemy 2.0 ORM models (Order, TrackingHistory, Batch, BatchResult)
│   │   └── enums.py                # OrderStatus, BatchStatus, ErrorCode, CourierPartner enums
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   └── order_service.py        # Core business service: order lifecycle, idempotency, bulk orchestration
│   │
│   ├── couriers/
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract CourierAdapter ABC & normalized courier DTOs
│   │   ├── registry.py             # Dynamic CourierRegistry for plug-and-play courier lookup
│   │   ├── urbanebolt.py           # UrbaneBolt UAT integration with token refresh & payload mapping
│   │   └── mock.py                 # MockCourierAdapter with failure simulation modes
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py             # Engine, SessionLocal, WAL mode listeners, init_db(), get_db dependency
│   │   └── repositories.py         # OrderRepository, TrackingRepository, BatchRepository
│   │
│   └── utils/
│       ├── __init__.py
│       ├── errors.py               # AppError hierarchy & global FastAPI exception handlers
│       ├── retry.py                # Exponential backoff retry utility and decorator
│       └── logger.py               # Structured logger with sanitization of sensitive credentials
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures: test DB, client, mock courier configuration
│   ├── test_orders.py              # Order creation, live tracking, cancellation tests
│   ├── test_bulk.py                # Bulk processing, 100 orders concurrent, partial failure tests
│   ├── test_mock_courier.py        # Failure simulation (timeout, 5xx, auth failure, client error)
│   ├── test_idempotency.py         # Duplicate order submission and conflict tests
│   ├── test_retry.py               # Exponential backoff retry and token refresh tests
│   └── test_urbanebolt.py          # UrbaneBolt payload conversion and normalized responses
│
├── .env.example                    # Environment variable template
├── requirements.txt                # Production and development dependencies
├── README.md                       # Architecture, setup, running, testing, adding new couriers
├── DESIGN.md                       # Comprehensive architectural design document
├── urbanebolt_doc.json             # Reference UrbaneBolt Postman collection
└── task.md                         # Authoritative task specifications
```

---

## 4. Database Schema & Persistence Strategy

### 4.1 SQLite Configuration & Concurrency Management
SQLite is a single-file database that, by default, locks the database file during write transactions. Under concurrent bulk order processing (e.g. 100 simultaneous orders), multiple threads/coroutines writing concurrently would trigger `sqlite3.OperationalError: database is locked`.

To guarantee non-blocking reads and high-throughput concurrent writes:
1. **Write-Ahead Logging (WAL)**: `PRAGMA journal_mode=WAL;` is activated upon every database connection. WAL enables multiple concurrent readers alongside a concurrent writer.
2. **Busy Timeout**: `PRAGMA busy_timeout=30000;` ensures the SQLite connection handler waits up to 30 seconds for locks to release rather than raising immediate busy errors.
3. **Foreign Keys Enforcement**: `PRAGMA foreign_keys=ON;` enforces referential integrity between orders and tracking histories.
4. **Thread Isolation**: `check_same_thread=False` allows connections to be shared safely across async execution threads.

```python
# app/db/database.py
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30.0},
)

@event.listens_for(engine, "connect")
def configure_sqlite_connection(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    Base.metadata.create_all(bind=engine)
```

### 4.2 Entity-Relationship & Schema Definition

```text
┌────────────────────────┐         ┌────────────────────────┐
│         orders         │         │    tracking_history    │
├────────────────────────┤         ├────────────────────────┤
│ id (PK)                │1       *│ id (PK)                │
│ order_id (UNIQUE, IDX) ├─────────┤ order_id (FK, IDX)     │
│ courier_partner        │         │ status                 │
│ courier_order_id       │         │ raw_payload (JSON)     │
│ awb_number (IDX)       │         │ created_at             │
│ status                 │         └────────────────────────┘
│ request_payload (JSON) │
│ response_payload (JSON)│
│ created_at             │
│ updated_at             │
└────────────────────────┘

┌────────────────────────┐         ┌────────────────────────┐
│        batches         │         │     batch_results      │
├────────────────────────┤         ├────────────────────────┤
│ id (PK)                │1       *│ id (PK)                │
│ batch_id (UNIQUE, IDX) ├─────────┤ batch_id (FK, IDX)     │
│ status                 │         │ order_id               │
│ total                  │         │ success (BOOLEAN)      │
│ successful             │         │ error_code             │
│ failed                 │         │ error_message          │
│ created_at             │         │ created_at             │
│ updated_at             │         └────────────────────────┘
└────────────────────────┘
```

#### Detailed Table Specifications

1. **`orders` Table**:
   - `id`: `Integer`, Primary Key, autoincrement.
   - `order_id`: `String(64)`, `unique=True`, `index=True`, `nullable=False`. The unique business identifier.
   - `courier_partner`: `String(32)`, `nullable=False`, `index=True`. Name of the registered courier (e.g. `mock`, `urbanebolt`).
   - `courier_order_id`: `String(128)`, `nullable=True`. The external courier reference identifier.
   - `awb_number`: `String(128)`, `nullable=True`, `index=True`. Air Waybill tracking number.
   - `status`: `String(32)`, `nullable=False`, `default="CREATED"`. Standardized order status (`CREATED`, `PICKED_UP`, `IN_TRANSIT`, `DELIVERED`, `CANCELLED`, `FAILED`).
   - `request_payload`: `Text` (JSON-encoded), `nullable=True`. Complete customer and item request payload.
   - `response_payload`: `Text` (JSON-encoded), `nullable=True`. Raw courier creation response.
   - `created_at`: `DateTime(timezone=True)`, `default=func.now()`, `nullable=False`.
   - `updated_at`: `DateTime(timezone=True)`, `default=func.now()`, `onupdate=func.now()`, `nullable=False`.

2. **`tracking_history` Table** (Immutable Audit Trail):
   - `id`: `Integer`, Primary Key, autoincrement.
   - `order_id`: `String(64)`, `index=True`, `nullable=False`. Logical link to `orders.order_id`.
   - `status`: `String(32)`, `nullable=False`. The state recorded at this event.
   - `raw_payload`: `Text` (JSON-encoded), `nullable=True`. Unmodified response received from courier tracking API.
   - `created_at`: `DateTime(timezone=True)`, `default=func.now()`, `nullable=False`.
   - *Rule*: Appended on order creation, status poll (`/track`), and cancellation (`/cancel`). Prior records are never updated or deleted.

3. **`batches` Table**:
   - `id`: `Integer`, Primary Key, autoincrement.
   - `batch_id`: `String(64)`, `unique=True`, `index=True`, `nullable=False`. Unique batch identifier (e.g. `BATCH-a1b2c3d4`).
   - `status`: `String(32)`, `nullable=False`, `default="PROCESSING"`. (`PROCESSING`, `COMPLETED`, `FAILED`).
   - `total`: `Integer`, `nullable=False`, `default=0`.
   - `successful`: `Integer`, `nullable=False`, `default=0`.
   - `failed`: `Integer`, `nullable=False`, `default=0`.
   - `created_at`: `DateTime(timezone=True)`, `default=func.now()`, `nullable=False`.
   - `updated_at`: `DateTime(timezone=True)`, `default=func.now()`, `onupdate=func.now()`, `nullable=False`.

4. **`batch_results` Table**:
   - `id`: `Integer`, Primary Key, autoincrement.
   - `batch_id`: `String(64)`, `index=True`, `nullable=False`. Reference to `batches.batch_id`.
   - `order_id`: `String(64)`, `nullable=False`.
   - `success`: `Boolean`, `nullable=False`.
   - `error_code`: `String(64)`, `nullable=True`. Standard error code if failed (e.g. `COURIER_TIMEOUT`, `DUPLICATE_ORDER`).
   - `error_message`: `Text`, `nullable=True`.
   - `created_at`: `DateTime(timezone=True)`, `default=func.now()`, `nullable=False`.

---

## 5. Decoupled Courier Adapter Architecture

### 5.1 The Abstract Interface (`CourierAdapter`)
To guarantee that the domain and API layers remain completely independent of external courier APIs, the abstract base class defines the standardized contract. All methods return strongly-typed, normalized data transfer objects (DTOs).

```python
# app/couriers/base.py
from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel
from app.domain.enums import OrderStatus
from app.api.schemas import OrderCreateRequest

class CourierOrderResult(BaseModel):
    courier_order_id: str
    awb_number: str
    status: OrderStatus
    raw_response: dict[str, Any]

class CourierTrackingResult(BaseModel):
    status: OrderStatus
    awb_number: str
    raw_response: dict[str, Any]
    tracking_events: list[dict[str, Any]] = []

class CourierCancelResult(BaseModel):
    status: OrderStatus
    success: bool
    raw_response: dict[str, Any]

class CourierAdapter(ABC):
    @property
    @abstractmethod
    def partner_name(self) -> str:
        """Returns the canonical courier name."""
        pass

    @abstractmethod
    async def authenticate(self) -> None:
        """Authenticates with the courier and caches credentials/tokens."""
        pass

    @abstractmethod
    async def create_order(self, order_data: OrderCreateRequest) -> CourierOrderResult:
        """Transforms unified request, calls courier manifest API, returns normalized result."""
        pass

    @abstractmethod
    async def track_order(self, awb_number: str) -> CourierTrackingResult:
        """Queries courier tracking API, normalizes status to OrderStatus."""
        pass

    @abstractmethod
    async def cancel_order(self, awb_number: str) -> CourierCancelResult:
        """Invokes courier cancellation API, confirms cancellation."""
        pass
```

### 5.2 Dynamic Registry (`CourierRegistry`)
The registry provides a centralized factory mechanism. Business logic never contains `if courier == 'urbanebolt'` branches.

```python
# app/couriers/registry.py
from typing import Callable, Optional
from app.couriers.base import CourierAdapter
from app.utils.errors import UnsupportedCourierError

class CourierRegistry:
    def __init__(self):
        self._adapters: dict[str, CourierAdapter] = {}

    def register(self, name: str, adapter: CourierAdapter) -> None:
        self._adapters[name.lower().strip()] = adapter

    def get(self, name: str) -> CourierAdapter:
        normalized = name.lower().strip()
        if normalized not in self._adapters:
            raise UnsupportedCourierError(courier_partner=name)
        return self._adapters[normalized]

    def list_supported(self) -> list[str]:
        return list(self._adapters.keys())

courier_registry = CourierRegistry()
```

#### Zero-Modification Extensibility
To add a new courier (e.g. `FedEx` or `Delhivery`):
1. Create `app/couriers/delhivery.py` subclassing `CourierAdapter`.
2. Register it in `app/main.py` lifespan: `courier_registry.register("delhivery", DelhiveryAdapter(config))`.
3. Add courier configuration to `.env`.
Zero modifications required in `routes_orders.py`, `order_service.py`, or existing adapters!

### 5.3 UrbaneBolt Adapter Design
Based on `urbanebolt_doc.json`:
- **Authentication**: `POST /api/v1/auth/getToken/` with `{"username": "...", "password": "..."}`. Returns JWT bearer token.
- **Manifest / Order Creation**: `POST /api/v1/services/manifest/` with `Authorization: Bearer <token>`. Request body is a JSON array of manifests. Adapter maps generic customer info into UrbaneBolt consignee fields (`consName`, `consAddress`, `consMobile`, `consCity`, `consState`, `consPincode`), supplies default shipper/seller settings, and extracts generated AWB from response.
- **Tracking**: `GET /api/v1/services/tracking-pub/?awb=<awb_number>`. Normalizes UrbaneBolt status string to `OrderStatus`.
- **Cancellation**: `POST /api/v1/services/cancel/` with `{"awbs": "<awb_number>"}`.
- **Token Invalidation & Auto-Refresh**: If any endpoint returns HTTP 401 Unauthorized, the adapter invalidates `self._token`, executes `authenticate()`, and retries the request exactly once.

### 5.4 Mock Courier Adapter Design
The `MockCourierAdapter` enables complete offline testing with predictable simulations:
- Generates realistic synthetic IDs (`MOCK-ORD-<uuid>`, `AWB-MOCK-<uuid>`).
- Supports simulated outcome modes configurable globally or via order attributes:
  1. `SUCCESS`: Normal instant success with status `CREATED`.
  2. `TIMEOUT`: Raises `CourierTimeoutError` simulating network timeout.
  3. `SERVER_ERROR`: Raises `CourierGenericError` simulating HTTP 500/503.
  4. `CLIENT_ERROR`: Raises `ValidationError` simulating HTTP 400 Bad Request.
  5. `AUTH_FAILURE`: Simulates 401 failure on first attempt, resets on re-auth, succeeds on retry.
- **Per-Order Bulk Simulation**: If `order.customer.name` contains `SIMULATE_TIMEOUT`, `SIMULATE_5XX`, or `SIMULATE_AUTH_FAIL`, the mock adapter triggers that specific behavior only for that order, enabling granular validation of partial bulk failures in a single test batch.

---

## 6. Error Handling Architecture & Standard Envelope

### 6.1 Unified Error Envelope
All error responses across the platform conform strictly to the specification in `task.md` Section 12:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Detailed human-readable message",
    "request_id": "c1f7a24e-b5c6-48c9-940e-561bcf704771",
    "details": {}
  }
}
```

### 6.2 Custom Exception Hierarchy
```text
AppError (base exception)
 ├── ValidationError (code: VALIDATION_ERROR, status: 400)
 ├── UnsupportedCourierError (code: UNSUPPORTED_COURIER, status: 400)
 ├── OrderNotFoundError (code: ORDER_NOT_FOUND, status: 404)
 ├── DuplicateOrderError (code: DUPLICATE_ORDER, status: 409)
 ├── CourierException (base courier error)
 │    ├── CourierTimeoutError (code: COURIER_TIMEOUT, status: 504)
 │    ├── CourierAuthError (code: COURIER_AUTH_ERROR, status: 502)
 │    └── CourierGenericError (code: COURIER_ERROR, status: 502)
 └── InternalServerError (code: INTERNAL_ERROR, status: 500)
```

### 6.3 Global Exception Handlers & Request-ID Middleware
- **Request ID Middleware**: Injects `request_id = str(uuid.uuid4())` into `request.state.request_id` and adds `X-Request-ID` header to all outgoing responses.
- **AppError Handler**: Maps any `AppError` subclass to its configured HTTP status code and standard error envelope.
- **RequestValidationError Handler**: Overrides FastAPI's default 422 JSON response to emit `VALIDATION_ERROR` with detailed validation paths in `details.fields`.
- **StarletteHTTPException Handler**: Catches standard 404/405/500 HTTP exceptions and encapsulates them in the standard format.
- **Catch-All Exception Handler**: Catches unexpected uncaught Python exceptions, logs the full traceback with the request ID, and returns HTTP 500 with `INTERNAL_ERROR`. Raw exception strings and secrets are never leaked to clients.

---

## 7. Resiliency Patterns: Retries, Exponential Backoff & Auth Refresh

### 7.1 Retry Mechanism with Exponential Backoff
Courier API calls are subject to transient network failures, connection drops, and temporary upstream downtime.

#### Classification of Errors
| Error Type | Action | Rationale |
|---|---|---|
| `httpx.TimeoutException`, `CourierTimeoutError` | **Retry with backoff** | Upstream courier server may be temporarily slow or experiencing transient network partition. |
| `httpx.HTTPStatusError` with 500, 502, 503, 504 | **Retry with backoff** | Transient upstream server error. |
| `httpx.ConnectError` | **Retry with backoff** | Transient TCP connection handshake failure. |
| `httpx.HTTPStatusError` with 401 | **Auth refresh, retry once** | Expired access token. |
| `httpx.HTTPStatusError` with 400, 404, 422 | **Do NOT retry (Fail fast)** | Client/semantic error; retrying identical payload will never succeed. |
| `DuplicateOrderError` | **Do NOT retry (Fail fast)** | Business constraint violation. |

#### Backoff Formula
$$\text{delay} = \text{RETRY\_DELAY} \times 2^{\text{attempt}}$$
For `RETRY_DELAY = 1.0` and `MAX_RETRIES = 2`:
- Attempt 0: initial attempt
- Attempt 1: wait $1.0 \times 2^0 = 1.0\text{s}$
- Attempt 2: wait $1.0 \times 2^1 = 2.0\text{s}$
- If still failing: raise `CourierTimeoutError` or `CourierGenericError`.

```python
# app/utils/retry.py
import asyncio
import logging
from typing import Callable, Coroutine, TypeVar, Any
from app.utils.errors import CourierTimeoutError, CourierGenericError
import httpx

T = TypeVar("T")
logger = logging.getLogger("courier_platform")

async def retry_with_backoff(
    operation: Callable[[], Coroutine[Any, Any, T]],
    max_retries: int = 2,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (CourierTimeoutError, httpx.TimeoutException, httpx.ConnectError)
) -> T:
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except retryable_exceptions as exc:
            last_exception = exc
            if attempt == max_retries:
                logger.error(f"Operation failed after {max_retries} retries: {exc}")
                break
            delay = initial_delay * (backoff_factor ** attempt)
            logger.warning(f"Transient error {type(exc).__name__}: {exc}. Retrying in {delay}s (attempt {attempt + 1}/{max_retries})...")
            await asyncio.sleep(delay)
        except Exception as exc:
            # Non-retryable error
            raise exc

    if isinstance(last_exception, (CourierTimeoutError, httpx.TimeoutException)):
        raise CourierTimeoutError(f"Courier operation timed out after {max_retries} retries")
    raise CourierGenericError(f"Courier operation failed after {max_retries} retries: {last_exception}")
```

### 7.2 Self-Healing Authentication Wrapper
For couriers requiring Bearer tokens (e.g. UrbaneBolt), tokens can expire. The adapter encapsulates authentication lifecycle management:
```python
async def _execute_with_auth(self, request_fn: Callable[[str], Coroutine[Any, Any, httpx.Response]]) -> httpx.Response:
    if not self._token:
        await self.authenticate()
    
    response = await request_fn(self._token)
    if response.status_code == 401:
        logger.warning(f"{self.partner_name}: Token expired (401). Refreshing token and retrying once...")
        self._token = None
        await self.authenticate()
        response = await request_fn(self._token)
        if response.status_code == 401:
            raise CourierAuthError(f"{self.partner_name} authentication failed: unauthorized credentials")
    return response
```

---

## 8. In-Process Background Bulk Processing Architecture

### 8.1 Constraints & Requirements
- **Max Bulk Size**: 100 orders per batch.
- **Immediate Response**: Return HTTP 202 Accepted (or 200) within milliseconds with `batch_id` and `status="PROCESSING"`.
- **Concurrency**: Up to 100 orders executed concurrently using in-process async coroutines.
- **No External Queues**: Celery, Redis, and RabbitMQ are explicitly disallowed.
- **Bounded Concurrency**: Avoid overwhelming system file handles or SQLite write locks by bounding concurrent worker tasks via `asyncio.Semaphore(10)`.
- **Database Session Isolation**: Each concurrent task opens its own scoped SQLAlchemy `SessionLocal()` to avoid cross-thread session corruption.
- **Partial Failure Resilience**: Individual order failures (e.g. timeout, invalid courier, duplicate ID) are recorded in `batch_results` without aborting other orders in the batch.

### 8.2 Bulk Workflow Sequence

```text
Client                          FastAPI Router                  OrderService                  Background Worker              Database
  │                                   │                              │                                │                         │
  │─── POST /api/v1/orders/bulk ─────>│                              │                                │                         │
  │    (up to 100 orders)             │                              │                                │                         │
  │                                   │─── validate batch size ─────>│                                │                         │
  │                                   │    generate batch_id         │                                │                         │
  │                                   │    insert Batch(PROCESSING)  ├────────────────────────────────────────────────────────>│ (commit)
  │                                   │                              │                                │                         │
  │                                   │─── asyncio.create_task() ───>│── spawn run_bulk_batch() ────>│                         │
  │                                   │                              │                                │                         │
  │<── 202 {"batch_id", "status"} ────│                              │                                │                         │
  │                                                                                                   │                         │
  │                                                                                                   │── asyncio.Semaphore(10) │
  │                                                                                                   │── gather(workers...)    │
  │                                                                                                   │                         │
  │                                                                                                   │── for each order:       │
  │                                                                                                   │     with SessionLocal():│
  │                                                                                                   │       process_order()   │
  │                                                                                                   │       insert Result ───>│
  │                                                                                                   │                         │
  │                                                                                                   │── update Batch:         │
  │                                                                                                   │     status="COMPLETED"  │
  │                                                                                                   │     successful=N        │
  │                                                                                                   │     failed=M ──────────>│
  │                                                                                                   │                         │
  │─── GET /api/v1/orders/bulk/{id} ─>│                              │                                                          │
  │                                   │─── query batch & results ──────────────────────────────────────────────────────────────>│
  │<── 200 {status, total, results} ──│                              │                                                          │
```

### 8.3 Concurrency & Session Implementation
```python
# app/services/order_service.py
import asyncio
from app.db.database import SessionLocal
from app.domain.models import Batch, BatchResult
from app.domain.enums import BatchStatus

async def run_bulk_batch(batch_id: str, orders_data: list[OrderCreateRequest], concurrency_limit: int = 10):
    semaphore = asyncio.Semaphore(concurrency_limit)
    successful_count = 0
    failed_count = 0

    async def process_item(order_data: OrderCreateRequest):
        nonlocal successful_count, failed_count
        async with semaphore:
            # Each worker uses an independent database session
            with SessionLocal() as db:
                repo = OrderRepository(db)
                try:
                    await create_order_core(order_data, repo)
                    repo.record_batch_result(batch_id, order_data.order_id, success=True)
                    successful_count += 1
                except AppError as exc:
                    repo.record_batch_result(batch_id, order_data.order_id, success=False, error_code=exc.code, error_message=exc.message)
                    failed_count += 1
                except Exception as exc:
                    repo.record_batch_result(batch_id, order_data.order_id, success=False, error_code="INTERNAL_ERROR", error_message=str(exc))
                    failed_count += 1

    await asyncio.gather(*(process_item(order) for order in orders_data))

    with SessionLocal() as db:
        repo = OrderRepository(db)
        repo.finalize_batch(batch_id, successful=successful_count, failed=failed_count, status=BatchStatus.COMPLETED)
```

---

## 9. Normalized Order Lifecycle & Tracking History

### 9.1 Status Transitions
The platform normalizes disparate courier-specific statuses into 6 canonical states:

```text
       ┌───────────┐
       │  CREATED  │
       └─────┬─────┘
             │
             ▼
       ┌───────────┐
       │ PICKED_UP │
       └─────┬─────┘
             │
             ▼
       ┌───────────┐
       │IN_TRANSIT │
       └─────┬─────┘
             │
      ┌──────┴──────┐
      │             │
      ▼             ▼
┌───────────┐ ┌───────────┐
│ DELIVERED │ │  FAILED   │
└───────────┘ └───────────┘
```
*Note*: An order can transition to `CANCELLED` from `CREATED` or `PICKED_UP` upon invoking `POST /api/v1/orders/{order_id}/cancel`.

### 9.2 Append-Only Tracking History Rules
1. **Order Creation**: Order is inserted with status `CREATED`; an initial record is inserted into `tracking_history` with `status="CREATED"`, `raw_payload={"event": "ORDER_CREATED"}`.
2. **Live Tracking Request (`GET /api/v1/orders/{order_id}/track`)**:
   - Queries `Order` from database. If not found, raises `OrderNotFoundError`.
   - Obtains courier adapter from `courier_registry.get(order.courier_partner)`.
   - Calls `adapter.track_order(order.awb_number)`.
   - Updates `orders.status` to normalized status.
   - **Appends a new row** to `tracking_history` with the current timestamp, new status, and raw courier tracking response.
   - All historical tracking rows remain untouched and immutable.
3. **Cancellation Request (`POST /api/v1/orders/{order_id}/cancel`)**:
   - Queries `Order` from database.
   - Calls `adapter.cancel_order(order.awb_number)`.
   - Updates `orders.status` to `CANCELLED`.
   - **Appends a new row** to `tracking_history` with `status="CANCELLED"`.

---

## 10. Test Architecture & Verification Matrix

### 10.1 Test Architecture Strategy
The testing suite uses `pytest` with `pytest-asyncio` and `httpx.AsyncClient` utilizing FastAPI ASGI in-memory transport (`ASGITransport`), providing millisecond execution speed without requiring a running web server process.

```python
# tests/conftest.py
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.database import Base, get_db

@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)

@pytest_asyncio.fixture
async def async_client(test_engine):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    def override_get_db():
        with TestingSessionLocal() as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()
```

### 10.2 Test Suite Matrix Mapping to Acceptance Criteria

| Test Suite | Test Case | Target Requirement | Verification Mechanism |
|---|---|---|---|
| `test_orders.py` | Create order (mock courier) | R1, R2 | Assert HTTP 201/200, valid `courier_order_id`, `awb_number`, `status="CREATED"`. |
| `test_orders.py` | Live tracking update | R2 | Call `/track`, assert status update, verify `tracking_history` row appended. |
| `test_orders.py` | Order cancellation | R2 | Call `/cancel`, assert `status="CANCELLED"`, verify cancellation audit row in history. |
| `test_orders.py` | Unsupported courier partner | R1, R5 | Submit order with `courier_partner="unknown"`, assert 400 `UNSUPPORTED_COURIER`. |
| `test_orders.py` | Non-existent order tracking | R5 | Track unknown ID, assert 404 `ORDER_NOT_FOUND`. |
| `test_orders.py` | Request validation failure | R5 | Submit payload missing required fields, assert 400/422 `VALIDATION_ERROR` standard format. |
| `test_idempotency.py` | Duplicate order resubmission | R3 | Submit `order_id="ORD-001"` twice, assert second call returns duplicate error or existing order without duplicate courier call. |
| `test_idempotency.py` | Database unique constraint | R3 | Attempt direct DB insert with duplicate `order_id`, assert `IntegrityError`. |
| `test_retry.py` | Courier timeout with retry | R3 | Configure mock to timeout twice then succeed; assert backoff retry succeeds. |
| `test_retry.py` | Max retries exhausted | R3 | Configure mock timeout continuously; assert backoff retries 2 times, then returns 504 `COURIER_TIMEOUT`. |
| `test_retry.py` | 5xx server error retry | R3 | Configure mock 500 error; assert exponential backoff executes. |
| `test_retry.py` | 401 Auth refresh retry | R3 | Configure mock 401 error; assert token refreshed and single retry succeeds. |
| `test_retry.py` | 4xx Fast failure | R3 | Configure mock 400 error; assert no retries are performed and error returned immediately. |
| `test_bulk.py` | 100 orders bulk creation | R4 | Submit 100 orders via `POST /orders/bulk`, assert 202 `batch_id`, poll until `COMPLETED`, assert 100 success. |
| `test_bulk.py` | Mixed multi-courier bulk | R4 | Submit batch with mix of `mock` and `urbanebolt` orders. |
| `test_bulk.py` | Partial failure isolation | R4 | Submit 10 orders where 2 have simulated timeouts and 1 duplicate ID; assert batch completes with `successful=7`, `failed=3`, and detailed item error codes. |
| `test_urbanebolt.py` | UrbaneBolt payload conversion | R1 | Test conversion of `OrderCreateRequest` to UrbaneBolt manifest payload structure. |
| `test_urbanebolt.py` | UrbaneBolt response parsing | R1 | Test parsing of tracking and cancellation responses using mock HTTP responses. |

---

## 11. Configuration & Secret Management

Configuration is handled via Pydantic `BaseSettings`, strictly loading values from environment variables and `.env` files without hardcoding credentials:

```python
# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App
    APP_NAME: str = "Courier Integration Platform"
    DEBUG: bool = False
    
    # Database
    DATABASE_URL: str = "sqlite:///./app.db"
    
    # UrbaneBolt Credentials
    URBANEBOLT_BASE_URL: str = "https://uat.urbanebolt.in"
    URBANEBOLT_API_KEY: str = ""
    URBANEBOLT_USERNAME: str = ""
    URBANEBOLT_PASSWORD: str = ""
    URBANEBOLT_CUSTOMER_CODE: str = "UEBCUS0008"
    
    # Shipper Defaults for Manifest
    SHIPPER_NAME: str = "Central Warehouse"
    SHIPPER_MOBILE: int = 9999999999
    SHIPPER_EMAIL: str = "warehouse@example.com"
    SHIPPER_ADDRESS: str = "Industrial Area Phase 1"
    SHIPPER_CITY: str = "Gurgaon"
    SHIPPER_STATE: str = "HARYANA"
    SHIPPER_PINCODE: int = 122001
    
    # Resiliency
    REQUEST_TIMEOUT: float = 10.0
    MAX_RETRIES: int = 2
    RETRY_DELAY: float = 1.0
    
    # Bulk Concurrency
    BULK_CONCURRENCY_LIMIT: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
```

---

## 12. Logging & Audit Architecture

Every courier operation must emit a structured log record containing contextual fields while strictly redacting sensitive customer data, passwords, API keys, and bearer tokens:

```python
# Required Log Context Format
{
  "timestamp": "2026-09-28T14:45:00.123Z",
  "request_id": "req-1234-abcd",
  "order_id": "ORD-001",
  "courier_partner": "urbanebolt",
  "operation": "CREATE_ORDER",
  "status": "SUCCESS",
  "duration_ms": 234.5,
  "error_type": null
}
```

---

## 13. Step-by-Step Implementation Roadmap

Aligned with the 18-step implementation order in `task.md` (lines 838-857):

1. **Phase 1: Foundation & Infrastructure**
   - Step 1: Create `requirements.txt` and `.env.example`.
   - Step 2: Implement `app/config.py` with Pydantic settings.
   - Step 3: Implement `app/domain/enums.py` and `app/domain/models.py`.
   - Step 4: Implement `app/db/database.py` (engine, SQLite WAL listener, `init_db`, `get_db`) and `app/db/repositories.py`.

2. **Phase 2: Courier Abstraction Layer**
   - Step 5: Implement `app/couriers/base.py` (`CourierAdapter` ABC and DTOs).
   - Step 6: Implement `app/couriers/registry.py` (`CourierRegistry`).
   - Step 7: Implement `app/couriers/mock.py` (`MockCourierAdapter` with failure simulation modes).

3. **Phase 3: Core Order Lifecycle & Error Handling**
   - Step 8: Implement `app/utils/errors.py` (custom exception hierarchy & standard error response handlers) and `app/utils/retry.py` (exponential backoff).
   - Step 9: Implement `app/api/schemas.py` (Pydantic v2 schemas).
   - Step 10: Implement `app/services/order_service.py` (order creation, idempotency enforcement, live tracking, cancellation).
   - Step 11: Implement `app/api/routes_orders.py` and `app/main.py`.

4. **Phase 4: Background Bulk Processing**
   - Step 12: Implement `POST /api/v1/orders/bulk` and `GET /api/v1/orders/bulk/{batch_id}` with `asyncio.Semaphore` bounded concurrency and database session isolation.

5. **Phase 5: Real Courier Integration**
   - Step 13: Implement `app/couriers/urbanebolt.py` (token caching, auto-refresh on 401, manifest mapping, tracking, cancellation).

6. **Phase 6: Testing & Quality Assurance**
   - Step 14: Build complete test suite across `tests/conftest.py`, `tests/test_orders.py`, `tests/test_mock_courier.py`, `tests/test_idempotency.py`, `tests/test_retry.py`, `tests/test_bulk.py`, and `tests/test_urbanebolt.py`.
   - Step 15: Run `pytest` and verify 100% pass rate with zero warnings.

7. **Phase 7: Documentation**
   - Step 16: Author comprehensive `README.md` and `DESIGN.md`.

---
