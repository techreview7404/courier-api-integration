# Courier Integration Platform — Local Development Task

## Goal

Build a small backend service for an e-commerce logistics platform.

The API consumer should use **one unified API** regardless of which courier is used.

Start with:

* `urbanebolt` — real courier adapter
* `mock` — simple fake courier adapter for testing

The architecture must make adding another courier easy without changing existing business logic.

---

# 1. Tech Stack

Use:

* Python 3.12+
* FastAPI
* SQLAlchemy
* SQLite for local development
* Pydantic
* httpx
* pytest

Keep dependencies minimal.

Do NOT introduce Redis, Kafka, Celery, Docker, Kubernetes, or external queues unless absolutely necessary.

Use an in-process background task/thread mechanism for bulk processing.

---

# 2. Project Structure

Use a simple layered structure:

```text
app/
├── main.py
├── config.py
│
├── api/
│   ├── routes_orders.py
│   └── schemas.py
│
├── domain/
│   ├── models.py
│   └── enums.py
│
├── services/
│   └── order_service.py
│
├── couriers/
│   ├── base.py
│   ├── registry.py
│   ├── urbanebolt.py
│   └── mock.py
│
├── db/
│   ├── database.py
│   └── repositories.py
│
└── utils/
    ├── errors.py
    └── retry.py

tests/
├── test_orders.py
├── test_bulk.py
├── test_mock_courier.py
└── test_idempotency.py

README.md
DESIGN.md
requirements.txt
.env.example
```

Keep the structure flexible if a simpler structure is more appropriate.

---

# 3. Core Architecture

Use the **Adapter Pattern**.

Create a common courier interface.

Example:

```python
class CourierAdapter(ABC):

    def authenticate(self):
        ...

    def create_order(self, order):
        ...

    def track_order(self, tracking_id):
        ...

    def cancel_order(self, tracking_id):
        ...
```

Each courier implements this interface.

Example:

```text
CourierAdapter
      │
      ├── UrbaneboltAdapter
      │
      └── MockCourierAdapter
```

The order service must depend on `CourierAdapter`, not on a specific courier.

---

# 4. Courier Registry

Create a registry/factory:

```text
"urbanebolt" → UrbaneboltAdapter
"mock"       → MockCourierAdapter
```

Business logic should do:

```python
courier = courier_registry.get(order.courier_partner)
```

Do NOT use large `if/elif` blocks throughout the application.

Adding a courier should require:

1. Create adapter
2. Register adapter
3. Add configuration if required

Do not modify controllers or existing courier adapters.

---

# 5. Normalized Order API

Create:

```http
POST /api/v1/orders
```

Request:

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

The API schema must be courier-independent.

Do not expose UrbaneBolt-specific fields in the public API.

---

# 6. Create Order Flow

Implement:

```text
Request
  ↓
Validate request
  ↓
Check order_id for existing order
  ↓
Get courier adapter
  ↓
Authenticate if required
  ↓
Convert internal order → courier payload
  ↓
Call courier
  ↓
Normalize courier response
  ↓
Persist order
  ↓
Return unified response
```

Response example:

```json
{
  "order_id": "ORD-001",
  "courier_partner": "mock",
  "courier_order_id": "MOCK-123",
  "awb_number": "AWB-123",
  "status": "CREATED"
}
```

---

# 7. Tracking

Implement:

```http
GET /api/v1/orders/{order_id}/track
```

The service should:

1. Find internal order
2. Find courier adapter
3. Call courier tracking API
4. Normalize status
5. Store status history
6. Update current order status
7. Return normalized response

Supported statuses:

```text
CREATED
PICKED_UP
IN_TRANSIT
DELIVERED
CANCELLED
FAILED
```

---

# 8. Tracking History

Create a separate table:

```text
tracking_history
----------------
id
order_id
status
raw_payload
created_at
```

Every tracking update creates a new record.

Never overwrite previous tracking history.

