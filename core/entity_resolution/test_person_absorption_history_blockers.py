"""Person absorption cluster-history preservation and active non-match blocker specimens.

Production owner: `core/entity_resolution/person_absorption.py`.
Merge contract: `docs/design/2026_08_21_er_general_merge_design.md`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from core.entity_resolution.persist import PersonAbsorptionBlocked
from core.entity_resolution.persist_clusters_test_support import (
    _BLOCKER_ACTIVE_NON_MATCH_DECISION,
    _BLOCKER_MANUAL_CONFIRMED_NON_MATCH,
    _absorb_person_cluster,
    _canonical_and_member,
    _canonical_and_two_members,
    _person_exists,
)
from core.entity_resolution.test_persist import _create_person

pytestmark = pytest.mark.integration


def _ordered_pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    a, b = sorted([first, second])
    return a, b


# ---- Identity and history references ---------------------------------------


def test_person_absorption_preserves_cluster_history_with_absorbed_ids(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Hist")

    cluster_ids = _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    cluster_id = cluster_ids[0]

    assert not _person_exists(db_conn, member_id)
    # cluster_member records merge history and must keep the absorbed id as an alias, not a self-pair.
    member_rows = db_conn.execute(
        "SELECT entity_id, is_canonical FROM core.cluster_member WHERE cluster_id = %s ORDER BY entity_id",
        (cluster_id,),
    ).fetchall()
    entity_ids = {row[0] for row in member_rows}
    assert member_id in entity_ids, "absorbed id must survive as a cluster_member alias"
    assert canonical_id in entity_ids
    canonical_flags = {row[0]: row[1] for row in member_rows}
    assert canonical_flags[canonical_id] is True
    assert canonical_flags[member_id] is False
    # entity_cluster's active canonical pointer must be the surviving person.
    cluster_row = db_conn.execute(
        "SELECT canonical_entity_id FROM core.entity_cluster WHERE id = %s", (cluster_id,)
    ).fetchone()
    assert cluster_row[0] == canonical_id


def test_person_absorption_keeps_match_decision_history_without_self_pair(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Md")
    a, b = _ordered_pair(canonical_id, member_id)
    decision_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.match_decision (
            id, entity_type, entity_id_a, entity_id_b, decision, confidence, decided_by, decision_method
        )
        VALUES (%s, 'person', %s, %s, 'match', 0.99, 'splink_v1', 'probabilistic')
        """,
        (decision_id, a, b),
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    row = db_conn.execute(
        "SELECT entity_id_a, entity_id_b FROM core.match_decision WHERE id = %s",
        (decision_id,),
    ).fetchone()
    assert row is not None
    assert (row[0], row[1]) == (a, b), "immutable match_decision pair keeps absorbed ids, never a self-pair"
    assert row[0] != row[1]


def test_person_absorption_blocks_on_active_non_match_decision(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="NoMatch")
    a, b = _ordered_pair(canonical_id, member_id)
    db_conn.execute(
        """
        INSERT INTO core.match_decision (
            id, entity_type, entity_id_a, entity_id_b, decision, confidence, decided_by, decision_method
        )
        VALUES (%s, 'person', %s, %s, 'no_match', 0.02, 'splink_v1', 'probabilistic')
        """,
        (uuid4(), a, b),
    )

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    assert exc_info.value.reason == _BLOCKER_ACTIVE_NON_MATCH_DECISION
    assert _person_exists(db_conn, member_id)


def test_person_absorption_blocks_on_manual_confirmed_non_match(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Manual")
    a, b = _ordered_pair(canonical_id, member_id)
    db_conn.execute(
        """
        INSERT INTO core.manual_override (
            id, entity_type, entity_id_a, entity_id_b, override_decision, reason, decided_by
        )
        VALUES (%s, 'person', %s, %s, 'confirmed_non_match', 'distinct people', 'reviewer:test')
        """,
        (uuid4(), a, b),
    )

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    assert exc_info.value.reason == _BLOCKER_MANUAL_CONFIRMED_NON_MATCH
    assert _person_exists(db_conn, member_id)


def test_person_absorption_blocks_on_active_non_match_between_absorbed_members(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_one, member_two = _canonical_and_two_members(db_conn, prefix="NoMatchInside")
    a, b = _ordered_pair(member_one, member_two)
    db_conn.execute(
        """
        INSERT INTO core.match_decision (
            id, entity_type, entity_id_a, entity_id_b, decision, confidence, decided_by, decision_method
        )
        VALUES (%s, 'person', %s, %s, 'no_match', 0.01, 'splink_v1', 'probabilistic')
        """,
        (uuid4(), a, b),
    )

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_one, member_two})
    assert exc_info.value.reason == _BLOCKER_ACTIVE_NON_MATCH_DECISION
    assert _person_exists(db_conn, member_one)
    assert _person_exists(db_conn, member_two)


