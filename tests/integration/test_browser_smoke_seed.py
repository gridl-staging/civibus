"""Browser-smoke seed contract.

Live-mode browser assertions reachable from ``ACCESSIBILITY_SCAN_DESTINATIONS``
and the live chart smoke tests require a seed-only database shape: Jane Doe as
the person detail heading and Congress leader, Pat Candidate as the only
candidate row, Citizens for Civibus as the only committee row with slug
``citizens-for-civibus``, Civibus Action Org as the ``/search?q=civ&entity_type=org``
result, ``3 members`` on ``/congress``, provenance label
``Indiana Campaign Finance (campaign_finance/state/IN)``, a renderable committee
cash-on-hand line chart, and a renderable person contribution-size bar chart.

The canonical 2024 FEC bulk sample is the only accepted preload: the seed
recognizes its exact source lineage, removes those relational rows, and then
supplies the isolated specimen rows required by ``Showing 1-1``. Any other
candidate, committee, current federal officeholder, or matching organization
still fails before mutation so a later browser assertion cannot fail opaquely.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row

import api.queries.civics as civics_queries
from api.models.campaign_finance import (
    CandidateListItem,
    CandidateListParams,
    CandidateListResponse,
    CommitteeListItem,
    CommitteeListParams,
    CommitteeListResponse,
    CommitteeResponse,
)
from api.models.search import SearchParams
from api.queries import (
    CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL,
    fetch_campaign_finance_provenance,
    fetch_candidate_list,
    fetch_committee_filing_breakdown,
    fetch_committee_linked_candidates,
    fetch_committee_list,
    fetch_one_row,
    fetch_person_contribution_insights,
    fetch_search_results,
)
from api.queries.civics import fetch_current_federal_members
from api.test_campaign_finance_support import insert_office_row, insert_officeholding_row
from core.db import get_connection, insert_organization, insert_person
from core.graph import age_post_connect, query_formatted_cypher
from core.graph import cli as graph_cli
from core.refresh.donor_rollup import donor_key_fingerprint
from core.types.python.models import Organization, Person
from domains.campaign_finance.constants import (
    FEC_BULK_DATA_SOURCE_DOMAIN,
    FEC_BULK_DATA_SOURCE_JURISDICTION,
    FEC_BULK_DATA_SOURCE_NAME,
)
from domains.campaign_finance.ingest import bulk_cli

pytestmark = pytest.mark.integration


def _browser_smoke_seed_module():
    return importlib.import_module("test_support.browser_smoke_seed")


def _seed_and_parse_stdout(capsys: pytest.CaptureFixture[str]) -> tuple[object, dict[str, str], datetime, datetime]:
    browser_smoke_seed = _browser_smoke_seed_module()
    started_at = datetime.now(timezone.utc)
    browser_smoke_seed.main()
    finished_at = datetime.now(timezone.utc)
    output = capsys.readouterr().out
    env_lines = dict(re.findall(r"^(SMOKE_PERSON_ID|SMOKE_COMMITTEE_SLUG)=(.+)$", output, flags=re.MULTILINE))
    return browser_smoke_seed, env_lines, started_at, finished_at


def test_browser_smoke_seed_is_idempotent_and_satisfies_live_smoke_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    browser_smoke_seed, first_env_lines, _first_started, _first_finished = _seed_and_parse_stdout(capsys)
    browser_smoke_seed, second_env_lines, second_started, second_finished = _seed_and_parse_stdout(capsys)

    assert first_env_lines == {
        "SMOKE_PERSON_ID": browser_smoke_seed.SMOKE_PERSON_ID,
        "SMOKE_COMMITTEE_SLUG": browser_smoke_seed.SMOKE_COMMITTEE_SLUG,
    }
    assert second_env_lines == first_env_lines

    with get_connection() as conn:
        _assert_shell_route_owner_contracts(conn, browser_smoke_seed)
        _assert_committee_detail_route_owner_contract(conn, browser_smoke_seed)
        _assert_officeholding_contract(conn, browser_smoke_seed)
        _assert_rollup_contract(conn, started_at=second_started, finished_at=second_finished)
        _assert_specimen_resolution(conn, browser_smoke_seed)
        _assert_chart_oracle_volume(conn, browser_smoke_seed)


def test_browser_smoke_seed_accepts_canonical_bulk_sample_preload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture_directory = Path(__file__).parents[1] / "fixtures/bulk"
    exit_code = bulk_cli.main(
        [
            "--cycle",
            "2024",
            "--all",
            "--directory",
            str(fixture_directory),
            "--batch-size",
            "1000",
        ]
    )
    assert exit_code == 0
    capsys.readouterr()

    with get_connection() as conn:
        assert len(fetch_candidate_list(conn, CandidateListParams())["items"]) > 1
        assert len(fetch_committee_list(conn, CommitteeListParams())["items"]) > 1
        bulk_entity_ids = _bulk_preload_entity_ids(conn)

    assert graph_cli.main([]) == 0
    capsys.readouterr()
    assert _graph_entity_ids() >= bulk_entity_ids

    browser_smoke_seed, env_lines, _started, _finished = _seed_and_parse_stdout(capsys)
    assert env_lines == {
        "SMOKE_PERSON_ID": browser_smoke_seed.SMOKE_PERSON_ID,
        "SMOKE_COMMITTEE_SLUG": browser_smoke_seed.SMOKE_COMMITTEE_SLUG,
    }
    assert _graph_entity_ids().isdisjoint(bulk_entity_ids)
    with get_connection() as conn:
        _assert_shell_route_owner_contracts(conn, browser_smoke_seed)


def _graph_entity_ids() -> set[UUID]:
    with get_connection(post_connect=age_post_connect) as conn:
        rows = query_formatted_cypher(conn, "MATCH (n) RETURN n.id")
    return {UUID(str(row).strip('"')) for row in rows}


def _bulk_preload_entity_ids(conn: psycopg.Connection) -> set[UUID]:
    source_identity = (
        FEC_BULK_DATA_SOURCE_DOMAIN,
        FEC_BULK_DATA_SOURCE_JURISDICTION,
        FEC_BULK_DATA_SOURCE_NAME,
    )
    rows = conn.execute(
        """
        SELECT candidate.id
        FROM cf.candidate candidate
        JOIN core.source_record record ON record.id = candidate.source_record_id
        JOIN core.data_source source ON source.id = record.data_source_id
        WHERE (source.domain, source.jurisdiction, source.name) = (%s, %s, %s)
        UNION ALL
        SELECT committee.id
        FROM cf.committee committee
        JOIN core.source_record record ON record.id = committee.source_record_id
        JOIN core.data_source source ON source.id = record.data_source_id
        WHERE (source.domain, source.jurisdiction, source.name) = (%s, %s, %s)
        """,
        (*source_identity, *source_identity),
    ).fetchall()
    return {row[0] for row in rows}


def test_browser_smoke_seed_literals_match_non_overridable_web_smoke_literals() -> None:
    browser_smoke_seed = _browser_smoke_seed_module()
    fixture_source = (Path(__file__).parents[2] / "web/tests/smoke/fixtures.ts").read_text()
    expected_python_values = {
        "SMOKE_PERSON_CANONICAL_NAME": browser_smoke_seed.SMOKE_PERSON_CANONICAL_NAME,
        "SMOKE_COMMITTEE_NAME": browser_smoke_seed.SMOKE_COMMITTEE_NAME,
        "SMOKE_CANDIDATE_NAME": browser_smoke_seed.SMOKE_CANDIDATE_NAME,
        "SMOKE_SEARCH_RESULT_NAME": browser_smoke_seed.SMOKE_SEARCH_RESULT_NAME,
        "SMOKE_SEARCH_QUERY": browser_smoke_seed.SMOKE_SEARCH_QUERY,
        "SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME": (
            browser_smoke_seed.SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME
        ),
        "SMOKE_CANDIDATE_LIST_CONTEXT": browser_smoke_seed.SMOKE_CANDIDATE_LIST_CONTEXT,
        "SMOKE_COMMITTEE_LIST_CONTEXT": browser_smoke_seed.SMOKE_COMMITTEE_LIST_CONTEXT,
    }

    assert {
        constant_name: _extract_typescript_string_literal(fixture_source, constant_name)
        for constant_name in expected_python_values
    } == expected_python_values


def _extract_typescript_string_literal(source: str, constant_name: str) -> str:
    match = re.search(
        rf'export const {re.escape(constant_name)}\s*=\s*"([^"]+)";',
        source,
    )
    assert match is not None, f"Missing direct string literal for {constant_name}"
    return match.group(1)


class _ConflictingRowCase(NamedTuple):
    """A single non-isolated-database scenario the seed must refuse."""

    label: str
    insert: Callable[[psycopg.Connection, object], None]
    delete: Callable[[psycopg.Connection], None]
    assert_route_owner_sees_conflict: Callable[[psycopg.Connection, object], None]


_CONFLICTING_ROW_ID = UUID("14d10000-0000-4000-8000-000000000701")
_CONFLICTING_OFFICE_ID = UUID("14d10000-0000-4000-8000-000000000702")
_CONFLICTING_CANONICAL_OFFICE_NAME = "us_resident_commissioner"
_MUTATION_CANARY_COMMITTEE_NAME = "Pre-Seed Canary Committee"


def _insert_conflicting_committee(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    conn.execute(
        """
        INSERT INTO cf.committee (
            id,
            fec_committee_id,
            name,
            source_record_id,
            committee_type,
            party,
            state
        )
        VALUES (%s, 'C14999999', 'Dirty Extra Committee', %s, 'Q', 'DEM', 'NC')
        """,
        (_CONFLICTING_ROW_ID, _fetch_seed_source_record_id(browser_smoke_seed)),
    )


def _delete_conflicting_committee(conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM cf.committee WHERE id = %s", (_CONFLICTING_ROW_ID,))


def _assert_committee_list_sees_conflict(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    committee_ids = {row["id"] for row in fetch_committee_list(conn, CommitteeListParams())["items"]}
    assert _CONFLICTING_ROW_ID in committee_ids
    assert UUID(browser_smoke_seed.SMOKE_COMMITTEE_ID) in committee_ids


def _insert_conflicting_search_organization(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    insert_organization(
        conn,
        Organization(
            id=_CONFLICTING_ROW_ID,
            canonical_name=f"Rival {browser_smoke_seed.SMOKE_SEARCH_QUERY.capitalize()}ic Alliance",
            org_type="nonprofit",
            registered_state="NC",
        ),
    )


def _delete_conflicting_search_organization(conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM core.organization WHERE id = %s", (_CONFLICTING_ROW_ID,))


def _assert_org_search_sees_conflict(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    result_ids = [
        row["entity_id"]
        for row in fetch_search_results(
            conn,
            SearchParams(q=browser_smoke_seed.SMOKE_SEARCH_QUERY, entity_type="org"),
        )
    ]
    assert _CONFLICTING_ROW_ID in result_ids
    assert UUID(browser_smoke_seed.SMOKE_ORG_ID) in result_ids


def _insert_conflicting_current_federal_officeholder(
    conn: psycopg.Connection,
    _browser_smoke_seed: object,
) -> None:
    insert_person(
        conn,
        Person(
            id=_CONFLICTING_ROW_ID,
            canonical_name="Dirty Extra Representative",
            first_name="Dirty",
            last_name="Representative",
        ),
    )
    insert_office_row(
        conn,
        office_id=_CONFLICTING_OFFICE_ID,
        name=_CONFLICTING_CANONICAL_OFFICE_NAME,
        title="Resident Commissioner",
        state=None,
        electoral_division_id=None,
    )
    insert_officeholding_row(
        conn,
        officeholding_id=_CONFLICTING_ROW_ID,
        person_id=_CONFLICTING_ROW_ID,
        office_id=_CONFLICTING_OFFICE_ID,
        electoral_division_id=None,
    )


def _delete_conflicting_current_federal_officeholder(conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM civic.officeholding WHERE id = %s", (_CONFLICTING_ROW_ID,))
    conn.execute("DELETE FROM civic.office WHERE id = %s", (_CONFLICTING_OFFICE_ID,))
    conn.execute("DELETE FROM core.person WHERE id = %s", (_CONFLICTING_ROW_ID,))


def _assert_congress_sees_conflict(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    member_ids = {row["person_id"] for row in fetch_current_federal_members(conn)}
    assert _CONFLICTING_ROW_ID in member_ids
    assert UUID(browser_smoke_seed.SMOKE_PERSON_ID) in member_ids


_CONFLICTING_ROW_CASES = (
    _ConflictingRowCase(
        label="extra_committee",
        insert=_insert_conflicting_committee,
        delete=_delete_conflicting_committee,
        assert_route_owner_sees_conflict=_assert_committee_list_sees_conflict,
    ),
    _ConflictingRowCase(
        label="extra_search_organization",
        insert=_insert_conflicting_search_organization,
        delete=_delete_conflicting_search_organization,
        assert_route_owner_sees_conflict=_assert_org_search_sees_conflict,
    ),
    _ConflictingRowCase(
        label="extra_current_federal_officeholder",
        insert=_insert_conflicting_current_federal_officeholder,
        delete=_delete_conflicting_current_federal_officeholder,
        assert_route_owner_sees_conflict=_assert_congress_sees_conflict,
    ),
)


@pytest.mark.parametrize("case", _CONFLICTING_ROW_CASES, ids=[case.label for case in _CONFLICTING_ROW_CASES])
def test_browser_smoke_seed_rejects_non_isolated_smoke_database(
    case: _ConflictingRowCase,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_smoke_seed, _env_lines, _started, _finished = _seed_and_parse_stdout(capsys)
    if case.label == "extra_current_federal_officeholder":
        monkeypatch.setattr(
            civics_queries,
            "CANONICAL_FEDERAL_DIRECTORY_OFFICE_NAMES",
            (*civics_queries.CANONICAL_FEDERAL_DIRECTORY_OFFICE_NAMES, _CONFLICTING_CANONICAL_OFFICE_NAME),
        )

    with get_connection() as conn:
        try:
            _stamp_mutation_canary(conn, browser_smoke_seed)
            case.insert(conn, browser_smoke_seed)
            conn.commit()
            case.assert_route_owner_sees_conflict(conn, browser_smoke_seed)

            with pytest.raises(RuntimeError, match="Browser-smoke seed requires an isolated database"):
                browser_smoke_seed.main()

            assert capsys.readouterr().out == ""
            assert _fetch_smoke_committee_name(conn, browser_smoke_seed) == _MUTATION_CANARY_COMMITTEE_NAME
        finally:
            case.delete(conn)
            conn.commit()
            browser_smoke_seed.main()
            capsys.readouterr()


def _stamp_mutation_canary(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    """Rename the smoke committee so any seed mutation past the guard is observable."""
    conn.execute(
        "UPDATE cf.committee SET name = %s WHERE id = %s",
        (_MUTATION_CANARY_COMMITTEE_NAME, UUID(browser_smoke_seed.SMOKE_COMMITTEE_ID)),
    )


def _fetch_smoke_committee_name(conn: psycopg.Connection, browser_smoke_seed: object) -> str | None:
    row = conn.execute(
        "SELECT name FROM cf.committee WHERE id = %s",
        (UUID(browser_smoke_seed.SMOKE_COMMITTEE_ID),),
    ).fetchone()
    return None if row is None else row[0]


def _assert_shell_route_owner_contracts(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    _assert_search_route_owner_contract(conn, browser_smoke_seed)
    _assert_candidate_list_route_owner_contract(conn, browser_smoke_seed)
    _assert_committee_list_route_owner_contract(conn, browser_smoke_seed)
    _assert_congress_route_owner_contract(conn, browser_smoke_seed)


def _assert_search_route_owner_contract(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    search_results = fetch_search_results(
        conn,
        SearchParams(q=browser_smoke_seed.SMOKE_SEARCH_QUERY, entity_type="org"),
    )
    assert search_results == [
        {
            "entity_type": "org",
            "entity_id": UUID(browser_smoke_seed.SMOKE_ORG_ID),
            "name": browser_smoke_seed.SMOKE_ORG_CANONICAL_NAME,
            "state": None,
            "party": None,
            "office_name": None,
            "committee_type": None,
            "total_raised": None,
        }
    ]


def _assert_candidate_list_route_owner_contract(
    conn: psycopg.Connection,
    browser_smoke_seed: object,
) -> None:
    candidate_page = fetch_candidate_list(conn, CandidateListParams())
    candidate_page["items"] = [CandidateListItem.model_validate(row) for row in candidate_page["items"]]
    candidate_response = CandidateListResponse.model_validate(candidate_page)
    assert candidate_response.model_dump() == {
        "items": [
            {
                "id": UUID(browser_smoke_seed.SMOKE_CANDIDATE_ID),
                "fec_candidate_id": browser_smoke_seed.SMOKE_CANDIDATE_FEC_ID,
                "name": browser_smoke_seed.SMOKE_CANDIDATE_NAME,
                "person_id": UUID(browser_smoke_seed.SMOKE_PERSON_ID),
                "party": "DEM",
                "office": "H",
                "state": "NC",
                "district": "01",
                "slug": browser_smoke_seed.SMOKE_CANDIDATE_SLUG,
                "slug_is_unique": True,
                "identity_is_safe": True,
                "has_official_total": True,
                # Money column value seeded by test_support.browser_smoke_seed.
                "total_receipts": Decimal("250.00"),
            }
        ],
        "has_next": False,
        "offset": 0,
        "limit": 50,
    }


def _assert_committee_list_route_owner_contract(
    conn: psycopg.Connection,
    browser_smoke_seed: object,
) -> None:
    committee_page = fetch_committee_list(conn, CommitteeListParams())
    committee_page["items"] = [CommitteeListItem.model_validate(row) for row in committee_page["items"]]
    committee_response = CommitteeListResponse.model_validate(committee_page)
    assert committee_response.model_dump() == {
        "items": [
            {
                "id": UUID(browser_smoke_seed.SMOKE_COMMITTEE_ID),
                "fec_committee_id": browser_smoke_seed.SMOKE_COMMITTEE_FEC_ID,
                "name": browser_smoke_seed.SMOKE_COMMITTEE_NAME,
                "committee_type": "Q",
                "party": "DEM",
                "state": "NC",
                "slug": browser_smoke_seed.SMOKE_COMMITTEE_SLUG,
                "slug_is_unique": True,
            }
        ],
        "has_next": False,
        "offset": 0,
        "limit": 50,
    }


def _assert_congress_route_owner_contract(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    congress_members = fetch_current_federal_members(conn)
    assert [(row["person_id"], row["person_name"]) for row in congress_members] == [
        (
            UUID(browser_smoke_seed.SMOKE_SECOND_PERSON_ID),
            browser_smoke_seed.SMOKE_SECOND_PERSON_CANONICAL_NAME,
        ),
        (UUID(browser_smoke_seed.SMOKE_PERSON_ID), browser_smoke_seed.SMOKE_PERSON_CANONICAL_NAME),
        (
            UUID(browser_smoke_seed.SMOKE_NO_MONEY_PERSON_ID),
            browser_smoke_seed.SMOKE_NO_MONEY_PERSON_CANONICAL_NAME,
        ),
    ]


def _assert_committee_detail_route_owner_contract(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    committee_id = UUID(browser_smoke_seed.SMOKE_COMMITTEE_ID)
    detail_row = fetch_one_row(conn, query=CAMPAIGN_FINANCE_COMMITTEE_DETAIL_SQL, row_id=committee_id)
    assert detail_row is not None
    row_source_record_id = detail_row.pop("source_record_id")
    detail_row["sources"] = fetch_campaign_finance_provenance(
        conn,
        row_source_record_id=row_source_record_id,
        canonical_entity_type="organization",
        canonical_entity_id=detail_row["organization_id"],
    )
    detail_row["linked_candidates"] = fetch_committee_linked_candidates(conn, committee_id)
    response = CommitteeResponse.model_validate(detail_row)

    assert response.name == browser_smoke_seed.SMOKE_COMMITTEE_NAME
    assert response.slug == browser_smoke_seed.SMOKE_COMMITTEE_SLUG
    assert [(candidate.name, candidate.person_id) for candidate in response.linked_candidates] == [
        (browser_smoke_seed.SMOKE_CANDIDATE_NAME, UUID(browser_smoke_seed.SMOKE_PERSON_ID))
    ]
    assert [(source.data_source_name, source.domain, source.jurisdiction) for source in response.sources] == [
        (
            browser_smoke_seed.SMOKE_DATA_SOURCE_NAME,
            browser_smoke_seed.SMOKE_DATA_SOURCE_DOMAIN,
            browser_smoke_seed.SMOKE_DATA_SOURCE_JURISDICTION,
        )
    ]


def _fetch_seed_source_record_id(browser_smoke_seed: object) -> UUID:
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT source_record_id
                FROM cf.committee
                WHERE id = %s
                """,
                (UUID(browser_smoke_seed.SMOKE_COMMITTEE_ID),),
            )
            row = cursor.fetchone()
    assert row is not None
    return row["source_record_id"]


