"""Tests for the authless public federal API (`/public/v1`).

Stage 1: two thin-wrapper endpoints over existing query owners —
``GET /public/v1/federal/officials`` and
``GET /public/v1/federal/officials/{person_id}/money``.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.deps import get_db
from api.middleware.access import enforce_public_ip_rate_limit
from api.models import (
    PublicContributorRow,
    PublicContributorsResponse,
    PublicEmployerRow,
    PublicEmployersResponse,
    PublicMemberMoneySummary,
)
from api.models.provenance import SourceInfo
from api.routes import civics as civics_route_module
from api.routes import public_federal as public_federal_route_module
from api.routes.public_federal import PUBLIC_FEDERAL_EXPORT_CSV_COLUMNS, router
from api.test_campaign_finance_support import (
    CandidateCommitteeLinkSeed,
    CandidateRowSeed,
    CommitteeRowSeed,
    CommitteeSummaryRowSeed,
    FilingRowSeed,
    TransactionRowSeed,
    insert_candidate_committee_link_row,
    insert_candidate_row,
    insert_committee_summary_row,
    insert_committee_row,
    insert_data_source_for_test,
    insert_filing_row,
    insert_source_record_for_test,
    insert_transaction_row,
)
from api.test_civics import (
    _CongressMemberExpectation,
    _expected_congress_http_rows,
    _insert_namesake_challenger_candidacy,
    _seed_current_federal_members_mix,
)
from core.db import insert_entity_source
from test_support.donor_search_fixture import (
    DonorSearchFullScopeCounts,
    cleanup_donor_search_fixture,
    seed_donor_search_fixture,
    seed_full_scope_skewed_donor_search_fixture,
)

pytestmark = pytest.mark.integration

_PUBLIC_FEDERAL_OPENAPI_PATH_PREFIX = "/public/v1/"
_DEVELOPERS_PAGE_PROXY_PREFIX = "/api"
_OPENAPI_OPERATION_KEYS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})

# The published client-generation contract for the six authless federal routes.
# Values are asserted literally rather than read back from the route module: a
# contract test that imports the value it checks cannot detect a renamed
# operation, and every rename here breaks already-generated clients.
_PUBLIC_FEDERAL_OPENAPI_TAG = "public-federal"
_PUBLIC_FEDERAL_OFFICIALS_PATH = "/public/v1/federal/officials"
_PUBLIC_FEDERAL_MONEY_PATH = "/public/v1/federal/officials/{person_id}/money"
_PUBLIC_FEDERAL_CONTRIBUTORS_PATH = "/public/v1/federal/officials/{person_id}/contributors"
_PUBLIC_FEDERAL_EMPLOYERS_PATH = "/public/v1/federal/officials/{person_id}/employers"
_PUBLIC_FEDERAL_EXPORT_JSON_PATH = "/public/v1/federal/export.json"
_PUBLIC_FEDERAL_EXPORT_CSV_PATH = "/public/v1/federal/export.csv"
_PUBLIC_FEDERAL_METADATA_PATH = "/public/v1/federal/metadata"
_CONGRESS_MONEY_SUMMARIES_PATH = "/v1/congress/money-summaries"

_EXPECTED_PUBLIC_FEDERAL_OPERATION_IDS = {
    _PUBLIC_FEDERAL_OFFICIALS_PATH: "list_public_federal_officials",
    _PUBLIC_FEDERAL_MONEY_PATH: "get_public_federal_official_money",
    _PUBLIC_FEDERAL_CONTRIBUTORS_PATH: "get_public_federal_official_contributors",
    _PUBLIC_FEDERAL_EMPLOYERS_PATH: "get_public_federal_official_employers",
    _PUBLIC_FEDERAL_EXPORT_JSON_PATH: "export_public_federal_money_json",
    _PUBLIC_FEDERAL_EXPORT_CSV_PATH: "export_public_federal_money_csv",
    _PUBLIC_FEDERAL_METADATA_PATH: "get_public_federal_metadata",
}

# Routes that resolve one officeholder by path parameter, and therefore own the
# 404 contract for an unknown ``person_id``.
_PUBLIC_FEDERAL_PER_OFFICIAL_PATHS = (
    _PUBLIC_FEDERAL_MONEY_PATH,
    _PUBLIC_FEDERAL_CONTRIBUTORS_PATH,
    _PUBLIC_FEDERAL_EMPLOYERS_PATH,
)


class _ExpectedJsonSuccessSchema(NamedTuple):
    model_name: str
    is_array: bool


_EXPECTED_PUBLIC_FEDERAL_SUCCESS_JSON_SCHEMAS = {
    _PUBLIC_FEDERAL_OFFICIALS_PATH: _ExpectedJsonSuccessSchema("PublicFederalOfficial", is_array=True),
    _PUBLIC_FEDERAL_MONEY_PATH: _ExpectedJsonSuccessSchema("PublicMemberMoneySummary", is_array=False),
    _PUBLIC_FEDERAL_CONTRIBUTORS_PATH: _ExpectedJsonSuccessSchema("PublicContributorsResponse", is_array=False),
    _PUBLIC_FEDERAL_EMPLOYERS_PATH: _ExpectedJsonSuccessSchema("PublicEmployersResponse", is_array=False),
    _PUBLIC_FEDERAL_EXPORT_JSON_PATH: _ExpectedJsonSuccessSchema("PublicMemberMoneySummary", is_array=True),
    _PUBLIC_FEDERAL_METADATA_PATH: _ExpectedJsonSuccessSchema("PublicFederalMetadataResponse", is_array=False),
}

_EXPECTED_PUBLIC_FEDERAL_OFFICIALS_FILTERS = ("chamber", "state", "party")
_EXPECTED_FEDERAL_OFFICIAL_NOT_FOUND_SCHEMA = {
    "type": "object",
    "properties": {
        "detail": {
            "type": "string",
            "const": "Federal official not found",
        }
    },
    "required": ["detail"],
    "additionalProperties": False,
}
_EXPECTED_CANDIDATE_SUMMARY_UNAVAILABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "detail": {
            "type": "string",
            "const": "Candidate summary unavailable",
        }
    },
    "required": ["detail"],
    "additionalProperties": False,
}
_MEMBER_MONEY_CANDIDATE_SUMMARY_FAILURE_PATHS = (
    _PUBLIC_FEDERAL_EXPORT_JSON_PATH,
    _PUBLIC_FEDERAL_EXPORT_CSV_PATH,
    _PUBLIC_FEDERAL_MONEY_PATH,
    _CONGRESS_MONEY_SUMMARIES_PATH,
)


def _public_contract_source() -> SourceInfo:
    return SourceInfo(
        domain="campaign_finance",
        jurisdiction="federal",
        data_source_name="FEC itemized individual contributions",
        data_source_url="https://www.fec.gov/data/receipts/individual-contributions/",
        source_record_key="H4NC00000",
        record_url="https://www.fec.gov/data/candidate/H4NC00000/",
        pull_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )


def test_public_contributors_response_serialization_contract() -> None:
    person_id = UUID("11111111-1111-1111-1111-111111111111")
    response = PublicContributorsResponse(
        person_id=person_id,
        contributors=[
            PublicContributorRow(name="Sample Contributor", total_amount=Decimal("5000.00"), transaction_count=3)
        ],
        sources=[_public_contract_source()],
    )

    assert response.model_dump(mode="json") == {
        "person_id": str(person_id),
        "contributors": [{"name": "Sample Contributor", "total_amount": "5000.00", "transaction_count": 3}],
        "sources": [
            {
                "domain": "campaign_finance",
                "jurisdiction": "federal",
                "data_source_name": "FEC itemized individual contributions",
                "data_source_url": "https://www.fec.gov/data/receipts/individual-contributions/",
                "source_record_key": "H4NC00000",
                "record_url": "https://www.fec.gov/data/candidate/H4NC00000/",
                "pull_date": "2026-07-10T00:00:00Z",
            }
        ],
    }


def test_public_employers_response_serialization_contract() -> None:
    person_id = UUID("11111111-1111-1111-1111-111111111111")
    response = PublicEmployersResponse(
        person_id=person_id,
        employers=[
            PublicEmployerRow(
                employer="Unclassified / not provided",
                total_amount=Decimal("29150.00"),
                transaction_count=85,
                industry="UNKNOWN_INDUSTRY",
            )
        ],
        classified_count=837,
        unknown_count=13487,
        sampled_coverage_percentage=Decimal("5.843340"),
        sources=[_public_contract_source()],
    )

    assert response.model_dump(mode="json") == {
        "person_id": str(person_id),
        "employers": [
            {
                "employer": "Unclassified / not provided",
                "total_amount": "29150.00",
                "transaction_count": 85,
                "industry": "UNKNOWN_INDUSTRY",
            }
        ],
        "classified_count": 837,
        "unknown_count": 13487,
        "sampled_coverage_percentage": "5.843340",
        "sources": [
            {
                "domain": "campaign_finance",
                "jurisdiction": "federal",
                "data_source_name": "FEC itemized individual contributions",
                "data_source_url": "https://www.fec.gov/data/receipts/individual-contributions/",
                "source_record_key": "H4NC00000",
                "record_url": "https://www.fec.gov/data/candidate/H4NC00000/",
                "pull_date": "2026-07-10T00:00:00Z",
            }
        ],
    }


@pytest.mark.parametrize(
    "missing_metadata_key",
    ["classified_count", "unknown_count", "sampled_coverage_percentage"],
)
def test_public_employers_response_requires_industry_coverage_metadata(missing_metadata_key: str) -> None:
    response_data = {
        "person_id": UUID("11111111-1111-1111-1111-111111111111"),
        "employers": [],
        "classified_count": 837,
        "unknown_count": 13487,
        "sampled_coverage_percentage": Decimal("5.843340"),
        "sources": [_public_contract_source()],
    }
    del response_data[missing_metadata_key]

    with pytest.raises(ValidationError) as exc_info:
        PublicEmployersResponse.model_validate(response_data)

    assert exc_info.value.errors(include_url=False) == [
        {
            "type": "missing",
            "loc": (missing_metadata_key,),
            "msg": "Field required",
            "input": response_data,
        }
    ]


def _member_by_name(expectations: list[_CongressMemberExpectation], person_name: str) -> _CongressMemberExpectation:
    for expectation in expectations:
        if expectation.person_name == person_name:
            return expectation
    raise AssertionError(f"seed mix did not produce a member named {person_name!r}")


def _member_by_office_name(
    expectations: list[_CongressMemberExpectation],
    office_name: str,
) -> _CongressMemberExpectation:
    for expectation in expectations:
        if expectation.office_name == office_name:
            return expectation
    raise AssertionError(f"seed mix did not produce an officeholder for {office_name!r}")


def _public_money_row_for_person(payload: list[dict[str, object]], person_id: UUID) -> dict[str, object]:
    expected_person_id = str(person_id)
    for row in payload:
        if row["person_id"] == expected_person_id:
            return row
    raise AssertionError(f"public money export did not include person_id {expected_person_id}")


def _public_money_csv_rows(response_text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(response_text)))


def _public_money_csv_header(response_text: str) -> list[str]:
    reader = csv.DictReader(io.StringIO(response_text))
    return list(reader.fieldnames or [])


def _public_money_csv_row_for_person(response_text: str, person_id: UUID) -> dict[str, str]:
    expected_person_id = str(person_id)
    for row in _public_money_csv_rows(response_text):
        if row["person_id"] == expected_person_id:
            return row
    raise AssertionError(f"public money CSV export did not include person_id {expected_person_id}")


def _public_cache_control_header() -> str:
    return "public, max-age=900"


@lru_cache(maxsize=1)
def _generated_openapi_document() -> dict[str, Any]:
    """Return the OpenAPI document FastAPI generates for the assembled app.

    Schema generation reads route metadata only, so this deliberately bypasses
    the ``api_client`` fixture and ``api/conftest.py:_build_api_test_client``:
    both open a real connection pool, and routing these contract assertions
    through them would make the whole public-API drift guard skip whenever
    Postgres is unreachable. Cached because every assertion below shares one
    document — ``create_app()`` is never re-invoked per test.
    """
    from api.main import create_app

    return create_app().openapi()


def _public_federal_openapi_path_items() -> dict[str, dict[str, Any]]:
    """Return the generated ``/public/v1`` path items, keyed by OpenAPI path."""
    return {
        path: path_item
        for path, path_item in _generated_openapi_document()["paths"].items()
        if path.startswith(_PUBLIC_FEDERAL_OPENAPI_PATH_PREFIX)
    }


def _public_federal_openapi_get_operation(path: str) -> dict[str, Any]:
    path_item = _public_federal_openapi_path_items()[path]
    assert "get" in path_item, f"{path} no longer publishes a GET operation"
    return path_item["get"]


def _expected_success_json_schema(expected: _ExpectedJsonSuccessSchema) -> dict[str, Any]:
    model_ref = {"$ref": f"#/components/schemas/{expected.model_name}"}
    if expected.is_array:
        return {"type": "array", "items": model_ref}
    return model_ref


def _developers_page_label_for_openapi_path(path: str) -> str:
    """Map a published OpenAPI path to the label the developers page documents.

    OpenAPI owns the app-native ``/public/v1/...`` paths; only the developers
    page prepends the ``/api`` reverse-proxy prefix the deployment serves.
    """
    return f"{_DEVELOPERS_PAGE_PROXY_PREFIX}{path}"


def _developers_page_public_api_endpoint_labels(source: str) -> list[str]:
    return re.findall(r'"GET (/api/public/v1/[^"]+)"', source)


def _developers_page_csv_columns(source: str) -> list[str]:
    match = re.search(r"const csvColumns = \[(?P<body>.*?)\]\s+as const;", source, re.DOTALL)
    if match is None:
        raise AssertionError("developers page no longer declares csvColumns as a static array")
    return re.findall(r'"([^"]+)"', match.group("body"))


def test_public_federal_openapi_publishes_exactly_the_shipped_public_routes() -> None:
    """The generated document is the client-generation contract for ``/public/v1``.

    Goes red if a public route is deleted, renamed, or added without being
    added to this contract, and if a public path grows a non-GET operation.
    """
    path_items = _public_federal_openapi_path_items()

    assert set(path_items) == set(_EXPECTED_PUBLIC_FEDERAL_OPERATION_IDS)
    for path, path_item in path_items.items():
        assert set(path_item) & _OPENAPI_OPERATION_KEYS == {"get"}, f"{path} publishes non-GET operations"


@pytest.mark.parametrize("path", sorted(_EXPECTED_PUBLIC_FEDERAL_OPERATION_IDS))
def test_public_federal_openapi_operation_carries_client_generation_metadata(path: str) -> None:
    operation = _public_federal_openapi_get_operation(path)

    assert operation["operationId"] == _EXPECTED_PUBLIC_FEDERAL_OPERATION_IDS[path]
    assert operation["tags"] == [_PUBLIC_FEDERAL_OPENAPI_TAG]
    assert operation["summary"].strip()
    assert operation["description"].strip()


def test_public_federal_openapi_operation_ids_are_unique_across_the_document() -> None:
    """A generated client collides on ANY duplicate, not just a public-subset one."""
    operation_ids = [
        operation["operationId"]
        for path_item in _generated_openapi_document()["paths"].values()
        for operation_key, operation in path_item.items()
        if operation_key in _OPENAPI_OPERATION_KEYS
    ]

    assert len(operation_ids) == len(set(operation_ids))


def test_public_federal_openapi_officials_declares_documented_filter_parameters() -> None:
    operation = _public_federal_openapi_get_operation(_PUBLIC_FEDERAL_OFFICIALS_PATH)

    parameters_by_name = {parameter["name"]: parameter for parameter in operation["parameters"]}

    assert tuple(parameters_by_name) == _EXPECTED_PUBLIC_FEDERAL_OFFICIALS_FILTERS
    for parameter in parameters_by_name.values():
        assert parameter["in"] == "query"
        assert parameter["required"] is False
        assert parameter["description"].strip()
        assert parameter["schema"]["anyOf"] == [{"type": "string"}, {"type": "null"}]


@pytest.mark.parametrize("path", _PUBLIC_FEDERAL_PER_OFFICIAL_PATHS)
def test_public_federal_openapi_per_official_route_declares_uuid_lookup_contract(path: str) -> None:
    operation = _public_federal_openapi_get_operation(path)

    assert len(operation["parameters"]) == 1
    person_id_parameter = operation["parameters"][0]
    assert person_id_parameter["name"] == "person_id"
    assert person_id_parameter["in"] == "path"
    assert person_id_parameter["required"] is True
    assert person_id_parameter["schema"]["type"] == "string"
    assert person_id_parameter["schema"]["format"] == "uuid"
    not_found_response = operation["responses"]["404"]
    assert not_found_response["description"].strip()
    assert set(not_found_response["content"]) == {"application/json"}
    assert not_found_response["content"]["application/json"]["schema"] == (_EXPECTED_FEDERAL_OFFICIAL_NOT_FOUND_SCHEMA)


@pytest.mark.parametrize("path", sorted(_EXPECTED_PUBLIC_FEDERAL_SUCCESS_JSON_SCHEMAS))
def test_public_federal_openapi_success_response_references_its_response_model(path: str) -> None:
    operation = _public_federal_openapi_get_operation(path)

    success_content = operation["responses"]["200"]["content"]
    assert set(success_content) == {"application/json"}
    published_schema = success_content["application/json"]["schema"]
    # FastAPI appends an auto-derived ``title`` to composed (array) response
    # schemas; the client-relevant contract is the model reference and shape.
    assert {key: value for key, value in published_schema.items() if key != "title"} == _expected_success_json_schema(
        _EXPECTED_PUBLIC_FEDERAL_SUCCESS_JSON_SCHEMAS[path]
    )


def test_member_money_openapi_matches_sanitized_candidate_summary_failure_contract() -> None:
    """Every route over the shared builder must publish its executable 500."""
    openapi_paths = _generated_openapi_document()["paths"]

    for path in _MEMBER_MONEY_CANDIDATE_SUMMARY_FAILURE_PATHS:
        unavailable_response = openapi_paths[path]["get"]["responses"]["500"]
        assert unavailable_response["description"].strip()
        assert set(unavailable_response["content"]) == {"application/json"}
        assert (
            unavailable_response["content"]["application/json"]["schema"]
            == _EXPECTED_CANDIDATE_SUMMARY_UNAVAILABLE_SCHEMA
        )


def test_member_money_runtime_sanitizes_missing_candidate_summary_across_shared_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented 500 exposes no query or model failure detail."""
    person_id = UUID("11111111-1111-1111-1111-111111111111")
    candidate_id = UUID("22222222-2222-2222-2222-222222222222")
    member = {
        "person_id": person_id,
        "person_name": "Contract Evidence Executive",
        "chamber": "Executive",
        "office_name": "President of the United States",
        "state": "US",
        "district": None,
        "officeholding_source_record_id": None,
    }
    candidate = {
        "id": candidate_id,
        "name": "Contract Evidence Candidate",
        "office": "P",
        "state": "US",
        "district": "00",
        "has_selected_cycle_link": True,
        "source_record_id": None,
    }

    monkeypatch.setattr(public_federal_route_module, "fetch_current_federal_members", lambda _conn: [member])
    monkeypatch.setattr(
        public_federal_route_module,
        "fetch_candidates_for_people",
        lambda _conn, _person_ids: {person_id: [candidate]},
    )
    monkeypatch.setattr(
        public_federal_route_module,
        "fetch_candidate_public_money_summaries",
        lambda _conn, _candidate_refs: {},
    )
    monkeypatch.setattr(public_federal_route_module, "fetch_candidate_summary", lambda *_args, **_kwargs: None)

    app = FastAPI()
    app.include_router(router)
    app.include_router(civics_route_module.router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[enforce_public_ip_rate_limit] = lambda: None

    with TestClient(app) as client:
        for path in (
            _PUBLIC_FEDERAL_EXPORT_JSON_PATH,
            _PUBLIC_FEDERAL_EXPORT_CSV_PATH,
            f"/public/v1/federal/officials/{person_id}/money",
            _CONGRESS_MONEY_SUMMARIES_PATH,
        ):
            response = client.get(path)
            assert response.status_code == 500
            assert response.headers["content-type"].startswith("application/json")
            assert response.json() == {"detail": "Candidate summary unavailable"}


def test_public_federal_openapi_csv_export_publishes_only_a_text_csv_body() -> None:
    """``application/json`` here would make generated clients JSON-decode CSV."""
    operation = _public_federal_openapi_get_operation(_PUBLIC_FEDERAL_EXPORT_CSV_PATH)

    success_content = operation["responses"]["200"]["content"]

    assert set(success_content) == {"text/csv"}
    assert success_content["text/csv"]["schema"] == {"type": "string"}


@pytest.mark.parametrize("path", sorted(_EXPECTED_PUBLIC_FEDERAL_OPERATION_IDS))
def test_public_federal_openapi_operation_declares_no_authentication_requirement(path: str) -> None:
    """The authless surface must never publish a security requirement."""
    operation = _public_federal_openapi_get_operation(path)

    assert operation.get("security", []) == []


def test_public_federal_metadata_operation_references_metadata_response_model() -> None:
    operation = _public_federal_openapi_get_operation(_PUBLIC_FEDERAL_METADATA_PATH)

    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success_schema == {"$ref": "#/components/schemas/PublicFederalMetadataResponse"}
    assert operation["operationId"] == "get_public_federal_metadata"


def test_public_top_donors_disclosure_is_unresolved_while_query_skips_resolution() -> None:
    """The public donor list groups by raw contributor identity, not resolved clusters.

    Goes red if the public top-donors query starts applying donor-identity
    resolution while the disclosure still claims ``"unresolved"``.
    """
    from api.queries.campaign_finance import (
        _PERSON_TOP_DONORS_SELECT_SQL,
        public_top_donors_identity_resolution_status,
    )

    assert "resolved_donor_identity_id" not in _PERSON_TOP_DONORS_SELECT_SQL
    assert public_top_donors_identity_resolution_status() == "unresolved"


def test_developers_page_public_api_reference_matches_router_contract() -> None:
    developers_page_source = Path("web/src/routes/developers/+page.svelte").read_text()

    published_public_paths = {
        _developers_page_label_for_openapi_path(path) for path in _public_federal_openapi_path_items()
    }
    documented_public_paths = _developers_page_public_api_endpoint_labels(developers_page_source)
    documented_csv_columns = _developers_page_csv_columns(developers_page_source)

    assert f"<code>{router.prefix}</code>" in developers_page_source
    assert len(documented_public_paths) == len(set(documented_public_paths))
    assert set(documented_public_paths) == published_public_paths
    assert documented_csv_columns == PUBLIC_FEDERAL_EXPORT_CSV_COLUMNS


def _seed_member_with_money_and_ie(
    db_conn: psycopg.Connection,
) -> tuple[_CongressMemberExpectation, UUID]:
    """Seed the federal directory and wire ONE member to FEC money + IE.

    Uses the shared campaign-finance seed primitives (the canonical seed owner)
    rather than copy-pasting inserts. The dedicated ``_seed_candidate_and_committee_for_ie``
    helper cannot be reused here because it creates its own candidate with no
    ``person_id``, and this endpoint resolves money through the member's person link.
    "Alice Representative" is chosen because the base directory mix seeds no
    ``cf.candidate`` for her (only "Blair Senator" carries an ``fec_candidate_id``).
    """
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")

    candidate_id = UUID("bb000000-0000-0000-0000-000000000001")
    committee_id = UUID("bb000000-0000-0000-0000-000000000010")
    filing_id = UUID("bb000000-0000-0000-0000-000000000020")

    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC01999",
            name="Alice Representative",
            office="H",
            person_id=member.person_id,
            party="DEM",
            state="NC",
            district="01",
            # Official FEC weball totals drive the fec_weball summary path.
            total_receipts=Decimal("9000.00"),
            total_disbursements=Decimal("1000.00"),
            cash_on_hand=Decimal("8000.00"),
            summary_coverage_end_date=date(2026, 12, 31),
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C99990001",
            name="Alice Support PAC",
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id="filing-C99990001",
            committee_id=committee_id,
        ),
    )
    # One support ($250) + one oppose ($100) IE transaction targeting the candidate.
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("bb000000-0000-0000-0000-000000000101"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24E",
            amount=Decimal("250.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 6, 1),
            recipient_candidate_id=candidate_id,
            support_oppose="S",
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("bb000000-0000-0000-0000-000000000102"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24A",
            amount=Decimal("100.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 6, 1),
            recipient_candidate_id=candidate_id,
            support_oppose="O",
        ),
    )
    return member, candidate_id


def _seed_member_with_public_breadth_transactions(
    db_conn: psycopg.Connection,
) -> tuple[_CongressMemberExpectation, str, str]:
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")

    candidate_id = UUID("bc000000-0000-0000-0000-000000000001")
    committee_id = UUID("bc000000-0000-0000-0000-000000000010")
    filing_id = UUID("bc000000-0000-0000-0000-000000000020")
    current_source_id = UUID("bc000000-0000-0000-0000-000000000101")
    out_of_cycle_source_id = UUID("bc000000-0000-0000-0000-000000000102")
    superseded_source_id = UUID("bc000000-0000-0000-0000-000000000103")

    data_source = insert_data_source_for_test(
        db_conn,
        jurisdiction="federal",
        name_suffix="public-itemized-contributions",
    )
    current_source = insert_source_record_for_test(
        db_conn,
        source_record_id=current_source_id,
        data_source_id=data_source.id,
        source_record_key="public-contribution-current",
        source_url="https://www.fec.gov/data/receipts/individual-contributions/?committee_id=C99990002",
        pull_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    out_of_cycle_source = insert_source_record_for_test(
        db_conn,
        source_record_id=out_of_cycle_source_id,
        data_source_id=data_source.id,
        source_record_key="public-contribution-out-of-cycle",
        source_url="https://example.org/fec/out-of-cycle",
        pull_date=datetime(2024, 7, 10, tzinfo=timezone.utc),
    )
    superseded_source = insert_source_record_for_test(
        db_conn,
        source_record_id=superseded_source_id,
        data_source_id=data_source.id,
        source_record_key="public-contribution-superseded",
        source_url="https://example.org/fec/superseded",
        pull_date=datetime(2026, 7, 9, tzinfo=timezone.utc),
        superseded_by=current_source.id,
    )

    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC01998",
            name="Alice Representative",
            office="H",
            person_id=member.person_id,
            party="DEM",
            state="NC",
            district="01",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C99990002",
            name="Alice Public Breadth Committee",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("bc000000-0000-0000-0000-000000000030"),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2025-01-01,2027-01-01)",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id="public-breadth-filing",
            committee_id=committee_id,
        ),
    )

    transaction_specs = [
        ("000201", date(2026, 4, 1), Decimal("1000.00"), "ZOE CURRENT", "GOOGLE", current_source.id),
        ("000202", date(2026, 5, 1), Decimal("250.00"), "ZOE CURRENT", "GOOGLE", current_source.id),
        ("000203", date(2026, 6, 1), Decimal("300.00"), "ALEX UNKNOWN", "", current_source.id),
        ("000204", date(2024, 6, 1), Decimal("4000.00"), "OUT OF CYCLE", "GOOGLE", out_of_cycle_source.id),
        ("000205", date(2026, 6, 2), Decimal("5000.00"), "SUPERSEDED DONOR", "GOOGLE", superseded_source.id),
        ("000206", date(2026, 6, 3), Decimal("7000.00"), "UNSOURCED DONOR", "UNSOURCED EMPLOYER", None),
    ]
    for suffix, transaction_date, amount, contributor_name, employer, source_record_id in transaction_specs:
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=UUID(f"bc000000-0000-0000-0000-000000{suffix}"),
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="15",
                amount=amount,
                amendment_indicator="N",
                source_record_id=source_record_id,
                transaction_date=transaction_date,
                contributor_name_raw=contributor_name,
                contributor_entity_type="IND",
                contributor_employer=employer,
                contributor_city="Raleigh",
                contributor_state="NC",
                contributor_zip="27601",
            ),
        )

    return member, current_source.source_record_key, current_source.source_url


