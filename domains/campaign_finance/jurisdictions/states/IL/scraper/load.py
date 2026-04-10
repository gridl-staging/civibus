
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

from . import (
    _load_column_for_semantic_path,
    _load_data_source_name_for_data_type,
    _load_data_source_url_for_data_type,
)
from .extract import extract_il_contribution, extract_il_expenditure
from .parse import parse_contributions, parse_expenditures

LOGGER = logging.getLogger(__name__)

_IL_DOMAIN = "campaign_finance"
_IL_JURISDICTION = "state/IL"
_IL_SOURCE_FORMAT = "csv"

_RECEIPT_TYPE_BY_PART = {
    "1": "contribution",
    "2": "transfer_in",
    "3": "loan_received",
    "4": "other_receipt",
    "5": "in_kind_contribution",
}
_EXPENDITURE_TYPE_BY_PART = {
    "6": "transfer_out",
    "7": "loan_made",
    "8": "expenditure",
    "9": "independent_expenditure",
}


@dataclass(slots=True)
class _ILLoadCounts:
    inserted: int = 0
    skipped: int = 0
    quarantined: int = 0
    superseded: int = 0


@dataclass(frozen=True, slots=True)
class _ILDataTypeSpec:

    person_key: str
    organization_key: str
    person_roles: tuple[str, ...]
    organization_roles: tuple[str, ...]
    committee_role: str
    address_role: str
    extract_row: Callable[[dict[str, str | None]], dict[str, Any]]
    parse_rows: Callable[[Path], Iterable[Mapping[str, str | None]]]
    date_path: str
    description_path: str
    aggregate_amount_path: str
    archived_path: str
    last_or_business_path: str
    first_name_path: str
    city_path: str
    state_path: str
    zip_path: str
    d2_part_path: str
    employer_path: str | None = None
    occupation_path: str | None = None
    supporting_path: str | None = None
    opposing_path: str | None = None


_IL_DATA_TYPE_SPECS = {
    "contributions": _ILDataTypeSpec(
        person_key="donor_person",
        organization_key="donor_org",
        person_roles=("donor",),
        organization_roles=("contributor",),
        committee_role="recipient",
        address_role="contributor_address",
        extract_row=extract_il_contribution,
        parse_rows=parse_contributions,
        date_path="transaction.date",
        description_path="transaction.description",
        aggregate_amount_path="il.aggregate_amount",
        archived_path="il.archived",
        last_or_business_path="donor.name.last_or_business",
        first_name_path="donor.name.first",
        city_path="donor.address.city",
        state_path="donor.address.state",
        zip_path="donor.address.zip",
        d2_part_path="il.d2_part",
        employer_path="donor.employer",
        occupation_path="donor.occupation",
    ),
    "expenditures": _ILDataTypeSpec(
        person_key="payee_person",
        organization_key="payee_org",
        person_roles=("payee",),
        organization_roles=("payee",),
        committee_role="payer",
        address_role="payee_address",
        extract_row=extract_il_expenditure,
        parse_rows=parse_expenditures,
        date_path="transaction.date",
        description_path="transaction.description",
        aggregate_amount_path="il.aggregate_amount",
        archived_path="il.archived",
        last_or_business_path="payee.name.last_or_business",
        first_name_path="payee.name.first",
        city_path="payee.address.city",
        state_path="payee.address.state",
        zip_path="payee.address.zip",
        d2_part_path="il.d2_part",
        supporting_path="il.supporting",
        opposing_path="il.opposing",
    ),
}


def _il_data_type_spec(data_type: str) -> _ILDataTypeSpec:
    try:
        return _IL_DATA_TYPE_SPECS[data_type]
    except KeyError as error:
        raise ValueError(f"Unsupported IL data type: {data_type}") from error


def _column(data_type: str, semantic_path: str) -> str:
    return _load_column_for_semantic_path(data_type, semantic_path)


def _normalized_column_text(row: Mapping[str, str | None], *, data_type: str, semantic_path: str) -> str | None:
    return normalize_optional_text(row.get(_column(data_type, semantic_path)))


def _required_column_text(row: Mapping[str, str | None], *, data_type: str, semantic_path: str) -> str:
    column_name = _column(data_type, semantic_path)
    normalized_value = normalize_optional_text(row.get(column_name))
    if normalized_value is None:
        raise ValueError(f"IL row is missing {column_name}")
    return normalized_value


def _parse_il_date(raw_value: str | None) -> date | None:
    normalized_value = normalize_optional_text(raw_value)
    if normalized_value is None:
        return None

    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized_value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"IL row has invalid date: {raw_value!r}")


def _parse_optional_amount(raw_value: str | None) -> Decimal | None:
    normalized_value = normalize_optional_text(raw_value)
    if normalized_value is None:
        return None
    try:
        return Decimal(normalized_value.replace(",", ""))
    except InvalidOperation as error:
        raise ValueError(f"IL row has invalid amount: {raw_value!r}") from error


def _parse_required_amount(raw_value: str | None, field_name: str) -> Decimal:
    amount = _parse_optional_amount(raw_value)
    if amount is None:
        raise ValueError(f"IL row is missing {field_name}")
    return amount


