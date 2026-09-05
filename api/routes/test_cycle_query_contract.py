from __future__ import annotations

from typing import Any

from api.main import create_app
from api.queries.campaign_finance import SUPPORTED_COMMITTEE_SUMMARY_CYCLES


_SELECTED_CYCLE_OPERATIONS = {
    ("GET", "/v1/transactions"),
    ("GET", "/v1/person/{person_id}/contribution-insights"),
    ("GET", "/v1/person/{person_id}/top-donors"),
    ("GET", "/v1/person/{person_id}/top-employers"),
    ("GET", "/v1/committees/{committee_id}/summary"),
    ("GET", "/v1/committees/{committee_id}/independent-expenditures-made"),
    ("GET", "/v1/candidates/{candidate_id}/summary"),
    ("GET", "/v1/candidates/{candidate_id}/independent-expenditures"),
    ("GET", "/v1/candidates/{candidate_id}/independent-expenditures/summary"),
    ("GET", "/v1/contests/{contest_id}/candidate-money"),
}


def _cycle_query_parameters() -> dict[tuple[str, str], dict[str, Any]]:
    parameters: dict[tuple[str, str], dict[str, Any]] = {}
    for path, path_item in create_app().openapi()["paths"].items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters", []):
                if parameter.get("in") == "query" and parameter.get("name") == "cycle":
                    parameters[(method.upper(), path)] = parameter
    return parameters


def test_selected_cycle_openapi_advertises_only_query_owner_supported_cycles() -> None:
    parameters = _cycle_query_parameters()

    assert parameters.keys() == _SELECTED_CYCLE_OPERATIONS
    for parameter in parameters.values():
        assert parameter["required"] is False
        schema = parameter["schema"]
        assert schema["enum"] == list(SUPPORTED_COMMITTEE_SUMMARY_CYCLES)
        assert schema["anyOf"] == [{"type": "integer"}, {"type": "null"}]


def test_committee_ie_openapi_requires_cycle_metadata_and_coverage() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    activity_schema = schemas["CommitteeIndependentExpenditureActivity"]

    assert {
        "selected_cycle",
        "coverage_start_date",
        "coverage_end_date",
        "coverage",
    } <= set(activity_schema["required"])
    assert activity_schema["properties"]["coverage"] == {"$ref": "#/components/schemas/CandidateMoneyCoverage"}
