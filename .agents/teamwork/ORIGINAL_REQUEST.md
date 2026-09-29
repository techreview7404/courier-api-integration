# Original User Request

## 2026-09-28T14:43:08Z

Build a unified Courier Integration Platform backend service in Python (FastAPI, SQLite, SQLAlchemy) providing a single normalized API across different shipping partners (UrbaneBolt and Mock courier), featuring tracking history, background bulk processing, idempotency, resilient retries, and comprehensive testing.

Working directory: .
Integrity mode: development

Reference material:
- Specification: task.md
- UrbaneBolt Postman Collection: urbanebolt_doc.json

## Requirements

### R1. Unified Courier Architecture & Adapter Pattern
Implement a decoupled courier abstraction layer using the Adapter Pattern with a dynamic CourierRegistry. Business logic and endpoints must depend solely on the unified CourierAdapter interface, never on concrete courier classes. Include a MockCourierAdapter supporting simulated outcomes (success, timeout, 4xx, 5xx, auth failure) and a real UrbaneboltAdapter integrating with UrbaneBolt UAT endpoints (auth/getToken, manifest, tracking-pub, cancel).

### R2. Normalized Order Lifecycle & Tracking History
Expose normalized REST endpoints:
- POST /api/v1/orders: Unified order creation returning standardized IDs and tracking details.
- GET /api/v1/orders/{order_id}/track: Fetches live status, updates the order, and appends a new record to an immutable tracking_history table without overwriting prior events.
- POST /api/v1/orders/{order_id}/cancel: Cancels order with the underlying courier and records cancellation in tracking history.

### R3. Idempotency & Resilient Execution
Enforce database-level uniqueness on order_id to prevent duplicate shipments, returning consistent responses or conflict errors on re-submission. Provide exponential backoff retries for transient courier network timeouts and 5xx responses (configurable MAX_RETRIES, RETRY_DELAY, REQUEST_TIMEOUT). Implement seamless token refresh on courier 401 authentication errors with a single retry.

### R4. Background Bulk Order Processing
Provide asynchronous bulk order submission for up to 100 orders via POST /api/v1/orders/bulk, executing orders concurrently using an in-process background task mechanism (no external queues like Celery/Redis). Expose GET /api/v1/orders/bulk/{batch_id} to poll batch progress, summary counts, and item-level results including partial failures.

### R5. Standardized Error Envelope, Testing & Documentation
Normalize all API and courier errors into a unified envelope (error.code, error.message, error.request_id, error.details). Provide a comprehensive pytest suite covering unit, integration, failure/retry, and bulk scenarios. Deliver README.md (setup, running, testing, adding new couriers) and DESIGN.md (architecture, trade-offs, sequence flows).

## Acceptance Criteria

### Automated Verification
- [ ] Test suite executes cleanly via pytest with zero failures covering order creation, tracking, cancellation, idempotency, retry backoff, auth refresh, and bulk processing.
- [ ] MockCourierAdapter validates all simulated failure modes (timeout, 5xx, auth failure) without external dependencies.
- [ ] tracking_history maintains complete chronological event audit without overwriting records across status updates.
- [ ] Bulk endpoint processes 100 orders concurrently in background and records individual order results and partial failures.
- [ ] Duplicate order_id requests trigger idempotent handling without duplicate courier calls.
- [ ] All error responses adhere to the standard { "error": { "code": ... } } schema.
- [ ] Complete README.md and DESIGN.md are generated as specified in task.md.


## Follow-up — 2026-09-28T14:47:07Z

The project prompt draft has been updated with full, exhaustive details from task.md (covering exact SQLite table schemas, error codes, API contracts, mock simulation flags, retry policies, and test requirements). Please ensure the Project Orchestrator and feature squads incorporate all items from prompt_draft.md and task.md.
