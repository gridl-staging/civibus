
from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
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
    link_entity_source_and_optional_mailing_address,
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import (
    _load_column_for_semantic_path,
    _load_data_source_name_for_data_type,
    _load_data_source_url_for_data_type,
)
from .extract import extract_mn_contribution, extract_mn_expenditure, extract_mn_independent_expenditure
from .parse import parse_contributions, parse_expenditures, parse_independent_expenditures

LOGGER = logging.getLogger(__name__)

_MN_DOMAIN = "campaign_finance"
_MN_JURISDICTION = "state/MN"
_MN_SOURCE_FORMAT = "csv"
_normalize_optional_text = normalize_optional_text


@dataclass(slots=True)
class _MNLoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _MNTransactionEntities:
    person: Person | None
    organization: Organization | None
    committee: Organization
    address: Address | None


@dataclass(frozen=True, slots=True)
class _MNTransactionRoles:
    person: str
    organization: str
    committee: str
    address: str


@dataclass(frozen=True, slots=True)
class _MNFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


_MN_ENTITY_ROLES_BY_TYPE = {
    "contributions": _MNTransactionRoles(
        person="donor", organization="contributor", committee="recipient", address="contributor_address"
    ),
    "expenditures": _MNTransactionRoles(
        person="payee", organization="payee", committee="payer", address="payee_address"
    ),
    "independent_expenditures": _MNTransactionRoles(
        person="payee", organization="payee", committee="payer", address="payee_address"
    ),
}
_MN_COUNTERPARTY_ROLES_BY_TYPE = {
    "contributions": (("donor",), ("contributor",)),
    "expenditures": (("payee",), ("payee",)),
    "independent_expenditures": (("payee",), ("payee",)),
}
_MN_EXTRACT_FN = {
    "contributions": extract_mn_contribution,
    "expenditures": extract_mn_expenditure,
    "independent_expenditures": extract_mn_independent_expenditure,
}
_MN_ENTITY_KEYS = {
    "contributions": ("donor_person", "donor_org"),
    "expenditures": ("payee_person", "payee_org"),
    "independent_expenditures": ("payee_person", "payee_org"),
}
_MN_PARSER_FN = {
    "contributions": parse_contributions,
    "expenditures": parse_expenditures,
    "independent_expenditures": parse_independent_expenditures,
}
_MN_COUNTERPARTY_NAME_PATH = {
    "contributions": "donor.name",
    "expenditures": "payee.name",
    "independent_expenditures": "payee.name",
}
_MN_COUNTERPARTY_EMPLOYER_PATH = {"contributions": "donor.employer"}


def ensure_mn_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_name = _load_data_source_name_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_MN_DOMAIN,
        jurisdiction=_MN_JURISDICTION,
        name=data_source_name,
        source_url=_load_data_source_url_for_data_type(normalized_data_type),
        source_format=_MN_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _mn_source_record_key(row: Mapping[str, str | None]) -> str:
    return compute_record_hash(dict(row))


def _build_mn_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> SourceRecord:
    raw_fields = dict(row)
    record_hash = compute_record_hash(raw_fields)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=record_hash,
        source_url=_load_data_source_url_for_data_type(data_type),
        raw_fields=raw_fields,
        record_hash=record_hash,
        pull_date=utc_now(),
    )


def _resolve_mn_committee_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = _normalize_optional_text(committee.identifiers.get("mn_committee_reg_num"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(conn, "mn_committee_reg_num", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id
    return resolve_organization_by_canonical_name(conn, committee)


def _load_mn_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    entities: _MNTransactionEntities,
    roles: _MNTransactionRoles,
) -> None:
    address_id = None
    if entities.address is not None:
        address_id = upsert_address(conn, entities.address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=roles.address,
            address_id=None,
        )

    person_id = resolve_person_by_name_and_zip(conn, entities.person, entities.address)
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=roles.person,
            address_id=address_id,
        )

    committee_id = _resolve_mn_committee_id(conn, entities.committee)
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_id,
        source_record_id=source_record_id,
        extraction_role=roles.committee,
        address_id=None,
    )

    organization_id = resolve_organization_by_canonical_name(conn, entities.organization)
    if organization_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=organization_id,
            source_record_id=source_record_id,
            extraction_role=roles.organization,
            address_id=address_id,
        )


def _load_mn_transaction_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
    entities: _MNTransactionEntities,
    roles: _MNTransactionRoles,
) -> bool:
    source_record_id = try_insert_source_record(conn, _build_mn_source_record(data_source_id, row, data_type=data_type))
    if source_record_id is None:
        return False

    _load_mn_transaction_entities(
        conn,
        source_record_id=source_record_id,
        entities=entities,
        roles=roles,
    )
    return True


