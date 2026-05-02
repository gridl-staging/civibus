import importlib
import ast
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

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

    configured_connection = SimpleNamespace(autocommit=False)
    configure_callback = captured_pool_kwargs["configure"]
    assert callable(configure_callback)
    configure_callback(configured_connection)
    assert observed_autocommit_during_age_setup == [True]
    assert configured_connection.autocommit is False

    pool_closed.assert_called_once_with()


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
        "/v1/elections/{election_date}",
        "/v1/elections/timeline/upcoming",
        "/v1/filings/{filing_id}",
        "/v1/geometry",
        "/v1/civics/geometry",
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
