## 2026-09-28T15:06:06Z

You are the Implementation Worker for Milestone 2: Courier Abstraction & Adapters of the Courier Integration Platform.

Working Directory: ./.agents/teamwork/worker_m2_couriers
Project Root: .
Parent Conversation ID: 53fe967f-356a-4dc8-a2a1-308ee9c4c592

MANDATORY INPUTS TO READ FIRST:
1. ./.agents/teamwork/ORIGINAL_REQUEST.md
2. ./task.md
3. ./PROJECT.md
4. ./.agents/teamwork/spec_miner_urbanebolt/analysis.md
5. ./.agents/teamwork/explorer_arch/analysis.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

EXCLUSIVE FILE WRITE OWNERSHIP:
You own and must implement the following files exclusively:
- app/couriers/__init__.py (exports CourierAdapter, CourierRegistry, courier_registry, MockCourierAdapter, UrbaneboltAdapter)
- app/couriers/base.py (CourierAdapter ABC with authenticate, create_order, track_order, cancel_order, plus strongly typed DTOs)
- app/couriers/registry.py (CourierRegistry with register, get, zero if/elif branching, default courier_registry instance registering mock and urbanebolt)
- app/couriers/client.py (Resilient HTTP client with configurable exponential backoff retry for timeouts/5xx, fail-fast on 4xx, and transparent 401 token refresh retry)
- app/couriers/mock.py (MockCourierAdapter with configurable simulation modes: success, timeout, 4xx, 5xx, auth failure, plus per-order outcome flags for bulk testing)
- app/couriers/urbanebolt.py (UrbaneboltAdapter implementing live UAT endpoints: getToken, manifest, tracking-pub, cancel, with Bearer token caching, schema mapping, and error translation)
- tests/unit/test_adapters.py (unit tests for CourierAdapter, CourierRegistry, and UrbaneboltAdapter mapping logic)
- tests/unit/test_resilience.py (unit tests for exponential backoff, timeout retries, 4xx fail-fast, and 401 token refresh)
- tests/test_mock_courier.py (MANDATORY top-level test file required by task.md §2, §20 testing all MockCourierAdapter simulated modes)

VERIFICATION REQUIREMENTS:
1. Run pytest `python3 -m pytest tests/unit tests/test_mock_courier.py -v --cov=app/couriers` to verify 100% passing tests and high coverage.
2. Run `python3 -m ruff check app/couriers tests/` to verify zero lint errors.
3. Document executed commands, results, and outputs in your handoff.md.
4. Update progress.md in your working directory.
5. Send completion message to parent when done.
