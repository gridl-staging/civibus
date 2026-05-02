
from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
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
from core.types.python.models import Organization, compute_record_hash, utc_now
from domains.campaign_finance.ingest.filing_loader import (
    ensure_state_committee,
    generate_synthetic_committee_id,
    resolve_transaction_counterparty_ids,
    upsert_filing,
    upsert_transaction,
)
from domains.campaign_finance.ingest.text_utils import normalize_optional_text
from domains.campaign_finance.jurisdictions.states.load_utils import (
    commit_managed_transaction,
    ensure_transaction_open,
    iter_rows_with_limit,
    link_entity_source_and_optional_mailing_address,
)
from domains.campaign_finance.types.models import Filing, Transaction

from . import load_support
from .committee_registry import NCCommitteeRegistryRow
from .extract import extract_nc_transaction
from .load_support import (
    build_nc_source_record as _build_nc_source_record,
    ensure_nc_committee_document_data_source,
    ensure_nc_data_source,
    select_nc_source_record_id as _select_nc_source_record_id,
)
from .load_types import (
    LoadResult,
    NCTransactionsLoadResult,
    NCFilingLookupEntry,
    _NCLoadCounts,
    _NCRowLoadConfig,
    _NCRowLoader,
    _NCTransactionEntities,
)
from .parse import (
    parse_amendment_flag,
    parse_committee_docs,
    parse_nc_amount,
    parse_nc_date,
    parse_transactions,
)

LOGGER = logging.getLogger(__name__)
build_data_source = load_support.build_data_source
ensure_nc_ie_document_index_data_source = load_support.ensure_nc_ie_document_index_data_source
_NC_ROW_LOADER_TYPE = _NCRowLoader

_NC_TRANSACTION_ENTITY_ROLES = {
    "person": "donor",
    "organization": "contributor",
    "committee": "recipient",
    "address": "contributor_address",
}
_NCFilingLookupKey = tuple[str, str]
_normalize_optional_text = normalize_optional_text
_NC_COMMITTEE_REGISTRY_ROW_LABEL = "committee_registry"
_NC_COMMITTEE_REGISTRY_UPSERT_SQL = """
INSERT INTO cf.nc_committee_registry (
    org_group_id,
    sboe_id,
    committee_name,
    status_desc,
    old_id,
    candidate_name,
    data_source_id,
    first_seen_at,
    last_seen_at
)
VALUES (
    %(org_group_id)s,
    %(sboe_id)s,
    %(committee_name)s,
    %(status_desc)s,
    %(old_id)s,
    %(candidate_name)s,
    %(data_source_id)s,
    %(seen_at)s,
    %(seen_at)s
)
ON CONFLICT (org_group_id) DO UPDATE
SET sboe_id = EXCLUDED.sboe_id,
    committee_name = EXCLUDED.committee_name,
    status_desc = EXCLUDED.status_desc,
    old_id = EXCLUDED.old_id,
    candidate_name = EXCLUDED.candidate_name,
    data_source_id = EXCLUDED.data_source_id,
    first_seen_at = LEAST(cf.nc_committee_registry.first_seen_at, EXCLUDED.first_seen_at),
    last_seen_at = GREATEST(cf.nc_committee_registry.last_seen_at, EXCLUDED.last_seen_at)
"""


def _iter_nc_rows(
    rows: Iterable[Mapping[str, str | None]],
    *,
    limit: int | None,
) -> Iterable[Mapping[str, str | None]]:
    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected mapping row, got {type(row)!r}")
        yield row


def _iter_nc_committee_registry_rows(
    rows: Iterable[NCCommitteeRegistryRow],
    *,
    limit: int | None,
) -> Iterable[NCCommitteeRegistryRow]:
    for row in iter_rows_with_limit(rows, limit):
        if not isinstance(row, NCCommitteeRegistryRow):
            raise TypeError(f"Expected NCCommitteeRegistryRow, got {type(row)!r}")
        yield row


def _resolve_seen_at(seen_at: datetime | None) -> datetime:
    resolved_seen_at = utc_now() if seen_at is None else seen_at
    if resolved_seen_at.tzinfo is None:
        raise ValueError("seen_at must be timezone-aware")
    return resolved_seen_at.astimezone(timezone.utc)


