from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.entity_resolution.persist import persist_auto_merge_clusters
from core.entity_resolution.test_persist import (
    _create_org,
    _create_person,
    _insert_data_source,
    _insert_entity_source,
    _insert_source_record,
)

pytestmark = pytest.mark.integration

_PERSON_NAME_SUFFIXES = ("Alpha", "Beta", "Gamma", "Delta", "Echo")


def _cluster_component(
    *,
    canonical_entity_id: UUID,
    member_ids: set[UUID],
    min_confidence: float,
) -> dict[str, object]:
    return {
        "canonical_entity_id": canonical_entity_id,
        "member_ids": member_ids,
        "min_confidence": min_confidence,
        "min_decision": "match",
        "links": [],
    }


def _setup_people_with_individual_sources(
    db_conn: psycopg.Connection,
    *,
    scenario_prefix: str,
    count: int,
) -> tuple[list[UUID], list[UUID]]:
    if count > len(_PERSON_NAME_SUFFIXES):
        raise ValueError(f"count must be <= {len(_PERSON_NAME_SUFFIXES)}")

    person_ids = [uuid4() for _ in range(count)]
    data_source_id = _insert_data_source(db_conn, name=f"{scenario_prefix.lower()}-source")
    source_record_ids = [
        _insert_source_record(
            db_conn,
            data_source_id=data_source_id,
            source_record_key=f"{scenario_prefix.lower()}-{suffix.lower()}",
        )
        for suffix in _PERSON_NAME_SUFFIXES[:count]
    ]
    for person_id, suffix, source_record_id in zip(
        person_ids,
        _PERSON_NAME_SUFFIXES[:count],
        source_record_ids,
        strict=True,
    ):
        _create_person(db_conn, person_id=person_id, name=f"{scenario_prefix} {suffix}")
        _insert_entity_source(
            db_conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role="donor",
        )
    return person_ids, source_record_ids


def _setup_three_people_with_shared_source(
    db_conn: psycopg.Connection,
    *,
    scenario_prefix: str,
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
    person_a = uuid4()
    person_b = uuid4()
    person_c = uuid4()
    _create_person(db_conn, person_id=person_a, name=f"{scenario_prefix} Alpha")
    _create_person(db_conn, person_id=person_b, name=f"{scenario_prefix} Beta")
    _create_person(db_conn, person_id=person_c, name=f"{scenario_prefix} Gamma")

    data_source_id = _insert_data_source(db_conn, name=f"{scenario_prefix.lower()}-source")
    source_a = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key=f"{scenario_prefix.lower()}-a"
    )
    source_b = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key=f"{scenario_prefix.lower()}-b"
    )
    source_c = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key=f"{scenario_prefix.lower()}-c"
    )
    source_shared = _insert_source_record(
        db_conn,
        data_source_id=data_source_id,
        source_record_key=f"{scenario_prefix.lower()}-shared",
    )

    for entity_id, source_record_id in (
        (person_a, source_a),
        (person_b, source_b),
        (person_c, source_c),
        (person_a, source_shared),
        (person_c, source_shared),
    ):
        _insert_entity_source(
            db_conn,
            entity_type="person",
            entity_id=entity_id,
            source_record_id=source_record_id,
            extraction_role="donor",
        )

    return person_a, person_b, person_c, source_a, source_b, source_c, source_shared


