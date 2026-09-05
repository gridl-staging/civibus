from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_db
import api.routes.entities as entities_routes


_PERSON_ID = UUID("11111111-1111-4111-8111-111111111111")
_ORGANIZATION_ID = UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def entity_detail_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(entities_routes, "fetch_entity_provenance", lambda *_args: [])
    monkeypatch.setattr(entities_routes, "fetch_current_office_for_person", lambda *_args: None)
    monkeypatch.setattr(entities_routes, "fetch_candidacies_for_person", lambda *_args: [])

    app = FastAPI()
    app.include_router(entities_routes.router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: object()
    return app


@pytest.mark.parametrize(
    ("path", "stored_row", "expected_detail"),
    [
        pytest.param(
            f"/v1/person/{_PERSON_ID}",
            {
                "id": _PERSON_ID,
                "canonical_name": "Synthetic Person",
                "identifiers": ["invalid-shape"],
            },
            "Stored person record does not satisfy the response contract and cannot be served.",
            id="person",
        ),
        pytest.param(
            f"/v1/org/{_ORGANIZATION_ID}",
            {
                "id": _ORGANIZATION_ID,
                "canonical_name": "Synthetic Organization",
                "identifiers": ["invalid-shape"],
            },
            "Stored organization record does not satisfy the response contract and cannot be served.",
            id="organization",
        ),
    ],
)
def test_entity_detail_stored_record_validation_failures_return_safe_typed_502(
    entity_detail_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    stored_row: Mapping[str, object],
    expected_detail: str,
) -> None:
    monkeypatch.setattr(
        entities_routes,
        "fetch_one_row",
        lambda _conn, *, query, row_id: dict(stored_row),
    )

    response = TestClient(entity_detail_app).get(path)

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": expected_detail}
    assert "invalid-shape" not in response.text


@pytest.mark.parametrize(
    ("path", "expected_detail"),
    [
        pytest.param(f"/v1/person/{_PERSON_ID}", "Person not found", id="person"),
        pytest.param(f"/v1/org/{_ORGANIZATION_ID}", "Organization not found", id="organization"),
    ],
)
def test_entity_detail_missing_records_preserve_typed_404(
    entity_detail_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    expected_detail: str,
) -> None:
    monkeypatch.setattr(entities_routes, "fetch_one_row", lambda _conn, *, query, row_id: None)

    response = TestClient(entity_detail_app).get(path)

    assert response.status_code == 404
    assert response.json() == {"detail": expected_detail}


@pytest.mark.parametrize(
    ("path", "path_parameter"),
    [
        pytest.param("/v1/person/not-a-uuid", "person_id", id="person"),
        pytest.param("/v1/org/not-a-uuid", "organization_id", id="organization"),
    ],
)
def test_entity_detail_malformed_ids_preserve_automatic_422(
    entity_detail_app: FastAPI,
    path: str,
    path_parameter: str,
) -> None:
    response = TestClient(entity_detail_app).get(path)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", path_parameter]


def _detail_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"detail": {"type": "string"}},
        "required": ["detail"],
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    ("path", "response_model"),
    [
        pytest.param(
            "/v1/person/{person_id}",
            "PersonResponse",
            id="person",
        ),
        pytest.param(
            "/v1/org/{organization_id}",
            "OrgResponse",
            id="organization",
        ),
    ],
)
def test_entity_detail_openapi_matches_runtime_error_contract(
    entity_detail_app: FastAPI,
    path: str,
    response_model: str,
) -> None:
    responses = entity_detail_app.openapi()["paths"][path]["get"]["responses"]

    assert set(responses) == {"200", "404", "422", "502"}
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": f"#/components/schemas/{response_model}"
    }
    assert responses["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HTTPValidationError"
    }
    for status_code in ("404", "502"):
        response_contract = responses[status_code]
        assert response_contract["description"].strip()
        assert set(response_contract["content"]) == {"application/json"}
        assert response_contract["content"]["application/json"]["schema"] == _detail_schema()
