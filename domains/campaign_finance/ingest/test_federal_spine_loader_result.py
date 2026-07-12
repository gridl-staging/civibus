"""Unit tests for federal spine loader result contracts."""

from __future__ import annotations

from domains.campaign_finance.ingest.federal_spine_loader import SpineLoadResult


def test_spine_load_result_exposes_refresh_runner_count_contract() -> None:
    """Bucketed spine counters must still look like a refresh-loader result."""
    result = SpineLoadResult()
    result.house.inserted = 2
    result.house.converged_candidates = 3
    result.senate.skipped = 1
    result.delegate.errors = 4
    result.president.inserted = 1
    result.vice_president.converged_candidates = 1

    assert result.inserted == 3
    assert result.skipped == 1
    assert result.quarantined == 0
    assert result.superseded == 0
    assert result.errors == 4
    assert result.converged_candidates == 4
