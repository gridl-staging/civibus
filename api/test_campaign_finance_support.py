from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import psycopg

from core.db import insert_data_source, insert_source_record
from core.types.python.models import DataSource, SourceRecord, compute_record_hash

_COMMITTEE_INSERT_SQL = """
    INSERT INTO cf.committee (
        id,
        fec_committee_id,
        name,
        organization_id,
        source_record_id,
        committee_type,
        committee_designation,
        party,
        state,
        city,
        zip_code,
        treasurer_name
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_CANDIDATE_INSERT_SQL = """
    INSERT INTO cf.candidate (
        id,
        fec_candidate_id,
        name,
        office,
        person_id,
        principal_committee_id,
        source_record_id,
        party,
        state,
        district,
        incumbent_challenge,
        total_receipts,
        total_disbursements,
        cash_on_hand,
        candidate_contrib,
        candidate_loans,
        candidate_loan_repay,
        summary_coverage_end_date
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_FILING_INSERT_SQL = """
    INSERT INTO cf.filing (
        id,
        filing_fec_id,
        committee_id,
        candidate_id,
        report_type,
        amendment_indicator,
        filing_name,
        coverage_start_date,
        coverage_end_date,
        due_date,
        receipt_date,
        accepted_date,
        amended_from_filing_id,
        source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_TRANSACTION_INSERT_SQL = """
    INSERT INTO cf.transaction (
        id,
        filing_id,
        committee_id,
        transaction_type,
        source_record_id,
        transaction_identifier,
        transaction_date,
        amount,
        contributor_name_raw,
        contributor_entity_type,
        contributor_employer,
        contributor_occupation,
        contributor_city,
        contributor_state,
        contributor_zip,
        contributor_person_id,
        contributor_organization_id,
        contributor_address_id,
        recipient_candidate_id,
        recipient_committee_id,
        memo_code,
        memo_text,
        is_memo,
        amendment_indicator,
        date_is_reliable,
        support_oppose,
        dissemination_date,
        aggregate_amount
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_CANDIDATE_COMMITTEE_LINK_INSERT_SQL = """
    INSERT INTO cf.candidate_committee_link (
        id,
        candidate_id,
        committee_id,
        designation,
        candidate_election_year,
        fec_election_year,
        valid_period,
        source_record_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s::daterange, %s)
"""

_COMMITTEE_SUMMARY_INSERT_SQL = """
    INSERT INTO cf.committee_summary (
        committee_id,
        cycle,
        total_receipts,
        total_disbursements,
        cash_on_hand,
        individual_contributions,
        party_committee_contributions,
        other_committee_contributions,
        transfers_from_other_authorized_committees,
        debts_owed_by_committee,
        individual_itemized_contributions,
        individual_unitemized_contributions,
        candidate_contributions,
        candidate_loans,
        coverage_start_date,
        coverage_end_date
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

_ELECTORAL_DIVISION_INSERT_SQL = """
    INSERT INTO civic.electoral_division (
        id,
        name,
        division_type,
        state,
        district_number
    )
    VALUES (%s, %s, %s, %s, %s)
"""

_OFFICE_INSERT_SQL = """
    INSERT INTO civic.office (
        id,
        name,
        office_level,
        title,
        state,
        electoral_division_id
    )
    VALUES (%s, %s, %s, %s, %s, %s)
"""

_OFFICEHOLDING_INSERT_SQL = """
    INSERT INTO civic.officeholding (
        id,
        person_id,
        office_id,
        electoral_division_id,
        valid_period
    )
    VALUES (%s, %s, %s, %s, %s::daterange)
"""

_ZCTA_DISTRICT_INSERT_SQL = """
    INSERT INTO civic.zcta_district (
        zcta5,
        boundary_year,
        state_fips,
        cd_geoid,
        district_number,
        land_share,
        source_url
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class CommitteeRowSeed:
    id: UUID
    fec_committee_id: str
    name: str
    organization_id: UUID | None = None
    source_record_id: UUID | None = None
    committee_type: str | None = None
    committee_designation: str | None = None
    party: str | None = None
    state: str | None = None
    city: str | None = None
    zip_code: str | None = None
    treasurer_name: str | None = None


@dataclass(frozen=True)
class CandidateRowSeed:
    id: UUID
    fec_candidate_id: str
    name: str
    office: str
    person_id: UUID | None = None
    principal_committee_id: UUID | None = None
    source_record_id: UUID | None = None
    party: str | None = None
    state: str | None = None
    district: str | None = None
    incumbent_challenge: str | None = None
    total_receipts: Decimal | None = None
    total_disbursements: Decimal | None = None
    cash_on_hand: Decimal | None = None
    candidate_contrib: Decimal | None = None
    candidate_loans: Decimal | None = None
    candidate_loan_repay: Decimal | None = None
    summary_coverage_end_date: date | None = None


@dataclass(frozen=True)
class CommitteeSummaryRowSeed:
    committee_id: UUID
    cycle: int
    total_receipts: Decimal | None = None
    total_disbursements: Decimal | None = None
    cash_on_hand: Decimal | None = None
    individual_contributions: Decimal | None = None
    party_committee_contributions: Decimal | None = None
    other_committee_contributions: Decimal | None = None
    transfers_from_other_authorized_committees: Decimal | None = None
    debts_owed_by_committee: Decimal | None = None
    individual_itemized_contributions: Decimal | None = None
    individual_unitemized_contributions: Decimal | None = None
    candidate_contributions: Decimal | None = None
    candidate_loans: Decimal | None = None
    coverage_start_date: date | None = None
    coverage_end_date: date | None = None


@dataclass(frozen=True)
class CandidateCommitteeLinkSeed:
    id: UUID
    candidate_id: UUID
    committee_id: UUID
    valid_period: str
    designation: str | None = None
    source_record_id: UUID | None = None
    candidate_election_year: int | None = None
    fec_election_year: int | None = None


@dataclass(frozen=True)
class FilingRowSeed:
    id: UUID
    filing_fec_id: str
    committee_id: UUID
    candidate_id: UUID | None = None
    report_type: str | None = None
    amendment_indicator: str = "N"
    filing_name: str | None = None
    coverage_start_date: date | None = None
    coverage_end_date: date | None = None
    due_date: date | None = None
    receipt_date: date | None = None
    accepted_date: date | None = None
    amended_from_filing_id: UUID | None = None
    source_record_id: UUID | None = None


@dataclass(frozen=True)
class TransactionRowSeed:
    id: UUID
    filing_id: UUID
    committee_id: UUID
    transaction_type: str
    amount: Decimal
    amendment_indicator: str
    source_record_id: UUID | None = None
    transaction_identifier: str | None = None
    transaction_date: date | None = None
    contributor_name_raw: str | None = None
    contributor_entity_type: str | None = None
    contributor_employer: str | None = None
    contributor_occupation: str | None = None
    contributor_city: str | None = None
    contributor_state: str | None = None
    contributor_zip: str | None = None
    contributor_person_id: UUID | None = None
    contributor_organization_id: UUID | None = None
    contributor_address_id: UUID | None = None
    recipient_candidate_id: UUID | None = None
    recipient_committee_id: UUID | None = None
    memo_code: str | None = None
    memo_text: str | None = None
    is_memo: bool = False
    date_is_reliable: bool = True
    support_oppose: str | None = None
    dissemination_date: date | None = None
    aggregate_amount: Decimal | None = None


@dataclass(frozen=True)
class TransactionFilterSeedContext:
    committee_a: UUID
    committee_b: UUID
    filing_a: UUID
    filing_b: UUID
    source_record_co_one: UUID
    source_record_nc: UUID
    source_record_co_two: UUID


def _execute_insert(conn: psycopg.Connection, *, query: str, params: tuple[object, ...]) -> None:
    with conn.cursor() as cursor:
        cursor.execute(query, params)


def _summary_filing_id(committee_id: UUID) -> UUID:
    return UUID(f"20000000-0000-0000-0000-{committee_id.hex[:12]}")


def _resolve_memo_code(*, is_memo: bool, memo_code: str | None) -> str | None:
    return memo_code if memo_code is not None else ("X" if is_memo else None)


def _build_transaction_seed(
    *,
    transaction_id: UUID,
    filing_id: UUID,
    committee_id: UUID,
    transaction_type: str,
    amount: Decimal,
    amendment_indicator: str,
    source_record_id: UUID | None = None,
    is_memo: bool = False,
    transaction_date: date | None = None,
    transaction_identifier: str | None = None,
    memo_code: str | None = None,
    recipient_candidate_id: UUID | None = None,
    support_oppose: str | None = None,
    dissemination_date: date | None = None,
    aggregate_amount: Decimal | None = None,
) -> TransactionRowSeed:
    return TransactionRowSeed(
        id=transaction_id,
        filing_id=filing_id,
        committee_id=committee_id,
        transaction_type=transaction_type,
        amount=amount,
        amendment_indicator=amendment_indicator,
        source_record_id=source_record_id,
        is_memo=is_memo,
        transaction_date=transaction_date,
        transaction_identifier=transaction_identifier,
        memo_code=_resolve_memo_code(is_memo=is_memo, memo_code=memo_code),
        recipient_candidate_id=recipient_candidate_id,
        support_oppose=support_oppose,
        dissemination_date=dissemination_date,
        aggregate_amount=aggregate_amount,
    )


def insert_data_source_for_test(
    db_conn: psycopg.Connection,
    *,
    jurisdiction: str,
    name_suffix: str,
) -> DataSource:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name=f"Campaign Finance API Source {name_suffix}",
        source_url="https://example.org/campaign-finance-source",
    )
    insert_data_source(db_conn, data_source)
    return data_source


def insert_source_record_for_test(
    db_conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_source_id: UUID,
    source_record_key: str,
    source_url: str,
    pull_date: datetime,
    superseded_by: UUID | None = None,
) -> SourceRecord:
    raw_fields = {"source_record_key": source_record_key}
    source_record = SourceRecord(
        id=source_record_id,
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        source_url=source_url,
        raw_fields=raw_fields,
        pull_date=pull_date,
        record_hash=compute_record_hash(raw_fields),
        superseded_by=superseded_by,
    )
    insert_source_record(db_conn, source_record)
    return source_record


def insert_committee_row(conn: psycopg.Connection, committee: CommitteeRowSeed) -> None:
    _execute_insert(
        conn,
        query=_COMMITTEE_INSERT_SQL,
        params=(
            committee.id,
            committee.fec_committee_id,
            committee.name,
            committee.organization_id,
            committee.source_record_id,
            committee.committee_type,
            committee.committee_designation,
            committee.party,
            committee.state,
            committee.city,
            committee.zip_code,
            committee.treasurer_name,
        ),
    )


def insert_candidate_row(conn: psycopg.Connection, candidate: CandidateRowSeed) -> None:
    _execute_insert(
        conn,
        query=_CANDIDATE_INSERT_SQL,
        params=(
            candidate.id,
            candidate.fec_candidate_id,
            candidate.name,
            candidate.office,
            candidate.person_id,
            candidate.principal_committee_id,
            candidate.source_record_id,
            candidate.party,
            candidate.state,
            candidate.district,
            candidate.incumbent_challenge,
            candidate.total_receipts,
            candidate.total_disbursements,
            candidate.cash_on_hand,
            candidate.candidate_contrib,
            candidate.candidate_loans,
            candidate.candidate_loan_repay,
            candidate.summary_coverage_end_date,
        ),
    )


def insert_committee_summary_row(conn: psycopg.Connection, summary: CommitteeSummaryRowSeed) -> None:
    _execute_insert(
        conn,
        query=_COMMITTEE_SUMMARY_INSERT_SQL,
        params=(
            summary.committee_id,
            summary.cycle,
            summary.total_receipts,
            summary.total_disbursements,
            summary.cash_on_hand,
            summary.individual_contributions,
            summary.party_committee_contributions,
            summary.other_committee_contributions,
            summary.transfers_from_other_authorized_committees,
            summary.debts_owed_by_committee,
            summary.individual_itemized_contributions,
            summary.individual_unitemized_contributions,
            summary.candidate_contributions,
            summary.candidate_loans,
            summary.coverage_start_date,
            summary.coverage_end_date,
        ),
    )


def insert_candidate_committee_link_row(
    conn: psycopg.Connection,
    link: CandidateCommitteeLinkSeed,
) -> None:
    _execute_insert(
        conn,
        query=_CANDIDATE_COMMITTEE_LINK_INSERT_SQL,
        params=(
            link.id,
            link.candidate_id,
            link.committee_id,
            link.designation,
            link.candidate_election_year,
            link.fec_election_year,
            link.valid_period,
            link.source_record_id,
        ),
    )


def insert_filing_row(conn: psycopg.Connection, filing: FilingRowSeed) -> None:
    _execute_insert(
        conn,
        query=_FILING_INSERT_SQL,
        params=(
            filing.id,
            filing.filing_fec_id,
            filing.committee_id,
            filing.candidate_id,
            filing.report_type,
            filing.amendment_indicator,
            filing.filing_name,
            filing.coverage_start_date,
            filing.coverage_end_date,
            filing.due_date,
            filing.receipt_date,
            filing.accepted_date,
            filing.amended_from_filing_id,
            filing.source_record_id,
        ),
    )


def insert_transaction_row(conn: psycopg.Connection, transaction: TransactionRowSeed) -> None:
    _execute_insert(
        conn,
        query=_TRANSACTION_INSERT_SQL,
        params=(
            transaction.id,
            transaction.filing_id,
            transaction.committee_id,
            transaction.transaction_type,
            transaction.source_record_id,
            transaction.transaction_identifier,
            transaction.transaction_date,
            transaction.amount,
            transaction.contributor_name_raw,
            transaction.contributor_entity_type,
            transaction.contributor_employer,
            transaction.contributor_occupation,
            transaction.contributor_city,
            transaction.contributor_state,
            transaction.contributor_zip,
            transaction.contributor_person_id,
            transaction.contributor_organization_id,
            transaction.contributor_address_id,
            transaction.recipient_candidate_id,
            transaction.recipient_committee_id,
            _resolve_memo_code(is_memo=transaction.is_memo, memo_code=transaction.memo_code),
            transaction.memo_text,
            transaction.is_memo,
            transaction.amendment_indicator,
            transaction.date_is_reliable,
            transaction.support_oppose,
            transaction.dissemination_date,
            transaction.aggregate_amount,
        ),
    )


def insert_electoral_division_row(
    conn: psycopg.Connection,
    *,
    division_id: UUID,
    name: str,
    division_type: str,
    state: str | None,
    district_number: str | None,
) -> None:
    _execute_insert(
        conn,
        query=_ELECTORAL_DIVISION_INSERT_SQL,
        params=(division_id, name, division_type, state, district_number),
    )


def insert_office_row(
    conn: psycopg.Connection,
    *,
    office_id: UUID,
    name: str,
    title: str,
    state: str | None,
    electoral_division_id: UUID | None,
) -> None:
    _execute_insert(
        conn,
        query=_OFFICE_INSERT_SQL,
        params=(office_id, name, "federal", title, state, electoral_division_id),
    )


def insert_officeholding_row(
    conn: psycopg.Connection,
    *,
    officeholding_id: UUID,
    person_id: UUID,
    office_id: UUID,
    electoral_division_id: UUID | None,
    valid_period: str = "[2000-01-01,2100-01-01)",
) -> None:
    _execute_insert(
        conn,
        query=_OFFICEHOLDING_INSERT_SQL,
        params=(officeholding_id, person_id, office_id, electoral_division_id, valid_period),
    )


def insert_zcta_district_row(
    conn: psycopg.Connection,
    *,
    zcta5: str,
    state_fips: str,
    cd_geoid: str,
    district_number: str,
    boundary_year: int = 2022,
    land_share: Decimal = Decimal("1.00000"),
) -> None:
    _execute_insert(
        conn,
        query=_ZCTA_DISTRICT_INSERT_SQL,
        params=(zcta5, boundary_year, state_fips, cd_geoid, district_number, land_share, "https://example.org/zcta"),
    )


def _seed_transaction_filter_context(db_conn: psycopg.Connection) -> TransactionFilterSeedContext:
    committee_a = UUID("00000000-0000-0000-0000-000000000951")
    committee_b = UUID("00000000-0000-0000-0000-000000000952")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_a,
            fec_committee_id="C12345682",
            name="Committee A",
            state="NC",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_b,
            fec_committee_id="C12345683",
            name="Committee B",
            state="CO",
        ),
    )

    filing_a = UUID("00000000-0000-0000-0000-000000000953")
    filing_b = UUID("00000000-0000-0000-0000-000000000954")
    insert_filing_row(
        db_conn,
        FilingRowSeed(id=filing_a, filing_fec_id="api-transactions-filing-a", committee_id=committee_a),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(id=filing_b, filing_fec_id="api-transactions-filing-b", committee_id=committee_b),
    )

    data_source_co = insert_data_source_for_test(db_conn, jurisdiction="state/co", name_suffix="transactions-co")
    data_source_nc = insert_data_source_for_test(db_conn, jurisdiction="state/nc", name_suffix="transactions-nc")
    source_record_co_one = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000955"),
        data_source_id=data_source_co.id,
        source_record_key="txn-co-one",
        source_url="https://example.org/record/txn-co-one",
        pull_date=datetime(2026, 3, 16, 7, 0, tzinfo=timezone.utc),
    )
    source_record_nc = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000956"),
        data_source_id=data_source_nc.id,
        source_record_key="txn-nc-one",
        source_url="https://example.org/record/txn-nc-one",
        pull_date=datetime(2026, 3, 16, 7, 0, tzinfo=timezone.utc),
    )
    source_record_co_two = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000957"),
        data_source_id=data_source_co.id,
        source_record_key="txn-co-two",
        source_url="https://example.org/record/txn-co-two",
        pull_date=datetime(2026, 3, 15, 7, 0, tzinfo=timezone.utc),
    )

    return TransactionFilterSeedContext(
        committee_a=committee_a,
        committee_b=committee_b,
        filing_a=filing_a,
        filing_b=filing_b,
        source_record_co_one=source_record_co_one.id,
        source_record_nc=source_record_nc.id,
        source_record_co_two=source_record_co_two.id,
    )