def _fetch_person_source_rows_by_source_record(
    db_conn: psycopg.Connection,
    *,
    source_record_id: UUID,
) -> list[dict[str, object]]:
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id, source_record_id, extracted_fields
            FROM core.entity_source
            WHERE entity_type = 'person'
              AND source_record_id = %s
              AND extraction_role = 'donor'
            ORDER BY entity_id
            """,
            (source_record_id,),
        )
        return cursor.fetchall()


def test_persist_auto_merge_clusters_inserts_cluster_members_updates_entities_and_relinks_sources(
    db_conn: psycopg.Connection,
) -> None:
    people, _ = _setup_people_with_individual_sources(
        db_conn,
        scenario_prefix="Cluster",
        count=3,
    )
    canonical_id, member_b, member_c = people

    data_source_id = _insert_data_source(db_conn, name="cluster-dup-source")
    source_dup = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="cluster-dup")
    # Duplicate link role/source between canonical and non-canonical; non-canonical row must be deleted.
    _insert_entity_source(
        db_conn,
        entity_type="person",
        entity_id=canonical_id,
        source_record_id=source_dup,
        extraction_role="donor",
    )
    _insert_entity_source(
        db_conn,
        entity_type="person",
        entity_id=member_b,
        source_record_id=source_dup,
        extraction_role="donor",
    )

    cluster_ids = persist_auto_merge_clusters(
        db_conn,
        [
            _cluster_component(
                canonical_entity_id=canonical_id, member_ids={canonical_id, member_b, member_c}, min_confidence=0.97
            )
        ],
        "person",
    )

    assert len(cluster_ids) == 1
    cluster_id = cluster_ids[0]

    cluster_row = db_conn.execute(
        """
        SELECT canonical_entity_id, cluster_confidence, member_count
        FROM core.entity_cluster
        WHERE id = %s
        """,
        (cluster_id,),
    ).fetchone()
    assert cluster_row is not None
    assert cluster_row[0] == canonical_id
    assert cluster_row[1] == pytest.approx(0.97)
    assert cluster_row[2] == 3

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id, is_canonical, split_at
            FROM core.cluster_member
            WHERE cluster_id = %s
            ORDER BY entity_id
            """,
            (cluster_id,),
        )
        member_rows = cursor.fetchall()
    assert len(member_rows) == 3
    assert sum(1 for row in member_rows if row["is_canonical"]) == 1
    assert next(row for row in member_rows if row["is_canonical"])["entity_id"] == canonical_id
    assert all(row["split_at"] is None for row in member_rows)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, er_cluster_id, er_confidence
            FROM core.person
            WHERE id IN (%s, %s, %s)
            ORDER BY id
            """,
            (canonical_id, member_b, member_c),
        )
        entity_rows = cursor.fetchall()

    assert len(entity_rows) == 3
    assert all(row["er_cluster_id"] == cluster_id for row in entity_rows)
    assert all(row["er_confidence"] == pytest.approx(0.97) for row in entity_rows)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id, source_record_id, extraction_role
            FROM core.entity_source
            WHERE entity_type = 'person'
            ORDER BY source_record_id
            """
        )
        source_rows = cursor.fetchall()

    assert {row["entity_id"] for row in source_rows} == {canonical_id}
    # source_dup should appear once, not twice.
    dup_rows = [row for row in source_rows if row["source_record_id"] == source_dup]
    assert len(dup_rows) == 1


