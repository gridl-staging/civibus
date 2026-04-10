
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from core.entity_resolution.pairing import canonicalize_entity_pair

_MATCH_DECISION_BASE_KEYS = {
    "entity_id_a",
    "entity_id_b",
    "confidence",
    "decision",
    "decided_by",
    "decision_method",
}
_ENTITY_TABLE_NAMES = {
    "person": "person",
    "organization": "organization",
}

# Stage 4 rerun policy for `core.entity_source` (single source of truth):
# 1. Merge writes one canonical row per `(source_record_id, extraction_role)` and stores
#    contributing owner IDs in `_er_source_entity_ids` when the tuple came from >1 entity.
# 2. Every rerun first unwinds active-cluster rows back to their owner entities using that
#    metadata so dropped members regain provenance before new clusters are applied.
# 3. If multiple entities still share a source tuple after unwind, re-merge keeps canonical
#    ownership and records sorted owner IDs to make behavior deterministic and reversible.
_ENTITY_SOURCE_OWNER_IDS_KEY = "_er_source_entity_ids"


def _entity_table_name(entity_type: str) -> str:
    table_name = _ENTITY_TABLE_NAMES.get(entity_type)
    if table_name is None:
        raise ValueError(f"entity_type must be 'person' or 'organization', got {entity_type!r}")
    return table_name


def _match_evidence_from_pair(pair: dict[str, Any]) -> dict[str, Any] | None:
    evidence = {key: value for key, value in pair.items() if key not in _MATCH_DECISION_BASE_KEYS}
    return evidence or None


def _jsonb_or_none(payload: dict[str, Any] | None) -> Jsonb | None:
    return None if payload is None else Jsonb(payload)


def log_splink_run_start(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    splink_version: str,
    model_config: dict[str, Any],
    started_at: datetime,
) -> UUID:
    run_id = uuid4()
    conn.execute(
        """
        INSERT INTO core.splink_run (
            id,
            entity_type,
            splink_version,
            model_config,
            started_at,
            status
        )
        VALUES (%s, %s, %s, %s, %s, 'running')
        """,
        (run_id, entity_type, splink_version, Jsonb(model_config), started_at),
    )
    return run_id


def _update_splink_run_status(
    conn: psycopg.Connection,
    run_id: UUID,
    *,
    status: str,
    completed_at: datetime,
    duration_seconds: float,
    error_message: str | None = None,
    counts: dict[str, int] | None = None,
) -> None:
    counts = counts or {}
    conn.execute(
        """
        UPDATE core.splink_run
        SET status = %s,
            completed_at = %s,
            duration_seconds = %s,
            error_message = %s,
            input_record_count = %s,
            pairs_compared = %s,
            matches_found = %s,
            auto_merged = %s,
            probable_matches = %s,
            possible_matches = %s
        WHERE id = %s
        """,
        (
            status,
            completed_at,
            duration_seconds,
            error_message,
            counts.get("input_record_count"),
            counts.get("pairs_compared"),
            counts.get("matches_found"),
            counts.get("auto_merged"),
            counts.get("probable_matches"),
            counts.get("possible_matches"),
            run_id,
        ),
    )


def log_splink_run_complete(
    conn: psycopg.Connection,
    run_id: UUID,
    *,
    completed_at: datetime,
    duration_seconds: float,
    counts: dict[str, int],
) -> None:
    _update_splink_run_status(
        conn,
        run_id,
        status="completed",
        completed_at=completed_at,
        duration_seconds=duration_seconds,
        counts=counts,
    )


def log_splink_run_failed(
    conn: psycopg.Connection,
    run_id: UUID,
    *,
    completed_at: datetime,
    duration_seconds: float,
    error_message: str,
) -> None:
    _update_splink_run_status(
        conn,
        run_id,
        status="failed",
        completed_at=completed_at,
        duration_seconds=duration_seconds,
        error_message=error_message,
    )


