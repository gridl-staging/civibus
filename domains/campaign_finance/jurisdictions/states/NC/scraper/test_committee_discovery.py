"""Tests for NC CFOrgLkup committee discovery parsing and dedupe orchestration."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from domains.campaign_finance.jurisdictions.states.NC.scraper.committee_discovery import (
    EXPECTED_STATEWIDE_COMMITTEE_COUNT,
    build_committee_search_buckets,
    crawl_committee_registry,
    parse_result_rows,
)


def _html_with_data(rows_json: str) -> str:
    return (
        "<html><head><script>\\n"
        f"var data = {rows_json};\\r\\n"
        "</script></head><body></body></html>"
    )


def test_parse_result_rows_extracts_expected_fields_and_dedupes_duplicate_rows() -> None:
    html = _html_with_data(
        """[
        {
            \"OrgName\": \"01ST CONG DIST BLACK LEADERSHIP CAUCUS\",
            \"SBoEID\": \"STA-C3672N-C-001\",
            \"OldID\": \"7940000\",
            \"CandName\": \"CIVIC\",
            \"StatusDesc\": \"CLOSED\",
            \"OrgGroupID\": 3970,
            \"Link\": null
        },
        {
            \"OrgName\": \"01ST CONG DIST BLACK LEADERSHIP CAUCUS\",
            \"SBoEID\": \"STA-C3672N-C-001\",
            \"OldID\": \"7940000\",
            \"CandName\": \"CIVIC\",
            \"StatusDesc\": \"CLOSED\",
            \"OrgGroupID\": 3970,
            \"Link\": null
        }
    ]"""
    )

    rows = parse_result_rows(html)

    assert len(rows) == 1
    row = rows[0]
    assert row.org_group_id == 3970
    assert row.sboe_id == "STA-C3672N-C-001"
    assert row.committee_name == "01ST CONG DIST BLACK LEADERSHIP CAUCUS"
    assert row.status_desc == "CLOSED"
    assert row.old_id == "7940000"
    assert row.candidate_name == "CIVIC"


def test_crawl_committee_registry_dedupes_same_org_group_id_across_buckets() -> None:
    bucket_to_html = {
        "B": _html_with_data(
            """[
            {
                \"OrgName\": \"BETA COMMITTEE\",
                \"SBoEID\": \"STA-BETA-C-001\",
                \"OldID\": \"111\",
                \"CandName\": \"CIVIC\",
                \"StatusDesc\": \"ACTIVE (EXEMPT)\",
                \"OrgGroupID\": 111,
                \"Link\": null
            }
        ]"""
        ),
        "BA": _html_with_data(
            """[
            {
                \"OrgName\": \"BETA COMMITTEE\",
                \"SBoEID\": \"STA-BETA-C-001\",
                \"OldID\": \"111\",
                \"CandName\": \"CIVIC\",
                \"StatusDesc\": \"ACTIVE (EXEMPT)\",
                \"OrgGroupID\": 111,
                \"Link\": null
            },
            {
                \"OrgName\": \"BAKER COMMITTEE\",
                \"SBoEID\": \"STA-BAKER-C-001\",
                \"OldID\": \"222\",
                \"CandName\": \"JANE DOE\",
                \"StatusDesc\": \"ACTIVE (NON-EXEMPT)\",
                \"OrgGroupID\": 222,
                \"Link\": null
            }
        ]"""
        ),
    }

    def _fetch_bucket_html(bucket: str) -> str:
        return bucket_to_html[bucket]

    discovered = crawl_committee_registry(
        fetch_bucket_html=_fetch_bucket_html,
        buckets=("B", "BA"),
        sleep_seconds=0.0,
    )

    assert set(discovered) == {111, 222}
    assert discovered[111].committee_name == "BETA COMMITTEE"
    assert discovered[222].committee_name == "BAKER COMMITTEE"


def test_parse_result_rows_rejects_unexpected_status_value_with_validation_error() -> None:
    invalid_html = _html_with_data(
        """[
        {
            \"OrgName\": \"BAD STATUS COMMITTEE\",
            \"SBoEID\": \"STA-BAD-C-001\",
            \"OldID\": \"333\",
            \"CandName\": \"CIVIC\",
            \"StatusDesc\": \"DISSOLVED\",
            \"OrgGroupID\": 333,
            \"Link\": null
        }
    ]"""
    )

    with pytest.raises(ValidationError):
        parse_result_rows(invalid_html)


def test_build_committee_search_buckets_matches_stage1_recipe() -> None:
    buckets = build_committee_search_buckets()

    assert len(buckets) == 186
    assert "B" in buckets
    assert "AA" in buckets
    assert "RZ" in buckets
    assert "A" not in buckets
    assert "C" not in buckets
    assert "E" not in buckets
    assert "N" not in buckets
    assert "O" not in buckets
    assert "R" not in buckets
    assert "0" in buckets
    assert "9" in buckets


def test_expected_statewide_committee_count_matches_stage1_contract() -> None:
    assert EXPECTED_STATEWIDE_COMMITTEE_COUNT == 13612
