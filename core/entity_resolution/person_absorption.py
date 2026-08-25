"""Conflict-aware physical absorption of resolved ``core.person`` rows.

`core/entity_resolution/persist.py::persist_auto_merge_clusters()` stays the only entry point;
this module owns the dependent moves, field precedence, tombstone, and restricted DELETE that
turn a `PersonAbsorptionPlan` into an irreversible merge. Nothing here commits — the caller's
execution savepoint owns the transaction boundary.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID
from weakref import WeakKeyDictionary

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from core.entity_resolution.candidacy_merge import repoint_candidacy_person
from core.entity_resolution.cluster_provenance import copy_entity_source_links
from core.entity_resolution.person_absorption_preflight import (
    ANCHOR_FIELDS,
    BIOGRAPHY_FIELDS,
    CONSENSUS_FIELDS,
    PersonAbsorptionBlocked,
    PersonAbsorptionPlan,
    preflight_person_absorption,
)

__all__ = [
    "PersonAbsorptionBlocked",
    "PersonAbsorptionPlan",
    "PersonAbsorptionSummary",
    "absorb_person_component",
    "preflight_person_absorption",
    "register_person_absorption_summaries",
    "summarize_person_absorption",
]

_HANDLED_TABLES = (
    "cf.candidate",
    "cf.transaction",
    "prop.ownership",
    "core.donor_cluster_person",
    "core.person_portrait",
    "civic.candidacy",
    "civic.officeholding",
    "core.entity_source",
    "core.field_provenance",
    "core.contact_point",
    "core.entity_address",
)


class PersonAbsorptionSummary(BaseModel):
    """Counts produced by one successful person-cluster persistence call."""

    absorbed_person_count: int = 0
    dependent_move_counts: dict[str, int] = Field(default_factory=lambda: dict.fromkeys(_HANDLED_TABLES, 0))


# Read-back channel for the most recent `persist_auto_merge_clusters()` call on a connection.
# Each registration replaces the previous one, so the mapping holds at most one batch per live
# connection instead of accumulating an entry per cluster for the life of that connection.
_SUMMARIES_BY_CONNECTION: WeakKeyDictionary[psycopg.Connection[Any], dict[UUID, PersonAbsorptionSummary]] = (
    WeakKeyDictionary()
)


def _move_plain_foreign_keys(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
) -> dict[str, int]:
    statements = {
        "cf.candidate": "UPDATE cf.candidate SET person_id = %s WHERE person_id = ANY(%s)",
        "cf.transaction": (
            "UPDATE cf.transaction SET contributor_person_id = %s WHERE contributor_person_id = ANY(%s)"
        ),
        "prop.ownership": "UPDATE prop.ownership SET owner_person_id = %s WHERE owner_person_id = ANY(%s)",
        "core.donor_cluster_person": ("UPDATE core.donor_cluster_person SET person_id = %s WHERE person_id = ANY(%s)"),
    }
    counts: dict[str, int] = {}
    for table_name, statement in statements.items():
        result = conn.execute(statement, (plan.canonical_person_id, plan.absorbed_person_ids))
        counts[table_name] = result.rowcount
    return counts


def _move_portraits(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
) -> int:
    rows = conn.execute(
        """
        SELECT id, dedup_key, status FROM core.person_portrait
        WHERE person_id = ANY(%s)
        ORDER BY id
        """,
        (plan.absorbed_person_ids,),
    ).fetchall()
    for portrait_id, dedup_key, status in rows:
        duplicate = conn.execute(
            "SELECT id, status FROM core.person_portrait WHERE person_id = %s AND dedup_key = %s",
            (plan.canonical_person_id, dedup_key),
        ).fetchone()
        if duplicate is None:
            conn.execute(
                "UPDATE core.person_portrait SET person_id = %s WHERE id = %s",
                (plan.canonical_person_id, portrait_id),
            )
            continue
        duplicate_id, duplicate_status = duplicate
        # `idx_person_portrait_dedup` forbids two rows sharing a dedup_key on one person, so the
        # colliding absorbed row cannot move: the retained duplicate inherits its active state
        # instead. Preflight has already rejected a component holding two distinct active portraits,
        # so promoting here can never collide with `idx_person_portrait_active_per_person`.
        if status == "active" and duplicate_status != "active":
            conn.execute(
                "UPDATE core.person_portrait SET status = 'active', updated_at = NOW() WHERE id = %s",
                (duplicate_id,),
            )
        conn.execute("DELETE FROM core.person_portrait WHERE id = %s", (portrait_id,))
    return len(rows)


def _move_candidacies(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
) -> int:
    rows = conn.execute(
        "SELECT id, person_id FROM civic.candidacy WHERE person_id = ANY(%s) ORDER BY id",
        (plan.absorbed_person_ids,),
    ).fetchall()
    for candidacy_id, person_id in rows:
        repoint_candidacy_person(
            conn,
            candidacy_id=candidacy_id,
            expected_person_id=person_id,
            target_person_id=plan.canonical_person_id,
        )
    return len(rows)


def _matching_officeholding_id(
    conn: psycopg.Connection[Any],
    canonical_person_id: UUID,
    source_officeholding_id: UUID,
) -> UUID | None:
    row = conn.execute(
        """
        SELECT target.id
        FROM civic.officeholding AS source
        JOIN civic.officeholding AS target
          ON target.person_id = %s
         AND target.office_id = source.office_id
         AND target.valid_period = source.valid_period
         AND target.electoral_division_id IS NOT DISTINCT FROM source.electoral_division_id
         AND target.holder_status = source.holder_status
         AND target.date_precision = source.date_precision
        WHERE source.id = %s
        ORDER BY target.id
        LIMIT 1
        """,
        (canonical_person_id, source_officeholding_id),
    ).fetchone()
    return None if row is None else row[0]


def _move_officeholdings(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
) -> int:
    rows = conn.execute(
        "SELECT id FROM civic.officeholding WHERE person_id = ANY(%s) ORDER BY id",
        (plan.absorbed_person_ids,),
    ).fetchall()
    for (officeholding_id,) in rows:
        matching_id = _matching_officeholding_id(conn, plan.canonical_person_id, officeholding_id)
        if matching_id is None:
            conn.execute(
                "UPDATE civic.officeholding SET person_id = %s, updated_at = NOW() WHERE id = %s",
                (plan.canonical_person_id, officeholding_id),
            )
            continue
        copy_entity_source_links(
            conn,
            entity_type="officeholding",
            source_id=officeholding_id,
            target_id=matching_id,
            delete_source=True,
        )
        conn.execute("DELETE FROM civic.officeholding WHERE id = %s", (officeholding_id,))
    return len(rows)


def _move_field_provenance(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
    filled_fields: set[str],
) -> int:
    rows = conn.execute(
        """
        SELECT id, field_name, field_value, source_record_id
        FROM core.field_provenance
        WHERE entity_type = 'person' AND entity_id = ANY(%s)
        ORDER BY id
        """,
        (plan.absorbed_person_ids,),
    ).fetchall()
    conn.execute(
        """
        UPDATE core.field_provenance SET is_current = FALSE
        WHERE entity_type = 'person' AND entity_id = ANY(%s) AND is_current
        """,
        (plan.absorbed_person_ids,),
    )
    for row_id, field_name, field_value, source_record_id in rows:
        duplicate = conn.execute(
            """
            SELECT id FROM core.field_provenance
            WHERE entity_type = 'person' AND entity_id = %s
              AND field_name = %s AND field_value = %s AND source_record_id = %s
            """,
            (plan.canonical_person_id, field_name, field_value, source_record_id),
        ).fetchone()
        if duplicate is not None:
            conn.execute("DELETE FROM core.field_provenance WHERE id = %s", (row_id,))
        else:
            conn.execute(
                "UPDATE core.field_provenance SET entity_id = %s WHERE id = %s",
                (plan.canonical_person_id, row_id),
            )
    _select_fill_provenance_winners(conn, plan.canonical_person_id, filled_fields)
    return len(rows)


def _select_fill_provenance_winners(
    conn: psycopg.Connection[Any],
    canonical_person_id: UUID,
    filled_fields: set[str],
) -> None:
    for field_name in sorted(filled_fields):
        current = conn.execute(
            """
            SELECT 1 FROM core.field_provenance
            WHERE entity_type = 'person' AND entity_id = %s AND field_name = %s AND is_current
            """,
            (canonical_person_id, field_name),
        ).fetchone()
        if current is not None:
            continue
        # Bind the promoted current row to the value the survivor actually stores: with more than
        # one moved observation for a filled field, lowest-id would publish an attribution that
        # contradicts `core.person`. `to_jsonb(person) ->> field_name` renders the stored scalar
        # exactly as ingest wrote `field_value`. If no row names it, the field keeps zero current
        # rows rather than promoting an unrelated observation.
        winner = conn.execute(
            """
            SELECT provenance.id
            FROM core.field_provenance AS provenance
            JOIN core.person AS survivor ON survivor.id = provenance.entity_id
            WHERE provenance.entity_type = 'person' AND provenance.entity_id = %s
              AND provenance.field_name = %s
              AND provenance.field_value = (to_jsonb(survivor) ->> %s)
            ORDER BY provenance.id LIMIT 1
            """,
            (canonical_person_id, field_name, field_name),
        ).fetchone()
        if winner is not None:
            conn.execute("UPDATE core.field_provenance SET is_current = TRUE WHERE id = %s", (winner[0],))


def _move_contact_points(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
) -> int:
    rows = conn.execute(
        """
        SELECT id, type, value_raw, role, is_preferred
        FROM core.contact_point
        WHERE owner_type = 'person' AND owner_id = ANY(%s)
        ORDER BY id
        """,
        (plan.absorbed_person_ids,),
    ).fetchall()
    # "Preferred" is a per-channel fact: a preferred email and a preferred phone do not conflict,
    # so demotion is scoped to the contact type that already has a claim. Demoting across types
    # would discard an unrelated fact in a merge that cannot be undone.
    claimed_preferred_types = {
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT type FROM core.contact_point
            WHERE owner_type = 'person' AND owner_id = %s AND is_preferred
            """,
            (plan.canonical_person_id,),
        ).fetchall()
    }
    for row_id, point_type, value_raw, role, is_preferred in rows:
        duplicate = conn.execute(
            """
            SELECT id FROM core.contact_point
            WHERE owner_type = 'person' AND owner_id = %s
              AND type = %s AND value_raw = %s AND role IS NOT DISTINCT FROM %s
            """,
            (plan.canonical_person_id, point_type, value_raw, role),
        ).fetchone()
        if duplicate is not None:
            # Both natural-key indexes forbid moving the colliding row, so the preferred fact it
            # carries has to survive on the retained duplicate rather than disappear with it.
            if is_preferred and point_type not in claimed_preferred_types:
                conn.execute(
                    "UPDATE core.contact_point SET is_preferred = TRUE, updated_at = NOW() WHERE id = %s",
                    (duplicate[0],),
                )
                claimed_preferred_types.add(point_type)
            conn.execute("DELETE FROM core.contact_point WHERE id = %s", (row_id,))
            continue
        keep_preferred = is_preferred and point_type not in claimed_preferred_types
        conn.execute(
            "UPDATE core.contact_point SET owner_id = %s, is_preferred = %s, updated_at = NOW() WHERE id = %s",
            (plan.canonical_person_id, keep_preferred, row_id),
        )
        if keep_preferred:
            claimed_preferred_types.add(point_type)
    return len(rows)


