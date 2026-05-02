from __future__ import annotations

from datetime import date
from decimal import Decimal
from re import fullmatch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.pq import TransactionStatus

from core.db import insert_data_source, insert_entity_source, insert_organization, insert_person, insert_source_record
from core.types.python.models import DataSource, Organization, Person, SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    generate_synthetic_committee_id,
    resolve_transaction_counterparty_ids,
    update_transaction_contributor_identity_ids,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.types.models import Filing, Transaction

pytestmark = pytest.mark.integration

_TEST_ORGANIZATION_PREFIX = "Test Filing Loader Organization"
_TEST_PERSON_PREFIX = "Test Filing Loader Person"
_TEST_FILING_PREFIX = "test-filing-loader-filing-"
_TEST_TRANSACTION_PREFIX = "test-filing-loader-transaction-"
_TEST_DATA_SOURCE_PREFIX = "Test Filing Loader Source "
_TEST_SOURCE_RECORD_KEY_PREFIX = "test-filing-loader-source-record-"
_TEST_SUB_ID_BASE = 990_000_000_000_000_000


@pytest.fixture(autouse=True)
def _cleanup_test_rows(db_conn: psycopg.Connection) -> None:
    yield
    if db_conn.info.transaction_status == TransactionStatus.INERROR:
        db_conn.rollback()

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM core.entity_source
            WHERE source_record_id IN (
                SELECT id
                FROM core.source_record
                WHERE source_record_key LIKE %s
            )
            """,
            (f"{_TEST_SOURCE_RECORD_KEY_PREFIX}%",),
        )
        cursor.execute(
            """
            DELETE FROM cf.transaction
            WHERE transaction_identifier LIKE %s
               OR (sub_id IS NOT NULL AND sub_id >= %s)
            """,
            (f"{_TEST_TRANSACTION_PREFIX}%", _TEST_SUB_ID_BASE),
        )
        cursor.execute("DELETE FROM cf.filing WHERE filing_fec_id LIKE %s", (f"{_TEST_FILING_PREFIX}%",))
        cursor.execute("DELETE FROM cf.committee WHERE name LIKE %s", (f"{_TEST_ORGANIZATION_PREFIX}%",))
        cursor.execute("DELETE FROM core.organization WHERE canonical_name LIKE %s", (f"{_TEST_ORGANIZATION_PREFIX}%",))
        cursor.execute("DELETE FROM core.person WHERE canonical_name LIKE %s", (f"{_TEST_PERSON_PREFIX}%",))
        cursor.execute(
            "DELETE FROM core.source_record WHERE source_record_key LIKE %s",
            (f"{_TEST_SOURCE_RECORD_KEY_PREFIX}%",),
        )
        cursor.execute("DELETE FROM core.data_source WHERE name LIKE %s", (f"{_TEST_DATA_SOURCE_PREFIX}%",))


def _insert_test_organization(conn: psycopg.Connection, label: str) -> UUID:
    return insert_organization(conn, Organization(canonical_name=f"{_TEST_ORGANIZATION_PREFIX} {label}"))


def _insert_test_person(conn: psycopg.Connection, label: str) -> UUID:
    return insert_person(
        conn,
        Person(
            canonical_name=f"{_TEST_PERSON_PREFIX} {label}",
            first_name="Test",
            last_name=label,
        ),
    )


def _insert_test_source_record(conn: psycopg.Connection, label: str) -> UUID:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="test/stage1",
        name=f"{_TEST_DATA_SOURCE_PREFIX}{label}",
        source_url="https://example.test/filing-loader",
    )
    insert_data_source(conn, data_source)
    raw_fields = {"test_label": label}
    return insert_source_record(
        conn,
        SourceRecord(
            data_source_id=data_source.id,
            source_record_key=f"{_TEST_SOURCE_RECORD_KEY_PREFIX}{label}",
            raw_fields=raw_fields,
            pull_date=utc_now(),
            record_hash=compute_record_hash(raw_fields),
        ),
    )


def _insert_test_committee(conn: psycopg.Connection, label: str, suffix: int) -> UUID:
    committee_fec_id = f"C{uuid4().int % 100_000_000:08d}"
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.committee (fec_committee_id, name)
            VALUES (%s, %s)
            RETURNING id
            """,
            (committee_fec_id, f"{_TEST_ORGANIZATION_PREFIX} Committee {label} {suffix}"),
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


