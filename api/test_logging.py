from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.main import create_app
from api.middleware.logging import RequestLoggingMiddleware

_REQUEST_ID_HEADER_NAME = "X-Request-ID"
_API_LOGGER_NAME = "civibus.api"


@pytest.fixture
def api_log_stream() -> io.StringIO:
    logger = logging.getLogger(_API_LOGGER_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate

    stream = io.StringIO()
    capture_handler = logging.StreamHandler(stream)
    capture_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [capture_handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield stream
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate


def _read_json_log_records(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


@pytest.mark.parametrize("supplied_request_id", [None, "client-request-id-123"])
def test_health_request_has_request_id_and_structured_json_log(
    monkeypatch: pytest.MonkeyPatch,
    api_log_stream: io.StringIO,
    supplied_request_id: str | None,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "logging-test-key")
    client = TestClient(create_app())
    request_headers = {} if supplied_request_id is None else {_REQUEST_ID_HEADER_NAME: supplied_request_id}

    response = client.get("/health", headers=request_headers)

    response_request_id = response.headers.get(_REQUEST_ID_HEADER_NAME)
    assert response.status_code == 200
    assert response_request_id
    if supplied_request_id is not None:
        assert response_request_id == supplied_request_id

    log_records = _read_json_log_records(api_log_stream)
    assert len(log_records) == 1
    assert log_records[0]["request_id"] == response_request_id
    assert log_records[0]["method"] == "GET"
    assert log_records[0]["path"] == "/health"
    assert log_records[0]["status_code"] == 200
    assert isinstance(log_records[0]["duration_ms"], int)
    assert log_records[0]["duration_ms"] >= 0


def test_fastapi_handled_404_reuses_same_request_id_in_response_and_log(
    monkeypatch: pytest.MonkeyPatch,
    api_log_stream: io.StringIO,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "logging-test-key")
    client = TestClient(create_app())

    response = client.get("/not-a-route")

    assert response.status_code == 404
    response_request_id = response.headers.get(_REQUEST_ID_HEADER_NAME)
    assert response_request_id

    log_records = _read_json_log_records(api_log_stream)
    assert len(log_records) == 1
    assert log_records[0]["request_id"] == response_request_id
    assert log_records[0]["method"] == "GET"
    assert log_records[0]["path"] == "/not-a-route"
    assert log_records[0]["status_code"] == 404
    assert isinstance(log_records[0]["duration_ms"], int)
    assert log_records[0]["duration_ms"] >= 0


def test_auth_denied_401_reuses_same_request_id_in_response_and_log(
    monkeypatch: pytest.MonkeyPatch,
    api_log_stream: io.StringIO,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "logging-test-key")
    client = TestClient(create_app())

    response = client.get("/v1/search", params={"q": "civ"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
    response_request_id = response.headers.get(_REQUEST_ID_HEADER_NAME)
    assert response_request_id

    log_records = _read_json_log_records(api_log_stream)
    assert len(log_records) == 1
    assert log_records[0]["request_id"] == response_request_id
    assert log_records[0]["method"] == "GET"
    assert log_records[0]["path"] == "/v1/search"
    assert log_records[0]["status_code"] == 401
    assert isinstance(log_records[0]["duration_ms"], int)
    assert log_records[0]["duration_ms"] >= 0


def test_unhandled_500_reuses_same_request_id_in_response_and_log(
    api_log_stream: io.StringIO,
) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    response_request_id = response.headers.get(_REQUEST_ID_HEADER_NAME)
    assert response_request_id

    log_records = _read_json_log_records(api_log_stream)
    assert len(log_records) == 1
    assert log_records[0]["request_id"] == response_request_id
    assert log_records[0]["method"] == "GET"
    assert log_records[0]["path"] == "/boom"
    assert log_records[0]["status_code"] == 500
    assert log_records[0]["exception_type"] == "RuntimeError"
    assert "exception_message" not in log_records[0]
    assert isinstance(log_records[0]["duration_ms"], int)
    assert log_records[0]["duration_ms"] >= 0


def test_request_log_path_omits_query_string_and_serialized_line_excludes_query_values(
    monkeypatch: pytest.MonkeyPatch,
    api_log_stream: io.StringIO,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "logging-test-key")
    client = TestClient(create_app())

    response = client.get("/health?secret=value&token=abc")

    assert response.status_code == 200

    log_records = _read_json_log_records(api_log_stream)
    assert len(log_records) == 1
    assert log_records[0]["path"] == "/health"
    serialized_log_line = api_log_stream.getvalue()
    assert "?secret=value" not in serialized_log_line
    assert "secret=value" not in serialized_log_line
    assert "token=abc" not in serialized_log_line


def test_unhandled_500_response_body_is_generic_and_omits_exception_details(
    api_log_stream: io.StringIO,
) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/explode")
    def explode() -> None:
        raise ValueError("sensitive runtime details")

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/explode")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "ValueError" not in response.text
    assert "sensitive runtime details" not in response.text


def test_unhandled_500_log_payload_contains_required_safe_keys_and_omits_sensitive_keys(
    api_log_stream: io.StringIO,
) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/panic")
    def panic() -> None:
        raise RuntimeError("do not leak me")

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/panic")

    assert response.status_code == 500

    log_records = _read_json_log_records(api_log_stream)
    assert len(log_records) == 1
    log_record = log_records[0]

    required_safe_keys = {"request_id", "method", "path", "status_code", "duration_ms", "exception_type"}
    assert required_safe_keys.issubset(set(log_record.keys()))
    forbidden_sensitive_keys = {"traceback", "stack_trace", "exc_info", "exception_message"}
    assert forbidden_sensitive_keys.isdisjoint(set(log_record.keys()))
