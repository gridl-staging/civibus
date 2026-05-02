"""Graph-edge contract tests for reconciliation helpers using mocked DB cursors."""

from __future__ import annotations

from uuid import uuid4

from domains.campaign_finance.quality.conftest import EXPECTED_EDGE_FAMILIES
from domains.campaign_finance.quality.test_reconciliation_helpers import (
    call_matches_family_route as _call_matches_family_route,
    has_candidate_eligibility_join as _has_candidate_eligibility_join,
    has_exact_support_oppose_routing as _has_exact_support_oppose_routing,
    has_source_record_id_join as _has_source_record_id_join,
    has_type_allowlist_in_sql_or_params as _has_type_allowlist,
    mock_conn_with_side_effect as _mock_conn_with_side_effect,
    query_references_edge_label as _query_references_edge_label,
    query_uses_cypher as _query_uses_cypher,
    routes_to_candidate_committee_link_table as _routes_to_candidate_committee_link_table,
    routes_to_filing_table as _routes_to_filing_table,
    sql_and_params_text as _sql_and_params_text,
)


class TestCountGraphEdgesByFamily:
    """Mocked-cursor tests for graph-edge counting scoped by data_source_id
    through each edge's source_record_id property."""

    def test_returns_dict_keyed_by_edge_family(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            count_graph_edges_by_family,
        )

        ds_id = uuid4()
        expected = dict(
            zip(
                EXPECTED_EDGE_FAMILIES,
                [11, 12, 13, 14, 15, 16],
                strict=True,
            )
        )
        conn, _ = _mock_conn_with_side_effect([(value,) for value in expected.values()])
        result = count_graph_edges_by_family(conn, ds_id)
        assert isinstance(result, dict)
        assert set(result) == set(EXPECTED_EDGE_FAMILIES)
        assert result == expected

    def test_counts_scoped_through_source_record_id(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            count_graph_edges_by_family,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(5,)] * 6)
        count_graph_edges_by_family(conn, ds_id)
        calls = mock_cursor.execute.call_args_list
        for call in calls:
            sql_lower, _ = _sql_and_params_text(call)
            assert _query_uses_cypher(sql_lower), (
                "Edge counts must query AGE edges via cypher(...), not relational row tables"
            )
            assert "source_record_id" in sql_lower, (
                "Query must join AGE edge source_record_id properties to source records"
            )
            assert "core.source_record" in sql_lower, (
                "Edge counts must join through core.source_record for data_source scoping"
            )
            assert "data_source_id" in sql_lower, "Edge counts must scope by core.source_record.data_source_id"
            assert _has_source_record_id_join(sql_lower), (
                "Edge count SQL must compare AGE edge source_record_id to "
                "core.source_record.id (join/equality), not just mention both tokens"
            )

    def test_each_family_tied_to_expected_graph_edge_label(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            count_graph_edges_by_family,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(5,)] * 6)
        result = count_graph_edges_by_family(conn, ds_id)
        calls = mock_cursor.execute.call_args_list
        assert set(result) == set(EXPECTED_EDGE_FAMILIES)

        for family in EXPECTED_EDGE_FAMILIES:
            edge_label = family
            matching_calls = []
            for call in calls:
                sql_lower, params_text = _sql_and_params_text(call)
                if _query_references_edge_label(
                    sql_lower,
                    params_text,
                    edge_label=edge_label,
                ):
                    matching_calls.append((sql_lower, params_text))
            assert matching_calls, (
                f"{family} result key must be bound to query contract for "
                f"edge label {edge_label}, not reused from a different family"
            )
            assert any(_query_uses_cypher(sql) for sql, _ in matching_calls), (
                f"{family} edge count contract must use AGE/Cypher query semantics"
            )

    def test_uses_literal_graph_name_for_cypher(self) -> None:
        from core.graph import GRAPH_NAME
        from domains.campaign_finance.quality.reconciliation import (
            count_graph_edges_by_family,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(5,)] * 6)
        count_graph_edges_by_family(conn, ds_id)

        calls = mock_cursor.execute.call_args_list
        for call in calls:
            sql_lower, params_text = _sql_and_params_text(call)
            assert "ag_catalog.cypher(%s" not in sql_lower, (
                "ag_catalog.cypher graph name must be emitted as a SQL literal, not a bind parameter"
            )
            assert f"ag_catalog.cypher('{GRAPH_NAME.lower()}'" in sql_lower, (
                "Graph edge counting must use the configured GRAPH_NAME as a literal "
                "first argument to ag_catalog.cypher()"
            )
            assert GRAPH_NAME.lower() not in params_text, (
                "GRAPH_NAME must not appear in execute() params; only data_source scoping should be parameterized"
            )

    def test_does_not_count_edges_from_other_data_sources(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            count_graph_edges_by_family,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(7,)] * 6)
        count_graph_edges_by_family(conn, ds_id)
        calls = mock_cursor.execute.call_args_list
        for call in calls:
            _, params_text = _sql_and_params_text(call)
            assert str(ds_id).lower() in params_text, "data_source_id must be passed as a query parameter for scoping"

    def test_excludes_superseded_source_records(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            count_graph_edges_by_family,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(5,)] * 6)
        count_graph_edges_by_family(conn, ds_id)
        calls = mock_cursor.execute.call_args_list
        for call in calls:
            sql_lower, _ = _sql_and_params_text(call)
            assert "superseded_by is null" in sql_lower, (
                "Graph-edge numerator must exclude superseded source records "
                "via source_record_scope_where() for active-only scoping"
            )