def _build_nc_committee_registry_upsert_params(
    row: NCCommitteeRegistryRow,
    *,
    data_source_id: UUID,
    seen_at: datetime,
) -> Mapping[str, object]:
    return {
        "org_group_id": row.org_group_id,
        "sboe_id": row.sboe_id,
        "committee_name": row.committee_name,
        "status_desc": row.status_desc,
        "old_id": row.old_id,
        "candidate_name": row.candidate_name,
        "data_source_id": data_source_id,
        "seen_at": seen_at,
    }


def _upsert_nc_committee_registry_row(
    conn: psycopg.Connection,
    row: NCCommitteeRegistryRow,
    *,
    data_source_id: UUID,
    seen_at: datetime,
) -> tuple[bool, bool, bool, str | None]:
    existing_candidate_name: str | None = None
    existing_sboe_id: str | None = None
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT candidate_name, sboe_id
            FROM cf.nc_committee_registry
            WHERE org_group_id = %s
            LIMIT 1
            """,
            (row.org_group_id,),
        )
        existing_row = cursor.fetchone()
        row_exists = existing_row is not None
        if row_exists:
            existing_candidate_name = existing_row[0]
            existing_sboe_id = existing_row[1]
        cursor.execute(
            _NC_COMMITTEE_REGISTRY_UPSERT_SQL,
            _build_nc_committee_registry_upsert_params(
                row,
                data_source_id=data_source_id,
                seen_at=seen_at,
            ),
        )
    candidate_name_changed = (
        _normalize_candidate_name_for_bridge(existing_candidate_name)
        != _normalize_candidate_name_for_bridge(row.candidate_name)
    )
    sboe_id_changed = normalize_optional_text(existing_sboe_id) != normalize_optional_text(row.sboe_id)
    return (
        not row_exists,
        row_exists and candidate_name_changed,
        row_exists and sboe_id_changed,
        existing_sboe_id,
    )


def _select_nc_committee_id_by_native_sboe_id(
    conn: psycopg.Connection,
    *,
    committee_sboe_id: str,
) -> UUID | None:
    """Return existing NC committee id for a native SBoE id; do not create rows."""
    synthetic_fec_committee_id = generate_synthetic_committee_id("NC", committee_sboe_id)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM cf.committee
            WHERE state = 'NC'
              AND fec_committee_id = %s
            LIMIT 1
            """,
            (synthetic_fec_committee_id,),
        )
        match = cursor.fetchone()
    if match is None:
        return None
    return match[0]


def _build_load_result(
    counts: _NCLoadCounts,
    *,
    rows: object,
    started_at: float,
) -> LoadResult:
    return LoadResult(
        inserted=counts.inserted,
        skipped=counts.skipped,
        quarantined=int(getattr(rows, "skipped", 0)),
        superseded=0,
        errors=counts.errors,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _build_transaction_row_load_config(data_source_id: UUID) -> _NCRowLoadConfig:
    return _NCRowLoadConfig(
        load_row=load_nc_transaction,
        row_type_label="transaction",
        data_source_id=data_source_id,
    )


def _resolve_nc_committee_id(conn: psycopg.Connection, committee: Organization) -> UUID:
    committee_id = committee.identifiers.get("nc_sboe_id")
    if committee_id:
        existing_org_id = find_organization_by_identifier(conn, "nc_sboe_id", committee_id)
        if existing_org_id is not None:
            return existing_org_id

    return insert_organization(conn, committee)


def _load_nc_transaction_entities(
    conn: psycopg.Connection,
    source_record_id: UUID,
    entities: _NCTransactionEntities,
) -> None:
    address_id = None
    if entities.address is not None:
        address_id = upsert_address(conn, entities.address)
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="address",
            entity_id=address_id,
            source_record_id=source_record_id,
            extraction_role=_NC_TRANSACTION_ENTITY_ROLES["address"],
            address_id=None,
        )

    person_id = resolve_person_by_name_and_zip(conn, entities.person, entities.address)
    if person_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role=_NC_TRANSACTION_ENTITY_ROLES["person"],
            address_id=address_id,
        )

    committee_id = _resolve_nc_committee_id(conn, entities.committee)
    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=committee_id,
        source_record_id=source_record_id,
        extraction_role=_NC_TRANSACTION_ENTITY_ROLES["committee"],
        address_id=None,
    )

    contributor_org_id = resolve_organization_by_canonical_name(conn, entities.contributor_org)
    if contributor_org_id is not None:
        link_entity_source_and_optional_mailing_address(
            conn,
            entity_type="organization",
            entity_id=contributor_org_id,
            source_record_id=source_record_id,
            extraction_role=_NC_TRANSACTION_ENTITY_ROLES["organization"],
            address_id=address_id,
        )


