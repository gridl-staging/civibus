"""
Stub summary for mar22_03_fec_schedule_e_independent_expenditures/civibus_dev/domains/campaign_finance/ingest/schedule_e_loader.py.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from pathlib import Path
from uuid import UUID

import psycopg

from core.db import try_insert_source_record
from core.types.python.models import SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.fec_lookup import find_candidate_id_by_fec_id, find_committee_id_by_fec_id
from domains.campaign_finance.ingest.filing_loader import upsert_filing, upsert_transaction
from domains.campaign_finance.ingest.schedule_loader_common import (
    create_schedule_loader_field_parsers,
    json_compatible_raw_fields,
    validate_batch_size,
)
from domains.campaign_finance.ingest.schedule_e_parser import read_schedule_e_file
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.types.models import Filing, Transaction

LOGGER = logging.getLogger(__name__)

_SCHEDULE_E_ROW_SAVEPOINT = "schedule_e_row"

_normalize_optional_text = normalize_optional_text
_field_parsers = create_schedule_loader_field_parsers("Schedule E")

_validate_batch_size = validate_batch_size
_require_text = _field_parsers.require_text
_require_decimal = _field_parsers.require_decimal
_optional_date = _field_parsers.optional_date
_normalize_amendment_indicator = _field_parsers.normalize_amendment_indicator
_json_compatible_raw_fields = json_compatible_raw_fields


def _normalize_support_oppose(value: object) -> str | None:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        return None
    if normalized_value not in {"S", "O"}:
        raise ValueError(f"Unsupported Schedule E support/oppose value: {normalized_value!r}")
    return normalized_value


def _build_source_record_key(*, cycle: int, row: Mapping[str, object]) -> str:
    committee_fec_id = _require_text(row, "spe_id")
    filing_fec_id = _require_text(row, "file_num")
    transaction_key = (
        _normalize_optional_text(row.get("tran_id")) or _normalize_optional_text(row.get("image_num")) or filing_fec_id
    )
    return f"schedule_e:{cycle}:{committee_fec_id}:{filing_fec_id}:{transaction_key}"


def _try_insert_schedule_e_source_record(
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


def _select_filing_id_by_fec_id(conn: psycopg.Connection, filing_fec_id: str) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM cf.filing WHERE filing_fec_id = %s LIMIT 1",
            (filing_fec_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _build_schedule_e_filing(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, object],
    committee_id: UUID,
    candidate_id: UUID | None,
    source_record_id: UUID,
    amendment_indicator: str,
) -> Filing:
    previous_filing_fec_id = _normalize_optional_text(row.get("prev_file_num"))
    amended_from_filing_id = None
    if previous_filing_fec_id is not None:
        amended_from_filing_id = _select_filing_id_by_fec_id(conn, previous_filing_fec_id)

    return Filing(
        filing_fec_id=_require_text(row, "file_num"),
        committee_id=committee_id,
        candidate_id=candidate_id,
        report_type="schedule_e",
        amendment_indicator=amendment_indicator,
        filing_name=_normalize_optional_text(row.get("spe_nam")),
        receipt_date=_optional_date(row, "receipt_dat"),
        accepted_date=_optional_date(row, "receipt_dat"),
        amended_from_filing_id=amended_from_filing_id,
        source_record_id=source_record_id,
    )


def _build_schedule_e_transaction(
    *,
    row: Mapping[str, object],
    filing_id: UUID,
    committee_id: UUID,
    recipient_candidate_id: UUID | None,
    source_record_id: UUID,
    source_record_key: str,
    amendment_indicator: str,
) -> Transaction:
    transaction_identifier = (
        _normalize_optional_text(row.get("tran_id"))
        or _normalize_optional_text(row.get("image_num"))
        or source_record_key
    )
    return Transaction(
        filing_id=filing_id,
        committee_id=committee_id,
        transaction_type="Independent Expenditure",
        transaction_identifier=transaction_identifier,
        transaction_date=_optional_date(row, "exp_date"),
        amount=_require_decimal(row, "exp_amo"),
        contributor_name_raw=_normalize_optional_text(row.get("pay")),
        memo_text=_normalize_optional_text(row.get("pur")),
        recipient_candidate_id=recipient_candidate_id,
        amendment_indicator=amendment_indicator,
        source_record_id=source_record_id,
        support_oppose=_normalize_support_oppose(row.get("sup_opp")),
        dissemination_date=_optional_date(row, "dissem_dt"),
        aggregate_amount=row.get("agg_amo"),
    )


def _commit_batch(conn: psycopg.Connection, processed_since_commit: int, batch_size: int) -> int:
    if processed_since_commit >= batch_size:
        conn.commit()
        return 0
    return processed_since_commit


def load_schedule_e(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    """Load Schedule E rows through the shared filing and transaction upsert path."""
    _validate_batch_size(batch_size)

    result = LoadResult()
    processed_since_commit = 0

    for row in read_schedule_e_file(path, limit=limit):
        processed_since_commit += 1
        with conn.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {_SCHEDULE_E_ROW_SAVEPOINT}")
            try:
                committee_fec_id = _require_text(row, "spe_id")
                committee_id = find_committee_id_by_fec_id(conn, committee_fec_id)
                if committee_id is None:
                    raise ValueError(
                        f"Schedule E row references missing committee spe_id={committee_fec_id}; load committees first"
                    )

                candidate_fec_id = _normalize_optional_text(row.get("cand_id"))
                candidate_id = (
                    find_candidate_id_by_fec_id(conn, candidate_fec_id) if candidate_fec_id is not None else None
                )
                amendment_indicator = _normalize_amendment_indicator(row.get("amndt_ind"))

                source_record_key, source_record_id = _try_insert_schedule_e_source_record(
                    conn,
                    cycle=cycle,
                    data_source_id=data_source_id,
                    row=row,
                )
                if source_record_id is None:
                    result.skipped += 1
                    cursor.execute(f"ROLLBACK TO SAVEPOINT {_SCHEDULE_E_ROW_SAVEPOINT}")
                    cursor.execute(f"RELEASE SAVEPOINT {_SCHEDULE_E_ROW_SAVEPOINT}")
                    processed_since_commit = _commit_batch(conn, processed_since_commit, batch_size)
                    continue

                filing = _build_schedule_e_filing(
                    conn,
                    row=row,
                    committee_id=committee_id,
                    candidate_id=candidate_id,
                    source_record_id=source_record_id,
                    amendment_indicator=amendment_indicator,
                )
                filing_id = upsert_filing(conn, filing)

                transaction = _build_schedule_e_transaction(
                    row=row,
                    filing_id=filing_id,
                    committee_id=committee_id,
                    recipient_candidate_id=candidate_id,
                    source_record_id=source_record_id,
                    source_record_key=source_record_key,
                    amendment_indicator=amendment_indicator,
                )
                upsert_transaction(conn, transaction)
            except Exception:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {_SCHEDULE_E_ROW_SAVEPOINT}")
                cursor.execute(f"RELEASE SAVEPOINT {_SCHEDULE_E_ROW_SAVEPOINT}")
                result.errors += 1
                LOGGER.warning("Skipping Schedule E row during ingest: %s", row, exc_info=True)
            else:
                cursor.execute(f"RELEASE SAVEPOINT {_SCHEDULE_E_ROW_SAVEPOINT}")
                result.inserted += 1

        processed_since_commit = _commit_batch(conn, processed_since_commit, batch_size)

    if processed_since_commit > 0:
        conn.commit()
    return result


__all__ = ["load_schedule_e"]
