from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.pq import TransactionStatus

from core.db import (
    insert_data_source,
    insert_entity_source,
    insert_organization,
    insert_person,
    insert_source_record,
)
from core.entity_resolution.l8_regression import _normalize_address
from core.types.python.models import (
    DataSource,
    Organization,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from core.entity_resolution.transaction_counterparty_resolver import (
    resolve_nc_transaction_counterparties,
)


pytestmark = pytest.mark.integration

_TEST_DATA_SOURCE_PREFIX = "Test NC Counterparty Resolver Source "
_TEST_SOURCE_RECORD_PREFIX = "test-nc-counterparty-resolver-source-record-"
_TEST_TRANSACTION_PREFIX = "test-nc-counterparty-resolver-transaction-"
_TEST_ADDRESS_PREFIX = "TEST NC COUNTERPARTY RESOLVER ADDRESS "
_TEST_COMMITTEE_PREFIX = "Test NC Counterparty Resolver Committee "
_TEST_FILING_PREFIX = "test-nc-counterparty-resolver-filing-"
_TEST_SUB_ID_BASE = 970_000_000_000_000_000


@pytest.fixture(autouse=True)
def _cleanup_test_rows(db_conn: psycopg.Connection) -> None:
    yield
    if db_conn.info.transaction_status == TransactionStatus.INERROR:
        db_conn.rollback()

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM cf.transaction
            WHERE transaction_identifier LIKE %s
               OR (sub_id IS NOT NULL AND sub_id >= %s)
            """,
            (f"{_TEST_TRANSACTION_PREFIX}%", _TEST_SUB_ID_BASE),
        )
        cursor.execute(
            """
            DELETE FROM core.entity_address
            WHERE entity_type = 'person'
              AND entity_id IN (
                SELECT es.entity_id
                FROM core.entity_source es
                JOIN core.source_record sr ON sr.id = es.source_record_id
                WHERE sr.source_record_key LIKE %s
                  AND es.entity_type = 'person'
              )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.entity_address
            WHERE entity_type = 'organization'
              AND entity_id IN (
                SELECT es.entity_id
                FROM core.entity_source es
                JOIN core.source_record sr ON sr.id = es.source_record_id
                WHERE sr.source_record_key LIKE %s
                  AND es.entity_type = 'organization'
              )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.person
            WHERE id IN (
                SELECT es.entity_id
                FROM core.entity_source es
                JOIN core.source_record sr ON sr.id = es.source_record_id
                WHERE sr.source_record_key LIKE %s
                  AND es.entity_type = 'person'
            )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.organization
            WHERE id IN (
                SELECT es.entity_id
                FROM core.entity_source es
                JOIN core.source_record sr ON sr.id = es.source_record_id
                WHERE sr.source_record_key LIKE %s
                  AND es.entity_type = 'organization'
            )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM core.entity_source
            WHERE source_record_id IN (
                SELECT id
                FROM core.source_record
                WHERE source_record_key LIKE %s
            )
            """,
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute("DELETE FROM cf.filing WHERE filing_fec_id LIKE %s", (f"{_TEST_FILING_PREFIX}%",))
        cursor.execute("DELETE FROM cf.committee WHERE name LIKE %s", (f"{_TEST_COMMITTEE_PREFIX}%",))
        cursor.execute(
            "DELETE FROM core.address WHERE normalized_address LIKE %s",
            (f"{_TEST_ADDRESS_PREFIX}%",),
        )
        cursor.execute(
            "DELETE FROM core.source_record WHERE source_record_key LIKE %s",
            (f"{_TEST_SOURCE_RECORD_PREFIX}%",),
        )
        cursor.execute("DELETE FROM core.data_source WHERE name LIKE %s", (f"{_TEST_DATA_SOURCE_PREFIX}%",))


def _insert_test_committee(conn: psycopg.Connection, label: str) -> UUID:
    committee_fec_id = f"C{uuid4().int % 100_000_000:08d}"
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.committee (fec_committee_id, name)
            VALUES (%s, %s)
            RETURNING id
            """,
            (committee_fec_id, f"{_TEST_COMMITTEE_PREFIX}{label}"),
        )
        return cursor.fetchone()[0]