def _lock_active_match_decision_id(
    cursor: psycopg.Cursor[tuple[Any, ...]],
    *,
    entity_type: str,
    entity_id_a: UUID,
    entity_id_b: UUID,
) -> UUID | None:
    cursor.execute(
        """
        SELECT id
        FROM core.match_decision
        WHERE entity_type = %s
          AND entity_id_a = %s
          AND entity_id_b = %s
          AND superseded_by IS NULL
        FOR UPDATE
        """,
        (entity_type, entity_id_a, entity_id_b),
    )
    row = cursor.fetchone()
    if row is None:
        return None

    return row[0]


def _set_match_decision_supersession(
    cursor: psycopg.Cursor[tuple[Any, ...]],
    *,
    decision_id: UUID,
    superseded_by: UUID,
    superseded_at: datetime,
) -> None:
    cursor.execute(
        """
        UPDATE core.match_decision
        SET superseded_by = %s,
            superseded_at = %s
        WHERE id = %s
        """,
        (superseded_by, superseded_at, decision_id),
    )


def persist_match_decisions(
    conn: psycopg.Connection,
    classified_pairs: list[dict[str, Any]],
    entity_type: str,
) -> list[UUID]:
    inserted_decision_ids: list[UUID] = []
    decided_at = datetime.now(UTC)

    with conn.cursor() as cursor:
        for pair in classified_pairs:
            entity_id_a, entity_id_b = canonicalize_entity_pair(pair["entity_id_a"], pair["entity_id_b"])
            decision_id = uuid4()
            active_decision_id = _lock_active_match_decision_id(
                cursor,
                entity_type=entity_type,
                entity_id_a=entity_id_a,
                entity_id_b=entity_id_b,
            )
            if active_decision_id is not None:
                # Use self-reference to satisfy fk_match_superseded while removing this row
                # from the active unique index before the replacement insert.
                _set_match_decision_supersession(
                    cursor,
                    decision_id=active_decision_id,
                    superseded_by=active_decision_id,
                    superseded_at=decided_at,
                )

            cursor.execute(
                """
                INSERT INTO core.match_decision (
                    id,
                    entity_type,
                    entity_id_a,
                    entity_id_b,
                    decision,
                    confidence,
                    decided_by,
                    decision_method,
                    match_evidence,
                    decided_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    decision_id,
                    entity_type,
                    entity_id_a,
                    entity_id_b,
                    pair["decision"],
                    pair["confidence"],
                    pair["decided_by"],
                    pair["decision_method"],
                    _jsonb_or_none(_match_evidence_from_pair(pair)),
                    decided_at,
                ),
            )
            if active_decision_id is not None:
                _set_match_decision_supersession(
                    cursor,
                    decision_id=active_decision_id,
                    superseded_by=decision_id,
                    superseded_at=decided_at,
                )
            inserted_decision_ids.append(decision_id)

    return inserted_decision_ids


def _supersede_active_cluster_members(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    member_ids: list[UUID],
    split_at: datetime,
    split_by: str,
) -> None:
    conn.execute(
        """
        UPDATE core.cluster_member
        SET split_at = %s,
            split_by = %s
        WHERE entity_type = %s
          AND entity_id = ANY(%s)
          AND split_at IS NULL
        """,
        (split_at, split_by, entity_type, member_ids),
    )


def _insert_cluster_members(
    conn: psycopg.Connection,
    *,
    cluster_id: UUID,
    entity_type: str,
    component: dict[str, Any],
    merged_at: datetime,
    merged_by: str,
) -> None:
    canonical_entity_id = component["canonical_entity_id"]
    for member_id in component["member_ids"]:
        conn.execute(
            """
            INSERT INTO core.cluster_member (
                cluster_id,
                entity_type,
                entity_id,
                is_canonical,
                merged_at,
                merged_by
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                cluster_id,
                entity_type,
                member_id,
                member_id == canonical_entity_id,
                merged_at,
                merged_by,
            ),
        )


def _set_cluster_fields_on_entities(
    conn: psycopg.Connection,
    *,
    entity_table: str,
    member_ids: list[UUID],
    cluster_id: UUID | None,
    cluster_confidence: float | None,
) -> None:
    if not member_ids:
        return

    conn.execute(
        f"""
        UPDATE core.{entity_table}
        SET er_cluster_id = %s,
            er_confidence = %s
        WHERE id = ANY(%s)
        """,
        (cluster_id, cluster_confidence, member_ids),
    )


