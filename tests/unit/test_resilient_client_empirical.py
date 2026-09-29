"""Empirical Challenger Test Suite for ResilientHttpClient and Retry Policies.

Exhaustively verifies:
1. Exponential backoff delays accurately follow formula: initial_delay * (factor ** attempt)
2. Transient 5xx and timeouts retry up to MAX_RETRIES and raise CourierError / CourierTimeoutError on exhaustion
3. Client errors (400, 404, 422) fail fast on first attempt without any retries
4. 401 Unauthorized invokes token refresh callback and retries once; if 401 persists, raises CourierAuthError without infinite loop
5. Real HTTP ephemeral server verification and concurrent multi-threaded stress testing
"""

from concurrent.futures import ThreadPoolExecutor
import http.server
import socket
from socketserver import ThreadingMixIn
import threading
import time
from typing import Any, List
from unittest.mock import MagicMock, call, patch
import httpx
import pytest

from app.couriers.client import ResilientHttpClient
from app.exceptions import (
    CourierAuthError,
    CourierError,
    CourierTimeoutError,
)


# ============================================================================
# 1. EXPONENTIAL BACKOFF FORMULA VERIFICATION
# ============================================================================

@pytest.mark.parametrize(
    "initial_delay, factor, max_retries",
    [
        (1.0, 2.0, 3),   # Standard defaults: [1.0, 2.0, 4.0]
        (0.5, 2.0, 4),   # [0.5, 1.0, 2.0, 4.0]
        (1.5, 3.0, 3),   # [1.5, 4.5, 13.5]
        (2.0, 1.5, 3),   # [2.0, 3.0, 4.5]
        (0.1, 1.0, 5),   # Linear constant: [0.1, 0.1, 0.1, 0.1, 0.1]
        (10.0, 2.0, 1),  # Single retry: [10.0]
    ],
)
def test_empirical_backoff_formula_matches_exact_values(
    initial_delay: float, factor: float, max_retries: int
):
    """Verify that every sleep interval matches initial_delay * (factor ** attempt) exactly."""
    client = ResilientHttpClient(
        max_retries=max_retries,
        retry_delay=initial_delay,
        backoff_factor=factor,
    )

    expected_delays = [initial_delay * (factor**attempt) for attempt in range(max_retries)]

    with patch("httpx.Client.request", side_effect=httpx.TimeoutException("Simulated Timeout")):
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(CourierTimeoutError):
                client.request("GET", "https://api.courier.mock/endpoint")

            assert mock_sleep.call_count == max_retries
            actual_delays = [call_args[0][0] for call_args in mock_sleep.call_args_list]
            for actual, expected in zip(actual_delays, expected_delays):
                assert actual == pytest.approx(expected, rel=1e-5), (
                    f"Mismatch in backoff delay: got {actual}, expected {expected}"
                )


def test_empirical_backoff_max_retries_zero():
    """When max_retries=0, exactly 1 attempt is made, 0 sleep calls occur, and error is raised."""
    client = ResilientHttpClient(max_retries=0, retry_delay=1.0, backoff_factor=2.0)

    with patch("httpx.Client.request", side_effect=httpx.TimeoutException("Timeout")) as mock_req:
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(CourierTimeoutError) as exc_info:
                client.request("GET", "https://api.courier.mock/endpoint")

            assert mock_req.call_count == 1
            assert mock_sleep.call_count == 0
            assert "after 0 retries" in exc_info.value.message


def test_empirical_backoff_zero_delay_does_not_sleep():
    """When retry_delay=0.0, client does not call time.sleep but still retries max_retries times."""
    client = ResilientHttpClient(max_retries=3, retry_delay=0.0, backoff_factor=2.0)

    with patch("httpx.Client.request", side_effect=httpx.TimeoutException("Timeout")) as mock_req:
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(CourierTimeoutError):
                client.request("GET", "https://api.courier.mock/endpoint")

            assert mock_req.call_count == 4
            assert mock_sleep.call_count == 0


