from __future__ import annotations

import csv
import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

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
    ensure_authority_committee,
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
    _load_dataset_id_for_data_type,
)
from .ie_record_classes import (
    _WA_EXTRACT_FN,
    _WATransactionDispatch,
    _WATransactionRoles,
    _resolve_wa_ie_record_class,
    _transaction_amount_field,
    _transaction_date_from_row,
    _transaction_type_from_row,
    _wa_effective_dispatch,
    _wa_support_oppose,
)
from .load_support import (
    WAIdentityAmbiguityError,
    _parse_required_wa_amount,
    _required_wa_text,
)
from .parse import parse_contributions, parse_expenditures, parse_independent_expenditures, parse_loans
from .relational_utils import (
    WAFilingLookupEntry as _WAFilingLookupEntry,
    WALoadCounts as _WALoadCounts,
    WARelationalOperations,
    WARelationalPassSettings,
    WASourceRecordKeyLedger as _WASourceRecordKeyLedger,
    load_wa_relational_transactions as _run_wa_relational_transactions,
)

LOGGER = logging.getLogger(__name__)

_WA_DOMAIN = "campaign_finance"
_WA_JURISDICTION = "state/WA"
_WA_SOURCE_FORMAT = "csv"


@dataclass(frozen=True, slots=True)
class WAContributionsRefreshBaseline:
    active_source_records: int
    last_pull_at: datetime | None


@dataclass(frozen=True, slots=True)
class WAContributionPageChanges:
    source_rows: int
    changed_rows: int
    path: Path | None


def select_wa_contributions_refresh_baseline(conn: psycopg.Connection) -> WAContributionsRefreshBaseline:
    """Read the durable source count and freshness cursor from the WA source owner."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(sr.id), ds.last_pull_at
            FROM core.data_source AS ds
            LEFT JOIN core.source_record AS sr
              ON sr.data_source_id = ds.id
             AND sr.superseded_by IS NULL
             AND sr.source_record_key IS NOT NULL
            WHERE ds.domain = %s
              AND ds.jurisdiction = %s
              AND ds.name = %s
            GROUP BY ds.id, ds.last_pull_at
            """,
            (_WA_DOMAIN, _WA_JURISDICTION, _load_data_source_name_for_data_type("contributions")),
        )
        row = cursor.fetchone()
    if row is None:
        return WAContributionsRefreshBaseline(active_source_records=0, last_pull_at=None)
    return WAContributionsRefreshBaseline(active_source_records=int(row[0]), last_pull_at=row[1])


def count_active_wa_source_records(conn: psycopg.Connection, *, data_type: str) -> int:
    """Count exact active source identities for final source-completeness refusal."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(sr.id)
            FROM core.data_source AS ds
            LEFT JOIN core.source_record AS sr
              ON sr.data_source_id = ds.id
             AND sr.superseded_by IS NULL
             AND sr.source_record_key IS NOT NULL
            WHERE ds.domain = %s
              AND ds.jurisdiction = %s
              AND ds.name = %s
            """,
            (_WA_DOMAIN, _WA_JURISDICTION, _load_data_source_name_for_data_type(data_type)),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"WA {data_type} data source count query returned no row")
    return int(row[0])


def filter_wa_contribution_page_changes(
    conn: psycopg.Connection,
    source_path: Path,
    changed_path: Path,
) -> WAContributionPageChanges:
    """Materialize only new or changed rows, using active source lineage as the checkpoint.

    The full downloaded page remains the provenance input. Existing source-record keys
    and content hashes make committed pages restart-safe without a second progress
    ledger: after an interruption, replayed rows compare equal and bypass the expensive
    relational loader while later pages can continue.
    """
    hashes_by_key: dict[str, str] = {}
    source_rows = 0
    for row in parse_contributions(source_path):
        source_rows += 1
        hashes_by_key[_wa_source_record_key(row, data_type="contributions")] = _wa_record_hash(row)

    persisted_hashes: dict[str, str] = {}
    keys = list(hashes_by_key)
    if keys:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT sr.source_record_key, sr.record_hash
                FROM core.data_source AS ds
                JOIN core.source_record AS sr
                  ON sr.data_source_id = ds.id
                 AND sr.superseded_by IS NULL
                WHERE ds.domain = %s
                  AND ds.jurisdiction = %s
                  AND ds.name = %s
                  AND sr.source_record_key = ANY(%s)
                """,
                (
                    _WA_DOMAIN,
                    _WA_JURISDICTION,
                    _load_data_source_name_for_data_type("contributions"),
                    keys,
                ),
            )
            persisted_hashes = {str(key): str(record_hash) for key, record_hash in cursor.fetchall()}

    changed_keys = {key for key, record_hash in hashes_by_key.items() if persisted_hashes.get(key) != record_hash}
    if not changed_keys:
        return WAContributionPageChanges(source_rows=source_rows, changed_rows=0, path=None)

    parser = parse_contributions(source_path)
    with changed_path.open("x", encoding="utf-8", newline="") as changed_file:
        writer = csv.DictWriter(changed_file, fieldnames=parser.columns)
        writer.writeheader()
        changed_rows = 0
        for row in parser:
            if _wa_source_record_key(row, data_type="contributions") not in changed_keys:
                continue
            writer.writerow(row)
            changed_rows += 1
    return WAContributionPageChanges(source_rows=source_rows, changed_rows=changed_rows, path=changed_path)


# One commit per this many iterated rows: both WA row loops share the boundary.
_COMMIT_BATCH_ROWS = 1_000
_normalize_optional_text = normalize_optional_text


@dataclass(frozen=True, slots=True)
class _WATransactionEntities:
    person: Person | None
    organization: Organization | None
    committee: Organization
    address: Address | None


@dataclass(frozen=True, slots=True)
class _WALegacyIdentityPlan:
    source_record_id: UUID
    legacy_source_record_key: str
    stable_source_record_key: str
    raw_fields: dict[str, str | None]
    record_class: _WATransactionDispatch | None
    lands_transaction: bool
    transaction_id: UUID | None
    legacy_filing_id: UUID | None
    legacy_filing_fec_id: str | None


_WA_PARSER_FN = {
    "contributions": parse_contributions,
    "expenditures": parse_expenditures,
    "independent_expenditures": parse_independent_expenditures,
    "loans": parse_loans,
}
_WA_COUNTERPARTY_NAME_PATH = {
    "contributions": "donor.name",
    "expenditures": "payee.name",
    "independent_expenditures": "payee.name",
    "loans": "lender.name",
}
_WA_COUNTERPARTY_EMPLOYER_PATH = {"contributions": "donor.employer", "loans": "lender.employer"}


def ensure_wa_data_source(conn: psycopg.Connection, data_type: str = "contributions") -> UUID:
    normalized_data_type = data_type.strip().lower()
    data_source_name = _load_data_source_name_for_data_type(normalized_data_type)

    data_source = DataSource(
        domain=_WA_DOMAIN,
        jurisdiction=_WA_JURISDICTION,
        filing_authority_type="state",
        filing_authority_code="WA",
        name=data_source_name,
        source_url=_load_data_source_url_for_data_type(normalized_data_type),
        source_format=_WA_SOURCE_FORMAT,
    )
    return ensure_data_source(conn, data_source)


def _wa_source_record_key(row: Mapping[str, str | None], *, data_type: str) -> str:
    native_id_column = _load_column_for_semantic_path(data_type, "wa.record.id")
    native_id = _required_wa_text(row.get(native_id_column), native_id_column)
    dataset_id = _load_dataset_id_for_data_type(data_type)
    return f"WA-PDC:{dataset_id}:{native_id}"


def _wa_record_hash(row: Mapping[str, str | None]) -> str:
    return compute_record_hash(dict(row))


def _index_wa_legacy_source_candidates(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    data_type: str,
) -> dict[str, tuple[UUID, ...]]:
    """Index only active, non-namespaced rows that the legacy loader may own."""
    native_id_column = _load_column_for_semantic_path(data_type, "wa.record.id")
    dataset_id = _load_dataset_id_for_data_type(data_type)
    candidates: dict[str, list[UUID]] = {}
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, raw_fields ->> %s AS native_id
            FROM core.source_record
            WHERE data_source_id = %s
              AND superseded_by IS NULL
              AND source_record_key IS NOT NULL
              AND source_record_key NOT LIKE 'WA-PDC:%%'
            """,
            (native_id_column, data_source_id),
        )
        for source_record_id, raw_native_id in cursor.fetchall():
            native_id = _normalize_optional_text(raw_native_id)
            if native_id is None:
                continue
            stable_key = f"WA-PDC:{dataset_id}:{native_id}"
            candidates.setdefault(stable_key, []).append(source_record_id)
    return {key: tuple(source_ids) for key, source_ids in candidates.items()}


