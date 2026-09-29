# E2E Test Suite Infrastructure & Architecture

This document describes the design, tier breakdown, execution model, and traceability matrix of the opaque-box End-to-End (E2E) Test Suite for the **Courier Integration Platform**.

---

## 1. Test Philosophy & Architecture

The E2E test suite adheres to strict **opaque-box, contract-driven verification**:

1. **Opaque-Box Evaluation**: Tests interact exclusively via standard HTTP REST endpoints using FastAPI's `TestClient` (`from fastapi.testclient import TestClient; from app.main import app`). Tests never mutate internal application state directly.
2. **Deterministic & Offline**: Downstream courier interactions run through deterministic adapters (`MockCourierAdapter`), simulating all required conditions (successful creation, tracking state progression, cancellations, network timeouts, 5xx failures, and 401 authentication token refreshes) without external network dependencies.
3. **Strict Contract Verification**: Every test validates compliance with the unified request/response schemas and the standardized error envelope (`{ "error": { "code", "message", "request_id", "details" } }`) specified in `task.md` and `ORIGINAL_REQUEST.md`.
4. **Isolated Test Execution**: Database state is isolated per test function via transactional session rollbacks (`db_session` fixture) or dedicated UUID keys (`_unique_id()`), guaranteeing zero test-order coupling and complete idempotency.

---

## 2. Test Suite Tiers & Coverage Summary

The E2E test suite comprises **79 tests** organized across four distinct tiers:

| Tier | Focus Area | Test File | Test Count | Minimum Spec | Status |
|------|------------|-----------|:----------:|:------------:|:------:|
| **Tier 1** | Feature Coverage | `tests/e2e/test_tier1_features.py` | **36** | $\ge 5$ per feature (7 features) | COMPLETE |
| **Tier 2** | Boundary & Corner Cases | `tests/e2e/test_tier2_boundaries.py` | **31** | $\ge 5$ per feature (6 features) | COMPLETE |
| **Tier 3** | Cross-Feature Combinations | `tests/e2e/test_tier3_combinations.py` | **6** | Cross-cutting combinations | COMPLETE |
| **Tier 4** | Real-World Application Workloads | `tests/e2e/test_tier4_scenarios.py` | **6** | Complex realistic scenarios | COMPLETE |
| **Total** | **All E2E Tiers** | `tests/e2e/` | **79** | — | **READY** |

---

## 3. Detailed Tier Breakdown

### 3.1 Tier 1: Core Feature Coverage (`tests/e2e/test_tier1_features.py`)
Covers the core features with $\ge 5$ tests per feature (36 total):

1. **Create Order (`POST /api/v1/orders`)** (6 tests)
   - `test_create_order_single_item_mock_success`: Single-item order creation returning 201/200, `order_id`, `courier_partner`, `awb_number`, status `CREATED`.
   - `test_create_order_multiple_items_success`: Multi-item orders with diverse quantities and prices.
   - `test_create_order_generates_initial_tracking_record`: Order creation appends initial `CREATED` record to `tracking_history`.
   - `test_create_order_persists_request_and_response_payloads`: Request and response JSON payloads are stored in the `orders` table.
   - `test_create_order_preserves_custom_request_id_header`: Propagation of `X-Request-ID` header.
   - `test_create_order_normalized_schema_no_leaked_fields`: Strict schema conformance without leaking internal implementation details.

2. **Track Order (`GET /api/v1/orders/{order_id}/track`)** (5 tests)
   - `test_track_order_success`: Normalized tracking response containing `order_id`, `status`, `history`.
   - `test_track_order_appends_tracking_history_event`: Each track query records a live event in `tracking_history`.
   - `test_track_order_history_events_chronological`: History entries maintain chronological order with statuses and timestamps.
   - `test_track_order_reflects_order_current_status`: Tracking updates reflect current order lifecycle status.
   - `test_track_order_retains_courier_partner_and_awb`: Tracking response preserves `courier_partner` and `awb_number`.

