from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from core.entity_resolution.splink_config import (
    DONOR_PREPROCESSING_SQL,
    ORGANIZATION_PREPROCESSING_SQL,
    PERSON_PREPROCESSING_SQL,
)
from domains.campaign_finance.entity_extractors.extract import _normalize_zip_parts
from domains.campaign_finance.normalize.names import parse_name

RowDict = dict[str, Any]
_PROBABILISTIC_ROW_ID_SEPARATOR = "__splink_row__"
_DONOR_IDENTITY_ID_SEPARATOR = "\x1f"
_DONOR_IDENTITY_ID_NAMESPACE = uuid5(NAMESPACE_URL, "civibus:federal:fec:donor_identity:v1")


def _donor_identity_schedule_a_predicate_sql(*, table_alias: str | None = None) -> str:
    prefix = f"{table_alias}." if table_alias else ""
    return f"""
{prefix}transaction_type LIKE '1%%'
  AND {prefix}contributor_entity_type = 'IND'
  AND {prefix}is_memo = FALSE
  AND {prefix}amendment_indicator != 'T'
  AND NULLIF(BTRIM({prefix}contributor_name_raw), '') IS NOT NULL
"""


_DONOR_IDENTITY_SCHEDULE_A_FROM_WHERE_SQL = (
    "\nFROM cf.transaction\nWHERE committee_id = ANY(%s)\n  AND " + _donor_identity_schedule_a_predicate_sql()
)


def _fetch_preprocessed_rows(
    conn: psycopg.Connection,
    preprocessing_sql: str,
    params: Sequence[Any] | None = None,
) -> list[RowDict]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(preprocessing_sql, params)
        rows = cursor.fetchall()

    return list(rows)


def extract_persons_for_matching(conn: psycopg.Connection) -> list[RowDict]:
    return _fetch_preprocessed_rows(conn, PERSON_PREPROCESSING_SQL)


def extract_organizations_for_matching(conn: psycopg.Connection) -> list[RowDict]:
    return _fetch_preprocessed_rows(conn, ORGANIZATION_PREPROCESSING_SQL)


def _donor_identity_id(row: RowDict) -> UUID:
    parts = [
        row["contributor_name_raw"],
        row["contributor_employer"] or "",
        row["contributor_occupation"] or "",
        row["contributor_city"] or "",
        row["contributor_state"] or "",
        row["contributor_zip"] or "",
    ]
    if any(_DONOR_IDENTITY_ID_SEPARATOR in part for part in parts):
        # Keep ordinary v1 IDs stable while making embedded separators unambiguous.
        identity_namespace = uuid5(_DONOR_IDENTITY_ID_NAMESPACE, "length_prefixed:v2")
        identity_name = "".join(f"{len(part)}:{part}" for part in parts)
        return uuid5(identity_namespace, identity_name)
    return uuid5(_DONOR_IDENTITY_ID_NAMESPACE, _DONOR_IDENTITY_ID_SEPARATOR.join(parts))


def _donor_scope_committee_ids(scope: dict[str, Any] | None) -> list[UUID]:
    committee_ids = scope.get("committee_ids") if isinstance(scope, dict) else None
    return _validated_donor_committee_ids(committee_ids)


def _validated_donor_committee_ids(committee_ids: Any) -> list[UUID]:
    if (
        isinstance(committee_ids, (str, bytes))
        or not isinstance(committee_ids, Sequence)
        or not committee_ids
        or any(not isinstance(committee_id, UUID) for committee_id in committee_ids)
    ):
        raise ValueError("scope['committee_ids'] must be a non-empty sequence of UUID values")
    return list(committee_ids)


def _donor_identity_transaction_rows(conn: psycopg.Connection, committee_ids: list[UUID]) -> list[RowDict]:
    scoped_committee_ids = _validated_donor_committee_ids(committee_ids)
    return _fetch_preprocessed_rows(
        conn,
        f"""
        SELECT
            id,
            contributor_name_raw,
            COALESCE(contributor_employer, '') AS contributor_employer,
            COALESCE(contributor_occupation, '') AS contributor_occupation,
            COALESCE(contributor_city, '') AS contributor_city,
            COALESCE(contributor_state, '') AS contributor_state,
            COALESCE(contributor_zip, '') AS contributor_zip
        {_DONOR_IDENTITY_SCHEDULE_A_FROM_WHERE_SQL}
        ORDER BY
            contributor_name_raw,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            contributor_zip,
            id
        """,
        (scoped_committee_ids,),
    )