def _insert_filter_transactions(
    db_conn: psycopg.Connection,
    context: TransactionFilterSeedContext,
) -> dict[str, UUID]:
    transaction_a = UUID("00000000-0000-0000-0000-000000000961")
    transaction_b = UUID("00000000-0000-0000-0000-000000000962")
    transaction_c = UUID("00000000-0000-0000-0000-000000000963")
    transaction_d = UUID("00000000-0000-0000-0000-000000000964")

    # Transaction A has IE fields populated to prove the API surfaces them
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=transaction_a,
            filing_id=context.filing_a,
            committee_id=context.committee_a,
            transaction_type="24E",
            amount=Decimal("110.00"),
            amendment_indicator="N",
            source_record_id=context.source_record_co_one,
            transaction_identifier="txn-a",
            transaction_date=date(2026, 3, 15),
            contributor_name_raw="Donor A",
            support_oppose="O",
            dissemination_date=date(2026, 3, 10),
            aggregate_amount=Decimal("5000.00"),
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=transaction_b,
            filing_id=context.filing_b,
            committee_id=context.committee_b,
            transaction_type="15",
            amount=Decimal("210.00"),
            amendment_indicator="N",
            source_record_id=context.source_record_nc,
            transaction_identifier="txn-b",
            transaction_date=date(2026, 3, 15),
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=transaction_c,
            filing_id=context.filing_a,
            committee_id=context.committee_a,
            transaction_type="15",
            amount=Decimal("90.00"),
            amendment_indicator="N",
            source_record_id=context.source_record_co_two,
            transaction_identifier="txn-c",
            transaction_date=date(2026, 3, 14),
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=transaction_d,
            filing_id=context.filing_a,
            committee_id=context.committee_a,
            transaction_type="15",
            amount=Decimal("70.00"),
            amendment_indicator="N",
            source_record_id=None,
            transaction_identifier="txn-d",
            transaction_date=date(2026, 3, 14),
        ),
    )

    return {
        "transaction_a": transaction_a,
        "transaction_b": transaction_b,
        "transaction_c": transaction_c,
        "transaction_d": transaction_d,
    }


