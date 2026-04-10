from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from core.db import (
    find_organization_by_identifier,
    resolve_organization_by_canonical_name,
    resolve_person_by_name_and_zip,
    try_insert_source_record,
    upsert_address,
)
from core.types.python.models import (
    Address,
    DataSource,
    Organization,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    resolve_transaction_counterparty_ids,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_data_source,
    ensure_transaction_open,
    iter_rows_with_limit,
    link_entity_source_and_optional_mailing_address,
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import _load_data_source_for_data_type
from .extract import extract_in_contribution, extract_in_expenditure
from .load_helpers import (
    _in_amendment_indicator,
    _in_counterparty_occupation,
    _in_filing_fec_id,
    _in_native_committee_id,
    _in_row_value,
    _in_source_record_key,
    _in_transaction_identifier,
    _in_transaction_type,
    _parse_in_date,
    _required_in_amount_from_row,
)
from .parse import parse_contributions, parse_expenditures

LOGGER = logging.getLogger(__name__)

_IN_DOMAIN = "campaign_finance"
_IN_JURISDICTION = "state/IN"
_IN_SOURCE_FORMAT = "csv"


@dataclass(slots=True)
class _INLoadCounts:
    inserted: int = 0
    skipped: int = 0
    superseded: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _INDataTypeSpec:
    person_key: str
    organization_key: str
    person_role: str
    organization_role: str
    committee_role: str
    address_role: str
    person_roles: tuple[str, ...]
    organization_roles: tuple[str, ...]
    extract_row: Callable[[dict[str, str | None]], dict[str, Any]]
    parse_rows: Callable[[Path], Iterable[Mapping[str, str | None]]]


@dataclass(frozen=True, slots=True)
class _INFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


_IN_DATA_TYPE_SPECS = {
    "contributions": _INDataTypeSpec(
        person_key="donor_person",
        organization_key="donor_org",
        person_role="donor",
        organization_role="contributor",
        committee_role="recipient",
        address_role="contributor_address",
        person_roles=("donor",),
        organization_roles=("contributor",),
        extract_row=extract_in_contribution,
        parse_rows=parse_contributions,
    ),
    "expenditures": _INDataTypeSpec(
        person_key="payee_person",
        organization_key="payee_org",
        person_role="payee",
        organization_role="payee",
        committee_role="payer",
        address_role="payee_address",
        person_roles=("payee",),
        organization_roles=("payee",),
        extract_row=extract_in_expenditure,
        parse_rows=parse_expenditures,
    ),
}


def _in_data_type_spec(data_type: str) -> _INDataTypeSpec:
    try:
        return _IN_DATA_TYPE_SPECS[data_type]
    except KeyError as error:
        raise ValueError(f"Unsupported IN data type: {data_type}") from error


def ensure_in_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_config = _load_data_source_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_IN_DOMAIN,
        jurisdiction=_IN_JURISDICTION,
        name=data_source_config.name,
        source_url=data_source_config.url,
        source_format=_IN_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _in_extract_row(row: Mapping[str, str | None], data_type: str) -> dict[str, Any]:
    spec = _in_data_type_spec(data_type)
    return spec.extract_row(dict(row))


def _build_in_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> SourceRecord:
    raw_fields = dict(row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_in_source_record_key(row, data_type=data_type),
        source_url=_load_data_source_for_data_type(data_type).url,
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _resolve_in_committee_organization_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = normalize_optional_text(committee.identifiers.get("in_committee_id"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(conn, "in_committee_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id

    resolved_org_id = resolve_organization_by_canonical_name(conn, committee)
    if resolved_org_id is None:
        raise ValueError("IN committee extraction did not produce a resolvable organization")
    return resolved_org_id


def _load_in_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: dict[str, Any],
    spec: _INDataTypeSpec,
) -> None:
    address = extracted["address"]
    address_id = None
    if address is not None:
        address_id = upsert_address(conn, address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=spec.address_role,
            address_id=None,
        )

    person_id = resolve_person_by_name_and_zip(conn, extracted[spec.person_key], address)
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=spec.person_role,
            address_id=address_id,
        )

    committee_org_id = _resolve_in_committee_organization_id(conn, extracted["committee"])
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_org_id,
        source_record_id=source_record_id,
        extraction_role=spec.committee_role,
        address_id=None,
    )

    organization_id = resolve_organization_by_canonical_name(conn, extracted[spec.organization_key])
    if organization_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=organization_id,
            source_record_id=source_record_id,
            extraction_role=spec.organization_role,
            address_id=address_id,
        )


def _extract_and_load_in_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    source_record = _build_in_source_record(data_source_id, row, data_type=data_type)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = _in_extract_row(row, data_type)
    spec = _in_data_type_spec(data_type)
    _load_in_transaction_entities(
        conn,
        source_record_id=source_record_id,
        extracted=extracted,
        spec=spec,
    )

    return True


def load_in_contribution(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_in_row(conn, row, data_source_id, data_type="contributions")


def load_in_expenditure(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_in_row(conn, row, data_source_id, data_type="expenditures")


def _try_load_in_row(
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

        # Row-level savepoint for per-row error isolation.
        with conn.transaction():
            return _extract_and_load_in_row(conn, row, data_source_id, data_type=data_type)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading IN %s row", data_type.rstrip("s"))
        return None


def _load_in_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _INLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        try:
            amendment_indicator = _in_amendment_indicator(row, data_type=data_type)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed loading IN %s row: invalid amendment indicator", data_type.rstrip("s"))
            counts.errors += 1
            processed_count = counts.inserted + counts.skipped + counts.errors
            if processed_count % 1_000 == 0:
                commit_managed_transaction(conn, manages_outer_transaction)
            continue

        if amendment_indicator == "T":
            counts.superseded += 1

        inserted = _try_load_in_row(
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

        processed_count = counts.inserted + counts.skipped + counts.errors
        if processed_count % 1_000 == 0:
            commit_managed_transaction(conn, manages_outer_transaction)

    commit_managed_transaction(conn, manages_outer_transaction)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=counts.superseded,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _load_in_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _in_data_type_spec(data_type).parse_rows(Path(file_path))
    return _load_in_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


def load_in_contributions(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    return _load_in_file(conn, fp, data_source_id=data_source_id, data_type="contributions", limit=limit)


def load_in_expenditures(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    return _load_in_file(conn, fp, data_source_id=data_source_id, data_type="expenditures", limit=limit)


def _select_in_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            LIMIT 1
            """,
            (data_source_id, source_record_key),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def _resolve_in_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    extracted = _in_extract_row(row, data_type)
    committee_organization_id = _resolve_in_committee_organization_id(conn, extracted["committee"])
    native_committee_id = _in_native_committee_id(row, data_type=data_type)

    return ensure_state_committee(
        conn,
        state="IN",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
    )


def _build_in_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    extracted = _in_extract_row(row, data_type)
    transaction_date = _parse_in_date(_in_row_value(row, data_type=data_type, semantic_path="transaction.date"))

    return Filing(
        filing_fec_id=_in_filing_fec_id(row, data_type=data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator=_in_amendment_indicator(row, data_type=data_type),
        filing_name=normalize_optional_text(extracted["committee"].canonical_name),
        receipt_date=transaction_date,
        accepted_date=transaction_date,
        source_record_id=source_record_id,
    )


def _upsert_in_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _INFilingLookupEntry],
) -> _INFilingLookupEntry:
    filing_fec_id = _in_filing_fec_id(row, data_type=data_type)
    existing_entry = filing_lookup.get(filing_fec_id)

    if existing_entry is None:
        committee_id = _resolve_in_filing_committee_id(conn, row, data_type)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id

    filing = _build_in_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)

    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise ValueError(
            f"IN filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )

    entry = _INFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None], data_type: str) -> str | None:
    return _counterparty_details(row, data_type)[0]


def _counterparty_details(row: Mapping[str, str | None], data_type: str) -> tuple[str | None, Address | None]:
    extracted = _in_extract_row(row, data_type)
    spec = _in_data_type_spec(data_type)
    address = extracted.get("address")

    person = extracted[spec.person_key]
    if person is not None:
        return normalize_optional_text(person.canonical_name), address

    organization = extracted[spec.organization_key]
    if organization is not None:
        return normalize_optional_text(organization.canonical_name), address

    return None, address


def _resolve_in_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    address_role = _in_data_type_spec(data_type).address_role

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = 'address'
              AND extraction_role = %s
            LIMIT 1
            """,
            (source_record_id, address_role),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def _counterparty_address(row: Mapping[str, str | None], data_type: str) -> Address | None:
    return _counterparty_details(row, data_type)[1]


def _upsert_in_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> None:
    spec = _in_data_type_spec(data_type)
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=spec.person_roles,
        organization_roles=spec.organization_roles,
    )

    contributor_address_id = _resolve_in_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
    )
    contributor_name_raw, counterparty_address = _counterparty_details(row, data_type)

    contributor_city = counterparty_address.city if counterparty_address is not None else None
    contributor_state = counterparty_address.state if counterparty_address is not None else None
    contributor_zip = counterparty_address.zip5 if counterparty_address is not None else None

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=_in_transaction_type(row, data_type=data_type),
            transaction_identifier=_in_transaction_identifier(row, data_type=data_type),
            transaction_date=_parse_in_date(_in_row_value(row, data_type=data_type, semantic_path="transaction.date")),
            amount=_required_in_amount_from_row(row, data_type=data_type, semantic_path="transaction.amount"),
            contributor_name_raw=contributor_name_raw,
            contributor_employer=None,
            contributor_occupation=_in_counterparty_occupation(row, data_type=data_type),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=contributor_address_id,
            recipient_committee_id=committee_id,
            amendment_indicator=_in_amendment_indicator(row, data_type=data_type),
            source_record_id=source_record_id,
        ),
    )


def _load_in_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> None:
    filing_lookup: dict[str, _INFilingLookupEntry] = {}
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_in_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_in_source_record_key(row, data_type=data_type),
        )
        if source_record_id is None:
            continue

        if manages_outer_transaction:
            ensure_transaction_open(conn)

        with conn.transaction():
            filing_entry = _upsert_in_filing(
                conn,
                row,
                source_record_id=source_record_id,
                data_type=data_type,
                filing_lookup=filing_lookup,
            )
            _upsert_in_transaction_with_filing(
                conn,
                row,
                filing_id=filing_entry.filing_id,
                committee_id=filing_entry.committee_id,
                source_record_id=source_record_id,
                data_type=data_type,
            )

    commit_managed_transaction(conn, manages_outer_transaction)


def _load_in_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_in_data_source(conn, data_type=data_type)
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    if manages_outer_transaction:
        ensure_transaction_open(conn)

    try:
        load_result = _load_in_file(
            conn,
            file_path,
            data_source_id=data_source_id,
            data_type=data_type,
            limit=validated_row_limit,
        )
        _load_in_relational_transactions(
            conn,
            _in_data_type_spec(data_type).parse_rows(Path(file_path)),
            data_source_id=data_source_id,
            data_type=data_type,
            limit=validated_row_limit,
        )
    except Exception:
        if manages_outer_transaction:
            conn.rollback()
        raise

    if manages_outer_transaction:
        conn.commit()

    return load_result


def load_in_contributions_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_in_with_filings(conn, fp, data_type="contributions", limit=limit)


def load_in_expenditures_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_in_with_filings(conn, fp, data_type="expenditures", limit=limit)


__all__ = [
    "LoadResult",
    "ensure_in_data_source",
    "load_in_contribution",
    "load_in_expenditure",
    "load_in_contributions",
    "load_in_expenditures",
    "load_in_contributions_with_filings",
    "load_in_expenditures_with_filings",
]