class TestExpectedEdgeDenominators:
    """Mocked-cursor tests for the expected-edge denominator helpers that lock
    denominator semantics to the existing loader contract."""

    def test_returns_dict_keyed_by_edge_family(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        expected = dict(
            zip(
                EXPECTED_EDGE_FAMILIES,
                [101, 102, 103, 104, 105, 106],
                strict=True,
            )
        )
        conn, _ = _mock_conn_with_side_effect([(value,) for value in expected.values()])
        result = expected_edge_denominators(conn, ds_id)
        assert isinstance(result, dict)
        assert set(result) == set(EXPECTED_EDGE_FAMILIES)
        assert result == expected

    def test_contributed_to_uses_contribution_like_types(self) -> None:
        from core.graph.loader import CONTRIBUTION_LIKE_TYPES
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        found = any(
            _has_type_allowlist(sql, params, CONTRIBUTION_LIKE_TYPES)
            for sql, params in (_sql_and_params_text(c) for c in mock_cursor.execute.call_args_list)
        )
        assert found, (
            f"CONTRIBUTED_TO denominator must include all CONTRIBUTION_LIKE_TYPES "
            f"{CONTRIBUTION_LIKE_TYPES} in SQL text or bound params"
        )

    def test_spent_on_uses_expenditure_like_types_with_null_support_oppose(self) -> None:
        from core.graph.loader import EXPENDITURE_LIKE_TYPES
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        found_matching_call = False
        for call in mock_cursor.execute.call_args_list:
            sql_lower, params_text = _sql_and_params_text(call)
            has_types = _has_type_allowlist(sql_lower, params_text, EXPENDITURE_LIKE_TYPES)
            has_null_filter = "support_oppose is null" in sql_lower
            if has_types and has_null_filter:
                found_matching_call = True
                break
        assert found_matching_call, (
            f"SPENT_ON denominator must include all EXPENDITURE_LIKE_TYPES "
            f"{EXPENDITURE_LIKE_TYPES} (in SQL or params) with "
            f"support_oppose IS NULL in the same query"
        )

    def test_supports_uses_support_oppose_s(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        found_supports_denominator = False
        for call in mock_cursor.execute.call_args_list:
            sql_lower, params_text = _sql_and_params_text(call)
            if _has_exact_support_oppose_routing(
                sql_lower,
                params_text,
                discriminator="S",
            ):
                found_supports_denominator = True
        assert found_supports_denominator, (
            "SUPPORTS denominator must prove exact S routing via "
            "support_oppose = 'S' or explicit split semantics (group/filter/case)"
        )

    def test_opposes_uses_support_oppose_o(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        found_opposes_denominator = False
        for call in mock_cursor.execute.call_args_list:
            sql_lower, params_text = _sql_and_params_text(call)
            if _has_exact_support_oppose_routing(
                sql_lower,
                params_text,
                discriminator="O",
            ):
                found_opposes_denominator = True
        assert found_opposes_denominator, (
            "OPPOSES denominator must prove exact O routing via "
            "support_oppose = 'O' or explicit split semantics (group/filter/case)"
        )

    def test_affiliated_with_counts_from_candidate_committee_link(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        found = any(
            _routes_to_candidate_committee_link_table(_sql_and_params_text(c)[0])
            for c in mock_cursor.execute.call_args_list
        )
        assert found, "AFFILIATED_WITH denominator must count from cf.candidate_committee_link in at least one query"

    def test_filed_counts_from_filing_table(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        found = any(_routes_to_filing_table(_sql_and_params_text(c)[0]) for c in mock_cursor.execute.call_args_list)
        assert found, "FILED denominator must count from cf.filing in at least one query"

    def test_all_denominators_scoped_by_data_source_id(self) -> None:
        from core.graph.loader import CONTRIBUTION_LIKE_TYPES, EXPENDITURE_LIKE_TYPES
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        calls = mock_cursor.execute.call_args_list
        transaction_families = {"CONTRIBUTED_TO", "SPENT_ON", "SUPPORTS", "OPPOSES"}

        for family in EXPECTED_EDGE_FAMILIES:
            family_calls = [
                (sql, params_text)
                for sql, params_text in (_sql_and_params_text(call) for call in calls)
                if _call_matches_family_route(
                    sql,
                    params_text,
                    family,
                    contribution_types=CONTRIBUTION_LIKE_TYPES,
                    expenditure_types=EXPENDITURE_LIKE_TYPES,
                )
            ]
            assert family_calls, (
                f"{family} denominator must be identifiable before validating data-source scope semantics"
            )
            assert any(
                "data_source_id" in sql
                and str(ds_id).lower() in params_text
                and (family not in transaction_families or _has_source_record_id_join(sql))
                for sql, params_text in family_calls
            ), (
                f"{family} denominator must apply SQL-level data_source_id scoping; "
                "transaction-derived families must scope via source_record_id -> "
                "core.source_record.id"
            )

    def test_transaction_family_queries_join_source_record_with_transaction_alias(self) -> None:
        from core.graph.loader import CONTRIBUTION_LIKE_TYPES, EXPENDITURE_LIKE_TYPES
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        calls = mock_cursor.execute.call_args_list

        for family in ("CONTRIBUTED_TO", "SPENT_ON", "SUPPORTS", "OPPOSES"):
            family_calls = [
                sql
                for sql, params_text in (_sql_and_params_text(call) for call in calls)
                if _call_matches_family_route(
                    sql,
                    params_text,
                    family,
                    contribution_types=CONTRIBUTION_LIKE_TYPES,
                    expenditure_types=EXPENDITURE_LIKE_TYPES,
                )
            ]
            assert family_calls, f"{family} denominator query must be present"
            assert any("join core.source_record sr on t.source_record_id = sr.id" in sql for sql in family_calls), (
                f"{family} denominator must qualify transaction source_record_id with the t alias "
                "to keep join routing explicit and stable"
            )

    def test_each_family_tied_to_expected_denominator_route(self) -> None:
        from core.graph.loader import CONTRIBUTION_LIKE_TYPES, EXPENDITURE_LIKE_TYPES
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        result = expected_edge_denominators(conn, ds_id)
        calls = mock_cursor.execute.call_args_list
        assert set(result) == set(EXPECTED_EDGE_FAMILIES)

        for family in EXPECTED_EDGE_FAMILIES:
            matching_calls = [
                (sql, params)
                for sql, params in (_sql_and_params_text(c) for c in calls)
                if _call_matches_family_route(
                    sql,
                    params,
                    family,
                    contribution_types=CONTRIBUTION_LIKE_TYPES,
                    expenditure_types=EXPENDITURE_LIKE_TYPES,
                )
            ]
            assert matching_calls, (
                f"{family} denominator must be tied to its own route/query "
                f"contract, not satisfied by unrelated family queries"
            )

    def test_contributed_to_excludes_rows_with_support_oppose(self) -> None:
        from core.graph.loader import CONTRIBUTION_LIKE_TYPES
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        for call in mock_cursor.execute.call_args_list:
            sql_lower, params_text = _sql_and_params_text(call)
            if _has_type_allowlist(sql_lower, params_text, CONTRIBUTION_LIKE_TYPES):
                assert "support_oppose is null" in sql_lower, (
                    "CONTRIBUTED_TO denominator must exclude rows with non-null support_oppose "
                    "to match the core.graph.loader contribution route semantics"
                )
                break

    def test_supports_denominator_requires_candidate_eligibility(self) -> None:
        """SUPPORTS must only count IE rows with a resolved recipient_candidate_id,
        matching load_ie_edges() which inner-joins cf.candidate."""
        from core.graph.loader import CONTRIBUTION_LIKE_TYPES, EXPENDITURE_LIKE_TYPES
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        supports_calls = [
            sql
            for sql, params_text in (_sql_and_params_text(c) for c in mock_cursor.execute.call_args_list)
            if _call_matches_family_route(
                sql,
                params_text,
                "SUPPORTS",
                contribution_types=CONTRIBUTION_LIKE_TYPES,
                expenditure_types=EXPENDITURE_LIKE_TYPES,
            )
        ]
        assert supports_calls, "SUPPORTS denominator query must be present"
        assert any(_has_candidate_eligibility_join(sql) for sql in supports_calls), (
            "SUPPORTS denominator must join cf.candidate on recipient_candidate_id "
            "to match load_ie_edges() eligibility — IE rows without a resolved "
            "candidate cannot become graph edges"
        )

    def test_opposes_denominator_requires_candidate_eligibility(self) -> None:
        """OPPOSES must only count IE rows with a resolved recipient_candidate_id,
        matching load_ie_edges() which inner-joins cf.candidate."""
        from core.graph.loader import CONTRIBUTION_LIKE_TYPES, EXPENDITURE_LIKE_TYPES
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        opposes_calls = [
            sql
            for sql, params_text in (_sql_and_params_text(c) for c in mock_cursor.execute.call_args_list)
            if _call_matches_family_route(
                sql,
                params_text,
                "OPPOSES",
                contribution_types=CONTRIBUTION_LIKE_TYPES,
                expenditure_types=EXPENDITURE_LIKE_TYPES,
            )
        ]
        assert opposes_calls, "OPPOSES denominator query must be present"
        assert any(_has_candidate_eligibility_join(sql) for sql in opposes_calls), (
            "OPPOSES denominator must join cf.candidate on recipient_candidate_id "
            "to match load_ie_edges() eligibility — IE rows without a resolved "
            "candidate cannot become graph edges"
        )

    def test_excludes_superseded_source_records(self) -> None:
        from domains.campaign_finance.quality.reconciliation import (
            expected_edge_denominators,
        )

        ds_id = uuid4()
        conn, mock_cursor = _mock_conn_with_side_effect([(10,)] * 6)
        expected_edge_denominators(conn, ds_id)
        calls = mock_cursor.execute.call_args_list
        for call in calls:
            sql_lower, _ = _sql_and_params_text(call)
            assert "superseded_by is null" in sql_lower, (
                "Edge denominators must exclude superseded source records "
                "via source_record_scope_where() for active-only scoping"
            )