def load_nc_transaction(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> bool:
    source_record = _build_nc_source_record(data_source_id, row)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is None:
        return False

    extracted = extract_nc_transaction(dict(row))
    _load_nc_transaction_entities(
        conn,
        source_record_id=source_record_id,
        entities=_NCTransactionEntities(
            person=extracted["person"],
            contributor_org=extracted["contributor_org"],
            committee=extracted["committee"],
            address=extracted["address"],
        ),
    )

    return True


def _require_text(value: str | None, field_name: str) -> str:
    normalized_value = _normalize_optional_text(value)
    if normalized_value is None:
        raise ValueError(f"NC row is missing required {field_name}")
    return normalized_value


def _parse_optional_date(raw_value: str | None) -> date | None:
    parsed = parse_nc_date(raw_value)
    if parsed is None:
        return None
    return date.fromisoformat(parsed)


def _require_amount(raw_value: str | None) -> Decimal:
    parsed = parse_nc_amount(raw_value)
    if parsed is None:
        raise ValueError("NC row is missing required Amount")
    return parsed


def _to_amendment_indicator(raw_amendment: str | None) -> str:
    is_amendment = parse_amendment_flag(raw_amendment)
    if is_amendment:
        return "A"
    return "N"


def normalize_nc_report_key(year: str | None, doc_name: str | None) -> str:
    normalized_year = _require_text(year, "Year")
    normalized_doc_name = _require_text(doc_name, "Doc Name")
    return f"{normalized_year} {normalized_doc_name}"


def _normalize_nc_transaction_report_key(report_name: str | None) -> str:
    normalized_report_name = _require_text(report_name, "Report Name")
    report_parts = normalized_report_name.split(" ", maxsplit=1)
    if len(report_parts) != 2:
        raise ValueError(f"NC Report Name is not in '<year> <doc name>' format: {normalized_report_name!r}")
    return normalize_nc_report_key(report_parts[0], report_parts[1])


def _normalize_nc_sboe_id(raw_sboe_id: str | None) -> str:
    return _require_text(raw_sboe_id, "SBoE ID")


def _doc_name_slug(raw_doc_name: str | None) -> str:
    normalized_doc_name = _require_text(raw_doc_name, "Doc Name")
    return normalized_doc_name.lower().replace(" ", "-")


def _build_nc_filing_fec_id(row: Mapping[str, str | None]) -> str:
    sboe_id = _normalize_nc_sboe_id(row.get("SBoE ID"))
    year = _require_text(row.get("Year"), "Year")
    doc_name_slug = _doc_name_slug(row.get("Doc Name"))
    return f"NC-{sboe_id}-{year}-{doc_name_slug}"


def _build_nc_committee_bridge_org(
    *,
    committee_sboe_id: str,
    committee_name: str,
) -> Organization:
    normalized_committee_name = _require_text(committee_name, "Committee Name")
    return Organization(
        canonical_name=f"{normalized_committee_name} {committee_sboe_id}",
        identifiers={"nc_sboe_id": committee_sboe_id},
    )


def _resolve_nc_committee_bridge(
    conn: psycopg.Connection,
    committee_sboe_id: str,
    *,
    committee_name: str | None = None,
) -> UUID:
    organization_id = find_organization_by_identifier(conn, "nc_sboe_id", committee_sboe_id)
    if organization_id is None:
        if committee_name is None:
            raise ValueError(
                f"No core.organization bridge exists for NC committee identifier nc_sboe_id={committee_sboe_id!r}"
            )
        organization_id = insert_organization(
            conn,
            _build_nc_committee_bridge_org(
                committee_sboe_id=committee_sboe_id,
                committee_name=committee_name,
            ),
        )
    return ensure_state_committee(
        conn,
        state="NC",
        native_committee_id=committee_sboe_id,
        organization_id=organization_id,
    )


# Whitespace inside candidate names varies between SBoE registry exports and
# civic.candidacy ingest sources (e.g. "ALEX  EXAMPLE" vs "ALEX EXAMPLE"). The
# bridge match must be exact only after trimming and collapsing internal
# whitespace runs to a single space — explicitly no fuzzy/alias logic.
_NC_INTERNAL_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_candidate_name_for_bridge(value: str | None) -> str | None:
    """Trim and collapse internal whitespace; return None for blank-equivalent input."""
    trimmed = normalize_optional_text(value)
    if trimmed is None:
        return None
    return _NC_INTERNAL_WHITESPACE_RE.sub(" ", trimmed)


def _select_unique_nc_candidacy_id_for_normalized_bridge_name(
    conn: psycopg.Connection,
    *,
    normalized_candidate_name: str,
) -> UUID | None:
    """Return one NC candidacy id for a normalized bridge name, else None."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.id
            FROM civic.candidacy c
            JOIN civic.contest co ON co.id = c.contest_id
            JOIN civic.office o ON o.id = co.office_id
            WHERE o.state = 'NC'
              AND c.name_on_ballot IS NOT NULL
              AND TRIM(REGEXP_REPLACE(c.name_on_ballot, '\\s+', ' ', 'g')) = %s
            """,
            (normalized_candidate_name,),
        )
        matches = cursor.fetchall()
    if len(matches) != 1:
        return None
    return matches[0][0]


