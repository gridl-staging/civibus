
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
    iter_rows_with_limit,
    link_entity_source_and_optional_mailing_address,
    try_row_without_savepoint,
    validated_limit,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import _load_column_for_semantic_path, _load_data_source_for_data_type
from .extract import extract_tx_contribution, extract_tx_expenditure, extract_tx_loan
from .parse import parse_contributions, parse_expenditures, parse_loans

LOGGER = logging.getLogger(__name__)

_TX_DOMAIN = "campaign_finance"
_TX_JURISDICTION = "state/TX"
_TX_SOURCE_FORMAT = "csv"

_TX_SOURCE_KEY_PATH_BY_TYPE = {
    "contributions": "tx.contribution_info_id",
    "expenditures": "tx.expend_info_id",
    "loans": "tx.loan_info_id",
}
_TX_COUNTERPARTY_EMPLOYER_PATH = {
    "contributions": "donor.employer",
    "loans": "lender.employer",
}


@dataclass(slots=True)
class _TXLoadCounts:
    inserted: int = 0
    skipped: int = 0
    superseded: int = 0
    errors: int = 0


@dataclass(slots=True)
class _TXRelationalLoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _TXTransactionRoles:
    person: str
    organization: str
    committee: str
    address: str


@dataclass(frozen=True, slots=True)
class _TXTransactionEntities:
    person: Person | None
    organization: Organization | None
    committee: Organization
    address: Address | None


@dataclass(frozen=True, slots=True)
class _TXFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


_TX_ENTITY_ROLES_BY_TYPE = {
    "contributions": _TXTransactionRoles("donor", "contributor", "recipient", "contributor_address"),
    "expenditures": _TXTransactionRoles("payee", "payee", "payer", "payee_address"),
    "loans": _TXTransactionRoles("lender", "lender", "borrower", "lender_address"),
}
_TX_COUNTERPARTY_ROLES_BY_TYPE = {
    "contributions": (("donor",), ("contributor",)),
    "expenditures": (("payee",), ("payee",)),
    "loans": (("lender",), ("lender",)),
}
_TX_EXTRACT_FN: dict[str, Callable[[dict[str, str | None]], dict[str, Any]]] = {
    "contributions": extract_tx_contribution,
    "expenditures": extract_tx_expenditure,
    "loans": extract_tx_loan,
}
_TX_ENTITY_KEYS = {
    "contributions": ("donor_person", "donor_org"),
    "expenditures": ("payee_person", "payee_org"),
    "loans": ("lender_person", "lender_org"),
}
_TX_PARSER_FN = {"contributions": parse_contributions, "expenditures": parse_expenditures, "loans": parse_loans}
# TX independent expenditures are identified by form type code DCE
# (Direct Campaign Expenditure) in live TEC data.
_TX_IE_FORM_TYPE_CODES = frozenset({"DCE"})


def _select_first_uuid(conn: psycopg.Connection, query: str, params: tuple[object, ...]) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def ensure_tx_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_config = _load_data_source_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_TX_DOMAIN,
        jurisdiction=_TX_JURISDICTION,
        name=data_source_config.name,
        source_url=data_source_config.url,
        source_format=_TX_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _required_tx_text(value: str | None, field_name: str) -> str:
    normalized_value = normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"TX row is missing {field_name}")
    return normalized_value


def _tx_source_identifier_column(data_type: str) -> str:
    semantic_path = _TX_SOURCE_KEY_PATH_BY_TYPE.get(data_type)
    if semantic_path is None:
        raise ValueError(f"Unsupported TX data type: {data_type}")
    return _load_column_for_semantic_path(data_type, semantic_path)


def _tx_source_record_key(row: Mapping[str, str | None], *, data_type: str) -> str:
    source_identifier_column = _tx_source_identifier_column(data_type)
    native_identifier = normalize_optional_text(row.get(source_identifier_column))
    if native_identifier is not None:
        return native_identifier

    return compute_record_hash(dict(row))


def _tx_transaction_identifier(row: Mapping[str, str | None], *, data_type: str) -> str:
    return _tx_source_record_key(row, data_type=data_type)


def _parse_tx_date(raw_value: str | None) -> date | None:
    normalized_value = normalize_optional_text(raw_value)
    if normalized_value is None:
        return None
    if len(normalized_value) != 8 or not normalized_value.isdigit():
        raise ValueError(f"TX row has invalid YYYYMMDD date: {raw_value!r}")

    return datetime.strptime(normalized_value, "%Y%m%d").date()


def _tx_amendment_indicator(row: Mapping[str, str | None], *, data_type: str) -> str:
    info_only_column = _load_column_for_semantic_path(data_type, "tx.info_only_flag")
    form_type_column = _load_column_for_semantic_path(data_type, "tx.form_type_code")

    info_only_flag = normalize_optional_text(row.get(info_only_column))
    form_type_code = (normalize_optional_text(row.get(form_type_column)) or "").upper()

    if info_only_flag == "Y":
        return "T"
    if form_type_code.startswith("COR"):
        return "A"
    return "N"


