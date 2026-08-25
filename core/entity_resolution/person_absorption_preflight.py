"""Decide whether a resolved `core.person` component may be absorbed, before anything mutates.

Every component of a batch is preflighted first, so a `PersonAbsorptionBlocked` conflict rejects
the whole call with a stable reason slug rather than leaving a half-merged component behind. The
result is a `PersonAbsorptionPlan`: the read-only decisions
`core/entity_resolution/person_absorption.py` then applies.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict

_BLOCKER_TWO_ACTIVE_PORTRAITS = "two_active_portraits"
_BLOCKER_OVERLAPPING_OFFICEHOLDING = "overlapping_officeholding_terms"
_BLOCKER_ACTIVE_NON_MATCH_DECISION = "active_non_match_decision"
_BLOCKER_MANUAL_CONFIRMED_NON_MATCH = "active_manual_confirmed_non_match"
_BLOCKER_CONFLICTING_ANCHOR_SCALAR = "conflicting_anchor_scalar_without_source"
_BLOCKER_CONFLICTING_IDENTIFIER = "conflicting_identifier_anchor"
_BLOCKER_CONFLICTING_CONSENSUS_SCALAR = "conflicting_consensus_scalar"
_BLOCKER_DOB_YEAR_MISMATCH = "date_of_birth_year_mismatch"

# Shared person-scalar precedence groups: preflight decides the fills and
# `person_absorption` writes them, so both read this single owner.
BIOGRAPHY_FIELDS = ("bio_text", "bio_source_url", "bio_license", "bio_pulled_at")
CONSENSUS_FIELDS = ("first_name", "middle_name", "last_name", "suffix", "occupation", "education")
ANCHOR_FIELDS = ("date_of_birth", "year_of_birth")
_FEC_IDENTIFIER_KEYS = frozenset({"fec_candidate_id", "fec_candidate_ids"})

# The person fields the provenance owner actually records. `core/db_ingest.py::insert_field_provenance`
# is the only writer of `core.field_provenance`, and its only caller
# (`core/people/enrichment/orchestrator.py`) records exactly these. Gating an ordinary fill on
# attribution nothing ever writes would be a guard that can never pass, so it would not protect the
# survivor — it would just discard the absorbed value before the row carrying it is deleted.
# `ANCHOR_FIELDS` are deliberately excluded from that reasoning: they are identity anchors, and the
# design requires a source for them even when that means blocking the component.
ATTRIBUTED_PERSON_FIELDS = frozenset({"occupation", "education", "bio_text", "bio_license"})


class PersonAbsorptionBlocked(Exception):
    """Reject a complete person component before any irreversible mutation."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PersonAbsorptionPlan(BaseModel):
    """Read-only component decisions produced by whole-batch preflight."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    canonical_person_id: UUID
    member_ids: list[UUID]
    absorbed_person_ids: list[UUID]
    scalar_fills: dict[str, Any]
    biography_fill: dict[str, Any]
    merged_identifiers: dict[str, Any]
    merged_name_variants: list[str]
    primary_address_id: UUID | None
    primary_address_link_ids: list[UUID]
    entity_source_move_count: int


def _person_rows(
    conn: psycopg.Connection[Any],
    member_ids: list[UUID],
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT * FROM core.person WHERE id = ANY(%s) ORDER BY id",
            (member_ids,),
        )
        return list(cursor.fetchall())


def _validate_component_members(
    conn: psycopg.Connection[Any],
    canonical_person_id: UUID,
    member_ids: list[UUID],
    rows: list[dict[str, Any]],
) -> None:
    existing_ids = {row["id"] for row in rows}
    if canonical_person_id not in existing_ids:
        raise ValueError(f"canonical person {canonical_person_id} does not exist")
    missing_ids = sorted(set(member_ids) - existing_ids)
    if not missing_ids:
        return
    tombstoned_ids = {
        row[0]
        for row in conn.execute(
            "SELECT absorbed_person_id FROM core.person_absorption WHERE absorbed_person_id = ANY(%s)",
            (missing_ids,),
        ).fetchall()
    }
    unknown_ids = sorted(set(missing_ids) - tombstoned_ids)
    if unknown_ids:
        raise ValueError(f"person component contains unknown member ids: {unknown_ids}")


def _raise_if_portraits_conflict(
    conn: psycopg.Connection[Any],
    member_ids: list[UUID],
) -> None:
    active_keys = conn.execute(
        """
        SELECT DISTINCT dedup_key
        FROM core.person_portrait
        WHERE person_id = ANY(%s) AND status = 'active'
        """,
        (member_ids,),
    ).fetchall()
    if len(active_keys) > 1:
        raise PersonAbsorptionBlocked(_BLOCKER_TWO_ACTIVE_PORTRAITS)


def _raise_if_officeholdings_conflict(
    conn: psycopg.Connection[Any],
    member_ids: list[UUID],
) -> None:
    conflict = conn.execute(
        """
        SELECT 1
        FROM civic.officeholding AS left_term
        JOIN civic.officeholding AS right_term
          ON left_term.id < right_term.id
         AND left_term.person_id <> right_term.person_id
         AND left_term.office_id = right_term.office_id
         AND left_term.valid_period && right_term.valid_period
        WHERE left_term.person_id = ANY(%(members)s)
          AND right_term.person_id = ANY(%(members)s)
          AND NOT (
              left_term.valid_period = right_term.valid_period
              AND left_term.electoral_division_id IS NOT DISTINCT FROM right_term.electoral_division_id
              AND left_term.holder_status = right_term.holder_status
              AND left_term.date_precision = right_term.date_precision
          )
        LIMIT 1
        """,
        {"members": member_ids},
    ).fetchone()
    if conflict is not None:
        raise PersonAbsorptionBlocked(_BLOCKER_OVERLAPPING_OFFICEHOLDING)


def _raise_if_identity_history_conflicts(
    conn: psycopg.Connection[Any],
    member_ids: list[UUID],
) -> None:
    active_non_match = conn.execute(
        """
        SELECT 1 FROM core.match_decision
        WHERE entity_type = 'person'
          AND decision = 'no_match'
          AND superseded_by IS NULL
          AND entity_id_a = ANY(%(members)s)
          AND entity_id_b = ANY(%(members)s)
        LIMIT 1
        """,
        {"members": member_ids},
    ).fetchone()
    if active_non_match is not None:
        raise PersonAbsorptionBlocked(_BLOCKER_ACTIVE_NON_MATCH_DECISION)
    active_manual_non_match = conn.execute(
        """
        SELECT 1 FROM core.manual_override
        WHERE entity_type = 'person'
          AND override_decision = 'confirmed_non_match'
          AND superseded_by IS NULL
          AND entity_id_a = ANY(%(members)s)
          AND entity_id_b = ANY(%(members)s)
        LIMIT 1
        """,
        {"members": member_ids},
    ).fetchone()
    if active_manual_non_match is not None:
        raise PersonAbsorptionBlocked(_BLOCKER_MANUAL_CONFIRMED_NON_MATCH)


def _normalized_identifier_values(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    return sorted({str(item).strip() for item in raw_values if str(item).strip()})


def _merge_identifiers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values_by_key: dict[str, dict[str, Any]] = {}
    fec_values: set[str] = set()
    fec_used_plural_form = False
    for row in rows:
        for key, value in (row["identifiers"] or {}).items():
            if key in _FEC_IDENTIFIER_KEYS:
                fec_values.update(_normalized_identifier_values(value))
                fec_used_plural_form = fec_used_plural_form or key == "fec_candidate_ids"
                continue
            normalized = value.strip() if isinstance(value, str) else value
            values_by_key.setdefault(key, {})[json.dumps(normalized, sort_keys=True)] = normalized
    if any(len(values) > 1 for values in values_by_key.values()):
        raise PersonAbsorptionBlocked(_BLOCKER_CONFLICTING_IDENTIFIER)
    merged = {key: next(iter(values.values())) for key, values in values_by_key.items()}
    if len(fec_values) == 1 and not fec_used_plural_form:
        merged["fec_candidate_id"] = next(iter(fec_values))
    elif fec_values:
        merged["fec_candidate_ids"] = sorted(fec_values)
    return merged


def _provenance_supports_stored_value(
    conn: psycopg.Connection[Any],
    person_id: UUID,
    field_name: str,
) -> bool:
    """Report whether a source attributes the value this person row actually stores.

    Attribution is per value, not per field: a provenance row naming some other value never
    authorises copying the stored scalar onto the survivor of an irreversible merge. The stored
    value is rendered by Postgres (`to_jsonb(person) ->> field`) so date, integer, and text columns
    compare against `core.field_provenance.field_value` exactly as ingest wrote them.
    """
    return (
        conn.execute(
            """
            SELECT 1
            FROM core.field_provenance AS attribution
            JOIN core.person AS attributed_person ON attributed_person.id = attribution.entity_id
            WHERE attribution.entity_type = 'person'
              AND attribution.entity_id = %(person_id)s
              AND attribution.field_name = %(field_name)s
              AND attribution.field_value = (to_jsonb(attributed_person) ->> %(field_name)s)
            LIMIT 1
            """,
            {"person_id": person_id, "field_name": field_name},
        ).fetchone()
        is not None
    )


def _consensus_scalar_fills(
    conn: psycopg.Connection[Any],
    canonical_row: dict[str, Any],
    absorbed_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    fills: dict[str, Any] = {}
    for field_name in CONSENSUS_FIELDS:
        if canonical_row[field_name] is not None:
            continue
        values = {row[field_name] for row in absorbed_rows if row[field_name] is not None}
        if len(values) > 1:
            raise PersonAbsorptionBlocked(_BLOCKER_CONFLICTING_CONSENSUS_SCALAR)
        if not values:
            continue
        value = next(iter(values))
        if _consensus_value_is_authorised(conn, absorbed_rows, field_name, value):
            fills[field_name] = value
    return fills


def _consensus_value_is_authorised(
    conn: psycopg.Connection[Any],
    absorbed_rows: list[dict[str, Any]],
    field_name: str,
    value: Any,
) -> bool:
    """Report whether the agreed consensus value may be copied onto the survivor.

    Fields the provenance owner records must have some absorbed member whose attribution names
    this exact value; the rest fill on member agreement alone, since no source could ever witness
    them (see `ATTRIBUTED_PERSON_FIELDS`).
    """
    if field_name not in ATTRIBUTED_PERSON_FIELDS:
        return True
    return any(
        row[field_name] == value and _provenance_supports_stored_value(conn, row["id"], field_name)
        for row in absorbed_rows
    )


def _anchor_scalar_fills(
    conn: psycopg.Connection[Any],
    canonical_row: dict[str, Any],
    absorbed_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Decide the identity-anchor fills, blocking rather than skipping an unsourced one.

    Anchors deliberately do not follow the `ATTRIBUTED_PERSON_FIELDS` rule that lets an ordinary
    consensus scalar fill unattributed: a birth date decides who a person IS, so publishing one no
    source stands behind is worse than refusing the merge. No ingest writes `core.person`'s anchor
    columns today, so the guard is dormant; a writer that starts populating them must record
    attribution through `core/db_ingest.py::insert_field_provenance` alongside the value.
    """
    fills: dict[str, Any] = {}
    for field_name in ANCHOR_FIELDS:
        observations = [(row["id"], row[field_name]) for row in absorbed_rows if row[field_name] is not None]
        values = {value for _, value in observations}
        if canonical_row[field_name] is None and len(values) > 1:
            raise PersonAbsorptionBlocked(_BLOCKER_CONFLICTING_CONSENSUS_SCALAR)
        relevant = canonical_row[field_name] is None or any(
            value != canonical_row[field_name] for _, value in observations
        )
        if relevant and any(
            not _provenance_supports_stored_value(conn, person_id, field_name) for person_id, _ in observations
        ):
            raise PersonAbsorptionBlocked(_BLOCKER_CONFLICTING_ANCHOR_SCALAR)
        if canonical_row[field_name] is None and values:
            fills[field_name] = next(iter(values))
    return fills


