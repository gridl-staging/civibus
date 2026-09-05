"""Read-only ``region-status`` projection for one campaign-finance jurisdiction.

This module projects over ``registry.py``, ``lifecycle.py``, ``status/municipality.py``,
``core/refresh/job_builders.py::build_refresh_plan``, ``core/refresh/runner.py``, and
``core/keel_gate_l3.py``. It owns no fact: callers supply the typed registries, matched
``RefreshJob`` values, and refresh-clock lookup callables.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import date, datetime, timezone
from functools import partial
import os
from pathlib import Path
import sys
from typing import Annotated, Any, Literal, Union

import psycopg
import yaml
from pydantic import Field

from core.db import get_connection
from core.keel_gate_l3 import DEFAULT_SOURCES_REGISTRY_PATH, SourcesRegistry, load_sources_registry
from core.refresh.job_builders import build_refresh_plan
from core.refresh.runner import (
    RefreshJob,
    cadence_last_pull_owner,
    select_latest_completed_run,
    select_latest_pull_at,
    should_run_job,
)
from domains.campaign_finance.coverage.lifecycle import (
    AUTHORITY_PROMOTION_RECEIPT_ENV,
    AuthorityPromotionReceipt,
    AuthorityPromotionEvidence,
    AuthorityRecurrenceEvidence,
    AuthoritySourceEvidence,
    DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH,
    ImplementedRegionLifecycleRegistry,
    ImplementedRegionLifecycleRow,
    assess_authority_promotion_receipt,
    assess_authority_promotion,
    load_authority_promotion_receipt,
    load_lifecycle,
)
from domains.campaign_finance.coverage.registry import (
    DEFAULT_REGISTRY_PATH,
    CoverageRegistry,
    CoverageRegistryRow,
    FilingAuthorityReference,
    load_registry,
)
from domains.campaign_finance.coverage.render_summary import (
    config_identity_for_coverage_identity,
)
from domains.campaign_finance.coverage.status.models import (
    NOT_APPLICABLE,
    FieldProvenance,
    JsonSerializableValue,
    ProjectedField,
    ProjectionReport,
    Refusal,
    StatusProjectionModel,
    UnknownFact,
    refuse,
)
from domains.campaign_finance.coverage.status.municipality import (
    LIFECYCLE_OWNER,
    build_region_owner_index,
    resolve_region_owners_from_index,
)
from domains.campaign_finance.coverage.status.registry_fields import (
    municipality_disposition_value,
    project_evidence_dated_field,
    project_municipality_audit_claim,
    registry_provenance,
)
from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionTypeLiteral,
    operational_scope_for_config_identity,
)

RUNNER_PLAN_OWNER = "core/refresh/job_builders.py::build_refresh_plan"
REFRESH_RUN_OWNER = "core.refresh_run"
REFRESH_RUN_READ_PATH = "core/refresh/runner.py::select_latest_completed_run"
RUNNER_READ_PATH = "core/refresh/runner.py::RefreshJob"
L3_OWNER = "sources.yaml"
L3_READ_PATH = "core/keel_gate_l3.py::load_sources_registry"
EXECUTION_ORIGIN_UNKNOWN_REASON = "no canonical owner records execution origin"
REFRESH_CLOCKS_UNAVAILABLE_REASON = "refresh clock database unavailable"
CADENCE_CLOCK_OWNER = "core/refresh/runner.py::cadence_last_pull_owner"

_LIFECYCLE_ROW_READ_PATH = "lifecycle.py::ImplementedRegionLifecycleRow"
_DERIVED_READ_PATH = "status/region_status.py"
_AUTHORITY_RELATION_READ_PATH = "registry.py::CoverageRegistryRow.authority_relation"
_AUTHORITY_HEALTH_OWNER = "authority-promotion-evidence"
_AUTHORITY_HEALTH_READ_PATH = "lifecycle.py::assess_authority_promotion"
_AUTHORITY_PROMOTION_RECEIPT_OWNER = "authority-promotion-receipt"
_AUTHORITY_PROMOTION_RECEIPT_READ_PATH = "lifecycle.py::load_authority_promotion_receipt"

RegionProjectionOutcome = Annotated[Union[ProjectedField, UnknownFact], Field(discriminator="status")]
LatestCompletedRun = dict[str, Any] | UnknownFact | None
CadenceLastPull = datetime | UnknownFact | None


class RegionStatusProjectionInputs(StatusProjectionModel):
    """Caller-supplied canonical owners and optional refresh-clock readers."""

    coverage_registry: CoverageRegistry
    lifecycle_registry: ImplementedRegionLifecycleRegistry
    sources_registry: SourcesRegistry | None
    refresh_jobs: list[RefreshJob]
    latest_completed_run_lookup: Callable[[RefreshJob], LatestCompletedRun]
    cadence_last_pull_lookup: Callable[[RefreshJob], CadenceLastPull]
    promotion_receipt: AuthorityPromotionReceipt | None = None


class RegionStatusReport(ProjectionReport):
    """One successfully projected ``region-status`` report."""

    status: Literal["region"] = "region"
    jurisdiction_code: ProjectedField
    name: ProjectedField
    municipality_disposition: ProjectedField
    acquisition_pattern: ProjectedField
    source_maturity: ProjectedField
    l3_source_state: list[RegionProjectionOutcome]
    public_claim: ProjectedField
    authority_relation: ProjectedField
    authority_health: list[ProjectedField]
    municipality_audit_claim: ProjectedField
    runner_wired: ProjectedField
    latest_operational_proof: list[RegionProjectionOutcome]
    cadence_clock_owner: list[ProjectedField]
    cadence_last_pull_at: list[RegionProjectionOutcome]
    proof_age: list[RegionProjectionOutcome]
    execution_origin: UnknownFact
    main_blocker: ProjectedField
    next_action: ProjectedField


def match_refresh_jobs_for_region(
    jurisdiction_type: JurisdictionTypeLiteral,
    jurisdiction_code: str,
    refresh_jobs: list[RefreshJob],
) -> list[RefreshJob]:
    """Forward-translate a typed coverage identity to exact runner-job scope."""

    return [job for job in refresh_jobs if _job_matches_region(jurisdiction_type, jurisdiction_code, job)]


def build_region_status_report(
    *,
    jurisdiction_code: str,
    inputs: RegionStatusProjectionInputs,
    calculated_at: datetime,
) -> RegionStatusReport | Refusal:
    """Project one region from caller-supplied owners and clock selectors."""

    envelope = ProjectionReport(calculated_at=calculated_at)
    index = build_region_owner_index(inputs.coverage_registry, inputs.lifecycle_registry)
    resolution = resolve_region_owners_from_index(jurisdiction_code, index=index)
    if isinstance(resolution, Refusal):
        return resolution

    refresh_plan_jurisdiction_code = (
        resolution.status_registry_row.jurisdiction_code
        if resolution.branch == "covered_by_parent"
        else jurisdiction_code
    )
    refresh_plan_jurisdiction_type = resolution.status_registry_row.jurisdiction_type
    matched_jobs = match_refresh_jobs_for_region(
        refresh_plan_jurisdiction_type,
        refresh_plan_jurisdiction_code,
        inputs.refresh_jobs,
    )
    runner_mismatch = _runner_wired_mismatch(resolution.identity_registry_row, matched_jobs)
    if runner_mismatch is not None:
        return runner_mismatch

    identity_row = resolution.identity_registry_row
    status_row = resolution.status_registry_row
    lifecycle_row = resolution.status_lifecycle_row
    latest_run_by_key = {job.key: inputs.latest_completed_run_lookup(job) for job in matched_jobs}
    cadence_last_pull_by_key = {job.key: inputs.cadence_last_pull_lookup(job) for job in matched_jobs}
    if inputs.promotion_receipt is not None and (
        inputs.promotion_receipt.jurisdiction_code != identity_row.jurisdiction_code
        or inputs.promotion_receipt.geographic_subject.kind != identity_row.jurisdiction_type
    ):
        return refuse(
            scope=jurisdiction_code,
            reason="authority promotion receipt belongs to a different typed geographic subject",
            canonical_owner=_AUTHORITY_PROMOTION_RECEIPT_OWNER,
        )

    return RegionStatusReport(
        calculated_at=envelope.calculated_at,
        jurisdiction_code=envelope.project_field(
            value=identity_row.jurisdiction_code,
            provenance=registry_provenance("direct"),
            source_observed_at=NOT_APPLICABLE,
        ),
        name=envelope.project_field(
            value=identity_row.name,
            provenance=registry_provenance("direct"),
            source_observed_at=NOT_APPLICABLE,
        ),
        municipality_disposition=envelope.project_field(
            value=municipality_disposition_value(identity_row),
            provenance=registry_provenance("direct"),
            source_observed_at=NOT_APPLICABLE,
        ),
        acquisition_pattern=_lifecycle_field(
            envelope,
            lifecycle_row.acquisition_pattern,
            inputs.lifecycle_registry.updated_at,
            origin=resolution.status_origin,
        ),
        source_maturity=_lifecycle_field(
            envelope,
            _source_maturity_value(lifecycle_row),
            inputs.lifecycle_registry.updated_at,
            origin=resolution.status_origin,
        ),
        l3_source_state=_project_l3_source_state(
            envelope,
            identity_row.jurisdiction_type,
            jurisdiction_code,
            inputs.sources_registry,
        ),
        public_claim=project_evidence_dated_field(
            envelope,
            value={"tier": status_row.tier, "evidence_summary": status_row.evidence_summary},
            origin=resolution.status_origin,
            evidence_date=status_row.evidence_date,
        ),
        authority_relation=_project_authority_relation(envelope, identity_row, inputs.promotion_receipt),
        authority_health=_project_authority_health(
            envelope,
            identity_row,
            matched_jobs,
            latest_run_by_key,
            cadence_last_pull_by_key,
            inputs.promotion_receipt,
        ),
        municipality_audit_claim=project_municipality_audit_claim(envelope, identity_row),
        runner_wired=envelope.project_field(
            value=bool(matched_jobs),
            provenance=FieldProvenance(owner=RUNNER_PLAN_OWNER, read_path=RUNNER_READ_PATH, origin="direct"),
            source_observed_at=NOT_APPLICABLE,
        ),
        latest_operational_proof=[
            _project_latest_operational_proof(envelope, job, latest_run_by_key[job.key]) for job in matched_jobs
        ],
        cadence_clock_owner=[_project_cadence_clock_owner(envelope, job) for job in matched_jobs],
        cadence_last_pull_at=[
            _project_cadence_last_pull_at(envelope, job, cadence_last_pull_by_key[job.key]) for job in matched_jobs
        ],
        proof_age=[_project_proof_age(envelope, job, latest_run_by_key[job.key]) for job in matched_jobs],
        execution_origin=UnknownFact(reason=EXECUTION_ORIGIN_UNKNOWN_REASON),
        main_blocker=_lifecycle_field(
            envelope,
            lifecycle_row.main_blocker,
            inputs.lifecycle_registry.updated_at,
            origin=resolution.status_origin,
        ),
        next_action=envelope.project_field(
            value=identity_row.next_action,
            provenance=registry_provenance("direct"),
            source_observed_at=identity_row.evidence_date,
        ),
    )


def _project_authority_relation(
    report: ProjectionReport,
    row: CoverageRegistryRow,
    receipt: AuthorityPromotionReceipt | None,
) -> ProjectedField:
    if receipt is not None:
        return report.project_field(
            value={
                "relation": receipt.authority_relation,
                "authority": receipt.filing_authority.model_dump(mode="json"),
            },
            provenance=FieldProvenance(
                owner=_AUTHORITY_PROMOTION_RECEIPT_OWNER,
                read_path=_AUTHORITY_PROMOTION_RECEIPT_READ_PATH,
                origin="direct",
            ),
            source_observed_at=receipt.issued_at,
        )
    return report.project_field(
        value=row.authority_relation.model_dump(mode="json"),
        provenance=FieldProvenance(
            owner="coverage-registry",
            read_path=_AUTHORITY_RELATION_READ_PATH,
            origin="direct",
        ),
        source_observed_at=row.evidence_date,
    )


def _relation_authorities(
    row: CoverageRegistryRow,
    receipt: AuthorityPromotionReceipt | None,
) -> list[FilingAuthorityReference]:
    if receipt is not None:
        return [receipt.filing_authority]
    relation = row.authority_relation
    if relation.relation in {"independent", "inherited"}:
        return [relation.authority]
    if relation.relation == "partitioned_overlapping":
        return relation.authorities
    return relation.candidate_authorities


def _aggregation_disposition(row: CoverageRegistryRow) -> str:
    relation = row.authority_relation
    if relation.relation == "partitioned_overlapping":
        return relation.deduplication.disposition
    if relation.relation == "unresolved":
        return relation.aggregation_disposition
    return "not_applicable"


def _source_identity(job: RefreshJob, source_name: str) -> str:
    return f"{job.jurisdiction}:{source_name}"


def _freshness_evidence(
    *,
    job: RefreshJob,
    source_name: str,
    latest_run: LatestCompletedRun,
    cadence_last_pull: CadenceLastPull,
    calculated_at: datetime,
) -> AuthoritySourceEvidence:
    observed_at = cadence_last_pull if isinstance(cadence_last_pull, datetime) else None
    if not isinstance(latest_run, dict) or observed_at is None:
        freshness_status = "unknown"
    elif latest_run.get("pull_status") != "success":
        freshness_status = "degraded"
    elif should_run_job(job, last_pull_at=observed_at, now=calculated_at):
        freshness_status = "stale"
    else:
        freshness_status = "fresh"
    return AuthoritySourceEvidence(
        source_identity=_source_identity(job, source_name),
        freshness_status=freshness_status,
        observed_at=observed_at,
    )


def _recurrence_evidence(
    *,
    job: RefreshJob,
    source_name: str,
    latest_run: LatestCompletedRun,
) -> AuthorityRecurrenceEvidence | None:
    if not isinstance(latest_run, dict):
        return None
    pull_status = latest_run.get("pull_status")
    if pull_status not in {"crashed", "empty", "degraded", "failed", "running", "success"}:
        return None
    execution_origin = latest_run.get("execution_origin")
    if execution_origin not in {"manual", "scheduled"}:
        execution_origin = "unknown"
    completed_at = latest_run.get("completed_at")
    return AuthorityRecurrenceEvidence(
        source_identity=_source_identity(job, source_name),
        pull_status=pull_status,
        execution_origin=execution_origin,
        completed_at=completed_at if isinstance(completed_at, datetime) else None,
    )


def _project_authority_health(
    report: ProjectionReport,
    row: CoverageRegistryRow,
    matched_jobs: list[RefreshJob],
    latest_run_by_key: dict[str, LatestCompletedRun],
    cadence_last_pull_by_key: dict[str, CadenceLastPull],
    promotion_receipt: AuthorityPromotionReceipt | None,
) -> list[ProjectedField]:
    authorities = _relation_authorities(row, promotion_receipt)
    source_jobs = [(job, source_name) for job in matched_jobs for source_name in job.data_source_names]
    values: list[ProjectedField] = []
    for authority in authorities:
        authority_identity = f"{authority.kind}/{authority.code}"
        # A multi-authority relation needs an owner-supplied authority-to-source
        # partition. Runner namespace membership alone cannot choose one.
        exact_source_jobs = source_jobs if len(authorities) == 1 else []
        expected_sources = [_source_identity(job, source_name) for job, source_name in exact_source_jobs]
        freshness = [
            _freshness_evidence(
                job=job,
                source_name=source_name,
                latest_run=latest_run_by_key[job.key],
                cadence_last_pull=cadence_last_pull_by_key[job.key],
                calculated_at=report.calculated_at,
            )
            for job, source_name in exact_source_jobs
        ]
        recurrence = [
            evidence
            for job, source_name in exact_source_jobs
            if (
                evidence := _recurrence_evidence(
                    job=job,
                    source_name=source_name,
                    latest_run=latest_run_by_key[job.key],
                )
            )
            is not None
        ]
        freshness_statuses = {evidence.freshness_status for evidence in freshness}
        freshness_status = (
            "degraded"
            if "degraded" in freshness_statuses
            else "stale"
            if "stale" in freshness_statuses
            else "unknown"
            if not freshness_statuses or "unknown" in freshness_statuses
            else "fresh"
        )
        recurrence_status = (
            "qualified"
            if expected_sources
            and len(recurrence) == len(expected_sources)
            and all(
                evidence.pull_status == "success"
                and evidence.execution_origin == "scheduled"
                and evidence.completed_at is not None
                for evidence in recurrence
            )
            else "degraded"
            if recurrence
            else "unknown"
        )
        if expected_sources:
            if promotion_receipt is not None:
                decision = assess_authority_promotion_receipt(
                    promotion_receipt,
                    jurisdiction_code=row.jurisdiction_code,
                    authority_identity=authority_identity,
                    expected_source_identities=expected_sources,
                    source_evidence=freshness,
                    recurrence_evidence=recurrence,
                )
                authority_relation = promotion_receipt.authority_relation
                aggregation_disposition = promotion_receipt.aggregation_disposition
            else:
                decision = assess_authority_promotion(
                    AuthorityPromotionEvidence(
                        authority_identity=authority_identity,
                        authority_relation=row.authority_relation.relation,
                        aggregation_disposition=_aggregation_disposition(row),
                        expected_source_identities=expected_sources,
                        source_evidence=freshness,
                        recurrence_evidence=recurrence,
                        provenance_source_identities=[],
                        keel_source_identities=[],
                        deployed_source_identities=[],
                        source_revision=None,
                        api_revision=None,
                        web_revision=None,
                    )
                )
                authority_relation = row.authority_relation.relation
                aggregation_disposition = _aggregation_disposition(row)
            revision_parity = decision.revision_parity
            promotion_eligible = decision.eligible
            refusal_reasons = decision.refusal_reasons
        else:
            authority_relation = row.authority_relation.relation
            aggregation_disposition = _aggregation_disposition(row)
            revision_parity = "unknown"
            promotion_eligible = False
            refusal_reasons = ["No exact source identities are assigned to this filing authority."]
            if row.authority_relation.relation == "unresolved":
                refusal_reasons.append("The filing authority relation is unresolved.")
            if row.authority_relation.relation == "partitioned_overlapping" and _aggregation_disposition(row) in {
                "refuse_combination",
                "refuse",
            }:
                refusal_reasons.append("The authority overlap disposition refuses combined promotion.")
            refusal_reasons.append("Serving source/API/web revision parity is unknown.")
        observed_times = [
            value
            for value in (
                *[evidence.observed_at for evidence in freshness],
                *[evidence.completed_at for evidence in recurrence],
            )
            if value is not None
        ]
        values.append(
            report.project_field(
                value={
                    "authority_identity": authority_identity,
                    "authority_relation": authority_relation,
                    "aggregation_disposition": aggregation_disposition,
                    "expected_source_identities": expected_sources,
                    "freshness_status": freshness_status,
                    "degraded_source_identities": [
                        evidence.source_identity for evidence in freshness if evidence.freshness_status != "fresh"
                    ],
                    "recurrence_status": recurrence_status,
                    "recurrence_observed_at": max(
                        (evidence.completed_at for evidence in recurrence if evidence.completed_at is not None),
                        default=None,
                    ),
                    "source_revision": (
                        promotion_receipt.promotion_evidence.source_revision if promotion_receipt is not None else None
                    ),
                    "revision_parity": revision_parity,
                    "promotion_eligible": promotion_eligible,
                    "refusal_reasons": refusal_reasons,
                },
                provenance=FieldProvenance(
                    owner=_AUTHORITY_HEALTH_OWNER,
                    read_path=_AUTHORITY_HEALTH_READ_PATH,
                    origin="direct",
                ),
                source_observed_at=max(observed_times) if observed_times else None,
            )
        )
    return values


def _job_matches_region(
    jurisdiction_type: JurisdictionTypeLiteral,
    jurisdiction_code: str,
    job: RefreshJob,
) -> bool:
    if jurisdiction_type == "federal":
        return jurisdiction_code == "FEC" and job.jurisdiction.startswith("federal/")
    try:
        config_identity = config_identity_for_coverage_identity((jurisdiction_type, jurisdiction_code))
    except KeyError:
        return False
    return job.jurisdiction == operational_scope_for_config_identity(config_identity)


def _runner_wired_mismatch(row: CoverageRegistryRow, matched_jobs: list[RefreshJob]) -> Refusal | None:
    plan_match = bool(matched_jobs)
    if row.runner_wired == plan_match:
        return None
    return refuse(
        scope=row.jurisdiction_code,
        reason=(
            f"coverage-registry runner_wired={row.runner_wired} disagrees with RefreshJob plan "
            f"match={plan_match} for '{row.jurisdiction_code}'"
        ),
        canonical_owner=RUNNER_PLAN_OWNER,
    )


def _lifecycle_field(
    report: ProjectionReport,
    value: JsonSerializableValue,
    observed_at: date,
    *,
    origin: Literal["direct", "inherited"],
) -> ProjectedField:
    return report.project_field(
        value=value,
        provenance=FieldProvenance(owner=LIFECYCLE_OWNER, read_path=_LIFECYCLE_ROW_READ_PATH, origin=origin),
        source_observed_at=observed_at,
    )


def _source_maturity_value(lifecycle_row: ImplementedRegionLifecycleRow) -> dict[str, JsonSerializableValue]:
    return {
        "discovery_maturity": lifecycle_row.discovery_maturity,
        "source_contract_maturity": lifecycle_row.source_contract_maturity,
        "legal_filing_semantics_maturity": lifecycle_row.legal_filing_semantics_maturity,
        "implementation_maturity": lifecycle_row.implementation_maturity,
        "operational_maturity": lifecycle_row.operational_maturity,
        "completeness_intelligence_maturity": lifecycle_row.completeness_intelligence_maturity,
        "civics_candidacy_status": lifecycle_row.civics_candidacy_status,
    }


def _project_l3_source_state(
    report: ProjectionReport,
    jurisdiction_type: JurisdictionTypeLiteral,
    jurisdiction_code: str,
    sources_registry: SourcesRegistry | None,
) -> list[RegionProjectionOutcome]:
    if sources_registry is None:
        return [UnknownFact(reason="sources.yaml unavailable")]
    scope = _sources_scope_for_region(jurisdiction_type, jurisdiction_code)
    entry = next((candidate for candidate in sources_registry.jurisdictions if candidate.scope == scope), None)
    if entry is None:
        return [UnknownFact(reason=f"sources.yaml has no scope for {scope}")]
    if not entry.sources:
        return [UnknownFact(reason=f"sources.yaml scope {scope} has no sources")]
    return [
        report.project_field(
            value={"source_id": source.source_id, "current_state": source.current_state},
            provenance=FieldProvenance(owner=L3_OWNER, read_path=L3_READ_PATH, origin="direct"),
            source_observed_at=source.transitions[-1].recorded_on if source.transitions else None,
        )
        for source in entry.sources
    ]


def _sources_scope_for_region(
    jurisdiction_type: JurisdictionTypeLiteral,
    jurisdiction_code: str,
) -> str:
    if jurisdiction_code == "FEC":
        return "FEDERAL"
    try:
        return config_identity_for_coverage_identity((jurisdiction_type, jurisdiction_code))[1]
    except KeyError:
        return jurisdiction_code


def _job_scoped_unknown(job: RefreshJob, unknown: UnknownFact) -> UnknownFact:
    """Re-scope an opaque clock ``UnknownFact`` to its owning job.

    A clock lookup that cannot reach the database returns one generic ``UnknownFact`` for
    every job, so a multi-job region (e.g. PA with four jobs) would otherwise emit
    indistinguishable per-job entries. Prefixing ``job.key`` keeps each entry attributable
    while reusing the shared ``UnknownFact`` envelope rather than adding a second schema.
    """

    return UnknownFact(reason=f"{job.key}: {unknown.reason}")


def _project_latest_operational_proof(
    report: ProjectionReport,
    job: RefreshJob,
    latest_run: LatestCompletedRun,
) -> RegionProjectionOutcome:
    if isinstance(latest_run, UnknownFact):
        return _job_scoped_unknown(job, latest_run)
    if latest_run is None:
        return UnknownFact(reason=f"core.refresh_run has no completed attempt for {job.key}")
    completed_at = latest_run["completed_at"]
    return report.project_field(
        value={
            "job_key": job.key,
            "completed_at": completed_at,
            "pull_status": latest_run["pull_status"],
            "inserted_count": latest_run["inserted_count"],
            "error": latest_run["error"],
        },
        provenance=FieldProvenance(owner=REFRESH_RUN_OWNER, read_path=REFRESH_RUN_READ_PATH, origin="direct"),
        source_observed_at=completed_at,
    )


def _project_cadence_clock_owner(report: ProjectionReport, job: RefreshJob) -> ProjectedField:
    return report.project_field(
        value={"job_key": job.key, "cadence_clock_owner": cadence_last_pull_owner(job)},
        provenance=FieldProvenance(
            owner=CADENCE_CLOCK_OWNER,
            read_path=CADENCE_CLOCK_OWNER,
            origin="direct",
        ),
        source_observed_at=NOT_APPLICABLE,
    )


def _project_cadence_last_pull_at(
    report: ProjectionReport,
    job: RefreshJob,
    cadence_last_pull_at: CadenceLastPull,
) -> RegionProjectionOutcome:
    if isinstance(cadence_last_pull_at, UnknownFact):
        return _job_scoped_unknown(job, cadence_last_pull_at)
    if cadence_last_pull_at is None:
        return UnknownFact(reason=f"cadence clock returned no row for {job.key}")
    clock_owner = "core.refresh_run" if cadence_last_pull_owner(job) == "refresh_history" else "core.data_source"
    return report.project_field(
        value={"job_key": job.key, "cadence_last_pull_at": cadence_last_pull_at},
        provenance=FieldProvenance(
            owner=clock_owner,
            read_path="core/refresh/runner.py::select_latest_pull_at",
            origin="direct",
        ),
        source_observed_at=cadence_last_pull_at,
    )


def _project_proof_age(
    report: ProjectionReport,
    job: RefreshJob,
    latest_run: LatestCompletedRun,
) -> RegionProjectionOutcome:
    if isinstance(latest_run, UnknownFact):
        return _job_scoped_unknown(job, latest_run)
    if latest_run is None:
        return UnknownFact(reason=f"proof age unavailable without latest operational proof for {job.key}")
    completed_at = latest_run["completed_at"]
    proof_field = report.project_field(
        value=completed_at,
        provenance=FieldProvenance(owner="derived", read_path=_DERIVED_READ_PATH, origin="direct"),
        source_observed_at=completed_at,
    )
    return report.project_field(
        value={"job_key": job.key, "proof_age": proof_field.model_dump(mode="json")["age"]},
        provenance=FieldProvenance(owner="derived", read_path=_DERIVED_READ_PATH, origin="direct"),
        source_observed_at=completed_at,
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project the read-only region-status view as JSON")
    parser.add_argument("--region", required=True, help="Coverage-registry jurisdiction_code to project")
    parser.add_argument("--registry-path", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--lifecycle-path", type=Path, default=DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)
    parser.add_argument("--sources-path", type=Path, default=DEFAULT_SOURCES_REGISTRY_PATH)
    parser.add_argument(
        "--promotion-receipt-json",
        type=Path,
        default=os.environ.get(AUTHORITY_PROMOTION_RECEIPT_ENV),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        coverage_registry = load_registry(args.registry_path)
        lifecycle_registry = load_lifecycle(args.lifecycle_path)
        refresh_jobs = build_refresh_plan()
        promotion_receipt = (
            load_authority_promotion_receipt(args.promotion_receipt_json)
            if args.promotion_receipt_json is not None
            else None
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    try:
        sources_registry = load_sources_registry(args.sources_path)
    except (OSError, ValueError, yaml.YAMLError):
        sources_registry = None

    connection = _connect_for_clock_selectors()
    if connection is None:
        latest_completed_run_lookup = _unknown_refresh_clock
        cadence_last_pull_lookup = _unknown_refresh_clock
    else:
        latest_completed_run_lookup = partial(_safe_latest_completed_run, connection)
        cadence_last_pull_lookup = partial(_safe_cadence_last_pull_at, connection)
    report = build_region_status_report(
        jurisdiction_code=args.region,
        inputs=RegionStatusProjectionInputs(
            coverage_registry=coverage_registry,
            lifecycle_registry=lifecycle_registry,
            sources_registry=sources_registry,
            refresh_jobs=refresh_jobs,
            latest_completed_run_lookup=latest_completed_run_lookup,
            cadence_last_pull_lookup=cadence_last_pull_lookup,
            promotion_receipt=promotion_receipt,
        ),
        calculated_at=datetime.now(timezone.utc),
    )
    if connection is not None:
        connection.close()
    print(report.model_dump_json(indent=2))
    return 1 if isinstance(report, Refusal) else 0


def _connect_for_clock_selectors() -> psycopg.Connection | None:
    try:
        return get_connection()
    except (RuntimeError, psycopg.Error):
        return None


def _unknown_refresh_clock(job: RefreshJob) -> UnknownFact:
    del job
    return UnknownFact(reason=REFRESH_CLOCKS_UNAVAILABLE_REASON)


def _safe_latest_completed_run(connection: psycopg.Connection, job: RefreshJob) -> LatestCompletedRun:
    try:
        return select_latest_completed_run(connection, job)
    except psycopg.Error:
        return UnknownFact(reason=REFRESH_CLOCKS_UNAVAILABLE_REASON)


def _safe_cadence_last_pull_at(connection: psycopg.Connection, job: RefreshJob) -> CadenceLastPull:
    try:
        return select_latest_pull_at(connection, job)
    except psycopg.Error:
        return UnknownFact(reason=REFRESH_CLOCKS_UNAVAILABLE_REASON)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
