from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from core.entity_resolution import extract as extract_module
from core.entity_resolution.extract import (
    extract_rows_for_matching,
    extract_organizations_for_matching,
    extract_persons_for_matching,
    prepare_rows_for_probabilistic_scoring,
    restore_entity_id_from_probabilistic_row,
)
from domains.property.ingest.durham_source import (
    load_durham_fixture_records,
    normalize_durham_raw_records,
)
from domains.property.ingest.ingest_test_helpers import (
    DURHAM_EXPECTED_OWNER_ROWS,
    fixture_reids,
    owner_rows_from_er_views_by_source_record_keys,
)
from domains.property.ingest.loader import (
    ensure_durham_data_source,
    ensure_durham_jurisdiction,
    load_durham_records,
)

pytestmark = pytest.mark.integration

_PERSON_OUTPUT_COLUMNS = {
    "id",
    "canonical_name",
    "first_name",
    "last_name",
    "last_name_prefix5",
    "last_name_prefix3",
    "date_of_birth",
    "normalized_address",
    "street_number",
    "zip5",
    "state",
    "employer",
    "occupation",
    "identifier_key",
}

_ORGANIZATION_OUTPUT_COLUMNS = {
    "id",
    "canonical_name",
    "canonical_name_soundex",
    "name_prefix5",
    "registered_state",
    "normalized_address",
    "zip5",
    "org_type",
    "ein",
    "fec_committee_id",
    "registered_agent_name",
}


def _insert_address(
    db_conn: psycopg.Connection,
    *,
    raw_address: str,
    normalized_address: str,
    street_number: str,
    state: str,
    zip5: str,
) -> UUID:
    address_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.address (id, raw_address, normalized_address, street_number, state, zip5)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (address_id, raw_address, normalized_address, street_number, state, zip5),
    )
    return address_id