def _donor_identity_transaction_rows_for_existing_identities(conn: psycopg.Connection) -> list[RowDict]:
    schedule_a_predicate = _donor_identity_schedule_a_predicate_sql(table_alias="t")
    return _fetch_preprocessed_rows(
        conn,
        f"""
        SELECT
            t.id,
            t.contributor_organization_id,
            t.contributor_name_raw,
            COALESCE(t.contributor_employer, '') AS contributor_employer,
            COALESCE(t.contributor_occupation, '') AS contributor_occupation,
            COALESCE(t.contributor_city, '') AS contributor_city,
            COALESCE(t.contributor_state, '') AS contributor_state,
            COALESCE(t.contributor_zip, '') AS contributor_zip
        FROM cf.transaction t
        JOIN core.donor_identity di
          ON di.contributor_name_raw = t.contributor_name_raw
         AND COALESCE(di.contributor_employer, '') = COALESCE(t.contributor_employer, '')
         AND COALESCE(di.contributor_occupation, '') = COALESCE(t.contributor_occupation, '')
         AND COALESCE(di.contributor_city, '') = COALESCE(t.contributor_city, '')
         AND COALESCE(di.contributor_state, '') = COALESCE(t.contributor_state, '')
         AND COALESCE(di.contributor_zip, '') = COALESCE(t.contributor_zip, '')
        WHERE {schedule_a_predicate}
        ORDER BY
            t.contributor_name_raw,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            contributor_zip,
            t.id
        """,
    )


def _donor_identity_committee_ids_for_existing_identities(conn: psycopg.Connection) -> list[UUID]:
    schedule_a_predicate = _donor_identity_schedule_a_predicate_sql(table_alias="t")
    return [
        row["committee_id"]
        for row in _fetch_preprocessed_rows(
            conn,
            f"""
            SELECT DISTINCT t.committee_id
            FROM cf.transaction t
            JOIN core.donor_identity di
              ON di.contributor_name_raw = t.contributor_name_raw
             AND COALESCE(di.contributor_employer, '') = COALESCE(t.contributor_employer, '')
             AND COALESCE(di.contributor_occupation, '') = COALESCE(t.contributor_occupation, '')
             AND COALESCE(di.contributor_city, '') = COALESCE(t.contributor_city, '')
             AND COALESCE(di.contributor_state, '') = COALESCE(t.contributor_state, '')
             AND COALESCE(di.contributor_zip, '') = COALESCE(t.contributor_zip, '')
            WHERE {schedule_a_predicate}
            ORDER BY t.committee_id
            """,
        )
    ]


def _donor_identity_source_rows(conn: psycopg.Connection, committee_ids: list[UUID]) -> list[RowDict]:
    scoped_committee_ids = _validated_donor_committee_ids(committee_ids)
    return _fetch_preprocessed_rows(
        conn,
        f"""
        WITH donor_source AS (
            SELECT
                contributor_name_raw,
                COALESCE(contributor_employer, '') AS contributor_employer,
                COALESCE(contributor_occupation, '') AS contributor_occupation,
                COALESCE(contributor_city, '') AS contributor_city,
                COALESCE(contributor_state, '') AS contributor_state,
                COALESCE(contributor_zip, '') AS contributor_zip
            {_DONOR_IDENTITY_SCHEDULE_A_FROM_WHERE_SQL}
        )
        SELECT
            contributor_name_raw,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            contributor_zip,
            COUNT(*)::int AS transaction_count
        FROM donor_source
        GROUP BY
            contributor_name_raw,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            contributor_zip
        ORDER BY
            COUNT(*) DESC,
            contributor_name_raw,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            contributor_zip
        """,
        (scoped_committee_ids,),
    )


def _donor_identity_row(source_row: RowDict) -> RowDict:
    zip5, _, _ = _normalize_zip_parts(source_row["contributor_zip"])
    parsed_name = parse_name(source_row["contributor_name_raw"])
    return {
        "id": _donor_identity_id(source_row),
        "canonical_name": parsed_name.canonical or source_row["contributor_name_raw"],
        "contributor_name_raw": source_row["contributor_name_raw"],
        "contributor_employer": source_row["contributor_employer"],
        "contributor_occupation": source_row["contributor_occupation"],
        "contributor_city": source_row["contributor_city"],
        "contributor_state": source_row["contributor_state"],
        "contributor_zip": source_row["contributor_zip"],
        "zip5": zip5,
        "transaction_count": source_row["transaction_count"],
    }


def _upsert_donor_identity(conn: psycopg.Connection, row: RowDict) -> None:
    conn.execute(
        """
        INSERT INTO core.donor_identity (
            id,
            canonical_name,
            contributor_name_raw,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            contributor_zip,
            zip5,
            transaction_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE
        SET canonical_name = EXCLUDED.canonical_name,
            contributor_name_raw = EXCLUDED.contributor_name_raw,
            contributor_employer = EXCLUDED.contributor_employer,
            contributor_occupation = EXCLUDED.contributor_occupation,
            contributor_city = EXCLUDED.contributor_city,
            contributor_state = EXCLUDED.contributor_state,
            contributor_zip = EXCLUDED.contributor_zip,
            zip5 = EXCLUDED.zip5,
            transaction_count = EXCLUDED.transaction_count
        """,
        (
            row["id"],
            row["canonical_name"],
            row["contributor_name_raw"],
            row["contributor_employer"],
            row["contributor_occupation"],
            row["contributor_city"],
            row["contributor_state"],
            row["contributor_zip"],
            row["zip5"],
            row["transaction_count"],
        ),
    )


