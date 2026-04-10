
from __future__ import annotations

from uuid import UUID

import psycopg

from core.graph.loader import (
    _fetch_dict_rows,
    _merge_edge_with_source_record_id,
    _merge_named_node,
    _require_nonnegative_limit,
    _serialize_date,
    merge_organization_node,
    merge_person_node,
)

_OWNS_EDGE_ROWS_QUERY = """
    SELECT
        o.owner_person_id,
        p_owner.canonical_name AS owner_person_name,
        o.owner_organization_id,
        o_owner.canonical_name AS owner_organization_name,
        o.parcel_id,
        p.reid AS parcel_reid,
        o.ownership_recorded_at,
        o.source_record_id
    FROM prop.ownership o
    JOIN prop.parcel p
      ON p.id = o.parcel_id
    LEFT JOIN core.person p_owner
      ON p_owner.id = o.owner_person_id
    LEFT JOIN core.organization o_owner
      ON o_owner.id = o.owner_organization_id
    ORDER BY o.id
    LIMIT %s
"""

_LOCATED_IN_EDGE_ROWS_QUERY = """
    SELECT
        p.id AS parcel_id,
        p.reid AS parcel_reid,
        p.jurisdiction_id,
        j.name AS jurisdiction_name,
        p.deed_date AS effective_at,
        p.source_record_id
    FROM prop.parcel p
    JOIN core.jurisdiction j
      ON j.id = p.jurisdiction_id
    ORDER BY p.id
    LIMIT %s
"""

_ZONED_AS_EDGE_ROWS_QUERY = """
    SELECT
        p.id AS parcel_id,
        p.reid AS parcel_reid,
        p.zoning_class,
        p.deed_date AS zoned_at,
        p.source_record_id
    FROM prop.parcel p
    WHERE p.zoning_class IS NOT NULL
    ORDER BY p.id
    LIMIT %s
"""

_ASSESSED_AT_EDGE_ROWS_QUERY = """
    SELECT
        p.id AS parcel_id,
        p.reid AS parcel_reid,
        a.id AS assessment_id,
        a.tax_year,
        a.assessed_at,
        a.source_record_id
    FROM prop.assessment a
    JOIN prop.parcel p
      ON p.id = a.parcel_id
    ORDER BY a.id
    LIMIT %s
"""


