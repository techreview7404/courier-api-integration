# Handoff Report: Milestone 2 — Courier Abstraction & Adapters

## 1. Observation

Direct observations from codebase inspection, implementation, and test execution:

1. **Files Created & Implemented under exclusive write ownership**:
   - `app/couriers/__init__.py`: Package exports for `CourierAdapter`, `CourierRegistry`, `courier_registry`, `MockCourierAdapter`, `MockSimulationMode`, `UrbaneboltAdapter`, `ResilientHttpClient`, and DTOs.
   - `app/couriers/base.py`: Defines `CourierAdapter` ABC with `authenticate`, `create_order`, `track_order`, `cancel_order` methods, and strongly-typed DTOs `CourierOrderResult`, `CourierTrackingResult`, `CourierCancelResult` inheriting from `AwaitableDTO` for dual sync and async execution compatibility.
   - `app/couriers/registry.py`: Defines `CourierRegistry` providing dynamic lookup via dictionary mapping (`self._adapters[key]`) with zero `if/elif` branching, raising `UnsupportedCourierError` on missing partners, and initializing singleton `courier_registry` registering `mock` and `urbanebolt`.
   - `app/couriers/client.py`: Defines `ResilientHttpClient` implementing configurable exponential backoff (`delay = retry_delay * (backoff_factor ** attempt)`) for timeouts (`httpx.TimeoutException`) and 5xx responses, fail-fast on non-401 4xx errors, and transparent 401 token refresh retry using `auth_refresh_callback`.
   - `app/couriers/mock.py`: Defines `MockCourierAdapter` supporting simulation modes (`SUCCESS`, `TIMEOUT`, `SERVER_ERROR`, `CLIENT_ERROR`, `AUTH_FAILURE`), per-order bulk simulation flags in customer name / order_id (`SIMULATE_TIMEOUT`, `SIMULATE_5XX`, `SIMULATE_4XX`, `SIMULATE_AUTH_FAIL`, `SIMULATE_PICKED_UP`, etc.), real in-memory state persistence, tracking progression, and cancellation.
   - `app/couriers/urbanebolt.py`: Defines `UrbaneboltAdapter` integrating live UAT endpoints: `POST /api/v1/auth/getToken/` (token caching with 300s expiry buffer), `POST /api/v1/services/manifest/` (array manifest payload, >= 10 char address enforcement, item aggregation, duplicate and validation error translation), `GET /api/v1/services/tracking-pub/` (canonical status mapping for MAN, PKD, RDC, DDS, OFD, DDL, CAN, RTL, UDD), and `POST /api/v1/services/cancel/` (handling already cancelled as idempotent success).
   - `tests/unit/test_adapters.py`: 20 unit tests verifying ABC enforcement, DTO awaitability, registry zero-branching AST validation, UrbaneBolt manifest mapping, duplicate order error handling, tracking normalization, and cancellation.
   - `tests/unit/test_resilience.py`: 10 unit tests verifying exponential backoff delay intervals, timeout retries and exhaustion, 5xx retries, 4xx fail-fast, and 401 token refresh recovery / exhaustion.
   - `tests/test_mock_courier.py`: 14 top-level test cases verifying full mock courier lifecycle, all simulation modes, per-order bulk outcome flags, auto-progress tracking, and not-found behavior.

2. **Verification Command Results**:
   - `python3 -m pytest tests/unit tests/test_mock_courier.py -v --cov=app/couriers`:
     ```text
     ====================== 131 passed, 4690 warnings in 1.18s ======================

     ---------- coverage: platform darwin, python 3.14.6-final-0 ----------
     Name                         Stmts   Miss  Cover
     ------------------------------------------------
     app/couriers/__init__.py         6      0   100%
     app/couriers/base.py            43      5    88%
     app/couriers/client.py          91      3    97%
     app/couriers/mock.py           135      8    94%
     app/couriers/registry.py        32      0   100%
     app/couriers/urbanebolt.py     179     13    93%
     ------------------------------------------------
     TOTAL                          486     29    94%
     ```
   - `python3 -m ruff check app/couriers tests/`:
     ```text
     All checks passed!
     ```
   - `python3 -m pytest tests/integration/ -v`:
     ```text
     11 passed in 1.50s
     ```

## 2. Logic Chain