3. **Cancel Order (`POST /api/v1/orders/{order_id}/cancel`)** (5 tests)
   - `test_cancel_order_success`: Returns 200 with `order_id` and `status: "CANCELLED"`.
   - `test_cancel_order_updates_order_status_in_database`: Database `orders.status` transitions to `CANCELLED`.
   - `test_cancel_order_appends_cancelled_event_to_history`: Cancellation appends `CANCELLED` record to `tracking_history`.
   - `test_cancel_order_repeated_cancellation`: Idempotent repeated cancellation handling.
   - `test_cancel_order_subsequent_track_returns_cancelled`: Tracking post-cancellation reports `status: "CANCELLED"`.

4. **Bulk Order Submission (`POST /api/v1/orders/bulk`)** (5 tests)
   - `test_bulk_submit_single_order_success`: Submitting single order in bulk returns 202/200 with `batch_id` and `status: "PROCESSING"`.
   - `test_bulk_submit_multiple_orders_success`: Submitting 5 orders returns accepted batch ID.
   - `test_bulk_submit_creates_batch_record_in_db`: Persists batch in `batches` table with `total=5`.
   - `test_bulk_submit_immediate_response_performance`: Returns within < 2 seconds without synchronous blocking.
   - `test_bulk_submit_heterogeneous_couriers_accepted`: Heterogeneous courier targets per item accepted.

5. **Bulk Polling & Progress (`GET /api/v1/orders/bulk/{batch_id}`)** (5 tests)
   - `test_bulk_poll_returns_correct_batch_metadata`: Returns `batch_id`, `status`, `total`, `successful`, `failed`, `results`.
   - `test_bulk_poll_eventual_completion`: Batch transitions to `COMPLETED` upon background worker completion.
   - `test_bulk_poll_item_results_structure`: Each item in `results` contains `order_id` and `success` boolean.
   - `test_bulk_poll_successful_count_matches_results`: Summary count `successful` matches items with `success=True`.
   - `test_bulk_poll_partial_failure_reporting`: Failed orders marked with `success=False` and `error_code`.

6. **Idempotency & Unique Order Constraints** (5 tests)
   - `test_idempotent_order_creation_same_payload`: Re-submitting identical payload returns 409 `DUPLICATE_ORDER` or existing order without duplicate shipment.
   - `test_idempotent_no_duplicate_rows_in_orders_table`: SQLite UNIQUE constraint prevents duplicate rows.
   - `test_idempotent_order_creation_preserves_original_awb`: Preserves original `awb_number` and creation timestamp.
   - `test_idempotent_submission_does_not_duplicate_tracking_events`: Duplicate submission does not append spurious tracking events.
   - `test_idempotent_modified_payload_rejected_or_unmutated`: Submitting modified payload on existing `order_id` is rejected (409) or original order remains unmutated.

7. **Standardized Error Envelope Conformance** (5 tests)
   - `test_error_envelope_404_order_not_found`: Top-level `"error"` key with `code="ORDER_NOT_FOUND"`, `message`, `request_id`, `details`.
   - `test_error_envelope_400_validation_error`: Invalid payload returns `code="VALIDATION_ERROR"`.
   - `test_error_envelope_400_unsupported_courier`: Unregistered courier partner returns `code="UNSUPPORTED_COURIER"`.
   - `test_error_envelope_request_id_always_non_empty_string`: Non-empty trace UUID string in all error envelopes.
   - `test_error_envelope_custom_request_id_in_error`: Custom `X-Request-ID` is preserved in error response and headers.

---

### 3.2 Tier 2: Boundary & Corner Cases (`tests/e2e/test_tier2_boundaries.py`)
Covers boundary conditions and error cases with $\ge 5$ tests per feature (31 total):

