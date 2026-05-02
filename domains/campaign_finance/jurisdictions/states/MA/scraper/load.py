
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
    _load_data_source_name,
    _load_data_source_url,
)
from .extract import extract_ma_contribution, extract_ma_expenditure
from .parse import parse_contributions, parse_expenditures

LOGGER = logging.getLogger(__name__)

_MA_DOMAIN = "campaign_finance"
_MA_JURISDICTION = "state/MA"
_MA_SOURCE_FORMAT = "tsv"
_normalize_optional_text = normalize_optional_text


@dataclass(slots=True)
class _MALoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _MAFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


_MA_ENTITY_KEYS: dict[str, tuple[str, str]] = {
    "contributions": ("donor_person", "donor_org"),
    "expenditures": ("payee_person", "payee_org"),
}

_MA_EXTRACT_FN = {
    "contributions": extract_ma_contribution,
    "expenditures": extract_ma_expenditure,
}

_MA_PARSER_FN = {
    "contributions": parse_contributions,
    "expenditures": parse_expenditures,
}

_MA_ENTITY_ROLES: dict[str, dict[str, str]] = {
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

_MA_COUNTERPARTY_ROLES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "contributions": (("donor",), ("donor_org",)),
    "expenditures": (("payee",), ("payee_org",)),
}

# MA OCPF Is_Supported field maps to support/oppose for IE classification.
# When Is_Supported is populated on an expenditure row, the row is an IE.
# "1"/"True" = supports candidate, "0"/"False" = opposes candidate.
_MA_SUPPORT_OPPOSE_MAP: dict[str, str] = {
    "1": "S",
    "TRUE": "S",
    "YES": "S",
    "Y": "S",
    "0": "O",
    "FALSE": "O",
    "NO": "O",
    "N": "O",
}


def _ma_support_oppose(row: Mapping[str, str | None]) -> str | None:
    is_supported_col = _load_column_for_semantic_path("contributions", "ma.is_supported")
    raw_value = _normalize_optional_text(row.get(is_supported_col))
    if raw_value is None:
        return None
    try:
        return _MA_SUPPORT_OPPOSE_MAP[raw_value.upper()]
    except KeyError as error:
        raise ValueError(f"Unsupported MA Is_Supported value: {raw_value!r}") from error


# ---------- Data source ----------


def ensure_ma_data_source(conn: psycopg.Connection) -> UUID:
    """Ensure the MA data source row exists in core.data_source."""
    return ensure_data_source(
        conn,
        DataSource(
            domain=_MA_DOMAIN,
            jurisdiction=_MA_JURISDICTION,
            name=_load_data_source_name(),
            source_url=_load_data_source_url(),
            source_format=_MA_SOURCE_FORMAT,
        ),
    )


# ---------- Source record ----------


def _ma_source_record_key(row: Mapping[str, str | None]) -> str:
    return compute_record_hash(dict(row))


def _build_ma_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
) -> SourceRecord:
    raw_fields = dict(row)
    record_hash = compute_record_hash(raw_fields)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=record_hash,
        source_url=_load_data_source_url(),
        raw_fields=raw_fields,
        record_hash=record_hash,
        pull_date=utc_now(),
    )


# ---------- Committee resolution ----------


def _resolve_ma_committee_id(conn: psycopg.Connection, committee_org: object) -> UUID:
    """Resolve committee Organization to core.organization row ID."""
    from core.types.python.models import Organization

    if not isinstance(committee_org, Organization):
        raise TypeError(f"Expected Organization, got {type(committee_org)!r}")

    ma_cpf_id = _normalize_optional_text(committee_org.identifiers.get("ma_cpf_id"))
    if ma_cpf_id is not None:
        existing = find_organization_by_identifier(conn, "ma_cpf_id", ma_cpf_id)
        if existing is not None:
            return existing
    return resolve_organization_by_canonical_name(conn, committee_org)


# ---------- Entity loading ----------


def _load_ma_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: dict,
    data_type: str,
) -> None:
    roles = _MA_ENTITY_ROLES[data_type]
    person_key, org_key = _MA_ENTITY_KEYS[data_type]

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
    committee_id = _resolve_ma_committee_id(conn, committee)
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


# ---------- Row-level loading (pass 1) ----------


