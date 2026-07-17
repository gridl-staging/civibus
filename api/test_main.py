import importlib
import ast
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from api.deps import get_db
from api.middleware.logging import RequestLoggingMiddleware

_STAGE_1_AUTH_TEST_MODULES = ("api/test_auth.py", "api/test_main.py", "api/test_cors.py")
_RATE_LIMIT_REQUESTS_ENV_VAR = "CIVIBUS_RATE_LIMIT_REQUESTS"
_RATE_LIMIT_WINDOW_SECONDS_ENV_VAR = "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS"
_API_LOGGER_NAME = "civibus.api"


def _load_api_main(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_keys: str = "main-test-key",
    admin_api_keys: str | None = None,
    environment: str = "production",
    rate_limit_requests: str = "5",
    rate_limit_window_seconds: str = "10",
) -> ModuleType:
    monkeypatch.setenv("CIVIBUS_ENV", environment)
    monkeypatch.setenv("CIVIBUS_API_KEYS", api_keys)
    monkeypatch.setenv(_RATE_LIMIT_REQUESTS_ENV_VAR, rate_limit_requests)
    monkeypatch.setenv(_RATE_LIMIT_WINDOW_SECONDS_ENV_VAR, rate_limit_window_seconds)
    if admin_api_keys is None:
        monkeypatch.delenv("CIVIBUS_ADMIN_API_KEYS", raising=False)
    else:
        monkeypatch.setenv("CIVIBUS_ADMIN_API_KEYS", admin_api_keys)

    sys.modules.pop("api.main", None)
    return importlib.import_module("api.main")


def build_probe_router(path: str, router_name: str) -> APIRouter:
    router = APIRouter()

    @router.get(path)
    def probe() -> dict[str, str]:
        return {"router": router_name}

    return router