1. **Empty Bulk Submissions** (5 tests)
   - `test_boundary_bulk_empty_orders_array`: `orders: []` $\rightarrow$ 400/422 `VALIDATION_ERROR`.
   - `test_boundary_bulk_missing_orders_key`: `{}` $\rightarrow$ 400/422 `VALIDATION_ERROR`.
   - `test_boundary_bulk_null_orders`: `orders: null` $\rightarrow$ 400/422 `VALIDATION_ERROR`.
   - `test_boundary_bulk_orders_as_string`: `orders: "invalid"` $\rightarrow$ 400/422 `VALIDATION_ERROR`.
   - `test_boundary_bulk_orders_as_dict`: `orders: {"order_id": ...}` $\rightarrow$ 400/422 `VALIDATION_ERROR`.

2. **Bulk > 100 Orders Limit** (5 tests)
   - `test_boundary_bulk_exact_101_orders`: Exactly 101 orders $\rightarrow$ 400/422 `VALIDATION_ERROR`.
   - `test_boundary_bulk_105_orders`: 105 orders $\rightarrow$ 400/422 `VALIDATION_ERROR`.
   - `test_boundary_bulk_150_orders`: 150 orders $\rightarrow$ 400/422 `VALIDATION_ERROR`.
   - `test_boundary_bulk_200_orders`: 200 orders $\rightarrow$ 400/422 `VALIDATION_ERROR`.
   - `test_boundary_bulk_exact_100_orders_allowed`: Exactly 100 orders is accepted (boundary contrast).

3. **Missing Required Fields** (6 tests)
   - `test_boundary_order_missing_order_id`: Missing `order_id` $\rightarrow$ `VALIDATION_ERROR`.
   - `test_boundary_order_missing_courier_partner`: Missing `courier_partner` $\rightarrow$ `VALIDATION_ERROR`.
   - `test_boundary_order_missing_customer`: Missing `customer` $\rightarrow$ `VALIDATION_ERROR`.
   - `test_boundary_order_missing_customer_name`: Missing `customer.name` $\rightarrow$ `VALIDATION_ERROR`.
   - `test_boundary_order_missing_customer_phone`: Missing `customer.phone` $\rightarrow$ `VALIDATION_ERROR`.
   - `test_boundary_order_missing_items_list`: Missing `items` or empty `items: []` $\rightarrow$ `VALIDATION_ERROR`.

4. **Zero & Negative Prices / Quantities** (5 tests)
   - `test_boundary_item_negative_price`: `price: -10.0` $\rightarrow$ `VALIDATION_ERROR`.
   - `test_boundary_item_negative_cents_price`: `price: -0.01` $\rightarrow$ `VALIDATION_ERROR`.
   - `test_boundary_item_zero_quantity`: `quantity: 0` $\rightarrow$ `VALIDATION_ERROR`.
   - `test_boundary_item_negative_quantity`: `quantity: -1` $\rightarrow$ `VALIDATION_ERROR`.
   - `test_boundary_item_zero_price_allowed`: `price: 0.0` promotional sample item accepted per spec (`price >= 0.0`).

5. **Non-Existent Entities** (5 tests)
   - `test_boundary_track_non_existent_order`: Non-existent order tracking $\rightarrow$ 404 `ORDER_NOT_FOUND`.
   - `test_boundary_cancel_non_existent_order`: Non-existent order cancellation $\rightarrow$ 404 `ORDER_NOT_FOUND`.
   - `test_boundary_poll_non_existent_batch`: Non-existent bulk batch polling $\rightarrow$ 404 `ORDER_NOT_FOUND`.
   - `test_boundary_track_special_characters_order_id`: URL-encoded special characters $\rightarrow$ 404 `ORDER_NOT_FOUND`.
   - `test_boundary_cancel_non_existent_uuid_order`: Random UUID cancel $\rightarrow$ 404 `ORDER_NOT_FOUND`.