def seed_transactions_for_filters(db_conn: psycopg.Connection) -> dict[str, UUID]:
    context = _seed_transaction_filter_context(db_conn)
    transaction_ids = _insert_filter_transactions(db_conn, context)
    return {
        "committee_a": context.committee_a,
        "committee_b": context.committee_b,
        **transaction_ids,
    }


@dataclass(frozen=True)
class SummaryTestContext:
    """Seed data IDs for committee summary aggregation tests."""

    committee_id: UUID
    committee_name: str
    data_source_id: UUID
    source_record_id: UUID
    data_source_jurisdiction: str
    pull_date: datetime


@dataclass(frozen=True)
class FilingBreakdownTestContext:
    """Seed data IDs for committee filing-breakdown aggregation tests."""

    committee_id: UUID
    committee_name: str


@dataclass(frozen=True)
class CountySummaryFixtureContext:
    """Seed ids for county campaign-finance summary tests."""

    committee_id: UUID
    recipient_committee_id: UUID
    candidate_id: UUID
    filing_id: UUID


@dataclass(frozen=True)
class CountySummaryRecipientContext:
    """Recipient committee + linked candidate for county summary fixtures."""

    recipient_committee_id: UUID
    candidate_id: UUID


def seed_committee_for_filing_breakdown(
    db_conn: psycopg.Connection,
    *,
    committee_id: UUID,
    committee_name: str = "Filing Breakdown Committee",
    fec_committee_id: str = "C99992001",
) -> FilingBreakdownTestContext:
    """Create a committee row for filing-breakdown tests."""
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id=fec_committee_id,
            name=committee_name,
        ),
    )
    return FilingBreakdownTestContext(
        committee_id=committee_id,
        committee_name=committee_name,
    )


