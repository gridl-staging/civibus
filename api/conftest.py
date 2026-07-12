from __future__ import annotations


import psycopg
import pytest
from fastapi.testclient import TestClient

from api.deps import get_db
from api.middleware import require_administrative_request, require_authorized_request


def _build_api_test_client(connection: psycopg.Connection) -> TestClient:
    from api.main import create_app

    app = create_app()

    def _get_db_override():
        yield connection

    def _allow_authorized_request_override() -> None:
        return None

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[require_administrative_request] = _allow_authorized_request_override
    app.dependency_overrides[require_authorized_request] = _allow_authorized_request_override
    return TestClient(app)


@pytest.fixture
def api_client(db_conn: psycopg.Connection) -> TestClient:
    client = _build_api_test_client(db_conn)
    try:
        with client:
            yield client
    finally:
        client.app.dependency_overrides.clear()


@pytest.fixture
def graph_api_client(graph_conn: psycopg.Connection) -> TestClient:
    """API test client backed by an AGE-enabled connection for graph route tests."""
    client = _build_api_test_client(graph_conn)
    try:
        with client:
            yield client
    finally:
        client.app.dependency_overrides.clear()
