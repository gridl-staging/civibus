"""Person absorption scalar, anchor, identifier, and DOB specimens.

Production owner: `core/entity_resolution/person_absorption.py`.
Merge contract: `docs/design/2026_08_21_er_general_merge_design.md`.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import psycopg
import pytest

from core.db_ingest import insert_field_provenance
from core.entity_resolution.persist import PersonAbsorptionBlocked
from core.entity_resolution.persist_clusters_test_support import (
    _BLOCKER_CONFLICTING_ANCHOR_SCALAR,
    _BLOCKER_CONFLICTING_CONSENSUS_SCALAR,
    _BLOCKER_CONFLICTING_IDENTIFIER,
    _BLOCKER_DOB_YEAR_MISMATCH,
    _absorb_person_cluster,
    _canonical_and_member,
    _canonical_and_two_members,
    _person_exists,
)
from core.entity_resolution.test_extract import _insert_person
from core.entity_resolution.test_persist import _insert_data_source, _insert_source_record

pytestmark = pytest.mark.integration


def test_person_absorption_person_row_scalar_and_name_precedence(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id = uuid4()
    member_id = uuid4()
    # Canonical scalar wins; canonical occupation NULL is consensus-fillable from the absorbed row.
    _insert_person(
        db_conn,
        person_id=canonical_id,
        canonical_name="Jane Canonical",
        first_name="Jane",
        last_name="Canonical",
        date_of_birth=None,
        identifiers={"fec_candidate_id": "H0AA00001"},
    )
    _insert_person(
        db_conn,
        person_id=member_id,
        canonical_name="Janie Member",
        first_name="Janie",
        last_name="Member",
        date_of_birth=None,
        identifiers={"bioguide_id": "B000001"},
    )
    # The absorbed row carries its own prior ER state. It must never be imported onto the
    # survivor: er_cluster_id/er_confidence always describe THIS run's cluster.
    stale_cluster_id = uuid4()
    db_conn.execute(
        """
        UPDATE core.person
        SET occupation = 'ENGINEER',
            name_variants = ARRAY['J. MEMBER'],
            er_cluster_id = %s,
            er_confidence = 0.51
        WHERE id = %s
        """,
        (stale_cluster_id, member_id),
    )
    data_source_id = _insert_data_source(db_conn, name="scalar-source")
    occupation_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="scalar-occupation"
    )
    insert_field_provenance(db_conn, "person", member_id, "occupation", "ENGINEER", occupation_source)

    cluster_ids = _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    canonical_cluster_id = cluster_ids[0]

    assert not _person_exists(db_conn, member_id)
    row = db_conn.execute(
        """
        SELECT canonical_name, first_name, last_name, occupation, name_variants,
               er_cluster_id, er_confidence, identifiers
        FROM core.person WHERE id = %s
        """,
        (canonical_id,),
    ).fetchone()
    assert row is not None
    (
        canonical_name,
        first_name,
        last_name,
        occupation,
        name_variants,
        er_cluster_id,
        er_confidence,
        identifiers,
    ) = row
    assert canonical_name == "Jane Canonical", "canonical_name is never filled from an absorbed row"
    # Ordinary non-null canonical scalars always win; the absorbed values are discarded.
    assert first_name == "Jane", "canonical non-null scalar must survive an absorbed conflicting value"
    assert last_name == "Canonical", "canonical non-null scalar must survive an absorbed conflicting value"
    assert occupation == "ENGINEER", "consensus fill-only supplies the canonical NULL scalar with attribution"
    # name_variants unions every absorbed observed name, excluding the surviving canonical name and blanks.
    assert set(name_variants) >= {"Janie Member", "J. MEMBER"}
    assert "Jane Canonical" not in name_variants
    # er_cluster_id/er_confidence reflect THIS run's cluster, never an absorbed row's prior values.
    assert er_cluster_id == canonical_cluster_id
    assert er_cluster_id != stale_cluster_id, "absorbed prior ER cluster must not be imported"
    assert er_confidence == pytest.approx(0.98)
    # Non-conflicting identifier keys union.
    assert identifiers.get("fec_candidate_id") == "H0AA00001"
    assert identifiers.get("bioguide_id") == "B000001"


def test_person_absorption_consensus_fill_requires_every_absorbed_member_to_agree(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_one, member_two = _canonical_and_two_members(db_conn, prefix="Consensus")
    data_source_id = _insert_data_source(db_conn, name="consensus-fill-source")
    member_one_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="consensus-member-one"
    )
    member_two_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="consensus-member-two"
    )
    db_conn.execute(
        "UPDATE core.person SET occupation = 'ENGINEER' WHERE id = ANY(%s)",
        ([member_one, member_two],),
    )
    insert_field_provenance(db_conn, "person", member_one, "occupation", "ENGINEER", member_one_source)
    insert_field_provenance(db_conn, "person", member_two, "occupation", "ENGINEER", member_two_source)

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_one, member_two})

    assert not _person_exists(db_conn, member_one)
    assert not _person_exists(db_conn, member_two)
    assert (
        db_conn.execute("SELECT occupation FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[0] == "ENGINEER"
    )
    provenance_rows = db_conn.execute(
        """
        SELECT entity_id, field_value, source_record_id, is_current
        FROM core.field_provenance
        WHERE entity_type = 'person'
          AND field_name = 'occupation'
          AND source_record_id = ANY(%s)
        """,
        ([member_one_source, member_two_source],),
    ).fetchall()
    assert {(row[0], row[1], row[2]) for row in provenance_rows} == {
        (canonical_id, "ENGINEER", member_one_source),
        (canonical_id, "ENGINEER", member_two_source),
    }
    assert sum(1 for row in provenance_rows if row[3]) == 1, "one preserved observation is the current winner"


def test_person_absorption_blocks_when_absorbed_members_disagree_on_consensus_scalar(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_one, member_two = _canonical_and_two_members(db_conn, prefix="ConsensusConflict")
    data_source_id = _insert_data_source(db_conn, name="consensus-conflict-source")
    member_one_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="consensus-conflict-one"
    )
    member_two_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="consensus-conflict-two"
    )
    db_conn.execute("UPDATE core.person SET occupation = 'ENGINEER' WHERE id = %s", (member_one,))
    db_conn.execute("UPDATE core.person SET occupation = 'LAWYER' WHERE id = %s", (member_two,))
    insert_field_provenance(db_conn, "person", member_one, "occupation", "ENGINEER", member_one_source)
    insert_field_provenance(db_conn, "person", member_two, "occupation", "LAWYER", member_two_source)

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_one, member_two})
    assert exc_info.value.reason == _BLOCKER_CONFLICTING_CONSENSUS_SCALAR
    assert _person_exists(db_conn, member_one)
    assert _person_exists(db_conn, member_two)
    assert db_conn.execute("SELECT occupation FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[0] is None


def test_person_absorption_blocks_on_conflicting_anchor_scalar_without_source(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id = uuid4()
    member_id = uuid4()
    # Both people carry a non-null date_of_birth that disagrees; the absorbed anchor has no
    # source attribution, so the merge must block rather than silently pick a winner.
    _insert_person(
        db_conn,
        person_id=canonical_id,
        canonical_name="Anchor Canonical",
        first_name="Anchor",
        last_name="Canonical",
        date_of_birth=date(1970, 1, 1),
        identifiers={},
    )
    _insert_person(
        db_conn,
        person_id=member_id,
        canonical_name="Anchor Member",
        first_name="Anchor",
        last_name="Member",
        date_of_birth=date(1980, 5, 5),
        identifiers={},
    )

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    assert exc_info.value.reason == _BLOCKER_CONFLICTING_ANCHOR_SCALAR
    assert _person_exists(db_conn, member_id)
    assert db_conn.execute("SELECT date_of_birth FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[
        0
    ] == date(1970, 1, 1)


def test_person_absorption_fills_anchor_scalar_from_attributed_absorbed_row(
    db_conn: psycopg.Connection,
) -> None:
    """The `_without_source` qualifier is load-bearing: attribution turns the blocker into a fill.

    Same shape as `..._blocks_on_unattributed_anchor_scalar_fill` below, differing ONLY in whether
    the absorbed `date_of_birth` carries a `core.field_provenance` row. An implementation that
    blocks on any absorbed-supplied anchor scalar regardless of attribution fails here while still
    passing every positive blocker fixture.
    """
    canonical_id = uuid4()
    member_id = uuid4()
    _insert_person(
        db_conn,
        person_id=canonical_id,
        canonical_name="Attributed Canonical",
        first_name="Attributed",
        last_name="Canonical",
        date_of_birth=None,
        identifiers={},
    )
    _insert_person(
        db_conn,
        person_id=member_id,
        canonical_name="Attributed Member",
        first_name="Attributed",
        last_name="Member",
        date_of_birth=date(1980, 5, 5),
        identifiers={},
    )
    data_source_id = _insert_data_source(db_conn, name="anchor-attributed-source")
    dob_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="anchor-attributed")
    insert_field_provenance(db_conn, "person", member_id, "date_of_birth", "1980-05-05", dob_source)

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id), "an attributed consensus fill is not a blocker"
    assert db_conn.execute("SELECT date_of_birth FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[
        0
    ] == date(1980, 5, 5), "the attributed absorbed anchor fills the canonical NULL"
    assert (
        db_conn.execute(
            """
            SELECT entity_id FROM core.field_provenance
            WHERE entity_type = 'person' AND field_name = 'date_of_birth' AND source_record_id = %s
            """,
            (dob_source,),
        ).fetchone()[0]
        == canonical_id
    ), "the attribution that authorised the fill follows the scalar onto the survivor"


def test_person_absorption_blocks_on_unattributed_anchor_scalar_fill(
    db_conn: psycopg.Connection,
) -> None:
    """Identical to the fixture above except the absorbed anchor has no source attribution."""
    canonical_id = uuid4()
    member_id = uuid4()
    _insert_person(
        db_conn,
        person_id=canonical_id,
        canonical_name="Unattributed Canonical",
        first_name="Unattributed",
        last_name="Canonical",
        date_of_birth=None,
        identifiers={},
    )
    _insert_person(
        db_conn,
        person_id=member_id,
        canonical_name="Unattributed Member",
        first_name="Unattributed",
        last_name="Member",
        date_of_birth=date(1980, 5, 5),
        identifiers={},
    )

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    assert exc_info.value.reason == _BLOCKER_CONFLICTING_ANCHOR_SCALAR
    assert _person_exists(db_conn, member_id)
    assert db_conn.execute("SELECT date_of_birth FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[0] is None


def test_person_absorption_blocks_on_conflicting_singleton_identifier(
    db_conn: psycopg.Connection,
) -> None:
    # Identifiers are not right-side-wins: non-conflicting keys union, but a singleton anchor
    # (`bioguide_id`) holding two different values means these are not the same person.
    canonical_id = uuid4()
    member_id = uuid4()
    _insert_person(
        db_conn,
        person_id=canonical_id,
        canonical_name="Ident Canonical",
        first_name="Ident",
        last_name="Canonical",
        date_of_birth=None,
        identifiers={"bioguide_id": "B000001"},
    )
    _insert_person(
        db_conn,
        person_id=member_id,
        canonical_name="Ident Member",
        first_name="Ident",
        last_name="Member",
        date_of_birth=None,
        identifiers={"bioguide_id": "B000999"},
    )

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    assert exc_info.value.reason == _BLOCKER_CONFLICTING_IDENTIFIER
    assert _person_exists(db_conn, member_id)
    assert db_conn.execute("SELECT identifiers FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[0] == {
        "bioguide_id": "B000001"
    }


def test_person_absorption_blocks_when_date_of_birth_and_year_of_birth_disagree(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_one, member_two = _canonical_and_two_members(db_conn, prefix="DobYear")
    data_source_id = _insert_data_source(db_conn, name="dob-year-source")
    dob_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="dob-year-dob")
    year_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="dob-year-year")
    db_conn.execute("UPDATE core.person SET date_of_birth = %s WHERE id = %s", (date(1980, 5, 5), member_one))
    db_conn.execute("UPDATE core.person SET year_of_birth = 1979 WHERE id = %s", (member_two,))
    insert_field_provenance(db_conn, "person", member_one, "date_of_birth", "1980-05-05", dob_source)
    insert_field_provenance(db_conn, "person", member_two, "year_of_birth", "1979", year_source)

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_one, member_two})
    assert exc_info.value.reason == _BLOCKER_DOB_YEAR_MISMATCH
    assert _person_exists(db_conn, member_one)
    assert _person_exists(db_conn, member_two)
    assert db_conn.execute(
        "SELECT date_of_birth, year_of_birth FROM core.person WHERE id = %s", (canonical_id,)
    ).fetchone() == (None, None)


def test_person_absorption_skips_consensus_fill_when_provenance_names_another_value(
    db_conn: psycopg.Connection,
) -> None:
    """Attribution must support the SELECTED value, not merely the field name.

    The absorbed row holds `occupation = 'ENGINEER'` while its only `core.field_provenance` row
    for `occupation` records 'LAWYER'. Nothing sources 'ENGINEER', so an irreversible merge must
    leave the canonical NULL alone instead of publishing an unsourced scalar.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="ConsensusMismatch")
    data_source_id = _insert_data_source(db_conn, name="consensus-mismatch-source")
    member_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="consensus-mismatch"
    )
    db_conn.execute("UPDATE core.person SET occupation = 'ENGINEER' WHERE id = %s", (member_id,))
    insert_field_provenance(db_conn, "person", member_id, "occupation", "LAWYER", member_source)

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    assert db_conn.execute("SELECT occupation FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[0] is None, (
        "a provenance row for a different value must not authorise the consensus fill"
    )


