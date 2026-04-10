
from __future__ import annotations

import logging
import re
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
from core.types.python.models import DataSource, SourceRecord, compute_record_hash, utc_now
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

from . import _load_column_for_semantic_path, _load_data_source_name_for_data_type, _load_data_source_url_for_data_type
from .extract import extract_ky_contribution, extract_ky_expenditure
from .parse import parse_contributions, parse_expenditures

LOGGER = logging.getLogger(__name__)

_KY_DOMAIN = "campaign_finance"
_KY_JURISDICTION = "state/KY"
_KY_SOURCE_FORMAT = "csv"
_normalize_optional_text = normalize_optional_text


@dataclass(slots=True)
class _KYLoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _KYFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


# Maps data types to the person/org keys in the extraction dict
_KY_ENTITY_KEYS: dict[str, tuple[str, str]] = {
    "contributions": ("donor_person", "donor_org"),
    "expenditures": ("payee_person", "payee_org"),
}

_KY_EXTRACT_FN = {
    "contributions": extract_ky_contribution,
    "expenditures": extract_ky_expenditure,
}

_KY_PARSER_FN = {
    "contributions": parse_contributions,
    "expenditures": parse_expenditures,
}

_KY_ENTITY_ROLES: dict[str, dict[str, str]] = {
    "contributions": {
        "person": "donor",
        "organization": "donor_org",
        "committee": "recipient_committee",
        "address": "donor_address",
    },
    "expenditures": {
        "person": "payee",
        "organization": "payee_org",
        "committee": "paying_committee",
        "address": "payee_address",
    },
}

_KY_COUNTERPARTY_ROLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "contributions": (("donor",), ("donor_org",)),
    "expenditures": (("payee",), ("payee_org",)),
}

_KY_TRANSACTION_KIND: dict[str, str] = {
    "contributions": "contribution",
    "expenditures": "expenditure",
}

_KY_IE_TRUTHY_VALUES = frozenset({"true", "yes", "y", "1"})


def _ky_is_independent_expenditure(row: Mapping[str, str | None]) -> bool:
    """Check whether a KY expenditure row is an independent expenditure.

    Uses the ``ky.is_independent_expenditure`` semantic path to resolve the
    column, then checks against an explicit truthy set to avoid treating
    arbitrary non-empty values (like ``"N"`` or ``"False"``) as IE.
    """
    raw_value = _optional_row_value(
        row,
        data_type="expenditures",
        semantic_path="ky.is_independent_expenditure",
    )
    if raw_value is None:
        return False
    return raw_value.casefold() in _KY_IE_TRUTHY_VALUES


def ensure_ky_data_source(conn: psycopg.Connection, data_type: str) -> UUID:
    """Ensure the KY data source row exists in core.data_source and return its UUID."""
    normalized = data_type.strip().lower()
    return ensure_data_source(
        conn,
        DataSource(
            domain=_KY_DOMAIN,
            jurisdiction=_KY_JURISDICTION,
            name=_load_data_source_name_for_data_type(normalized),
            source_url=_load_data_source_url_for_data_type(normalized),
            source_format=_KY_SOURCE_FORMAT,
        ),
    )


def _ky_source_record_key(row: Mapping[str, str | None]) -> str:
    return compute_record_hash(dict(row))


def _build_ky_source_record(
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


def _resolve_ky_committee_id(conn: psycopg.Connection, committee_org: object) -> UUID:
    """Resolve a committee Organization to its core entity UUID."""
    from core.types.python.models import Organization

    if not isinstance(committee_org, Organization):
        raise TypeError(f"Expected Organization, got {type(committee_org)}")

    ky_org_id = _normalize_optional_text(committee_org.identifiers.get("ky_org_id"))
    if ky_org_id is not None:
        existing = find_organization_by_identifier(conn, "ky_org_id", ky_org_id)
        if existing is not None:
            return existing
    return resolve_organization_by_canonical_name(conn, committee_org)


def _load_ky_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: dict,
    data_type: str,
) -> None:
    """Insert entity_source and entity_address links for the row's entities."""
    roles = _KY_ENTITY_ROLES[data_type]
    person_key, org_key = _KY_ENTITY_KEYS[data_type]

    address_id = None
    address = extracted.get("address")
    if address is not None:
        address_id = upsert_address(conn, address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=roles["address"],
            address_id=None,
        )

    person = extracted.get(person_key)
    if person is not None:
        person_id = resolve_person_by_name_and_zip(conn, person, address)
        if person_id is not None:
            link_entity_source_and_optional_mailing_address(
                conn,
                entity_type="person",
                entity_id=person_id,
                source_record_id=source_record_id,
                extraction_role=roles["person"],
                address_id=address_id,
            )

    committee = extracted["committee"]
    committee_id = _resolve_ky_committee_id(conn, committee)
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_id,
        source_record_id=source_record_id,
        extraction_role=roles["committee"],
        address_id=None,
    )

    org = extracted.get(org_key)
    if org is not None:
        org_id = resolve_organization_by_canonical_name(conn, org)
        if org_id is not None:
            link_entity_source_and_optional_mailing_address(
                conn,
                entity_type="organization",
                entity_id=org_id,
                source_record_id=source_record_id,
                extraction_role=roles["organization"],
                address_id=address_id,
            )


