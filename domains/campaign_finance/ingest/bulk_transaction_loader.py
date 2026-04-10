"""Pure builders and lookups for FEC bulk transaction loading (Stage 2).

Consumes already-mapped contribution records from field_mapper.py.
Routes all cf.* writes through filing_loader.py.
Does not own raw-row parsing or direct SQL upserts.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

import psycopg

from domains.campaign_finance.ingest.fec_lookup import find_candidate_id_by_fec_id, find_committee_id_by_fec_id
from domains.campaign_finance.ingest.filing_loader import resolve_transaction_counterparty_ids
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.types.models import Filing, Transaction


_optional_text = normalize_optional_text


def _require_text(record: Mapping[str, object], field_name: str) -> str:
    value = _optional_text(record.get(field_name))
    if value is None:
        raise ValueError(f"{field_name} is required in mapped contribution record")
    return value


def _parse_sub_id(value: object) -> int | None:
    normalized_value = _optional_text(value)
    if normalized_value is None:
        return None
    try:
        return int(normalized_value)
    except ValueError as error:
        raise ValueError(f"sub_id must be numeric when present, got {normalized_value!r}") from error


def _parse_date(value: object) -> date | None:
    normalized_value = _optional_text(value)
    if normalized_value is None:
        return None
    return date.fromisoformat(normalized_value)


def _parse_amount(value: object) -> Decimal:
    if value is None:
        raise ValueError("contribution_receipt_amount is required in mapped contribution record")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"contribution_receipt_amount must be numeric, got {value!r}") from error


def _derive_filing_fec_id(record: Mapping[str, object]) -> str:
    """Filing ID precedence: image_number -> file_number -> synthetic fallback."""
    image_number = _optional_text(record.get("image_number"))
    if image_number:
        return image_number

    file_number = _optional_text(record.get("file_number"))
    if file_number:
        return file_number

    committee_fec_id = _require_text(record, "committee_id")
    report_type = _require_text(record, "report_type")
    amendment_indicator = _require_text(record, "amendment_indicator")
    return f"FEC-{committee_fec_id}-{report_type}-{amendment_indicator}"


def build_filing_from_contribution(
    conn: psycopg.Connection,
    record: Mapping[str, object],
    *,
    source_record_id: UUID | None = None,
) -> Filing:
    """Build a Filing model from an already-mapped contribution record."""
    committee_fec_id = _require_text(record, "committee_id")
    committee_id = find_committee_id_by_fec_id(conn, committee_fec_id)
    if committee_id is None:
        raise ValueError(f"committee not found for fec_id={committee_fec_id}")

    filing_fec_id = _derive_filing_fec_id(record)
    amendment_indicator = _require_text(record, "amendment_indicator")
    report_type = _optional_text(record.get("report_type"))

    return Filing(
        filing_fec_id=filing_fec_id,
        committee_id=committee_id,
        amendment_indicator=amendment_indicator,
        report_type=report_type,
        source_record_id=source_record_id,
    )


def build_transaction_from_contribution(
    conn: psycopg.Connection,
    record: Mapping[str, object],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID | None = None,
) -> Transaction:
    """Build a Transaction model from an already-mapped contribution record."""
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=("donor",),
        organization_roles=("contributor",),
    )
    recipient_candidate_id = None
    candidate_fec_id = _optional_text(record.get("candidate_fec_id"))
    if candidate_fec_id:
        recipient_candidate_id = find_candidate_id_by_fec_id(conn, candidate_fec_id)

    recipient_committee_id = None
    other_id = _optional_text(record.get("other_id"))
    if other_id:
        recipient_committee_id = find_committee_id_by_fec_id(conn, other_id)

    return Transaction(
        filing_id=filing_id,
        committee_id=committee_id,
        transaction_type=_require_text(record, "transaction_type"),
        transaction_identifier=_optional_text(record.get("transaction_identifier")),
        sub_id=_parse_sub_id(record.get("sub_id")),
        transaction_date=_parse_date(record.get("contribution_receipt_date")),
        amount=_parse_amount(record.get("contribution_receipt_amount")),
        contributor_name_raw=_optional_text(record.get("contributor_name")),
        contributor_employer=_optional_text(record.get("contributor_employer")),
        contributor_occupation=_optional_text(record.get("contributor_occupation")),
        contributor_city=_optional_text(record.get("contributor_city")),
        contributor_state=_optional_text(record.get("contributor_state")),
        contributor_zip=_optional_text(record.get("contributor_zip")),
        contributor_person_id=contributor_person_id,
        contributor_organization_id=contributor_organization_id,
        memo_code=_optional_text(record.get("memo_code")),
        memo_text=_optional_text(record.get("memo_text")),
        amendment_indicator=_require_text(record, "amendment_indicator"),
        recipient_candidate_id=recipient_candidate_id,
        recipient_committee_id=recipient_committee_id,
        source_record_id=source_record_id,
    )


def resolve_source_record_id(
    conn: psycopg.Connection,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    """Look up existing active source_record by its unique key.

    Used for backfill: when load_contribution() already created the
    provenance row in a prior run, this resolves the source_record_id
    so the relational path can attach it to cf.filing / cf.transaction.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            """,
            (data_source_id, source_record_key),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


__all__ = [
    "build_filing_from_contribution",
    "build_transaction_from_contribution",
    "resolve_source_record_id",
]
