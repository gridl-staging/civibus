
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from core import db, db_ingest
from core.people.enrichment.models import CandidateEnrichmentRecord, CandidateEnrichmentTarget
from core.people.enrichment.strategy_chain import StrategyChain
from core.people.enrichment.strategy_official_roster_cache import (
    OfficialRosterCacheStrategy,
    ROSTER_CACHE_PORTRAIT_REUSE_METADATA_KEY,
    ROSTER_CACHE_PORTRAIT_REUSE_METADATA_VALUE,
)
from core.types.python.models import DataSource, PersonPortrait, SourceRecord, compute_record_hash
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source, validated_limit

_CANDIDACY_SCOPE_EMPTY_WARNING = "nc_candidacy_scope_empty"
_ENRICHMENT_SOURCE_DOMAIN = "people_enrichment"
_ENRICHMENT_SOURCE_OWNER_URL = "https://civibus.shareborough.com/provenance/people-enrichment"

_NC_CANDIDACY_TARGETS_SQL = """
    SELECT
        c.person_id,
        p.canonical_name,
        p.identifiers->>'roster_bio_url' AS roster_bio_url
    FROM civic.candidacy c
    JOIN civic.contest ct ON ct.id = c.contest_id
    JOIN civic.office o ON o.id = ct.office_id
    JOIN core.person p ON p.id = c.person_id
    WHERE o.state = %s
      AND ct.election_date IS NOT NULL
      AND DATE_PART('year', ct.election_date) = %s
    ORDER BY p.canonical_name, c.person_id
"""

_NC_OFFICEHOLDER_TARGETS_SQL = """
    SELECT
        oh.person_id,
        p.canonical_name,
        p.identifiers->>'roster_bio_url' AS roster_bio_url
    FROM civic.officeholding oh
    JOIN civic.office o ON o.id = oh.office_id
    JOIN core.person p ON p.id = oh.person_id
    WHERE o.state = %s
      AND upper_inf(oh.valid_period)
    ORDER BY p.canonical_name, oh.person_id
"""

_CF_CANDIDATE_TARGETS_SQL = """
    SELECT
        c.person_id,
        p.canonical_name,
        p.identifiers->>'roster_bio_url' AS roster_bio_url
    FROM cf.candidate c
    JOIN core.person p ON p.id = c.person_id
    WHERE c.state = %s
      AND c.person_id IS NOT NULL
    ORDER BY p.canonical_name, c.person_id, c.id
"""


@dataclass(frozen=True)
class NcScopeTarget:
    person_id: UUID
    canonical_name: str
    roster_bio_url: str | None = None


@dataclass(frozen=True)
class NcScopeSelectionResult:
    targets: list[NcScopeTarget]
    warnings: list[str]
    candidacy_count: int
    officeholder_count: int


def _rows_to_scope_targets(rows: list[dict[str, Any]]) -> list[NcScopeTarget]:
    return [
        NcScopeTarget(
            person_id=row["person_id"],
            canonical_name=row["canonical_name"],
            roster_bio_url=row.get("roster_bio_url"),
        )
        for row in rows
    ]


def _select_nc_candidacy_targets(
    conn: psycopg.Connection,
    *,
    state: str,
    cycle: int,
) -> list[NcScopeTarget]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_NC_CANDIDACY_TARGETS_SQL, (state, cycle))
        rows = list(cursor.fetchall())
    return _rows_to_scope_targets(rows)


def _select_nc_current_officeholder_targets(
    conn: psycopg.Connection,
    *,
    state: str,
) -> list[NcScopeTarget]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_NC_OFFICEHOLDER_TARGETS_SQL, (state,))
        rows = list(cursor.fetchall())
    return _rows_to_scope_targets(rows)


def _select_cf_candidate_person_targets(
    conn: psycopg.Connection,
    *,
    state: str,
) -> list[NcScopeTarget]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_CF_CANDIDATE_TARGETS_SQL, (state,))
        rows = list(cursor.fetchall())
    return _rows_to_scope_targets(rows)


def _merge_and_sort_targets(
    primary_targets: list[NcScopeTarget],
    secondary_targets: list[NcScopeTarget],
) -> list[NcScopeTarget]:
    merged_by_person_id: dict[UUID, NcScopeTarget] = {}
    for target in primary_targets:
        merged_by_person_id[target.person_id] = target

    for target in secondary_targets:
        merged_by_person_id.setdefault(target.person_id, target)

    return sorted(
        merged_by_person_id.values(),
        key=lambda target: (target.canonical_name.lower(), str(target.person_id)),
    )