def _match_and_update_nc_candidacy_committee(
    conn: psycopg.Connection,
    *,
    candidate_name: str | None,
    committee_id: UUID,
) -> int:
    """Bridge an NC committee to its unique NC candidacy by name_on_ballot.

    Updates ``civic.candidacy.committee_id`` for the single NC candidacy whose
    normalized ``name_on_ballot`` equals the normalized ``candidate_name``.
    Skips zero-match and multi-match rows. Re-runs remain idempotent: if the
    resolved row is already linked and already stamped as Stage 1-owned, this
    no-ops. Returns the number of candidacy rows updated.
    """
    normalized_name = _normalize_candidate_name_for_bridge(candidate_name)
    if normalized_name is None:
        return 0
    candidacy_id = _select_unique_nc_candidacy_id_for_normalized_bridge_name(
        conn,
        normalized_candidate_name=normalized_name,
    )
    if candidacy_id is None:
        return 0
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE civic.candidacy
            SET committee_id = %s,
                raw_fields = COALESCE(raw_fields, '{}'::jsonb) || '{"nc_stage1_bridge_owned": true}'::jsonb,
                updated_at = NOW()
            WHERE id = %s
              AND (
                    committee_id IS DISTINCT FROM %s
                    OR NOT (
                        COALESCE(raw_fields, '{}'::jsonb)
                        @> '{"nc_stage1_bridge_owned": true}'::jsonb
                    )
              )
            """,
            (committee_id, candidacy_id, committee_id),
        )
        return cursor.rowcount


def _clear_stale_nc_candidacy_committee_links(
    conn: psycopg.Connection,
    *,
    committee_id: UUID,
    keep_candidacy_id: UUID | None,
) -> int:
    """Clear committee links for the resolved NC committee except an optional keep row."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE civic.candidacy
            SET committee_id = NULL,
                updated_at = NOW()
            WHERE committee_id = %s
              AND (%s::uuid IS NULL OR id IS DISTINCT FROM %s::uuid)
            """,
            (committee_id, keep_candidacy_id, keep_candidacy_id),
        )
        return cursor.rowcount


def _select_unique_nc_candidacy_id_for_bridge_name(
    conn: psycopg.Connection,
    *,
    candidate_name: str | None,
) -> UUID | None:
    """Return the single NC candidacy id matching candidate_name, else None."""
    normalized_name = _normalize_candidate_name_for_bridge(candidate_name)
    if normalized_name is None:
        return None
    return _select_unique_nc_candidacy_id_for_normalized_bridge_name(
        conn,
        normalized_candidate_name=normalized_name,
    )


def _bridge_nc_registry_row_to_candidacy(
    conn: psycopg.Connection,
    row: NCCommitteeRegistryRow,
    *,
    clear_stale_links: bool,
) -> int:
    """Resolve the registry row's committee through the existing NC bridge owner
    and run the candidacy match-and-update pass. Rows without a usable
    candidate_name are a no-op. Returns rows updated."""
    normalized_candidate_name = _normalize_candidate_name_for_bridge(row.candidate_name)
    if normalized_candidate_name is None and not clear_stale_links:
        return 0

    committee_id = _resolve_nc_committee_bridge(
        conn,
        row.sboe_id,
        committee_name=row.committee_name,
    )
    keep_candidacy_id = (
        _select_unique_nc_candidacy_id_for_normalized_bridge_name(
            conn,
            normalized_candidate_name=normalized_candidate_name,
        )
        if normalized_candidate_name is not None
        else None
    )
    cleared_rows = 0
    if clear_stale_links:
        cleared_rows = _clear_stale_nc_candidacy_committee_links(
            conn,
            committee_id=committee_id,
            keep_candidacy_id=keep_candidacy_id,
        )
    matched_rows = 0
    if normalized_candidate_name is not None:
        matched_rows = _match_and_update_nc_candidacy_committee(
            conn,
            candidate_name=normalized_candidate_name,
            committee_id=committee_id,
        )
    return cleared_rows + matched_rows


def build_nc_filing(
    row: Mapping[str, str | None],
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> Filing:
    return Filing(
        filing_fec_id=_build_nc_filing_fec_id(row),
        committee_id=committee_id,
        report_type=_normalize_optional_text(row.get("Doc Type")),
        amendment_indicator=_to_amendment_indicator(row.get("Amend")),
        filing_name=_normalize_optional_text(row.get("Doc Name")),
        coverage_start_date=_parse_optional_date(row.get("Start Date")),
        coverage_end_date=_parse_optional_date(row.get("End Date")),
        receipt_date=_parse_optional_date(row.get("Received Data")),
        accepted_date=_parse_optional_date(row.get("Received Image")),
        source_record_id=source_record_id,
    )


def _resolve_committee_doc_source_record(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, str | None],
    data_source_id: UUID,
) -> tuple[UUID, bool]:
    source_record = _build_nc_source_record(data_source_id, row)
    source_record_id = try_insert_source_record(conn, source_record)
    if source_record_id is not None:
        return source_record_id, True

    existing_source_record_id = _select_nc_source_record_id(
        conn,
        data_source_id=data_source_id,
        source_record_key=source_record.source_record_key,
    )
    if existing_source_record_id is None:
        raise RuntimeError(
            "Committee-document source_record insert reported conflict but existing source_record row was not found"
        )
    return existing_source_record_id, False


# Shared helper API for NC loader modules. Keep these names public so other
# modules do not need to import underscore-prefixed implementation details.
build_load_result = _build_load_result
iter_nc_rows = _iter_nc_rows
parse_optional_date = _parse_optional_date
require_text = _require_text
resolve_committee_doc_source_record = _resolve_committee_doc_source_record
resolve_nc_committee_bridge = _resolve_nc_committee_bridge
to_amendment_indicator = _to_amendment_indicator


def _select_nc_filing_lookup_entry(
    conn: psycopg.Connection,
    *,
    filing_id: UUID,
    expected_filing_fec_id: str,
) -> NCFilingLookupEntry:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id, committee_id, amendment_indicator, source_record_id
            FROM cf.filing
            WHERE id = %s
            LIMIT 1
            """,
            (filing_id,),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(f"NC filing upsert returned filing_id={filing_id} but no cf.filing row was found")

    filing_fec_id, committee_id, amendment_indicator, source_record_id = row
    if filing_fec_id != expected_filing_fec_id:
        raise RuntimeError(
            "NC filing lookup entry drifted from expected filing_fec_id "
            f"{expected_filing_fec_id!r}: got {filing_fec_id!r}"
        )

    return NCFilingLookupEntry(
        filing_id=filing_id,
        filing_fec_id=filing_fec_id,
        committee_id=committee_id,
        amendment_indicator=amendment_indicator,
        source_record_id=source_record_id,
    )


