"""Person absorption atomicity, rollback, orphan-cleanup, and per-table summary specimens.

Production owner: `core/entity_resolution/person_absorption.py`.
Merge contract: `docs/design/2026_08_21_er_general_merge_design.md`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest

from core.db_ingest import insert_entity_address, insert_field_provenance
from core.entity_resolution.persist import (
    PersonAbsorptionBlocked,
    persist_auto_merge_clusters,
    summarize_person_absorption,
)
from core.entity_resolution.persist_clusters_test_support import (
    _BLOCKER_TWO_ACTIVE_PORTRAITS,
    _absorb_person_cluster,
    _canonical_and_member,
    _cluster_component,
    _insert_address_row,
    _insert_cf_candidate,
    _insert_cf_transaction,
    _insert_civic_candidacy,
    _insert_civic_contest,
    _insert_civic_office,
    _insert_contact_point,
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
    _insert_data_source,
    _insert_entity_source,
    _insert_source_record,
)

pytestmark = pytest.mark.integration

# `summarize_person_absorption()` is a sibling accessor rather than a widened
# `persist_auto_merge_clusters()` return, because that entry point must keep its `list[UUID]`
# shape (cli.py:379, tuning.py:230, test_graph_edges.py:518 ignore it;
# test_transaction_counterparty_resolver.py:1336 indexes `[0]`).


# Known-answer per-table move counts for `_seed_handled_dependents()`. Tables with no absorbable
# row still appear with an explicit 0 so a summary that drops a table cannot pass. This mapping is
# the single owner of the handled-table set; `_DEPENDENT_MOVE_TABLES` below is derived from its keys
# so the two literals cannot silently diverge when Stage 2 adds or drops a handled table.
_EXPECTED_COMPOSITE_MOVE_COUNTS = {
    "cf.candidate": 1,
    "cf.transaction": 2,
    "prop.ownership": 1,
    "core.donor_cluster_person": 1,
    "core.person_portrait": 0,
    "civic.candidacy": 1,
    "civic.officeholding": 0,
    "core.entity_source": 1,
    "core.field_provenance": 1,
    "core.contact_point": 1,
    "core.entity_address": 1,
}

# Every dependent table the absorber handles, and therefore every key
# `summarize_person_absorption(...).dependent_move_counts` must report. A table with no
# absorbed rows reports an explicit 0 rather than being omitted, so an implementation that
# silently forgets a table cannot pass by leaving its key out of the mapping.
_DEPENDENT_MOVE_TABLES = frozenset(_EXPECTED_COMPOSITE_MOVE_COUNTS)


def _absorb_person_components(
    db_conn: psycopg.Connection,
    components: list[tuple[UUID, set[UUID]]],
    *,
    min_confidence: float = 0.98,
) -> list[UUID]:
    """Invoke the orchestrator with a MULTI-component batch, the way real callers do.

    `core/entity_resolution/tuning.py::_apply_candidate_clusters` hands the entire
    `clustered_pairs["auto_merge_clusters"]` list to a single call, so batch-level blocker
    semantics are part of the contract, not an implementation detail.
    """
    return persist_auto_merge_clusters(
        db_conn,
        [
            _cluster_component(
                canonical_entity_id=canonical_id,
                member_ids=member_ids,
                min_confidence=min_confidence,
            )
            for canonical_id, member_ids in components
        ],
        "person",
    )


def _seed_handled_dependents(
    db_conn: psycopg.Connection,
    *,
    canonical_id: UUID,
    member_id: UUID,
    prefix: str,
) -> dict[str, object]:
    """Seed one absorbable row per handled dependent table, with no blocker present.

    Row counts match `_EXPECTED_COMPOSITE_MOVE_COUNTS`. The returned ids let a caller assert either
    that every row moved to the canonical person or that none of them moved at all.
    """
    data_source_id = _insert_data_source(db_conn, name=f"{prefix}-source")
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key=f"{prefix}-member")
    committee_id = _insert_fec_committee(
        db_conn, fec_committee_id=f"C{uuid4().int % 100_000_000:08d}", name=f"{prefix} Committee"
    )
    filing_id = _insert_fec_filing(db_conn, committee_id=committee_id, filing_fec_id=f"FEC-{uuid4().hex[:12]}")
    parcel_id = _insert_prop_parcel(db_conn)
    office_id = _insert_civic_office(db_conn)
    contest_id = _insert_civic_contest(db_conn, office_id=office_id)
    address_id = _insert_address_row(db_conn, raw_address=f"{prefix} 900 Composite Rd")
    # The member holds an attributed `education` value the canonical row lacks, so a successful
    # absorption MUST consensus-fill `core.person.education` on the canonical row. Without the
    # scalar actually set here, a "blocked component applied no fill" assertion would hold whether
    # or not the implementation applies fills at all.
    db_conn.execute("UPDATE core.person SET education = 'State University' WHERE id = %s", (member_id,))
    insert_field_provenance(db_conn, "person", member_id, "education", "State University", member_source)
    return {
        "member_source": member_source,
        "candidate_id": _insert_cf_candidate(db_conn, person_id=member_id, name=f"{prefix} Cand"),
        "transaction_ids": [
            _insert_cf_transaction(
                db_conn, filing_id=filing_id, committee_id=committee_id, contributor_person_id=member_id
            )
            for _ in range(_EXPECTED_COMPOSITE_MOVE_COUNTS["cf.transaction"])
        ],
        "ownership_id": _insert_prop_ownership(db_conn, parcel_id=parcel_id, owner_person_id=member_id),
        "donor_cluster_id": _insert_donor_cluster_person(db_conn, person_id=member_id),
        "candidacy_id": _insert_civic_candidacy(db_conn, person_id=member_id, contest_id=contest_id, party="D"),
        "entity_source_id": _insert_entity_source(
            db_conn,
            entity_type="person",
            entity_id=member_id,
            source_record_id=member_source,
            extraction_role="donor",
        ),
        "contact_point_id": _insert_contact_point(
            db_conn, owner_id=member_id, value_raw=f"{prefix}@example.test", source_record_id=member_source
        ),
        "entity_address_id": insert_entity_address(
            db_conn, "person", member_id, address_id, member_source, address_role="mailing"
        ),
    }


def _handled_dependent_owners(db_conn: psycopg.Connection, seeded: dict[str, object]) -> set[UUID]:
    """Return the distinct person id every seeded dependent row currently points at."""
    owners: set[UUID] = set()
    owners.add(
        db_conn.execute("SELECT person_id FROM cf.candidate WHERE id = %s", (seeded["candidate_id"],)).fetchone()[0]
    )
    owners.update(
        row[0]
        for row in db_conn.execute(
            "SELECT contributor_person_id FROM cf.transaction WHERE id = ANY(%s)",
            (seeded["transaction_ids"],),
        ).fetchall()
    )
    owners.add(
        db_conn.execute(
            "SELECT owner_person_id FROM prop.ownership WHERE id = %s", (seeded["ownership_id"],)
        ).fetchone()[0]
    )
    owners.add(
        db_conn.execute(
            "SELECT person_id FROM core.donor_cluster_person WHERE cluster_id = %s",
            (seeded["donor_cluster_id"],),
        ).fetchone()[0]
    )
    owners.add(
        db_conn.execute("SELECT person_id FROM civic.candidacy WHERE id = %s", (seeded["candidacy_id"],)).fetchone()[0]
    )
    owners.add(
        db_conn.execute(
            "SELECT entity_id FROM core.entity_source WHERE id = %s", (seeded["entity_source_id"],)
        ).fetchone()[0]
    )
    owners.add(
        db_conn.execute(
            """
            SELECT entity_id FROM core.field_provenance
            WHERE entity_type = 'person' AND source_record_id = %s AND field_name = 'education'
            """,
            (seeded["member_source"],),
        ).fetchone()[0]
    )
    owners.add(
        db_conn.execute(
            "SELECT owner_id FROM core.contact_point WHERE id = %s", (seeded["contact_point_id"],)
        ).fetchone()[0]
    )
    owners.add(
        db_conn.execute(
            "SELECT entity_id FROM core.entity_address WHERE id = %s", (seeded["entity_address_id"],)
        ).fetchone()[0]
    )
    return owners


# ---- Blocker atomicity (complete-component preflight) ----------------------


def test_person_absorption_blocker_leaves_every_handled_dependent_untouched(
    db_conn: psycopg.Connection,
) -> None:
    """A blocker is evaluated for the complete component BEFORE the first mutation.

    Without this fixture a blocker test passes even when the absorber moves or deduplicates the
    dependents it happens to visit first and only then discovers the conflict, publishing an
    internally inconsistent partial merge. Every handled dependent is seeded here, so a preflight
    that runs late leaves observable damage.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Atomic")
    seeded = _seed_handled_dependents(db_conn, canonical_id=canonical_id, member_id=member_id, prefix="atomic")
    # Blocker: two distinct active portraits (one per person).
    portrait_source = _insert_source_record(
        db_conn,
        data_source_id=_insert_data_source(db_conn, name="atomic-portrait-source"),
        source_record_key="atomic-portrait",
    )
    _insert_person_portrait(
        db_conn,
        person_id=canonical_id,
        source_record_id=portrait_source,
        dedup_key="atomic-canonical",
        status="active",
        image_hash="hash-atomic-canonical",
    )
    _insert_person_portrait(
        db_conn,
        person_id=member_id,
        source_record_id=portrait_source,
        dedup_key="atomic-member",
        status="active",
        image_hash="hash-atomic-member",
    )

    with pytest.raises(PersonAbsorptionBlocked) as exc_info:
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    assert exc_info.value.reason == _BLOCKER_TWO_ACTIVE_PORTRAITS

    # Both people survive and every handled dependent still points at the member.
    assert _person_exists(db_conn, member_id)
    assert _person_exists(db_conn, canonical_id)
    assert _handled_dependent_owners(db_conn, seeded) == {member_id}
    # The fill-only provenance winner was not applied to the survivor either.
    person_rows = db_conn.execute(
        "SELECT id, education, er_cluster_id, er_confidence FROM core.person WHERE id = ANY(%s)",
        ([canonical_id, member_id],),
    ).fetchall()
    by_id = {row[0]: row for row in person_rows}
    assert set(by_id) == {canonical_id, member_id}
    # The absorbed row carries an attributed `education` value that a successful merge would fill
    # into the canonical NULL, so this assertion fails for an implementation that fills before
    # preflighting the component.
    assert by_id[canonical_id][1] is None, "a blocked component must not fill canonical scalars"
    assert by_id[member_id][1] == "State University", "the absorbed row's fillable value is left in place"
    assert all(row[2] is None and row[3] is None for row in person_rows), (
        "a blocked component must not stamp ER cluster state on either person"
    )
    # No cluster identity was published for the rejected component.
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.cluster_member WHERE entity_type = 'person' AND entity_id = ANY(%s)",
            ([canonical_id, member_id],),
        ).fetchone()[0]
        == 0
    )
    assert (
        db_conn.execute(
            """
            SELECT count(*) FROM core.entity_cluster
            WHERE entity_type = 'person' AND canonical_entity_id = ANY(%s)
            """,
            ([canonical_id, member_id],),
        ).fetchone()[0]
        == 0
    )
    # The single current provenance row is still owned by the member, not demoted or repointed.
    provenance_rows = db_conn.execute(
        """
        SELECT entity_id, is_current FROM core.field_provenance
        WHERE entity_type = 'person' AND source_record_id = %s AND field_name = 'education'
        """,
        (seeded["member_source"],),
    ).fetchall()
    assert [(row[0], row[1]) for row in provenance_rows] == [(member_id, True)]


