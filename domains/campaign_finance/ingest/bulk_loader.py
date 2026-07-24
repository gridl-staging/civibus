"""
Stub summary for jun04_3pm_1_fec_money_pipeline/civibus_dev/domains/campaign_finance/ingest/bulk_loader.py.
"""

from __future__ import annotations

from datetime import date
import logging
from pathlib import Path
from uuid import UUID

import psycopg

from core.db import (
    find_organization_by_identifier,
    find_person_by_identifier,
    insert_entity_source,
    insert_organization,
    insert_person,
    try_insert_data_source,
    try_insert_source_record,
)
from core.types.python.models import (
    DataSource,
    Organization,
    Person,
    SourceRecord,
    compute_record_hash,
    utc_now,
)
from domains.campaign_finance.constants import (
    FEC_BULK_DATA_SOURCE_DOMAIN as _FEC_BULK_DATA_SOURCE_DOMAIN,
    FEC_BULK_DATA_SOURCE_JURISDICTION as _FEC_BULK_DATA_SOURCE_JURISDICTION,
    FEC_BULK_DATA_SOURCE_NAME,
)
from domains.campaign_finance.ingest.bulk_loader_addresses import (
    _build_fec_mailing_address,
    _link_row_mailing_address,
    _normalize_optional_state_code,
    _normalize_zip_parts,
)
from domains.campaign_finance.ingest.bulk_parser import read_bulk_file
from domains.campaign_finance.ingest.bulk_stage4_loader import (
    LoadResult,
    Stage4LoadOptions,
    _commit_batch,
    _commit_final_batch,
    _log_stage4_progress,
    _validate_batch_size,
    load_committee_transactions,
    load_contributions,
)
from domains.campaign_finance.ingest.bulk_loader_ccl import (
    _build_ccl_source_record_key,
    _insert_candidate_committee_link,
)
from domains.campaign_finance.ingest.field_mapper import (
    map_candidate_fields,
    map_candidate_summary_fields,
    map_ccl_fields,
    map_committee_fields,
)
from domains.campaign_finance.ingest.fec_lookup import find_candidate_id_by_fec_id, find_committee_id_by_fec_id
from domains.campaign_finance.ingest.text_utils import normalize_optional_text

LOGGER = logging.getLogger(__name__)

_FEC_BULK_DATA_SOURCE_URL = "https://www.fec.gov/data/browse-data/?tab=bulk-data"
_FEC_BULK_DATA_SOURCE_FORMAT = "pipe_delimited"


def _select_fec_bulk_data_source_id(conn: psycopg.Connection) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            LIMIT 1
            """,
            (
                _FEC_BULK_DATA_SOURCE_DOMAIN,
                _FEC_BULK_DATA_SOURCE_JURISDICTION,
                FEC_BULK_DATA_SOURCE_NAME,
            ),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def ensure_fec_bulk_data_source(conn: psycopg.Connection) -> UUID:
    existing_id = _select_fec_bulk_data_source_id(conn)
    if existing_id is not None:
        return existing_id

    data_source = DataSource(
        domain=_FEC_BULK_DATA_SOURCE_DOMAIN,
        jurisdiction=_FEC_BULK_DATA_SOURCE_JURISDICTION,
        name=FEC_BULK_DATA_SOURCE_NAME,
        source_url=_FEC_BULK_DATA_SOURCE_URL,
        source_format=_FEC_BULK_DATA_SOURCE_FORMAT,
        license="public_domain",
        update_frequency="periodic",
    )

    inserted_id = try_insert_data_source(conn, data_source)
    if inserted_id is not None:
        return inserted_id

    existing_id = _select_fec_bulk_data_source_id(conn)
    if existing_id is not None:
        return existing_id

    raise RuntimeError("FEC bulk data source insert reported conflict but existing row could not be selected")


def _build_source_record(
    *, data_source_id: UUID, source_record_key: str, raw_fields: dict[str, object]
) -> SourceRecord:
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        raw_fields=raw_fields,
        pull_date=utc_now(),
        record_hash=compute_record_hash(raw_fields),
    )


def _try_insert_bulk_source_record(
    conn: psycopg.Connection, *, data_source_id: UUID, source_record_key: str, raw_row: dict[str, object]
) -> UUID | None:
    return try_insert_source_record(
        conn,
        _build_source_record(
            data_source_id=data_source_id,
            source_record_key=source_record_key,
            raw_fields=dict(raw_row),
        ),
    )


def _upsert_committee(
    conn: psycopg.Connection,
    *,
    mapped_fields: dict[str, object],
    organization_id: UUID,
    source_record_id: UUID,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.committee (
                fec_committee_id,
                name,
                committee_type,
                committee_designation,
                party,
                state,
                city,
                zip_code,
                treasurer_name,
                organization_id,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fec_committee_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                committee_type = EXCLUDED.committee_type,
                committee_designation = EXCLUDED.committee_designation,
                party = EXCLUDED.party,
                state = EXCLUDED.state,
                city = EXCLUDED.city,
                zip_code = EXCLUDED.zip_code,
                treasurer_name = EXCLUDED.treasurer_name,
                organization_id = EXCLUDED.organization_id,
                source_record_id = EXCLUDED.source_record_id
            """,
            (
                mapped_fields["fec_committee_id"],
                mapped_fields["name"],
                mapped_fields["committee_type"],
                mapped_fields["committee_designation"],
                mapped_fields["party"],
                mapped_fields["state"],
                mapped_fields["city"],
                mapped_fields["zip_code"],
                mapped_fields["treasurer_name"],
                organization_id,
                source_record_id,
            ),
        )


