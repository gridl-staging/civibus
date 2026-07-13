"""
Stub summary for jun04_3pm_5_launch_gate_and_golive/civibus_dev/api/main.py.
"""

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import psycopg
from psycopg_pool import ConnectionPool

from api import health_content as _health_content_module

from api.middleware import (
    API_KEY_HEADER_NAME,
    RATE_LIMIT_REQUESTS_ENV_VAR,
    RATE_LIMIT_WINDOW_SECONDS_ENV_VAR,
    REQUEST_ID_HEADER_NAME,
    RequestLoggingMiddleware,
    configure_api_json_logger,
    initialize_rate_limiter_state,
    require_administrative_request,
    require_api_keys_configured_for_environment,
    require_authorized_request,
)
from api.routes.campaign_finance import router as campaign_finance_router
from api.routes.civics import router as civics_router
from api.routes.donors import router as donors_router
from api.routes.entity_resolution import router as entity_resolution_router
from api.routes.entities import router as entities_router
from api.routes.graph import router as graph_router
from api.routes.investigate import router as investigate_router
from api.routes.metadata import router as metadata_router
from api.routes.portrait_admin import router as portrait_admin_router
from api.routes.property import router as property_router
from api.routes.public_federal import router as public_federal_router
from api.routes.search import router as search_router
from core.db import build_connection_parameters
from core.graph import age_post_connect

_DB_POOL_MIN_SIZE_ENV_VAR = "CIVIBUS_API_DB_POOL_MIN_SIZE"
_DB_POOL_MAX_SIZE_ENV_VAR = "CIVIBUS_API_DB_POOL_MAX_SIZE"
_DB_POOL_TIMEOUT_SECONDS_ENV_VAR = "CIVIBUS_API_DB_POOL_TIMEOUT_SECONDS"
_DEFAULT_DB_POOL_MIN_SIZE = 2
_DEFAULT_DB_POOL_MAX_SIZE = 8
_DEFAULT_DB_POOL_TIMEOUT_SECONDS = 5.0


def _v1_routers() -> tuple[APIRouter, ...]:
    return (
        entities_router,
        campaign_finance_router,
        civics_router,
        metadata_router,
        property_router,
        investigate_router,
        graph_router,
        search_router,
        donors_router,
    )


def _administrative_v1_routers() -> tuple[APIRouter, ...]:
    return (entity_resolution_router, portrait_admin_router)


def _public_routers() -> tuple[APIRouter, ...]:
    return (public_federal_router,)


def _include_versioned_routers(
    app: FastAPI,
    *,
    routers: tuple[APIRouter, ...],
    dependency: object,
) -> None:
    for router in routers:
        app.include_router(router, prefix="/v1", dependencies=[Depends(dependency)])


def _include_public_routers(app: FastAPI, *, routers: tuple[APIRouter, ...]) -> None:
    # Authless by design — do NOT add a dependency here. These routers own the
    # public ``/public/v1`` surface and must serve nonpartisan public-record data
    # with no API key. Auth-gated routes belong on ``_include_versioned_routers``.
    for router in routers:
        app.include_router(router)


def _parse_positive_int_env_var(env_var_name: str) -> int:
    error_message = f"{env_var_name} must be set to a positive integer"
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None:
        raise RuntimeError(error_message)
    try:
        parsed_value = int(raw_env_value)
    except ValueError as exc:
        raise RuntimeError(error_message) from exc
    if parsed_value <= 0:
        raise RuntimeError(error_message)
    return parsed_value


def _parse_optional_positive_int_env_var(env_var_name: str, *, default: int) -> int:
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


def _parse_optional_positive_float_env_var(env_var_name: str, *, default: float) -> float:
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None:
        return default
    try:
        parsed_value = float(raw_env_value)
    except ValueError as exc:
        raise RuntimeError(f"{env_var_name} must be set to a positive number") from exc
    if parsed_value <= 0:
        raise RuntimeError(f"{env_var_name} must be set to a positive number")
    return parsed_value


def _rate_limit_config_from_env() -> tuple[int, int]:
    return (
        _parse_positive_int_env_var(RATE_LIMIT_REQUESTS_ENV_VAR),
        _parse_positive_int_env_var(RATE_LIMIT_WINDOW_SECONDS_ENV_VAR),
    )


def _strip_cors_headers(response: Response) -> None:
    # CORSMiddleware still adds response headers for disallowed origins, so remove
    # them to keep the app-factory contract fail-closed outside the configured origin.
    cors_header_names = [
        header_name for header_name in response.headers.keys() if header_name.lower().startswith("access-control-")
    ]
    for header_name in cors_header_names:
        del response.headers[header_name]

    vary_header = response.headers.get("vary")
    if vary_header is None:
        return
    remaining_vary_values = [
        value for value in (part.strip() for part in vary_header.split(",")) if value and value.lower() != "origin"
    ]
    if remaining_vary_values:
        response.headers["vary"] = ", ".join(remaining_vary_values)
        return
    del response.headers["vary"]