def _tx_filing_fec_id(row: Mapping[str, str | None], *, data_type: str) -> str:
    committee_id_column = _load_column_for_semantic_path(data_type, "committee.id")
    received_date_column = _load_column_for_semantic_path(data_type, "tx.received_date")

    committee_identifier = _required_tx_text(row.get(committee_id_column), committee_id_column)
    received_date = _parse_tx_date(row.get(received_date_column))
    if received_date is None:
        raise ValueError("TX row is missing receivedDt for filing_fec_id generation")

    return f"TX-{committee_identifier}-{received_date.year}-{data_type}"


def _tx_transaction_type(row: Mapping[str, str | None], *, data_type: str) -> str:
    for semantic_path in ("tx.schedule_form_type_code", "tx.form_type_code"):
        column_name = _load_column_for_semantic_path(data_type, semantic_path)
        value = normalize_optional_text(row.get(column_name))
        if value is not None:
            return value

    return data_type.rstrip("s")


def _tx_is_independent_expenditure(row: Mapping[str, str | None], *, data_type: str) -> bool:
    """Return True when an expenditure row matches TX IE form type codes."""
    if data_type != "expenditures":
        return False

    form_type_column = _load_column_for_semantic_path(data_type, "tx.form_type_code")
    form_type_code = normalize_optional_text(row.get(form_type_column))
    if form_type_code is None:
        return False
    return form_type_code.upper() in _TX_IE_FORM_TYPE_CODES


def _parse_required_tx_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized_value = _required_tx_text(raw_value, field_name)
    try:
        return Decimal(normalized_value.replace(",", ""))
    except InvalidOperation as error:
        raise ValueError(f"TX row has invalid {field_name}: {raw_value!r}") from error


