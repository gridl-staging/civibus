
from __future__ import annotations

from collections import deque
import logging
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import psycopg

from core.types.python.models import compute_record_hash
from domains.campaign_finance.types.models import Filing

from .download import fetch_ie_document_result_report_section_urls
from .load import (
    build_load_result,
    iter_nc_rows,
    parse_optional_date,
    require_text,
    resolve_committee_doc_source_record,
    resolve_nc_committee_bridge,
    to_amendment_indicator,
)
from .load_support import set_nc_source_record_report_section_url
from .load_types import LoadResult, NCLoadCounts
from .parse import (
    NCCommitteeDocumentRowKey,
    build_nc_committee_doc_linkage_key,
    classify_ie_filing,
    is_within_ie_year_window,
    parse_committee_docs,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.ingest.filing_loader import upsert_filing
from domains.campaign_finance.jurisdictions.states.load_utils import (
    commit_managed_transaction,
    ensure_transaction_open,
)

LOGGER = logging.getLogger(__name__)


def _build_nc_ie_filing_fec_id(row: Mapping[str, str | None]) -> str:
    source_record_key = compute_record_hash(dict(row))
    return f"NC-IE-{source_record_key}"


def _normalize_nc_ie_committee_sboe_id(row: Mapping[str, str | None]) -> str:
    normalized_sboe_id = normalize_optional_text(row.get("SBoE ID"))
    if normalized_sboe_id is not None and normalized_sboe_id.lower() != "no id":
        return normalized_sboe_id

    committee_name = require_text(row.get("Committee Name"), "Committee Name")
    committee_hash = compute_record_hash({"Committee Name": committee_name})[:16]
    return f"NC-IE-{committee_hash}"


def _build_nc_ie_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> Filing:
    return Filing(
        filing_fec_id=_build_nc_ie_filing_fec_id(row),
        committee_id=committee_id,
        report_type=normalize_optional_text(row.get("Doc Type")),
        amendment_indicator=to_amendment_indicator(row.get("Amend")),
        filing_name=normalize_optional_text(row.get("Doc Name")),
        coverage_start_date=parse_optional_date(row.get("Start Date")),
        coverage_end_date=parse_optional_date(row.get("End Date")),
        receipt_date=parse_optional_date(row.get("Received Data")),
        accepted_date=parse_optional_date(row.get("Received Image")),
        source_record_id=source_record_id,
    )


def _load_nc_ie_document_index_row(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    report_section_url: str | None,
) -> bool:
    source_record_id, inserted_source_record = resolve_committee_doc_source_record(
        conn,
        row=row,
        data_source_id=data_source_id,
    )

    committee_sboe_id = _normalize_nc_ie_committee_sboe_id(row)
    committee_id = resolve_nc_committee_bridge(
        conn,
        committee_sboe_id,
        committee_name=row.get("Committee Name"),
    )
    filing = _build_nc_ie_filing(
        row,
        committee_id=committee_id,
        source_record_id=source_record_id,
    )
    upsert_filing(conn, filing)
    if report_section_url:
        set_nc_source_record_report_section_url(
            conn,
            source_record_id=source_record_id,
            report_section_url=report_section_url,
        )
    return inserted_source_record


def _build_report_section_url_queues_by_row_key(
    ie_rows: list[Mapping[str, str | None]],
) -> dict[NCCommitteeDocumentRowKey, deque[str | None]]:
    report_section_url_queues: dict[NCCommitteeDocumentRowKey, deque[str | None]] = {}
    target_years: set[int] = set()
    for row in ie_rows:
        normalized_year = normalize_optional_text(row.get("Year"))
        if normalized_year is None:
            continue
        try:
            target_years.add(int(normalized_year))
        except ValueError:
            continue

    for year in sorted(target_years):
        try:
            year_report_section_urls = fetch_ie_document_result_report_section_urls(year)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed fetching NC IE DocumentResult report-section URLs for year=%s", year)
            continue

        for row_key, captured_urls in year_report_section_urls.items():
            queue_for_key = report_section_url_queues.setdefault(row_key, deque())
            queue_for_key.extend(captured_urls)

    return report_section_url_queues


def _resolve_row_report_section_url(
    row: Mapping[str, str | None],
    *,
    report_section_url_queues: dict[NCCommitteeDocumentRowKey, deque[str | None]],
) -> str | None:
    row_key = build_nc_committee_doc_linkage_key(row)
    queue_for_key = report_section_url_queues.get(row_key)
    if not queue_for_key:
        return None
    candidate_url = queue_for_key.popleft()
    return candidate_url or None


def load_nc_ie_document_index(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    parser = parse_committee_docs(Path(file_path))
    started_at = time.monotonic()
    counts = NCLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    current_year = datetime.now(timezone.utc).year
    candidate_ie_rows: list[Mapping[str, str | None]] = []

    for row in iter_nc_rows(parser, limit=limit):
        if not classify_ie_filing(row) or not is_within_ie_year_window(row, current_year=current_year):
            counts.skipped += 1
            continue
        candidate_ie_rows.append(row)

    report_section_url_queues = _build_report_section_url_queues_by_row_key(candidate_ie_rows)

    for row in candidate_ie_rows:
        try:
            if manages_outer_transaction:
                ensure_transaction_open(conn)
            with conn.transaction():
                inserted = _load_nc_ie_document_index_row(
                    conn,
                    row=row,
                    data_source_id=data_source_id,
                    report_section_url=_resolve_row_report_section_url(
                        row,
                        report_section_url_queues=report_section_url_queues,
                    ),
                )
        except Exception:  # noqa: BLE001
            LOGGER.exception(
                "Failed loading NC ie_document_index row source_record_key=%s",
                compute_record_hash(dict(row)),
            )
            counts.errors += 1
            continue

        if inserted:
            counts.inserted += 1
        else:
            counts.skipped += 1

    commit_managed_transaction(conn, manages_outer_transaction)
    return build_load_result(counts, rows=parser, started_at=started_at)