def _finalize_stage3_row(
    conn: psycopg.Connection,
    *,
    file_type: str,
    processed_rows: int,
    load_result: LoadResult,
    processed_since_commit: int,
    batch_size: int,
) -> int:
    _log_stage4_progress(file_type, processed_rows, load_result)
    return _commit_batch(conn, processed_since_commit, batch_size)


def load_committees(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int | str,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    _validate_batch_size(batch_size)

    cycle_key = str(cycle)
    load_result = LoadResult()
    processed_rows = 0
    processed_since_commit = 0

    for raw_row in read_bulk_file(path, "cm", limit=limit):
        processed_rows += 1
        processed_since_commit += 1
        mapped_fields = map_committee_fields(raw_row)
        mapped_fields["state"] = _normalize_optional_state_code(mapped_fields.get("state"))

        fec_committee_id = normalize_optional_text(mapped_fields.get("fec_committee_id"))
        committee_name = normalize_optional_text(mapped_fields.get("name"))
        if fec_committee_id is None or committee_name is None:
            load_result.errors += 1
            LOGGER.warning("Skipping committee row with missing required fields: %s", raw_row)
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="cm",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        source_record_id = _try_insert_bulk_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=f"cm:{cycle_key}:{fec_committee_id}",
            raw_row=dict(raw_row),
        )
        if source_record_id is None:
            load_result.skipped += 1
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="cm",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        organization_id = find_organization_by_identifier(conn, "fec_committee_id", fec_committee_id)
        if organization_id is None:
            organization_id = insert_organization(
                conn,
                Organization(
                    canonical_name=committee_name,
                    identifiers={"fec_committee_id": fec_committee_id},
                ),
            )

        insert_entity_source(conn, "organization", organization_id, source_record_id, "committee")

        _link_row_mailing_address(
            conn,
            raw_row=dict(raw_row),
            field_prefix="CMTE",
            entity_type="organization",
            entity_id=organization_id,
            source_record_id=source_record_id,
            extraction_role="committee_mailing_address",
        )

        _upsert_committee(
            conn,
            mapped_fields={
                **mapped_fields,
                "fec_committee_id": fec_committee_id,
                "name": committee_name,
            },
            organization_id=organization_id,
            source_record_id=source_record_id,
        )

        load_result.inserted += 1
        processed_since_commit = _finalize_stage3_row(
            conn,
            file_type="cm",
            processed_rows=processed_rows,
            load_result=load_result,
            processed_since_commit=processed_since_commit,
            batch_size=batch_size,
        )

    _commit_final_batch(conn, processed_since_commit)
    return load_result