def _extract_mn_row(
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> dict[str, object]:
    extract_fn = _MN_EXTRACT_FN.get(data_type)
    if extract_fn is None:
        raise ValueError(f"Unsupported MN data_type: {data_type}")
    return extract_fn(dict(row))


def _extract_and_load_mn_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    extracted = _extract_mn_row(row, data_type=data_type)
    person_key, organization_key = _MN_ENTITY_KEYS[data_type]
    return _load_mn_transaction_row(
        conn,
        row,
        data_source_id,
        data_type=data_type,
        entities=_MNTransactionEntities(
            person=extracted[person_key],
            organization=extracted[organization_key],
            committee=extracted["committee"],
            address=extracted["address"],
        ),
        roles=_MN_ENTITY_ROLES_BY_TYPE[data_type],
    )


def load_mn_contribution(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> bool:
    return _extract_and_load_mn_row(conn, row, data_source_id, data_type="contributions")


def load_mn_expenditure(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> bool:
    return _extract_and_load_mn_row(conn, row, data_source_id, data_type="expenditures")


def _try_load_row(
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
            return _extract_and_load_mn_row(conn, row, data_source_id, data_type=data_type)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading MN %s row", data_type.rstrip("s"))
        return None


def _load_mn_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _MNLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        inserted = _try_load_row(
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
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def load_mn_contributions(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    return _load_mn_file(conn, file_path, data_source_id=data_source_id, data_type="contributions", limit=limit)


def load_mn_expenditures(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    return _load_mn_file(conn, file_path, data_source_id=data_source_id, data_type="expenditures", limit=limit)


def _load_mn_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _MN_PARSER_FN[data_type](Path(file_path))
    return _load_mn_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


def _select_mn_source_record_id(
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


def _required_mn_text(value: str | None, field_name: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise ValueError(f"MN row is missing {field_name}")
    return normalized


def _parse_optional_mn_date(raw_value: str | None) -> date | None:
    normalized = _normalize_optional_text(raw_value)
    if normalized is None:
        return None

    try:
        return date.fromisoformat(normalized)
    except ValueError:
        pass

    for date_format in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"MN row has invalid date: {raw_value!r}")


def _parse_required_mn_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized = _required_mn_text(raw_value, field_name)
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"MN row has invalid {field_name}: {raw_value!r}") from exc


def _transaction_amount_field(data_type: str) -> str:
    return _load_column_for_semantic_path(data_type, "transaction.amount")


def _transaction_date_field(data_type: str) -> str:
    return _load_column_for_semantic_path(data_type, "transaction.date")


def _transaction_type_from_row(row: Mapping[str, str | None], data_type: str) -> str:
    candidate_paths = ("transaction.type", "transaction.receipt_type")
    for semantic_path in candidate_paths:
        try:
            column_name = _load_column_for_semantic_path(data_type, semantic_path)
        except RuntimeError:
            continue
        normalized = _normalize_optional_text(row.get(column_name))
        if normalized is not None:
            return normalized
    raise ValueError(f"MN row is missing transaction type for {data_type}")


def _build_mn_filing_fec_id(row: Mapping[str, str | None], data_type: str) -> str:
    committee_id_column = _load_column_for_semantic_path(data_type, "committee.id")
    year_column = _load_column_for_semantic_path(data_type, "transaction.year")
    committee_identifier = _required_mn_text(row.get(committee_id_column), committee_id_column)
    filing_year = _normalize_optional_text(row.get(year_column))
    if filing_year is None:
        transaction_date = _parse_optional_mn_date(row.get(_transaction_date_field(data_type)))
        if transaction_date is None:
            raise ValueError("MN row is missing both transaction year and transaction date")
        filing_year = str(transaction_date.year)
    return f"MN-{committee_identifier}-{filing_year}-{data_type}"


def _resolve_mn_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    extracted = _extract_mn_row(row, data_type=data_type)
    committee_organization_id = _resolve_mn_committee_id(conn, extracted["committee"])
    committee_id_column = _load_column_for_semantic_path(data_type, "committee.id")
    native_committee_id = _required_mn_text(row.get(committee_id_column), committee_id_column)
    return ensure_state_committee(
        conn,
        state="MN",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
    )


def _build_mn_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    committee_name_column = _load_column_for_semantic_path(data_type, "committee.name")
    transaction_date = _parse_optional_mn_date(row.get(_transaction_date_field(data_type)))
    return Filing(
        filing_fec_id=_build_mn_filing_fec_id(row, data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator="N",
        filing_name=_normalize_optional_text(row.get(committee_name_column)),
        receipt_date=transaction_date,
        accepted_date=transaction_date,
        source_record_id=source_record_id,
    )


def _upsert_mn_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _MNFilingLookupEntry],
) -> _MNFilingLookupEntry:
    filing_fec_id = _build_mn_filing_fec_id(row, data_type)
    existing_entry = filing_lookup.get(filing_fec_id)
    if existing_entry is None:
        committee_id = _resolve_mn_filing_committee_id(conn, row, data_type)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id

    filing = _build_mn_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)
    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise ValueError(
            f"MN filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )

    entry = _MNFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None], data_type: str) -> str | None:
    semantic_path = _MN_COUNTERPARTY_NAME_PATH.get(data_type)
    if semantic_path is None:
        raise ValueError(f"Unsupported MN data_type: {data_type}")
    return _normalize_optional_text(row.get(_load_column_for_semantic_path(data_type, semantic_path)))


def _counterparty_employer(row: Mapping[str, str | None], data_type: str) -> str | None:
    semantic_path = _MN_COUNTERPARTY_EMPLOYER_PATH.get(data_type)
    if semantic_path is None:
        return None
    return _normalize_optional_text(row.get(_load_column_for_semantic_path(data_type, semantic_path)))


def _counterparty_address(row: Mapping[str, str | None], data_type: str) -> Address | None:
    return _extract_mn_row(row, data_type=data_type)["address"]


def _mn_support_oppose(row: Mapping[str, str | None]) -> str | None:
    support_oppose_column = _load_column_for_semantic_path(
        "independent_expenditures",
        "mn.independent_expenditure.support_oppose",
    )
    support_oppose_value = _normalize_optional_text(row.get(support_oppose_column))
    if support_oppose_value is None:
        return None
    try:
        return {"for": "S", "against": "O"}[support_oppose_value.casefold()]
    except KeyError as error:
        raise ValueError(
            f"Unsupported MN independent expenditure support/oppose value: {support_oppose_value!r}"
        ) from error


def _resolve_mn_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    address_role = _MN_ENTITY_ROLES_BY_TYPE[data_type].address
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
    return None if row is None else row[0]


def _upsert_mn_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> None:
    person_roles, organization_roles = _MN_COUNTERPARTY_ROLES_BY_TYPE[data_type]
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=organization_roles,
    )
    contributor_address_id = _resolve_mn_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
    )

    counterparty_address = _counterparty_address(row, data_type)
    if counterparty_address is None:
        contributor_city = None
        contributor_state = None
        contributor_zip = None
    else:
        contributor_city = counterparty_address.city
        contributor_state = counterparty_address.state
        contributor_zip = counterparty_address.zip5

    amount_field = _transaction_amount_field(data_type)
    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=_transaction_type_from_row(row, data_type),
            transaction_identifier=_mn_source_record_key(row),
            transaction_date=_parse_optional_mn_date(row.get(_transaction_date_field(data_type))),
            amount=_parse_required_mn_amount(row.get(amount_field), amount_field),
            contributor_name_raw=_counterparty_name_raw(row, data_type),
            contributor_employer=_counterparty_employer(row, data_type),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=contributor_address_id,
            recipient_committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
            support_oppose=_mn_support_oppose(row) if data_type == "independent_expenditures" else None,
        ),
    )


