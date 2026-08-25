"""Person absorption direct `core.person` FK dependent and `core.person_portrait` specimens.

Production owner: `core/entity_resolution/person_absorption.py`.
Merge contract: `docs/design/2026_08_21_er_general_merge_design.md`.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from core.entity_resolution.persist import PersonAbsorptionBlocked
from core.entity_resolution.persist_clusters_test_support import (
    _BLOCKER_TWO_ACTIVE_PORTRAITS,
    _absorb_person_cluster,
    _canonical_and_member,
    _insert_cf_candidate,
    _insert_cf_transaction,
    _insert_donor_cluster_person,
    _insert_person_portrait,
    _insert_prop_ownership,
    _insert_prop_parcel,
    _person_exists,
)
from core.entity_resolution.test_extract import (
    _insert_fec_committee,
    _insert_fec_filing,
)
from core.entity_resolution.test_persist import (
    _create_org,
    _insert_data_source,
    _insert_source_record,
)

pytestmark = pytest.mark.integration


def test_person_absorption_moves_cf_candidate_person_id_to_canonical(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Cand")
    candidate_id = _insert_cf_candidate(db_conn, person_id=member_id)

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id), "absorbed person must be physically deleted"
    moved = db_conn.execute("SELECT person_id FROM cf.candidate WHERE id = %s", (candidate_id,)).fetchone()
    assert moved is not None
    assert moved[0] == canonical_id


def test_person_absorption_moves_cf_transaction_contributor_and_preserves_org_field(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Txn")
    committee_id = _insert_fec_committee(
        db_conn, fec_committee_id=f"C{uuid4().int % 100_000_000:08d}", name="Absorb Committee"
    )
    filing_id = _insert_fec_filing(db_conn, committee_id=committee_id, filing_fec_id=f"FEC-{uuid4().hex[:12]}")
    transaction_id = _insert_cf_transaction(
        db_conn,
        filing_id=filing_id,
        committee_id=committee_id,
        contributor_person_id=member_id,
    )
    # `ck_transaction_contributor_id_exclusive` allows at most one of the two contributor columns,
    # so the "organization fields stay untouched" rule needs a real organization-contributed row to
    # be observable at all. A sweep that rewrites contributor columns by position would move this
    # one onto the canonical person.
    organization_id = uuid4()
    _create_org(db_conn, organization_id=organization_id, name="Txn Org Contributor")
    org_transaction_id = _insert_cf_transaction(
        db_conn,
        filing_id=filing_id,
        committee_id=committee_id,
        contributor_person_id=None,
        contributor_organization_id=organization_id,
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    row = db_conn.execute(
        "SELECT contributor_person_id, contributor_organization_id FROM cf.transaction WHERE id = %s",
        (transaction_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == canonical_id
    assert row[1] is None, "the moved row gains no organization contributor"
    org_row = db_conn.execute(
        "SELECT contributor_person_id, contributor_organization_id FROM cf.transaction WHERE id = %s",
        (org_transaction_id,),
    ).fetchone()
    assert org_row == (None, organization_id), "an organization-contributed row is untouched by a person move"


def test_person_absorption_moves_prop_ownership_owner_and_preserves_org_field(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Own")
    parcel_id = _insert_prop_parcel(db_conn)
    ownership_id = _insert_prop_ownership(db_conn, parcel_id=parcel_id, owner_person_id=member_id)
    # `ck_ownership_owner_entity_links` allows at most one owner column, so an organization-owned
    # row is the only way "never alter owner_organization_id" can be observed failing.
    organization_id = uuid4()
    _create_org(db_conn, organization_id=organization_id, name="Own Org Owner")
    org_ownership_id = _insert_prop_ownership(
        db_conn, parcel_id=parcel_id, owner_person_id=None, owner_organization_id=organization_id
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    row = db_conn.execute(
        "SELECT owner_person_id, owner_organization_id FROM prop.ownership WHERE id = %s",
        (ownership_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == canonical_id
    assert row[1] is None, "the moved row gains no organization owner"
    org_row = db_conn.execute(
        "SELECT owner_person_id, owner_organization_id FROM prop.ownership WHERE id = %s",
        (org_ownership_id,),
    ).fetchone()
    assert org_row == (None, organization_id), "an organization-owned row is untouched by a person move"


def test_person_absorption_moves_donor_cluster_person_mapping_to_canonical(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Donor")
    # Multiple donor clusters may map to one canonical person after the move.
    cluster_one = _insert_donor_cluster_person(db_conn, person_id=member_id)
    cluster_two = _insert_donor_cluster_person(db_conn, person_id=canonical_id)

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    rows = db_conn.execute(
        "SELECT person_id FROM core.donor_cluster_person WHERE cluster_id IN (%s, %s)",
        (cluster_one, cluster_two),
    ).fetchall()
    assert {row[0] for row in rows} == {canonical_id}


def test_person_absorption_dedupes_identical_portrait_dedup_key(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Portrait")
    data_source_id = _insert_data_source(db_conn, name="portrait-source")
    source_record_id = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="portrait-shared"
    )
    # Same (dedup_key) on both people; canonical keeps active, member row dedupes away.
    _insert_person_portrait(
        db_conn, person_id=canonical_id, source_record_id=source_record_id, dedup_key="shared-key", status="active"
    )
    _insert_person_portrait(
        db_conn,
        person_id=member_id,
        source_record_id=source_record_id,
        dedup_key="shared-key",
        status="superseded",
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    portrait_rows = db_conn.execute(
        """
        SELECT person_id, dedup_key FROM core.person_portrait
        WHERE dedup_key = 'shared-key' AND person_id = ANY(%s)
        """,
        ([canonical_id, member_id],),
    ).fetchall()
    assert {row[0] for row in portrait_rows} == {canonical_id}
    assert len(portrait_rows) == 1, "identical dedup_key must collapse to one canonical portrait"


def test_person_absorption_blocks_on_two_distinct_active_portraits(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="TwoPortrait")
    data_source_id = _insert_data_source(db_conn, name="two-portrait-source")
    source_record_id = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="two-portrait")
    _insert_person_portrait(
        db_conn,
        person_id=canonical_id,
        source_record_id=source_record_id,
        dedup_key="canonical-key",
        status="active",
        image_hash="hash-canonical",
    )
    _insert_person_portrait(
        db_conn,
        person_id=member_id,
        source_record_id=source_record_id,
        dedup_key="member-key",
        status="active",
        image_hash="hash-member",
    )

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    assert exc_info.value.reason == _BLOCKER_TWO_ACTIVE_PORTRAITS
    assert _person_exists(db_conn, member_id), "a blocked component must not delete the member"


def test_person_absorption_keeps_absorbed_active_portrait_over_nonactive_duplicate(
    db_conn: psycopg.Connection,
) -> None:
    """A shared dedup_key must not discard the component's only active portrait.

    `idx_person_portrait_dedup` forbids moving the absorbed row onto the canonical person, so the
    retained duplicate has to adopt the active state instead of the merge silently losing it.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="PortraitState")
    data_source_id = _insert_data_source(db_conn, name="portrait-state-source")
    source_record_id = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="portrait-state")
    canonical_portrait = _insert_person_portrait(
        db_conn,
        person_id=canonical_id,
        source_record_id=source_record_id,
        dedup_key="state-key",
        status="rejected",
    )
    member_portrait = _insert_person_portrait(
        db_conn,
        person_id=member_id,
        source_record_id=source_record_id,
        dedup_key="state-key",
        status="active",
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    assert (
        db_conn.execute("SELECT count(*) FROM core.person_portrait WHERE id = %s", (member_portrait,)).fetchone()[0]
        == 0
    ), "the colliding absorbed row still dedupes away"
    assert db_conn.execute(
        "SELECT person_id, status FROM core.person_portrait WHERE id = %s", (canonical_portrait,)
    ).fetchone() == (canonical_id, "active"), "the surviving person keeps the active portrait state"
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.person_portrait WHERE person_id = %s AND status = 'active'",
            (canonical_id,),
        ).fetchone()[0]
        == 1
    )
