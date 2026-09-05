from __future__ import annotations

import csv
from io import StringIO
import os
from pathlib import Path

import pytest

from domains.campaign_finance.coverage.generate_master_csv import (
    OUTPUT_PATH,
    _audit_method,
    _get_portal_url,
    assert_output_is_fresh,
    render_csv_text,
    stale_input_paths,
)


def test_get_portal_url_uses_current_illinois_bulk_download_page() -> None:
    row = {
        "jurisdiction_code": "IL",
        "jurisdiction_type": "state",
    }

    assert _get_portal_url(row) == "https://elections.il.gov/CampaignDisclosure/DownloadCDDataFiles.aspx"


def test_get_portal_url_reads_municipal_portal_url_for_independent_cities() -> None:
    row = {
        "jurisdiction_code": "CA_SAN_FRANCISCO",
        "jurisdiction_type": "municipality",
        "parent_jurisdiction_code": "CA",
        "municipal_audit_decision": "independent_target",
        "municipal_portal_url": "https://sfethics.org/disclosures/campaign-finance-disclosure",
    }
    assert _get_portal_url(row) == "https://sfethics.org/disclosures/campaign-finance-disclosure"


def test_get_portal_url_falls_back_to_needs_investigation_when_no_municipal_url() -> None:
    row = {
        "jurisdiction_code": "CA_SAN_FRANCISCO",
        "jurisdiction_type": "municipality",
        "parent_jurisdiction_code": "CA",
        "municipal_audit_decision": "independent_target",
    }
    assert _get_portal_url(row) == "needs_investigation"


def test_get_portal_url_covered_by_parent_still_shows_parent_reference() -> None:
    row = {
        "jurisdiction_code": "IL_CHICAGO",
        "jurisdiction_type": "municipality",
        "parent_jurisdiction_code": "IL",
        "municipal_audit_decision": "covered_by_parent",
    }
    assert _get_portal_url(row) == "(see IL)"


def test_audit_method_returns_browser_verified_for_browser_evidence() -> None:
    row = {
        "jurisdiction_code": "CA_SAN_FRANCISCO",
        "jurisdiction_type": "municipality",
        "runner_wired": False,
        "tier": "deferred/blocked",
        "evidence_summary": "Browser-verified city portal research (2026-03-31): SF Ethics Commission",
        "evidence_date": "2026-03-31",
    }
    assert _audit_method(row) == "browser_verified"


def test_tracked_jurisdiction_master_csv_matches_generator() -> None:
    assert OUTPUT_PATH.read_bytes() == render_csv_text().encode()


def test_master_csv_projects_typed_authority_without_flattening_overlaps() -> None:
    rows = {row["jurisdiction_code"]: row for row in csv.DictReader(StringIO(render_csv_text()))}

    assert rows["NY_NEW_YORK"]["authority_relation"] == "partitioned_overlapping"
    assert rows["NY_NEW_YORK"]["filing_authorities"] == "state/NY;municipality/NY_NEW_YORK"
    assert rows["NY_NEW_YORK"]["aggregation_disposition"] == "refuse_combination"
    assert rows["WA_SEATTLE"]["authority_relation"] == "partitioned_overlapping"
    assert rows["WA_SEATTLE"]["filing_authorities"] == (
        "state/WA;named_other/WA_SEATTLE_CITY_CLERK (Seattle City Clerk);"
        "named_other/WA_SEEC (Seattle Ethics and Elections Commission)"
    )
    assert rows["WA_SEATTLE"]["aggregation_disposition"] == "refuse_combination"
    assert rows["WA_SEATTLE"]["municipal_compatibility_decision"] == "covered_by_parent"


def test_output_is_stale_when_owned_input_is_newer(tmp_path: Path) -> None:
    output_path = tmp_path / "jurisdiction-master.csv"
    older_input_path = tmp_path / "older_input.txt"
    newer_input_path = tmp_path / "newer_input.txt"

    output_path.write_text("generated")
    older_input_path.write_text("older")
    newer_input_path.write_text("newer")

    older_timestamp = 100
    output_timestamp = 200
    newer_timestamp = 300
    os.utime(older_input_path, (older_timestamp, older_timestamp))
    os.utime(output_path, (output_timestamp, output_timestamp))
    os.utime(newer_input_path, (newer_timestamp, newer_timestamp))

    stale_inputs = stale_input_paths(
        output_path=output_path,
        input_paths=(older_input_path, newer_input_path),
    )

    assert stale_inputs == (newer_input_path,)
    with pytest.raises(RuntimeError) as exc_info:
        assert_output_is_fresh(
            output_path=output_path,
            input_paths=(older_input_path, newer_input_path),
        )

    message = str(exc_info.value)
    assert str(output_path) in message
    assert str(newer_input_path) in message
    assert str(older_input_path) not in message


def test_output_is_stale_when_generated_csv_is_missing(tmp_path: Path) -> None:
    output_path = tmp_path / "jurisdiction-master.csv"
    first_input_path = tmp_path / "first_input.txt"
    second_input_path = tmp_path / "second_input.txt"
    first_input_path.write_text("first")
    second_input_path.write_text("second")

    input_paths = (first_input_path, second_input_path)

    assert stale_input_paths(output_path=output_path, input_paths=input_paths) == input_paths
    with pytest.raises(RuntimeError) as exc_info:
        assert_output_is_fresh(output_path=output_path, input_paths=input_paths)

    message = str(exc_info.value)
    assert str(output_path) in message
    assert str(first_input_path) in message
    assert str(second_input_path) in message
