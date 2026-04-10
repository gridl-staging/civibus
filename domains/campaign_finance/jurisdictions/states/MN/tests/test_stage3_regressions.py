from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import (
    assert_files_exist,
    nested_keys,
    read,
    source_block_by_name,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
MN_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "MN"
CONFIG_PATH = MN_DIR / "config.yaml"
README_PATH = MN_DIR / "README.md"
LAWS_PATH = MN_DIR / "laws.md"
SEMANTICS_PATH = MN_DIR / "data_semantics.md"
FIXTURE_DIR = MN_DIR / "scraper" / "test_fixtures"
CONTRIBUTION_FIXTURE_PATH = FIXTURE_DIR / "sample_contributions.csv"
EXPENDITURE_FIXTURE_PATH = FIXTURE_DIR / "sample_expenditures.csv"
_SOURCE_NAME_BY_FIXTURE_PATH = {
    CONTRIBUTION_FIXTURE_PATH: "MN CFB Contributions (All)",
    EXPENDITURE_FIXTURE_PATH: "MN CFB Expenditures (All)",
}


def _csv_header(path: Path) -> tuple[str, ...]:
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    return tuple(first_line.split(","))


def _config_header_for_source(source_name: str) -> tuple[str, ...]:
    source_block = source_block_by_name(read(CONFIG_PATH), source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_stage3_files_exist() -> None:
    assert_files_exist(
        CONFIG_PATH,
        README_PATH,
        LAWS_PATH,
        SEMANTICS_PATH,
        CONTRIBUTION_FIXTURE_PATH,
        EXPENDITURE_FIXTURE_PATH,
    )


@pytest.mark.parametrize("fixture_path", (CONTRIBUTION_FIXTURE_PATH, EXPENDITURE_FIXTURE_PATH))
def test_fixture_header_matches_config_order(fixture_path: Path) -> None:
    assert _csv_header(fixture_path) == _config_header_for_source(_SOURCE_NAME_BY_FIXTURE_PATH[fixture_path])


def test_docs_lock_quarterly_direct_download_contract_and_source_boundaries() -> None:
    readme_text = read(README_PATH)
    readme_text_lower = readme_text.lower()
    semantics_text = read(SEMANTICS_PATH)
    semantics_text_lower = semantics_text.lower()

    assert "canonical ingest contract" in readme_text_lower
    assert "quarterly" in readme_text_lower
    assert "?download=" in readme_text
    assert "local campaign finance reports" in readme_text_lower
    assert "independent expenditures remain documented in config/docs only" in readme_text_lower
    assert "stage 3 loader ingests contributions and expenditures" in readme_text_lower

    assert "/reports/#/" in readme_text
    assert "/reports/api/" in readme_text
    assert "supplemental evidence surfaces only" in readme_text_lower
    assert "not required for canonical ingest" in readme_text_lower

    assert "/reports/#/" in semantics_text
    assert "/reports/api/" in semantics_text
    assert "supplemental evidence surfaces only" in semantics_text_lower
    assert "not required for canonical ingest" in semantics_text_lower
    assert "not a replacement freshness source" in semantics_text_lower
    assert "stage 5 freshness source decision" in semantics_text_lower
    assert "stage 10 freshness source decision" not in semantics_text_lower
    assert "stage 3 loader ingests contributions and expenditures" in semantics_text_lower
    assert "independent expenditures remain documented in config/docs only" in semantics_text_lower
    assert "for later config/readme update" not in semantics_text_lower