def _move_entity_addresses(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
) -> int:
    rows = conn.execute(
        """
        SELECT id, address_id, address_role, valid_period
        FROM core.entity_address
        WHERE entity_type = 'person' AND entity_id = ANY(%s)
        ORDER BY id
        """,
        (plan.absorbed_person_ids,),
    ).fetchall()
    for row_id, address_id, address_role, valid_period in rows:
        overlap = conn.execute(
            """
            SELECT 1 FROM core.entity_address
            WHERE entity_type = 'person' AND entity_id = %s
              AND address_id = %s AND address_role = %s AND valid_period && %s
            LIMIT 1
            """,
            (plan.canonical_person_id, address_id, address_role, valid_period),
        ).fetchone()
        if overlap is not None:
            conn.execute("DELETE FROM core.entity_address WHERE id = %s", (row_id,))
        else:
            conn.execute(
                "UPDATE core.entity_address SET entity_id = %s WHERE id = %s",
                (plan.canonical_person_id, row_id),
            )
    return len(rows)


def _update_canonical_person(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
) -> set[str]:
    fills = {**plan.scalar_fills, **plan.biography_fill}
    primary_address_survived = bool(plan.primary_address_link_ids) and (
        conn.execute(
            """
            SELECT 1 FROM core.entity_address
            WHERE id = ANY(%s) AND entity_type = 'person' AND entity_id = %s
            LIMIT 1
            """,
            (plan.primary_address_link_ids, plan.canonical_person_id),
        ).fetchone()
        is not None
    )
    conn.execute(
        """
        UPDATE core.person
        SET first_name = COALESCE(first_name, %(first_name)s),
            middle_name = COALESCE(middle_name, %(middle_name)s),
            last_name = COALESCE(last_name, %(last_name)s),
            suffix = COALESCE(suffix, %(suffix)s),
            occupation = COALESCE(occupation, %(occupation)s),
            education = COALESCE(education, %(education)s),
            bio_text = COALESCE(bio_text, %(bio_text)s),
            bio_source_url = COALESCE(bio_source_url, %(bio_source_url)s),
            bio_license = COALESCE(bio_license, %(bio_license)s),
            bio_pulled_at = COALESCE(bio_pulled_at, %(bio_pulled_at)s),
            date_of_birth = COALESCE(date_of_birth, %(date_of_birth)s),
            year_of_birth = COALESCE(year_of_birth, %(year_of_birth)s),
            primary_address_id = COALESCE(primary_address_id, %(primary_address_id)s),
            identifiers = %(identifiers)s,
            name_variants = %(name_variants)s,
            updated_at = NOW()
        WHERE id = %(canonical_person_id)s
        """,
        {
            **dict.fromkeys((*CONSENSUS_FIELDS, *BIOGRAPHY_FIELDS, *ANCHOR_FIELDS)),
            **fills,
            "primary_address_id": plan.primary_address_id if primary_address_survived else None,
            "identifiers": Jsonb(plan.merged_identifiers),
            "name_variants": plan.merged_name_variants,
            "canonical_person_id": plan.canonical_person_id,
        },
    )
    return set(fills)


