"""Helper-contract tests for reconciliation SQL assertion utilities."""

from __future__ import annotations

from unittest.mock import MagicMock

from domains.campaign_finance.quality.test_reconciliation_helpers import (
    call_matches_family_route as _call_matches_family_route,
    has_candidate_eligibility_join as _has_candidate_eligibility_join,
    has_source_record_id_join as _has_source_record_id_join,
    routes_to_candidate_committee_link_table as _routes_to_candidate_committee_link_table,
    routes_to_filing_table as _routes_to_filing_table,
    routes_to_transaction_table as _routes_to_transaction_table,
    sql_and_params_text as _sql_and_params_text,
)


class TestSqlAndParamsTextHelper:
    """Regression coverage for execute() call-shape normalization helper."""

    def test_defaults_params_to_empty_tuple_for_single_positional_execute_arg(self) -> None:
        mock_cursor = MagicMock()
        mock_cursor.execute("SELECT 1")

        sql_lower, params_text = _sql_and_params_text(mock_cursor.execute.call_args)

        assert sql_lower == "select 1"
        assert params_text == "()"

    def test_reads_params_from_two_argument_execute_call(self) -> None:
        mock_cursor = MagicMock()
        mock_cursor.execute("SELECT 1 WHERE id = %s", (123,))

        sql_lower, params_text = _sql_and_params_text(mock_cursor.execute.call_args)

        assert sql_lower == "select 1 where id = %s"
        assert params_text == "(123,)"


class TestSourceRecordIdJoinContractHelper:
    """Contract tests for source_record_id join-shape helper assertions."""

    def test_accepts_direct_equality_join(self) -> None:
        sql = """
            SELECT COUNT(*)
            FROM cypher('graph', $$ MATCH ()-[e:CONTRIBUTED_TO]->() RETURN e $$) AS (edge agtype)
            JOIN core.source_record sr
              ON (edge->>'source_record_id')::uuid = sr.id
            WHERE sr.data_source_id = %s
        """
        assert _has_source_record_id_join(sql)

    def test_rejects_direct_equality_when_join_alias_is_not_source_record(self) -> None:
        sql = """
            SELECT COUNT(*)
            FROM cypher('graph', $$ MATCH ()-[e:CONTRIBUTED_TO]->() RETURN e $$) AS (edge agtype)
            JOIN some_other_table sr
              ON (edge->>'source_record_id')::uuid = sr.id
            JOIN core.source_record source_record
              ON source_record.id = sr.source_record_id
            WHERE source_record.data_source_id = %s
        """
        assert not _has_source_record_id_join(sql), (
            "Direct equality scoping must bind source_record_id to the alias that comes "
            "from core.source_record and carries data_source_id"
        )

    def test_accepts_in_subquery_join_shape(self) -> None:
        sql = """
            SELECT COUNT(*)
            FROM cypher('graph', $$ MATCH ()-[e:CONTRIBUTED_TO]->() RETURN e $$) AS (edge agtype)
            WHERE (edge->>'source_record_id')::uuid IN (
                SELECT sr.id FROM core.source_record sr WHERE sr.data_source_id = %s
            )
        """
        assert _has_source_record_id_join(sql), (
            "Valid data-source scoping may use source_record_id IN (SELECT sr.id ...)"
        )

    def test_accepts_alias_qualified_source_record_id_equality(self) -> None:
        sql = """
            SELECT COUNT(*)
            FROM cf.transaction t
            JOIN core.source_record sr
              ON t.source_record_id = sr.id
            WHERE sr.data_source_id = %s
        """
        assert _has_source_record_id_join(sql), (
            "Join-shape detection must accept explicit table-qualified source_record_id "
            "columns (for example t.source_record_id = sr.id)"
        )

    def test_rejects_in_subquery_without_data_source_scope(self) -> None:
        sql = """
            SELECT COUNT(*)
            FROM cypher('graph', $$ MATCH ()-[e:CONTRIBUTED_TO]->() RETURN e $$) AS (edge agtype)
            WHERE (edge->>'source_record_id')::uuid IN (
                SELECT sr.id FROM core.source_record sr WHERE sr.superseded_by IS NULL
            )
              AND unrelated.data_source_id = %s
        """
        assert not _has_source_record_id_join(sql), (
            "IN-subquery scoping must tie data_source_id to the selected source_record rows"
        )

    def test_rejects_in_subquery_when_scope_alias_differs_from_selected_rows(self) -> None:
        sql = """
            SELECT COUNT(*)
            FROM cypher('graph', $$ MATCH ()-[e:CONTRIBUTED_TO]->() RETURN e $$) AS (edge agtype)
            WHERE (edge->>'source_record_id')::uuid IN (
                SELECT sr.id
                FROM core.source_record sr
                WHERE source_record.data_source_id = %s
            )
        """
        assert not _has_source_record_id_join(sql), (
            "IN-subquery scoping must use the same source_record alias as SELECT ... id"
        )