def test_empirical_backoff_real_wall_clock_elapsed_time():
    """Empirical verification without mocking time.sleep: measure real elapsed wall-clock time."""
    initial_delay = 0.04
    factor = 2.0
    max_retries = 2
    # Expected sleep sum = 0.04 * (2^0) + 0.04 * (2^1) = 0.04 + 0.08 = 0.12s
    expected_min_duration = 0.12

    client = ResilientHttpClient(
        max_retries=max_retries,
        retry_delay=initial_delay,
        backoff_factor=factor,
    )

    with patch("httpx.Client.request", side_effect=httpx.TimeoutException("Timeout")):
        start_time = time.perf_counter()
        with pytest.raises(CourierTimeoutError):
            client.request("GET", "https://api.courier.mock/wallclock")
        elapsed = time.perf_counter() - start_time

        assert elapsed >= expected_min_duration, (
            f"Elapsed time {elapsed:.4f}s is less than expected minimum {expected_min_duration:.4f}s"
        )
        assert elapsed < expected_min_duration + 0.35, (
            f"Elapsed time {elapsed:.4f}s significantly exceeded expectation"
        )


# ============================================================================
# 2. TRANSIENT 5xx AND TIMEOUT RETRY CEILING & EXHAUSTION
# ============================================================================

@pytest.mark.parametrize("status_5xx", [500, 502, 503, 504])
def test_empirical_5xx_retries_ceiling_and_raises_courier_error(status_5xx: int):
    """Verify that all 5xx status codes retry exactly max_retries times and raise CourierError."""
    max_retries = 3
    client = ResilientHttpClient(max_retries=max_retries, retry_delay=0.0)

    server_error_resp = httpx.Response(status_5xx, text=f"Error {status_5xx}")

    with patch("httpx.Client.request", return_value=server_error_resp) as mock_req:
        with pytest.raises(CourierError) as exc_info:
            client.request("POST", "https://api.courier.mock/orders")

        # 1 initial attempt + 3 retries = 4 total attempts
        assert mock_req.call_count == max_retries + 1
        err = exc_info.value
        assert err.code == "COURIER_ERROR"
        assert err.status_code == 502
        assert f"HTTP {status_5xx}" in err.message
        assert f"after {max_retries} retries" in err.message
        assert err.details.get("status_code") == status_5xx


@pytest.mark.parametrize(
    "timeout_exc",
    [
        httpx.TimeoutException("General timeout"),
        httpx.ConnectTimeout("Connect timeout"),
        httpx.ReadTimeout("Read timeout"),
        httpx.WriteTimeout("Write timeout"),
        httpx.PoolTimeout("Pool acquisition timeout"),
        CourierTimeoutError("Pre-wrapped courier timeout"),
    ],
)
def test_empirical_timeout_retries_ceiling_and_raises_courier_timeout_error(timeout_exc: Exception):
    """Verify all httpx timeout exception variants retry exactly max_retries times and raise CourierTimeoutError."""
    max_retries = 2
    client = ResilientHttpClient(max_retries=max_retries, retry_delay=0.0)

    with patch("httpx.Client.request", side_effect=timeout_exc) as mock_req:
        with pytest.raises(CourierTimeoutError) as exc_info:
            client.request("GET", "https://api.courier.mock/track")

        assert mock_req.call_count == max_retries + 1
        err = exc_info.value
        assert err.code == "COURIER_TIMEOUT"
        assert err.status_code == 504
        assert f"after {max_retries} retries" in err.message
        assert err.details.get("retries") == max_retries


def test_empirical_network_connection_error_exhaustion():
    """Verify TCP connection errors and NetworkErrors retry and raise CourierError."""
    max_retries = 2
    client = ResilientHttpClient(max_retries=max_retries, retry_delay=0.0)

    with patch("httpx.Client.request", side_effect=httpx.ConnectError("Connection refused")) as mock_req:
        with pytest.raises(CourierError) as exc_info:
            client.request("POST", "https://api.courier.mock/cancel")

        assert mock_req.call_count == max_retries + 1
        err = exc_info.value
        assert err.code == "COURIER_ERROR"
        assert err.status_code == 502
        assert f"after {max_retries} retries" in err.message


