# Scope: Milestone 1 (Core Foundation, Database & Error Handling)

## Objective
Establish the foundational infrastructure of the Courier Integration Platform backend service:
1. `requirements.txt`: Python package dependencies (fastapi, uvicorn, sqlalchemy, pydantic, pydantic-settings, httpx, pytest, pytest-asyncio).
2. Configuration (`app/config.py`): Pydantic Settings supporting environment variables and `.env` for database URL, retry settings (MAX_RETRIES=3, RETRY_DELAY=1.0, REQUEST_TIMEOUT=10.0), and courier credentials.
3. Database Setup (`app/database.py`): SQLite engine with WAL mode (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=30000;`), `check_same_thread=False`, Base declarative model, and `get_db` session dependency generator.
4. SQLAlchemy Models:
   - `orders`: `id`, `order_id` (UNIQUE index), `courier_partner`, `courier_order_id`, `awb_number`, `status`, `request_payload` (JSON), `response_payload` (JSON), `created_at`, `updated_at`.
   - `tracking_history`: `id`, `order_id` (FK), `status`, `raw_payload` (JSON), `created_at` (strictly append-only).
   - `batches`: `id`, `batch_id` (UNIQUE index), `status`, `total`, `successful`, `failed`, `created_at`, `updated_at`.
   - `batch_results`: `id`, `batch_id`, `order_id`, `success`, `error_code`, `error_message`, `created_at`.
5. Pydantic Schemas (`app/schemas/`):
   - `common.py`: Error envelope (`{ "error": { "code", "message", "request_id", "details" } }`)
   - `order.py`: `Customer`, `OrderItem`, `OrderCreateRequest`, `OrderResponse`
   - `tracking.py`: `TrackingEvent`, `OrderTrackingResponse`, `OrderStatus` enum
   - `bulk.py`: `BulkOrderRequest`, `BulkSubmitResponse`, `BatchItemResult`, `BulkStatusResponse`
6. Exception Hierarchy (`app/exceptions.py`):
   - Base `AppError` with `code`, `message`, `status_code`, `details`
   - Specific errors: `ValidationError`, `EntityNotFoundError`, `DuplicateEntityError`, `UnsupportedCourierError`, `CourierError`, `CourierTimeoutError`, `CourierAuthError`
7. Error Handling Middleware (`app/middleware/errors.py`):
   - Global exception handlers for `AppError`, `RequestValidationError`, `StarletteHTTPException`, and unhandled `Exception`, guaranteeing every error outputs the exact standardized error envelope with a generated `request_id`.
8. Base FastAPI App Factory (`app/main.py`):
   - App initialization, CORS, global exception handler registration, health check endpoint (`GET /health` and `GET /api/v1/health`), and database table creation on startup.
9. Unit Tests:
   - `tests/conftest.py` with test database session fixture
   - `tests/unit/test_models.py`
   - `tests/unit/test_schemas.py`
   - `tests/unit/test_errors.py`

## Acceptance Criteria
- `pytest tests/unit` passes 100%.
- Database tables initialize cleanly with SQLite WAL mode enabled.
- Error handlers correctly format validation and domain errors into the unified error envelope.