def seed_committee_for_summary(
    db_conn: psycopg.Connection,
    *,
    committee_id: UUID,
    committee_name: str = "Summary Test Committee",
    fec_committee_id: str = "C99990001",
    state: str | None = None,
    jurisdiction: str = "federal/fec",
    pull_date: datetime = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
) -> SummaryTestContext:
    """Create a committee with provenance chain (data_source + source_record + filing).

    Returns context for inserting transactions against this committee.
    """
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_id, fec_committee_id=fec_committee_id, name=committee_name, state=state),
    )

    data_source = insert_data_source_for_test(db_conn, jurisdiction=jurisdiction, name_suffix=f"summary-{committee_id}")
    source_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID(f"10000000-0000-0000-0000-{committee_id.hex[:12]}"),
        data_source_id=data_source.id,
        source_record_key=f"summary-sr-{committee_id}",
        source_url=f"https://example.org/record/summary-{committee_id}",
        pull_date=pull_date,
    )

    filing_id = _summary_filing_id(committee_id)
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id=f"summary-filing-{committee_id}",
            committee_id=committee_id,
            source_record_id=source_record.id,
        ),
    )

    return SummaryTestContext(
        committee_id=committee_id,
        committee_name=committee_name,
        data_source_id=data_source.id,
        source_record_id=source_record.id,
        data_source_jurisdiction=jurisdiction,
        pull_date=pull_date,
    )


