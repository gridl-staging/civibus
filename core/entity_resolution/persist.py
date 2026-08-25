"""Persist entity-resolution match decisions and clusters to the database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from core.entity_resolution.cluster_provenance import (
    jsonb_or_none,
    relink_entity_source_to_canonical,
    unwind_entity_source_links,
)
from core.entity_resolution.pairing import canonicalize_entity_pair
from core.entity_resolution.person_absorption import (
    PersonAbsorptionBlocked,
    PersonAbsorptionPlan,
    PersonAbsorptionSummary,
    absorb_person_component,
    preflight_person_absorption,
    register_person_absorption_summaries,
    summarize_person_absorption,
)

# `person_absorption` owns the physical merge; this module stays the single public entry point
# for cluster persistence, so its two caller-facing symbols are re-exported here.
__all__ = [
    "PersonAbsorptionBlocked",
    "log_splink_run_complete",
    "log_splink_run_failed",
    "log_splink_run_start",
    "persist_auto_merge_clusters",
    "persist_match_decisions",
    "summarize_person_absorption",
]

_MATCH_DECISION_BASE_KEYS = {
    "entity_id_a",
    "entity_id_b",
    "confidence",
    "decision",
    "decided_by",
    "decision_method",
}
_ENTITY_TABLE_NAMES = {
    "donor_identity": "donor_identity",
    "person": "person",
    "organization": "organization",
}


def _entity_table_name(entity_type: str) -> str:
    table_name = _ENTITY_TABLE_NAMES.get(entity_type)
    if table_name is None:
        supported_types = sorted(_ENTITY_TABLE_NAMES)
        supported_message = ", ".join(f"'{supported_type}'" for supported_type in supported_types[:-1])
        raise ValueError(
            f"entity_type must be one of {supported_message}, or '{supported_types[-1]}', got {entity_type!r}"
        )
    return table_name


def _match_evidence_from_pair(pair: dict[str, Any]) -> dict[str, Any] | None:
    evidence = {key: value for key, value in pair.items() if key not in _MATCH_DECISION_BASE_KEYS}
    return evidence or None


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
                    jsonb_or_none(_match_evidence_from_pair(pair)),
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


def _validated_cluster_member_ids(
    *,
    canonical_entity_id: UUID,
    member_ids: set[UUID] | list[UUID],
) -> list[UUID]:
    normalized_member_ids = sorted(member_ids)
    if canonical_entity_id not in normalized_member_ids:
        raise ValueError("canonical_entity_id must be present in member_ids")
    return normalized_member_ids


def _active_donor_person_ids_by_member_id(
    conn: psycopg.Connection,
    member_ids: list[UUID],
) -> dict[UUID, UUID]:
    if not member_ids:
        return {}

    rows = conn.execute(
        """
        SELECT cm.entity_id, dcp.person_id
        FROM core.cluster_member cm
        JOIN core.donor_cluster_person dcp ON dcp.cluster_id = cm.cluster_id
        WHERE cm.entity_type = 'donor_identity'
          AND cm.entity_id = ANY(%s)
          AND cm.split_at IS NULL
        """,
        (member_ids,),
    ).fetchall()
    return {entity_id: person_id for entity_id, person_id in rows}


def _insert_person_for_donor_identity(
    conn: psycopg.Connection,
    donor_identity_id: UUID,
) -> UUID:
    row = conn.execute(
        """
        SELECT canonical_name, contributor_occupation
        FROM core.donor_identity
        WHERE id = %s
        """,
        (donor_identity_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"donor identity {donor_identity_id} does not exist")

    person_id = uuid4()
    conn.execute(
        """
        INSERT INTO core.person (id, canonical_name, occupation)
        VALUES (%s, %s, %s)
        """,
        (person_id, row[0], row[1]),
    )
    return person_id


def _reusable_donor_person_id_for_component(
    *,
    canonical_entity_id: UUID,
    member_ids: list[UUID],
    prior_person_ids_by_member_id: dict[UUID, UUID],
    claimed_prior_person_ids: set[UUID],
) -> UUID | None:
    prioritized_person_ids: list[UUID] = []
    canonical_person_id = prior_person_ids_by_member_id.get(canonical_entity_id)
    if canonical_person_id is not None:
        prioritized_person_ids.append(canonical_person_id)

    prioritized_person_ids.extend(
        sorted(
            {
                prior_person_ids_by_member_id[member_id]
                for member_id in member_ids
                if member_id in prior_person_ids_by_member_id
            }
            - set(prioritized_person_ids)
        )
    )
    return next(
        (person_id for person_id in prioritized_person_ids if person_id not in claimed_prior_person_ids),
        None,
    )


def _persist_donor_cluster_person_mapping(
    conn: psycopg.Connection,
    *,
    cluster_id: UUID,
    canonical_entity_id: UUID,
    person_id: UUID | None,
) -> None:
    mapped_person_id = person_id or _insert_person_for_donor_identity(conn, canonical_entity_id)
    conn.execute(
        """
        INSERT INTO core.donor_cluster_person (cluster_id, person_id)
        VALUES (%s, %s)
        """,
        (cluster_id, mapped_person_id),
    )


def _clear_prior_active_clusters(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    entity_table: str,
    member_ids: list[UUID],
    merged_at: datetime,
    merged_by: str,
) -> None:
    """Retire the previous generation of clusters so this run can republish from a clean slate."""
    unwind_entity_source_links(
        conn,
        entity_type=entity_type,
        member_ids=member_ids,
    )
    _supersede_active_cluster_members(
        conn,
        entity_type=entity_type,
        member_ids=member_ids,
        split_at=merged_at,
        split_by=merged_by,
    )
    _set_cluster_fields_on_entities(
        conn,
        entity_table=entity_table,
        member_ids=member_ids,
        cluster_id=None,
        cluster_confidence=None,
    )


def _publish_cluster_identity(
    conn: psycopg.Connection,
    *,
    cluster_id: UUID,
    entity_type: str,
    entity_table: str,
    component: dict[str, Any],
    merge_stamp: tuple[datetime, str],
) -> None:
    """Record the cluster, its membership history, and the canonical provenance collapse."""
    canonical_entity_id = component["canonical_entity_id"]
    member_ids = component["member_ids"]
    cluster_confidence = component["min_confidence"]
    merged_at, merged_by = merge_stamp

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
    relink_entity_source_to_canonical(
        conn,
        entity_type=entity_type,
        member_ids=member_ids,
        canonical_entity_id=canonical_entity_id,
    )


def _promote_donor_cluster_to_person(
    conn: psycopg.Connection,
    *,
    cluster_id: UUID,
    component: dict[str, Any],
    prior_person_ids_by_member_id: dict[UUID, UUID],
    claimed_person_ids: set[UUID],
) -> None:
    """Auto-merge is the precision gate that authorizes donor-cluster promotion."""
    canonical_entity_id = component["canonical_entity_id"]
    reusable_person_id = _reusable_donor_person_id_for_component(
        canonical_entity_id=canonical_entity_id,
        member_ids=component["member_ids"],
        prior_person_ids_by_member_id=prior_person_ids_by_member_id,
        claimed_prior_person_ids=claimed_person_ids,
    )
    if reusable_person_id is not None:
        claimed_person_ids.add(reusable_person_id)
    _persist_donor_cluster_person_mapping(
        conn,
        cluster_id=cluster_id,
        canonical_entity_id=canonical_entity_id,
        person_id=reusable_person_id,
    )


def _person_absorption_plans(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    components: list[dict[str, Any]],
) -> list[PersonAbsorptionPlan | None]:
    """Preflight every person component up front so a blocker rejects the batch before any mutation."""
    if entity_type != "person":
        return [None] * len(components)
    return list(preflight_person_absorption(conn, components))


def persist_auto_merge_clusters(
    conn: psycopg.Connection,
    auto_merge_clusters: list[dict[str, Any]],
    entity_type: str,
    *,
    merged_by: str = "splink_v1",
) -> list[UUID]:
    """Publish auto-merge components as clusters and return the new cluster ids.

    Person components are also absorbed physically: every whole batch is preflighted first, so a
    `PersonAbsorptionBlocked` conflict aborts the call before the first row mutates. Per-table move
    counts are read back through `summarize_person_absorption()` rather than by widening this
    return type, which existing callers index as a plain `list[UUID]`. Nothing here commits; the
    caller's execution savepoint owns the transaction boundary.
    """
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
    absorption_plans = _person_absorption_plans(
        conn,
        entity_type=entity_type,
        components=normalized_components,
    )
    prior_member_ids = _active_cluster_member_ids(
        conn,
        entity_type=entity_type,
    )
    prior_donor_person_ids_by_member_id = (
        _active_donor_person_ids_by_member_id(conn, prior_member_ids) if entity_type == "donor_identity" else {}
    )
    claimed_donor_person_ids: set[UUID] = set()
    absorption_summaries: list[tuple[UUID, PersonAbsorptionSummary]] = []

    if prior_member_ids:
        _clear_prior_active_clusters(
            conn,
            entity_type=entity_type,
            entity_table=entity_table,
            member_ids=prior_member_ids,
            merged_at=merged_at,
            merged_by=merged_by,
        )

    for component, absorption_plan in zip(normalized_components, absorption_plans, strict=True):
        cluster_id = uuid4()
        _publish_cluster_identity(
            conn,
            cluster_id=cluster_id,
            entity_type=entity_type,
            entity_table=entity_table,
            component=component,
            merge_stamp=(merged_at, merged_by),
        )
        if absorption_plan is not None:
            absorption_summaries.append(
                (cluster_id, absorb_person_component(conn, absorption_plan, cluster_id, merged_by))
            )
        if entity_type == "donor_identity":
            _promote_donor_cluster_to_person(
                conn,
                cluster_id=cluster_id,
                component=component,
                prior_person_ids_by_member_id=prior_donor_person_ids_by_member_id,
                claimed_person_ids=claimed_donor_person_ids,
            )
        cluster_ids.append(cluster_id)

    register_person_absorption_summaries(conn, absorption_summaries)
    return cluster_ids