1. **Decoupled Architecture & Registry**:
   - `CourierAdapter` establishes the uniform contract (`create_order`, `track_order`, `cancel_order`, `authenticate`).
   - `CourierRegistry` decouples service layer consumers from concrete implementations. By using dictionary hashing rather than conditional branching, new adapters can be registered dynamically at runtime without modifying existing code.
   - AST inspection in `test_courier_registry_zero_if_elif_branching` formally confirms zero `if/elif` branching on courier names.

2. **Dual Synchronous / Asynchronous Execution Compatibility**:
   - All DTOs (`CourierOrderResult`, `CourierTrackingResult`, `CourierCancelResult`) inherit from `AwaitableDTO`, which defines `__await__`.
   - If a caller invokes `res = adapter.create_order(payload)`, `res` is immediately accessible as a DTO.
   - If a caller in an async coroutine calls `res = await adapter.create_order(payload)`, Python evaluates `__await__` seamlessly returning the DTO without `TypeError`.

3. **Resilience & Self-Healing Authentication**:
   - `ResilientHttpClient` encapsulates retry policies using configurable exponential backoff (`delay = initial * (factor ** attempt)`).
   - Downstream network timeouts and 5xx responses retry up to `MAX_RETRIES` times and fail gracefully to `CourierTimeoutError` (504) or `CourierError` (502).
   - HTTP 401 Unauthorized responses trigger `auth_refresh_callback`, acquiring a fresh token and retrying the request once. If the retry fails, it raises `CourierAuthError` without looping.
   - HTTP 4xx client errors (400, 404, 422) fail fast on the first attempt without redundant retries.

4. **Realistic Mock Simulation & In-Memory State**:
   - `MockCourierAdapter` maintains stateful tracking and order dictionaries (`_orders`, `_awb_to_order_id`).
   - Supports global failure modes (`TIMEOUT`, `SERVER_ERROR`, `CLIENT_ERROR`, `AUTH_FAILURE`) and per-order outcome flags (`SIMULATE_TIMEOUT`, `SIMULATE_5XX`, etc.) in order identifiers and customer names, enabling isolated partial-failure testing in bulk batches.

5. **UrbaneBolt Production UAT Integration**:
   - Adheres strictly to the specification mined from `urbanebolt_doc.json` and UAT probes.
   - Handles address length >= 10 char constraints, array wrapping of manifests, status code mapping (`MAN`, `PKD`, `RDC`, `DDL`, etc.), and duplicate order detection in `errorResponse`.

## 3. Caveats

- Live calls to `https://uat.urbanebolt.in` require network access and valid test credentials in `.env` (`URBANEBOLT_USERNAME`, `URBANEBOLT_PASSWORD`). All unit tests run deterministically with mocked HTTP responses without external network dependencies.
- UrbaneBolt UAT uses an internal/self-signed SSL certificate; `ResilientHttpClient` is configured with `verify_ssl=False` for UrbaneBolt by default.

## 4. Conclusion

Milestone 2 (Courier Abstraction & Adapters) is complete and fully verified:
- `CourierAdapter` ABC and strongly typed DTOs are implemented and tested.
- `CourierRegistry` is implemented with zero `if/elif` branching and pre-registered with `mock` and `urbanebolt`.
- `ResilientHttpClient` handles exponential backoff retries, fail-fast on 4xx, and transparent 401 token refresh.
- `MockCourierAdapter` provides in-memory state tracking, all simulated failure modes, and per-order bulk outcome flags.
- `UrbaneboltAdapter` implements live UAT endpoint contracts, Bearer token caching, schema mapping, and error translation.
- 100% test pass rate across 131 tests with 94% coverage on `app/couriers` and 0 ruff lint errors.

## 5. Verification Method

To independently verify the implementation:

1. **Run Unit & Top-Level Mock Courier Tests with Coverage**:
   ```bash
   python3 -m pytest tests/unit tests/test_mock_courier.py -v --cov=app/couriers
   ```
   *Expected*: 131 passed tests, >= 90% coverage on `app/couriers`.

2. **Run Ruff Linter**:
   ```bash
   python3 -m ruff check app/couriers tests/
   ```
   *Expected*: Zero errors (`All checks passed!`).

3. **Run Integration Suite**:
   ```bash
   python3 -m pytest tests/integration/ -v
   ```
   *Expected*: 11 passed tests.

4. **Verify Zero Branching in Registry**:
   Inspect `app/couriers/registry.py` and run `pytest tests/unit/test_adapters.py -k test_courier_registry_zero_if_elif_branching`.