def test_person_absorption_ignores_active_non_match_with_external_person(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="NoMatchExternal")
    external_id = uuid4()
    _create_person(db_conn, person_id=external_id, name="NoMatchExternal Outside")
    a, b = _ordered_pair(member_id, external_id)
    decision_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.match_decision (
            id, entity_type, entity_id_a, entity_id_b, decision, confidence, decided_by, decision_method
        )
        VALUES (%s, 'person', %s, %s, 'no_match', 0.01, 'splink_v1', 'probabilistic')
        """,
        (decision_id, a, b),
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id), "only inside-component no_match pairs block absorption"
    assert _person_exists(db_conn, external_id)
    assert db_conn.execute(
        "SELECT entity_id_a, entity_id_b, decision FROM core.match_decision WHERE id = %s",
        (decision_id,),
    ).fetchone() == (a, b, "no_match")


def test_person_absorption_blocks_on_manual_non_match_between_absorbed_members(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_one, member_two = _canonical_and_two_members(db_conn, prefix="ManualInside")
    a, b = _ordered_pair(member_one, member_two)
    db_conn.execute(
        """
        INSERT INTO core.manual_override (
            id, entity_type, entity_id_a, entity_id_b, override_decision, reason, decided_by
        )
        VALUES (%s, 'person', %s, %s, 'confirmed_non_match', 'distinct absorbed members', 'reviewer:test')
        """,
        (uuid4(), a, b),
    )

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_one, member_two})
    assert exc_info.value.reason == _BLOCKER_MANUAL_CONFIRMED_NON_MATCH
    assert _person_exists(db_conn, member_one)
    assert _person_exists(db_conn, member_two)


def test_person_absorption_ignores_manual_non_match_with_external_person(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="ManualExternal")
    external_id = uuid4()
    _create_person(db_conn, person_id=external_id, name="ManualExternal Outside")
    a, b = _ordered_pair(member_id, external_id)
    override_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.manual_override (
            id, entity_type, entity_id_a, entity_id_b, override_decision, reason, decided_by
        )
        VALUES (%s, 'person', %s, %s, 'confirmed_non_match', 'outside component', 'reviewer:test')
        """,
        (override_id, a, b),
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id), "only inside-component manual non-match pairs block absorption"
    assert _person_exists(db_conn, external_id)
    assert db_conn.execute(
        "SELECT entity_id_a, entity_id_b, override_decision FROM core.manual_override WHERE id = %s",
        (override_id,),
    ).fetchone() == (a, b, "confirmed_non_match")


def test_person_absorption_ignores_superseded_non_match_decision(
    db_conn: psycopg.Connection,
) -> None:
    """`active` means `superseded_by IS NULL`, exactly as `idx_match_active` defines it.

    A reversed no_match must not block forever. An implementation that scans
    `core.match_decision` for `decision = 'no_match'` without the `superseded_by IS NULL`
    predicate passes `..._blocks_on_active_non_match_decision` and fails here.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Superseded")
    a, b = _ordered_pair(canonical_id, member_id)
    # The newer decision is inserted first so only ONE row for this pair is ever active
    # (`idx_match_active_pair` is a partial UNIQUE index over `superseded_by IS NULL`).
    superseding_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.match_decision (
            id, entity_type, entity_id_a, entity_id_b, decision, confidence, decided_by, decision_method
        )
        VALUES (%s, 'person', %s, %s, 'match', 0.99, 'splink_v1', 'probabilistic')
        """,
        (superseding_id, a, b),
    )
    superseded_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.match_decision (
            id, entity_type, entity_id_a, entity_id_b, decision, confidence, decided_by,
            decision_method, superseded_by, superseded_at
        )
        VALUES (%s, 'person', %s, %s, 'no_match', 0.02, 'splink_v1', 'probabilistic', %s, NOW())
        """,
        (superseded_id, a, b, superseding_id),
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id), "a superseded no_match is not an active blocker"
    # The reversed decision stays in the immutable history with its absorbed ids intact.
    row = db_conn.execute(
        "SELECT entity_id_a, entity_id_b, superseded_by FROM core.match_decision WHERE id = %s",
        (superseded_id,),
    ).fetchone()
    assert row == (a, b, superseding_id)


def test_person_absorption_ignores_superseded_manual_confirmed_non_match(
    db_conn: psycopg.Connection,
) -> None:
    """A reviewer who changed their mind must not block the merge forever.

    `idx_override_active_pair` defines active as `superseded_by IS NULL`; an implementation that
    matches on `override_decision = 'confirmed_non_match'` alone fails here.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="SupersededManual")
    a, b = _ordered_pair(canonical_id, member_id)
    superseding_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.manual_override (
            id, entity_type, entity_id_a, entity_id_b, override_decision, reason, decided_by
        )
        VALUES (%s, 'person', %s, %s, 'confirmed_match', 'same person after review', 'reviewer:test')
        """,
        (superseding_id, a, b),
    )
    superseded_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.manual_override (
            id, entity_type, entity_id_a, entity_id_b, override_decision, reason, decided_by,
            superseded_by, superseded_at
        )
        VALUES (%s, 'person', %s, %s, 'confirmed_non_match', 'initial call, later reversed',
                'reviewer:test', %s, NOW())
        """,
        (superseded_id, a, b, superseding_id),
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id), "a superseded confirmed_non_match is not an active blocker"
    row = db_conn.execute(
        "SELECT entity_id_a, entity_id_b, superseded_by FROM core.manual_override WHERE id = %s",
        (superseded_id,),
    ).fetchone()
    assert row == (a, b, superseding_id)
