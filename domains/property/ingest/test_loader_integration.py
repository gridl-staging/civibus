from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from domains.property.ingest.durham_source import (
    build_durham_source_url,
    load_durham_config,
    load_durham_fixture_records,
    normalize_durham_raw_records,
)
from domains.property.ingest.ingest_test_helpers import (
    DURHAM_EXPECTED_OWNER_ROWS,
    fixture_reids,
    fixture_row_counts,
    owner_rows_from_er_views_by_source_record_keys,
)
from domains.property.ingest.loader import (
    ensure_durham_data_source,
    ensure_durham_jurisdiction,
    load_durham_record,
    load_durham_records,
)

pytestmark = pytest.mark.integration


def _fixture_records() -> list[dict[str, object]]:
    return normalize_durham_raw_records(load_durham_fixture_records())


def _assert_entity_source_linked(
    cursor: psycopg.Cursor,
    entity_type: str,
    entity_id: object,
    source_record_id: UUID,
    extraction_role: str,
) -> None:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM core.entity_source
        WHERE entity_type = %s
          AND entity_id = %s
          AND source_record_id = %s
          AND extraction_role = %s
        """,
        (entity_type, entity_id, source_record_id, extraction_role),
    )
    row = cursor.fetchone()
    assert row is not None and row[0] == 1


def _assert_entity_address_linked(
    cursor: psycopg.Cursor,
    entity_type: str,
    entity_id: object,
    address_id: object,
    source_record_id: UUID,
    address_role: str,
) -> None:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM core.entity_address
        WHERE entity_type = %s
            AND entity_id = %s
            AND address_id = %s
            AND source_record_id = %s
            AND address_role = %s
        """,
        (entity_type, entity_id, address_id, source_record_id, address_role),
    )
    row = cursor.fetchone()
    assert row is not None and row[0] == 1


def test_load_durham_fixture_persists_property_rows_and_provenance(db_conn: psycopg.Connection) -> None:
    records = _fixture_records()
    data_source_id = ensure_durham_data_source(db_conn)
    jurisdiction_id = ensure_durham_jurisdiction(db_conn)

    inserted, skipped, errors = load_durham_records(db_conn, data_source_id, jurisdiction_id, records)

    assert inserted == len(records)
    assert skipped == 0
    assert errors == 0

    reids = fixture_reids(records)
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT p.reid, p.jurisdiction_id, p.source_record_id, sr.source_record_key
            FROM prop.parcel p
            JOIN core.source_record sr ON sr.id = p.source_record_id
            WHERE p.reid = ANY(%s)
            ORDER BY p.reid
            """,
            (reids,),
        )
        parcel_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM prop.assessment a
            JOIN prop.parcel p ON p.id = a.parcel_id
            WHERE p.reid = ANY(%s)
            """,
            (reids,),
        )
        assessment_count_row = cursor.fetchone()
        assert assessment_count_row is not None
        assessment_count = assessment_count_row["count"]

        cursor.execute(
            """
            SELECT id, owner_person_id, owner_organization_id, source_record_id
            FROM prop.ownership
            WHERE parcel_id IN (
                SELECT id FROM prop.parcel WHERE reid = ANY(%s)
            )
            """,
            (reids,),
        )
        ownership_rows = cursor.fetchall()

    assert len(parcel_rows) == len(records)
    assert assessment_count == 1
    assert len(ownership_rows) >= len(records)

    for parcel_row in parcel_rows:
        assert parcel_row["jurisdiction_id"] == jurisdiction_id
        assert parcel_row["source_record_id"] is not None
        assert parcel_row["source_record_key"] == parcel_row["reid"]

    for ownership_row in ownership_rows:
        owner_person_id = ownership_row["owner_person_id"]
        owner_organization_id = ownership_row["owner_organization_id"]
        source_record_id = ownership_row["source_record_id"]
        assert source_record_id is not None

        with db_conn.cursor() as cursor:
            if owner_person_id is not None:
                _assert_entity_source_linked(cursor, "person", owner_person_id, source_record_id, "owner")
            if owner_organization_id is not None:
                _assert_entity_source_linked(cursor, "organization", owner_organization_id, source_record_id, "owner")