def seed_county_summary_fixture(
    db_conn: psycopg.Connection,
    *,
    committee_id: UUID,
    committee_name: str,
    recipient_committee_id: UUID,
    recipient_committee_name: str,
    candidate_id: UUID,
    candidate_name: str,
) -> CountySummaryFixtureContext:
    """Seed committee/candidate linkage for county-summary route tests."""
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C99991001",
            name=committee_name,
            state="NC",
            city="Raleigh",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=recipient_committee_id,
            fec_committee_id="C99991002",
            name=recipient_committee_name,
            state="NC",
            city="Raleigh",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC09999",
            name=candidate_name,
            office="H",
            state="NC",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("30000000-0000-0000-0000-000000000001"),
            candidate_id=candidate_id,
            committee_id=recipient_committee_id,
            valid_period="[2024-01-01,2030-01-01)",
        ),
    )
    filing_id = _summary_filing_id(committee_id)
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id=f"county-summary-filing-{committee_id}",
            committee_id=committee_id,
        ),
    )
    return CountySummaryFixtureContext(
        committee_id=committee_id,
        recipient_committee_id=recipient_committee_id,
        candidate_id=candidate_id,
        filing_id=filing_id,
    )


def seed_county_summary_recipient(
    db_conn: psycopg.Connection,
    *,
    recipient_committee_id: UUID,
    recipient_committee_name: str,
    recipient_committee_fec_id: str,
    candidate_id: UUID,
    candidate_name: str,
    candidate_fec_id: str,
    link_id: UUID,
) -> CountySummaryRecipientContext:
    """Seed one recipient committee and active candidate link for county summary tests."""
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=recipient_committee_id,
            fec_committee_id=recipient_committee_fec_id,
            name=recipient_committee_name,
            state="NC",
            city="Raleigh",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id=candidate_fec_id,
            name=candidate_name,
            office="H",
            state="NC",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=link_id,
            candidate_id=candidate_id,
            committee_id=recipient_committee_id,
            valid_period="[2024-01-01,2030-01-01)",
        ),
    )
    return CountySummaryRecipientContext(
        recipient_committee_id=recipient_committee_id,
        candidate_id=candidate_id,
    )


