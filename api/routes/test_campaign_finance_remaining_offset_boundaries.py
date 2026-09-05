from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.deps import get_db
from api.main import create_app
from api.middleware import require_authorized_request
from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX
from api.models.campaign_finance import TransactionListParams
from api.queries.campaign_finance import SelectedCycle
from api.routes import campaign_finance as campaign_finance_route_module

_CANDIDATE_ID = UUID("cb000000-0000-0000-0000-000000000001")
_COMMITTEE_ID = UUID("cb000000-0000-0000-0000-000000000002")


def _client_with_query_spies(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[tuple[object, ...]]]:
    calls: list[tuple[object, ...]] = []

    def fake_fetch_transaction_list(
        _conn: object,
        params: TransactionListParams,
        selected_cycle: SelectedCycle,
    ) -> list[dict[str, object]]:
        calls.append(("transactions", params, selected_cycle.selected_cycle))
        return []

    def fake_fetch_row_or_404(
        _conn: object,
        _query: str,
        row_id: UUID,
        not_found_detail: str,
    ) -> dict[str, object]:
        calls.append(("candidate_detail", row_id, not_found_detail))
        return {}

    def fake_fetch_candidate_ie_transactions(
        _conn: object,
        candidate_id: UUID,
        *,
        limit: int,
        offset: int,
        selected_cycle: SelectedCycle,
    ) -> list[dict[str, object]]:
        calls.append(
            (
                "candidate_independent_expenditures",
                candidate_id,
                limit,
                offset,
                selected_cycle.selected_cycle,
            )
        )
        return []

    monkeypatch.setattr(
        campaign_finance_route_module,
        "fetch_transaction_list",
        fake_fetch_transaction_list,
    )
    monkeypatch.setattr(
        campaign_finance_route_module,
        "_fetch_row_or_404",
        fake_fetch_row_or_404,
    )
    monkeypatch.setattr(
        campaign_finance_route_module,
        "fetch_candidate_ie_transactions",
        fake_fetch_candidate_ie_transactions,
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[require_authorized_request] = lambda: None
    return TestClient(app), calls


@pytest.mark.parametrize(
    "path",
    [
        "/v1/transactions",
        f"/v1/candidates/{_CANDIDATE_ID}/independent-expenditures",
    ],
    ids=["transactions", "candidate-independent-expenditures"],
)
def test_remaining_campaign_finance_offsets_reject_postgres_overflow_before_query_execution(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    client, query_calls = _client_with_query_spies(monkeypatch)

    response = client.get(path, params={"offset": POSTGRES_SIGNED_BIGINT_MAX + 1})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "offset"]
    assert query_calls == []


def test_transaction_offset_accepts_inclusive_postgres_maximum_without_filter_or_cycle_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spies(monkeypatch)

    response = client.get(
        "/v1/transactions",
        params={
            "committee_id": str(_COMMITTEE_ID),
            "jurisdiction": "state/co",
            "min_date": "2023-01-01",
            "max_date": "2024-12-31",
            "min_amount": "10.50",
            "max_amount": "99.99",
            "limit": 17,
            "offset": POSTGRES_SIGNED_BIGINT_MAX,
            "cycle": 2024,
        },
    )

    assert response.status_code == 200
    assert response.json() == []
    assert query_calls == [
        (
            "transactions",
            TransactionListParams(
                committee_id=_COMMITTEE_ID,
                jurisdiction="state/co",
                min_date=date(2023, 1, 1),
                max_date=date(2024, 12, 31),
                min_amount=10.50,
                max_amount=99.99,
                limit=17,
                offset=POSTGRES_SIGNED_BIGINT_MAX,
            ),
            2024,
        )
    ]


def test_candidate_ie_offset_accepts_inclusive_postgres_maximum_without_404_or_cycle_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spies(monkeypatch)

    response = client.get(
        f"/v1/candidates/{_CANDIDATE_ID}/independent-expenditures",
        params={
            "limit": 19,
            "offset": POSTGRES_SIGNED_BIGINT_MAX,
            "cycle": 2024,
        },
    )

    assert response.status_code == 200
    assert response.json() == []
    assert query_calls == [
        ("candidate_detail", _CANDIDATE_ID, "Candidate not found"),
        (
            "candidate_independent_expenditures",
            _CANDIDATE_ID,
            19,
            POSTGRES_SIGNED_BIGINT_MAX,
            2024,
        ),
    ]


def test_transaction_list_model_bounds_offset_to_postgres_signed_bigint() -> None:
    assert TransactionListParams(offset=POSTGRES_SIGNED_BIGINT_MAX).offset == POSTGRES_SIGNED_BIGINT_MAX

    with pytest.raises(ValidationError) as exc_info:
        TransactionListParams(offset=POSTGRES_SIGNED_BIGINT_MAX + 1)

    assert exc_info.value.errors()[0]["loc"] == ("offset",)


@pytest.mark.parametrize(
    "path",
    [
        "/v1/transactions",
        "/v1/candidates/{candidate_id}/independent-expenditures",
    ],
    ids=["transactions", "candidate-independent-expenditures"],
)
def test_remaining_campaign_finance_offset_openapi_declares_postgres_boundary(path: str) -> None:
    parameters = {
        parameter["name"]: parameter["schema"]
        for parameter in create_app().openapi()["paths"][path]["get"]["parameters"]
    }

    assert parameters["offset"]["minimum"] == 0
    assert parameters["offset"]["maximum"] == POSTGRES_SIGNED_BIGINT_MAX