def _build_wa_source_record(
    data_source_id: UUID,
    row: Mapping[str, str | None],
    *,
    data_type: str,
) -> SourceRecord:
    raw_fields = dict(row)
    record_hash = _wa_record_hash(row)
    source_record_key = _wa_source_record_key(row, data_type=data_type)
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        source_url=_source_record_url(row, data_type=data_type),
        raw_fields=raw_fields,
        record_hash=record_hash,
        pull_date=utc_now(),
    )


def _source_record_url(row: Mapping[str, str | None], *, data_type: str) -> str:
    try:
        source_url_column = _load_column_for_semantic_path(data_type, "wa.source_url")
    except RuntimeError:
        return _load_data_source_url_for_data_type(data_type)

    source_url = _normalize_optional_text(row.get(source_url_column))
    if source_url is not None:
        return source_url
    return _load_data_source_url_for_data_type(data_type)


def _resolve_wa_committee_id(
    conn: psycopg.Connection,
    committee: Organization,
    *,
    data_source_id: UUID,
) -> UUID:
    committee_identifier = _normalize_optional_text(committee.identifiers.get("wa_committee_id"))
    if committee_identifier is not None:
        existing_org_id = find_organization_by_identifier(
            conn,
            "wa_committee_id",
            committee_identifier,
            data_source_id=data_source_id,
        )
        if existing_org_id is not None:
            return existing_org_id
    return resolve_organization_by_canonical_name(
        conn,
        committee,
        data_source_id=data_source_id,
    )


def _load_wa_transaction_entities(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_source_id: UUID,
    entities: _WATransactionEntities,
    roles: _WATransactionRoles,
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

    person_id = resolve_person_by_name_and_zip(
        conn,
        entities.person,
        entities.address,
        data_source_id=data_source_id,
    )
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=roles.person,
            address_id=address_id,
        )

    committee_id = _resolve_wa_committee_id(conn, entities.committee, data_source_id=data_source_id)
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_id,
        source_record_id=source_record_id,
        extraction_role=roles.committee,
        address_id=None,
    )

    organization_id = resolve_organization_by_canonical_name(
        conn,
        entities.organization,
        data_source_id=data_source_id,
    )
    if organization_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=organization_id,
            source_record_id=source_record_id,
            extraction_role=roles.organization,
            address_id=address_id,
        )


def _load_wa_transaction_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
    entities: _WATransactionEntities,
    roles: _WATransactionRoles,
    legacy_identity_index: dict[str, tuple[UUID, ...]] | None = None,
) -> bool:
    stable_key = _wa_source_record_key(row, data_type=data_type)
    if legacy_identity_index is None:
        legacy_identity_index = _index_wa_legacy_source_candidates(
            conn,
            data_source_id=data_source_id,
            data_type=data_type,
        )
    legacy_source_ids = legacy_identity_index.get(stable_key, ())
    if legacy_source_ids:
        _reconcile_wa_legacy_identities(
            conn,
            data_source_id=data_source_id,
            data_type=data_type,
            stable_source_record_key=stable_key,
            legacy_source_ids=legacy_source_ids,
        )
    source_record = _build_wa_source_record(data_source_id, row, data_type=data_type)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    _load_wa_transaction_entities(
        conn,
        source_record_id=source_record_id,
        data_source_id=data_source_id,
        entities=entities,
        roles=roles,
    )
    return True


def _extract_and_load_wa_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
    *,
    data_type: str,
    legacy_identity_index: dict[str, tuple[UUID, ...]] | None = None,
) -> bool:
    if data_type not in _WA_EXTRACT_FN:
        raise ValueError(f"Unsupported WA data_type: {data_type}")
    dispatch = _wa_effective_dispatch(data_type, _resolve_wa_ie_record_class(row, data_type))
    person_key, org_key = dispatch.entity_keys
    extracted = dispatch.extract_fn(dict(row))
    return _load_wa_transaction_row(
        conn,
        row,
        data_source_id,
        data_type=data_type,
        entities=_WATransactionEntities(
            person=extracted[person_key],
            organization=extracted[org_key],
            committee=extracted["committee"],
            address=extracted["address"],
        ),
        roles=dispatch.entity_roles,
        legacy_identity_index=legacy_identity_index,
    )


