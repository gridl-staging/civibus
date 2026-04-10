"""Property/parcel SQL constants and database fetchers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from api.models.investigate import DonorsWithPropertyParams
from api.models.property import ParcelListParams
from api.queries._common import _fetch_filtered_rows, fetch_one_row

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_PROPERTY_SOURCE_ROWS_SQL = """
    SELECT
        sr.id AS source_record_id,
        ds.domain AS domain,
        ds.jurisdiction AS jurisdiction,
        ds.name AS data_source_name,
        ds.source_url AS data_source_url,
        sr.source_record_key AS source_record_key,
        sr.source_url AS record_url,
        sr.pull_date AS pull_date
    FROM core.source_record sr
    JOIN core.data_source ds
      ON ds.id = sr.data_source_id
    WHERE sr.id = ANY(%s)
    ORDER BY sr.pull_date DESC, sr.id ASC
"""

_PARCEL_DETAIL_SQL = """
    SELECT
        id,
        reid,
        pin,
        site_address,
        property_description,
        city,
        zoning_class,
        land_class,
        acreage,
        neighborhood,
        fire_district,
        is_pending,
        deed_date,
        deed_book,
        deed_page,
        jurisdiction_id,
        source_record_id
    FROM prop.parcel
    WHERE id = %s
"""

_PARCEL_ASSESSMENTS_SQL = """
    SELECT
        id,
        tax_year,
        land_assessed_value,
        improvement_assessed_value,
        total_assessed_value,
        assessed_at,
        heated_area,
        exemption_description,
        source_record_id
    FROM prop.assessment
    WHERE parcel_id = %s
    ORDER BY tax_year DESC, id ASC
"""

_PARCEL_OWNERSHIP_SQL = """
    SELECT
        id,
        owner_name,
        owner_mail_line1,
        owner_mail_line2,
        owner_mail_line3,
        owner_mail_city,
        owner_mail_state,
        owner_mail_zip5,
        ownership_recorded_at,
        valid_period::text AS valid_period,
        date_precision::text AS date_precision,
        owner_person_id,
        owner_organization_id,
        owner_address_id,
        source_record_id
    FROM prop.ownership
    WHERE parcel_id = %s
    ORDER BY ownership_recorded_at DESC NULLS LAST, id ASC
"""

_PARCEL_LIST_SQL_TEMPLATE = """
    SELECT
        p.id,
        p.reid,
        p.pin,
        p.site_address,
        p.property_description,
        p.city,
        p.zoning_class,
        p.land_class,
        p.acreage,
        p.neighborhood,
        p.fire_district,
        p.is_pending,
        p.deed_date,
        p.deed_book,
        p.deed_page,
        p.jurisdiction_id,
        p.source_record_id
    FROM prop.parcel p
    WHERE {where_sql}
    ORDER BY p.site_address ASC, p.id ASC
    LIMIT %s
    OFFSET %s