def _build_test_transaction(
    filing_id: UUID,
    committee_id: UUID,
    amount: str,
    **overrides: object,
) -> Transaction:
    payload: dict[str, object] = {
        "filing_id": filing_id,
        "committee_id": committee_id,
        "transaction_type": "15",
        "amount": Decimal(amount),
        "amendment_indicator": "N",
    }
    payload.update(overrides)
    return Transaction(**payload)


def _select_filing_row(db_conn: psycopg.Connection, filing_fec_id: str) -> dict[str, object]:
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, filing_fec_id, report_type, amendment_indicator
            FROM cf.filing
            WHERE filing_fec_id = %s
            """,
            (filing_fec_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row


def _select_transaction_row(db_conn: psycopg.Connection, transaction_id: UUID) -> dict[str, object]:
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, amendment_indicator, back_ref_transaction_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (transaction_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row


def test_generate_synthetic_committee_id_is_deterministic() -> None:
    first_value = generate_synthetic_committee_id("NC", "SBOE-100")
    second_value = generate_synthetic_committee_id("NC", "SBOE-100")
    different_value = generate_synthetic_committee_id("GA", "SBOE-100")

    assert first_value == second_value
    assert first_value != different_value
    assert fullmatch(r"C\d{8}", first_value) is not None


def test_ensure_state_committee_links_existing_organization(db_conn: psycopg.Connection) -> None:
    organization_id = _insert_test_organization(db_conn, "Ensure Committee")

    first_committee_id = ensure_state_committee(db_conn, "NC", "COMMITTEE-42", organization_id)
    second_committee_id = ensure_state_committee(db_conn, "NC", "COMMITTEE-42", organization_id)

    assert second_committee_id == first_committee_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT committee.id, committee.fec_committee_id, committee.organization_id, committee.name,
                   organization.canonical_name
            FROM cf.committee AS committee
            JOIN core.organization AS organization
              ON organization.id = committee.organization_id
            WHERE committee.id = %s
            """,
            (first_committee_id,),
        )
        committee_row = cursor.fetchone()

    assert committee_row is not None
    assert committee_row["fec_committee_id"] == generate_synthetic_committee_id("NC", "COMMITTEE-42")
    assert committee_row["organization_id"] == organization_id
    assert committee_row["name"] == committee_row["canonical_name"]


def test_resolve_transaction_counterparty_ids_returns_person_match(db_conn: psycopg.Connection) -> None:
    source_record_id = _insert_test_source_record(db_conn, "counterparty-person")
    person_id = _insert_test_person(db_conn, "Counterparty Person")
    insert_entity_source(db_conn, "person", person_id, source_record_id, "donor")

    assert resolve_transaction_counterparty_ids(
        db_conn,
        source_record_id=source_record_id,
        person_roles=("donor",),
        organization_roles=("contributor",),
    ) == (person_id, None)


def test_resolve_transaction_counterparty_ids_returns_organization_match(db_conn: psycopg.Connection) -> None:
    source_record_id = _insert_test_source_record(db_conn, "counterparty-organization")
    organization_id = _insert_test_organization(db_conn, "Counterparty Organization")
    insert_entity_source(db_conn, "organization", organization_id, source_record_id, "contributor")

    assert resolve_transaction_counterparty_ids(
        db_conn,
        source_record_id=source_record_id,
        person_roles=("donor",),
        organization_roles=("contributor",),
    ) == (None, organization_id)


def test_resolve_transaction_counterparty_ids_returns_none_for_conflicting_matches(
    db_conn: psycopg.Connection,
) -> None:
    source_record_id = _insert_test_source_record(db_conn, "counterparty-conflict")
    person_id = _insert_test_person(db_conn, "Counterparty Conflict Person")
    organization_id = _insert_test_organization(db_conn, "Counterparty Conflict Organization")
    insert_entity_source(db_conn, "person", person_id, source_record_id, "donor")
    insert_entity_source(db_conn, "organization", organization_id, source_record_id, "contributor")

    assert resolve_transaction_counterparty_ids(
        db_conn,
        source_record_id=source_record_id,
        person_roles=("donor",),
        organization_roles=("contributor",),
    ) == (None, None)


