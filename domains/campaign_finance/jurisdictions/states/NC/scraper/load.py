
from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg

from core.db import (
    find_organization_by_identifier,
    insert_organization,
    resolve_organization_by_canonical_name,
    resolve_person_by_name_and_zip,
    try_insert_source_record,
    upsert_address,
)
from core.types.python.models import Organization, compute_record_hash
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    resolve_transaction_counterparty_ids,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    commit_managed_transaction,
    ensure_transaction_open,
    iter_rows_with_limit,
    link_entity_source_and_optional_mailing_address,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import load_support
from .extract import extract_nc_transaction
from .load_support import (
    build_nc_source_record as _build_nc_source_record,
    ensure_nc_committee_document_data_source,
    ensure_nc_data_source,
    select_nc_source_record_id as _select_nc_source_record_id,
)
from .load_types import (
    LoadResult,
    NCFilingLookupEntry,
    _NCLoadCounts,
    _NCRowLoadConfig,
    _NCRowLoader,
    _NCTransactionEntities,
)
from .parse import (
    parse_amendment_flag,
    parse_committee_docs,
    parse_nc_amount,
    parse_nc_date,
    parse_transactions,
)

LOGGER = logging.getLogger(__name__)
build_data_source = load_support.build_data_source
_NC_ROW_LOADER_TYPE = _NCRowLoader

_NC_TRANSACTION_ENTITY_ROLES = {
    "person": "donor",
    "organization": "contributor",
    "committee": "recipient",
    "address": "contributor_address",
}
_NCFilingLookupKey = tuple[str, str]
_normalize_optional_text = normalize_optional_text


def _iter_nc_rows(
    rows: Iterable[Mapping[str, str | None]],
    *,
    limit: int | None,
) -> Iterable[Mapping[str, str | None]]:
    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")
        yield row


def _build_load_result(
    counts: _NCLoadCounts,
    *,
    rows: object,
    started_at: float,
) -> LoadResult:
    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _build_transaction_row_load_config(data_source_id: UUID) -> _NCRowLoadConfig:
    return _NCRowLoadConfig(
        load_row=load_nc_transaction,
        row_type_label="transaction",
        data_source_id=data_source_id,
    )


def _resolve_nc_committee_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_id = committee.identifiers.get("nc_sboe_id")
    if committee_id:
        existing_org_id = find_organization_by_identifier(conn, "nc_sboe_id", committee_id)
        if existing_org_id is not None:
            return existing_org_id

    return insert_organization(conn, committee)


def _load_nc_transaction_entities(
    conn: psycopg.Connection,
    source_record_id: UUID,
    entities: _NCTransactionEntities,
) -> None:
    address_id = None
    if entities.address is not None:
        address_id = upsert_address(conn, entities.address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=_NC_TRANSACTION_ENTITY_ROLES["address"],
            address_id=None,
        )

    person_id = resolve_person_by_name_and_zip(conn, entities.person, entities.address)
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=_NC_TRANSACTION_ENTITY_ROLES["person"],
            address_id=address_id,
        )

    committee_id = _resolve_nc_committee_id(conn, entities.committee)
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_id,
        source_record_id=source_record_id,
        extraction_role=_NC_TRANSACTION_ENTITY_ROLES["committee"],
        address_id=None,
    )

    contributor_org_id = resolve_organization_by_canonical_name(conn, entities.contributor_org)
    if contributor_org_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=contributor_org_id,
            source_record_id=source_record_id,
            extraction_role=_NC_TRANSACTION_ENTITY_ROLES["organization"],
            address_id=address_id,
        )


def load_nc_transaction(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> bool:
    source_record = _build_nc_source_record(data_source_id, row)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = extract_nc_transaction(dict(row))
    _load_nc_transaction_entities(
        conn,
        source_record_id=source_record_id,
        entities=_NCTransactionEntities(
            person=extracted["person"],
            contributor_org=extracted["contributor_org"],
            committee=extracted["committee"],
            address=extracted["address"],
        ),
    )

    return True


def _require_text(value: str | None, field_name: str) -> str:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"NC row is missing required {field_name}")
    return normalized_value


def _parse_optional_date(raw_value: str | None) -> date | None:
    parsed = parse_nc_date(raw_value)
    if parsed is None:
        return None
    return date.fromisoformat(parsed)


def _require_amount(raw_value: str | None) -> Decimal:
    parsed = parse_nc_amount(raw_value)
    if parsed is None:
        raise ValueError("NC row is missing required Amount")
    return parsed


def _to_amendment_indicator(raw_amendment: str | None) -> str:
    is_amendment = parse_amendment_flag(raw_amendment)
    if is_amendment:
        return "A"
    return "N"


