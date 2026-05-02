"""Load NY campaign finance data into the database.

Two-pass loading (same pattern as WA):
1. First pass: insert source records + resolve entities (person/org/address)
2. Second pass: create cf.filing + cf.transaction records linked to source records

NY rows come from the SODA API with sched_date as the transaction date and
org_amt as the transaction amount. The filing_fec_id is synthetic:
  NY-{filer_id}-{election_year}-{data_type}
"""

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
    DataSource,
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
from .extract import extract_ny_contribution, extract_ny_expenditure
from .parse import parse_contributions, parse_expenditures, parse_independent_expenditures

LOGGER = logging.getLogger(__name__)

_NY_DOMAIN = "campaign_finance"
_NY_JURISDICTION = "state/NY"
_NY_SOURCE_FORMAT = "csv"
_normalize_optional_text = normalize_optional_text


@dataclass(slots=True)
class _NYLoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _NYFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


# Maps data_type -> (person_key, org_key) in the extraction TypedDict.
_NY_ENTITY_KEYS: dict[str, tuple[str, str]] = {
    "contributions": ("donor_person", "donor_org"),
    "expenditures": ("payee_person", "payee_org"),
    "independent_expenditures": ("payee_person", "payee_org"),
}

# Maps data_type -> extraction function.
_NY_EXTRACT_FN = {
    "contributions": extract_ny_contribution,
    "expenditures": extract_ny_expenditure,
    "independent_expenditures": extract_ny_expenditure,
}

# Maps data_type -> parser function.
_NY_PARSER_FN = {
    "contributions": parse_contributions,
    "expenditures": parse_expenditures,
    "independent_expenditures": parse_independent_expenditures,
}

# Semantic path for the counterparty name (for contributor_name_raw on Transaction).
_NY_COUNTERPARTY_NAME_PATHS: dict[str, list[str]] = {
    # For contributions, try org name first, then last name.
    "contributions": ["donor.org_name", "donor.last_name"],
    "expenditures": ["payee.org_name", "payee.last_name"],
    "independent_expenditures": ["payee.org_name", "payee.last_name"],
}

# Semantic path for donor employer.
_NY_COUNTERPARTY_EMPLOYER_PATH: dict[str, str | None] = {
    "contributions": None,  # NY SODA doesn't have employer fields
    "expenditures": None,
    "independent_expenditures": None,
}

# Entity roles for entity_source linkage.
_NY_ENTITY_ROLES: dict[str, dict[str, str]] = {
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
    "independent_expenditures": {
        "person": "payee",
        "organization": "payee_org",
        "committee": "paying_committee",
        "address": "payee_address",
    },
}

# For resolve_transaction_counterparty_ids: (person_roles, organization_roles).
_NY_COUNTERPARTY_ROLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "contributions": (("donor",), ("donor_org",)),
    "expenditures": (("payee",), ("payee_org",)),
    "independent_expenditures": (("payee",), ("payee_org",)),
}


# ---------- Data source ----------


def ensure_ny_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    """Ensure the NY data source row exists in core.data_source."""
    normalized = data_type.strip().lower()
    return ensure_data_source(
        conn,
        DataSource(
            domain=_NY_DOMAIN,
            jurisdiction=_NY_JURISDICTION,
            name=_load_data_source_name_for_data_type(normalized),
            source_url=_load_data_source_url_for_data_type(normalized),
            source_format=_NY_SOURCE_FORMAT,
        ),
    )


# ---------- Source record building ----------


def _ny_source_record_key(row: Mapping[str, str | None]) -> str:
    """Compute a deterministic hash key for deduplication."""
    return compute_record_hash(dict(row))


def _build_ny_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> SourceRecord:
    """Build a SourceRecord from a parsed row."""
    raw_fields = dict(row)
    record_hash = compute_record_hash(raw_fields)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=record_hash,
        source_url=_source_record_url(row, data_type=data_type),
        raw_fields=raw_fields,
        record_hash=record_hash,
        pull_date=utc_now(),
    )


