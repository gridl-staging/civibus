"""Atomic refresh builder for the donor-search aggregate."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from pydantic import BaseModel

from api.contribution_insights_contract import (
    CONTRIBUTION_INSIGHTS_MIN_DATE,
    NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL,
    contribution_insights_transaction_where_sql,
)
from api.queries import campaign_finance as campaign_finance_queries
from core.types.python.models import DataSource
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source


# Lane 2 calls donor_key_fingerprint(), so this alias is part of the cross-lane
# contract: every render uses one name regardless of a caller's local SQL aliases.
DONOR_GRAIN_ALIAS = "donor_source"
_ROLLUP_RELATION = "donor_search_rollup"
_IDENTITY_VARIANT_RELATION = "donor_search_rollup_identity_variant"
_PROVENANCE_RELATION = "donor_search_rollup_provenance"
_ROLLUP_LOCK_NAME = "cf.donor_search_rollup.rebuild"
DONOR_SEARCH_ROLLUP_DATA_SOURCE_NAME = "civibus-donor-search-rollup"

_SAFE_COLUMN_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class DonorRollupBuildResult(BaseModel):
    row_count: int
    build_duration_milliseconds: int
    completed_at: datetime
    donor_key_fingerprint: str


def donor_search_rollup_data_source() -> DataSource:
    return DataSource(
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name=DONOR_SEARCH_ROLLUP_DATA_SOURCE_NAME,
        source_url="internal://civibus/cf/donor_search_rollup",
        source_format="postgres_aggregate",
        license="public_domain",
        update_frequency="weekly",
        notes=(
            "Internally built donor-search aggregate over recent federal FEC Schedule A "
            "transactions scoped to current federal officeholders."
        ),
    )


def ensure_donor_search_rollup_data_source(conn: psycopg.Connection) -> UUID:
    return ensure_data_source(conn, donor_search_rollup_data_source())


def _source_expression_for_key_column(column_name: str) -> str:
    if not _SAFE_COLUMN_NAME.fullmatch(column_name):
        raise ValueError(f"Unsafe donor key column name: {column_name!r}")
    if column_name == "contributor_name":
        return "BTRIM(t.contributor_name_raw)"
    if column_name == "normalized_zip5":
        return "NULLIF(LEFT(t.contributor_zip, 5), '')"
    return f"NULLIF(BTRIM(t.{column_name}), '')"


def _grain_projection_sql() -> str:
    projection_lines = [
        f"{_source_expression_for_key_column(column_name)} AS {column_name}"
        for column_name in campaign_finance_queries._DONOR_SEARCH_KEY_COLUMNS
    ]
    return ",\n            ".join(projection_lines)


def _grain_group_by_sql() -> str:
    return ", ".join(
        f"{DONOR_GRAIN_ALIAS}.{column_name}" for column_name in campaign_finance_queries._DONOR_SEARCH_KEY_COLUMNS
    )


def rendered_donor_grain_expression() -> str:
    """Render the complete producer-side grain definition with one pinned alias."""
    key_expression = campaign_finance_queries._donor_key_sql(DONOR_GRAIN_ALIAS)
    return f"{_grain_projection_sql()}\n{key_expression}\nGROUP BY {_grain_group_by_sql()}"


def donor_key_fingerprint() -> str:
    """Hash the rendered grain definition used by the current builder."""
    return hashlib.sha256(rendered_donor_grain_expression().encode()).hexdigest()


def _raw_identity_projection_sql() -> str:
    return """
                t.contributor_name_raw AS identity_contributor_name_raw,
                COALESCE(t.contributor_employer, '') AS identity_contributor_employer,
                COALESCE(t.contributor_occupation, '') AS identity_contributor_occupation,
                COALESCE(t.contributor_city, '') AS identity_contributor_city,
                COALESCE(t.contributor_state, '') AS identity_contributor_state,
                COALESCE(t.contributor_zip, '') AS identity_contributor_zip
    """.strip()


def _donor_source_ctes_sql() -> str:
    receipt_filter_sql = contribution_insights_transaction_where_sql()
    return f"""
        WITH current_federal_officeholders AS MATERIALIZED (
            SELECT DISTINCT officeholding.person_id
            FROM civic.officeholding officeholding
            JOIN civic.office office
              ON office.id = officeholding.office_id
            WHERE officeholding.valid_period @> CURRENT_DATE
              AND office.office_level = 'federal'
        ),
        current_federal_committee_scope AS MATERIALIZED (
            SELECT DISTINCT link.committee_id
            FROM current_federal_officeholders current_officeholder
            JOIN cf.candidate candidate
              ON candidate.person_id = current_officeholder.person_id
            JOIN cf.candidate_committee_link link
              ON link.candidate_id = candidate.id
            WHERE candidate.person_id IS NOT NULL
              AND link.valid_period @> CURRENT_DATE
        ),
        committee_jurisdiction AS MATERIALIZED (
            SELECT DISTINCT ON (summary.committee_id)
                summary.committee_id,
                summary.derived_jurisdiction AS jurisdiction
            FROM cf.committee_summary summary
            WHERE summary.derived_jurisdiction IS NOT NULL
            ORDER BY summary.committee_id, summary.cycle DESC, summary.id ASC
        ),
        {DONOR_GRAIN_ALIAS} AS MATERIALIZED (
            SELECT
                t.id AS transaction_id,
                {_grain_projection_sql()},
                {_raw_identity_projection_sql()},
                jurisdiction.jurisdiction,
                t.amount,
                t.transaction_date
            FROM cf.transaction t
            JOIN current_federal_committee_scope scope
              ON scope.committee_id = t.committee_id
            LEFT JOIN committee_jurisdiction jurisdiction
              ON jurisdiction.committee_id = t.committee_id
            WHERE t.contributor_name_raw IS NOT NULL
              AND BTRIM(t.contributor_name_raw) != ''
{receipt_filter_sql}
{NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL}
        )
    """


def _rollup_select_sql() -> str:
    donor_key_sql = campaign_finance_queries._donor_key_sql(DONOR_GRAIN_ALIAS)
    return f"""
        {_donor_source_ctes_sql()}
        SELECT
            {donor_key_sql} AS donor_key,
            MIN({DONOR_GRAIN_ALIAS}.transaction_id::text)::uuid AS representative_transaction_id,
            {DONOR_GRAIN_ALIAS}.contributor_name,
            {DONOR_GRAIN_ALIAS}.contributor_employer,
            {DONOR_GRAIN_ALIAS}.contributor_occupation,
            {DONOR_GRAIN_ALIAS}.contributor_city,
            {DONOR_GRAIN_ALIAS}.contributor_state,
            {DONOR_GRAIN_ALIAS}.normalized_zip5,
            MIN({DONOR_GRAIN_ALIAS}.jurisdiction) AS jurisdiction,
            LOWER(CONCAT_WS(
                E'\\x1f',
                {DONOR_GRAIN_ALIAS}.contributor_name,
                {DONOR_GRAIN_ALIAS}.contributor_employer,
                {DONOR_GRAIN_ALIAS}.normalized_zip5
            )) AS search_text,
            COALESCE(SUM({DONOR_GRAIN_ALIAS}.amount), 0) AS total_amount,
            COUNT(*)::integer AS transaction_count,
            MAX({DONOR_GRAIN_ALIAS}.transaction_date) AS latest_transaction_date
        FROM {DONOR_GRAIN_ALIAS}
        GROUP BY {_grain_group_by_sql()}, donor_key
    """


def _identity_variant_select_sql() -> str:
    donor_key_sql = campaign_finance_queries._donor_key_sql(DONOR_GRAIN_ALIAS)
    return f"""
        {_donor_source_ctes_sql()}
        SELECT DISTINCT
            {donor_key_sql} AS donor_key,
            {DONOR_GRAIN_ALIAS}.identity_contributor_name_raw,
            {DONOR_GRAIN_ALIAS}.identity_contributor_employer,
            {DONOR_GRAIN_ALIAS}.identity_contributor_occupation,
            {DONOR_GRAIN_ALIAS}.identity_contributor_city,
            {DONOR_GRAIN_ALIAS}.identity_contributor_state,
            {DONOR_GRAIN_ALIAS}.identity_contributor_zip
        FROM {DONOR_GRAIN_ALIAS}
    """


def _create_replacement_table(
    cursor: psycopg.Cursor,
    replacement_name: str,
    variant_replacement_name: str,
) -> int:
    replacement_identifier = sql.Identifier(replacement_name)
    variant_replacement_identifier = sql.Identifier(variant_replacement_name)
    cursor.execute(
        sql.SQL("CREATE TABLE cf.{} (LIKE cf.donor_search_rollup INCLUDING DEFAULTS INCLUDING CONSTRAINTS)").format(
            replacement_identifier
        )
    )
    cursor.execute(
        sql.SQL(
            "INSERT INTO cf.{} ("
            "donor_key, representative_transaction_id, contributor_name, contributor_employer, "
            "contributor_occupation, contributor_city, contributor_state, normalized_zip5, jurisdiction, "
            "search_text, total_amount, transaction_count, latest_transaction_date) "
        ).format(replacement_identifier)
        + sql.SQL(_rollup_select_sql()),
        (CONTRIBUTION_INSIGHTS_MIN_DATE,),
    )
    rollup_row_count = cursor.rowcount
    cursor.execute(
        sql.SQL("CREATE TABLE cf.{} (LIKE cf.{} INCLUDING DEFAULTS INCLUDING CONSTRAINTS)").format(
            variant_replacement_identifier,
            sql.Identifier(_IDENTITY_VARIANT_RELATION),
        )
    )
    cursor.execute(
        sql.SQL(
            "INSERT INTO cf.{} ("
            "donor_key, contributor_name_raw, contributor_employer, contributor_occupation, "
            "contributor_city, contributor_state, contributor_zip) "
        ).format(variant_replacement_identifier)
        + sql.SQL(_identity_variant_select_sql()),
        (CONTRIBUTION_INSIGHTS_MIN_DATE,),
    )
    return rollup_row_count


def _index_replacement_table(
    cursor: psycopg.Cursor,
    replacement_name: str,
    variant_replacement_name: str,
) -> None:
    replacement_identifier = sql.Identifier(replacement_name)
    variant_replacement_identifier = sql.Identifier(variant_replacement_name)
    cursor.execute(sql.SQL("ALTER TABLE cf.{} ADD PRIMARY KEY (donor_key)").format(replacement_identifier))
    cursor.execute(
        sql.SQL("CREATE INDEX {} ON cf.{} USING GIN (search_text gin_trgm_ops)").format(
            sql.Identifier(f"{replacement_name}_search_text_trgm"),
            replacement_identifier,
        )
    )
    cursor.execute(
        sql.SQL("CREATE INDEX {} ON cf.{} (normalized_zip5)").format(
            sql.Identifier(f"{replacement_name}_normalized_zip5"),
            replacement_identifier,
        )
    )
    cursor.execute(
        sql.SQL(
            "ALTER TABLE cf.{} ADD CONSTRAINT {} UNIQUE ("
            "donor_key, contributor_name_raw, contributor_employer, contributor_occupation, "
            "contributor_city, contributor_state, contributor_zip)"
        ).format(
            variant_replacement_identifier,
            sql.Identifier(f"{variant_replacement_name}_uq"),
        )
    )
    cursor.execute(
        sql.SQL(
            "CREATE INDEX {} ON cf.{} ("
            "contributor_name_raw, contributor_employer, contributor_occupation, "
            "contributor_city, contributor_state, contributor_zip)"
        ).format(
            sql.Identifier(f"{variant_replacement_name}_tuple_idx"),
            variant_replacement_identifier,
        )
    )


def _swap_replacement_table(
    cursor: psycopg.Cursor,
    replacement_name: str,
    variant_replacement_name: str,
) -> None:
    cursor.execute(sql.SQL("DROP TABLE cf.{}").format(sql.Identifier(_IDENTITY_VARIANT_RELATION)))
    cursor.execute(sql.SQL("DROP TABLE cf.{}").format(sql.Identifier(_ROLLUP_RELATION)))
    cursor.execute(
        sql.SQL("ALTER TABLE cf.{} RENAME TO {}").format(
            sql.Identifier(replacement_name),
            sql.Identifier(_ROLLUP_RELATION),
        )
    )
    cursor.execute(
        sql.SQL("ALTER TABLE cf.{} RENAME CONSTRAINT {} TO donor_search_rollup_pkey").format(
            sql.Identifier(_ROLLUP_RELATION),
            sql.Identifier(f"{replacement_name}_pkey"),
        )
    )
    cursor.execute(
        sql.SQL("ALTER INDEX cf.{} RENAME TO idx_donor_search_rollup_search_text_trgm").format(
            sql.Identifier(f"{replacement_name}_search_text_trgm")
        )
    )
    cursor.execute(
        sql.SQL("ALTER INDEX cf.{} RENAME TO idx_donor_search_rollup_normalized_zip5").format(
            sql.Identifier(f"{replacement_name}_normalized_zip5")
        )
    )
    cursor.execute(
        sql.SQL("ALTER TABLE cf.{} RENAME TO {}").format(
            sql.Identifier(variant_replacement_name),
            sql.Identifier(_IDENTITY_VARIANT_RELATION),
        )
    )
    cursor.execute(
        sql.SQL("ALTER TABLE cf.{} RENAME CONSTRAINT {} TO donor_search_rollup_identity_variant_unique").format(
            sql.Identifier(_IDENTITY_VARIANT_RELATION),
            sql.Identifier(f"{variant_replacement_name}_uq"),
        )
    )
    cursor.execute(
        sql.SQL("ALTER INDEX cf.{} RENAME TO idx_donor_search_rollup_identity_variant_identity_tuple").format(
            sql.Identifier(f"{variant_replacement_name}_tuple_idx")
        )
    )


def _store_build_provenance(cursor: psycopg.Cursor, result: DonorRollupBuildResult) -> None:
    cursor.execute(
        f"""
        INSERT INTO cf.{_PROVENANCE_RELATION} (
            singleton,
            donor_key_fingerprint,
            row_count,
            build_duration_milliseconds,
            completed_at
        )
        VALUES (TRUE, %s, %s, %s, %s)
        ON CONFLICT (singleton) DO UPDATE
        SET donor_key_fingerprint = EXCLUDED.donor_key_fingerprint,
            row_count = EXCLUDED.row_count,
            build_duration_milliseconds = EXCLUDED.build_duration_milliseconds,
            completed_at = EXCLUDED.completed_at
        """,
        (
            result.donor_key_fingerprint,
            result.row_count,
            result.build_duration_milliseconds,
            result.completed_at,
        ),
    )


def rebuild_donor_search_rollup(connection: psycopg.Connection) -> DonorRollupBuildResult:
    """Build, index, and atomically expose a complete donor-search rollup."""
    replacement_name = f"donor_search_rollup_build_{uuid4().hex}"
    variant_replacement_name = f"donor_variant_build_{uuid4().hex}"
    fingerprint = donor_key_fingerprint()
    started_at = time.perf_counter()

    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (_ROLLUP_LOCK_NAME,))
            row_count = _create_replacement_table(cursor, replacement_name, variant_replacement_name)
            _index_replacement_table(cursor, replacement_name, variant_replacement_name)
            completed_at = datetime.now(timezone.utc)
            result = DonorRollupBuildResult(
                row_count=row_count,
                build_duration_milliseconds=int((time.perf_counter() - started_at) * 1000),
                completed_at=completed_at,
                donor_key_fingerprint=fingerprint,
            )
            _swap_replacement_table(cursor, replacement_name, variant_replacement_name)
            _store_build_provenance(cursor, result)

    return result
