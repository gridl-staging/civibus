from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import psycopg

from api.test_campaign_finance_support import (
    CandidateCommitteeLinkSeed,
    CandidateRowSeed,
    CommitteeRowSeed,
    FilingRowSeed,
    TransactionRowSeed,
    insert_candidate_committee_link_row,
    insert_candidate_row,
    insert_committee_row,
    insert_data_source_for_test,
    insert_electoral_division_row,
    insert_filing_row,
    insert_office_row,
    insert_officeholding_row,
    insert_source_record_for_test,
    insert_transaction_row,
)
from core.db import get_connection, insert_person
from core.refresh.donor_rollup import rebuild_donor_search_rollup
from core.types.python.models import Person


@dataclass(frozen=True)
class DonorSearchRecipientIds:
    person_id: UUID
    candidate_id: UUID
    committee_id: UUID


@dataclass(frozen=True)
class DonorSearchFixtureIds:
    alpha: DonorSearchRecipientIds
    alpha_duplicate_candidate: DonorSearchRecipientIds
    alpha_second_committee: DonorSearchRecipientIds
    beta: DonorSearchRecipientIds
    inactive: DonorSearchRecipientIds
    source_record_current: UUID
    source_record_secondary: UUID
    source_record_superseded: UUID
    source_record_replacement: UUID


@dataclass(frozen=True)
class DonorSearchFullScopeCounts:
    current_federal_officeholders: int
    linked_people: int
    candidate_scope_rows: int
    distinct_linked_committees: int
    unrelated_candidate_rows: int
    common_surname_transactions: int
    official_total_candidates: int
    support_ie_candidates: int
    oppose_ie_candidates: int


@dataclass(frozen=True)
class FullScopeDonorSearchFixtureIds:
    counts: DonorSearchFullScopeCounts
    primary_recipient: DonorSearchRecipientIds
    secondary_recipient: DonorSearchRecipientIds
    source_record_current: UUID
    source_record_secondary: UUID


@dataclass(frozen=True)
class DonorSearchSourceRecordIds:
    current: UUID
    secondary: UUID
    superseded: UUID
    replacement: UUID


@dataclass(frozen=True)
class DonorSearchRecipientScope:
    alpha: DonorSearchRecipientIds
    alpha_duplicate_candidate: DonorSearchRecipientIds
    alpha_second_committee: DonorSearchRecipientIds
    beta: DonorSearchRecipientIds
    inactive: DonorSearchRecipientIds


@dataclass(frozen=True)
class DonorSearchFilingIds:
    alpha: UUID
    alpha_second_committee: UUID
    beta: UUID
    inactive: UUID


@dataclass(frozen=True)
class CurrentRecipientSeedSpec:
    label: str
    person_id: UUID
    person_name: str
    officeholding_id: UUID
    office_id: UUID
    division_id: UUID
    candidate_id: UUID
    committee_id: UUID
    link_id: UUID
    fec_candidate_id: str
    fec_committee_id: str
    state: str
    district: str | None


@dataclass(frozen=True)
class ExistingRecipientCandidateLinkSpec:
    candidate_id: UUID
    committee_id: UUID
    link_id: UUID
    fec_candidate_id: str
    candidate_name: str
    state: str
    district: str | None


_PULL_DATE = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
_SOURCE_URL = "https://example.org/fec/donor-search"
_DATA_SOURCE_NAME = "Campaign Finance API Source donor-search-fixture"
_FULL_SCOPE_LINKED_OFFICEHOLDER_COUNT = 518
_FULL_SCOPE_EXTRA_CURRENT_CANDIDATE_ROWS = 8
_FULL_SCOPE_UNRELATED_CANDIDATE_ROWS = 300
_FULL_SCOPE_HIGH_FREQUENCY_DONOR_COUNT = 220
_FULL_SCOPE_WILLIAMS_TRANSACTION_COUNT = 30
_FULL_SCOPE_FOCUSED_RECIPIENT_COUNT = 2
_FULL_SCOPE_FOCUSED_FEC_AREA_CODE = "NC"
_FULL_SCOPE_CURRENT_FEC_AREA_CODE = "T0"
_FULL_SCOPE_EXTRA_FEC_AREA_CODE = "T9"
_FULL_SCOPE_UNRELATED_FEC_AREA_CODE = "T8"
DONOR_SEARCH_ALPHA_PERSON_ID = UUID("72000000-0000-4000-8000-000000000001")
DONOR_SEARCH_BETA_PERSON_ID = UUID("72000000-0000-4000-8000-000000000002")
DONOR_SEARCH_INACTIVE_PERSON_ID = UUID("72000000-0000-4000-8000-000000000003")


def seed_donor_search_fixture(
    conn: psycopg.Connection,
    *,
    extra_smith_rows: int = 0,
    include_ordering_tie_rows: bool = False,
) -> DonorSearchFixtureIds:
    cleanup_donor_search_fixture(conn)
    source_records = _seed_source_records(conn)
    recipients = _seed_recipient_scope(conn, source_records.current)
    filings = _seed_filings(conn, recipients, source_records)

    _seed_base_transactions(
        conn,
        recipients=recipients,
        filings=filings,
        source_records=source_records,
    )
    _seed_extra_smith_rows(
        conn,
        alpha=recipients.alpha,
        filing_alpha=filings.alpha,
        source_record_id=source_records.current,
        count=extra_smith_rows,
    )
    if include_ordering_tie_rows:
        _seed_ordering_tie_rows(
            conn,
            alpha=recipients.alpha,
            filing_alpha=filings.alpha,
            source_record_id=source_records.current,
        )
    rebuild_donor_search_rollup(conn)

    return DonorSearchFixtureIds(
        alpha=recipients.alpha,
        alpha_duplicate_candidate=recipients.alpha_duplicate_candidate,
        alpha_second_committee=recipients.alpha_second_committee,
        beta=recipients.beta,
        inactive=recipients.inactive,
        source_record_current=source_records.current,
        source_record_secondary=source_records.secondary,
        source_record_superseded=source_records.superseded,
        source_record_replacement=source_records.replacement,
    )


def seed_full_scope_skewed_donor_search_fixture(
    conn: psycopg.Connection,
) -> FullScopeDonorSearchFixtureIds:
    cleanup_donor_search_fixture(conn)
    source_records = _seed_source_records(conn)
    with conn.pipeline():
        recipients = _seed_full_current_recipient_scope(conn, source_record_id=source_records.current)
        _seed_extra_current_candidate_links(conn, recipients=recipients, source_record_id=source_records.current)
        _seed_unrelated_candidate_rows(conn, source_record_id=source_records.current)
        inactive = _seed_inactive_recipient(conn, source_record_id=source_records.current)
        inactive_filing_id = _seed_filing(
            conn,
            filing_id=UUID("72000000-0000-0000-0000-000000000043"),
            committee_id=inactive.committee_id,
            source_record_id=source_records.current,
        )
        unscoped_committee_id, unscoped_filing_id = _seed_unscoped_committee_control(conn, source_records.current)
        filings = _seed_full_scope_filings(conn, recipients, source_records.current)

        _seed_skewed_full_scope_transactions(
            conn,
            recipients=recipients,
            filings=filings,
            source_records=source_records,
            inactive=inactive,
            inactive_filing_id=inactive_filing_id,
            unscoped_committee_id=unscoped_committee_id,
            unscoped_filing_id=unscoped_filing_id,
        )
    _refresh_full_scope_planner_statistics(conn)
    rebuild_donor_search_rollup(conn)
    counts = fetch_full_scope_donor_search_counts(conn)
    return FullScopeDonorSearchFixtureIds(
        counts=counts,
        primary_recipient=recipients[0],
        secondary_recipient=recipients[1],
        source_record_current=source_records.current,
        source_record_secondary=source_records.secondary,
    )