class TestTransactionDenominatorRouteContractHelper:
    """Contract tests for transaction-derived denominator route predicates."""

    def test_call_route_rejects_contributed_to_without_cf_transaction_table(self) -> None:
        sql = "select count(*) from cf.filing where transaction_type = any(%s)"
        assert not _call_matches_family_route(
            sql,
            "('monetary', 'monetary (itemized)', 'monetary (non-itemized)')",
            "CONTRIBUTED_TO",
            contribution_types=frozenset({"Monetary", "Monetary (Itemized)", "Monetary (Non-Itemized)"}),
            expenditure_types=frozenset(),
        )

    def test_call_route_rejects_spent_on_without_cf_transaction_table(self) -> None:
        sql = "select count(*) from cf.filing where support_oppose is null and transaction_type = any(%s)"
        assert not _call_matches_family_route(
            sql,
            "('expenditure (itemized)', 'expenditure (non-itemized)', 'independent expenditure')",
            "SPENT_ON",
            contribution_types=frozenset(),
            expenditure_types=frozenset(
                {"Expenditure (Itemized)", "Expenditure (Non-Itemized)", "Independent Expenditure"}
            ),
        )

    def test_call_route_rejects_supports_without_cf_transaction_table(self) -> None:
        sql = "select count(*) from cf.filing where support_oppose = 's'"
        assert not _call_matches_family_route(
            sql,
            "()",
            "SUPPORTS",
            contribution_types=frozenset(),
            expenditure_types=frozenset(),
        )

    def test_call_route_rejects_opposes_without_cf_transaction_table(self) -> None:
        sql = "select count(*) from cf.filing where support_oppose = 'o'"
        assert not _call_matches_family_route(
            sql,
            "()",
            "OPPOSES",
            contribution_types=frozenset(),
            expenditure_types=frozenset(),
        )

    def test_transaction_route_requires_cf_transaction_table(self) -> None:
        sql = "select count(*) from cf.transaction where support_oppose = 's'"
        assert _routes_to_transaction_table(sql)

    def test_transaction_route_accepts_join_cf_transaction(self) -> None:
        sql = "select count(distinct t.source_record_id) from core.source_record sr join cf.transaction t on t.source_record_id = sr.id"
        assert _routes_to_transaction_table(sql)

    def test_call_route_accepts_contributed_to_via_join(self) -> None:
        sql = (
            "select count(distinct t.source_record_id) "
            "from core.source_record sr "
            "join cf.transaction t on t.source_record_id = sr.id "
            "where t.support_oppose is null "
            "and t.transaction_type in ('Monetary', 'Monetary (Itemized)', 'Monetary (Non-Itemized)')"
        )
        assert _call_matches_family_route(
            sql,
            "()",
            "CONTRIBUTED_TO",
            contribution_types=frozenset({"Monetary", "Monetary (Itemized)", "Monetary (Non-Itemized)"}),
            expenditure_types=frozenset(),
        )

    def test_call_route_rejects_contributed_to_without_null_support_oppose_filter(self) -> None:
        sql = (
            "select count(distinct t.source_record_id) "
            "from core.source_record sr "
            "join cf.transaction t on t.source_record_id = sr.id "
            "where t.transaction_type in ('Monetary', 'Monetary (Itemized)', 'Monetary (Non-Itemized)')"
        )
        assert not _call_matches_family_route(
            sql,
            "()",
            "CONTRIBUTED_TO",
            contribution_types=frozenset({"Monetary", "Monetary (Itemized)", "Monetary (Non-Itemized)"}),
            expenditure_types=frozenset(),
        )

    def test_call_route_accepts_spent_on_via_join(self) -> None:
        sql = "select count(distinct t.source_record_id) from core.source_record sr join cf.transaction t on t.source_record_id = sr.id where t.support_oppose is null and t.transaction_type in ('Expenditure (Itemized)', 'Expenditure (Non-Itemized)', 'Independent Expenditure')"
        assert _call_matches_family_route(
            sql,
            "()",
            "SPENT_ON",
            contribution_types=frozenset(),
            expenditure_types=frozenset(
                {"Expenditure (Itemized)", "Expenditure (Non-Itemized)", "Independent Expenditure"}
            ),
        )

    def test_call_route_accepts_supports_via_join(self) -> None:
        sql = "select count(distinct t.source_record_id) from core.source_record sr join cf.transaction t on t.source_record_id = sr.id where t.support_oppose = 's'"
        assert _call_matches_family_route(
            sql,
            "()",
            "SUPPORTS",
            contribution_types=frozenset(),
            expenditure_types=frozenset(),
        )

    def test_call_route_accepts_opposes_via_join(self) -> None:
        sql = "select count(distinct t.source_record_id) from core.source_record sr join cf.transaction t on t.source_record_id = sr.id where t.support_oppose = 'o'"
        assert _call_matches_family_route(
            sql,
            "()",
            "OPPOSES",
            contribution_types=frozenset(),
            expenditure_types=frozenset(),
        )

    def test_transaction_route_rejects_count_star_when_cf_transaction_is_only_joined(self) -> None:
        sql = "select count(*) from cf.filing f join cf.transaction t on t.filing_id = f.id"
        assert not _routes_to_transaction_table(sql), (
            "JOIN-only cf.transaction route must not pass when COUNT(*) is not bound to a cf.transaction alias"
        )

    def test_transaction_route_accepts_count_star_when_cf_transaction_is_from_table(self) -> None:
        sql = "select count(*) from cf.transaction t join cf.filing f on f.id = t.filing_id"
        assert _routes_to_transaction_table(sql), (
            "COUNT(*) is a valid route shape when cf.transaction is the counted FROM table"
        )

    def test_call_route_rejects_supports_when_join_route_uses_count_star(self) -> None:
        sql = (
            "select count(*) from cf.filing f join cf.transaction t on t.filing_id = f.id where t.support_oppose = 's'"
        )
        assert not _call_matches_family_route(
            sql,
            "()",
            "SUPPORTS",
            contribution_types=frozenset(),
            expenditure_types=frozenset(),
        )

    def test_transaction_route_accepts_table_qualified_count_without_alias(self) -> None:
        sql = (
            "select count(distinct cf.transaction.source_record_id) "
            "from core.source_record sr "
            "join cf.transaction on cf.transaction.source_record_id = sr.id"
        )
        assert _routes_to_transaction_table(sql)

    def test_transaction_route_accepts_count_star_when_join_is_only_in_subquery(self) -> None:
        sql = """
            WITH tx AS (
                SELECT t.source_record_id
                FROM cf.transaction t
                WHERE t.source_record_id IN (
                    SELECT sr.id
                    FROM core.source_record sr
                    JOIN core.data_source ds ON ds.id = sr.data_source_id
                )
            )
            SELECT COUNT(*) FROM tx
        """
        assert _routes_to_transaction_table(sql), (
            "JOIN tokens inside subqueries/CTEs must not invalidate a valid cf.transaction count route"
        )