def _insert_candidate_with_official_totals(
    db_conn: psycopg.Connection,
    *,
    candidate_id: UUID,
    fec_candidate_id: str,
    name: str,
    person_id: UUID,
    office: str,
    state: str | None,
    district: str | None,
    total_receipts: Decimal,
    total_disbursements: Decimal,
    cash_on_hand: Decimal,
    summary_coverage_end_date: date = date(2026, 12, 31),
    source_record_id: UUID | None = None,
) -> None:
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id=fec_candidate_id,
            name=name,
            office=office,
            person_id=person_id,
            party="DEM",
            state=state,
            district=district,
            total_receipts=total_receipts,
            total_disbursements=total_disbursements,
            cash_on_hand=cash_on_hand,
            summary_coverage_end_date=summary_coverage_end_date,
            source_record_id=source_record_id,
        ),
    )


def _seed_member_with_candidate_direct_source(
    db_conn: psycopg.Connection,
    *,
    last_pull_at: datetime | None = None,
    last_pull_status: str | None = None,
) -> tuple[_CongressMemberExpectation, UUID, str]:
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")
    source_url = "https://example.org/fec/public-candidate-direct"
    data_source = insert_data_source_for_test(
        db_conn,
        jurisdiction="federal/fec",
        name_suffix="public-money-source",
        last_pull_at=last_pull_at,
        last_pull_status=last_pull_status,
    )
    candidate_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("bb000000-0000-0000-0000-000000000301"),
        data_source_id=data_source.id,
        source_record_key="public-candidate-direct",
        source_url=source_url,
        pull_date=datetime(2026, 3, 17, 9, 30, tzinfo=timezone.utc),
    )
    person_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("bb000000-0000-0000-0000-000000000302"),
        data_source_id=data_source.id,
        source_record_key="public-person-fallback",
        source_url="https://example.org/fec/public-person-fallback",
        pull_date=datetime(2026, 3, 16, 9, 30, tzinfo=timezone.utc),
    )
    insert_entity_source(db_conn, "person", member.person_id, person_source.id, "candidate")
    candidate_id = UUID("bb000000-0000-0000-0000-000000000303")
    _insert_candidate_with_official_totals(
        db_conn,
        candidate_id=candidate_id,
        fec_candidate_id="H0NC01003",
        name="Alice Source Linked Candidate",
        person_id=member.person_id,
        office="H",
        state="NC",
        district="01",
        total_receipts=Decimal("333.00"),
        total_disbursements=Decimal("30.00"),
        cash_on_hand=Decimal("303.00"),
        source_record_id=candidate_source.id,
    )
    return member, candidate_id, source_url


