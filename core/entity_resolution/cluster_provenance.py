"""Collapse and restore ``core.entity_source`` ownership across ER cluster generations.

Absorbed people are the one-way exception to the reversible policy below: their tombstones drop
them from the restored owner set, because the row whose provenance they carried no longer exists.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

# Stage 4 rerun policy for `core.entity_source` (single source of truth):
# 1. Merge writes one canonical row per `(source_record_id, extraction_role)` and stores
#    contributing owner IDs in `_er_source_entity_ids` when the tuple came from >1 entity.
# 2. Every rerun first unwinds active-cluster rows back to their owner entities using that
#    metadata so dropped members regain provenance before new clusters are applied.
# 3. If multiple entities still share a source tuple after unwind, re-merge keeps canonical
#    ownership and records sorted owner IDs to make behavior deterministic and reversible.
_ENTITY_SOURCE_OWNER_IDS_KEY = "_er_source_entity_ids"


def jsonb_or_none(payload: dict[str, Any] | None) -> Jsonb | None:
    return None if payload is None else Jsonb(payload)


def copy_entity_source_links(
    executor: psycopg.Connection | psycopg.Cursor,
    *,
    entity_type: str,
    source_id: UUID,
    target_id: UUID,
    delete_source: bool,
) -> None:
    """Copy one entity's `core.entity_source` links onto another, deduped on the natural key.

    Single owner of the "collapse one polymorphic entity's provenance onto its survivor" rule
    shared by person absorption (`_move_officeholdings`) and the candidacy repoint merge. Because
    `entity_source.entity_id` is polymorphic with no FK, a caller that deletes the collapsed entity
    must pass ``delete_source=True`` so the now-orphaned links go with it.
    """
    executor.execute(
        """
        INSERT INTO core.entity_source (
            entity_type, entity_id, source_record_id, extraction_role, confidence, extracted_fields
        )
        SELECT entity_type, %s, source_record_id, extraction_role, confidence, extracted_fields
        FROM core.entity_source
        WHERE entity_type = %s AND entity_id = %s
        ON CONFLICT (entity_type, entity_id, source_record_id, extraction_role) DO NOTHING
        """,
        (target_id, entity_type, source_id),
    )
    if delete_source:
        executor.execute(
            "DELETE FROM core.entity_source WHERE entity_type = %s AND entity_id = %s",
            (entity_type, source_id),
        )


def _entity_source_owner_ids(
    entity_id: UUID,
    extracted_fields: dict[str, Any] | None,
) -> list[UUID]:
    if not extracted_fields:
        return [entity_id]

    owner_ids = extracted_fields.get(_ENTITY_SOURCE_OWNER_IDS_KEY)
    if owner_ids is None:
        return [entity_id]

    return sorted({UUID(str(owner_id)) for owner_id in owner_ids})


def _entity_source_payload_without_owner_ids(
    extracted_fields: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not extracted_fields:
        return None

    payload = dict(extracted_fields)
    payload.pop(_ENTITY_SOURCE_OWNER_IDS_KEY, None)
    return payload or None


def _entity_source_payload_with_owner_ids(
    extracted_fields: dict[str, Any] | None,
    *,
    row_entity_id: UUID,
    owner_ids: list[UUID],
) -> dict[str, Any] | None:
    payload = _entity_source_payload_without_owner_ids(extracted_fields)
    if owner_ids != [row_entity_id]:
        payload = dict(payload or {})
        payload[_ENTITY_SOURCE_OWNER_IDS_KEY] = [str(owner_id) for owner_id in owner_ids]
    return payload or None


def _absorbed_person_ids_for_unwind(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    member_ids: list[UUID],
) -> set[UUID]:
    if entity_type != "person" or not member_ids:
        return set()

    rows = conn.execute(
        """
        SELECT absorbed_person_id
        FROM core.person_absorption
        WHERE absorbed_person_id = ANY(%s)
        """,
        (member_ids,),
    ).fetchall()
    return {row[0] for row in rows}


def unwind_entity_source_links(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    member_ids: list[UUID],
) -> None:
    """Restore merged `entity_source` rows to their owner entities for rerun reconciliation."""
    if not member_ids:
        return

    rows = conn.execute(
        """
        SELECT id, entity_id, source_record_id, extraction_role, confidence, extracted_fields
        FROM core.entity_source
        WHERE entity_type = %s
          AND entity_id = ANY(%s)
        ORDER BY id
        """,
        (entity_type, member_ids),
    ).fetchall()
    absorbed_person_ids = _absorbed_person_ids_for_unwind(
        conn,
        entity_type=entity_type,
        member_ids=member_ids,
    )

    for row_id, entity_id, source_record_id, extraction_role, confidence, extracted_fields in rows:
        restored_owner_ids = [
            owner_id
            for owner_id in _entity_source_owner_ids(entity_id, extracted_fields)
            if owner_id not in absorbed_person_ids
        ]
        if not restored_owner_ids and entity_id not in absorbed_person_ids:
            restored_owner_ids = [entity_id]
        restored_payload = _entity_source_payload_without_owner_ids(extracted_fields)
        restored_payload_json = jsonb_or_none(restored_payload)
        if restored_owner_ids == [entity_id]:
            # The row already sits on its only surviving owner, so drop the collapsed owner list
            # in place. Recreating an equivalent row would churn the link's identity, which callers
            # and dependent-row assertions treat as a durable handle.
            conn.execute(
                "UPDATE core.entity_source SET extracted_fields = %s WHERE id = %s",
                (restored_payload_json, row_id),
            )
            continue
        conn.execute("DELETE FROM core.entity_source WHERE id = %s", (row_id,))
        for owner_id in restored_owner_ids:
            conn.execute(
                """
                INSERT INTO core.entity_source (
                    entity_type,
                    entity_id,
                    source_record_id,
                    extraction_role,
                    confidence,
                    extracted_fields
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (entity_type, entity_id, source_record_id, extraction_role)
                DO NOTHING
                """,
                (
                    entity_type,
                    owner_id,
                    source_record_id,
                    extraction_role,
                    confidence,
                    restored_payload_json,
                ),
            )


def relink_entity_source_to_canonical(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    member_ids: list[UUID],
    canonical_entity_id: UUID,
) -> None:
    """Collapse member provenance onto the canonical entity after rerun unwind.

    Shared source tuples are merged deterministically: keep the canonical row when present,
    otherwise keep the lowest-id row from the stable ordered query, then stamp owner IDs.
    """
    if len(member_ids) <= 1:
        return

    rows = conn.execute(
        """
        SELECT id, entity_id, source_record_id, extraction_role, confidence, extracted_fields
        FROM core.entity_source
        WHERE entity_type = %s
          AND entity_id = ANY(%s)
        ORDER BY source_record_id, extraction_role, id
        """,
        (entity_type, member_ids),
    ).fetchall()

    grouped_rows: dict[tuple[UUID, str | None], list[tuple[Any, ...]]] = {}
    for row in rows:
        grouped_rows.setdefault((row[2], row[3]), []).append(row)

    for source_rows in grouped_rows.values():
        keep_row = next((row for row in source_rows if row[1] == canonical_entity_id), source_rows[0])
        owner_ids = sorted({owner_id for row in source_rows for owner_id in _entity_source_owner_ids(row[1], row[5])})
        merged_payload_json = jsonb_or_none(
            _entity_source_payload_with_owner_ids(
                keep_row[5],
                row_entity_id=canonical_entity_id,
                owner_ids=owner_ids,
            )
        )
        conn.execute(
            """
            UPDATE core.entity_source
            SET entity_id = %s,
                extracted_fields = %s
            WHERE id = %s
            """,
            (
                canonical_entity_id,
                merged_payload_json,
                keep_row[0],
            ),
        )

        delete_ids = [row[0] for row in source_rows if row[0] != keep_row[0]]
        if delete_ids:
            conn.execute("DELETE FROM core.entity_source WHERE id = ANY(%s)", (delete_ids,))