def _extract_and_load_ma_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    extract_fn = _MA_EXTRACT_FN.get(data_type)
    if extract_fn is None:
        raise ValueError(f"Unsupported MA data_type: {data_type}")

    source_record_id = try_insert_source_record(
        conn,
        _build_ma_source_record(data_source_id, row),
    )
    if source_record_id is None:
        return False

    extracted = extract_fn(dict(row))
    _load_ma_transaction_entities(
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
            return _extract_and_load_ma_row(conn, row, data_source_id, data_type=data_type)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading MA %s row", data_type.rstrip("s"))
        return None


def _load_ma_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _MALoadCounts()
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


def _load_ma_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _MA_PARSER_FN[data_type](Path(file_path))
    return _load_ma_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


# ---------- Filing/transaction loading (pass 2) ----------


def _parse_optional_ma_date(raw_value: str | None) -> date | None:
    """Parse MA date formats: M/D/YYYY or YYYY-MM-DD."""
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
    raise ValueError(f"MA row has invalid date: {raw_value!r}")


def _required_ma_text(value: str | None, field_name: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise ValueError(f"MA row missing {field_name}")
    return normalized


_TWO_PLACES = Decimal("0.01")


def _parse_required_ma_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized = _required_ma_text(raw_value, field_name)
    try:
        # MA source data occasionally has >2 decimal places (e.g. 100.0010).
        # Quantize to 2 places to match the Transaction model's decimal_places=2.
        return Decimal(normalized.replace(",", "").replace("$", "")).quantize(_TWO_PLACES)
    except InvalidOperation as exc:
        raise ValueError(f"MA row has invalid {field_name}: {raw_value!r}") from exc


def _build_ma_filing_fec_id(row: Mapping[str, str | None], data_type: str) -> str:
    """Synthetic filing ID: MA-{cpf_id}-{report_id}-{data_type}."""
    report_id_col = _load_column_for_semantic_path("contributions", "ma.report_id")
    cpf_id_col = _load_column_for_semantic_path("contributions", "ma.related_cpf_id")
    report_id = _normalize_optional_text(row.get(report_id_col)) or "unknown"
    cpf_id = _normalize_optional_text(row.get(cpf_id_col)) or "no-cpf"
    return f"MA-{cpf_id}-{report_id}-{data_type}"


def _resolve_ma_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    extracted = _MA_EXTRACT_FN[data_type](dict(row))
    org_id = _resolve_ma_committee_id(conn, extracted["committee"])
    return ensure_state_committee(
        conn,
        state="MA",
        native_committee_id=_resolve_ma_filing_native_committee_id(row),
        organization_id=org_id,
    )


def _resolve_ma_filing_native_committee_id(row: Mapping[str, str | None]) -> str:
    """Resolve MA filing committee key used for cf.committee synthetic ID generation."""
    cpf_id_col = _load_column_for_semantic_path("contributions", "ma.related_cpf_id")
    native_id = _normalize_optional_text(row.get(cpf_id_col))
    if native_id is not None:
        return native_id
    report_id_col = _load_column_for_semantic_path("contributions", "ma.report_id")
    return _required_ma_text(row.get(report_id_col), report_id_col)


def _resolve_ma_filing_committee_id_in_short_transaction(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    """Resolve committee id with a short transaction to avoid long-held upsert locks."""
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        return _resolve_ma_filing_committee_id(conn, row, data_type)
    with conn.transaction():
        return _resolve_ma_filing_committee_id(conn, row, data_type)


def _build_ma_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    date_col = _load_column_for_semantic_path("contributions", "transaction.date")
    txn_date = _parse_optional_ma_date(row.get(date_col))

    return Filing(
        filing_fec_id=_build_ma_filing_fec_id(row, data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator="N",
        receipt_date=txn_date,
        accepted_date=txn_date,
        source_record_id=source_record_id,
    )


def _upsert_ma_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _MAFilingLookupEntry],
    committee_id: UUID | None = None,
) -> _MAFilingLookupEntry:
    filing_fec_id = _build_ma_filing_fec_id(row, data_type)
    existing = filing_lookup.get(filing_fec_id)

    if existing is None:
        if committee_id is None:
            committee_id = _resolve_ma_filing_committee_id(conn, row, data_type)
        filing_src = source_record_id
    else:
        committee_id = existing.committee_id
        filing_src = existing.source_record_id

    filing = _build_ma_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_src,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)

    entry = _MAFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_src,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None]) -> str | None:
    """Get the raw counterparty name from the Name field."""
    name_col = _load_column_for_semantic_path("contributions", "donor.org_name")
    return _normalize_optional_text(row.get(name_col))


def _select_ma_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (data_source_id, source_record_key),
        )
        result = cursor.fetchone()
    return result[0] if result else None