def fetch_full_scope_donor_search_counts(conn: psycopg.Connection) -> DonorSearchFullScopeCounts:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH current_federal_candidate_committees AS (
                SELECT DISTINCT ON (candidate.person_id, link.committee_id)
                    candidate.person_id,
                    candidate.id AS candidate_id,
                    link.committee_id
                FROM civic.officeholding officeholding
                JOIN civic.office office
                  ON office.id = officeholding.office_id
                JOIN cf.candidate candidate
                  ON candidate.person_id = officeholding.person_id
                JOIN cf.candidate_committee_link link
                  ON link.candidate_id = candidate.id
                JOIN cf.committee committee
                  ON committee.id = link.committee_id
                WHERE officeholding.valid_period @> CURRENT_DATE
                  AND office.office_level = 'federal'
                  AND candidate.person_id IS NOT NULL
                  AND link.valid_period @> CURRENT_DATE
                ORDER BY
                    candidate.person_id,
                    link.committee_id,
                    candidate.name ASC,
                    candidate.id ASC
            )
            SELECT
                (
                    SELECT COUNT(*)
                    FROM civic.officeholding officeholding
                    JOIN civic.office office ON office.id = officeholding.office_id
                    WHERE officeholding.valid_period @> CURRENT_DATE
                      AND office.office_level = 'federal'
                )::integer AS current_federal_officeholders,
                COUNT(DISTINCT person_id)::integer AS linked_people,
                COUNT(*)::integer AS candidate_scope_rows,
                COUNT(DISTINCT committee_id)::integer AS distinct_linked_committees,
                (
                    SELECT COUNT(*)
                    FROM cf.candidate candidate
                    WHERE candidate.id::text LIKE '72000000-0000-000f-8000-%'
                )::integer AS unrelated_candidate_rows,
                (
                    SELECT COUNT(*)
                    FROM cf.transaction transaction
                    JOIN (
                        SELECT DISTINCT committee_id
                        FROM current_federal_candidate_committees
                    ) scope ON scope.committee_id = transaction.committee_id
                    WHERE transaction.contributor_name_raw ILIKE '%williams%'
                      AND transaction.transaction_type LIKE '1%'
                      AND transaction.contributor_entity_type = 'IND'
                      AND transaction.is_memo = FALSE
                      AND transaction.amendment_indicator != 'T'
                )::integer AS common_surname_transactions,
                COUNT(DISTINCT candidate_id) FILTER (
                    WHERE candidate_id IN (
                        SELECT candidate.id
                        FROM cf.candidate candidate
                        WHERE candidate.summary_coverage_end_date
                              BETWEEN DATE '2025-01-01' AND DATE '2026-12-31'
                          AND (
                              candidate.total_receipts IS NOT NULL
                              OR candidate.total_disbursements IS NOT NULL
                              OR candidate.cash_on_hand IS NOT NULL
                          )
                    )
                )::integer AS official_total_candidates,
                COUNT(DISTINCT candidate_id) FILTER (
                    WHERE candidate_id IN (
                        SELECT transaction.recipient_candidate_id
                        FROM cf.transaction transaction
                        WHERE transaction.support_oppose = 'S'
                          AND transaction.transaction_date
                              BETWEEN DATE '2025-01-01' AND DATE '2026-12-31'
                          AND transaction.is_memo = FALSE
                          AND transaction.amendment_indicator != 'T'
                    )
                )::integer AS support_ie_candidates,
                COUNT(DISTINCT candidate_id) FILTER (
                    WHERE candidate_id IN (
                        SELECT transaction.recipient_candidate_id
                        FROM cf.transaction transaction
                        WHERE transaction.support_oppose = 'O'
                          AND transaction.transaction_date
                              BETWEEN DATE '2025-01-01' AND DATE '2026-12-31'
                          AND transaction.is_memo = FALSE
                          AND transaction.amendment_indicator != 'T'
                    )
                )::integer AS oppose_ie_candidates
            FROM current_federal_candidate_committees
            """
        )
        row = cursor.fetchone()
    return DonorSearchFullScopeCounts(
        current_federal_officeholders=row[0],
        linked_people=row[1],
        candidate_scope_rows=row[2],
        distinct_linked_committees=row[3],
        unrelated_candidate_rows=row[4],
        common_surname_transactions=row[5],
        official_total_candidates=row[6],
        support_ie_candidates=row[7],
        oppose_ie_candidates=row[8],
    )


# source_record_key values are unique only within a data source, so fixture
# ownership must be anchored to the fixture's own core.data_source identity.
# Matching source_record_key alone would let cleanup delete an unrelated data
# source's committee/summary/source_record that happens to reuse a
# `donor-search-%` key. `%%` escapes the LIKE wildcard because every statement
# below carries the data-source-name parameter.
_FIXTURE_DATA_SOURCE_IDS_SQL = """
    SELECT id FROM core.data_source
    WHERE domain = 'campaign_finance'
      AND jurisdiction = 'federal/fec'
      AND name = %s
"""
_FIXTURE_SOURCE_RECORD_IDS_SQL = f"""
    SELECT id FROM core.source_record
    WHERE source_record_key LIKE 'donor-search-%%'
      AND data_source_id IN ({_FIXTURE_DATA_SOURCE_IDS_SQL})
