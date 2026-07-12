from __future__ import annotations

from typing import Any

import psycopg
import pytest

from api.queries.campaign_finance import _build_donor_search_statement
from test_support.donor_search_fixture import seed_donor_search_fixture

pytestmark = pytest.mark.integration


def _plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


def _explain_donor_search(
    db_conn: psycopg.Connection,
    *,
    q: str,
    by: str,
) -> dict[str, Any]:
    sql, params = _build_donor_search_statement(q=q, by=by, limit=20, offset=0)
    with db_conn.cursor() as cursor:
        # The deterministic fixture is intentionally tiny, so PostgreSQL would
        # normally prefer sequential scans even when the Stage 1 indexes are usable.
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(f"EXPLAIN (FORMAT JSON) {sql}", params)
        return cursor.fetchone()[0][0]["Plan"]


def _cte_sql(sql: str, *, name: str, next_name: str) -> str:
    start = sql.index(f"{name} AS MATERIALIZED (")
    end = sql.index(f"{next_name} AS", start)
    return sql[start:end]


def _transaction_access_index_names(nodes: list[dict[str, Any]]) -> set[str]:
    return {
        node["Index Name"]
        for node in nodes
        if node.get("Index Name", "").startswith("idx_transaction_")
        and node.get("Index Name") != "idx_transaction_pkey"
    }


@pytest.mark.parametrize(
    ("by", "query", "expected_indexes"),
    [
        ("name", "smith", {"idx_transaction_donor_search_name_receipt_trgm", "idx_transaction_committee_date"}),
        (
            "employer",
            "technical services",
            {"idx_transaction_donor_search_employer_receipt_trgm", "idx_transaction_committee_date"},
        ),
        ("zip", "27701-1234", {"idx_transaction_donor_search_zip5_receipt"}),
    ],
)
def test_donor_search_plan_uses_indexed_transaction_access(
    db_conn: psycopg.Connection,
    by: str,
    query: str,
    expected_indexes: set[str],
) -> None:
    seed_donor_search_fixture(db_conn)

    plan = _explain_donor_search(db_conn, q=query, by=by)
    nodes = _plan_nodes(plan)

    assert _transaction_access_index_names(nodes) & expected_indexes
    assert not any(node.get("Node Type") == "Seq Scan" and node.get("Relation Name") == "transaction" for node in nodes)


def test_donor_search_match_cte_keeps_scope_and_receipt_filters_before_materialized_ids() -> None:
    sql, _params = _build_donor_search_statement(q="smith", by="name", limit=20, offset=0)

    match_cte = _cte_sql(sql, name="matching_transactions", next_name="qualifying_transactions")

    assert "search_matched_transactions AS MATERIALIZED" not in sql
    assert "search_matched_transaction_ids AS MATERIALIZED" not in sql
    assert "matching_transaction_ids AS MATERIALIZED" not in sql
    assert "FROM cf.transaction t" in match_cte
    assert "LEFT JOIN core.source_record sr" not in match_cte
    assert "t.transaction_type LIKE '1%%'" in match_cte
    assert "t.contributor_entity_type = 'IND'" in match_cte
    assert "t.is_memo = FALSE" in match_cte
    assert "t.amendment_indicator != 'T'" in match_cte
    assert "EXISTS (" in match_cte
    assert "scope.committee_id = t.committee_id" in match_cte
    assert "t.transaction_date >= %s" in match_cte
    assert "NOT EXISTS (" in match_cte
    assert "superseded.superseded_by IS NOT NULL" in match_cte