def load_wa_contribution(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_wa_row(conn, row, data_source_id, data_type="contributions")


def load_wa_expenditure(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_wa_row(conn, row, data_source_id, data_type="expenditures")


def load_wa_loan(conn: psycopg.Connection, row: Mapping[str, str | None], data_source_id: UUID) -> bool:
    return _extract_and_load_wa_row(conn, row, data_source_id, data_type="loans")


def _try_load_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    data_source_id: UUID,
    data_type: str,
    manages_outer_transaction: bool,
    legacy_identity_index: dict[str, tuple[UUID, ...]],
) -> bool | None:
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return _extract_and_load_wa_row(
                conn,
                row,
                data_source_id,
                data_type=data_type,
                legacy_identity_index=legacy_identity_index,
            )
    except WAIdentityAmbiguityError:
        raise
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed loading WA %s row", data_type.rstrip("s"))
        return None


def _load_wa_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
    key_ledger: _WASourceRecordKeyLedger | None = None,
    legacy_identity_index: dict[str, tuple[UUID, ...]] | None = None,
) -> LoadResult:
    """Load WA source records for ``data_type``, tallying per-row load outcomes.

    When ``key_ledger`` is supplied, every row's source-record key is recorded on it — as
    rejected when this pass errors on the row, as persisted when the row lands by insert or
    by dedupe skip. The two-pass ``_load_wa_with_filings`` uses that ledger to let the
    relational pass skip a row this pass errored on and nothing persisted — so a single
    malformed row (e.g. an unknown IE origin) is counted once, even if a stale source record
    for it survives from an earlier load.
    """
    started_at = time.monotonic()
    counts = _WALoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    if legacy_identity_index is None:
        legacy_identity_index = _index_wa_legacy_source_candidates(
            conn,
            data_source_id=data_source_id,
            data_type=data_type,
        )

    try:
        for index, row in enumerate(rows, start=1):
            if limit is not None and index > limit:
                break
            if not isinstance(row, Mapping):
                raise TypeError(f"Expected mapping row, got {type(row)!r}")

            row_hash = _wa_record_hash(row)
            inserted = _try_load_row(
                conn,
                row,
                data_source_id=data_source_id,
                data_type=data_type,
                manages_outer_transaction=manages_outer_transaction,
                legacy_identity_index=legacy_identity_index,
            )
            if inserted is None:
                counts.errors += 1
                if key_ledger is not None:
                    key_ledger.rejected_attempts[row_hash] += 1
            else:
                if inserted:
                    counts.inserted += 1
                else:
                    counts.skipped += 1
                if key_ledger is not None:
                    key_ledger.persisted.add(row_hash)

            processed_count = counts.inserted + counts.skipped + counts.errors
            if processed_count % _COMMIT_BATCH_ROWS == 0:
                commit_managed_transaction(conn, manages_outer_transaction)
    except WAIdentityAmbiguityError:
        if manages_outer_transaction:
            conn.rollback()
        raise

    commit_managed_transaction(conn, manages_outer_transaction)

    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _load_wa_file(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None = None,
    key_ledger: _WASourceRecordKeyLedger | None = None,
    legacy_identity_index: dict[str, tuple[UUID, ...]] | None = None,
) -> LoadResult:
    validated_row_limit = validated_limit(limit)
    parser = _WA_PARSER_FN[data_type](Path(file_path))
    return _load_wa_rows(
        conn,
        parser,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
        key_ledger=key_ledger,
        legacy_identity_index=legacy_identity_index,
    )


def load_wa_contributions(
    conn: psycopg.Connection, fp: str | Path, *, data_source_id: UUID, limit: int | None = None
) -> LoadResult:
    return _load_wa_file(conn, fp, data_source_id=data_source_id, data_type="contributions", limit=limit)


def load_wa_expenditures(
    conn: psycopg.Connection, fp: str | Path, *, data_source_id: UUID, limit: int | None = None
) -> LoadResult:
    return _load_wa_file(conn, fp, data_source_id=data_source_id, data_type="expenditures", limit=limit)


def load_wa_loans(
    conn: psycopg.Connection, fp: str | Path, *, data_source_id: UUID, limit: int | None = None
) -> LoadResult:
    return _load_wa_file(conn, fp, data_source_id=data_source_id, data_type="loans", limit=limit)


