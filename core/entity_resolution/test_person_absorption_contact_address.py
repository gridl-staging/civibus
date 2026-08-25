"""Person absorption `core.contact_point` and `core.entity_address` specimens.

Production owner: `core/entity_resolution/person_absorption.py`.
Merge contract: `docs/design/2026_08_21_er_general_merge_design.md`.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest
from psycopg.types.range import DateRange

from core.db_ingest import insert_entity_address
from core.entity_resolution.persist_clusters_test_support import (
    _absorb_person_cluster,
    _canonical_and_member,
    _insert_address_row,
    _insert_contact_point,
    _person_exists,
)
from core.entity_resolution.test_persist import (
    _insert_data_source,
    _insert_source_record,
)

pytestmark = pytest.mark.integration


def test_person_absorption_copies_contact_point_to_canonical(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Contact")
    data_source_id = _insert_data_source(db_conn, name="contact-source")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="contact-member")
    contact_point_id = _insert_contact_point(
        db_conn, owner_id=member_id, value_raw="jane@example.test", source_record_id=member_source
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    row = db_conn.execute(
        "SELECT owner_id, source_record_id FROM core.contact_point WHERE id = %s",
        (contact_point_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == canonical_id, "contact point must move to the canonical owner"
    assert row[1] == member_source, "source record id is preserved on the moved contact point"


def test_person_absorption_moves_noncolliding_entity_address_to_canonical(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Addr")
    data_source_id = _insert_data_source(db_conn, name="addr-source")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="addr-member")
    address_id = _insert_address_row(db_conn, raw_address="500 Absorb Ave")
    entity_address_id = insert_entity_address(
        db_conn, "person", member_id, address_id, member_source, address_role="mailing"
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    row = db_conn.execute(
        "SELECT entity_id FROM core.entity_address WHERE id = %s",
        (entity_address_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == canonical_id


def test_person_absorption_dedupes_colliding_contact_points_for_both_role_branches(
    db_conn: psycopg.Connection,
) -> None:
    """Both `core.contact_point` natural-key branches dedupe; non-colliding rows move.

    `uq_contact_point_natural_key` covers non-null roles and `uq_contact_point_natural_key_null_role`
    covers null roles, so a blind owner rewrite violates one index per branch.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="ContactCollide")
    data_source_id = _insert_data_source(db_conn, name="contact-collide-source")
    canonical_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="cc-canonical")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="cc-member")

    canonical_roled = _insert_contact_point(
        db_conn, owner_id=canonical_id, value_raw="shared@example.test", source_record_id=canonical_source
    )
    member_roled = _insert_contact_point(
        db_conn, owner_id=member_id, value_raw="shared@example.test", source_record_id=member_source
    )
    canonical_null_role = _insert_contact_point(
        db_conn,
        owner_id=canonical_id,
        value_raw="nullrole@example.test",
        source_record_id=canonical_source,
        role=None,
    )
    member_null_role = _insert_contact_point(
        db_conn, owner_id=member_id, value_raw="nullrole@example.test", source_record_id=member_source, role=None
    )
    member_unique = _insert_contact_point(
        db_conn,
        owner_id=member_id,
        value_raw="unique@example.test",
        source_record_id=member_source,
        role="office",
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    rows = db_conn.execute(
        """
        SELECT id, value_raw, role, source_record_id
        FROM core.contact_point
        WHERE owner_type = 'person' AND owner_id = %s AND source_record_id = ANY(%s)
        """,
        (canonical_id, [canonical_source, member_source]),
    ).fetchall()
    # Retained rows are the canonical ones for both colliding branches; the unique row moves intact.
    assert {(r[0], r[1], r[2], r[3]) for r in rows} == {
        (canonical_roled, "shared@example.test", "campaign", canonical_source),
        (canonical_null_role, "nullrole@example.test", None, canonical_source),
        (member_unique, "unique@example.test", "office", member_source),
    }
    # The absorbed duplicates are gone, not merely repointed.
    surviving_duplicates = db_conn.execute(
        "SELECT count(*) FROM core.contact_point WHERE id = ANY(%s)",
        ([member_roled, member_null_role],),
    ).fetchone()[0]
    assert surviving_duplicates == 0
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.contact_point WHERE owner_type = 'person' AND owner_id = %s",
            (member_id,),
        ).fetchone()[0]
        == 0
    )