def test_public_federal_list_and_detail_share_effective_provenance_freshness(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    effective_pull_at = datetime(2026, 7, 25, 7, 35, 34, tzinfo=timezone.utc)
    member, _candidate_id, _source_url = _seed_member_with_candidate_direct_source(
        db_conn,
        last_pull_at=effective_pull_at,
        last_pull_status="success",
    )

    export_response = api_client.get("/public/v1/federal/export.json")
    detail_response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")

    assert export_response.status_code == 200
    assert detail_response.status_code == 200
    export_sources = _public_money_row_for_person(export_response.json(), member.person_id)["sources"]
    detail_sources = detail_response.json()["sources"]
    expected_source_record_keys = [
        "public-candidate-direct",
        "public-person-fallback",
    ]
    expected_pull_dates = [
        "2026-07-25T07:35:34Z",
        "2026-07-25T07:35:34Z",
    ]
    assert [source["source_record_key"] for source in export_sources] == expected_source_record_keys
    assert [source["pull_date"] for source in export_sources] == expected_pull_dates
    assert [source["source_record_key"] for source in detail_sources] == expected_source_record_keys
    assert [source["pull_date"] for source in detail_sources] == expected_pull_dates
    assert export_sources == detail_sources


def test_public_officials_requires_no_api_key(db_conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """The public router is authless even under a production, keyed configuration.

    Built WITHOUT the ``api_client`` fixture (which overrides
    ``require_authorized_request``) so the real auth dependency runs: the private
    ``/v1`` surface must 401, the ``/public/v1`` surface must 200.
    """
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "public-federal-red-test-key")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", "100")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "60")

    from api.main import create_app

    app = create_app()

    def _get_db_override():
        yield db_conn

    app.dependency_overrides[get_db] = _get_db_override
    try:
        with TestClient(app) as client:
            assert client.get("/v1/candidates").status_code == 401
            assert client.get("/public/v1/federal/officials").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_public_endpoints_return_cache_control_header(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")

    public_paths = [
        "/public/v1/federal/officials",
        f"/public/v1/federal/officials/{member.person_id}/money",
        f"/public/v1/federal/officials/{member.person_id}/contributors",
        f"/public/v1/federal/officials/{member.person_id}/employers",
        "/public/v1/federal/export.json",
        "/public/v1/federal/export.csv",
    ]

    for path in public_paths:
        response = api_client.get(path)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == _public_cache_control_header()

    unknown_person_id = uuid4()
    for path in [
        f"/public/v1/federal/officials/{unknown_person_id}/contributors",
        f"/public/v1/federal/officials/{unknown_person_id}/employers",
    ]:
        response = api_client.get(path)
        assert response.status_code == 404
        assert response.json() == {"detail": "Federal official not found"}
        assert response.headers["Cache-Control"] == _public_cache_control_header()

    private_response = api_client.get("/v1/person/not-a-uuid")
    assert private_response.status_code == 422
    assert "Cache-Control" not in private_response.headers


def test_public_endpoints_ip_rate_limited_without_api_key(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    _without_persisted_full_scope_latency_fixture: None,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "private-key-for-public-rate-test")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("CIVIBUS_RATE_LIMIT_WINDOW_SECONDS", "30")

    from api.main import create_app

    app = create_app()

    def _get_db_override():
        yield db_conn

    app.dependency_overrides[get_db] = _get_db_override
    try:
        with TestClient(app) as client:
            first_response = client.get("/public/v1/federal/officials")
            second_response = client.get("/public/v1/federal/officials")
            limited_response = client.get("/public/v1/federal/officials")
    finally:
        app.dependency_overrides.clear()

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert limited_response.status_code == 429
    assert limited_response.json() == {"detail": "Rate limit exceeded"}
    assert 0 < int(limited_response.headers["Retry-After"]) <= 30


def test_public_officials_returns_directory_projection(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    _without_persisted_full_scope_latency_fixture: None,
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)

    response = api_client.get("/public/v1/federal/officials")

    assert response.status_code == 200
    assert response.json() == _expected_congress_http_rows(expectations)


def test_public_officials_excludes_namesake_challenger(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    _without_persisted_full_scope_latency_fixture: None,
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    officeholder = _member_by_name(expectations, "Alice Representative")
    _insert_namesake_challenger_candidacy(
        db_conn,
        officeholder,
        person_id=UUID("00000000-0000-0000-0000-000000000045"),
    )

    response = api_client.get("/public/v1/federal/officials")

    assert response.status_code == 200
    assert response.json() == _expected_congress_http_rows(expectations)


def test_public_officials_chamber_filter_returns_only_senate(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    _without_persisted_full_scope_latency_fixture: None,
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    expected_senate_names = sorted(
        expectation.person_name for expectation in expectations if expectation.chamber == "Senate"
    )
    # Guard the fixture itself: the directory mix must contain Senate members.
    assert expected_senate_names

    response = api_client.get("/public/v1/federal/officials", params={"chamber": "Senate"})

    assert response.status_code == 200
    payload = response.json()
    assert {row["chamber"] for row in payload} == {"Senate"}
    assert sorted(row["person_name"] for row in payload) == expected_senate_names


def test_public_member_money_returns_official_totals_and_ie(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    member, candidate_id = _seed_member_with_money_and_ie(db_conn)

    response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")

    assert response.status_code == 200
    payload = response.json()
    assert payload["person_id"] == str(member.person_id)
    assert payload["person_name"] == member.person_name
    assert payload["has_fec_money"] is True
    assert payload["candidate_id"] == str(candidate_id)
    assert payload["summary_source"] == "fec_weball"
    # Hand-calculated: net = 9000.00 - 1000.00.
    assert payload["total_raised"] == "9000.00"
    assert payload["total_spent"] == "1000.00"
    assert payload["net"] == "8000.00"
    assert payload["cash_on_hand"] == "8000.00"
    # IE: one support ($250) + one oppose ($100) row.
    assert payload["ie_support_total"] == "250.00"
    assert payload["ie_oppose_total"] == "100.00"
    assert payload["ie_support_count"] == 1
    assert payload["ie_oppose_count"] == 1

    # Cross-check IE totals against the private per-candidate IE summary endpoint.
    ie_response = api_client.get(f"/v1/candidates/{candidate_id}/independent-expenditures/summary")
    assert ie_response.status_code == 200
    ie_payload = ie_response.json()
    assert payload["ie_support_total"] == ie_payload["support_total"]
    assert payload["ie_oppose_total"] == ie_payload["oppose_total"]
    assert payload["ie_support_count"] == ie_payload["support_count"]
    assert payload["ie_oppose_count"] == ie_payload["oppose_count"]


def test_public_official_contributors_returns_default_cycle_totals_and_transaction_sources(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    member, expected_source_record_key, expected_record_url = _seed_member_with_public_breadth_transactions(db_conn)

    response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/contributors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["person_id"] == str(member.person_id)
    assert payload["contributors"][0] == {
        "name": "ZOE CURRENT",
        "total_amount": "1250.00",
        "transaction_count": 2,
    }
    contributor_names = [row["name"] for row in payload["contributors"]]
    assert "OUT OF CYCLE" not in contributor_names
    assert "SUPERSEDED DONOR" not in contributor_names
    assert "UNSOURCED DONOR" not in contributor_names
    assert [source["source_record_key"] for source in payload["sources"]] == [expected_source_record_key]
    assert payload["sources"][0]["record_url"] == expected_record_url
    assert payload["sources"][0]["pull_date"] == "2026-07-10T00:00:00Z"


def test_public_official_contributors_keep_source_backed_selection_separate_from_private_breadth(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    member, expected_source_record_key, expected_record_url = _seed_member_with_public_breadth_transactions(db_conn)

    private_response = api_client.get(f"/v1/person/{member.person_id}/top-donors?cycle=2026")
    public_response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/contributors")

    assert private_response.status_code == 200
    private_payload = private_response.json()
    assert [row["name"] for row in private_payload] == [
        "UNSOURCED DONOR",
        "ZOE CURRENT",
        "ALEX UNKNOWN",
    ]
    assert private_payload[0] == {
        "name": "UNSOURCED DONOR",
        "total_amount": "7000.00",
        "transaction_count": 1,
        "city": "Raleigh",
        "state": "NC",
    }
    assert "OUT OF CYCLE" not in [row["name"] for row in private_payload]
    assert "SUPERSEDED DONOR" not in [row["name"] for row in private_payload]

    assert public_response.status_code == 200
    public_payload = public_response.json()
    assert public_payload["contributors"] == [
        {
            "name": "ZOE CURRENT",
            "total_amount": "1250.00",
            "transaction_count": 2,
        },
        {
            "name": "ALEX UNKNOWN",
            "total_amount": "300.00",
            "transaction_count": 1,
        },
    ]
    public_contributor_names = [row["name"] for row in public_payload["contributors"]]
    assert "UNSOURCED DONOR" not in public_contributor_names
    assert "OUT OF CYCLE" not in public_contributor_names
    assert "SUPERSEDED DONOR" not in public_contributor_names
    assert [source["source_record_key"] for source in public_payload["sources"]] == [expected_source_record_key]
    assert public_payload["sources"][0]["record_url"] == expected_record_url
    assert public_payload["sources"][0]["pull_date"] == "2026-07-10T00:00:00Z"


def test_public_official_employers_returns_default_cycle_totals_industries_and_transaction_sources(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    member, expected_source_record_key, expected_record_url = _seed_member_with_public_breadth_transactions(db_conn)

    response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/employers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["person_id"] == str(member.person_id)
    assert payload["employers"] == [
        {
            "employer": "GOOGLE",
            "total_amount": "1250.00",
            "transaction_count": 2,
            "industry": "Technology",
        },
        {
            "employer": "Unclassified / not provided",
            "total_amount": "300.00",
            "transaction_count": 1,
            "industry": "UNKNOWN_INDUSTRY",
        },
    ]
    assert payload["classified_count"] == 837
    assert payload["unknown_count"] == 13487
    assert payload["sampled_coverage_percentage"] == "5.843340"
    assert [source["source_record_key"] for source in payload["sources"]] == [expected_source_record_key]
    assert payload["sources"][0]["record_url"] == expected_record_url


def test_public_official_employers_keep_source_backed_selection_separate_from_private_breadth(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    member, expected_source_record_key, expected_record_url = _seed_member_with_public_breadth_transactions(db_conn)

    private_response = api_client.get(f"/v1/person/{member.person_id}/top-employers?cycle=2026")
    public_response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/employers")

    assert private_response.status_code == 200
    private_payload = private_response.json()
    assert private_payload == [
        {
            "employer": "UNSOURCED EMPLOYER",
            "total_amount": "7000.00",
            "transaction_count": 1,
            "industry": "UNKNOWN_INDUSTRY",
            "industry_rollup_eligible": True,
        },
        {
            "employer": "GOOGLE",
            "total_amount": "1250.00",
            "transaction_count": 2,
            "industry": "Technology",
            "industry_rollup_eligible": True,
        },
        {
            "employer": "Unclassified / not provided",
            "total_amount": "300.00",
            "transaction_count": 1,
            "industry": "UNKNOWN_INDUSTRY",
            "industry_rollup_eligible": False,
        },
    ]

    assert public_response.status_code == 200
    public_payload = public_response.json()
    assert public_payload["employers"] == [
        {
            "employer": "GOOGLE",
            "total_amount": "1250.00",
            "transaction_count": 2,
            "industry": "Technology",
        },
        {
            "employer": "Unclassified / not provided",
            "total_amount": "300.00",
            "transaction_count": 1,
            "industry": "UNKNOWN_INDUSTRY",
        },
    ]
    public_employer_names = [row["employer"] for row in public_payload["employers"]]
    assert "UNSOURCED EMPLOYER" not in public_employer_names
    assert "OUT OF CYCLE" not in public_employer_names
    assert public_payload["classified_count"] == 837
    assert public_payload["unknown_count"] == 13487
    assert public_payload["sampled_coverage_percentage"] == "5.843340"
    assert [source["source_record_key"] for source in public_payload["sources"]] == [expected_source_record_key]
    assert public_payload["sources"][0]["record_url"] == expected_record_url
    assert public_payload["sources"][0]["pull_date"] == "2026-07-10T00:00:00Z"


def test_full_scope_latency_fixture_keeps_every_official_money_and_ie_linked(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_full_scope_skewed_donor_search_fixture(db_conn)

    response = api_client.get("/public/v1/federal/export.json")

    expected_current_officeholders = 518
    assert fixture.counts.current_federal_officeholders == expected_current_officeholders
    assert fixture.counts.linked_people == expected_current_officeholders
    assert fixture.counts.distinct_linked_committees == expected_current_officeholders
    assert fixture.counts.candidate_scope_rows == 526
    assert fixture.counts.official_total_candidates == fixture.counts.candidate_scope_rows
    assert fixture.counts.support_ie_candidates == expected_current_officeholders
    assert fixture.counts.oppose_ie_candidates == expected_current_officeholders
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == expected_current_officeholders
    assert len({row["person_id"] for row in payload}) == len(payload)
    rows_without_selected_ie = 0
    for row in payload:
        assert row["has_fec_money"] is True
        assert row["candidate_id"]
        assert row["summary_source"] == "fec_weball"
        assert [source["source_record_key"] for source in row["sources"]] == ["donor-search-current"]
        if row["ie_support_count"] == 0 and row["ie_oppose_count"] == 0:
            assert row["ie_support_total"] == "0.00"
            assert row["ie_oppose_total"] == "0.00"
            rows_without_selected_ie += 1
            continue
        assert Decimal(row["ie_support_total"]) > Decimal("0.00")
        assert Decimal(row["ie_oppose_total"]) > Decimal("0.00")
        assert row["ie_support_count"] > 0
        assert row["ie_oppose_count"] > 0
    assert rows_without_selected_ie == (
        fixture.counts.official_total_candidates - fixture.counts.current_federal_officeholders
    )
    representative = _public_money_row_for_person(payload, fixture.primary_recipient.person_id)
    assert representative["person_name"] == "Full Scope Officeholder 000"
    assert representative["candidate_id"] == str(fixture.primary_recipient.candidate_id)
    assert representative["summary_source"] == "fec_weball"
    assert representative["total_raised"] == "10000.00"
    assert representative["total_spent"] == "2500.00"
    assert representative["net"] == "7500.00"
    assert representative["cash_on_hand"] == "7500.00"
    assert representative["ie_support_total"] == "25.00"
    assert representative["ie_oppose_total"] == "10.00"
    assert representative["ie_support_count"] == 1
    assert representative["ie_oppose_count"] == 1
    assert [source["source_record_key"] for source in representative["sources"]] == ["donor-search-current"]


def test_full_scope_fixture_candidate_ids_do_not_collide_with_real_fec_candidate_id(
    db_conn: psycopg.Connection,
) -> None:
    real_candidate_id = UUID("71000000-0000-4000-8000-000000000324")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=real_candidate_id,
            fec_candidate_id="S6NC00324",
            name="Real FEC Candidate S6NC00324",
            office="S",
            state="NC",
        ),
    )

    fixture = seed_full_scope_skewed_donor_search_fixture(db_conn)

    real_candidate = db_conn.execute(
        "SELECT id, name FROM cf.candidate WHERE fec_candidate_id = 'S6NC00324'"
    ).fetchone()
    fixture_candidates_using_real_fec_id = db_conn.execute(
        """
        SELECT COUNT(*)::integer
        FROM cf.candidate
        WHERE id::text LIKE '72000000-%'
          AND fec_candidate_id = 'S6NC00324'
        """
    ).fetchone()
    assert real_candidate == (real_candidate_id, "Real FEC Candidate S6NC00324")
    assert fixture_candidates_using_real_fec_id == (0,)
    assert fixture.counts.linked_people == 518
    assert fixture.counts.candidate_scope_rows == 526
    assert fixture.counts.unrelated_candidate_rows == 300


def test_donor_search_fixture_cleanup_preserves_non_fixture_committee_summary(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("72000000-ffff-4fff-8fff-ffffffffffff")
    person_id = UUID("72000000-ffff-4fff-8fff-fffffffffff0")
    db_conn.execute(
        "INSERT INTO core.person (id, canonical_name) VALUES (%s, %s)",
        (person_id, "Legitimate Person With Fixture-Like UUID"),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C99999998",
            name="Legitimate Committee With Fixture-Like UUID",
            state="NC",
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=Decimal("123.45"),
        ),
    )

    cleanup_donor_search_fixture(db_conn)

    preserved_rows = db_conn.execute(
        """
        SELECT committee.name, summary.cycle, summary.total_receipts
        FROM cf.committee committee
        JOIN cf.committee_summary summary ON summary.committee_id = committee.id
        WHERE committee.id = %s
        """,
        (committee_id,),
    ).fetchall()
    preserved_person = db_conn.execute(
        "SELECT canonical_name FROM core.person WHERE id = %s",
        (person_id,),
    ).fetchone()
    assert preserved_rows == [("Legitimate Committee With Fixture-Like UUID", 2026, Decimal("123.45"))]
    assert preserved_person == ("Legitimate Person With Fixture-Like UUID",)


def test_donor_search_fixture_cleanup_preserves_other_data_source_with_same_source_record_key(
    db_conn: psycopg.Connection,
) -> None:
    # source_record_key is unique only within a data source, so an unrelated data
    # source may legitimately reuse the key "donor-search-current". Cleanup must
    # scope by the fixture data source and leave that unrelated committee/summary,
    # source record, and officeholding intact.
    fixture = seed_donor_search_fixture(db_conn)
    unrelated_source = insert_data_source_for_test(
        db_conn,
        jurisdiction="state/nc",
        name_suffix="unrelated-donor-search",
    )
    unrelated_source_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("73000000-0000-4000-8000-000000000001"),
        data_source_id=unrelated_source.id,
        source_record_key="donor-search-current",
        source_url="https://example.org/unrelated/donor-search-current",
        pull_date=datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc),
    )
    committee_id = UUID("73000000-0000-4000-8000-000000000002")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C88888887",
            name="Unrelated Data Source Committee",
            source_record_id=unrelated_source_record.id,
            state="NC",
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=Decimal("456.78"),
        ),
    )
    unrelated_officeholding_id = UUID("73000000-0000-4000-8000-000000000005")
    db_conn.execute(
        """
        WITH inserted_division AS (
            INSERT INTO civic.electoral_division (id, name, division_type, state)
            VALUES ('73000000-0000-4000-8000-000000000003', 'Unrelated division', 'statewide', 'NC')
            RETURNING id
        ), inserted_office AS (
            INSERT INTO civic.office (id, name, office_level, title, state, electoral_division_id)
            SELECT
                '73000000-0000-4000-8000-000000000004',
                'unrelated_office',
                'state',
                'Unrelated official',
                'NC',
                id
            FROM inserted_division
            RETURNING id, electoral_division_id
        )
        INSERT INTO civic.officeholding (
            id, person_id, office_id, electoral_division_id, valid_period, source_record_id
        )
        SELECT %s, %s, id, electoral_division_id, '[2010-01-01,2011-01-01)', %s
        FROM inserted_office
        """,
        (unrelated_officeholding_id, fixture.alpha.person_id, unrelated_source_record.id),
    )

    cleanup_donor_search_fixture(db_conn)

    preserved_rows = db_conn.execute(
        """
        SELECT committee.name, summary.cycle, summary.total_receipts
        FROM cf.committee committee
        JOIN cf.committee_summary summary ON summary.committee_id = committee.id
        WHERE committee.id = %s
        """,
        (committee_id,),
    ).fetchall()
    preserved_source_record = db_conn.execute(
        "SELECT source_record_key FROM core.source_record WHERE id = %s",
        (unrelated_source_record.id,),
    ).fetchone()
    preserved_officeholding = db_conn.execute(
        "SELECT person_id, source_record_id FROM civic.officeholding WHERE id = %s",
        (unrelated_officeholding_id,),
    ).fetchone()
    assert preserved_rows == [("Unrelated Data Source Committee", 2026, Decimal("456.78"))]
    assert preserved_source_record == ("donor-search-current",)
    assert preserved_officeholding == (fixture.alpha.person_id, unrelated_source_record.id)


def test_donor_search_fixture_can_be_seeded_twice_with_exact_counts(
    db_conn: psycopg.Connection,
) -> None:
    first_fixture = seed_donor_search_fixture(db_conn)

    second_fixture = seed_donor_search_fixture(db_conn)

    fixture_counts = db_conn.execute(
        """
        WITH fixture_source_records AS (
            SELECT source_record.id
            FROM core.source_record source_record
            JOIN core.data_source data_source ON data_source.id = source_record.data_source_id
            WHERE data_source.domain = 'campaign_finance'
              AND data_source.jurisdiction = 'federal/fec'
              AND data_source.name = 'Campaign Finance API Source donor-search-fixture'
        )
        SELECT
            (SELECT COUNT(*) FROM fixture_source_records)::integer,
            (
                SELECT COUNT(*)
                FROM civic.officeholding officeholding
                WHERE EXISTS (
                    SELECT 1
                    FROM cf.candidate candidate
                    WHERE candidate.person_id = officeholding.person_id
                      AND candidate.source_record_id IN (SELECT id FROM fixture_source_records)
                )
            )::integer,
            (
                SELECT COUNT(*) FROM cf.candidate
                WHERE source_record_id IN (SELECT id FROM fixture_source_records)
            )::integer,
            (
                SELECT COUNT(*) FROM cf.committee
                WHERE source_record_id IN (SELECT id FROM fixture_source_records)
            )::integer,
            (
                SELECT COUNT(*) FROM cf.filing
                WHERE source_record_id IN (SELECT id FROM fixture_source_records)
            )::integer,
            (
                SELECT COUNT(*) FROM cf.transaction
                WHERE source_record_id IN (SELECT id FROM fixture_source_records)
            )::integer
        """
    ).fetchone()
    assert first_fixture == second_fixture
    assert fixture_counts == (4, 3, 5, 4, 4, 12)


def test_full_scope_donor_search_fixture_can_be_seeded_twice_with_exact_counts(
    db_conn: psycopg.Connection,
) -> None:
    first_fixture = seed_full_scope_skewed_donor_search_fixture(db_conn)

    second_fixture = seed_full_scope_skewed_donor_search_fixture(db_conn)

    expected_counts = DonorSearchFullScopeCounts(
        current_federal_officeholders=518,
        linked_people=518,
        candidate_scope_rows=526,
        distinct_linked_committees=518,
        unrelated_candidate_rows=300,
        common_surname_transactions=250,
        official_total_candidates=526,
        support_ie_candidates=518,
        oppose_ie_candidates=518,
    )
    assert first_fixture.counts == expected_counts
    assert second_fixture.counts == expected_counts
    assert first_fixture.primary_recipient == second_fixture.primary_recipient
    assert first_fixture.secondary_recipient == second_fixture.secondary_recipient


def test_donor_search_fixture_cleanup_preserves_prefixed_transaction_from_other_data_source(
    db_conn: psycopg.Connection,
) -> None:
    unrelated_source = insert_data_source_for_test(
        db_conn,
        jurisdiction="state/nc",
        name_suffix="unrelated-prefixed-transaction",
    )
    unrelated_source_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("73000000-0000-4000-8000-000000000011"),
        data_source_id=unrelated_source.id,
        source_record_key="unrelated-prefixed-transaction",
        source_url="https://example.org/unrelated/prefixed-transaction",
        pull_date=datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc),
    )
    committee_id = UUID("73000000-0000-4000-8000-000000000012")
    filing_id = UUID("73000000-0000-4000-8000-000000000013")
    transaction_id = UUID("73000000-0000-4000-8000-000000000014")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C88888886",
            name="Unrelated Prefixed Transaction Committee",
            source_record_id=unrelated_source_record.id,
            state="NC",
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id="unrelated-prefixed-transaction-filing",
            committee_id=committee_id,
            source_record_id=unrelated_source_record.id,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=transaction_id,
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="15",
            amount=Decimal("789.01"),
            amendment_indicator="N",
            source_record_id=unrelated_source_record.id,
            transaction_identifier="donor-search-unrelated-source",
        ),
    )

    cleanup_donor_search_fixture(db_conn)

    preserved_transaction = db_conn.execute(
        """
        SELECT id, transaction_identifier, source_record_id, amount
        FROM cf.transaction
        WHERE id = %s
        """,
        (transaction_id,),
    ).fetchone()
    assert preserved_transaction == (
        transaction_id,
        "donor-search-unrelated-source",
        unrelated_source_record.id,
        Decimal("789.01"),
    )


