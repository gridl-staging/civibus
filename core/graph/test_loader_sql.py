from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from psycopg.types.range import DateRange

from core.graph import query_formatted_cypher
from core.graph.loader import (
    CONTRIBUTION_LIKE_TYPES,
    EXPENDITURE_LIKE_TYPES,
    _merge_cf_edge,
    _merge_edge_with_source_record_id,
    _serialize_valid_period,
    classify_transaction_type,
    create_contributed_to_edge,
    load_affiliated_with_edges,
    load_contributed_to_edges,
    load_filed_edges,
    load_ie_edges,
    load_spent_on_edges,
    merge_candidate_node,
    merge_committee_node,
    merge_filing_node,
    merge_organization_node,
    merge_person_node,
)
from core.graph.loader_test_support import count_edge, edge_properties, seed_candidate_committee_link


def _assert_uses_plpgsql_format_query(connection: MagicMock) -> None:
    sql_text = str(connection.execute.call_args.args[0])
    assert "DO $$" in sql_text
    assert "EXECUTE format(" in sql_text
    assert "cypher(" in sql_text


def _assert_sql_contains_escaped_literal(connection: MagicMock, raw_value: str) -> None:
    sql_text = str(connection.execute.call_args.args[0])
    escaped_value = raw_value.replace("\\", "\\\\").replace('"', '\\"')
    escaped_value_with_sql_literal_rendering = escaped_value.replace("\\", "\\\\")
    assert escaped_value in sql_text or escaped_value_with_sql_literal_rendering in sql_text


def test_merge_person_node_uses_plpgsql_do_format_query() -> None:
    connection = MagicMock()
    person_id = uuid4()

    merge_person_node(connection, person_id, 'Alice "A." Example')

    _assert_uses_plpgsql_format_query(connection)


def test_merge_organization_node_uses_plpgsql_do_format_query() -> None:
    connection = MagicMock()
    organization_id = uuid4()

    merge_organization_node(connection, organization_id, "Example Org")

    _assert_uses_plpgsql_format_query(connection)


def test_create_contributed_to_edge_uses_plpgsql_do_format_query() -> None:
    connection = MagicMock()

    create_contributed_to_edge(connection, uuid4(), uuid4(), 99.25, "2024-04-02", uuid4())

    _assert_uses_plpgsql_format_query(connection)
    sql_text = str(connection.execute.call_args.args[0])
    assert "transaction_date" in sql_text
    assert " date:" not in sql_text


def test_create_contributed_to_edge_skips_work_when_person_id_missing() -> None:
    connection = MagicMock()

    create_contributed_to_edge(connection, None, uuid4(), 10.0, "2024-01-01", uuid4())

    connection.execute.assert_not_called()


def test_query_formatted_cypher_uses_non_colliding_dollar_quote_tag() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []

    query_formatted_cypher(connection, "RETURN '$cypher$'")

    rendered_statement = str(connection.execute.call_args_list[2].args[0])
    assert "$civibus_cypher$" in rendered_statement


# ---------------------------------------------------------------------------
# Stage 2: Committee / Candidate / Filing node helpers — SQL plumbing
# ---------------------------------------------------------------------------


def test_merge_committee_node_uses_plpgsql_do_format_query() -> None:
    connection = MagicMock()
    merge_committee_node(connection, uuid4(), "ACTBLUE")
    _assert_uses_plpgsql_format_query(connection)


def test_merge_candidate_node_uses_plpgsql_do_format_query() -> None:
    connection = MagicMock()
    merge_candidate_node(connection, uuid4(), "DOE, JOHN")
    _assert_uses_plpgsql_format_query(connection)


def test_merge_filing_node_uses_plpgsql_do_format_query() -> None:
    connection = MagicMock()
    merge_filing_node(connection, uuid4(), "FEC-12345")
    _assert_uses_plpgsql_format_query(connection)


@pytest.mark.parametrize(
    ("merge_fn", "canonical_name"),
    [
        (merge_committee_node, 'Committee "A" \\\\ Path'),
        (merge_candidate_node, 'Candidate "B" \\\\ Alias'),
        (merge_filing_node, 'Filing "C" \\\\ Ref'),
    ],
)
def test_stage2_node_helpers_escape_canonical_names(merge_fn, canonical_name: str) -> None:
    connection = MagicMock()
    merge_fn(connection, uuid4(), canonical_name)
    _assert_uses_plpgsql_format_query(connection)
    _assert_sql_contains_escaped_literal(connection, canonical_name)


