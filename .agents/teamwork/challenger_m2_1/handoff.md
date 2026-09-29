# Handoff Report: Challenger M2-1 — Mock Courier Adapter Empirical Verification

## 1. Observation

Direct empirical observations from test authoring, code inspection, and test execution:

1. **Target Implementation Files**:
   - `app/couriers/mock.py`: 323 lines implementing `MockCourierAdapter` with `MockSimulationMode`, in-memory order and AWB dictionaries (`_orders`, `_awb_to_order_id`), deterministic synthetic ID generation (`MOCK-{order_id}`, `AWB-MOCK-{order_id}`), simulation checks in `_check_simulation`, auto-progression in `track_order`, and cancellation tracking in `cancel_order`.
   - `app/couriers/base.py`: 86 lines defining `CourierAdapter` ABC and `AwaitableDTO` enabling dual sync (`result = adapter.create_order(...)`) and async (`result = await adapter.create_order(...)`) execution.
   - `app/couriers/registry.py`: 68 lines registering default `mock` adapter instance via `register_default_couriers()`.

2. **Empirical Test Suite Authored & Executed**:
   - Created `tests/unit/test_mock_courier_empirical.py` containing 37 distinct empirical stress-test cases organized into 4 test classes:
     - `TestMockCourierStatePersistence`: 8 test cases verifying independent order persistence, dictionary payload acceptance, full auto-progress chains (`CREATED` -> `PICKED_UP` -> `IN_TRANSIT` -> `DELIVERED`), static tracking when auto-progress is disabled, cancellation lifecycle and idempotency, terminal state persistence, unknown order tracking/cancellation raising `OrderNotFoundError` (404), and `reset()` state purge.
     - `TestMockCourierGlobalSimulationModes`: 6 test cases verifying global `TIMEOUT` (504 `CourierTimeoutError`), `SERVER_ERROR` (502 `CourierError` with status 500 details), `CLIENT_ERROR` (400 `ValidationError`), `AUTH_FAILURE` (502 `CourierAuthError` with 401 details) with recovery via `authenticate()`, permanent auth failure via `set_permanent_auth_failure(True)`, and flexible string/enum mode configuration.
     - `TestMockCourierPerOrderFlags`: 6 test cases (19 parameterized permutations) verifying failure and status flags embedded in `order_id` and `customer.name`, case-insensitivity, flag triggers in `track_order` and `cancel_order`, and strict cross-order isolation (no state leakage).
     - `TestMockCourierConcurrencyAndStress`: 4 stress tests verifying 100 concurrent threads creating orders against a single adapter, concurrent tracking advancing to `DELIVERED`, 50 concurrent threads executing mixed operations (creates, tracks, cancels, failure injections), and 50 concurrent async coroutines awaiting `AwaitableDTO` methods.

3. **Verbatim Execution Commands & Results**:
   - Command: `python3 -m pytest tests/unit/test_mock_courier_empirical.py tests/test_mock_courier.py -v --cov=app.couriers.mock --cov-report=term-missing`
     ```text
     ============================= test session starts ==============================
     platform darwin -- Python 3.14.6, pytest-8.3.3, pluggy-1.6.0
     rootdir: .
     plugins: asyncio-0.24.0, cov-5.0.0, anyio-4.14.2
     collected 51 items

     tests/unit/test_mock_courier_empirical.py ..................................... [ 72%]
     tests/test_mock_courier.py ..............                                [100%]

     ---------- coverage: platform darwin, python 3.14.6-final-0 ----------
     Name                   Stmts   Miss  Cover   Missing
     ----------------------------------------------------
     app/couriers/mock.py     135      1    99%   70
     ----------------------------------------------------
     TOTAL                    135      1    99%
     ====================== 51 passed, 1719 warnings in 0.22s =======================
     ```
   - Command: `python3 -m ruff check tests/unit/test_mock_courier_empirical.py app/couriers/mock.py tests/test_mock_courier.py`
     ```text
     All checks passed!
     ```

4. **Code Inspection Observation (Line 70 Unreachable Fallback)**:
   - In `app/couriers/mock.py`:
     ```python
     28: class MockSimulationMode(str, Enum):
     ...
     66:     def simulation_mode(self, mode: MockSimulationMode | str) -> None:
     67:         if isinstance(mode, str):
     68:             self._mode = MockSimulationMode(mode)
     69:         else:
     70:             self._mode = mode
     ```
   - Because `MockSimulationMode` inherits from `str`, `isinstance(mode, str)` evaluates to `True` for both strings and enum instances. Line 70 is unreachable, resulting in the 99% coverage metric (134/135 statements). This is benign and does not affect behavior or correctness.

## 2. Logic Chain