def test_load_durham_fixture_source_records_have_pin_specific_source_urls(db_conn: psycopg.Connection) -> None:
    records = _fixture_records()
    reids = fixture_reids(records)
    data_source_id = ensure_durham_data_source(db_conn)
    jurisdiction_id = ensure_durham_jurisdiction(db_conn)

    inserted, skipped, errors = load_durham_records(db_conn, data_source_id, jurisdiction_id, records)

    assert inserted == len(records)
    assert skipped == 0
    assert errors == 0

    expected_pin_by_reid = {str(record["reid"]): str(record["pin"]) for record in records}
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_record_key, source_url
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
            ORDER BY source_record_key
            """,
            (data_source_id, reids),
        )
        source_records = cursor.fetchall()

    assert len(source_records) == len(records)
    for source_record in source_records:
        record_key = source_record["source_record_key"]
        source_url = source_record["source_url"]
        assert record_key is not None
        assert source_url is not None
        assert expected_pin_by_reid[record_key] in source_url


def test_fixture_owner_entities_are_visible_in_shared_er_views(db_conn: psycopg.Connection) -> None:
    records = _fixture_records()
    reids = fixture_reids(records)
    data_source_id = ensure_durham_data_source(db_conn)
    jurisdiction_id = ensure_durham_jurisdiction(db_conn)

    inserted, skipped, errors = load_durham_records(db_conn, data_source_id, jurisdiction_id, records)
    assert (inserted, skipped, errors) == (len(records), 0, 0)

    owner_rows = owner_rows_from_er_views_by_source_record_keys(db_conn, data_source_id, reids)
    assert len(owner_rows) == len(DURHAM_EXPECTED_OWNER_ROWS)
    for row in owner_rows:
        assert row["source_record_key"] is not None
        assert row["entity_type"] is not None
        assert row["owner_name_as_filed"] is not None
        assert row["canonical_name"] is not None

    observed_owner_rows = {
        (row["source_record_key"], row["entity_type"], row["owner_name_as_filed"]) for row in owner_rows
    }
    assert observed_owner_rows == DURHAM_EXPECTED_OWNER_ROWS
    assert {row["canonical_name"] for row in owner_rows} == {
        "Smith John",
        "Doe Jane",
        "Duke University",
    }


def test_fixture_owner_entities_are_scoped_to_durham_data_source(
    db_conn: psycopg.Connection,
) -> None:
    records = _fixture_records()
    reids = fixture_reids(records)
    data_source_id = ensure_durham_data_source(db_conn)
    jurisdiction_id = ensure_durham_jurisdiction(db_conn)

    inserted, skipped, errors = load_durham_records(db_conn, data_source_id, jurisdiction_id, records)
    assert (inserted, skipped, errors) == (len(records), 0, 0)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            """,
            (data_source_id, reids[0]),
        )
        active_source_record_row = cursor.fetchone()

    assert active_source_record_row is not None

    colliding_data_source_id = uuid4()
    colliding_source_record_id = uuid4()
    colliding_person_id = uuid4()
    superseded_source_record_id = uuid4()
    superseded_person_id = uuid4()
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core.data_source (id, domain, jurisdiction, name, source_url)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                colliding_data_source_id,
                "campaign_finance",
                "federal/fec",
                "Collision Source",
                "https://example.com/collision-source",
            ),
        )
        cursor.execute(
            """
            INSERT INTO core.source_record (
                id,
                data_source_id,
                source_record_key,
                source_url,
                raw_fields,
                pull_date,
                record_hash
            )
            VALUES (%s, %s, %s, %s, %s, NOW(), %s)
            """,
            (
                colliding_source_record_id,
                colliding_data_source_id,
                reids[0],
                "https://example.com/collision-source/100000001",
                Jsonb({"source_record_key": reids[0]}),
                "collision-source-record-hash",
            ),
        )
        cursor.execute(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                colliding_person_id,
                "Collision Person",
                "Collision",
                "Person",
                Jsonb({"owner_name_as_filed": "COLLISION PERSON"}),
            ),
        )
        cursor.execute(
            """
            INSERT INTO core.entity_source (entity_type, entity_id, source_record_id, extraction_role)
            VALUES ('person', %s, %s, 'owner')
            """,
            (colliding_person_id, colliding_source_record_id),
        )
        cursor.execute(
            """
            INSERT INTO core.source_record (
                id,
                data_source_id,
                source_record_key,
                source_url,
                raw_fields,
                pull_date,
                record_hash,
                superseded_by
            )
            VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s)
            """,
            (
                superseded_source_record_id,
                data_source_id,
                reids[0],
                "https://example.com/durham-source/100000001/superseded",
                Jsonb({"source_record_key": reids[0], "version": "superseded"}),
                "superseded-source-record-hash",
                active_source_record_row["id"],
            ),
        )
        cursor.execute(
            """
            INSERT INTO core.person (id, canonical_name, first_name, last_name, identifiers)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                superseded_person_id,
                "Superseded Person",
                "Superseded",
                "Person",
                Jsonb({"owner_name_as_filed": "SUPERSEDED PERSON"}),
            ),
        )
        cursor.execute(
            """
            INSERT INTO core.entity_source (entity_type, entity_id, source_record_id, extraction_role)
            VALUES ('person', %s, %s, 'owner')
            """,
            (superseded_person_id, superseded_source_record_id),
        )

    owner_rows = owner_rows_from_er_views_by_source_record_keys(db_conn, data_source_id, reids)

    assert {
        (row["source_record_key"], row["entity_type"], row["owner_name_as_filed"]) for row in owner_rows
    } == DURHAM_EXPECTED_OWNER_ROWS
    assert {row["canonical_name"] for row in owner_rows} == {
        "Smith John",
        "Doe Jane",
        "Duke University",
    }


def test_pending_and_exempt_parcels_do_not_get_null_assessment_rows(db_conn: psycopg.Connection) -> None:
    records = _fixture_records()
    data_source_id = ensure_durham_data_source(db_conn)
    jurisdiction_id = ensure_durham_jurisdiction(db_conn)

    load_durham_records(db_conn, data_source_id, jurisdiction_id, records)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT p.reid, COUNT(a.id)::int AS assessment_count
            FROM prop.parcel p
            LEFT JOIN prop.assessment a ON a.parcel_id = p.id
            WHERE p.reid IN ('100000002', '100000003')
            GROUP BY p.reid
            ORDER BY p.reid
            """
        )
        rows = cursor.fetchall()

    assert rows == [
        {"reid": "100000002", "assessment_count": 0},
        {"reid": "100000003", "assessment_count": 0},
    ]


