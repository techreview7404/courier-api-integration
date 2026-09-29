## 2026-09-28T14:52:18Z
You are the Implementation Worker for Milestone 1: Core Foundation & Database of the Courier Integration Platform.

Working Directory: ./.agents/teamwork/worker_m1_core
Project Root: .
Parent Conversation ID: 53fe967f-356a-4dc8-a2a1-308ee9c4c592

MANDATORY INPUTS TO READ FIRST:
1. ./.agents/teamwork/ORIGINAL_REQUEST.md
2. ./task.md
3. ./PROJECT.md
4. ./.agents/teamwork/sub_orch_m1_core/SCOPE.md
5. ./.agents/teamwork/explorer_arch/analysis.md
6. ./.agents/teamwork/spec_miner_task/analysis.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

EXCLUSIVE FILE WRITE OWNERSHIP:
You own and must implement the following files exclusively:
- requirements.txt
- app/__init__.py
- app/config.py (Pydantic Settings: DATABASE_URL, MAX_RETRIES, RETRY_DELAY, REQUEST_TIMEOUT, URBANBOLT_*, etc.)
- app/database.py (SQLite engine with WAL mode: PRAGMA journal_mode=WAL; PRAGMA busy_timeout=30000; check_same_thread=False, Base declarative, SessionLocal, get_db)
- app/models/__init__.py, app/models/order.py (Order table with unique order_id, TrackingHistory append-only table), app/models/batch.py (Batch, BatchResult tables)
- app/schemas/__init__.py, app/schemas/common.py (ErrorResponse envelope), app/schemas/order.py, app/schemas/tracking.py, app/schemas/bulk.py
- app/exceptions.py (AppError hierarchy: ValidationError, EntityNotFoundError, DuplicateEntityError, UnsupportedCourierError, CourierError, CourierTimeoutError, CourierAuthError)
- app/middleware/__init__.py, app/middleware/errors.py (Global exception handlers transforming all exceptions into standard envelope { "error": { "code", "message", "request_id", "details" } })
- app/main.py (FastAPI app factory with CORS, exception handlers registered, database table creation on startup, health endpoint GET /health and GET /api/v1/health)
- tests/conftest.py (fixtures: test db session, test client)
- tests/unit/__init__.py, tests/unit/test_models.py, tests/unit/test_schemas.py, tests/unit/test_errors.py

VERIFICATION REQUIREMENTS:
1. Run pytest tests/unit using run_command to verify 100% passing tests.
2. Verify SQLite WAL mode and table constraints.
3. Document executed commands, results, and test outputs in your handoff.md.
4. Update progress.md in your working directory.
5. Send completion message to parent when done.