def normalize_nc_report_key(year: str | None, doc_name: str | None) -> str:
    normalized_year = _require_text(year, "Year")
    normalized_doc_name = _require_text(doc_name, "Doc Name")
    return f"{normalized_year} {normalized_doc_name}"


def _normalize_nc_transaction_report_key(report_name: str | None) -> str:
    normalized_report_name = _require_text(report_name, "Report Name")
    report_parts = normalized_report_name.split(" ", maxsplit=1)
    if len(report_parts) != 2:
        raise ValueError(f"NC Report Name is not in '<year> <doc name>' format: {normalized_report_name!r}")
    return normalize_nc_report_key(report_parts[0], report_parts[1])


def _normalize_nc_sboe_id(raw_sboe_id: str | None) -> str:
    return _require_text(raw_sboe_id, "SBoE ID")


def _doc_name_slug(raw_doc_name: str | None) -> str:
    normalized_doc_name = _require_text(raw_doc_name, "Doc Name")
    return normalized_doc_name.lower().replace(" ", "-")


def _build_nc_filing_fec_id(row: Mapping[str, str | None]) -> str:
    sboe_id = _normalize_nc_sboe_id(row.get("SBoE ID"))
    year = _require_text(row.get("Year"), "Year")
    doc_name_slug = _doc_name_slug(row.get("Doc Name"))
    return f"NC-{sboe_id}-{year}-{doc_name_slug}"


def _build_nc_committee_bridge_org(
    *,
    committee_sboe_id: str,
    committee_name: str,
) -> Organization:
    normalized_committee_name = _require_text(committee_name, "Committee Name")
    return Organization(
        canonical_name=f"{normalized_committee_name} {committee_sboe_id}",
        identifiers={"nc_sboe_id": committee_sboe_id},
    )


def _resolve_nc_committee_bridge(
    conn: psycopg.Connection,
    committee_sboe_id: str,
    *,
    committee_name: str | None = None,
) -> UUID:
    organization_id = find_organization_by_identifier(conn, "nc_sboe_id", committee_sboe_id)
    if organization_id is None:
        if committee_name is None:
            raise ValueError(
                f"No core.organization bridge exists for NC committee identifier nc_sboe_id={committee_sboe_id!r}"
            )
        organization_id = insert_organization(
            conn,
            _build_nc_committee_bridge_org(
                committee_sboe_id=committee_sboe_id,
                committee_name=committee_name,
            ),
        )
    return ensure_state_committee(
        conn,
        state="NC",
        native_committee_id=committee_sboe_id,
        organization_id=organization_id,
    )


def build_nc_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> Filing:
    return Filing(
        filing_fec_id=_build_nc_filing_fec_id(row),
        committee_id=committee_id,
        report_type=_normalize_optional_text(row.get("Doc Type")),
        amendment_indicator=_to_amendment_indicator(row.get("Amend")),
        filing_name=_normalize_optional_text(row.get("Doc Name")),
        coverage_start_date=_parse_optional_date(row.get("Start Date")),
        coverage_end_date=_parse_optional_date(row.get("End Date")),
        receipt_date=_parse_optional_date(row.get("Received Data")),
        accepted_date=_parse_optional_date(row.get("Received Image")),
        source_record_id=source_record_id,
    )