def _insert_test_filing(conn: psycopg.Connection, committee_id: UUID, label: str) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.filing (filing_fec_id, committee_id, amendment_indicator)
            VALUES (%s, %s, 'N')
            RETURNING id
            """,
            (f"{_TEST_FILING_PREFIX}{label}", committee_id),
        )
        return cursor.fetchone()[0]


def _insert_test_source_record(
    conn: psycopg.Connection,
    *,
    label: str,
    raw_fields: dict[str, object],
    jurisdiction: str = "state/NC",
) -> UUID:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name=f"{_TEST_DATA_SOURCE_PREFIX}{label}",
        source_url="https://example.test/nc-counterparty-resolver",
    )
    insert_data_source(conn, data_source)
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"{_TEST_SOURCE_RECORD_PREFIX}{label}",
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    insert_source_record(conn, source_record)
    return source_record.id


def _build_nc_transaction_raw_fields(
    *,
    name: str,
    street_line_1: str,
    city: str,
    state: str,
    zip_code: str,
    occupation: str = "Legislator",
    employer_or_business: str = "NC House",
    transaction_type: str | None = None,
) -> dict[str, str]:
    prefixed_street_line_1 = f"{_TEST_ADDRESS_PREFIX}{street_line_1}"
    raw_fields = {
        "Name": name,
        "Street Line 1": prefixed_street_line_1,
        "Street Line 2": "",
        "City": city,
        "State": state,
        "Zip Code": zip_code,
        "Profession/Job Title": occupation,
        "Employer's Name/Specific Field": employer_or_business,
    }
    if transaction_type is not None:
        raw_fields["Transction Type"] = transaction_type
    return raw_fields


def _insert_address_and_link(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    entity_id: UUID,
    normalized_address: str,
    state: str,
    zip5: str,
) -> None:
    normalized_value = _normalize_address(normalized_address)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.address (id, raw_address, normalized_address, street_number, state, zip5)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (normalized_address) WHERE normalized_address IS NOT NULL
            DO UPDATE SET
                raw_address = EXCLUDED.raw_address,
                street_number = EXCLUDED.street_number,
                state = EXCLUDED.state,
                zip5 = EXCLUDED.zip5
            RETURNING id
            """,
            (uuid4(), normalized_value, normalized_value, "123", state, zip5),
        )
        address_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO core.entity_address (entity_type, entity_id, address_id, address_role, valid_period)
            VALUES (%s, %s, %s, 'mailing', daterange('2024-01-01', NULL, '[)'))
            """,
            (entity_type, entity_id, address_id),
        )


def _insert_person_candidate(
    conn: psycopg.Connection,
    *,
    label: str,
    canonical_name: str,
    identifier_key: str,
    normalized_address: str,
    zip5: str,
) -> UUID:
    first_name, last_name = canonical_name.split(" ", 1)
    person_id = insert_person(
        conn,
        Person(
            canonical_name=canonical_name,
            first_name=first_name,
            last_name=last_name,
            identifiers={
                "voter_reg_id": identifier_key.split(":", 1)[1],
                "employer": "NC House",
                "occupation": "Legislator",
            },
        ),
    )
    _insert_address_and_link(
        conn,
        entity_type="person",
        entity_id=person_id,
        normalized_address=f"{_TEST_ADDRESS_PREFIX}{normalized_address}",
        state="NC",
        zip5=zip5,
    )
    return person_id


def _insert_organization_candidate(
    conn: psycopg.Connection,
    *,
    canonical_name: str,
    ein: str,
    normalized_address: str,
    zip5: str,
) -> UUID:
    organization_id = insert_organization(
        conn,
        Organization(
            canonical_name=canonical_name,
            registered_state="NC",
            identifiers={"ein": ein},
        ),
    )
    _insert_address_and_link(
        conn,
        entity_type="organization",
        entity_id=organization_id,
        normalized_address=f"{_TEST_ADDRESS_PREFIX}{normalized_address}",
        state="NC",
        zip5=zip5,
    )
    return organization_id


def _insert_transaction(
    conn: psycopg.Connection,
    *,
    label: str,
    source_record_id: UUID,
    contributor_name_raw: str,
    contributor_state: str,
    contributor_zip: str,
    contributor_city: str = "Raleigh",
    contributor_employer: str = "NC House",
    contributor_occupation: str = "Legislator",
    transaction_type: str = "15",
) -> UUID:
    committee_id = _insert_test_committee(conn, label)
    filing_id = _insert_test_filing(conn, committee_id, label)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.transaction (
                filing_id,
                committee_id,
                transaction_type,
                transaction_identifier,
                sub_id,
                amount,
                contributor_name_raw,
                contributor_employer,
                contributor_occupation,
                contributor_city,
                contributor_state,
                contributor_zip,
                amendment_indicator,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'N', %s)
            RETURNING id
            """,
            (
                filing_id,
                committee_id,
                transaction_type,
                f"{_TEST_TRANSACTION_PREFIX}{label}",
                _TEST_SUB_ID_BASE + int(label[-3:]),
                Decimal("100.00"),
                contributor_name_raw,
                contributor_employer,
                contributor_occupation,
                contributor_city,
                contributor_state,
                contributor_zip,
                source_record_id,
            ),
        )
        return cursor.fetchone()[0]


