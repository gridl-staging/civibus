"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_01_fec_pipeline_hardening/civibus_dev/domains/campaign_finance/jurisdictions/states/NC/scraper/cli_test_support.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

SAMPLE_TRANSACTIONS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "transaction_export_sample.csv"
SAMPLE_COMMITTEE_DOCS = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "committee_document_export_sample.csv"
)


def _build_path_args(path: Path, data_type: str, *extra_args: str) -> list[str]:
    return ["--path", str(path), "--data-type", data_type, *extra_args]


def build_transaction_path_args(*extra_args: str) -> list[str]:
    return _build_path_args(SAMPLE_TRANSACTIONS, "transactions", *extra_args)


def build_committee_document_path_args(*extra_args: str) -> list[str]:
    return _build_path_args(SAMPLE_COMMITTEE_DOCS, "committee-documents", *extra_args)


def build_download_transaction_args(
    *extra_args: str,
    committee_id: str | None = "C12345",
    committee_name: str | None = None,
    output_path: str | None = "/tmp/nc-transactions.csv",
    date_from: str = "01/01/2024",
    date_to: str = "01/31/2024",
) -> list[str]:
    if committee_id is None and committee_name is None:
        raise ValueError("committee_id or committee_name is required")

    committee_filters: list[str] = []
    if committee_id is not None:
        committee_filters.extend(["--committee-id", committee_id])
    if committee_name is not None:
        committee_filters.extend(["--committee-name", committee_name])

    output_path_args: list[str] = []
    if output_path is not None:
        output_path_args.extend(["--output-path", output_path])

    return [
        "--download",
        "--data-type",
        "transactions",
        "--date-from",
        date_from,
        "--date-to",
        date_to,
        *output_path_args,
        *committee_filters,
        *extra_args,
    ]


def patch_download_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    cli_module: object,
) -> tuple[MagicMock, Path]:
    downloaded_path = tmp_path / "nc-download" / "transactions.csv"
    download_mock = MagicMock()
    monkeypatch.setattr(cli_module, "download_transaction_export_playwright", download_mock)

    return download_mock, downloaded_path
