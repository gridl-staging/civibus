from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from api.deps import get_db
from api.main import create_app
from api.middleware import require_authorized_request
from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX
from api.models.campaign_finance import CandidateListParams, CommitteeListParams
from api.routes import campaign_finance as campaign_finance_route_module


def _client_with_list_query_spies(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[tuple[str, BaseModel]]]:
    calls: list[tuple[str, BaseModel]] = []

    def fake_fetch_candidate_list(_conn: object, params: CandidateListParams) -> dict[str, Any]:
        calls.append(("candidates", params))
        return {"items": [], "has_next": False, "offset": params.offset, "limit": params.limit}

    def fake_fetch_committee_list(_conn: object, params: CommitteeListParams) -> dict[str, Any]:
        calls.append(("committees", params))
        return {"items": [], "has_next": False, "offset": params.offset, "limit": params.limit}

    monkeypatch.setattr(campaign_finance_route_module, "fetch_candidate_list", fake_fetch_candidate_list)
    monkeypatch.setattr(campaign_finance_route_module, "fetch_committee_list", fake_fetch_committee_list)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[require_authorized_request] = lambda: None
    return TestClient(app), calls


@pytest.mark.parametrize(
    ("path", "resource"),
    [
        ("/v1/candidates", "candidates"),
        ("/v1/committees", "committees"),
    ],
    ids=["candidate", "committee"],
)
def test_campaign_finance_list_rejects_postgres_offset_overflow_before_query_execution(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    resource: str,
) -> None:
    client, query_calls = _client_with_list_query_spies(monkeypatch)

    response = client.get(path, params={"offset": POSTGRES_SIGNED_BIGINT_MAX + 1})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "offset"]
    assert query_calls == [], f"{resource} query executed for an offset PostgreSQL cannot represent"


@pytest.mark.parametrize(
    ("model_type", "path", "resource"),
    [
        (CandidateListParams, "/v1/candidates", "candidates"),
        (CommitteeListParams, "/v1/committees", "committees"),
    ],
    ids=["candidate", "committee"],
)
def test_campaign_finance_list_accepts_inclusive_postgres_offset_maximum(
    monkeypatch: pytest.MonkeyPatch,
    model_type: type[CandidateListParams] | type[CommitteeListParams],
    path: str,
    resource: str,
) -> None:
    client, query_calls = _client_with_list_query_spies(monkeypatch)

    response = client.get(path, params={"limit": 1, "offset": POSTGRES_SIGNED_BIGINT_MAX})

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "has_next": False,
        "offset": POSTGRES_SIGNED_BIGINT_MAX,
        "limit": 1,
    }
    assert query_calls == [(resource, model_type(limit=1, offset=POSTGRES_SIGNED_BIGINT_MAX))]


@pytest.mark.parametrize("model_type", [CandidateListParams, CommitteeListParams])
def test_campaign_finance_list_models_bound_offset_to_postgres_signed_bigint(
    model_type: type[CandidateListParams] | type[CommitteeListParams],
) -> None:
    assert model_type(offset=POSTGRES_SIGNED_BIGINT_MAX).offset == POSTGRES_SIGNED_BIGINT_MAX

    with pytest.raises(ValidationError) as exc_info:
        model_type(offset=POSTGRES_SIGNED_BIGINT_MAX + 1)

    assert exc_info.value.errors()[0]["loc"] == ("offset",)


@pytest.mark.parametrize("path", ["/v1/candidates", "/v1/committees"])
def test_campaign_finance_list_openapi_declares_postgres_offset_boundary(path: str) -> None:
    parameters = {
        parameter["name"]: parameter["schema"]
        for parameter in create_app().openapi()["paths"][path]["get"]["parameters"]
    }

    assert parameters["offset"]["minimum"] == 0
    assert parameters["offset"]["maximum"] == POSTGRES_SIGNED_BIGINT_MAX