def _source_record_url(row: Mapping[str, str | None], *, data_type: str) -> str:
    """Build a source URL for the row (falls back to data source URL)."""
    # NY SODA rows don't have a per-row URL field — use the dataset URL.
    return _load_data_source_url_for_data_type(data_type)


# ---------- Committee resolution ----------


def _resolve_ny_committee_id(conn: psycopg.Connection, committee_org: object) -> UUID:
    """Resolve committee Organization to a core.organization row ID.

    Tries identifier lookup first (ny_filer_id), then falls back to name.
    """
    # committee_org is an Organization from extract.py
    from core.types.python.models import Organization

    if not isinstance(committee_org, Organization):
        raise TypeError(f"Expected Organization, got {type(committee_org)!r}")

    ny_filer_id = _normalize_optional_text(committee_org.identifiers.get("ny_filer_id"))
    if ny_filer_id is not None:
        existing = find_organization_by_identifier(conn, "ny_filer_id", ny_filer_id)
        if existing is not None:
            return existing
    return resolve_organization_by_canonical_name(conn, committee_org)


# ---------- Entity loading ----------


def _load_ny_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: dict,
    data_type: str,
) -> None:
    """Insert/upsert person, org, committee, and address entities, linking to source record."""
    roles = _NY_ENTITY_ROLES[data_type]
    person_key, org_key = _NY_ENTITY_KEYS[data_type]

    # Address
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

    # Person (donor/payee)
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

    # Committee
    committee = extracted["committee"]
    committee_id = _resolve_ny_committee_id(conn, committee)
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_id,
        source_record_id=source_record_id,
        extraction_role=roles["committee"],
        address_id=None,
    )

    # Organization (donor org / payee org)
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


# ---------- Row-level loading (pass 1) ----------


def _extract_and_load_ny_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    """Insert source record + extract/link entities. Returns True if inserted."""
    extract_fn = _NY_EXTRACT_FN.get(data_type)
    if extract_fn is None:
        raise ValueError(f"Unsupported NY data_type: {data_type}")

    source_record_id = try_insert_source_record(
        conn,
        _build_ny_source_record(data_source_id, row, data_type=data_type),
    )
    if source_record_id is None:
        return False  # Duplicate

    extracted = extract_fn(dict(row))
    _load_ny_transaction_entities(
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
    """Try to load a single row, catching exceptions. Returns None on error."""
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return _extract_and_load_ny_row(conn, row, data_source_id, data_type=data_type)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading NY %s row", data_type.rstrip("s"))
        return None


def _load_ny_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    """Load parsed rows into core.source_record + entity tables (pass 1)."""
    started_at = time.monotonic()
    counts = _NYLoadCounts()
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

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
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _load_ny_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    """Parse a CSV file and load rows (pass 1)."""
    validated_row_limit = validated_limit(limit)
    parser = _NY_PARSER_FN[data_type](Path(file_path))
    return _load_ny_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


# ---------- Filing/transaction loading (pass 2) ----------


def _parse_optional_ny_date(raw_value: str | None) -> date | None:
    """Parse SODA floating_timestamp dates. Handles ISO 8601 and common formats."""
    normalized = _normalize_optional_text(raw_value)
    if normalized is None:
        return None

    # SODA typically returns "2024-01-15T00:00:00.000" format.
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        pass

    # Strip timezone designator if present.
    normalized_iso = normalized.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized_iso).date()
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(fmt, normalized).date()
        except ValueError:
            continue
    raise ValueError(f"NY row has invalid date: {raw_value!r}")


def _required_ny_text(value: str | None, field_name: str) -> str:
    """Require a non-empty text value."""
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise ValueError(f"NY row missing {field_name}")
    return normalized


def _parse_required_ny_amount(raw_value: str | None, field_name: str) -> Decimal:
    """Parse a required monetary amount."""
    normalized = _required_ny_text(raw_value, field_name)
    try:
        return Decimal(normalized.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"NY row has invalid {field_name}: {raw_value!r}") from exc


