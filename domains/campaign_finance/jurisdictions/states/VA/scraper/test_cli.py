"""Tests for Virginia CLI entry point.

Tests argument parsing, dry-run mode against real fixtures,
and validation of supported data types.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.VA.scraper import cli

# Fixture directory lives next to this test file
_FIXTURE_DIR = Path(__file__).resolve().parent / "test_fixtures"


def test_build_argument_parser_parses_path_input() -> None:
    """Parser should accept --path with --data-type."""
    args = cli._build_argument_parser().parse_args(
        [
            "--path",
            "/tmp/sample.csv",
            "--data-type",
            "contributions",
        ]
    )

    assert args.path == Path("/tmp/sample.csv")
    assert args.download is False
    assert args.data_type == "contributions"
    assert args.year_month is None
    assert args.limit is None
    assert args.dry_run is False


def test_build_argument_parser_parses_download_input() -> None:
    """Parser should accept --download with --year-month."""
    args = cli._build_argument_parser().parse_args(
        [
            "--download",
            "--data-type",
            "contributions",
            "--year-month",
            "2026_03",
        ]
    )

    assert args.download is True
    assert args.data_type == "contributions"
    assert args.year_month == "2026_03"


def test_build_argument_parser_accepts_expenditures() -> None:
    """Parser should accept expenditures as a data type."""
    args = cli._build_argument_parser().parse_args(
        [
            "--path",
            "/tmp/sample.csv",
            "--data-type",
            "expenditures",
        ]
    )
    assert args.data_type == "expenditures"


def test_main_dry_run_with_contribution_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    """Dry-run against real contribution fixture should parse and report row count."""
    fixture_path = _FIXTURE_DIR / "sample_contributions.csv"

    exit_code = cli.main(
        [
            "--path",
            str(fixture_path),
            "--data-type",
            "contributions",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "VA contributions dry-run: parsed 5 rows" in captured.out


def test_main_dry_run_with_expenditure_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    """Dry-run against real expenditure fixture should parse and report row count."""
    fixture_path = _FIXTURE_DIR / "sample_expenditures.csv"

    exit_code = cli.main(
        [
            "--path",
            str(fixture_path),
            "--data-type",
            "expenditures",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "VA expenditures dry-run: parsed 5 rows" in captured.out


def test_main_dry_run_with_limit(capsys: pytest.CaptureFixture[str]) -> None:
    """Dry-run with --limit should cap the parsed row count."""
    fixture_path = _FIXTURE_DIR / "sample_contributions.csv"

    exit_code = cli.main(
        [
            "--path",
            str(fixture_path),
            "--data-type",
            "contributions",
            "--dry-run",
            "--limit",
            "2",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "VA contributions dry-run: parsed 2 rows" in captured.out


def test_main_non_dry_run_returns_parked_refusal_before_database_connection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-dry-run local file mode should refuse writes before DB access."""
    fixture_path = _FIXTURE_DIR / "sample_contributions.csv"

    def raise_if_called() -> None:
        raise AssertionError("sentinel database connection attempted")

    monkeypatch.setattr(cli, "get_connection", raise_if_called)

    exit_code = cli.main(
        [
            "--path",
            str(fixture_path),
            "--data-type",
            "contributions",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert f"VA ingest failed: {cli.VA_WRITE_MODE_REFUSAL}" in captured.err
    assert "sentinel database connection attempted" not in captured.err
    assert "Unable to connect to PostgreSQL" not in captured.err


def test_main_download_non_dry_run_returns_parked_refusal_before_download(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-dry-run download mode should refuse writes before portal access."""

    def raise_if_called(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("sentinel download attempted")

    monkeypatch.setattr(cli, "download_va_csv", raise_if_called)

    exit_code = cli.main(
        [
            "--download",
            "--data-type",
            "contributions",
            "--year-month",
            "2026_03",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert f"VA ingest failed: {cli.VA_WRITE_MODE_REFUSAL}" in captured.err
    assert "sentinel download attempted" not in captured.err


def test_run_va_refresh_rejects_unsupported_data_type() -> None:
    """run_va_refresh should raise for data types not in _SUPPORTED_DATA_TYPES."""
    with pytest.raises(ValueError, match="Unsupported VA data type"):
        cli.run_va_refresh(
            data_type="loans",
            year_month="2026_03",
            path=Path("/tmp/sample.csv"),
        )