def _load_mn_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> None:
    filing_lookup: dict[str, _MNFilingLookupEntry] = {}
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_mn_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_mn_source_record_key(row),
        )
        if source_record_id is None:
            continue

        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            filing_entry = _upsert_mn_filing(
                conn,
                row,
                source_record_id=source_record_id,
                data_type=data_type,
                filing_lookup=filing_lookup,
            )
            _upsert_mn_transaction_with_filing(
                conn,
                row,
                filing_id=filing_entry.filing_id,
                committee_id=filing_entry.committee_id,
                source_record_id=source_record_id,
                data_type=data_type,
            )

    commit_managed_transaction(conn, manages_outer_transaction)


def load_mn_contributions_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_mn_file_with_filings(conn, file_path, data_type="contributions", limit=limit)


def load_mn_expenditures_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_mn_file_with_filings(conn, file_path, data_type="expenditures", limit=limit)


def load_mn_independent_expenditures_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_mn_file_with_filings(conn, file_path, data_type="independent_expenditures", limit=limit)


def _load_mn_file_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_mn_data_source(conn, data_type=data_type)
    parser = _MN_PARSER_FN[data_type](Path(file_path))
    load_result = _load_mn_file(
        conn,
        file_path,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )
    _load_mn_relational_transactions(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )
    return load_result