def _build_ny_filing_fec_id(row: Mapping[str, str | None], data_type: str) -> str:
    """Build a synthetic filing ID: NY-{filer_id}-{election_year}-{data_type}."""
    committee_id_col = _load_column_for_semantic_path(data_type, "committee.id")
    year_col = _load_column_for_semantic_path(data_type, "transaction.year")
    committee_id = _required_ny_text(row.get(committee_id_col), committee_id_col)
    filing_year = _normalize_optional_text(row.get(year_col))

    if filing_year is None:
        # Fall back to extracting year from transaction date.
        date_col = _load_column_for_semantic_path(data_type, "transaction.date")
        txn_date = _parse_optional_ny_date(row.get(date_col))
        if txn_date is None:
            raise ValueError("NY row missing both election_year and sched_date")
        filing_year = str(txn_date.year)

    return f"NY-{committee_id}-{filing_year}-{data_type}"


def _resolve_ny_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    """Resolve row -> committee_id in cf.committee via ensure_state_committee."""
    extracted = _NY_EXTRACT_FN[data_type](dict(row))
    org_id = _resolve_ny_committee_id(conn, extracted["committee"])
    committee_id_col = _load_column_for_semantic_path(data_type, "committee.id")
    native_id = _required_ny_text(row.get(committee_id_col), committee_id_col)
    return ensure_state_committee(
        conn,
        state="NY",
        native_committee_id=native_id,
        organization_id=org_id,
    )


def _build_ny_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    """Build a Filing model from a parsed row."""
    committee_name_col = _load_column_for_semantic_path(data_type, "committee.name")
    date_col = _load_column_for_semantic_path(data_type, "transaction.date")
    txn_date = _parse_optional_ny_date(row.get(date_col))

    # NY SODA has r_amend field — treat "Y" as amendment.
    amend_col = _load_column_for_semantic_path(data_type, "ny.r_amend")
    is_amendment = _normalize_optional_text(row.get(amend_col)) == "Y"

    return Filing(
        filing_fec_id=_build_ny_filing_fec_id(row, data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator="A" if is_amendment else "N",
        filing_name=_normalize_optional_text(row.get(committee_name_col)),
        receipt_date=txn_date,
        accepted_date=txn_date,
        source_record_id=source_record_id,
    )


def _upsert_ny_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _NYFilingLookupEntry],
) -> _NYFilingLookupEntry:
    """Upsert a filing, caching by filing_fec_id to avoid redundant lookups."""
    filing_fec_id = _build_ny_filing_fec_id(row, data_type)
    existing = filing_lookup.get(filing_fec_id)

    if existing is None:
        committee_id = _resolve_ny_filing_committee_id(conn, row, data_type)
        filing_src = source_record_id
    else:
        committee_id = existing.committee_id
        filing_src = existing.source_record_id

    filing = _build_ny_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_src,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)

    entry = _NYFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_src,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None], data_type: str) -> str | None:
    """Extract the raw counterparty name for the Transaction model."""
    paths = _NY_COUNTERPARTY_NAME_PATHS.get(data_type, [])
    for path in paths:
        col = _load_column_for_semantic_path(data_type, path)
        value = _normalize_optional_text(row.get(col))
        if value is not None:
            return value
    return None


def _resolve_ny_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    """Look up the address entity linked to this source record."""
    address_role = _NY_ENTITY_ROLES[data_type]["address"]
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


def _resolve_ny_transaction_type(row: Mapping[str, str | None], *, data_type: str) -> str:
    """Resolve transaction_type with canonical IE labeling."""
    if data_type == "independent_expenditures":
        return "Independent Expenditure"
    sched_col = _load_column_for_semantic_path(data_type, "ny.filing_sched_abbrev")
    return _normalize_optional_text(row.get(sched_col)) or data_type.rstrip("s")