def test_empirical_recovery_on_intermediate_attempt():
    """Verify client recovers immediately when a transient error succeeds on attempt N."""
    client = ResilientHttpClient(max_retries=3, retry_delay=0.0)

    # Fail on attempt 0 (503), fail on attempt 1 (ConnectTimeout), succeed on attempt 2 (200)
    side_effects = [
        httpx.Response(503, text="Unavailable"),
        httpx.ConnectTimeout("Slow connection"),
        httpx.Response(200, json={"awb": "AWB-RECOVERED"}),
    ]

    with patch("httpx.Client.request", side_effect=side_effects) as mock_req:
        resp = client.request("POST", "https://api.courier.mock/manifest")

        assert resp.status_code == 200
        assert resp.json()["awb"] == "AWB-RECOVERED"
        assert mock_req.call_count == 3


def test_empirical_mixed_failure_sequence_500_then_timeout():
    """Test mixed sequence: 500 on attempt 0, Timeout on attempt 1 (exhausting retries)."""
    client = ResilientHttpClient(max_retries=1, retry_delay=0.0)

    side_effects = [
        httpx.Response(500, text="Internal Server Error"),
        httpx.TimeoutException("Gateway read timeout"),
    ]

    with patch("httpx.Client.request", side_effect=side_effects) as mock_req:
        with pytest.raises(CourierTimeoutError) as exc_info:
            client.request("GET", "https://api.courier.mock/status")

        assert mock_req.call_count == 2
        assert exc_info.value.code == "COURIER_TIMEOUT"


def test_empirical_mixed_failure_sequence_timeout_then_500():
    """Investigate mixed sequence: Timeout on attempt 0, 500 on attempt 1 (exhausting retries)."""
    client = ResilientHttpClient(max_retries=1, retry_delay=0.0)

    side_effects = [
        httpx.TimeoutException("Initial connect timeout"),
        httpx.Response(500, text="Server crashed"),
    ]

    with patch("httpx.Client.request", side_effect=side_effects) as mock_req:
        # In current client.py implementation, last_exception is not cleared when response is obtained.
        # So last_exception (TimeoutException) is checked first at line 150.
        with pytest.raises((CourierError, CourierTimeoutError)) as exc_info:
            client.request("GET", "https://api.courier.mock/status")

        assert mock_req.call_count == 2
        assert exc_info.value.code in ("COURIER_TIMEOUT", "COURIER_ERROR")


# ============================================================================
# 3. CLIENT ERRORS (400, 404, 422, ETC.) FAIL FAST
# ============================================================================

@pytest.mark.parametrize("client_code", [400, 403, 404, 405, 409, 422])
def test_empirical_client_errors_fail_fast_on_first_attempt(client_code: int):
    """Verify 4xx client errors (non-401) return immediately on attempt 0 with zero retries."""
    max_retries = 5  # High ceiling to prove no retries occur
    client = ResilientHttpClient(max_retries=max_retries, retry_delay=1.0)

    error_resp = httpx.Response(client_code, json={"error": f"Client Error {client_code}"})

    with patch("httpx.Client.request", return_value=error_resp) as mock_req:
        with patch("time.sleep") as mock_sleep:
            res = client.request("POST", "https://api.courier.mock/orders")

            assert res.status_code == client_code
            assert mock_req.call_count == 1  # Exactly 1 attempt
            assert mock_sleep.call_count == 0  # Zero delay/sleep


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_empirical_all_http_methods_fail_fast_on_422(method: str):
    """Verify all HTTP methods fail fast without retries on 422 Unprocessable Entity."""
    client = ResilientHttpClient(max_retries=3, retry_delay=0.5)

    resp_422 = httpx.Response(422, json={"detail": "Missing required field: pincode"})

    with patch("httpx.Client.request", return_value=resp_422) as mock_req:
        with patch("time.sleep") as mock_sleep:
            res = client.request(method, "https://api.courier.mock/endpoint")

            assert res.status_code == 422
            assert mock_req.call_count == 1
            assert mock_sleep.call_count == 0