def _insert_person(
    db_conn: psycopg.Connection,
    *,
    person_id: UUID,
    canonical_name: str,
    first_name: str,
    last_name: str,
    date_of_birth: date | None,
    identifiers: dict[str, str],
) -> None:
    db_conn.execute(
        """
        INSERT INTO core.person (
            id,
            canonical_name,
            first_name,
            last_name,
            date_of_birth,
            identifiers
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (person_id, canonical_name, first_name, last_name, date_of_birth, Jsonb(identifiers)),
    )


def _link_person_address(db_conn: psycopg.Connection, *, person_id: UUID, address_id: UUID) -> None:
    db_conn.execute(
        """
        INSERT INTO core.entity_address (entity_type, entity_id, address_id, address_role, valid_period)
        VALUES ('person', %s, %s, 'mailing', daterange('2020-01-01', NULL, '[)'))
        """,
        (person_id, address_id),
    )


def _insert_organization(
    db_conn: psycopg.Connection,
    *,
    organization_id: UUID,
    canonical_name: str,
    registered_state: str,
    org_type: str,
    identifiers: dict[str, str],
) -> None:
    db_conn.execute(
        """
        INSERT INTO core.organization (
            id,
            canonical_name,
            registered_state,
            org_type,
            identifiers
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (organization_id, canonical_name, registered_state, org_type, Jsonb(identifiers)),
    )


def _link_organization_address(db_conn: psycopg.Connection, *, organization_id: UUID, address_id: UUID) -> None:
    db_conn.execute(
        """
        INSERT INTO core.entity_address (entity_type, entity_id, address_id, address_role, valid_period)
        VALUES ('organization', %s, %s, 'registered', daterange('2020-01-01', NULL, '[)'))
        """,
        (organization_id, address_id),
    )


def _organization_output_by_id(
    db_conn: psycopg.Connection,
    *,
    organization_id: UUID,
) -> dict[str, str | None]:
    rows = extract_organizations_for_matching(db_conn)
    row = next(result for result in rows if result["id"] == organization_id)
    return row


def test_extract_persons_for_matching_returns_expected_columns_and_values(
    db_conn: psycopg.Connection,
) -> None:
    person_with_stable_identifiers = uuid4()
    person_without_address = uuid4()

    address_id = _insert_address(
        db_conn,
        raw_address="123 Main St, Durham, NC 27701",
        normalized_address="123 MAIN ST DURHAM NC 27701",
        street_number="123",
        state="NC",
        zip5="27701",
    )

    _insert_person(
        db_conn,
        person_id=person_with_stable_identifiers,
        canonical_name="Alice Example",
        first_name="Alice",
        last_name="Example",
        date_of_birth=date(1985, 4, 12),
        identifiers={
            "fec_id": "FEC-123",
            "voter_reg_id": "VR-999",
            "employer": "Acme Corp",
            "occupation": "Engineer",
            "occupation_comments": "Senior",
            "llc_name": "Example Holdings LLC",
        },
    )
    _link_person_address(db_conn, person_id=person_with_stable_identifiers, address_id=address_id)

    _insert_person(
        db_conn,
        person_id=person_without_address,
        canonical_name="Bob Noaddress",
        first_name="Bob",
        last_name="Noaddress",
        date_of_birth=None,
        identifiers={
            "employer": "None",
            "occupation": "Unemployed",
        },
    )

    rows = extract_persons_for_matching(db_conn)
    matching_rows = [row for row in rows if row["id"] == person_with_stable_identifiers]
    no_address_row = next(row for row in rows if row["id"] == person_without_address)

    assert matching_rows
    for row in matching_rows:
        assert set(row.keys()) == _PERSON_OUTPUT_COLUMNS
        assert row["canonical_name"] == "Alice Example"
        assert row["last_name_prefix5"] == "Examp"
        assert row["last_name_prefix3"] == "Exa"
        assert row["normalized_address"] == "123 MAIN ST DURHAM NC 27701"
        assert row["street_number"] == "123"
        assert row["zip5"] == "27701"
        assert row["state"] == "NC"
        assert row["employer"] == "Acme Corp"
        assert row["occupation"] == "Engineer"

    identifier_keys = {row["identifier_key"] for row in matching_rows}
    assert identifier_keys == {"fec_id:FEC-123", "voter_reg_id:VR-999"}
    assert all(identifier_key.count(":") == 1 for identifier_key in identifier_keys)

    assert set(no_address_row.keys()) == _PERSON_OUTPUT_COLUMNS
    assert no_address_row["normalized_address"] is None
    assert no_address_row["street_number"] is None
    assert no_address_row["zip5"] is None
    assert no_address_row["state"] is None
    assert no_address_row["identifier_key"] is None


def test_extract_persons_for_matching_filters_blank_stable_identifiers(
    db_conn: psycopg.Connection,
) -> None:
    person_id = uuid4()

    _insert_person(
        db_conn,
        person_id=person_id,
        canonical_name="Casey Trimmed",
        first_name="Casey",
        last_name="Trimmed",
        date_of_birth=None,
        identifiers={
            "fec_id": "   ",
            "voter_reg_id": " VR-123 ",
            "employer": "Acme Corp",
        },
    )

    rows = [row for row in extract_persons_for_matching(db_conn) if row["id"] == person_id]

    assert rows == [
        {
            "id": person_id,
            "canonical_name": "Casey Trimmed",
            "first_name": "Casey",
            "last_name": "Trimmed",
            "last_name_prefix5": "Trimm",
            "last_name_prefix3": "Tri",
            "date_of_birth": None,
            "normalized_address": None,
            "street_number": None,
            "zip5": None,
            "state": None,
            "employer": "Acme Corp",
            "occupation": None,
            "identifier_key": "voter_reg_id:VR-123",
        }
    ]


def test_prepare_rows_for_probabilistic_scoring_keeps_duplicate_identifier_rows() -> None:
    person_id = uuid4()
    rows = [
        {
            "id": person_id,
            "canonical_name": "Casey Trimmed",
            "identifier_key": "fec_id:FEC-123",
        },
        {
            "id": person_id,
            "canonical_name": "Casey Trimmed",
            "identifier_key": "voter_reg_id:VR-123",
        },
    ]

    prepared_rows = prepare_rows_for_probabilistic_scoring(rows)

    assert prepared_rows == [
        {
            "id": f"{person_id}__splink_row__0",
            "canonical_name": "Casey Trimmed",
            "identifier_key": "fec_id:FEC-123",
        },
        {
            "id": f"{person_id}__splink_row__1",
            "canonical_name": "Casey Trimmed",
            "identifier_key": "voter_reg_id:VR-123",
        },
    ]


def test_prepare_rows_for_probabilistic_scoring_stringifies_unique_uuid_rows() -> None:
    first_id = uuid4()
    second_id = uuid4()
    rows = [
        {"id": first_id, "canonical_name": "Alpha", "identifier_key": None},
        {"id": second_id, "canonical_name": "Beta", "identifier_key": "ein:12-3456789"},
    ]

    prepared_rows = prepare_rows_for_probabilistic_scoring(rows)

    assert prepared_rows == [
        {"id": str(first_id), "canonical_name": "Alpha", "identifier_key": None},
        {"id": str(second_id), "canonical_name": "Beta", "identifier_key": "ein:12-3456789"},
    ]


def test_prepare_rows_for_probabilistic_scoring_preserves_shape_without_identifier_key() -> None:
    organization_id = uuid4()
    rows = [
        {"id": organization_id, "canonical_name": "Alpha Org", "ein": "12-3456789"},
        {"id": organization_id, "canonical_name": "Alpha Org", "ein": "12-3456789"},
    ]

    prepared_rows = prepare_rows_for_probabilistic_scoring(rows)

    assert prepared_rows == [
        {
            "id": f"{organization_id}__splink_row__0",
            "canonical_name": "Alpha Org",
            "ein": "12-3456789",
        },
        {
            "id": f"{organization_id}__splink_row__1",
            "canonical_name": "Alpha Org",
            "ein": "12-3456789",
        },
    ]


def test_restore_entity_id_from_probabilistic_row_returns_original_uuid() -> None:
    entity_id = uuid4()

    restored_id = restore_entity_id_from_probabilistic_row(f"{entity_id}__splink_row__2")

    assert restored_id == entity_id


def test_restore_entity_id_from_probabilistic_row_parses_plain_uuid_strings() -> None:
    entity_id = uuid4()

    restored_id = restore_entity_id_from_probabilistic_row(str(entity_id))

    assert restored_id == entity_id


def test_extract_organizations_for_matching_returns_expected_columns_and_values(
    db_conn: psycopg.Connection,
) -> None:
    organization_id = uuid4()
    address_id = _insert_address(
        db_conn,
        raw_address="500 Oak Rd, Raleigh, NC 27601",
        normalized_address="500 OAK RD RALEIGH NC 27601",
        street_number="500",
        state="NC",
        zip5="27601",
    )

    _insert_organization(
        db_conn,
        organization_id=organization_id,
        canonical_name="Example Action Committee",
        registered_state="NC",
        org_type="pac",
        identifiers={
            "ein": "12-3456789",
            "fec_committee_id": "C12345678",
            "registered_agent_name": "Jordan Agent",
        },
    )
    _link_organization_address(db_conn, organization_id=organization_id, address_id=address_id)

    row = _organization_output_by_id(db_conn, organization_id=organization_id)

    assert set(row.keys()) == _ORGANIZATION_OUTPUT_COLUMNS
    assert row["canonical_name"] == "Example Action Committee"
    assert row["name_prefix5"] == "Examp"
    assert row["registered_state"] == "NC"
    assert row["normalized_address"] == "500 OAK RD RALEIGH NC 27601"
    assert row["zip5"] == "27601"
    assert row["org_type"] == "pac"
    assert row["ein"] == "12-3456789"
    assert row["fec_committee_id"] == "C12345678"
    assert row["registered_agent_name"] == "Jordan Agent"

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT SOUNDEX(%s) AS soundex", ("Example Action Committee",))
        expected_soundex = cursor.fetchone()["soundex"]

    assert row["canonical_name_soundex"] == expected_soundex


def test_extract_organizations_for_matching_includes_orgs_without_addresses(
    db_conn: psycopg.Connection,
) -> None:
    organization_id = uuid4()

    _insert_organization(
        db_conn,
        organization_id=organization_id,
        canonical_name="No Address Org",
        registered_state="NC",
        org_type="nonprofit",
        identifiers={"ein": "98-7654321"},
    )

    row = _organization_output_by_id(db_conn, organization_id=organization_id)

    assert row["normalized_address"] is None
    assert row["zip5"] is None


def test_extract_functions_include_durham_fixture_owners_via_shared_er_views(
    db_conn: psycopg.Connection,
) -> None:
    records = normalize_durham_raw_records(load_durham_fixture_records())
    reids = fixture_reids(records)
    data_source_id = ensure_durham_data_source(db_conn)
    jurisdiction_id = ensure_durham_jurisdiction(db_conn)

    inserted, skipped, errors = load_durham_records(db_conn, data_source_id, jurisdiction_id, records)
    assert (inserted, skipped, errors) == (len(records), 0, 0)

    owner_rows = owner_rows_from_er_views_by_source_record_keys(db_conn, data_source_id, reids)
    observed_owner_rows = {
        (row["source_record_key"], row["entity_type"], row["owner_name_as_filed"]) for row in owner_rows
    }
    assert observed_owner_rows == DURHAM_EXPECTED_OWNER_ROWS

    expected_person_owner_ids = {row["entity_id"] for row in owner_rows if row["entity_type"] == "person"}
    expected_organization_owner_ids = {row["entity_id"] for row in owner_rows if row["entity_type"] == "organization"}
    expected_person_owner_identifiers = {
        f"owner_name_as_filed:{row['owner_name_as_filed']}" for row in owner_rows if row["entity_type"] == "person"
    }
    expected_organization_owner_names = {
        row["canonical_name"] for row in owner_rows if row["entity_type"] == "organization"
    }

    person_rows = extract_persons_for_matching(db_conn)
    organization_rows = extract_organizations_for_matching(db_conn)
    person_rows_from_consumer = extract_rows_for_matching(db_conn, "person")
    organization_rows_from_consumer = extract_rows_for_matching(db_conn, "organization")

    durham_person_rows = [row for row in person_rows if row["id"] in expected_person_owner_ids]
    durham_organization_rows = [row for row in organization_rows if row["id"] in expected_organization_owner_ids]

    assert {row["id"] for row in durham_person_rows} == expected_person_owner_ids
    assert {row["id"] for row in durham_organization_rows} == expected_organization_owner_ids
    assert {row["identifier_key"] for row in durham_person_rows} == expected_person_owner_identifiers
    assert {row["canonical_name"] for row in durham_organization_rows} == expected_organization_owner_names

    for row in durham_person_rows:
        assert set(row.keys()) == _PERSON_OUTPUT_COLUMNS
    for row in durham_organization_rows:
        assert set(row.keys()) == _ORGANIZATION_OUTPUT_COLUMNS

    assert {
        (row["id"], row["identifier_key"])
        for row in person_rows_from_consumer
        if row["id"] in expected_person_owner_ids
    } == {(row["id"], row["identifier_key"]) for row in durham_person_rows}
    assert {
        (row["id"], row["canonical_name"])
        for row in organization_rows_from_consumer
        if row["id"] in expected_organization_owner_ids
    } == {(row["id"], row["canonical_name"]) for row in durham_organization_rows}


def test_extract_rows_for_matching_dispatches_to_entity_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = object()

    person_rows = [{"id": uuid4(), "canonical_name": "Person Example"}]
    organization_rows = [{"id": uuid4(), "canonical_name": "Organization Example"}]

    person_calls = 0
    organization_calls = 0

    def _fake_extract_persons_for_matching(incoming_conn: object) -> list[dict[str, object]]:
        nonlocal person_calls
        person_calls += 1
        assert incoming_conn is conn
        return person_rows

    def _fake_extract_organizations_for_matching(
        incoming_conn: object,
    ) -> list[dict[str, object]]:
        nonlocal organization_calls
        organization_calls += 1
        assert incoming_conn is conn
        return organization_rows

    monkeypatch.setattr(
        extract_module,
        "extract_persons_for_matching",
        _fake_extract_persons_for_matching,
    )
    monkeypatch.setattr(
        extract_module,
        "extract_organizations_for_matching",
        _fake_extract_organizations_for_matching,
    )

    assert extract_rows_for_matching(conn, "person") == person_rows
    assert extract_rows_for_matching(conn, "organization") == organization_rows
    assert person_calls == 1
    assert organization_calls == 1


@pytest.mark.parametrize(
    "entity_type",
    ["committee", "office", "electoral_division", "contest", "candidacy", "officeholding"],
)
def test_extract_rows_for_matching_rejects_unsupported_entity_type(entity_type: str) -> None:
    with pytest.raises(
        ValueError,
        match=rf"entity_type must be 'person' or 'organization', got '{entity_type}'",
    ):
        extract_rows_for_matching(object(), entity_type)