def test_person_absorption_blocker_aborts_the_whole_batch_including_clean_components(
    db_conn: psycopg.Connection,
) -> None:
    """One blocked component aborts the ENTIRE call; no clean sibling component publishes.

    Real callers batch: `core/entity_resolution/tuning.py::_apply_candidate_clusters` passes the
    whole `clustered_pairs["auto_merge_clusters"]` list to a single `persist_auto_merge_clusters()`
    call, and `core/entity_resolution/cli.py` wraps the action in one execution savepoint that it
    rolls back on failure while recording a run failure. The design fixes the semantics: "A blocker
    or restricted-delete failure rolls back the execution savepoint and records the run failure
    without publishing a partial merge" (`docs/design/2026_08_21_er_general_merge_design.md`,
    "Idempotency and transaction boundaries"). So the contract Stages 2-4 implement is
    raise-out-of-the-call, NOT skip-the-blocked-component-and-publish-the-rest.

    The clean component is deliberately FIRST in the batch, so a per-component implementation that
    published it before reaching the blocker would have to be undone by the savepoint, and a
    skip-and-continue implementation fails immediately at `pytest.raises`.
    """
    clean_canonical, clean_member = _canonical_and_member(db_conn, prefix="BatchClean")
    clean_candidate_id = _insert_cf_candidate(db_conn, person_id=clean_member, name="Batch Clean Cand")

    blocked_canonical, blocked_member = _canonical_and_member(db_conn, prefix="BatchBlocked")
    portrait_source = _insert_source_record(
        db_conn,
        data_source_id=_insert_data_source(db_conn, name="batch-portrait-source"),
        source_record_key="batch-portrait",
    )
    _insert_person_portrait(
        db_conn,
        person_id=blocked_canonical,
        source_record_id=portrait_source,
        dedup_key="batch-canonical",
        status="active",
        image_hash="hash-batch-canonical",
    )
    _insert_person_portrait(
        db_conn,
        person_id=blocked_member,
        source_record_id=portrait_source,
        dedup_key="batch-member",
        status="active",
        image_hash="hash-batch-member",
    )

    # `db_conn.transaction()` is the test-local stand-in for the CLI's execution savepoint.
    with pytest.raises(PersonAbsorptionBlocked) as exc_info, db_conn.transaction():
        _absorb_person_components(
            db_conn,
            [
                (clean_canonical, {clean_canonical, clean_member}),
                (blocked_canonical, {blocked_canonical, blocked_member}),
            ],
        )
    assert exc_info.value.reason == _BLOCKER_TWO_ACTIVE_PORTRAITS

    # Nothing from the batch published: the clean component's member survives and its dependent
    # never moved, and the blocked component is untouched.
    assert _person_exists(db_conn, clean_member), "a blocked batch must not absorb its clean components"
    assert _person_exists(db_conn, clean_canonical)
    assert _person_exists(db_conn, blocked_member)
    assert (
        db_conn.execute("SELECT person_id FROM cf.candidate WHERE id = %s", (clean_candidate_id,)).fetchone()[0]
        == clean_member
    ), "a rolled-back batch must not leave a clean component's dependent move applied"
    published_people = [clean_canonical, clean_member, blocked_canonical, blocked_member]
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.cluster_member WHERE entity_type = 'person' AND entity_id = ANY(%s)",
            (published_people,),
        ).fetchone()[0]
        == 0
    ), "no cluster identity is published for any component of an aborted batch"
    assert (
        db_conn.execute(
            "SELECT count(*) FROM core.person WHERE id = ANY(%s) AND er_cluster_id IS NOT NULL",
            (published_people,),
        ).fetchone()[0]
        == 0
    )


