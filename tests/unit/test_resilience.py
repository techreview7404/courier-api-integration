"""Unit tests for ResilientHttpClient: exponential backoff, timeout retries, 4xx fail-fast, and 401 token refresh."""

from unittest.mock import MagicMock, patch
import httpx
import pytest

from app.couriers.client import ResilientHttpClient
from app.exceptions import (
    CourierAuthError,
    CourierError,
    CourierTimeoutError,
)


def test_resilient_client_success_no_retries():
    """Verify standard successful call executes once and returns response."""
    client = ResilientHttpClient(max_retries=2, retry_delay=0.0)

    mock_resp = httpx.Response(200, json={"status": "ok"})
    with patch("httpx.Client.request", return_value=mock_resp) as mock_req:
        res = client.request("GET", "https://api.example.com/test")
        assert res.status_code == 200
        assert mock_req.call_count == 1


def test_resilient_client_timeout_retries_and_exhausts():
    """Verify client retries max_retries times on timeout and then raises CourierTimeoutError."""
    client = ResilientHttpClient(max_retries=3, retry_delay=0.0, backoff_factor=1.5)

    with patch("httpx.Client.request", side_effect=httpx.TimeoutException("Read timed out")) as mock_req:
        with pytest.raises(CourierTimeoutError) as exc_info:
            client.request("POST", "https://api.example.com/orders", json={})

        # 1 initial + 3 retries = 4 total attempts
        assert mock_req.call_count == 4
        err = exc_info.value
        assert err.code == "COURIER_TIMEOUT"
        assert err.status_code == 504
        assert "timed out after 3 retries" in err.message


def test_resilient_client_timeout_succeeds_on_retry():
    """Verify client recovers when a timeout succeeds on subsequent retry."""
    client = ResilientHttpClient(max_retries=2, retry_delay=0.0)

    success_resp = httpx.Response(200, json={"order_id": "ORD-123"})
    # Fail twice with timeout, then succeed
    side_effects = [
        httpx.TimeoutException("Timeout 1"),
        httpx.TimeoutException("Timeout 2"),
        success_resp,
    ]

    with patch("httpx.Client.request", side_effect=side_effects) as mock_req:
        res = client.request("GET", "https://api.example.com/orders/ORD-123")
        assert res.status_code == 200
        assert mock_req.call_count == 3
        assert res.json()["order_id"] == "ORD-123"


def test_resilient_client_5xx_server_error_retries_and_exhausts():
    """Verify client retries on 500/502/503/504 errors and raises CourierError when exhausted."""
    client = ResilientHttpClient(max_retries=2, retry_delay=0.0)

    error_resp = httpx.Response(503, text="Service Unavailable")
    with patch("httpx.Client.request", return_value=error_resp) as mock_req:
        with pytest.raises(CourierError) as exc_info:
            client.request("POST", "https://api.example.com/manifest")

        # 1 initial + 2 retries = 3 attempts
        assert mock_req.call_count == 3
        err = exc_info.value
        assert err.code == "COURIER_ERROR"
        assert err.status_code == 502
        assert "503" in err.message


def test_resilient_client_connection_error_retries():
    """Verify client retries on TCP network connection failures."""
    client = ResilientHttpClient(max_retries=2, retry_delay=0.0)

    with patch("httpx.Client.request", side_effect=httpx.ConnectError("Connection refused")) as mock_req:
        with pytest.raises(CourierError) as exc_info:
            client.request("GET", "https://api.example.com/health")

        assert mock_req.call_count == 3
        assert "network failure" in exc_info.value.message


def test_resilient_client_4xx_fail_fast_no_retries():
    """Verify client fails fast on 4xx errors (e.g. 400, 404, 422) without retrying."""
    client = ResilientHttpClient(max_retries=3, retry_delay=0.0)

    bad_request_resp = httpx.Response(400, json={"error": "Bad Request"})
    with patch("httpx.Client.request", return_value=bad_request_resp) as mock_req:
        res = client.request("POST", "https://api.example.com/orders")
        assert res.status_code == 400
        # Exactly 1 attempt, zero retries
        assert mock_req.call_count == 1


