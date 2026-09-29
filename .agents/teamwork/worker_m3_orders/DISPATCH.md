## 2026-09-28T15:22:04Z
You are the Implementation Worker for Milestone 3: Order Lifecycle & Tracking History of the Courier Integration Platform.

Working Directory: ./.agents/teamwork/worker_m3_orders
Project Root: .
Parent Conversation ID: 53fe967f-356a-4dc8-a2a1-308ee9c4c592

MANDATORY INPUTS TO READ FIRST:
1. ./.agents/teamwork/ORIGINAL_REQUEST.md
2. ./task.md
3. ./PROJECT.md
4. ./.agents/teamwork/orchestrator/handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

EXCLUSIVE FILE WRITE OWNERSHIP:
You own and must implement the following files exclusively:
- app/services/__init__.py (exports OrderService)
- app/services/order_service.py (OrderService with create_order, track_order, cancel_order; enforces idempotency, invokes courier_registry.get(courier_partner), appends to immutable tracking_history on every status change)
- app/api/__init__.py, app/api/v1/__init__.py, app/api/v1/router.py, app/api/v1/endpoints/__init__.py, app/api/v1/endpoints/orders.py (POST /api/v1/orders, GET /api/v1/orders/{order_id}/track, POST /api/v1/orders/{order_id}/cancel)
- app/main.py (mount app.include_router(api_v1_router, prefix="/api/v1"))
- tests/unit/test_order_service.py (service-level unit tests)
- tests/test_orders.py (MANDATORY top-level test file required by task.md §2, §20 testing POST /orders, GET /orders/{order_id}/track, POST /orders/{order_id}/cancel, and tracking history immutability)
- tests/test_idempotency.py (MANDATORY top-level test file required by task.md §2, §20 testing duplicate order_id submission, UNIQUE constraint, consistent response or 409 conflict, and zero duplicate courier calls)

VERIFICATION REQUIREMENTS:
1. Run pytest `python3 -m pytest tests/unit/test_order_service.py tests/test_orders.py tests/test_idempotency.py -v --cov=app/services/order_service.py --cov=app/api/v1/endpoints/orders.py` to verify 100% passing tests and high coverage.
2. Run `python3 -m ruff check app/ tests/` to verify zero lint errors.
3. Verify existing tests still pass: `python3 -m pytest tests/unit tests/test_mock_courier.py tests/integration/ -v`.
4. Document executed commands, results, and outputs in your handoff.md.
5. Update progress.md in your working directory.
6. Send completion message to parent when done.
