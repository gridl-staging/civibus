"""
Stub summary for mar19_02_backend_hardening/civibus_dev/api/middleware/access.py.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request, status

_API_KEYS_ENV_VAR = "CIVIBUS_API_KEYS"
ADMIN_API_KEYS_ENV_VAR = "CIVIBUS_ADMIN_API_KEYS"
API_KEY_HEADER_NAME = "X-API-Key"
_AUTH_FAILURE_DETAIL = "Invalid or missing API key"
_DEVELOPMENT_ENVIRONMENT = "development"
RATE_LIMIT_REQUESTS_ENV_VAR = "CIVIBUS_RATE_LIMIT_REQUESTS"
RATE_LIMIT_WINDOW_SECONDS_ENV_VAR = "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS"
_RATE_LIMIT_EXCEEDED_DETAIL = "Rate limit exceeded"
_RETRY_AFTER_HEADER = "Retry-After"
_RATE_LIMIT_REQUESTS_STATE_KEY = "rate_limit_requests"
_RATE_LIMIT_WINDOW_SECONDS_STATE_KEY = "rate_limit_window_seconds"
_RATE_LIMIT_BUCKETS_STATE_KEY = "rate_limit_buckets"
_RATE_LIMIT_LOCK_STATE_KEY = "rate_limit_lock"


@dataclass
class _FixedWindowBucket:
    window_started_at: int
    request_count: int


def _parse_api_keys(raw_api_keys: str | None) -> set[str]:
    if raw_api_keys is None:
        return set()
    return {api_key.strip() for api_key in raw_api_keys.split(",") if api_key.strip()}


def _configured_api_keys(env_var_name: str = _API_KEYS_ENV_VAR) -> set[str]:
    return _parse_api_keys(os.getenv(env_var_name))


def _current_environment() -> str:
    return os.getenv("CIVIBUS_ENV", "").strip().lower()


def _allows_unauthenticated_development_requests(configured_keys: set[str]) -> bool:
    return _current_environment() == _DEVELOPMENT_ENVIRONMENT and not configured_keys


def require_api_keys_configured_for_environment() -> None:
    configured_keys = _configured_api_keys()
    if _allows_unauthenticated_development_requests(configured_keys):
        return
    if not configured_keys:
        raise RuntimeError(
            f"{_API_KEYS_ENV_VAR} must be set to one or more comma-separated API keys outside development"
        )


def initialize_rate_limiter_state(
    app_state: object,
    *,
    max_requests: int,
    window_seconds: int,
) -> None:
    setattr(app_state, _RATE_LIMIT_REQUESTS_STATE_KEY, max_requests)
    setattr(app_state, _RATE_LIMIT_WINDOW_SECONDS_STATE_KEY, window_seconds)
    setattr(app_state, _RATE_LIMIT_BUCKETS_STATE_KEY, {})
    setattr(app_state, _RATE_LIMIT_LOCK_STATE_KEY, threading.Lock())


def _current_epoch_seconds() -> int:
    return int(time.time())


def _rate_limit_state_for_request(
    request: Request,
) -> tuple[int, int, dict[str, _FixedWindowBucket], threading.Lock]:
    max_requests = getattr(request.app.state, _RATE_LIMIT_REQUESTS_STATE_KEY, None)
    window_seconds = getattr(request.app.state, _RATE_LIMIT_WINDOW_SECONDS_STATE_KEY, None)
    buckets = getattr(request.app.state, _RATE_LIMIT_BUCKETS_STATE_KEY, None)
    lock = getattr(request.app.state, _RATE_LIMIT_LOCK_STATE_KEY, None)
    if not isinstance(max_requests, int) or max_requests <= 0:
        raise RuntimeError("Rate limiter is not configured: invalid max requests state")
    if not isinstance(window_seconds, int) or window_seconds <= 0:
        raise RuntimeError("Rate limiter is not configured: invalid window seconds state")
    if not isinstance(buckets, dict):
        raise RuntimeError("Rate limiter is not configured: invalid buckets state")
    if lock is None:
        raise RuntimeError("Rate limiter is not configured: missing state lock")
    return max_requests, window_seconds, buckets, lock


def _retry_after_seconds(window_started_at: int, window_seconds: int, now_seconds: int) -> int:
    elapsed_seconds = now_seconds - window_started_at
    return max(window_seconds - elapsed_seconds, 1)


def _enforce_fixed_window_rate_limit(
    request: Request,
    api_key: str,
) -> None:
    _enforce_fixed_window_rate_limit_for_key(request=request, key=api_key)


def _enforce_fixed_window_rate_limit_for_key(
    request: Request,
    key: str,
) -> None:
    """Enforce the shared fixed-window rate limit for a caller key."""
    max_requests, window_seconds, buckets, lock = _rate_limit_state_for_request(request)
    with lock:
        now_seconds = _current_epoch_seconds()
        current_bucket = buckets.get(key)
        if current_bucket is None or now_seconds - current_bucket.window_started_at >= window_seconds:
            buckets[key] = _FixedWindowBucket(window_started_at=now_seconds, request_count=1)
            return
        if current_bucket.request_count < max_requests:
            current_bucket.request_count += 1
            return
        retry_after_seconds = _retry_after_seconds(
            window_started_at=current_bucket.window_started_at,
            window_seconds=window_seconds,
            now_seconds=now_seconds,
        )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=_RATE_LIMIT_EXCEEDED_DETAIL,
        headers={_RETRY_AFTER_HEADER: str(retry_after_seconds)},
    )


def enforce_public_ip_rate_limit(request: Request) -> None:
    """Rate-limit authless public routes by client host."""
    if request.client is None:
        return
    _enforce_fixed_window_rate_limit_for_key(request=request, key=request.client.host)


def _require_api_key_from_config(
    request: Request,
    x_api_key: str | None,
    *,
    env_var_name: str,
) -> None:
    configured_keys = _configured_api_keys(env_var_name)
    if _allows_unauthenticated_development_requests(configured_keys):
        return
    if x_api_key is None or x_api_key not in configured_keys:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILURE_DETAIL)
    _enforce_fixed_window_rate_limit(request=request, api_key=x_api_key)


def require_authorized_request(
    request: Request,
    x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER_NAME),
) -> None:
    _require_api_key_from_config(request, x_api_key, env_var_name=_API_KEYS_ENV_VAR)


def require_administrative_request(
    request: Request,
    x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER_NAME),
) -> None:
    _require_api_key_from_config(request, x_api_key, env_var_name=ADMIN_API_KEYS_ENV_VAR)
