from __future__ import annotations

from collections.abc import Generator
from contextlib import ExitStack
import os

import psycopg
from fastapi import HTTPException, Request
from psycopg_pool import PoolTimeout

_API_STATEMENT_TIMEOUT_MS_ENV_VAR = "CIVIBUS_API_STATEMENT_TIMEOUT_MS"
_API_EXPORT_STATEMENT_TIMEOUT_MS_ENV_VAR = "CIVIBUS_API_EXPORT_STATEMENT_TIMEOUT_MS"
_DEFAULT_API_STATEMENT_TIMEOUT_MS = 10_000
_DEFAULT_API_EXPORT_STATEMENT_TIMEOUT_MS = 30_000
_PUBLIC_EXPORT_PATHS = {"/public/v1/federal/export.json", "/public/v1/federal/export.csv"}


def _positive_int_env_or_default(env_var_name: str, *, default: int) -> int:
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None:
        return default
    try:
        parsed_value = int(raw_env_value)
    except ValueError as exc:
        raise RuntimeError(f"{env_var_name} must be set to a positive integer") from exc
    if parsed_value <= 0:
        raise RuntimeError(f"{env_var_name} must be set to a positive integer")
    return parsed_value


def _statement_timeout_ms_for_request(request: Request) -> int:
    if request.url.path in _PUBLIC_EXPORT_PATHS:
        return _positive_int_env_or_default(
            _API_EXPORT_STATEMENT_TIMEOUT_MS_ENV_VAR,
            default=_DEFAULT_API_EXPORT_STATEMENT_TIMEOUT_MS,
        )
    return _positive_int_env_or_default(
        _API_STATEMENT_TIMEOUT_MS_ENV_VAR,
        default=_DEFAULT_API_STATEMENT_TIMEOUT_MS,
    )


def get_db(request: Request) -> Generator[psycopg.Connection, None, None]:
    with ExitStack() as stack:
        try:
            connection = stack.enter_context(request.app.state.db_pool.connection())
            connection.execute(f"SET LOCAL statement_timeout = {_statement_timeout_ms_for_request(request)}")
        except (psycopg.Error, PoolTimeout) as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        try:
            yield connection
        except psycopg.errors.QueryCanceled as exc:
            raise HTTPException(status_code=504, detail="Database query exceeded the request time limit") from exc