"""

_DONORS_WITH_PROPERTY_SQL_TEMPLATE = (
    "WITH property_owners AS (SELECT DISTINCT o.owner_person_id FROM prop.ownership o "
    "LEFT JOIN core.source_record sr ON sr.id = o.source_record_id "
    "LEFT JOIN core.data_source ds ON ds.id = sr.data_source_id WHERE o.owner_person_id IS NOT NULL AND {where_sql}), "
    "direct_matches AS (SELECT DISTINCT t.contributor_person_id AS person_id, 'direct'::text AS match_type FROM cf.transaction t "
    "JOIN property_owners po ON po.owner_person_id = t.contributor_person_id WHERE t.contributor_person_id IS NOT NULL), "
    "cluster_matches AS (SELECT DISTINCT t.contributor_person_id AS person_id, 'cluster'::text AS match_type FROM cf.transaction t "
    "JOIN core.cluster_member contributor_member ON contributor_member.entity_type = 'person' AND contributor_member.entity_id = t.contributor_person_id AND contributor_member.split_at IS NULL "
    "JOIN core.cluster_member owner_member ON owner_member.entity_type = 'person' AND owner_member.cluster_id = contributor_member.cluster_id AND owner_member.split_at IS NULL "
    "JOIN property_owners po ON po.owner_person_id = owner_member.entity_id WHERE t.contributor_person_id IS NOT NULL "
    "AND owner_member.entity_id <> t.contributor_person_id), matched_people AS (SELECT person_id, 1 AS match_rank FROM direct_matches "
    "UNION ALL SELECT person_id, 2 AS match_rank FROM cluster_matches) SELECT matches.person_id, p.canonical_name, "
    "CASE matches.match_rank WHEN 1 THEN 'direct'::text ELSE 'cluster'::text END AS match_type "
    "FROM (SELECT person_id, MIN(match_rank) AS match_rank FROM matched_people GROUP BY person_id) matches "
    "JOIN core.person p ON p.id = matches.person_id ORDER BY p.canonical_name ASC, matches.person_id ASC LIMIT %s OFFSET %s"
)

# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


def _fetch_source_rows_by_id(
    conn: psycopg.Connection,
    source_record_ids: Sequence[UUID | None],
) -> dict[UUID, list[dict[str, Any]]]:
    """Batch-fetch source provenance rows keyed by source_record_id."""
    non_null_source_ids = list(
        dict.fromkeys(source_record_id for source_record_id in source_record_ids if source_record_id is not None)
    )
    if not non_null_source_ids:
        return {}

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PROPERTY_SOURCE_ROWS_SQL, (non_null_source_ids,))
        rows = list(cursor.fetchall())

    source_rows_by_id: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for source_row in rows:
        source_record_id = source_row.pop("source_record_id")
        source_rows_by_id[source_record_id].append(source_row)
    return dict(source_rows_by_id)


def _attach_source_rows(
    rows: Sequence[dict[str, Any]],
    source_rows_by_id: dict[UUID, list[dict[str, Any]]],
) -> None:
    for row in rows:
        source_record_id = row.pop("source_record_id")
        row["sources"] = source_rows_by_id.get(source_record_id, []) if source_record_id is not None else []


def _attach_property_sources(
    conn: psycopg.Connection,
    *row_groups: Sequence[dict[str, Any]],
) -> None:
    source_rows_by_id = _fetch_source_rows_by_id(
        conn,
        [row.get("source_record_id") for rows in row_groups for row in rows],
    )
    for rows in row_groups:
        _attach_source_rows(rows, source_rows_by_id)


def fetch_parcel_detail(conn: psycopg.Connection, parcel_id: UUID) -> dict[str, Any] | None:
    """Fetch a single parcel with assessments, ownership, and source provenance."""
    parcel_row = fetch_one_row(conn, query=_PARCEL_DETAIL_SQL, row_id=parcel_id)
    if parcel_row is None:
        return None

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_PARCEL_ASSESSMENTS_SQL, (parcel_id,))
        assessment_rows = list(cursor.fetchall())
        cursor.execute(_PARCEL_OWNERSHIP_SQL, (parcel_id,))
        ownership_rows = list(cursor.fetchall())

    _attach_property_sources(conn, [parcel_row], assessment_rows, ownership_rows)
    parcel_row["assessments"] = assessment_rows
    parcel_row["ownership"] = ownership_rows
    return parcel_row


def fetch_parcel_list(conn: psycopg.Connection, params: ParcelListParams) -> list[dict[str, Any]]:
    """Fetch filtered parcel list with source provenance attached."""
    parcel_rows = _fetch_filtered_rows(
        conn,
        sql_template=_PARCEL_LIST_SQL_TEMPLATE,
        filter_values=(
            (params.city, "p.city = %s"),
            (params.zoning_class, "p.zoning_class = %s"),
            (params.min_acreage, "p.acreage >= %s"),
            (params.max_acreage, "p.acreage <= %s"),
        ),
        limit=params.limit,
        offset=params.offset,
    )

    _attach_property_sources(conn, parcel_rows)
    return parcel_rows


def fetch_donors_with_property(conn: psycopg.Connection, params: DonorsWithPropertyParams) -> list[dict[str, Any]]:
    return _fetch_filtered_rows(
        conn,
        sql_template=_DONORS_WITH_PROPERTY_SQL_TEMPLATE,
        filter_values=((params.jurisdiction, "ds.jurisdiction = %s"),),
        limit=params.limit,
        offset=params.offset,
    )
