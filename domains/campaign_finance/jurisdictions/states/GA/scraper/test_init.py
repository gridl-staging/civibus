from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

import domains.campaign_finance.jurisdictions.states.GA.scraper as ga_scraper
from _test_helpers import csv_headers, nested_keys, read, source_block_by_name

REPO_ROOT = Path(__file__).resolve().parents[6]
GA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "GA"
CONFIG_PATH = GA_DIR / "config.yaml"
CONTRIBUTION_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "contribution_export_sample.xls"
EXPENDITURE_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "expenditure_export_sample.xls"
_CONTRIBUTION_SOURCE_NAME = "Georgia Campaign Portal — Contributions Search Export"
_EXPENDITURE_SOURCE_NAME = "Georgia Campaign Portal — Expenditures Search Export"


def _expenditure_headers() -> list[str]:
    fixture_text = read(EXPENDITURE_FIXTURE_PATH)
    first_row_match = re.search(r"<tr[^>]*>(.*?)</tr>", fixture_text, re.DOTALL | re.IGNORECASE)
    if first_row_match is None:
        raise AssertionError("expected HTML header row in expenditure fixture")

    return re.findall(r"<td[^>]*>([^<]+)</td>", first_row_match.group(1), re.IGNORECASE)


def _clear_loader_caches() -> None:
    ga_scraper._load_ga_data_source_blocks.cache_clear()
    ga_scraper._load_columns.cache_clear()
    load_by_transaction_type = getattr(ga_scraper, "_load_columns_for_transaction_type", None)
    if load_by_transaction_type is not None:
        load_by_transaction_type.cache_clear()
    load_date_selectors_by_transaction_type = getattr(ga_scraper, "_load_date_selectors_for_transaction_type", None)
    if load_date_selectors_by_transaction_type is not None:
        load_date_selectors_by_transaction_type.cache_clear()


def _data_source_by_transaction_type(config: dict[str, Any], transaction_type: str) -> dict[str, Any]:
    for data_source in config["data_sources"]:
        if transaction_type in data_source["coverage"]["transaction_types"]:
            return data_source
    raise AssertionError(f"expected a data source covering transaction type {transaction_type!r}")


def test_contribution_columns_derive_from_config_and_match_fixture_header() -> None:
    config_text = read(CONFIG_PATH)
    contribution_source = source_block_by_name(config_text, _CONTRIBUTION_SOURCE_NAME)

    assert ga_scraper.CONTRIBUTION_COLUMNS == tuple(nested_keys(contribution_source, "field_mappings"))
    assert ga_scraper.CONTRIBUTION_COLUMNS == tuple(csv_headers(CONTRIBUTION_FIXTURE_PATH))


def test_expenditure_columns_derive_from_config_and_match_fixture_header() -> None:
    config_text = read(CONFIG_PATH)
    expenditure_source = source_block_by_name(config_text, _EXPENDITURE_SOURCE_NAME)

    assert ga_scraper.EXPENDITURE_COLUMNS == tuple(nested_keys(expenditure_source, "field_mappings"))
    assert ga_scraper.EXPENDITURE_COLUMNS == tuple(_expenditure_headers())


def test_load_columns_ignores_valid_yaml_comment_lines_inside_field_mappings(tmp_path: Path, monkeypatch) -> None:
    config_text = read(CONFIG_PATH)
    commented_config, replacements = re.subn(
        r"(?m)^(?P<indent>\s*)field_mappings:\n",
        lambda match: (
            f"{match.group(0)}"
            f"{match.group('indent')}  # Comments inside field_mappings are valid YAML and not column names.\n"
        ),
        config_text,
        count=1,
    )
    assert replacements == 1, "expected to inject a comment into exactly one field_mappings block"
    temporary_config_path = tmp_path / "config.yaml"
    temporary_config_path.write_text(commented_config, encoding="utf-8")

    _clear_loader_caches()
    monkeypatch.setattr(ga_scraper, "_CONFIG_PATH", temporary_config_path)
    try:
        assert ga_scraper._load_columns(_CONTRIBUTION_SOURCE_NAME) == ga_scraper.CONTRIBUTION_COLUMNS
    finally:
        _clear_loader_caches()


def test_load_columns_for_transaction_type_uses_config_metadata_not_source_names(tmp_path: Path, monkeypatch) -> None:
    config = yaml.safe_load(read(CONFIG_PATH))
    contribution_source = _data_source_by_transaction_type(config, "contributions")
    expenditure_source = _data_source_by_transaction_type(config, "expenditures")
    independent_expenditure_source = _data_source_by_transaction_type(config, "independent_expenditures")
    contribution_source["name"] = "Temporary Contribution Export Name"
    contribution_source["field_mappings"]["TemporaryContributionTestColumn"] = "transaction.test_contribution"
    expenditure_source["name"] = "Temporary Expenditure Export Name"
    expenditure_source["field_mappings"]["TemporaryExpenditureTestColumn"] = "transaction.test_expenditure"
    independent_expenditure_source["name"] = "Temporary Independent Expenditure Export Name"
    independent_expenditure_source["field_mappings"]["TemporaryIndependentExpenditureTestColumn"] = (
        "transaction.test_independent_expenditure"
    )
    expected_contribution_columns = tuple(contribution_source["field_mappings"].keys())
    expected_expenditure_columns = tuple(expenditure_source["field_mappings"].keys())
    expected_independent_expenditure_columns = tuple(independent_expenditure_source["field_mappings"].keys())
    rewritten_config = yaml.safe_dump(
        config,
        sort_keys=False,
        allow_unicode=True,
    )
    temporary_config_path = tmp_path / "config.yaml"
    temporary_config_path.write_text(rewritten_config, encoding="utf-8")

    load_by_transaction_type = getattr(ga_scraper, "_load_columns_for_transaction_type", None)
    assert load_by_transaction_type is not None, "expected transaction-type based column loader"

    _clear_loader_caches()
    monkeypatch.setattr(ga_scraper, "_CONFIG_PATH", temporary_config_path)
    try:
        assert load_by_transaction_type("contributions") == expected_contribution_columns
        assert load_by_transaction_type("expenditures") == expected_expenditure_columns
        assert load_by_transaction_type("independent_expenditures") == expected_independent_expenditure_columns
    finally:
        _clear_loader_caches()


def test_load_columns_for_transaction_type_rejects_ambiguous_config(tmp_path: Path, monkeypatch) -> None:
    config = yaml.safe_load(read(CONFIG_PATH))
    independent_expenditure_source = _data_source_by_transaction_type(config, "independent_expenditures")
    independent_expenditure_source["coverage"]["transaction_types"].append("expenditures")
    temporary_config_path = tmp_path / "config.yaml"
    temporary_config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    load_by_transaction_type = getattr(ga_scraper, "_load_columns_for_transaction_type", None)
    assert load_by_transaction_type is not None, "expected transaction-type based column loader"

    _clear_loader_caches()
    monkeypatch.setattr(ga_scraper, "_CONFIG_PATH", temporary_config_path)
    try:
        with pytest.raises(
            RuntimeError,
            match=r"multiple data_sources with transaction type 'expenditures'",
        ):
            load_by_transaction_type("expenditures")
    finally:
        _clear_loader_caches()