def _build_tx_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> SourceRecord:
    raw_fields = dict(row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_tx_source_record_key(row, data_type=data_type),
        source_url=_load_data_source_for_data_type(data_type).url,
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _resolve_tx_committee_organization_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = normalize_optional_text(committee.identifiers.get("tx_committee_id"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(conn, "tx_committee_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id

    resolved_org_id = resolve_organization_by_canonical_name(conn, committee)
    if resolved_org_id is None:
        raise ValueError("TX committee extraction did not produce a resolvable organization")
    return resolved_org_id


def _load_tx_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    entities: _TXTransactionEntities,
    roles: _TXTransactionRoles,
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

    committee_id = _resolve_tx_committee_organization_id(conn, entities.committee)
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


def _tx_extract_row(row: Mapping[str, str | None], data_type: str) -> dict[str, Any]:
    extract_fn = _TX_EXTRACT_FN.get(data_type)
    if extract_fn is None:
        raise ValueError(f"Unsupported TX data type: {data_type}")
    return extract_fn(dict(row))


def _extract_and_load_tx_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    source_record = _build_tx_source_record(data_source_id, row, data_type=data_type)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = _tx_extract_row(row, data_type)
    person_key, organization_key = _TX_ENTITY_KEYS[data_type]
    _load_tx_transaction_entities(
        conn,
        source_record_id=source_record_id,
        entities=_TXTransactionEntities(
            person=extracted[person_key],
            organization=extracted[organization_key],
            committee=extracted["committee"],
            address=extracted["address"],
        ),
        roles=_TX_ENTITY_ROLES_BY_TYPE[data_type],
    )
    return True


def load_tx_contribution(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_tx_row(conn, row, data_source_id, data_type="contributions")


def load_tx_expenditure(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_tx_row(conn, row, data_source_id, data_type="expenditures")


def load_tx_loan(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_tx_row(conn, row, data_source_id, data_type="loans")


def _try_load_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    data_source_id: UUID,
    data_type: str,
    manages_outer_transaction: bool,
) -> tuple[bool | None, bool]:
    return try_row_without_savepoint(
        conn,
        lambda: _extract_and_load_tx_row(conn, row, data_source_id, data_type=data_type),
        manages_outer_transaction=manages_outer_transaction,
        label=f"TX {data_type.rstrip('s')} row",
    )


def _load_tx_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _TXLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        if _tx_amendment_indicator(row, data_type=data_type) == "T":
            counts.superseded += 1

        inserted, was_db_error = _try_load_row(
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

        # DB errors roll back the current transaction, losing uncommitted rows
        # in this batch. This is acceptable — we log and continue.

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


def _load_tx_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
    year_from: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _TX_PARSER_FN[data_type](Path(file_path), year_from=year_from)
    return _load_tx_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


def load_tx_contributions(
    conn: psycopg.Connection, fp: str | Path, *, data_source_id: UUID, limit: int | None = None
) -> LoadResult:
    return _load_tx_file(conn, fp, data_source_id=data_source_id, data_type="contributions", limit=limit)


def load_tx_expenditures(
    conn: psycopg.Connection, fp: str | Path, *, data_source_id: UUID, limit: int | None = None
) -> LoadResult:
    return _load_tx_file(conn, fp, data_source_id=data_source_id, data_type="expenditures", limit=limit)


def load_tx_loans(
    conn: psycopg.Connection, fp: str | Path, *, data_source_id: UUID, limit: int | None = None
) -> LoadResult:
    return _load_tx_file(conn, fp, data_source_id=data_source_id, data_type="loans", limit=limit)


def _select_tx_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    return _select_first_uuid(
        conn,
        """
        SELECT id
        FROM core.source_record
        WHERE data_source_id = %s
          AND source_record_key = %s
        LIMIT 1
        """,
        (data_source_id, source_record_key),
    )


def _select_tx_transaction_id(
    conn: psycopg.Connection,
    *,
    filing_id: UUID,
    transaction_identifier: str,
) -> UUID | None:
    return _select_first_uuid(
        conn,
        """
        SELECT id
        FROM cf.transaction
        WHERE filing_id = %s
          AND transaction_identifier = %s
        LIMIT 1
        """,
        (filing_id, transaction_identifier),
    )


def _resolve_tx_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    extracted = _tx_extract_row(row, data_type)
    committee_organization_id = _resolve_tx_committee_organization_id(conn, extracted["committee"])
    committee_id_column = _load_column_for_semantic_path(data_type, "committee.id")
    native_committee_id = _required_tx_text(row.get(committee_id_column), committee_id_column)

    return ensure_state_committee(
        conn,
        state="TX",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
    )


def _build_tx_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    committee_name_column = _load_column_for_semantic_path(data_type, "committee.name")
    received_date_column = _load_column_for_semantic_path(data_type, "tx.received_date")
    received_date = _parse_tx_date(row.get(received_date_column))

    return Filing(
        filing_fec_id=_tx_filing_fec_id(row, data_type=data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator=_tx_amendment_indicator(row, data_type=data_type),
        filing_name=normalize_optional_text(row.get(committee_name_column)),
        receipt_date=received_date,
        accepted_date=received_date,
        source_record_id=source_record_id,
    )


def _upsert_tx_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _TXFilingLookupEntry],
) -> _TXFilingLookupEntry:
    filing_fec_id = _tx_filing_fec_id(row, data_type=data_type)
    existing_entry = filing_lookup.get(filing_fec_id)

    if existing_entry is None:
        committee_id = _resolve_tx_filing_committee_id(conn, row, data_type)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id

    filing = _build_tx_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)

    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise ValueError(
            f"TX filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )

    entry = _TXFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_employer(row: Mapping[str, str | None], data_type: str) -> str | None:
    semantic_path = _TX_COUNTERPARTY_EMPLOYER_PATH.get(data_type)
    if semantic_path is None:
        return None

    employer_column = _load_column_for_semantic_path(data_type, semantic_path)
    return normalize_optional_text(row.get(employer_column))


def _tx_counterparty_name(
    extracted: dict[str, Any],
    *,
    data_type: str,
) -> str | None:
    person_key, organization_key = _TX_ENTITY_KEYS[data_type]
    person = extracted[person_key]
    if person is not None:
        return normalize_optional_text(person.canonical_name)

    organization = extracted[organization_key]
    if organization is None:
        return None
    return normalize_optional_text(organization.canonical_name)


def _tx_counterparty_address_parts(address: Address | None) -> tuple[str | None, str | None, str | None]:
    if address is None:
        return None, None, None
    return address.city, address.state, address.zip5


def _resolve_tx_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    address_role = _TX_ENTITY_ROLES_BY_TYPE[data_type].address

    return _select_first_uuid(
        conn,
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


def _upsert_tx_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> bool:
    person_roles, organization_roles = _TX_COUNTERPARTY_ROLES_BY_TYPE[data_type]
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=organization_roles,
    )

    contributor_address_id = _resolve_tx_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
    )
    extracted = _tx_extract_row(row, data_type)
    counterparty_address = extracted["address"]
    contributor_name_raw = _tx_counterparty_name(extracted, data_type=data_type)
    contributor_city, contributor_state, contributor_zip = _tx_counterparty_address_parts(counterparty_address)

    amount_column = _load_column_for_semantic_path(data_type, "transaction.amount")
    transaction_date_column = _load_column_for_semantic_path(data_type, "transaction.date")
    transaction_identifier = _tx_transaction_identifier(row, data_type=data_type)
    existing_transaction_id = _select_tx_transaction_id(
        conn,
        filing_id=filing_id,
        transaction_identifier=transaction_identifier,
    )

    transaction_type = (
        "Independent Expenditure"
        if _tx_is_independent_expenditure(row, data_type=data_type)
        else _tx_transaction_type(row, data_type=data_type)
    )

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=transaction_type,
            transaction_identifier=transaction_identifier,
            transaction_date=_parse_tx_date(row.get(transaction_date_column)),
            amount=_parse_required_tx_amount(row.get(amount_column), amount_column),
            contributor_name_raw=contributor_name_raw,
            contributor_employer=_counterparty_employer(row, data_type),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=contributor_address_id,
            recipient_committee_id=committee_id,
            amendment_indicator=_tx_amendment_indicator(row, data_type=data_type),
            source_record_id=source_record_id,
        ),
    )
    return existing_transaction_id is None


def _restore_tx_filing_lookup_entry(
    filing_lookup: dict[str, _TXFilingLookupEntry],
    *,
    filing_fec_id: str,
    cached_entry: _TXFilingLookupEntry | None,
) -> None:
    if cached_entry is None:
        filing_lookup.pop(filing_fec_id, None)
        return
    filing_lookup[filing_fec_id] = cached_entry


def _load_tx_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> _TXRelationalLoadCounts:
    filing_lookup: dict[str, _TXFilingLookupEntry] = {}
    counts = _TXRelationalLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    processed_count = 0

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_tx_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_tx_source_record_key(row, data_type=data_type),
        )
        if source_record_id is None:
            continue

        # Capture filing context before the load attempt so we can restore
        # the in-memory lookup cache if the row fails.
        filing_fec_id = _tx_filing_fec_id(row, data_type=data_type)
        cached_filing_entry = filing_lookup.get(filing_fec_id)

        def _link_row() -> bool:
            """Upsert filing + link transaction. No per-row savepoint."""
            filing_entry = _upsert_tx_filing(
                conn,
                row,
                source_record_id=source_record_id,
                data_type=data_type,
                filing_lookup=filing_lookup,
            )
            return _upsert_tx_transaction_with_filing(
                conn,
                row,
                filing_id=filing_entry.filing_id,
                committee_id=filing_entry.committee_id,
                source_record_id=source_record_id,
                data_type=data_type,
            )

        result, was_db_error = try_row_without_savepoint(
            conn,
            _link_row,
            manages_outer_transaction=manages_outer_transaction,
            label=f"TX {data_type.rstrip('s')} filing link",
        )
        inserted = result

        if inserted is None:
            counts.errors += 1
            # Restore the in-memory filing lookup cache on failure so that
            # subsequent rows don't reference a rolled-back filing entry.
            if filing_fec_id is not None:
                _restore_tx_filing_lookup_entry(
                    filing_lookup,
                    filing_fec_id=filing_fec_id,
                    cached_entry=cached_filing_entry,
                )
            continue

        if inserted:
            counts.inserted += 1
        else:
            counts.skipped += 1
        processed_count += 1
        if processed_count % 1_000 == 0:
            commit_managed_transaction(conn, manages_outer_transaction)

    commit_managed_transaction(conn, manages_outer_transaction)
    return counts


def _load_tx_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
    year_from: int | None = None,
) -> LoadResult:
    started_at = time.monotonic()
    validated_row_limit = validated_limit(limit)
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    data_source_id = ensure_tx_data_source(conn, data_type=data_type)

    # Commit the data-source lookup/insert so inner functions see an IDLE
    # connection and activate their own batch-commit logic. Only do this when
    # this function started from IDLE; a caller-owned outer transaction must
    # remain open and uncommitted.
    if manages_outer_transaction and conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        conn.commit()

    load_result = _load_tx_file(
        conn,
        file_path,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
        year_from=year_from,
    )
    relational_counts = _load_tx_relational_transactions(
        conn,
        _TX_PARSER_FN[data_type](Path(file_path), year_from=year_from),
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )
    return LoadResult(
        inserted=relational_counts.inserted,
        skipped=relational_counts.skipped,
        quarantined=load_result.quarantined,
        superseded=load_result.superseded,
        errors=load_result.errors + relational_counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def load_tx_contributions_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None, year_from: int | None = None
) -> LoadResult:
    return _load_tx_with_filings(conn, fp, data_type="contributions", limit=limit, year_from=year_from)


def load_tx_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None, year_from: int | None = None
) -> LoadResult:
    return _load_tx_with_filings(conn, fp, data_type="expenditures", limit=limit, year_from=year_from)


def load_tx_loans_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None, year_from: int | None = None
) -> LoadResult:
    return _load_tx_with_filings(conn, fp, data_type="loans", limit=limit, year_from=year_from)