def test_export_json_contains_seeded_member_with_money(api_client: TestClient, db_conn: psycopg.Connection) -> None:
    member, candidate_id = _seed_member_with_money_and_ie(db_conn)

    response = api_client.get("/public/v1/federal/export.json")

    assert response.status_code == 200
    row = _public_money_row_for_person(response.json(), member.person_id)
    assert row["person_id"] == str(member.person_id)
    assert row["person_name"] == member.person_name
    assert row["candidate_id"] == str(candidate_id)
    assert row["has_fec_money"] is True
    assert row["total_raised"] == "9000.00"
    assert row["total_spent"] == "1000.00"
    assert row["net"] == "8000.00"
    assert row["cash_on_hand"] == "8000.00"
    assert row["summary_source"] == "fec_weball"
    assert row["ie_support_total"] == "250.00"
    assert row["ie_oppose_total"] == "100.00"
    assert row["ie_support_count"] == 1
    assert row["ie_oppose_count"] == 1


def test_export_json_uses_official_totals_without_full_candidate_summary(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member, candidate_id = _seed_member_with_money_and_ie(db_conn)
    candidate_batch_calls: list[list[UUID]] = []
    public_summary_batch_calls: list[list[tuple[UUID, str]]] = []
    original_fetch_candidates_for_people = public_federal_route_module.fetch_candidates_for_people
    original_fetch_candidate_public_money_summaries = public_federal_route_module.fetch_candidate_public_money_summaries

    def track_candidates_for_people(
        conn: psycopg.Connection,
        person_ids: list[UUID],
    ) -> dict[UUID, list[dict[str, object]]]:
        candidate_batch_calls.append(person_ids)
        return original_fetch_candidates_for_people(conn, person_ids)

    def track_public_money_summaries(
        conn: psycopg.Connection,
        candidates: list[tuple[UUID, str]],
    ) -> dict[UUID, dict[str, object]]:
        public_summary_batch_calls.append(list(candidates))
        return original_fetch_candidate_public_money_summaries(conn, candidates)

    monkeypatch.setattr(public_federal_route_module, "fetch_candidates_for_people", track_candidates_for_people)
    monkeypatch.setattr(
        public_federal_route_module,
        "fetch_candidate_public_money_summaries",
        track_public_money_summaries,
    )

    response = api_client.get("/public/v1/federal/export.json")

    assert response.status_code == 200
    row = _public_money_row_for_person(response.json(), member.person_id)
    assert row["candidate_id"] == str(candidate_id)
    assert row["summary_source"] == "fec_weball"
    assert row["total_raised"] == "9000.00"
    assert row["total_spent"] == "1000.00"
    assert row["net"] == "8000.00"
    assert row["cash_on_hand"] == "8000.00"
    assert row["ie_support_total"] == "250.00"
    assert row["ie_oppose_total"] == "100.00"
    assert len(candidate_batch_calls) == 1
    assert member.person_id in candidate_batch_calls[0]
    assert len(public_summary_batch_calls) == 1
    assert (candidate_id, "Alice Representative") in public_summary_batch_calls[0]


def test_export_and_per_member_endpoint_agree(api_client: TestClient, db_conn: psycopg.Connection) -> None:
    member, _candidate_id = _seed_member_with_money_and_ie(db_conn)

    export_response = api_client.get("/public/v1/federal/export.json")
    member_response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")

    assert export_response.status_code == 200
    assert member_response.status_code == 200
    export_row = _public_money_row_for_person(export_response.json(), member.person_id)
    member_payload = member_response.json()
    fields_checked_for_export_parity = [
        "candidate_id",
        "has_fec_money",
        "total_raised",
        "total_spent",
        "net",
        "cash_on_hand",
        "summary_source",
        "ie_support_total",
        "ie_oppose_total",
        "ie_support_count",
        "ie_oppose_count",
        "sources",
    ]
    assert {field: export_row[field] for field in fields_checked_for_export_parity} == {
        field: member_payload[field] for field in fields_checked_for_export_parity
    }


def test_export_csv_header_and_known_row(api_client: TestClient, db_conn: psycopg.Connection) -> None:
    member, candidate_id = _seed_member_with_money_and_ie(db_conn)

    response = api_client.get("/public/v1/federal/export.csv")

    assert response.status_code == 200
    assert _public_money_csv_header(response.text) == [
        "person_id",
        "person_name",
        "has_fec_money",
        "candidate_id",
        "total_raised",
        "total_spent",
        "net",
        "cash_on_hand",
        "summary_source",
        "ie_support_total",
        "ie_oppose_total",
        "ie_support_count",
        "ie_oppose_count",
        "source_urls",
    ]
    row = _public_money_csv_row_for_person(response.text, member.person_id)
    assert row == {
        "person_id": str(member.person_id),
        "person_name": member.person_name,
        "has_fec_money": "true",
        "candidate_id": str(candidate_id),
        "total_raised": "9000.00",
        "total_spent": "1000.00",
        "net": "8000.00",
        "cash_on_hand": "8000.00",
        "summary_source": "fec_weball",
        "ie_support_total": "250.00",
        "ie_oppose_total": "100.00",
        "ie_support_count": "1",
        "ie_oppose_count": "1",
        "source_urls": "",
    }


def test_export_csv_leaves_unloaded_fundraising_cells_empty(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    """An unknown is an empty CSV cell, never ``0.00``.

    A downstream spreadsheet cannot see a coverage block; the cell is the whole
    claim. ``0.00`` there sums into totals and averages as a real measurement,
    which is the CSV form of the same fabrication. The precedent is the
    Schedule E columns, which already ship empty when nothing was loaded.
    """
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")
    # Official totals whose coverage window ends in a prior cycle and which are
    # not promotable, so the selected cycle resolves to not_loaded.
    _insert_candidate_with_official_totals(
        db_conn,
        candidate_id=UUID("bb000000-0000-0000-0000-000000000271"),
        fec_candidate_id="H4NC01271",
        name="Alice Unloaded Cycle Candidate",
        person_id=member.person_id,
        office="H",
        state="NC",
        district="01",
        total_receipts=Decimal("31077805.53"),
        total_disbursements=Decimal("31027960.15"),
        cash_on_hand=Decimal("49845.38"),
        summary_coverage_end_date=date(2024, 12, 31),
    )

    response = api_client.get("/public/v1/federal/export.csv")

    assert response.status_code == 200
    row = _public_money_csv_row_for_person(response.text, member.person_id)
    assert row["has_fec_money"] == "true"
    assert row["total_raised"] == ""
    assert row["total_spent"] == ""
    assert row["net"] == ""
    assert row["cash_on_hand"] == ""
    assert row["summary_source"] == ""


@pytest.mark.parametrize(
    ("raw_value", "expected_csv_value"),
    [
        ("=SUM(1,1)", "'=SUM(1,1)"),
        ("+cmd", "'+cmd"),
        ("-2+3", "'-2+3"),
        ("@hidden", "'@hidden"),
        (" \t=with-leading-space", "' \t=with-leading-space"),
        ("plain text", "plain text"),
    ],
)
def test_export_csv_escapes_formula_like_string_cells(raw_value: str, expected_csv_value: str) -> None:
    assert public_federal_route_module._csv_cell(raw_value) == expected_csv_value


def test_export_csv_formula_escape_policy_covers_every_string_bearing_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = UUID("11111111-1111-1111-1111-111111111111")
    candidate_id = UUID("22222222-2222-2222-2222-222222222222")
    row = PublicMemberMoneySummary(
        person_id=person_id,
        person_name=' =HYPERLINK("https://attacker.invalid","name")',
        has_fec_money=True,
        candidate_id=candidate_id,
        total_raised=Decimal("0.00"),
        total_spent=Decimal("1.00"),
        net=Decimal("-1.00"),
        cash_on_hand=None,
        summary_source="@formula-like-source",
        ie_support_total=Decimal("0.00"),
        ie_oppose_total=None,
        ie_support_count=0,
        ie_oppose_count=None,
        sources=[
            SourceInfo(
                domain="campaign_finance",
                jurisdiction="federal",
                data_source_name="Adversarial record URL",
                data_source_url="https://unused.invalid/",
                source_record_key="dangerous-record-url",
                record_url='=HYPERLINK("https://attacker.invalid","source")',
                pull_date=datetime(2026, 8, 27, tzinfo=timezone.utc),
            ),
            SourceInfo(
                domain="campaign_finance",
                jurisdiction="federal",
                data_source_name="Fallback data-source URL",
                data_source_url="https://fallback.invalid/",
                source_record_key=None,
                record_url=None,
                pull_date=datetime(2026, 8, 27, tzinfo=timezone.utc),
            ),
        ],
    )
    monkeypatch.setattr(public_federal_route_module, "build_public_federal_money_rows", lambda _conn: [row])

    response = public_federal_route_module.export_federal_money_csv(None)

    assert response.status_code == 200
    assert _public_money_csv_rows(response.body.decode()) == [
        {
            "person_id": str(person_id),
            "person_name": '\' =HYPERLINK("https://attacker.invalid","name")',
            "has_fec_money": "true",
            "candidate_id": str(candidate_id),
            "total_raised": "0.00",
            "total_spent": "1.00",
            "net": "-1.00",
            "cash_on_hand": "",
            "summary_source": "'@formula-like-source",
            "ie_support_total": "0.00",
            "ie_oppose_total": "",
            "ie_support_count": "0",
            "ie_oppose_count": "",
            "source_urls": '\'=HYPERLINK("https://attacker.invalid","source");https://fallback.invalid/',
        }
    ]


def test_export_row_carries_source_url(api_client: TestClient, db_conn: psycopg.Connection) -> None:
    member, _candidate_id, source_url = _seed_member_with_candidate_direct_source(db_conn)

    response = api_client.get("/public/v1/federal/export.csv")

    assert response.status_code == 200
    row = _public_money_csv_row_for_person(response.text, member.person_id)
    assert row["source_urls"]
    assert source_url in row["source_urls"]


def test_export_batches_provenance_lookup_for_selected_candidates(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member, _candidate_id, source_url = _seed_member_with_candidate_direct_source(db_conn)
    batch_calls: list[tuple[list[tuple[UUID, UUID | None]], str]] = []
    original_fetch_batch = public_federal_route_module.fetch_campaign_finance_provenance_batch

    def track_provenance_batch(
        conn: psycopg.Connection,
        *,
        provenance_requests: list[tuple[UUID, UUID | None]],
        canonical_entity_type: str,
    ) -> dict[UUID, list[dict[str, object]]]:
        batch_calls.append((list(provenance_requests), canonical_entity_type))
        return original_fetch_batch(
            conn,
            provenance_requests=provenance_requests,
            canonical_entity_type=canonical_entity_type,
        )

    def fail_single_provenance_lookup(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("public export must not do per-row provenance lookups")

    monkeypatch.setattr(
        public_federal_route_module,
        "fetch_campaign_finance_provenance_batch",
        track_provenance_batch,
    )
    monkeypatch.setattr(
        public_federal_route_module,
        "fetch_campaign_finance_provenance",
        fail_single_provenance_lookup,
    )

    response = api_client.get("/public/v1/federal/export.csv")

    assert response.status_code == 200
    row = _public_money_csv_row_for_person(response.text, member.person_id)
    assert source_url in row["source_urls"]
    assert len(batch_calls) == 1
    provenance_requests, canonical_entity_type = batch_calls[0]
    assert canonical_entity_type == "person"
    assert member.person_id in {person_id for person_id, _source_record_id in provenance_requests}


def test_export_batches_public_money_summary_for_selected_candidates(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member, candidate_id = _seed_member_with_money_and_ie(db_conn)
    batch_calls: list[list[tuple[UUID, str]]] = []
    original_fetch_batch = public_federal_route_module.fetch_candidate_public_money_summaries

    def track_summary_batch(
        conn: psycopg.Connection,
        candidates: list[tuple[UUID, str]],
    ) -> dict[UUID, dict[str, object]]:
        batch_calls.append(list(candidates))
        return original_fetch_batch(conn, candidates)

    def fail_single_summary(*_args: object, **_kwargs: object) -> dict[str, object] | None:
        raise AssertionError("public export must not do per-candidate money summary lookups")

    monkeypatch.setattr(
        public_federal_route_module,
        "fetch_candidate_public_money_summaries",
        track_summary_batch,
    )
    monkeypatch.setattr(
        public_federal_route_module,
        "fetch_candidate_public_money_summary",
        fail_single_summary,
    )

    response = api_client.get("/public/v1/federal/export.json")

    assert response.status_code == 200
    row = _public_money_row_for_person(response.json(), member.person_id)
    assert row["candidate_id"] == str(candidate_id)
    assert row["total_raised"] == "9000.00"
    assert len(batch_calls) == 1
    assert (candidate_id, "Alice Representative") in batch_calls[0]


def _seed_executive_out_of_cycle_public_money_fixture(
    db_conn: psycopg.Connection,
) -> tuple[dict[str, _CongressMemberExpectation], dict[str, UUID]]:
    expectations = _seed_current_federal_members_mix(db_conn)
    members = {
        "president": _member_by_office_name(expectations, "President of the United States"),
        "vice_president": _member_by_office_name(expectations, "Vice President of the United States"),
        "representative": _member_by_name(expectations, "Alice Representative"),
    }
    candidate_ids = {
        "president": UUID("bb000000-0000-0000-0000-000000000231"),
        "vice_president": UUID("bb000000-0000-0000-0000-000000000232"),
        "representative": UUID("bb000000-0000-0000-0000-000000000233"),
    }

    _insert_candidate_with_official_totals(
        db_conn,
        candidate_id=candidate_ids["president"],
        fec_candidate_id="P80001571",
        name="President Prior Cycle",
        person_id=members["president"].person_id,
        office="P",
        state="US",
        district="00",
        total_receipts=Decimal("29133.95"),
        total_disbursements=Decimal("29133.95"),
        cash_on_hand=Decimal("0.00"),
        summary_coverage_end_date=date(2024, 8, 8),
    )
    _insert_candidate_with_official_totals(
        db_conn,
        candidate_id=candidate_ids["vice_president"],
        fec_candidate_id="S2OH00232",
        name="Vice President Prior Senate Race",
        person_id=members["vice_president"].person_id,
        office="S",
        state="OH",
        district="00",
        total_receipts=Decimal("2704752.40"),
        total_disbursements=Decimal("3010429.69"),
        cash_on_hand=Decimal("135631.56"),
        summary_coverage_end_date=date(2024, 12, 31),
    )
    _insert_candidate_with_official_totals(
        db_conn,
        candidate_id=candidate_ids["representative"],
        fec_candidate_id="H0NC01233",
        name="Alice Representative",
        person_id=members["representative"].person_id,
        office="H",
        state="NC",
        district="01",
        total_receipts=Decimal("222.00"),
        total_disbursements=Decimal("20.00"),
        cash_on_hand=Decimal("202.00"),
        summary_coverage_end_date=date(2026, 12, 31),
    )
    return members, candidate_ids


def _assert_president_out_of_cycle_money_row(row: dict[str, object], candidate_id: UUID) -> None:
    assert row["candidate_id"] == str(candidate_id)
    assert row["summary_source"] == "fec_weball"
    assert row["total_raised"] == "29133.95"
    assert row["total_spent"] == "29133.95"
    assert row["net"] == "0.00"
    assert row["cash_on_hand"] == "0.00"
    assert row["fundraising_coverage"] == {
        "activity_state": "out_of_cycle_official_total",
        "basis": "fec_official_candidate_summary",
        "completeness": "complete",
    }
    assert row["out_of_cycle_official_total"] == {
        "coverage_start_date": "2023-01-01",
        "coverage_end_date": "2024-08-08",
        "total_raised": "29133.95",
        "total_spent": "29133.95",
        "net": "0.00",
        "cash_on_hand": "0.00",
        "summary_source": "fec_weball",
    }


def _assert_vice_president_out_of_cycle_money_row(row: dict[str, object], candidate_id: UUID) -> None:
    assert row["candidate_id"] == str(candidate_id)
    assert row["summary_source"] == "fec_weball"
    assert row["total_raised"] == "2704752.40"
    assert row["total_spent"] == "3010429.69"
    assert row["net"] == "-305677.29"
    assert row["cash_on_hand"] == "135631.56"
    assert row["out_of_cycle_official_total"]["coverage_start_date"] == "2023-01-01"
    assert row["out_of_cycle_official_total"]["coverage_end_date"] == "2024-12-31"
    # No Schedule E in this cycle window: unknown, not a measured zero.
    assert row["ie_support_total"] is None
    assert row["ie_oppose_total"] is None
    assert row["ie_coverage"]["activity_state"] == "not_loaded"
    assert row["sources"] == []


def test_president_default_cycle_promotes_out_of_cycle_official_total(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    from api.queries.campaign_finance import resolve_selected_cycle

    members, candidate_ids = _seed_executive_out_of_cycle_public_money_fixture(db_conn)
    selected_cycle = resolve_selected_cycle(None)
    with db_conn.cursor() as cursor:
        cursor.execute(
            "SELECT fec_candidate_id FROM cf.candidate WHERE id = %s",
            (candidate_ids["president"],),
        )
        candidate_row = cursor.fetchone()

    response = api_client.get(f"/public/v1/federal/officials/{members['president'].person_id}/money")

    assert selected_cycle.selected_cycle == 2026
    assert candidate_row == ("P80001571",)
    assert response.status_code == 200
    president_row = response.json()
    _assert_president_out_of_cycle_money_row(president_row, candidate_ids["president"])
    assert president_row["total_raised"] == "29133.95"
    assert president_row["summary_source"] == "fec_weball"
    assert president_row["out_of_cycle_official_total"] == {
        "coverage_start_date": "2023-01-01",
        "coverage_end_date": "2024-08-08",
        "total_raised": "29133.95",
        "total_spent": "29133.95",
        "net": "0.00",
        "cash_on_hand": "0.00",
        "summary_source": "fec_weball",
    }


def test_export_enriches_only_executive_out_of_cycle_official_totals(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    members, candidate_ids = _seed_executive_out_of_cycle_public_money_fixture(db_conn)
    full_summary_calls: list[UUID] = []
    original_fetch_candidate_summary = getattr(public_federal_route_module, "fetch_candidate_summary", None)

    def track_full_summary(
        conn: psycopg.Connection,
        candidate_id: UUID,
        candidate_name: str,
        selected_cycle: object | None = None,
    ) -> dict[str, object] | None:
        assert original_fetch_candidate_summary is not None
        full_summary_calls.append(candidate_id)
        return original_fetch_candidate_summary(conn, candidate_id, candidate_name, selected_cycle)

    monkeypatch.setattr(public_federal_route_module, "fetch_candidate_summary", track_full_summary, raising=False)

    export_response = api_client.get("/public/v1/federal/export.json")
    president_response = api_client.get(f"/public/v1/federal/officials/{members['president'].person_id}/money")
    vice_president_response = api_client.get(
        f"/public/v1/federal/officials/{members['vice_president'].person_id}/money"
    )

    assert export_response.status_code == 200
    assert president_response.status_code == 200
    assert vice_president_response.status_code == 200
    export_payload = export_response.json()
    president_row = _public_money_row_for_person(export_payload, members["president"].person_id)
    vice_president_row = _public_money_row_for_person(export_payload, members["vice_president"].person_id)
    representative_row = _public_money_row_for_person(export_payload, members["representative"].person_id)

    assert president_row == president_response.json()
    assert vice_president_row == vice_president_response.json()
    _assert_president_out_of_cycle_money_row(president_row, candidate_ids["president"])
    _assert_vice_president_out_of_cycle_money_row(vice_president_row, candidate_ids["vice_president"])
    assert representative_row["candidate_id"] == str(candidate_ids["representative"])
    assert representative_row["summary_source"] == "fec_weball"
    assert representative_row["total_raised"] == "222.00"
    assert "fundraising_coverage" not in representative_row
    assert "out_of_cycle_official_total" not in representative_row
    assert full_summary_calls == [
        candidate_ids["president"],
        candidate_ids["vice_president"],
        candidate_ids["president"],
        candidate_ids["vice_president"],
    ]


def test_public_member_money_selects_candidate_matching_current_office(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")
    wrong_candidate_id = UUID("bb000000-0000-0000-0000-000000000201")
    current_candidate_id = UUID("bb000000-0000-0000-0000-000000000202")

    _insert_candidate_with_official_totals(
        db_conn,
        candidate_id=wrong_candidate_id,
        fec_candidate_id="S0CA09999",
        name="Aaron Older Senate Race",
        person_id=member.person_id,
        office="S",
        state="CA",
        district=None,
        total_receipts=Decimal("111.00"),
        total_disbursements=Decimal("10.00"),
        cash_on_hand=Decimal("101.00"),
    )
    _insert_candidate_with_official_totals(
        db_conn,
        candidate_id=current_candidate_id,
        fec_candidate_id="H0NC01001",
        name="Zelda Current House Race",
        person_id=member.person_id,
        office="H",
        state="NC",
        district="01",
        total_receipts=Decimal("222.00"),
        total_disbursements=Decimal("20.00"),
        cash_on_hand=Decimal("202.00"),
    )

    response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"] == str(current_candidate_id)
    assert payload["total_raised"] == "222.00"
    assert payload["total_spent"] == "20.00"
    assert payload["net"] == "202.00"


def test_public_member_money_selects_vice_president_sole_prior_federal_candidacy() -> None:
    member = {
        "chamber": "Executive",
        "office_name": "Vice President of the United States",
        "state": None,
        "district": None,
    }
    candidate = {
        "id": UUID("bb000000-0000-0000-0000-000000000241"),
        "name": "Prior Senate Race",
        "office": "S",
        "state": "OH",
        "district": "00",
        "has_selected_cycle_link": False,
    }

    selected = public_federal_route_module._select_public_money_candidate([candidate], member)

    assert selected == candidate


def test_public_member_money_president_does_not_select_sole_senate_prior_candidacy() -> None:
    member = {
        "chamber": "Executive",
        "office_name": "President of the United States",
        "state": None,
        "district": None,
    }
    candidate = {
        "id": UUID("bb000000-0000-0000-0000-000000000242"),
        "name": "Prior Senate Race",
        "office": "S",
        "state": "OH",
        "district": "00",
        "has_selected_cycle_link": False,
    }

    selected = public_federal_route_module._select_public_money_candidate([candidate], member)

    assert selected is None


def test_public_member_money_rejects_linked_candidate_for_prior_office(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")
    candidate_id = UUID("bb000000-0000-0000-0000-000000000211")

    _insert_candidate_with_official_totals(
        db_conn,
        candidate_id=candidate_id,
        fec_candidate_id="S0CA08888",
        name="Alice Prior Senate Race",
        person_id=member.person_id,
        office="S",
        state="CA",
        district=None,
        total_receipts=Decimal("444.00"),
        total_disbursements=Decimal("40.00"),
        cash_on_hand=Decimal("404.00"),
    )

    response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_fec_money"] is False
    assert payload["candidate_id"] is None
    # The prior-office candidate was rejected, so no FEC identity is attached to
    # this member for the selected cycle and nothing about their fundraising is
    # known -- not zero.
    assert payload["total_raised"] is None
    assert payload["total_spent"] is None
    assert payload["net"] is None


def test_public_member_money_uses_committee_summary_when_candidate_official_totals_missing(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")
    candidate_id = UUID("bb000000-0000-0000-0000-000000000221")
    committee_id = UUID("bb000000-0000-0000-0000-000000000222")

    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC01221",
            name="Alice Committee Summary Candidate",
            office="H",
            person_id=member.person_id,
            party="DEM",
            state="NC",
            district="01",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C99990221",
            name="Alice Committee Summary Committee",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("bb000000-0000-0000-0000-000000000223"),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2000-01-01,2100-01-01)",
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=Decimal("1200.00"),
            total_disbursements=Decimal("450.00"),
            cash_on_hand=Decimal("750.00"),
        ),
    )

    response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"] == str(candidate_id)
    assert payload["summary_source"] == "fec_committee_summary"
    assert payload["total_raised"] == "1200.00"
    assert payload["total_spent"] == "450.00"
    assert payload["net"] == "750.00"
    assert payload["cash_on_hand"] == "750.00"


def test_public_member_money_preserves_not_loaded_coverage_for_selected_zero_candidate(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")
    candidate_id = UUID("bb000000-0000-0000-0000-000000000224")

    _insert_candidate_with_official_totals(
        db_conn,
        candidate_id=candidate_id,
        fec_candidate_id="H4NC01224",
        name="Alice Prior Cycle Candidate",
        person_id=member.person_id,
        office="H",
        state="NC",
        district="01",
        total_receipts=Decimal("31077805.53"),
        total_disbursements=Decimal("31027960.15"),
        cash_on_hand=Decimal("49845.38"),
        summary_coverage_end_date=date(2024, 12, 31),
    )

    response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_fec_money"] is True
    assert payload["candidate_id"] == str(candidate_id)
    # The zeros this summary carries are pre-seeded placeholders for a load that
    # never happened, not measurements. The row used to publish them beside its
    # own no_authoritative_load_evidence coverage block: one row, two claims,
    # only one of which can be true (civibus-9nu).
    assert payload["total_raised"] is None
    assert payload["total_spent"] is None
    assert payload["net"] is None
    assert payload["cash_on_hand"] is None
    # summary_source names the origin of a figure; with no figure it has no
    # referent either.
    assert payload["summary_source"] is None
    assert payload["fundraising_coverage"] == {
        "activity_state": "not_loaded",
        "basis": "no_authoritative_load_evidence",
        "completeness": "unknown",
    }
    assert "out_of_cycle_official_total" not in payload


def test_public_member_money_includes_chosen_candidate_direct_source(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    member, candidate_id, _source_url = _seed_member_with_candidate_direct_source(db_conn)

    response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"] == str(candidate_id)
    assert [source["source_record_key"] for source in payload["sources"]] == [
        "public-candidate-direct",
        "public-person-fallback",
    ]


def test_public_member_money_reports_no_fec_money_for_member_without_candidate(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    # "Alice Representative" has no seeded cf.candidate in the base directory mix.
    member = _member_by_name(expectations, "Alice Representative")

    response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")

    assert response.status_code == 200
    payload = response.json()
    assert payload["person_id"] == str(member.person_id)
    assert payload["person_name"] == member.person_name
    assert payload["has_fec_money"] is False
    assert payload["candidate_id"] is None
    assert payload["summary_source"] is None
    # No cf.candidate row: no committee could have filed a Schedule A against
    # this member, so their fundraising is unknown, never a minted zero. The
    # same conclusion the outside-spending fields below already reached.
    assert payload["total_raised"] is None
    assert payload["total_spent"] is None
    assert payload["net"] is None
    assert payload["cash_on_hand"] is None
    assert payload["fundraising_coverage"]["activity_state"] == "not_loaded"
    # No cf.candidate row: outside spending is unknown, never a minted zero.
    assert payload["ie_support_total"] is None
    assert payload["ie_oppose_total"] is None
    assert payload["ie_support_count"] is None
    assert payload["ie_oppose_count"] is None
    assert payload["ie_coverage"]["activity_state"] == "not_loaded"
    assert [source["source_record_key"] for source in payload["sources"]] == [f"officeholding-{member.person_id}"]


def test_documented_no_candidate_absence_exposes_source_in_detail_and_exports(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")
    source_url = f"https://example.org/congress/officeholding-{member.person_id}"

    detail_response = api_client.get(f"/public/v1/federal/officials/{member.person_id}/money")
    json_response = api_client.get("/public/v1/federal/export.json")
    csv_response = api_client.get("/public/v1/federal/export.csv")

    assert detail_response.status_code == 200
    assert json_response.status_code == 200
    assert csv_response.status_code == 200
    detail_payload = detail_response.json()
    json_row = _public_money_row_for_person(json_response.json(), member.person_id)
    csv_row = _public_money_csv_row_for_person(csv_response.text, member.person_id)
    assert detail_payload["has_fec_money"] is False
    assert detail_payload["candidate_id"] is None
    assert [source["source_record_key"] for source in detail_payload["sources"]] == [
        f"officeholding-{member.person_id}"
    ]
    assert detail_payload["sources"][0]["record_url"] == source_url
    assert json_row["sources"] == detail_payload["sources"]
    assert csv_row["source_urls"] == source_url


def test_public_member_money_returns_404_for_unknown_person(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    _seed_current_federal_members_mix(db_conn)
    unknown_person_id = uuid4()

    response = api_client.get(f"/public/v1/federal/officials/{unknown_person_id}/money")

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == _public_cache_control_header()
