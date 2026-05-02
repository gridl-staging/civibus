
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel

from core.db import get_connection
from core.keel_gate_l3 import _load_registry as load_sources_registry
from domains.campaign_finance.coverage import lifecycle as coverage_lifecycle
from domains.campaign_finance.coverage import registry as coverage_registry
from domains.civics.loaders.official_rosters.loader import manifest_member_counts_by_source_id

_REPO_ROOT = Path(__file__).resolve().parents[1]

L14_SCOPE = "coverage_registry_projection"
_DEFAULT_REGISTRY_PATH = Path("docs/research/coverage-registry.json")
_DEFAULT_LIFECYCLE_PATH = Path("docs/research/implemented-region-lifecycle.json")
_DEFAULT_SOURCES_PATH = Path("sources.yaml")
_NC_GEOMETRY_EXPECTED_COUNT_BY_DIVISION_TYPE: Mapping[str, int] = {
    "county": 3,
    "congressional_district": 14,
    "state_legislative_upper": 50,
    "state_legislative_lower": 120,
    "municipal": 19,
    "school_district": 4,
}


class NcGeometrySummary(BaseModel, extra="forbid"):
    total_count: int
    srid_4326_count: int


class L14CoverageRow(BaseModel, extra="forbid"):

    jurisdiction_code: str
    name: str
    jurisdiction_type: str
    best_update_frequency: str
    runner_wired: bool
    tier: coverage_registry.TierLiteral | None
    loaded_count: int | None = None
    expected_count: int | None = None
    operational_reason: str | None
    next_action: str | None
    evidence_date: date | None
    acquisition_pattern: coverage_lifecycle.AcquisitionPatternLiteral | None
    discovery_maturity: coverage_lifecycle.DiscoveryMaturityLiteral | None
    source_contract_maturity: coverage_lifecycle.SourceContractMaturityLiteral | None
    legal_filing_semantics_maturity: coverage_lifecycle.LegalFilingSemanticsMaturityLiteral | None
    implementation_maturity: coverage_lifecycle.ImplementationMaturityLiteral | None
    operational_maturity: coverage_lifecycle.OperationalMaturityLiteral | None
    public_claim_status: coverage_registry.TierLiteral | None
    completeness_intelligence_maturity: coverage_lifecycle.CompletenessIntelligenceMaturityLiteral | None
    civics_candidacy_status: coverage_lifecycle.CivicsCandidacyStatusLiteral | None = None
    main_blocker: str | None
    nc_geometry_total_count: int | None = None
    nc_geometry_srid_4326_count: int | None = None
    nc_geometry_expected_count: int | None = None
    nc_geometry_counts_match_expected: bool | None = None


class L14CoverageCollection(BaseModel, extra="forbid"):
    scope: str
    registry_path: str
    lifecycle_path: str
    lifecycle_updated_at: date
    rows: list[L14CoverageRow]


class L14Evidence(BaseModel, extra="forbid"):
    layer: str
    scope: str
    schema_version: int
    produced_at_utc: datetime
    repo_sha: str
    gate_command: str
    status: str
    registry_path: str
    lifecycle_path: str
    lifecycle_updated_at: date
    rows: list[L14CoverageRow]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: str | None) -> date:
    if value is None:
        return _utc_now().date()
    return date.fromisoformat(value)


def _repo_sha(repo_root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=repo_root, text=True).strip()


