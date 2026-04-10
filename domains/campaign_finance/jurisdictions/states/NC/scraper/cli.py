"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_01_fec_pipeline_hardening/civibus_dev/domains/campaign_finance/jurisdictions/states/NC/scraper/cli.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from core.db import get_connection
from domains.campaign_finance.jurisdictions.states.load_utils import iter_rows_with_limit
from domains.campaign_finance.jurisdictions.states.NC.scraper.download import (
    TransactionSearchCriteria,
    download_transaction_export_playwright,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    LoadResult,
    ensure_nc_committee_document_data_source,
    ensure_nc_data_source,
    load_nc_committee_documents,
    load_nc_transactions,
    load_nc_transactions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
    NCSBoECsvParser,
    parse_committee_docs,
    parse_transactions,
)


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _require_download_options(
    parser: argparse.ArgumentParser,
    parsed_args: argparse.Namespace,
    *option_names: str,
) -> None:
    for option_name in option_names:
        attribute_name = option_name.removeprefix("--").replace("-", "_")
        if getattr(parsed_args, attribute_name):
            continue
        parser.error(f"--download requires {option_name}")


class _NCArgumentParser(argparse.ArgumentParser):

    def parse_args(
        self,
        args: list[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        parsed_args = super().parse_args(args, namespace)
        if parsed_args.download:
            if parsed_args.data_type != "transactions":
                self.error("--download is only supported with --data-type transactions")
            _require_download_options(self, parsed_args, "--date-from", "--date-to")
            _require_download_options(self, parsed_args, "--output-path")
            if not parsed_args.committee_id and not parsed_args.committee_name:
                self.error("--download requires --committee-id or --committee-name")
        elif parsed_args.output_path is not None:
            self.error("--output-path is only supported with --download")
        return parsed_args


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = _NCArgumentParser(description="Load North Carolina SBoE CSV data into Civibus")
    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to an NC SBoE CSV export")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download NC transaction export with Playwright before parsing and loading",
    )
    parser.add_argument(
        "--data-type",
        required=True,
        choices=["transactions", "committee-documents"],
        help="NC data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to parse/load")
    parser.add_argument(
        "--committee-docs-path",
        type=Path,
        help="Optional path to NC SBoE committee-document CSV. "
        "If provided with --data-type transactions, enables full filing/transaction loading.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        help="Retained destination path for CSV downloaded with --download",
    )
    parser.add_argument(
        "--date-from",
        help="Transaction download start date filter (MM/DD/YYYY); required with --download",
    )
    parser.add_argument(
        "--date-to",
        help="Transaction download end date filter (MM/DD/YYYY); required with --download",
    )
    parser.add_argument(
        "--committee-id",
        help="NC committee ID filter for transaction download; required with --download "
        "unless --committee-name is provided",
    )
    parser.add_argument(
        "--committee-name",
        help="NC committee name filter for transaction download; required with --download "
        "unless --committee-id is provided",
    )
    parser.add_argument(
        "--trans-type",
        choices=["all", "rec", "exp"],
        help="Optional NC transaction type filter for download mode (all, rec, exp)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse rows and report counts without writing to the database",
    )
    return parser


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"NC {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _select_parser(path: Path, data_type: str) -> NCSBoECsvParser:
    if data_type == "committee-documents":
        return parse_committee_docs(path)
    return parse_transactions(path)


def _count_parsed_rows(parser: NCSBoECsvParser, limit: int | None) -> int:
    return sum(1 for _row in iter_rows_with_limit(parser, limit))


def _build_transaction_search_criteria(args: argparse.Namespace) -> TransactionSearchCriteria:
    return TransactionSearchCriteria(
        trans_type=args.trans_type or "",
        committee_name=args.committee_name or "",
        committee_id=args.committee_id or "",
        date_from=args.date_from or "",
        date_to=args.date_to or "",
    )


def _resolve_transaction_csv_path(
    args: argparse.Namespace,
) -> Path:
    if args.path is not None:
        return args.path
    if args.output_path is None:
        raise ValueError("--output-path is required with --download")

    search_criteria = _build_transaction_search_criteria(args)
    download_transaction_export_playwright(search_criteria, args.output_path)
    return args.output_path


def _resolve_input_path(
    args: argparse.Namespace,
) -> Path:
    if args.data_type == "committee-documents":
        if args.path is None:
            raise ValueError("--path is required for --data-type committee-documents")
        return args.path
    return _resolve_transaction_csv_path(args)


def _print_dry_run_summary(
    data_type: str,
    *,
    parsed_count: int,
    quarantined_count: int,
) -> None:
    print(f"NC {data_type} dry-run complete: parsed={parsed_count} quarantined={quarantined_count}")


def _run_dry_run(input_path: Path, args: argparse.Namespace) -> int:
    parser = _select_parser(input_path, args.data_type)
    parsed_count = _count_parsed_rows(parser, args.limit)
    _print_dry_run_summary(
        args.data_type,
        parsed_count=parsed_count,
        quarantined_count=parser.skipped,
    )
    return 0


def _load_committee_documents_data(
    connection: psycopg.Connection,
    input_path: Path,
    *,
    limit: int | None,
) -> LoadResult:
    committee_doc_source_id = ensure_nc_committee_document_data_source(connection)
    load_result, _ = load_nc_committee_documents(
        connection,
        input_path,
        data_source_id=committee_doc_source_id,
        limit=limit,
    )
    return load_result


def _load_transactions_without_filings(
    connection: psycopg.Connection,
    input_path: Path,
    *,
    limit: int | None,
) -> LoadResult:
    print(
        "Note: --committee-docs-path not provided; loading transactions without cf.transaction rows.",
        file=sys.stderr,
    )
    data_source_id = ensure_nc_data_source(connection)
    return load_nc_transactions(
        connection,
        input_path,
        data_source_id=data_source_id,
        limit=limit,
    )


def _load_input_data(
    connection: psycopg.Connection,
    input_path: Path,
    args: argparse.Namespace,
) -> LoadResult:
    if args.data_type == "committee-documents":
        return _load_committee_documents_data(
            connection,
            input_path,
            limit=args.limit,
        )
    if args.committee_docs_path is not None:
        return load_nc_transactions_with_filings(
            connection,
            input_path,
            args.committee_docs_path,
            limit=args.limit,
        )
    return _load_transactions_without_filings(
        connection,
        input_path,
        limit=args.limit,
    )


def run_nc_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
    committee_docs_path: Path | None = None,
    output_path: Path | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    committee_id: str | None = None,
    committee_name: str | None = None,
    trans_type: str | None = None,
) -> LoadResult:
    """Run one NC refresh with typed parameters and shared loader helpers."""
    if path is None and not download:
        raise ValueError("NC refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("NC refresh accepts path or download mode, not both")
    if download:
        if data_type != "transactions":
            raise ValueError("NC download mode only supports transactions")
        if output_path is None:
            raise ValueError("NC download mode requires output_path")
        if not date_from or not date_to:
            raise ValueError("NC download mode requires date_from and date_to")
        if not committee_id and not committee_name:
            raise ValueError("NC download mode requires committee_id or committee_name")
    elif output_path is not None:
        raise ValueError("NC output_path is only supported in download mode")

    args = argparse.Namespace(
        path=path,
        download=download,
        data_type=data_type,
        limit=limit,
        committee_docs_path=committee_docs_path,
        output_path=output_path,
        date_from=date_from,
        date_to=date_to,
        committee_id=committee_id,
        committee_name=committee_name,
        trans_type=trans_type,
        dry_run=False,
    )

    connection: psycopg.Connection | None = None
    try:
        input_path = _resolve_input_path(args)
        connection = get_connection()
        load_result = _load_input_data(connection, input_path, args)
        connection.commit()
        return load_result
    finally:
        if connection is not None:
            connection.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    try:
        if args.dry_run:
            input_path = _resolve_input_path(args)
            return _run_dry_run(input_path, args)

        load_result = run_nc_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
            committee_docs_path=args.committee_docs_path,
            output_path=args.output_path,
            date_from=args.date_from,
            date_to=args.date_to,
            committee_id=args.committee_id,
            committee_name=args.committee_name,
            trans_type=args.trans_type,
        )
    except Exception as error:  # noqa: BLE001
        print(f"NC ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, data_type=args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