# ---- Unhandled direct-FK rollback guard ------------------------------------


def test_person_absorption_unhandled_direct_fk_rolls_back_component(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Rollback")
    # A handled direct FK whose move we can observe reverting when the final DELETE fails.
    candidate_id = _insert_cf_candidate(db_conn, person_id=member_id)
    # A schema-local table with a direct FK to core.person that the absorber does not know about.
    # The final restricted DELETE of the member person must raise ForeignKeyViolation, and the
    # surrounding savepoint must roll back the already-applied candidate move. A regular (non-temp)
    # table is required: a TEMP table may not carry an FK to a permanent table, and the db_conn
    # fixture rolls the whole outer transaction back at teardown so this DDL never persists.
    unhandled_table = f"public.er_unhandled_person_ref_{uuid4().hex[:12]}"
    db_conn.execute(
        f"""
        CREATE TABLE {unhandled_table} (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            person_id UUID NOT NULL REFERENCES core.person(id)
        )
        """
    )
    db_conn.execute(f"INSERT INTO {unhandled_table} (person_id) VALUES (%s)", (member_id,))

    with pytest.raises(psycopg.errors.ForeignKeyViolation), db_conn.transaction():
        _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    # Savepoint rollback: the member survives and its handled FK move is undone.
    assert _person_exists(db_conn, member_id)
    moved = db_conn.execute("SELECT person_id FROM cf.candidate WHERE id = %s", (candidate_id,)).fetchone()
    assert moved is not None
    assert moved[0] == member_id, "a rolled-back component must not leave a half-applied FK move"


# ---- Rerun / idempotency and summary surface -------------------------------


def test_person_absorption_summary_reports_move_and_absorbed_counts(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Summary")
    seeded = _seed_handled_dependents(db_conn, canonical_id=canonical_id, member_id=member_id, prefix="summary")

    cluster_ids = _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
    summary = summarize_person_absorption(db_conn, cluster_ids)

    assert summary.absorbed_person_count == 1
    dependent_move_counts = summary.dependent_move_counts
    # Every handled table is reported, including the ones with nothing to move.
    assert set(dependent_move_counts) == _DEPENDENT_MOVE_TABLES
    assert dict(dependent_move_counts) == _EXPECTED_COMPOSITE_MOVE_COUNTS
    # The reported counts describe real moves.
    assert not _person_exists(db_conn, member_id)
    assert _handled_dependent_owners(db_conn, seeded) == {canonical_id}


def test_person_absorption_second_run_reports_zero_moves_and_absorptions(
    db_conn: psycopg.Connection,
) -> None:
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="Idempotent")
    seeded = _seed_handled_dependents(db_conn, canonical_id=canonical_id, member_id=member_id, prefix="idempotent")

    first_component = {canonical_id, member_id}
    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids=set(first_component))
    assert not _person_exists(db_conn, member_id)

    # A byte-for-byte equivalent rerun replays the ORIGINAL component, absorbed member id included.
    # The absorbed id is a durable alias, so the identical input must be accepted (no rejection for a
    # missing person) and must produce zero further absorptions and zero further dependent moves.
    second_cluster_ids = _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids=set(first_component))
    summary = summarize_person_absorption(db_conn, second_cluster_ids)

    assert summary.absorbed_person_count == 0
    dependent_move_counts = summary.dependent_move_counts
    assert set(dependent_move_counts) == _DEPENDENT_MOVE_TABLES
    assert dict(dependent_move_counts) == dict.fromkeys(_DEPENDENT_MOVE_TABLES, 0)
    # The rerun neither resurrects the absorbed person nor duplicates or re-moves its dependents.
    assert not _person_exists(db_conn, member_id)
    assert _person_exists(db_conn, canonical_id)
    assert _handled_dependent_owners(db_conn, seeded) == {canonical_id}
    assert (
        db_conn.execute(
            "SELECT count(*) FROM cf.transaction WHERE contributor_person_id = %s", (canonical_id,)
        ).fetchone()[0]
        == _EXPECTED_COMPOSITE_MOVE_COUNTS["cf.transaction"]
    )
    assert (
        db_conn.execute(
            """
            SELECT count(*) FROM core.entity_source
            WHERE entity_type = 'person' AND source_record_id = %s
            """,
            (seeded["member_source"],),
        ).fetchone()[0]
        == _EXPECTED_COMPOSITE_MOVE_COUNTS["core.entity_source"]
    )