# ---------------------------------------------------------------------------
# Stage 3: Shared CF edge-writing seam — SQL plumbing
# ---------------------------------------------------------------------------


def test_merge_cf_edge_uses_plpgsql_do_format_query() -> None:
    connection = MagicMock()
    _merge_cf_edge(
        connection,
        ("Person", uuid4()),
        ("Committee", uuid4()),
        "CONTRIBUTED_TO",
        {
            "amount": 250.0,
            "transaction_date": "2024-06-15",
            "transaction_type": "Monetary (Itemized)",
            "filing_id": str(uuid4()),
            "source_record_id": str(uuid4()),
        },
    )
    _assert_uses_plpgsql_format_query(connection)


def test_merge_edge_with_source_record_id_uses_plpgsql_do_format_query() -> None:
    connection = MagicMock()
    _merge_edge_with_source_record_id(
        connection,
        source=("Person", "person-1"),
        target=("Office", "office-1"),
        edge_type="HOLDS",
        properties={
            "holder_status": "elected",
            "source_record_id": str(uuid4()),
        },
    )
    _assert_uses_plpgsql_format_query(connection)


def test_merge_edge_with_source_record_id_coerces_decimal_to_float() -> None:
    connection = MagicMock()
    with patch("core.graph.loader._execute_formatted_cypher") as execute_cypher:
        _merge_edge_with_source_record_id(
            connection,
            source=("Committee", "committee-1"),
            target=("Organization", "organization-1"),
            edge_type="SPENT_ON",
            properties={
                "amount": Decimal("91.25"),
                "source_record_id": str(uuid4()),
            },
        )

    format_args = execute_cypher.call_args.args[2:]
    assert 91.25 in format_args
    assert not any(isinstance(value, Decimal) for value in format_args)


def test_merge_cf_edge_uses_merge_keyword() -> None:
    connection = MagicMock()
    _merge_cf_edge(
        connection,
        ("Person", uuid4()),
        ("Committee", uuid4()),
        "CONTRIBUTED_TO",
        {"amount": 100.0, "source_record_id": str(uuid4())},
    )
    sql_text = str(connection.execute.call_args.args[0])
    assert "MERGE" in sql_text


def test_merge_cf_edge_source_record_id_in_merge_key() -> None:
    connection = MagicMock()
    srid = str(uuid4())
    _merge_cf_edge(
        connection,
        ("Person", uuid4()),
        ("Committee", uuid4()),
        "CONTRIBUTED_TO",
        {"amount": 50.0, "source_record_id": srid},
    )
    sql_text = str(connection.execute.call_args.args[0])
    # source_record_id must be in the MERGE edge pattern (not only in SET)
    escaped_srid = srid.replace("\\", "\\\\").replace('"', '\\"')
    assert "source_record_id" in sql_text
    assert escaped_srid in sql_text


def test_merge_cf_edge_escapes_string_properties() -> None:
    connection = MagicMock()
    _merge_cf_edge(
        connection,
        ("Person", uuid4()),
        ("Committee", uuid4()),
        "CONTRIBUTED_TO",
        {
            "amount": 100.0,
            "transaction_type": 'Type "quoted" \\ special',
            "source_record_id": str(uuid4()),
        },
    )
    _assert_sql_contains_escaped_literal(connection, 'Type "quoted" \\ special')


def test_merge_cf_edge_skips_none_properties() -> None:
    connection = MagicMock()
    _merge_cf_edge(
        connection,
        ("Committee", uuid4()),
        ("Filing", uuid4()),
        "FILED",
        {
            "receipt_date": "2024-01-15",
            "due_date": None,
            "accepted_date": None,
            "report_type": "Q1",
            "source_record_id": str(uuid4()),
        },
    )
    sql_text = str(connection.execute.call_args.args[0])
    assert "due_date" not in sql_text
    assert "accepted_date" not in sql_text
    assert "receipt_date" in sql_text
    assert "report_type" in sql_text