def _raise_if_birth_fields_disagree(
    rows: list[dict[str, Any]],
) -> None:
    date_years = {row["date_of_birth"].year for row in rows if row["date_of_birth"] is not None}
    explicit_years = {row["year_of_birth"] for row in rows if row["year_of_birth"] is not None}
    if date_years and explicit_years and date_years != explicit_years:
        raise PersonAbsorptionBlocked(_BLOCKER_DOB_YEAR_MISMATCH)


def _biography_fill(
    conn: psycopg.Connection[Any],
    canonical_row: dict[str, Any],
    absorbed_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(canonical_row[field_name] is not None for field_name in BIOGRAPHY_FIELDS):
        return {}
    complete_rows = [
        row for row in absorbed_rows if all(row[field_name] is not None for field_name in BIOGRAPHY_FIELDS)
    ]
    bundles = {tuple(row[field_name] for field_name in BIOGRAPHY_FIELDS) for row in complete_rows}
    if len(bundles) > 1:
        raise PersonAbsorptionBlocked(_BLOCKER_CONFLICTING_CONSENSUS_SCALAR)
    if not bundles:
        return {}
    # Attribution gates the bundle on the fields the provenance owner actually records (see
    # `ATTRIBUTED_PERSON_FIELDS`); the design gates on "the selected value", which those fields
    # witness. Any complete row's attribution settles the question, because every complete row
    # carries the byte-identical bundle already selected above — asking only the lowest-id row
    # would drop a fully sourced biography that a later member attributes.
    required_attribution = [field_name for field_name in BIOGRAPHY_FIELDS if field_name in ATTRIBUTED_PERSON_FIELDS]
    bundle_is_attributed = any(
        all(_provenance_supports_stored_value(conn, row["id"], field_name) for field_name in required_attribution)
        for row in complete_rows
    )
    if not bundle_is_attributed:
        return {}
    return dict(zip(BIOGRAPHY_FIELDS, next(iter(bundles)), strict=True))


def _merged_name_variants(
    canonical_row: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[str]:
    canonical_name = canonical_row["canonical_name"].strip()
    observed_names = {
        str(value).strip()
        for row in rows
        for value in [row["canonical_name"], *(row["name_variants"] or [])]
        if value is not None and str(value).strip()
    }
    observed_names.discard(canonical_name)
    return sorted(observed_names)


def _primary_address_fill(
    conn: psycopg.Connection[Any],
    canonical_row: dict[str, Any],
    absorbed_rows: list[dict[str, Any]],
) -> tuple[UUID | None, list[UUID]]:
    if canonical_row["primary_address_id"] is not None:
        return None, []
    values = {row["primary_address_id"] for row in absorbed_rows if row["primary_address_id"] is not None}
    if len(values) != 1:
        return None, []
    address_id = next(iter(values))
    owner_ids = [row["id"] for row in absorbed_rows if row["primary_address_id"] == address_id]
    link_ids = conn.execute(
        """
        SELECT absorbed_link.id
        FROM core.entity_address AS absorbed_link
        WHERE absorbed_link.entity_type = 'person'
          AND absorbed_link.entity_id = ANY(%(owners)s)
          AND absorbed_link.address_id = %(address)s
          AND NOT EXISTS (
              SELECT 1 FROM core.entity_address AS canonical_link
              WHERE canonical_link.entity_type = 'person'
                AND canonical_link.entity_id = %(canonical)s
                AND canonical_link.address_id = absorbed_link.address_id
                AND canonical_link.address_role = absorbed_link.address_role
                AND canonical_link.valid_period && absorbed_link.valid_period
          )
        ORDER BY absorbed_link.id
        """,
        {"owners": owner_ids, "address": address_id, "canonical": canonical_row["id"]},
    ).fetchall()
    return (address_id, [row[0] for row in link_ids]) if link_ids else (None, [])


def _build_component_plan(
    conn: psycopg.Connection[Any],
    component: Mapping[str, Any],
) -> PersonAbsorptionPlan:
    canonical_person_id = component["canonical_entity_id"]
    member_ids = list(component["member_ids"])
    rows = _person_rows(conn, member_ids)
    _validate_component_members(conn, canonical_person_id, member_ids, rows)
    _raise_if_portraits_conflict(conn, member_ids)
    _raise_if_officeholdings_conflict(conn, member_ids)
    _raise_if_identity_history_conflicts(conn, member_ids)
    canonical_row = next(row for row in rows if row["id"] == canonical_person_id)
    absorbed_rows = [row for row in rows if row["id"] != canonical_person_id]
    _raise_if_birth_fields_disagree(rows)
    scalar_fills = _consensus_scalar_fills(conn, canonical_row, absorbed_rows)
    scalar_fills.update(_anchor_scalar_fills(conn, canonical_row, absorbed_rows))
    primary_address_id, primary_link_ids = _primary_address_fill(conn, canonical_row, absorbed_rows)
    absorbed_ids = [row["id"] for row in absorbed_rows]
    entity_source_count = conn.execute(
        """
        SELECT count(*) FROM core.entity_source
        WHERE entity_type = 'person' AND entity_id = ANY(%s)
        """,
        (absorbed_ids,),
    ).fetchone()[0]
    return PersonAbsorptionPlan(
        canonical_person_id=canonical_person_id,
        member_ids=member_ids,
        absorbed_person_ids=absorbed_ids,
        scalar_fills=scalar_fills,
        biography_fill=_biography_fill(conn, canonical_row, absorbed_rows),
        merged_identifiers=_merge_identifiers(rows),
        merged_name_variants=_merged_name_variants(canonical_row, rows),
        primary_address_id=primary_address_id,
        primary_address_link_ids=primary_link_ids,
        entity_source_move_count=entity_source_count,
    )


def preflight_person_absorption(
    conn: psycopg.Connection[Any],
    components: list[dict[str, Any]],
) -> list[PersonAbsorptionPlan]:
    """Validate every component before the persistence orchestrator mutates any row."""
    return [_build_component_plan(conn, component) for component in components]
