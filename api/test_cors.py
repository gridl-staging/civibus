import pytest
from fastapi.testclient import TestClient

from api.middleware import API_KEY_HEADER_NAME, REQUEST_ID_HEADER_NAME
from api.main import create_app


def _cors_related_headers(response) -> dict[str, str]:
    return {
        header_name.lower(): header_value
        for header_name, header_value in response.headers.items()
        if header_name.lower().startswith("access-control-") or header_name.lower() == "vary"
    }


def test_health_preflight_request_includes_cors_headers(monkeypatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "development")
    client = TestClient(create_app())
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Test-Header",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "GET" in response.headers["access-control-allow-methods"]
    assert "x-test-header" in response.headers["access-control-allow-headers"].lower()


def test_health_simple_cross_origin_request_includes_cors_headers(monkeypatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "development")
    client = TestClient(create_app())
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_health_cross_origin_request_allows_configured_origin_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "cors-test-key")
    configured_origin = "https://app.example.com"
    monkeypatch.setenv("CIVIBUS_CORS_ORIGIN", configured_origin)
    client = TestClient(create_app())
    response = client.get("/health", headers={"Origin": configured_origin})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["access-control-allow-origin"] == configured_origin
    assert REQUEST_ID_HEADER_NAME.lower() in response.headers["access-control-expose-headers"].lower()


def test_health_preflight_request_allows_required_headers_for_configured_origin_outside_development(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "cors-test-key")
    configured_origin = "https://app.example.com"
    monkeypatch.setenv("CIVIBUS_CORS_ORIGIN", configured_origin)
    client = TestClient(create_app())
    response = client.options(
        "/health",
        headers={
            "Origin": configured_origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": f"{API_KEY_HEADER_NAME}, {REQUEST_ID_HEADER_NAME}",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == configured_origin
    assert response.headers["access-control-allow-methods"] == "GET"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert API_KEY_HEADER_NAME.lower() in allowed_headers
    assert REQUEST_ID_HEADER_NAME.lower() in allowed_headers


@pytest.mark.parametrize("configured_origin", [None, "", "  "])
def test_health_cross_origin_request_omits_cors_headers_when_configured_origin_missing_or_blank(
    monkeypatch, configured_origin
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "cors-test-key")
    if configured_origin is None:
        monkeypatch.delenv("CIVIBUS_CORS_ORIGIN", raising=False)
    else:
        monkeypatch.setenv("CIVIBUS_CORS_ORIGIN", configured_origin)

    client = TestClient(create_app())
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert _cors_related_headers(response) == {}


def test_health_cross_origin_request_omits_cors_headers_for_non_matching_origin(monkeypatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "cors-test-key")
    monkeypatch.setenv("CIVIBUS_CORS_ORIGIN", "https://app.example.com")
    client = TestClient(create_app())
    response = client.get("/health", headers={"Origin": "https://other.example.com"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert _cors_related_headers(response) == {}


def test_health_preflight_request_omits_cors_headers_for_non_matching_origin(monkeypatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "cors-test-key")
    monkeypatch.setenv("CIVIBUS_CORS_ORIGIN", "https://app.example.com")
    client = TestClient(create_app())
    response = client.options(
        "/health",
        headers={
            "Origin": "https://other.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": f"{API_KEY_HEADER_NAME}, {REQUEST_ID_HEADER_NAME}",
        },
    )

    assert response.status_code == 400
    assert _cors_related_headers(response) == {}


def test_unhandled_error_for_configured_origin_preserves_cors_and_request_id_headers(monkeypatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "cors-test-key")
    configured_origin = "https://app.example.com"
    monkeypatch.setenv("CIVIBUS_CORS_ORIGIN", configured_origin)
    app = create_app()

    @app.get("/__cors_error_probe")
    def cors_error_probe() -> None:
        raise RuntimeError("cors error-path probe")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/__cors_error_probe", headers={"Origin": configured_origin})

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers["access-control-allow-origin"] == configured_origin
    assert response.headers["vary"] == "Origin"
    assert REQUEST_ID_HEADER_NAME.lower() in response.headers["access-control-expose-headers"].lower()
    assert response.headers[REQUEST_ID_HEADER_NAME]
