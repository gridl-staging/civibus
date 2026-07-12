"""
Stub summary for jun04_3pm_5_launch_gate_and_golive/civibus_dev/core/people/enrichment/orchestrator.py.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from core import db, db_ingest
from core.people.federal_officeholders import federal_officeholder_targets_sql
from core.people.enrichment.models import CandidateEnrichmentRecord, CandidateEnrichmentTarget
from core.people.enrichment.strategy_chain import StrategyChain
from core.people.enrichment.strategy_official_roster_cache import (
    OfficialRosterCacheStrategy,
    ROSTER_CACHE_PORTRAIT_REUSE_METADATA_KEY,
    ROSTER_CACHE_PORTRAIT_REUSE_METADATA_VALUE,
)
from core.people.enrichment.strategy_wikipedia_bio import (
    WikipediaBioStrategy,
    _normalize_qid,
    batch_fetch_wikipedia_summaries,
    batch_fetch_wikipedia_titles,
)
from core.types.python.models import DataSource, PersonPortrait, SourceRecord, compute_record_hash
from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source, validated_limit

_CANDIDACY_SCOPE_EMPTY_WARNING = "nc_candidacy_scope_empty"
_ENRICHMENT_SOURCE_DOMAIN = "people_enrichment"
_ENRICHMENT_SOURCE_OWNER_URL = "https://civibus.shareborough.com/provenance/people-enrichment"
_BIO_TEXT_REUSABLE_LICENSES = frozenset({"public_domain", "licensed"})
FEDERAL_ENRICHMENT_JURISDICTION_SLUG = "federal-congress"
FEDERAL_ENRICHMENT_DATA_SOURCE_NAME = f"people-enrichment-{FEDERAL_ENRICHMENT_JURISDICTION_SLUG}"

_NC_CANDIDACY_TARGETS_SQL = """
    SELECT
        c.person_id,
        p.canonical_name,
        p.identifiers->>'roster_bio_url' AS roster_bio_url,
        p.identifiers->>'wikidata_id' AS wikidata_entity_id,
        p.identifiers->>'bioguide_id' AS bioguide_id
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
        p.identifiers->>'roster_bio_url' AS roster_bio_url,
        p.identifiers->>'wikidata_id' AS wikidata_entity_id,
        p.identifiers->>'bioguide_id' AS bioguide_id
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
        p.identifiers->>'roster_bio_url' AS roster_bio_url,
        p.identifiers->>'wikidata_id' AS wikidata_entity_id,
        p.identifiers->>'bioguide_id' AS bioguide_id
    FROM cf.candidate c
    JOIN core.person p ON p.id = c.person_id
    WHERE c.state = %s
      AND c.person_id IS NOT NULL
    ORDER BY p.canonical_name, c.person_id, c.id