def _upsert_candidate(
    conn: psycopg.Connection,
    *,
    mapped_fields: dict[str, object],
    principal_committee_id: UUID | None,
    person_id: UUID,
    source_record_id: UUID,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.candidate (
                fec_candidate_id,
                name,
                party,
                office,
                state,
                district,
                incumbent_challenge,
                principal_committee_id,
                person_id,
                source_record_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fec_candidate_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                party = EXCLUDED.party,
                office = EXCLUDED.office,
                state = EXCLUDED.state,
                district = EXCLUDED.district,
                incumbent_challenge = EXCLUDED.incumbent_challenge,
                principal_committee_id = EXCLUDED.principal_committee_id,
                person_id = EXCLUDED.person_id,
                source_record_id = EXCLUDED.source_record_id
            """,
            (
                mapped_fields["fec_candidate_id"],
                mapped_fields["name"],
                mapped_fields["party"],
                mapped_fields["office"],
                mapped_fields["state"],
                mapped_fields["district"],
                mapped_fields["incumbent_challenge"],
                principal_committee_id,
                person_id,
                source_record_id,
            ),
        )


def load_candidates(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int | str,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    _validate_batch_size(batch_size)

    cycle_key = str(cycle)
    load_result = LoadResult()
    processed_rows = 0
    processed_since_commit = 0

    for raw_row in read_bulk_file(path, "cn", limit=limit):
        processed_rows += 1
        processed_since_commit += 1
        mapped_fields = map_candidate_fields(raw_row)

        fec_candidate_id = normalize_optional_text(mapped_fields.get("fec_candidate_id"))
        candidate_name = normalize_optional_text(mapped_fields.get("name"))
        candidate_office = normalize_optional_text(mapped_fields.get("office"))
        if fec_candidate_id is None or candidate_name is None or candidate_office is None:
            load_result.errors += 1
            LOGGER.warning("Skipping candidate row with missing required fields: %s", raw_row)
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="cn",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        source_record_id = _try_insert_bulk_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=f"cn:{cycle_key}:{fec_candidate_id}",
            raw_row=dict(raw_row),
        )
        if source_record_id is None:
            load_result.skipped += 1
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="cn",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        person_id = find_person_by_identifier(conn, "fec_candidate_id", fec_candidate_id)
        if person_id is None:
            person_id = insert_person(
                conn,
                Person(
                    canonical_name=candidate_name,
                    identifiers={"fec_candidate_id": fec_candidate_id},
                ),
            )

        insert_entity_source(conn, "person", person_id, source_record_id, "candidate")

        _link_row_mailing_address(
            conn,
            raw_row=dict(raw_row),
            field_prefix="CAND",
            entity_type="person",
            entity_id=person_id,
            source_record_id=source_record_id,
            extraction_role="candidate_mailing_address",
        )

        principal_committee_fec_id = normalize_optional_text(mapped_fields.get("principal_committee_fec_id"))
        principal_committee_id = None
        if principal_committee_fec_id is not None:
            principal_committee_id = find_committee_id_by_fec_id(conn, principal_committee_fec_id)

        _upsert_candidate(
            conn,
            mapped_fields={
                **mapped_fields,
                "fec_candidate_id": fec_candidate_id,
                "name": candidate_name,
                "office": candidate_office,
            },
            principal_committee_id=principal_committee_id,
            person_id=person_id,
            source_record_id=source_record_id,
        )

        load_result.inserted += 1
        processed_since_commit = _finalize_stage3_row(
            conn,
            file_type="cn",
            processed_rows=processed_rows,
            load_result=load_result,
            processed_since_commit=processed_since_commit,
            batch_size=batch_size,
        )

    _commit_final_batch(conn, processed_since_commit)
    return load_result


def _update_candidate_summary(
    conn: psycopg.Connection,
    *,
    mapped_fields: dict[str, object],
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE cf.candidate
            SET total_receipts = %s,
                total_disbursements = %s,
                cash_on_hand = %s,
                candidate_contrib = %s,
                candidate_loans = %s,
                candidate_loan_repay = %s,
                summary_coverage_end_date = %s,
                updated_at = NOW()
            WHERE fec_candidate_id = %s
            """,
            (
                mapped_fields["total_receipts"],
                mapped_fields["total_disbursements"],
                mapped_fields["cash_on_hand"],
                mapped_fields["candidate_contrib"],
                mapped_fields["candidate_loans"],
                mapped_fields["candidate_loan_repay"],
                mapped_fields["summary_coverage_end_date"],
                mapped_fields["fec_candidate_id"],
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Expected one candidate summary update for {mapped_fields['fec_candidate_id']}")


def load_candidate_summaries(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int | str,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    """Load official all-candidate totals from FEC weball without creating candidate rows."""
    _validate_batch_size(batch_size)

    cycle_key = str(cycle)
    load_result = LoadResult()
    processed_rows = 0
    processed_since_commit = 0

    for raw_row in read_bulk_file(path, "weball", limit=limit):
        processed_rows += 1
        processed_since_commit += 1
        mapped_fields = map_candidate_summary_fields(raw_row)
        fec_candidate_id = normalize_optional_text(mapped_fields.get("fec_candidate_id"))
        if fec_candidate_id is None:
            load_result.errors += 1
            LOGGER.warning("Skipping weball row with missing candidate id: %s", raw_row)
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="weball",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        if find_candidate_id_by_fec_id(conn, fec_candidate_id) is None:
            load_result.skipped += 1
            LOGGER.warning("Skipping weball row with unresolved candidate_fec_id=%s", fec_candidate_id)
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="weball",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        source_record_id = _try_insert_bulk_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=f"weball:{cycle_key}:{fec_candidate_id}",
            raw_row=dict(raw_row),
        )
        if source_record_id is None:
            load_result.skipped += 1
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="weball",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        _update_candidate_summary(
            conn,
            mapped_fields={**mapped_fields, "fec_candidate_id": fec_candidate_id},
        )
        load_result.inserted += 1
        processed_since_commit = _finalize_stage3_row(
            conn,
            file_type="weball",
            processed_rows=processed_rows,
            load_result=load_result,
            processed_since_commit=processed_since_commit,
            batch_size=batch_size,
        )

    _commit_final_batch(conn, processed_since_commit)
    return load_result


def load_candidate_committee_links(
    conn: psycopg.Connection,
    path: str | Path,
    *,
    cycle: int | str,
    data_source_id: UUID,
    batch_size: int = 1000,
    limit: int | None = None,
) -> LoadResult:
    _validate_batch_size(batch_size)

    cycle_key = str(cycle)
    load_result = LoadResult()
    processed_rows = 0
    processed_since_commit = 0

    for raw_row in read_bulk_file(path, "ccl", limit=limit):
        processed_rows += 1
        processed_since_commit += 1
        mapped_fields = map_ccl_fields(raw_row)

        candidate_fec_id = normalize_optional_text(mapped_fields.get("candidate_fec_id"))
        committee_fec_id = normalize_optional_text(mapped_fields.get("committee_fec_id"))
        if candidate_fec_id is None or committee_fec_id is None:
            load_result.errors += 1
            LOGGER.warning("Skipping CCL row with missing candidate or committee id: %s", raw_row)
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="ccl",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        candidate_id = find_candidate_id_by_fec_id(conn, candidate_fec_id)
        committee_id = find_committee_id_by_fec_id(conn, committee_fec_id)
        if candidate_id is None or committee_id is None:
            load_result.skipped += 1
            LOGGER.warning(
                "Skipping CCL row with unresolved foreign keys candidate_fec_id=%s committee_fec_id=%s",
                candidate_fec_id,
                committee_fec_id,
            )
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="ccl",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        source_record_key = _build_ccl_source_record_key(cycle_key, mapped_fields)
        if source_record_key is None:
            load_result.errors += 1
            LOGGER.warning("Skipping CCL row with no stable source key: %s", raw_row)
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="ccl",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        candidate_election_year = mapped_fields.get("candidate_election_year")
        if not isinstance(candidate_election_year, int):
            load_result.errors += 1
            LOGGER.warning("Skipping CCL row with invalid candidate_election_year: %s", raw_row)
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="ccl",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        source_record_id = _try_insert_bulk_source_record(
            conn,
            data_source_id=data_source_id,
            source_record_key=source_record_key,
            raw_row=dict(raw_row),
        )
        if source_record_id is None:
            load_result.skipped += 1
            processed_since_commit = _finalize_stage3_row(
                conn,
                file_type="ccl",
                processed_rows=processed_rows,
                load_result=load_result,
                processed_since_commit=processed_since_commit,
                batch_size=batch_size,
            )
            continue

        period_start = date(candidate_election_year, 1, 1)
        period_end = date(candidate_election_year + 1, 1, 1)

        inserted = _insert_candidate_committee_link(
            conn,
            candidate_id=candidate_id,
            committee_id=committee_id,
            designation=normalize_optional_text(mapped_fields.get("designation")),
            candidate_election_year=candidate_election_year,
            fec_election_year=mapped_fields.get("fec_election_year")
            if isinstance(mapped_fields.get("fec_election_year"), int)
            else None,
            period_start=period_start,
            period_end=period_end,
            source_record_id=source_record_id,
        )
        if inserted:
            load_result.inserted += 1
        else:
            load_result.skipped += 1

        processed_since_commit = _finalize_stage3_row(
            conn,
            file_type="ccl",
            processed_rows=processed_rows,
            load_result=load_result,
            processed_since_commit=processed_since_commit,
            batch_size=batch_size,
        )

    _commit_final_batch(conn, processed_since_commit)
    return load_result


def _count_active_source_records(conn: psycopg.Connection, data_source_id: UUID) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM core.source_record WHERE data_source_id = %s AND superseded_by IS NULL",
            (data_source_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def sync_data_source_metadata(
    conn: psycopg.Connection,
    data_source_id: UUID,
    *,
    pull_status: str,
) -> int:
    """Sync record_count, last_pull_at, last_pull_status on core.data_source.

    Sources record_count from active core.source_record rows (superseded_by IS NULL)
    instead of trusting caller-supplied counts. Returns the stored record_count.
    """
    record_count = _count_active_source_records(conn, data_source_id)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE core.data_source
            SET record_count = %s,
                last_pull_at = NOW(),
                last_pull_status = %s
            WHERE id = %s
            """,
            (record_count, pull_status, data_source_id),
        )
    conn.commit()
    return record_count


__all__ = [
    "FEC_BULK_DATA_SOURCE_NAME",
    "LoadResult",
    "Stage4LoadOptions",
    "_build_fec_mailing_address",
    "_link_row_mailing_address",
    "_normalize_optional_state_code",
    "_normalize_zip_parts",
    "ensure_fec_bulk_data_source",
    "load_committees",
    "load_candidates",
    "load_candidate_summaries",
    "load_candidate_committee_links",
    "load_contributions",
    "load_committee_transactions",
    "sync_data_source_metadata",
]