def _select_wa_source_record_id(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    record_hash: str,
) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND record_hash = %s
              AND superseded_by IS NULL
            LIMIT 1
            """,
            (data_source_id, source_record_key, record_hash),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _build_wa_filing_fec_id(
    row: Mapping[str, str | None],
    data_type: str,
) -> str:
    report_number_column = _load_column_for_semantic_path(data_type, "wa.report_number")
    report_number = _required_wa_text(row.get(report_number_column), report_number_column)
    return f"WA-PDC:{report_number}"


def _build_wa_legacy_filing_fec_id(
    row: Mapping[str, str | None],
    data_type: str,
    *,
    record_class: _WATransactionDispatch | None,
) -> str:
    committee_id_column = _load_column_for_semantic_path(data_type, "committee.id")
    year_column = _load_column_for_semantic_path(data_type, "transaction.year")
    committee_identifier = _required_wa_text(row.get(committee_id_column), committee_id_column)
    filing_year = _normalize_optional_text(row.get(year_column))
    if filing_year is None:
        transaction_date = _transaction_date_from_row(row, data_type, record_class=record_class)
        if transaction_date is None:
            raise ValueError("WA row is missing both transaction year and transaction date")
        filing_year = str(transaction_date.year)
    return f"WA-{committee_identifier}-{filing_year}-{data_type}"


def _resolve_wa_filing_committee_id(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_type: str,
    *,
    data_source_id: UUID,
    source_record_id: UUID,
    record_class: _WATransactionDispatch | None,
) -> UUID:
    extracted = _wa_effective_dispatch(data_type, record_class).extract_fn(dict(row))
    committee_organization_id = _resolve_wa_committee_id(
        conn,
        extracted["committee"],
        data_source_id=data_source_id,
    )
    committee_id_column = _load_column_for_semantic_path(data_type, "committee.id")
    native_committee_id = _required_wa_text(row.get(committee_id_column), committee_id_column)
    return ensure_authority_committee(
        conn,
        data_source_id=data_source_id,
        authority_type="state",
        authority_code="WA",
        native_committee_id=native_committee_id,
        organization_id=committee_organization_id,
        source_record_id=source_record_id,
    )


def _build_wa_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
    data_source_id: UUID,
    data_type: str,
    record_class: _WATransactionDispatch | None,
) -> Filing:
    """Build the report-number-owned WA filing without inventing a filing date."""
    return Filing(
        filing_fec_id=_build_wa_filing_fec_id(row, data_type),
        data_source_id=data_source_id,
        native_filing_id=_required_wa_text(
            row.get(_load_column_for_semantic_path(data_type, "wa.report_number")),
            _load_column_for_semantic_path(data_type, "wa.report_number"),
        ),
        committee_id=committee_id,
        report_type=None,
        amendment_indicator="N",
        filing_name=_normalize_optional_text(row.get(_load_column_for_semantic_path(data_type, "committee.name"))),
        receipt_date=None,
        accepted_date=None,
        source_record_id=source_record_id,
    )


def _upsert_wa_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    source_record_id: UUID,
    data_source_id: UUID,
    data_type: str,
    filing_lookup: dict[str, _WAFilingLookupEntry],
    record_class: _WATransactionDispatch | None,
) -> _WAFilingLookupEntry:
    """Upsert a report-owned filing after serializing and validating ownership."""
    filing_fec_id = _build_wa_filing_fec_id(row, data_type)
    existing_entry = filing_lookup.get(filing_fec_id)
    report_number_column = _load_column_for_semantic_path(data_type, "wa.report_number")
    report_number = _required_wa_text(row.get(report_number_column), report_number_column)
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            (f"WA PDC filing:{data_source_id}", filing_fec_id),
        )
        committee_id = _resolve_wa_filing_committee_id(
            conn,
            row,
            data_type,
            data_source_id=data_source_id,
            source_record_id=source_record_id,
            record_class=record_class,
        )
        if existing_entry is not None and existing_entry.committee_id != committee_id:
            raise WAIdentityAmbiguityError(f"WA filing {filing_fec_id!r} maps to multiple committees")
        cursor.execute(
            """
            SELECT filing.committee_id,
                   filing.source_record_id,
                   source_record.source_record_key,
                   source_record.raw_fields ->> %s AS source_report_number,
                   data_source.domain AS source_domain,
                   data_source.jurisdiction AS source_jurisdiction,
                   data_source.name AS source_name
            FROM cf.filing AS filing
            LEFT JOIN core.source_record AS source_record
              ON source_record.id = filing.source_record_id
            LEFT JOIN core.data_source AS data_source
              ON data_source.id = source_record.data_source_id
            WHERE filing.data_source_id = %s
              AND filing.native_filing_id = %s
            FOR UPDATE OF filing
            """,
            (report_number_column, data_source_id, report_number),
        )
        persisted_filing = cursor.fetchone()
    if persisted_filing is not None:
        (
            persisted_committee_id,
            persisted_source_record_id,
            persisted_source_record_key,
            persisted_report_number,
            persisted_source_domain,
            persisted_source_jurisdiction,
            persisted_source_name,
        ) = persisted_filing
        if persisted_committee_id != committee_id:
            raise WAIdentityAmbiguityError(f"WA filing {filing_fec_id!r} conflicts with its persisted committee")
        if _normalize_optional_text(persisted_report_number) != report_number:
            raise WAIdentityAmbiguityError(f"WA filing {filing_fec_id!r} conflicts with its persisted source report")
        if (
            persisted_source_domain != _WA_DOMAIN
            or persisted_source_jurisdiction != _WA_JURISDICTION
            or not str(persisted_source_name).startswith("WA PDC ")
        ):
            raise WAIdentityAmbiguityError(f"WA filing {filing_fec_id!r} has a foreign persisted source owner")
    else:
        persisted_source_record_id = None
        persisted_source_record_key = None
    current_source_record_key = _wa_source_record_key(row, data_type=data_type)
    if existing_entry is not None:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT source_record_key FROM core.source_record WHERE id = %s",
                (existing_entry.source_record_id,),
            )
            cached_source = cursor.fetchone()
        if cached_source is not None and cached_source[0] == current_source_record_key:
            filing_source_record_id = source_record_id
        else:
            filing_source_record_id = existing_entry.source_record_id
    elif persisted_source_record_key == current_source_record_key:
        filing_source_record_id = source_record_id
    else:
        filing_source_record_id = persisted_source_record_id or source_record_id

    filing = _build_wa_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
        data_source_id=data_source_id,
        data_type=data_type,
        record_class=record_class,
    )
    filing_id = upsert_filing(conn, filing)
    if existing_entry is not None and existing_entry.filing_id != filing_id:
        raise ValueError(
            f"WA filing lookup drift for filing_fec_id={filing_fec_id!r}: {existing_entry.filing_id} != {filing_id}"
        )

    entry = _WAFilingLookupEntry(
        filing_id=filing_id,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_lookup[filing_fec_id] = entry
    return entry


def _counterparty_name_raw(row: Mapping[str, str | None], data_type: str) -> str | None:
    semantic_path = _WA_COUNTERPARTY_NAME_PATH.get(data_type)
    if semantic_path is None:
        raise ValueError(f"Unsupported WA data_type: {data_type}")
    return _normalize_optional_text(row.get(_load_column_for_semantic_path(data_type, semantic_path)))


def _counterparty_employer(row: Mapping[str, str | None], data_type: str) -> str | None:
    semantic_path = _WA_COUNTERPARTY_EMPLOYER_PATH.get(data_type)
    if semantic_path is None:
        return None
    return _normalize_optional_text(row.get(_load_column_for_semantic_path(data_type, semantic_path)))


def _resolve_wa_transaction_address_id(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_type: str,
    record_class: _WATransactionDispatch | None,
) -> UUID | None:
    address_role = _wa_effective_dispatch(data_type, record_class).entity_roles.address
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


def _upsert_wa_transaction_with_filing(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    *,
    filing_id: UUID,
    committee_id: UUID,
    source_record_id: UUID,
    data_source_id: UUID,
    data_type: str,
    record_class: _WATransactionDispatch | None,
) -> None:
    """Upsert a WA transaction through its record-class-aware dispatch.

    The dispatch extractor is the router's authoritative output and cannot diverge from
    the resolved record class. Recomputing this pure, cheap extraction keeps the filing
    and transaction paths independent; caching its payload is intentionally unnecessary.
    """
    dispatch = _wa_effective_dispatch(data_type, record_class)
    person_roles, organization_roles = dispatch.counterparty_roles
    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=person_roles,
        organization_roles=organization_roles,
    )
    contributor_address_id = _resolve_wa_transaction_address_id(
        conn,
        source_record_id=source_record_id,
        data_type=data_type,
        record_class=record_class,
    )

    counterparty_addr = dispatch.extract_fn(dict(row))["address"]
    contributor_state = counterparty_addr.state if counterparty_addr is not None else None
    contributor_city = counterparty_addr.city if counterparty_addr is not None else None
    contributor_zip = counterparty_addr.zip5 if counterparty_addr is not None else None

    amount_field = _transaction_amount_field(data_type, record_class=record_class)
    transaction_identifier = _wa_source_record_key(row, data_type=data_type)
    transaction = Transaction(
        filing_id=filing_id,
        committee_id=committee_id,
        data_source_id=data_source_id,
        native_transaction_id=transaction_identifier,
        transaction_type=_transaction_type_from_row(row, data_type, record_class=record_class),
        transaction_identifier=transaction_identifier,
        transaction_date=_transaction_date_from_row(row, data_type, record_class=record_class),
        amount=_parse_required_wa_amount(row.get(amount_field), amount_field),
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
        support_oppose=_wa_support_oppose(row, data_type, record_class=record_class),
    )
    old_filing_id, reconciled_existing = _reconcile_wa_transaction_identity(
        conn,
        data_source_id=data_source_id,
        source_record_key=transaction_identifier,
        transaction=transaction,
    )
    if not reconciled_existing:
        upsert_transaction(conn, transaction)
    if old_filing_id is not None and old_filing_id != filing_id:
        _delete_empty_wa_superseded_filing(
            conn,
            filing_id=old_filing_id,
            expected_legacy_filing_fec_id=_build_wa_legacy_filing_fec_id(
                row,
                data_type,
                record_class=record_class,
            ),
            expected_data_source_id=data_source_id,
            data_type=data_type,
        )


def _reconcile_wa_transaction_identity(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    transaction: Transaction,
) -> tuple[UUID | None, bool]:
    """Rehome one existing transaction UUID through its native source lineage."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            (f"WA PDC transaction:{data_source_id}", source_record_key),
        )
        cursor.execute(
            """
            SELECT transaction.id, transaction.filing_id
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            WHERE source_record.data_source_id = %s
              AND source_record.source_record_key = %s
            FOR UPDATE OF transaction
            """,
            (data_source_id, source_record_key),
        )
        lineage_transactions = cursor.fetchall()
        if len(lineage_transactions) > 1:
            raise WAIdentityAmbiguityError(f"WA source identity {source_record_key!r} maps to multiple transactions")

        cursor.execute(
            """
            SELECT id
            FROM cf.transaction
            WHERE filing_id = %s
              AND transaction_identifier = %s
            FOR UPDATE
            """,
            (transaction.filing_id, transaction.transaction_identifier),
        )
        target_row = cursor.fetchone()
        if not lineage_transactions:
            if target_row is not None:
                raise WAIdentityAmbiguityError(
                    f"WA transaction identity {source_record_key!r} has no matching source lineage"
                )
            return None, False

        transaction_id, old_filing_id = lineage_transactions[0]
        if target_row is not None and target_row[0] != transaction_id:
            raise WAIdentityAmbiguityError(
                f"WA transaction identity {source_record_key!r} conflicts at its target filing"
            )
        cursor.execute(
            """
            UPDATE cf.transaction
            SET filing_id = %s,
                committee_id = %s,
                data_source_id = %s,
                native_transaction_id = %s,
                transaction_type = %s,
                transaction_identifier = %s,
                transaction_date = %s,
                amount = %s,
                contributor_name_raw = %s,
                contributor_employer = %s,
                contributor_city = %s,
                contributor_state = %s,
                contributor_zip = %s,
                contributor_person_id = %s,
                contributor_organization_id = %s,
                contributor_address_id = %s,
                recipient_committee_id = %s,
                source_record_id = %s,
                support_oppose = %s
            WHERE id = %s
            """,
            (
                transaction.filing_id,
                transaction.committee_id,
                transaction.data_source_id,
                transaction.native_transaction_id,
                transaction.transaction_type,
                transaction.transaction_identifier,
                transaction.transaction_date,
                transaction.amount,
                transaction.contributor_name_raw,
                transaction.contributor_employer,
                transaction.contributor_city,
                transaction.contributor_state,
                transaction.contributor_zip,
                transaction.contributor_person_id,
                transaction.contributor_organization_id,
                transaction.contributor_address_id,
                transaction.recipient_committee_id,
                transaction.source_record_id,
                transaction.support_oppose,
                transaction_id,
            ),
        )
        return old_filing_id, True


