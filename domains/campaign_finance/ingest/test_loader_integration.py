from __future__ import annotations

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from core.types.python.models import compute_record_hash
from domains.campaign_finance.entity_extractors.extract import extract_contribution
from domains.campaign_finance.ingest.loader import ensure_fec_data_source, load_contribution
from test_support.fec_fixtures import clone_with_unique_sub_id, load_fixture_results


pytestmark = pytest.mark.integration


def _find_two_records_with_shared_committee(records: list[dict]) -> tuple[dict, dict]:
    records_by_committee_id: dict[str, list[dict]] = {}
    for record in records:
        committee_id = record.get("committee_id")
        if not committee_id:
            continue
        records_by_committee_id.setdefault(committee_id, []).append(record)

    for matching_records in records_by_committee_id.values():
        if len(matching_records) >= 2:
            return matching_records[0], matching_records[1]

    raise AssertionError("Fixture must include at least two records with the same committee_id")


def test_ensure_fec_data_source_is_idempotent(db_conn: psycopg.Connection) -> None:
    first_id = ensure_fec_data_source(db_conn)
    second_id = ensure_fec_data_source(db_conn)

    assert second_id == first_id
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            """,
            ("campaign_finance", "federal/fec", "FEC Schedule A API"),
        )
        data_source_count = cursor.fetchone()["count"]

    assert data_source_count == 1


def test_load_contribution_round_trip(db_conn: psycopg.Connection) -> None:
    contribution = clone_with_unique_sub_id(load_fixture_results()[0])
    extracted = extract_contribution(contribution)

    data_source_id = ensure_fec_data_source(db_conn)
    loaded = load_contribution(db_conn, data_source_id, contribution)
    assert loaded is True

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash
            FROM core.source_record
            WHERE data_source_id = %s AND source_record_key = %s
            """,
            (data_source_id, contribution["sub_id"]),
        )
        source_record = cursor.fetchone()

    assert source_record is not None
    source_record_id = source_record["id"]
    assert source_record["source_record_key"] == contribution["sub_id"]
    assert source_record["record_hash"] == compute_record_hash(contribution)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT p.canonical_name
            FROM core.entity_source es
            JOIN core.person p ON p.id = es.entity_id
            WHERE es.source_record_id = %s
              AND es.entity_type = 'person'
              AND es.extraction_role = 'donor'
            """,
            (source_record_id,),
        )
        person_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT o.canonical_name, o.identifiers
            FROM core.entity_source es
            JOIN core.organization o ON o.id = es.entity_id
            WHERE es.source_record_id = %s
              AND es.entity_type = 'organization'
              AND es.extraction_role = 'recipient'
            """,
            (source_record_id,),
        )
        organization_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT a.id, a.raw_address, a.state, a.zip5
            FROM core.entity_source es
            JOIN core.address a ON a.id = es.entity_id
            WHERE es.source_record_id = %s
              AND es.entity_type = 'address'
              AND es.extraction_role = 'contributor_address'
            """,
            (source_record_id,),
        )
        address_row = cursor.fetchone()

    assert organization_row is not None
    assert organization_row["canonical_name"] == extracted["organization"].canonical_name
    assert (
        organization_row["identifiers"]["fec_committee_id"] == extracted["organization"].identifiers["fec_committee_id"]
    )

    expected_person = extracted["person"]
    if expected_person is not None:
        assert person_row is not None
        assert person_row["canonical_name"] == expected_person.canonical_name
    else:
        assert person_row is None

    expected_address = extracted["address"]
    if expected_address is not None:
        assert address_row is not None
        assert address_row["raw_address"] == expected_address.raw_address
        assert address_row["state"] == expected_address.state
        assert address_row["zip5"] == expected_address.zip5

        with db_conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id
                FROM core.entity_address
                WHERE entity_type = 'person'
                  AND address_id = %s
                """,
                (address_row["id"],),
            )
            person_address_link = cursor.fetchone()
        if expected_person is not None:
            assert person_address_link is not None
    else:
        assert address_row is None


def test_load_idempotent(db_conn: psycopg.Connection) -> None:
    contribution = clone_with_unique_sub_id(load_fixture_results()[0])
    data_source_id = ensure_fec_data_source(db_conn)
    extracted = extract_contribution(contribution)

    first_load = load_contribution(db_conn, data_source_id, contribution)
    second_load = load_contribution(db_conn, data_source_id, contribution)
    assert first_load is True
    assert second_load is False

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS count FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
            (data_source_id, contribution["sub_id"]),
        )
        source_record_count = cursor.fetchone()["count"]

        fec_committee_id = extracted["organization"].identifiers["fec_committee_id"]
        cursor.execute(
            "SELECT COUNT(*) AS count FROM core.organization WHERE identifiers @> %s",
            (Jsonb({"fec_committee_id": fec_committee_id}),),
        )
        organization_count = cursor.fetchone()["count"]

        if extracted["person"] is not None:
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM core.person
                WHERE first_name = %s AND last_name = %s
                """,
                (extracted["person"].first_name, extracted["person"].last_name),
            )
            person_count = cursor.fetchone()["count"]
        else:
            person_count = 0

        if extracted["address"] is not None:
            cursor.execute(
                "SELECT COUNT(*) AS count FROM core.address WHERE raw_address = %s",
                (extracted["address"].raw_address,),
            )
            address_count = cursor.fetchone()["count"]
        else:
            address_count = 0

    assert source_record_count == 1
    assert organization_count == 1
    if extracted["person"] is not None:
        assert person_count == 1
    if extracted["address"] is not None:
        assert address_count == 1


def test_load_multiple_contributions_shared_committee(db_conn: psycopg.Connection) -> None:
    records = load_fixture_results()
    base_first_record, base_second_record = _find_two_records_with_shared_committee(records)
    first_record = clone_with_unique_sub_id(base_first_record)
    second_record = clone_with_unique_sub_id(base_second_record)
    data_source_id = ensure_fec_data_source(db_conn)

    load_contribution(db_conn, data_source_id, first_record)
    load_contribution(db_conn, data_source_id, second_record)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS count FROM core.organization WHERE identifiers @> %s",
            (Jsonb({"fec_committee_id": first_record["committee_id"]}),),
        )
        organization_count = cursor.fetchone()["count"]

    assert organization_count == 1
