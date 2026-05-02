
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg

from core.db import get_connection
from core.keel_gate_l6 import build_load_id, run_l6_gate_for_nc_load
from domains.campaign_finance.jurisdictions.states.load_utils import iter_rows_with_limit
from domains.campaign_finance.jurisdictions.states.NC.scraper.committee_discovery import (
    crawl_committee_registry_httpx,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.download import (
    TransactionSearchCriteria,
    download_transaction_export_playwright,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.orchestrate_committee_ingest import (
    CommitteeIngestRunResult,
    run_nc_committee_orchestrator,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.mvp_scope_selector import (
    select_mvp_scope_committees,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    LoadResult,
    ensure_nc_committee_document_data_source,
    ensure_nc_data_source,
    ensure_nc_ie_document_index_data_source,
    load_nc_committee_documents,
    load_nc_committee_registry_rows,
    load_nc_ie_document_index,
    load_nc_ie_transactions,
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


def _non_negative_float(raw_value: str) -> float:
    value = float(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("value must be greater than or equal to 0")
    return value


def _iso_date(raw_value: str) -> date:
    try:
        return date.fromisoformat(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date values must use YYYY-MM-DD format") from error


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
        if parsed_args.orchestrate_committees:
            if parsed_args.data_type != "transactions":
                self.error("--orchestrate-committees requires --data-type transactions")
            if parsed_args.window_start is None:
                self.error("--orchestrate-committees requires --window-start")
            if parsed_args.window_end is None:
                self.error("--orchestrate-committees requires --window-end")
            if parsed_args.dry_run:
                self.error("--dry-run is not supported with --orchestrate-committees")
            if parsed_args.window_end < parsed_args.window_start:
                self.error("--window-end must be greater than or equal to --window-start")
            if parsed_args.stale_after_minutes is None:
                parsed_args.stale_after_minutes = 60
            if parsed_args.politeness_delay_seconds is None:
                parsed_args.politeness_delay_seconds = 0.0
            return parsed_args

        if parsed_args.window_start is not None or parsed_args.window_end is not None:
            self.error("--window-start and --window-end are only supported with --orchestrate-committees")
        if parsed_args.stale_after_minutes is not None:
            self.error("--stale-after-minutes is only supported with --orchestrate-committees")
        if parsed_args.politeness_delay_seconds is not None:
            self.error("--politeness-delay-seconds is only supported with --orchestrate-committees")
        if parsed_args.committees_from_query:
            self.error("--committees-from-query is only supported with --orchestrate-committees")
        if parsed_args.year_from is not None:
            self.error("--year-from is only supported with --orchestrate-committees")

        if parsed_args.data_type == "ie-transactions":
            if parsed_args.path is not None:
                self.error("--path is not supported with --data-type ie-transactions")
            if parsed_args.download:
                self.error("--download is not supported with --data-type ie-transactions")
            if parsed_args.dry_run:
                self.error("--dry-run is not supported with --data-type ie-transactions")
            incompatible_options = (
                ("committee_docs_path", "--committee-docs-path"),
                ("committee_id", "--committee-id"),
                ("committee_name", "--committee-name"),
                ("date_from", "--date-from"),
                ("date_to", "--date-to"),
                ("trans_type", "--trans-type"),
                ("output_path", "--output-path"),
            )
            for attribute_name, option_name in incompatible_options:
                if getattr(parsed_args, attribute_name) is not None:
                    self.error(f"{option_name} is not supported with --data-type ie-transactions")
            return parsed_args

        if parsed_args.data_type == "transactions" and parsed_args.path is None and not parsed_args.download:
            self.error("--path or --download is required with --data-type transactions")
        if parsed_args.data_type in {"committee-documents", "ie-document-index"} and parsed_args.path is None:
            self.error("--path is required for --data-type committee-documents or ie-document-index")
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
    input_source_group = parser.add_mutually_exclusive_group(required=False)
    input_source_group.add_argument("--path", type=Path, help="Path to an NC SBoE CSV export")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download NC transaction export with Playwright before parsing and loading",
    )
    input_source_group.add_argument(
        "--orchestrate-committees",
        action="store_true",
        help="Run statewide sequential committee orchestration for a date window",
    )
    parser.add_argument(
        "--data-type",
        required=True,
        choices=["transactions", "committee-documents", "ie-document-index", "ie-transactions"],
        help="NC data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to parse/load")
    parser.add_argument(
        "--window-start",
        type=_iso_date,
        help="Inclusive lower bound for orchestrator transaction window (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--window-end",
        type=_iso_date,
        help="Inclusive upper bound for orchestrator transaction window (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--stale-after-minutes",
        type=_non_negative_int,
        help="Minutes before in-progress orchestrator rows are reclaimed (default: 60)",
    )
    parser.add_argument(
        "--politeness-delay-seconds",
        type=_non_negative_float,
        help="Delay before each portal request in orchestrator mode (default: 0)",
    )
    parser.add_argument(
        "--committees-from-query",
        action="store_true",
        help="Use the NC MVP committee selector to scope orchestrator queue seeding",
    )
    parser.add_argument(
        "--year-from",
        type=int,
        help="Inclusive lower year bound for transaction parser filtering in orchestrator mode",
    )
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


def _print_orchestrator_summary(result: CommitteeIngestRunResult) -> None:
    print(
        "NC committee orchestrator complete: "
        f"seeded={result.seeded} "
        f"reclaimed={result.reclaimed} "
        f"claimed={result.claimed} "
        f"completed={result.completed} "
        f"year_filtered={result.year_filtered} "
        f"retryable_failures={result.retryable_failures} "
        f"permanent_failures={result.permanent_failures}"
    )


def _select_parser(path: Path, data_type: str) -> NCSBoECsvParser:
    if data_type in {"committee-documents", "ie-document-index"}:
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
) -> Path | None:
    if args.data_type == "ie-transactions":
        return None
    if args.data_type in {"committee-documents", "ie-document-index"}:
        if args.path is None:
            raise ValueError("--path is required for --data-type committee-documents or ie-document-index")
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


def _load_ie_document_index_data(
    connection: psycopg.Connection,
    input_path: Path,
    *,
    limit: int | None,
) -> LoadResult:
    ie_source_id = ensure_nc_ie_document_index_data_source(connection)
    return load_nc_ie_document_index(
        connection,
        input_path,
        data_source_id=ie_source_id,
        limit=limit,
    )


def _load_committee_discovery_data(
    connection: psycopg.Connection,
    *,
    limit: int | None,
) -> LoadResult:
    discovered_rows_by_org_group_id = crawl_committee_registry_httpx()
    return load_nc_committee_registry_rows(
        connection,
        discovered_rows_by_org_group_id.values(),
        limit=limit,
    )


def _load_input_data(
    connection: psycopg.Connection,
    input_path: Path | None,
    args: argparse.Namespace,
) -> LoadResult:
    if args.data_type == "committee-discovery":
        return _load_committee_discovery_data(connection, limit=args.limit)
    if args.data_type == "ie-transactions":
        ie_source_id = ensure_nc_ie_document_index_data_source(connection)
        return load_nc_ie_transactions(
            connection,
            data_source_id=ie_source_id,
            limit=args.limit,
        )
    if input_path is None:
        raise ValueError(f"NC data type {args.data_type!r} requires a CSV input path")
    if args.data_type == "committee-documents":
        return _load_committee_documents_data(
            connection,
            input_path,
            limit=args.limit,
        )
    if args.data_type == "ie-document-index":
        return _load_ie_document_index_data(
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
    is_committee_discovery = data_type == "committee-discovery"
    is_ie_transactions = data_type == "ie-transactions"
    if is_committee_discovery:
        if path is not None:
            raise ValueError("NC committee-discovery refresh does not accept path")
        if download:
            raise ValueError("NC committee-discovery refresh does not accept download mode")
        if output_path is not None:
            raise ValueError("NC committee-discovery refresh does not accept output_path")
    elif is_ie_transactions:
        if path is not None:
            raise ValueError("NC ie-transactions refresh does not support path input")
        if download:
            raise ValueError("NC ie-transactions refresh does not support download mode")
        if committee_docs_path is not None:
            raise ValueError("NC ie-transactions refresh does not support committee_docs_path")
        if committee_id is not None or committee_name is not None:
            raise ValueError("NC ie-transactions refresh does not support committee filters")
        if date_from is not None or date_to is not None:
            raise ValueError("NC ie-transactions refresh does not support date range filters")
        if trans_type is not None:
            raise ValueError("NC ie-transactions refresh does not support trans_type")
        if output_path is not None:
            raise ValueError("NC ie-transactions refresh does not support output_path")
    else:
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
        input_path: Path | None = None
        if not is_committee_discovery and not is_ie_transactions:
            input_path = _resolve_input_path(args)
        if input_path is not None:
            produced_at = datetime.now(timezone.utc)
            temporal_gate_result = run_l6_gate_for_nc_load(
                path=input_path,
                data_type=data_type,
                load_id=build_load_id(
                    jurisdiction="NC",
                    data_type=data_type,
                    produced_at=produced_at,
                ),
                load_date=produced_at.date(),
            )
            if temporal_gate_result.status != "pass":
                raise ValueError(
                    "L6 temporal gate failed "
                    f"(load_id={temporal_gate_result.load_id}, evidence={temporal_gate_result.evidence_path})"
                )
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
        if args.orchestrate_committees:
            allowlist_sboe_ids: list[str] | None = None
            if args.committees_from_query:
                selector_conn: psycopg.Connection | None = None
                try:
                    selector_conn = get_connection()
                    allowlist_sboe_ids = select_mvp_scope_committees(selector_conn)
                finally:
                    if selector_conn is not None:
                        selector_conn.close()
            orchestrator_result = run_nc_committee_orchestrator(
                window_start=args.window_start,
                window_end=args.window_end,
                limit=args.limit,
                stale_after_minutes=args.stale_after_minutes,
                politeness_delay_seconds=args.politeness_delay_seconds,
                allowlist_sboe_ids=allowlist_sboe_ids,
                year_from=args.year_from,
            )
            _print_orchestrator_summary(orchestrator_result)
            return 0

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
