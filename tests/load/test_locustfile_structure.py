"""Structural tests for the load-test Locust user."""

from __future__ import annotations

import importlib
import inspect
import sys
from types import ModuleType
from pathlib import Path

import pytest


def _load_module(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, type]:
    """Import the Locust harness with a lightweight fake `locust` module."""
    fake_locust = ModuleType("locust")

    class FakeHttpUser:
        pass

    def fake_between(_minimum_wait: float, _maximum_wait: float):
        return (1, 3)

    def fake_task(function=None):
        def decorator(task_function):
            setattr(task_function, "locust_task_weight", 1)
            return task_function

        return decorator(function) if function is not None else decorator

    fake_locust.HttpUser = FakeHttpUser
    fake_locust.between = fake_between
    fake_locust.task = fake_task
    monkeypatch.setitem(sys.modules, "locust", fake_locust)
    sys.modules.pop("tests.load.locustfile", None)

    return importlib.import_module("tests.load.locustfile"), FakeHttpUser


def test_civibus_user_imports_and_subclasses_http_user(monkeypatch: pytest.MonkeyPatch) -> None:
    module, expected_http_user = _load_module(monkeypatch)

    assert hasattr(module, "CivibusUser")
    assert issubclass(module.CivibusUser, expected_http_user)


def test_civibus_user_defines_on_start(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = _load_module(monkeypatch)

    assert "on_start" in module.CivibusUser.__dict__
    assert callable(module.CivibusUser.__dict__["on_start"])


def test_locust_tasks_do_not_reference_admin_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = _load_module(monkeypatch)
    civibus_user = module.CivibusUser

    for name, member in civibus_user.__dict__.items():
        if not callable(member):
            continue

        if not getattr(member, "locust_task_weight", None):
            continue

        normalized_name = name.lower()
        assert "_er_" not in normalized_name
        assert not normalized_name.startswith("er_")
        assert not normalized_name.endswith("_er")
        assert "/er/" not in inspect.getsource(member)


def test_load_readme_documents_api_runtime_environment_contract() -> None:
    readme_text = Path("tests/load/README.md").read_text(encoding="utf-8")

    for required_fragment in (
        "CIVIBUS_API_KEYS",
        "CIVIBUS_RATE_LIMIT_REQUESTS",
        "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS",
        "POSTGRES_PASSWORD",
        "make api-dev",
    ):
        assert required_fragment in readme_text
