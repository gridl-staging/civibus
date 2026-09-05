from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from api.deps import get_db
from api.main import create_app
from api.middleware import require_authorized_request
from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX
from api.routes import campaign_finance as campaign_finance_route_module


_COMMITTEE_ID = UUID("a0000000-0000-0000-0000-000000000130")
_PATH = f"/v1/committees/{_COMMITTEE_ID}/filings/summary"


def _client_with_filing_query_spies(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[tuple[str, int, int] | tuple[str]]]:
    calls: list[tuple[str, int, int] | tuple[str]] = []

    def fake_fetch_row_or_404(*_args: object, **_kwargs: object) -> dict[str, Any]:
        calls.append(("detail",))
        return {"name": "Filing Offset Boundary Committee"}

    def fake_fetch_committee_filing_breakdown(
        _conn: object,
        _committee_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        calls.append(("filings", limit, offset))
        return []

    def fake_count_committee_filings(_conn: object, _committee_id: UUID) -> int:
        calls.append(("count",))
        return 0

    monkeypatch.setattr(campaign_finance_route_module, "_fetch_row_or_404", fake_fetch_row_or_404)
    monkeypatch.setattr(
        campaign_finance_route_module,
        "fetch_committee_filing_breakdown",
        fake_fetch_committee_filing_breakdown,
    )
    monkeypatch.setattr(campaign_finance_route_module, "count_committee_filings", fake_count_committee_filings)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[require_authorized_request] = lambda: None
    return TestClient(app), calls


def test_committee_filing_summary_rejects_postgres_offset_overflow_before_query_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_filing_query_spies(monkeypatch)

    response = client.get(_PATH, params={"offset": POSTGRES_SIGNED_BIGINT_MAX + 1})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "offset"]
    assert query_calls == []


def test_committee_filing_summary_accepts_inclusive_postgres_offset_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_filing_query_spies(monkeypatch)

    response = client.get(_PATH, params={"limit": 1, "offset": POSTGRES_SIGNED_BIGINT_MAX})

    assert response.status_code == 200
    assert response.json() == {
        "committee_id": str(_COMMITTEE_ID),
        "committee_name": "Filing Offset Boundary Committee",
        "total_filings": 0,
        "store_limit": 200,
        "has_next": False,
        "offset": POSTGRES_SIGNED_BIGINT_MAX,
        "limit": 1,
        "filings": [],
    }
    assert query_calls == [
        ("detail",),
        ("filings", 1, POSTGRES_SIGNED_BIGINT_MAX),
        ("count",),
    ]


def test_committee_filing_summary_openapi_declares_postgres_offset_boundary() -> None:
    parameters = {
        parameter["name"]: parameter["schema"]
        for parameter in create_app().openapi()["paths"]["/v1/committees/{committee_id}/filings/summary"]["get"][
            "parameters"
        ]
    }

    assert parameters["offset"]["minimum"] == 0
    assert parameters["offset"]["maximum"] == POSTGRES_SIGNED_BIGINT_MAX