def _coerce_nonblank_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def merge_parcel_node(conn: psycopg.Connection, parcel_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Parcel", parcel_id, canonical_name)


def merge_jurisdiction_node(conn: psycopg.Connection, jurisdiction_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Jurisdiction", jurisdiction_id, canonical_name)


def merge_zoning_class_node(conn: psycopg.Connection, zoning_class: str, canonical_name: str) -> None:
    _merge_named_node(conn, "ZoningClass", zoning_class, canonical_name)


def merge_assessment_node(conn: psycopg.Connection, assessment_id: UUID, canonical_name: str) -> None:
    _merge_named_node(conn, "Assessment", assessment_id, canonical_name)


def _merge_owner_node(conn: psycopg.Connection, row: dict[str, object]) -> tuple[str, str] | None:
    owner_person_id = row.get("owner_person_id")
    owner_person_name = _coerce_nonblank_text(row.get("owner_person_name"))
    if isinstance(owner_person_id, UUID) and owner_person_name is not None:
        merge_person_node(conn, owner_person_id, owner_person_name)
        return "Person", str(owner_person_id)

    owner_organization_id = row.get("owner_organization_id")
    owner_organization_name = _coerce_nonblank_text(row.get("owner_organization_name"))
    if isinstance(owner_organization_id, UUID) and owner_organization_name is not None:
        merge_organization_node(conn, owner_organization_id, owner_organization_name)
        return "Organization", str(owner_organization_id)

    return None


def load_owns_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _OWNS_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0
    for row in rows:
        parcel_id = row.get("parcel_id")
        parcel_reid = _coerce_nonblank_text(row.get("parcel_reid"))
        source_record_id = row.get("source_record_id")
        if not isinstance(parcel_id, UUID) or parcel_reid is None:
            continue
        if not isinstance(source_record_id, UUID):
            continue

        owner_node = _merge_owner_node(conn, row)
        if owner_node is None:
            continue
        source_label, source_id = owner_node

        merge_parcel_node(conn, parcel_id, parcel_reid)
        _merge_edge_with_source_record_id(
            conn,
            source=(source_label, source_id),
            target=("Parcel", str(parcel_id)),
            edge_type="OWNS",
            properties={
                "ownership_recorded_at": _serialize_date(row.get("ownership_recorded_at")),
                "source_record_id": str(source_record_id),
            },
        )
        edge_count += 1

    return edge_count


def load_located_in_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _LOCATED_IN_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0
    for row in rows:
        parcel_id = row.get("parcel_id")
        parcel_reid = _coerce_nonblank_text(row.get("parcel_reid"))
        jurisdiction_id = row.get("jurisdiction_id")
        jurisdiction_name = _coerce_nonblank_text(row.get("jurisdiction_name"))
        source_record_id = row.get("source_record_id")

        if not isinstance(parcel_id, UUID) or parcel_reid is None:
            continue
        if not isinstance(jurisdiction_id, UUID) or jurisdiction_name is None:
            continue
        if not isinstance(source_record_id, UUID):
            continue

        merge_parcel_node(conn, parcel_id, parcel_reid)
        merge_jurisdiction_node(conn, jurisdiction_id, jurisdiction_name)
        _merge_edge_with_source_record_id(
            conn,
            source=("Parcel", str(parcel_id)),
            target=("Jurisdiction", str(jurisdiction_id)),
            edge_type="LOCATED_IN",
            properties={
                "effective_at": _serialize_date(row.get("effective_at")),
                "source_record_id": str(source_record_id),
            },
        )
        edge_count += 1

    return edge_count


def load_zoned_as_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _ZONED_AS_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0
    for row in rows:
        parcel_id = row.get("parcel_id")
        parcel_reid = _coerce_nonblank_text(row.get("parcel_reid"))
        zoning_class = _coerce_nonblank_text(row.get("zoning_class"))
        source_record_id = row.get("source_record_id")

        if not isinstance(parcel_id, UUID) or parcel_reid is None:
            continue
        if zoning_class is None:
            continue
        if not isinstance(source_record_id, UUID):
            continue

        merge_parcel_node(conn, parcel_id, parcel_reid)
        merge_zoning_class_node(conn, zoning_class, zoning_class)
        _merge_edge_with_source_record_id(
            conn,
            source=("Parcel", str(parcel_id)),
            target=("ZoningClass", zoning_class),
            edge_type="ZONED_AS",
            properties={
                "zoned_at": _serialize_date(row.get("zoned_at")),
                "source_record_id": str(source_record_id),
            },
        )
        edge_count += 1

    return edge_count


def load_assessed_at_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)

    rows = _fetch_dict_rows(conn, _ASSESSED_AT_EDGE_ROWS_QUERY, (limit,))
    edge_count = 0
    for row in rows:
        parcel_id = row.get("parcel_id")
        parcel_reid = _coerce_nonblank_text(row.get("parcel_reid"))
        assessment_id = row.get("assessment_id")
        tax_year = row.get("tax_year")
        source_record_id = row.get("source_record_id")

        if not isinstance(parcel_id, UUID) or parcel_reid is None:
            continue
        if not isinstance(assessment_id, UUID) or not isinstance(tax_year, int):
            continue
        if not isinstance(source_record_id, UUID):
            continue

        merge_parcel_node(conn, parcel_id, parcel_reid)
        merge_assessment_node(conn, assessment_id, str(tax_year))
        _merge_edge_with_source_record_id(
            conn,
            source=("Parcel", str(parcel_id)),
            target=("Assessment", str(assessment_id)),
            edge_type="ASSESSED_AT",
            properties={
                "assessed_at": _serialize_date(row.get("assessed_at")),
                "source_record_id": str(source_record_id),
            },
        )
        edge_count += 1

    return edge_count


def load_property_edges(conn: psycopg.Connection, *, limit: int) -> int:
    _require_nonnegative_limit(limit)
    return (
        load_owns_edges(conn, limit=limit)
        + load_located_in_edges(conn, limit=limit)
        + load_zoned_as_edges(conn, limit=limit)
        + load_assessed_at_edges(conn, limit=limit)
    )
