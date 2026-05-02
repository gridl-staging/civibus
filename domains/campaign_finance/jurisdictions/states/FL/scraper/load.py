
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
    resolve_organization_by_canonical_name,
    resolve_person_by_name_and_zip,
    try_insert_source_record,
    upsert_address,
)
from core.types.python.models import (
    Address,
    DataSource,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    generate_synthetic_committee_id,
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
from .extract import (
    extract_fl_contribution,
    extract_fl_expenditure,
    extract_fl_other,
    extract_fl_transfer,
)
from .parse import parse_contributions, parse_expenditures, parse_other, parse_transfers

LOGGER = logging.getLogger(__name__)

_FL_DOMAIN = "campaign_finance"
_FL_JURISDICTION = "state/FL"
_FL_SOURCE_FORMAT = "csv"


@dataclass(slots=True)
class _FLLoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _FLTransactionEntities:
    person: object | None
    organization: object | None
    committee: object
    address: Address | None


@dataclass(frozen=True, slots=True)
class _FLTransactionRoles:
    person: str
    organization: str
    committee: str
    address: str


@dataclass(frozen=True, slots=True)
class _FLFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


# -- Per-type config tables --

_FL_ENTITY_ROLES_BY_TYPE = {
    "contributions": _FLTransactionRoles(
        person="donor", organization="contributor", committee="recipient", address="contributor_address"
    ),
    "expenditures": _FLTransactionRoles(
        person="payee", organization="payee", committee="payer", address="payee_address"
    ),
    "transfers": _FLTransactionRoles(
        person="target", organization="target", committee="source", address="target_address"
    ),
    "other": _FLTransactionRoles(person="payee", organization="payee", committee="payer", address="payee_address"),
}
_FL_EXTRACT_FN = {
    "contributions": extract_fl_contribution,
    "expenditures": extract_fl_expenditure,
    "transfers": extract_fl_transfer,
    "other": extract_fl_other,
}
_FL_ENTITY_KEYS = {
    "contributions": ("donor_person", "donor_org"),
    "expenditures": ("payee_person", "payee_org"),
    "transfers": ("target_person", "target_org"),
    "other": ("payee_person", "payee_org"),
}
_FL_PARSER_FN = {
    "contributions": parse_contributions,
    "expenditures": parse_expenditures,
    "transfers": parse_transfers,
    "other": parse_other,
}
_FL_COUNTERPARTY_NAME_PATH = {
    "contributions": "donor.name",
    "expenditures": "payee.name",
    "transfers": "payee.name",
    "other": "payee.name",
}
# Stage 3 assumption from PRIORITIES.md field-investigation notes for FL:
# transaction type token IND (and IE shorthand) indicates independent expenditures.
_FL_IE_TRANSACTION_TYPE_CODES = frozenset({"IND", "IE"})


# -- Data source helpers --


def ensure_fl_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    """Ensure a data source row exists for the given FL data type, returning its id."""
    normalized_data_type = data_type.strip().lower()
    data_source_name = _load_data_source_name_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_FL_DOMAIN,
        jurisdiction=_FL_JURISDICTION,
        name=data_source_name,
        source_url=_load_data_source_url_for_data_type(normalized_data_type),
        source_format=_FL_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


# -- Source record helpers --


def _fl_source_record_key(row: Mapping[str, str | None]) -> str:
    """Hash-based key since FL has no native unique record IDs."""
    return compute_record_hash(dict(row))


def _build_fl_source_record(
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


# -- Entity loading --


def _load_fl_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    entities: _FLTransactionEntities,
    roles: _FLTransactionRoles,
) -> None:
    """Resolve and link all entities from an FL transaction row."""
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

    committee_id = resolve_organization_by_canonical_name(conn, entities.committee)
    if committee_id is not None:
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


# -- Per-row loading --


def _load_fl_transaction_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
    entities: _FLTransactionEntities,
    roles: _FLTransactionRoles,
) -> bool:
    """Insert a source record and link entities. Returns True if inserted, False if duplicate."""
    source_record_id = try_insert_source_record(conn, _build_fl_source_record(data_source_id, row, data_type=data_type))
    if source_record_id is None:
        return False

    _load_fl_transaction_entities(
        conn,
        source_record_id=source_record_id,
        entities=entities,
        roles=roles,
    )
    return True