def test_upsert_filing_is_idempotent_on_filing_fec_id(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Filing Upsert", suffix=1)
    filing_fec_id = f"{_TEST_FILING_PREFIX}idempotent"

    initial_filing = Filing(
        filing_fec_id=filing_fec_id,
        committee_id=committee_id,
        amendment_indicator="N",
        report_type="Q1",
    )
    first_id = upsert_filing(db_conn, initial_filing)

    repeated_filing = initial_filing.model_copy(update={"id": uuid4(), "report_type": None})
    second_id = upsert_filing(db_conn, repeated_filing)

    assert second_id == first_id

    filing_row = _select_filing_row(db_conn, filing_fec_id)
    assert filing_row["id"] == first_id
    assert filing_row["report_type"] == "Q1"

    with db_conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM cf.filing WHERE filing_fec_id = %s", (filing_fec_id,))
        filing_count = cursor.fetchone()[0]
    assert filing_count == 1


def test_upsert_filing_uses_explicit_amendment_precedence(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Filing Precedence", suffix=2)
    filing_fec_id = f"{_TEST_FILING_PREFIX}precedence"

    filing_id = upsert_filing(
        db_conn,
        Filing(
            filing_fec_id=filing_fec_id,
            committee_id=committee_id,
            amendment_indicator="N",
        ),
    )

    assert (
        upsert_filing(
            db_conn,
            Filing(
                id=uuid4(),
                filing_fec_id=filing_fec_id,
                committee_id=committee_id,
                amendment_indicator="A",
            ),
        )
        == filing_id
    )
    assert _select_filing_row(db_conn, filing_fec_id)["amendment_indicator"] == "A"

    upsert_filing(
        db_conn,
        Filing(
            id=uuid4(),
            filing_fec_id=filing_fec_id,
            committee_id=committee_id,
            amendment_indicator="N",
        ),
    )
    assert _select_filing_row(db_conn, filing_fec_id)["amendment_indicator"] == "A"

    upsert_filing(
        db_conn,
        Filing(
            id=uuid4(),
            filing_fec_id=filing_fec_id,
            committee_id=committee_id,
            amendment_indicator="T",
        ),
    )
    assert _select_filing_row(db_conn, filing_fec_id)["amendment_indicator"] == "T"

    upsert_filing(
        db_conn,
        Filing(
            id=uuid4(),
            filing_fec_id=filing_fec_id,
            committee_id=committee_id,
            amendment_indicator="A",
        ),
    )
    assert _select_filing_row(db_conn, filing_fec_id)["amendment_indicator"] == "T"


def test_upsert_transaction_uses_explicit_amendment_precedence(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Transaction Precedence", suffix=10)
    filing_id = _insert_test_filing(db_conn, committee_id, "transaction-precedence")
    sub_id = _TEST_SUB_ID_BASE + 10

    transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(filing_id, committee_id, "71.00", sub_id=sub_id, amendment_indicator="N"),
    )

    assert (
        upsert_transaction(
            db_conn,
            _build_test_transaction(
                filing_id,
                committee_id,
                "72.00",
                id=uuid4(),
                sub_id=sub_id,
                amendment_indicator="A",
            ),
        )
        == transaction_id
    )
    assert _select_transaction_row(db_conn, transaction_id)["amendment_indicator"] == "A"

    upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "73.00",
            id=uuid4(),
            sub_id=sub_id,
            amendment_indicator="N",
        ),
    )
    assert _select_transaction_row(db_conn, transaction_id)["amendment_indicator"] == "A"

    upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "74.00",
            id=uuid4(),
            sub_id=sub_id,
            amendment_indicator="T",
        ),
    )
    assert _select_transaction_row(db_conn, transaction_id)["amendment_indicator"] == "T"

    upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "75.00",
            id=uuid4(),
            sub_id=sub_id,
            amendment_indicator="A",
        ),
    )
    assert _select_transaction_row(db_conn, transaction_id)["amendment_indicator"] == "T"