"""


def cleanup_donor_search_fixture(conn: psycopg.Connection) -> None:
    """Remove deterministic donor-search fixture rows before reseeding."""
    fixture_person_ids, fixture_office_ids, fixture_division_ids = conn.execute(
        f"""
        WITH fixture_source_records AS (
            {_FIXTURE_SOURCE_RECORD_IDS_SQL}
        ), fixture_people AS (
            SELECT DISTINCT person_id
            FROM cf.candidate
            WHERE source_record_id IN (SELECT id FROM fixture_source_records)
              AND person_id IS NOT NULL
        ), fixture_officeholdings AS (
            SELECT office_id, electoral_division_id
            FROM civic.officeholding
            WHERE person_id IN (SELECT person_id FROM fixture_people)
              AND (source_record_id IS NULL
                   OR source_record_id IN (SELECT id FROM fixture_source_records))
        )
        SELECT
            ARRAY(SELECT person_id FROM fixture_people),
            ARRAY(SELECT DISTINCT office_id FROM fixture_officeholdings),
            ARRAY(SELECT DISTINCT electoral_division_id FROM fixture_officeholdings
                  WHERE electoral_division_id IS NOT NULL)
        """,
        (_DATA_SOURCE_NAME,),
    ).fetchone()
    delete_statements = [
        f"""
        DELETE FROM cf.transaction
        WHERE source_record_id IN ({_FIXTURE_SOURCE_RECORD_IDS_SQL})
        """,
        f"""
        DELETE FROM cf.filing
        WHERE source_record_id IN ({_FIXTURE_SOURCE_RECORD_IDS_SQL})
        """,
        f"""
        DELETE FROM cf.candidate_committee_link
        WHERE source_record_id IN ({_FIXTURE_SOURCE_RECORD_IDS_SQL})
        """,
        f"""
        DELETE FROM civic.officeholding officeholding
        WHERE EXISTS (
            SELECT 1
            FROM cf.candidate candidate
            WHERE candidate.person_id = officeholding.person_id
              AND candidate.source_record_id IN ({_FIXTURE_SOURCE_RECORD_IDS_SQL})
        )
          AND (officeholding.source_record_id IS NULL
               OR officeholding.source_record_id IN ({_FIXTURE_SOURCE_RECORD_IDS_SQL}))
        """,
        f"""
        DELETE FROM cf.candidate
        WHERE source_record_id IN ({_FIXTURE_SOURCE_RECORD_IDS_SQL})
        """,
        f"""
        DELETE FROM cf.committee_summary
        WHERE committee_id IN (
            SELECT committee.id
            FROM cf.committee committee
            WHERE committee.source_record_id IN ({_FIXTURE_SOURCE_RECORD_IDS_SQL})
        )
        """,
        f"""
        DELETE FROM cf.committee
        WHERE source_record_id IN ({_FIXTURE_SOURCE_RECORD_IDS_SQL})
        """,
        f"""
        UPDATE core.source_record SET superseded_by = NULL
        WHERE source_record_key LIKE 'donor-search-%%'
          AND data_source_id IN ({_FIXTURE_DATA_SOURCE_IDS_SQL})
        """,
        f"""
        DELETE FROM core.source_record
        WHERE source_record_key LIKE 'donor-search-%%'
          AND data_source_id IN ({_FIXTURE_DATA_SOURCE_IDS_SQL})
        """,
        "DELETE FROM core.data_source WHERE domain = 'campaign_finance' AND jurisdiction = 'federal/fec' AND name = %s",
    ]
    for statement in delete_statements:
        params = (_DATA_SOURCE_NAME,) * statement.count("%s") or None
        conn.execute(statement, params)
    conn.execute(
        "DELETE FROM civic.office office WHERE id = ANY(%s) "
        "AND NOT EXISTS (SELECT 1 FROM civic.officeholding WHERE office_id = office.id)",
        (fixture_office_ids,),
    )
    conn.execute(
        "DELETE FROM civic.electoral_division division WHERE id = ANY(%s) "
        "AND NOT EXISTS (SELECT 1 FROM civic.office WHERE electoral_division_id = division.id) "
        "AND NOT EXISTS (SELECT 1 FROM civic.officeholding WHERE electoral_division_id = division.id)",
        (fixture_division_ids,),
    )
    conn.execute(
        "DELETE FROM core.person person WHERE id = ANY(%s) "
        "AND NOT EXISTS (SELECT 1 FROM civic.officeholding WHERE person_id = person.id) "
        "AND NOT EXISTS (SELECT 1 FROM cf.candidate WHERE person_id = person.id)",
        (fixture_person_ids,),
    )


def _seed_source_records(conn: psycopg.Connection) -> DonorSearchSourceRecordIds:
    data_source = insert_data_source_for_test(
        conn,
        jurisdiction="federal/fec",
        name_suffix="donor-search-fixture",
    )
    current_source_id = UUID("72000000-0000-0000-0000-000000000001")
    secondary_source_id = UUID("72000000-0000-0000-0000-000000000002")
    replacement_source_id = UUID("72000000-0000-0000-0000-000000000003")
    superseded_source_id = UUID("72000000-0000-0000-0000-000000000004")
    insert_source_record_for_test(
        conn,
        source_record_id=current_source_id,
        data_source_id=data_source.id,
        source_record_key="donor-search-current",
        source_url=f"{_SOURCE_URL}/current",
        pull_date=_PULL_DATE,
    )
    insert_source_record_for_test(
        conn,
        source_record_id=secondary_source_id,
        data_source_id=data_source.id,
        source_record_key="donor-search-secondary",
        source_url=f"{_SOURCE_URL}/secondary",
        pull_date=_PULL_DATE.replace(hour=11),
    )
    insert_source_record_for_test(
        conn,
        source_record_id=replacement_source_id,
        data_source_id=data_source.id,
        source_record_key="donor-search-replacement",
        source_url=f"{_SOURCE_URL}/replacement",
        pull_date=_PULL_DATE.replace(hour=10),
    )
    insert_source_record_for_test(
        conn,
        source_record_id=superseded_source_id,
        data_source_id=data_source.id,
        source_record_key="donor-search-superseded",
        source_url=f"{_SOURCE_URL}/superseded",
        pull_date=_PULL_DATE.replace(hour=9),
        superseded_by=replacement_source_id,
    )
    return DonorSearchSourceRecordIds(
        current=current_source_id,
        secondary=secondary_source_id,
        superseded=superseded_source_id,
        replacement=replacement_source_id,
    )


def _seed_recipient_scope(conn: psycopg.Connection, source_record_id: UUID) -> DonorSearchRecipientScope:
    alpha = _seed_current_federal_recipient(
        conn,
        CurrentRecipientSeedSpec(
            label="alpha",
            person_id=DONOR_SEARCH_ALPHA_PERSON_ID,
            person_name="Alpha Officeholder",
            officeholding_id=UUID("72000000-0000-0000-0000-000000000011"),
            office_id=UUID("72000000-0000-0000-0000-000000000012"),
            division_id=UUID("72000000-0000-0000-0000-000000000013"),
            candidate_id=UUID("72000000-0000-0000-0000-000000000014"),
            committee_id=UUID("72000000-0000-0000-0000-000000000015"),
            link_id=UUID("72000000-0000-0000-0000-000000000016"),
            fec_candidate_id="H9NC72001",
            fec_committee_id="C72000001",
            state="NC",
            district="01",
        ),
        source_record_id=source_record_id,
    )
    alpha_duplicate_candidate = _seed_candidate_link_for_existing_recipient(
        conn,
        person_id=alpha.person_id,
        spec=ExistingRecipientCandidateLinkSpec(
            candidate_id=UUID("72000000-0000-0000-0000-000000000017"),
            committee_id=alpha.committee_id,
            link_id=UUID("72000000-0000-0000-0000-000000000018"),
            fec_candidate_id="H0NC01099",
            candidate_name="Alpha Officeholder Alternate Filing",
            state="NC",
            district="01",
        ),
        source_record_id=source_record_id,
    )
    alpha_second_committee_id = UUID("72000000-0000-0000-0000-000000000019")
    insert_committee_row(
        conn,
        CommitteeRowSeed(
            id=alpha_second_committee_id,
            fec_committee_id="C72000009",
            name="Alpha Officeholder Victory Committee",
            source_record_id=source_record_id,
            state="NC",
        ),
    )
    alpha_second_committee = _seed_candidate_link_for_existing_recipient(
        conn,
        person_id=alpha.person_id,
        spec=ExistingRecipientCandidateLinkSpec(
            candidate_id=UUID("72000000-0000-0000-0000-000000000020"),
            committee_id=alpha_second_committee_id,
            link_id=UUID("72000000-0000-0000-0000-000000000029"),
            fec_candidate_id="H0NC01100",
            candidate_name="Alpha Officeholder Victory",
            state="NC",
            district="01",
        ),
        source_record_id=source_record_id,
    )
    beta = _seed_current_federal_recipient(
        conn,
        CurrentRecipientSeedSpec(
            label="beta",
            person_id=DONOR_SEARCH_BETA_PERSON_ID,
            person_name="Beta Officeholder",
            officeholding_id=UUID("72000000-0000-0000-0000-000000000021"),
            office_id=UUID("72000000-0000-0000-0000-000000000022"),
            division_id=UUID("72000000-0000-0000-0000-000000000023"),
            candidate_id=UUID("72000000-0000-0000-0000-000000000024"),
            committee_id=UUID("72000000-0000-0000-0000-000000000025"),
            link_id=UUID("72000000-0000-0000-0000-000000000026"),
            fec_candidate_id="S0NC00002",
            fec_committee_id="C72000002",
            state="NC",
            district=None,
        ),
        source_record_id=source_record_id,
    )
    inactive = _seed_inactive_recipient(
        conn,
        source_record_id=source_record_id,
    )
    return DonorSearchRecipientScope(
        alpha=alpha,
        alpha_duplicate_candidate=alpha_duplicate_candidate,
        alpha_second_committee=alpha_second_committee,
        beta=beta,
        inactive=inactive,
    )


def _seed_filings(
    conn: psycopg.Connection,
    recipients: DonorSearchRecipientScope,
    source_records: DonorSearchSourceRecordIds,
) -> DonorSearchFilingIds:
    filing_alpha = _seed_filing(
        conn,
        filing_id=UUID("72000000-0000-0000-0000-000000000041"),
        committee_id=recipients.alpha.committee_id,
        source_record_id=source_records.current,
    )
    filing_beta = _seed_filing(
        conn,
        filing_id=UUID("72000000-0000-0000-0000-000000000042"),
        committee_id=recipients.beta.committee_id,
        source_record_id=source_records.secondary,
    )
    filing_inactive = _seed_filing(
        conn,
        filing_id=UUID("72000000-0000-0000-0000-000000000043"),
        committee_id=recipients.inactive.committee_id,
        source_record_id=source_records.current,
    )
    filing_alpha_second_committee = _seed_filing(
        conn,
        filing_id=UUID("72000000-0000-0000-0000-000000000044"),
        committee_id=recipients.alpha_second_committee.committee_id,
        source_record_id=source_records.current,
    )
    return DonorSearchFilingIds(
        alpha=filing_alpha,
        alpha_second_committee=filing_alpha_second_committee,
        beta=filing_beta,
        inactive=filing_inactive,
    )


def _seed_current_federal_recipient(
    conn: psycopg.Connection,
    spec: CurrentRecipientSeedSpec,
    *,
    source_record_id: UUID,
) -> DonorSearchRecipientIds:
    person_id = _seed_person(conn, person_id=spec.person_id, name=spec.person_name)
    insert_electoral_division_row(
        conn,
        division_id=spec.division_id,
        name=f"{spec.state} {spec.label} federal division",
        division_type="congressional_district" if spec.district else "statewide",
        state=spec.state,
        district_number=spec.district,
    )
    insert_office_row(
        conn,
        office_id=spec.office_id,
        name="us_house" if spec.district else "us_senate",
        title="Representative" if spec.district else "Senator",
        state=spec.state,
        electoral_division_id=spec.division_id,
    )
    insert_officeholding_row(
        conn,
        officeholding_id=spec.officeholding_id,
        person_id=person_id,
        office_id=spec.office_id,
        electoral_division_id=spec.division_id,
    )
    insert_committee_row(
        conn,
        CommitteeRowSeed(
            id=spec.committee_id,
            fec_committee_id=spec.fec_committee_id,
            name=f"{spec.person_name} Committee",
            source_record_id=source_record_id,
            state=spec.state,
        ),
    )
    insert_candidate_row(
        conn,
        CandidateRowSeed(
            id=spec.candidate_id,
            fec_candidate_id=spec.fec_candidate_id,
            name=spec.person_name,
            office="H" if spec.district else "S",
            person_id=person_id,
            principal_committee_id=spec.committee_id,
            source_record_id=source_record_id,
            state=spec.state,
            district=spec.district,
        ),
    )
    insert_candidate_committee_link_row(
        conn,
        CandidateCommitteeLinkSeed(
            id=spec.link_id,
            candidate_id=spec.candidate_id,
            committee_id=spec.committee_id,
            valid_period="[2024-01-01,2100-01-01)",
            designation="P",
            source_record_id=source_record_id,
        ),
    )
    return DonorSearchRecipientIds(
        person_id=person_id,
        candidate_id=spec.candidate_id,
        committee_id=spec.committee_id,
    )


def _seed_candidate_link_for_existing_recipient(
    conn: psycopg.Connection,
    *,
    person_id: UUID,
    spec: ExistingRecipientCandidateLinkSpec,
    source_record_id: UUID,
) -> DonorSearchRecipientIds:
    insert_candidate_row(
        conn,
        CandidateRowSeed(
            id=spec.candidate_id,
            fec_candidate_id=spec.fec_candidate_id,
            name=spec.candidate_name,
            office="H" if spec.district else "S",
            person_id=person_id,
            principal_committee_id=spec.committee_id,
            source_record_id=source_record_id,
            state=spec.state,
            district=spec.district,
        ),
    )
    insert_candidate_committee_link_row(
        conn,
        CandidateCommitteeLinkSeed(
            id=spec.link_id,
            candidate_id=spec.candidate_id,
            committee_id=spec.committee_id,
            valid_period="[2024-01-01,2100-01-01)",
            designation="P",
            source_record_id=source_record_id,
        ),
    )
    return DonorSearchRecipientIds(
        person_id=person_id,
        candidate_id=spec.candidate_id,
        committee_id=spec.committee_id,
    )


def _seed_inactive_recipient(conn: psycopg.Connection, *, source_record_id: UUID) -> DonorSearchRecipientIds:
    person_id = _seed_person(
        conn,
        person_id=DONOR_SEARCH_INACTIVE_PERSON_ID,
        name="Inactive Officeholder",
    )
    division_id = UUID("72000000-0000-0000-0000-000000000033")
    office_id = UUID("72000000-0000-0000-0000-000000000032")
    insert_electoral_division_row(
        conn,
        division_id=division_id,
        name="Inactive federal division",
        division_type="congressional_district",
        state="NC",
        district_number="02",
    )
    insert_office_row(
        conn,
        office_id=office_id,
        name="us_house",
        title="Representative",
        state="NC",
        electoral_division_id=division_id,
    )
    insert_officeholding_row(
        conn,
        officeholding_id=UUID("72000000-0000-0000-0000-000000000031"),
        person_id=person_id,
        office_id=office_id,
        electoral_division_id=division_id,
        valid_period="[2020-01-01,2021-01-01)",
    )
    candidate_id = UUID("72000000-0000-0000-0000-000000000034")
    committee_id = UUID("72000000-0000-0000-0000-000000000035")
    insert_committee_row(
        conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C72000003",
            name="Inactive Officeholder Committee",
            source_record_id=source_record_id,
            state="NC",
        ),
    )
    insert_candidate_row(
        conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02003",
            name="Inactive Officeholder",
            office="H",
            person_id=person_id,
            principal_committee_id=committee_id,
            source_record_id=source_record_id,
            state="NC",
            district="02",
        ),
    )
    insert_candidate_committee_link_row(
        conn,
        CandidateCommitteeLinkSeed(
            id=UUID("72000000-0000-0000-0000-000000000036"),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2024-01-01,2100-01-01)",
            designation="P",
            source_record_id=source_record_id,
        ),
    )
    return DonorSearchRecipientIds(person_id=person_id, candidate_id=candidate_id, committee_id=committee_id)


def _full_scope_uuid(kind: int, index: int) -> UUID:
    return UUID(f"72000000-0000-{kind:04x}-8000-{index + 1:012d}")


def _full_scope_fec_candidate_id(*, office: str, cycle: int, area_code: str, index: int) -> str:
    return f"{office}{cycle}{area_code}{index:05d}"


def _seed_full_current_recipient_scope(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
) -> list[DonorSearchRecipientIds]:
    division_id = _full_scope_uuid(4, 0)
    office_id = _full_scope_uuid(3, 0)
    insert_electoral_division_row(
        conn,
        division_id=division_id,
        name="Full scope federal division",
        division_type="statewide",
        state="NC",
        district_number=None,
    )
    insert_office_row(
        conn,
        office_id=office_id,
        name="us_senate",
        title="Senator",
        state="NC",
        electoral_division_id=division_id,
    )
    recipients: list[DonorSearchRecipientIds] = []
    for index in range(_FULL_SCOPE_LINKED_OFFICEHOLDER_COUNT):
        recipients.append(
            _seed_current_federal_recipient_link(
                conn,
                index=index,
                office_id=office_id,
                division_id=division_id,
                source_record_id=source_record_id,
            )
        )
    return recipients


def _seed_current_federal_recipient_link(
    conn: psycopg.Connection,
    *,
    index: int,
    office_id: UUID,
    division_id: UUID,
    source_record_id: UUID,
) -> DonorSearchRecipientIds:
    person_name = f"Full Scope Officeholder {index:03d}"
    person_id = _seed_person(conn, person_id=_full_scope_uuid(1, index), name=person_name)
    insert_officeholding_row(
        conn,
        officeholding_id=_full_scope_uuid(2, index),
        person_id=person_id,
        office_id=office_id,
        electoral_division_id=division_id,
    )
    committee_id = _full_scope_uuid(6, index)
    candidate_id = _full_scope_uuid(5, index)
    insert_committee_row(
        conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id=f"C7{index + 200000:07d}",
            name=f"{person_name} Committee",
            source_record_id=source_record_id,
            state="NC",
        ),
    )
    insert_candidate_row(
        conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id=_full_scope_fec_candidate_id(
                office="S",
                cycle=6,
                area_code=(
                    _FULL_SCOPE_FOCUSED_FEC_AREA_CODE
                    if index < _FULL_SCOPE_FOCUSED_RECIPIENT_COUNT
                    else _FULL_SCOPE_CURRENT_FEC_AREA_CODE
                ),
                index=index,
            ),
            name=person_name,
            office="S",
            person_id=person_id,
            principal_committee_id=committee_id,
            source_record_id=source_record_id,
            state="NC",
            district=None,
            total_receipts=Decimal("10000.00") + index,
            total_disbursements=Decimal("2500.00") + index,
            cash_on_hand=Decimal("7500.00"),
            summary_coverage_end_date=date(2026, 6, 30),
        ),
    )
    insert_candidate_committee_link_row(
        conn,
        CandidateCommitteeLinkSeed(
            id=_full_scope_uuid(7, index),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2024-01-01,2100-01-01)",
            designation="P",
            source_record_id=source_record_id,
        ),
    )
    return DonorSearchRecipientIds(person_id=person_id, candidate_id=candidate_id, committee_id=committee_id)


def _seed_extra_current_candidate_links(
    conn: psycopg.Connection,
    *,
    recipients: list[DonorSearchRecipientIds],
    source_record_id: UUID,
) -> None:
    """Add live-shape duplicate scope rows without increasing committee scope.

    Stage 1 measured about 526 current candidate-scope rows but 518 distinct
    committees. These rows model that gap by linking already-current people to
    already-scoped committees that do not receive the focused known-answer donor.
    """
    for index in range(_FULL_SCOPE_EXTRA_CURRENT_CANDIDATE_ROWS):
        person = recipients[100 + index]
        committee = recipients[200 + index]
        candidate_id = _full_scope_uuid(18, index)
        insert_candidate_row(
            conn,
            CandidateRowSeed(
                id=candidate_id,
                fec_candidate_id=_full_scope_fec_candidate_id(
                    office="S",
                    cycle=6,
                    area_code=_FULL_SCOPE_EXTRA_FEC_AREA_CODE,
                    index=index,
                ),
                name=f"Full Scope Alternate Current {index:03d}",
                office="S",
                person_id=person.person_id,
                principal_committee_id=committee.committee_id,
                source_record_id=source_record_id,
                state="NC",
                district=None,
                total_receipts=Decimal("9000.00") + index,
                total_disbursements=Decimal("2000.00") + index,
                cash_on_hand=Decimal("7000.00"),
                summary_coverage_end_date=date(2026, 6, 30),
            ),
        )
        insert_candidate_committee_link_row(
            conn,
            CandidateCommitteeLinkSeed(
                id=_full_scope_uuid(19, index),
                candidate_id=candidate_id,
                committee_id=committee.committee_id,
                valid_period="[2024-01-01,2100-01-01)",
                designation="J",
                source_record_id=source_record_id,
            ),
        )


def _seed_unrelated_candidate_rows(conn: psycopg.Connection, *, source_record_id: UUID) -> None:
    for index in range(_FULL_SCOPE_UNRELATED_CANDIDATE_ROWS):
        person_name = f"Unrelated Candidate Person {index:04d}"
        person_id = _seed_person(conn, person_id=_full_scope_uuid(14, index), name=person_name)
        committee_id = _full_scope_uuid(16, index)
        candidate_id = _full_scope_uuid(15, index)
        insert_committee_row(
            conn,
            CommitteeRowSeed(
                id=committee_id,
                fec_committee_id=f"C8{index + 300000:07d}",
                name=f"{person_name} Committee",
                source_record_id=source_record_id,
                state="NC",
            ),
        )
        insert_candidate_row(
            conn,
            CandidateRowSeed(
                id=candidate_id,
                fec_candidate_id=_full_scope_fec_candidate_id(
                    office="H",
                    cycle=8,
                    area_code=_FULL_SCOPE_UNRELATED_FEC_AREA_CODE,
                    index=index,
                ),
                name=person_name,
                office="H",
                person_id=person_id,
                principal_committee_id=committee_id,
                source_record_id=source_record_id,
                state="NC",
                district=f"{index % 99 + 1:02d}",
                total_receipts=Decimal("100.00") + index,
                summary_coverage_end_date=date(2026, 6, 30),
            ),
        )
        insert_candidate_committee_link_row(
            conn,
            CandidateCommitteeLinkSeed(
                id=_full_scope_uuid(17, index),
                candidate_id=candidate_id,
                committee_id=committee_id,
                valid_period="[2024-01-01,2100-01-01)",
                designation="P",
                source_record_id=source_record_id,
            ),
        )


def _refresh_full_scope_planner_statistics(conn: psycopg.Connection) -> None:
    for table in (
        "civic.officeholding",
        "civic.office",
        "core.person",
        "cf.candidate",
        "cf.candidate_committee_link",
        "cf.committee",
        "cf.filing",
        "cf.transaction",
    ):
        conn.execute(f"ANALYZE {table}")


def _seed_full_scope_filings(
    conn: psycopg.Connection,
    recipients: list[DonorSearchRecipientIds],
    source_record_id: UUID,
) -> dict[UUID, UUID]:
    filings: dict[UUID, UUID] = {}
    for index, recipient in enumerate(recipients):
        filings[recipient.committee_id] = _seed_filing(
            conn,
            filing_id=_full_scope_uuid(8, index),
            committee_id=recipient.committee_id,
            source_record_id=source_record_id,
        )
    return filings


def _seed_unscoped_committee_control(conn: psycopg.Connection, source_record_id: UUID) -> tuple[UUID, UUID]:
    committee_id = _full_scope_uuid(10, 0)
    filing_id = _full_scope_uuid(11, 0)
    insert_committee_row(
        conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C72999999",
            name="Unscoped Donor Search Control",
            source_record_id=source_record_id,
            state="NC",
        ),
    )
    _seed_filing(conn, filing_id=filing_id, committee_id=committee_id, source_record_id=source_record_id)
    return committee_id, filing_id


def _seed_skewed_full_scope_transactions(
    conn: psycopg.Connection,
    *,
    recipients: list[DonorSearchRecipientIds],
    filings: dict[UUID, UUID],
    source_records: DonorSearchSourceRecordIds,
    inactive: DonorSearchRecipientIds,
    inactive_filing_id: UUID,
    unscoped_committee_id: UUID,
    unscoped_filing_id: UUID,
) -> None:
    rows = _full_scope_high_frequency_rows(recipients, filings, source_records)
    rows.extend(_full_scope_ie_rows(recipients, filings, source_records.current))
    rows.extend(
        [
            _full_scope_control_transaction(
                index=1,
                filing_id=inactive_filing_id,
                committee_id=inactive.committee_id,
                source_record_id=source_records.current,
                contributor_name_raw="CONTROL WILLIAMS INACTIVE",
            ),
            _full_scope_control_transaction(
                index=2,
                filing_id=unscoped_filing_id,
                committee_id=unscoped_committee_id,
                source_record_id=source_records.current,
                contributor_name_raw="CONTROL WILLIAMS UNSCOPED",
            ),
        ]
    )
    for row in rows:
        insert_transaction_row(conn, row)


def _full_scope_ie_rows(
    recipients: list[DonorSearchRecipientIds],
    filings: dict[UUID, UUID],
    source_record_id: UUID,
) -> list[TransactionRowSeed]:
    rows: list[TransactionRowSeed] = []
    for index, recipient in enumerate(recipients):
        transaction_values = {
            "filing_id": filings[recipient.committee_id],
            "committee_id": recipient.committee_id,
            "source_record_id": source_record_id,
            "contributor_name_raw": f"FULL SCOPE IE SPENDER {index:03d}",
            "contributor_employer": "Schedule E Fixture",
            "contributor_zip": "27701",
            "recipient_candidate_id": recipient.candidate_id,
            "recipient_committee_id": recipient.committee_id,
            "transaction_date": date(2026, 6, 1),
        }
        rows.append(
            _transaction(
                _full_scope_uuid(12, index),
                transaction_type="24E",
                transaction_identifier=f"donor-search-ie-support-{index:03d}",
                amount=Decimal("25.00"),
                support_oppose="S",
                **transaction_values,
            )
        )
        rows.append(
            _transaction(
                _full_scope_uuid(13, index),
                transaction_type="24E",
                transaction_identifier=f"donor-search-ie-oppose-{index:03d}",
                amount=Decimal("10.00"),
                support_oppose="O",
                **transaction_values,
            )
        )
    return rows


def _full_scope_high_frequency_rows(
    recipients: list[DonorSearchRecipientIds],
    filings: dict[UUID, UUID],
    source_records: DonorSearchSourceRecordIds,
) -> list[TransactionRowSeed]:
    rows: list[TransactionRowSeed] = []
    primary = recipients[0]
    secondary = recipients[1]
    for index in range(_FULL_SCOPE_WILLIAMS_TRANSACTION_COUNT):
        recipient = primary if index % 3 else secondary
        rows.append(
            _full_scope_transaction(
                index=index,
                filing_id=filings[recipient.committee_id],
                committee_id=recipient.committee_id,
                source_record_id=source_records.current if recipient is primary else source_records.secondary,
                amount=Decimal("100.00"),
                contributor_name_raw="FOCUSED WILLIAMS",
                contributor_employer="Bound Fixture",
                contributor_zip="27701",
                recipient_candidate_id=recipient.candidate_id,
                recipient_committee_id=recipient.committee_id,
            )
        )
    surname_offsets = {"williams": 1000, "johnson": 2000, "smith": 3000}
    for surname, offset in surname_offsets.items():
        for index in range(_FULL_SCOPE_HIGH_FREQUENCY_DONOR_COUNT):
            recipient = recipients[(index + offset) % len(recipients)]
            rows.append(
                _full_scope_transaction(
                    index=offset + index,
                    filing_id=filings[recipient.committee_id],
                    committee_id=recipient.committee_id,
                    source_record_id=source_records.current,
                    amount=Decimal("1.00"),
                    contributor_name_raw=f"{surname.upper()} COMMON DONOR {index:03d}",
                    contributor_employer="Common Surname Fixture",
                    contributor_zip=f"27{index % 1000:03d}",
                    recipient_candidate_id=recipient.candidate_id,
                    recipient_committee_id=recipient.committee_id,
                )
            )
    return rows


def _full_scope_transaction(
    *,
    index: int,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    amount: Decimal,
    contributor_name_raw: str,
    contributor_employer: str,
    contributor_zip: str,
    recipient_candidate_id: UUID | None,
    recipient_committee_id: UUID,
) -> TransactionRowSeed:
    return _transaction(
        _full_scope_uuid(9, index),
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=source_record_id,
        amount=amount,
        contributor_name_raw=contributor_name_raw,
        contributor_employer=contributor_employer,
        contributor_zip=contributor_zip,
        recipient_candidate_id=recipient_candidate_id,
        recipient_committee_id=recipient_committee_id,
        transaction_date=date(2025, 6, index % 27 + 1),
    )


def _full_scope_control_transaction(
    *,
    index: int,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    contributor_name_raw: str,
) -> TransactionRowSeed:
    return _full_scope_transaction(
        index=4000 + index,
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=source_record_id,
        amount=Decimal("99999.00"),
        contributor_name_raw=contributor_name_raw,
        contributor_employer="Control Fixture",
        contributor_zip="99999",
        recipient_candidate_id=None,
        recipient_committee_id=committee_id,
    )


def _seed_person(conn: psycopg.Connection, *, person_id: UUID, name: str) -> UUID:
    return insert_person(
        conn,
        Person(
            id=person_id,
            canonical_name=name,
            first_name=name.split()[0],
            last_name=name.split()[-1],
        ),
    )


def _seed_filing(
    conn: psycopg.Connection,
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
) -> UUID:
    insert_filing_row(
        conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id=f"FILING-{filing_id.hex}",
            committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
        ),
    )
    return filing_id


def _seed_base_transactions(
    conn: psycopg.Connection,
    *,
    recipients: DonorSearchRecipientScope,
    filings: DonorSearchFilingIds,
    source_records: DonorSearchSourceRecordIds,
) -> None:
    for row in _included_transactions(recipients, filings, source_records):
        insert_transaction_row(conn, row)
    for row in _excluded_transactions(recipients, filings, source_records):
        insert_transaction_row(conn, row)


def _included_transactions(
    recipients: DonorSearchRecipientScope,
    filings: DonorSearchFilingIds,
    source_records: DonorSearchSourceRecordIds,
) -> list[TransactionRowSeed]:
    return [
        _transaction(
            UUID("72000000-0000-0000-0000-000000000101"),
            filing_id=filings.alpha,
            committee_id=recipients.alpha.committee_id,
            source_record_id=source_records.current,
            amount=Decimal("300.00"),
            contributor_name_raw="JANE SMITH",
            contributor_employer="Civibus Labs",
            contributor_zip="27701-1234",
            recipient_candidate_id=recipients.alpha.candidate_id,
            recipient_committee_id=recipients.alpha.committee_id,
            transaction_date=date(2024, 6, 1),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000102"),
            filing_id=filings.beta,
            committee_id=recipients.beta.committee_id,
            source_record_id=source_records.secondary,
            amount=Decimal("125.00"),
            contributor_name_raw="JANE SMITH",
            contributor_employer="Civibus Labs",
            contributor_zip="27701-1234",
            recipient_candidate_id=recipients.beta.candidate_id,
            recipient_committee_id=recipients.beta.committee_id,
            transaction_date=date(2024, 7, 2),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000112"),
            filing_id=filings.alpha_second_committee,
            committee_id=recipients.alpha_second_committee.committee_id,
            source_record_id=source_records.current,
            amount=Decimal("75.00"),
            contributor_name_raw="JANE SMITH",
            contributor_employer="Civibus Labs",
            contributor_zip="27701-1234",
            recipient_candidate_id=recipients.alpha_second_committee.candidate_id,
            recipient_committee_id=recipients.alpha_second_committee.committee_id,
            transaction_date=date(2024, 7, 15),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000103"),
            filing_id=filings.alpha,
            committee_id=recipients.alpha.committee_id,
            source_record_id=source_records.current,
            amount=Decimal("425.00"),
            contributor_name_raw="JOHN SMITH",
            contributor_employer="Open City Works",
            contributor_zip="10001",
            recipient_candidate_id=recipients.alpha.candidate_id,
            recipient_committee_id=recipients.alpha.committee_id,
            transaction_date=date(2025, 1, 15),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000104"),
            filing_id=filings.alpha,
            committee_id=recipients.alpha.committee_id,
            source_record_id=source_records.current,
            amount=Decimal("250.00"),
            contributor_name_raw="PRIYA PATEL",
            contributor_employer="Civic Health",
            contributor_zip="60601-7777",
            recipient_candidate_id=recipients.alpha.candidate_id,
            recipient_committee_id=recipients.alpha.committee_id,
            transaction_date=date(2025, 2, 20),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000105"),
            filing_id=filings.beta,
            committee_id=recipients.beta.committee_id,
            source_record_id=source_records.secondary,
            amount=Decimal("90.00"),
            contributor_name_raw="ALICIA RIVERA",
            contributor_employer="ActBlue Technical Services",
            contributor_zip="02139",
            recipient_candidate_id=recipients.beta.candidate_id,
            recipient_committee_id=recipients.beta.committee_id,
            transaction_date=date(2025, 3, 10),
        ),
    ]


def _excluded_transactions(
    recipients: DonorSearchRecipientScope,
    filings: DonorSearchFilingIds,
    source_records: DonorSearchSourceRecordIds,
) -> list[TransactionRowSeed]:
    return [
        _transaction(
            UUID("72000000-0000-0000-0000-000000000106"),
            filing_id=filings.inactive,
            committee_id=recipients.inactive.committee_id,
            source_record_id=source_records.current,
            amount=Decimal("9999.00"),
            contributor_name_raw="JANE SMITH",
            contributor_employer="Civibus Labs",
            contributor_zip="27701-1234",
            recipient_candidate_id=recipients.inactive.candidate_id,
            recipient_committee_id=recipients.inactive.committee_id,
            transaction_date=date(2024, 8, 1),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000107"),
            filing_id=filings.alpha,
            committee_id=recipients.alpha.committee_id,
            source_record_id=source_records.current,
            amount=Decimal("9999.00"),
            contributor_name_raw="JANE SMITH",
            contributor_employer="Civibus Labs",
            contributor_zip="27701-1234",
            recipient_candidate_id=recipients.alpha.candidate_id,
            recipient_committee_id=recipients.alpha.committee_id,
            transaction_date=date(2024, 8, 2),
            contributor_entity_type="ORG",
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000108"),
            filing_id=filings.alpha,
            committee_id=recipients.alpha.committee_id,
            source_record_id=source_records.current,
            amount=Decimal("9999.00"),
            contributor_name_raw="JANE SMITH",
            contributor_employer="Civibus Labs",
            contributor_zip="27701-1234",
            recipient_candidate_id=recipients.alpha.candidate_id,
            recipient_committee_id=recipients.alpha.committee_id,
            transaction_date=date(2024, 8, 3),
            is_memo=True,
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000109"),
            filing_id=filings.alpha,
            committee_id=recipients.alpha.committee_id,
            source_record_id=source_records.current,
            amount=Decimal("9999.00"),
            contributor_name_raw="JANE SMITH",
            contributor_employer="Civibus Labs",
            contributor_zip="27701-1234",
            recipient_candidate_id=recipients.alpha.candidate_id,
            recipient_committee_id=recipients.alpha.committee_id,
            transaction_date=date(2024, 8, 4),
            amendment_indicator="T",
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000110"),
            filing_id=filings.alpha,
            committee_id=recipients.alpha.committee_id,
            source_record_id=source_records.current,
            amount=Decimal("9999.00"),
            contributor_name_raw="JANE SMITH",
            contributor_employer="Civibus Labs",
            contributor_zip="27701-1234",
            recipient_candidate_id=recipients.alpha.candidate_id,
            recipient_committee_id=recipients.alpha.committee_id,
            transaction_date=date(2021, 12, 31),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000111"),
            filing_id=filings.alpha,
            committee_id=recipients.alpha.committee_id,
            source_record_id=source_records.superseded,
            amount=Decimal("9999.00"),
            contributor_name_raw="JANE SMITH",
            contributor_employer="Civibus Labs",
            contributor_zip="27701-1234",
            recipient_candidate_id=recipients.alpha.candidate_id,
            recipient_committee_id=recipients.alpha.committee_id,
            transaction_date=date(2024, 8, 5),
        ),
    ]


def _transaction(
    transaction_id: UUID,
    *,
    transaction_type: str = "15",
    transaction_identifier: str | None = None,
    **transaction_values: object,
) -> TransactionRowSeed:
    seed_values = {
        "amendment_indicator": "N",
        "contributor_entity_type": "IND",
        "is_memo": False,
        **transaction_values,
    }
    return TransactionRowSeed(
        id=transaction_id,
        transaction_type=transaction_type,
        transaction_identifier=transaction_identifier or f"donor-search-{transaction_id.hex[-6:]}",
        contributor_occupation="Engineer",
        contributor_city="Durham",
        contributor_state="NC",
        **seed_values,
    )


def _seed_extra_smith_rows(
    conn: psycopg.Connection,
    *,
    alpha: DonorSearchRecipientIds,
    filing_alpha: UUID,
    source_record_id: UUID,
    count: int,
) -> None:
    for index in range(count):
        transaction_id = UUID(f"72000000-0000-0000-0001-{index + 1:012d}")
        insert_transaction_row(
            conn,
            _transaction(
                transaction_id,
                filing_id=filing_alpha,
                committee_id=alpha.committee_id,
                source_record_id=source_record_id,
                amount=Decimal("10.00"),
                contributor_name_raw=f"SMITH LIMIT {index:02d}",
                contributor_employer="Limit Fixture",
                contributor_zip="27701",
                recipient_candidate_id=alpha.candidate_id,
                recipient_committee_id=alpha.committee_id,
                transaction_date=date(2025, 4, 1),
            ),
        )


def _seed_ordering_tie_rows(
    conn: psycopg.Connection,
    *,
    alpha: DonorSearchRecipientIds,
    filing_alpha: UUID,
    source_record_id: UUID,
) -> None:
    rows = [
        _transaction(
            UUID("72000000-0000-0000-0000-000000000121"),
            filing_id=filing_alpha,
            committee_id=alpha.committee_id,
            source_record_id=source_record_id,
            amount=Decimal("30.00"),
            contributor_name_raw="ORDER SMITH COUNT",
            contributor_employer="Ordering Fixture",
            contributor_zip="27702",
            recipient_candidate_id=alpha.candidate_id,
            recipient_committee_id=alpha.committee_id,
            transaction_date=date(2025, 5, 1),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000122"),
            filing_id=filing_alpha,
            committee_id=alpha.committee_id,
            source_record_id=source_record_id,
            amount=Decimal("30.00"),
            contributor_name_raw="ORDER SMITH COUNT",
            contributor_employer="Ordering Fixture",
            contributor_zip="27702",
            recipient_candidate_id=alpha.candidate_id,
            recipient_committee_id=alpha.committee_id,
            transaction_date=date(2025, 5, 2),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000123"),
            filing_id=filing_alpha,
            committee_id=alpha.committee_id,
            source_record_id=source_record_id,
            amount=Decimal("60.00"),
            contributor_name_raw="ORDER SMITH ALPHA",
            contributor_employer="Ordering Fixture",
            contributor_zip="27703",
            recipient_candidate_id=alpha.candidate_id,
            recipient_committee_id=alpha.committee_id,
            transaction_date=date(2025, 5, 3),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000124"),
            filing_id=filing_alpha,
            committee_id=alpha.committee_id,
            source_record_id=source_record_id,
            amount=Decimal("60.00"),
            contributor_name_raw="ORDER SMITH BETA",
            contributor_employer="Ordering Fixture",
            contributor_zip="27704",
            recipient_candidate_id=alpha.candidate_id,
            recipient_committee_id=alpha.committee_id,
            transaction_date=date(2025, 5, 4),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000125"),
            filing_id=filing_alpha,
            committee_id=alpha.committee_id,
            source_record_id=source_record_id,
            amount=Decimal("40.00"),
            contributor_name_raw="ORDER SMITH STABLE",
            contributor_employer="Ordering Fixture A",
            contributor_zip="27705",
            recipient_candidate_id=alpha.candidate_id,
            recipient_committee_id=alpha.committee_id,
            transaction_date=date(2025, 5, 5),
        ),
        _transaction(
            UUID("72000000-0000-0000-0000-000000000126"),
            filing_id=filing_alpha,
            committee_id=alpha.committee_id,
            source_record_id=source_record_id,
            amount=Decimal("40.00"),
            contributor_name_raw="ORDER SMITH STABLE",
            contributor_employer="Ordering Fixture B",
            contributor_zip="27706",
            recipient_candidate_id=alpha.candidate_id,
            recipient_committee_id=alpha.committee_id,
            transaction_date=date(2025, 5, 6),
        ),
    ]
    for row in rows:
        insert_transaction_row(conn, row)


def main() -> None:
    with get_connection() as conn:
        with conn.transaction():
            fixture_ids = seed_donor_search_fixture(conn)
        print(f"seeded donor search fixture for {fixture_ids.alpha.person_id}")


if __name__ == "__main__":
    main()