"""


@dataclass(frozen=True)
class ScopeTarget:
    person_id: UUID
    canonical_name: str
    roster_bio_url: str | None = None
    wikidata_entity_id: str | None = None
    bioguide_id: str | None = None


@dataclass(frozen=True)
class ScopeSelectionResult:
    targets: list[ScopeTarget]
    warnings: list[str]
    candidacy_count: int
    officeholder_count: int


def _rows_to_scope_targets(rows: list[dict[str, Any]]) -> list[ScopeTarget]:
    return [
        ScopeTarget(
            person_id=row["person_id"],
            canonical_name=row["canonical_name"],
            roster_bio_url=row.get("roster_bio_url"),
            wikidata_entity_id=row.get("wikidata_entity_id"),
            bioguide_id=row.get("bioguide_id"),
        )
        for row in rows
    ]


def _select_nc_candidacy_targets(
    conn: psycopg.Connection,
    *,
    state: str,
    cycle: int,
) -> list[ScopeTarget]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_NC_CANDIDACY_TARGETS_SQL, (state, cycle))
        rows = list(cursor.fetchall())
    return _rows_to_scope_targets(rows)


def _select_nc_current_officeholder_targets(
    conn: psycopg.Connection,
    *,
    state: str,
) -> list[ScopeTarget]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_NC_OFFICEHOLDER_TARGETS_SQL, (state,))
        rows = list(cursor.fetchall())
    return _rows_to_scope_targets(rows)


def _select_cf_candidate_person_targets(
    conn: psycopg.Connection,
    *,
    state: str,
) -> list[ScopeTarget]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(_CF_CANDIDATE_TARGETS_SQL, (state,))
        rows = list(cursor.fetchall())
    return _rows_to_scope_targets(rows)


def _select_federal_current_officeholder_targets(conn: psycopg.Connection) -> list[ScopeTarget]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(federal_officeholder_targets_sql())
        rows = list(cursor.fetchall())
    return _rows_to_scope_targets(rows)


def _merge_and_sort_targets(
    primary_targets: list[ScopeTarget],
    secondary_targets: list[ScopeTarget],
) -> list[ScopeTarget]:
    merged_by_person_id: dict[UUID, ScopeTarget] = {}
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
) -> ScopeSelectionResult:
    candidacy_targets = _select_nc_candidacy_targets(conn, state=state, cycle=cycle)
    officeholder_targets = _select_nc_current_officeholder_targets(conn, state=state)
    merged_targets = _merge_and_sort_targets(candidacy_targets, officeholder_targets)

    warnings: list[str] = []
    if len(candidacy_targets) == 0:
        warnings.append(_CANDIDACY_SCOPE_EMPTY_WARNING)

    return ScopeSelectionResult(
        targets=merged_targets,
        warnings=warnings,
        candidacy_count=len(candidacy_targets),
        officeholder_count=len(officeholder_targets),
    )


def select_cf_candidate_scope_targets(
    conn: psycopg.Connection,
    *,
    state: str = "NC",
) -> ScopeSelectionResult:
    candidate_targets = _select_cf_candidate_person_targets(conn, state=state)
    merged_targets = _merge_and_sort_targets(candidate_targets, [])
    return ScopeSelectionResult(
        targets=merged_targets,
        warnings=[],
        candidacy_count=len(candidate_targets),
        officeholder_count=0,
    )


def select_federal_scope_targets(conn: psycopg.Connection) -> ScopeSelectionResult:
    """Select active federal officeholders for shared people enrichment."""
    officeholder_targets = _select_federal_current_officeholder_targets(conn)
    merged_targets = _merge_and_sort_targets(officeholder_targets, [])
    return ScopeSelectionResult(
        targets=merged_targets,
        warnings=[],
        candidacy_count=0,
        officeholder_count=len(officeholder_targets),
    )


def _build_enrichment_target(target: ScopeTarget, *, state: str | None) -> CandidateEnrichmentTarget:
    roster_bio_url = target.roster_bio_url
    if state is None and (roster_bio_url is None or roster_bio_url.strip() == "") and target.bioguide_id is not None:
        normalized_bioguide_id = target.bioguide_id.strip().upper()
        if normalized_bioguide_id != "":
            roster_bio_url = f"https://bioguide.congress.gov/search/bio/{normalized_bioguide_id}"

    return CandidateEnrichmentTarget(
        canonical_name=target.canonical_name,
        person_id=target.person_id,
        state_code=state,
        roster_bio_url=roster_bio_url,
        wikidata_entity_id=target.wikidata_entity_id,
        bioguide_id=target.bioguide_id,
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


def _resolve_writable_bio_text(record: CandidateEnrichmentRecord) -> str | None:
    normalized_license = record.bio_license.strip().lower() if isinstance(record.bio_license, str) else ""
    if normalized_license in _BIO_TEXT_REUSABLE_LICENSES:
        return record.biography
    return None


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


def _federal_jurisdiction_slug() -> str:
    return FEDERAL_ENRICHMENT_JURISDICTION_SLUG


def _build_enrichment_data_source(*, scope: str, state: str | None = None) -> DataSource:
    normalized_scope = scope.lower()
    if normalized_scope == "federal":
        return DataSource(
            domain=_ENRICHMENT_SOURCE_DOMAIN,
            jurisdiction="federal/congress",
            name=FEDERAL_ENRICHMENT_DATA_SOURCE_NAME,
            source_url=_ENRICHMENT_SOURCE_OWNER_URL,
            source_format="json",
            update_frequency="run",
        )

    if state is None:
        raise ValueError("state is required for state people enrichment scopes")
    normalized_state = _normalize_state_code(state)
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
    state: str | None = None,
    cycle: int | None,
    effective_limit: int | None = None,
) -> SourceRecord:
    normalized_scope = scope.lower()
    if normalized_scope == "federal":
        jurisdiction_key = _federal_jurisdiction_slug()
        raw_fields: dict[str, object] = {
            "scope": normalized_scope,
            "jurisdiction": "federal/congress",
        }
    else:
        if state is None:
            raise ValueError("state is required for state people enrichment scopes")
        jurisdiction_key = _normalize_state_code(state)
        raw_fields = {
            "scope": normalized_scope,
            "state": jurisdiction_key,
        }

    scope_cycle = cycle if cycle is not None else "all"
    normalized_effective_limit = validated_limit(effective_limit)
    source_record_key = f"people-enrichment:{normalized_scope}:{jurisdiction_key}:{scope_cycle}"
    if normalized_effective_limit is not None:
        source_record_key = f"{source_record_key}:limit-{normalized_effective_limit}"
    pull_date = datetime.now(timezone.utc)
    raw_fields.update(
        {
            "cycle": cycle,
            "run_scope": "partial" if normalized_effective_limit is not None else "full",
            "effective_limit": normalized_effective_limit,
            "run_id": str(uuid4()),
        }
    )
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
    state: str | None = None,
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
    scope_targets: list[ScopeTarget],
    source_record_id: UUID | None,
    state: str | None,
    summary: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return _with_refresh_loader_counts(summary)

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
            bio_text=_resolve_writable_bio_text(record),
            bio_source_url=record.bio_source_url,
            bio_license=record.bio_license,
        )
        summary["bio_updates"] += len(updated_fields)

        bio_source_record_id: UUID | None = None
        normalized_bio_source_url = record.bio_source_url.strip() if isinstance(record.bio_source_url, str) else None
        if normalized_bio_source_url == "":
            normalized_bio_source_url = None
        bio_field_updates_require_source_record = {"bio_text", "bio_source_url", "bio_license"}
        if (
            bio_field_updates_require_source_record.intersection(updated_fields)
            and normalized_bio_source_url is not None
        ):
            if run_source_data_source_id is None:
                run_source_record = db.select_source_record(conn, source_record_id)
                if run_source_record is None:
                    raise RuntimeError("Expected enrichment source_record to exist before applying enrichment writes")
                run_source_data_source_id = run_source_record.data_source_id
            observed_bio_field = "bio_text"
            for candidate_field in ("bio_text", "bio_license", "bio_source_url"):
                if candidate_field in updated_fields:
                    observed_bio_field = candidate_field
                    break
            bio_raw_fields: dict[str, object] = {
                "person_id": str(scope_target.person_id),
                "field": observed_bio_field,
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
                        rights_status=portrait_metadata.rights_status,
                    ),
                )
                summary["portrait_writes"] += 1

        summary["processed"] += 1

    return _with_refresh_loader_counts(summary)


def _with_refresh_loader_counts(summary: dict[str, Any]) -> dict[str, Any]:
    inserted_count = (
        int(summary.get("portrait_writes") or 0)
        + int(summary.get("bio_updates") or 0)
        + int(summary.get("field_provenance_writes") or 0)
    )
    return {
        **summary,
        "inserted": inserted_count,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }


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


def run_federal_enrichment(
    conn: psycopg.Connection,
    *,
    chain: StrategyChain | Any | None = None,
    source_record_id: UUID | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run people enrichment for active federal officeholders."""
    strategy_chain = StrategyChain.federal(conn=conn) if chain is None else chain
    effective_limit = validated_limit(limit)
    scope_result = select_federal_scope_targets(conn)
    scope_targets = scope_result.targets if effective_limit is None else scope_result.targets[:effective_limit]

    summary: dict[str, Any] = {
        "scope": "federal",
        "jurisdiction": "federal/congress",
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

    if chain is None:
        qids = [
            normalized_qid
            for normalized_qid in (_normalize_qid(t.wikidata_entity_id) for t in scope_targets)
            if normalized_qid is not None
        ]
        if qids:
            try:
                title_cache = batch_fetch_wikipedia_titles(qids)
                summary_cache = batch_fetch_wikipedia_summaries(list(title_cache.values()))
            except Exception as exc:  # noqa: BLE001
                summary["warnings"].append(f"wikipedia_title_prefetch_failed: {type(exc).__name__}: {exc}")
            else:
                for strategy in getattr(strategy_chain, "_strategies", ()):
                    if isinstance(strategy, WikipediaBioStrategy):
                        strategy.install_prefetch_cache(
                            title_cache=title_cache,
                            summary_cache=summary_cache,
                        )
                        break

    if not dry_run and source_record_id is None:
        data_source_id, source_record_id = _bootstrap_enrichment_source_record(
            conn,
            scope="federal",
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
        state=None,
        summary=summary,
        dry_run=dry_run,
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run people enrichment scopes")
    parser.add_argument("--scope", choices=("nc", "cf-candidate", "federal"), default="nc")
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
        if args.scope == "federal":
            summary = run_federal_enrichment(
                conn,
                source_record_id=args.source_record_id,
                limit=args.limit,
                dry_run=args.dry_run,
            )
        elif args.scope == "cf-candidate":
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
