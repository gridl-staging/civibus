from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Literal
import time
from uuid import UUID

import psycopg

from core.db import try_insert_source_record
from core.types.python.models import SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.filing_loader import upsert_transaction
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_transaction_open,
)
from domains.campaign_finance.types.models import Transaction

from .download import NCIEReportUnavailableError, fetch_ie_report_detail_export_csv
from .load_support import ensure_nc_ie_document_index_data_source, select_nc_source_record_id
from .load_types import NCLoadCounts
from .parse_ie_report_section import NCIEReportRow, parse_ie_report_section_csv

LOGGER = logging.getLogger(__name__)

_NC_IE_FILING_PREFIX = "NC-IE-"
_OFFICE_TO_CANDIDATE_CODE = {
    "HOUSE": "H",
    "U.S. HOUSE OF REPRESENTATIVES": "H",
    "SENATE": "S",
    "U.S. SENATE": "S",
    "PRESIDENT": "P",
}


@dataclass(frozen=True, slots=True)
class NCIEFilingWorkItem:
    filing_id: UUID
    filing_fec_id: str
    committee_id: UUID
    committee_name: str
    amendment_indicator: str
    report_section_url: str | None


def _build_load_result(counts: NCLoadCounts, *, started_at: float) -> LoadResult:
    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=0,
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _select_ie_filing_work_items(
    conn: psycopg.Connection,
    *,
    limit: int | None,
) -> list[NCIEFilingWorkItem]:
    sql = """
        SELECT
            f.id,
            f.filing_fec_id,
            f.committee_id,
            f.amendment_indicator,
            c.name AS committee_name,
            sr.raw_fields ->> 'report_section_url' AS report_section_url
        FROM cf.filing f
        JOIN cf.committee c
          ON c.id = f.committee_id
        JOIN core.source_record sr
          ON sr.id = f.source_record_id
        WHERE f.filing_fec_id LIKE %s
        ORDER BY f.receipt_date NULLS LAST, f.created_at, f.filing_fec_id
    """
    params: list[object] = [f"{_NC_IE_FILING_PREFIX}%"]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()

    return [
        NCIEFilingWorkItem(
            filing_id=row[0],
            filing_fec_id=row[1],
            committee_id=row[2],
            amendment_indicator=row[3],
            committee_name=row[4],
            report_section_url=row[5],
        )
        for row in rows
    ]


def _normalize_support_oppose(value: str | None) -> Literal["S", "O"] | None:
    normalized_value = normalize_optional_text(value)
    if normalized_value is None:
        return None
    normalized_token = normalized_value.casefold()
    if normalized_token == "support":
        return "S"
    if normalized_token == "oppose":
        return "O"
    raise ValueError(f"Unsupported NC IE declaration value: {normalized_value!r}")


def _candidate_lookup_office(target_office: str | None) -> str | None:
    normalized_office = normalize_optional_text(target_office)
    if normalized_office is None:
        return None
    return _OFFICE_TO_CANDIDATE_CODE.get(normalized_office.upper())


def _normalize_candidate_name(name: str) -> str:
    return " ".join(name.upper().split())