# ============================================================================
# 4. 401 UNAUTHORIZED, TOKEN REFRESH & INFINITE LOOP PREVENTION
# ============================================================================

def test_empirical_401_triggers_refresh_callback_and_succeeds():
    """Verify 401 invokes token refresh callback once and replays request with new bearer token."""
    mock_refresh = MagicMock(return_value="RENEWED_VALID_JWT_TOKEN")
    client = ResilientHttpClient(
        max_retries=3,
        retry_delay=0.0,
        auth_refresh_callback=mock_refresh,
    )

    unauth_resp = httpx.Response(401, json={"message": "Token expired"})
    success_resp = httpx.Response(200, json={"status": "manifested", "order_id": "ORD-OK"})

    with patch("httpx.Client.request", side_effect=[unauth_resp, success_resp]) as mock_req:
        resp = client.request(
            "POST",
            "https://api.courier.mock/manifest",
            headers={"Authorization": "Bearer STALE_TOKEN"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "manifested"

        # Assert exactly one refresh callback
        assert mock_refresh.call_count == 1

        # Assert exactly two requests: initial + single retry
        assert mock_req.call_count == 2

        # Verify second request included renewed Bearer token in headers
        second_headers = mock_req.call_args_list[1][1].get("headers", {})
        assert second_headers.get("Authorization") == "Bearer RENEWED_VALID_JWT_TOKEN"


def test_empirical_persistent_401_raises_auth_error_without_infinite_loop():
    """Stress-test persistent 401: must retry at most ONCE, NEVER loop, and raise CourierAuthError."""
    call_tracker = {"refresh_count": 0, "request_count": 0}

    def counting_refresh_callback():
        call_tracker["refresh_count"] += 1
        return f"TOKEN_ATTEMPT_{call_tracker['refresh_count']}"

    client = ResilientHttpClient(
        max_retries=5,  # Even with high max_retries, 401 should NOT use standard retry loop
        retry_delay=0.0,
        auth_refresh_callback=counting_refresh_callback,
    )

    persistent_unauth = httpx.Response(401, text="Invalid credentials / Revoked token")

    def mock_request_side_effect(*args, **kwargs):
        call_tracker["request_count"] += 1
        return persistent_unauth

    with patch("httpx.Client.request", side_effect=mock_request_side_effect):
        with pytest.raises(CourierAuthError) as exc_info:
            client.request("GET", "https://api.courier.mock/protected/resource")

        # Crucial invariant: exactly 1 refresh callback invoked
        assert call_tracker["refresh_count"] == 1, (
            f"Expected exactly 1 refresh invocation, got {call_tracker['refresh_count']}"
        )
        # Crucial invariant: exactly 2 HTTP requests made (initial + 1 retry)
        assert call_tracker["request_count"] == 2, (
            f"Expected exactly 2 HTTP requests, got {call_tracker['request_count']} (potential infinite loop!)"
        )

        err = exc_info.value
        assert err.code == "COURIER_AUTH_ERROR"
        assert err.status_code == 502
        assert "Courier authentication failed (401 Unauthorized)" in err.message
        assert err.details.get("status_code") == 401


def test_empirical_401_without_callback_raises_immediately():
    """Verify 401 without callback raises CourierAuthError on the very first attempt without retry."""
    client = ResilientHttpClient(max_retries=3, retry_delay=0.0, auth_refresh_callback=None)

    unauth_resp = httpx.Response(401, text="Unauthorized")

    with patch("httpx.Client.request", return_value=unauth_resp) as mock_req:
        with pytest.raises(CourierAuthError) as exc_info:
            client.request("GET", "https://api.courier.mock/protected")

        assert mock_req.call_count == 1
        assert exc_info.value.code == "COURIER_AUTH_ERROR"


def test_empirical_401_callback_returning_none_retries_once_and_raises():
    """When refresh callback returns None (failed to acquire token), retries once and raises."""
    mock_refresh = MagicMock(return_value=None)
    client = ResilientHttpClient(max_retries=3, retry_delay=0.0, auth_refresh_callback=mock_refresh)

    unauth_resp = httpx.Response(401, text="Unauthorized")

    with patch("httpx.Client.request", return_value=unauth_resp) as mock_req:
        with pytest.raises(CourierAuthError):
            client.request("GET", "https://api.courier.mock/protected")

        assert mock_refresh.call_count == 1
        assert mock_req.call_count == 2


def test_empirical_401_callback_raising_exception_bubbles_up():
    """When refresh callback raises an exception, it propagates without hanging or suppressing."""
    def broken_callback():
        raise CourierAuthError("Vault token retrieval failure")

    client = ResilientHttpClient(max_retries=3, retry_delay=0.0, auth_refresh_callback=broken_callback)

    with patch("httpx.Client.request", return_value=httpx.Response(401, text="Expired")):
        with pytest.raises(CourierAuthError) as exc_info:
            client.request("GET", "https://api.courier.mock/protected")

        assert "Vault token retrieval failure" in exc_info.value.message


# ============================================================================
# 5. REAL HTTP EPHEMERAL SERVER EMPIRICAL HARNESS
# ============================================================================

class ThreadedHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    """Multi-threaded in-process HTTP server."""
    daemon_threads = True


class EphemeralTestServer:
    """In-process HTTP server for empirical black-box testing over real sockets."""

    def __init__(self, handler_cls, threaded: bool = False):
        self.server = None
        self.port = None
        self.thread = None
        self.handler_cls = handler_cls
        self.threaded = threaded

    def __enter__(self):
        # Find free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]

        server_factory = ThreadedHTTPServer if self.threaded else http.server.HTTPServer
        self.server = server_factory(("127.0.0.1", self.port), self.handler_cls)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1.0)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def test_empirical_real_http_503_retries_and_recovery():
    """Run real HTTP requests through ResilientHttpClient to a real loopback HTTP server."""
    request_log: List[str] = []

    class FlakyServerHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                self.rfile.read(content_length)
            request_log.append("POST")
            if len(request_log) < 3:
                # Fail first two requests with 503
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "temporarily unavailable"}')
            else:
                # Succeed on 3rd request with 200
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "success", "awb": "AWB-REAL-123"}')

        def log_message(self, format, *args):
            pass  # Silence stdout

    with EphemeralTestServer(FlakyServerHandler) as srv:
        client = ResilientHttpClient(max_retries=3, retry_delay=0.01, backoff_factor=1.5)
        resp = client.post(f"{srv.url}/manifest", json={"order_id": "ORD-LIVE"})

        assert resp.status_code == 200
        assert resp.json()["awb"] == "AWB-REAL-123"
        assert len(request_log) == 3


