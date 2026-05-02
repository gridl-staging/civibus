"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_api_graph_routes_and_property_endpoints/civibus_dev/domains/campaign_finance/jurisdictions/states/GA/scraper/load.py.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.pq import TransactionStatus

from core.db import (
    find_organization_by_identifier,
    find_person_by_name_and_zip,
    insert_entity_address,
    insert_entity_source,
    insert_organization,
    insert_person,
    try_insert_source_record,
    upsert_address,
)
from core.types.python.models import (
    Address,
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
    commit_managed_transaction,
    ensure_data_source,
    ensure_transaction_open,
    validated_limit,
)
from domains.campaign_finance.normalize.addresses import normalize_state
from domains.campaign_finance.types.models import Filing, Transaction

from .extract import build_ga_data_source, extract_ga_contribution, extract_ga_expenditure
from .load_types import (
    LoadResult,
    _GAFilingLookupEntry,
    _GALoadCounts,
    _GARowLoadConfig,
    _GARowLoader,
    _GATransactionEntities,
    _GATransactionRoles,
)
from .parse import parse_contributions, parse_expenditures
from .relational_utils import (
    ga_contributor_name,
    ga_source_record_key,
    json_compatible_raw_fields,
    parse_ga_row_date,
    require_ga_text,
)

LOGGER = logging.getLogger(__name__)

_GA_TRANSACTION_TYPE_FIELD = "Type"
_GA_TRANSACTION_DATE_FIELD = "Date"
_GA_FILING_NAME_FIELD = "Committee_Name"
_GA_AMOUNT_FIELDS_BY_TYPE = {
    "contributions": ("Cash_Amount", "In_Kind_Amount"),
    "expenditures": ("Paid", "Other"),
}
_GA_COUNTERPARTY_ROLES_BY_TYPE = {
    "contributions": (("donor",), ("contributor",)),
    "expenditures": (("payee",), ("payee",)),
}
_GA_EXTRACTOR_BY_TYPE = {
    "contributions": extract_ga_contribution,
    "expenditures": extract_ga_expenditure,
}


_GA_CONTRIBUTION_ENTITY_ROLES = _GATransactionRoles(
    person="donor",
    organization="contributor",
    committee="recipient",
    candidate="candidate",
    address="donor_address",
)
_GA_EXPENDITURE_ENTITY_ROLES = _GATransactionRoles(
    person="payee",
    organization="payee",
    committee="payer",
    candidate="candidate",
    address="payee_address",
)
_normalize_optional_text = normalize_optional_text


def ensure_ga_data_source(conn: psycopg.Connection, transaction_type: str) -> UUID:
    data_source = build_ga_data_source(transaction_type)
    return ensure_data_source(conn, data_source)


def _build_ga_source_record(data_source_id: UUID, row: Mapping[str, object]) -> SourceRecord:
    raw_fields = json_compatible_raw_fields(row)
    record_hash = compute_record_hash(raw_fields)

    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=record_hash,
        raw_fields=raw_fields,
        record_hash=record_hash,
        pull_date=utc_now(),
    )


def _ga_decimal_amount(raw_value: object, field_name: str) -> Decimal | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, Decimal):
        return raw_value
    normalized_value = _normalize_optional_text(raw_value)
    if normalized_value is None:
        return None
    try:
        return Decimal(normalized_value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"GA row has invalid {field_name}: {raw_value!r}") from exc


def _ga_amount_fields(data_type: str) -> tuple[str, str]:
    fields = _GA_AMOUNT_FIELDS_BY_TYPE.get(data_type)
    if fields is None:
        raise ValueError(f"Unsupported GA data_type: {data_type}")
    return fields


def _resolve_ga_transaction_amount(row: Mapping[str, object], data_type: str) -> Decimal:
    primary_field, secondary_field = _ga_amount_fields(data_type)
    primary_amount = _ga_decimal_amount(row.get(primary_field), primary_field)
    secondary_amount = _ga_decimal_amount(row.get(secondary_field), secondary_field)

    if primary_amount is not None and primary_amount != Decimal("0.00"):
        return primary_amount
    if secondary_amount is not None and secondary_amount != Decimal("0.00"):
        return secondary_amount
    if primary_amount is not None:
        return primary_amount
    if secondary_amount is not None:
        return secondary_amount

    raise ValueError(f"GA row is missing both primary and secondary amount fields ({primary_field}, {secondary_field})")