def _upsert_ny_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> None:
    """Build and upsert a Transaction linked to the filing."""
    person_roles, org_roles = _NY_COUNTERPARTY_ROLES[data_type]
    person_id, org_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=org_roles,
    )
    address_id = _resolve_ny_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
    )

    # Extract address components for denormalized Transaction fields.
    extracted = _NY_EXTRACT_FN[data_type](dict(row))
    addr = extracted.get("address")
    contributor_state = addr.state if addr is not None else None
    contributor_city = addr.city if addr is not None else None
    contributor_zip = addr.zip5 if addr is not None else None

    amount_col = _load_column_for_semantic_path(data_type, "transaction.amount")
    date_col = _load_column_for_semantic_path(data_type, "transaction.date")

    txn_type = _resolve_ny_transaction_type(row, data_type=data_type)

    # Use trans_number as the unique transaction identifier.
    trans_num_col = _load_column_for_semantic_path(data_type, "ny.trans_number")
    txn_identifier = _normalize_optional_text(row.get(trans_num_col)) or _ny_source_record_key(row)

    # NY r_amend flag for amendment detection.
    amend_col = _load_column_for_semantic_path(data_type, "ny.r_amend")
    is_amendment = _normalize_optional_text(row.get(amend_col)) == "Y"

    # Memo/explanation text.
    memo_col = _load_column_for_semantic_path(data_type, "transaction.description")
    memo_text = _normalize_optional_text(row.get(memo_col))

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=txn_type,
            transaction_identifier=txn_identifier,
            transaction_date=_parse_optional_ny_date(row.get(date_col)),
            amount=_parse_required_ny_amount(row.get(amount_col), amount_col),
            contributor_name_raw=_counterparty_name_raw(row, data_type),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=person_id,
            contributor_organization_id=org_id,
            contributor_address_id=address_id,
            recipient_committee_id=committee_id,
            amendment_indicator="A" if is_amendment else "N",
            memo_text=memo_text,
            source_record_id=source_record_id,
        ),
    )


def _select_ny_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    """Look up a source record by its hash key."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (data_source_id, source_record_key),
        )
        result = cursor.fetchone()
    return result[0] if result else None


def _load_ny_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> int:
    """Pass 2: create cf.filing + cf.transaction for rows with existing source records."""
    filing_lookup: dict[str, _NYFilingLookupEntry] = {}
    relational_errors = 0
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_ny_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_ny_source_record_key(row),
        )
        if source_record_id is None:
            continue

        filing_fec_id = _build_ny_filing_fec_id(row, data_type)
        was_cached = filing_fec_id in filing_lookup
        try:
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                filing_entry = _upsert_ny_filing(
                    conn,
                    row,
                    source_record_id=source_record_id,
                    data_type=data_type,
                    filing_lookup=filing_lookup,
                )
                _upsert_ny_transaction_with_filing(
                    conn,
                    row,
                    filing_id=filing_entry.filing_id,
                    committee_id=filing_entry.committee_id,
                    source_record_id=source_record_id,
                    data_type=data_type,
                )
        except Exception:  # noqa: BLE001
            if not was_cached:
                filing_lookup.pop(filing_fec_id, None)
            relational_errors += 1
            LOGGER.exception("Failed linking NY %s row to filing", data_type.rstrip("s"))

    commit_managed_transaction(conn, manages_outer)
    return relational_errors


# ---------- Public load functions ----------


def _load_ny_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    """Full two-pass load: source records + entities, then filings + transactions."""
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_ny_data_source(conn, data_type=data_type)
    # ensure_ny_data_source leaves conn IN_TRANSACTION; commit so _load_ny_rows
    # sees IDLE and enables periodic commits every 1000 rows.
    conn.commit()

    # Pass 1: source records + entity resolution.
    load_result = _load_ny_file(
        conn,
        file_path,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )

    # Pass 2: filings + transactions (re-parses the file).
    load_result.errors += _load_ny_relational_transactions(
        conn,
        _NY_PARSER_FN[data_type](Path(file_path)),
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )
    return load_result


def load_ny_contributions_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    """Load NY contributions from CSV with filing + transaction creation."""
    return _load_ny_with_filings(conn, fp, data_type="contributions", limit=limit)


def load_ny_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    """Load NY expenditures from CSV with filing + transaction creation."""
    return _load_ny_with_filings(conn, fp, data_type="expenditures", limit=limit)


def load_ny_independent_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    """Load NY independent expenditures from CSV with filing + transaction creation."""
    return _load_ny_with_filings(conn, fp, data_type="independent_expenditures", limit=limit)