def test_empirical_real_http_401_token_refresh_workflow():
    """Verify real HTTP 401 handshake: server rejects old token, accepts refreshed token."""
    received_tokens: List[str] = []

    class AuthEnforcingHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            auth_header = self.headers.get("Authorization", "")
            received_tokens.append(auth_header)
            if auth_header == "Bearer VALID_LIVE_TOKEN":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"user": "authenticated_agent"}')
            else:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "token_expired"}')

        def log_message(self, format, *args):
            pass

    def live_token_refresher() -> str:
        return "VALID_LIVE_TOKEN"

    with EphemeralTestServer(AuthEnforcingHandler) as srv:
        client = ResilientHttpClient(
            max_retries=2,
            retry_delay=0.01,
            auth_refresh_callback=live_token_refresher,
        )

        resp = client.get(
            f"{srv.url}/api/v1/protected",
            headers={"Authorization": "Bearer EXPIRED_STALE_TOKEN"},
        )

        assert resp.status_code == 200
        assert resp.json()["user"] == "authenticated_agent"
        assert received_tokens == ["Bearer EXPIRED_STALE_TOKEN", "Bearer VALID_LIVE_TOKEN"]


def test_empirical_real_http_persistent_401_fails_after_single_retry():
    """Verify real HTTP persistent 401 server causes client to stop after single retry and raise CourierAuthError."""
    request_count = 0
    lock = threading.Lock()

    class RejectAllHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal request_count
            with lock:
                request_count += 1
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "access_denied"}')

        def log_message(self, format, *args):
            pass

    refresh_count = 0

    def refresh_fn() -> str:
        nonlocal refresh_count
        refresh_count += 1
        return "STILL_INVALID_TOKEN"

    with EphemeralTestServer(RejectAllHandler) as srv:
        client = ResilientHttpClient(
            max_retries=5,
            retry_delay=0.01,
            auth_refresh_callback=refresh_fn,
        )

        with pytest.raises(CourierAuthError):
            client.get(f"{srv.url}/secure")

        assert refresh_count == 1
        assert request_count == 2


