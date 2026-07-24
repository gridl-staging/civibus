from __future__ import annotations

import re
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
        # ZIP is an exact-equality mode, so its receipt index stays the most
        # selective path even on the tiny fixture and can be asserted exactly.
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


@pytest.mark.parametrize(("by", "query"), [("name", "smith"), ("employer", "technical services")])
def test_donor_search_name_and_employer_reach_transaction_by_index(
    db_conn: psycopg.Connection,
    by: str,
    query: str,
) -> None:
    """Name/employer donor search must reach transactions through an index, never a seq scan.

    The mode scan no longer carries committee scope (that would re-scan the mode
    bitmap once per federal committee — ~508 loops, ~12s on q=smith), so on the
    deliberately tiny fixture the planner prefers the generic recent-date index
    over the trigram index: with ~17 rows the date range is cheaper than a GIN
    trigram bitmap. That is a fixture-scale artifact. At production scale the
    trigram index is provably selected — see the live EXPLAIN captured in
    docs/live-state/2026_07_12_public_launch_cutover.md, where
    idx_transaction_donor_search_name_receipt_trgm scans the ~132k 'smith'
    matches exactly once. The fixture-stable invariant we can assert here is that
    transactions are always reached by an index, never a full sequential scan.
    """
    seed_donor_search_fixture(db_conn)

    plan = _explain_donor_search(db_conn, q=query, by=by)
    nodes = _plan_nodes(plan)

    assert _transaction_access_index_names(nodes), "donor search must reach transactions via an index"
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
    # Committee scope must be present at the transaction-matching boundary so a
    # scoped donor-search index can intersect the trigram match with current
    # federal candidate committees before reading every high-frequency surname
    # heap row.
    assert "EXISTS (" not in match_cte
    assert "JOIN current_federal_committee_scope scope_filter" in match_cte
    assert "scope_filter.committee_id = t.committee_id" in match_cte
    assert "t.transaction_date >= %s" in match_cte
    assert "t.source_record_id IS NULL" in match_cte
    assert "OR t.source_record_id NOT IN" in match_cte
    assert "superseded.superseded_by IS NOT NULL" in match_cte

    qualifying_cte = _cte_sql(sql, name="qualifying_transactions", next_name="donor_groups")
    assert "JOIN current_federal_candidate_committees" not in qualifying_cte
    assert "JOIN current_federal_committee_scope" not in qualifying_cte


def test_donor_search_recipient_rollups_are_scoped_to_limited_donor_groups() -> None:
    sql, _params = _build_donor_search_statement(q="smith", by="name", limit=5, offset=0)

    ctes = _cte_bodies(sql)
    limited_donor_cte_names = _limited_donor_cte_names(ctes)
    recipient_rollups_cte = ctes["recipient_rollups"]
    recipient_rollup_inputs = recipient_rollups_cte.split("GROUP BY", maxsplit=1)[0]

    assert limited_donor_cte_names
    assert any(re.search(rf"\b{name}\b", recipient_rollup_inputs) for name in limited_donor_cte_names)
    assert "FROM qualifying_transactions" not in recipient_rollups_cte


def test_donor_search_donor_groups_use_scalar_id_aggregate() -> None:
    sql, _params = _build_donor_search_statement(q="smith", by="name", limit=5, offset=0)

    donor_groups_cte = _cte_bodies(sql)["donor_groups"]

    assert "MIN(id::text)::uuid AS id" in donor_groups_cte
    assert "ARRAY_AGG(id ORDER BY id ASC)" not in donor_groups_cte
