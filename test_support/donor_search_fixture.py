
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


def cleanup_donor_search_fixture(conn: psycopg.Connection) -> None:
    """Remove deterministic donor-search fixture rows before reseeding."""
    delete_statements = [
        "DELETE FROM cf.transaction WHERE transaction_identifier LIKE 'donor-search-%'",
        "DELETE FROM cf.filing WHERE id::text LIKE '72000000-%'",
        "DELETE FROM cf.candidate_committee_link WHERE id::text LIKE '72000000-%'",
        "DELETE FROM civic.officeholding WHERE id::text LIKE '72000000-%'",
        "DELETE FROM cf.candidate WHERE id::text LIKE '72000000-%'",
        "DELETE FROM cf.committee WHERE id::text LIKE '72000000-%'",
        "DELETE FROM civic.office WHERE id::text LIKE '72000000-%'",
        "DELETE FROM civic.electoral_division WHERE id::text LIKE '72000000-%'",
        "DELETE FROM core.person WHERE id::text LIKE '72000000-%'",
        "UPDATE core.source_record SET superseded_by = NULL WHERE source_record_key LIKE 'donor-search-%'",
        "DELETE FROM core.source_record WHERE source_record_key LIKE 'donor-search-%'",
        "DELETE FROM core.data_source WHERE domain = 'campaign_finance' AND jurisdiction = 'federal/fec' AND name = %s",
    ]
    for statement in delete_statements:
        params = (_DATA_SOURCE_NAME,) if "%s" in statement else None
        conn.execute(statement, params)


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
            filing_fec_id=f"FILING-{filing_id.hex[-6:]}",
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
        transaction_type="15",
        transaction_identifier=f"donor-search-{transaction_id.hex[-6:]}",
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
