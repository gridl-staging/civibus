"""Tests for NY CLI module."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions.states.NY.scraper import _load_ny_config
from domains.campaign_finance.jurisdictions.states.NY.scraper import cli
from domains.campaign_finance.jurisdictions.states.NY.scraper.cli import (
    _SUPPORTED_DATA_TYPES,
    _validate_data_type,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_IE_PATH = _FIXTURE_DIR / "sample_ie.csv"


class TestNYCLIContract:
    """Verify CLI contract for runner integration."""

    def test_supported_data_types_include_independent_expenditures(self) -> None:
        assert _SUPPORTED_DATA_TYPES == ("contributions", "expenditures", "independent_expenditures")

    def test_supported_data_types_are_subset_of_config(self) -> None:
        config = _load_ny_config()
        config_types = {
            transaction_type.strip().lower()
            for data_source in config.data_sources
            for transaction_type in data_source.coverage.transaction_types
        }
        assert set(_SUPPORTED_DATA_TYPES) <= config_types

    def test_validate_data_type_accepts_valid_types(self) -> None:
        assert _validate_data_type("contributions") == "contributions"
        assert _validate_data_type("expenditures") == "expenditures"
        assert _validate_data_type("independent_expenditures") == "independent_expenditures"

    def test_validate_data_type_rejects_invalid_type(self) -> None:
        with pytest.raises(ValueError, match="Unsupported NY data type"):
            _validate_data_type("loans")

    def test_count_rows_uses_parser_dispatch_table_for_independent_expenditures(self, monkeypatch) -> None:
        contribution_parser = MagicMock(side_effect=AssertionError("contributions parser should not be used"))
        expenditure_parser = MagicMock(side_effect=AssertionError("expenditures parser should not be used"))
        ie_parser = MagicMock(return_value=[{"trans_number": "ie-1"}, {"trans_number": "ie-2"}])
        monkeypatch.setattr(
            cli,
            "_NY_PARSER_FN",
            {
                "contributions": contribution_parser,
                "expenditures": expenditure_parser,
                "independent_expenditures": ie_parser,
            },
        )

        assert cli._count_rows(_SAMPLE_IE_PATH, data_type="independent_expenditures", limit=None) == 2
        ie_parser.assert_called_once_with(_SAMPLE_IE_PATH)

    def test_count_rows_keeps_existing_contributions_behavior(self) -> None:
        assert cli._count_rows(_SAMPLE_CONTRIBUTIONS_PATH, data_type="contributions", limit=1) == 1

    def test_load_path_delegates_to_internal_loader_with_data_type(self, monkeypatch) -> None:
        internal_loader = MagicMock(return_value=object())
        monkeypatch.setattr(cli, "_load_ny_with_filings", internal_loader)

        result = cli._load_path(
            MagicMock(),
            _SAMPLE_IE_PATH,
            data_type="independent_expenditures",
            limit=9,
        )

        assert result is internal_loader.return_value
        internal_loader.assert_called_once()
        _, kwargs = internal_loader.call_args
        assert kwargs["data_type"] == "independent_expenditures"
        assert kwargs["limit"] == 9

    def test_resolve_input_path_passes_limit_to_downloader(self, monkeypatch, tmp_path: Path) -> None:
        expected_path = tmp_path / "ny_contributions.csv"
        expected_path.write_text("header\n", encoding="utf-8")
        download_mock = MagicMock(return_value=expected_path)
        monkeypatch.setattr(cli, "download_ny_csv", download_mock)
        args = argparse.Namespace(
            path=None,
            download=True,
            data_type="contributions",
            limit=77,
            dry_run=True,
        )

        resolved_path, temp_dir = cli._resolve_input_path(args, download_limit=args.limit)

        assert resolved_path == expected_path
        assert temp_dir is not None
        download_mock.assert_called_once()
        _, kwargs = download_mock.call_args
        assert kwargs["limit"] == 77
        temp_dir.cleanup()

    def test_main_dry_run_prints_explicit_parsed_row_count_field(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(cli, "_resolve_input_path", MagicMock(return_value=(_SAMPLE_IE_PATH, None)))
        monkeypatch.setattr(cli, "_count_rows", MagicMock(return_value=12))

        exit_code = cli.main(
            [
                "--download",
                "--data-type",
                "independent_expenditures",
                "--dry-run",
                "--limit",
                "12",
            ]
        )

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "parsed_row_count=12" in out