def test_resilient_client_401_transparent_token_refresh_success():
    """Verify 401 Unauthorized triggers auth refresh callback and retries once with new token."""
    mock_auth_callback = MagicMock(return_value="NEW_BEARER_TOKEN")
    client = ResilientHttpClient(
        max_retries=2,
        retry_delay=0.0,
        auth_refresh_callback=mock_auth_callback,
    )

    unauth_resp = httpx.Response(401, text="Authentication credentials were not provided.")
    success_resp = httpx.Response(200, json={"data": "authorized"})

    with patch("httpx.Client.request", side_effect=[unauth_resp, success_resp]) as mock_req:
        res = client.request(
            "GET",
            "https://api.example.com/protected",
            headers={"Authorization": "Bearer OLD_EXPIRED_TOKEN"},
        )
        assert res.status_code == 200
        assert mock_auth_callback.call_count == 1
        assert mock_req.call_count == 2

        # Check that second call used the refreshed token
        second_call_headers = mock_req.call_args_list[1][1].get("headers", {})
        assert second_call_headers.get("Authorization") == "Bearer NEW_BEARER_TOKEN"


def test_resilient_client_401_token_refresh_exhausts_and_raises():
    """Verify that if the retried request also returns 401, it raises CourierAuthError without infinite loop."""
    mock_auth_callback = MagicMock(return_value="RENEWED_TOKEN")
    client = ResilientHttpClient(
        max_retries=2,
        retry_delay=0.0,
        auth_refresh_callback=mock_auth_callback,
    )

    unauth_resp_1 = httpx.Response(401, text="Token Expired")
    unauth_resp_2 = httpx.Response(401, text="Token Still Invalid")

    with patch("httpx.Client.request", side_effect=[unauth_resp_1, unauth_resp_2]) as mock_req:
        with pytest.raises(CourierAuthError) as exc_info:
            client.request("GET", "https://api.example.com/protected")

        assert mock_auth_callback.call_count == 1
        assert mock_req.call_count == 2
        assert exc_info.value.code == "COURIER_AUTH_ERROR"
        assert exc_info.value.status_code == 502


def test_resilient_client_401_without_callback_raises_auth_error():
    """Verify 401 without refresh callback immediately raises CourierAuthError."""
    client = ResilientHttpClient(max_retries=2, retry_delay=0.0, auth_refresh_callback=None)

    unauth_resp = httpx.Response(401, text="Unauthorized")
    with patch("httpx.Client.request", return_value=unauth_resp) as mock_req:
        with pytest.raises(CourierAuthError) as exc_info:
            client.request("GET", "https://api.example.com/resource")

        assert mock_req.call_count == 1
        assert exc_info.value.code == "COURIER_AUTH_ERROR"


def test_resilient_client_exponential_backoff_delays():
    """Verify backoff sleep intervals follow initial_delay * (backoff_factor ** attempt)."""
    client = ResilientHttpClient(max_retries=3, retry_delay=1.0, backoff_factor=2.0)

    with patch("httpx.Client.request", side_effect=httpx.TimeoutException("Timeout")):
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(CourierTimeoutError):
                client.request("GET", "https://api.example.com/test")

            # Delays should be 1.0 * (2^0) = 1.0, 1.0 * (2^1) = 2.0, 1.0 * (2^2) = 4.0
            assert mock_sleep.call_count == 3
            delays = [call[0][0] for call in mock_sleep.call_args_list]
            assert delays == [1.0, 2.0, 4.0]


def test_resilient_client_convenience_methods():
    """Verify get, post, put, delete, and generic request methods route properly."""
    client = ResilientHttpClient(max_retries=1, retry_delay=0.0)
    mock_resp = httpx.Response(200, json={"ok": True})

    with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
        res = client.get("https://api.example.com/get")
        assert res.status_code == 200
        mock_get.assert_called_once()

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        res = client.post("https://api.example.com/post", json={"a": 1})
        assert res.status_code == 200
        mock_post.assert_called_once()

    with patch("httpx.Client.put", return_value=mock_resp) as mock_put:
        res = client.put("https://api.example.com/put", json={"b": 2})
        assert res.status_code == 200
        mock_put.assert_called_once()

    with patch("httpx.Client.delete", return_value=mock_resp) as mock_delete:
        res = client.delete("https://api.example.com/delete")
        assert res.status_code == 200
        mock_delete.assert_called_once()

    with patch("httpx.Client.request", return_value=mock_resp) as mock_req:
        res = client.request("PATCH", "https://api.example.com/patch")
        assert res.status_code == 200
        mock_req.assert_called_once()