def test_person_absorption_blocks_when_anchor_provenance_names_another_value(
    db_conn: psycopg.Connection,
) -> None:
    """An anchor scalar whose provenance names a different date is unattributed, hence a blocker."""
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="AnchorMismatch")
    data_source_id = _insert_data_source(db_conn, name="anchor-mismatch-source")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="anchor-mismatch")
    db_conn.execute("UPDATE core.person SET date_of_birth = %s WHERE id = %s", (date(1980, 5, 5), member_id))
    insert_field_provenance(db_conn, "person", member_id, "date_of_birth", "1975-01-01", member_source)

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    assert exc_info.value.reason == _BLOCKER_CONFLICTING_ANCHOR_SCALAR
    assert _person_exists(db_conn, member_id)
    assert db_conn.execute("SELECT date_of_birth FROM core.person WHERE id = %s", (canonical_id,)).fetchone()[0] is None


def test_person_absorption_fills_structured_name_fields_without_field_provenance(
    db_conn: psycopg.Connection,
) -> None:
    """Structured names fill on consensus alone, because nothing ever attributes them.

    `core/db_ingest.py::insert_field_provenance` is the only writer of `core.field_provenance`,
    and its only caller (`core/people/enrichment/orchestrator.py`) records `occupation`,
    `education`, `bio_text`, and `bio_license`. Requiring attribution for the name fields would be
    a guard that can never pass on live data, so an irreversible merge would silently keep NULL
    names while deleting the row that carried them.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="NameFill")
    db_conn.execute(
        """
        UPDATE core.person
        SET first_name = NULL, middle_name = NULL, last_name = NULL, suffix = NULL
        WHERE id = %s
        """,
        (canonical_id,),
    )
    db_conn.execute(
        "UPDATE core.person SET middle_name = 'Quinn', suffix = 'Jr.' WHERE id = %s",
        (member_id,),
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert not _person_exists(db_conn, member_id)
    assert db_conn.execute(
        "SELECT first_name, middle_name, last_name, suffix FROM core.person WHERE id = %s",
        (canonical_id,),
    ).fetchone() == ("NameFill", "Quinn", "Member", "Jr."), (
        "unattributable consensus scalars must still fill the canonical NULL"
    )
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.field_provenance WHERE entity_type = 'person' AND entity_id = %s",
            (canonical_id,),
        ).fetchone()[0]
        == 0
    ), "the fill happened with no attribution row anywhere in the component"