def _rechain_earlier_absorptions(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
) -> None:
    """Point tombstones of previously absorbed people at the person who now survives.

    An absorbed person may itself have been the canonical survivor of an earlier merge. Its
    tombstones carry a real FK to `core.person`, so the chain has to be re-pointed before the
    restricted DELETE, and re-pointing keeps every historical absorbed id resolvable to a live row.
    """
    conn.execute(
        """
        UPDATE core.person_absorption
        SET canonical_person_id = %s
        WHERE canonical_person_id = ANY(%s)
        """,
        (plan.canonical_person_id, plan.absorbed_person_ids),
    )


def _insert_tombstones_and_delete(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
    cluster_id: UUID,
    merged_by: str,
) -> int:
    _rechain_earlier_absorptions(conn, plan)
    deleted = 0
    for absorbed_person_id in plan.absorbed_person_ids:
        payload_row = conn.execute(
            "SELECT to_jsonb(person_row) FROM core.person AS person_row WHERE id = %s",
            (absorbed_person_id,),
        ).fetchone()
        if payload_row is None:
            continue
        conn.execute(
            """
            INSERT INTO core.person_absorption (
                absorbed_person_id, canonical_person_id, cluster_id, merged_by, absorbed_payload
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (absorbed_person_id, plan.canonical_person_id, cluster_id, merged_by, Jsonb(payload_row[0])),
        )
        deleted += conn.execute("DELETE FROM core.person WHERE id = %s", (absorbed_person_id,)).rowcount
    return deleted


def absorb_person_component(
    conn: psycopg.Connection[Any],
    plan: PersonAbsorptionPlan,
    cluster_id: UUID,
    merged_by: str,
) -> PersonAbsorptionSummary:
    """Apply one preflighted component without committing the caller's transaction."""
    counts = dict.fromkeys(_HANDLED_TABLES, 0)
    if not plan.absorbed_person_ids:
        return PersonAbsorptionSummary(dependent_move_counts=counts)
    counts.update(_move_plain_foreign_keys(conn, plan))
    counts["core.person_portrait"] = _move_portraits(conn, plan)
    counts["civic.candidacy"] = _move_candidacies(conn, plan)
    counts["civic.officeholding"] = _move_officeholdings(conn, plan)
    counts["core.contact_point"] = _move_contact_points(conn, plan)
    counts["core.entity_address"] = _move_entity_addresses(conn, plan)
    filled_fields = _update_canonical_person(conn, plan)
    counts["core.field_provenance"] = _move_field_provenance(conn, plan, filled_fields)
    counts["core.entity_source"] = plan.entity_source_move_count
    absorbed_count = _insert_tombstones_and_delete(conn, plan, cluster_id, merged_by)
    return PersonAbsorptionSummary(
        absorbed_person_count=absorbed_count,
        dependent_move_counts=counts,
    )


def register_person_absorption_summaries(
    conn: psycopg.Connection[Any],
    summaries: list[tuple[UUID, PersonAbsorptionSummary]],
) -> None:
    """Publish this batch's summaries, superseding the previous batch's, once persistence succeeds."""
    _SUMMARIES_BY_CONNECTION[conn] = dict(summaries)


def _visible_tombstone_counts(
    conn: psycopg.Connection[Any],
    cluster_ids: list[UUID],
) -> dict[UUID, int]:
    """Count the `core.person_absorption` tombstones the caller's transaction can currently see.

    Every absorbed person leaves exactly one tombstone stamped with its cluster id, all written
    inside the caller's savepoint. A rolled-back savepoint therefore takes the tombstones with it,
    and a cached count that no longer matches stops describing anything a reader can observe. One
    grouped read answers the whole batch, rather than a round-trip per cluster.
    """
    rows = conn.execute(
        """
        SELECT cluster_id, count(*)
        FROM core.person_absorption
        WHERE cluster_id = ANY(%s)
        GROUP BY cluster_id
        """,
        (cluster_ids,),
    ).fetchall()
    return {cluster_id: tombstone_count for cluster_id, tombstone_count in rows}


def summarize_person_absorption(
    conn: psycopg.Connection[Any],
    cluster_ids: list[UUID],
) -> PersonAbsorptionSummary:
    """Return the per-table result for clusters whose absorption is still transaction-visible."""
    connection_summaries = _SUMMARIES_BY_CONNECTION.get(conn, {})
    known_cluster_ids = [cluster_id for cluster_id in cluster_ids if cluster_id in connection_summaries]
    tombstone_counts = _visible_tombstone_counts(conn, known_cluster_ids) if known_cluster_ids else {}
    counts = dict.fromkeys(_HANDLED_TABLES, 0)
    absorbed_count = 0
    for cluster_id in known_cluster_ids:
        summary = connection_summaries[cluster_id]
        if tombstone_counts.get(cluster_id, 0) != summary.absorbed_person_count:
            connection_summaries.pop(cluster_id, None)
            continue
        absorbed_count += summary.absorbed_person_count
        for table_name, move_count in summary.dependent_move_counts.items():
            counts[table_name] += move_count
    return PersonAbsorptionSummary(
        absorbed_person_count=absorbed_count,
        dependent_move_counts=counts,
    )