class TestJoinBasedRoutingContractHelper:
    """Contract tests for JOIN-based table routing in non-transaction families."""

    def test_candidate_committee_link_route_accepts_join(self) -> None:
        sql = "select count(distinct ccl.source_record_id) from core.source_record sr join cf.candidate_committee_link ccl on ccl.source_record_id = sr.id"
        assert _routes_to_candidate_committee_link_table(sql)

    def test_candidate_committee_link_route_accepts_from(self) -> None:
        sql = "select count(*) from cf.candidate_committee_link where data_source_id = %s"
        assert _routes_to_candidate_committee_link_table(sql)

    def test_candidate_committee_link_route_rejects_incidental_text(self) -> None:
        sql = "select count(*) from cf.transaction where notes ilike '%candidate_committee_link%'"
        assert not _routes_to_candidate_committee_link_table(sql)

    def test_filing_route_accepts_join(self) -> None:
        sql = "select count(distinct f.source_record_id) from core.source_record sr join cf.filing f on f.source_record_id = sr.id"
        assert _routes_to_filing_table(sql)

    def test_filing_route_accepts_from(self) -> None:
        sql = "select count(*) from cf.filing where data_source_id = %s"
        assert _routes_to_filing_table(sql)

    def test_filing_route_rejects_incidental_text(self) -> None:
        sql = "select count(*) from cf.transaction where filing_id = %s"
        assert not _routes_to_filing_table(sql)

    def test_call_route_accepts_affiliated_with_via_join(self) -> None:
        sql = "select count(distinct ccl.source_record_id) from core.source_record sr join cf.candidate_committee_link ccl on ccl.source_record_id = sr.id where sr.data_source_id = %s"
        assert _call_matches_family_route(
            sql,
            "()",
            "AFFILIATED_WITH",
            contribution_types=frozenset(),
            expenditure_types=frozenset(),
        )

    def test_call_route_accepts_filed_via_join(self) -> None:
        sql = "select count(distinct f.source_record_id) from core.source_record sr join cf.filing f on f.source_record_id = sr.id where sr.data_source_id = %s"
        assert _call_matches_family_route(
            sql,
            "()",
            "FILED",
            contribution_types=frozenset(),
            expenditure_types=frozenset(),
        )

    def test_candidate_committee_link_route_rejects_count_star_when_only_joined(self) -> None:
        sql = "select count(*) from cf.transaction t join cf.candidate_committee_link ccl on ccl.source_record_id = t.source_record_id"
        assert not _routes_to_candidate_committee_link_table(sql), (
            "JOIN-only candidate_committee_link must not pass when COUNT(*) does not bind to ccl alias"
        )

    def test_candidate_committee_link_route_accepts_count_star_when_from_table(self) -> None:
        sql = "select count(*) from cf.candidate_committee_link ccl join cf.transaction t on t.source_record_id = ccl.source_record_id"
        assert _routes_to_candidate_committee_link_table(sql), (
            "COUNT(*) is valid when candidate_committee_link is the FROM route table"
        )

    def test_filing_route_rejects_count_star_when_only_joined(self) -> None:
        sql = "select count(*) from cf.transaction t join cf.filing f on f.id = t.filing_id"
        assert not _routes_to_filing_table(sql), "JOIN-only cf.filing route must not pass when COUNT(*) is unbound"

    def test_filing_route_accepts_count_star_when_from_table(self) -> None:
        sql = "select count(*) from cf.filing f join cf.transaction t on t.filing_id = f.id"
        assert _routes_to_filing_table(sql), "COUNT(*) is valid when cf.filing is the FROM route table"