def _ga_extract_row(row: Mapping[str, object], data_type: str) -> dict[str, object]:
    extractor = _GA_EXTRACTOR_BY_TYPE.get(data_type)
    if extractor is None:
        raise ValueError(f"Unsupported GA data_type: {data_type}")
    return extractor(dict(row))


def _build_ga_filing_fec_id(row: Mapping[str, object], data_type: str) -> str:
    filer_id = require_ga_text(row.get("FilerID"), "FilerID")
    transaction_date = parse_ga_row_date(row.get(_GA_TRANSACTION_DATE_FIELD))
    if transaction_date is None:
        raise ValueError("GA row is missing Date")
    return f"GA-{filer_id}-{transaction_date.year}-{data_type}"


def _resolve_ga_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, object],
    data_type: str,
) -> UUID:
    extracted = _ga_extract_row(row, data_type)
    organization_id = _resolve_ga_committee_id(conn, extracted["committee"])
    return ensure_state_committee(
        conn,
        state="GA",
        native_committee_id=require_ga_text(row.get("FilerID"), "FilerID"),
        organization_id=organization_id,
    )


def build_ga_filing(
    row: Mapping[str, object],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    filing_date = parse_ga_row_date(row.get(_GA_TRANSACTION_DATE_FIELD))
    return Filing(
        filing_fec_id=_build_ga_filing_fec_id(row, data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator="N",
        filing_name=_normalize_optional_text(row.get(_GA_FILING_NAME_FIELD)),
        receipt_date=filing_date,
        accepted_date=filing_date,
        source_record_id=source_record_id,
    )


def _select_ga_source_record_id(
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


def _upsert_ga_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, object],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> None:
    person_roles, organization_roles = _GA_COUNTERPARTY_ROLES_BY_TYPE[data_type]
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=organization_roles,
    )
    normalized_state_code = normalize_state(_normalize_optional_text(row.get("State")))
    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=require_ga_text(row.get(_GA_TRANSACTION_TYPE_FIELD), _GA_TRANSACTION_TYPE_FIELD),
            transaction_identifier=ga_source_record_key(row),
            transaction_date=parse_ga_row_date(row.get(_GA_TRANSACTION_DATE_FIELD)),
            amount=_resolve_ga_transaction_amount(row, data_type),
            contributor_name_raw=ga_contributor_name(row),
            contributor_employer=_normalize_optional_text(row.get("Employer")),
            contributor_occupation=_normalize_optional_text(row.get("Occupation"))
            or _normalize_optional_text(row.get("Occupation_or_Employer")),
            contributor_city=_normalize_optional_text(row.get("City")),
            contributor_state=normalized_state_code,
            contributor_zip=_normalize_optional_text(row.get("Zip")),
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
        ),
    )


def _resolve_ga_person_id(
    conn: psycopg.Connection,
    person: Person | None,
    address: Address | None,
) -> UUID | None:
    if person is None:
        return None

    zip5 = address.zip5 if address is not None else None
    existing_person_id = None
    if person.last_name and person.first_name and zip5 is not None:
        existing_person_id = find_person_by_name_and_zip(conn, person.last_name, person.first_name, zip5)
    if existing_person_id is not None:
        return existing_person_id

    return insert_person(conn, person)