def _assert_officeholding_contract(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                officeholding.person_id,
                candidate.id AS candidate_id,
                candidate.name AS candidate_name,
                committee.id AS committee_id,
                committee.name AS committee_name
            FROM civic.officeholding officeholding
            JOIN civic.office office ON office.id = officeholding.office_id
            JOIN cf.candidate candidate ON candidate.person_id = officeholding.person_id
            JOIN cf.candidate_committee_link link ON link.candidate_id = candidate.id
            JOIN cf.committee committee ON committee.id = link.committee_id
            WHERE officeholding.valid_period @> CURRENT_DATE
              AND office.office_level = 'federal'
              AND candidate.person_id IS NOT NULL
              AND link.valid_period @> CURRENT_DATE
            """
        )
        rows = cursor.fetchall()

    assert rows == [
        {
            "person_id": UUID(browser_smoke_seed.SMOKE_PERSON_ID),
            "candidate_id": UUID(browser_smoke_seed.SMOKE_CANDIDATE_ID),
            "candidate_name": browser_smoke_seed.SMOKE_CANDIDATE_NAME,
            "committee_id": UUID(browser_smoke_seed.SMOKE_COMMITTEE_ID),
            "committee_name": browser_smoke_seed.SMOKE_COMMITTEE_NAME,
        }
    ]


def _assert_rollup_contract(conn: psycopg.Connection, *, started_at: datetime, finished_at: datetime) -> None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT donor_key_fingerprint, row_count, completed_at
            FROM cf.donor_search_rollup_provenance
            """
        )
        rows = cursor.fetchall()

    assert len(rows) == 1
    assert rows[0]["donor_key_fingerprint"] == donor_key_fingerprint()
    assert rows[0]["row_count"] > 0
    assert started_at <= rows[0]["completed_at"] <= finished_at