# ---- Summary rollback and orphan cleanup -----------------------------------


def test_person_absorption_summary_reports_zero_after_savepoint_rollback(
    db_conn: psycopg.Connection,
) -> None:
    """Counts describe rows a caller can still see; a rolled-back batch reports nothing.

    `cli.py::_persist_cluster_results` wraps persistence in a savepoint and records a failed run
    when later work raises, so a summary that keeps reporting absorbed people and dependent moves
    after that rollback is success telemetry for a merge that never landed.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="RollbackSummary")
    seeded = _seed_handled_dependents(db_conn, canonical_id=canonical_id, member_id=member_id, prefix="rollbacksummary")

    cluster_ids: list[UUID] = []
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db_conn.transaction():
        cluster_ids.extend(
            _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})
        )
        assert not _person_exists(db_conn, member_id)
        # Any later failure inside the caller's savepoint discards the whole absorption.
        db_conn.execute(
            "INSERT INTO cf.candidate (id, fec_candidate_id, name, office, person_id) "
            "VALUES (%s, 'H0AA00099', 'Rollback Trigger', 'H', %s)",
            (uuid4(), uuid4()),
        )

    summary = summarize_person_absorption(db_conn, cluster_ids)

    assert summary.absorbed_person_count == 0
    dependent_move_counts = summary.dependent_move_counts
    assert set(dependent_move_counts) == _DEPENDENT_MOVE_TABLES
    assert dict(dependent_move_counts) == dict.fromkeys(_DEPENDENT_MOVE_TABLES, 0)
    # The rollback really did revert the merge the summary must stop claiming.
    assert _person_exists(db_conn, member_id)
    assert _handled_dependent_owners(db_conn, seeded) == {member_id}


def test_person_absorption_leaves_no_entity_source_orphans_for_collapsed_candidacy(
    db_conn: psycopg.Connection,
) -> None:
    """A candidacy collapsed by the repoint rule leaves no `core.entity_source` rows behind.

    `entity_source.entity_id` is polymorphic with no FK, so a stale link pointing at the deleted
    candidacy id would never be caught by a constraint. The copy-with-dedup owner must delete the
    source links, not just copy them.
    """
    canonical_id, member_id = _canonical_and_member(db_conn, prefix="CyOrphan")
    office_id = _insert_civic_office(db_conn)
    contest_id = _insert_civic_contest(db_conn, office_id=office_id)
    data_source_id = _insert_data_source(db_conn, name="candidacy-orphan-source")
    canonical_source = _insert_source_record(
        db_conn, data_source_id=data_source_id, source_record_key="orphan-canonical"
    )
    member_source = _insert_source_record(db_conn, data_source_id=data_source_id, source_record_key="orphan-member")

    _insert_civic_candidacy(
        db_conn, person_id=canonical_id, contest_id=contest_id, party="D", source_record_id=canonical_source
    )
    member_candidacy = _insert_civic_candidacy(
        db_conn, person_id=member_id, contest_id=contest_id, party="R", source_record_id=member_source
    )
    _insert_entity_source(
        db_conn,
        entity_type="candidacy",
        entity_id=member_candidacy,
        source_record_id=member_source,
        extraction_role="candidacy",
    )

    _absorb_person_cluster(db_conn, canonical_id=canonical_id, member_ids={canonical_id, member_id})

    assert db_conn.execute("SELECT count(*) FROM civic.candidacy WHERE id = %s", (member_candidacy,)).fetchone()[0] == 0
    orphan_links = db_conn.execute(
        "SELECT count(*) FROM core.entity_source WHERE entity_type = 'candidacy' AND entity_id = %s",
        (member_candidacy,),
    ).fetchone()[0]
    assert orphan_links == 0, "the collapsed candidacy must leave no entity_source rows behind"


# ---- Summary read-back bounds ----------------------------------------------


def test_person_absorption_summary_reports_only_the_most_recent_batch(
    db_conn: psycopg.Connection,
) -> None:
    """Registered counts describe one persistence call, so the cache cannot grow without bound.

    `summarize_person_absorption()` is the read-back channel for the batch that just ran. Keeping
    every batch a long-lived connection ever persisted would accumulate one entry per cluster for
    the life of the connection.
    """
    first_canonical, first_member = _canonical_and_member(db_conn, prefix="BatchOne")
    second_canonical, second_member = _canonical_and_member(db_conn, prefix="BatchTwo")

    first_cluster_ids = _absorb_person_cluster(
        db_conn, canonical_id=first_canonical, member_ids={first_canonical, first_member}
    )
    second_cluster_ids = _absorb_person_cluster(
        db_conn, canonical_id=second_canonical, member_ids={second_canonical, second_member}
    )

    second_summary = summarize_person_absorption(db_conn, second_cluster_ids)
    assert second_summary.absorbed_person_count == 1
    superseded_summary = summarize_person_absorption(db_conn, first_cluster_ids)
    assert superseded_summary.absorbed_person_count == 0, (
        "an earlier batch's counts are not retained once a later batch registers its own"
    )
    assert dict(superseded_summary.dependent_move_counts) == dict.fromkeys(_DEPENDENT_MOVE_TABLES, 0)
    # The earlier merge itself is untouched; only the read-back channel moved on.
    assert not _person_exists(db_conn, first_member)
    assert _person_exists(db_conn, first_canonical)
