from __future__ import annotations

import threading

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

import api.main as api_main
import api.middleware.access as access_middleware
from api.main import create_app

_VALID_API_KEY = "valid-key"
_SECOND_VALID_API_KEY = "second-valid-key"
_PROBE_ROUTE_PATH = "/rate-limit-probe"


def _build_probe_router() -> APIRouter:
    router = APIRouter()

    @router.get(_PROBE_ROUTE_PATH)
    def rate_limit_probe() -> dict[str, str]:
        return {"status": "ok"}

    return router


def _build_rate_limited_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_requests: int,
    window_seconds: int,
) -> TestClient:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", f"{_VALID_API_KEY},{_SECOND_VALID_API_KEY}")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", str(max_requests))
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", str(window_seconds))
    monkeypatch.setattr(api_main, "_v1_routers", lambda: (_build_probe_router(),))
    return TestClient(create_app())


def test_authenticated_rate_limit_wrapper_documents_public_reuse_contract() -> None:
    docstring = access_middleware._enforce_fixed_window_rate_limit.__doc__ or ""

    assert "authenticated API-key requests" in docstring
    assert "_enforce_fixed_window_rate_limit_for_key" in docstring
    assert "enforce_public_ip_rate_limit" in docstring
    assert "TODO" not in docstring


def test_valid_key_hits_cap_then_returns_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time_seconds = {"value": 100}
    monkeypatch.setattr(access_middleware, "_current_epoch_seconds", lambda: current_time_seconds["value"])
    client = _build_rate_limited_client(monkeypatch, max_requests=2, window_seconds=10)

    first_response = client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY})
    second_response = client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY})
    limited_response = client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY})

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert limited_response.status_code == 429
    assert limited_response.json() == {"detail": "Rate limit exceeded"}
    assert limited_response.headers["Retry-After"] == "10"


def test_second_key_isolated_and_window_reset_restores_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time_seconds = {"value": 100}
    monkeypatch.setattr(access_middleware, "_current_epoch_seconds", lambda: current_time_seconds["value"])
    client = _build_rate_limited_client(monkeypatch, max_requests=2, window_seconds=10)

    for _ in range(2):
        assert client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY}).status_code == 200
    assert client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY}).status_code == 429

    isolated_key_response = client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _SECOND_VALID_API_KEY})
    assert isolated_key_response.status_code == 200

    current_time_seconds["value"] = 111
    reset_window_response = client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY})
    assert reset_window_response.status_code == 200


def test_ip_rate_limit_keys_are_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    current_time_seconds = {"value": 100}
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", _VALID_API_KEY)
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "10")
    monkeypatch.setattr(api_main, "_v1_routers", lambda: ())
    monkeypatch.setattr(access_middleware, "_current_epoch_seconds", lambda: current_time_seconds["value"])
    app = create_app()
    request = Request({"type": "http", "app": app, "method": "GET", "path": "/public/v1/federal/officials"})

    access_middleware._enforce_fixed_window_rate_limit_for_key(request, "1.1.1.1")
    access_middleware._enforce_fixed_window_rate_limit_for_key(request, "1.1.1.1")
    with pytest.raises(access_middleware.HTTPException) as exc_info:
        access_middleware._enforce_fixed_window_rate_limit_for_key(request, "1.1.1.1")

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "10"}
    access_middleware._enforce_fixed_window_rate_limit_for_key(request, "2.2.2.2")


def test_fresh_app_instance_starts_with_fresh_rate_limit_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time_seconds = {"value": 500}
    monkeypatch.setattr(access_middleware, "_current_epoch_seconds", lambda: current_time_seconds["value"])
    first_client = _build_rate_limited_client(monkeypatch, max_requests=1, window_seconds=60)

    assert first_client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY}).status_code == 200
    assert first_client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY}).status_code == 429

    second_client = _build_rate_limited_client(monkeypatch, max_requests=1, window_seconds=60)
    fresh_app_response = second_client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY})
    assert fresh_app_response.status_code == 200


@pytest.mark.parametrize("request_headers", [{}, {"X-API-Key": "invalid-key"}])
def test_missing_or_invalid_key_does_not_consume_valid_key_quota(
    monkeypatch: pytest.MonkeyPatch,
    request_headers: dict[str, str],
) -> None:
    current_time_seconds = {"value": 900}
    monkeypatch.setattr(access_middleware, "_current_epoch_seconds", lambda: current_time_seconds["value"])
    client = _build_rate_limited_client(monkeypatch, max_requests=1, window_seconds=30)

    unauthorized_response = client.get(f"/v1{_PROBE_ROUTE_PATH}", headers=request_headers)
    assert unauthorized_response.status_code == 401
    assert unauthorized_response.json() == {"detail": "Invalid or missing API key"}
    assert "Retry-After" not in unauthorized_response.headers

    first_valid_response = client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY})
    second_valid_response = client.get(f"/v1{_PROBE_ROUTE_PATH}", headers={"X-API-Key": _VALID_API_KEY})

    assert first_valid_response.status_code == 200
    assert second_valid_response.status_code == 429


def test_same_key_requests_are_serialized_within_a_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CoordinatedBucket:
        def __init__(self) -> None:
            self.window_started_at = 100
            self._request_count = 1
            self.first_read_started = threading.Event()
            self.release_first_read = threading.Event()
            self.second_read_started = threading.Event()
            self._reads = 0

        @property
        def request_count(self) -> int:
            self._reads += 1
            if self._reads == 1:
                self.first_read_started.set()
                assert self.release_first_read.wait(timeout=1)
            else:
                self.second_read_started.set()
            return self._request_count

        @request_count.setter
        def request_count(self, value: int) -> None:
            self._request_count = value

    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", _VALID_API_KEY)
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "30")
    monkeypatch.setattr(api_main, "_v1_routers", lambda: ())
    monkeypatch.setattr(access_middleware, "_current_epoch_seconds", lambda: 100)
    app = create_app()

    coordinated_bucket = CoordinatedBucket()
    app.state.rate_limit_buckets[_VALID_API_KEY] = coordinated_bucket
    request = Request({"type": "http", "app": app, "method": "GET", "path": "/v1/rate-limit-probe"})
    second_worker_started = threading.Event()
    results: list[int] = []

    def worker(started_event: threading.Event | None = None) -> None:
        if started_event is not None:
            started_event.set()
        try:
            access_middleware._enforce_fixed_window_rate_limit(request, _VALID_API_KEY)
            results.append(200)
        except access_middleware.HTTPException as exc:
            results.append(exc.status_code)

    first_thread = threading.Thread(target=worker)
    first_thread.start()
    assert coordinated_bucket.first_read_started.wait(timeout=1)

    second_thread = threading.Thread(target=worker, args=(second_worker_started,))
    second_thread.start()
    assert second_worker_started.wait(timeout=1)
    assert not coordinated_bucket.second_read_started.wait(timeout=0.1)

    coordinated_bucket.release_first_read.set()
    first_thread.join(timeout=1)
    second_thread.join(timeout=1)

    assert sorted(results) == [200, 429]
    assert coordinated_bucket._request_count == 2
