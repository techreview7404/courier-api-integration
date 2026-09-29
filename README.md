# Courier Integration Platform

A modular, extensible backend service built with FastAPI, SQLite, and SQLAlchemy providing a **unified normalized shipping API** across multiple logistics and courier partners (including **UrbaneBolt** and **Mock Courier**).

The platform abstracts courier-specific schemas, authentication, and protocols behind a decoupled **Adapter Pattern** with dynamic registry lookup, idempotent order creation, an append-only tracking audit trail, and concurrent in-process background bulk processing.

---

## Architecture Overview

```
                      +-----------------------------+
                      |   Client / API Consumer     |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |   FastAPI REST Endpoints    |
                      |   (/api/v1/orders/*)        |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |   Order & Bulk Services     |
                      |   (Idempotency & History)   |
                      +-------+--------------+------+
                              |              |
              +---------------+              +---------------+
              v                                              v
+-----------------------------+                +-----------------------------+
|    CourierRegistry (O(1))   |                |   SQLite (WAL Mode) DB      |
+--------------+--------------+                |   - orders (unique order_id)|
               |                               |   - tracking_history        |
       +-------+-------+                       |   - batches & batch_results |
       |               |                       +-----------------------------+
       v               v
+-------------+ +-------------+
| Urbanebolt  | | MockCourier |
|   Adapter   | |   Adapter   |
+-------------+ +-------------+
```

### Key Highlights
- **Unified Interface:** Consumers interact with one standard schema regardless of carrier.
- **Zero Business-Logic Coupling:** Courier selection is dynamic via `CourierRegistry`; adding a new courier requires zero changes to route handlers or database models.
- **Resilient HTTP Client:** Automatic exponential backoff retries for transient 5xx errors and network timeouts, plus transparent token refresh on 401 Unauthorized responses.
- **Immutable Tracking Audit Trail:** State transitions are appended to `tracking_history` without mutating prior records.
- **In-Process Bulk Processing:** Asynchronous concurrent execution of batches up to 100 orders using thread pool workers without external queue dependencies (no Celery/Redis).
- **Strict Idempotency:** Re-submitting an existing `order_id` is safely handled without duplicate courier calls.
- **Normalized Error Envelope:** All 4xx and 5xx errors return a uniform `{ "error": { "code", "message", "request_id", "details" } }` structure.

---

## Prerequisites

- **Python:** 3.12 or newer (tested on Python 3.12, 3.13, 3.14)
- **pip** and **virtualenv** / **venv**
- Operating System: macOS, Linux, or Windows

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone git@github.com:techreview7404/courier-api-integration.git
   cd courier-api-integration
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Environment Variables

Copy the sample environment file to configure your local setup:

```bash
cp .env.example .env
```

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///./app.db` | SQLAlchemy database connection URI |
| `MAX_RETRIES` | `3` | Maximum retry attempts for transient courier calls |
| `RETRY_DELAY` | `0.5` | Initial backoff delay in seconds |
| `REQUEST_TIMEOUT` | `10.0` | Courier HTTP request timeout in seconds |
| `BULK_MAX_ORDERS` | `100` | Maximum allowed orders per bulk batch submission |
| `BULK_CONCURRENCY` | `10` | Worker thread concurrency for background bulk processing |
| `URBANEBOLT_BASE_URL` | `https://preprod.urbanebolt.in/api/v1` | UrbaneBolt UAT API base URL |
| `URBANEBOLT_EMAIL` | `info@urbanebolt.com` | UrbaneBolt UAT account email |
| `URBANEBOLT_PASSWORD` | `Urbanebolt@123` | UrbaneBolt UAT account password |
| `LOG_LEVEL` | `INFO` | Application log verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Database Setup

The application uses SQLite with Write-Ahead Logging (`WAL`) mode, foreign key constraint enforcement, and a 30-second busy timeout for safe concurrent operations.

Database tables are automatically created on application startup via the FastAPI lifespan event handler:
```python
# Automatic table creation on startup
Base.metadata.create_all(bind=engine)
```

To explicitly verify database schema creation:
```bash
python3 -c "from app.database import init_db; init_db()"
```

---

## Running Locally

Start the development server with **Uvicorn**:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The interactive OpenAPI documentation will be accessible at:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

---

## Running Tests

Run the complete test suite across unit, integration, and end-to-end scenarios:

```bash
python3 -m pytest tests/
```

To run with verbose output and coverage report:
```bash
python3 -m pytest tests/ -v --cov=app --cov-report=term-missing
```

To run a specific test suite:
```bash
python3 -m pytest tests/test_orders.py
python3 -m pytest tests/test_bulk.py
python3 -m pytest tests/test_mock_courier.py
python3 -m pytest tests/test_idempotency.py
```

---

## API Examples (cURL)

### 1. Create Order (Mock Courier)

```bash
curl -X POST "http://localhost:8000/api/v1/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD-1001",
    "courier_partner": "mock",
    "customer": {
      "name": "Alice Smith",
      "phone": "9876543210",
      "address": "Flat 402, Lotus Apt, Pune, Maharashtra - 411001"
    },
    "items": [
      {
        "name": "Wireless Headphones",
        "quantity": 1,
        "price": 2999.0
      }
    ]
  }'
```

