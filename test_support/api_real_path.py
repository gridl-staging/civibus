"""Shared real-path API test environment helpers."""

from __future__ import annotations

import importlib
import os
import sys

from fastapi.testclient import TestClient

PUBLIC_API_KEY = "stage1-public-key"
ADMIN_API_KEY = "stage1-admin-key"

_REAL_PATH_ENVIRONMENT = {
    "CIVIBUS_ENV": "production",
    "CIVIBUS_API_KEYS": PUBLIC_API_KEY,
    "CIVIBUS_ADMIN_API_KEYS": ADMIN_API_KEY,
    "CIVIBUS_RATE_LIMIT_REQUESTS": "100",
    "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS": "60",
}


def resolve_postgres_password() -> str:
    return os.getenv("POSTGRES_PASSWORD", "civibus_dev")


def real_path_environment_values() -> dict[str, str]:
    return {
        **_REAL_PATH_ENVIRONMENT,
        "POSTGRES_USER": os.getenv("POSTGRES_USER", "civibus"),
        "POSTGRES_PASSWORD": resolve_postgres_password(),
        "POSTGRES_DB": os.getenv("POSTGRES_DB", "civibus"),
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "POSTGRES_PORT": os.getenv("POSTGRES_PORT", "5433"),
    }


def configure_real_path_environment() -> dict[str, str | None]:
    environment_overrides = real_path_environment_values()
    previous_environment = {env_var_name: os.environ.get(env_var_name) for env_var_name in environment_overrides}
    os.environ.update(environment_overrides)
    return previous_environment


def restore_environment(previous_environment: dict[str, str | None]) -> None:
    for env_var_name, previous_value in previous_environment.items():
        if previous_value is None:
            os.environ.pop(env_var_name, None)
            continue
        os.environ[env_var_name] = previous_value


def build_public_headers() -> dict[str, str]:
    return {"X-API-Key": PUBLIC_API_KEY}


def build_admin_headers() -> dict[str, str]:
    return {"X-API-Key": ADMIN_API_KEY}


def build_real_path_client() -> tuple[TestClient, dict[str, str], dict[str, str]]:
    sys.modules.pop("api.main", None)
    api_main = importlib.import_module("api.main")
    client = TestClient(api_main.create_app())

    assert client.app.dependency_overrides == {}

    return client, build_public_headers(), build_admin_headers()
