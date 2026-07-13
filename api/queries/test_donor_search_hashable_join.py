from __future__ import annotations

import psycopg
import pytest

from api.queries.campaign_finance import _build_donor_search_statement, _donor_key_sql


def _donor_search_sql() -> str:
    sql, _params = _build_donor_search_statement(q="smith", by="name", limit=20, offset=0)
    return sql


def test_donor_rollup_joins_use_hashable_key_not_is_not_distinct_from() -> None:
    """Donor rollup/source joins must be hashable equality, not a NULL-safe cross product.

    ``IS NOT DISTINCT FROM`` is not hashable, so PostgreSQL falls back to a
    nested-loop join. On common terms (q=smith) the recipient and source rollups
    then cross-product ~57k matched transactions against the paginated donor page,
    which timed the endpoint out at ~16s. Joining on a single hashable donor_key
    lets the planner use a hash join instead.
    """
    sql = _donor_search_sql()

    assert "IS NOT DISTINCT FROM" not in sql
    # The paginated donor page, recipient rollups, and source rollups all join on
    # the same precomputed donor_key equality.
    assert sql.count("donor_key") >= 4
    assert "recipient.donor_key = dg.donor_key" in sql
    assert "source.donor_key = dg.donor_key" in sql
    assert "qt.donor_key = dg.donor_key" in sql


def test_donor_search_nested_details_are_bounded_before_final_join() -> None:
    """Search pages must not serialize every recipient/source row for common donors."""
    sql = _donor_search_sql()

    assert "limited_recipient_rollups AS" in sql
    assert "limited_source_rollups AS" in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "WHERE recipient_rank <= 5" in sql
    assert "WHERE source_rank <= 5" in sql
    assert "LEFT JOIN limited_recipient_rollups recipient" in sql
    assert "LEFT JOIN limited_source_rollups source" in sql


def test_donor_key_expression_wraps_columns_with_null_marker() -> None:
    """The key encoding must keep NULL distinguishable from any present value."""
    key_sql = _donor_key_sql("t")

    assert key_sql.startswith("md5(")
    for column in (
        "contributor_name",
        "contributor_employer",
        "contributor_occupation",
        "contributor_city",
        "contributor_state",
        "normalized_zip5",
    ):
        assert f"CASE WHEN t.{column} IS NULL THEN 'N' ELSE 'V' || t.{column} END" in key_sql


@pytest.mark.integration
def test_donor_key_preserves_null_safe_equality_semantics(db_conn: psycopg.Connection) -> None:
    """The md5 key must match old IS NOT DISTINCT FROM semantics on the real engine.

    Two donor rows are the same donor iff every grouping column is equal *including
    matching NULLs*. This asserts the key: (1) is stable for identical inputs,
    (2) separates a NULL column from a present value in that column, and
    (3) separates a NULL column from an empty string in that column.
    """
    key = _donor_key_sql("t")
    rows = (
        # Baseline donor with a present employer.
        "('SMITH', 'Acme', 'Eng', 'Durham', 'NC', '27701')",
        # Identical to baseline -> same key.
        "('SMITH', 'Acme', 'Eng', 'Durham', 'NC', '27701')",
        # Employer is NULL instead of present -> distinct donor.
        "('SMITH', NULL, 'Eng', 'Durham', 'NC', '27701')",
        # Employer is empty string instead of NULL -> distinct donor.
        "('SMITH', '', 'Eng', 'Durham', 'NC', '27701')",
    )
    values_sql = ", ".join(rows)
    sql = (
        f"SELECT {key} AS k FROM (VALUES {values_sql}) "
        "AS t(contributor_name, contributor_employer, contributor_occupation, "
        "contributor_city, contributor_state, normalized_zip5)"
    )
    with db_conn.cursor() as cursor:
        cursor.execute(sql)
        keys = [row[0] for row in cursor.fetchall()]

    assert keys[0] == keys[1], "identical donor rows must share a key"
    assert len({keys[0], keys[2], keys[3]}) == 3, "NULL, present, and empty must be distinct keys"