def _upsert_committee_document_filing(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, str | None],
    committee_document_data_source_id: UUID,
    filing_lookup: dict[_NCFilingLookupKey, NCFilingLookupEntry],
) -> bool:
    source_record_id, inserted_source_record = _resolve_committee_doc_source_record(
        conn,
        row=row,
        data_source_id=committee_document_data_source_id,
    )

    # Skip rows with blank Doc Name (e.g. Statement of Organization) — they
    # are administrative records that cannot participate in the filing join.
    # Keep their source_record so committee-document provenance stays intact.
    raw_doc_name = _normalize_optional_text(row.get("Doc Name"))
    if raw_doc_name is None:
        return inserted_source_record
    # Only Disclosure Report rows with a live DATA export can participate in
    # filing lookup joins. Other committee-document rows retain provenance but
    # should not create cf.filing records used by transaction joins.
    if _normalize_optional_text(row.get("Doc Type")) != "Disclosure Report":
        return inserted_source_record
    if _normalize_optional_text(row.get("Data")) is None:
        return inserted_source_record
    committee_sboe_id = _normalize_nc_sboe_id(row.get("SBoE ID"))
    report_key = normalize_nc_report_key(row.get("Year"), row.get("Doc Name"))
    lookup_key = (committee_sboe_id, report_key)

    committee_id = _resolve_nc_committee_bridge(
        conn,
        committee_sboe_id,
        committee_name=row.get("Committee Name"),
    )
    existing_entry = filing_lookup.get(lookup_key)
    filing_source_record_id = source_record_id if existing_entry is None else existing_entry.source_record_id
    filing = build_nc_filing(
        row,
        committee_id=committee_id,
        source_record_id=filing_source_record_id,
    )
    filing_id = upsert_filing(conn, filing)
    entry = _select_nc_filing_lookup_entry(
        conn,
        filing_id=filing_id,
        expected_filing_fec_id=filing.filing_fec_id,
    )
    if existing_entry is not None and existing_entry.filing_fec_id != entry.filing_fec_id:
        raise ValueError(
            "Ambiguous NC committee-document filing lookup key "
            f"{lookup_key!r}: {existing_entry.filing_fec_id!r} != {entry.filing_fec_id!r}"
        )
    filing_lookup[lookup_key] = entry
    return inserted_source_record


