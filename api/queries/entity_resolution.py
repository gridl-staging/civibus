"""Entity-resolution SQL constants and database fetchers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from api.models.entity_resolution import ERClusterListParams
from core.entity_resolution.confidence import classify_confidence
from core.entity_resolution.splink_config import (
    THRESHOLD_AUTO_MERGE,
    THRESHOLD_POSSIBLE,
    THRESHOLD_PROBABLE,
)

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_ER_CLUSTER_CANONICAL_NAME_SQL = """
CASE
    WHEN ec.entity_type = 'person' THEN p.canonical_name
    ELSE o.canonical_name
END AS canonical_name
""".strip()

_ER_CLUSTER_CANONICAL_NAME_JOINS_SQL = """
LEFT JOIN core.person p
  ON ec.entity_type = 'person'
 AND p.id = ec.canonical_entity_id
LEFT JOIN core.organization o
  ON ec.entity_type = 'organization'
 AND o.id = ec.canonical_entity_id
""".strip()


def _build_er_cluster_summary_sql(where_clause: str, suffix_sql: str = "") -> str:
    """Build ER cluster summary SQL with configurable WHERE and suffix."""
    return f"""
    SELECT
        ec.id,
        ec.entity_type,
        ec.canonical_entity_id,
        {_ER_CLUSTER_CANONICAL_NAME_SQL},
        ec.cluster_confidence,
        COUNT(cm.id)::integer AS member_count
    FROM core.entity_cluster ec
    JOIN core.cluster_member cm
      ON cm.cluster_id = ec.id
     AND cm.entity_type = ec.entity_type
     AND cm.split_at IS NULL
    {_ER_CLUSTER_CANONICAL_NAME_JOINS_SQL}
    WHERE {where_clause}
    GROUP BY
        ec.id,
        ec.entity_type,
        ec.canonical_entity_id,
        ec.cluster_confidence,
        p.canonical_name,
        o.canonical_name
    {suffix_sql}
    """


_ER_CLUSTER_LIST_SQL = _build_er_cluster_summary_sql(
    where_clause="(%s::text IS NULL OR ec.entity_type = %s)",
    suffix_sql="ORDER BY ec.cluster_confidence DESC NULLS LAST, ec.id ASC LIMIT %s OFFSET %s",
)

_ER_CLUSTER_DETAIL_SQL = _build_er_cluster_summary_sql(where_clause="ec.id = %s")

_ER_MEMBER_CANONICAL_NAME_SQL = """
CASE
    WHEN cm.entity_type = 'person' THEN p.canonical_name
    ELSE o.canonical_name
END AS canonical_name
""".strip()

_ER_MEMBER_CANONICAL_NAME_JOINS_SQL = """
LEFT JOIN core.person p
  ON cm.entity_type = 'person'
 AND p.id = cm.entity_id
LEFT JOIN core.organization o
  ON cm.entity_type = 'organization'
 AND o.id = cm.entity_id
""".strip()

_ER_CLUSTER_MEMBER_SQL = f"""
    SELECT
        cm.entity_type,
        cm.entity_id,
        cm.is_canonical,
        {_ER_MEMBER_CANONICAL_NAME_SQL}
    FROM core.cluster_member cm
    {_ER_MEMBER_CANONICAL_NAME_JOINS_SQL}
    WHERE cm.cluster_id = %s
      AND cm.split_at IS NULL
    ORDER BY cm.is_canonical DESC, cm.entity_id ASC
"""

_ER_SUMMARY_ACTIVE_COUNTS_SQL = """
    WITH active_members AS (
        SELECT cluster_id
        FROM core.cluster_member
        WHERE split_at IS NULL
    )
    SELECT
        COUNT(DISTINCT cluster_id)::integer AS total_active_clusters,
        COUNT(*)::integer AS total_active_members
    FROM active_members
"""

_ER_SUMMARY_DECISION_COUNTS_SQL = """
    SELECT
        decision,
        COUNT(*)::integer AS decision_count
    FROM core.match_decision
    WHERE superseded_by IS NULL
    GROUP BY decision
"""

_ER_ENTITY_MATCHES_SQL = """
    SELECT
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
    FROM core.match_decision
    WHERE entity_type = %s
      AND superseded_by IS NULL
      AND (entity_id_a = %s OR entity_id_b = %s)
    ORDER BY confidence DESC, id ASC
"""

_ER_DECISION_TIER_ORDER = (
    classify_confidence(THRESHOLD_AUTO_MERGE),
    classify_confidence(THRESHOLD_PROBABLE),
    classify_confidence(THRESHOLD_POSSIBLE),
    classify_confidence(0.0),
)

# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


def fetch_er_cluster_list(conn: psycopg.Connection, params: ERClusterListParams) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _ER_CLUSTER_LIST_SQL,
            (params.entity_type, params.entity_type, params.limit, params.offset),
        )
        return list(cursor.fetchall())


def fetch_er_cluster_detail(conn: psycopg.Connection, cluster_id: UUID) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_ER_CLUSTER_DETAIL_SQL, (cluster_id,))
        detail_row = cursor.fetchone()
        if detail_row is None:
            return None

        cursor.execute(_ER_CLUSTER_MEMBER_SQL, (cluster_id,))
        member_rows = list(cursor.fetchall())

    detail_row["members"] = member_rows
    return detail_row


def fetch_er_summary(conn: psycopg.Connection) -> dict[str, Any]:
    """Fetch active cluster/member counts and decision distribution."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_ER_SUMMARY_ACTIVE_COUNTS_SQL)
        active_counts_row = cursor.fetchone()
        if active_counts_row is None:
            raise RuntimeError("ER summary active counts query returned no rows")

        cursor.execute(_ER_SUMMARY_DECISION_COUNTS_SQL)
        decision_rows = list(cursor.fetchall())

    decision_counts = {decision_label: 0 for decision_label in _ER_DECISION_TIER_ORDER}
    for decision_row in decision_rows:
        decision_label = decision_row["decision"]
        if decision_label in decision_counts:
            decision_counts[decision_label] = decision_row["decision_count"]

    total_active_matches = sum(decision_counts.values())
    return {
        "total_active_clusters": active_counts_row["total_active_clusters"],
        "total_active_members": active_counts_row["total_active_members"],
        "total_active_matches": total_active_matches,
        "decision_counts": decision_counts,
    }


def fetch_entity_matches(
    conn: psycopg.Connection,
    entity_type: str,
    entity_id: UUID,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_ER_ENTITY_MATCHES_SQL, (entity_type, entity_id, entity_id))
        return list(cursor.fetchall())
