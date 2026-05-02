"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar22_pm_02_oh_state_pipeline/civibus_dev/domains/campaign_finance/jurisdictions/states/OH/scraper/load.py.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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
    Person,
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

from . import _load_column_for_semantic_path, _load_data_source_for_data_type
from .extract import extract_oh_contribution, extract_oh_expenditure
from .parse import parse_contributions, parse_expenditures

LOGGER = logging.getLogger(__name__)

_OH_DOMAIN = "campaign_finance"
_OH_JURISDICTION = "state/OH"
_OH_SOURCE_FORMAT = "csv"


@dataclass(slots=True)
class _OHLoadCounts:
    inserted: int = 0
    skipped: int = 0
    superseded: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _OHDataTypeSpec:
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
    employer_semantic_path: str | None = None


_OH_DATA_TYPE_SPECS = {
    "contributions": _OHDataTypeSpec(
        person_key="donor_person",
        organization_key="donor_org",
        person_role="donor",
        organization_role="contributor",
        committee_role="recipient",
        address_role="contributor_address",
        person_roles=("donor",),
        organization_roles=("contributor",),
        extract_row=extract_oh_contribution,
        parse_rows=parse_contributions,
        employer_semantic_path="oh.donor_employer_occupation",
    ),
    "expenditures": _OHDataTypeSpec(
        person_key="payee_person",
        organization_key="payee_org",
        person_role="payee",
        organization_role="payee",
        committee_role="payer",
        address_role="payee_address",
        person_roles=("payee",),
        organization_roles=("payee",),
        extract_row=extract_oh_expenditure,
        parse_rows=parse_expenditures,
    ),
}


def _oh_data_type_spec(data_type: str) -> _OHDataTypeSpec:
    try:
        return _OH_DATA_TYPE_SPECS[data_type]
    except KeyError as error:
        raise ValueError(f"Unsupported OH data type: {data_type}") from error


def ensure_oh_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_config = _load_data_source_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_OH_DOMAIN,
        jurisdiction=_OH_JURISDICTION,
        name=data_source_config.name,
        source_url=data_source_config.url,
        source_format=_OH_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _required_oh_text(value: str | None, field_name: str) -> str:
    normalized_value = normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"OH row is missing {field_name}")
    return normalized_value


def _parse_oh_date(raw_value: str | None) -> date | None:
    normalized_value = normalize_optional_text(raw_value)
    if normalized_value is None:
        return None

    try:
        return datetime.strptime(normalized_value, "%m/%d/%Y").date()
    except ValueError as error:
        raise ValueError(f"OH row has invalid MM/DD/YYYY date: {raw_value!r}") from error


def _parse_required_oh_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized_value = _required_oh_text(raw_value, field_name)
    try:
        return Decimal(normalized_value.replace(",", ""))
    except InvalidOperation as error:
        raise ValueError(f"OH row has invalid {field_name}: {raw_value!r}") from error


def _oh_source_record_key(row: Mapping[str, str | None]) -> str:
    # OH has no native per-row transaction identifier in bulk CSVs.
    return compute_record_hash(dict(row))


def _oh_row_value(
    row: Mapping[str, str | None],
    *,
    data_type: str,
    semantic_path: str,
) -> str | None:
    return row.get(_load_column_for_semantic_path(data_type, semantic_path))


def _required_oh_row_value(
    row: Mapping[str, str | None],
    *,
    data_type: str,
    semantic_path: str,
) -> str:
    column_name = _load_column_for_semantic_path(data_type, semantic_path)
    return _required_oh_text(row.get(column_name), column_name)


def _required_oh_amount_from_row(
    row: Mapping[str, str | None],
    *,
    data_type: str,
    semantic_path: str,
) -> Decimal:
    column_name = _load_column_for_semantic_path(data_type, semantic_path)
    return _parse_required_oh_amount(row.get(column_name), column_name)


def _oh_filing_fec_id(row: Mapping[str, str | None], *, data_type: str) -> str:
    committee_identifier = _required_oh_row_value(row, data_type=data_type, semantic_path="committee.id")
    report_year = _required_oh_row_value(row, data_type=data_type, semantic_path="transaction.year")
    report_identifier = _required_oh_row_value(row, data_type=data_type, semantic_path="transaction.report_id")
    # REPORT_KEY is the Ohio filing-native identifier, so include it to keep
    # separate reports in the same committee/year bucket from colliding.
    return f"OH-{committee_identifier}-{report_year}-{report_identifier}-{data_type}"


def _oh_amendment_indicator(_row: Mapping[str, str | None]) -> str:
    # Stage 1 verified no amendment indicator column in OH bulk CSV exports.
    return "N"


def _oh_transaction_type(row: Mapping[str, str | None], *, data_type: str) -> str:
    short_description = (
        normalize_optional_text(_oh_row_value(row, data_type=data_type, semantic_path="oh.short_description")) or ""
    ).lower()

    if "contribution" in short_description:
        return "contribution"
    if "expenditure" in short_description:
        return "expenditure"

    return data_type.rstrip("s")


