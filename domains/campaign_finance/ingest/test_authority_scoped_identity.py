"""Multi-authority known-answer tests for shared ingest identity and overlap policy."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest

from core.db import (
    find_organization_by_identifier,
    find_person_by_identifier,
    insert_data_source,
    insert_entity_source,
    insert_field_provenance,
    insert_organization,
    insert_person,
    try_insert_source_record,
)
from core.db_ingest import AuthorityScopedIdentityAmbiguityError
from core.types.python.models import DataSource, Organization, Person, SourceRecord, compute_record_hash
from domains.campaign_finance.coverage.registry import (
    AuthorityDeduplicationDisposition,
    AuthorityPartition,
    AuthorityPrecedence,
    AuthorityProvenanceScope,
    AuthorityRelationEvidence,
    FilingAuthorityReference,
    PartitionedOverlappingAuthorityRelation,
    UnresolvedAuthorityRelation,
)
from domains.campaign_finance.ingest.authority_identity import (
    AuthorityOverlapRefusal,
    AuthorityScopedSourceRecord,
    deduplicate_authority_overlap,
)
from domains.campaign_finance.ingest.filing_loader import (
    ensure_authority_committee,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.ingest.fec_lookup import (
    find_candidate_id_by_fec_id,
    find_committee_id_by_fec_id,
)
from domains.campaign_finance.types.models import Filing, Transaction


pytestmark = pytest.mark.integration

_OBSERVED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _source(
    *,
    authority_type: str,
    authority_code: str,
    name: str,
) -> DataSource:
    return DataSource(
        domain="campaign_finance",
        jurisdiction=f"{authority_type}/{authority_code}",
        filing_authority_type=authority_type,
        filing_authority_code=authority_code,
        name=name,
        source_url=f"https://example.test/{authority_type}/{authority_code}/{name}",
        source_format="api",
    )


def _record(data_source_id: UUID, key: str, **raw_fields: object) -> SourceRecord:
    raw = {"native_id": key, **raw_fields}
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=key,
        raw_fields=raw,
        pull_date=_OBSERVED_AT,
        record_hash=compute_record_hash(raw),
    )


def _insert_source_with_record(
    conn: psycopg.Connection,
    *,
    authority_type: str,
    authority_code: str,
    name: str,
    record_key: str,
    **raw_fields: object,
) -> tuple[DataSource, SourceRecord]:
    source = _source(
        authority_type=authority_type,
        authority_code=authority_code,
        name=name,
    )
    insert_data_source(conn, source)
    record = _record(source.id, record_key, **raw_fields)
    assert try_insert_source_record(conn, record) == record.id
    return source, record


def test_data_source_and_source_record_identity_is_typed_by_authority_and_source(
    db_conn: psycopg.Connection,
) -> None:
    """The same source name/native record ID is distinct under independent authorities."""
    state_source, state_record = _insert_source_with_record(
        db_conn,
        authority_type="state",
        authority_code="WA",
        name="C-3 filings",
        record_key="shared-42",
        amount="100.00",
    )
    city_source, city_record = _insert_source_with_record(
        db_conn,
        authority_type="municipality",
        authority_code="SEA",
        name="C-3 filings",
        record_key="shared-42",
        amount="100.00",
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT filing_authority_type, filing_authority_code, name
            FROM core.data_source
            WHERE id = ANY(%s)
            ORDER BY filing_authority_type, filing_authority_code
            """,
            ([state_source.id, city_source.id],),
        )
        source_scopes = cursor.fetchall()
        cursor.execute(
            """
            SELECT data_source_id, source_record_key
            FROM core.source_record
            WHERE id = ANY(%s)
            ORDER BY data_source_id
            """,
            ([state_record.id, city_record.id],),
        )
        record_scopes = cursor.fetchall()

    assert source_scopes == [
        ("municipality", "SEA", "C-3 filings"),
        ("state", "WA", "C-3 filings"),
    ]
    assert {tuple(row) for row in record_scopes} == {
        (state_source.id, "shared-42"),
        (city_source.id, "shared-42"),
    }


