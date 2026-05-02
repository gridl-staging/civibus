
from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import psycopg

from core.db import try_insert_source_record
from core.types.python.models import SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.fec_lookup import find_committee_id_by_fec_id
from domains.campaign_finance.ingest.filing_loader import upsert_filing, upsert_transaction
from domains.campaign_finance.ingest.schedule_loader_common import (
    create_schedule_loader_field_parsers,
    json_compatible_raw_fields,
    validate_batch_size,
)
from domains.campaign_finance.ingest.schedule_b_parser import map_schedule_b_fields, read_schedule_b_file
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    commit_managed_transaction,
    try_row_without_savepoint,
)
from domains.campaign_finance.types.models import Filing, Transaction

LOGGER = logging.getLogger(__name__)

_normalize_optional_text = normalize_optional_text
_field_parsers = create_schedule_loader_field_parsers("Schedule B")

_validate_batch_size = validate_batch_size
_require_text = _field_parsers.require_text
_require_decimal = _field_parsers.require_decimal
_optional_date = _field_parsers.optional_date
_normalize_amendment_indicator = _field_parsers.normalize_amendment_indicator
_json_compatible_raw_fields = json_compatible_raw_fields


def _build_source_record_key(*, cycle: int, row: Mapping[str, object]) -> str:
    committee_fec_id = _require_text(row, "committee_id")
    filing_fec_id = _require_text(row, "file_number")
    transaction_key = (
        _normalize_optional_text(row.get("transaction_identifier"))
        or _normalize_optional_text(row.get("image_number"))
        or filing_fec_id
    )
    return f"schedule_b:{cycle}:{committee_fec_id}:{filing_fec_id}:{transaction_key}"


def _try_insert_schedule_b_source_record(
    conn: psycopg.Connection,
    *,
    cycle: int,
    data_source_id: UUID,
    row: Mapping[str, object],
) -> tuple[str, UUID | None]:
    source_record_key = _build_source_record_key(cycle=cycle, row=row)
    raw_fields = _json_compatible_raw_fields(row)
    source_record_id = try_insert_source_record(
        conn,
        SourceRecord(
            data_source_id=data_source_id,
            source_record_key=source_record_key,
            raw_fields=raw_fields,
            pull_date=utc_now(),
            record_hash=compute_record_hash(raw_fields),
        ),
    )
    return source_record_key, source_record_id


def _build_schedule_b_filing(
    *,
    row: Mapping[str, object],
    committee_id: UUID,
    source_record_id: UUID,
    amendment_indicator: str,
) -> Filing:
    return Filing(
        filing_fec_id=_require_text(row, "file_number"),
        committee_id=committee_id,
        report_type="schedule_b",
        amendment_indicator=amendment_indicator,
        source_record_id=source_record_id,
    )


def _build_schedule_b_transaction(
    *,
    row: Mapping[str, object],
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    source_record_key: str,
    amendment_indicator: str,
) -> Transaction:
    transaction_identifier = (
        _normalize_optional_text(row.get("transaction_identifier"))
        or _normalize_optional_text(row.get("image_number"))
        or source_record_key
    )
    sub_id_raw = _normalize_optional_text(row.get("sub_id"))
    sub_id = int(sub_id_raw) if sub_id_raw is not None else None

    return Transaction(
        filing_id=filing_id,
        committee_id=committee_id,
        transaction_type="Expenditure (Itemized)",
        transaction_identifier=transaction_identifier,
        sub_id=sub_id,
        back_ref_transaction_id=_normalize_optional_text(row.get("back_ref_transaction_id")),
        transaction_date=_optional_date(row, "transaction_date"),
        amount=_require_decimal(row, "transaction_amount"),
        contributor_name_raw=_normalize_optional_text(row.get("contributor_name_raw")),
        contributor_city=_normalize_optional_text(row.get("city")),
        contributor_state=_normalize_optional_text(row.get("state")),
        contributor_zip=_normalize_optional_text(row.get("zip_code")),
        memo_code=_normalize_optional_text(row.get("memo_code")),
        memo_text=_normalize_optional_text(row.get("memo_text")),
        amendment_indicator=amendment_indicator,
        source_record_id=source_record_id,
    )


def _process_schedule_b_row(
    conn: psycopg.Connection,
    *,
    cycle: int,
    data_source_id: UUID,
    mapped_row: Mapping[str, object],
    result: LoadResult,
) -> None:
    committee_fec_id = _require_text(mapped_row, "committee_id")
    committee_id = find_committee_id_by_fec_id(conn, committee_fec_id)
    if committee_id is None:
        raise ValueError(
            f"Schedule B row references missing committee CMTE_ID={committee_fec_id}; load committees first"
        )

    amendment_indicator = _normalize_amendment_indicator(mapped_row.get("amendment_indicator"))

    source_record_key, source_record_id = _try_insert_schedule_b_source_record(
        conn,
        cycle=cycle,
        data_source_id=data_source_id,
        row=mapped_row,
    )
    if source_record_id is None:
        result.skipped += 1
        return

    filing = _build_schedule_b_filing(
        row=mapped_row,
        committee_id=committee_id,
        source_record_id=source_record_id,
        amendment_indicator=amendment_indicator,
    )
    filing_id = upsert_filing(conn, filing)

    transaction = _build_schedule_b_transaction(
        row=mapped_row,
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=source_record_id,
        source_record_key=source_record_key,
        amendment_indicator=amendment_indicator,
    )
    upsert_transaction(conn, transaction)
    result.inserted += 1


def load_schedule_b(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    """Load Schedule B rows through the shared filing and transaction upsert path."""
    _validate_batch_size(batch_size)

    result = LoadResult()
    processed_since_commit = 0

    for raw_row in read_schedule_b_file(path, limit=limit):
        mapped_row = map_schedule_b_fields(raw_row)

        def row_callable(
            _mapped=mapped_row,
        ) -> bool:
            _process_schedule_b_row(
                conn,
                cycle=cycle,
                data_source_id=data_source_id,
                mapped_row=_mapped,
                result=result,
            )
            return True

        row_result, was_db_error = try_row_without_savepoint(
            conn,
            row_callable,
            manages_outer_transaction=True,
            label="schedule_b",
        )

        if row_result is None and not was_db_error:
            result.errors += 1
        elif was_db_error:
            result.errors += 1
            processed_since_commit = 0
            continue

        processed_since_commit += 1
        if processed_since_commit >= batch_size:
            commit_managed_transaction(conn, manages_outer_transaction=True)
            processed_since_commit = 0

    if processed_since_commit > 0:
        commit_managed_transaction(conn, manages_outer_transaction=True)

    return result


__all__ = ["load_schedule_b"]