def _resolve_committee_doc_source_record(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> tuple[UUID, bool]:
    source_record = _build_nc_source_record(data_source_id, row)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is not None:
        return source_record_id, True

    existing_source_record_id = _select_nc_source_record_id(
        conn,
        data_source_id=data_source_id,
        source_record_key=source_record.source_record_key,
    )
    if existing_source_record_id is None:
        raise RuntimeError(
            "Committee-document source_record insert reported conflict but existing source_record row was not found"
        )
    return existing_source_record_id, False


def _select_nc_filing_lookup_entry(
    conn: psycopg.Connection,
    *,
    filing_id: UUID,
    expected_filing_fec_id: str,
) -> NCFilingLookupEntry:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id, committee_id, amendment_indicator, source_record_id
            FROM cf.filing
            WHERE id = %s
            LIMIT 1
            """,
            (filing_id,),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"NC filing upsert returned filing_id={filing_id} but no cf.filing row was found")

    filing_fec_id, committee_id, amendment_indicator, source_record_id = row
    if filing_fec_id != expected_filing_fec_id:
        raise RuntimeError(
            "NC filing lookup entry drifted from expected filing_fec_id "
            f"{expected_filing_fec_id!r}: got {filing_fec_id!r}"
        )

    return NCFilingLookupEntry(
        filing_id=filing_id,
        filing_fec_id=filing_fec_id,
        committee_id=committee_id,
        amendment_indicator=amendment_indicator,
        source_record_id=source_record_id,
    )


def _upsert_committee_document_filing(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, str | None],
    committee_document_data_source_id: UUID,
    filing_lookup: dict[_NCFilingLookupKey, NCFilingLookupEntry],
) -> bool:
    source_record_id, inserted_source_record = _resolve_committee_doc_source_record(
        conn,
        row=row,
        data_source_id=committee_document_data_source_id,
    )

    # Skip rows with blank Doc Name (e.g. Statement of Organization) — they
    # are administrative records that cannot participate in the filing join.
    # Keep their source_record so committee-document provenance stays intact.
    raw_doc_name = _normalize_optional_text(row.get("Doc Name"))
    if raw_doc_name is None:
        return inserted_source_record
    committee_sboe_id = _normalize_nc_sboe_id(row.get("SBoE ID"))
    report_key = normalize_nc_report_key(row.get("Year"), row.get("Doc Name"))
    lookup_key = (committee_sboe_id, report_key)

    committee_id = _resolve_nc_committee_bridge(
        conn,
        committee_sboe_id,
        committee_name=row.get("Committee Name"),
    )
    existing_entry = filing_lookup.get(lookup_key)
    filing_source_record_id = source_record_id if existing_entry is None else existing_entry.source_record_id
    filing = build_nc_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_id = upsert_filing(conn, filing)
    entry = _select_nc_filing_lookup_entry(
        conn,
        filing_id=filing_id,
        expected_filing_fec_id=filing.filing_fec_id,
    )
    if existing_entry is not None and existing_entry.filing_fec_id != entry.filing_fec_id:
        raise ValueError(
            "Ambiguous NC committee-document filing lookup key "
            f"{lookup_key!r}: {existing_entry.filing_fec_id!r} != {entry.filing_fec_id!r}"
        )
    filing_lookup[lookup_key] = entry
    return inserted_source_record


def build_nc_filing_lookup(
    conn: psycopg.Connection,
    committee_document_rows: Iterable[Mapping[str, str | None]],
    *,
    committee_document_data_source_id: UUID,
    limit: int | None = None,
) -> tuple[LoadResult, dict[_NCFilingLookupKey, NCFilingLookupEntry]]:
    started_at = time.monotonic()
    counts = _NCLoadCounts()
    filing_lookup: dict[_NCFilingLookupKey, NCFilingLookupEntry] = {}
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in _iter_nc_rows(committee_document_rows, limit=limit):
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            inserted = _upsert_committee_document_filing(
                conn,
                row=row,
                committee_document_data_source_id=committee_document_data_source_id,
                filing_lookup=filing_lookup,
            )
        if inserted:
            counts.inserted += 1
        else:
            counts.skipped += 1

        _maybe_commit_and_log_progress(
            conn,
            row_type_label="committee_document",
            counts=counts,
            manages_outer_transaction=manages_outer_transaction,
        )

    commit_managed_transaction(conn, manages_outer_transaction)

    return (
        _build_load_result(
            counts,
            rows=committee_document_rows,
            started_at=started_at,
        ),
        filing_lookup,
    )


def load_nc_committee_documents(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> tuple[LoadResult, dict[_NCFilingLookupKey, NCFilingLookupEntry]]:
    parser = parse_committee_docs(Path(file_path))
    return build_nc_filing_lookup(
        conn,
        parser,
        committee_document_data_source_id=data_source_id,
        limit=limit,
    )


def _upsert_transaction_with_filing_lookup(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, str | None],
    transaction_data_source_id: UUID,
    filing_lookup: Mapping[_NCFilingLookupKey, NCFilingLookupEntry],
) -> None:
    transaction_source_record = _build_nc_source_record(transaction_data_source_id, row)
    source_record_key = transaction_source_record.source_record_key
    source_record_id = _select_nc_source_record_id(
        conn,
        data_source_id=transaction_data_source_id,
        source_record_key=source_record_key,
    )
    if source_record_id is None:
        raise RuntimeError(f"Transaction source_record was not found for source_record_key={source_record_key!r}")

    committee_sboe_id = _normalize_nc_sboe_id(row.get("Committee SBoE ID"))
    report_key = _normalize_nc_transaction_report_key(row.get("Report Name"))
    lookup_key = (committee_sboe_id, report_key)
    filing_entry = filing_lookup.get(lookup_key)
    if filing_entry is None:
        raise ValueError(
            "No NC filing join match for transaction row using key "
            f"(SBoE ID={committee_sboe_id!r}, report_key={report_key!r})"
        )

    committee_id = _resolve_nc_committee_bridge(conn, committee_sboe_id)
    if committee_id != filing_entry.committee_id:
        raise ValueError(
            "NC filing join resolved mismatched committee IDs: "
            f"transaction committee_id={committee_id}, filing committee_id={filing_entry.committee_id}"
        )

    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=("donor",),
        organization_roles=("contributor",),
    )
    contributor_state = _normalize_optional_text(row.get("State"))
    normalized_contributor_state = contributor_state.upper() if contributor_state is not None else None

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_entry.filing_id,
            committee_id=committee_id,
            transaction_type=_require_text(row.get("Transction Type"), "Transction Type"),
            transaction_identifier=source_record_key,
            transaction_date=_parse_optional_date(row.get("Date Occured")),
            amount=_require_amount(row.get("Amount")),
            contributor_name_raw=_normalize_optional_text(row.get("Name")),
            contributor_employer=_normalize_optional_text(row.get("Employer's Name/Specific Field")),
            contributor_occupation=_normalize_optional_text(row.get("Profession/Job Title")),
            contributor_city=_normalize_optional_text(row.get("City")),
            contributor_state=normalized_contributor_state,
            contributor_zip=_normalize_optional_text(row.get("Zip Code")),
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            amendment_indicator=filing_entry.amendment_indicator,
            source_record_id=source_record_id,
        ),
    )


def _load_nc_relational_transactions(
    conn: psycopg.Connection,
    transaction_rows: Iterable[Mapping[str, str | None]],
    *,
    transaction_data_source_id: UUID,
    filing_lookup: Mapping[_NCFilingLookupKey, NCFilingLookupEntry],
    limit: int | None = None,
) -> None:
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in _iter_nc_rows(transaction_rows, limit=limit):
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            _upsert_transaction_with_filing_lookup(
                conn,
                row=row,
                transaction_data_source_id=transaction_data_source_id,
                filing_lookup=filing_lookup,
            )

    commit_managed_transaction(conn, manages_outer_transaction)


def _try_load_nc_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    row_load_config: _NCRowLoadConfig,
    manages_outer_transaction: bool,
) -> bool | None:
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return row_load_config.load_row(conn, row, row_load_config.data_source_id)
    except Exception:  # noqa: BLE001
        LOGGER.exception(
            "Failed loading NC %s row source_record_key=%s",
            row_load_config.row_type_label,
            compute_record_hash(dict(row)),
        )
        return None


def _maybe_commit_and_log_progress(
    conn: psycopg.Connection,
    *,
    row_type_label: str,
    counts: _NCLoadCounts,
    manages_outer_transaction: bool,
) -> None:
    processed_count = counts.inserted + counts.skipped + counts.errors
    if processed_count % 1_000 == 0:
        commit_managed_transaction(conn, manages_outer_transaction)

    if processed_count % 10_000 == 0:
        LOGGER.info(
            "NC %s load progress processed=%s inserted=%s skipped=%s errors=%s",
            row_type_label,
            processed_count,
            counts.inserted,
            counts.skipped,
            counts.errors,
        )


def _load_nc_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    row_load_config: _NCRowLoadConfig,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _NCLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in _iter_nc_rows(rows, limit=limit):
        inserted_row = _try_load_nc_row(
            conn,
            row,
            row_load_config,
            manages_outer_transaction=manages_outer_transaction,
        )

        if inserted_row is None:
            counts.errors += 1
        elif inserted_row:
            counts.inserted += 1
        else:
            counts.skipped += 1

        _maybe_commit_and_log_progress(
            conn,
            row_type_label=row_load_config.row_type_label,
            counts=counts,
            manages_outer_transaction=manages_outer_transaction,
        )

    commit_managed_transaction(conn, manages_outer_transaction)

    return _build_load_result(
        counts,
        rows=rows,
        started_at=started_at,
    )


def load_nc_transactions(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    parser = parse_transactions(Path(file_path))
    return _load_nc_rows(
        conn,
        parser,
        _build_transaction_row_load_config(data_source_id),
        limit=limit,
    )


def load_nc_transactions_with_filings(
    conn: psycopg.Connection,
    transaction_file_path: str | Path,
    committee_document_file_path: str | Path,
    *,
    limit: int | None = None,
    committee_document_limit: int | None = None,
) -> LoadResult:
    transaction_data_source_id = ensure_nc_data_source(conn)
    committee_document_data_source_id = ensure_nc_committee_document_data_source(conn)
    _, filing_lookup = load_nc_committee_documents(
        conn,
        committee_document_file_path,
        data_source_id=committee_document_data_source_id,
        limit=committee_document_limit,
    )
    parser = parse_transactions(Path(transaction_file_path))
    transaction_rows = list(parser)
    quarantined = parser.skipped

    transaction_load_result = _load_nc_rows(
        conn,
        iter(transaction_rows),
        _build_transaction_row_load_config(transaction_data_source_id),
        limit=limit,
    )
    transaction_load_result.quarantined = quarantined

    _load_nc_relational_transactions(
        conn,
        iter(transaction_rows),
        transaction_data_source_id=transaction_data_source_id,
        filing_lookup=filing_lookup,
        limit=limit,
    )
    return transaction_load_result