6. **Unassigned / Unsupported Couriers** (5 tests)
   - `test_boundary_unsupported_courier_fedex`: `courier_partner: "fedex"` $\rightarrow$ 400 `UNSUPPORTED_COURIER`.
   - `test_boundary_unsupported_courier_dhl`: `courier_partner: "dhl"` $\rightarrow$ 400 `UNSUPPORTED_COURIER`.
   - `test_boundary_unsupported_courier_ups`: `courier_partner: "ups"` $\rightarrow$ 400 `UNSUPPORTED_COURIER`.
   - `test_boundary_unsupported_courier_arbitrary_string`: Arbitrary carrier string $\rightarrow$ 400 `UNSUPPORTED_COURIER`.
   - `test_boundary_empty_courier_partner_string`: Empty string `courier_partner: ""` $\rightarrow$ 400/422 error.

---

### 3.3 Tier 3: Cross-Feature Combinations (`tests/e2e/test_tier3_combinations.py`)
Covers complex cross-cutting interactions (6 tests):

- `test_mixed_couriers_in_bulk_dispatch`: Bulk batch with multiple courier partners resolved independently by registry.
- `test_partial_batch_failures_and_counts_integrity`: Batch containing valid and invalid orders completes with partial failure counts (`total=2, successful=1, failed=1`) and granular item-level error reporting.
- `test_track_order_lifecycle_before_and_after_cancellation`: Full status transition check: `CREATED` $\rightarrow$ `CANCELLED`, verifying tracking reflects state and appends audit events.
- `test_tracking_history_immutability_audit_log`: Direct database audit proving `tracking_history` is append-only, chronologically sorted, and never mutates prior events.
- `test_duplicate_submission_does_not_mutate_or_duplicate_tracking`: Demonstrates idempotency across both `orders` and `tracking_history` tables.
- `test_bulk_batch_with_duplicate_order_ids_handles_partial_conflict`: Bulk worker catches duplicate order IDs without aborting the rest of the batch.

---

### 3.4 Tier 4: Real-World Application Workloads (`tests/e2e/test_tier4_scenarios.py`)
Covers full operational workflows and resilience patterns (6 tests):

- `test_scenario_full_ecommerce_fulfillment_lifecycle`: Full customer order journey through warehouse pickup, transit, and delivery with complete tracking audit log.
- `test_scenario_concurrent_bulk_batch_100_orders_to_completion`: 100 concurrent orders submitted in single bulk batch, polled to `COMPLETED` status, and verified via random sample tracking.
- `test_scenario_transient_retry_recovery`: Transparent automatic recovery from transient network timeouts / 5xx responses using exponential backoff.
- `test_scenario_transient_retry_exhaustion`: Exhaustion of retries cleanly maps to `COURIER_TIMEOUT` (504) or `COURIER_ERROR` (502).
- `test_scenario_auth_failure_with_token_refresh`: Automatic token renewal and replay upon courier HTTP 401 Unauthorized.
- `test_scenario_order_cancellation_and_subsequent_tracking`: Full order cancellation with post-cancellation audit validation.

---

## 4. Execution Commands

### Run Full Test Suite
```bash
DEBUG=false PYTHONPATH=. pytest tests/ -v
```

### Run All E2E Tests
```bash
DEBUG=false PYTHONPATH=. pytest tests/e2e/ -v
```

### Run by Specific Tier
```bash
# Tier 1: Feature Coverage (36 tests)
DEBUG=false PYTHONPATH=. pytest tests/e2e/test_tier1_features.py -v

# Tier 2: Boundary & Corner Cases (31 tests)
DEBUG=false PYTHONPATH=. pytest tests/e2e/test_tier2_boundaries.py -v

# Tier 3: Cross-Feature Combinations (6 tests)
DEBUG=false PYTHONPATH=. pytest tests/e2e/test_tier3_combinations.py -v

# Tier 4: Real-World Scenarios (6 tests)
DEBUG=false PYTHONPATH=. pytest tests/e2e/test_tier4_scenarios.py -v
```