def test_persist_auto_merge_clusters_rerun_supersedes_active_memberships_and_reassigns_canonical(
    db_conn: psycopg.Connection,
) -> None:
    people, _ = _setup_people_with_individual_sources(
        db_conn,
        scenario_prefix="Rerun",
        count=2,
    )
    person_a, person_b = people

    first_cluster_id = persist_auto_merge_clusters(
        db_conn,
        [_cluster_component(canonical_entity_id=person_a, member_ids={person_a, person_b}, min_confidence=0.96)],
        "person",
    )[0]
    second_cluster_id = persist_auto_merge_clusters(
        db_conn,
        [_cluster_component(canonical_entity_id=person_b, member_ids={person_a, person_b}, min_confidence=0.98)],
        "person",
    )[0]

    assert first_cluster_id != second_cluster_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT cluster_id, entity_id, split_at, split_by
            FROM core.cluster_member
            WHERE entity_type = 'person'
            ORDER BY created_at
            """
        )
        rows = cursor.fetchall()

    assert len(rows) == 4
    split_rows = [row for row in rows if row["split_at"] is not None]
    active_rows = [row for row in rows if row["split_at"] is None]
    assert len(split_rows) == 2
    assert len(active_rows) == 2
    assert {row["cluster_id"] for row in active_rows} == {second_cluster_id}
    assert all(row["split_by"] == "splink_v1" for row in split_rows)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, er_cluster_id, er_confidence
            FROM core.person
            WHERE id IN (%s, %s)
            ORDER BY id
            """,
            (person_a, person_b),
        )
        person_rows = cursor.fetchall()

    assert all(row["er_cluster_id"] == second_cluster_id for row in person_rows)
    assert all(row["er_confidence"] == pytest.approx(0.98) for row in person_rows)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id, source_record_id
            FROM core.entity_source
            WHERE entity_type = 'person'
            ORDER BY source_record_id
            """
        )
        entity_source_rows = cursor.fetchall()

    assert {row["entity_id"] for row in entity_source_rows} == {person_b}


def test_persist_auto_merge_clusters_rerun_shrink_restores_dropped_member_state_and_provenance(
    db_conn: psycopg.Connection,
) -> None:
    people, source_records = _setup_people_with_individual_sources(
        db_conn,
        scenario_prefix="Shrink",
        count=3,
    )
    person_a, person_b, person_c = people
    source_a, source_b, source_c = source_records

    first_cluster_id = persist_auto_merge_clusters(
        db_conn,
        [
            _cluster_component(
                canonical_entity_id=person_a, member_ids={person_a, person_b, person_c}, min_confidence=0.96
            )
        ],
        "person",
    )[0]
    second_cluster_id = persist_auto_merge_clusters(
        db_conn,
        [_cluster_component(canonical_entity_id=person_b, member_ids={person_a, person_b}, min_confidence=0.98)],
        "person",
    )[0]

    assert first_cluster_id != second_cluster_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT cluster_id, entity_id, split_at
            FROM core.cluster_member
            WHERE entity_type = 'person'
            ORDER BY created_at, entity_id
            """
        )
        membership_rows = cursor.fetchall()

    active_rows = [row for row in membership_rows if row["split_at"] is None]
    split_rows = [row for row in membership_rows if row["split_at"] is not None]
    assert len(active_rows) == 2
    assert len(split_rows) == 3
    assert {row["cluster_id"] for row in active_rows} == {second_cluster_id}
    assert {row["entity_id"] for row in active_rows} == {person_a, person_b}
    assert {row["entity_id"] for row in split_rows if row["cluster_id"] == first_cluster_id} == {
        person_a,
        person_b,
        person_c,
    }

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, er_cluster_id, er_confidence
            FROM core.person
            WHERE id IN (%s, %s, %s)
            ORDER BY id
            """,
            (person_a, person_b, person_c),
        )
        person_rows = cursor.fetchall()

    by_id = {row["id"]: row for row in person_rows}
    assert by_id[person_a]["er_cluster_id"] == second_cluster_id
    assert by_id[person_b]["er_cluster_id"] == second_cluster_id
    assert by_id[person_a]["er_confidence"] == pytest.approx(0.98)
    assert by_id[person_b]["er_confidence"] == pytest.approx(0.98)
    assert by_id[person_c]["er_cluster_id"] is None
    assert by_id[person_c]["er_confidence"] is None

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id, source_record_id
            FROM core.entity_source
            WHERE entity_type = 'person'
            ORDER BY source_record_id
            """
        )
        entity_source_rows = cursor.fetchall()

    assert {(row["entity_id"], row["source_record_id"]) for row in entity_source_rows} == {
        (person_b, source_a),
        (person_b, source_b),
        (person_c, source_c),
    }