def _parse_il_bool(raw_value: str | None) -> bool | None:
    normalized_value = normalize_optional_text(raw_value)
    if normalized_value is None:
        return None
    lowered = normalized_value.casefold()
    if lowered in {"true", "t", "1", "y", "yes"}:
        return True
    if lowered in {"false", "f", "0", "n", "no"}:
        return False
    raise ValueError(f"IL row has invalid boolean value: {raw_value!r}")


def _combine_name(*, last_or_business: str | None, first_name: str | None) -> str | None:
    normalized_last = normalize_optional_text(last_or_business)
    normalized_first = normalize_optional_text(first_name)
    if normalized_last is None and normalized_first is None:
        return None
    if normalized_last is None:
        return normalized_first
    if normalized_first is None:
        return normalized_last
    return f"{normalized_first} {normalized_last}"


def _il_source_record_key(row: Mapping[str, str | None], *, data_type: str) -> str:
    transaction_identifier = _normalized_column_text(row, data_type=data_type, semantic_path="transaction.id")
    if transaction_identifier is not None:
        return transaction_identifier
    return compute_record_hash(dict(row))


def _build_il_source_record(data_source_id: UUID, row: Mapping[str, str | None], *, data_type: str) -> SourceRecord:
    raw_fields = dict(row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_il_source_record_key(row, data_type=data_type),
        source_url=_load_data_source_url_for_data_type(data_type),
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def ensure_il_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_name = _load_data_source_name_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_IL_DOMAIN,
        jurisdiction=_IL_JURISDICTION,
        name=data_source_name,
        source_url=_load_data_source_url_for_data_type(normalized_data_type),
        source_format=_IL_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _resolve_il_committee_organization_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = normalize_optional_text(committee.identifiers.get("il_committee_id"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(conn, "il_committee_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id

    resolved_org_id = resolve_organization_by_canonical_name(conn, committee)
    if resolved_org_id is None:
        raise ValueError("IL committee extraction did not produce a resolvable organization")
    return resolved_org_id


def _load_il_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: dict[str, object],
    data_type: str,
) -> tuple[UUID, UUID | None]:
    spec = _il_data_type_spec(data_type)

    address = extracted["address"]
    address_id: UUID | None = None
    if isinstance(address, Address):
        address_id = upsert_address(conn, address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=spec.address_role,
            address_id=None,
        )

    person = extracted[spec.person_key]
    if isinstance(person, Person):
        person_id = resolve_person_by_name_and_zip(conn, person, address if isinstance(address, Address) else None)
        if person_id is not None:
            link_entity_source_and_optional_mailing_address(
                conn,
                entity_type="person",
                entity_id=person_id,
                source_record_id=source_record_id,
                extraction_role=spec.person_roles[0],
                address_id=address_id,
            )

    organization = extracted[spec.organization_key]
    if isinstance(organization, Organization):
        organization_id = resolve_organization_by_canonical_name(conn, organization)
        if organization_id is not None:
            link_entity_source_and_optional_mailing_address(
                conn,
                entity_type="organization",
                entity_id=organization_id,
                source_record_id=source_record_id,
                extraction_role=spec.organization_roles[0],
                address_id=address_id,
            )

    committee = extracted["committee"]
    if not isinstance(committee, Organization):
        raise ValueError("IL extraction must include committee organization")

    committee_org_id = _resolve_il_committee_organization_id(conn, committee)
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_org_id,
        source_record_id=source_record_id,
        extraction_role=spec.committee_role,
        address_id=None,
    )

    native_committee_id = normalize_optional_text(committee.identifiers.get("il_committee_id"))
    if native_committee_id is None:
        raise ValueError("IL committee extraction must include il_committee_id")

    committee_id = ensure_state_committee(conn, "IL", native_committee_id, committee_org_id)
    return committee_id, address_id


def _il_is_archived(row: Mapping[str, str | None], *, data_type: str) -> bool:
    spec = _il_data_type_spec(data_type)
    return _parse_il_bool(row.get(_column(data_type, spec.archived_path))) is True


def _il_filing_fec_id(row: Mapping[str, str | None], *, data_type: str) -> str:
    filed_doc_id = _required_column_text(row, data_type=data_type, semantic_path="filing.id")
    return f"IL-{filed_doc_id}"


def _upsert_il_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> UUID:
    filing_identifier = _required_column_text(row, data_type=data_type, semantic_path="filing.id")
    filing = Filing(
        filing_fec_id=_il_filing_fec_id(row, data_type=data_type),
        committee_id=committee_id,
        report_type="D-2",
        amendment_indicator="N",
        filing_name=f"FiledDoc {filing_identifier}",
        source_record_id=source_record_id,
    )
    return upsert_filing(conn, filing)


def _il_transaction_type(row: Mapping[str, str | None], *, data_type: str) -> str:
    d2_part = _required_column_text(row, data_type=data_type, semantic_path="il.d2_part")
    leading_digit = d2_part[0]
    if data_type == "contributions":
        return _RECEIPT_TYPE_BY_PART.get(leading_digit, "contribution")
    return _EXPENDITURE_TYPE_BY_PART.get(leading_digit, "expenditure")


def _il_support_oppose(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    spec = _il_data_type_spec(data_type)
    if spec.supporting_path is None or spec.opposing_path is None:
        return None

    supporting = _parse_il_bool(row.get(_column(data_type, spec.supporting_path)))
    opposing = _parse_il_bool(row.get(_column(data_type, spec.opposing_path)))
    if supporting and not opposing:
        return "S"
    if opposing and not supporting:
        return "O"
    return None


def _upsert_il_transaction(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    contributor_address_id: UUID | None,
    data_type: str,
) -> None:
    spec = _il_data_type_spec(data_type)
    counterparty_person_id, counterparty_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=spec.person_roles,
        organization_roles=spec.organization_roles,
    )
    transaction_identifier = _required_column_text(row, data_type=data_type, semantic_path="transaction.id")
    amount = _parse_required_amount(
        row.get(_column(data_type, "transaction.amount")),
        _column(data_type, "transaction.amount"),
    )
    aggregate_amount = _parse_optional_amount(row.get(_column(data_type, spec.aggregate_amount_path)))
    transaction_date = _parse_il_date(row.get(_column(data_type, spec.date_path)))
    contributor_name_raw = _combine_name(
        last_or_business=row.get(_column(data_type, spec.last_or_business_path)),
        first_name=row.get(_column(data_type, spec.first_name_path)),
    )

    contributor_employer = None
    if spec.employer_path is not None:
        contributor_employer = _normalized_column_text(row, data_type=data_type, semantic_path=spec.employer_path)

    contributor_occupation = None
    if spec.occupation_path is not None:
        contributor_occupation = _normalized_column_text(row, data_type=data_type, semantic_path=spec.occupation_path)

    transaction = Transaction(
        filing_id=filing_id,
        committee_id=committee_id,
        transaction_type=_il_transaction_type(row, data_type=data_type),
        transaction_identifier=transaction_identifier,
        sub_id=int(transaction_identifier),
        transaction_date=transaction_date,
        amount=amount,
        contributor_name_raw=contributor_name_raw,
        contributor_employer=contributor_employer,
        contributor_occupation=contributor_occupation,
        contributor_city=_normalized_column_text(row, data_type=data_type, semantic_path=spec.city_path),
        contributor_state=_normalized_column_text(row, data_type=data_type, semantic_path=spec.state_path),
        contributor_zip=_normalized_column_text(row, data_type=data_type, semantic_path=spec.zip_path),
        contributor_person_id=counterparty_person_id,
        contributor_organization_id=counterparty_organization_id,
        contributor_address_id=contributor_address_id,
        recipient_committee_id=committee_id,
        memo_text=_normalized_column_text(row, data_type=data_type, semantic_path=spec.description_path),
        amendment_indicator="N",
        source_record_id=source_record_id,
        date_is_reliable=transaction_date is not None,
        support_oppose=_il_support_oppose(row, data_type=data_type),
        aggregate_amount=aggregate_amount,
    )
    upsert_transaction(conn, transaction)


def _load_il_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    counts = _ILLoadCounts()
    start_time = time.monotonic()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    spec = _il_data_type_spec(data_type)

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        if _il_is_archived(row, data_type=data_type):
            counts.superseded += 1
            continue

        try:
            if manages_outer_transaction:
                ensure_transaction_open(conn)

            with conn.transaction():
                source_record_id = try_insert_source_record(
                    conn,
                    _build_il_source_record(data_source_id, row, data_type=data_type),
                )
                if source_record_id is None:
                    counts.skipped += 1
                    continue

                extracted = spec.extract_row(dict(row))
                committee_id, contributor_address_id = _load_il_entities(
                    conn,
                    source_record_id=source_record_id,
                    extracted=extracted,
                    data_type=data_type,
                )
                filing_id = _upsert_il_filing(
                    conn,
                    row,
                    committee_id=committee_id,
                    source_record_id=source_record_id,
                    data_type=data_type,
                )
                _upsert_il_transaction(
                    conn,
                    row,
                    filing_id=filing_id,
                    committee_id=committee_id,
                    source_record_id=source_record_id,
                    contributor_address_id=contributor_address_id,
                    data_type=data_type,
                )
                counts.inserted += 1
        except Exception:  # noqa: BLE001
            counts.quarantined += 1
            LOGGER.exception("Failed processing IL %s row", data_type)

    commit_managed_transaction(conn, manages_outer_transaction)
    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=counts.quarantined,
        superseded=counts.superseded,
        errors=0,
        elapsed_seconds=time.monotonic() - start_time,
    )


def _load_il_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_il_data_source(conn, data_type=data_type)
    return _load_il_rows(
        conn,
        _il_data_type_spec(data_type).parse_rows(Path(file_path)),
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


def load_il_contributions_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_il_with_filings(conn, fp, data_type="contributions", limit=limit)


def load_il_expenditures_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_il_with_filings(conn, fp, data_type="expenditures", limit=limit)