def build_nc_filing_lookup(
    conn: psycopg.Connection,
    committee_document_rows: Iterable[Mapping[str, str | None]],
    *,
    committee_document_data_source_id: UUID,
    limit: int | None = None,
) -> tuple[LoadResult, dict[_NCFilingLookupKey, NCFilingLookupEntry]]:
    started_at = time.monotonic()
    counts = _NCLoadCounts()
    filing_lookup: dict[_NCFilingLookupKey, NCFilingLookupEntry] = {}
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in _iter_nc_rows(committee_document_rows, limit=limit):
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            inserted = _upsert_committee_document_filing(
                conn,
                row=row,
                committee_document_data_source_id=committee_document_data_source_id,
                filing_lookup=filing_lookup,
            )
        if inserted:
            counts.inserted += 1
        else:
            counts.skipped += 1

        _maybe_commit_and_log_progress(
            conn,
            row_type_label="committee_document",
            counts=counts,
            manages_outer_transaction=manages_outer_transaction,
        )

    commit_managed_transaction(conn, manages_outer_transaction)

    return (
        _build_load_result(
            counts,
            rows=committee_document_rows,
            started_at=started_at,
        ),
        filing_lookup,
    )


def load_nc_committee_documents(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> tuple[LoadResult, dict[_NCFilingLookupKey, NCFilingLookupEntry]]:
    parser = parse_committee_docs(Path(file_path))
    return build_nc_filing_lookup(
        conn,
        parser,
        committee_document_data_source_id=data_source_id,
        limit=limit,
    )


def load_nc_ie_document_index(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    from .load_ie_document_index import load_nc_ie_document_index as _load_nc_ie_document_index

    return _load_nc_ie_document_index(
        conn,
        file_path,
        data_source_id=data_source_id,
        limit=limit,
    )


def load_nc_committee_registry_rows(
    conn: psycopg.Connection,
    rows: Iterable[NCCommitteeRegistryRow],
    *,
    limit: int | None = None,
    seen_at: datetime | None = None,
) -> LoadResult:
    """UPSERT CFOrgLkup committee discovery rows into cf.nc_committee_registry."""
    started_at = time.monotonic()
    counts = _NCLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    committee_document_data_source_id = ensure_nc_committee_document_data_source(conn)
    resolved_seen_at = _resolve_seen_at(seen_at)

    for row in _iter_nc_committee_registry_rows(rows, limit=limit):
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            inserted, candidate_name_changed, sboe_id_changed, previous_sboe_id = _upsert_nc_committee_registry_row(
                conn,
                row,
                data_source_id=committee_document_data_source_id,
                seen_at=resolved_seen_at,
            )
            if sboe_id_changed and previous_sboe_id is not None:
                prior_committee_id = _select_nc_committee_id_by_native_sboe_id(
                    conn,
                    committee_sboe_id=previous_sboe_id,
                )
                if prior_committee_id is not None:
                    _clear_stale_nc_candidacy_committee_links(
                        conn,
                        committee_id=prior_committee_id,
                        keep_candidacy_id=None,
                    )
            # Bridge pass: cf.nc_committee_registry is now persisted (the
            # SSOT for NC committee→candidacy mapping). Resolve the committee
            # through the existing NC bridge owner and write
            # civic.candidacy.committee_id where exactly one NC candidacy
            # matches by normalized name_on_ballot. Same transaction so a
            # rollback of the upsert also rolls back the bridge.
            _bridge_nc_registry_row_to_candidacy(
                conn,
                row,
                clear_stale_links=candidate_name_changed,
            )
        if inserted:
            counts.inserted += 1
        else:
            counts.skipped += 1
        _maybe_commit_and_log_progress(
            conn,
            row_type_label=_NC_COMMITTEE_REGISTRY_ROW_LABEL,
            counts=counts,
            manages_outer_transaction=manages_outer_transaction,
        )

    commit_managed_transaction(conn, manages_outer_transaction)
    return _build_load_result(
        counts,
        rows=rows,
        started_at=started_at,
    )


def load_nc_ie_transactions(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    limit: int | None = None,
) -> LoadResult:
    from .load_ie_transactions import load_nc_ie_transactions as _load_nc_ie_transactions

    return _load_nc_ie_transactions(
        conn,
        data_source_id=data_source_id,
        limit=limit,
    )


def _upsert_transaction_with_filing_lookup(
    conn: psycopg.Connection,
    *,
    row: Mapping[str, str | None],
    transaction_data_source_id: UUID,
    filing_lookup: Mapping[_NCFilingLookupKey, NCFilingLookupEntry],
) -> None:
    transaction_source_record = _build_nc_source_record(transaction_data_source_id, row)
    source_record_key = transaction_source_record.source_record_key
    source_record_id = _select_nc_source_record_id(
        conn,
        data_source_id=transaction_data_source_id,
        source_record_key=source_record_key,
    )
    if source_record_id is None:
        raise RuntimeError(f"Transaction source_record was not found for source_record_key={source_record_key!r}")

    committee_sboe_id = _normalize_nc_sboe_id(row.get("Committee SBoE ID"))
    report_key = _normalize_nc_transaction_report_key(row.get("Report Name"))
    lookup_key = (committee_sboe_id, report_key)
    filing_entry = filing_lookup.get(lookup_key)
    if filing_entry is None:
        raise ValueError(
            "No NC filing join match for transaction row using key "
            f"(SBoE ID={committee_sboe_id!r}, report_key={report_key!r})"
        )

    committee_id = _resolve_nc_committee_bridge(conn, committee_sboe_id)
    if committee_id != filing_entry.committee_id:
        raise ValueError(
            "NC filing join resolved mismatched committee IDs: "
            f"transaction committee_id={committee_id}, filing committee_id={filing_entry.committee_id}"
        )

    contributor_person_id, contributor_organization_id = resolve_transaction_counterparty_ids(
        conn,
        source_record_id=source_record_id,
        person_roles=("donor",),
        organization_roles=("contributor",),
    )
    contributor_state = _normalize_optional_text(row.get("State"))
    normalized_contributor_state = contributor_state.upper() if contributor_state is not None else None

    upsert_transaction(
        conn,
        Transaction(
            filing_id=filing_entry.filing_id,
            committee_id=committee_id,
            transaction_type=_require_text(row.get("Transction Type"), "Transction Type"),
            transaction_identifier=source_record_key,
            transaction_date=_parse_optional_date(row.get("Date Occured")),
            amount=_require_amount(row.get("Amount")),
            contributor_name_raw=_normalize_optional_text(row.get("Name")),
            contributor_employer=_normalize_optional_text(row.get("Employer's Name/Specific Field")),
            contributor_occupation=_normalize_optional_text(row.get("Profession/Job Title")),
            contributor_city=_normalize_optional_text(row.get("City")),
            contributor_state=normalized_contributor_state,
            contributor_zip=_normalize_optional_text(row.get("Zip Code")),
            contributor_person_id=contributor_person_id,
            contributor_organization_id=contributor_organization_id,
            amendment_indicator=filing_entry.amendment_indicator,
            source_record_id=source_record_id,
        ),
    )


def _load_nc_relational_transactions(
    conn: psycopg.Connection,
    transaction_rows: Iterable[Mapping[str, str | None]],
    *,
    transaction_data_source_id: UUID,
    filing_lookup: Mapping[_NCFilingLookupKey, NCFilingLookupEntry],
    limit: int | None = None,
) -> None:
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in _iter_nc_rows(transaction_rows, limit=limit):
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            _upsert_transaction_with_filing_lookup(
                conn,
                row=row,
                transaction_data_source_id=transaction_data_source_id,
                filing_lookup=filing_lookup,
            )

    commit_managed_transaction(conn, manages_outer_transaction)


def _try_load_nc_row(
    conn: psycopg.Connection,
    row: Mapping[str, str | None],
    row_load_config: _NCRowLoadConfig,
    manages_outer_transaction: bool,
) -> bool | None:
    try:
        if manages_outer_transaction:
            ensure_transaction_open(conn)
        with conn.transaction():
            return row_load_config.load_row(conn, row, row_load_config.data_source_id)
    except Exception:  # noqa: BLE001
        LOGGER.exception(
            "Failed loading NC %s row source_record_key=%s",
            row_load_config.row_type_label,
            compute_record_hash(dict(row)),
        )
        return None


def _maybe_commit_and_log_progress(
    conn: psycopg.Connection,
    *,
    row_type_label: str,
    counts: _NCLoadCounts,
    manages_outer_transaction: bool,
) -> None:
    processed_count = counts.inserted + counts.skipped + counts.errors
    if processed_count % 1_000 == 0:
        commit_managed_transaction(conn, manages_outer_transaction)

    if processed_count % 10_000 == 0:
        LOGGER.info(
            "NC %s load progress processed=%s inserted=%s skipped=%s errors=%s",
            row_type_label,
            processed_count,
            counts.inserted,
            counts.skipped,
            counts.errors,
        )


def _load_nc_rows(
    conn: psycopg.Connection,
    rows: Iterable[Mapping[str, str | None]],
    row_load_config: _NCRowLoadConfig,
    limit: int | None,
) -> LoadResult:
    started_at = time.monotonic()
    counts = _NCLoadCounts()
    manages_outer_transaction = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    for row in _iter_nc_rows(rows, limit=limit):
        inserted_row = _try_load_nc_row(
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

    return _build_load_result(
        counts,
        rows=rows,
        started_at=started_at,
    )


def load_nc_transactions(
    conn: psycopg.Connection,
    file_path: str | Path,
    *,
    data_source_id: UUID,
    limit: int | None = None,
    year_from: int | None = None,
) -> LoadResult:
    parser = parse_transactions(Path(file_path), year_from=year_from)
    return _load_nc_rows(
        conn,
        parser,
        _build_transaction_row_load_config(data_source_id),
        limit=limit,
    )


def load_nc_transactions_with_filings(
    conn: psycopg.Connection,
    transaction_file_path: str | Path,
    committee_document_file_path: str | Path,
    *,
    limit: int | None = None,
    committee_document_limit: int | None = None,
    year_from: int | None = None,
) -> NCTransactionsLoadResult:
    transaction_data_source_id = ensure_nc_data_source(conn)
    committee_document_data_source_id = ensure_nc_committee_document_data_source(conn)
    _, filing_lookup = load_nc_committee_documents(
        conn,
        committee_document_file_path,
        data_source_id=committee_document_data_source_id,
        limit=committee_document_limit,
    )
    parser = parse_transactions(Path(transaction_file_path), year_from=year_from)
    transaction_rows = list(parser)
    quarantined = parser.skipped

    transaction_load_result = _load_nc_rows(
        conn,
        iter(transaction_rows),
        _build_transaction_row_load_config(transaction_data_source_id),
        limit=limit,
    )
    transaction_result = NCTransactionsLoadResult(
        inserted=transaction_load_result.inserted,
        skipped=transaction_load_result.skipped,
        quarantined=quarantined,
        superseded=transaction_load_result.superseded,
        errors=transaction_load_result.errors,
        elapsed_seconds=transaction_load_result.elapsed_seconds,
        year_filtered=parser.filtered,
    )

    _load_nc_relational_transactions(
        conn,
        iter(transaction_rows),
        transaction_data_source_id=transaction_data_source_id,
        filing_lookup=filing_lookup,
        limit=limit,
    )
    return transaction_result