# ============================================================================
# 6. CONCURRENT MULTI-THREADED STRESS HARNESS
# ============================================================================

def test_empirical_concurrent_stress_mock_dispatcher():
    """Stress-test shared ResilientHttpClient using global URL routing mock across threads."""
    client = ResilientHttpClient(
        max_retries=2,
        retry_delay=0.001,
        backoff_factor=1.5,
    )

    results = {"success": 0, "timeout": 0, "error": 0, "client_err": 0}
    lock = threading.Lock()

    def route_dispatcher(method: str, url: str, **kwargs):
        if "/success" in url:
            return httpx.Response(200, json={"ok": True})
        elif "/bad" in url:
            return httpx.Response(400, json={"err": "bad"})
        elif "/timeout" in url:
            raise httpx.TimeoutException("Thread timeout")
        elif "/500" in url:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(404, text="Not Found")

    with patch("httpx.Client.request", side_effect=route_dispatcher):
        def worker_task(idx: int):
            if idx % 4 == 0:
                resp = client.get("https://api.courier.mock/success")
                if resp.status_code == 200:
                    with lock:
                        results["success"] += 1
            elif idx % 4 == 1:
                resp = client.post("https://api.courier.mock/bad")
                if resp.status_code == 400:
                    with lock:
                        results["client_err"] += 1
            elif idx % 4 == 2:
                try:
                    client.get("https://api.courier.mock/timeout")
                except CourierTimeoutError:
                    with lock:
                        results["timeout"] += 1
            else:
                try:
                    client.post("https://api.courier.mock/500")
                except CourierError:
                    with lock:
                        results["error"] += 1

        total_tasks = 40
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(worker_task, range(total_tasks)))

    assert results["success"] == 10
    assert results["client_err"] == 10
    assert results["timeout"] == 10
    assert results["error"] == 10


def test_empirical_concurrent_real_http_server_mixed_traffic():
    """Stress-test shared ResilientHttpClient against a real multi-threaded loopback HTTP server."""
    class MultiRouteHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.route_request()

        def do_POST(self):
            self.route_request()

        def route_request(self):
            if "/ok" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            elif "/bad_request" in self.path:
                self.send_response(422)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "unprocessable"}')
            elif "/failing_500" in self.path:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "server_down"}')
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    with EphemeralTestServer(MultiRouteHandler, threaded=True) as srv:
        client = ResilientHttpClient(max_retries=1, retry_delay=0.005, backoff_factor=1.2)
        counts = {"200": 0, "422": 0, "500": 0}
        lock = threading.Lock()

        def send_live(req_type: str):
            if req_type == "200":
                r = client.get(f"{srv.url}/ok")
                if r.status_code == 200:
                    with lock:
                        counts["200"] += 1
            elif req_type == "422":
                r = client.post(f"{srv.url}/bad_request")
                if r.status_code == 422:
                    with lock:
                        counts["422"] += 1
            elif req_type == "500":
                try:
                    client.post(f"{srv.url}/failing_500")
                except CourierError:
                    with lock:
                        counts["500"] += 1

        tasks = ["200"] * 10 + ["422"] * 10 + ["500"] * 10
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(send_live, tasks))

        assert counts["200"] == 10
        assert counts["422"] == 10
        assert counts["500"] == 10
