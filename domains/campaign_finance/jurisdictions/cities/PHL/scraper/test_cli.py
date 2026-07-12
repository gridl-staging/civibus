"""Unit tests for PHL Carto SQL ingest CLI argument parsing.

Side-effect commands (download/load/refresh) are mostly exercised via
test_download.py / test_load.py. This file pins the CLI argument
contract so a careless arg rename does not silently break callers,
plus the small set of end-to-end orchestration assertions that need
the CLI seam (e.g. "refresh runs both pass-1 and pass-2 in order").
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli import (
    _SUPPORTED_DATA_TYPES,
    _build_argument_parser,
    run_phl_refresh,
)
from domains.campaign_finance.jurisdictions.cities.PHL.scraper.load import LoadResult


def test_cli_supports_three_subcommands() -> None:
    parser = _build_argument_parser()
    args = parser.parse_args(["download", "--data-type", "contributions", "--output", "/tmp/out.jsonl"])
    assert args.command == "download"
    assert args.data_type == "contributions"
    assert args.output == Path("/tmp/out.jsonl")


def test_cli_load_requires_path() -> None:
    parser = _build_argument_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["load", "--data-type", "contributions"])

    args = parser.parse_args(["load", "--data-type", "contributions", "--path", "/tmp/in.jsonl"])
    assert args.command == "load"
    assert args.path == Path("/tmp/in.jsonl")


def test_cli_refresh_runs_with_minimum_args() -> None:
    parser = _build_argument_parser()
    args = parser.parse_args(["refresh", "--data-type", "expenditures"])
    assert args.command == "refresh"
    assert args.data_type == "expenditures"


def test_cli_data_type_must_be_in_supported_set() -> None:
    parser = _build_argument_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["refresh", "--data-type", "campaign_loans_or_something"])


def test_cli_data_type_supports_both_canonical_values() -> None:
    """contributions and expenditures are the two backed PHL Carto tables."""
    assert set(_SUPPORTED_DATA_TYPES) == {"contributions", "expenditures"}


def test_cli_limit_rejects_negative() -> None:
    parser = _build_argument_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["refresh", "--data-type", "contributions", "--limit", "-1"])


def test_cli_limit_accepts_zero() -> None:
    """`--limit 0` is a valid no-op pull (lets ops sanity-check the auth/path
    without writing rows)."""
    parser = _build_argument_parser()
    args = parser.parse_args(["refresh", "--data-type", "contributions", "--limit", "0"])
    assert args.limit == 0


def test_refresh_runs_pass1_then_pass2_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`run_phl_refresh` MUST run pass-1 (source_records) THEN pass-2
    (cf.committee/filing/transaction relational) so the refresh runner
    produces the full domain-level data, not just provenance rows.

    Pinning order matters because pass-2 reads back source_record IDs
    inserted by pass-1; reversing the order would produce 0 cf.* rows.
    """
    # Order is recorded as a side effect of each mock so a reordering
    # regression makes call_order != ["pass1", "pass2"] and fails loudly.
    call_order: list[str] = []
    stub_result = LoadResult(
        inserted=0,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.0,
    )

    def record_pass1(*_args: object, **_kwargs: object) -> LoadResult:
        call_order.append("pass1")
        return stub_result

    def record_pass2(*_args: object, **_kwargs: object) -> LoadResult:
        call_order.append("pass2")
        return stub_result

    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli.load_phl_source_records",
        record_pass1,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli.load_phl_relational",
        record_pass2,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli.get_connection",
        lambda: MagicMock(),
    )

    jsonl = tmp_path / "phl.jsonl"
    jsonl.write_text("{}\n", encoding="utf-8")

    run_phl_refresh(data_type="contributions", path=jsonl)

    # Single equality assertion catches all three failure modes:
    # pass-1 missing, pass-2 missing, or wrong order.
    assert call_order == ["pass1", "pass2"], f"refresh must call pass-1 then pass-2; got {call_order}"


def test_run_phl_refresh_emits_pass_markers_for_detached_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The canonical refresh path must emit bounded pass markers.

    Detached maintenance probes rely on these lines to classify outcomes
    without inferring success from PID exit alone.
    """
    stub_result = LoadResult(
        inserted=11,
        skipped=2,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=1.25,
    )
    pass2_result = LoadResult(
        inserted=11,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=2.50,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli.load_phl_source_records",
        lambda *_args, **_kwargs: stub_result,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli.load_phl_relational",
        lambda *_args, **_kwargs: pass2_result,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.jurisdictions.cities.PHL.scraper.cli.get_connection",
        lambda: MagicMock(),
    )

    jsonl = tmp_path / "phl.jsonl"
    jsonl.write_text("{}\n", encoding="utf-8")
    run_phl_refresh(data_type="contributions", path=jsonl)

    output = capsys.readouterr().out
    assert "PHL contributions load complete: inserted=11 skipped=2" in output
    assert "PHL contributions pass-2 relational complete: inserted=11 skipped=0" in output
