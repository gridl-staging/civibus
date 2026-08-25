from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from core.db import (
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
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_data_source,
    ensure_transaction_open,
    iter_rows_with_limit,
    link_entity_source_and_optional_mailing_address,
    validated_limit,
)

from . import _load_data_source_for_data_type
from .load_helpers import (
    _INDataTypeSpec,
    _in_amendment_indicator,
    _in_data_type_spec,
    _in_extract_row,
    _in_source_record_key,
    _resolve_in_committee_organization_id,
)
from .relational_load import (
    INCallerTransactionRolledBack,
    INFilingLookupDrift,
    _load_in_relational_transactions,
)

LOGGER = logging.getLogger(__name__)

_IN_DOMAIN = "campaign_finance"
_IN_JURISDICTION = "state/IN"
_IN_SOURCE_FORMAT = "csv"
_COMMIT_BATCH_ROWS = 1_000


@dataclass(slots=True)
class _INLoadCounts:
    inserted: int = 0
    skipped: int = 0
    superseded: int = 0
    errors: int = 0


def ensure_in_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_config = _load_data_source_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_IN_DOMAIN,
        jurisdiction=_IN_JURISDICTION,
        name=data_source_config.name,
        source_url=data_source_config.url,
        source_format=_IN_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _build_in_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> SourceRecord:
    raw_fields: dict[str, object] = dict(row)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=_in_source_record_key(row, data_type=data_type),
        source_url=_load_data_source_for_data_type(data_type).url,
        raw_fields=raw_fields,
        record_hash=compute_record_hash(raw_fields),
        pull_date=utc_now(),
    )


def _load_in_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    extracted: Mapping[str, Any],
    spec: _INDataTypeSpec,
) -> None:
    address = extracted["address"]
    address_id = None
    if address is not None:
        address_id = upsert_address(conn, address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=spec.address_role,
            address_id=None,
        )

    person_id = resolve_person_by_name_and_zip(conn, extracted[spec.person_key], address)
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=spec.person_role,
            address_id=address_id,
        )

    committee_org_id = _resolve_in_committee_organization_id(conn, extracted["committee"])
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_org_id,
        source_record_id=source_record_id,
        extraction_role=spec.committee_role,
        address_id=None,
    )

    organization_id = resolve_organization_by_canonical_name(conn, extracted[spec.organization_key])
    if organization_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=organization_id,
            source_record_id=source_record_id,
            extraction_role=spec.organization_role,
            address_id=address_id,
        )


def _extract_and_load_in_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
) -> bool:
    source_record = _build_in_source_record(data_source_id, row, data_type=data_type)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = _in_extract_row(row, data_type)
    spec = _in_data_type_spec(data_type)
    _load_in_transaction_entities(
        conn,
        source_record_id=source_record_id,
        extracted=extracted,
        spec=spec,
    )

    return True


def load_in_contribution(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_in_row(conn, row, data_source_id, data_type="contributions")


def load_in_expenditure(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_in_row(conn, row, data_source_id, data_type="expenditures")


def _try_load_in_row(
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

        # Row-level savepoint for per-row error isolation.
        with conn.transaction():
            return _extract_and_load_in_row(conn, row, data_source_id, data_type=data_type)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading IN %s row", data_type.rstrip("s"))
        return None


def _load_in_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _INLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")

        try:
            amendment_indicator = _in_amendment_indicator(row, data_type=data_type)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed loading IN %s row: invalid amendment indicator", data_type.rstrip("s"))
            counts.errors += 1
            processed_count = counts.inserted + counts.skipped + counts.errors
            if processed_count % _COMMIT_BATCH_ROWS == 0:
                commit_managed_transaction(conn, manages_outer_transaction)
            continue

        if amendment_indicator == "T":
            counts.superseded += 1

        inserted = _try_load_in_row(
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
        if processed_count % _COMMIT_BATCH_ROWS == 0:
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


def _load_in_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _in_data_type_spec(data_type).parse_rows(Path(file_path))
    return _load_in_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
    )


def load_in_contributions(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    return _load_in_file(conn, fp, data_source_id=data_source_id, data_type="contributions", limit=limit)


def load_in_expenditures(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    return _load_in_file(conn, fp, data_source_id=data_source_id, data_type="expenditures", limit=limit)


def _load_in_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    # Capture ownership before ensure_in_data_source runs SQL and implicitly opens a
    # transaction; committing the data-source row here leaves the connection IDLE so each
    # inner pass owns and periodically commits its own batch.
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    data_source_id = ensure_in_data_source(conn, data_type=data_type)
    commit_managed_transaction(conn, manages_outer_transaction)

    try:
        load_result = _load_in_file(
            conn,
            file_path,
            data_source_id=data_source_id,
            data_type=data_type,
            limit=validated_row_limit,
        )
        load_result.errors += _load_in_relational_transactions(
            conn,
            _in_data_type_spec(data_type).parse_rows(Path(file_path)),
            data_source_id=data_source_id,
            data_type=data_type,
            limit=validated_row_limit,
        )
    except Exception:
        if manages_outer_transaction:
            conn.rollback()
        raise

    commit_managed_transaction(conn, manages_outer_transaction)

    return load_result


def load_in_contributions_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_in_with_filings(conn, fp, data_type="contributions", limit=limit)


def load_in_expenditures_with_filings(
    conn: psycopg.Connection,
    fp: str | Path,
    *,
    limit: int | None = None,
) -> LoadResult:
    return _load_in_with_filings(conn, fp, data_type="expenditures", limit=limit)


__all__ = [
    "INCallerTransactionRolledBack",
    "INFilingLookupDrift",
    "LoadResult",
    "ensure_in_data_source",
    "load_in_contribution",
    "load_in_expenditure",
    "load_in_contributions",
    "load_in_expenditures",
    "load_in_contributions_with_filings",
    "load_in_expenditures_with_filings",
]