def _active_cluster_member_ids(
    conn: psycopg.Connection,
    *,
    entity_type: str,
) -> list[UUID]:
    rows = conn.execute(
        """
        SELECT entity_id
        FROM core.cluster_member
        WHERE entity_type = %s
          AND split_at IS NULL
        ORDER BY entity_id
        """,
        (entity_type,),
    ).fetchall()
    return [row[0] for row in rows]


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


def _unwind_entity_source_links(
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

    for row_id, entity_id, source_record_id, extraction_role, confidence, extracted_fields in rows:
        owner_ids = _entity_source_owner_ids(entity_id, extracted_fields)
        restored_payload = _entity_source_payload_without_owner_ids(extracted_fields)
        conn.execute("DELETE FROM core.entity_source WHERE id = %s", (row_id,))
        for owner_id in owner_ids:
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
                    _jsonb_or_none(restored_payload),
                ),
            )


def _relink_entity_source_to_canonical(
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
        merged_payload = _entity_source_payload_with_owner_ids(
            keep_row[5],
            row_entity_id=canonical_entity_id,
            owner_ids=owner_ids,
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
                _jsonb_or_none(merged_payload),
                keep_row[0],
            ),
        )

        delete_ids = [row[0] for row in source_rows if row[0] != keep_row[0]]
        if delete_ids:
            conn.execute("DELETE FROM core.entity_source WHERE id = ANY(%s)", (delete_ids,))


def _validated_cluster_member_ids(
    *,
    canonical_entity_id: UUID,
    member_ids: set[UUID] | list[UUID],
) -> list[UUID]:
    normalized_member_ids = sorted(member_ids)
    if canonical_entity_id not in normalized_member_ids:
        raise ValueError("canonical_entity_id must be present in member_ids")
    return normalized_member_ids


def persist_auto_merge_clusters(
    conn: psycopg.Connection,
    auto_merge_clusters: list[dict[str, Any]],
    entity_type: str,
    *,
    merged_by: str = "splink_v1",
) -> list[UUID]:
    entity_table = _entity_table_name(entity_type)
    merged_at = datetime.now(UTC)
    cluster_ids: list[UUID] = []
    normalized_components = [
        {
            **component,
            "member_ids": _validated_cluster_member_ids(
                canonical_entity_id=component["canonical_entity_id"],
                member_ids=component["member_ids"],
            ),
        }
        for component in auto_merge_clusters
    ]
    prior_member_ids = _active_cluster_member_ids(
        conn,
        entity_type=entity_type,
    )

    if prior_member_ids:
        _unwind_entity_source_links(
            conn,
            entity_type=entity_type,
            member_ids=prior_member_ids,
        )
        _supersede_active_cluster_members(
            conn,
            entity_type=entity_type,
            member_ids=prior_member_ids,
            split_at=merged_at,
            split_by=merged_by,
        )
        _set_cluster_fields_on_entities(
            conn,
            entity_table=entity_table,
            member_ids=prior_member_ids,
            cluster_id=None,
            cluster_confidence=None,
        )

    for component in normalized_components:
        cluster_id = uuid4()
        canonical_entity_id = component["canonical_entity_id"]
        member_ids = component["member_ids"]
        cluster_confidence = component["min_confidence"]

        conn.execute(
            """
            INSERT INTO core.entity_cluster (
                id,
                entity_type,
                canonical_entity_id,
                cluster_confidence,
                member_count
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                cluster_id,
                entity_type,
                canonical_entity_id,
                cluster_confidence,
                len(member_ids),
            ),
        )
        _insert_cluster_members(
            conn,
            cluster_id=cluster_id,
            entity_type=entity_type,
            component=component,
            merged_at=merged_at,
            merged_by=merged_by,
        )
        _set_cluster_fields_on_entities(
            conn,
            entity_table=entity_table,
            member_ids=member_ids,
            cluster_id=cluster_id,
            cluster_confidence=cluster_confidence,
        )
        _relink_entity_source_to_canonical(
            conn,
            entity_type=entity_type,
            member_ids=member_ids,
            canonical_entity_id=canonical_entity_id,
        )
        cluster_ids.append(cluster_id)

    return cluster_ids