class TestCandidateEligibilityJoinContractHelper:
    """Contract tests for has_candidate_eligibility_join helper."""

    def test_accepts_loader_style_candidate_join(self) -> None:
        sql = (
            "SELECT COUNT(*) FROM cf.transaction t "
            "JOIN core.source_record sr ON t.source_record_id = sr.id "
            "JOIN cf.candidate cand ON cand.id = t.recipient_candidate_id "
            "WHERE sr.data_source_id = %s AND t.support_oppose = %s"
        )
        assert _has_candidate_eligibility_join(sql)

    def test_rejects_query_without_candidate_join(self) -> None:
        sql = (
            "SELECT COUNT(*) FROM cf.transaction t "
            "JOIN core.source_record sr ON t.source_record_id = sr.id "
            "WHERE sr.data_source_id = %s AND t.support_oppose = %s"
        )
        assert not _has_candidate_eligibility_join(sql)

    def test_rejects_candidate_join_on_wrong_column(self) -> None:
        sql = (
            "SELECT COUNT(*) FROM cf.transaction t "
            "JOIN cf.candidate cand ON cand.id = t.committee_id "
            "WHERE t.support_oppose = %s"
        )
        assert not _has_candidate_eligibility_join(sql)

    def test_accepts_reversed_join_condition_order(self) -> None:
        sql = (
            "SELECT COUNT(*) FROM cf.transaction t "
            "JOIN cf.candidate cand ON t.recipient_candidate_id = cand.id "
            "WHERE t.support_oppose = %s"
        )
        assert _has_candidate_eligibility_join(sql)