def test_deterministic_person_and_organization_lookup_is_source_scoped(
    db_conn: psycopg.Connection,
) -> None:
    """Equal native values in overlapping systems do not create deterministic cross-links."""
    state_source, state_record = _insert_source_with_record(
        db_conn,
        authority_type="state",
        authority_code="WA",
        name="State filers",
        record_key="state-filer-7",
    )
    city_source, city_record = _insert_source_with_record(
        db_conn,
        authority_type="municipality",
        authority_code="SEA",
        name="City filers",
        record_key="city-filer-7",
    )

    state_person = Person(canonical_name="Alex Morgan", identifiers={"filer_id": "7"})
    city_person = Person(canonical_name="Alex Morgan", identifiers={"filer_id": "7"})
    state_org = Organization(canonical_name="Shared Name Committee", identifiers={"committee_id": "7"})
    city_org = Organization(canonical_name="Shared Name Committee", identifiers={"committee_id": "7"})
    for entity in (state_person, city_person):
        insert_person(db_conn, entity)
    for entity in (state_org, city_org):
        insert_organization(db_conn, entity)
    insert_entity_source(db_conn, "person", state_person.id, state_record.id, "candidate")
    insert_entity_source(db_conn, "person", city_person.id, city_record.id, "candidate")
    insert_entity_source(db_conn, "organization", state_org.id, state_record.id, "committee")
    insert_entity_source(db_conn, "organization", city_org.id, city_record.id, "committee")

    assert find_person_by_identifier(db_conn, "filer_id", "7", data_source_id=state_source.id) == state_person.id
    assert find_person_by_identifier(db_conn, "filer_id", "7", data_source_id=city_source.id) == city_person.id
    assert find_organization_by_identifier(db_conn, "committee_id", "7", data_source_id=state_source.id) == state_org.id
    assert find_organization_by_identifier(db_conn, "committee_id", "7", data_source_id=city_source.id) == city_org.id


def test_legacy_unscoped_entity_can_be_adopted_once_but_not_borrowed_by_another_source(
    db_conn: psycopg.Connection,
) -> None:
    state_source, state_record = _insert_source_with_record(
        db_conn,
        authority_type="state",
        authority_code="WA",
        name="Legacy adoption state source",
        record_key="legacy-state-7",
    )
    city_source, _city_record = _insert_source_with_record(
        db_conn,
        authority_type="municipality",
        authority_code="SEA",
        name="Legacy adoption city source",
        record_key="legacy-city-7",
    )
    legacy_person = Person(canonical_name="Legacy Candidate", identifiers={"legacy_filer_id": "7"})
    legacy_org = Organization(canonical_name="Legacy Committee", identifiers={"legacy_committee_id": "7"})
    insert_person(db_conn, legacy_person)
    insert_organization(db_conn, legacy_org)

    assert (
        find_person_by_identifier(
            db_conn,
            "legacy_filer_id",
            "7",
            data_source_id=state_source.id,
        )
        == legacy_person.id
    )
    assert (
        find_organization_by_identifier(
            db_conn,
            "legacy_committee_id",
            "7",
            data_source_id=state_source.id,
        )
        == legacy_org.id
    )
    insert_entity_source(db_conn, "person", legacy_person.id, state_record.id, "candidate")
    insert_entity_source(db_conn, "organization", legacy_org.id, state_record.id, "committee")

    assert (
        find_person_by_identifier(
            db_conn,
            "legacy_filer_id",
            "7",
            data_source_id=city_source.id,
        )
        is None
    )
    assert (
        find_organization_by_identifier(
            db_conn,
            "legacy_committee_id",
            "7",
            data_source_id=city_source.id,
        )
        is None
    )