Example:

```text
CREATED
   ↓
PICKED_UP
   ↓
IN_TRANSIT
   ↓
DELIVERED
```

All four events must remain in the database.

---

# 9. Cancel Order

Implement:

```http
POST /api/v1/orders/{order_id}/cancel
```

Flow:

```text
Find order
   ↓
Get courier adapter
   ↓
Call courier cancel API
   ↓
Normalize response
   ↓
Update order status
   ↓
Add tracking history
```

Return:

```json
{
  "order_id": "ORD-001",
  "status": "CANCELLED"
}
```

---

# 10. Bulk Orders

Implement:

```http
POST /api/v1/orders/bulk
```

Maximum:

```text
100 orders
```

Each order can use a different courier.

Example:

```json
{
  "orders": [
    {
      "order_id": "ORD-001",
      "courier_partner": "mock"
    },
    {
      "order_id": "ORD-002",
      "courier_partner": "urbanebolt"
    }
  ]
}
```

Do NOT process 100 orders sequentially.

Use background processing/concurrent execution.

For the local version:

```text
POST /bulk
      ↓
Validate
      ↓
Create batch_id
      ↓
Start background processing
      ↓
Return batch_id
```

Example response:

```json
{
  "batch_id": "BATCH-001",
  "status": "PROCESSING"
}
```

Provide an endpoint to retrieve batch results:

```http
GET /api/v1/orders/bulk/{batch_id}
```

Example:

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

# 11. Idempotency

`order_id` must be unique.

If:

```text
ORD-001
```

is submitted twice, the system must NOT create two shipments.

Return the existing order/result or an appropriate conflict response.

Add a database unique constraint.

---

# 12. Error Handling

Create one common error format:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request",
    "request_id": "req-123",
    "details": {}
  }
}
```

Implement at least:

```text
VALIDATION_ERROR
UNSUPPORTED_COURIER
ORDER_NOT_FOUND
DUPLICATE_ORDER
COURIER_ERROR
COURIER_TIMEOUT
COURIER_AUTH_ERROR
INTERNAL_ERROR
```

Never expose raw courier errors directly to API consumers.

---

# 13. Retry

For temporary courier failures:

```text
Timeout / 5xx
     ↓
Retry
     ↓
Retry
     ↓
Final failure
```

Use configurable:

```text
MAX_RETRIES
RETRY_DELAY
REQUEST_TIMEOUT
```

Use exponential backoff.

Example:

```text
1 second
2 seconds
4 seconds
```

Do not retry normal validation or business errors.

---

# 14. Authentication

Courier authentication must be hidden inside the courier adapter.

The application should simply call:

```python
adapter.create_order(order)
```

The adapter handles authentication internally.

For authentication failure:

```text
Request
  ↓
Auth failure
  ↓
Re-authenticate
  ↓
Retry once
  ↓
Success / failure
```

Credentials must come from environment variables.

Never hardcode credentials.

---

# 15. UrbaneBolt Adapter

Implement the real UrbaneBolt integration using the provided UAT documentation:

```text
https://bit.ly/ease-commerce-assignment
```

Implement at minimum:

```text
Authentication
Create order/shipment
Track shipment
Cancel order
```

Keep all UrbaneBolt-specific request/response mapping inside:

```text
couriers/urbanebolt.py
```

Do not allow UrbaneBolt payloads to leak into the domain/API layer.

---

# 16. Mock Courier

Implement a simple `MockCourierAdapter`.

It should support:

```text
authenticate()
create_order()
track_order()
cancel_order()
```

Generate fake:

```text
courier_order_id
awb_number
status
```

Allow it to simulate:

```text
success
timeout
4xx error
5xx error
authentication failure
```

This adapter will make local testing possible without depending on UrbaneBolt.

---

# 17. Database

Use SQLite.

Create at minimum:

### orders

```text
id
order_id UNIQUE
courier_partner
courier_order_id
awb_number
status
request_payload
response_payload
created_at
updated_at
```

### tracking_history

```text
id
order_id
status
raw_payload
created_at
```

### batches

```text
id
batch_id UNIQUE
status
total
successful
failed
created_at
updated_at
```

### batch_results

```text
id
batch_id
order_id
success
error_code
error_message
created_at
```

Store raw courier request/response as JSON.

---

# 18. Configuration

Create `.env.example`.

Example:

```text
DATABASE_URL=sqlite:///./app.db