def _extract_and_load_fl_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    extract_fn = _FL_EXTRACT_FN.get(data_type)
    if extract_fn is None:
        raise ValueError(f"Unsupported FL data_type: {data_type}")
    person_key, org_key = _FL_ENTITY_KEYS[data_type]
    extracted = extract_fn(dict(row))
    return _load_fl_transaction_row(
        conn,
        row,
        data_source_id,
        data_type=data_type,
        entities=_FLTransactionEntities(
            person=extracted[person_key],
            organization=extracted[org_key],
            committee=extracted["committee"],
            address=extracted["address"],
        ),
        roles=_FL_ENTITY_ROLES_BY_TYPE[data_type],
    )


# -- Public per-type row loaders --


def load_fl_contribution(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_fl_row(conn, row, data_source_id, data_type="contributions")


def load_fl_expenditure(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_fl_row(conn, row, data_source_id, data_type="expenditures")


def load_fl_transfer(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_fl_row(conn, row, data_source_id, data_type="transfers")


def load_fl_other(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_fl_row(conn, row, data_source_id, data_type="other")


# -- Batch loading --


def _try_load_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    data_source_id: UUID,
    data_type: str,
    manages_outer_transaction: bool,
) -> bool | None:
    """Try to load a single row, returning True/False/None (error)."""
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return _extract_and_load_fl_row(conn, row, data_source_id, data_type=data_type)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading FL %s row", data_type.rstrip("s"))
        return None


def _load_fl_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _FLLoadCounts()
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


def _load_fl_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _FL_PARSER_FN[data_type](Path(file_path))
    return _load_fl_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


# -- Filing/transaction relational loading --


def _parse_optional_fl_date(raw_value: str | None) -> date | None:
    normalized = normalize_optional_text(raw_value)
    if normalized is None:
        return None
    # FL dates are MM/DD/YYYY
    for date_format in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"FL row has invalid date: {raw_value!r}")


def _parse_required_fl_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized = normalize_optional_text(raw_value)
    if normalized is None:
        raise ValueError(f"FL row is missing {field_name}")
    try:
        return Decimal(normalized.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"FL row has invalid {field_name}: {raw_value!r}") from exc


def _transaction_field(data_type: str, semantic: str) -> str:
    return _load_column_for_semantic_path(data_type, semantic)


def _transaction_type_from_row(row: Mapping[str, str | None], data_type: str) -> str:
    """Extract the transaction type from a row, trying semantic paths."""
    candidate_paths = ("transaction.type", "transaction.account_nature")
    for semantic_path in candidate_paths:
        try:
            column_name = _load_column_for_semantic_path(data_type, semantic_path)
        except RuntimeError:
            continue
        normalized = normalize_optional_text(row.get(column_name))
        if normalized is not None:
            return normalized
    # FL "other" type has no explicit type column — default to data_type
    return data_type


def _fl_is_independent_expenditure(row: Mapping[str, str | None], *, data_type: str) -> bool:
    """Return True when an expenditure row has an assumed FL IE type token."""
    if data_type != "expenditures":
        return False

    type_column = _load_column_for_semantic_path(data_type, "transaction.type")
    raw_type = normalize_optional_text(row.get(type_column))
    if raw_type is None:
        return False
    return raw_type.upper() in _FL_IE_TRANSACTION_TYPE_CODES


def _build_fl_filing_fec_id(row: Mapping[str, str | None], data_type: str) -> str:
    """Build a synthetic filing ID from committee name + date + data type.

    FL has no native filing IDs, so we construct one from the committee name
    and the transaction date to group rows into logical filings.
    """
    committee_name_column = _load_column_for_semantic_path(data_type, "committee.name")
    committee_name = normalize_optional_text(row.get(committee_name_column)) or "UNKNOWN"
    # Use committee name hash + date for a stable synthetic filing ID
    transaction_date = _parse_optional_fl_date(row.get(_transaction_field(data_type, "transaction.date")))
    date_part = transaction_date.isoformat() if transaction_date is not None else "NODATE"
    synthetic_committee_id = generate_synthetic_committee_id("FL", committee_name)
    return f"FL-{synthetic_committee_id}-{date_part}-{data_type}"


def _resolve_fl_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    extracted = _FL_EXTRACT_FN[data_type](dict(row))
    committee_organization_id = resolve_organization_by_canonical_name(conn, extracted["committee"])
    if committee_organization_id is None:
        raise ValueError("FL row has unresolvable committee organization")
    committee_name_column = _load_column_for_semantic_path(data_type, "committee.name")
    native_committee_id = normalize_optional_text(row.get(committee_name_column)) or "UNKNOWN"
    return ensure_state_committee(
        conn,
        state="FL",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
    )


def _build_fl_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    committee_name_column = _load_column_for_semantic_path(data_type, "committee.name")
    transaction_date = _parse_optional_fl_date(row.get(_transaction_field(data_type, "transaction.date")))
    return Filing(
        filing_fec_id=_build_fl_filing_fec_id(row, data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator="N",
        filing_name=normalize_optional_text(row.get(committee_name_column)),
        receipt_date=transaction_date,
        accepted_date=transaction_date,
        source_record_id=source_record_id,
    )


def _upsert_fl_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _FLFilingLookupEntry],
) -> _FLFilingLookupEntry:
    filing_fec_id = _build_fl_filing_fec_id(row, data_type)
    existing_entry = filing_lookup.get(filing_fec_id)
    if existing_entry is None:
        committee_id = _resolve_fl_filing_committee_id(conn, row, data_type)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id

    filing = _build_fl_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)

    entry = _FLFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None], data_type: str) -> str | None:
    semantic_path = _FL_COUNTERPARTY_NAME_PATH.get(data_type)
    if semantic_path is None:
        raise ValueError(f"Unsupported FL data_type: {data_type}")
    return normalize_optional_text(row.get(_load_column_for_semantic_path(data_type, semantic_path)))