def test_supersession_and_filing_amendment_links_refuse_cross_source_ownership(
    db_conn: psycopg.Connection,
) -> None:
    state_source, state_record = _insert_source_with_record(
        db_conn,
        authority_type="state",
        authority_code="WA",
        name="State amendments",
        record_key="shared-amendment",
    )
    city_source, city_record = _insert_source_with_record(
        db_conn,
        authority_type="municipality",
        authority_code="SEA",
        name="City amendments",
        record_key="shared-amendment",
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db_conn.transaction():
            db_conn.execute(
                "UPDATE core.source_record SET superseded_by = %s WHERE id = %s",
                (city_record.id, state_record.id),
            )

    state_org = Organization(canonical_name="State Amendment Committee", identifiers={})
    city_org = Organization(canonical_name="City Amendment Committee", identifiers={})
    insert_organization(db_conn, state_org)
    insert_organization(db_conn, city_org)
    state_committee_id = ensure_authority_committee(
        db_conn,
        data_source_id=state_source.id,
        authority_type="state",
        authority_code="WA",
        native_committee_id="amendment-committee",
        organization_id=state_org.id,
        source_record_id=state_record.id,
    )
    city_committee_id = ensure_authority_committee(
        db_conn,
        data_source_id=city_source.id,
        authority_type="municipality",
        authority_code="SEA",
        native_committee_id="amendment-committee",
        organization_id=city_org.id,
        source_record_id=city_record.id,
    )
    city_parent_filing_id = upsert_filing(
        db_conn,
        Filing(
            filing_fec_id="city-parent",
            data_source_id=city_source.id,
            native_filing_id="parent",
            committee_id=city_committee_id,
            amendment_indicator="N",
            source_record_id=city_record.id,
        ),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db_conn.transaction():
            upsert_filing(
                db_conn,
                Filing(
                    filing_fec_id="state-child",
                    data_source_id=state_source.id,
                    native_filing_id="child",
                    committee_id=state_committee_id,
                    amendment_indicator="A",
                    amended_from_filing_id=city_parent_filing_id,
                    source_record_id=state_record.id,
                ),
            )

    state_parent_filing_id = upsert_filing(
        db_conn,
        Filing(
            filing_fec_id="state-parent",
            data_source_id=state_source.id,
            native_filing_id="parent",
            committee_id=state_committee_id,
            amendment_indicator="N",
            source_record_id=state_record.id,
        ),
    )
    city_transaction_id = upsert_transaction(
        db_conn,
        Transaction(
            filing_id=city_parent_filing_id,
            committee_id=city_committee_id,
            data_source_id=city_source.id,
            native_transaction_id="city-amendment-parent",
            transaction_type="expenditure",
            amount=Decimal("12.00"),
            amendment_indicator="N",
            source_record_id=city_record.id,
        ),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db_conn.transaction():
            upsert_transaction(
                db_conn,
                Transaction(
                    filing_id=state_parent_filing_id,
                    committee_id=state_committee_id,
                    data_source_id=state_source.id,
                    native_transaction_id="state-cross-source-record",
                    transaction_type="expenditure",
                    amount=Decimal("13.00"),
                    amendment_indicator="N",
                    source_record_id=city_record.id,
                ),
            )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db_conn.transaction():
            upsert_transaction(
                db_conn,
                Transaction(
                    filing_id=state_parent_filing_id,
                    committee_id=state_committee_id,
                    data_source_id=state_source.id,
                    native_transaction_id="state-cross-source-amendment",
                    transaction_type="expenditure",
                    amount=Decimal("14.00"),
                    amendment_indicator="A",
                    amended_by_transaction_id=city_transaction_id,
                    source_record_id=state_record.id,
                ),
            )


def test_committee_filing_and_transaction_native_keys_do_not_collide_across_authorities(
    db_conn: psycopg.Connection,
) -> None:
    state_source, state_record = _insert_source_with_record(
        db_conn,
        authority_type="state",
        authority_code="WA",
        name="State reports",
        record_key="report-42",
        amount="125.50",
    )
    city_source, city_record = _insert_source_with_record(
        db_conn,
        authority_type="municipality",
        authority_code="SEA",
        name="City reports",
        record_key="report-42",
        amount="80.25",
    )
    state_org = Organization(canonical_name="State Committee", identifiers={})
    city_org = Organization(canonical_name="City Committee", identifiers={})
    insert_organization(db_conn, state_org)
    insert_organization(db_conn, city_org)

    state_committee_id = ensure_authority_committee(
        db_conn,
        data_source_id=state_source.id,
        authority_type="state",
        authority_code="WA",
        native_committee_id="committee-7",
        organization_id=state_org.id,
        source_record_id=state_record.id,
    )
    city_committee_id = ensure_authority_committee(
        db_conn,
        data_source_id=city_source.id,
        authority_type="municipality",
        authority_code="SEA",
        native_committee_id="committee-7",
        organization_id=city_org.id,
        source_record_id=city_record.id,
    )
    assert state_committee_id != city_committee_id
    assert (
        find_committee_id_by_fec_id(
            db_conn,
            "committee-7",
            data_source_id=state_source.id,
        )
        == state_committee_id
    )
    assert (
        find_committee_id_by_fec_id(
            db_conn,
            "committee-7",
            data_source_id=city_source.id,
        )
        == city_committee_id
    )
    with pytest.raises(AuthorityScopedIdentityAmbiguityError):
        find_committee_id_by_fec_id(db_conn, "committee-7")

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.candidate (
                fec_candidate_id,
                data_source_id,
                native_candidate_id,
                name,
                office,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, 'H', %s)
            RETURNING id
            """,
            ("H1WA00007", state_source.id, "candidate-7", "State Candidate", state_record.id),
        )
        state_candidate_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO cf.candidate (
                fec_candidate_id,
                data_source_id,
                native_candidate_id,
                name,
                office,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, 'H', %s)
            RETURNING id
            """,
            ("H1WA00007", city_source.id, "candidate-7", "City Candidate", city_record.id),
        )
        city_candidate_id = cursor.fetchone()[0]
    assert state_candidate_id != city_candidate_id
    assert (
        find_candidate_id_by_fec_id(
            db_conn,
            "candidate-7",
            data_source_id=state_source.id,
        )
        == state_candidate_id
    )
    assert (
        find_candidate_id_by_fec_id(
            db_conn,
            "candidate-7",
            data_source_id=city_source.id,
        )
        == city_candidate_id
    )
    with pytest.raises(AuthorityScopedIdentityAmbiguityError):
        find_candidate_id_by_fec_id(db_conn, "candidate-7")

    state_filing_id = upsert_filing(
        db_conn,
        Filing(
            filing_fec_id="compat-report-42",
            data_source_id=state_source.id,
            native_filing_id="report-42",
            committee_id=state_committee_id,
            candidate_id=state_candidate_id,
            amendment_indicator="N",
            source_record_id=state_record.id,
        ),
    )
    city_filing_id = upsert_filing(
        db_conn,
        Filing(
            filing_fec_id="compat-report-42",
            data_source_id=city_source.id,
            native_filing_id="report-42",
            committee_id=city_committee_id,
            candidate_id=city_candidate_id,
            amendment_indicator="N",
            source_record_id=city_record.id,
        ),
    )
    assert state_filing_id != city_filing_id

    state_transaction_id = upsert_transaction(
        db_conn,
        Transaction(
            filing_id=state_filing_id,
            committee_id=state_committee_id,
            data_source_id=state_source.id,
            native_transaction_id="transaction-9",
            transaction_type="contribution",
            transaction_identifier="transaction-9",
            amount=Decimal("125.50"),
            amendment_indicator="N",
            source_record_id=state_record.id,
        ),
    )
    city_transaction_id = upsert_transaction(
        db_conn,
        Transaction(
            filing_id=city_filing_id,
            committee_id=city_committee_id,
            data_source_id=city_source.id,
            native_transaction_id="transaction-9",
            transaction_type="contribution",
            transaction_identifier="transaction-9",
            amount=Decimal("80.25"),
            amendment_indicator="N",
            source_record_id=city_record.id,
        ),
    )
    assert state_transaction_id != city_transaction_id

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*), sum(amount)
            FROM cf.transaction
            WHERE native_transaction_id = 'transaction-9'
            """
        )
        count, total = cursor.fetchone()
    assert (count, total) == (2, Decimal("205.75"))


def test_source_supersession_preserves_field_lineage_and_updates_current_filing_provenance(
    db_conn: psycopg.Connection,
) -> None:
    source, original_record = _insert_source_with_record(
        db_conn,
        authority_type="state",
        authority_code="WA",
        name="Amended reports",
        record_key="filing-88",
        amount="100.00",
        amendment="N",
    )
    organization = Organization(canonical_name="Amendment Committee", identifiers={})
    insert_organization(db_conn, organization)
    committee_id = ensure_authority_committee(
        db_conn,
        data_source_id=source.id,
        authority_type="state",
        authority_code="WA",
        native_committee_id="committee-88",
        organization_id=organization.id,
        source_record_id=original_record.id,
    )
    filing_id = upsert_filing(
        db_conn,
        Filing(
            filing_fec_id="compat-filing-88",
            data_source_id=source.id,
            native_filing_id="filing-88",
            committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=original_record.id,
        ),
    )
    insert_field_provenance(
        db_conn,
        "organization",
        organization.id,
        "reported_total",
        "100.00",
        original_record.id,
        _OBSERVED_AT,
    )

    amended_record = _record(
        source.id,
        "filing-88",
        amount="125.50",
        amendment="A",
    )
    assert try_insert_source_record(db_conn, amended_record) == amended_record.id
    assert (
        upsert_filing(
            db_conn,
            Filing(
                id=uuid4(),
                filing_fec_id="compat-filing-88",
                data_source_id=source.id,
                native_filing_id="filing-88",
                committee_id=committee_id,
                amendment_indicator="A",
                source_record_id=amended_record.id,
            ),
        )
        == filing_id
    )
    insert_field_provenance(
        db_conn,
        "organization",
        organization.id,
        "reported_total",
        "125.50",
        amended_record.id,
        _OBSERVED_AT,
    )

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_record_id, amendment_indicator
            FROM cf.filing
            WHERE id = %s
            """,
            (filing_id,),
        )
        filing_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT source_record_id, field_value, is_current
            FROM core.field_provenance
            WHERE entity_type = 'organization'
              AND entity_id = %s
              AND field_name = 'reported_total'
            ORDER BY field_value
            """,
            (organization.id,),
        )
        field_rows = cursor.fetchall()
        cursor.execute("SELECT superseded_by FROM core.source_record WHERE id = %s", (original_record.id,))
        superseded_by = cursor.fetchone()[0]

    assert filing_row == (amended_record.id, "A")
    assert field_rows == [
        (original_record.id, "100.00", False),
        (amended_record.id, "125.50", True),
    ]
    assert superseded_by == amended_record.id


def _overlap_relation(*, deduplication: AuthorityDeduplicationDisposition) -> PartitionedOverlappingAuthorityRelation:
    state = FilingAuthorityReference(kind="state", code="WA")
    city = FilingAuthorityReference(kind="municipality", code="SEA")
    return PartitionedOverlappingAuthorityRelation(
        relation="partitioned_overlapping",
        authorities=[state, city],
        precedence=[
            AuthorityPrecedence(authority=state, scope="state reports take precedence for identical report IDs"),
            AuthorityPrecedence(authority=city, scope="city-only reports remain city-owned"),
        ],
        partitions=[
            AuthorityPartition(authority=state, scope="state filers and state reports"),
            AuthorityPartition(authority=city, scope="city filers and local reports"),
        ],
        provenance=[
            AuthorityProvenanceScope(authority=state, source_scope="state source records"),
            AuthorityProvenanceScope(authority=city, source_scope="city source records"),
        ],
        deduplication=deduplication,
        refusals=["refuse any aggregate without the declared identity keys"],
        evidence=AuthorityRelationEvidence(
            owner="synthetic fixture",
            receipt="synthetic://authority-overlap",
            receipt_sha256="1" * 64,
        ),
    )


def test_hand_calculated_overlap_deduplication_uses_registry_keys_and_precedence() -> None:
    state = FilingAuthorityReference(kind="state", code="WA")
    city = FilingAuthorityReference(kind="municipality", code="SEA")
    records = [
        AuthorityScopedSourceRecord(
            source_record_id=UUID(int=1),
            authority=state,
            source_name="state reports",
            raw_fields={"report_id": "shared-42", "amount": Decimal("125.50")},
        ),
        AuthorityScopedSourceRecord(
            source_record_id=UUID(int=2),
            authority=city,
            source_name="city reports",
            raw_fields={"report_id": "shared-42", "amount": Decimal("125.50")},
        ),
        AuthorityScopedSourceRecord(
            source_record_id=UUID(int=3),
            authority=city,
            source_name="city reports",
            raw_fields={"report_id": "city-9", "amount": Decimal("45.75")},
        ),
    ]
    relation = _overlap_relation(
        deduplication=AuthorityDeduplicationDisposition(
            disposition="deduplicate",
            identity_keys=["report_id"],
        )
    )

    deduplicated = deduplicate_authority_overlap(relation, records)

    assert [record.source_record_id for record in deduplicated] == [UUID(int=1), UUID(int=3)]
    assert sum(Decimal(str(record.raw_fields["amount"])) for record in deduplicated) == Decimal("171.25")


@pytest.mark.parametrize(
    "relation",
    [
        UnresolvedAuthorityRelation(
            relation="unresolved",
            candidate_authorities=[
                FilingAuthorityReference(kind="state", code="WA"),
                FilingAuthorityReference(kind="municipality", code="SEA"),
            ],
            reason="no accepted crosswalk",
            aggregation_disposition="refuse",
        ),
        _overlap_relation(
            deduplication=AuthorityDeduplicationDisposition(
                disposition="refuse_combination",
                identity_keys=[],
            )
        ),
    ],
)
def test_hand_calculated_overlap_refuses_without_registry_deduplication_policy(
    relation: UnresolvedAuthorityRelation | PartitionedOverlappingAuthorityRelation,
) -> None:
    records = [
        AuthorityScopedSourceRecord(
            source_record_id=UUID(int=4),
            authority=FilingAuthorityReference(kind="state", code="WA"),
            source_name="state reports",
            raw_fields={"report_id": "shared-42", "amount": Decimal("999999.00")},
        ),
        AuthorityScopedSourceRecord(
            source_record_id=UUID(int=5),
            authority=FilingAuthorityReference(kind="municipality", code="SEA"),
            source_name="city reports",
            raw_fields={"report_id": "shared-42", "amount": Decimal("999999.00")},
        ),
    ]

    with pytest.raises(AuthorityOverlapRefusal):
        deduplicate_authority_overlap(relation, records)
