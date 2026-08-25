"""Person absorption `core.entity_source` and `core.field_provenance` specimens.

Production owner: `core/entity_resolution/person_absorption.py`.
Merge contract: `docs/design/2026_08_21_er_general_merge_design.md`.
"""

from __future__ import annotations

from uuid import UUID

import psycopg
import pytest

from core.db_ingest import insert_field_provenance
from core.entity_resolution.persist_clusters_test_support import (
    _absorb_person_cluster,
    _canonical_and_member,
    _person_exists,
)
from core.entity_resolution.test_persist import (
    _insert_data_source,
    _insert_entity_source,
    _insert_source_record,
)

pytestmark = pytest.mark.integration


def test_person_absorption_preserves_source_records_and_per_key_entity_source_counts(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Prov")
    data_source_id = _insert_data_source(db_conn, name="prov-source")
    canonical_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="prov-canonical")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="prov-member")
    shared_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="prov-shared")
    _insert_entity_source(
        db_conn,
        entity_type="person",
        entity_id=canonical_id,
        source_record_id=canonical_source,
        extraction_role="donor",
    )
    _insert_entity_source(
        db_conn, entity_type="person", entity_id=member_id, source_record_id=member_source, extraction_role="donor"
    )
    _insert_entity_source(
        db_conn, entity_type="person", entity_id=canonical_id, source_record_id=shared_source, extraction_role="donor"
    )
    _insert_entity_source(
        db_conn, entity_type="person", entity_id=member_id, source_record_id=shared_source, extraction_role="donor"
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    # source_record rows are immutable inputs and must never be deleted.
    surviving_source_records = db_conn.execute(
        "SELECT count(*) FROM core.source_record WHERE id = ANY(%s)",
        ([canonical_source, member_source, shared_source],),
    ).fetchone()[0]
    assert surviving_source_records == 3
    # Exact per-source-record counts so an equal total cannot hide a moved or lost filing.
    per_key = dict(
        db_conn.execute(
            """
            SELECT source_record_id, count(*)
            FROM core.entity_source
            WHERE entity_type = 'person' AND source_record_id = ANY(%s)
            GROUP BY source_record_id
            """,
            ([canonical_source, member_source, shared_source],),
        ).fetchall()
    )
    assert per_key == {canonical_source: 1, member_source: 1, shared_source: 1}
    owners = db_conn.execute(
        """
        SELECT DISTINCT entity_id FROM core.entity_source
        WHERE entity_type = 'person' AND source_record_id = ANY(%s)
        """,
        ([canonical_source, member_source, shared_source],),
    ).fetchall()
    assert {row[0] for row in owners} == {canonical_id}


def test_person_absorption_repoints_field_provenance_to_canonical(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Field")
    data_source_id = _insert_data_source(db_conn, name="field-source")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="field-member")
    insert_field_provenance(db_conn, "person", member_id, "education", "State University", member_source)

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    rows = db_conn.execute(
        """
        SELECT entity_id, is_current FROM core.field_provenance
        WHERE entity_type = 'person'
          AND field_name = 'education'
          AND field_value = 'State University'
          AND source_record_id = %s
          AND entity_id = ANY(%s)
        """,
        (member_source, [canonical_id, member_id]),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == canonical_id, "absorbed field provenance history must repoint to canonical"
    assert (
        db_conn.execute("SELECT count(*) FROM core.field_provenance WHERE entity_id = %s", (member_id,)).fetchone()[0]
        == 0
    )


def test_person_absorption_resolves_colliding_field_provenance_current_rows(
    db_conn: psycopg.Connection,
) -> None:
    """Canonical current provenance wins, fill-only winners become current, history is kept.

    `idx_field_prov_current` allows one `is_current` row per (entity_type, entity_id, field_name),
    and `idx_field_prov_dedup` forbids duplicate (entity, field, value, source) tuples. A repoint
    that does not demote the absorbed current row or dedupe the shared observation violates one of
    those indexes; a repoint that deletes the absorbed row instead loses a distinct observation.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="FieldCollide")
    data_source_id = _insert_data_source(db_conn, name="field-collide-source")
    canonical_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="fc-canonical")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="fc-member")
    shared_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="fc-shared")

    # occupation: both sides hold a conflicting *current* value; the canonical scalar wins.
    db_conn.execute("UPDATE core.person SET occupation = 'LAWYER' WHERE id = %s", (canonical_id,))
    db_conn.execute("UPDATE core.person SET occupation = 'ENGINEER' WHERE id = %s", (member_id,))
    insert_field_provenance(db_conn, "person", canonical_id, "occupation", "LAWYER", canonical_source)
    insert_field_provenance(db_conn, "person", member_id, "occupation", "ENGINEER", member_source)
    # education: canonical NULL, so the absorbed observation is a fill-only winner and becomes current.
    db_conn.execute("UPDATE core.person SET education = 'State University' WHERE id = %s", (member_id,))
    insert_field_provenance(db_conn, "person", member_id, "education", "State University", member_source)
    # employer: the identical (field, value, source) tuple on both sides must collapse to one row.
    insert_field_provenance(db_conn, "person", canonical_id, "employer", "ACME", shared_source)
    insert_field_provenance(db_conn, "person", member_id, "employer", "ACME", shared_source)

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    rows = db_conn.execute(
        """
        SELECT field_name, field_value, source_record_id, is_current
        FROM core.field_provenance
        WHERE entity_type = 'person' AND entity_id = %s AND source_record_id = ANY(%s)
        """,
        (canonical_id, [canonical_source, member_source, shared_source]),
    ).fetchall()
    assert {(r[0], r[1], r[2], r[3]) for r in rows} == {
        ("occupation", "LAWYER", canonical_source, True),
        ("occupation", "ENGINEER", member_source, False),
        ("education", "State University", member_source, True),
        ("employer", "ACME", shared_source, True),
    }
    assert len(rows) == 4, "the shared (field, value, source) observation must dedupe to a single row"
    # Nothing is left pointing at the absorbed person.
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.field_provenance WHERE entity_type = 'person' AND entity_id = %s",
            (member_id,),
        ).fetchone()[0]
        == 0
    )
    # The surviving scalars follow the winning provenance rows exactly.
    scalars = db_conn.execute("SELECT occupation, education FROM core.person WHERE id = %s", (canonical_id,)).fetchone()
    assert scalars == ("LAWYER", "State University")


def test_person_absorption_fill_only_current_becomes_the_row_naming_the_stored_value(
    db_conn: psycopg.Connection,
) -> None:
    """The fill-only current provenance row must name the value written to `core.person`.

    When more than one moved provenance row survives for a filled field, promoting the lowest-id
    row to `is_current` can name a value the survivor never stored. `idx_field_prov_current` allows
    exactly one current row per field, so the merge must pick the row whose `field_value` matches
    the filled scalar, not whichever row happens to sort first.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="FillWinner")
    data_source_id = _insert_data_source(db_conn, name="fill-winner-source")
    stored_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="fw-stored")
    stale_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="fw-stale")

    # Canonical occupation is NULL, so the attributed absorbed value is a fill-only winner.
    db_conn.execute("UPDATE core.person SET occupation = 'ENGINEER' WHERE id = %s", (member_id,))
    stored_prov = insert_field_provenance(db_conn, "person", member_id, "occupation", "ENGINEER", stored_source)
    stale_prov = insert_field_provenance(db_conn, "person", member_id, "occupation", "TYPOVALUE", stale_source)
    # Force ids so the stale row (naming a value the survivor never stores) sorts first by id.
    low_id = UUID("00000000-0000-0000-0000-000000000001")
    high_id = UUID("00000000-0000-0000-0000-000000000002")
    db_conn.execute("UPDATE core.field_provenance SET id = %s WHERE id = %s", (low_id, stale_prov))
    db_conn.execute("UPDATE core.field_provenance SET id = %s WHERE id = %s", (high_id, stored_prov))

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    stored_occupation = db_conn.execute("SELECT occupation FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[
        0
    ]
    assert stored_occupation == "ENGINEER"
    current_rows = db_conn.execute(
        """
        SELECT field_value
        FROM core.field_provenance
        WHERE entity_type = 'person' AND entity_id = %s AND field_name = 'occupation' AND is_current
        """,
        (canonical_id,),
    ).fetchall()
    assert current_rows == [("ENGINEER",)], "the current row must name the value the survivor stores, not the stale one"