@pytest.mark.parametrize(
    ("source_label", "target_label", "edge_type"),
    [
        ("Person", "Committee", "CONTRIBUTED_TO"),
        ("Committee", "Organization", "SPENT_ON"),
        ("Candidate", "Committee", "AFFILIATED_WITH"),
        ("Committee", "Filing", "FILED"),
    ],
    ids=["contributed_to", "spent_on", "affiliated_with", "filed"],
)
def test_merge_cf_edge_renders_labels_and_edge_type(
    source_label: str,
    target_label: str,
    edge_type: str,
) -> None:
    connection = MagicMock()
    _merge_cf_edge(
        connection,
        (source_label, uuid4()),
        (target_label, uuid4()),
        edge_type,
        {"source_record_id": str(uuid4())},
    )
    sql_text = str(connection.execute.call_args.args[0])
    assert source_label in sql_text
    assert target_label in sql_text
    assert edge_type in sql_text


def test_merge_cf_edge_integer_properties_in_cypher() -> None:
    connection = MagicMock()
    _merge_cf_edge(
        connection,
        ("Candidate", uuid4()),
        ("Committee", uuid4()),
        "AFFILIATED_WITH",
        {
            "candidate_election_year": 2024,
            "fec_election_year": 2024,
            "source_record_id": str(uuid4()),
        },
    )
    sql_text = str(connection.execute.call_args.args[0])
    assert "candidate_election_year" in sql_text
    assert "fec_election_year" in sql_text


# ---------------------------------------------------------------------------
# Stage 3: valid_period serialization
# ---------------------------------------------------------------------------


def test_serialize_valid_period_formats_bounded_range() -> None:
    period = DateRange(date(2024, 1, 1), date(2025, 1, 1), "[)")
    assert _serialize_valid_period(period) == "[2024-01-01,2025-01-01)"


def test_serialize_valid_period_formats_unbounded_range() -> None:
    period = DateRange(None, None, "()")
    assert _serialize_valid_period(period) == "(-infinity,infinity)"


def test_count_edge_rejects_invalid_cypher_identifiers() -> None:
    connection = MagicMock()

    with pytest.raises(ValueError, match="Invalid Cypher identifier"):
        count_edge(
            connection,
            source_label="Person}) MATCH (n) RETURN n //",
            source_id=uuid4(),
            edge_type="CONTRIBUTED_TO",
            target_label="Committee",
            target_id=uuid4(),
        )


def test_edge_properties_rejects_invalid_projection() -> None:
    connection = MagicMock()

    with pytest.raises(ValueError, match="Invalid edge projection"):
        edge_properties(
            connection,
            edge_type="FILED",
            source_record_id=uuid4(),
            projection="e.amount, e.source_record_id, n.hack",
            aliases="amount agtype, source_record_id agtype, hack agtype",
        )


def test_seed_candidate_committee_link_rejects_invalid_bounds() -> None:
    connection = MagicMock()

    with pytest.raises(ValueError, match="valid_period_bounds"):
        seed_candidate_committee_link(
            connection,
            candidate_id=uuid4(),
            committee_id=uuid4(),
            source_record_id=uuid4(),
            designation="P",
            candidate_election_year=2024,
            fec_election_year=2024,
            valid_period_start=date(2024, 1, 1),
            valid_period_end=date(2025, 1, 1),
            valid_period_bounds="DROP TABLE",
        )


# ---------------------------------------------------------------------------
# Stage 3: Public loader SQL/routing plumbing
# ---------------------------------------------------------------------------


def _build_cursor_connection(rows: list[dict[str, object]]) -> MagicMock:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = rows
    return connection


def test_load_contributed_to_edges_queries_transaction_rows() -> None:
    connection = _build_cursor_connection([])
    load_contributed_to_edges(connection, limit=25)
    cursor = connection.cursor.return_value.__enter__.return_value
    sql_text = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "FROM cf.transaction t" in sql_text
    assert "JOIN cf.committee c" in sql_text
    assert "WHERE t.transaction_type = ANY(%s)" in sql_text
    assert set(params[0]) == CONTRIBUTION_LIKE_TYPES
    assert params[1] == 25