def select_nc_scope_targets(
    conn: psycopg.Connection,
    *,
    state: str = "NC",
    cycle: int = 2026,
) -> NcScopeSelectionResult:
    candidacy_targets = _select_nc_candidacy_targets(conn, state=state, cycle=cycle)
    officeholder_targets = _select_nc_current_officeholder_targets(conn, state=state)
    merged_targets = _merge_and_sort_targets(candidacy_targets, officeholder_targets)

    warnings: list[str] = []
    if len(candidacy_targets) == 0:
        warnings.append(_CANDIDACY_SCOPE_EMPTY_WARNING)

    return NcScopeSelectionResult(
        targets=merged_targets,
        warnings=warnings,
        candidacy_count=len(candidacy_targets),
        officeholder_count=len(officeholder_targets),
    )


def select_cf_candidate_scope_targets(
    conn: psycopg.Connection,
    *,
    state: str = "NC",
) -> NcScopeSelectionResult:
    candidate_targets = _select_cf_candidate_person_targets(conn, state=state)
    merged_targets = _merge_and_sort_targets(candidate_targets, [])
    return NcScopeSelectionResult(
        targets=merged_targets,
        warnings=[],
        candidacy_count=len(candidate_targets),
        officeholder_count=0,
    )


def _build_enrichment_target(target: NcScopeTarget, *, state: str) -> CandidateEnrichmentTarget:
    return CandidateEnrichmentTarget(
        canonical_name=target.canonical_name,
        person_id=target.person_id,
        state_code=state,
        roster_bio_url=target.roster_bio_url,
    )


def _resolve_portrait_status(record: CandidateEnrichmentRecord) -> str | None:
    for attempt in reversed(record.attempts):
        if attempt.portrait_status is not None:
            return attempt.portrait_status

    if record.portrait_metadata is not None:
        return "active"

    return None


def _normalize_state_code(state: str) -> str:
    return state.strip().upper()


def _is_roster_cached_portrait_reuse(record: CandidateEnrichmentRecord) -> bool:
    portrait_source = record.field_provenance.get("portrait_image_url")
    if portrait_source == OfficialRosterCacheStrategy.source_name:
        return True

    for attempt in record.attempts:
        if attempt.source != OfficialRosterCacheStrategy.source_name:
            continue
        if attempt.status != "succeeded":
            continue
        if attempt.metadata.get(ROSTER_CACHE_PORTRAIT_REUSE_METADATA_KEY) != ROSTER_CACHE_PORTRAIT_REUSE_METADATA_VALUE:
            continue
        return True

    return False


def _build_enrichment_data_source(*, scope: str, state: str) -> DataSource:
    normalized_state = _normalize_state_code(state)
    normalized_scope = scope.lower()
    return DataSource(
        domain=_ENRICHMENT_SOURCE_DOMAIN,
        jurisdiction=f"state/{normalized_state}",
        name=f"people-enrichment-{normalized_scope}-{normalized_state}",
        source_url=_ENRICHMENT_SOURCE_OWNER_URL,
        source_format="json",
        update_frequency="run",
    )


def _build_enrichment_source_record(
    *,
    data_source_id: UUID,
    scope: str,
    state: str,
    cycle: int | None,
    effective_limit: int | None = None,
) -> SourceRecord:
    normalized_state = _normalize_state_code(state)
    normalized_scope = scope.lower()
    scope_cycle = cycle if cycle is not None else "all"
    normalized_effective_limit = validated_limit(effective_limit)
    source_record_key = f"people-enrichment:{normalized_scope}:{normalized_state}:{scope_cycle}"
    if normalized_effective_limit is not None:
        source_record_key = f"{source_record_key}:limit-{normalized_effective_limit}"
    pull_date = datetime.now(timezone.utc)
    raw_fields: dict[str, object] = {
        "scope": normalized_scope,
        "state": normalized_state,
        "cycle": cycle,
        "run_scope": "partial" if normalized_effective_limit is not None else "full",
        "effective_limit": normalized_effective_limit,
        "run_id": str(uuid4()),
    }
    return SourceRecord(
        data_source_id=data_source_id,
        source_record_key=source_record_key,
        source_url=None,
        raw_fields=raw_fields,
        pull_date=pull_date,
        record_hash=compute_record_hash(raw_fields),
    )