def _delete_empty_wa_owned_filing(
    conn: psycopg.Connection,
    *,
    filing_id: UUID,
    expected_filing_fec_id: str,
    expected_data_source_id: UUID,
    expected_report_type: str | None,
    data_type: str,
    expected_source_report_number: str | None = None,
) -> None:
    """Delete only an empty, unextended filing proven to be loader-owned legacy state."""
    report_number_column = _load_column_for_semantic_path(data_type, "wa.report_number")
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id,
                   candidate_id,
                   election_id,
                   coverage_start_date,
                   coverage_end_date,
                   due_date,
                   report_type,
                   amendment_indicator,
                   amended_from_filing_id,
                   source_record.data_source_id,
                   source_record.raw_fields ->> %s AS source_report_number,
                   EXISTS (
                       SELECT 1 FROM cf.transaction AS transaction
                       WHERE transaction.filing_id = filing.id
                   ) AS has_transactions,
                   EXISTS (
                       SELECT 1 FROM cf.filing AS child
                       WHERE child.amended_from_filing_id = filing.id
                   ) AS has_amendment_children
            FROM cf.filing AS filing
            LEFT JOIN core.source_record AS source_record
              ON source_record.id = filing.source_record_id
            WHERE filing.id = %s
            FOR UPDATE OF filing
            """,
            (report_number_column, filing_id),
        )
        filing = cursor.fetchone()
        if filing is None or filing["filing_fec_id"] != expected_filing_fec_id:
            return
        if filing["has_transactions"]:
            return
        if filing["report_type"] != expected_report_type or filing["data_source_id"] != expected_data_source_id:
            raise WAIdentityAmbiguityError(f"WA legacy filing {expected_filing_fec_id!r} has unfamiliar ownership")
        if expected_source_report_number is not None and (
            _normalize_optional_text(filing["source_report_number"]) != expected_source_report_number
        ):
            raise WAIdentityAmbiguityError(
                f"WA filing {expected_filing_fec_id!r} conflicts with source report ownership"
            )
        protected_values = (
            filing["candidate_id"],
            filing["election_id"],
            filing["coverage_start_date"],
            filing["coverage_end_date"],
            filing["due_date"],
            filing["amended_from_filing_id"],
        )
        if any(value is not None for value in protected_values) or filing["amendment_indicator"] != "N":
            raise WAIdentityAmbiguityError(
                f"WA legacy filing {expected_filing_fec_id!r} carries non-loader-owned state"
            )
        if filing["has_amendment_children"]:
            raise WAIdentityAmbiguityError(f"WA legacy filing {expected_filing_fec_id!r} has amendment children")
        cursor.execute(
            "DELETE FROM cf.filing WHERE id = %s",
            (filing_id,),
        )


def _delete_empty_wa_superseded_filing(
    conn: psycopg.Connection,
    *,
    filing_id: UUID,
    expected_legacy_filing_fec_id: str,
    expected_data_source_id: UUID,
    data_type: str,
) -> None:
    """Delete a vacated report or legacy filing only after proving its owner shape."""
    report_number_column = _load_column_for_semantic_path(data_type, "wa.report_number")
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id,
                   report_type,
                   source_record.raw_fields ->> %s AS source_report_number
            FROM cf.filing AS filing
            LEFT JOIN core.source_record AS source_record
              ON source_record.id = filing.source_record_id
            WHERE filing.id = %s
            FOR UPDATE OF filing
            """,
            (report_number_column, filing_id),
        )
        filing = cursor.fetchone()
    if filing is None:
        return

    source_report_number = _normalize_optional_text(filing["source_report_number"])
    if filing["report_type"] is None:
        if source_report_number is None:
            raise WAIdentityAmbiguityError("WA report filing has no source report owner")
        expected_filing_fec_id = f"WA-PDC:{source_report_number}"
        if filing["filing_fec_id"] != expected_filing_fec_id:
            raise WAIdentityAmbiguityError("WA report filing conflicts with its source report owner")
        _advance_wa_filing_source_after_claim_removal(
            conn,
            filing_id=filing_id,
            data_type=data_type,
            expected_report_number=source_report_number,
        )
        _delete_empty_wa_owned_filing(
            conn,
            filing_id=filing_id,
            expected_filing_fec_id=expected_filing_fec_id,
            expected_data_source_id=expected_data_source_id,
            expected_report_type=None,
            data_type=data_type,
            expected_source_report_number=source_report_number,
        )
        return

    if filing["filing_fec_id"] != expected_legacy_filing_fec_id:
        raise WAIdentityAmbiguityError("WA vacated filing has an unfamiliar identity shape")
    _delete_empty_wa_owned_filing(
        conn,
        filing_id=filing_id,
        expected_filing_fec_id=expected_legacy_filing_fec_id,
        expected_data_source_id=expected_data_source_id,
        expected_report_type=data_type,
        data_type=data_type,
    )