def materialize_donor_identities(
    conn: psycopg.Connection,
    *,
    scope: dict[str, Any] | None = None,
) -> list[RowDict]:
    committee_ids = _donor_scope_committee_ids(scope)
    rows = [_donor_identity_row(row) for row in _donor_identity_source_rows(conn, committee_ids)]
    for row in rows:
        _upsert_donor_identity(conn, row)
    return rows


def extract_donors_for_matching(
    conn: psycopg.Connection,
    *,
    scope: dict[str, Any] | None = None,
) -> list[RowDict]:
    materialized_rows = materialize_donor_identities(conn, scope=scope)
    if not materialized_rows:
        return []
    return _fetch_preprocessed_rows(
        conn,
        f"""
        {DONOR_PREPROCESSING_SQL}
        WHERE id = ANY(%s)
        ORDER BY
            transaction_count DESC,
            contributor_name_raw,
            contributor_employer NULLS FIRST,
            contributor_occupation NULLS FIRST,
            contributor_city NULLS FIRST,
            contributor_state NULLS FIRST,
            contributor_zip NULLS FIRST
        """,
        ([row["id"] for row in materialized_rows],),
    )


def extract_rows_for_matching(
    conn: psycopg.Connection,
    entity_type: str,
    *,
    scope: dict[str, Any] | None = None,
) -> list[RowDict]:
    if entity_type == "person":
        return extract_persons_for_matching(conn)
    if entity_type == "organization":
        return extract_organizations_for_matching(conn)
    if entity_type == "donor_identity":
        return extract_donors_for_matching(conn, scope=scope)

    raise ValueError(f"entity_type must be one of 'donor_identity', 'organization', or 'person', got {entity_type!r}")


def _synthetic_probabilistic_row_id(entity_id: Any, row_index: int) -> str:
    return f"{entity_id}{_PROBABILISTIC_ROW_ID_SEPARATOR}{row_index}"


def _restore_uuid_string(row_id: str) -> UUID | str:
    try:
        return UUID(row_id)
    except ValueError:
        return row_id


def restore_entity_id_from_probabilistic_row(row_id: Any) -> Any:
    """Recover the original entity ID from a prepared Splink row ID or UUID string."""
    if isinstance(row_id, UUID):
        return row_id
    if not isinstance(row_id, str):
        return row_id

    prefix, separator, suffix = row_id.rpartition(_PROBABILISTIC_ROW_ID_SEPARATOR)
    if not separator or not suffix.isdigit():
        return _restore_uuid_string(row_id)

    return _restore_uuid_string(prefix)


def prediction_row_ids_from_record(record: RowDict) -> tuple[Any, Any]:
    """Read the configured left/right row IDs from a Splink prediction record."""
    left_row_id = record.get("unique_id_l", record.get("id_l"))
    right_row_id = record.get("unique_id_r", record.get("id_r"))
    if left_row_id is None or right_row_id is None:
        raise RuntimeError("Splink prediction rows must include left/right entity IDs.")
    return left_row_id, right_row_id


def restore_entity_pair_from_prediction_record(record: RowDict) -> tuple[Any, Any]:
    """Recover canonical entity IDs from a Splink prediction record."""
    left_row_id, right_row_id = prediction_row_ids_from_record(record)

    return (
        restore_entity_id_from_probabilistic_row(left_row_id),
        restore_entity_id_from_probabilistic_row(right_row_id),
    )


def prediction_record_restores_same_entity(record: RowDict) -> bool:
    """Return True when both prediction sides map back to the same entity ID."""
    left_entity_id, right_entity_id = restore_entity_pair_from_prediction_record(record)
    return left_entity_id == right_entity_id


def prepare_rows_for_probabilistic_scoring(rows: list[RowDict]) -> list[RowDict]:
    """Preserve all rows while assigning Splink-safe string record IDs."""
    row_count_by_entity_id = Counter(row["id"] for row in rows)

    row_index_by_entity_id: defaultdict[Any, int] = defaultdict(int)
    prepared_rows: list[RowDict] = []
    for row in rows:
        prepared_row = dict(row)
        entity_id = prepared_row["id"]
        row_index = row_index_by_entity_id[entity_id]
        row_index_by_entity_id[entity_id] += 1
        if row_count_by_entity_id[entity_id] > 1:
            prepared_row["id"] = _synthetic_probabilistic_row_id(entity_id, row_index)
        else:
            prepared_row["id"] = str(entity_id)
        prepared_rows.append(prepared_row)

    return prepared_rows