def test_load_durham_records_is_idempotent_by_source_record_key(db_conn: psycopg.Connection) -> None:
    records = _fixture_records()
    data_source_id = ensure_durham_data_source(db_conn)
    jurisdiction_id = ensure_durham_jurisdiction(db_conn)

    first_inserted, first_skipped, first_errors = load_durham_records(db_conn, data_source_id, jurisdiction_id, records)
    reids = fixture_reids(records)
    expected_counts_after_first_load = fixture_row_counts(db_conn, data_source_id, reids)
    second_inserted, second_skipped, second_errors = load_durham_records(
        db_conn,
        data_source_id,
        jurisdiction_id,
        records,
    )

    assert first_inserted == len(records)
    assert first_skipped == 0
    assert first_errors == 0
    assert second_inserted == 0
    assert second_skipped == len(records)
    assert second_errors == 0

    counts_after_second_load = fixture_row_counts(db_conn, data_source_id, reids)

    assert expected_counts_after_first_load == {
        "core.source_record": 3,
        "prop.parcel": 3,
        "prop.assessment": 1,
        "prop.ownership": 3,
        "core.entity_source": 6,
        "core.entity_address": 3,
    }
    assert counts_after_second_load == expected_counts_after_first_load


@pytest.mark.parametrize("mutation_kind", ["hash", "url"])
def test_load_durham_record_fails_fast_when_existing_key_payload_changes(
    db_conn: psycopg.Connection,
    mutation_kind: str,
) -> None:
    records = _fixture_records()
    reids = fixture_reids(records)
    data_source_id = ensure_durham_data_source(db_conn)
    jurisdiction_id = ensure_durham_jurisdiction(db_conn)

    inserted, skipped, errors = load_durham_records(db_conn, data_source_id, jurisdiction_id, records)
    assert (inserted, skipped, errors) == (len(records), 0, 0)

    updated_record = deepcopy(records[0])
    if mutation_kind == "hash":
        raw_record = dict(updated_record["raw_record"])
        raw_record["PROPERTY_DESCRIPTION"] = "UPDATED DURHAM DESCRIPTION"
        updated_record["raw_record"] = raw_record
    else:
        updated_record["pin"] = "0999999999"
        updated_record["source_url"] = build_durham_source_url("0999999999")

    with pytest.raises(ValueError, match="conflicting source payload"):
        load_durham_record(db_conn, data_source_id, jurisdiction_id, updated_record)

    assert fixture_row_counts(db_conn, data_source_id, reids) == {
        "core.source_record": 3,
        "prop.parcel": 3,
        "prop.assessment": 1,
        "prop.ownership": 3,
        "core.entity_source": 6,
        "core.entity_address": 3,
    }