def _remove_wa_source_only_claim(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    source_record_key: str,
    data_type: str,
) -> None:
    """Remove one derived claim when the active native row is source-only."""
    report_number_column = _load_column_for_semantic_path(data_type, "wa.report_number")
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            (f"WA PDC transaction:{data_source_id}", source_record_key),
        )
        cursor.execute(
            """
            SELECT transaction.id,
                   transaction.filing_id,
                   transaction.committee_id,
                   transaction.transaction_identifier,
                   transaction.back_ref_transaction_id,
                   transaction.sub_id,
                   transaction.contributor_entity_type,
                   transaction.contributor_occupation,
                   transaction.recipient_candidate_id,
                   transaction.memo_code,
                   transaction.memo_text,
                   transaction.is_memo,
                   transaction.amendment_indicator,
                   transaction.amended_by_transaction_id,
                   transaction.date_is_reliable,
                   transaction.dissemination_date,
                   transaction.aggregate_amount,
                   EXISTS (
                       SELECT 1 FROM cf.transaction AS referring_transaction
                       WHERE referring_transaction.amended_by_transaction_id = transaction.id
                   ) AS has_amendment_references,
                   filing.filing_fec_id,
                   filing.committee_id AS filing_committee_id,
                   source_record.raw_fields ->> %s AS source_report_number
            FROM cf.transaction AS transaction
            JOIN core.source_record AS source_record
              ON source_record.id = transaction.source_record_id
            JOIN cf.filing AS filing
              ON filing.id = transaction.filing_id
            WHERE source_record.data_source_id = %s
              AND source_record.source_record_key = %s
            FOR UPDATE OF transaction, filing
            """,
            (report_number_column, data_source_id, source_record_key),
        )
        lineage_transactions = cursor.fetchall()
        if len(lineage_transactions) > 1:
            raise WAIdentityAmbiguityError(
                f"WA source-only identity {source_record_key!r} maps to multiple transactions"
            )
        if not lineage_transactions:
            return
        transaction = lineage_transactions[0]
        if transaction["transaction_identifier"] != source_record_key:
            raise WAIdentityAmbiguityError(
                f"WA source-only identity {source_record_key!r} conflicts with its transaction"
            )
        if transaction["committee_id"] != transaction["filing_committee_id"]:
            raise WAIdentityAmbiguityError(
                f"WA source-only identity {source_record_key!r} conflicts with committee ownership"
            )
        _assert_wa_legacy_transaction_is_removable(transaction)
        source_report_number = _normalize_optional_text(transaction["source_report_number"])
        if source_report_number is None:
            raise WAIdentityAmbiguityError(f"WA source-only identity {source_record_key!r} has no prior report owner")
        expected_filing_fec_id = f"WA-PDC:{source_report_number}"
        if transaction["filing_fec_id"] != expected_filing_fec_id:
            raise WAIdentityAmbiguityError(
                f"WA source-only identity {source_record_key!r} conflicts with filing ownership"
            )
        cursor.execute("DELETE FROM cf.transaction WHERE id = %s", (transaction["id"],))

    _advance_wa_filing_source_after_claim_removal(
        conn,
        filing_id=transaction["filing_id"],
        data_type=data_type,
        expected_report_number=source_report_number,
    )
    _delete_empty_wa_owned_filing(
        conn,
        filing_id=transaction["filing_id"],
        expected_filing_fec_id=expected_filing_fec_id,
        expected_data_source_id=data_source_id,
        expected_report_type=None,
        data_type=data_type,
        expected_source_report_number=source_report_number,
    )


