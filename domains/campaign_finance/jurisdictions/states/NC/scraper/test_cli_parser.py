from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.NC.scraper import cli
from domains.campaign_finance.jurisdictions.states.NC.scraper.cli_test_support import (
    build_download_transaction_args,
)


def test_build_argument_parser_parses_transactions_path_input() -> None:
    args = cli._build_argument_parser().parse_args(["--path", "/tmp/file.csv", "--data-type", "transactions"])

    assert args.path == Path("/tmp/file.csv")
    assert args.data_type == "transactions"
    assert args.dry_run is False
    assert args.limit is None
    assert args.committee_docs_path is None


def test_build_argument_parser_accepts_committee_docs_path() -> None:
    args = cli._build_argument_parser().parse_args(
        [
            "--path",
            "/tmp/transactions.csv",
            "--data-type",
            "transactions",
            "--committee-docs-path",
            "/tmp/committee_docs.csv",
        ]
    )

    assert args.committee_docs_path == Path("/tmp/committee_docs.csv")


def test_build_argument_parser_accepts_committee_documents_data_type() -> None:
    args = cli._build_argument_parser().parse_args(["--path", "/tmp/file.csv", "--data-type", "committee-documents"])

    assert args.data_type == "committee-documents"


def test_build_argument_parser_rejects_unknown_data_type() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(["--path", "/tmp/file.csv", "--data-type", "unknown"])


def test_build_argument_parser_parses_limit_and_rejects_negative_values() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--path", "/tmp/file.csv", "--data-type", "transactions", "--limit", "100"]
    )

    assert args.limit == 100

    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            ["--path", "/tmp/file.csv", "--data-type", "transactions", "--limit", "-1"]
        )


def test_build_argument_parser_parses_dry_run_flag() -> None:
    args = cli._build_argument_parser().parse_args(
        ["--path", "/tmp/file.csv", "--data-type", "transactions", "--dry-run"]
    )

    assert args.dry_run is True


def test_build_argument_parser_accepts_download_for_transactions() -> None:
    args = cli._build_argument_parser().parse_args(build_download_transaction_args())

    assert args.download is True
    assert args.path is None
    assert args.output_path == Path("/tmp/nc-transactions.csv")
    assert args.date_from == "01/01/2024"
    assert args.date_to == "01/31/2024"
    assert args.committee_id == "C12345"


def test_build_argument_parser_accepts_download_with_committee_name() -> None:
    args = cli._build_argument_parser().parse_args(
        build_download_transaction_args(committee_id=None, committee_name="Example Committee")
    )

    assert args.download is True
    assert args.committee_name == "Example Committee"
    assert args.committee_id is None


def test_build_argument_parser_accepts_download_with_both_committee_filters() -> None:
    args = cli._build_argument_parser().parse_args(build_download_transaction_args(committee_name="Example Committee"))

    assert args.committee_id == "C12345"
    assert args.committee_name == "Example Committee"


def test_build_argument_parser_accepts_optional_trans_type() -> None:
    args = cli._build_argument_parser().parse_args(build_download_transaction_args("--trans-type", "rec"))

    assert args.trans_type == "rec"

    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(build_download_transaction_args("--trans-type", "invalid"))


def test_build_argument_parser_rejects_download_with_path() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--path",
                "/tmp/file.csv",
                "--download",
                "--data-type",
                "transactions",
                "--date-from",
                "01/01/2024",
                "--date-to",
                "01/31/2024",
                "--output-path",
                "/tmp/download.csv",
                "--committee-id",
                "C12345",
            ]
        )


def test_build_argument_parser_rejects_download_without_date_from() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--download",
                "--data-type",
                "transactions",
                "--output-path",
                "/tmp/transactions.csv",
                "--date-to",
                "01/31/2024",
                "--committee-id",
                "C12345",
            ]
        )


def test_build_argument_parser_rejects_download_without_date_to() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--download",
                "--data-type",
                "transactions",
                "--date-from",
                "01/01/2024",
                "--output-path",
                "/tmp/transactions.csv",
                "--committee-id",
                "C12345",
            ]
        )


def test_build_argument_parser_rejects_download_without_committee_filter() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--download",
                "--data-type",
                "transactions",
                "--date-from",
                "01/01/2024",
                "--date-to",
                "01/31/2024",
                "--output-path",
                "/tmp/transactions.csv",
            ]
        )


def test_build_argument_parser_rejects_download_for_committee_documents() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--download",
                "--data-type",
                "committee-documents",
                "--date-from",
                "01/01/2024",
                "--date-to",
                "01/31/2024",
                "--output-path",
                "/tmp/transactions.csv",
                "--committee-id",
                "C12345",
            ]
        )


def test_build_argument_parser_rejects_download_without_output_path() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(build_download_transaction_args(output_path=None))


def test_build_argument_parser_rejects_output_path_without_download() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(
            [
                "--path",
                "/tmp/file.csv",
                "--data-type",
                "transactions",
                "--output-path",
                "/tmp/download.csv",
            ]
        )


def test_build_argument_parser_requires_path_or_download() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli._build_argument_parser().parse_args(["--data-type", "transactions"])
