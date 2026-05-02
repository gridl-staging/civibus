"""Tests for the API container startup canary.

The canary is the mechanical guard against the Apr 30 incident class:
bringing up an API process against an empty/wrong DB. It must:

* exit 0 only when ``evaluate_content_health`` returns no failures
* exit 1 when failures are present (don't let the container start)
* exit 1 when the DB is unreachable past the configured deadline
* exit 0 when explicitly skipped via env (dev / fresh-DB bootstrap / CI)

These tests stub out ``get_connection`` and ``evaluate_content_health``
so the canary's flow can be exercised without a live Postgres.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


def _fresh_canary_module() -> ModuleType:
    sys.modules.pop("api.canary_check", None)
    return importlib.import_module("api.canary_check")


def test_canary_exits_zero_when_skip_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVIBUS_STARTUP_CANARY", "skip")
    canary = _fresh_canary_module()

    # If skip is honoured, get_connection MUST NOT be called — that's the
    # point of skip (e.g. fresh DB bootstrap before there's data to check).
    sentinel_called = MagicMock()
    monkeypatch.setattr(canary, "get_connection", sentinel_called)

    assert canary.main() == 0
    sentinel_called.assert_not_called()


def test_canary_exits_zero_when_health_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVIBUS_STARTUP_CANARY", raising=False)
    canary = _fresh_canary_module()

    fake_connection = MagicMock()
    fake_connection.close = MagicMock()
    monkeypatch.setattr(canary, "get_connection", lambda: fake_connection)
    monkeypatch.setattr(canary, "evaluate_content_health", lambda *a, **k: [])

    assert canary.main() == 0
    fake_connection.close.assert_called_once()


def test_canary_exits_one_when_health_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVIBUS_STARTUP_CANARY", raising=False)
    canary = _fresh_canary_module()
    from api.health_content import ContentHealthFailure

    fake_connection = MagicMock()
    fake_connection.close = MagicMock()
    monkeypatch.setattr(canary, "get_connection", lambda: fake_connection)
    monkeypatch.setattr(
        canary,
        "evaluate_content_health",
        lambda *a, **k: [ContentHealthFailure(check="cf_transaction_total", actual=0, floor=1_000_000)],
    )

    assert canary.main() == 1
    # Even on failure the connection must close, otherwise repeated boot
    # attempts leak DB connections.
    fake_connection.close.assert_called_once()


def test_canary_exits_one_when_db_unreachable_past_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVIBUS_STARTUP_CANARY", raising=False)
    # Tight deadline keeps the test fast.
    monkeypatch.setenv("CIVIBUS_STARTUP_CANARY_TIMEOUT_SECONDS", "0.5")
    canary = _fresh_canary_module()

    def _boom() -> None:
        raise RuntimeError("simulated db outage")

    monkeypatch.setattr(canary, "get_connection", _boom)
    # evaluate_content_health must not be reached because get_connection raises.
    monkeypatch.setattr(canary, "evaluate_content_health", lambda *a, **k: [])

    assert canary.main() == 1