def _advance_wa_filing_source_after_claim_removal(
    conn: psycopg.Connection,
    *,
    filing_id: UUID,
    data_type: str,
    expected_report_number: str,
) -> None:
    """Keep a nonempty report filing on active provenance after one claim is removed."""
    report_number_column = _load_column_for_semantic_path(data_type, "wa.report_number")
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (active_source.id)
                   active_source.id AS source_record_id,
                   active_source.raw_fields ->> %s AS report_number,
                   transaction_source.superseded_by AS transaction_source_superseded_by
            FROM cf.transaction AS transaction
            JOIN core.source_record AS transaction_source
              ON transaction_source.id = transaction.source_record_id
            JOIN core.source_record AS active_source
              ON active_source.data_source_id = transaction_source.data_source_id
             AND active_source.source_record_key = transaction_source.source_record_key
             AND active_source.superseded_by IS NULL
            JOIN core.data_source AS data_source
              ON data_source.id = active_source.data_source_id
            WHERE transaction.filing_id = %s
              AND data_source.jurisdiction = %s
            ORDER BY active_source.id, active_source.created_at
            """,
            (report_number_column, filing_id, _WA_JURISDICTION),
        )
        active_sources = cursor.fetchall()
        if not active_sources:
            return
        conflicting_active_sources = [
            source
            for source in active_sources
            if source["transaction_source_superseded_by"] is None
            and _normalize_optional_text(source["report_number"]) != expected_report_number
        ]
        if conflicting_active_sources:
            raise WAIdentityAmbiguityError("WA report filing has surviving claims from another report")
        eligible_sources = [
            source
            for source in active_sources
            if _normalize_optional_text(source["report_number"]) == expected_report_number
        ]
        if not eligible_sources:
            return
        chosen_source_id = min(source["source_record_id"] for source in eligible_sources)
        cursor.execute(
            "UPDATE cf.filing SET source_record_id = %s WHERE id = %s",
            (chosen_source_id, filing_id),
        )


def _assert_wa_legacy_transaction_is_removable(transaction: Mapping[str, object]) -> None:
    """Fail closed before removing a legacy claim carrying later enrichment/lifecycle state."""
    protected_fields = (
        "back_ref_transaction_id",
        "sub_id",
        "contributor_entity_type",
        "contributor_occupation",
        "recipient_candidate_id",
        "memo_code",
        "memo_text",
        "amended_by_transaction_id",
        "dissemination_date",
        "aggregate_amount",
    )
    if any(transaction[field] is not None for field in protected_fields):
        raise WAIdentityAmbiguityError("WA legacy transaction carries non-loader-owned state")
    if transaction["is_memo"] or transaction["amendment_indicator"] != "N":
        raise WAIdentityAmbiguityError("WA legacy transaction carries lifecycle state")
    if not transaction["date_is_reliable"] or transaction["has_amendment_references"]:
        raise WAIdentityAmbiguityError("WA legacy transaction participates in unknown lifecycle state")


def _reconcile_wa_legacy_identities(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    data_type: str,
    stable_source_record_key: str,
    legacy_source_ids: tuple[UUID, ...],
) -> None:
    """Atomically migrate the exact legacy WA identity shape for one input row.

    The old loader used each row hash as both source and transaction identity and grouped
    filings by committee/year/data type. Only active rows with that exact hash-key shape
    are eligible. Any duplicate native identity, unfamiliar key, conflicting reference,
    or protected enrichment aborts the savepoint before a source key changes.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            (str(data_source_id), stable_source_record_key),
        )
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND id = ANY(%s)
              AND superseded_by IS NULL
            FOR UPDATE
            """,
            (data_source_id, list(legacy_source_ids)),
        )
        active_sources = cursor.fetchall()

        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            FOR UPDATE
            """,
            (data_source_id, stable_source_record_key),
        )
        existing_stable_source = cursor.fetchone()
        active_source_ids = {source["id"] for source in active_sources}
        if existing_stable_source is not None and (
            not active_sources or (len(active_sources) == 1 and existing_stable_source["id"] in active_source_ids)
        ):
            return
        if existing_stable_source is not None:
            raise WAIdentityAmbiguityError(
                f"WA source identity {stable_source_record_key!r} has legacy and namespaced owners"
            )

        legacy_source_ids = {
            source["id"] for source in active_sources if source["source_record_key"] == source["record_hash"]
        }
        transactions_by_source: dict[UUID, list[dict[str, object]]] = {}
        source_filings_by_source: dict[UUID, list[dict[str, object]]] = {}
        if legacy_source_ids:
            cursor.execute(
                """
                SELECT transaction.source_record_id,
                       transaction.id,
                       transaction.filing_id,
                       transaction.committee_id,
                       transaction.transaction_identifier,
                       transaction.back_ref_transaction_id,
                       transaction.sub_id,
                       transaction.contributor_entity_type,
                       transaction.contributor_occupation,
                       transaction.recipient_candidate_id,
                       transaction.memo_code,
                       transaction.memo_text,
                       transaction.is_memo,
                       transaction.amendment_indicator,
                       transaction.amended_by_transaction_id,
                       transaction.date_is_reliable,
                       transaction.dissemination_date,
                       transaction.aggregate_amount,
                       EXISTS (
                           SELECT 1 FROM cf.transaction AS referring_transaction
                           WHERE referring_transaction.amended_by_transaction_id = transaction.id
                       ) AS has_amendment_references,
                       filing.filing_fec_id,
                       filing.committee_id AS filing_committee_id
                FROM cf.transaction AS transaction
                JOIN cf.filing AS filing
                  ON filing.id = transaction.filing_id
                WHERE transaction.source_record_id = ANY(%s)
                FOR UPDATE OF transaction, filing
                """,
                (list(legacy_source_ids),),
            )
            for transaction in cursor.fetchall():
                transactions_by_source.setdefault(transaction["source_record_id"], []).append(transaction)

            cursor.execute(
                """
                SELECT filing.source_record_id,
                       filing.id AS filing_id,
                       filing.filing_fec_id,
                       filing.committee_id AS filing_committee_id
                FROM cf.filing AS filing
                WHERE filing.source_record_id = ANY(%s)
                FOR UPDATE OF filing
                """,
                (list(legacy_source_ids),),
            )
            for filing in cursor.fetchall():
                source_filings_by_source.setdefault(filing["source_record_id"], []).append(filing)

    sources_by_stable_key: dict[str, list[dict[str, object]]] = {}
    plans: list[_WALegacyIdentityPlan] = []
    for source in active_sources:
        raw_fields = dict(source["raw_fields"])
        if _wa_record_hash(raw_fields) != source["record_hash"]:
            raise WAIdentityAmbiguityError(f"WA existing source {source['id']} has inconsistent hash provenance")
        try:
            stable_key = _wa_source_record_key(raw_fields, data_type=data_type)
        except ValueError as error:
            raise WAIdentityAmbiguityError(
                f"WA existing source {source['id']} has no usable native identity"
            ) from error
        sources_by_stable_key.setdefault(stable_key, []).append(source)

    ambiguous_keys = [key for key, sources in sources_by_stable_key.items() if len(sources) > 1]
    if ambiguous_keys:
        raise WAIdentityAmbiguityError(
            f"WA native source identities have multiple active rows: {sorted(ambiguous_keys)!r}"
        )

    for stable_key, sources in sources_by_stable_key.items():
        if stable_key != stable_source_record_key:
            raise WAIdentityAmbiguityError(
                f"WA legacy candidate does not match input identity {stable_source_record_key!r}"
            )
        source = sources[0]
        current_key = source["source_record_key"]
        record_hash = source["record_hash"]
        if current_key == stable_key:
            continue
        if not record_hash or current_key != record_hash:
            raise WAIdentityAmbiguityError(f"WA existing source {source['id']} has an unfamiliar identity shape")

        raw_fields = dict(source["raw_fields"])
        try:
            record_class = _resolve_wa_ie_record_class(raw_fields, data_type)
        except ValueError as error:
            raise WAIdentityAmbiguityError(f"WA legacy source {source['id']} has an unknown record class") from error
        try:
            _build_wa_filing_fec_id(raw_fields, data_type)
            has_report_number = True
        except ValueError:
            has_report_number = False
        lands_transaction = has_report_number and (record_class is None or record_class.lands_transaction)

        source_transactions = transactions_by_source.get(source["id"], [])
        if len(source_transactions) > 1:
            raise WAIdentityAmbiguityError(f"WA legacy source {source['id']} maps to multiple transactions")
        transaction = source_transactions[0] if source_transactions else None

        referenced_filings: dict[UUID, dict[str, object]] = {}
        if transaction is not None:
            referenced_filings[transaction["filing_id"]] = transaction
        for filing in source_filings_by_source.get(source["id"], []):
            referenced_filings[filing["filing_id"]] = filing
        if len(referenced_filings) > 1:
            raise WAIdentityAmbiguityError(f"WA legacy source {source['id']} maps to multiple filings")
        filing = next(iter(referenced_filings.values()), None)

        expected_legacy_filing_fec_id = None
        if filing is not None:
            try:
                expected_legacy_filing_fec_id = _build_wa_legacy_filing_fec_id(
                    raw_fields,
                    data_type,
                    record_class=record_class,
                )
            except ValueError as error:
                raise WAIdentityAmbiguityError(
                    f"WA legacy source {source['id']} cannot prove its old filing identity"
                ) from error
        if filing is not None and filing["filing_fec_id"] != expected_legacy_filing_fec_id:
            raise WAIdentityAmbiguityError(f"WA legacy source {source['id']} conflicts with its filing identity")
        if transaction is not None:
            if transaction["transaction_identifier"] != current_key:
                raise WAIdentityAmbiguityError(
                    f"WA legacy source {source['id']} conflicts with its transaction identity"
                )
            if transaction["committee_id"] != transaction["filing_committee_id"]:
                raise WAIdentityAmbiguityError(
                    f"WA legacy source {source['id']} conflicts with transaction committee ownership"
                )
            if not lands_transaction:
                _assert_wa_legacy_transaction_is_removable(transaction)

        plans.append(
            _WALegacyIdentityPlan(
                source_record_id=source["id"],
                legacy_source_record_key=current_key,
                stable_source_record_key=stable_key,
                raw_fields=raw_fields,
                record_class=record_class,
                lands_transaction=lands_transaction,
                transaction_id=None if transaction is None else transaction["id"],
                legacy_filing_id=None if filing is None else filing["filing_id"],
                legacy_filing_fec_id=expected_legacy_filing_fec_id,
            )
        )

    if not plans:
        return

    with conn.cursor() as cursor:
        for plan in plans:
            cursor.execute(
                "UPDATE core.source_record SET source_record_key = %s WHERE id = %s",
                (plan.stable_source_record_key, plan.source_record_id),
            )

    filing_lookup: dict[str, _WAFilingLookupEntry] = {}
    for plan in plans:
        if not plan.lands_transaction:
            if plan.transaction_id is not None:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM cf.transaction WHERE id = %s", (plan.transaction_id,))
            if plan.legacy_filing_id is not None and plan.legacy_filing_fec_id is not None:
                _delete_empty_wa_owned_filing(
                    conn,
                    filing_id=plan.legacy_filing_id,
                    expected_filing_fec_id=plan.legacy_filing_fec_id,
                    expected_data_source_id=data_source_id,
                    expected_report_type=data_type,
                    data_type=data_type,
                )
            continue
        if plan.transaction_id is None:
            if plan.legacy_filing_id is not None and plan.legacy_filing_fec_id is not None:
                _delete_empty_wa_owned_filing(
                    conn,
                    filing_id=plan.legacy_filing_id,
                    expected_filing_fec_id=plan.legacy_filing_fec_id,
                    expected_data_source_id=data_source_id,
                    expected_report_type=data_type,
                    data_type=data_type,
                )
            continue

        filing_entry = _upsert_wa_filing(
            conn,
            plan.raw_fields,
            source_record_id=plan.source_record_id,
            data_source_id=data_source_id,
            data_type=data_type,
            filing_lookup=filing_lookup,
            record_class=plan.record_class,
        )
        _upsert_wa_transaction_with_filing(
            conn,
            plan.raw_fields,
            filing_id=filing_entry.filing_id,
            committee_id=filing_entry.committee_id,
            source_record_id=plan.source_record_id,
            data_source_id=data_source_id,
            data_type=data_type,
            record_class=plan.record_class,
        )