def _resolve_ma_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
) -> UUID | None:
    address_role = _MA_ENTITY_ROLES[data_type]["address"]
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT entity_id FROM core.entity_source
            WHERE source_record_id = %s AND entity_type = 'address' AND extraction_role = %s
            LIMIT 1
            """,
            (source_record_id, address_role),
        )
        result = cursor.fetchone()
    return result[0] if result else None


def _upsert_ma_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> None:
    person_roles, org_roles = _MA_COUNTERPARTY_ROLES[data_type]
    person_id, org_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=org_roles,
    )
    address_id = _resolve_ma_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
    )

    extracted = _MA_EXTRACT_FN[data_type](dict(row))
    addr = extracted.get("address")
    contributor_state = addr.state if addr is not None else None
    contributor_city = addr.city if addr is not None else None
    contributor_zip = addr.zip5 if addr is not None else None

    amount_col = _load_column_for_semantic_path("contributions", "transaction.amount")
    date_col = _load_column_for_semantic_path("contributions", "transaction.date")
    desc_col = _load_column_for_semantic_path("contributions", "transaction.description")
    record_type_col = _load_column_for_semantic_path("contributions", "ma.record_type_id")
    item_id_col = _load_column_for_semantic_path("contributions", "ma.item_id")

    support_oppose = _ma_support_oppose(row) if data_type == "expenditures" else None
    txn_type = (
        "Independent Expenditure"
        if support_oppose is not None
        else (_normalize_optional_text(row.get(record_type_col)) or data_type.rstrip("s"))
    )
    txn_identifier = _normalize_optional_text(row.get(item_id_col)) or _ma_source_record_key(row)

    # Employer/occupation from MA data.
    employer_col = _load_column_for_semantic_path("contributions", "donor.employer")
    occupation_col = _load_column_for_semantic_path("contributions", "donor.occupation")

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=txn_type,
            transaction_identifier=txn_identifier,
            transaction_date=_parse_optional_ma_date(row.get(date_col)),
            amount=_parse_required_ma_amount(row.get(amount_col), amount_col),
            contributor_name_raw=_counterparty_name_raw(row),
            contributor_employer=_normalize_optional_text(row.get(employer_col)),
            contributor_occupation=_normalize_optional_text(row.get(occupation_col)),
            contributor_city=contributor_city,
            contributor_state=contributor_state,
            contributor_zip=contributor_zip,
            contributor_person_id=person_id,
            contributor_organization_id=org_id,
            contributor_address_id=address_id,
            recipient_committee_id=committee_id,
            amendment_indicator="N",
            support_oppose=support_oppose,
            memo_text=_normalize_optional_text(row.get(desc_col)),
            source_record_id=source_record_id,
        ),
    )


def _load_ma_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> int:
    if conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS:
        # This pass owns its own transaction boundaries. Commit any ambient transaction
        # (for example, statement_timeout setup) so committee upserts can run in short
        # independent transactions before filing+transaction writes.
        conn.commit()

    filing_lookup: dict[str, _MAFilingLookupEntry] = {}
    committee_lookup: dict[str, UUID] = {}
    relational_errors = 0
    manages_outer = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_ma_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_ma_source_record_key(row),
        )
        if source_record_id is None:
            continue

        filing_fec_id = _build_ma_filing_fec_id(row, data_type)
        was_cached = filing_fec_id in filing_lookup
        try:
            committee_id: UUID | None = None
            if not was_cached:
                # Keep MA committee upserts in short transactions before filing+transaction writes.
                # Contribution and expenditure lanes can share one Related_CPF_ID; if committee
                # upsert stays inside the longer relational transaction, one lane can time out
                # waiting on the cf.committee index tuple lock held by the other lane.
                native_committee_id = _resolve_ma_filing_native_committee_id(row)
                committee_id = committee_lookup.get(native_committee_id)
                if committee_id is None:
                    committee_id = _resolve_ma_filing_committee_id_in_short_transaction(conn, row, data_type)
                    committee_lookup[native_committee_id] = committee_id
            if manages_outer:
                ensure_transaction_open(conn)
            with conn.transaction():
                filing_entry = _upsert_ma_filing(
                    conn,
                    row,
                    source_record_id=source_record_id,
                    data_type=data_type,
                    filing_lookup=filing_lookup,
                    committee_id=committee_id,
                )
                _upsert_ma_transaction_with_filing(
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
            LOGGER.exception("Failed linking MA %s row to filing", data_type.rstrip("s"))

    commit_managed_transaction(conn, manages_outer)
    return relational_errors


# ---------- Public load functions ----------


def _load_ma_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_ma_data_source(conn)
    # ensure_ma_data_source leaves conn IN_TRANSACTION; commit so _load_ma_rows
    # sees IDLE and enables periodic commits every 1000 rows.
    conn.commit()

    load_result = _load_ma_file(
        conn,
        file_path,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )

    load_result.errors += _load_ma_relational_transactions(
        conn,
        _MA_PARSER_FN[data_type](Path(file_path)),
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )
    return load_result


def load_ma_contributions_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_ma_with_filings(conn, fp, data_type="contributions", limit=limit)


def load_ma_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_ma_with_filings(conn, fp, data_type="expenditures", limit=limit)