def _extract_and_load_ky_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    """Insert source record and extract entities for a single row. Returns True if inserted."""
    extract_fn = _KY_EXTRACT_FN.get(data_type)
    if extract_fn is None:
        raise ValueError(f"Unsupported KY data type: {data_type}")

    source_record_id = try_insert_source_record(
        conn,
        _build_ky_source_record(data_source_id, row, data_type=data_type),
    )
    if source_record_id is None:
        return False

    extracted = extract_fn(dict(row))
    _load_ky_transaction_entities(
        conn,
        source_record_id=source_record_id,
        extracted=extracted,
        data_type=data_type,
    )
    return True


def _try_load_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    data_source_id: UUID,
    data_type: str,
    manages_outer_transaction: bool,
) -> bool | None:
    """Try to load a single row with savepoint. Returns None on error."""
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return _extract_and_load_ky_row(conn, row, data_source_id, data_type=data_type)
    except Exception:
        LOGGER.exception("Failed loading KY %s row", data_type.rstrip("s"))
        return None


def _load_ky_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    """Load parsed rows into the DB: source records + entity extraction."""
    started_at = time.monotonic()
    counts = _KYLoadCounts()
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)}")

        inserted = _try_load_row(
            conn,
            row,
            data_source_id=data_source_id,
            data_type=data_type,
            manages_outer_transaction=manages_outer,
        )
        if inserted is None:
            counts.errors += 1
        elif inserted:
            counts.inserted += 1
        else:
            counts.skipped += 1

        processed = counts.inserted + counts.skipped + counts.errors
        if processed % 1_000 == 0:
            commit_managed_transaction(conn, manages_outer)

    commit_managed_transaction(conn, manages_outer)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=int(getattr(rows, "skipped", 0)) + int(getattr(rows, "filtered", 0)),
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _load_ky_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    year_from: int | None,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _KY_PARSER_FN[data_type](Path(file_path), year_from=year_from)
    return _load_ky_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


def _parse_optional_ky_date(raw_value: str | None) -> date | None:
    """Parse a date from KY CSV. Returns None for empty/missing values."""
    normalized = _normalize_optional_text(raw_value)
    if normalized is None:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"KY row has invalid date: {raw_value}")