**Response (`201 Created`):**
```json
{
  "order_id": "ORD-1001",
  "courier_partner": "mock",
  "courier_order_id": "MOCK-ORD-1001",
  "awb_number": "AWB-ORD-1001",
  "status": "MANIFESTED",
  "tracking_url": "https://track.mockcourier.local/AWB-ORD-1001",
  "created_at": "2026-09-29T11:40:00Z"
}
```

---

### 2. Track Order & View Append-Only Audit History

```bash
curl -X GET "http://localhost:8000/api/v1/orders/ORD-1001/track"
```

**Response (`200 OK`):**
```json
{
  "order_id": "ORD-1001",
  "courier_partner": "mock",
  "awb_number": "AWB-ORD-1001",
  "status": "CREATED",
  "history": [
    {
      "status": "MANIFESTED",
      "timestamp": "2026-09-29T11:40:00Z",
      "raw_payload": { ... }
    }
  ]
}
```

---

### 3. Cancel Order

```bash
curl -X POST "http://localhost:8000/api/v1/orders/ORD-1001/cancel"
```

**Response (`200 OK`):**
```json
{
  "order_id": "ORD-1001",
  "courier_partner": "mock",
  "status": "CANCELLED",
  "message": "Order ORD-1001 successfully cancelled with courier 'mock'"
}
```

---

### 4. Bulk Order Creation (Up to 100 Orders)

```bash
curl -X POST "http://localhost:8000/api/v1/orders/bulk" \
  -H "Content-Type: application/json" \
  -d '{
    "orders": [
      {
        "order_id": "BULK-001",
        "courier_partner": "mock",
        "customer": {
          "name": "Bob Jones",
          "phone": "9876543211",
          "address": "Suite 12, Sector 18, Noida, UP - 201301"
        },
        "items": [
          { "name": "USB Cable", "quantity": 1, "price": 299.0 }
        ]
      }
    ]
  }'
```

**Response (`202 Accepted`):**
```json
{
  "batch_id": "d8213b2c-c820-410e-a612-32b55f17a942",
  "status": "PROCESSING",
  "total": 1,
  "created_at": "2026-09-29T11:42:00Z"
}
```

---

### 5. Poll Bulk Batch Status

```bash
curl -X GET "http://localhost:8000/api/v1/orders/bulk/d8213b2c-c820-410e-a612-32b55f17a942"
```

**Response (`200 OK`):**
```json
{
  "batch_id": "d8213b2c-c820-410e-a612-32b55f17a942",
  "status": "COMPLETED",
  "total": 1,
  "successful": 1,
  "failed": 0,
  "results": [
    {
      "order_id": "BULK-001",
      "success": true,
      "courier_order_id": "MOCK-BULK-001",
      "awb_number": "AWB-BULK-001",
      "status": "MANIFESTED",
      "error_code": null,
      "error_message": null
    }
  ],
  "created_at": "2026-09-29T11:42:00Z",
  "updated_at": "2026-09-29T11:42:01Z"
}
```

---

## Adding a New Courier

Adding a new shipping partner (e.g. `bluedart`, `delhivery`, `fedex`) requires **zero modifications to existing business logic or routes**:

1. **Create an Adapter Class:**
   Create a new file in `app/couriers/my_courier.py` inheriting from `CourierAdapter`:

   ```python
   from app.couriers.base import (
       CourierAdapter,
       CourierOrderDTO,
       CourierOrderResult,
       CourierTrackingResult,
       CourierCancelResult,
   )

   class MyCourierAdapter(CourierAdapter):
       def __init__(self, api_key: str = "default_key"):
           self.api_key = api_key

       def authenticate(self) -> None:
           # Authenticate or validate API key
           pass

       def create_order(self, order: CourierOrderDTO) -> CourierOrderResult:
           # Map normalized DTO -> courier payload, call upstream, map response
           return CourierOrderResult(
               courier_order_id="MC-" + order.order_id,
               awb_number="AWB-" + order.order_id,
               status="MANIFESTED",
               tracking_url=f"https://track.mycourier.com/{order.order_id}",
               raw_response={"status": "success"},
           )

       def track_order(self, tracking_id: str) -> CourierTrackingResult:
           return CourierTrackingResult(
               status="IN_TRANSIT",
               status_details="Package in transit",
               raw_response={"status": "IN_TRANSIT"},
           )

       def cancel_order(self, tracking_id: str) -> CourierCancelResult:
           return CourierCancelResult(
               success=True,
               message="Order cancelled",
               raw_response={"status": "cancelled"},
           )
   ```

2. **Register the Adapter:**
   Register the instance with `CourierRegistry`:

   ```python
   from app.couriers.registry import courier_registry
   from app.couriers.my_courier import MyCourierAdapter

   courier_registry.register("mycourier", MyCourierAdapter())
   ```

3. **Submit Orders:**
   Clients can immediately pass `"courier_partner": "mycourier"` in `POST /api/v1/orders`. The platform automatically routes requests to your adapter.