def _oh_counterparty_employer(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    employer_semantic_path = _oh_data_type_spec(data_type).employer_semantic_path
    if employer_semantic_path is None:
        return None

    return normalize_optional_text(_oh_row_value(row, data_type=data_type, semantic_path=employer_semantic_path))


def _oh_extract_row(row: Mapping[str, str | None], data_type: str) -> dict[str, Any]:
    return _oh_data_type_spec(data_type).extract_row(dict(row))


def _build_oh_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> SourceRecord:
    raw_fields = dict(row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_oh_source_record_key(row),
        source_url=_load_data_source_for_data_type(data_type).url,
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _resolve_oh_committee_organization_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = normalize_optional_text(committee.identifiers.get("oh_committee_id"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(conn, "oh_committee_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id

    resolved_org_id = resolve_organization_by_canonical_name(conn, committee)
    if resolved_org_id is None:
        raise ValueError("OH committee extraction did not produce a resolvable organization")
    return resolved_org_id


def _link_oh_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: dict[str, Any],
    person_key: str,
    organization_key: str,
    person_role: str,
    organization_role: str,
    committee_role: str,
    address_role: str,
) -> tuple[UUID | None, UUID]:
    """Link extracted entities to source record. Returns (address_id, committee_org_id)."""
    address = extracted["address"]
    address_id = None
    if address is not None:
        address_id = upsert_address(conn, address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=address_role,
            address_id=None,
        )

    person_id = resolve_person_by_name_and_zip(conn, extracted[person_key], address)
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=person_role,
            address_id=address_id,
        )

    committee_org_id = _resolve_oh_committee_organization_id(conn, extracted["committee"])
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_org_id,
        source_record_id=source_record_id,
        extraction_role=committee_role,
        address_id=None,
    )

    organization_id = resolve_organization_by_canonical_name(conn, extracted[organization_key])
    if organization_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=organization_id,
            source_record_id=source_record_id,
            extraction_role=organization_role,
            address_id=address_id,
        )

    return address_id, committee_org_id


def _counterparty_name_raw(
    person: Person | None,
    organization: Organization | None,
) -> str | None:
    if person is not None:
        return normalize_optional_text(person.canonical_name)
    if organization is not None:
        return normalize_optional_text(organization.canonical_name)
    return None


def _load_oh_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    spec = _oh_data_type_spec(data_type)
    extracted = _oh_extract_row(row, data_type)

    source_record = _build_oh_source_record(data_source_id, row, data_type=data_type)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    address_id, committee_organization_id = _link_oh_transaction_entities(
        conn,
        source_record_id=source_record_id,
        extracted=extracted,
        person_key=spec.person_key,
        organization_key=spec.organization_key,
        person_role=spec.person_role,
        organization_role=spec.organization_role,
        committee_role=spec.committee_role,
        address_role=spec.address_role,
    )

    native_committee_id = _required_oh_row_value(row, data_type=data_type, semantic_path="committee.id")
    committee_id = ensure_state_committee(
        conn,
        state="OH",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
    )

    transaction_date = _parse_oh_date(_oh_row_value(row, data_type=data_type, semantic_path="transaction.date"))

    filing_id = upsert_filing(
        conn,
        Filing(
            filing_fec_id=_oh_filing_fec_id(row, data_type=data_type),
            committee_id=committee_id,
            report_type=data_type,
            amendment_indicator=_oh_amendment_indicator(row),
            filing_name=normalize_optional_text(extracted["committee"].canonical_name),
            receipt_date=transaction_date,
            accepted_date=transaction_date,
            source_record_id=source_record_id,
        ),
    )

    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=spec.person_roles,
        organization_roles=spec.organization_roles,
    )

    address: Address | None = extracted["address"]

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=_oh_transaction_type(row, data_type=data_type),
            transaction_identifier=_oh_source_record_key(row),
            transaction_date=transaction_date,
            amount=_required_oh_amount_from_row(row, data_type=data_type, semantic_path="transaction.amount"),
            contributor_name_raw=_counterparty_name_raw(
                extracted[spec.person_key],
                extracted[spec.organization_key],
            ),
            # OH publishes one combined EMP_OCCUPATION field (unlike TX's 3-field
            # employer/occupation/employer_type split and PA's 2-field
            # employer/occupation split). Keep it as employer text and leave
            # occupation unset until OH SOS provides structured data.
            contributor_employer=_oh_counterparty_employer(row, data_type=data_type),
            contributor_occupation=None,
            contributor_city=address.city if address is not None else None,
            contributor_state=address.state if address is not None else None,
            contributor_zip=address.zip5 if address is not None else None,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=address_id,
            recipient_committee_id=committee_id,
            amendment_indicator=_oh_amendment_indicator(row),
            source_record_id=source_record_id,
        ),
    )

    return True


def _try_load_oh_row(
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
            return _load_oh_row(conn, row, data_source_id, data_type=data_type)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading OH %s row", data_type.rstrip("s"))
        return None


def _load_oh_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _OHLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        if _oh_amendment_indicator(row) == "T":
            counts.superseded += 1

        inserted = _try_load_oh_row(
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

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=counts.superseded,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _load_oh_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _oh_data_type_spec(data_type).parse_rows(Path(file_path))
    return _load_oh_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


def _load_oh_data_type(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    if manages_outer_transaction:
        ensure_transaction_open(conn)

    try:
        data_source_id = ensure_oh_data_source(conn, data_type=data_type)
        load_result = _load_oh_file(
            conn,
            file_path,
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


def load_oh_contributions(conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None) -> LoadResult:
    return _load_oh_data_type(conn, fp, data_type="contributions", limit=limit)


def load_oh_expenditures(conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None) -> LoadResult:
    return _load_oh_data_type(conn, fp, data_type="expenditures", limit=limit)