def test_person_absorption_demotes_conflicting_preferred_contact_point(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="ContactPref")
    data_source_id = _insert_data_source(db_conn, name="contact-pref-source")
    canonical_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="cp-canonical")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="cp-member")
    canonical_preferred = _insert_contact_point(
        db_conn,
        owner_id=canonical_id,
        value_raw="pref-canonical@example.test",
        source_record_id=canonical_source,
        is_preferred=True,
    )
    member_preferred = _insert_contact_point(
        db_conn,
        owner_id=member_id,
        value_raw="pref-member@example.test",
        source_record_id=member_source,
        is_preferred=True,
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    rows = db_conn.execute(
        """
        SELECT id, is_preferred, source_record_id
        FROM core.contact_point
        WHERE owner_type = 'person' AND owner_id = %s AND id = ANY(%s)
        ORDER BY is_preferred DESC
        """,
        (canonical_id, [canonical_preferred, member_preferred]),
    ).fetchall()
    assert {(r[0], r[1], r[2]) for r in rows} == {
        (canonical_preferred, True, canonical_source),
        (member_preferred, False, member_source),
    }, "the canonical preferred fact wins and the absorbed one is deterministically demoted"


def test_person_absorption_drops_overlapping_entity_address_and_moves_the_rest(
    db_conn: psycopg.Connection,
) -> None:
    """`UNIQUE (entity_type, entity_id, address_id, address_role, valid_period WITHOUT OVERLAPS)`.

    A blind repoint of an overlapping absorbed link raises an exclusion violation, so the colliding
    link is dropped while the canonical fact and every non-colliding link are retained.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="AddrCollide")
    data_source_id = _insert_data_source(db_conn, name="addr-collide-source")
    canonical_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="ac-canonical")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="ac-member")
    address_x = _insert_address_row(db_conn, raw_address="100 Overlap Way")
    address_y = _insert_address_row(db_conn, raw_address="200 Distinct Way")

    canonical_link = insert_entity_address(
        db_conn,
        "person",
        canonical_id,
        address_x,
        canonical_source,
        address_role="mailing",
        valid_period=DateRange(date(2020, 1, 1), date(2024, 1, 1)),
    )
    colliding_link = insert_entity_address(
        db_conn,
        "person",
        member_id,
        address_x,
        member_source,
        address_role="mailing",
        valid_period=DateRange(date(2022, 1, 1), date(2026, 1, 1)),
    )
    other_address_link = insert_entity_address(
        db_conn,
        "person",
        member_id,
        address_y,
        member_source,
        address_role="mailing",
        valid_period=DateRange(date(2020, 1, 1), None),
    )
    other_role_link = insert_entity_address(
        db_conn,
        "person",
        member_id,
        address_x,
        member_source,
        address_role="physical",
        valid_period=DateRange(date(2022, 1, 1), date(2026, 1, 1)),
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    rows = db_conn.execute(
        """
        SELECT id, address_id, address_role, lower(valid_period), upper(valid_period), source_record_id
        FROM core.entity_address
        WHERE entity_type = 'person' AND entity_id = %s
        """,
        (canonical_id,),
    ).fetchall()
    assert {tuple(r) for r in rows} == {
        (canonical_link, address_x, "mailing", date(2020, 1, 1), date(2024, 1, 1), canonical_source),
        (other_address_link, address_y, "mailing", date(2020, 1, 1), None, member_source),
        (other_role_link, address_x, "physical", date(2022, 1, 1), date(2026, 1, 1), member_source),
    }
    assert (
        db_conn.execute("SELECT count(*) FROM core.entity_address WHERE id = %s", (colliding_link,)).fetchone()[0] == 0
    ), "the overlapping absorbed link is dropped, never repointed onto the canonical person"
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.entity_address WHERE entity_type = 'person' AND entity_id = %s",
            (member_id,),
        ).fetchone()[0]
        == 0
    )


def test_person_absorption_does_not_fill_primary_address_from_dropped_absorbed_link(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="DroppedPrimary")
    data_source_id = _insert_data_source(db_conn, name="dropped-primary-source")
    canonical_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="dropped-primary-canonical"
    )
    member_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="dropped-primary-member"
    )
    address_id = _insert_address_row(db_conn, raw_address="300 Dropped Primary Way")
    canonical_link = insert_entity_address(
        db_conn,
        "person",
        canonical_id,
        address_id,
        canonical_source,
        address_role="mailing",
        valid_period=DateRange(date(2020, 1, 1), date(2024, 1, 1)),
    )
    dropped_link = insert_entity_address(
        db_conn,
        "person",
        member_id,
        address_id,
        member_source,
        address_role="mailing",
        valid_period=DateRange(date(2022, 1, 1), date(2026, 1, 1)),
    )
    db_conn.execute("UPDATE core.person SET primary_address_id = %s WHERE id = %s", (address_id, member_id))

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    assert (
        db_conn.execute("SELECT primary_address_id FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[0]
        is None
    ), "a deleted absorbed address link must not still drive primary_address_id on the survivor"
    assert db_conn.execute(
        "SELECT entity_id, source_record_id FROM core.entity_address WHERE id = %s",
        (canonical_link,),
    ).fetchone() == (canonical_id, canonical_source)
    assert db_conn.execute("SELECT count(*) FROM core.entity_address WHERE id = %s", (dropped_link,)).fetchone()[0] == 0


@pytest.mark.parametrize("role", ["campaign", None])
def test_person_absorption_keeps_absorbed_preferred_contact_over_nonpreferred_duplicate(
    db_conn: psycopg.Connection,
    role: str | None,
) -> None:
    """Natural-key dedup must not erase the component's only preferred contact fact.

    Runs over both uniqueness branches (`uq_contact_point_natural_key` and
    `uq_contact_point_natural_key_null_role`) because each indexes a different tuple.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix=f"ContactPrefState{role or 'Null'}")
    data_source_id = _insert_data_source(db_conn, name=f"contact-pref-state-{role or 'null'}-source")
    canonical_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key=f"cps-canonical-{role or 'null'}"
    )
    member_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key=f"cps-member-{role or 'null'}"
    )
    canonical_contact = _insert_contact_point(
        db_conn,
        owner_id=canonical_id,
        value_raw="shared-pref@example.test",
        source_record_id=canonical_source,
        role=role,
        is_preferred=False,
    )
    member_contact = _insert_contact_point(
        db_conn,
        owner_id=member_id,
        value_raw="shared-pref@example.test",
        source_record_id=member_source,
        role=role,
        is_preferred=True,
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    assert (
        db_conn.execute("SELECT count(*) FROM core.contact_point WHERE id = %s", (member_contact,)).fetchone()[0] == 0
    ), "the colliding absorbed row still dedupes away"
    assert db_conn.execute(
        "SELECT owner_id, is_preferred FROM core.contact_point WHERE id = %s", (canonical_contact,)
    ).fetchone() == (canonical_id, True), "the retained duplicate inherits the sole preferred fact"
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.contact_point WHERE owner_type = 'person' AND owner_id = %s AND is_preferred",
            (canonical_id,),
        ).fetchone()[0]
        == 1
    ), "exactly one preferred contact survives"


