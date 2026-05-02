
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
from .extract import extract_ne_contribution, extract_ne_expenditure, extract_ne_loan
from .parse import parse_contributions, parse_expenditures, parse_loans

LOGGER = logging.getLogger(__name__)

_NE_DOMAIN = "campaign_finance"
_NE_JURISDICTION = "state/NE"
_NE_SOURCE_FORMAT = "csv"
_normalize_optional_text = normalize_optional_text


@dataclass(slots=True)
class _NELoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _NEFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


_NE_ENTITY_KEYS: dict[str, tuple[str, str]] = {
    "contributions": ("donor_person", "donor_org"),
    "loans": ("lender_person", "lender_org"),
    "expenditures": ("payee_person", "payee_org"),
}

_NE_EXTRACT_FN = {
    "contributions": extract_ne_contribution,
    "loans": extract_ne_loan,
    "expenditures": extract_ne_expenditure,
}

_NE_PARSER_FN = {
    "contributions": parse_contributions,
    "loans": parse_loans,
    "expenditures": parse_expenditures,
}

_NE_ENTITY_ROLES: dict[str, dict[str, str]] = {
    "contributions": {
        "person": "donor",
        "organization": "donor_org",
        "committee": "recipient_committee",
        "address": "donor_address",
    },
    "loans": {
        "person": "lender",
        "organization": "lender_org",
        "committee": "recipient_committee",
        "address": "lender_address",
    },
    "expenditures": {
        "person": "payee",
        "organization": "payee_org",
        "committee": "paying_committee",
        "address": "payee_address",
    },
}

_NE_COUNTERPARTY_ROLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "contributions": (("donor",), ("donor_org",)),
    "loans": (("lender",), ("lender_org",)),
    "expenditures": (("payee",), ("payee_org",)),
}

_NE_TRANSACTION_KIND: dict[str, str] = {
    "contributions": "contribution",
    "loans": "loan",
    "expenditures": "expenditure",
}

_NE_SUPPORT_OPPOSE_MAP: dict[str, str] = {
    "S": "S",
    "SUPPORT": "S",
    "FOR": "S",
    "O": "O",
    "OPPOSE": "O",
    "AGAINST": "O",
    "OPPOSITION": "O",
}


def _ne_support_oppose(row: Mapping[str, str | None]) -> str | None:
    """Normalize the NE ``Support Or Oppose`` field to canonical ``"S"``/``"O"``.

    Returns ``None`` for empty/missing values.  Raises ``ValueError`` on
    unexpected tokens so data drift fails loudly rather than silently
    misclassifying rows.
    """
    column_name = _load_column_for_semantic_path("expenditures", "ne.support_or_oppose")
    raw_value = _normalize_optional_text(row.get(column_name))
    if raw_value is None:
        return None
    try:
        return _NE_SUPPORT_OPPOSE_MAP[raw_value.upper()]
    except KeyError as error:
        raise ValueError(f"Unsupported NE independent expenditure support/oppose value: {raw_value!r}") from error


# NE expenditure transaction type values that indicate independent expenditures,
# even when the ``Support Or Oppose`` field is null.
_NE_IE_TRANSACTION_TYPE_TOKENS: frozenset[str] = frozenset(
    {
        "INDEPENDENT EXPENDITURE",
        "IND. EXPEND. CONTRIBUTOR SOURCE OVER $250",
    }
)


def _ne_is_independent_expenditure(row: Mapping[str, str | None]) -> bool:
    """Return True if the row is an independent expenditure by either signal.

    NE has two IE signals: the ``Support Or Oppose`` field (non-null = IE with
    direction) and the ``Expenditure Transaction Type`` field (contains "Independent
    Expenditure" even when support/oppose is null). The Apr 2026 Hetzner proof found
    42 raw IE rows but only 12 had support/oppose populated — the other 30 have the
    transaction type but no direction. Both signals should classify as IE.
    """
    if _ne_support_oppose(row) is not None:
        return True
    type_col = _load_column_for_semantic_path("expenditures", "ne.expenditure_transaction_type")
    raw_type = _normalize_optional_text(row.get(type_col))
    if raw_type is None:
        return False
    return raw_type.upper() in _NE_IE_TRANSACTION_TYPE_TOKENS


def ensure_ne_data_source(conn: psycopg.Connection, data_type: str) -> UUID:
    normalized = data_type.strip().lower()
    return ensure_data_source(
        conn,
        DataSource(
            domain=_NE_DOMAIN,
            jurisdiction=_NE_JURISDICTION,
            name=_load_data_source_name_for_data_type(normalized),
            source_url=_load_data_source_url_for_data_type(normalized),
            source_format=_NE_SOURCE_FORMAT,
        ),
    )


def _ne_source_record_key(row: Mapping[str, str | None]) -> str:
    return compute_record_hash(dict(row))