def _bootstrap_enrichment_source_record(
    conn: psycopg.Connection,
    *,
    scope: str,
    state: str,
    cycle: int | None,
    effective_limit: int | None = None,
) -> tuple[UUID, UUID]:
    data_source = _build_enrichment_data_source(scope=scope, state=state)
    data_source_id = ensure_data_source(conn, data_source)
    source_record = _build_enrichment_source_record(
        data_source_id=data_source_id,
        scope=scope,
        state=state,
        cycle=cycle,
        effective_limit=effective_limit,
    )

    inserted_source_record_id = db_ingest.try_insert_source_record(conn, source_record)
    if inserted_source_record_id is None:
        selected_source_record = db.select_active_source_record_by_key(
            conn,
            data_source_id=data_source_id,
            source_record_key=source_record.source_record_key or "",
        )
        if selected_source_record is None:
            raise RuntimeError("Expected an active enrichment source_record after insert conflict")
        return data_source_id, selected_source_record.id

    selected_source_record = db.select_source_record(conn, inserted_source_record_id)
    if selected_source_record is None:
        raise RuntimeError("Expected inserted enrichment source_record to be selectable")
    return data_source_id, selected_source_record.id


def _apply_enrichment_for_targets(
    conn: psycopg.Connection,
    *,
    strategy_chain: StrategyChain | Any,
    scope_targets: list[NcScopeTarget],
    source_record_id: UUID | None,
    state: str,
    summary: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return summary

    if source_record_id is None:
        raise ValueError("enrichment run requires source_record_id when dry_run=False")
    run_source_data_source_id: UUID | None = None

    for scope_target in scope_targets:
        enrichment_target = _build_enrichment_target(scope_target, state=state)
        record = strategy_chain.enrich(enrichment_target)

        selected_person = db.select_person(conn, scope_target.person_id)
        if selected_person is None:
            continue

        updated_fields = db.update_person_bio_fields_if_missing(
            conn,
            person_id=scope_target.person_id,
            occupation=record.occupation,
            education=record.education,
            bio_text=record.biography,
            bio_source_url=record.bio_source_url,
            bio_license=record.bio_license,
        )
        summary["bio_updates"] += len(updated_fields)

        bio_source_record_id: UUID | None = None
        normalized_bio_source_url = record.bio_source_url.strip() if isinstance(record.bio_source_url, str) else None
        if normalized_bio_source_url == "":
            normalized_bio_source_url = None
        if "bio_text" in updated_fields and normalized_bio_source_url is not None:
            if run_source_data_source_id is None:
                run_source_record = db.select_source_record(conn, source_record_id)
                if run_source_record is None:
                    raise RuntimeError("Expected enrichment source_record to exist before applying enrichment writes")
                run_source_data_source_id = run_source_record.data_source_id
            bio_raw_fields: dict[str, object] = {
                "person_id": str(scope_target.person_id),
                "field": "bio_text",
                "bio_source_url": normalized_bio_source_url,
                "bio_license": record.bio_license,
            }
            bio_source_record = SourceRecord(
                data_source_id=run_source_data_source_id,
                source_record_key=normalized_bio_source_url,
                source_url=normalized_bio_source_url,
                raw_fields=bio_raw_fields,
                pull_date=datetime.now(timezone.utc),
                record_hash=compute_record_hash(bio_raw_fields),
            )
            inserted_bio_source_record_id = db_ingest.try_insert_source_record(conn, bio_source_record)
            if inserted_bio_source_record_id is None:
                selected_bio_source_record = db.select_active_source_record_by_key(
                    conn,
                    data_source_id=run_source_data_source_id,
                    source_record_key=normalized_bio_source_url,
                )
                if selected_bio_source_record is None:
                    raise RuntimeError("Expected active bio source_record after insert conflict")
                bio_source_record_id = selected_bio_source_record.id
            else:
                bio_source_record_id = inserted_bio_source_record_id

        for field_name in updated_fields:
            if field_name == "bio_source_url":
                continue
            if field_name == "bio_text":
                field_value = record.biography
            else:
                field_value = getattr(record, field_name)
            if isinstance(field_value, str) and field_value.strip() != "":
                provenance_source_record_id = source_record_id
                if field_name in {"bio_text", "bio_license"} and bio_source_record_id is not None:
                    provenance_source_record_id = bio_source_record_id
                db_ingest.insert_field_provenance(
                    conn,
                    "person",
                    scope_target.person_id,
                    field_name,
                    field_value,
                    provenance_source_record_id,
                )
                summary["field_provenance_writes"] += 1

        portrait_status = _resolve_portrait_status(record)
        portrait_metadata = record.portrait_metadata
        portrait_is_roster_cache_reuse = _is_roster_cached_portrait_reuse(record)
        if portrait_status is not None and portrait_metadata is not None and not portrait_is_roster_cache_reuse:
            takedown_exists_for_source_image = db.person_has_takedown_requested_portrait_source_image(
                conn,
                person_id=selected_person.id,
                source_image_url=portrait_metadata.source_image_url,
            )
            if not takedown_exists_for_source_image:
                db.insert_person_portrait(
                    conn,
                    PersonPortrait(
                        person_id=selected_person.id,
                        source_record_id=source_record_id,
                        status=portrait_status,
                        image_hash=portrait_metadata.image_hash,
                        mime_type=portrait_metadata.mime_type,
                        width_px=portrait_metadata.width_px,
                        height_px=portrait_metadata.height_px,
                        source_image_url=portrait_metadata.source_image_url,
                    ),
                )
                summary["portrait_writes"] += 1

        summary["processed"] += 1

    return summary


def run_nc_enrichment(
    conn: psycopg.Connection,
    *,
    chain: StrategyChain | Any | None = None,
    source_record_id: UUID | None = None,
    state: str = "NC",
    cycle: int = 2026,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    strategy_chain = chain or StrategyChain.default(conn=conn)
    effective_limit = validated_limit(limit)
    scope_result = select_nc_scope_targets(conn, state=state, cycle=cycle)
    scope_targets = scope_result.targets if effective_limit is None else scope_result.targets[:effective_limit]

    summary: dict[str, Any] = {
        "state": state,
        "cycle": cycle,
        "selected": len(scope_targets),
        "processed": 0,
        "warnings": list(scope_result.warnings),
        "candidacy_count": scope_result.candidacy_count,
        "officeholder_count": scope_result.officeholder_count,
        "portrait_writes": 0,
        "bio_updates": 0,
        "field_provenance_writes": 0,
        "dry_run": dry_run,
        "data_source_id": None,
        "source_record_id": source_record_id,
    }

    if not dry_run and source_record_id is None:
        data_source_id, source_record_id = _bootstrap_enrichment_source_record(
            conn,
            scope="nc",
            state=state,
            cycle=cycle,
            effective_limit=effective_limit,
        )
        summary["data_source_id"] = data_source_id
        summary["source_record_id"] = source_record_id

    return _apply_enrichment_for_targets(
        conn,
        strategy_chain=strategy_chain,
        scope_targets=scope_targets,
        source_record_id=source_record_id,
        state=state,
        summary=summary,
        dry_run=dry_run,
    )


def run_cf_candidate_enrichment(
    conn: psycopg.Connection,
    *,
    chain: StrategyChain | Any | None = None,
    source_record_id: UUID | None = None,
    state: str = "NC",
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    strategy_chain = chain or StrategyChain.default(conn=conn)
    effective_limit = validated_limit(limit)
    scope_result = select_cf_candidate_scope_targets(conn, state=state)
    scope_targets = scope_result.targets if effective_limit is None else scope_result.targets[:effective_limit]

    summary: dict[str, Any] = {
        "state": state,
        "selected": len(scope_targets),
        "processed": 0,
        "warnings": list(scope_result.warnings),
        "candidacy_count": scope_result.candidacy_count,
        "officeholder_count": scope_result.officeholder_count,
        "portrait_writes": 0,
        "bio_updates": 0,
        "field_provenance_writes": 0,
        "dry_run": dry_run,
        "data_source_id": None,
        "source_record_id": source_record_id,
    }

    if not dry_run and source_record_id is None:
        data_source_id, source_record_id = _bootstrap_enrichment_source_record(
            conn,
            scope="cf-candidate",
            state=state,
            cycle=None,
            effective_limit=effective_limit,
        )
        summary["data_source_id"] = data_source_id
        summary["source_record_id"] = source_record_id

    return _apply_enrichment_for_targets(
        conn,
        strategy_chain=strategy_chain,
        scope_targets=scope_targets,
        source_record_id=source_record_id,
        state=state,
        summary=summary,
        dry_run=dry_run,
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run NC people enrichment scope")
    parser.add_argument("--scope", choices=("nc", "cf-candidate"), default="nc")
    parser.add_argument("--state", default="NC")
    parser.add_argument("--cycle", default=2026, type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source-record-id", type=UUID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    conn = db.get_connection()
    try:
        if args.scope == "cf-candidate":
            summary = run_cf_candidate_enrichment(
                conn,
                source_record_id=args.source_record_id,
                state=args.state,
                limit=args.limit,
                dry_run=args.dry_run,
            )
        else:
            summary = run_nc_enrichment(
                conn,
                source_record_id=args.source_record_id,
                state=args.state,
                cycle=args.cycle,
                limit=args.limit,
                dry_run=args.dry_run,
            )
        if not args.dry_run:
            conn.commit()
    except Exception:
        if not args.dry_run:
            conn.rollback()
        raise
    finally:
        conn.close()

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