def test_upsert_transaction_is_idempotent_by_sub_id(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Sub ID", suffix=3)
    filing_id = _insert_test_filing(db_conn, committee_id, "sub-id")
    sub_id = _TEST_SUB_ID_BASE + 1

    transaction = _build_test_transaction(filing_id, committee_id, "25.00", sub_id=sub_id)
    first_id = upsert_transaction(db_conn, transaction)
    second_id = upsert_transaction(db_conn, transaction.model_copy(update={"id": uuid4()}))

    assert second_id == first_id
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM cf.transaction WHERE sub_id = %s", (sub_id,))
        transaction_count = cursor.fetchone()[0]
    assert transaction_count == 1


def test_upsert_transaction_persists_back_ref_transaction_id(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Back Ref Persist", suffix=11)
    filing_id = _insert_test_filing(db_conn, committee_id, "back-ref-persist")
    sub_id = _TEST_SUB_ID_BASE + 11
    back_ref_transaction_id = f"{_TEST_TRANSACTION_PREFIX}back-ref-001"

    transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "31.00",
            sub_id=sub_id,
            back_ref_transaction_id=back_ref_transaction_id,
        ),
    )

    row = _select_transaction_row(db_conn, transaction_id)
    assert row["back_ref_transaction_id"] == back_ref_transaction_id


def test_upsert_transaction_allows_missing_back_ref_transaction_id(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Back Ref Missing", suffix=12)
    filing_id = _insert_test_filing(db_conn, committee_id, "back-ref-missing")
    sub_id = _TEST_SUB_ID_BASE + 12

    transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(filing_id, committee_id, "32.00", sub_id=sub_id),
    )
    assert _select_transaction_row(db_conn, transaction_id)["back_ref_transaction_id"] is None

    updated_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "33.00",
            id=uuid4(),
            sub_id=sub_id,
        ),
    )
    assert updated_id == transaction_id
    assert _select_transaction_row(db_conn, transaction_id)["back_ref_transaction_id"] is None


def test_upsert_transaction_preserves_existing_back_ref_transaction_id_when_omitted(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = _insert_test_committee(db_conn, "Back Ref Preserve On Omit", suffix=13)
    filing_id = _insert_test_filing(db_conn, committee_id, "back-ref-preserve-on-omit")
    sub_id = _TEST_SUB_ID_BASE + 13
    back_ref_transaction_id = f"{_TEST_TRANSACTION_PREFIX}back-ref-keep-001"

    transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "34.00",
            sub_id=sub_id,
            back_ref_transaction_id=back_ref_transaction_id,
        ),
    )
    assert _select_transaction_row(db_conn, transaction_id)["back_ref_transaction_id"] == back_ref_transaction_id

    updated_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "35.00",
            id=uuid4(),
            sub_id=sub_id,
        ),
    )

    assert updated_id == transaction_id
    assert _select_transaction_row(db_conn, transaction_id)["back_ref_transaction_id"] == back_ref_transaction_id


def test_upsert_transaction_is_idempotent_by_filing_and_identifier(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Filing Identifier", suffix=4)
    filing_id = _insert_test_filing(db_conn, committee_id, "filing-identifier")
    transaction_identifier = f"{_TEST_TRANSACTION_PREFIX}filing-id"

    first_id = upsert_transaction(
        db_conn,
        _build_test_transaction(filing_id, committee_id, "30.00", transaction_identifier=transaction_identifier),
    )
    second_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id, committee_id, "35.00", id=uuid4(), transaction_identifier=transaction_identifier
        ),
    )

    assert second_id == first_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count, MIN(amount) AS amount
            FROM cf.transaction
            WHERE filing_id = %s
              AND transaction_identifier = %s
            """,
            (filing_id, transaction_identifier),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["count"] == 1
    assert row["amount"] == Decimal("35.00")


def test_upsert_transaction_prefers_existing_row_when_one_key_matches(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Both Keys", suffix=5)
    filing_id = _insert_test_filing(db_conn, committee_id, "both-keys")
    sub_id = _TEST_SUB_ID_BASE + 2
    transaction_identifier = f"{_TEST_TRANSACTION_PREFIX}both-keys"

    first_id = upsert_transaction(
        db_conn,
        _build_test_transaction(filing_id, committee_id, "50.00", sub_id=sub_id),
    )
    second_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "50.00",
            id=uuid4(),
            sub_id=sub_id,
            transaction_identifier=transaction_identifier,
        ),
    )

    assert second_id == first_id
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, transaction_identifier
            FROM cf.transaction
            WHERE sub_id = %s
            """,
            (sub_id,),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["id"] == first_id
    assert row["transaction_identifier"] == transaction_identifier


