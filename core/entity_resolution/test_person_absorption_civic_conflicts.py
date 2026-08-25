"""Person absorption `civic.candidacy` repoint/collision and `civic.officeholding` overlap-blocker specimens.

Production owner: `core/entity_resolution/person_absorption.py`.
Merge contract: `docs/design/2026_08_21_er_general_merge_design.md`.
"""

from __future__ import annotations

import psycopg
import pytest

from core.entity_resolution.persist import PersonAbsorptionBlocked
from core.entity_resolution.persist_clusters_test_support import (
    _BLOCKER_OVERLAPPING_OFFICEHOLDING,
    _absorb_person_cluster,
    _canonical_and_member,
    _insert_civic_candidacy,
    _insert_civic_contest,
    _insert_civic_office,
    _insert_civic_officeholding,
    _person_exists,
)
from core.entity_resolution.test_persist import (
    _insert_data_source,
    _insert_entity_source,
    _insert_source_record,
)

pytestmark = pytest.mark.integration


def test_person_absorption_repoints_lone_candidacy_person_id(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Cy")
    office_id = _insert_civic_office(db_conn)
    contest_id = _insert_civic_contest(db_conn, office_id=office_id)
    candidacy_id = _insert_civic_candidacy(db_conn, person_id=member_id, contest_id=contest_id, party="D")

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    row = db_conn.execute("SELECT person_id, party FROM civic.candidacy WHERE id = %s", (candidacy_id,)).fetchone()
    assert row is not None
    assert row[0] == canonical_id
    assert row[1] == "D"


def test_person_absorption_merges_colliding_candidacy_per_repoint_rule(
    db_conn: psycopg.Connection,
) -> None:
    # repoint_candidacy_person(): target fields win, missing target fields fill from source,
    # source provenance links copy with dedup, redundant source candidacy deletes.
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="CyMerge")
    office_id = _insert_civic_office(db_conn)
    contest_id = _insert_civic_contest(db_conn, office_id=office_id)
    data_source_id = _insert_data_source(db_conn, name="candidacy-merge-source")
    canonical_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="cand-canonical")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="cand-member")

    canonical_candidacy = _insert_civic_candidacy(
        db_conn,
        person_id=canonical_id,
        contest_id=contest_id,
        party="D",
        name_on_ballot=None,
        source_record_id=canonical_source,
    )
    member_candidacy = _insert_civic_candidacy(
        db_conn,
        person_id=member_id,
        contest_id=contest_id,
        party="R",
        name_on_ballot="MEMBER ON BALLOT",
        source_record_id=member_source,
    )
    _insert_entity_source(
        db_conn,
        entity_type="candidacy",
        entity_id=member_candidacy,
        source_record_id=member_source,
        extraction_role="candidacy",
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    remaining = db_conn.execute(
        "SELECT id, party, name_on_ballot FROM civic.candidacy WHERE contest_id = %s ORDER BY id",
        (contest_id,),
    ).fetchall()
    assert len(remaining) == 1, "colliding candidacies must merge to one row on the canonical person"
    assert remaining[0][0] == canonical_candidacy
    assert remaining[0][1] == "D", "target party wins (COALESCE target, source)"
    assert remaining[0][2] == "MEMBER ON BALLOT", "missing target field fills from source"
    assert db_conn.execute("SELECT count(*) FROM civic.candidacy WHERE id = %s", (member_candidacy,)).fetchone()[0] == 0
    # Source provenance link from the redundant candidacy is copied onto the surviving row.
    copied_links = db_conn.execute(
        """
        SELECT count(*) FROM core.entity_source
        WHERE entity_type = 'candidacy' AND entity_id = %s AND source_record_id = %s
        """,
        (canonical_candidacy, member_source),
    ).fetchone()[0]
    assert copied_links == 1


def test_person_absorption_dedupes_equal_officeholding_terms(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="OhEqual")
    office_id = _insert_civic_office(db_conn)
    data_source_id = _insert_data_source(db_conn, name="officeholding-equal-source")
    canonical_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="oh-canonical")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="oh-member")
    canonical_officeholding = _insert_civic_officeholding(
        db_conn,
        person_id=canonical_id,
        office_id=office_id,
        start="2020-01-01",
        end="2024-01-01",
        source_record_id=canonical_source,
    )
    member_officeholding = _insert_civic_officeholding(
        db_conn,
        person_id=member_id,
        office_id=office_id,
        start="2020-01-01",
        end="2024-01-01",
        source_record_id=member_source,
    )
    _insert_entity_source(
        db_conn,
        entity_type="officeholding",
        entity_id=canonical_officeholding,
        source_record_id=canonical_source,
        extraction_role="officeholding",
    )
    _insert_entity_source(
        db_conn,
        entity_type="officeholding",
        entity_id=member_officeholding,
        source_record_id=member_source,
        extraction_role="officeholding",
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    rows = db_conn.execute(
        "SELECT id, person_id, source_record_id FROM civic.officeholding WHERE office_id = %s",
        (office_id,),
    ).fetchall()
    assert len(rows) == 1, "equal officeholding facts must deduplicate onto the canonical person"
    assert rows[0] == (canonical_officeholding, canonical_id, canonical_source)
    assert (
        db_conn.execute("SELECT count(*) FROM civic.officeholding WHERE id = %s", (member_officeholding,)).fetchone()[0]
        == 0
    )
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.source_record WHERE id = ANY(%s)",
            ([canonical_source, member_source],),
        ).fetchone()[0]
        == 2
    ), "deduplicating equal facts must not delete either immutable source record"
    provenance_rows = db_conn.execute(
        """
        SELECT entity_id, source_record_id, extraction_role
        FROM core.entity_source
        WHERE entity_type = 'officeholding' AND source_record_id = ANY(%s)
        ORDER BY source_record_id
        """,
        ([canonical_source, member_source],),
    ).fetchall()
    assert set(provenance_rows) == {
        (canonical_officeholding, canonical_source, "officeholding"),
        (canonical_officeholding, member_source, "officeholding"),
    }, "the surviving equal officeholding must retain both source links"


def test_person_absorption_blocks_on_overlapping_nonequal_officeholding(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="OhOverlap")
    office_id = _insert_civic_office(db_conn)
    _insert_civic_officeholding(
        db_conn, person_id=canonical_id, office_id=office_id, start="2020-01-01", end="2024-01-01"
    )
    # Overlaps [2020,2024) but is not an equal term -> collapsing onto one person violates
    # UNIQUE (person_id, office_id, valid_period WITHOUT OVERLAPS); block the whole component.
    _insert_civic_officeholding(db_conn, person_id=member_id, office_id=office_id, start="2022-01-01", end="2026-01-01")

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    assert exc_info.value.reason == _BLOCKER_OVERLAPPING_OFFICEHOLDING
    assert _person_exists(db_conn, member_id)
    assert (
        db_conn.execute("SELECT count(*) FROM civic.officeholding WHERE office_id = %s", (office_id,)).fetchone()[0]
        == 2
    )