def _resolve_candidate_id(
    conn: psycopg.Connection,
    *,
    target_name: str | None,
    target_office: str | None,
) -> UUID | None:
    normalized_name = normalize_optional_text(target_name)
    office_code = _candidate_lookup_office(target_office)
    if normalized_name is None or office_code is None:
        return None

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM cf.candidate
            WHERE upper(regexp_replace(name, '\\s+', ' ', 'g')) = %s
              AND office = %s
              AND state = 'NC'
            ORDER BY id
            """,
            (_normalize_candidate_name(normalized_name), office_code),
        )
        rows = cursor.fetchall()

    if len(rows) != 1:
        return None
    return rows[0][0]


def _build_source_record_key(
    *,
    filing_fec_id: str,
    row: NCIEReportRow,
) -> str:
    return f"nc-ie-transaction:{filing_fec_id}:{row.row_index}"


def _build_source_record_payload(
    *,
    filing_fec_id: str,
    report_section_url: str,
    report_detail_url: str | None,
    report_export_url: str | None,
    row: NCIEReportRow,
) -> dict[str, object]:
    return {
        "filing_fec_id": filing_fec_id,
        "report_section_url": report_section_url,
        "report_detail_url": report_detail_url,
        "report_export_url": report_export_url,
        "row_index": row.row_index,
        "spender_committee_name": row.spender_committee_name,
        "payee_name": row.payee_name,
        "target_name": row.target_name,
        "target_office": row.target_office,
        "support_or_oppose_raw": row.support_or_oppose_raw,
        "amount": str(row.amount),
        "transaction_date": row.transaction_date.isoformat(),
        "purpose": row.purpose,
        "payee_city": row.payee_city,
        "payee_state": row.payee_state,
        "payee_zip": row.payee_zip,
    }


def _ensure_transaction_source_record(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    filing_fec_id: str,
    report_section_url: str,
    report_detail_url: str | None,
    report_export_url: str | None,
    row: NCIEReportRow,
) -> tuple[str, UUID]:
    source_record_key = _build_source_record_key(filing_fec_id=filing_fec_id, row=row)
    raw_fields = _build_source_record_payload(
        filing_fec_id=filing_fec_id,
        report_section_url=report_section_url,
        report_detail_url=report_detail_url,
        report_export_url=report_export_url,
        row=row,
    )
    source_record = SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        existing_id = select_nc_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=source_record_key,
        )
        if existing_id is None:
            raise RuntimeError(
                "NC IE transaction source_record insert was skipped but the existing row could not be resolved"
            )
        return source_record_key, existing_id
    return source_record_key, source_record_id


def _build_transaction(
    *,
    filing: NCIEFilingWorkItem,
    row: NCIEReportRow,
    source_record_id: UUID,
    source_record_key: str,
    recipient_candidate_id: UUID | None,
) -> Transaction:
    normalized_state = normalize_optional_text(row.payee_state)
    return Transaction(
        filing_id=filing.filing_id,
        committee_id=filing.committee_id,
        transaction_type="Independent Expenditure",
        transaction_identifier=source_record_key,
        transaction_date=row.transaction_date,
        amount=row.amount,
        contributor_name_raw=row.payee_name,
        contributor_city=row.payee_city,
        contributor_state=normalized_state.upper() if normalized_state is not None else None,
        contributor_zip=row.payee_zip,
        recipient_candidate_id=recipient_candidate_id,
        memo_text=row.purpose,
        amendment_indicator=filing.amendment_indicator,
        source_record_id=source_record_id,
        support_oppose=_normalize_support_oppose(row.support_or_oppose_raw),
    )


def _load_filing_transactions(
    conn: psycopg.Connection,
    *,
    filing: NCIEFilingWorkItem,
    data_source_id: UUID,
) -> NCLoadCounts:
    counts = NCLoadCounts()
    report_section_url = normalize_optional_text(filing.report_section_url)
    if report_section_url is None:
        LOGGER.warning("Skipping NC IE filing without report_section_url: %s", filing.filing_fec_id)
        counts.skipped += 1
        return counts

    try:
        export_csv_text, report_detail_url, report_export_url = fetch_ie_report_detail_export_csv(
            report_section_url
        )
        parsed_rows = parse_ie_report_section_csv(
            export_csv_text,
            spender_committee_name=filing.committee_name,
            source_filing_url=report_section_url,
            report_detail_url=report_detail_url,
            report_export_url=report_export_url,
        )
    except NCIEReportUnavailableError:
        LOGGER.warning("Skipping NC IE filing whose report detail is unavailable: %s", filing.filing_fec_id)
        counts.skipped += 1
        return counts

    for row in parsed_rows:
        try:
            source_record_key, source_record_id = _ensure_transaction_source_record(
                conn,
                data_source_id=data_source_id,
                filing_fec_id=filing.filing_fec_id,
                report_section_url=report_section_url,
                report_detail_url=report_detail_url,
                report_export_url=report_export_url,
                row=row,
            )
            transaction = _build_transaction(
                filing=filing,
                row=row,
                source_record_id=source_record_id,
                source_record_key=source_record_key,
                recipient_candidate_id=_resolve_candidate_id(
                    conn,
                    target_name=row.target_name,
                    target_office=row.target_office,
                ),
            )
            existing_transaction_id = None
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM cf.transaction
                    WHERE filing_id = %s
                      AND transaction_identifier = %s
                    LIMIT 1
                    """,
                    (filing.filing_id, source_record_key),
                )
                transaction_row = cursor.fetchone()
                if transaction_row is not None:
                    existing_transaction_id = transaction_row[0]

            upsert_transaction(conn, transaction)
        except Exception:  # noqa: BLE001
            LOGGER.exception(
                "Failed loading NC IE transaction row filing_fec_id=%s row_index=%s",
                filing.filing_fec_id,
                row.row_index,
            )
            counts.errors += 1
            continue

        if existing_transaction_id is None:
            counts.inserted += 1
        else:
            counts.skipped += 1

    return counts


def load_nc_ie_transactions(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    """Load NC IE transaction rows from filing-linked CFOrgLkup detail exports."""
    started_at = time.monotonic()
    counts = NCLoadCounts()
    filings = _select_ie_filing_work_items(conn, limit=limit)
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for filing in filings:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            filing_counts = _load_filing_transactions(
                conn,
                filing=filing,
                data_source_id=data_source_id,
            )
            counts.inserted += filing_counts.inserted
            counts.skipped += filing_counts.skipped
            counts.errors += filing_counts.errors

    commit_managed_transaction(conn, manages_outer_transaction)
    return _build_load_result(counts, started_at=started_at)


def run_nc_ie_transactions_refresh(*, limit: int | None = None) -> LoadResult:
    """Runner-facing NC IE refresh entrypoint that consumes already-loaded filing rows."""
    from core.db import get_connection

    connection = get_connection()
    try:
        data_source_id = ensure_nc_ie_document_index_data_source(connection)
        result = load_nc_ie_transactions(connection, data_source_id=data_source_id, limit=limit)
        connection.commit()
        return result
    finally:
        connection.close()