def test_upsert_transaction_preserves_existing_idempotency_keys(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Preserve Keys", suffix=7)
    filing_id = _insert_test_filing(db_conn, committee_id, "preserve-keys")
    sub_id = _TEST_SUB_ID_BASE + 7
    transaction_identifier = f"{_TEST_TRANSACTION_PREFIX}preserve-keys"

    original_transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "51.00",
            sub_id=sub_id,
            transaction_identifier=transaction_identifier,
        ),
    )

    identifier_update_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "52.00",
            id=uuid4(),
            sub_id=None,
            transaction_identifier=transaction_identifier,
        ),
    )
    assert identifier_update_id == original_transaction_id

    sub_id_update_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id, committee_id, "53.00", id=uuid4(), sub_id=sub_id, transaction_identifier=None
        ),
    )
    assert sub_id_update_id == original_transaction_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT sub_id, transaction_identifier
            FROM cf.transaction
            WHERE id = %s
            """,
            (original_transaction_id,),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["sub_id"] == sub_id
    assert row["transaction_identifier"] == transaction_identifier


def test_upsert_transaction_treats_blank_identifier_as_missing_key(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Blank Identifier", suffix=8)
    filing_id = _insert_test_filing(db_conn, committee_id, "blank-identifier")

    with pytest.raises(ValueError, match="idempotency key"):
        upsert_transaction(
            db_conn,
            _build_test_transaction(filing_id, committee_id, "55.00", transaction_identifier="   "),
        )

    transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "56.00",
            transaction_identifier="   ",
            sub_id=_TEST_SUB_ID_BASE + 8,
        ),
    )

    with db_conn.cursor() as cursor:
        cursor.execute("SELECT transaction_identifier FROM cf.transaction WHERE id = %s", (transaction_id,))
        normalized_identifier = cursor.fetchone()[0]

    assert normalized_identifier is None


def test_upsert_transaction_preserves_existing_source_record_id(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Preserve Source", suffix=9)
    filing_id = _insert_test_filing(db_conn, committee_id, "preserve-source")
    source_record_id = _insert_test_source_record(db_conn, "preserve-source")
    sub_id = _TEST_SUB_ID_BASE + 9

    original_transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(filing_id, committee_id, "60.00", sub_id=sub_id, source_record_id=source_record_id),
    )

    updated_transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(filing_id, committee_id, "61.00", id=uuid4(), sub_id=sub_id),
    )

    assert updated_transaction_id == original_transaction_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT amount, source_record_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (original_transaction_id,),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["amount"] == Decimal("61.00")
    assert row["source_record_id"] == source_record_id


def test_upsert_transaction_persists_schedule_e_columns(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Schedule E Columns", suffix=10)
    filing_id = _insert_test_filing(db_conn, committee_id, "schedule-e-columns")
    sub_id = _TEST_SUB_ID_BASE + 10

    original_transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "62.00",
            sub_id=sub_id,
            support_oppose="S",
            dissemination_date=date(2024, 10, 14),
            aggregate_amount=Decimal("120.50"),
        ),
    )

    updated_transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id,
            committee_id,
            "63.00",
            id=uuid4(),
            sub_id=sub_id,
            support_oppose="O",
            dissemination_date=date(2024, 10, 15),
            aggregate_amount=Decimal("130.75"),
        ),
    )

    assert updated_transaction_id == original_transaction_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT support_oppose, dissemination_date, aggregate_amount
            FROM cf.transaction
            WHERE id = %s
            """,
            (original_transaction_id,),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["support_oppose"] == "O"
    assert row["dissemination_date"] == date(2024, 10, 15)
    assert row["aggregate_amount"] == Decimal("130.75")


def test_upsert_transaction_treats_blank_back_ref_as_null_on_insert(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Blank BackRef Insert", suffix=14)
    filing_id = _insert_test_filing(db_conn, committee_id, "blank-backref-insert")
    sub_id = _TEST_SUB_ID_BASE + 14

    transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(filing_id, committee_id, "70.00", sub_id=sub_id, back_ref_transaction_id="   "),
    )

    assert _select_transaction_row(db_conn, transaction_id)["back_ref_transaction_id"] is None


