"""Conflict-safe `civic.candidacy` person repoint rule.

Canonical owner of the "move one candidacy row to a canonical person" merge
semantics shared by the roster candidacy resolver, the federal spine loader, and
Stage 4 person absorption. It lives in ``core`` so those consumers depend on a
lower-level ER helper instead of importing back into ``domains.civics``.
"""

from __future__ import annotations

from uuid import UUID

import psycopg

from core.entity_resolution.cluster_provenance import copy_entity_source_links


def _merge_colliding_candidacies(
    cursor: psycopg.Cursor[tuple[object, ...]],
    *,
    source_candidacy_id: UUID,
    target_candidacy_id: UUID,
) -> None:
    cursor.execute(
        """
        UPDATE civic.candidacy AS target
        SET
            party = COALESCE(target.party, source.party),
            name_on_ballot = COALESCE(target.name_on_ballot, source.name_on_ballot),
            is_unexpired_term = COALESCE(target.is_unexpired_term, source.is_unexpired_term),
            raw_fields = COALESCE(target.raw_fields, source.raw_fields),
            committee_id = COALESCE(target.committee_id, source.committee_id),
            filing_date = COALESCE(target.filing_date, source.filing_date),
            status = COALESCE(target.status, source.status),
            incumbent_challenge = COALESCE(target.incumbent_challenge, source.incumbent_challenge),
            candidate_number = COALESCE(target.candidate_number, source.candidate_number),
            source_record_id = COALESCE(target.source_record_id, source.source_record_id),
            updated_at = NOW()
        FROM civic.candidacy AS source
        WHERE target.id = %s
          AND source.id = %s
        """,
        (target_candidacy_id, source_candidacy_id),
    )
    # Copy provenance onto the surviving row and drop the collapsed candidacy's now-orphaned links:
    # `entity_source.entity_id` is polymorphic with no FK, so a stale 'candidacy' link would survive
    # the DELETE below with nothing to catch it.
    copy_entity_source_links(
        cursor,
        entity_type="candidacy",
        source_id=source_candidacy_id,
        target_id=target_candidacy_id,
        delete_source=True,
    )
    cursor.execute(
        """
        DELETE FROM civic.candidacy
        WHERE id = %s
        """,
        (source_candidacy_id,),
    )


def repoint_candidacy_person(
    conn: psycopg.Connection,
    *,
    candidacy_id: UUID,
    expected_person_id: UUID,
    target_person_id: UUID,
) -> bool:
    """Move one candidacy row to a canonical person with conflict-safe merge semantics.

    When the target person already has a candidacy in the same contest, we merge
    the source row into the canonical target row and copy the source provenance
    links before deleting the now-redundant source row.
    """
    if expected_person_id == target_person_id:
        return False

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT contest_id
            FROM civic.candidacy
            WHERE id = %s
              AND person_id = %s
            """,
            (candidacy_id, expected_person_id),
        )
        source_row = cur.fetchone()
        if source_row is None:
            return False
        contest_id = source_row[0]

        cur.execute(
            """
            SELECT id
            FROM civic.candidacy
            WHERE person_id = %s
              AND contest_id = %s
            LIMIT 1
            """,
            (target_person_id, contest_id),
        )
        existing_target_row = cur.fetchone()

        if existing_target_row is not None:
            _merge_colliding_candidacies(
                cur,
                source_candidacy_id=candidacy_id,
                target_candidacy_id=existing_target_row[0],
            )
            return True

        cur.execute(
            """
            UPDATE civic.candidacy
            SET person_id = %s,
                updated_at = NOW()
            WHERE id = %s
              AND person_id = %s
            """,
            (target_person_id, candidacy_id, expected_person_id),
        )
        return cur.rowcount == 1
