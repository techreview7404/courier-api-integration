# Project: Courier Integration Platform

## Architecture
Decoupled, layered FastAPI architecture with an Adapter Pattern for multi-courier logistics integration:

```
[ Client / Public API ]
         │ (HTTP REST, JSON)
         ▼
[ API Routing & Controllers ] (app/api/v1/endpoints/orders.py, bulk.py)
         │ (Normalized Pydantic Schemas, Global Error Envelope)
         ▼
[ Service Layer ] (OrderService, BulkService)
    ├── Idempotency Check & Tracking Audit Log
    └── Background In-Process Concurrency (asyncio.create_task + Semaphore)
         │
         ├── [ Data Access Layer ] (SQLAlchemy 2.0 ORM + SQLite WAL)
         │     ├── orders (UNIQUE order_id)
         │     ├── tracking_history (Immutable Append-Only Audit)
         │     ├── batches
         │     └── batch_results
         │
         └── [ Courier Abstraction Layer ]
               ├── CourierRegistry (Dynamic dispatch, zero if/elif)
               ├── CourierAdapter (ABC: authenticate, create_order, track_order, cancel_order)
               ├── Resiliency Layer (Exponential backoff retry, 401 token refresh)
               ├── MockCourierAdapter (Offline deterministic simulations: success, timeout, 5xx, 4xx, auth failure)
               └── UrbaneboltAdapter (Live UAT endpoints: getToken, manifest, tracking-pub, cancel)
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Configuration & Environment | Pydantic Settings loading configs, timeouts, retry parameters, courier credentials | M1 | task.md §18 |
| 2 | SQLite Engine & WAL Setup | SQLite setup with `PRAGMA journal_mode=WAL` and `busy_timeout=30000` | M1 | explorer_arch |
| 3 | Core SQLAlchemy Models | `orders`, `tracking_history`, `batches`, `batch_results` models & table creation | M1 | task.md §17 |
| 4 | Standardized Error Envelope | Unified `{ "error": { "code", "message", "request_id", "details" } }` schema & exception hierarchy | M1 | task.md §12 |
| 5 | Request Validation & Pydantic Schemas | Strong typing for Order, Customer, Item, Tracking, and Bulk payloads | M1 | task.md §5, §10 |
| 6 | CourierAdapter ABC & DTOs | Interface contract defining `authenticate`, `create_order`, `track_order`, `cancel_order` | M2 | task.md §3 |
| 7 | Dynamic CourierRegistry | Extensible registry resolving couriers by partner string without `if/elif` branching | M2 | task.md §4 |
| 8 | Resilient Network Client | HTTP client with configurable exponential backoff retry and 401 token refresh | M2 | task.md §13, §14 |
| 9 | MockCourierAdapter | Offline mock supporting success, timeout, 4xx, 5xx, and auth failure simulation modes | M2 | task.md §16 |
| 10 | UrbaneboltAdapter | Live UAT adapter for UrbaneBolt (getToken, manifest, tracking-pub, cancel) | M2 | task.md §15, urbanebolt_doc.json |
| 11 | Order Creation (`POST /api/v1/orders`) | Normalized order creation across couriers with idempotency check | M3 | task.md §5, §6 |
| 12 | Database Idempotency | UNIQUE constraint on `order_id` preventing duplicate shipments/calls | M3 | task.md §11 |
| 13 | Order Tracking (`GET /api/v1/orders/{order_id}/track`) | Real-time tracking from courier, updates status, appends to tracking_history | M3 | task.md §7, §8 |
| 14 | Immutable Tracking Audit History | Append-only audit trail preserving all tracking events without mutation | M3 | task.md §8, §17 |
| 15 | Order Cancellation (`POST /api/v1/orders/{order_id}/cancel`) | Order cancellation with courier and audit logging | M3 | task.md §9 |
| 16 | Bulk Order Submission (`POST /api/v1/orders/bulk`) | Up to 100 orders concurrent submission, returns batch_id (HTTP 202) | M4 | task.md §10 |
| 17 | In-Process Concurrent Background Worker | `asyncio.create_task` with `asyncio.Semaphore(10)` executing batch orders | M4 | task.md §1, §10 |
| 18 | Bulk Batch Polling (`GET /api/v1/orders/bulk/{batch_id}`) | Polling batch progress, summary counts, and item-level results/partial failures | M4 | task.md §10 |
| 19 | Structured Logging & Redaction | Request-scoped logging with sanitized payloads (no PII or credentials) | M5 | task.md §19 |
| 20 | Developer Documentation | Comprehensive `README.md` and `DESIGN.md` | M5 | task.md §21 |
| 21 | Full E2E Test Suite (Tiers 1-4) | Opaque-box test suite covering feature, boundary, pairwise, and application workloads | E2E Track / M6 | task.md §20 |
| 22 | Adversarial Hardening (Tier 5) | White-box stress-testing, failure injection, and coverage hardening | M6 Phase 2 | Project Pattern |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core Foundation & Database | Config, DB engine (WAL mode), SQLAlchemy models, Pydantic schemas, Error envelope middleware | none | DONE |
| M2 | Courier Abstraction & Adapters | CourierAdapter ABC, CourierRegistry, Resilient Client (retry/auth refresh), Mock & UrbaneBolt adapters | M1 | DONE |
| M3 | Order Lifecycle & Tracking History | OrderService, POST /orders (idempotent), GET /track (immutable audit), POST /cancel | M1, M2 | IN_PROGRESS |
| M4 | In-Process Bulk Order Processing | BulkService, in-process async concurrency worker (Semaphore), POST /bulk, GET /bulk/{batch_id} | M1, M2, M3 | PLANNED |
| M5 | Documentation & System Polish | README.md, DESIGN.md, .env.example, structured logging | M1, M2, M3, M4 | PLANNED |
| M6 | Final Milestone: 100% E2E Pass & Hardening | Phase 1: Pass 100% E2E tests (Tiers 1-4). Phase 2: Adversarial coverage hardening (Tier 5) | M1-M5, TEST_READY.md | PLANNED |

## Parallel Track: E2E Testing
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | Requirement-Driven Opaque-Box Test Suite | Test harness, Tiers 1-4 test cases (≥5 per feature, boundary, pairwise, real-world), TEST_READY.md | none (runs parallel) | IN_PROGRESS |

## Interface Contracts
### API ↔ Service Layer
- `OrderService.create_order(db: Session, order_in: OrderCreateRequest) -> OrderResponse`
- `OrderService.track_order(db: Session, order_id: str) -> OrderTrackingResponse`
- `OrderService.cancel_order(db: Session, order_id: str) -> OrderCancelResponse`
- `BulkService.submit_bulk(db: Session, bulk_in: BulkOrderRequest) -> BulkSubmitResponse`
- `BulkService.get_batch_status(db: Session, batch_id: str) -> BulkStatusResponse`

### Service Layer ↔ Courier Abstraction
- `CourierAdapter.create_order(payload: NormalizedOrderPayload) -> NormalizedCreateResponse`
- `CourierAdapter.track_order(awb: str) -> NormalizedTrackingResponse`
- `CourierAdapter.cancel_order(awb: str) -> NormalizedCancelResponse`
- `CourierRegistry.register(name: str, adapter: CourierAdapter)`
- `CourierRegistry.get(name: str) -> CourierAdapter` (raises `UnsupportedCourierError` if missing)

### Database Layer
- `orders`: `id`, `order_id` (UNIQUE), `courier_partner`, `courier_order_id`, `awb_number`, `status`, `request_payload`, `response_payload`, `created_at`, `updated_at`
- `tracking_history`: `id`, `order_id` (FK -> orders.order_id), `status`, `raw_payload`, `created_at` (APPEND-ONLY)
- `batches`: `id`, `batch_id` (UNIQUE), `status`, `total`, `successful`, `failed`, `created_at`, `updated_at`
- `batch_results`: `id`, `batch_id`, `order_id`, `success`, `error_code`, `error_message`, `created_at`

## Code Layout
```
courier-api-integration/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application factory & lifespan
│   ├── config.py                   # Pydantic Settings
│   ├── database.py                 # SQLite engine (WAL mode) & SessionLocal
│   ├── models/
│   │   ├── __init__.py
│   │   ├── order.py                # Order and TrackingHistory SQLAlchemy models
│   │   └── batch.py                # Batch and BatchResult SQLAlchemy models
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py               # Error envelope, base schemas
│   │   ├── order.py                # Order request/response Pydantic models
│   │   ├── tracking.py             # Tracking schemas & status enums
│   │   └── bulk.py                 # Bulk request/response schemas
│   ├── exceptions.py               # Custom domain exceptions (AppError hierarchy)
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── errors.py               # Global exception handlers & error envelope
│   ├── couriers/
│   │   ├── __init__.py
│   │   ├── base.py                 # CourierAdapter ABC & DTOs
│   │   ├── registry.py             # Dynamic CourierRegistry
│   │   ├── client.py               # Resilient HTTP client (exponential backoff & 401 refresh)
│   │   ├── mock.py                 # MockCourierAdapter with simulation modes
│   │   └── urbanebolt.py           # UrbaneboltAdapter for UAT endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   ├── order_service.py        # Order creation, tracking, cancellation, idempotency
│   │   └── bulk_service.py         # In-process concurrent bulk execution
│   └── api/
│       ├── __init__.py
│       └── v1/
│           ├── __init__.py
│           ├── router.py           # API v1 router aggregator
│           └── endpoints/
│               ├── __init__.py
│               ├── orders.py       # POST /orders, GET /orders/{id}/track, POST /orders/{id}/cancel
│               └── bulk.py         # POST /orders/bulk, GET /orders/bulk/{batch_id}
├── tests/
│   ├── conftest.py                 # Pytest fixtures (test client, in-memory/temp DB, mock couriers)
│   ├── unit/                       # Unit tests for adapters, registry, models, schemas
│   ├── integration/                # Integration tests for services and endpoints
│   └── e2e/                        # Opaque-box requirement-driven E2E tests (Tiers 1-4, Tier 5)
├── README.md
├── DESIGN.md
├── .env.example
├── requirements.txt
└── PROJECT.md
```
