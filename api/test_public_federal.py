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
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
from pydantic import ValidationError

from api.deps import get_db
from api.models import (
    PublicContributorRow,
    PublicContributorsResponse,
    PublicEmployerRow,
    PublicEmployersResponse,
)
from api.models.provenance import SourceInfo
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
from test_support.donor_search_fixture import seed_full_scope_skewed_donor_search_fixture

pytestmark = pytest.mark.integration


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


def _public_federal_get_paths() -> list[str]:
    return [f"/api{route.path}" for route in router.routes if isinstance(route, APIRoute) and "GET" in route.methods]


def _developers_page_public_api_endpoint_labels(source: str) -> list[str]:
    return re.findall(r'"GET (/api/public/v1/[^"]+)"', source)


def _developers_page_csv_columns(source: str) -> list[str]:
    match = re.search(r"const csvColumns = \[(?P<body>.*?)\]\s+as const;", source, re.DOTALL)
    if match is None:
        raise AssertionError("developers page no longer declares csvColumns as a static array")
    return re.findall(r'"([^"]+)"', match.group("body"))


def test_developers_page_public_api_reference_matches_router_contract() -> None:
    developers_page_source = Path("web/src/routes/developers/+page.svelte").read_text()

    public_paths = _public_federal_get_paths()
    documented_public_paths = _developers_page_public_api_endpoint_labels(developers_page_source)
    documented_csv_columns = _developers_page_csv_columns(developers_page_source)

    assert f"<code>{router.prefix}</code>" in developers_page_source
    assert len(public_paths) == 6
    assert len(documented_public_paths) == len(set(documented_public_paths))
    assert set(documented_public_paths) == set(public_paths)
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
        fec_candidate_id="P0US00231",
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
    assert row["ie_support_total"] == "0.00"
    assert row["ie_oppose_total"] == "0.00"
    assert row["sources"] == []


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
    assert payload["total_raised"] == "0"
    assert payload["total_spent"] == "0"
    assert payload["net"] == "0"


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
    assert payload["total_raised"] == "0"
    assert payload["total_spent"] == "0"
    assert payload["net"] == "0"
    assert payload["cash_on_hand"] is None
    assert payload["ie_support_total"] == "0"
    assert payload["ie_oppose_total"] == "0"
    assert payload["ie_support_count"] == 0
    assert payload["ie_oppose_count"] == 0
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
