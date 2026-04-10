from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import (
    assert_files_exist,
    nested_keys,
    read,
    source_block_by_name,
)
from domains.campaign_finance.jurisdictions.states.WA.scraper import cli as wa_cli
from domains.campaign_finance.jurisdictions.states.WA.scraper import load as wa_load

REPO_ROOT = Path(__file__).resolve().parents[6]
WA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "WA"
CONFIG_PATH = WA_DIR / "config.yaml"
README_PATH = WA_DIR / "README.md"
LAWS_PATH = WA_DIR / "laws.md"
SEMANTICS_PATH = WA_DIR / "data_semantics.md"
FIXTURE_DIR = WA_DIR / "scraper" / "test_fixtures"
CONTRIBUTION_FIXTURE_PATH = FIXTURE_DIR / "sample_contributions.csv"
EXPENDITURE_FIXTURE_PATH = FIXTURE_DIR / "sample_expenditures.csv"
INDEPENDENT_EXPENDITURE_FIXTURE_PATH = FIXTURE_DIR / "sample_independent_expenditures.csv"
LOAN_FIXTURE_PATH = FIXTURE_DIR / "sample_loans.csv"


def _csv_header(path: Path) -> tuple[str, ...]:
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    return tuple(first_line.split(","))


def _expected_header(source_name: str) -> tuple[str, ...]:
    source_block = source_block_by_name(read(CONFIG_PATH), source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_stage4_files_exist() -> None:
    assert_files_exist(
        CONFIG_PATH,
        README_PATH,
        LAWS_PATH,
        SEMANTICS_PATH,
        CONTRIBUTION_FIXTURE_PATH,
        EXPENDITURE_FIXTURE_PATH,
        INDEPENDENT_EXPENDITURE_FIXTURE_PATH,
        LOAN_FIXTURE_PATH,
    )


@pytest.mark.parametrize(
    ("fixture_path", "source_name"),
    [
        (CONTRIBUTION_FIXTURE_PATH, "WA PDC Contributions"),
        (EXPENDITURE_FIXTURE_PATH, "WA PDC Expenditures"),
        (INDEPENDENT_EXPENDITURE_FIXTURE_PATH, "WA PDC Independent Expenditures"),
        (LOAN_FIXTURE_PATH, "WA PDC Loans"),
    ],
)
def test_fixture_header_matches_config_order(fixture_path: Path, source_name: str) -> None:
    assert _csv_header(fixture_path) == _expected_header(source_name)


def test_wa_ingest_surface_includes_independent_expenditures() -> None:
    assert wa_cli._SUPPORTED_DATA_TYPES == ("contributions", "expenditures", "independent_expenditures", "loans")
    assert hasattr(wa_load, "load_wa_contributions_with_filings")
    assert hasattr(wa_load, "load_wa_expenditures_with_filings")
    assert hasattr(wa_load, "load_wa_independent_expenditures_with_filings")
    assert hasattr(wa_load, "load_wa_loans_with_filings")


def test_wa_docs_include_independent_expenditure_ingest_scope() -> None:
    config_text = read(CONFIG_PATH)
    readme_text = read(README_PATH)
    semantics_text = read(SEMANTICS_PATH)

    source_block_by_name(config_text, "WA PDC Independent Expenditures")

    assert "| WA PDC Independent Expenditures | independent_expenditures | Ingest-supported |" in readme_text
    assert "source-available in config.yaml but intentionally excluded from the current ingest path" not in readme_text
    assert "Dataset IDs are authoritative in config.yaml." in readme_text
    assert "Loans dataset drift note: g6x6-jd8p -> d2ig-r3q4." in readme_text

    assert (
        "For ingest scope and source availability, use README.md and config.yaml as the truth surfaces."
        in semantics_text
    )