def _required_ky_text(value: str | None, field_name: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise ValueError(f"KY row missing {field_name}")
    return normalized


def _parse_required_ky_amount(raw_value: str | None, field_name: str) -> Decimal:
    """Parse a monetary amount, stripping $ and commas."""
    normalized = _required_ky_text(raw_value, field_name)
    try:
        return Decimal(normalized.replace(",", "").replace("$", ""))
    except InvalidOperation as exc:
        raise ValueError(f"KY row has invalid {field_name}: {raw_value}") from exc


def _load_optional_column_for_semantic_path(data_type: str, semantic_path: str) -> str | None:
    try:
        return _load_column_for_semantic_path(data_type, semantic_path)
    except RuntimeError:
        return None


def _optional_row_value(
    row: Mapping[str, str | None],
    *,
    data_type: str,
    semantic_path: str,
) -> str | None:
    column_name = _load_optional_column_for_semantic_path(data_type, semantic_path)
    if column_name is None:
        return None
    return _normalize_optional_text(row.get(column_name))


def _build_ky_committee_name(row: Mapping[str, str | None], *, data_type: str) -> str:
    organization_name = _optional_row_value(
        row,
        data_type=data_type,
        semantic_path="ky.to_organization" if data_type == "contributions" else "ky.from_organization_name",
    )
    if organization_name is not None:
        return organization_name

    first_name = _optional_row_value(row, data_type=data_type, semantic_path="ky.committee_candidate_first_name")
    last_name = _optional_row_value(row, data_type=data_type, semantic_path="ky.committee_candidate_last_name")
    if first_name is not None and last_name is not None:
        return f"{first_name} {last_name}"
    if last_name is not None:
        return last_name
    if first_name is not None:
        return first_name
    return "Unknown KY Committee"


def _filing_key_part(value: str | None) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return "unknown"
    compact = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return compact or "unknown"


def _build_ky_committee_native_id(row: Mapping[str, str | None], *, data_type: str) -> str:
    committee_name = _build_ky_committee_name(row, data_type=data_type)
    office = _optional_row_value(row, data_type=data_type, semantic_path="jurisdiction.office")
    election_date = _optional_row_value(row, data_type=data_type, semantic_path="ky.election_date")
    return f"KY::{_filing_key_part(committee_name)}::{_filing_key_part(office)}::{_filing_key_part(election_date)}"


def _build_ky_filing_fec_id(row: Mapping[str, str | None], data_type: str) -> str:
    """Synthesize a stable filing key from committee identity plus statement scope."""
    statement_type = _optional_row_value(row, data_type=data_type, semantic_path="ky.statement_type")
    election_date = _optional_row_value(row, data_type=data_type, semantic_path="ky.election_date")
    return (
        f"{_build_ky_committee_native_id(row, data_type=data_type)}"
        f"::{_filing_key_part(statement_type)}::{_filing_key_part(election_date)}::{data_type}"
    )


def _resolve_ky_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    """Resolve the committee for a filing row using extraction + state committee upsert."""
    extracted = _KY_EXTRACT_FN[data_type](dict(row))
    org_id = _resolve_ky_committee_id(conn, extracted["committee"])
    native_id = _build_ky_committee_native_id(row, data_type=data_type)

    return ensure_state_committee(
        conn,
        state="KY",
        native_committee_id=native_id,
        organization_id=org_id,
    )


def _build_ky_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    """Build a Filing model from a KY row."""
    statement_type = _optional_row_value(row, data_type=data_type, semantic_path="ky.statement_type")

    return Filing(
        filing_fec_id=_build_ky_filing_fec_id(row, data_type),
        committee_id=committee_id,
        report_type=statement_type or data_type,
        amendment_indicator="N",
        receipt_date=None,
        accepted_date=None,
        source_record_id=source_record_id,
    )


def _upsert_ky_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _KYFilingLookupEntry],
) -> _KYFilingLookupEntry:
    """Upsert a filing for the given row, caching results in the lookup dict."""
    filing_fec_id = _build_ky_filing_fec_id(row, data_type)
    existing = filing_lookup.get(filing_fec_id)

    if existing is None:
        committee_id = _resolve_ky_filing_committee_id(conn, row, data_type)
        filing_src = source_record_id
    else:
        committee_id = existing.committee_id
        filing_src = existing.source_record_id

    filing = _build_ky_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_src,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)

    entry = _KYFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_src,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    """Get the raw counterparty name for a row."""
    if data_type == "contributions":
        name_col = _load_optional_column_for_semantic_path(data_type, "donor.org_name")
        first_name_col = _load_optional_column_for_semantic_path(data_type, "donor.first_name")
        last_name_col = _load_optional_column_for_semantic_path(data_type, "donor.last_name")
    else:
        name_col = _load_optional_column_for_semantic_path(data_type, "payee.org_name")
        first_name_col = _load_optional_column_for_semantic_path(data_type, "payee.first_name")
        last_name_col = _load_optional_column_for_semantic_path(data_type, "payee.last_name")

    name_value = _normalize_optional_text(row.get(name_col)) if name_col is not None else None
    if name_value is not None:
        return name_value

    first_name = _normalize_optional_text(row.get(first_name_col)) if first_name_col is not None else None
    last_name = _normalize_optional_text(row.get(last_name_col)) if last_name_col is not None else None
    if first_name is not None and last_name is not None:
        return f"{first_name} {last_name}"
    return first_name or last_name