def test_load_spent_on_edges_queries_transaction_rows() -> None:
    connection = _build_cursor_connection([])
    load_spent_on_edges(connection, limit=9)
    cursor = connection.cursor.return_value.__enter__.return_value
    sql_text = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "FROM cf.transaction t" in sql_text
    assert "JOIN cf.committee c" in sql_text
    assert "WHERE t.transaction_type = ANY(%s)" in sql_text
    assert "AND t.support_oppose IS NULL" in sql_text
    assert set(params[0]) == EXPENDITURE_LIKE_TYPES
    assert params[1] == 9


def test_load_ie_edges_queries_candidate_rows() -> None:
    connection = _build_cursor_connection([])
    load_ie_edges(connection, limit=11)
    cursor = connection.cursor.return_value.__enter__.return_value
    sql_text = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "FROM cf.transaction t" in sql_text
    assert "JOIN cf.committee c" in sql_text
    assert "JOIN cf.candidate cand" in sql_text
    assert "WHERE t.support_oppose IS NOT NULL" in sql_text
    assert params == (11,)


def test_load_affiliated_with_edges_queries_candidate_committee_link() -> None:
    connection = _build_cursor_connection([])
    load_affiliated_with_edges(connection, limit=12)
    cursor = connection.cursor.return_value.__enter__.return_value
    sql_text = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "FROM cf.candidate_committee_link link" in sql_text
    assert "JOIN cf.candidate cand" in sql_text
    assert "JOIN cf.committee cmte" in sql_text
    assert params == (12,)


def test_load_filed_edges_queries_filing_rows() -> None:
    connection = _build_cursor_connection([])
    load_filed_edges(connection, limit=6)
    cursor = connection.cursor.return_value.__enter__.return_value
    sql_text = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "FROM cf.filing f" in sql_text
    assert "JOIN cf.committee c" in sql_text
    assert params == (6,)


def test_load_contributed_to_edges_routes_only_contribution_like_rows() -> None:
    person_id = uuid4()
    committee_id = uuid4()
    source_record_id = uuid4()
    filing_id = uuid4()
    connection = _build_cursor_connection(
        [
            {
                "transaction_type": "Monetary (Itemized)",
                "contributor_person_id": person_id,
                "contributor_person_name": "Donor Person",
                "contributor_organization_id": None,
                "contributor_organization_name": None,
                "committee_id": committee_id,
                "committee_name": "Recipient Committee",
                "amount": 123.45,
                "transaction_date": date(2024, 6, 1),
                "filing_id": filing_id,
                "source_record_id": source_record_id,
            },
            {
                "transaction_type": "Expenditure (Itemized)",
                "contributor_person_id": person_id,
                "contributor_person_name": "Should Be Skipped",
                "contributor_organization_id": None,
                "contributor_organization_name": None,
                "committee_id": committee_id,
                "committee_name": "Recipient Committee",
                "amount": 50.00,
                "transaction_date": date(2024, 6, 2),
                "filing_id": filing_id,
                "source_record_id": uuid4(),
            },
        ]
    )

    with (
        patch("core.graph.loader.merge_person_node") as merge_person,
        patch("core.graph.loader.merge_committee_node") as merge_committee,
        patch("core.graph.loader._merge_cf_edge") as merge_edge,
    ):
        processed = load_contributed_to_edges(connection, limit=10)

    assert processed == 1
    merge_person.assert_called_once()
    merge_committee.assert_called_once()
    merge_edge.assert_called_once()