def _select_transaction_identity_snapshot(
    conn: psycopg.Connection,
    transaction_ids: list[UUID],
) -> list[tuple[UUID, UUID | None, UUID | None, object]]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, contributor_person_id, contributor_organization_id, updated_at
            FROM cf.transaction
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (transaction_ids,),
        )
        return list(cursor.fetchall())


def _seed_resolver_fixture(
    db_conn: psycopg.Connection,
) -> tuple[dict[str, UUID], dict[str, UUID]]:
    donor_source_record_id = _insert_test_source_record(
        db_conn,
        label="donor-julia-howard",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Julia Howard",
            street_line_1="123 Main Street",
            city="Raleigh",
            state="NC",
            zip_code="27601",
            transaction_type="Individual",
        ),
    )
    donor_person_id = _insert_person_candidate(
        db_conn,
        label="donor-match",
        canonical_name="Julia Howard",
        identifier_key="voter_reg_id:VR-JULIA-HOWARD",
        normalized_address="123 Main St Raleigh NC 27601",
        zip5="27601",
    )
    insert_entity_source(db_conn, "person", donor_person_id, donor_source_record_id, "donor")
    donor_transaction_id = _insert_transaction(
        db_conn,
        label="101",
        source_record_id=donor_source_record_id,
        contributor_name_raw="Julia Howard",
        contributor_state="NC",
        contributor_zip="27601",
    )

    vendor_source_record_id = _insert_test_source_record(
        db_conn,
        label="vendor-adams",
        raw_fields=_build_nc_transaction_raw_fields(
            name="ADAMS FOR NC HOUSE",
            street_line_1="123 Main Street",
            city="Raleigh",
            state="NC",
            zip_code="27602",
            occupation="Business",
            employer_or_business="Campaign Vendor",
            transaction_type="Business/Group/Org",
        ),
    )
    vendor_org_id = _insert_organization_candidate(
        db_conn,
        canonical_name="ADAMS FOR NC HOUSE",
        ein="12-3456789",
        normalized_address="123 Main St Raleigh NC 27602",
        zip5="27602",
    )
    insert_entity_source(db_conn, "organization", vendor_org_id, vendor_source_record_id, "vendor")
    vendor_transaction_id = _insert_transaction(
        db_conn,
        label="102",
        source_record_id=vendor_source_record_id,
        contributor_name_raw="ADAMS FOR NC HOUSE",
        contributor_state="NC",
        contributor_zip="27602",
    )

    ambiguity_source_record_id = _insert_test_source_record(
        db_conn,
        label="ambiguous-setzer",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Mitchell Setzer",
            street_line_1="123 Main Street",
            city="Raleigh",
            state="NC",
            zip_code="27603",
            transaction_type="Individual",
        ),
    )
    ambiguous_person_a = _insert_person_candidate(
        db_conn,
        label="ambiguous-a",
        canonical_name="Mitchell Setzer",
        identifier_key="voter_reg_id:VR-SETZER",
        normalized_address="123 Main St Raleigh NC 27603",
        zip5="27603",
    )
    ambiguous_person_b = _insert_person_candidate(
        db_conn,
        label="ambiguous-b",
        canonical_name="Mitchell Setzer",
        identifier_key="voter_reg_id:VR-SETZER",
        normalized_address="123 Main St Raleigh NC 27603",
        zip5="27603",
    )
    insert_entity_source(db_conn, "person", ambiguous_person_a, ambiguity_source_record_id, "donor")
    insert_entity_source(db_conn, "person", ambiguous_person_b, ambiguity_source_record_id, "donor")
    ambiguity_transaction_id = _insert_transaction(
        db_conn,
        label="103",
        source_record_id=ambiguity_source_record_id,
        contributor_name_raw="Mitchell Setzer",
        contributor_state="NC",
        contributor_zip="27603",
    )

    return (
        {
            "donor_transaction_id": donor_transaction_id,
            "vendor_transaction_id": vendor_transaction_id,
            "ambiguity_transaction_id": ambiguity_transaction_id,
        },
        {
            "donor_person_id": donor_person_id,
            "vendor_org_id": vendor_org_id,
        },
    )