def _counterparty_employer(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    """Get the counterparty employer. Only contributions have this field."""
    if data_type == "contributions":
        employer_col = _load_column_for_semantic_path(data_type, "donor.employer")
        return _normalize_optional_text(row.get(employer_col))
    return None


def _counterparty_occupation(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    """Get the counterparty occupation. Only contributions have this field."""
    if data_type == "contributions":
        occupation_col = _load_column_for_semantic_path(data_type, "donor.occupation")
        return _normalize_optional_text(row.get(occupation_col))
    return None


def _select_ky_source_record_id(
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
        result = cursor.fetchone()
    return result[0] if result else None


def _resolve_ky_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    address_role = _KY_ENTITY_ROLES[data_type]["address"]
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
        result = cursor.fetchone()
    return result[0] if result else None


def _upsert_ky_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> None:
    """Build and upsert a Transaction linked to a Filing for the given row."""
    person_roles, org_roles = _KY_COUNTERPARTY_ROLES[data_type]
    person_id, org_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=org_roles,
    )
    address_id = _resolve_ky_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
    )

    extracted = _KY_EXTRACT_FN[data_type](dict(row))
    address = extracted.get("address")
    contributor_state = address.state if address is not None else None
    contributor_city = address.city if address is not None else None
    contributor_zip = address.zip5 if address is not None else None

    amount_col = _load_column_for_semantic_path(data_type, "transaction.amount")
    date_col = _load_column_for_semantic_path(data_type, "transaction.date")
    # Expenditures have a Purpose field for memo; contributions do not
    memo_col = (
        _load_column_for_semantic_path(data_type, "transaction.description") if data_type == "expenditures" else None
    )

    is_ie = data_type == "expenditures" and _ky_is_independent_expenditure(row)
    transaction_type = "Independent Expenditure" if is_ie else _KY_TRANSACTION_KIND[data_type]

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=transaction_type,
            transaction_identifier=_ky_source_record_key(row),
            transaction_date=_parse_optional_ky_date(row.get(date_col)),
            amount=_parse_required_ky_amount(row.get(amount_col), amount_col),
            contributor_name_raw=_counterparty_name_raw(row, data_type=data_type),
            contributor_employer=_counterparty_employer(row, data_type=data_type),
            contributor_occupation=_counterparty_occupation(row, data_type=data_type),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=person_id,
            contributor_organization_id=org_id,
            contributor_address_id=address_id,
            recipient_committee_id=committee_id,
            amendment_indicator="N",
            memo_text=_normalize_optional_text(row.get(memo_col)) if memo_col else None,
            source_record_id=source_record_id,
        ),
    )


def _load_ky_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> int:
    """Second pass: link source records to filings and transactions."""
    filing_lookup: dict[str, _KYFilingLookupEntry] = {}
    relational_errors = 0
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)}")

        source_record_id = _select_ky_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_ky_source_record_key(row),
        )
        if source_record_id is None:
            continue

        try:
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                filing_entry = _upsert_ky_filing(
                    conn,
                    row,
                    source_record_id=source_record_id,
                    data_type=data_type,
                    filing_lookup=filing_lookup,
                )
                _upsert_ky_transaction_with_filing(
                    conn,
                    row,
                    filing_id=filing_entry.filing_id,
                    committee_id=filing_entry.committee_id,
                    source_record_id=source_record_id,
                    data_type=data_type,
                )
        except Exception:
            relational_errors += 1
            LOGGER.exception("Failed linking KY %s row to filing", data_type.rstrip("s"))

    commit_managed_transaction(conn, manages_outer)
    return relational_errors


def _load_ky_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    data_type: str,
    year_from: int | None = None,
    limit: int | None = None,
) -> LoadResult:
    """Full load pipeline: source records + entities, then filings + transactions."""
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_ky_data_source(conn, data_type=data_type)

    # First pass: insert source records and extract entities
    load_result = _load_ky_file(
        conn,
        fp,
        data_source_id=data_source_id,
        data_type=data_type,
        year_from=year_from,
        limit=validated_row_limit,
    )

    # Second pass: link to filings and transactions
    load_result.errors += _load_ky_relational_transactions(
        conn,
        _KY_PARSER_FN[data_type](Path(fp), year_from=year_from),
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )
    return load_result


def load_ky_contributions_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    year_from: int | None = None,
    limit: int | None = None,
) -> LoadResult:
    """Load KY contributions from CSV into the DB."""
    return _load_ky_with_filings(conn, fp, data_type="contributions", year_from=year_from, limit=limit)


def load_ky_expenditures_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    year_from: int | None = None,
    limit: int | None = None,
) -> LoadResult:
    """Load KY expenditures from CSV into the DB."""
    return _load_ky_with_filings(conn, fp, data_type="expenditures", year_from=year_from, limit=limit)
