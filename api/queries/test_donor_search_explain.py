from __future__ import annotations

import re
from time import perf_counter
from typing import Any

import psycopg
import pytest

from api.queries.campaign_finance import _build_donor_search_statement
from test_support.donor_search_fixture import (
    seed_donor_search_fixture,
    seed_full_scope_skewed_donor_search_fixture,
)

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


def _explain_analyze_donor_search(
    db_conn: psycopg.Connection,
    *,
    q: str,
) -> dict[str, Any]:
    sql, params = _build_donor_search_statement(q=q, by="name", limit=20, offset=0)
    with db_conn.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", params)
        return cursor.fetchone()[0][0]["Plan"]


_CTE_HEADER_RE = re.compile(r"\s*(?P<name>[a-z_][a-z0-9_]*)\s+AS(?:\s+MATERIALIZED)?\s*\(", re.IGNORECASE)


def _matching_close_paren(sql: str, open_paren: int) -> int:
    depth = 0
    for index, char in enumerate(sql[open_paren:], start=open_paren):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("CTE body has no closing parenthesis")


def _cte_bodies(sql: str) -> dict[str, str]:
    with_start = sql.upper().index("WITH") + len("WITH")
    ctes: dict[str, str] = {}
    cursor = with_start
    while match := _CTE_HEADER_RE.match(sql, cursor):
        open_paren = match.end() - 1
        close_paren = _matching_close_paren(sql, open_paren)
        ctes[match.group("name")] = sql[open_paren + 1 : close_paren]
        cursor = close_paren + 1
        while cursor < len(sql) and sql[cursor].isspace():
            cursor += 1
        if cursor >= len(sql) or sql[cursor] != ",":
            break
        cursor += 1
    return ctes


def _cte_sql(sql: str, *, name: str, next_name: str) -> str:
    del next_name
    return _cte_bodies(sql)[name]


def _transaction_access_index_names(nodes: list[dict[str, Any]]) -> set[str]:
    return {
        node["Index Name"]
        for node in nodes
        if node.get("Index Name", "").startswith("idx_transaction_")
        and node.get("Index Name") != "idx_transaction_pkey"
    }


def _rollup_access_index_names(nodes: list[dict[str, Any]]) -> set[str]:
    return {node["Index Name"] for node in nodes if node.get("Index Name", "").startswith("idx_donor_search_rollup_")}


def _cte_node(nodes: list[dict[str, Any]], cte_name: str) -> dict[str, Any]:
    matches = [
        node
        for node in nodes
        if node.get("CTE Name") == cte_name and node.get("Node Type") == "CTE Scan" and node.get("Alias") == cte_name
    ]
    assert len(matches) == 1, [node.get("CTE Name") for node in nodes if node.get("CTE Name")]
    return matches[0]


def _cte_scan_rows(nodes: list[dict[str, Any]], cte_name: str) -> int:
    return int(_cte_node(nodes, cte_name)["Actual Rows"])


def _single_loop_cte_scan(nodes: list[dict[str, Any]], cte_name: str) -> dict[str, Any]:
    matches = [
        node
        for node in nodes
        if node.get("CTE Name") == cte_name and node.get("Node Type") == "CTE Scan" and node.get("Actual Loops") == 1
    ]
    assert matches, [node.get("CTE Name") for node in nodes if node.get("CTE Name")]
    return max(matches, key=lambda node: node.get("Actual Rows", 0))


def _cte_producer_node(nodes: list[dict[str, Any]], cte_name: str) -> dict[str, Any]:
    matches = [node for node in nodes if node.get("Subplan Name") == f"CTE {cte_name}"]
    assert len(matches) == 1, [node.get("Subplan Name") for node in nodes if node.get("Subplan Name")]
    return matches[0]


def _transaction_access_loop_counts(nodes: list[dict[str, Any]]) -> list[int]:
    return [
        int(node["Actual Loops"])
        for node in nodes
        if node.get("Relation Name") == "transaction" or node.get("Index Name", "").startswith("idx_transaction_")
    ]


def _cte_name_containing(ctes: dict[str, str], text: str) -> str:
    matches = [name for name, body in ctes.items() if text in body]
    assert len(matches) == 1
    return matches[0]


def _limited_donor_cte_names(ctes: dict[str, str]) -> set[str]:
    return {
        name
        for name, body in ctes.items()
        if "LIMIT %s" in body and "OFFSET %s" in body and "total_amount" in body and "transaction_count" in body
    }


