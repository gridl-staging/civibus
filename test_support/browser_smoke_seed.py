"""Seed the DB-backed live browser-smoke contract."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg

from api.models.search import SearchParams
from api.queries import fetch_search_results
from api.queries.civics import fetch_current_federal_members
from api.test_campaign_finance_support import (
    CandidateCommitteeLinkSeed,
    CandidateRowSeed,
    CommitteeRowSeed,
    FilingRowSeed,
    TransactionRowSeed,
    insert_candidate_committee_link_row,
    insert_candidate_row,
    insert_committee_row,
    insert_electoral_division_row,
    insert_filing_row,
    insert_office_row,
    insert_officeholding_row,
    insert_transaction_row,
)
from core.db import get_connection, insert_data_source, insert_organization, insert_person, insert_source_record
from core.graph import age_post_connect, delete_entity_nodes
from core.refresh.donor_rollup import rebuild_donor_search_rollup
from core.types.python.models import DataSource, Organization, Person, SourceRecord, compute_record_hash
from domains.campaign_finance.constants import (
    FEC_BULK_DATA_SOURCE_DOMAIN,
    FEC_BULK_DATA_SOURCE_JURISDICTION,
    FEC_BULK_DATA_SOURCE_NAME,
)
from domains.campaign_finance.ingest.bulk_parser import read_bulk_file

SMOKE_PERSON_ID = "11111111-1111-4111-8111-111111111111"
SMOKE_PERSON_CANONICAL_NAME = "Jane Doe"
SMOKE_SECOND_PERSON_ID = "21111111-1111-4111-8111-111111111111"
SMOKE_SECOND_PERSON_CANONICAL_NAME = "Alex Money Senator"
SMOKE_NO_MONEY_PERSON_ID = "31111111-1111-4111-8111-111111111111"
SMOKE_NO_MONEY_PERSON_CANONICAL_NAME = "Maria No Money Delegate"
SMOKE_COMMITTEE_ID = "44444444-4444-4444-8444-444444444444"
SMOKE_COMMITTEE_FEC_ID = "C14000001"
SMOKE_COMMITTEE_NAME = "Citizens for Civibus"
SMOKE_COMMITTEE_SLUG = "citizens-for-civibus"
SMOKE_CANDIDATE_ID = "55555555-5555-4555-8555-555555555555"
SMOKE_CANDIDATE_FEC_ID = "H6NC14001"
SMOKE_CANDIDATE_NAME = "Pat Candidate"
SMOKE_CANDIDATE_SLUG = "pat-candidate"
# The /congress money leaderboard's second-ranked member (civibus-8lu): Alex
# Money Senator carries official FEC totals and Schedule E rows so the
# leaderboard's ordering, sort toggle, and comparison-bar ratio have live
# proof. Kept deliberately minimal — one candidate row, one spender committee,
# four IE transactions — per the civibus-5ud lesson: fix the seed gap, don't
# grow the seed wholesale.
SMOKE_SECOND_CANDIDATE_ID = "65555555-5555-4555-8555-555555555555"
SMOKE_SECOND_CANDIDATE_FEC_ID = "H6NC02001"
SMOKE_SECOND_CANDIDATE_NAME = "Senator, Alex Money"
SMOKE_IE_COMMITTEE_ID = "74444444-4444-4444-8444-444444444444"
SMOKE_IE_COMMITTEE_FEC_ID = "C14000002"
SMOKE_IE_COMMITTEE_NAME = "Civibus Outside Spenders"
# Rendered money the live leaderboard must show — the seed owns these numbers.
SMOKE_LEADER_IE_SUPPORT = Decimal("90.00")
SMOKE_LEADER_IE_OPPOSE = Decimal("30.00")
SMOKE_SECOND_TOTAL_RECEIPTS = Decimal("100.00")
SMOKE_SECOND_TOTAL_DISBURSEMENTS = Decimal("75.00")
SMOKE_SECOND_CASH_ON_HAND = Decimal("0.00")
SMOKE_SECOND_IE_SUPPORT = Decimal("20.00")
SMOKE_SECOND_IE_OPPOSE = Decimal("80.00")
SMOKE_SECOND_SOURCE_RECORD_URL = "https://example.org/browser-smoke/alex-money/record"
SMOKE_ORG_ID = "22222222-2222-4222-8222-222222222222"
SMOKE_SEARCH_RESULT_NAME = "Civibus Action Org"
SMOKE_ORG_CANONICAL_NAME = SMOKE_SEARCH_RESULT_NAME
# Mirrors SMOKE_SEARCH_QUERY in web/tests/smoke/fixtures.ts: the a11y shell
# journey loads /search?q=civ&entity_type=org and asserts a single result.
SMOKE_SEARCH_QUERY = "civ"
SMOKE_CANDIDATE_LIST_CONTEXT = "DEM · H · NC-01"
SMOKE_COMMITTEE_LIST_CONTEXT = "Q · DEM · NC"
SMOKE_DATA_SOURCE_NAME = "Indiana Campaign Finance"
SMOKE_DATA_SOURCE_DOMAIN = "campaign_finance"
SMOKE_DATA_SOURCE_JURISDICTION = "state/IN"
SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME = (
    f"{SMOKE_DATA_SOURCE_NAME} ({SMOKE_DATA_SOURCE_DOMAIN}/{SMOKE_DATA_SOURCE_JURISDICTION})"
)

_DIVISION_IDS = (
    UUID("14d10000-0000-4000-8000-000000000101"),
    UUID("14d10000-0000-4000-8000-000000000102"),
    UUID("14d10000-0000-4000-8000-000000000103"),
)
_OFFICE_ID = UUID("ee111111-1111-4111-8111-111111111111")
_OFFICEHOLDING_IDS = (
    UUID("14d10000-0000-4000-8000-000000000201"),
    UUID("14d10000-0000-4000-8000-000000000202"),
    UUID("14d10000-0000-4000-8000-000000000203"),
)
_DATA_SOURCE_ID = UUID("14d10000-0000-4000-8000-000000000301")
_SOURCE_RECORD_ID = UUID("14d10000-0000-4000-8000-000000000302")
# Alex's candidate rides its own source record so the leaderboard's per-member
# money-source links resolve to two DISTINCT hrefs — an ordering-proof detail.
_SECOND_SOURCE_RECORD_ID = UUID("14d10000-0000-4000-8000-000000000303")
_LINK_ID = UUID("14d10000-0000-4000-8000-000000000401")
_FILING_IDS = (
    UUID("14d10000-0000-4000-8000-000000000501"),
    UUID("14d10000-0000-4000-8000-000000000502"),
)
_IE_FILING_ID = UUID("14d10000-0000-4000-8000-000000000503")
_TRANSACTION_IDS = (
    UUID("14d10000-0000-4000-8000-000000000601"),
    UUID("14d10000-0000-4000-8000-000000000602"),
    UUID("14d10000-0000-4000-8000-000000000603"),
)
_IE_TRANSACTION_IDS = (
    UUID("14d10000-0000-4000-8000-000000000604"),
    UUID("14d10000-0000-4000-8000-000000000605"),
    UUID("14d10000-0000-4000-8000-000000000606"),
    UUID("14d10000-0000-4000-8000-000000000607"),
)
_PULL_DATE = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
_BULK_SAMPLE_DIRECTORY = Path(__file__).parents[1] / "tests/fixtures/bulk"
_PERSON_IDS = (
    UUID(SMOKE_PERSON_ID),
    UUID(SMOKE_SECOND_PERSON_ID),
    UUID(SMOKE_NO_MONEY_PERSON_ID),
)


def _fixture_column_values(file_type: str, column_name: str) -> frozenset[str]:
    path = (
        _BULK_SAMPLE_DIRECTORY
        / {
            "cm": "cm_sample.txt",
            "cn": "cn_sample.txt",
            "ccl": "ccl_sample.txt",
            "itcont": "itcont_sample.txt",
            "itpas2": "itpas2_sample.txt",
        }[file_type]
    )
    return frozenset(value for row in read_bulk_file(path, file_type) if (value := row[column_name]) is not None)


_BULK_SAMPLE_COMMITTEE_FEC_IDS = _fixture_column_values("cm", "CMTE_ID")
_BULK_SAMPLE_CANDIDATE_FEC_IDS = _fixture_column_values("cn", "CAND_ID")
_BULK_SAMPLE_SOURCE_RECORD_KEYS = frozenset(
    {
        *(f"cm:2024:{value}" for value in _BULK_SAMPLE_COMMITTEE_FEC_IDS),
        *(f"cn:2024:{value}" for value in _BULK_SAMPLE_CANDIDATE_FEC_IDS),
        *(f"ccl:2024:{value}" for value in _fixture_column_values("ccl", "LINKAGE_ID")),
        *_fixture_column_values("itcont", "SUB_ID"),
        *_fixture_column_values("itpas2", "SUB_ID"),
    }
)


def seed_browser_smoke(conn: psycopg.Connection) -> None:
    """Replace the deterministic browser-smoke rows and rebuild donor search."""
    canonical_bulk_sample_is_loaded = _assert_smoke_isolated(conn)
    with conn.transaction():
        if canonical_bulk_sample_is_loaded:
            _cleanup_canonical_bulk_sample(conn)
        _cleanup(conn)
        _seed_sources(conn)
        _seed_people_and_search_org(conn)
        _seed_civic_officeholders(conn)
        _seed_campaign_finance(conn)
    rebuild_donor_search_rollup(conn)


def main() -> None:
    with get_connection() as conn:
        seed_browser_smoke(conn)

    print(f"SMOKE_PERSON_ID={SMOKE_PERSON_ID}")
    print(f"SMOKE_COMMITTEE_SLUG={SMOKE_COMMITTEE_SLUG}")


def _cleanup_canonical_bulk_sample(conn: psycopg.Connection) -> None:
    data_source_id, source_record_ids = _bulk_sample_source_records(conn)
    candidate_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM cf.candidate WHERE fec_candidate_id = ANY(%s)",
            (list(_BULK_SAMPLE_CANDIDATE_FEC_IDS),),
        ).fetchall()
    ]
    committee_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM cf.committee WHERE fec_committee_id = ANY(%s)",
            (list(_BULK_SAMPLE_COMMITTEE_FEC_IDS),),
        ).fetchall()
    ]
    entity_ids_by_type = _bulk_sample_entity_ids(conn, source_record_ids)
    address_ids = entity_ids_by_type.get("address", [])
    age_post_connect(conn)
    delete_entity_nodes(conn, [*candidate_ids, *committee_ids])

    statements_and_params = (
        (
            "DELETE FROM cf.transaction WHERE source_record_id = ANY(%s) OR committee_id = ANY(%s)",
            (source_record_ids, committee_ids),
        ),
        (
            "DELETE FROM cf.filing WHERE source_record_id = ANY(%s) OR committee_id = ANY(%s)",
            (source_record_ids, committee_ids),
        ),
        (
            "DELETE FROM cf.candidate_committee_link WHERE source_record_id = ANY(%s) "
            "OR candidate_id = ANY(%s) OR committee_id = ANY(%s)",
            (source_record_ids, candidate_ids, committee_ids),
        ),
        (
            "DELETE FROM cf.committee_summary WHERE source_record_id = ANY(%s) OR committee_id = ANY(%s)",
            (source_record_ids, committee_ids),
        ),
        ("DELETE FROM cf.candidate WHERE id = ANY(%s)", (candidate_ids,)),
        ("DELETE FROM cf.committee WHERE id = ANY(%s)", (committee_ids,)),
        ("DELETE FROM core.field_provenance WHERE source_record_id = ANY(%s)", (source_record_ids,)),
        ("DELETE FROM core.contact_point WHERE source_record_id = ANY(%s)", (source_record_ids,)),
        ("DELETE FROM core.person_portrait WHERE source_record_id = ANY(%s)", (source_record_ids,)),
        ("DELETE FROM core.entity_address WHERE source_record_id = ANY(%s)", (source_record_ids,)),
        ("DELETE FROM core.entity_source WHERE source_record_id = ANY(%s)", (source_record_ids,)),
        ("DELETE FROM core.person WHERE id = ANY(%s)", (entity_ids_by_type.get("person", []),)),
        ("DELETE FROM core.organization WHERE id = ANY(%s)", (entity_ids_by_type.get("organization", []),)),
        ("DELETE FROM core.address WHERE id = ANY(%s)", (address_ids,)),
        ("DELETE FROM cf.stage4_resume_checkpoint WHERE data_source_id = %s", (data_source_id,)),
        ("DELETE FROM core.source_record WHERE id = ANY(%s)", (source_record_ids,)),
        ("DELETE FROM core.data_source WHERE id = %s", (data_source_id,)),
    )
    for statement, params in statements_and_params:
        conn.execute(statement, params)


def _bulk_sample_source_records(conn: psycopg.Connection) -> tuple[UUID, list[UUID]]:
    rows = conn.execute(
        """
        SELECT source.id, record.id, record.source_record_key
        FROM core.data_source source
        JOIN core.source_record record ON record.data_source_id = source.id
        WHERE source.domain = %s AND source.jurisdiction = %s AND source.name = %s
        """,
        (FEC_BULK_DATA_SOURCE_DOMAIN, FEC_BULK_DATA_SOURCE_JURISDICTION, FEC_BULK_DATA_SOURCE_NAME),
    ).fetchall()
    if not rows or {row[2] for row in rows} != _BULK_SAMPLE_SOURCE_RECORD_KEYS:
        raise RuntimeError("Canonical FEC bulk sample source records changed during browser-smoke seeding")
    return rows[0][0], [row[1] for row in rows]


def _bulk_sample_entity_ids(conn: psycopg.Connection, source_record_ids: list[UUID]) -> dict[str, list[UUID]]:
    entity_ids_by_type: dict[str, list[UUID]] = {}
    for entity_type, entity_id in conn.execute(
        "SELECT DISTINCT entity_type, entity_id FROM core.entity_source WHERE source_record_id = ANY(%s)",
        (source_record_ids,),
    ).fetchall():
        entity_ids_by_type.setdefault(entity_type, []).append(entity_id)
    return entity_ids_by_type


def _cleanup(conn: psycopg.Connection) -> None:
    conn.execute(
        "DELETE FROM cf.transaction WHERE id = ANY(%s::uuid[])",
        (list(_TRANSACTION_IDS) + list(_IE_TRANSACTION_IDS),),
    )
    conn.execute("DELETE FROM cf.filing WHERE id = ANY(%s::uuid[])", (list(_FILING_IDS) + [_IE_FILING_ID],))
    conn.execute("DELETE FROM cf.candidate_committee_link WHERE id = %s", (_LINK_ID,))
    conn.execute(
        "DELETE FROM cf.candidate WHERE id = ANY(%s::uuid[])",
        ([UUID(SMOKE_CANDIDATE_ID), UUID(SMOKE_SECOND_CANDIDATE_ID)],),
    )
    conn.execute(
        "DELETE FROM cf.committee WHERE id = ANY(%s::uuid[])",
        ([UUID(SMOKE_COMMITTEE_ID), UUID(SMOKE_IE_COMMITTEE_ID)],),
    )
    conn.execute(
        """
        DELETE FROM civic.officeholding
        WHERE id = ANY(%s::uuid[])
           OR person_id = ANY(%s::uuid[])
        """,
        (list(_OFFICEHOLDING_IDS), list(_PERSON_IDS)),
    )
    conn.execute(
        """
        DELETE FROM civic.office
        WHERE id = %s
          AND NOT EXISTS (
              SELECT 1
              FROM civic.officeholding officeholding
              WHERE officeholding.office_id = civic.office.id
          )
        """,
        (_OFFICE_ID,),
    )
    conn.execute("DELETE FROM civic.electoral_division WHERE id = ANY(%s::uuid[])", (list(_DIVISION_IDS),))
    conn.execute("DELETE FROM core.organization WHERE id = %s", (UUID(SMOKE_ORG_ID),))
    conn.execute(
        "DELETE FROM core.source_record WHERE id = ANY(%s::uuid[])",
        ([_SOURCE_RECORD_ID, _SECOND_SOURCE_RECORD_ID],),
    )
    conn.execute("DELETE FROM core.data_source WHERE id = %s", (_DATA_SOURCE_ID,))
    conn.execute("DELETE FROM core.person WHERE id = ANY(%s::uuid[])", (list(_PERSON_IDS),))


def _assert_smoke_isolated(conn: psycopg.Connection) -> bool:
    candidate_rows = conn.execute(
        """
        SELECT candidate.fec_candidate_id, source.domain, source.jurisdiction, source.name
        FROM cf.candidate candidate
        LEFT JOIN core.source_record record ON record.id = candidate.source_record_id
        LEFT JOIN core.data_source source ON source.id = record.data_source_id
        WHERE candidate.id <> ALL(%s::uuid[])
        """,
        ([UUID(SMOKE_CANDIDATE_ID), UUID(SMOKE_SECOND_CANDIDATE_ID)],),
    ).fetchall()
    committee_rows = conn.execute(
        """
        SELECT committee.fec_committee_id, source.domain, source.jurisdiction, source.name
        FROM cf.committee committee
        LEFT JOIN core.source_record record ON record.id = committee.source_record_id
        LEFT JOIN core.data_source source ON source.id = record.data_source_id
        WHERE committee.id <> ALL(%s::uuid[])
        """,
        ([UUID(SMOKE_COMMITTEE_ID), UUID(SMOKE_IE_COMMITTEE_ID)],),
    ).fetchall()
    canonical_bulk_sample_is_loaded = _is_canonical_bulk_sample(conn, candidate_rows, committee_rows)
    extra_search_org_count = _count_extra_search_organizations(
        conn,
        ignore_bulk_sample=canonical_bulk_sample_is_loaded,
    )
    extra_current_federal_member_count = _count_extra_current_federal_members(conn)
    campaign_finance_rows_are_allowed = (not candidate_rows and not committee_rows) or canonical_bulk_sample_is_loaded
    if campaign_finance_rows_are_allowed and extra_search_org_count == 0 and extra_current_federal_member_count == 0:
        return canonical_bulk_sample_is_loaded

    raise RuntimeError(
        "Browser-smoke seed requires an isolated database; found "
        f"{len(candidate_rows)} extra candidates, {len(committee_rows)} extra committees, "
        f"{extra_current_federal_member_count} extra current federal officeholders, and "
        f"{extra_search_org_count} extra organizations on the "
        f"'{SMOKE_SEARCH_QUERY}' organization search result page."
    )


def _is_canonical_bulk_sample(
    conn: psycopg.Connection,
    candidate_rows: list[tuple[object, ...]],
    committee_rows: list[tuple[object, ...]],
) -> bool:
    expected_source_identity = (
        FEC_BULK_DATA_SOURCE_DOMAIN,
        FEC_BULK_DATA_SOURCE_JURISDICTION,
        FEC_BULK_DATA_SOURCE_NAME,
    )
    campaign_finance_rows_match = {(row[0], *row[1:]) for row in candidate_rows} == {
        (fec_id, *expected_source_identity) for fec_id in _BULK_SAMPLE_CANDIDATE_FEC_IDS
    } and {(row[0], *row[1:]) for row in committee_rows} == {
        (fec_id, *expected_source_identity) for fec_id in _BULK_SAMPLE_COMMITTEE_FEC_IDS
    }
    if not campaign_finance_rows_match:
        return False
    try:
        _bulk_sample_source_records(conn)
    except RuntimeError:
        return False
    return True


def _count_extra_search_organizations(conn: psycopg.Connection, *, ignore_bulk_sample: bool) -> int:
    """Count non-canonical organizations the /search org route owner would return."""
    results = fetch_search_results(conn, SearchParams(q=SMOKE_SEARCH_QUERY, entity_type="org"))
    ignored_ids = {UUID(SMOKE_ORG_ID)}
    if ignore_bulk_sample:
        ignored_ids.update(
            row[0]
            for row in conn.execute(
                """
                SELECT id
                FROM core.organization
                WHERE identifiers ->> 'fec_committee_id' = ANY(%s)
                """,
                (list(_BULK_SAMPLE_COMMITTEE_FEC_IDS),),
            ).fetchall()
        )
    return sum(1 for result in results if result["entity_id"] not in ignored_ids)


def _count_extra_current_federal_members(conn: psycopg.Connection) -> int:
    """Count non-canonical members the /congress route owner would return."""
    return sum(1 for member in fetch_current_federal_members(conn) if member["person_id"] not in _PERSON_IDS)


def _seed_sources(conn: psycopg.Connection) -> None:
    source = DataSource(
        id=_DATA_SOURCE_ID,
        domain=SMOKE_DATA_SOURCE_DOMAIN,
        jurisdiction=SMOKE_DATA_SOURCE_JURISDICTION,
        name=SMOKE_DATA_SOURCE_NAME,
        source_url="https://example.org/browser-smoke/indiana-campaign-finance",
        source_format="api",
        license="public_domain",
        update_frequency="weekly",
        last_pull_at=_PULL_DATE,
        last_pull_status="success",
    )
    insert_data_source(conn, source)
    raw_fields = {
        "fixture": "browser-smoke-seed",
        "fec_candidate_id": SMOKE_CANDIDATE_FEC_ID,
        "fec_committee_id": SMOKE_COMMITTEE_FEC_ID,
    }
    insert_source_record(
        conn,
        SourceRecord(
            id=_SOURCE_RECORD_ID,
            data_source_id=_DATA_SOURCE_ID,
            source_record_key="browser-smoke-campaign-finance",
            source_url="https://example.org/browser-smoke/indiana-campaign-finance/record",
            raw_fields=raw_fields,
            pull_date=_PULL_DATE,
            record_hash=compute_record_hash(raw_fields),
        ),
    )
    second_raw_fields = {
        "fixture": "browser-smoke-seed-second-member",
        "fec_candidate_id": SMOKE_SECOND_CANDIDATE_FEC_ID,
        "fec_committee_id": SMOKE_IE_COMMITTEE_FEC_ID,
    }
    insert_source_record(
        conn,
        SourceRecord(
            id=_SECOND_SOURCE_RECORD_ID,
            data_source_id=_DATA_SOURCE_ID,
            source_record_key="browser-smoke-campaign-finance-second-member",
            source_url=SMOKE_SECOND_SOURCE_RECORD_URL,
            raw_fields=second_raw_fields,
            pull_date=_PULL_DATE,
            record_hash=compute_record_hash(second_raw_fields),
        ),
    )


def _seed_people_and_search_org(conn: psycopg.Connection) -> None:
    people = (
        (UUID(SMOKE_PERSON_ID), SMOKE_PERSON_CANONICAL_NAME, "Jane", "Doe"),
        (UUID(SMOKE_SECOND_PERSON_ID), SMOKE_SECOND_PERSON_CANONICAL_NAME, "Alex", "Senator"),
        (UUID(SMOKE_NO_MONEY_PERSON_ID), SMOKE_NO_MONEY_PERSON_CANONICAL_NAME, "Maria", "Delegate"),
    )
    for person_id, canonical_name, first_name, last_name in people:
        insert_person(
            conn,
            Person(
                id=person_id,
                canonical_name=canonical_name,
                first_name=first_name,
                last_name=last_name,
            ),
        )
    insert_organization(
        conn,
        Organization(
            id=UUID(SMOKE_ORG_ID),
            canonical_name=SMOKE_ORG_CANONICAL_NAME,
            org_type="nonprofit",
            registered_state="NC",
        ),
    )


def _seed_civic_officeholders(conn: psycopg.Connection) -> None:
    division_rows = (
        (_DIVISION_IDS[0], "nc_cd_01", "01"),
        (_DIVISION_IDS[1], "nc_cd_02", "02"),
        (_DIVISION_IDS[2], "nc_cd_03", "03"),
    )
    for division_id, name, district_number in division_rows:
        insert_electoral_division_row(
            conn,
            division_id=division_id,
            name=name,
            division_type="congressional_district",
            state="NC",
            district_number=district_number,
        )
    office_id = _resolve_or_seed_house_office(conn)
    for officeholding_id, person_id, division_id in zip(_OFFICEHOLDING_IDS, _PERSON_IDS, _DIVISION_IDS, strict=True):
        insert_officeholding_row(
            conn,
            officeholding_id=officeholding_id,
            person_id=person_id,
            office_id=office_id,
            electoral_division_id=division_id,
            valid_period="[2025-01-03,2100-01-01)",
        )


def _resolve_or_seed_house_office(conn: psycopg.Connection) -> UUID:
    row = conn.execute(
        """
        SELECT id
        FROM civic.office
        WHERE office_level = 'federal'
          AND state IS NULL
          AND name = 'us_house'
          AND electoral_division_id IS NULL
        ORDER BY id ASC
        LIMIT 1
        """
    ).fetchone()
    if row is not None:
        return row[0]

    insert_office_row(
        conn,
        office_id=_OFFICE_ID,
        name="us_house",
        title="Representative",
        state=None,
        electoral_division_id=None,
    )
    return _OFFICE_ID


def _seed_campaign_finance(conn: psycopg.Connection) -> None:
    insert_committee_row(
        conn,
        CommitteeRowSeed(
            id=UUID(SMOKE_COMMITTEE_ID),
            fec_committee_id=SMOKE_COMMITTEE_FEC_ID,
            name=SMOKE_COMMITTEE_NAME,
            source_record_id=_SOURCE_RECORD_ID,
            committee_type="Q",
            committee_designation="P",
            party="DEM",
            state="NC",
            city="Raleigh",
            zip_code="27601",
            treasurer_name="Smoke Treasurer",
        ),
    )
    insert_candidate_row(
        conn,
        CandidateRowSeed(
            id=UUID(SMOKE_CANDIDATE_ID),
            fec_candidate_id=SMOKE_CANDIDATE_FEC_ID,
            name=SMOKE_CANDIDATE_NAME,
            office="H",
            person_id=UUID(SMOKE_PERSON_ID),
            principal_committee_id=UUID(SMOKE_COMMITTEE_ID),
            source_record_id=_SOURCE_RECORD_ID,
            party="DEM",
            state="NC",
            district="01",
            incumbent_challenge="I",
            total_receipts=Decimal("250.00"),
            total_disbursements=Decimal("80.00"),
            cash_on_hand=Decimal("125.00"),
            summary_coverage_end_date=date(2026, 3, 19),
        ),
    )
    insert_candidate_committee_link_row(
        conn,
        CandidateCommitteeLinkSeed(
            id=_LINK_ID,
            candidate_id=UUID(SMOKE_CANDIDATE_ID),
            committee_id=UUID(SMOKE_COMMITTEE_ID),
            designation="P",
            candidate_election_year=2026,
            fec_election_year=2026,
            valid_period="[2025-01-01,2100-01-01)",
            source_record_id=_SOURCE_RECORD_ID,
        ),
    )
    # Second money-carrying member (civibus-8lu): official totals only — the
    # leaderboard's fundraising figures come from the candidate row's FEC
    # weball columns, so no committee link or itemized rows are needed.
    insert_candidate_row(
        conn,
        CandidateRowSeed(
            id=UUID(SMOKE_SECOND_CANDIDATE_ID),
            fec_candidate_id=SMOKE_SECOND_CANDIDATE_FEC_ID,
            name=SMOKE_SECOND_CANDIDATE_NAME,
            # Must match Alex's live officeholding (House, NC-02): the public
            # money row only links a candidate whose office/state/district
            # match the member's current seat.
            office="H",
            person_id=UUID(SMOKE_SECOND_PERSON_ID),
            principal_committee_id=None,
            source_record_id=_SECOND_SOURCE_RECORD_ID,
            party="REP",
            state="NC",
            district="02",
            incumbent_challenge="I",
            total_receipts=SMOKE_SECOND_TOTAL_RECEIPTS,
            total_disbursements=SMOKE_SECOND_TOTAL_DISBURSEMENTS,
            cash_on_hand=SMOKE_SECOND_CASH_ON_HAND,
            summary_coverage_end_date=date(2026, 3, 19),
        ),
    )
    _seed_filings(conn)
    _seed_transactions(conn)
    _seed_independent_expenditures(conn)


def _seed_filings(conn: psycopg.Connection) -> None:
    filing_rows = (
        (_FILING_IDS[0], "browser-smoke-2026-q1", "Q1 Filing (F3N)", date(2026, 1, 1), date(2026, 3, 31)),
        (_FILING_IDS[1], "browser-smoke-2026-q2", "Q2 Filing (F3N)", date(2026, 4, 1), date(2026, 6, 30)),
    )
    for filing_id, filing_fec_id, filing_name, coverage_start, coverage_end in filing_rows:
        insert_filing_row(
            conn,
            FilingRowSeed(
                id=filing_id,
                filing_fec_id=filing_fec_id,
                committee_id=UUID(SMOKE_COMMITTEE_ID),
                candidate_id=UUID(SMOKE_CANDIDATE_ID),
                report_type="F3",
                amendment_indicator="N",
                filing_name=filing_name,
                coverage_start_date=coverage_start,
                coverage_end_date=coverage_end,
                receipt_date=coverage_end,
                accepted_date=coverage_end,
                source_record_id=_SOURCE_RECORD_ID,
            ),
        )


def _seed_transactions(conn: psycopg.Connection) -> None:
    rows = (
        (_TRANSACTION_IDS[0], _FILING_IDS[0], date(2026, 2, 10), "15", Decimal("125.00"), "Small Donor", "Teacher"),
        (_TRANSACTION_IDS[1], _FILING_IDS[1], date(2026, 5, 10), "15", Decimal("300.00"), "Medium Donor", "Engineer"),
        (_TRANSACTION_IDS[2], _FILING_IDS[1], date(2026, 5, 20), "21B", Decimal("80.00"), "Office Vendor", None),
    )
    for transaction_id, filing_id, transaction_date, transaction_type, amount, contributor_name, occupation in rows:
        insert_transaction_row(
            conn,
            TransactionRowSeed(
                id=transaction_id,
                filing_id=filing_id,
                committee_id=UUID(SMOKE_COMMITTEE_ID),
                transaction_type=transaction_type,
                amount=amount,
                amendment_indicator="N",
                source_record_id=_SOURCE_RECORD_ID,
                transaction_identifier=f"browser-smoke-{transaction_id.hex[-4:]}",
                transaction_date=transaction_date,
                contributor_name_raw=contributor_name,
                contributor_entity_type="IND" if transaction_type.startswith("1") else "ORG",
                contributor_employer="Civibus Labs" if transaction_type.startswith("1") else None,
                contributor_occupation=occupation,
                contributor_city="Raleigh",
                contributor_state="NC",
                contributor_zip="27601",
            ),
        )


def _seed_independent_expenditures(conn: psycopg.Connection) -> None:
    """Schedule E rows for both money-carrying members (civibus-8lu).

    A dedicated spender committee keeps Citizens for Civibus's derived
    summary, cash trend, and chart oracles untouched. The four rows are the
    minimal set that makes both leaderboard sorts discriminating: Jane leads
    total_raised while Alex leads outside_against, so a broken sort toggle
    cannot render the same order twice.
    """
    insert_committee_row(
        conn,
        CommitteeRowSeed(
            id=UUID(SMOKE_IE_COMMITTEE_ID),
            fec_committee_id=SMOKE_IE_COMMITTEE_FEC_ID,
            name=SMOKE_IE_COMMITTEE_NAME,
            source_record_id=_SECOND_SOURCE_RECORD_ID,
            committee_type="O",
            committee_designation="U",
            party=None,
            state="NC",
            city="Raleigh",
            zip_code="27601",
            treasurer_name="Outside Treasurer",
        ),
    )
    insert_filing_row(
        conn,
        FilingRowSeed(
            id=_IE_FILING_ID,
            filing_fec_id="browser-smoke-2026-ie",
            committee_id=UUID(SMOKE_IE_COMMITTEE_ID),
            candidate_id=None,
            report_type="F24",
            amendment_indicator="N",
            filing_name="IE Filing (F24)",
            coverage_start_date=date(2026, 1, 1),
            coverage_end_date=date(2026, 6, 30),
            receipt_date=date(2026, 6, 30),
            accepted_date=date(2026, 6, 30),
            source_record_id=_SECOND_SOURCE_RECORD_ID,
        ),
    )
    ie_rows = (
        (_IE_TRANSACTION_IDS[0], UUID(SMOKE_CANDIDATE_ID), "S", "24E", SMOKE_LEADER_IE_SUPPORT),
        (_IE_TRANSACTION_IDS[1], UUID(SMOKE_CANDIDATE_ID), "O", "24A", SMOKE_LEADER_IE_OPPOSE),
        (_IE_TRANSACTION_IDS[2], UUID(SMOKE_SECOND_CANDIDATE_ID), "S", "24E", SMOKE_SECOND_IE_SUPPORT),
        (_IE_TRANSACTION_IDS[3], UUID(SMOKE_SECOND_CANDIDATE_ID), "O", "24A", SMOKE_SECOND_IE_OPPOSE),
    )
    for transaction_id, recipient_candidate_id, support_oppose, transaction_type, amount in ie_rows:
        insert_transaction_row(
            conn,
            TransactionRowSeed(
                id=transaction_id,
                filing_id=_IE_FILING_ID,
                committee_id=UUID(SMOKE_IE_COMMITTEE_ID),
                transaction_type=transaction_type,
                amount=amount,
                amendment_indicator="N",
                source_record_id=_SECOND_SOURCE_RECORD_ID,
                transaction_identifier=f"browser-smoke-ie-{transaction_id.hex[-4:]}",
                transaction_date=date(2026, 5, 15),
                contributor_entity_type="ORG",
                support_oppose=support_oppose,
                recipient_candidate_id=recipient_candidate_id,
            ),
        )


if __name__ == "__main__":
    main()
