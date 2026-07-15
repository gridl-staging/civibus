"""Tests for the build-provenance version probe.

The ``/health/version`` endpoint exposes the dev-repo commit SHA and build
timestamp stamped into the image at deploy time so downstream stages can detect
deploy drift. The pure ``build_version_payload`` helper is tested by injecting an
env record (no ``os.environ`` monkeypatching), mirroring the logic-in-module /
route-in-main split used by ``api/health_content.py``.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.health_version import build_version_payload


_SAMPLE_SHA = "a19ecebf4d111dbd6dfbe3e46c4fc4cf304be714"
_SAMPLE_BUILT_AT = "2026-07-14T21:20:44Z"


def _load_api_main(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Mirror api/test_health_content.py loader: env must be set before import."""
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "health-version-test-key")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", "20")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "10")
    monkeypatch.delenv("CIVIBUS_ADMIN_API_KEYS", raising=False)
    sys.modules.pop("api.main", None)
    return importlib.import_module("api.main")


def _install_fake_pool(monkeypatch: pytest.MonkeyPatch, api_main: ModuleType) -> None:
    """The version route never touches the DB; stub the pool so lifespan is inert."""

    class _FakePool:
        def connection(self):  # noqa: D401
            return MagicMock()

        def open(self, *, wait: bool) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(api_main, "_build_app_connection_pool", lambda: _FakePool())


def test_build_version_payload_echoes_env_values_byte_exactly() -> None:
    payload = build_version_payload({"CIVIBUS_GIT_SHA": _SAMPLE_SHA, "CIVIBUS_BUILT_AT": _SAMPLE_BUILT_AT})
    assert payload == {"git_sha": _SAMPLE_SHA, "built_at": _SAMPLE_BUILT_AT}


def test_build_version_payload_defaults_to_unknown_when_key_absent() -> None:
    assert build_version_payload({}) == {"git_sha": "unknown", "built_at": "unknown"}
    assert build_version_payload({"CIVIBUS_GIT_SHA": _SAMPLE_SHA}) == {
        "git_sha": _SAMPLE_SHA,
        "built_at": "unknown",
    }


def test_health_version_endpoint_returns_stamped_values(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    _install_fake_pool(monkeypatch, api_main)
    monkeypatch.setenv("CIVIBUS_GIT_SHA", _SAMPLE_SHA)
    monkeypatch.setenv("CIVIBUS_BUILT_AT", _SAMPLE_BUILT_AT)

    with TestClient(api_main.create_app()) as client:
        response = client.get("/health/version")

    assert response.status_code == 200
    assert response.json() == {"git_sha": _SAMPLE_SHA, "built_at": _SAMPLE_BUILT_AT}


def test_health_version_endpoint_reports_unknown_when_unstamped(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    _install_fake_pool(monkeypatch, api_main)
    monkeypatch.delenv("CIVIBUS_GIT_SHA", raising=False)
    monkeypatch.delenv("CIVIBUS_BUILT_AT", raising=False)

    with TestClient(api_main.create_app()) as client:
        response = client.get("/health/version")

    assert response.status_code == 200
    assert response.json() == {"git_sha": "unknown", "built_at": "unknown"}


def test_health_version_excluded_from_openapi_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    _install_fake_pool(monkeypatch, api_main)

    with TestClient(api_main.create_app()) as client:
        spec = client.get("/openapi.json").json()

    assert "/health/version" not in spec["paths"]
