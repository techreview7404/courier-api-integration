# Scope: E2E Testing Track

## Architecture & Test Philosophy
- Requirement-driven, opaque-box testing based strictly on `ORIGINAL_REQUEST.md` and `task.md`.
- Tests exercise the service via FastAPI `TestClient` (or `httpx.AsyncClient`) invoking endpoints without depending on internal implementation details.
- Couriers are exercised via `MockCourierAdapter` or simulated responses, ensuring 100% offline, deterministic execution.

## Coverage Goals & Tiers
1. **Tier 1: Feature Coverage (>=5 per feature)**
   - Order creation (`POST /api/v1/orders`)
   - Order tracking (`GET /api/v1/orders/{order_id}/track`)
   - Order cancellation (`POST /api/v1/orders/{order_id}/cancel`)
   - Bulk submission (`POST /api/v1/orders/bulk`)
   - Bulk status polling (`GET /api/v1/orders/bulk/{batch_id}`)
   - Idempotency & unique order ID
   - Standardized error envelope structure

2. **Tier 2: Boundary & Corner Cases (>=5 per feature)**
   - Bulk submission with 0 orders (422)
   - Bulk submission with 101 orders (422)
   - Missing required fields (customer name, phone, address, empty items list)
   - Zero or negative quantity / price
   - Duplicate order ID submitted concurrently or sequentially
   - Non-existent order tracking (404 ORDER_NOT_FOUND)
   - Non-existent order cancellation (404 ORDER_NOT_FOUND)
   - Non-existent bulk batch polling (404)
   - Unregistered courier partner (400 UNSUPPORTED_COURIER)

3. **Tier 3: Cross-Feature Combinations**
   - Bulk submission mixing multiple couriers (mock and urbanebolt)
   - Bulk batch with partial failures (some succeed, some fail, batch status COMPLETED with total/successful/failed counts)
   - Tracking an order before and after cancellation
   - Tracking history audit immutability: multiple track calls append successive records without mutating prior ones
   - Re-submitting duplicate order does not call courier or mutate history

4. **Tier 4: Real-World Application Workloads**
   - Scenario 1: End-to-end e-commerce shipment lifecycle (order created -> tracking updates -> delivered)
   - Scenario 2: High-volume bulk dispatch (100 orders processed in background with polling until COMPLETED)
   - Scenario 3: Mixed batch with transient failures and retry recovery
   - Scenario 4: Order cancellation and subsequent tracking verification
   - Scenario 5: Multi-tenant / heterogeneous courier dispatch

## Deliverables
- `tests/e2e/test_tier1_features.py`
- `tests/e2e/test_tier2_boundaries.py`
- `tests/e2e/test_tier3_combinations.py`
- `tests/e2e/test_tier4_scenarios.py`
- `TEST_INFRA.md` at project root
- `TEST_READY.md` at project root signaling test readiness