@pytest.mark.parametrize(
    ("by", "query", "expected_indexes"),
    [
        (
            "zip",
            "27701-1234",
            {
                "idx_donor_search_rollup_normalized_zip5",
            },
        ),
    ],
)
def test_donor_search_plan_uses_indexed_rollup_access(
    db_conn: psycopg.Connection,
    by: str,
    query: str,
    expected_indexes: set[str],
) -> None:
    seed_donor_search_fixture(db_conn)

    plan = _explain_donor_search(db_conn, q=query, by=by)
    nodes = _plan_nodes(plan)

    assert _rollup_access_index_names(nodes) & expected_indexes
    assert not any(
        node.get("Node Type") == "Seq Scan" and node.get("Relation Name") == "donor_search_rollup" for node in nodes
    )


@pytest.mark.parametrize(("by", "query"), [("name", "smith"), ("employer", "technical services")])
def test_donor_search_name_and_employer_reach_rollup_by_index(
    db_conn: psycopg.Connection,
    by: str,
    query: str,
) -> None:
    """Name/employer donor discovery must reach the refresh rollup by index."""
    seed_donor_search_fixture(db_conn)

    plan = _explain_donor_search(db_conn, q=query, by=by)
    nodes = _plan_nodes(plan)

    assert "idx_donor_search_rollup_search_text_trgm" in _rollup_access_index_names(nodes)
    assert not any(
        node.get("Node Type") == "Seq Scan" and node.get("Relation Name") == "donor_search_rollup" for node in nodes
    )


def test_donor_search_detail_uses_page_driven_name_index_probes(
    db_conn: psycopg.Connection,
) -> None:
    """Transaction detail must be fetched from page donors, not a full-table scan."""
    seed_full_scope_skewed_donor_search_fixture(db_conn)

    plan = _explain_donor_search(db_conn, q="williams", by="name")
    nodes = _plan_nodes(plan)

    name_probe_indexes = {
        "idx_transaction_donor_search_name_receipt_trgm",
        "idx_transaction_contributor_name_lower_trgm",
    }
    assert _transaction_access_index_names(nodes) & name_probe_indexes
    assert not any(
        node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") == "transaction"
        and node.get("Alias") == "transaction_row"
        for node in nodes
    )


def test_donor_search_full_scope_common_surname_bounds_qualifying_transactions(
    db_conn: psycopg.Connection,
) -> None:
    baseline_officeholder_count = db_conn.execute(
        """
        SELECT COUNT(*)::integer
        FROM civic.officeholding officeholding
        JOIN civic.office office ON office.id = officeholding.office_id
        WHERE officeholding.valid_period @> CURRENT_DATE
          AND office.office_level = 'federal'
        """
    ).fetchone()[0]
    fixture = seed_full_scope_skewed_donor_search_fixture(db_conn)

    # Deterministic Stage 1 live-shape proxy: 518 scoped committees with eight
    # extra current candidate-scope rows, plus unrelated candidate fan-out.
    assert fixture.counts.current_federal_officeholders - baseline_officeholder_count == 518
    assert fixture.counts.linked_people == 518
    assert fixture.counts.candidate_scope_rows == 526
    assert fixture.counts.distinct_linked_committees == 518
    assert fixture.counts.unrelated_candidate_rows == 300
    assert fixture.counts.common_surname_transactions == 250

    started_at = perf_counter()
    plan = _explain_analyze_donor_search(db_conn, q="williams")
    elapsed_seconds = perf_counter() - started_at
    nodes = _plan_nodes(plan)
    officeholder_node = _single_loop_cte_scan(nodes, "current_federal_officeholders")
    matching_node = _single_loop_cte_scan(nodes, "matching_donor_records")
    qualifying_node = _cte_producer_node(nodes, "qualifying_transactions")
    transaction_loops = _transaction_access_loop_counts(nodes)

    assert elapsed_seconds < 5, (
        f"full-scope donor-search fixture should stay fast enough for local regression use; counts={fixture.counts!r}"
    )
    assert officeholder_node["Actual Loops"] == 1
    assert int(officeholder_node["Actual Rows"]) == fixture.counts.current_federal_officeholders
    assert transaction_loops
    assert 0 < max(transaction_loops) <= 20
    assert max(transaction_loops) < int(matching_node["Actual Rows"])
    assert qualifying_node["Actual Loops"] == 1
    assert qualifying_node["Actual Rows"] <= 80
    assert matching_node["Actual Rows"] > 0
    assert matching_node["Actual Rows"] < fixture.counts.common_surname_transactions
    assert any(node.get("Relation Name") == "transaction" for node in nodes)