def _counterparty_address(row: Mapping[str, str | None], data_type: str) -> Address | None:
    return _FL_EXTRACT_FN[data_type](dict(row))["address"]


def _resolve_fl_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    address_role = _FL_ENTITY_ROLES_BY_TYPE[data_type].address
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


def _select_fl_source_record_id(
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


def _upsert_fl_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> None:
    _roles = _FL_ENTITY_ROLES_BY_TYPE[data_type]
    person_roles, organization_roles = (_roles.person,), (_roles.organization,)
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=organization_roles,
    )
    contributor_address_id = _resolve_fl_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
    )

    counterparty_addr = _counterparty_address(row, data_type)
    contributor_state = counterparty_addr.state if counterparty_addr is not None else None
    contributor_city = counterparty_addr.city if counterparty_addr is not None else None
    contributor_zip = counterparty_addr.zip5 if counterparty_addr is not None else None

    amount_field = _transaction_field(data_type, "transaction.amount")
    transaction_type = (
        "Independent Expenditure"
        if _fl_is_independent_expenditure(row, data_type=data_type)
        else _transaction_type_from_row(row, data_type)
    )

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=transaction_type,
            transaction_identifier=_fl_source_record_key(row),
            transaction_date=_parse_optional_fl_date(row.get(_transaction_field(data_type, "transaction.date"))),
            amount=_parse_required_fl_amount(row.get(amount_field), amount_field),
            contributor_name_raw=_counterparty_name_raw(row, data_type),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            contributor_address_id=contributor_address_id,
            recipient_committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
        ),
    )


def _load_fl_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> None:
    filing_lookup: dict[str, _FLFilingLookupEntry] = {}
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_fl_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_fl_source_record_key(row),
        )
        if source_record_id is None:
            continue

        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            filing_entry = _upsert_fl_filing(
                conn,
                row,
                source_record_id=source_record_id,
                data_type=data_type,
                filing_lookup=filing_lookup,
            )
            _upsert_fl_transaction_with_filing(
                conn,
                row,
                filing_id=filing_entry.filing_id,
                committee_id=filing_entry.committee_id,
                source_record_id=source_record_id,
                data_type=data_type,
            )

    commit_managed_transaction(conn, manages_outer_transaction)


# -- Public with-filings wrappers --


def _load_fl_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_fl_data_source(conn, data_type=data_type)
    load_result = _load_fl_file(
        conn,
        file_path,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )
    _load_fl_relational_transactions(
        conn,
        _FL_PARSER_FN[data_type](Path(file_path)),
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )
    return load_result


def load_fl_contributions_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_fl_with_filings(conn, fp, data_type="contributions", limit=limit)


def load_fl_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_fl_with_filings(conn, fp, data_type="expenditures", limit=limit)


def load_fl_transfers_with_filings(conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None) -> LoadResult:
    return _load_fl_with_filings(conn, fp, data_type="transfers", limit=limit)


def load_fl_other_with_filings(conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None) -> LoadResult:
    return _load_fl_with_filings(conn, fp, data_type="other", limit=limit)