def test_load_spent_on_edges_routes_only_expenditure_like_rows() -> None:
    payee_org_id = uuid4()
    committee_id = uuid4()
    source_record_id = uuid4()
    filing_id = uuid4()
    connection = _build_cursor_connection(
        [
            {
                "transaction_type": "Expenditure (Itemized)",
                "contributor_person_id": None,
                "contributor_person_name": None,
                "contributor_organization_id": payee_org_id,
                "contributor_organization_name": "Vendor LLC",
                "committee_id": committee_id,
                "committee_name": "Paying Committee",
                "amount": 75.00,
                "transaction_date": date(2024, 7, 2),
                "filing_id": filing_id,
                "source_record_id": source_record_id,
            },
            {
                "transaction_type": "Monetary (Itemized)",
                "contributor_person_id": None,
                "contributor_person_name": None,
                "contributor_organization_id": payee_org_id,
                "contributor_organization_name": "Should Be Skipped",
                "committee_id": committee_id,
                "committee_name": "Paying Committee",
                "amount": 10.00,
                "transaction_date": date(2024, 7, 3),
                "filing_id": filing_id,
                "source_record_id": uuid4(),
            },
        ]
    )

    with (
        patch("core.graph.loader.merge_committee_node") as merge_committee,
        patch("core.graph.loader.merge_organization_node") as merge_org,
        patch("core.graph.loader._merge_cf_edge") as merge_edge,
    ):
        processed = load_spent_on_edges(connection, limit=10)

    assert processed == 1
    merge_committee.assert_called_once()
    merge_org.assert_called_once()
    merge_edge.assert_called_once()


def test_load_ie_edges_routes_supports_vs_opposes() -> None:
    committee_id = uuid4()
    candidate_id = uuid4()
    filing_id = uuid4()
    connection = _build_cursor_connection(
        [
            {
                "committee_id": committee_id,
                "committee_name": "IE Committee",
                "candidate_id": candidate_id,
                "candidate_name": "IE Candidate",
                "support_oppose": "S",
                "amount": 100.00,
                "transaction_date": date(2024, 8, 1),
                "transaction_type": "Independent Expenditure",
                "filing_id": filing_id,
                "source_record_id": uuid4(),
            },
            {
                "committee_id": committee_id,
                "committee_name": "IE Committee",
                "candidate_id": candidate_id,
                "candidate_name": "IE Candidate",
                "support_oppose": "O",
                "amount": 200.00,
                "transaction_date": date(2024, 8, 2),
                "transaction_type": "Independent Expenditure",
                "filing_id": filing_id,
                "source_record_id": uuid4(),
            },
            {
                "committee_id": committee_id,
                "committee_name": "IE Committee",
                "candidate_id": candidate_id,
                "candidate_name": "IE Candidate",
                "support_oppose": "X",
                "amount": 300.00,
                "transaction_date": date(2024, 8, 3),
                "transaction_type": "Independent Expenditure",
                "filing_id": filing_id,
                "source_record_id": uuid4(),
            },
        ]
    )

    with patch("core.graph.loader._merge_node_ref_edge") as merge_edge:
        processed = load_ie_edges(connection, limit=10)

    assert processed == 2
    assert [call.kwargs["edge_type"] for call in merge_edge.call_args_list] == ["SUPPORTS", "OPPOSES"]


# ---------------------------------------------------------------------------
# Stage 2: Transaction-type classifier — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("transaction_type", "expected"),
    [
        # Live contribution-like value (CO)
        ("Monetary (Itemized)", "contribution"),
        # Live contribution-like value (CO)
        ("Monetary (Non-Itemized)", "contribution"),
        # Live contribution-like value (GA — see open question in design doc)
        ("Monetary", "contribution"),
        # Fixture-backed expenditure-like (no live rows)
        ("Expenditure (Itemized)", "expenditure"),
        ("Expenditure (Non-Itemized)", "expenditure"),
        ("Independent Expenditure", "expenditure"),
        # Unsupported sentinel
        ("UNKNOWN_TYPE_SENTINEL", None),
        ("", None),
    ],
)
def test_classify_transaction_type(transaction_type: str, expected: str | None) -> None:
    assert classify_transaction_type(transaction_type) == expected


def test_allowlist_constants_are_frozensets() -> None:
    """Allowlists must be immutable so call sites cannot accidentally mutate them."""
    assert isinstance(CONTRIBUTION_LIKE_TYPES, frozenset)
    assert isinstance(EXPENDITURE_LIKE_TYPES, frozenset)


def test_allowlist_constants_are_nonempty() -> None:
    assert len(CONTRIBUTION_LIKE_TYPES) > 0
    assert len(EXPENDITURE_LIKE_TYPES) > 0


def test_allowlists_are_disjoint() -> None:
    """No value should appear in both allowlists."""
    assert CONTRIBUTION_LIKE_TYPES.isdisjoint(EXPENDITURE_LIKE_TYPES)