def test_upsert_transaction_blank_back_ref_does_not_overwrite_existing(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "Blank BackRef Preserve", suffix=15)
    filing_id = _insert_test_filing(db_conn, committee_id, "blank-backref-preserve")
    sub_id = _TEST_SUB_ID_BASE + 15
    real_back_ref = f"{_TEST_TRANSACTION_PREFIX}back-ref-real-001"

    transaction_id = upsert_transaction(
        db_conn,
        _build_test_transaction(filing_id, committee_id, "71.00", sub_id=sub_id, back_ref_transaction_id=real_back_ref),
    )
    assert _select_transaction_row(db_conn, transaction_id)["back_ref_transaction_id"] == real_back_ref

    updated_id = upsert_transaction(
        db_conn,
        _build_test_transaction(
            filing_id, committee_id, "72.00", id=uuid4(), sub_id=sub_id, back_ref_transaction_id="   "
        ),
    )

    assert updated_id == transaction_id
    assert _select_transaction_row(db_conn, transaction_id)["back_ref_transaction_id"] == real_back_ref


def test_upsert_transaction_requires_at_least_one_idempotency_key(db_conn: psycopg.Connection) -> None:
    committee_id = _insert_test_committee(db_conn, "No Keys", suffix=6)
    filing_id = _insert_test_filing(db_conn, committee_id, "no-keys")

    with pytest.raises(ValueError, match="idempotency key"):
        upsert_transaction(
            db_conn,
            _build_test_transaction(filing_id, committee_id, "42.00"),
        )


def test_update_transaction_contributor_identity_ids_updates_only_identity_columns(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = _insert_test_committee(db_conn, "Contributor IDs", suffix=21)
    filing_id = _insert_test_filing(db_conn, committee_id, "contributor-identity-only-update")
    transaction = _build_test_transaction(
        filing_id,
        committee_id,
        "91.00",
        sub_id=_TEST_SUB_ID_BASE + 21,
        transaction_identifier=f"{_TEST_TRANSACTION_PREFIX}contributor-update-001",
        contributor_name_raw="Test Contributor",
        contributor_city="Raleigh",
        contributor_state="NC",
        contributor_zip="27601",
    )
    transaction_id = upsert_transaction(db_conn, transaction)
    person_id = _insert_test_person(db_conn, "Contributor Update Person")

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                id,
                amount,
                contributor_name_raw,
                contributor_city,
                contributor_state,
                contributor_zip,
                contributor_person_id,
                contributor_organization_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (transaction_id,),
        )
        before_row = cursor.fetchone()
    assert before_row is not None

    updated = update_transaction_contributor_identity_ids(
        db_conn,
        transaction_id=transaction_id,
        contributor_person_id=person_id,
        contributor_organization_id=None,
    )
    assert updated is True

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                id,
                amount,
                contributor_name_raw,
                contributor_city,
                contributor_state,
                contributor_zip,
                contributor_person_id,
                contributor_organization_id
            FROM cf.transaction
            WHERE id = %s
            """,
            (transaction_id,),
        )
        after_row = cursor.fetchone()
    assert after_row is not None
    assert after_row["id"] == before_row["id"]
    assert after_row["amount"] == before_row["amount"]
    assert after_row["contributor_name_raw"] == before_row["contributor_name_raw"]
    assert after_row["contributor_city"] == before_row["contributor_city"]
    assert after_row["contributor_state"] == before_row["contributor_state"]
    assert after_row["contributor_zip"] == before_row["contributor_zip"]
    assert after_row["contributor_person_id"] == person_id
    assert after_row["contributor_organization_id"] is None


def test_update_transaction_contributor_identity_ids_is_idempotent_when_values_match(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = _insert_test_committee(db_conn, "Contributor IDs Idempotent", suffix=22)
    filing_id = _insert_test_filing(db_conn, committee_id, "contributor-identity-idempotent")
    person_id = _insert_test_person(db_conn, "Contributor Idempotent Person")
    transaction = _build_test_transaction(
        filing_id,
        committee_id,
        "92.00",
        sub_id=_TEST_SUB_ID_BASE + 22,
        transaction_identifier=f"{_TEST_TRANSACTION_PREFIX}contributor-idempotent-001",
        contributor_person_id=person_id,
    )
    transaction_id = upsert_transaction(db_conn, transaction)

    updated = update_transaction_contributor_identity_ids(
        db_conn,
        transaction_id=transaction_id,
        contributor_person_id=person_id,
        contributor_organization_id=None,
    )
    assert updated is False