def test_fixture_records_share_one_coherent_source_record_chain(db_conn: psycopg.Connection) -> None:
    records = _fixture_records()
    reids = fixture_reids(records)
    data_source_id = ensure_durham_data_source(db_conn)
    jurisdiction_id = ensure_durham_jurisdiction(db_conn)

    inserted, skipped, errors = load_durham_records(db_conn, data_source_id, jurisdiction_id, records)
    assert (inserted, skipped, errors) == (len(records), 0, 0)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, reid, is_pending, source_record_id
            FROM prop.parcel
            WHERE reid = ANY(%s)
            ORDER BY reid
            """,
            (reids,),
        )
        parcels = cursor.fetchall()

    assert len(parcels) == len(records)

    for parcel in parcels:
        parcel_id = parcel["id"]
        parcel_source_record_id = parcel["source_record_id"]
        assert parcel_source_record_id is not None

        with db_conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT source_record_id
                FROM prop.assessment
                WHERE parcel_id = %s
                """,
                (parcel_id,),
            )
            assessment_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT owner_person_id, owner_organization_id, owner_address_id, source_record_id
                FROM prop.ownership
                WHERE parcel_id = %s
                """,
                (parcel_id,),
            )
            ownership_rows = cursor.fetchall()

        if parcel["reid"] == "100000001":
            assert len(assessment_rows) == 1
        else:
            assert len(assessment_rows) == 0

        for assessment in assessment_rows:
            assert assessment["source_record_id"] == parcel_source_record_id

        assert len(ownership_rows) >= 1
        for ownership in ownership_rows:
            assert ownership["source_record_id"] == parcel_source_record_id

            owner_person_id = ownership["owner_person_id"]
            owner_organization_id = ownership["owner_organization_id"]
            owner_address_id = ownership["owner_address_id"]

            with db_conn.cursor() as cursor:
                if owner_person_id is not None:
                    _assert_entity_source_linked(cursor, "person", owner_person_id, parcel_source_record_id, "owner")
                    if owner_address_id is not None:
                        _assert_entity_address_linked(
                            cursor, "person", owner_person_id, owner_address_id, parcel_source_record_id, "mailing"
                        )

                if owner_organization_id is not None:
                    _assert_entity_source_linked(
                        cursor, "organization", owner_organization_id, parcel_source_record_id, "owner"
                    )
                    if owner_address_id is not None:
                        _assert_entity_address_linked(
                            cursor,
                            "organization",
                            owner_organization_id,
                            owner_address_id,
                            parcel_source_record_id,
                            "mailing",
                        )

                if owner_address_id is not None:
                    _assert_entity_source_linked(
                        cursor, "address", owner_address_id, parcel_source_record_id, "owner_mailing_address"
                    )


def test_ensure_durham_data_source_refreshes_existing_metadata_from_config(db_conn: psycopg.Connection) -> None:
    config = load_durham_config()
    source = config["source"]
    jurisdiction = config["jurisdiction"]

    assert isinstance(source, dict)
    assert isinstance(jurisdiction, dict)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            INSERT INTO core.data_source (
                domain,
                jurisdiction,
                name,
                source_url,
                source_format,
                license,
                update_frequency
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                "property",
                jurisdiction["slug"],
                source["name"],
                "https://stale.example/query",
                "csv",
                "restricted",
                "annual",
            ),
        )
        existing_row = cursor.fetchone()

    assert existing_row is not None
    data_source_id = existing_row["id"]

    resolved_id = ensure_durham_data_source(db_conn, config)

    assert resolved_id == data_source_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_url, source_format, license, update_frequency
            FROM core.data_source
            WHERE id = %s
            """,
            (data_source_id,),
        )
        refreshed_row = cursor.fetchone()

    assert refreshed_row == {
        "source_url": source["arcgis_query_url"],
        "source_format": source["source_format"],
        "license": source["license"],
        "update_frequency": source["update_frequency"],
    }


def test_ensure_durham_jurisdiction_refreshes_existing_metadata_from_config(db_conn: psycopg.Connection) -> None:
    config = load_durham_config()
    jurisdiction = config["jurisdiction"]
    assert isinstance(jurisdiction, dict)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            INSERT INTO core.jurisdiction (name, jurisdiction_type, fips, state)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            ("Old Durham Label", "municipality", jurisdiction["fips"], "SC"),
        )
        existing_row = cursor.fetchone()

    assert existing_row is not None
    jurisdiction_id = existing_row["id"]

    resolved_id = ensure_durham_jurisdiction(db_conn, config)

    assert resolved_id == jurisdiction_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT name, jurisdiction_type, fips, state
            FROM core.jurisdiction
            WHERE id = %s
            """,
            (jurisdiction_id,),
        )
        refreshed_row = cursor.fetchone()

    assert refreshed_row == {
        "name": jurisdiction["name"],
        "jurisdiction_type": jurisdiction["type"],
        "fips": jurisdiction["fips"],
        "state": jurisdiction["state"],
    }
