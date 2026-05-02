"""Unit tests for reconciliation helpers using mocked DB cursors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.quality.test_reconciliation_helpers import (
    call_matches_family_route as _call_matches_family_route,
    has_type_allowlist_in_sql_or_params as _has_type_allowlist,
    routes_to_candidate_committee_link_table as _routes_to_candidate_committee_link_table,
    routes_to_filing_table as _routes_to_filing_table,
)

from domains.campaign_finance.quality.reconciliation import (
    _validate_identifier,
    check_key_field_completeness,
    check_record_count_reconciliation,
    completeness_sample,
    count_source_records,
    duplicate_hashes,
    fetch_data_source_metadata,
    list_data_source_jurisdictions,
    null_rate,
    pull_date_range,
    resolve_data_source_ids,
    source_record_scope_where,
)

_TEST_FILE_LINE_HARD_LIMIT = 800


def _mock_conn(rows: list[tuple], *, fetchone: bool = False) -> MagicMock:
    """Build a mock psycopg connection returning the given rows."""
    mock_cursor = MagicMock()
    if fetchone:
        mock_cursor.fetchone.return_value = rows[0] if rows else None
    else:
        mock_cursor.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


class TestTestFileSizeGuard:
    def test_reconciliation_file_stays_within_line_hard_limit(self) -> None:
        line_count = len(Path(__file__).read_text().splitlines())
        assert line_count <= _TEST_FILE_LINE_HARD_LIMIT, (
            "test_reconciliation.py exceeds the 800-line hard limit and must be split"
        )


class TestResolveDataSourceIds:
    def test_returns_ids_for_domain_and_jurisdiction(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([(ds_id,)])
        result = resolve_data_source_ids(conn, domain="campaign_finance", jurisdiction="federal/fec")
        assert result == [ds_id]
        execute_args = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
        assert "AND name = %s" not in execute_args[0]
        assert "ORDER BY name, id" in execute_args[0]
        assert execute_args[1] == ("campaign_finance", "federal/fec")

    def test_returns_ids_with_name_filter(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([(ds_id,)])
        result = resolve_data_source_ids(
            conn,
            domain="campaign_finance",
            jurisdiction="state/CO",
            name="TRACER Bulk Download — Contributions",
        )
        assert result == [ds_id]
        execute_args = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
        assert "AND name = %s" in execute_args[0]
        assert "ORDER BY name, id" in execute_args[0]
        assert execute_args[1] == ("campaign_finance", "state/CO", "TRACER Bulk Download — Contributions")

    def test_returns_empty_for_no_matches(self) -> None:
        conn = _mock_conn([])
        result = resolve_data_source_ids(conn, domain="campaign_finance", jurisdiction="state/XX")
        assert result == []

    def test_orders_results_by_name_then_id_for_stable_output(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([(ds_id,)])

        resolve_data_source_ids(conn, domain="campaign_finance", jurisdiction="state/GA")

        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "ORDER BY name, id" in sql


class TestListDataSourceJurisdictions:
    def test_returns_distinct_ordered_jurisdictions(self) -> None:
        conn = _mock_conn([("federal/fec",), ("state/CO",), ("state/NC",)])
        result = list_data_source_jurisdictions(conn, domain="campaign_finance")
        assert result == ["federal/fec", "state/CO", "state/NC"]
        execute_args = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
        assert "jurisdiction IS NOT NULL" in execute_args[0]
        assert "ORDER BY jurisdiction" in execute_args[0]
        assert execute_args[1] == ("campaign_finance",)


class TestCountSourceRecords:
    def test_counts_active_records(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([(42,)], fetchone=True)
        assert count_source_records(conn, ds_id) == 42
        execute_args = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
        assert "sr.superseded_by IS NULL" in execute_args[0]
        assert execute_args[1] == [ds_id]

    def test_counts_all_records_when_active_only_false(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([(100,)], fetchone=True)
        assert count_source_records(conn, ds_id, active_only=False) == 100
        execute_args = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
        assert "sr.superseded_by IS NULL" not in execute_args[0]
        assert execute_args[1] == [ds_id]

    def test_returns_zero_for_none_row(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([], fetchone=True)
        assert count_source_records(conn, ds_id) == 0


class TestNullRate:
    def test_returns_null_and_total_counts(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([(3, 100)], fetchone=True)
        nulls, total = null_rate(conn, ds_id, "source_url")
        assert nulls == 3
        assert total == 100

    def test_returns_zeros_for_empty_result(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([], fetchone=True)
        nulls, total = null_rate(conn, ds_id, "source_url")
        assert nulls == 0
        assert total == 0


class TestDuplicateHashes:
    def test_returns_duplicate_pairs(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([("abc123", 3), ("def456", 2)])
        result = duplicate_hashes(conn, ds_id)
        assert result == [("abc123", 3), ("def456", 2)]

    def test_returns_empty_when_no_duplicates(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([])
        result = duplicate_hashes(conn, ds_id)
        assert result == []

    def test_excludes_null_hashes_from_query(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([])
        duplicate_hashes(conn, ds_id)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "sr.record_hash IS NOT NULL" in sql

    def test_omits_limit_clause_when_limit_is_none(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([])
        duplicate_hashes(conn, ds_id, limit=None)
        call_args = conn.cursor.return_value.__enter__.return_value.execute.call_args
        assert "LIMIT" not in call_args.args[0]
        assert call_args.args[1] == [ds_id]


class TestPullDateRange:
    def test_returns_min_max_dates(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([("2024-01-01", "2024-12-31")], fetchone=True)
        min_d, max_d = pull_date_range(conn, ds_id)
        assert min_d == "2024-01-01"
        assert max_d == "2024-12-31"

    def test_returns_none_for_empty(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([], fetchone=True)
        min_d, max_d = pull_date_range(conn, ds_id)
        assert min_d is None
        assert max_d is None


class TestFetchDataSourceMetadata:
    def test_returns_name_and_source_url(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([("FEC Bulk Data", "https://www.fec.gov/data/browse-data/?tab=bulk-data")], fetchone=True)
        result = fetch_data_source_metadata(conn, ds_id)
        assert result == ("FEC Bulk Data", "https://www.fec.gov/data/browse-data/?tab=bulk-data")

    def test_returns_id_string_when_data_source_missing(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([], fetchone=True)
        result = fetch_data_source_metadata(conn, ds_id)
        assert result == (str(ds_id), None)


class TestCompletenessSample:
    def test_returns_per_column_null_counts(self) -> None:
        ds_id = uuid4()
        # 3 columns × 2 values each = 6 values in row
        conn = _mock_conn([(0, 100, 5, 100, 0, 100)], fetchone=True)
        result = completeness_sample(conn, ds_id)
        assert result["source_record_key"] == (0, 100)
        assert result["source_url"] == (5, 100)
        assert result["raw_fields"] == (0, 100)

    def test_returns_zeros_for_no_rows(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([], fetchone=True)
        result = completeness_sample(conn, ds_id)
        assert result["source_record_key"] == (0, 0)
        assert result["source_url"] == (0, 0)
        assert result["raw_fields"] == (0, 0)

    def test_uses_deterministic_order_with_created_at_id_tiebreaker(self) -> None:
        ds_id = uuid4()
        conn = _mock_conn([(0, 1, 0, 1, 0, 1)], fetchone=True)
        completeness_sample(conn, ds_id, sample_limit=50)

        execute_args = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
        assert "ORDER BY sr.created_at, sr.id LIMIT %s" in execute_args[0]
        assert execute_args[1] == (ds_id, 50)


class TestValidateIdentifier:
    def test_accepts_valid_identifiers(self) -> None:
        _validate_identifier("source_url")
        _validate_identifier("record_hash")
        _validate_identifier("count")

    def test_rejects_invalid_identifiers(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _validate_identifier("source; DROP TABLE")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _validate_identifier("")
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _validate_identifier("col-name")


class TestSourceRecordScopeWhere:
    def test_defaults_to_active_filter(self) -> None:
        where = source_record_scope_where()
        assert where == "sr.data_source_id = %s AND sr.superseded_by IS NULL"

    def test_omits_active_filter_when_requested(self) -> None:
        where = source_record_scope_where(active_only=False)
        assert where == "sr.data_source_id = %s"

    def test_supports_custom_alias(self) -> None:
        where = source_record_scope_where(alias="source", active_only=True)
        assert where == "source.data_source_id = %s AND source.superseded_by IS NULL"

    def test_rejects_invalid_alias(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            source_record_scope_where(alias="sr; DROP TABLE")


class TestFetchAggregate:
    def test_returns_aggregate_value(self) -> None:
        from domains.campaign_finance.quality.reconciliation import fetch_aggregate

        ds_id = uuid4()
        conn = _mock_conn([(42,)], fetchone=True)
        result = fetch_aggregate(conn, ds_id, "record_hash", "COUNT")
        assert result == 42

    def test_returns_none_for_empty_result(self) -> None:
        from domains.campaign_finance.quality.reconciliation import fetch_aggregate

        ds_id = uuid4()
        conn = _mock_conn([], fetchone=True)
        result = fetch_aggregate(conn, ds_id, "record_hash", "COUNT")
        assert result is None

    def test_rejects_invalid_column_name(self) -> None:
        from domains.campaign_finance.quality.reconciliation import fetch_aggregate

        ds_id = uuid4()
        conn = _mock_conn([], fetchone=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            fetch_aggregate(conn, ds_id, "col; DROP TABLE", "COUNT")

    def test_rejects_invalid_aggregate_name(self) -> None:
        from domains.campaign_finance.quality.reconciliation import fetch_aggregate

        ds_id = uuid4()
        conn = _mock_conn([], fetchone=True)
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            fetch_aggregate(conn, ds_id, "record_hash", "COUNT; --")

    def test_active_only_false_omits_superseded_filter(self) -> None:
        from domains.campaign_finance.quality.reconciliation import fetch_aggregate

        ds_id = uuid4()
        conn = _mock_conn([(10,)], fetchone=True)
        fetch_aggregate(conn, ds_id, "record_hash", "COUNT", active_only=False)
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "superseded_by" not in sql


class TestCheckRecordCountReconciliation:
    def test_pass_when_counts_match(self) -> None:
        ds_id = uuid4()
        # First query: record_count from data_source; second: COUNT from source_record
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [(50,), (50,)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = check_record_count_reconciliation(mock_conn, ds_id, "FEC Bulk Data")
        assert result.status == "pass"
        assert result.details["expected"] == 50
        assert result.details["actual"] == 50

    def test_fail_when_counts_differ(self) -> None:
        ds_id = uuid4()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [(100,), (90,)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = check_record_count_reconciliation(mock_conn, ds_id, "FEC Bulk Data")
        assert result.status == "fail"
        assert result.metric_value == 10.0

    def test_warn_when_expected_is_null(self) -> None:
        ds_id = uuid4()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [(None,), (42,)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = check_record_count_reconciliation(mock_conn, ds_id, "FEC Bulk Data")
        assert result.status == "warn"
        assert result.details["expected"] is None


class TestCheckKeyFieldCompleteness:
    def test_all_pass_when_no_nulls(self) -> None:
        ds_id = uuid4()
        # completeness_sample returns 3 columns × 2 values
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0, 100, 0, 100, 0, 100)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = check_key_field_completeness(mock_conn, ds_id, "Test Source")
        assert len(results) == 3
        assert all(r.status == "pass" for r in results)

    def test_warn_when_null_rate_is_nonzero_but_below_threshold(self) -> None:
        ds_id = uuid4()
        # source_record_key: 0/100 (pass), source_url: 3/100=0.03 (warn), raw_fields: 0/100 (pass)
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0, 100, 3, 100, 0, 100)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = check_key_field_completeness(mock_conn, ds_id, "Test Source", null_rate_threshold=0.05)
        url_check = next(r for r in results if r.name == "completeness_source_url")
        assert url_check.status == "warn"
        assert url_check.metric_value == pytest.approx(0.03)

    def test_fail_when_null_rate_exceeds_threshold(self) -> None:
        ds_id = uuid4()
        # source_record_key: 0/100 (pass), source_url: 10/100=0.10 (fail), raw_fields: 0/100 (pass)
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0, 100, 10, 100, 0, 100)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = check_key_field_completeness(mock_conn, ds_id, "Test Source", null_rate_threshold=0.05)
        url_check = next(r for r in results if r.name == "completeness_source_url")
        assert url_check.status == "fail"
        assert url_check.metric_value == pytest.approx(0.10)


class TestDenominatorRouteContractHelpers:
    """Regression coverage for denominator-route helper predicates."""

    def test_allowlist_requires_complete_value_set(self) -> None:
        full_allowlist = frozenset({"monetary", "monetary (itemized)", "monetary (non-itemized)"})
        sql = "select * from cf.transaction where transaction_type = %s"
        params_text = "('monetary',)"

        assert not _has_type_allowlist(sql, params_text, full_allowlist), (
            "Allowlist contract must reject partial route-type coverage"
        )

    def test_allowlist_accepts_complete_value_set_across_sql_and_params(self) -> None:
        full_allowlist = frozenset({"monetary", "monetary (itemized)", "monetary (non-itemized)"})
        sql = "select * from cf.transaction where transaction_type in ('monetary', 'monetary (itemized)')"
        params_text = "('monetary (non-itemized)',)"

        assert _has_type_allowlist(sql, params_text, full_allowlist)

    def test_allowlist_rejects_substring_only_coverage(self) -> None:
        full_allowlist = frozenset({"monetary", "monetary (itemized)", "monetary (non-itemized)"})
        sql = """
            select * from cf.transaction
            where transaction_type in ('monetary (itemized)', 'monetary (non-itemized)')
        """
        params_text = "()"

        assert not _has_type_allowlist(sql, params_text, full_allowlist), (
            "Allowlist contract must require exact literal coverage for each type value;"
            " substring overlap must not satisfy missing values"
        )

    def test_filed_route_rejects_incidental_filing_id_text(self) -> None:
        sql = "select count(*) from cf.transaction where filing_id is not null"
        assert not _routes_to_filing_table(sql)

    def test_filed_route_requires_cf_filing_table(self) -> None:
        sql = "select count(*) from cf.filing where data_source_id = %s"
        assert _routes_to_filing_table(sql)

    def test_affiliated_route_rejects_incidental_candidate_committee_link_text(self) -> None:
        sql = """
            select count(*)
            from cf.transaction
            where notes ilike '%candidate_committee_link%'
        """
        assert not _routes_to_candidate_committee_link_table(sql)

    def test_affiliated_route_requires_cf_candidate_committee_link_table(self) -> None:
        sql = "select count(*) from cf.candidate_committee_link where data_source_id = %s"
        assert _routes_to_candidate_committee_link_table(sql)

    def test_call_route_rejects_incidental_affiliated_with_link_text(self) -> None:
        sql = "select count(*) from cf.transaction where metadata->>'route' = 'candidate_committee_link'"
        assert not _call_matches_family_route(
            sql,
            "()",
            "AFFILIATED_WITH",
            contribution_types=frozenset(),
            expenditure_types=frozenset(),
        )

    def test_call_route_accepts_affiliated_with_candidate_committee_link_table(self) -> None:
        sql = "select count(*) from cf.candidate_committee_link where data_source_id = %s"
        assert _call_matches_family_route(
            sql,
            "()",
            "AFFILIATED_WITH",
            contribution_types=frozenset(),
            expenditure_types=frozenset(),
        )