def test_persist_auto_merge_clusters_merge_policy_records_owner_ids_for_shared_source_tuple(
    db_conn: psycopg.Connection,
) -> None:
    person_a, person_b, person_c, _, _, _, source_shared = _setup_three_people_with_shared_source(
        db_conn,
        scenario_prefix="Policy",
    )

    persist_auto_merge_clusters(
        db_conn,
        [
            _cluster_component(
                canonical_entity_id=person_a, member_ids={person_a, person_b, person_c}, min_confidence=0.95
            )
        ],
        "person",
    )

    shared_rows = _fetch_person_source_rows_by_source_record(db_conn, source_record_id=source_shared)
    assert len(shared_rows) == 1
    assert shared_rows[0]["entity_id"] == person_a
    extracted_fields = shared_rows[0]["extracted_fields"]
    assert extracted_fields is not None
    assert extracted_fields["_er_source_entity_ids"] == [str(owner_id) for owner_id in sorted({person_a, person_c})]


def test_persist_auto_merge_clusters_rerun_shrink_then_reexpand_restores_shared_source_ownership(
    db_conn: psycopg.Connection,
) -> None:
    person_a, person_b, person_c, source_a, source_b, source_c, source_shared = _setup_three_people_with_shared_source(
        db_conn,
        scenario_prefix="Reexpand",
    )

    persist_auto_merge_clusters(
        db_conn,
        [
            _cluster_component(
                canonical_entity_id=person_a, member_ids={person_a, person_b, person_c}, min_confidence=0.95
            )
        ],
        "person",
    )
    persist_auto_merge_clusters(
        db_conn,
        [_cluster_component(canonical_entity_id=person_b, member_ids={person_a, person_b}, min_confidence=0.96)],
        "person",
    )

    shrunk_rows = _fetch_person_source_rows_by_source_record(db_conn, source_record_id=source_shared)
    assert len(shrunk_rows) == 2
    shrunk_by_entity = {row["entity_id"]: row["extracted_fields"] for row in shrunk_rows}
    assert shrunk_by_entity[person_b]["_er_source_entity_ids"] == [str(person_a)]
    assert shrunk_by_entity[person_c] is None

    final_cluster_id = persist_auto_merge_clusters(
        db_conn,
        [
            _cluster_component(
                canonical_entity_id=person_c, member_ids={person_a, person_b, person_c}, min_confidence=0.99
            )
        ],
        "person",
    )[0]

    reexpanded_shared_rows = _fetch_person_source_rows_by_source_record(db_conn, source_record_id=source_shared)
    assert len(reexpanded_shared_rows) == 1
    assert reexpanded_shared_rows[0]["entity_id"] == person_c
    assert reexpanded_shared_rows[0]["extracted_fields"]["_er_source_entity_ids"] == [
        str(owner_id) for owner_id in sorted({person_a, person_c})
    ]

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, er_cluster_id, er_confidence
            FROM core.person
            WHERE id IN (%s, %s, %s)
            ORDER BY id
            """,
            (person_a, person_b, person_c),
        )
        people = cursor.fetchall()

    assert all(row["er_cluster_id"] == final_cluster_id for row in people)
    assert all(row["er_confidence"] == pytest.approx(0.99) for row in people)
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id, source_record_id
            FROM core.entity_source
            WHERE entity_type = 'person'
            ORDER BY source_record_id, entity_id
            """
        )
        final_source_rows = cursor.fetchall()

    assert {(row["entity_id"], row["source_record_id"]) for row in final_source_rows} == {
        (person_c, source_a),
        (person_c, source_b),
        (person_c, source_c),
        (person_c, source_shared),
    }