def test_donor_search_match_cte_keeps_scope_and_receipt_filters_before_materialized_ids() -> None:
    sql, _params = _build_donor_search_statement(q="smith", by="name", limit=20, offset=0)

    ctes = _cte_bodies(sql)
    officeholder_cte = ctes["current_federal_officeholders"]
    candidate_scope_cte = ctes["current_federal_candidate_committees"]
    match_cte = _cte_sql(sql, name="matching_donor_records", next_name="qualifying_transactions")

    assert sql.index("current_federal_officeholders AS MATERIALIZED") < sql.index(
        "current_federal_candidate_committees AS MATERIALIZED"
    )
    assert "FROM civic.officeholding officeholding" in officeholder_cte
    assert "JOIN cf.candidate candidate" not in officeholder_cte
    assert "FROM current_federal_officeholders current_officeholder" in candidate_scope_cte
    assert "candidate.person_id = current_officeholder.person_id" in candidate_scope_cte
    assert "search_matched_transactions AS MATERIALIZED" not in sql
    assert "search_matched_transaction_ids AS MATERIALIZED" not in sql
    assert "matching_transaction_ids AS MATERIALIZED" not in sql
    assert "FROM cf.donor_search_rollup rollup" in match_cte
    assert "rollup.search_text LIKE" in match_cte
    assert "cf.transaction" not in match_cte

    qualifying_cte = _cte_sql(sql, name="qualifying_transactions", next_name="donor_groups")
    assert "FROM cf.transaction transaction_row" in qualifying_cte
    assert "FROM page_donor_records record" in qualifying_cte
    assert "CROSS JOIN LATERAL" in qualifying_cte
    assert "LOWER(transaction_row.contributor_name_raw)" in qualifying_cte
    assert "LIKE '%%' || LOWER(record.identity_name) || '%%'" in qualifying_cte
    assert "OFFSET 0" in qualifying_cte
    assert "JOIN current_federal_candidate_committees" not in qualifying_cte
    assert "JOIN current_federal_committee_scope scope_filter" in qualifying_cte
    assert "transaction_row.transaction_type LIKE '1%%'" in qualifying_cte
    assert "transaction_row.contributor_entity_type = 'IND'" in qualifying_cte
    assert "transaction_row.is_memo = FALSE" in qualifying_cte
    assert "transaction_row.amendment_indicator != 'T'" in qualifying_cte
    assert "transaction_row.transaction_date >= %s" in qualifying_cte
    assert "transaction_row.source_record_id IS NULL" in qualifying_cte
    assert "OR transaction_row.source_record_id NOT IN" in qualifying_cte
    assert "superseded.superseded_by IS NOT NULL" in qualifying_cte


def test_donor_search_recipient_rollups_are_scoped_to_limited_donor_groups() -> None:
    sql, _params = _build_donor_search_statement(q="smith", by="name", limit=5, offset=0)

    ctes = _cte_bodies(sql)
    donor_page_transactions_cte = ctes["donor_page_transactions"]
    recipient_rollups_cte = ctes["recipient_rollups"]
    recipient_rollup_inputs = recipient_rollups_cte.split("GROUP BY", maxsplit=1)[0]

    assert "matching_donor_keys AS MATERIALIZED" in sql
    assert "FROM donor_groups" in donor_page_transactions_cte
    assert "FROM donor_page_transactions" in recipient_rollup_inputs
    assert "FROM qualifying_transactions" not in recipient_rollups_cte


def test_donor_search_donor_groups_use_scalar_id_aggregate() -> None:
    sql, _params = _build_donor_search_statement(q="smith", by="name", limit=5, offset=0)

    ctes = _cte_bodies(sql)
    matching_donor_keys_cte = ctes["matching_donor_keys"]
    donor_groups_cte = ctes["donor_groups"]

    assert "MIN(record.id::text)::uuid AS id" in matching_donor_keys_cte
    assert "page_key.id" in donor_groups_cte
    assert "ARRAY_AGG(id ORDER BY id ASC)" not in donor_groups_cte
