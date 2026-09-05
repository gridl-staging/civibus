from __future__ import annotations

from decimal import Decimal
import re
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.deps import get_db
import api.queries.campaign_finance as campaign_finance_queries
import api.routes.campaign_finance as campaign_finance_routes


_LARGE_VALID_MONEY = "100000000000000000000000000.00"
_ROUNDING_CARRY_MONEY = "99999999999999999999999999.995"
_SUMMARY_UNAVAILABLE = "Campaign-finance detail unavailable"


@pytest.mark.parametrize("stored_value", ("NaN", "Infinity", "-Infinity", "not-money"))
def test_money_normalizer_rejects_invalid_stored_values(stored_value: str) -> None:
    with pytest.raises(ValueError, match="Campaign-finance money value must be finite"):
        campaign_finance_queries._quantize_money(stored_value)


def test_committee_summary_preserves_large_valid_money_through_openapi_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committee_id = "cf200000-0000-0000-0000-000000000001"
    app = FastAPI()
    app.include_router(campaign_finance_routes.router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: object()

    monkeypatch.setattr(
        campaign_finance_routes,
        "fetch_one_row",
        lambda *_args, **_kwargs: {"name": "Large Money Committee"},
    )

    def fetch_summary(
        _conn: object,
        current_committee_id: UUID,
        selected_cycle: campaign_finance_queries.SelectedCycle,
    ) -> dict[str, object]:
        large_money = campaign_finance_queries._quantize_money(_LARGE_VALID_MONEY)
        rounded_money = campaign_finance_queries._quantize_money(_ROUNDING_CARRY_MONEY)
        genuine_zero = campaign_finance_queries._quantize_money("0")
        return {
            "committee_id": current_committee_id,
            "committee_name": "Large Money Committee",
            "selected_cycle": selected_cycle.selected_cycle,
            "coverage_start_date": selected_cycle.coverage_start_date,
            "coverage_end_date": selected_cycle.coverage_end_date,
            "total_raised": large_money,
            "total_spent": genuine_zero,
            "net": rounded_money,
            "transaction_count": 1,
            "receipt_source_composition": [
                {
                    "label": "Cash receipts",
                    "total_amount": large_money,
                    "source": "fec_committee_summary",
                },
                {
                    "label": "Genuine zero",
                    "total_amount": genuine_zero,
                    "source": "fec_committee_summary",
                },
            ],
        }

    monkeypatch.setattr(campaign_finance_routes, "fetch_committee_fundraising_summary", fetch_summary)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/v1/committees/{committee_id}/summary?cycle=2026")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_raised"] == _LARGE_VALID_MONEY
    assert payload["total_spent"] == "0.00"
    assert payload["net"] == _LARGE_VALID_MONEY
    assert [component["total_amount"] for component in payload["receipt_source_composition"]] == [
        _LARGE_VALID_MONEY,
        "0.00",
    ]

    openapi = app.openapi()
    assert openapi["paths"]["/v1/committees/{committee_id}/summary"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/CommitteeFundraisingSummary"}
    for schema_name, field_name in (
        ("CommitteeFundraisingSummary", "total_raised"),
        ("ReceiptSourceComponent", "total_amount"),
    ):
        money_schema = openapi["components"]["schemas"][schema_name]["properties"][field_name]
        assert money_schema["type"] == "string"
        assert re.fullmatch(money_schema["pattern"], _LARGE_VALID_MONEY)
        assert "maxLength" not in money_schema


@pytest.mark.parametrize(
    ("failure_source", "expected_exception_type"),
    (("query", "InvalidCampaignFinanceMoneyError"), ("model", "ValidationError")),
)
def test_invalid_committee_summary_returns_sanitized_observable_500(
    monkeypatch: pytest.MonkeyPatch,
    failure_source: str,
    expected_exception_type: str,
) -> None:
    committee_id = "cf200000-0000-0000-0000-000000000002"
    corrupt_value = "NaN"
    observed_exception_types: list[str] = []
    app = FastAPI()
    app.include_router(campaign_finance_routes.router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: object()

    monkeypatch.setattr(
        campaign_finance_routes,
        "fetch_one_row",
        lambda *_args, **_kwargs: {"name": "Invalid Money Committee"},
    )
    monkeypatch.setattr(
        campaign_finance_routes,
        "record_handled_exception_type",
        lambda _request, exception: observed_exception_types.append(type(exception).__name__),
    )

    def fetch_summary(
        _conn: object,
        current_committee_id: UUID,
        selected_cycle: campaign_finance_queries.SelectedCycle,
    ) -> dict[str, object]:
        invalid_money = (
            campaign_finance_queries._quantize_money(corrupt_value)
            if failure_source == "query"
            else Decimal(corrupt_value)
        )
        return {
            "committee_id": current_committee_id,
            "committee_name": "Invalid Money Committee",
            "selected_cycle": selected_cycle.selected_cycle,
            "coverage_start_date": selected_cycle.coverage_start_date,
            "coverage_end_date": selected_cycle.coverage_end_date,
            "total_raised": invalid_money,
            "total_spent": Decimal("0.00"),
            "net": invalid_money,
            "transaction_count": 1,
        }

    monkeypatch.setattr(campaign_finance_routes, "fetch_committee_fundraising_summary", fetch_summary)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/v1/committees/{committee_id}/summary?cycle=2026")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": _SUMMARY_UNAVAILABLE}
    assert corrupt_value not in response.text
    assert "validation" not in response.text.lower()
    assert observed_exception_types == [expected_exception_type]


def test_invalid_candidate_summary_query_money_uses_same_sanitized_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id = "cf200000-0000-0000-0000-000000000003"
    observed_exception_types: list[str] = []
    app = FastAPI()
    app.include_router(campaign_finance_routes.router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: object()

    monkeypatch.setattr(
        campaign_finance_routes,
        "fetch_one_row",
        lambda *_args, **_kwargs: {"name": "Invalid Money Candidate"},
    )
    monkeypatch.setattr(
        campaign_finance_routes,
        "record_handled_exception_type",
        lambda _request, exception: observed_exception_types.append(type(exception).__name__),
    )

    def fetch_summary(*_args: object, **_kwargs: object) -> None:
        campaign_finance_queries._quantize_money("Infinity")

    monkeypatch.setattr(campaign_finance_routes, "fetch_candidate_summary", fetch_summary)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/v1/candidates/{candidate_id}/summary?cycle=2026")

    assert response.status_code == 500
    assert response.json() == {"detail": _SUMMARY_UNAVAILABLE}
    assert "Infinity" not in response.text
    assert observed_exception_types == ["InvalidCampaignFinanceMoneyError"]


@pytest.mark.parametrize(
    "path",
    (
        "/v1/committees/{committee_id}/summary",
        "/v1/candidates/{candidate_id}/summary",
    ),
)
def test_campaign_finance_summary_openapi_documents_sanitized_500(path: str) -> None:
    app = FastAPI()
    app.include_router(campaign_finance_routes.router, prefix="/v1")

    responses = app.openapi()["paths"][path]["get"]["responses"]

    assert responses["500"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CampaignFinanceDetailErrorResponse"
    }