def test_resolver_links_known_donor_and_vendor_and_skips_ambiguous_match(
    db_conn: psycopg.Connection,
) -> None:
    transaction_ids, expected_ids = _seed_resolver_fixture(db_conn)

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary == {
        "candidate_transactions": 3,
        "mutated_rows": 2,
        "matched_person_rows": 1,
        "matched_organization_rows": 1,
        "skipped_rows": 1,
        "ambiguous_rows": 1,
        "dual_match_rows": 0,
    }

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            (list(transaction_ids.values()),),
        )
        rows = {row["id"]: row for row in cursor.fetchall()}

    donor_row = rows[transaction_ids["donor_transaction_id"]]
    vendor_row = rows[transaction_ids["vendor_transaction_id"]]
    ambiguity_row = rows[transaction_ids["ambiguity_transaction_id"]]
    assert donor_row["contributor_person_id"] == expected_ids["donor_person_id"]
    assert donor_row["contributor_organization_id"] is None
    assert vendor_row["contributor_person_id"] is None
    assert vendor_row["contributor_organization_id"] == expected_ids["vendor_org_id"]
    assert ambiguity_row["contributor_person_id"] is None
    assert ambiguity_row["contributor_organization_id"] is None


def test_resolver_includes_transactions_seeded_with_loader_jurisdiction_casing(
    db_conn: psycopg.Connection,
) -> None:
    source_record_id = _insert_test_source_record(
        db_conn,
        label="loader-jurisdiction-casing",
        jurisdiction="state/NC",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Loader Jurisdiction Case",
            street_line_1="77 Capitol Ave",
            city="Raleigh",
            state="NC",
            zip_code="27605",
            transaction_type="Individual",
        ),
    )
    person_id = _insert_person_candidate(
        db_conn,
        label="loader-jurisdiction-person",
        canonical_name="Loader Jurisdiction Case",
        identifier_key="voter_reg_id:VR-LOADER-CASE",
        normalized_address="77 Capitol Ave Raleigh NC 27605",
        zip5="27605",
    )
    insert_entity_source(db_conn, "person", person_id, source_record_id, "donor")
    transaction_id = _insert_transaction(
        db_conn,
        label="104",
        source_record_id=source_record_id,
        contributor_name_raw="Loader Jurisdiction Case",
        contributor_state="NC",
        contributor_zip="27605",
        transaction_type="Individual",
    )

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary["candidate_transactions"] == 1
    assert summary["mutated_rows"] == 1
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (transaction_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    assert row["contributor_person_id"] == person_id
    assert row["contributor_organization_id"] is None


def test_resolver_second_run_is_idempotent_with_stable_transaction_identity_columns(
    db_conn: psycopg.Connection,
) -> None:
    transaction_ids, _ = _seed_resolver_fixture(db_conn)
    target_transaction_ids = list(transaction_ids.values())

    first_summary = resolve_nc_transaction_counterparties(db_conn)
    before_second_run = _select_transaction_identity_snapshot(db_conn, target_transaction_ids)
    second_summary = resolve_nc_transaction_counterparties(db_conn)
    after_second_run = _select_transaction_identity_snapshot(db_conn, target_transaction_ids)

    assert first_summary["mutated_rows"] == 2
    assert second_summary == {
        "candidate_transactions": 1,
        "mutated_rows": 0,
        "matched_person_rows": 0,
        "matched_organization_rows": 0,
        "skipped_rows": 1,
        "ambiguous_rows": 1,
        "dual_match_rows": 0,
    }
    assert after_second_run == before_second_run


def test_resolver_uses_transaction_context_when_source_record_has_both_donor_and_vendor_rows(
    db_conn: psycopg.Connection,
) -> None:
    shared_source_record_id = _insert_test_source_record(
        db_conn,
        label="mixed-role-shared-record",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Mixed Role Shared",
            street_line_1="123 Main Street",
            city="Raleigh",
            state="NC",
            zip_code="27604",
        ),
    )

    donor_person_id = _insert_person_candidate(
        db_conn,
        label="mixed-role-donor",
        canonical_name="Mixed Role Shared",
        identifier_key="voter_reg_id:VR-MIXED-DONOR",
        normalized_address="123 Main St Raleigh NC 27604",
        zip5="27604",
    )
    vendor_org_id = _insert_organization_candidate(
        db_conn,
        canonical_name="Mixed Role Shared",
        ein="98-7654321",
        normalized_address="123 Main St Raleigh NC 27604",
        zip5="27604",
    )
    insert_entity_source(db_conn, "person", donor_person_id, shared_source_record_id, "donor")
    insert_entity_source(db_conn, "organization", vendor_org_id, shared_source_record_id, "vendor")

    donor_transaction_id = _insert_transaction(
        db_conn,
        label="201",
        source_record_id=shared_source_record_id,
        contributor_name_raw="Mixed Role Shared",
        contributor_state="NC",
        contributor_zip="27604",
        transaction_type="Individual",
    )
    vendor_transaction_id = _insert_transaction(
        db_conn,
        label="202",
        source_record_id=shared_source_record_id,
        contributor_name_raw="Mixed Role Shared",
        contributor_state="NC",
        contributor_zip="27604",
        transaction_type="Business/Group/Org",
    )

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary == {
        "candidate_transactions": 2,
        "mutated_rows": 2,
        "matched_person_rows": 1,
        "matched_organization_rows": 1,
        "skipped_rows": 0,
        "ambiguous_rows": 0,
        "dual_match_rows": 0,
    }

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            ([donor_transaction_id, vendor_transaction_id],),
        )
        rows = {row["id"]: row for row in cursor.fetchall()}

    assert rows[donor_transaction_id]["contributor_person_id"] == donor_person_id
    assert rows[donor_transaction_id]["contributor_organization_id"] is None
    assert rows[vendor_transaction_id]["contributor_person_id"] is None
    assert rows[vendor_transaction_id]["contributor_organization_id"] == vendor_org_id


