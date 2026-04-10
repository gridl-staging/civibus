
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping
from uuid import UUID

import psycopg

from core.db import (
    find_organization_by_identifier,
    insert_organization,
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

from .extract import extract_co_contribution, extract_co_expenditure
from .parse import is_superseded, parse_co_date, parse_contributions, parse_expenditures

LOGGER = logging.getLogger(__name__)

_CO_DOMAIN = "campaign_finance"
_CO_JURISDICTION = "state/CO"
_CO_CONTRIBUTIONS_NAME = "TRACER Bulk Download — Contributions"
_CO_EXPENDITURES_NAME = "TRACER Bulk Download — Expenditures"
_CO_CONTRIBUTIONS_URL = "https://tracer.sos.colorado.gov/PublicSite/DataDownload.aspx"
_CO_SOURCE_FORMAT = "csv"
_CO_DATA_SOURCE_NAME_BY_TYPE = {
    "contributions": _CO_CONTRIBUTIONS_NAME,
    "expenditures": _CO_EXPENDITURES_NAME,
}
_CO_TRANSACTION_FIELD_BY_TYPE = {
    "contributions": ("ContributionType", "ContributionAmount", "ContributionDate"),
    "expenditures": ("ExpenditureType", "ExpenditureAmount", "ExpenditureDate"),
}
_CO_COUNTERPARTY_ROLES_BY_TYPE = {
    "contributions": (("donor",), ("contributor",)),
    "expenditures": (("payee",), ("payee",)),
}
_CO_EXTRACTOR_BY_TYPE = {
    "contributions": extract_co_contribution,
    "expenditures": extract_co_expenditure,
}
_CORowLoader = Callable[[psycopg.Connection, Mapping[str, str | None], UUID], bool]


@dataclass(slots=True)
class _COLoadCounts:
    inserted: int = 0
    skipped: int = 0
    superseded: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _CORowLoadConfig:
    load_row: _CORowLoader
    row_type_label: str
    data_source_id: UUID


@dataclass(frozen=True, slots=True)
class _COTransactionEntities:
    person: Person | None
    organization: Organization | None
    committee: Organization
    address: Address | None


@dataclass(frozen=True, slots=True)
class _COTransactionRoles:
    person: str
    organization: str
    committee: str
    address: str


@dataclass(frozen=True, slots=True)
class _COFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID


_CO_CONTRIBUTION_ENTITY_ROLES = _COTransactionRoles(
    person="donor",
    organization="contributor",
    committee="recipient",
    address="contributor_address",
)
_CO_EXPENDITURE_ENTITY_ROLES = _COTransactionRoles(
    person="payee",
    organization="payee",
    committee="payer",
    address="payee_address",
)
_normalize_optional_text = normalize_optional_text


def ensure_co_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    data_source_name = _CO_DATA_SOURCE_NAME_BY_TYPE.get(data_type)
    if data_source_name is None:
        raise ValueError(f"Unsupported CO data_type: {data_type}")

    data_source = DataSource(
        domain=_CO_DOMAIN,
        jurisdiction=_CO_JURISDICTION,
        name=data_source_name,
        source_url=_CO_CONTRIBUTIONS_URL,
        source_format=_CO_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _build_co_source_record(data_source_id: UUID, row: Mapping[str, str | None]) -> SourceRecord:
    raw_fields = dict(row)
    source_record_key = _required_source_record_key(row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _required_source_record_key(row: Mapping[str, str | None]) -> str:
    source_record_key = row.get("RecordID")
    if source_record_key is None:
        raise ValueError("CO row is missing RecordID")

    normalized_source_record_key = source_record_key.strip()
    if not normalized_source_record_key:
        raise ValueError("CO row is missing RecordID")

    return normalized_source_record_key


def _required_co_text(value: str | None, field_name: str) -> str:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"CO row is missing {field_name}")
    return normalized_value


def _parse_optional_co_date(raw_value: str | None) -> date | None:
    parsed_value = parse_co_date(raw_value)
    if parsed_value is None:
        return None
    return date.fromisoformat(parsed_value)


def _parse_required_co_amount(raw_value: str | None, field_name: str) -> Decimal:
    normalized_value = _required_co_text(raw_value, field_name)
    try:
        return Decimal(normalized_value)
    except InvalidOperation as exc:
        raise ValueError(f"CO row has invalid {field_name}: {raw_value!r}") from exc


def _to_co_amendment_indicator(row: Mapping[str, str | None]) -> str:
    amendment_flag = _normalize_optional_text(row.get("Amendment"))
    if amendment_flag == "Y":
        return "A"
    if amendment_flag in {None, "N"}:
        return "N"
    raise ValueError(f"Unknown CO Amendment flag: {amendment_flag!r}")


def _co_transaction_fields(data_type: str) -> tuple[str, str, str]:
    fields = _CO_TRANSACTION_FIELD_BY_TYPE.get(data_type)
    if fields is None:
        raise ValueError(f"Unsupported CO data_type: {data_type}")
    return fields


def _co_extract_row(
    row: Mapping[str, str | None],
    data_type: str,
) -> dict[str, object]:
    extractor = _CO_EXTRACTOR_BY_TYPE.get(data_type)
    if extractor is None:
        raise ValueError(f"Unsupported CO data_type: {data_type}")
    return extractor(dict(row))


def _co_contributor_name(row: Mapping[str, str | None]) -> str | None:
    first_name = _normalize_optional_text(row.get("FirstName"))
    last_name = _normalize_optional_text(row.get("LastName"))
    joined_name = " ".join(name for name in (first_name, last_name) if name is not None)
    return _normalize_optional_text(joined_name) or last_name


def _build_co_filing_fec_id(row: Mapping[str, str | None], data_type: str) -> str:
    committee_identifier = _required_co_text(row.get("CO_ID"), "CO_ID")
    filed_date = _parse_optional_co_date(row.get("FiledDate"))
    if filed_date is None:
        raise ValueError("CO row is missing FiledDate")
    return f"CO-{committee_identifier}-{filed_date.year}-{data_type}"


def _resolve_co_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
) -> UUID:
    extracted = _co_extract_row(row, data_type)
    organization_id = _resolve_co_committee_id(conn, extracted["committee"])
    return ensure_state_committee(
        conn,
        state="CO",
        native_committee_id=_required_co_text(row.get("CO_ID"), "CO_ID"),
        organization_id=organization_id,
    )


def build_co_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> Filing:
    return Filing(
        filing_fec_id=_build_co_filing_fec_id(row, data_type),
        committee_id=committee_id,
        report_type=data_type,
        amendment_indicator=_to_co_amendment_indicator(row),
        filing_name=_normalize_optional_text(row.get("CommitteeName")),
        receipt_date=_parse_optional_co_date(row.get("FiledDate")),
        accepted_date=_parse_optional_co_date(row.get("FiledDate")),
        source_record_id=source_record_id,
    )


def _select_co_source_record_id(
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
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (data_source_id, source_record_key),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


_CO_ELECTIONEERING_TRUTHY = frozenset({"y", "yes", "true", "1"})


def _co_is_electioneering(row: Mapping[str, str | None]) -> bool:
    """Check whether a CO row has Electioneering=Y (truthy boolean column)."""
    raw_value = row.get("Electioneering")
    if raw_value is None:
        return False
    stripped = raw_value.strip()
    if not stripped:
        return False
    return stripped.casefold() in _CO_ELECTIONEERING_TRUTHY


def _upsert_co_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_type: str,
) -> None:
    transaction_type_field, amount_field, date_field = _co_transaction_fields(data_type)
    person_roles, organization_roles = _CO_COUNTERPARTY_ROLES_BY_TYPE[data_type]
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=organization_roles,
    )
    is_ie = data_type == "expenditures" and _co_is_electioneering(row)
    transaction_type = (
        "Independent Expenditure"
        if is_ie
        else _required_co_text(row.get(transaction_type_field), transaction_type_field)
    )
    state_code = _normalize_optional_text(row.get("State"))
    normalized_state_code = state_code.upper() if state_code is not None else None
    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type=transaction_type,
            transaction_identifier=_required_source_record_key(row),
            transaction_date=_parse_optional_co_date(row.get(date_field)),
            amount=_parse_required_co_amount(row.get(amount_field), amount_field),
            contributor_name_raw=_co_contributor_name(row),
            contributor_employer=_normalize_optional_text(row.get("Employer")),
            contributor_occupation=_normalize_optional_text(row.get("Occupation")),
            contributor_city=_normalize_optional_text(row.get("City")),
            contributor_state=normalized_state_code,
            contributor_zip=_normalize_optional_text(row.get("Zip")),
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            amendment_indicator=_to_co_amendment_indicator(row),
            source_record_id=source_record_id,
        ),
    )