def test_stage1_auth_test_modules_do_not_bootstrap_api_keys_at_import() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    for relative_path in _STAGE_1_AUTH_TEST_MODULES:
        module_source = (repository_root / relative_path).read_text(encoding="utf-8")
        module_tree = ast.parse(module_source)
        setdefault_calls = [
            node
            for node in ast.walk(module_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setdefault"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "environ"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "os"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "CIVIBUS_API_KEYS"
        ]
        assert not setdefault_calls


def test_create_app_returns_fastapi_app(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    app = api_main.create_app()

    assert isinstance(app, FastAPI)


def test_create_app_lifespan_manages_connection_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)

    pool_closed = MagicMock()
    captured_pool_kwargs: dict[str, object] = {}
    observed_autocommit_during_age_setup: list[bool] = []

    def _fake_age_post_connect(connection: SimpleNamespace) -> None:
        observed_autocommit_during_age_setup.append(connection.autocommit)

    monkeypatch.setattr(api_main, "age_post_connect", _fake_age_post_connect)

    class FakeConnectionPool:
        check_connection = staticmethod(lambda _connection: None)

        def __init__(self, **kwargs: object) -> None:
            captured_pool_kwargs.update(kwargs)

        def open(self, *, wait: bool) -> None:
            captured_pool_kwargs["open_wait"] = wait

        def close(self) -> None:
            pool_closed()

    monkeypatch.setattr(api_main, "ConnectionPool", FakeConnectionPool, raising=False)

    app = api_main.create_app()

    assert not hasattr(app.state, "db_pool")
    with TestClient(app) as client:
        assert isinstance(client.app.state.db_pool, FakeConnectionPool)
        assert captured_pool_kwargs["open"] is False
        assert captured_pool_kwargs["open_wait"] is False
        assert captured_pool_kwargs["min_size"] == 2
        assert captured_pool_kwargs["max_size"] == 8
        assert captured_pool_kwargs["timeout"] == 5.0
        assert captured_pool_kwargs["check"] is api_main.ConnectionPool.check_connection

    configured_connection = SimpleNamespace(autocommit=False)
    configure_callback = captured_pool_kwargs["configure"]
    assert callable(configure_callback)
    configure_callback(configured_connection)
    assert observed_autocommit_during_age_setup == [True]
    assert configured_connection.autocommit is False

    pool_closed.assert_called_once_with()


def test_create_app_connection_pool_uses_env_pool_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    monkeypatch.setenv("CIVIBUS_API_DB_POOL_MIN_SIZE", "3")
    monkeypatch.setenv("CIVIBUS_API_DB_POOL_MAX_SIZE", "10")
    monkeypatch.setenv("CIVIBUS_API_DB_POOL_TIMEOUT_SECONDS", "2.5")
    captured_pool_kwargs: dict[str, object] = {}

    class FakeConnectionPool:
        check_connection = staticmethod(lambda _connection: None)

        def __init__(self, **kwargs: object) -> None:
            captured_pool_kwargs.update(kwargs)

        def open(self, *, wait: bool) -> None:
            captured_pool_kwargs["open_wait"] = wait

    monkeypatch.setattr(api_main, "ConnectionPool", FakeConnectionPool, raising=False)

    pool = api_main._build_app_connection_pool()

    assert isinstance(pool, FakeConnectionPool)
    assert captured_pool_kwargs["min_size"] == 3
    assert captured_pool_kwargs["max_size"] == 10
    assert captured_pool_kwargs["timeout"] == 2.5
    assert captured_pool_kwargs["open_wait"] is False


def test_create_app_connection_pool_rejects_invalid_pool_size(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    monkeypatch.setenv("CIVIBUS_API_DB_POOL_MIN_SIZE", "9")
    monkeypatch.setenv("CIVIBUS_API_DB_POOL_MAX_SIZE", "8")

    with pytest.raises(RuntimeError, match="CIVIBUS_API_DB_POOL_MIN_SIZE"):
        api_main._build_app_connection_pool()


def test_create_app_keeps_api_logger_handler_count_stable_across_factory_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_main = _load_api_main(monkeypatch)
    logger = logging.getLogger(_API_LOGGER_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        api_main.create_app()
        first_handler_count = len(logger.handlers)
        api_main.create_app()
        second_handler_count = len(logger.handlers)
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate

    assert first_handler_count > 0
    assert second_handler_count == first_handler_count


def test_create_app_initializes_independent_rate_limit_state_per_app_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_main = _load_api_main(
        monkeypatch,
        rate_limit_requests="3",
        rate_limit_window_seconds="30",
    )

    first_app = api_main.create_app()
    second_app = api_main.create_app()

    assert first_app.state.rate_limit_requests == 3
    assert first_app.state.rate_limit_window_seconds == 30
    assert first_app.state.rate_limit_buckets == {}
    assert second_app.state.rate_limit_requests == 3
    assert second_app.state.rate_limit_window_seconds == 30
    assert second_app.state.rate_limit_buckets == {}

    first_app.state.rate_limit_buckets["main-test-key"] = object()
    assert second_app.state.rate_limit_buckets == {}


def test_create_app_registers_versioned_routers(monkeypatch: pytest.MonkeyPatch) -> None:
    # rate_limit_requests must exceed the number of public-key probe requests
    api_main = _load_api_main(
        monkeypatch,
        admin_api_keys="main-admin-key",
        rate_limit_requests="20",
    )
    monkeypatch.setattr(api_main, "entities_router", build_probe_router("/entities-probe", "entities"))
    monkeypatch.setattr(
        api_main,
        "campaign_finance_router",
        build_probe_router("/campaign-finance-probe", "campaign_finance"),
    )
    monkeypatch.setattr(
        api_main,
        "entity_resolution_router",
        build_probe_router("/entity-resolution-probe", "entity_resolution"),
    )
    monkeypatch.setattr(
        api_main,
        "portrait_admin_router",
        build_probe_router("/admin/portraits/probe/takedown", "portrait_admin"),
        raising=False,
    )
    monkeypatch.setattr(api_main, "property_router", build_probe_router("/property-probe", "property"))
    monkeypatch.setattr(api_main, "investigate_router", build_probe_router("/investigate-probe", "investigate"))
    monkeypatch.setattr(api_main, "graph_router", build_probe_router("/graph-probe", "graph"))
    monkeypatch.setattr(api_main, "search_router", build_probe_router("/search-probe", "search"))

    client = TestClient(api_main.create_app())
    public_request_headers = {"X-API-Key": "main-test-key"}
    admin_request_headers = {"X-API-Key": "main-admin-key"}

    assert client.get("/v1/entities-probe", headers=public_request_headers).json() == {"router": "entities"}
    assert client.get("/v1/campaign-finance-probe", headers=public_request_headers).json() == {
        "router": "campaign_finance"
    }
    assert client.get("/v1/entity-resolution-probe", headers=admin_request_headers).json() == {
        "router": "entity_resolution"
    }
    assert client.get("/v1/admin/portraits/probe/takedown", headers=admin_request_headers).json() == {
        "router": "portrait_admin"
    }
    assert client.get("/v1/property-probe", headers=public_request_headers).json() == {"router": "property"}
    assert client.get("/v1/investigate-probe", headers=public_request_headers).json() == {"router": "investigate"}
    assert client.get("/v1/graph-probe", headers=public_request_headers).json() == {"router": "graph"}
    assert client.get("/v1/search-probe", headers=public_request_headers).json() == {"router": "search"}


def test_create_app_registers_unique_expected_v1_get_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    app = api_main.create_app()

    actual_paths = {
        route.path for route in app.routes if route.path.startswith("/v1") and route.methods and "GET" in route.methods
    }
    expected_paths = {
        "/v1/person/{person_id}",
        "/v1/person/{person_id}/contribution-insights",
        "/v1/person/{person_id}/top-donors",
        "/v1/person/{person_id}/top-employers",
        "/v1/person/by-slug/{slug}",
        "/v1/org/{organization_id}",
        "/v1/offices/{office_id}",
        "/v1/contests/{contest_id}",
        "/v1/candidacies/{candidacy_id}",
        "/v1/officeholdings/{officeholding_id}",
        "/v1/jurisdictions/{jurisdiction_id}/offices",
        "/v1/contacts",
        "/v1/committees",
        "/v1/committees/by-slug/{slug}",
        "/v1/committees/{committee_id}",
        "/v1/committees/{committee_id}/summary",
        "/v1/committees/{committee_id}/filings/summary",
        "/v1/committees/{committee_id}/independent-expenditures-made",
        "/v1/candidates",
        "/v1/candidates/by-slug/{slug}",
        "/v1/candidates/{candidate_id}",
        "/v1/candidates/{candidate_id}/summary",
        "/v1/candidates/{candidate_id}/independent-expenditures",
        "/v1/candidates/{candidate_id}/independent-expenditures/summary",
        "/v1/campaign-finance/states/summary",
        "/v1/campaign-finance/states/{state_code}",
        "/v1/coverage/registry",
        "/v1/counties/{state}/{county_slug}/campaign-finance-summary",
        "/v1/data-sources",
        "/v1/donors/search",
        "/v1/elections/{election_date}",
        "/v1/elections/timeline/upcoming",
        "/v1/filings/{filing_id}",
        "/v1/geometry",
        "/v1/civics/geometry",
        "/v1/congress/members",
        "/v1/congress/money-summaries",
        "/v1/transactions",
        "/v1/parcels/{parcel_id}",
        "/v1/parcels",
        "/v1/investigate/donors-with-property",
        "/v1/er/clusters",
        "/v1/er/clusters/{cluster_id}",
        "/v1/er/summary",
        "/v1/er/{entity_type}/{entity_id}/matches",
        "/v1/graph/{entity_type}/{entity_id}/relationships",
        "/v1/search",
    }

    assert actual_paths == expected_paths

    route_method_pairs = [
        (route.path, method)
        for route in app.routes
        if route.path.startswith("/v1") and route.methods
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    ]
    assert len(route_method_pairs) == len(set(route_method_pairs))


def test_health_endpoint_returns_ok_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    client = TestClient(api_main.create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_content_health_endpoint_uses_post_strip_health_path(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    monkeypatch.setattr(api_main._health_content_module, "evaluate_content_health", lambda _connection: [])

    class FakePool:
        def connection(self) -> "FakePool":
            return self

        def __enter__(self) -> "FakePool":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    app = api_main.create_app()
    app.state.db_pool = FakePool()
    client = TestClient(app)
    response = client.get("/health/content")

    assert response.status_code == 200
    assert response.json() == {"healthy": True}


def test_query_cancellation_returns_connection_before_health_and_fast_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_main = _load_api_main(monkeypatch)
    monkeypatch.setattr(api_main._health_content_module, "evaluate_content_health", lambda _connection: [])

    class FakeConnection:
        def __init__(self) -> None:
            self.executed: list[str] = []

        def execute(self, sql: str) -> None:
            self.executed.append(sql)

    class FakePoolConnectionContext:
        def __init__(self, pool: "FakeBoundedPool") -> None:
            self._pool = pool

        def __enter__(self) -> FakeConnection:
            if self._pool.active_checkouts >= self._pool.max_checkouts:
                raise AssertionError("pool checkout capacity exhausted")
            self._pool.active_checkouts += 1
            self._pool.checkout_connection_ids.append(id(self._pool.pooled_connection))
            self._pool.max_observed_checkouts = max(
                self._pool.max_observed_checkouts,
                self._pool.active_checkouts,
            )
            return self._pool.pooled_connection

        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
            self._pool.active_checkouts -= 1
            return False

    class FakeBoundedPool:
        def __init__(self) -> None:
            self.active_checkouts = 0
            self.max_checkouts = 1
            self.max_observed_checkouts = 0
            self.pooled_connection = FakeConnection()
            self.checkout_connection_ids: list[int] = []

        def connection(self) -> FakePoolConnectionContext:
            return FakePoolConnectionContext(self)

        def open(self, *, wait: bool) -> None:
            return None

        def close(self) -> None:
            assert self.active_checkouts == 0

    fake_pool = FakeBoundedPool()
    monkeypatch.setattr(api_main, "_build_app_connection_pool", lambda: fake_pool)

    probe_router = APIRouter()

    @probe_router.get("/stage3/slow")
    def slow_probe(_connection: FakeConnection = Depends(get_db)) -> dict[str, str]:
        raise psycopg.errors.QueryCanceled("statement timeout")

    @probe_router.get("/stage3/fast")
    def fast_probe(_connection: FakeConnection = Depends(get_db)) -> dict[str, bool]:
        return {"ok": True}

    app = api_main.create_app()
    app.include_router(probe_router)

    with TestClient(app) as client:
        slow_response = client.get("/stage3/slow")
        assert fake_pool.active_checkouts == 0
        health_response = client.get("/health/content")
        assert fake_pool.active_checkouts == 0
        fast_response = client.get("/stage3/fast")
        assert fake_pool.active_checkouts == 0

    assert slow_response.status_code == 504
    assert slow_response.json() == {"detail": "Database query exceeded the request time limit"}
    assert health_response.status_code == 200
    assert health_response.json() == {"healthy": True}
    assert fast_response.status_code == 200
    assert fast_response.json() == {"ok": True}
    assert fake_pool.active_checkouts == 0
    assert len(fake_pool.checkout_connection_ids) == 3
    assert len(set(fake_pool.checkout_connection_ids)) == 1
    assert len(fake_pool.pooled_connection.executed) == 2
    assert fake_pool.max_observed_checkouts == 1


def test_people_enrichment_provenance_endpoint_is_owner_backed_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_main = _load_api_main(monkeypatch)
    client = TestClient(api_main.create_app())
    response = client.get("/provenance/people-enrichment")

    assert response.status_code == 200
    assert response.json() == {
        "source": "people-enrichment",
        "contract": "core.people.enrichment.orchestrator",
    }


def test_create_app_registers_logging_middleware_once_per_app_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_main = _load_api_main(monkeypatch)
    app = api_main.create_app()

    middleware_classes = [middleware.cls for middleware in app.user_middleware]
    assert middleware_classes.count(RequestLoggingMiddleware) == 1

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _load_api_main(monkeypatch)
    client = TestClient(api_main.create_app())
    response = client.get("/not-a-route")

    assert response.status_code == 404


@pytest.mark.parametrize("configured_keys", [None, "", "  ,  "])
def test_create_app_fails_closed_outside_development_when_keys_missing(
    monkeypatch: pytest.MonkeyPatch,
    configured_keys: str | None,
) -> None:
    api_main = _load_api_main(monkeypatch)
    if configured_keys is None:
        monkeypatch.delenv("CIVIBUS_API_KEYS", raising=False)
    else:
        monkeypatch.setenv("CIVIBUS_API_KEYS", configured_keys)

    with pytest.raises(RuntimeError, match="CIVIBUS_API_KEYS"):
        api_main.create_app()


@pytest.mark.parametrize(
    ("env_var_name", "env_value"),
    [
        (_RATE_LIMIT_REQUESTS_ENV_VAR, None),
        (_RATE_LIMIT_REQUESTS_ENV_VAR, "abc"),
        (_RATE_LIMIT_REQUESTS_ENV_VAR, "0"),
        (_RATE_LIMIT_REQUESTS_ENV_VAR, "-1"),
        (_RATE_LIMIT_WINDOW_SECONDS_ENV_VAR, None),
        (_RATE_LIMIT_WINDOW_SECONDS_ENV_VAR, "xyz"),
        (_RATE_LIMIT_WINDOW_SECONDS_ENV_VAR, "0"),
        (_RATE_LIMIT_WINDOW_SECONDS_ENV_VAR, "-5"),
    ],
)
def test_create_app_fails_closed_for_invalid_rate_limit_env(
    monkeypatch: pytest.MonkeyPatch,
    env_var_name: str,
    env_value: str | None,
) -> None:
    api_main = _load_api_main(monkeypatch)
    if env_value is None:
        monkeypatch.delenv(env_var_name, raising=False)
    else:
        monkeypatch.setenv(env_var_name, env_value)

    with pytest.raises(RuntimeError, match=env_var_name):
        api_main.create_app()