def test_resolver_includes_nc_contributor_organization_role_candidates(
    db_conn: psycopg.Connection,
) -> None:
    source_record_id = _insert_test_source_record(
        db_conn,
        label="org-contributor-role",
        raw_fields=_build_nc_transaction_raw_fields(
            name="ORG CONTRIBUTOR ROLE LLC",
            street_line_1="88 Broad Street",
            city="Raleigh",
            state="NC",
            zip_code="27601",
            occupation="Business",
            employer_or_business="ORG CONTRIBUTOR ROLE LLC",
            transaction_type="Business/Group/Org",
        ),
    )
    organization_id = _insert_organization_candidate(
        db_conn,
        canonical_name="ORG CONTRIBUTOR ROLE LLC",
        ein="55-4433221",
        normalized_address="88 Broad St Raleigh NC 27601",
        zip5="27601",
    )
    insert_entity_source(db_conn, "organization", organization_id, source_record_id, "contributor")
    transaction_id = _insert_transaction(
        db_conn,
        label="301",
        source_record_id=source_record_id,
        contributor_name_raw="ORG CONTRIBUTOR ROLE LLC",
        contributor_state="NC",
        contributor_zip="27601",
    )

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary["mutated_rows"] == 1
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (transaction_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    assert row["contributor_person_id"] is None
    assert row["contributor_organization_id"] == organization_id


def test_resolver_uses_nc_transaction_type_for_role_specific_identifier_and_address(
    db_conn: psycopg.Connection,
) -> None:
    source_record_id = _insert_test_source_record(
        db_conn,
        label="nc-transaction-type-organization",
        raw_fields=_build_nc_transaction_raw_fields(
            name="Portal Participant Label",
            street_line_1="900 Market St",
            city="Raleigh",
            state="NC",
            zip_code="27602",
            occupation="Business",
            employer_or_business="Acme Group",
            transaction_type="Business/Group/Org",
        ),
    )
    person_id = _insert_person_candidate(
        db_conn,
        label="wrong-side-person",
        canonical_name="Real Transaction Name",
        identifier_key="voter_reg_id:VR-SHARED-ROLE",
        normalized_address="900 Market St Raleigh NC 27602",
        zip5="27602",
    )
    organization_id = _insert_organization_candidate(
        db_conn,
        canonical_name="Real Transaction Name",
        ein="11-2233445",
        normalized_address="900 Market St Raleigh NC 27602",
        zip5="27602",
    )
    insert_entity_source(db_conn, "person", person_id, source_record_id, "donor")
    insert_entity_source(db_conn, "organization", organization_id, source_record_id, "vendor")

    transaction_id = _insert_transaction(
        db_conn,
        label="302",
        source_record_id=source_record_id,
        contributor_name_raw="Real Transaction Name",
        contributor_state="NC",
        contributor_zip="27602",
        transaction_type="Business/Group/Org",
    )

    summary = resolve_nc_transaction_counterparties(db_conn)

    assert summary["mutated_rows"] == 1
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT contributor_person_id, contributor_organization_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (transaction_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    assert row["contributor_person_id"] is None
    assert row["contributor_organization_id"] == organization_id