def _upsert_co_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _COFilingLookupEntry],
) -> _COFilingLookupEntry:
    filing_fec_id = _build_co_filing_fec_id(row, data_type)
    existing_entry = filing_lookup.get(filing_fec_id)
    if existing_entry is None:
        committee_id = _resolve_co_filing_committee_id(conn, row, data_type)
        filing_source_record_id = source_record_id
    else:
        committee_id = existing_entry.committee_id
        filing_source_record_id = existing_entry.source_record_id
    filing = build_co_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_type=data_type,
    )
    filing_id = upsert_filing(conn, filing)
    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise ValueError(
            f"CO filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )
    entry = _COFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _load_co_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> None:
    filing_lookup: dict[str, _COFilingLookupEntry] = {}
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")
        source_record_key = row.get("RecordID")
        if _normalize_optional_text(source_record_key) is None:
            continue
        source_record_id = _select_co_source_record_id(
            conn,
            data_source_id=data_source_id,
            source_record_key=_required_source_record_key(row),
        )
        if source_record_id is None:
            continue
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            filing_entry = _upsert_co_filing(
                conn,
                row,
                source_record_id=source_record_id,
                data_type=data_type,
                filing_lookup=filing_lookup,
            )
            if not is_superseded(row):
                _upsert_co_transaction_with_filing(
                    conn,
                    row,
                    filing_id=filing_entry.filing_id,
                    committee_id=filing_entry.committee_id,
                    source_record_id=source_record_id,
                    data_type=data_type,
                )
    commit_managed_transaction(conn, manages_outer_transaction)


def _resolve_co_committee_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_identifier = committee.identifiers.get("co_committee_id")
    if committee_identifier:
        existing_org_id = find_organization_by_identifier(conn, "co_committee_id", committee_identifier)
        if existing_org_id is not None:
            return existing_org_id

    return insert_organization(conn, committee)


def _load_co_transaction_entities(
    conn: psycopg.Connection,
    source_record_id: UUID,
    entities: _COTransactionEntities,
    roles: _COTransactionRoles,
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

    committee_id = _resolve_co_committee_id(conn, entities.committee)
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


def _try_insert_co_source_record(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> UUID | None:
    return try_insert_source_record(conn, _build_co_source_record(data_source_id, row))


def _load_co_transaction_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    entities: _COTransactionEntities,
    roles: _COTransactionRoles,
) -> bool:
    source_record_id = _try_insert_co_source_record(conn, row, data_source_id)
    if source_record_id is None:
        return False

    _load_co_transaction_entities(
        conn,
        source_record_id=source_record_id,
        entities=entities,
        roles=roles,
    )
    return True


def load_co_contribution(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> bool:
    extracted = extract_co_contribution(dict(row))
    return _load_co_transaction_row(
        conn,
        row,
        data_source_id,
        entities=_COTransactionEntities(
            person=extracted["person"],
            organization=extracted["contributor_org"],
            committee=extracted["committee"],
            address=extracted["address"],
        ),
        roles=_CO_CONTRIBUTION_ENTITY_ROLES,
    )


def load_co_expenditure(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> bool:
    extracted = extract_co_expenditure(dict(row))
    return _load_co_transaction_row(
        conn,
        row,
        data_source_id,
        entities=_COTransactionEntities(
            person=extracted["payee_person"],
            organization=extracted["payee_org"],
            committee=extracted["committee"],
            address=extracted["address"],
        ),
        roles=_CO_EXPENDITURE_ENTITY_ROLES,
    )


def _try_load_co_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    row_load_config: _CORowLoadConfig,
    manages_outer_transaction: bool,
) -> bool | None:
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return row_load_config.load_row(conn, row, row_load_config.data_source_id)
    except Exception:  # noqa: BLE001
        LOGGER.exception(
            "Failed loading CO %s row RecordID=%s",
            row_load_config.row_type_label,
            row.get("RecordID"),
        )
        return None


def _maybe_commit_and_log_progress(
    conn: psycopg.Connection,
    *,
    row_type_label: str,
    counts: _COLoadCounts,
    manages_outer_transaction: bool,
) -> None:
    processed_count = counts.inserted + counts.skipped + counts.errors
    if processed_count % 1_000 == 0:
        commit_managed_transaction(conn, manages_outer_transaction)

    if processed_count % 10_000 == 0:
        LOGGER.info(
            "CO %s load progress processed=%s inserted=%s skipped=%s errors=%s superseded=%s",
            row_type_label,
            processed_count,
            counts.inserted,
            counts.skipped,
            counts.errors,
            counts.superseded,
        )


def _load_co_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    row_load_config: _CORowLoadConfig,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _COLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for index, row in enumerate(rows, start=1):
        if limit is not None and index > limit:
            break

        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")
        if is_superseded(row):
            counts.superseded += 1

        inserted_row = _try_load_co_row(
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
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=counts.superseded,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def load_co_contributions(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    limit = validated_limit(limit)
    parser = parse_contributions(Path(file_path))
    return _load_co_rows(
        conn,
        parser,
        _CORowLoadConfig(
            load_row=load_co_contribution,
            row_type_label="contribution",
            data_source_id=data_source_id,
        ),
        limit=limit,
    )


def load_co_expenditures(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    limit = validated_limit(limit)
    parser = parse_expenditures(Path(file_path))
    return _load_co_rows(
        conn,
        parser,
        _CORowLoadConfig(
            load_row=load_co_expenditure,
            row_type_label="expenditure",
            data_source_id=data_source_id,
        ),
        limit=limit,
    )


def load_co_contributions_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_co_data_source(conn, data_type="contributions")
    load_result = load_co_contributions(
        conn,
        file_path,
        data_source_id=data_source_id,
        limit=validated_row_limit,
    )
    _load_co_relational_transactions(
        conn,
        parse_contributions(Path(file_path)),
        data_source_id=data_source_id,
        data_type="contributions",
        limit=validated_row_limit,
    )
    return load_result


def load_co_expenditures_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    data_source_id = ensure_co_data_source(conn, data_type="expenditures")
    load_result = load_co_expenditures(
        conn,
        file_path,
        data_source_id=data_source_id,
        limit=validated_row_limit,
    )
    _load_co_relational_transactions(
        conn,
        parse_expenditures(Path(file_path)),
        data_source_id=data_source_id,
        data_type="expenditures",
        limit=validated_row_limit,
    )
    return load_result