def _assert_specimen_resolution(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT canonical_name
            FROM core.person
            WHERE id = %s
            """,
            (UUID(browser_smoke_seed.SMOKE_PERSON_ID),),
        )
        person = cursor.fetchone()
        cursor.execute(
            """
            SELECT id, name
            FROM cf.committee
            WHERE btrim(lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g')), '-') = %s
            """,
            (browser_smoke_seed.SMOKE_COMMITTEE_SLUG,),
        )
        committee_rows = cursor.fetchall()

    assert person == {"canonical_name": browser_smoke_seed.SMOKE_PERSON_CANONICAL_NAME}
    assert committee_rows == [
        {
            "id": UUID(browser_smoke_seed.SMOKE_COMMITTEE_ID),
            "name": browser_smoke_seed.SMOKE_COMMITTEE_NAME,
        }
    ]


def _assert_chart_oracle_volume(conn: psycopg.Connection, browser_smoke_seed: object) -> None:
    filing_rows = fetch_committee_filing_breakdown(conn, UUID(browser_smoke_seed.SMOKE_COMMITTEE_ID))
    assert [(row["coverage_end_date"], row["cash_on_hand"]) for row in filing_rows] == [
        (date(2026, 6, 30), Decimal("345.00")),
        (date(2026, 3, 31), Decimal("125.00")),
    ]

    insights = fetch_person_contribution_insights(conn, UUID(browser_smoke_seed.SMOKE_PERSON_ID))
    assert insights is not None
    assert [
        (
            bucket["label"],
            bucket["min_amount"],
            bucket["max_amount"],
            bucket["total_amount"],
            bucket["transaction_count"],
        )
        for bucket in insights["itemized_size_buckets"]
        if bucket["transaction_count"] > 0
    ] == [
        ("$200 and under", Decimal("0.01"), Decimal("200.00"), Decimal("125.00"), 1),
        ("$200.01-$499.99", Decimal("200.01"), Decimal("499.99"), Decimal("300.00"), 1),
    ]


def test_chart_oracle_rejects_superseded_seed_receipts(capsys: pytest.CaptureFixture[str]) -> None:
    browser_smoke_seed, _env_lines, _started, _finished = _seed_and_parse_stdout(capsys)
    source_record_id = _fetch_seed_source_record_id(browser_smoke_seed)

    with get_connection() as conn:
        try:
            conn.execute(
                "UPDATE core.source_record SET superseded_by = id WHERE id = %s",
                (source_record_id,),
            )
            conn.commit()
            insights = fetch_person_contribution_insights(conn, UUID(browser_smoke_seed.SMOKE_PERSON_ID))
            assert insights is not None
            assert all(bucket["transaction_count"] == 0 for bucket in insights["itemized_size_buckets"])

            with pytest.raises(AssertionError):
                _assert_chart_oracle_volume(conn, browser_smoke_seed)
        finally:
            conn.execute(
                "UPDATE core.source_record SET superseded_by = NULL WHERE id = %s",
                (source_record_id,),
            )
            conn.commit()
            browser_smoke_seed.main()
            capsys.readouterr()