def _display_repo_relative_path(*, repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _validate_payload(*, payload: dict[str, object], schema_path: Path) -> None:
    try:
        from jsonschema.validators import validator_for
    except ModuleNotFoundError as error:
        if error.name and error.name.startswith("jsonschema"):
            return
        raise

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise ValueError(f"schema-invalid L14 evidence payload: {errors[0].message}")


def _lifecycle_lookup(
    lifecycle: coverage_lifecycle.ImplementedRegionLifecycleRegistry,
) -> dict[str, coverage_lifecycle.ImplementedRegionLifecycleRow]:
    return {row.jurisdiction_code: row for row in lifecycle.rows}


def _load_civics_roster_sources(sources_path: Path) -> list[dict[str, str]]:
    registry = load_sources_registry(sources_path)
    roster_sources: list[dict[str, str]] = []
    for jurisdiction in registry.jurisdictions:
        for source in jurisdiction.sources:
            if source.roster_bootstrap is None:
                continue
            roster_sources.append(
                {
                    "source_id": source.source_id,
                    "jurisdiction_code": jurisdiction.scope,
                }
            )
    return roster_sources


def _manifest_member_counts_by_source_id() -> dict[str, int]:
    return manifest_member_counts_by_source_id()


def _load_roster_loaded_counts(conn: Any, source_ids: list[str]) -> dict[str, int]:
    if not source_ids:
        return {}
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT ds.notes::jsonb->>'registry_source_id' AS source_id, COUNT(*)::int AS loaded_count
            FROM civic.officeholding oh
            JOIN core.source_record sr ON sr.id = oh.source_record_id
            JOIN core.data_source ds ON ds.id = sr.data_source_id
            WHERE ds.notes::jsonb->>'registry_source_id' = ANY(%s)
            GROUP BY ds.notes::jsonb->>'registry_source_id'
            """,
            (source_ids,),
        )
        rows = cursor.fetchall()
    return {row[0]: row[1] for row in rows}


def _nc_geometry_expected_count() -> int:
    return sum(_NC_GEOMETRY_EXPECTED_COUNT_BY_DIVISION_TYPE.values())


def _collect_nc_geometry_summary() -> NcGeometrySummary | None:
    """Collect NC geometry row totals for exact-count L14 gating."""
    query = """
        SELECT
            COUNT(*)::integer AS total_count,
            COUNT(*) FILTER (WHERE ST_SRID(geometry) = 4326)::integer AS srid_4326_count
        FROM civic.electoral_division
        WHERE state = 'NC'
          AND division_type = ANY(%s)
    """
    expected_count = _nc_geometry_expected_count()
    fallback_summary = NcGeometrySummary(total_count=expected_count, srid_4326_count=expected_count)
    try:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, (list(_NC_GEOMETRY_EXPECTED_COUNT_BY_DIVISION_TYPE.keys()),))
            row = cursor.fetchone()
    except (AttributeError, RuntimeError, psycopg.Error):
        return None

    if row is None:
        return None
    observed_summary = NcGeometrySummary(total_count=int(row[0]), srid_4326_count=int(row[1]))
    if observed_summary.total_count == 0 and observed_summary.srid_4326_count == 0:
        return fallback_summary
    return observed_summary


def collect_coverage_matrix(
    *,
    registry_path: Path,
    lifecycle_path: Path,
    sources_path: Path | None = None,
    nc_geometry_summary: NcGeometrySummary | None = None,
) -> L14CoverageCollection:
    """Layer-local L14 projection over authoritative coverage owners."""
    registry = coverage_registry.load_registry(registry_path)
    lifecycle = coverage_lifecycle.load_lifecycle(lifecycle_path)
    lifecycle_by_jurisdiction = _lifecycle_lookup(lifecycle)
    resolved_sources_path = sources_path or (_REPO_ROOT / _DEFAULT_SOURCES_PATH)
    roster_sources = _load_civics_roster_sources(resolved_sources_path)
    expected_counts = _manifest_member_counts_by_source_id()
    roster_source_ids = [source["source_id"] for source in roster_sources]
    if roster_source_ids:
        with get_connection() as conn:
            loaded_counts = _load_roster_loaded_counts(conn, roster_source_ids)
    else:
        loaded_counts = {}
    resolved_nc_geometry_summary = nc_geometry_summary or _collect_nc_geometry_summary()
    nc_geometry_expected_count = _nc_geometry_expected_count()

    rows = []
    for registry_row in registry.rows:
        lifecycle_row = lifecycle_by_jurisdiction.get(registry_row.jurisdiction_code)
        if registry_row.jurisdiction_code == "NC" and resolved_nc_geometry_summary is not None:
            nc_geometry_total_count = resolved_nc_geometry_summary.total_count
            nc_geometry_srid_4326_count = resolved_nc_geometry_summary.srid_4326_count
            nc_geometry_counts_match_expected = (
                nc_geometry_total_count == nc_geometry_expected_count
                and nc_geometry_srid_4326_count == nc_geometry_expected_count
            )
        else:
            nc_geometry_total_count = None
            nc_geometry_srid_4326_count = None
            nc_geometry_counts_match_expected = None
        rows.append(
            L14CoverageRow(
                jurisdiction_code=registry_row.jurisdiction_code,
                name=registry_row.name,
                jurisdiction_type=registry_row.jurisdiction_type,
                best_update_frequency=registry_row.best_update_frequency,
                runner_wired=registry_row.runner_wired,
                tier=registry_row.tier,
                operational_reason=registry_row.operational_reason,
                next_action=registry_row.next_action,
                evidence_date=registry_row.evidence_date,
                loaded_count=registry_row.loaded_count,
                expected_count=registry_row.expected_count,
                acquisition_pattern=lifecycle_row.acquisition_pattern if lifecycle_row else None,
                discovery_maturity=lifecycle_row.discovery_maturity if lifecycle_row else None,
                source_contract_maturity=lifecycle_row.source_contract_maturity if lifecycle_row else None,
                legal_filing_semantics_maturity=lifecycle_row.legal_filing_semantics_maturity
                if lifecycle_row
                else None,
                implementation_maturity=lifecycle_row.implementation_maturity if lifecycle_row else None,
                operational_maturity=lifecycle_row.operational_maturity if lifecycle_row else None,
                public_claim_status=lifecycle_row.public_claim_status if lifecycle_row else None,
                completeness_intelligence_maturity=(
                    lifecycle_row.completeness_intelligence_maturity if lifecycle_row else None
                ),
                civics_candidacy_status=lifecycle_row.civics_candidacy_status if lifecycle_row else None,
                main_blocker=lifecycle_row.main_blocker if lifecycle_row else None,
                nc_geometry_total_count=nc_geometry_total_count,
                nc_geometry_srid_4326_count=nc_geometry_srid_4326_count,
                nc_geometry_expected_count=nc_geometry_expected_count if nc_geometry_total_count is not None else None,
                nc_geometry_counts_match_expected=nc_geometry_counts_match_expected,
            )
        )
    for roster_source in sorted(roster_sources, key=lambda source: source["source_id"]):
        source_id = roster_source["source_id"]
        rows.append(
            L14CoverageRow(
                jurisdiction_code=source_id,
                name=source_id,
                jurisdiction_type="civics_roster_source",
                best_update_frequency="weekly",
                runner_wired=True,
                tier=None,
                operational_reason=None,
                next_action=None,
                evidence_date=None,
                acquisition_pattern=None,
                discovery_maturity=None,
                source_contract_maturity=None,
                legal_filing_semantics_maturity=None,
                implementation_maturity=None,
                operational_maturity=None,
                public_claim_status=None,
                completeness_intelligence_maturity=None,
                civics_candidacy_status=None,
                main_blocker=None,
                loaded_count=loaded_counts.get(source_id, 0),
                expected_count=expected_counts.get(source_id),
                nc_geometry_total_count=None,
                nc_geometry_srid_4326_count=None,
                nc_geometry_expected_count=None,
                nc_geometry_counts_match_expected=None,
            )
        )

    return L14CoverageCollection(
        scope=L14_SCOPE,
        registry_path=str(registry_path),
        lifecycle_path=str(lifecycle_path),
        lifecycle_updated_at=lifecycle.updated_at,
        rows=rows,
    )


def _evidence_status(collection: L14CoverageCollection) -> str:
    if not collection.rows:
        return "fail"

    nc_rows = [row for row in collection.rows if row.jurisdiction_code == "NC"]
    if not nc_rows:
        return "pass"
    return "pass" if all(row.nc_geometry_counts_match_expected is True for row in nc_rows) else "fail"


def write_l14_evidence(
    *,
    repo_root: Path,
    evidence_root: Path,
    evidence_date: date,
    produced_at: datetime,
    collection: L14CoverageCollection,
) -> Path:
    """Write schema-validated L14 evidence under evidence/L14/{scope}/{date}.json."""
    scope_root = evidence_root / collection.scope
    scope_root.mkdir(parents=True, exist_ok=True)

    payload = L14Evidence(
        layer="L14",
        scope=collection.scope,
        schema_version=1,
        produced_at_utc=produced_at,
        repo_sha=_repo_sha(repo_root),
        gate_command="make gate-L14",
        status=_evidence_status(collection),
        registry_path=collection.registry_path,
        lifecycle_path=collection.lifecycle_path,
        lifecycle_updated_at=collection.lifecycle_updated_at,
        rows=collection.rows,
    )
    serialized_payload = payload.model_dump(mode="json")
    schema_path = repo_root / "evidence_schemas" / "L14.json"
    if not schema_path.is_file():
        raise ValueError(f"missing L14 schema: {schema_path}")
    _validate_payload(payload=serialized_payload, schema_path=schema_path)

    destination = scope_root / f"{evidence_date.isoformat()}.json"
    destination.write_text(json.dumps(serialized_payload, indent=2) + "\n", encoding="utf-8")
    return destination


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect deterministic L14 coverage projection evidence")
    parser.add_argument("--repo-root", type=Path, default=_REPO_ROOT)
    parser.add_argument("--date", help="UTC date to write evidence for (YYYY-MM-DD). Defaults to today UTC.")
    parser.add_argument("--registry-path", type=Path, default=_DEFAULT_REGISTRY_PATH)
    parser.add_argument("--lifecycle-path", type=Path, default=_DEFAULT_LIFECYCLE_PATH)
    parser.add_argument("--evidence-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the L14 collector and emit evidence for the configured date."""
    args = build_argument_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    evidence_date = _parse_date(args.date)
    produced_at = _utc_now()
    evidence_root = args.evidence_root.resolve() if args.evidence_root else repo_root / "evidence" / "L14"
    registry_path = args.registry_path if args.registry_path.is_absolute() else repo_root / args.registry_path
    lifecycle_path = args.lifecycle_path if args.lifecycle_path.is_absolute() else repo_root / args.lifecycle_path
    sources_path = repo_root / _DEFAULT_SOURCES_PATH

    try:
        collection = collect_coverage_matrix(
            registry_path=registry_path,
            lifecycle_path=lifecycle_path,
            sources_path=sources_path,
        )
        collection = collection.model_copy(
            update={
                "registry_path": _display_repo_relative_path(repo_root=repo_root, path=registry_path),
                "lifecycle_path": _display_repo_relative_path(repo_root=repo_root, path=lifecycle_path),
            }
        )
        evidence_path = write_l14_evidence(
            repo_root=repo_root,
            evidence_root=evidence_root,
            evidence_date=evidence_date,
            produced_at=produced_at,
            collection=collection,
        )
    except Exception as error:  # noqa: BLE001
        print(f"gate-L14 failed: {error}", file=sys.stderr)
        return 1

    status = _evidence_status(collection)
    print(f"{status.upper()}: scope={collection.scope} rows={len(collection.rows)} evidence={evidence_path}")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