def _evict_rolled_back_filing(
    filing_lookup: dict[str, _WAFilingLookupEntry],
    row: Mapping[str, str | None],
    data_type: str,
    record_class: _WATransactionDispatch | None,
) -> None:
    """Drop a rolled-back filing's cache entry so a later good row re-upserts it.

    The failing row may not have a computable filing_fec_id (e.g. an unknown origin that
    raised before any filing was built), in which case there is nothing cached to evict.
    """
    try:
        filing_fec_id = _build_wa_filing_fec_id(row, data_type)
    except Exception:  # noqa: BLE001
        return
    filing_lookup.pop(filing_fec_id, None)


def _load_wa_relational_transactions(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    *,
    data_source_id: UUID,
    data_type: str,
    limit: int | None,
    key_ledger: _WASourceRecordKeyLedger | None = None,
) -> _WALoadCounts:
    """Delegate WA's relational pass while keeping its row operations patchable here.

    :func:`~.relational_utils.load_wa_relational_transactions` owns the loop, the commit
    boundary, and what the returned counts mean.
    """
    return _run_wa_relational_transactions(
        conn,
        rows,
        settings=WARelationalPassSettings(
            data_source_id=data_source_id,
            data_type=data_type,
            limit=limit,
            commit_batch_rows=_COMMIT_BATCH_ROWS,
            key_ledger=key_ledger,
            operations=WARelationalOperations(
                source_record_key=lambda row: _wa_source_record_key(row, data_type=data_type),
                record_hash=_wa_record_hash,
                filing_identity=lambda row: _build_wa_filing_fec_id(row, data_type),
                select_source_record_id=_select_wa_source_record_id,
                remove_source_only_claim=_remove_wa_source_only_claim,
                upsert_filing=_upsert_wa_filing,
                upsert_transaction=_upsert_wa_transaction_with_filing,
                evict_rolled_back_filing=_evict_rolled_back_filing,
            ),
        ),
    )


def _load_wa_with_filings(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_type: str,
    limit: int | None = None,
) -> LoadResult:
    """Run the source-record pass then the relational pass, folding both into one result.

    The relational pass's ``errors`` and ``skipped`` counts are folded into the
    ``LoadResult`` the source-record pass produced;
    :func:`~.relational_utils.load_wa_relational_transactions` owns what those two counts
    mean. Conflating both skip causes into one field is
    intentional — it keeps the decision's "a skip is never an error" invariant without
    adding a cross-loader field to the shared ``LoadResult``.
    """
    validated_row_limit = validated_limit(limit)
    # Sample ownership before ensure_wa_data_source runs SQL and implicitly opens a
    # transaction, then commit the data-source row so the connection is IDLE again. Both
    # passes below sample ownership on entry, so a lookup left open here would make them
    # believe an outer caller owns the transaction and silently skip every periodic
    # commit — leaving the boundary in place but dead.
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    data_source_id = ensure_wa_data_source(conn, data_type=data_type)
    try:
        legacy_identity_index = _index_wa_legacy_source_candidates(
            conn,
            data_source_id=data_source_id,
            data_type=data_type,
        )
    except Exception:
        if manages_outer_transaction:
            conn.rollback()
        raise
    commit_managed_transaction(conn, manages_outer_transaction)
    key_ledger = _WASourceRecordKeyLedger()
    load_result = _load_wa_file(
        conn,
        file_path,
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
        key_ledger=key_ledger,
        legacy_identity_index=legacy_identity_index,
    )
    # A key the source-record pass both rejected and persisted lost nothing: attempts may
    # have failed non-deterministically, but a byte-identical duplicate row confirmed the
    # content persisted, so those attempt errors are spurious and every copy links below.
    # The attempts move to ``skipped`` rather than disappearing: their content was already
    # persisted by the copy that landed, which is what a dedupe skip means, and rebucketing
    # keeps inserted + skipped + errors equal to the rows the source-record pass read.
    spurious_attempt_errors = key_ledger.rejected_attempts_for_persisted_keys()
    load_result.errors -= spurious_attempt_errors
    load_result.skipped += spurious_attempt_errors
    relational_counts = _load_wa_relational_transactions(
        conn,
        _WA_PARSER_FN[data_type](Path(file_path)),
        data_source_id=data_source_id,
        data_type=data_type,
        limit=validated_row_limit,
        key_ledger=key_ledger,
    )
    load_result.errors += relational_counts.errors
    load_result.skipped += relational_counts.skipped
    return load_result


def load_wa_contributions_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_wa_with_filings(conn, fp, data_type="contributions", limit=limit)


def load_wa_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_wa_with_filings(conn, fp, data_type="expenditures", limit=limit)


def load_wa_independent_expenditures_with_filings(
    conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None
) -> LoadResult:
    return _load_wa_with_filings(conn, fp, data_type="independent_expenditures", limit=limit)


def load_wa_loans_with_filings(conn: psycopg.Connection, fp: str | Path, *, limit: int | None = None) -> LoadResult:
    return _load_wa_with_filings(conn, fp, data_type="loans", limit=limit)