def test_persist_auto_merge_clusters_empty_rerun_clears_previous_active_cluster_state(
    db_conn: psycopg.Connection,
) -> None:
    person_a = uuid4()
    person_b = uuid4()
    _create_person(db_conn, person_id=person_a, name="Dissolve Alpha")
    _create_person(db_conn, person_id=person_b, name="Dissolve Beta")

    data_source_id = _insert_data_source(db_conn, name="cluster-dissolve-source")
    source_a = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="dissolve-a")
    source_b = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="dissolve-b")
    _insert_entity_source(
        db_conn,
        entity_type="person",
        entity_id=person_a,
        source_record_id=source_a,
        extraction_role="donor",
    )
    _insert_entity_source(
        db_conn,
        entity_type="person",
        entity_id=person_b,
        source_record_id=source_b,
        extraction_role="donor",
    )

    first_cluster_id = persist_auto_merge_clusters(
        db_conn,
        [
            {
                "canonical_entity_id": person_a,
                "member_ids": {person_a, person_b},
                "min_confidence": 0.96,
                "min_decision": "match",
                "links": [],
            }
        ],
        "person",
    )[0]

    assert persist_auto_merge_clusters(db_conn, [], "person") == []

    active_membership_count = db_conn.execute(
        """
        SELECT count(*)
        FROM core.cluster_member
        WHERE entity_type = 'person'
          AND entity_id IN (%s, %s)
          AND split_at IS NULL
        """,
        (person_a, person_b),
    ).fetchone()[0]
    assert active_membership_count == 0

    split_membership_count = db_conn.execute(
        """
        SELECT count(*)
        FROM core.cluster_member
        WHERE entity_type = 'person'
          AND cluster_id = %s
          AND split_at IS NOT NULL
        """,
        (first_cluster_id,),
    ).fetchone()[0]
    assert split_membership_count == 2

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, er_cluster_id, er_confidence
            FROM core.person
            WHERE id IN (%s, %s)
            ORDER BY id
            """,
            (person_a, person_b),
        )
        people = cursor.fetchall()

    assert all(row["er_cluster_id"] is None for row in people)
    assert all(row["er_confidence"] is None for row in people)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id, source_record_id
            FROM core.entity_source
            WHERE entity_type = 'person'
            ORDER BY source_record_id
            """
        )
        entity_source_rows = cursor.fetchall()

    assert {(row["entity_id"], row["source_record_id"]) for row in entity_source_rows} == {
        (person_a, source_a),
        (person_b, source_b),
    }


def test_persist_auto_merge_clusters_updates_organization_rows_when_entity_type_is_organization(
    db_conn: psycopg.Connection,
) -> None:
    canonical_org = uuid4()
    merged_org = uuid4()
    _create_org(db_conn, organization_id=canonical_org, name="Canonical Org")
    _create_org(db_conn, organization_id=merged_org, name="Merged Org")

    cluster_id = persist_auto_merge_clusters(
        db_conn,
        [
            {
                "canonical_entity_id": canonical_org,
                "member_ids": {canonical_org, merged_org},
                "min_confidence": 0.95,
                "min_decision": "match",
                "links": [],
            }
        ],
        "organization",
    )[0]

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, er_cluster_id, er_confidence
            FROM core.organization
            WHERE id IN (%s, %s)
            ORDER BY id
            """,
            (canonical_org, merged_org),
        )
        rows = cursor.fetchall()

    assert len(rows) == 2
    assert all(row["er_cluster_id"] == cluster_id for row in rows)
    assert all(row["er_confidence"] == pytest.approx(0.95) for row in rows)


def test_persist_auto_merge_clusters_rejects_cluster_without_canonical_member(
    db_conn: psycopg.Connection,
) -> None:
    canonical_org = uuid4()
    other_org = uuid4()
    _create_org(db_conn, organization_id=canonical_org, name="Canonical Missing")
    _create_org(db_conn, organization_id=other_org, name="Other Org")

    with pytest.raises(ValueError, match="canonical_entity_id must be present in member_ids"):
        persist_auto_merge_clusters(
            db_conn,
            [
                {
                    "canonical_entity_id": canonical_org,
                    "member_ids": {other_org},
                    "min_confidence": 0.95,
                    "min_decision": "match",
                    "links": [],
                }
            ],
            "organization",
        )