def insert_summary_transaction(
    db_conn: psycopg.Connection,
    *,
    context: SummaryTestContext,
    transaction_id: UUID,
    transaction_type: str,
    amount: Decimal,
    source_record_id: UUID | None = None,
    is_memo: bool = False,
    transaction_date: date | None = date(2026, 3, 15),
    memo_code: str | None = None,
    amendment_indicator: str = "N",
    recipient_candidate_id: UUID | None = None,
    support_oppose: str | None = None,
    dissemination_date: date | None = None,
    aggregate_amount: Decimal | None = None,
) -> None:
    """Insert a transaction for summary testing with sensible defaults."""
    insert_transaction_row(
        db_conn,
        _build_transaction_seed(
            transaction_id=transaction_id,
            filing_id=_summary_filing_id(context.committee_id),
            committee_id=context.committee_id,
            transaction_type=transaction_type,
            amount=amount,
            amendment_indicator=amendment_indicator,
            source_record_id=source_record_id,
            is_memo=is_memo,
            transaction_date=transaction_date,
            memo_code=memo_code,
            recipient_candidate_id=recipient_candidate_id,
            support_oppose=support_oppose,
            dissemination_date=dissemination_date,
            aggregate_amount=aggregate_amount,
        ),
    )


def insert_filing_breakdown_transaction(
    db_conn: psycopg.Connection,
    *,
    committee_id: UUID,
    filing_id: UUID,
    transaction_id: UUID,
    transaction_type: str,
    amount: Decimal,
    source_record_id: UUID | None = None,
    is_memo: bool = False,
    amendment_indicator: str = "N",
    transaction_identifier: str | None = None,
    memo_code: str | None = None,
) -> None:
    """Insert a transaction tied to a specific filing for breakdown tests."""
    insert_transaction_row(
        db_conn,
        _build_transaction_seed(
            transaction_id=transaction_id,
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=transaction_type,
            amount=amount,
            amendment_indicator=amendment_indicator,
            source_record_id=source_record_id,
            is_memo=is_memo,
            transaction_identifier=transaction_identifier,
            memo_code=memo_code,
        ),
    )