def _build_app_connection_pool() -> ConnectionPool:
    """Build the API request pool with bounded checkout and stale-connection checks."""

    def _configure_pool_connection(connection: psycopg.Connection) -> None:
        original_autocommit = connection.autocommit
        connection.autocommit = True
        try:
            age_post_connect(connection)
        finally:
            connection.autocommit = original_autocommit

    min_size = _parse_optional_positive_int_env_var(_DB_POOL_MIN_SIZE_ENV_VAR, default=_DEFAULT_DB_POOL_MIN_SIZE)
    max_size = _parse_optional_positive_int_env_var(_DB_POOL_MAX_SIZE_ENV_VAR, default=_DEFAULT_DB_POOL_MAX_SIZE)
    if min_size > max_size:
        raise RuntimeError(f"{_DB_POOL_MIN_SIZE_ENV_VAR} must be less than or equal to {_DB_POOL_MAX_SIZE_ENV_VAR}")

    connection_pool = ConnectionPool(
        kwargs=build_connection_parameters(),
        min_size=min_size,
        max_size=max_size,
        timeout=_parse_optional_positive_float_env_var(
            _DB_POOL_TIMEOUT_SECONDS_ENV_VAR,
            default=_DEFAULT_DB_POOL_TIMEOUT_SECONDS,
        ),
        configure=_configure_pool_connection,
        check=ConnectionPool.check_connection,
        open=False,
    )
    # Keep DB outages as request-time failures instead of startup-time crashes.
    connection_pool.open(wait=False)
    return connection_pool


@asynccontextmanager
async def _app_lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_pool = _build_app_connection_pool()
    app.state.db_pool = db_pool
    try:
        yield
    finally:
        db_pool.close()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=_app_lifespan)
    configure_api_json_logger()
    require_api_keys_configured_for_environment()
    rate_limit_requests, rate_limit_window_seconds = _rate_limit_config_from_env()
    initialize_rate_limiter_state(
        app.state,
        max_requests=rate_limit_requests,
        window_seconds=rate_limit_window_seconds,
    )
    environment = os.getenv("CIVIBUS_ENV", "").strip().lower()
    configured_cors_origin = os.getenv("CIVIBUS_CORS_ORIGIN", "").strip()
    if environment == "development":
        # Enable permissive cross-origin access only for explicit local development.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    elif configured_cors_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[configured_cors_origin],
            allow_methods=["GET"],
            allow_headers=[API_KEY_HEADER_NAME, REQUEST_ID_HEADER_NAME],
            expose_headers=[REQUEST_ID_HEADER_NAME],
        )

        @app.middleware("http")
        async def remove_cors_headers_for_disallowed_origin(request: Request, call_next) -> Response:
            response = await call_next(request)
            request_origin = request.headers.get("origin")
            if request_origin is not None and request_origin != configured_cors_origin:
                _strip_cors_headers(response)
            return response

    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _content_health_cache: dict[str, object] = {"response": None, "timestamp": 0.0}
    _CONTENT_HEALTH_TTL_SECONDS = float(os.getenv("CIVIBUS_HEALTH_CONTENT_TTL_SECONDS", "300"))

    @app.get("/health/content")
    def content_health(request: Request) -> Response:
        """Content-aware probe for external uptime monitors.

        Returns 200 when all DB content floors are met, 503 (with
        per-check details) otherwise. See ``api/health_content.py`` for
        the rationale (Apr 30 wrong-volume-bootstrap incident). The
        endpoint deliberately lives outside ``/v1`` so monitors can hit
        it without rotating API keys; it exposes only row-count metadata
        which is non-sensitive.
        """
        now = time.monotonic()
        cached = _content_health_cache["response"]
        cached_at = _content_health_cache["timestamp"]
        if cached is not None and (now - cached_at) < _CONTENT_HEALTH_TTL_SECONDS:  # type: ignore[operator]
            return cached  # type: ignore[return-value]

        pool: ConnectionPool = request.app.state.db_pool
        try:
            with pool.connection() as connection:
                failures = _health_content_module.evaluate_content_health(connection)
        except Exception as exc:  # noqa: BLE001 — probe must catch broadly.
            return JSONResponse(
                status_code=503,
                content={
                    "healthy": False,
                    "error": "db_unreachable",
                    "detail": str(exc),
                },
            )
        if failures:
            response = JSONResponse(
                status_code=503,
                content={
                    "healthy": False,
                    "failures": [{"check": f.check, "actual": f.actual, "floor": f.floor} for f in failures],
                },
            )
        else:
            response = JSONResponse(status_code=200, content={"healthy": True})
        _content_health_cache["response"] = response
        _content_health_cache["timestamp"] = now
        return response

    @app.get("/provenance/people-enrichment")
    def people_enrichment_provenance_contract() -> dict[str, str]:
        return {
            "source": "people-enrichment",
            "contract": "core.people.enrichment.orchestrator",
        }

    _include_versioned_routers(app, routers=_v1_routers(), dependency=require_authorized_request)
    _include_versioned_routers(app, routers=_administrative_v1_routers(), dependency=require_administrative_request)
    _include_public_routers(app, routers=_public_routers())

    return app


app = create_app()