def _resolve_ga_committee_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    """Find or insert a GA committee, serialized by advisory lock to prevent deadlocks.

    When multiple concurrent A-Z letter iterations try to insert the same committee,
    they can deadlock on the core.organization table. An advisory lock keyed on the
    committee identifier serializes these find-or-insert operations.
    """
    committee_identifier = committee.identifiers.get("ga_filer_id")
    if committee_identifier:
        # Advisory lock prevents concurrent inserts for the same committee.
        # pg_advisory_xact_lock is released automatically at transaction end.
        lock_key = hash(f"ga_committee:{committee_identifier}") & 0x7FFFFFFFFFFFFFFF
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
        existing_org_id = find_organization_by_identifier(conn, "ga_filer_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id

    return insert_organization(conn, committee)


def _find_organization_id_by_canonical_name(
    conn: psycopg.Connection,
    canonical_name: str,
) -> UUID | None:
    row = conn.execute(
        "SELECT id FROM core.organization WHERE canonical_name = %s LIMIT 1",
        (canonical_name,),
    ).fetchone()
    return row[0] if row is not None else None


def _resolve_ga_named_org_id(
    conn: psycopg.Connection,
    organization: Organization | None,
) -> UUID | None:
    if organization is None:
        return None

    existing_org_id = _find_organization_id_by_canonical_name(conn, organization.canonical_name)
    if existing_org_id is not None:
        return existing_org_id

    return insert_organization(conn, organization)


def _load_ga_transaction_entities(
    conn: psycopg.Connection,
    source_record_id: UUID,
    entities: _GATransactionEntities,
    roles: _GATransactionRoles,
) -> None:
    address_id = None
    if entities.address is not None:
        address_id = upsert_address(conn, entities.address)
        insert_entity_source(conn, "address", address_id, source_record_id, roles.address)

    person_id = _resolve_ga_person_id(conn, entities.person, entities.address)
    if person_id is not None:
        insert_entity_source(conn, "person", person_id, source_record_id, roles.person)
        if address_id is not None:
            insert_entity_address(conn, "person", person_id, address_id, source_record_id, "mailing")

    committee_id = _resolve_ga_committee_id(conn, entities.committee)
    insert_entity_source(conn, "organization", committee_id, source_record_id, roles.committee)

    organization_id = _resolve_ga_named_org_id(conn, entities.organization)
    if organization_id is not None:
        insert_entity_source(conn, "organization", organization_id, source_record_id, roles.organization)
        if address_id is not None:
            insert_entity_address(conn, "organization", organization_id, address_id, source_record_id, "mailing")

    candidate_id = _resolve_ga_person_id(conn, entities.candidate, None)
    if candidate_id is not None:
        insert_entity_source(conn, "person", candidate_id, source_record_id, roles.candidate)


def _try_insert_ga_source_record(
    conn: psycopg.Connection,
    row: Mapping[str, object],
    data_source_id: UUID,
) -> UUID | None:
    return try_insert_source_record(conn, _build_ga_source_record(data_source_id, row))


def _load_ga_transaction_row(
    conn: psycopg.Connection,
    row: Mapping[str, object],
    data_source_id: UUID,
    *,
    entities: _GATransactionEntities,
    roles: _GATransactionRoles,
) -> bool:
    source_record_id = _try_insert_ga_source_record(conn, row, data_source_id)
    if source_record_id is None:
        return False

    _load_ga_transaction_entities(
        conn,
        source_record_id=source_record_id,
        entities=entities,
        roles=roles,
    )
    return True


def load_ga_contribution(
    conn: psycopg.Connection,
    row: Mapping[str, object],
    data_source_id: UUID,
) -> bool:
    extracted = extract_ga_contribution(dict(row))
    return _load_ga_transaction_row(
        conn,
        row,
        data_source_id,
        entities=_GATransactionEntities(
            person=extracted["donor_person"],
            organization=extracted["donor_org"],
            committee=extracted["committee"],
            candidate=extracted["candidate"],
            address=extracted["address"],
        ),
        roles=_GA_CONTRIBUTION_ENTITY_ROLES,
    )


def load_ga_expenditure(
    conn: psycopg.Connection,
    row: Mapping[str, object],
    data_source_id: UUID,
) -> bool:
    extracted = extract_ga_expenditure(dict(row))
    return _load_ga_transaction_row(
        conn,
        row,
        data_source_id,
        entities=_GATransactionEntities(
            person=extracted["payee_person"],
            organization=extracted["payee_org"],
            committee=extracted["committee"],
            candidate=extracted["candidate"],
            address=extracted["address"],
        ),
        roles=_GA_EXPENDITURE_ENTITY_ROLES,
    )


def _try_load_ga_row(
    conn: psycopg.Connection,
    row: Mapping[str, object],
    row_load_config: _GARowLoadConfig,
    manages_outer_transaction: bool,
) -> bool | None:
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return row_load_config.load_row(conn, row, row_load_config.data_source_id)
    except Exception:  # noqa: BLE001
        LOGGER.exception(
            "Failed loading GA %s row with record hash %s",
            row_load_config.row_type_label,
            _safe_row_hash_for_logging(row),
        )
        return None


def _safe_row_hash_for_logging(row: Mapping[str, object]) -> str:
    try:
        return compute_record_hash(json_compatible_raw_fields(row))
    except Exception:  # noqa: BLE001
        return "<unavailable>"


def _maybe_commit_and_log_progress(
    conn: psycopg.Connection,
    *,
    row_type_label: str,
    counts: _GALoadCounts,
    manages_outer_transaction: bool,
) -> None:
    processed_count = counts.inserted + counts.skipped + counts.errors

    if processed_count % 1_000 == 0:
        commit_managed_transaction(conn, manages_outer_transaction)

    if processed_count % 10_000 == 0:
        LOGGER.info(
            "GA %s load progress processed=%s inserted=%s skipped=%s errors=%s",
            row_type_label,
            processed_count,
            counts.inserted,
            counts.skipped,
            counts.errors,
        )


def _load_ga_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, object]],
    row_load_config: _GARowLoadConfig,
    limit: int | None,
    *,
    manages_outer_transaction: bool | None = None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _GALoadCounts()
    if manages_outer_transaction is None:
        manages_outer_transaction = conn.info.transaction_status == TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break

        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        inserted_row = _try_load_ga_row(
            conn,
            row,
            row_load_config,
            manages_outer_transaction=manages_outer_transaction,
        )

        if inserted_row is None:
            counts.errors += 1
        elif inserted_row:
            counts.inserted += 1
        else:
            counts.skipped += 1

        _maybe_commit_and_log_progress(
            conn,
            row_type_label=row_load_config.row_type_label,
            counts=counts,
            manages_outer_transaction=manages_outer_transaction,
        )

    commit_managed_transaction(conn, manages_outer_transaction)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _load_ga_batch(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, object]],
    *,
    transaction_type: str,
    row_loader: _GARowLoader,
    row_type_label: str,
    limit: int | None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    manages_outer_transaction = conn.info.transaction_status == TransactionStatus.IDLE
    data_source_id = ensure_ga_data_source(conn, transaction_type)

    return _load_ga_rows(
        conn,
        rows,
        _GARowLoadConfig(
            load_row=row_loader,
            row_type_label=row_type_label,
            data_source_id=data_source_id,
        ),
        limit=validated_row_limit,
        manages_outer_transaction=manages_outer_transaction,
    )


