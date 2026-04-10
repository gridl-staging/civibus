from __future__ import annotations

from pathlib import Path

import pytest

from _test_helpers import (
    assert_files_exist,
    extract_named_block,
    nested_keys,
    read,
    scalar_value,
    shared_data_source_scalar,
    source_block_by_name,
)
from domains.campaign_finance.jurisdictions.states.CO.scraper import cli as co_cli
from domains.campaign_finance.jurisdictions.states.CO.scraper import load as co_load
from domains.campaign_finance.jurisdictions.states.CO.scraper import parse as co_parse

REPO_ROOT = Path(__file__).resolve().parents[6]
CO_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "CO"
CONFIG_PATH = CO_DIR / "config.yaml"
README_PATH = CO_DIR / "README.md"
LAWS_PATH = CO_DIR / "laws.md"
SEMANTICS_PATH = CO_DIR / "data_semantics.md"


def test_stage4_files_exist():
    assert_files_exist(CONFIG_PATH, README_PATH, LAWS_PATH, SEMANTICS_PATH)


def test_update_frequency_regression_is_weekly_for_all_sources():
    config_text = read(CONFIG_PATH)
    assert config_text.count('update_frequency: "weekly"') == 3
    assert 'update_frequency: "quarterly"' not in config_text


def test_field_mapping_counts_match_documented_stage4_shapes():
    config_text = read(CONFIG_PATH)
    expected_mapping_counts = {
        "TRACER Bulk Download — Contributions": 29,
        "TRACER Bulk Download — Expenditures": 28,
        "TRACER Bulk Download — Loans": 26,
    }

    for source_name, expected_count in expected_mapping_counts.items():
        source_block = source_block_by_name(config_text, source_name)
        assert len(nested_keys(source_block, "field_mappings")) == expected_count


def test_malformed_row_documentation_is_present_in_config_and_semantics():
    config_text = read(CONFIG_PATH)
    semantics_text = read(SEMANTICS_PATH)

    assert "malformed quoted donor names in at least 14 rows (26 columns instead of 29)" in config_text
    assert "Row shape validation required" in semantics_text
    assert "29 columns in contributions, 28 in expenditures, and 26 in loans" in semantics_text


def test_home_rule_caveat_is_present_in_config_and_laws():
    config_text = read(CONFIG_PATH)
    laws_text = read(LAWS_PATH)

    assert "Home-rule counties and municipalities may adopt their own contribution limits" in config_text
    assert "**Home-rule exception**" in laws_text
    assert "Home Rule counties or municipalities may have their own contribution limits." in laws_text


def test_laws_citation_regression_uses_resolving_crs_source():
    laws_text = read(LAWS_PATH)
    assert "https://olls.info/crs/crs2025-title-01.htm" in laws_text
    assert "https://colorado.public.law/statutes/crs_1-45-103-7" not in laws_text


def test_readme_documents_weekly_frequency_and_mid_quarter_refresh_evidence():
    config_text = read(CONFIG_PATH)
    readme_text = read(README_PATH)
    source_verified = shared_data_source_scalar(config_text, "last_verified_working")
    laws_verified = scalar_value(extract_named_block(config_text, "laws"), "last_verified")

    assert "**Update frequency**: Weekly" in readme_text
    assert "March 10–12, mid-quarter" in readme_text
    assert f"- Source access verified: {source_verified}" in readme_text
    assert f"- Laws research verified: {laws_verified}" in readme_text


def test_co_loans_source_is_documented_but_not_ingest_supported() -> None:
    with pytest.raises(SystemExit, match="2"):
        co_cli._build_argument_parser().parse_args(
            ["--year", "2026", "--data-type", "loans", "--path", "/tmp/loans.csv"]
        )

    assert "loans" not in co_load._CO_DATA_SOURCE_NAME_BY_TYPE

    with pytest.raises(ValueError, match="Unsupported CO data_type: loans"):
        co_load.ensure_co_data_source(object(), data_type="loans")

    assert not hasattr(co_parse, "parse_loans")


def test_co_docs_state_loans_source_is_available_but_ingest_is_unsupported() -> None:
    config_text = read(CONFIG_PATH)
    readme_text = read(README_PATH)

    assert "Loans bulk file is source-available but the current CO ingest path does not load loans" in config_text
    assert (
        "Current ingest support: contributions and expenditures are ingest-supported; loans remain source-available only."
        in readme_text
    )