URBANEBOLT_BASE_URL=
URBANEBOLT_API_KEY=
URBANEBOLT_USERNAME=
URBANEBOLT_PASSWORD=

REQUEST_TIMEOUT=10
MAX_RETRIES=2
RETRY_DELAY=1
```

Use configuration classes.

Never hardcode secrets.

---

# 19. Logging

Every courier operation should log:

```text
request_id
order_id
courier_partner
operation
success/failure
error type
```

Do not log passwords, API keys, tokens, or sensitive customer information.

---

# 20. Tests

Write tests for:

### API

```text
Create order
Track order
Cancel order
Bulk orders
Unknown courier
Invalid request
Order not found
```

### Architecture

Test that:

```text
Mock courier works
Urbanebolt adapter can be selected
Courier registry works
```

### Reliability

Test:

```text
Duplicate order
Courier timeout
Courier 5xx
Authentication failure
Retry behavior
Partial bulk failure
```

### Bulk

Test:

```text
100 orders
Multiple couriers
Partial success
Background processing
```

---

# 21. Documentation

Create `README.md` containing:

```text
Project overview
Architecture
Prerequisites
Installation
Environment variables
Database setup
Running locally
Running tests
API examples
Adding a new courier
```

Create `DESIGN.md` containing:

```text
Architecture
Adapter pattern
Courier registry
Request flow
Database design
Bulk processing approach
Retry strategy
Idempotency
Error handling
Trade-offs
How a new courier is added
```

---

# 22. Definition of Done

The project is complete when:

* [ ] FastAPI application runs locally
* [ ] SQLite database works
* [ ] Unified order API works
* [ ] Mock courier works end-to-end
* [ ] UrbaneBolt adapter is implemented
* [ ] Tracking works
* [ ] Cancellation works
* [ ] Tracking history is persisted
* [ ] Bulk endpoint supports up to 100 orders
* [ ] Bulk processing is concurrent/background
* [ ] Partial failures are supported
* [ ] `order_id` is idempotent
* [ ] Retry with exponential backoff works
* [ ] Authentication retry works
* [ ] Normalized errors are implemented
* [ ] Configuration uses environment variables
* [ ] Logging is implemented
* [ ] Unit/integration tests pass
* [ ] README.md is complete
* [ ] DESIGN.md is complete
* [ ] curl/Postman examples are provided
* [ ] Mock courier demonstrates plug-in architecture

---

# Development Rules

1. Keep the implementation simple.
2. Prefer standard library/FastAPI features over additional infrastructure.
3. Keep courier-specific code isolated.
4. Keep business logic independent of courier implementations.
5. Use small, reusable functions.
6. Avoid duplicated logic.
7. Keep domain models independent of external courier schemas.
8. Validate at API boundaries.
9. Never hardcode secrets.
10. Write tests while implementing features.
11. Do not implement unnecessary features.
12. Prioritize correctness and clean architecture over UI or infrastructure.

## Implementation Order

Implement in this order:

```text
1. Project setup
2. Configuration
3. Database
4. Domain models
5. Courier interface
6. Courier registry
7. Mock courier
8. Create-order API
9. Tracking
10. Cancellation
11. Idempotency
12. Error handling
13. Retry mechanism
14. Bulk processing
15. UrbaneBolt integration
16. Tests
17. README
18. DESIGN.md
```

After each major step, run the tests and fix failures before continuing.

Do not implement everything in one large change.