def test_person_absorption_keeps_absorbed_preferred_contact_of_an_unclaimed_type(
    db_conn: psycopg.Connection,
) -> None:
    """Demotion is per contact channel, not per person.

    `docs/design/2026_08_21_er_general_merge_design.md` demands deterministic demotion of
    *conflicting* preferred facts. A preferred email and a preferred phone do not conflict — no
    index forbids both — so demoting the absorbed phone would discard a fact the merge cannot
    restore.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="CrossTypePref")
    data_source_id = _insert_data_source(db_conn, name="cross-type-pref-source")
    canonical_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="ctp-canonical")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="ctp-member")
    canonical_preferred_email = _insert_contact_point(
        db_conn,
        owner_id=canonical_id,
        value_raw="ctp-canonical@example.test",
        source_record_id=canonical_source,
        is_preferred=True,
    )
    member_preferred_phone = _insert_contact_point(
        db_conn,
        owner_id=member_id,
        value_raw="+15550001111",
        source_record_id=member_source,
        is_preferred=True,
        contact_type="phone",
    )
    # A second preferred email on the absorbed person still loses: that type is already claimed.
    member_preferred_email = _insert_contact_point(
        db_conn,
        owner_id=member_id,
        value_raw="ctp-member@example.test",
        source_record_id=member_source,
        is_preferred=True,
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    preference_by_id = dict(
        db_conn.execute(
            """
            SELECT id, is_preferred
            FROM core.contact_point
            WHERE owner_type = 'person' AND owner_id = %s AND id = ANY(%s)
            """,
            (canonical_id, [canonical_preferred_email, member_preferred_phone, member_preferred_email]),
        ).fetchall()
    )
    assert preference_by_id == {
        canonical_preferred_email: True,
        member_preferred_phone: True,
        member_preferred_email: False,
    }, "only the already-claimed channel demotes; an unclaimed channel keeps its preferred fact"
