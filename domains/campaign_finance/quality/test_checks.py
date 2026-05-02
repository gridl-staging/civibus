"""Unit tests for anomaly checks using deterministic fixtures."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domains.campaign_finance.quality.checks import (
    check_amount_sanity,
    check_date_range,
    check_duplicate_records,
    check_null_rate,
    check_raw_field_null_rate,
    check_source_count,
)
from domains.campaign_finance.quality.conftest import EXPECTED_EDGE_FAMILIES
from domains.campaign_finance.quality.models import CheckResult


def _mock_conn(fetchone_value: tuple | None = None, fetchall_value: list | None = None) -> MagicMock:
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone_value
    mock_cursor.fetchall.return_value = fetchall_value or []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


class TestCheckNullRate:
    def test_pass_when_no_nulls(self) -> None:
        conn = _mock_conn(fetchone_value=(0, 100))
        result = check_null_rate(conn, uuid4(), "Test Source", "source_url")
        assert result.status == "pass"
        assert result.metric_value == 0.0

    def test_warn_when_below_threshold(self) -> None:
        conn = _mock_conn(fetchone_value=(2, 100))
        result = check_null_rate(conn, uuid4(), "Test Source", "source_url", threshold=0.05)
        assert result.status == "warn"
        assert result.metric_value == 0.02

    def test_fail_when_above_threshold(self) -> None:
        conn = _mock_conn(fetchone_value=(15, 100))
        result = check_null_rate(conn, uuid4(), "Test Source", "source_url", threshold=0.05)
        assert result.status == "fail"
        assert result.metric_value == 0.15

    def test_warn_at_exact_threshold_boundary(self) -> None:
        # 5/100 = 0.05, exactly at threshold — should be warn (nonzero and <= threshold)
        conn = _mock_conn(fetchone_value=(5, 100))
        result = check_null_rate(conn, uuid4(), "Test Source", "source_url", threshold=0.05)
        assert result.status == "warn"
        assert result.metric_value == pytest.approx(0.05)

    def test_pass_when_empty(self) -> None:
        conn = _mock_conn(fetchone_value=(0, 0))
        result = check_null_rate(conn, uuid4(), "Test Source", "source_url")
        assert result.status == "pass"
        assert result.metric_value == 0.0


class TestCheckDuplicateRecords:
    def test_pass_when_no_duplicates(self) -> None:
        conn = _mock_conn(fetchall_value=[])
        result = check_duplicate_records(conn, uuid4(), "Test Source")
        assert result.status == "pass"
        assert result.metric_value == 0.0

    def test_warn_when_few_duplicates(self) -> None:
        # 3 records with same hash = 2 extras, under default fail_threshold=10
        conn = _mock_conn(fetchall_value=[("abc", 3)])
        result = check_duplicate_records(conn, uuid4(), "Test Source")
        assert result.status == "warn"
        assert result.metric_value == 2.0

    def test_fail_when_many_duplicates(self) -> None:
        conn = _mock_conn(fetchall_value=[("abc", 8), ("def", 6)])
        # 7 + 5 = 12 extras, above default fail_threshold=10
        result = check_duplicate_records(conn, uuid4(), "Test Source")
        assert result.status == "fail"
        assert result.metric_value == 12.0

    def test_details_include_top_duplicates(self) -> None:
        conn = _mock_conn(fetchall_value=[("abc", 3)])
        result = check_duplicate_records(conn, uuid4(), "Test Source")
        assert result.details["top_duplicates"] == [{"hash": "abc", "count": 3}]

    def test_fetches_all_duplicate_groups_for_threshold_evaluation(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.duplicate_hashes",
            return_value=[("abc", 3)],
        ) as mock_duplicate_hashes:
            result = check_duplicate_records(_mock_conn(), uuid4(), "Test Source")

        assert result.status == "warn"
        assert mock_duplicate_hashes.call_args.kwargs["limit"] is None


class TestCheckAmountSanity:
    def test_pass_when_no_records(self) -> None:
        conn = _mock_conn(fetchone_value=None)
        result = check_amount_sanity(conn, uuid4(), "Test Source")
        assert result.status == "pass"

    def test_pass_when_no_amount_field(self) -> None:
        # outliers=0, invalid_amounts=0, with_field=0, total=100
        conn = _mock_conn(fetchone_value=(0, 0, 0, 100))
        result = check_amount_sanity(conn, uuid4(), "Test Source")
        assert result.status == "pass"
        assert result.details["records_with_field"] == 0

    def test_pass_when_all_in_range(self) -> None:
        conn = _mock_conn(fetchone_value=(0, 0, 50, 100))
        result = check_amount_sanity(conn, uuid4(), "Test Source")
        assert result.status == "pass"
        assert result.metric_value == 0.0

    def test_fail_when_outliers_found(self) -> None:
        conn = _mock_conn(fetchone_value=(3, 1, 50, 100))
        result = check_amount_sanity(conn, uuid4(), "Test Source")
        assert result.status == "fail"
        assert result.metric_value == 3.0
        assert result.details["invalid_amount_count"] == 1

    def test_query_scopes_to_active_records(self) -> None:
        conn = _mock_conn(fetchone_value=(0, 0, 1, 1))
        check_amount_sanity(conn, uuid4(), "Test Source")
        sql = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "sr.data_source_id = %s" in sql
        assert "sr.superseded_by IS NULL" in sql


class TestCheckDateRange:
    def test_pass_with_valid_dates(self) -> None:
        past = datetime(2024, 1, 1, tzinfo=timezone.utc)
        recent = datetime(2024, 6, 1, tzinfo=timezone.utc)
        with patch(
            "domains.campaign_finance.quality.checks.pull_date_range",
            return_value=(past, recent),
        ):
            result = check_date_range(_mock_conn(), uuid4(), "Test Source")
        assert result.status == "pass"
        assert result.metric_value == 152.0

    def test_warn_when_no_dates(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.pull_date_range",
            return_value=(None, None),
        ):
            result = check_date_range(_mock_conn(), uuid4(), "Test Source")
        assert result.status == "warn"

    def test_warn_when_future_date(self) -> None:
        past = datetime(2024, 1, 1, tzinfo=timezone.utc)
        future = datetime.now(timezone.utc) + timedelta(days=30)
        with patch(
            "domains.campaign_finance.quality.checks.pull_date_range",
            return_value=(past, future),
        ):
            result = check_date_range(_mock_conn(), uuid4(), "Test Source")
        assert result.status == "warn"
        assert result.details["future_records"] is True

    def test_handles_naive_datetimes_when_computing_range_days(self) -> None:
        past = datetime(2024, 1, 1)
        recent = datetime(2024, 1, 3)
        with patch(
            "domains.campaign_finance.quality.checks.pull_date_range",
            return_value=(past, recent),
        ):
            result = check_date_range(_mock_conn(), uuid4(), "Test Source")

        assert result.status == "pass"
        assert result.metric_value == 2.0


class TestCheckSourceCount:
    """Tests for check_source_count — Schedule E source record count check."""

    def test_pass_when_records_exist(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.count_source_records",
            return_value=42,
        ):
            result = check_source_count(_mock_conn(), uuid4(), "Test Source")
        assert result.status == "pass"
        assert result.metric_value == 42.0
        assert result.name == "source_count"

    def test_fail_when_no_records(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.count_source_records",
            return_value=0,
        ):
            result = check_source_count(_mock_conn(), uuid4(), "Test Source")
        assert result.status == "fail"
        assert result.metric_value == 0.0

    def test_custom_check_name(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.count_source_records",
            return_value=10,
        ):
            result = check_source_count(
                _mock_conn(),
                uuid4(),
                "Test Source",
                check_name="schedule_e_source_count",
            )
        assert result.name == "schedule_e_source_count"

    def test_prefix_passed_to_count_source_records(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.count_source_records",
            return_value=5,
        ) as mock_count:
            check_source_count(
                _mock_conn(),
                uuid4(),
                "Test Source",
                source_key_prefix="schedule_e:",
            )
        assert mock_count.call_args.kwargs["source_key_prefix"] == "schedule_e:"

    def test_fail_when_below_min_expected(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.count_source_records",
            return_value=3,
        ):
            result = check_source_count(
                _mock_conn(),
                uuid4(),
                "Test Source",
                min_expected=10,
            )
        assert result.status == "fail"
        assert result.details["min_expected"] == 10


class TestCheckRawFieldNullRate:
    """Tests for check_raw_field_null_rate — Schedule E raw_fields null checks."""

    def test_pass_when_no_nulls(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.raw_field_null_rate",
            return_value=(0, 100),
        ):
            result = check_raw_field_null_rate(
                _mock_conn(),
                uuid4(),
                "Test Source",
                "sup_opp",
            )
        assert result.status == "pass"
        assert result.metric_value == 0.0
        assert result.name == "null_rate_sup_opp"

    def test_warn_when_below_threshold(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.raw_field_null_rate",
            return_value=(2, 100),
        ):
            result = check_raw_field_null_rate(
                _mock_conn(),
                uuid4(),
                "Test Source",
                "exp_amo",
                threshold=0.05,
            )
        assert result.status == "warn"
        assert result.metric_value == 0.02

    def test_fail_when_above_threshold(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.raw_field_null_rate",
            return_value=(20, 100),
        ):
            result = check_raw_field_null_rate(
                _mock_conn(),
                uuid4(),
                "Test Source",
                "can_id",
                threshold=0.05,
            )
        assert result.status == "fail"
        assert result.metric_value == 0.20

    def test_custom_check_name(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.raw_field_null_rate",
            return_value=(0, 50),
        ):
            result = check_raw_field_null_rate(
                _mock_conn(),
                uuid4(),
                "Test Source",
                "sup_opp",
                check_name="schedule_e_null_rate_sup_opp",
            )
        assert result.name == "schedule_e_null_rate_sup_opp"

    def test_prefix_passed_to_raw_field_null_rate(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.raw_field_null_rate",
            return_value=(0, 10),
        ) as mock_null:
            check_raw_field_null_rate(
                _mock_conn(),
                uuid4(),
                "Test Source",
                "sup_opp",
                source_key_prefix="schedule_e:",
            )
        assert mock_null.call_args.kwargs["source_key_prefix"] == "schedule_e:"

    def test_pass_when_empty_dataset(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.raw_field_null_rate",
            return_value=(0, 0),
        ):
            result = check_raw_field_null_rate(
                _mock_conn(),
                uuid4(),
                "Test Source",
                "sup_opp",
            )
        assert result.status == "pass"
        assert result.metric_value == 0.0

    def test_details_include_field_name_and_counts(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.raw_field_null_rate",
            return_value=(3, 100),
        ):
            result = check_raw_field_null_rate(
                _mock_conn(),
                uuid4(),
                "Test Source",
                "can_id",
            )
        assert result.details["field_name"] == "can_id"
        assert result.details["null_count"] == 3
        assert result.details["total_count"] == 100


class TestCheckDuplicateRecordsWithPrefix:
    """Tests for check_duplicate_records with source_key_prefix."""

    def test_prefix_passed_to_duplicate_hashes(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.duplicate_hashes",
            return_value=[],
        ) as mock_dup:
            check_duplicate_records(
                _mock_conn(),
                uuid4(),
                "Test Source",
                source_key_prefix="schedule_e:",
            )
        assert mock_dup.call_args.kwargs["source_key_prefix"] == "schedule_e:"

    def test_custom_check_name(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.duplicate_hashes",
            return_value=[],
        ):
            result = check_duplicate_records(
                _mock_conn(),
                uuid4(),
                "Test Source",
                check_name="schedule_e_duplicate_records",
            )
        assert result.name == "schedule_e_duplicate_records"

    def test_defaults_preserve_backward_compatibility(self) -> None:
        with patch(
            "domains.campaign_finance.quality.checks.duplicate_hashes",
            return_value=[],
        ) as mock_dup:
            result = check_duplicate_records(_mock_conn(), uuid4(), "Test Source")
        assert result.name == "duplicate_records"
        assert mock_dup.call_args.kwargs.get("source_key_prefix") is None


# ---------------------------------------------------------------------------
# Graph-edge population contract tests (Stage 1 — graph_edge_population_audit)
# ---------------------------------------------------------------------------


def _edge_family_counts(
    *,
    default_expected: int = 10,
    default_actual: int = 10,
    overrides: dict[str, tuple[int, int]] | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    expected = {family: default_expected for family in EXPECTED_EDGE_FAMILIES}
    actual = {family: default_actual for family in EXPECTED_EDGE_FAMILIES}
    for family, (family_expected, family_actual) in (overrides or {}).items():
        expected[family] = family_expected
        actual[family] = family_actual
    return expected, actual


def _run_graph_edge_presence_with_mocked_helpers(
    *,
    expected_counts: dict[str, int],
    actual_counts: dict[str, int],
    threshold: float | None = None,
) -> CheckResult:
    from domains.campaign_finance.quality.checks import check_graph_edge_presence

    conn = _mock_conn()
    data_source_id = uuid4()
    kwargs = {"threshold": threshold} if threshold is not None else {}
    with (
        patch(
            "domains.campaign_finance.quality.checks.expected_edge_denominators",
            return_value=expected_counts,
            create=True,
        ) as mock_expected_edge_denominators,
        patch(
            "domains.campaign_finance.quality.checks.count_graph_edges_by_family",
            return_value=actual_counts,
            create=True,
        ) as mock_count_graph_edges_by_family,
    ):
        result = check_graph_edge_presence(conn, data_source_id, "Test Source", **kwargs)
    mock_expected_edge_denominators.assert_called_once_with(conn, data_source_id)
    mock_count_graph_edges_by_family.assert_called_once_with(conn, data_source_id)
    return result


class TestCheckGraphEdgePresenceContract:
    """Lock the return contract for check_graph_edge_presence.

    These tests use delayed imports so they fail with ImportError (the
    expected missing-implementation failure) rather than collection errors.
    """

    def test_returns_check_result_instance(self) -> None:
        expected_counts, actual_counts = _edge_family_counts()
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        assert isinstance(result, CheckResult)

    def test_check_name_is_graph_edge_presence(self) -> None:
        expected_counts, actual_counts = _edge_family_counts(default_expected=5, default_actual=5)
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        assert result.name == "graph_edge_presence"

    def test_metric_name_is_edge_population_ratio(self) -> None:
        expected_counts, actual_counts = _edge_family_counts(default_expected=5, default_actual=5)
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        assert result.metric_name == "edge_population_ratio"

    def test_metric_value_is_minimum_ratio_across_families(self) -> None:
        expected_counts, actual_counts = _edge_family_counts(overrides={"SPENT_ON": (10, 8)})
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        assert result.metric_value == pytest.approx(0.8)

    def test_threshold_default_is_0_95(self) -> None:
        expected_counts, actual_counts = _edge_family_counts()
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        assert result.threshold == pytest.approx(0.95)

    def test_details_contain_per_family_counts(self) -> None:
        expected_counts, actual_counts = _edge_family_counts(
            overrides={
                "SPENT_ON": (5, 5),
                "SUPPORTS": (3, 3),
                "OPPOSES": (2, 2),
                "AFFILIATED_WITH": (7, 7),
                "FILED": (4, 4),
            }
        )
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        assert "edge_families" in result.details
        families = result.details["edge_families"]
        assert isinstance(families, dict)
        for fam in EXPECTED_EDGE_FAMILIES:
            assert fam in families
            entry = families[fam]
            assert "expected" in entry
            assert "actual" in entry
            assert "ratio" in entry

    def test_details_are_json_safe(self) -> None:
        import json

        expected_counts, actual_counts = _edge_family_counts()
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        serialized = json.dumps(result.details)
        parsed = json.loads(serialized)
        assert "edge_families" in parsed


class TestCheckGraphEdgePresenceThresholds:
    """Lock threshold behavior for check_graph_edge_presence."""

    def test_full_population_passes(self) -> None:
        expected_counts, actual_counts = _edge_family_counts()
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        assert result.status == "pass"
        assert result.metric_value == pytest.approx(1.0)

    def test_below_threshold_fails(self) -> None:
        expected_counts, actual_counts = _edge_family_counts(
            default_expected=100,
            default_actual=100,
            overrides={"CONTRIBUTED_TO": (100, 50)},
        )
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
            threshold=0.95,
        )
        assert result.status == "fail"
        assert result.metric_value == pytest.approx(0.5)

    def test_exactly_at_threshold_passes(self) -> None:
        expected_counts, actual_counts = _edge_family_counts(
            default_expected=100,
            default_actual=100,
            overrides={"SPENT_ON": (100, 95)},
        )
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
            threshold=0.95,
        )
        assert result.status == "pass"

    def test_zero_denominator_passes(self) -> None:
        expected_counts, actual_counts = _edge_family_counts(overrides={"OPPOSES": (0, 0)})
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        assert result.status == "pass"

    def test_all_zero_denominators_passes(self) -> None:
        expected_counts, actual_counts = _edge_family_counts(default_expected=0, default_actual=0)
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
        )
        assert result.status == "pass"

    def test_custom_threshold(self) -> None:
        expected_counts, actual_counts = _edge_family_counts(
            default_expected=100,
            default_actual=100,
            overrides={"FILED": (100, 80)},
        )
        result = _run_graph_edge_presence_with_mocked_helpers(
            expected_counts=expected_counts,
            actual_counts=actual_counts,
            threshold=0.75,
        )
        assert result.status == "pass"
        assert result.metric_value == pytest.approx(0.8)