def _build_ne_source_record(
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


def _resolve_ne_committee_id(conn: psycopg.Connection, committee_org: object) -> UUID:
    from core.types.python.models import Organization

    if not isinstance(committee_org, Organization):
        raise TypeError(f"Expected Organization, got {type(committee_org)}")

    ne_org_id = _normalize_optional_text(committee_org.identifiers.get("ne_org_id"))
    if ne_org_id is not None:
        existing = find_organization_by_identifier(conn, "ne_org_id", ne_org_id)
        if existing is not None:
            return existing
    return resolve_organization_by_canonical_name(conn, committee_org)


def _load_ne_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: dict,
    data_type: str,
) -> None:
    roles = _NE_ENTITY_ROLES[data_type]
    person_key, org_key = _NE_ENTITY_KEYS[data_type]

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
    committee_id = _resolve_ne_committee_id(conn, committee)
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


def _extract_and_load_ne_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    extract_fn = _NE_EXTRACT_FN.get(data_type)
    if extract_fn is None:
        raise ValueError(f"Unsupported NE data type: {data_type}")

    source_record_id = try_insert_source_record(
        conn,
        _build_ne_source_record(data_source_id, row, data_type=data_type),
    )
    if source_record_id is None:
        return False

    extracted = extract_fn(dict(row))
    _load_ne_transaction_entities(
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
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return _extract_and_load_ne_row(conn, row, data_source_id, data_type=data_type)
    except Exception:
        LOGGER.exception("Failed loading NE %s row", data_type.rstrip("s"))
        return None


def _load_ne_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _NELoadCounts()
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


def _load_ne_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    year: int,
    year_from: int | None,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _NE_PARSER_FN[data_type](Path(file_path), year=year, year_from=year_from)
    return _load_ne_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


def _parse_optional_ne_date(raw_value: str | None) -> date | None:
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
    raise ValueError(f"NE row has invalid date: {raw_value}")


def _required_ne_text(value: str | None, field_name: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise ValueError(f"NE row missing {field_name}")
    return normalized


def _parse_required_ne_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized = _required_ne_text(raw_value, field_name)
    try:
        return Decimal(normalized.replace(",", "").replace("$", ""))
    except InvalidOperation as exc:
        raise ValueError(f"NE row has invalid {field_name}: {raw_value}") from exc


def _amendment_indicator(raw_value: str | None) -> str:
    normalized = _normalize_optional_text(raw_value)
    if normalized is None:
        return "N"
    upper = normalized.upper()
    if upper.startswith("Y"):
        return "A"
    if upper.startswith("T"):
        return "T"
    return "N"


def _build_ne_filing_fec_id(row: Mapping[str, str | None], data_type: str) -> str:
    committee_id_col = _load_column_for_semantic_path(data_type, "committee.id")
    filed_date_col = _load_column_for_semantic_path(data_type, "filing.submitted_date")
    committee_id = _normalize_optional_text(row.get(committee_id_col)) or "no-org"
    filed_date = _normalize_optional_text(row.get(filed_date_col)) or "no-filed-date"
    return f"NE-{committee_id}-{filed_date}-{data_type}"


def _resolve_ne_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    extracted = _NE_EXTRACT_FN[data_type](dict(row))
    org_id = _resolve_ne_committee_id(conn, extracted["committee"])
    committee_id_col = _load_column_for_semantic_path(data_type, "committee.id")
    native_id = _normalize_optional_text(row.get(committee_id_col))
    if native_id is None:
        native_id = _build_ne_filing_fec_id(row, data_type)

    return ensure_state_committee(
        conn,
        state="NE",
        native_committee_id=native_id,
        organization_id=org_id,
    )


def _build_ne_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    filed_date_col = _load_column_for_semantic_path(data_type, "filing.submitted_date")
    amended_col = _load_column_for_semantic_path(data_type, "ne.amended")
    filed_date = _parse_optional_ne_date(row.get(filed_date_col))

    return Filing(
        filing_fec_id=_build_ne_filing_fec_id(row, data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator=_amendment_indicator(row.get(amended_col)),
        receipt_date=filed_date,
        accepted_date=filed_date,
        source_record_id=source_record_id,
    )


def _upsert_ne_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _NEFilingLookupEntry],
) -> _NEFilingLookupEntry:
    filing_fec_id = _build_ne_filing_fec_id(row, data_type)
    existing = filing_lookup.get(filing_fec_id)

    if existing is None:
        committee_id = _resolve_ne_filing_committee_id(conn, row, data_type)
        filing_src = source_record_id
    else:
        committee_id = existing.committee_id
        filing_src = existing.source_record_id

    filing = _build_ne_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_src,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)

    entry = _NEFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_src,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    if data_type in {"contributions", "loans"}:
        name_col = _load_column_for_semantic_path(data_type, "donor.org_name")
    else:
        name_col = _load_column_for_semantic_path(data_type, "payee.org_name")
    return _normalize_optional_text(row.get(name_col))