def load_ga_contributions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, object]],
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_ga_batch(
        conn,
        rows,
        transaction_type="contributions",
        row_loader=load_ga_contribution,
        row_type_label="contribution",
        limit=limit,
    )


def load_ga_expenditures(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, object]],
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_ga_batch(
        conn,
        rows,
        transaction_type="expenditures",
        row_loader=load_ga_expenditure,
        row_type_label="expenditure",
        limit=limit,
    )


def _upsert_ga_filing(
    conn: psycopg.Connection,
    row: Mapping[str, object],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _GAFilingLookupEntry],
) -> _GAFilingLookupEntry:
    filing_fec_id = _build_ga_filing_fec_id(row, data_type)
    existing_entry = filing_lookup.get(filing_fec_id)
    if existing_entry is None:
        committee_id = _resolve_ga_filing_committee_id(conn, row, data_type)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id

    filing = build_ga_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)
    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise ValueError(
            f"GA filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )
    entry = _GAFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _load_ga_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, object]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> None:
    filing_lookup: dict[str, _GAFilingLookupEntry] = {}
    manages_outer_transaction = conn.info.transaction_status == TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        source_record_id = _select_ga_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=ga_source_record_key(row),
        )
        if source_record_id is None:
            continue

        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            filing_entry = _upsert_ga_filing(
                conn,
                row,
                source_record_id=source_record_id,
                data_type=data_type,
                filing_lookup=filing_lookup,
            )
            _upsert_ga_transaction_with_filing(
                conn,
                row,
                filing_id=filing_entry.filing_id,
                committee_id=filing_entry.committee_id,
                source_record_id=source_record_id,
                data_type=data_type,
            )

    commit_managed_transaction(conn, manages_outer_transaction)


def load_ga_contributions_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parsed_path = Path(file_path)
    provenance_result = load_ga_contributions(
        conn,
        parse_contributions(parsed_path),
        limit=validated_row_limit,
    )
    _load_ga_relational_transactions(
        conn,
        parse_contributions(parsed_path),
        data_source_id=ensure_ga_data_source(conn, "contributions"),
        data_type="contributions",
        limit=validated_row_limit,
    )
    return provenance_result


def load_ga_expenditures_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parsed_path = Path(file_path)
    provenance_result = load_ga_expenditures(
        conn,
        parse_expenditures(parsed_path),
        limit=validated_row_limit,
    )
    _load_ga_relational_transactions(
        conn,
        parse_expenditures(parsed_path),
        data_source_id=ensure_ga_data_source(conn, "expenditures"),
        data_type="expenditures",
        limit=validated_row_limit,
    )
    return provenance_result


__all__ = [
    "LoadResult",
    "build_ga_filing",
    "ensure_ga_data_source",
    "load_ga_contribution",
    "load_ga_contributions",
    "load_ga_contributions_with_filings",
    "load_ga_expenditure",
    "load_ga_expenditures",
    "load_ga_expenditures_with_filings",
]
