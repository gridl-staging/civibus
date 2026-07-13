"""Tests for the authless public federal API (`/public/v1`).

Stage 1: two thin-wrapper endpoints over existing query owners —
``GET /public/v1/federal/officials`` and
``GET /public/v1/federal/officials/{person_id}/money``.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from api.deps import get_db
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
    _seed_current_federal_members_mix,
)
from core.db import insert_entity_source

pytestmark = pytest.mark.integration


def _member_by_name(expectations: list[_CongressMemberExpectation], person_name: str) -> _CongressMemberExpectation:
    for expectation in expectations:
        if expectation.person_name == person_name:
            return expectation
    raise AssertionError(f"seed mix did not produce a member named {person_name!r}")


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
    assert len(public_paths) == 4
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
            recipient_candidate_id=candidate_id,
            support_oppose="O",
        ),
    )
    return member, candidate_id


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
            source_record_id=source_record_id,
        ),
    )


def _seed_member_with_candidate_direct_source(
    db_conn: psycopg.Connection,
) -> tuple[_CongressMemberExpectation, UUID, str]:
    expectations = _seed_current_federal_members_mix(db_conn)
    member = _member_by_name(expectations, "Alice Representative")
    source_url = "https://example.org/fec/public-candidate-direct"
    data_source = insert_data_source_for_test(db_conn, jurisdiction="federal/fec", name_suffix="public-money-source")
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
        "/public/v1/federal/export.json",
        "/public/v1/federal/export.csv",
    ]

    for path in public_paths:
        response = api_client.get(path)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == _public_cache_control_header()

    private_response = api_client.get("/v1/person/not-a-uuid")
    assert private_response.status_code == 422
    assert "Cache-Control" not in private_response.headers


def test_public_endpoints_ip_rate_limited_without_api_key(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
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
    assert limited_response.headers["Retry-After"] == "30"


def test_public_officials_returns_directory_projection(api_client: TestClient, db_conn: psycopg.Connection) -> None:
    expectations = _seed_current_federal_members_mix(db_conn)

    response = api_client.get("/public/v1/federal/officials")

    assert response.status_code == 200
    assert response.json() == _expected_congress_http_rows(expectations)


def test_public_officials_chamber_filter_returns_only_senate(
    api_client: TestClient, db_conn: psycopg.Connection
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


def test_public_member_money_uses_linked_candidate_when_current_office_mismatch(
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
    assert payload["has_fec_money"] is True
    assert payload["candidate_id"] == str(candidate_id)
    assert payload["total_raised"] == "444.00"
    assert payload["total_spent"] == "40.00"
    assert payload["net"] == "404.00"


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
    assert payload["sources"] == []


def test_public_member_money_returns_404_for_unknown_person(
    api_client: TestClient, db_conn: psycopg.Connection
) -> None:
    _seed_current_federal_members_mix(db_conn)
    unknown_person_id = uuid4()

    response = api_client.get(f"/public/v1/federal/officials/{unknown_person_id}/money")

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == _public_cache_control_header()
