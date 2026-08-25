from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from domains.campaign_finance.ingest import bulk_loader, bulk_stage4_loader
from test_support.line_budget import HARD_LINE_LIMIT, count_lines


REPO_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.unit


def test_bulk_loader_module_stays_within_line_budget() -> None:
    bulk_loader_path = REPO_ROOT / "domains" / "campaign_finance" / "ingest" / "bulk_loader.py"

    assert count_lines(bulk_loader_path) <= HARD_LINE_LIMIT


def test_nc_load_module_stays_within_line_budget() -> None:
    nc_load_path = (
        REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "NC" / "scraper" / "load.py"
    )

    assert count_lines(nc_load_path) <= 1200


def test_in_load_module_stays_within_line_budget() -> None:
    in_load_path = (
        REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "IN" / "scraper" / "load.py"
    )

    assert count_lines(in_load_path) <= HARD_LINE_LIMIT


def test_stage4_loader_signatures_stay_within_six_parameters() -> None:
    expected_functions = {
        "load_contributions": bulk_loader.load_contributions,
        "load_committee_transactions": bulk_loader.load_committee_transactions,
        "_load_stage4_contributions": bulk_stage4_loader._load_stage4_contributions,
    }

    for function_name, function in expected_functions.items():
        assert len(inspect.signature(function).parameters) <= 6, function_name