1. **State Persistence Verification**:
   - Observation 2 & 3: `TestMockCourierStatePersistence` executed 8 tests.
   - When 3 distinct orders were created, each received unique AWB numbers (`AWB-MOCK-...`) and courier order IDs (`MOCK-...`). Tracking by either AWB or internal order ID retrieved the correct matching record without cross-contamination.
   - Order cancellation updated `order_data["status"] = OrderStatus.CANCELLED`, appended audit log `"Order cancelled by client"`, and subsequent tracking returned `OrderStatus.CANCELLED`.
   - Calling `cancel_order` on an already cancelled order succeeded idempotently.
   - Calling `track_order` or `cancel_order` with an unregistered ID raised `OrderNotFoundError` with `code="ORDER_NOT_FOUND"` and HTTP status 404.
   - Calling `reset()` purged all internal state dictionaries, resetting the adapter to its pristine state.

2. **Global Simulation Mode Verification**:
   - Observation 2 & 3: `TestMockCourierGlobalSimulationModes` executed 6 tests.
   - Setting global mode to `TIMEOUT` caused `create_order`, `track_order`, and `cancel_order` to raise `CourierTimeoutError` (status 504).
   - Setting `SERVER_ERROR` raised `CourierError` (status 502) with `details={"status_code": 500}`.
   - Setting `CLIENT_ERROR` raised `ValidationError` (status 400).
   - Setting `AUTH_FAILURE` raised `CourierAuthError` (status 502, 401 details) on initial attempt, but succeeded after calling `authenticate()`. Permanent auth mode (`set_permanent_auth_failure(True)`) ensured the error persisted even across repeated re-authentication calls.

3. **Per-Order Outcome Flags Verification**:
   - Observation 2 & 3: `TestMockCourierPerOrderFlags` executed 6 tests across 19 permutations.
   - Embedding `SIMULATE_TIMEOUT`, `SIMULATE_5XX`, `SIMULATE_SERVER_ERROR`, `SIMULATE_4XX`, `SIMULATE_CLIENT_ERROR`, or `SIMULATE_AUTH_FAIL` in either `order_id` or `customer.name` triggered the exact expected exceptions.
   - Lowercase and mixed-case strings (`simulate_timeout`, `ord-simulate_5xx-002`) triggered identically, verifying case-insensitive matching.
   - Initial status flags (`SIMULATE_PICKED_UP`, `SIMULATE_IN_TRANSIT`, `SIMULATE_DELIVERED`, `SIMULATE_FAILED`) set the initial order status directly upon creation.
   - Crucially, per-order failure flags did not leak: creating an order with `SIMULATE_TIMEOUT` failed, and the immediately following standard order succeeded with status `CREATED`.

4. **Concurrency & Stress Verification**:
   - Observation 2 & 3: `TestMockCourierConcurrencyAndStress` executed 4 tests.
   - 100 concurrent threads creating orders via `ThreadPoolExecutor(max_workers=20)` resulted in all 100 orders successfully persisted in `_orders` and `_awb_to_order_id`, and all 100 were verified retrievable via concurrent tracking calls.
   - 30 concurrent tracking calls on an `auto_progress=True` order reliably converged to terminal status `OrderStatus.DELIVERED`.
   - 50 concurrent worker threads executing randomized operations (creates, tracks, cancels, simulated timeouts) executed without deadlocks, memory corruption, or race conditions.
   - 50 concurrent async coroutines using `asyncio.gather` successfully awaited all operations via `AwaitableDTO`.

## 3. Caveats

- In-memory state: As intended by design for offline development and testing, `MockCourierAdapter` stores state in in-memory dictionaries. Process restarts reset state unless persisted at the database level by higher-level services (to be verified in Milestone 3).
- Real UrbaneBolt UAT integration is challenged separately by Challenger 2 (`challenger_m2_2`).

## 4. Conclusion

**Verdict: APPROVE**

The `MockCourierAdapter` implementation is robust, complete, fully conformant to specification, thread-safe under concurrent stress, and exhibits zero state corruption or cross-order leakage:
- 100% test pass rate across 51 mock courier tests (37 empirical stress tests + 14 standard unit tests).
- 99% statement coverage on `app/couriers/mock.py` (134/135 statements).
- Zero lint or style violations.

## 5. Verification Method

To independently reproduce and verify this empirical challenge:

1. **Execute Mock Courier Empirical Stress Suite**:
   ```bash
   python3 -m pytest tests/unit/test_mock_courier_empirical.py -v
   ```
   *Expected*: 37 passed tests in ~0.2s.

2. **Execute Full Mock Courier Suite with Coverage**:
   ```bash
   python3 -m pytest tests/unit/test_mock_courier_empirical.py tests/test_mock_courier.py --cov=app.couriers.mock --cov-report=term-missing
   ```
   *Expected*: 51 passed tests, 99% statement coverage.

3. **Verify Code Style**:
   ```bash
   python3 -m ruff check tests/unit/test_mock_courier_empirical.py app/couriers/mock.py
   ```
   *Expected*: `All checks passed!`.
