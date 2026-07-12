"""
Stub summary for mar21_02_tx_pa_state_pipelines/civibus_dev/domains/campaign_finance/jurisdictions/states/PA/scraper/load.py.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from core.db import try_insert_source_record
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    resolve_transaction_counterparty_ids,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_transaction_open,
    iter_rows_with_limit,
    validated_limit,
)
from domains.campaign_finance.types.models import Transaction

from . import _load_column_for_semantic_path
from . import load_support as _load_support
from .extract import (
    extract_pa_contribution,
    extract_pa_debt,
    extract_pa_expenditure,
    extract_pa_filing,
    extract_pa_receipt,
)
from .parse import parse_contributions, parse_debts, parse_expenditures, parse_filings, parse_receipts

LOGGER = logging.getLogger(__name__)

ensure_pa_data_source = _load_support.ensure_pa_data_source
_build_filer_amendment_lookup = _load_support._build_filer_amendment_lookup
_build_filer_row_lookup = _load_support._build_filer_row_lookup
_build_pa_filing = _load_support._build_pa_filing
_build_pa_source_record = _load_support._build_pa_source_record
_load_pa_transaction_entities = _load_support._load_pa_transaction_entities
_pa_campaign_finance_id = _load_support._pa_campaign_finance_id
_pa_counterparty_employer = _load_support._pa_counterparty_employer
_pa_counterparty_name_raw = _load_support._pa_counterparty_name_raw
_pa_counterparty_occupation = _load_support._pa_counterparty_occupation
_pa_filing_fec_id = _load_support._pa_filing_fec_id
_pa_filing_fec_id_from_filer_row = _load_support._pa_filing_fec_id_from_filer_row
_pa_source_record_key = _load_support._pa_source_record_key
_pa_transaction_date = _load_support._pa_transaction_date
_pa_transaction_identifier = _load_support._pa_transaction_identifier
_pa_transaction_type = _load_support._pa_transaction_type
_parse_pa_compact_date = _load_support._parse_pa_compact_date
_parse_pa_submitted_date = _load_support._parse_pa_submitted_date
_parse_required_pa_amount = _load_support._parse_required_pa_amount
_require_pa_filer_row = _load_support._require_pa_filer_row
_required_pa_text = _load_support._required_pa_text
_resolve_pa_amendment_indicator = _load_support._resolve_pa_amendment_indicator
_resolve_pa_committee_organization_id = _load_support._resolve_pa_committee_organization_id
_resolve_pa_transaction_address_id = _load_support._resolve_pa_transaction_address_id
_select_pa_source_record_id = _load_support._select_pa_source_record_id

_PA_EXTRACT_FN: dict[str, Callable[[dict[str, str | None]], dict[str, Any]]] = {
    "contributions": extract_pa_contribution,
    "expenditures": extract_pa_expenditure,
    "debts": extract_pa_debt,
    "receipts": extract_pa_receipt,
}
_PA_ENTITY_KEYS_BY_TYPE = {
    "contributions": ("donor_person", "donor_org"),
    "expenditures": ("payee_person", "payee_org"),
    "debts": ("lender_person", "lender_org"),
    "receipts": ("source_person", "source_org"),
}
_PA_COUNTERPARTY_ROLES_BY_TYPE = {
    "contributions": (("donor",), ("contributor",)),
    "expenditures": (("payee",), ("payee",)),
    "debts": (("lender",), ("lender",)),
    "receipts": (("source",), ("source",)),
}
_PA_PARSER_FN = {
    "contributions": parse_contributions,
    "expenditures": parse_expenditures,
    "debts": parse_debts,
    "receipts": parse_receipts,
}


@dataclass(slots=True)
class _PALoadCounts:
    inserted: int = 0
    skipped: int = 0
    superseded: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _PAFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


@dataclass(frozen=True, slots=True)
class _PAFilerContext:
    amendment_lookup: Mapping[str, str]
    row_lookup: Mapping[str, Mapping[str, str | None]]


def _iter_pa_mapping_rows(
    rows: Iterable[Mapping[str, str | None]],
    *,
    limit: int | None,
) -> Iterable[Mapping[str, str | None]]:
    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")
        yield row


def _pa_counterparty_location(
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> tuple[str | None, str | None, str | None]:
    counterparty_address = _PA_EXTRACT_FN[data_type](dict(row))["address"]
    if counterparty_address is None:
        return None, None, None
    return counterparty_address.city, counterparty_address.state, counterparty_address.zip5


def _load_pa_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    source_record = _build_pa_source_record(data_source_id, row, data_type=data_type)
    inserted_source_record_id = try_insert_source_record(conn, source_record)
    if inserted_source_record_id is None:
        return False

    extracted = _PA_EXTRACT_FN[data_type](dict(row))
    person_key, organization_key = _PA_ENTITY_KEYS_BY_TYPE[data_type]
    _load_pa_transaction_entities(
        conn,
        source_record_id=inserted_source_record_id,
        data_type=data_type,
        person=extracted[person_key],
        organization=extracted[organization_key],
        address=extracted["address"],
    )
    return True


def _try_load_pa_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    data_source_id: UUID,
    data_type: str,
    manages_outer_transaction: bool,
) -> bool | None:
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return _load_pa_row(conn, row, data_source_id, data_type=data_type)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading PA %s row", data_type)
        return None


def _load_pa_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> _PALoadCounts:
    counts = _PALoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in _iter_pa_mapping_rows(rows, limit=limit):
        inserted = _try_load_pa_row(
            conn,
            row,
            data_source_id=data_source_id,
            data_type=data_type,
            manages_outer_transaction=manages_outer_transaction,
        )
        if inserted is None:
            counts.errors += 1
        elif inserted:
            counts.inserted += 1
        else:
            counts.skipped += 1

    commit_managed_transaction(conn, manages_outer_transaction)
    return counts


def _load_pa_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    year: int,
    limit: int | None = None,
) -> LoadResult:
    row_limit = validated_limit(limit)
    start = time.perf_counter()
    rows = _PA_PARSER_FN[data_type](Path(file_path), year)
    counts = _load_pa_rows(
        conn,
        rows,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=row_limit,
    )
    elapsed_seconds = time.perf_counter() - start
    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=getattr(rows, "skipped", 0),
        superseded=counts.superseded,
        errors=counts.errors,
        elapsed_seconds=elapsed_seconds,
    )


def _resolve_pa_filing_committee_id(
    conn: psycopg.Connection,
    filer_row: Mapping[str, str | None],
) -> UUID:
    extracted = extract_pa_filing(dict(filer_row))
    committee_org_id = _resolve_pa_committee_organization_id(conn, extracted["committee"])
    committee_id_column = _load_column_for_semantic_path("filings", "committee.id")
    native_committee_id = _required_pa_text(filer_row.get(committee_id_column), committee_id_column)
    return ensure_state_committee(
        conn,
        state="PA",
        native_committee_id=native_committee_id,
        organization_id=committee_org_id,
    )


def _upsert_pa_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filer_context: _PAFilerContext,
    filing_lookup: dict[str, _PAFilingLookupEntry],
) -> _PAFilingLookupEntry:
    filer_row = _require_pa_filer_row(row, data_type=data_type, filer_row_lookup=filer_context.row_lookup)
    filing_fec_id = _pa_filing_fec_id_from_filer_row(filer_row, data_type=data_type)
    existing_entry = filing_lookup.get(filing_fec_id)

    amendment_indicator = _resolve_pa_amendment_indicator(
        row,
        data_type=data_type,
        filer_lookup=filer_context.amendment_lookup,
    )
    if amendment_indicator is None:
        raise ValueError(f"PA detail row has unresolved amendment indicator for filing_fec_id={filing_fec_id!r}")

    if existing_entry is None:
        committee_id = _resolve_pa_filing_committee_id(conn, filer_row)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id

    filing = _build_pa_filing(
        filer_row,
        filing_fec_id=filing_fec_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_type=data_type,
        amendment_indicator=amendment_indicator,
    )
    filing_id = upsert_filing(conn, filing)

    entry = _PAFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _upsert_pa_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_entry: _PAFilingLookupEntry,
    source_record_id: UUID,
    data_type: str,
    filer_context: _PAFilerContext,
) -> None:
    amendment_indicator = _resolve_pa_amendment_indicator(
        row,
        data_type=data_type,
        filer_lookup=filer_context.amendment_lookup,
    )
    if amendment_indicator is None:
        raise ValueError("PA transaction row has unresolved amendment indicator")

    person_roles, organization_roles = _PA_COUNTERPARTY_ROLES_BY_TYPE[data_type]
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=organization_roles,
    )
    contributor_address_id = _resolve_pa_transaction_address_id(
        conn, source_record_id=source_record_id, data_type=data_type
    )
    contributor_city, contributor_state, contributor_zip = _pa_counterparty_location(row, data_type=data_type)
    amount_column = _load_column_for_semantic_path(data_type, "transaction.amount")

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_entry.filing_id,
            committee_id=filing_entry.committee_id,
            transaction_type=_pa_transaction_type(data_type),
            transaction_identifier=_pa_transaction_identifier(row, data_type=data_type),
            transaction_date=_pa_transaction_date(row, data_type=data_type),
            amount=_parse_required_pa_amount(row.get(amount_column), amount_column),
            contributor_name_raw=_pa_counterparty_name_raw(row, data_type=data_type),
            contributor_employer=_pa_counterparty_employer(row, data_type=data_type),
            contributor_occupation=_pa_counterparty_occupation(row, data_type=data_type),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=contributor_address_id,
            recipient_committee_id=filing_entry.committee_id,
            amendment_indicator=amendment_indicator,
            source_record_id=source_record_id,
        ),
    )


def _load_pa_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    filer_context: _PAFilerContext,
    limit: int | None,
) -> int:
    filing_lookup: dict[str, _PAFilingLookupEntry] = {}
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    superseded = 0

    for row in _iter_pa_mapping_rows(rows, limit=limit):
        if (
            _resolve_pa_amendment_indicator(row, data_type=data_type, filer_lookup=filer_context.amendment_lookup)
            == "T"
        ):
            superseded += 1

        source_record_id = _select_pa_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_pa_source_record_key(row, data_type=data_type),
        )
        if source_record_id is None:
            continue

        if manages_outer_transaction:
            ensure_transaction_open(conn)

        with conn.transaction():
            filing_entry = _upsert_pa_filing(
                conn,
                row,
                source_record_id=source_record_id,
                data_type=data_type,
                filer_context=filer_context,
                filing_lookup=filing_lookup,
            )
            _upsert_pa_transaction_with_filing(
                conn,
                row,
                filing_entry=filing_entry,
                source_record_id=source_record_id,
                data_type=data_type,
                filer_context=filer_context,
            )

    commit_managed_transaction(conn, manages_outer_transaction)
    return superseded


def _resolve_pa_filings_path(detail_path: Path, *, data_type: str) -> Path:
    """Resolve the PA filings CSV path from a detail file path.

    ZIP archives contain both detail and filer members, so the same path works.
    For non-ZIP files (e.g. test fixtures), derive the sibling filings CSV path
    by replacing the data-type segment in the filename.
    """
    if detail_path.suffix.lower() == ".zip":
        return detail_path
    candidate = detail_path.parent / detail_path.name.replace(data_type, "filings")
    if candidate != detail_path and candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"Cannot locate PA filings CSV alongside {detail_path}; "
        "provide a ZIP archive or place a filings CSV in the same directory"
    )


def _load_pa_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    year: int,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_pa_data_source(conn, data_type=data_type)
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    if manages_outer_transaction:
        ensure_transaction_open(conn)

    try:
        load_result = _load_pa_file(
            conn,
            file_path,
            data_source_id=data_source_id,
            data_type=data_type,
            year=year,
            limit=validated_row_limit,
        )

        filings_path = _resolve_pa_filings_path(Path(file_path), data_type=data_type)
        filer_rows = list(parse_filings(filings_path, year))
        filer_context = _PAFilerContext(
            amendment_lookup=_build_filer_amendment_lookup(filer_rows),
            row_lookup=_build_filer_row_lookup(filer_rows),
        )
        load_result.superseded = _load_pa_relational_transactions(
            conn,
            _PA_PARSER_FN[data_type](Path(file_path), year),
            data_source_id=data_source_id,
            data_type=data_type,
            filer_context=filer_context,
            limit=validated_row_limit,
        )
    except Exception:
        if manages_outer_transaction:
            conn.rollback()
        raise

    if manages_outer_transaction:
        conn.commit()
    return load_result


def load_pa_contributions_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, year: int, limit: int | None = None
) -> LoadResult:
    return _load_pa_with_filings(conn, fp, data_type="contributions", year=year, limit=limit)


def load_pa_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, year: int, limit: int | None = None
) -> LoadResult:
    return _load_pa_with_filings(conn, fp, data_type="expenditures", year=year, limit=limit)


def load_pa_debts_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, year: int, limit: int | None = None
) -> LoadResult:
    return _load_pa_with_filings(conn, fp, data_type="debts", year=year, limit=limit)


def load_pa_receipts_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, year: int, limit: int | None = None
) -> LoadResult:
    return _load_pa_with_filings(conn, fp, data_type="receipts", year=year, limit=limit)