def _counterparty_employer(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    if data_type in {"contributions", "loans"}:
        employer_col = _load_column_for_semantic_path(data_type, "donor.employer")
    else:
        employer_col = _load_column_for_semantic_path(data_type, "payee.employer")
    return _normalize_optional_text(row.get(employer_col))


def _counterparty_occupation(row: Mapping[str, str | None], *, data_type: str) -> str | None:
    if data_type in {"contributions", "loans"}:
        occupation_col = _load_column_for_semantic_path(data_type, "donor.occupation")
    else:
        occupation_col = _load_column_for_semantic_path(data_type, "payee.occupation")
    return _normalize_optional_text(row.get(occupation_col))


def _transaction_identifier(row: Mapping[str, str | None], *, data_type: str) -> str:
    identifier_path = "ne.receipt_id" if data_type in {"contributions", "loans"} else "ne.expenditure_id"
    identifier_col = _load_column_for_semantic_path(data_type, identifier_path)
    return _normalize_optional_text(row.get(identifier_col)) or _ne_source_record_key(row)


def _select_ne_source_record_id(
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


def _resolve_ne_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    address_role = _NE_ENTITY_ROLES[data_type]["address"]
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


def _upsert_ne_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> None:
    person_roles, org_roles = _NE_COUNTERPARTY_ROLES[data_type]
    person_id, org_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=org_roles,
    )
    address_id = _resolve_ne_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
    )

    extracted = _NE_EXTRACT_FN[data_type](dict(row))
    address = extracted.get("address")
    contributor_state = address.state if address is not None else None
    contributor_city = address.city if address is not None else None
    contributor_zip = address.zip5 if address is not None else None

    amount_col = _load_column_for_semantic_path(data_type, "transaction.amount")
    date_col = _load_column_for_semantic_path(data_type, "transaction.date")
    memo_col = _load_column_for_semantic_path(data_type, "transaction.description")
    amended_col = _load_column_for_semantic_path(data_type, "ne.amended")

    support_oppose = _ne_support_oppose(row) if data_type == "expenditures" else None
    is_ie = _ne_is_independent_expenditure(row) if data_type == "expenditures" else False
    transaction_type = "Independent Expenditure" if is_ie else _NE_TRANSACTION_KIND[data_type]

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=transaction_type,
            transaction_identifier=_transaction_identifier(row, data_type=data_type),
            transaction_date=_parse_optional_ne_date(row.get(date_col)),
            amount=_parse_required_ne_amount(row.get(amount_col), amount_col),
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
            support_oppose=support_oppose,
            amendment_indicator=_amendment_indicator(row.get(amended_col)),
            memo_text=_normalize_optional_text(row.get(memo_col)),
            source_record_id=source_record_id,
        ),
    )


def _load_ne_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> int:
    filing_lookup: dict[str, _NEFilingLookupEntry] = {}
    relational_errors = 0
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)}")

        source_record_id = _select_ne_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_ne_source_record_key(row),
        )
        if source_record_id is None:
            continue

        try:
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                filing_entry = _upsert_ne_filing(
                    conn,
                    row,
                    source_record_id=source_record_id,
                    data_type=data_type,
                    filing_lookup=filing_lookup,
                )
                _upsert_ne_transaction_with_filing(
                    conn,
                    row,
                    filing_id=filing_entry.filing_id,
                    committee_id=filing_entry.committee_id,
                    source_record_id=source_record_id,
                    data_type=data_type,
                )
        except Exception:
            relational_errors += 1
            LOGGER.exception("Failed linking NE %s row to filing", data_type.rstrip("s"))

    commit_managed_transaction(conn, manages_outer)
    return relational_errors


def _load_ne_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    data_type: str,
    year: int,
    year_from: int | None = None,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_ne_data_source(conn, data_type=data_type)

    load_result = _load_ne_file(
        conn,
        fp,
        data_source_id=data_source_id,
        data_type=data_type,
        year=year,
        year_from=year_from,
        limit=validated_row_limit,
    )

    load_result.errors += _load_ne_relational_transactions(
        conn,
        _NE_PARSER_FN[data_type](Path(fp), year=year, year_from=year_from),
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )
    return load_result


def load_ne_contributions_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    year: int,
    year_from: int | None = None,
    limit: int | None = None,
) -> LoadResult:
    return _load_ne_with_filings(conn, fp, data_type="contributions", year=year, year_from=year_from, limit=limit)


def load_ne_expenditures_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    year: int,
    year_from: int | None = None,
    limit: int | None = None,
) -> LoadResult:
    return _load_ne_with_filings(conn, fp, data_type="expenditures", year=year, year_from=year_from, limit=limit)


def load_ne_loans_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    year: int,
    year_from: int | None = None,
    limit: int | None = None,
) -> LoadResult:
    return _load_ne_with_filings(conn, fp, data_type="loans", year=year, year_from=year_from, limit=limit)
