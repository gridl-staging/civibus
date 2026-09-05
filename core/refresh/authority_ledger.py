"""Fail-closed ledger acceptance for one authority-scoped execution plan.

The proof is an immutable read-only observation artifact.  It does not query or
mutate a database; operators create it from the exact plan window and validate it
locally before any later lifecycle decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from core.refresh import job_builders
from core.refresh.authority_execution_plan import (
    AuthorityExecutionPlan,
    AuthorityIdentity,
    ExecutionPlanMode,
    RefreshJobLike,
    select_execution_plan_jobs,
)
from core.refresh.authority_operations_profile import (
    AuthorityOperationsProfile,
    canonical_sha256,
    expected_image_plan_proof,
    load_authority_operations_profile,
    read_strict_json,
)
from core.refresh.runner import RunnerParameters


ResultStatus = Literal["success", "skipped", "crashed", "degraded", "empty", "failed"]
PullStatus = Literal["success", "crashed", "degraded", "empty", "failed"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunnerResultEvidence(_StrictModel):
    job_key: str
    status: ResultStatus
    metadata_updates: int = Field(ge=0)


class RefreshRunEvidence(_StrictModel):
    refresh_run_id: UUID
    job_key: str
    data_source_names: tuple[str, ...]
    execution_origin: Literal["scheduled", "operator_attended"]
    pull_status: PullStatus
    metadata_updates: int = Field(ge=0)
    started_at: AwareDatetime
    completed_at: AwareDatetime


class DataSourceEvidence(_StrictModel):
    domain: Literal["campaign_finance"]
    jurisdiction: str
    name: str
    baseline_last_pull_at: AwareDatetime | None
    post_last_pull_at: AwareDatetime
    post_last_pull_status: Literal["success"]


class AuthorityLedgerProof(_StrictModel):
    schema_version: Literal[1]
    authority: AuthorityIdentity
    execution_plan_id: str
    execution_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_mode: ExecutionPlanMode
    observed_after: AwareDatetime
    observed_plan_row_count: int = Field(ge=0)
    runner_results: tuple[RunnerResultEvidence, ...]
    refresh_runs: tuple[RefreshRunEvidence, ...]
    data_sources: tuple[DataSourceEvidence, ...]


class ScheduledStartEvent(_StrictModel):
    source: Literal["scheduler", "host"]
    machine_id: str
    occurred_at: AwareDatetime


class ScheduledTerminalEvent(_StrictModel):
    state: Literal["stopped"]
    exit_code: Literal[0]
    machine_id: str
    occurred_at: AwareDatetime


class DatabaseIdentity(_StrictModel):
    host: str
    port: int = Field(ge=1, le=65535)
    name: str


class RefreshQuiescence(_StrictModel):
    running_refresh_rows: Literal[0]
    active_refresh_backends: Literal[0]
    long_idle_transactions: Literal[0]
    ungranted_locks: Literal[0]


class RawObservationEvidence(_StrictModel):
    kind: Literal["fly_app_status", "fly_machine_status", "database_observation"]
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: AwareDatetime


class RawFlyAppStatus(_StrictModel):
    """Exact normalized JSON emitted by the Fly app-status capture owner."""

    schema_version: Literal[1]
    captured_at: AwareDatetime
    app: str
    machine_ids: tuple[str, ...]


class RawFlyMachineEvent(_StrictModel):
    type: Literal["start", "stop"]
    occurred_at: AwareDatetime
    source: Literal["scheduler", "host"] | None = None
    state: Literal["stopped"] | None = None
    exit_code: Literal[0] | None = None

    @model_validator(mode="after")
    def _validate_event_shape(self) -> "RawFlyMachineEvent":
        if self.type == "start":
            if self.source is None or self.state is not None or self.exit_code is not None:
                raise ValueError("raw Fly start event shape mismatch")
        elif self.source is not None or self.state != "stopped" or self.exit_code != 0:
            raise ValueError("raw Fly terminal event shape mismatch")
        return self


class RawFlyMachineStatus(_StrictModel):
    """Exact normalized JSON emitted by the Fly Machine-status capture owner."""

    schema_version: Literal[1]
    captured_at: AwareDatetime
    app: str
    machine_id: str
    machine_name: str
    image: str
    machine_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    events: tuple[RawFlyMachineEvent, ...]


class RawDatabaseObservation(_StrictModel):
    """Exact read-only database observation emitted for one Machine window."""

    schema_version: Literal[1]
    captured_at: AwareDatetime
    machine_id: str
    authority: AuthorityIdentity
    execution_plan_id: str
    database: DatabaseIdentity
    runner_results: tuple[RunnerResultEvidence, ...]
    refresh_runs: tuple[RefreshRunEvidence, ...]
    data_sources: tuple[DataSourceEvidence, ...]
    quiescence: RefreshQuiescence


class RegionalScheduledObservation(_StrictModel):
    schema_version: Literal[1]
    observed_after: AwareDatetime
    observed_at: AwareDatetime
    profile_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_receipt_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_source_git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    candidate_tree_git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    qualified_image: str
    app: str
    machine_id: str
    machine_name: str
    machine_created_at: AwareDatetime
    start_event: ScheduledStartEvent
    terminal_event: ScheduledTerminalEvent
    database: DatabaseIdentity
    runner_results: tuple[RunnerResultEvidence, ...]
    refresh_runs: tuple[RefreshRunEvidence, ...]
    data_sources: tuple[DataSourceEvidence, ...]
    quiescence: RefreshQuiescence
    raw_evidence: tuple[RawObservationEvidence, ...]


class RegionalScheduledObservationReceipt(_StrictModel):
    schema_version: Literal[1]
    observed_after: AwareDatetime
    observed_at: AwareDatetime
    authority: AuthorityIdentity
    app: str
    machine_id: str
    machine_name: str
    machine_created_at: AwareDatetime
    profile_id: str
    profile_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_receipt_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_source_git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    candidate_tree_git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    qualified_image: str
    execution_plan_id: str
    execution_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    machine_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_ledger_proof_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_event: ScheduledStartEvent
    terminal_event: ScheduledTerminalEvent
    database: DatabaseIdentity
    quiescence: RefreshQuiescence
    data_sources: tuple[DataSourceEvidence, ...]
    raw_evidence: tuple[RawObservationEvidence, ...]


def _resolve_plan(owner: AuthorityExecutionPlan | AuthorityOperationsProfile) -> AuthorityExecutionPlan:
    return owner if isinstance(owner, AuthorityExecutionPlan) else owner.execution_plan


def validate_authority_ledger_proof(
    owner: AuthorityExecutionPlan | AuthorityOperationsProfile,
    proof: AuthorityLedgerProof,
    *,
    registry_jobs: Sequence[RefreshJobLike],
) -> None:
    """Require proof for the owner's exact plan, mode, ledger rows, and freshness.

    A scheduled proof must contain every selected result in plan order; cadence
    skips are explicit.  A canary additionally requires one successful row and
    exact data-source advancement.  Both modes reject failure-class results.
    """

    plan = _resolve_plan(owner)
    if proof.authority != plan.authority:
        raise ValueError("authority ledger proof authority mismatch")
    if proof.execution_plan_id != plan.plan_id:
        raise ValueError("authority ledger proof plan mismatch")
    if proof.execution_plan_sha256 != canonical_sha256(plan.model_dump(mode="json")):
        raise ValueError("authority ledger proof plan digest mismatch")

    # Selection validates the complete scheduled image registry even for canary.
    selected = select_execution_plan_jobs(registry_jobs, plan, mode=proof.execution_mode)
    mode_plan = plan.mode(proof.execution_mode)
    actual_result_keys = tuple(result.job_key for result in proof.runner_results)
    if actual_result_keys != mode_plan.job_keys:
        raise ValueError("authority ledger proof does not contain exact ordered job results")
    non_green = [result.job_key for result in proof.runner_results if result.status not in {"success", "skipped"}]
    if non_green:
        raise ValueError(f"authority ledger proof contains non-green result: {non_green!r}")

    results_by_key = {result.job_key: result for result in proof.runner_results}
    expected_run_keys = tuple(result.job_key for result in proof.runner_results if result.status != "skipped")
    actual_run_keys = tuple(row.job_key for row in proof.refresh_runs)
    if proof.observed_plan_row_count != len(proof.refresh_runs):
        raise ValueError("authority ledger proof observed plan row count mismatch")
    if actual_run_keys != expected_run_keys:
        raise ValueError("authority ledger rows do not exactly match executed plan results")
    refresh_run_ids = tuple(row.refresh_run_id for row in proof.refresh_runs)
    if len(refresh_run_ids) != len(set(refresh_run_ids)):
        raise ValueError("authority ledger proof contains duplicate or replayed refresh attempts")

    jobs_by_key = {job.key: job for job in selected}
    for row in proof.refresh_runs:
        result = results_by_key[row.job_key]
        job = jobs_by_key[row.job_key]
        if row.execution_origin != mode_plan.execution_origin:
            raise ValueError("authority ledger row execution-origin mismatch")
        if row.started_at < proof.observed_after or row.completed_at < row.started_at:
            raise ValueError("authority ledger row falls outside the observed execution window")
        if row.pull_status != result.status or row.metadata_updates != result.metadata_updates:
            raise ValueError("authority ledger rows do not match runner results")
        if row.data_source_names != tuple(job.data_source_names):
            raise ValueError("authority ledger row data-source names do not match registry ownership")

    if proof.execution_mode == "scheduled":
        if proof.data_sources:
            raise ValueError("scheduled ledger proof must not claim canary freshness evidence")
        return

    canary_job = selected[0]
    canary_result = proof.runner_results[0]
    if canary_result.status != "success" or canary_result.metadata_updates != len(canary_job.data_source_names):
        raise ValueError("canary ledger proof requires exact successful metadata advancement")
    expected_sources = tuple(canary_job.data_source_names)
    actual_sources = tuple(source.name for source in proof.data_sources)
    if actual_sources != expected_sources:
        raise ValueError("canary ledger proof does not contain exact registry data sources")
    for source in proof.data_sources:
        if source.jurisdiction != plan.authority.operational_scope:
            raise ValueError("canary ledger data-source ownership mismatch")
        if source.baseline_last_pull_at is not None and source.post_last_pull_at <= source.baseline_last_pull_at:
            raise ValueError("canary ledger data-source freshness did not advance")
        if source.post_last_pull_at < proof.observed_after:
            raise ValueError("canary ledger post-run freshness predates the execution window")


def _file_sha256(path: Path | str, *, label: str) -> str:
    resolved = Path(path)
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return hashlib.sha256(resolved.read_bytes()).hexdigest()


def _write_new_canonical_json(path: Path | str, payload: object, *, label: str) -> None:
    resolved = Path(path)
    if not resolved.parent.is_dir() or resolved.parent.is_symlink():
        raise ValueError(f"{label} parent must be an existing regular directory")
    data = (
        json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary = resolved.parent / f".{resolved.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600)
    except FileExistsError as error:
        raise ValueError(f"{label} temporary path collision") from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, resolved, follow_symlinks=False)
        except FileExistsError as error:
            raise ValueError(f"{label} path already exists") from error
        directory = os.open(resolved.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_regional_candidate_receipt(
    profile: AuthorityOperationsProfile,
    candidate_receipt_path: Path | str,
) -> tuple[str, str, str, str]:
    candidate_sha256 = _file_sha256(candidate_receipt_path, label="candidate receipt JSON")
    candidate = read_strict_json(candidate_receipt_path, label="candidate receipt JSON")
    if not isinstance(candidate, dict):
        raise ValueError("regional scheduled observation candidate receipt must be an object")
    expected_candidate_fields = {
        "canonical_receipt_git_sha",
        "canonical_source_git_sha",
        "canonical_tree_git_sha",
        "image_proof",
        "machine_config_sha256",
        "produced_image_tagged_digest",
        "profile_sha256",
        "qualification_kind",
        "schema_version",
        "source_git_sha",
        "source_tree_git_sha",
    }
    if set(candidate) != expected_candidate_fields:
        raise ValueError("regional scheduled observation candidate receipt shape mismatch")
    expected_identity = {
        "canonical_receipt_git_sha": profile.canonical_source.receipt_git_sha,
        "canonical_source_git_sha": profile.canonical_source.source_git_sha,
        "canonical_tree_git_sha": profile.canonical_source.tree_git_sha,
        "machine_config_sha256": profile.machine.config_sha256,
        "profile_sha256": canonical_sha256(profile.model_dump(mode="json")),
        "qualification_kind": "authority_refresh_image_candidate",
        "schema_version": 2,
    }
    if {key: candidate.get(key) for key in expected_identity} != expected_identity:
        raise ValueError("regional scheduled observation candidate receipt identity mismatch")
    if any(
        not isinstance(candidate.get(field), str) or re.fullmatch(r"[0-9a-f]{40}", candidate[field]) is None
        for field in ("source_git_sha", "source_tree_git_sha")
    ):
        raise ValueError("regional scheduled observation candidate receipt identity mismatch")
    candidate_image = candidate.get("produced_image_tagged_digest")
    image_pattern = rf"{re.escape(profile.image.repository)}:[A-Za-z0-9_][A-Za-z0-9_.-]{{0,127}}@sha256:[0-9a-f]{{64}}"
    if not isinstance(candidate_image, str) or re.fullmatch(image_pattern, candidate_image) is None:
        raise ValueError("regional scheduled observation candidate receipt identity mismatch")
    image_proof = candidate.get("image_proof")
    build_version = image_proof.get("build_version") if isinstance(image_proof, dict) else None
    if not isinstance(build_version, dict):
        raise ValueError("regional scheduled observation candidate receipt identity mismatch")
    if build_version.get("git_sha") != candidate.get("source_git_sha"):
        raise ValueError("regional scheduled observation candidate receipt identity mismatch")
    built_at = build_version.get("built_at")
    if not isinstance(built_at, str) or not built_at:
        raise ValueError("regional scheduled observation candidate receipt identity mismatch")
    if image_proof != expected_image_plan_proof(profile, build_version=build_version):
        raise ValueError("regional scheduled observation candidate receipt identity mismatch")
    return (
        candidate_sha256,
        candidate_image,
        candidate["source_git_sha"],
        candidate["source_tree_git_sha"],
    )


def _expected_regional_database(profile: AuthorityOperationsProfile) -> DatabaseIdentity:
    return DatabaseIdentity(
        host=profile.machine.config.env["POSTGRES_HOST"],
        port=int(profile.machine.config.env["POSTGRES_PORT"]),
        name=profile.machine.config.env["POSTGRES_DB"],
    )


def _load_regional_raw_observations(
    observation: RegionalScheduledObservation,
) -> tuple[RawFlyAppStatus, RawFlyMachineStatus, RawDatabaseObservation]:
    expected_raw_kinds = ("fly_app_status", "fly_machine_status", "database_observation")
    if tuple(item.kind for item in observation.raw_evidence) != expected_raw_kinds:
        raise ValueError("regional scheduled observation requires exact ordered raw Fly and database evidence")
    raw_paths = tuple(item.path for item in observation.raw_evidence)
    if len(set(raw_paths)) != len(raw_paths):
        raise ValueError("regional scheduled observation raw evidence paths must be distinct")
    raw_models: dict[str, type[_StrictModel]] = {
        "fly_app_status": RawFlyAppStatus,
        "fly_machine_status": RawFlyMachineStatus,
        "database_observation": RawDatabaseObservation,
    }
    raw_payloads: dict[str, _StrictModel] = {}
    for item in observation.raw_evidence:
        if not observation.terminal_event.occurred_at <= item.captured_at <= observation.observed_at:
            raise ValueError("regional scheduled observation raw evidence falls outside the terminal window")
        if _file_sha256(item.path, label=f"{item.kind} raw evidence") != item.sha256:
            raise ValueError(f"regional scheduled observation {item.kind} digest mismatch")
        try:
            raw_payload = raw_models[item.kind].model_validate(
                read_strict_json(item.path, label=f"{item.kind} raw evidence")
            )
        except (KeyError, ValueError) as error:
            raise ValueError(
                f"regional scheduled observation {item.kind} is not valid owner-format evidence"
            ) from error
        if raw_payload.captured_at != item.captured_at:  # type: ignore[attr-defined]
            raise ValueError(f"regional scheduled observation {item.kind} capture timestamp mismatch")
        raw_payloads[item.kind] = raw_payload
    raw_app = raw_payloads["fly_app_status"]
    raw_machine = raw_payloads["fly_machine_status"]
    raw_database = raw_payloads["database_observation"]
    assert isinstance(raw_app, RawFlyAppStatus)
    assert isinstance(raw_machine, RawFlyMachineStatus)
    assert isinstance(raw_database, RawDatabaseObservation)
    return raw_app, raw_machine, raw_database


def derive_regional_scheduled_observation(
    profile: AuthorityOperationsProfile,
    *,
    profile_path: Path | str,
    candidate_receipt_path: Path | str,
    raw_fly_app_status_path: Path | str,
    raw_fly_machine_status_path: Path | str,
    raw_database_observation_path: Path | str,
) -> RegionalScheduledObservation:
    """Derive the one scheduled-observation format from its three raw owners.

    The caller supplies no Machine event, ledger, freshness, quiescence, or
    observation identity fields.  Those fields are projected from the strict
    owner-format captures and are revalidated by
    :func:`build_regional_scheduled_observation` before publication.
    """

    raw_inputs: tuple[tuple[str, Path | str, type[_StrictModel]], ...] = (
        ("fly_app_status", raw_fly_app_status_path, RawFlyAppStatus),
        ("fly_machine_status", raw_fly_machine_status_path, RawFlyMachineStatus),
        ("database_observation", raw_database_observation_path, RawDatabaseObservation),
    )
    raw_models: dict[str, _StrictModel] = {}
    raw_evidence: list[RawObservationEvidence] = []
    for kind, path_text, model in raw_inputs:
        path = Path(path_text)
        if not path.is_absolute():
            raise ValueError(f"regional scheduled {kind} raw evidence path must be absolute")
        try:
            payload = model.model_validate(read_strict_json(path, label=f"{kind} raw evidence"))
        except ValueError as error:
            raise ValueError(f"regional scheduled {kind} is not valid owner-format evidence") from error
        captured_at = payload.captured_at  # type: ignore[attr-defined]
        raw_models[kind] = payload
        raw_evidence.append(
            RawObservationEvidence(
                kind=kind,
                path=str(path),
                sha256=_file_sha256(path, label=f"{kind} raw evidence"),
                captured_at=captured_at,
            )
        )

    raw_app = raw_models["fly_app_status"]
    raw_machine = raw_models["fly_machine_status"]
    raw_database = raw_models["database_observation"]
    assert isinstance(raw_app, RawFlyAppStatus)
    assert isinstance(raw_machine, RawFlyMachineStatus)
    assert isinstance(raw_database, RawDatabaseObservation)
    if len(raw_machine.events) != 2:
        raise ValueError("regional scheduled raw Fly Machine events are ambiguous or incomplete")
    raw_start, raw_terminal = raw_machine.events
    if raw_start.type != "start" or raw_terminal.type != "stop":
        raise ValueError("regional scheduled raw Fly Machine events are ambiguous or incomplete")
    assert raw_start.source is not None
    assert raw_terminal.state is not None
    assert raw_terminal.exit_code is not None
    if raw_app.machine_ids != (raw_machine.machine_id,):
        raise ValueError("regional scheduled raw app Machine identity mismatch")
    (
        _candidate_sha256,
        candidate_image,
        candidate_source_git_sha,
        candidate_tree_git_sha,
    ) = _validate_regional_candidate_receipt(profile, candidate_receipt_path)

    return RegionalScheduledObservation(
        schema_version=1,
        observed_after=raw_machine.created_at,
        observed_at=max(reference.captured_at for reference in raw_evidence),
        profile_file_sha256=_file_sha256(profile_path, label="profile JSON"),
        candidate_receipt_file_sha256=_file_sha256(
            candidate_receipt_path,
            label="candidate receipt JSON",
        ),
        candidate_source_git_sha=candidate_source_git_sha,
        candidate_tree_git_sha=candidate_tree_git_sha,
        qualified_image=candidate_image,
        app=raw_app.app,
        machine_id=raw_machine.machine_id,
        machine_name=raw_machine.machine_name,
        machine_created_at=raw_machine.created_at,
        start_event=ScheduledStartEvent(
            source=raw_start.source,
            machine_id=raw_machine.machine_id,
            occurred_at=raw_start.occurred_at,
        ),
        terminal_event=ScheduledTerminalEvent(
            state=raw_terminal.state,
            exit_code=raw_terminal.exit_code,
            machine_id=raw_machine.machine_id,
            occurred_at=raw_terminal.occurred_at,
        ),
        database=raw_database.database,
        runner_results=raw_database.runner_results,
        refresh_runs=raw_database.refresh_runs,
        data_sources=raw_database.data_sources,
        quiescence=raw_database.quiescence,
        raw_evidence=tuple(raw_evidence),
    )


def _validate_regional_raw_fly_evidence(
    profile: AuthorityOperationsProfile,
    observation: RegionalScheduledObservation,
    raw_app: RawFlyAppStatus,
    raw_machine: RawFlyMachineStatus,
    *,
    candidate_image: str,
) -> None:
    if (raw_app.app, raw_app.machine_ids) != (profile.app, (observation.machine_id,)):
        raise ValueError("regional scheduled observation raw app Machine identity mismatch")
    raw_machine_identity = (
        raw_machine.app,
        raw_machine.machine_id,
        raw_machine.machine_name,
        raw_machine.image,
        raw_machine.machine_config_sha256,
        raw_machine.created_at,
    )
    expected_machine_identity = (
        profile.app,
        observation.machine_id,
        profile.machine.name,
        candidate_image,
        profile.machine.config_sha256,
        observation.machine_created_at,
    )
    if raw_machine_identity != expected_machine_identity:
        raise ValueError("regional scheduled observation raw Fly Machine identity mismatch")
    if tuple(event.type for event in raw_machine.events) != ("start", "stop"):
        raise ValueError("regional scheduled observation raw Fly Machine events are ambiguous or incomplete")
    raw_start, raw_terminal = raw_machine.events
    derived_start = ScheduledStartEvent(
        source=raw_start.source,
        machine_id=raw_machine.machine_id,
        occurred_at=raw_start.occurred_at,
    )
    derived_terminal = ScheduledTerminalEvent(
        state=raw_terminal.state,
        exit_code=raw_terminal.exit_code,
        machine_id=raw_machine.machine_id,
        occurred_at=raw_terminal.occurred_at,
    )
    if (observation.start_event, observation.terminal_event) != (derived_start, derived_terminal):
        raise ValueError("regional scheduled observation self-asserted Machine events do not match raw evidence")


def _validate_regional_raw_database_evidence(
    profile: AuthorityOperationsProfile,
    observation: RegionalScheduledObservation,
    raw_database: RawDatabaseObservation,
    *,
    expected_database: DatabaseIdentity,
) -> None:
    raw_database_identity = (
        raw_database.machine_id,
        raw_database.authority,
        raw_database.execution_plan_id,
        raw_database.database,
    )
    expected_identity = (
        observation.machine_id,
        profile.authority,
        profile.execution_plan.plan_id,
        expected_database,
    )
    if raw_database_identity != expected_identity:
        if raw_database.machine_id != observation.machine_id:
            raise ValueError("regional scheduled observation raw database Machine identity mismatch")
        if (raw_database.authority, raw_database.execution_plan_id) != (
            profile.authority,
            profile.execution_plan.plan_id,
        ):
            raise ValueError("regional scheduled observation raw database authority or plan mismatch")
        raise ValueError("regional scheduled observation raw database identity mismatch")
    if (
        observation.database,
        observation.runner_results,
        observation.refresh_runs,
        observation.data_sources,
        observation.quiescence,
    ) != (
        raw_database.database,
        raw_database.runner_results,
        raw_database.refresh_runs,
        raw_database.data_sources,
        raw_database.quiescence,
    ):
        raise ValueError("regional scheduled observation self-asserted database evidence does not match raw evidence")


def build_regional_scheduled_observation(
    profile: AuthorityOperationsProfile,
    observation: RegionalScheduledObservation,
    *,
    profile_path: Path | str,
    candidate_receipt_path: Path | str,
    registry_jobs: Sequence[RefreshJobLike],
) -> tuple[AuthorityLedgerProof, RegionalScheduledObservationReceipt]:
    """Build one fail-closed regional scheduler proof and durable receipt.

    This function is deliberately offline.  Raw Fly and database captures are
    accepted only as exact, timestamped, hash-bound local files; no production
    command or mutation is performed here.
    """

    profile_sha256 = _file_sha256(profile_path, label="profile JSON")
    (
        candidate_sha256,
        candidate_image,
        candidate_source_git_sha,
        candidate_tree_git_sha,
    ) = _validate_regional_candidate_receipt(profile, candidate_receipt_path)
    if observation.profile_file_sha256 != profile_sha256:
        raise ValueError("regional scheduled observation profile digest mismatch")
    if observation.candidate_receipt_file_sha256 != candidate_sha256:
        raise ValueError("regional scheduled observation candidate receipt digest mismatch")
    if (
        observation.candidate_source_git_sha,
        observation.candidate_tree_git_sha,
        observation.qualified_image,
    ) != (candidate_source_git_sha, candidate_tree_git_sha, candidate_image):
        raise ValueError("regional scheduled observation candidate source, tree, or image mismatch")
    if observation.app != profile.app or observation.machine_name != profile.machine.name:
        raise ValueError("regional scheduled observation app or Machine identity mismatch")
    if not observation.machine_id:
        raise ValueError("regional scheduled observation Machine id must not be empty")
    if {
        observation.start_event.machine_id,
        observation.terminal_event.machine_id,
    } != {observation.machine_id}:
        raise ValueError("regional scheduled observation event Machine identity mismatch")
    if observation.machine_created_at != observation.observed_after:
        raise ValueError("regional scheduled observation window must be anchored to Machine creation")
    if not (
        observation.observed_after
        < observation.start_event.occurred_at
        < observation.terminal_event.occurred_at
        <= observation.observed_at
    ):
        raise ValueError("regional scheduled observation event window is invalid")

    expected_database = _expected_regional_database(profile)
    if observation.database != expected_database:
        raise ValueError("regional scheduled observation database identity mismatch")

    raw_app, raw_machine, raw_database = _load_regional_raw_observations(observation)
    if observation.observed_at != max(reference.captured_at for reference in observation.raw_evidence):
        raise ValueError("regional scheduled observation time is not derived from the latest raw capture")
    _validate_regional_raw_fly_evidence(
        profile,
        observation,
        raw_app,
        raw_machine,
        candidate_image=candidate_image,
    )
    _validate_regional_raw_database_evidence(
        profile,
        observation,
        raw_database,
        expected_database=expected_database,
    )

    proof = AuthorityLedgerProof(
        schema_version=1,
        authority=profile.authority,
        execution_plan_id=profile.execution_plan.plan_id,
        execution_plan_sha256=canonical_sha256(profile.execution_plan.model_dump(mode="json")),
        execution_mode="scheduled",
        observed_after=observation.observed_after,
        observed_plan_row_count=len(raw_database.refresh_runs),
        runner_results=raw_database.runner_results,
        refresh_runs=raw_database.refresh_runs,
        data_sources=(),
    )
    validate_authority_ledger_proof(profile, proof, registry_jobs=registry_jobs)
    if any(result.status != "success" for result in raw_database.runner_results):
        raise ValueError("regional scheduled observation requires every plan result to succeed")

    selected = select_execution_plan_jobs(registry_jobs, profile.execution_plan, mode="scheduled")
    expected_source_names = tuple(name for job in selected for name in job.data_source_names)
    if profile.authority.operational_scope == "state/WA" and (len(selected) != 4 or len(expected_source_names) != 4):
        raise ValueError("regional Washington scheduled observation requires exact four jobs and sources")
    actual_source_names = tuple(source.name for source in raw_database.data_sources)
    if actual_source_names != expected_source_names:
        raise ValueError("regional scheduled observation does not contain exact ordered registry sources")
    rows_by_job = {row.job_key: row for row in raw_database.refresh_runs}
    sources_by_name = {source.name: source for source in raw_database.data_sources}
    for job in selected:
        row = rows_by_job[job.key]
        result = next(result for result in raw_database.runner_results if result.job_key == job.key)
        if result.metadata_updates != len(job.data_source_names):
            raise ValueError("regional scheduled observation result metadata count mismatch")
        if not (
            observation.start_event.occurred_at
            <= row.started_at
            <= row.completed_at
            <= observation.terminal_event.occurred_at
        ):
            raise ValueError("regional scheduled observation refresh row falls outside Machine execution")
        for source_name in job.data_source_names:
            source = sources_by_name[source_name]
            if source.jurisdiction != profile.authority.operational_scope:
                raise ValueError("regional scheduled observation source ownership mismatch")
            if not row.completed_at <= source.post_last_pull_at <= raw_database.captured_at:
                raise ValueError("regional scheduled observation source clock is not current")
            if source.baseline_last_pull_at is not None and source.post_last_pull_at <= source.baseline_last_pull_at:
                raise ValueError("regional scheduled observation source freshness did not advance")

    receipt = RegionalScheduledObservationReceipt(
        schema_version=1,
        observed_after=observation.observed_after,
        observed_at=observation.observed_at,
        authority=profile.authority,
        app=profile.app,
        machine_id=observation.machine_id,
        machine_name=profile.machine.name,
        machine_created_at=observation.machine_created_at,
        profile_id=profile.profile_id,
        profile_file_sha256=profile_sha256,
        candidate_receipt_file_sha256=candidate_sha256,
        candidate_source_git_sha=candidate_source_git_sha,
        candidate_tree_git_sha=candidate_tree_git_sha,
        qualified_image=candidate_image,
        execution_plan_id=profile.execution_plan.plan_id,
        execution_plan_sha256=proof.execution_plan_sha256,
        machine_config_sha256=profile.machine.config_sha256,
        authority_ledger_proof_sha256=canonical_sha256(proof.model_dump(mode="json")),
        start_event=observation.start_event,
        terminal_event=observation.terminal_event,
        database=raw_database.database,
        quiescence=raw_database.quiescence,
        data_sources=raw_database.data_sources,
        raw_evidence=observation.raw_evidence,
    )
    return proof, receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an authority-scoped refresh ledger proof")
    parser.add_argument("--profile-json", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--proof-json")
    mode.add_argument("--observation-json")
    parser.add_argument("--raw-fly-app-status-json")
    parser.add_argument("--raw-fly-machine-status-json")
    parser.add_argument("--raw-database-observation-json")
    parser.add_argument("--observation-output-json")
    parser.add_argument("--candidate-receipt-json")
    parser.add_argument("--proof-output-json")
    parser.add_argument("--receipt-output-json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    profile = load_authority_operations_profile(args.profile_json)
    registry_jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=RunnerParameters(),
        job_key_prefixes=(),
    )
    raw_inputs = (
        args.raw_fly_app_status_json,
        args.raw_fly_machine_status_json,
        args.raw_database_observation_json,
    )
    if any(raw_inputs):
        if args.proof_json is not None or args.observation_json is not None:
            raise ValueError("raw scheduled observation production is exclusive with proof or observation input")
        required = (
            *raw_inputs,
            args.candidate_receipt_json,
            args.observation_output_json,
            args.proof_output_json,
            args.receipt_output_json,
        )
        if not all(required):
            raise ValueError(
                "raw scheduled observation production requires all three raw owners, candidate receipt, "
                "observation output, proof output, and receipt output"
            )
        output_paths = (
            (args.observation_output_json, "regional scheduled observation output"),
            (args.proof_output_json, "authority ledger proof output"),
            (args.receipt_output_json, "regional scheduled observation receipt output"),
        )
        if len({path for path, _label in output_paths}) != len(output_paths):
            raise ValueError("regional scheduled observation outputs must be distinct")
        for path, label in output_paths:
            if Path(path).exists() or Path(path).is_symlink():
                raise ValueError(f"{label} path already exists")
        observation = derive_regional_scheduled_observation(
            profile,
            profile_path=args.profile_json,
            candidate_receipt_path=args.candidate_receipt_json,
            raw_fly_app_status_path=args.raw_fly_app_status_json,
            raw_fly_machine_status_path=args.raw_fly_machine_status_json,
            raw_database_observation_path=args.raw_database_observation_json,
        )
        proof, receipt = build_regional_scheduled_observation(
            profile,
            observation,
            profile_path=args.profile_json,
            candidate_receipt_path=args.candidate_receipt_json,
            registry_jobs=registry_jobs,
        )
        _write_new_canonical_json(
            args.observation_output_json,
            observation.model_dump(mode="json"),
            label="regional scheduled observation output",
        )
        _write_new_canonical_json(
            args.proof_output_json,
            proof.model_dump(mode="json"),
            label="authority ledger proof output",
        )
        _write_new_canonical_json(
            args.receipt_output_json,
            receipt.model_dump(mode="json"),
            label="regional scheduled observation receipt output",
        )
        print(
            "PASS: derived regional scheduled observation "
            f"authority={profile.authority.operational_scope} "
            f"plan={profile.execution_plan.plan_id} "
            f"machine={observation.machine_id} results={len(proof.runner_results)}"
        )
        return 0
    if args.proof_json is not None:
        if any((args.candidate_receipt_json, args.proof_output_json, args.receipt_output_json)):
            raise ValueError("ledger proof validation does not accept observation output options")
        proof = AuthorityLedgerProof.model_validate(read_strict_json(args.proof_json, label="ledger proof JSON"))
        validate_authority_ledger_proof(profile, proof, registry_jobs=registry_jobs)
        print(
            "PASS: authority ledger proof "
            f"authority={profile.authority.operational_scope} "
            f"plan={profile.execution_plan.plan_id} mode={proof.execution_mode}"
        )
        return 0

    if args.observation_json is None:
        raise ValueError("one of proof JSON, observation JSON, or all three raw owners is required")

    if not all((args.candidate_receipt_json, args.proof_output_json, args.receipt_output_json)):
        raise ValueError(
            "regional scheduled observation requires candidate receipt, proof output, and receipt output paths"
        )
    if args.proof_output_json == args.receipt_output_json:
        raise ValueError("regional scheduled observation proof and receipt outputs must be distinct")
    for path, label in (
        (args.proof_output_json, "authority ledger proof output"),
        (args.receipt_output_json, "regional scheduled observation receipt output"),
    ):
        if Path(path).exists() or Path(path).is_symlink():
            raise ValueError(f"{label} path already exists")
    observation = RegionalScheduledObservation.model_validate(
        read_strict_json(args.observation_json, label="regional scheduled observation JSON")
    )
    proof, receipt = build_regional_scheduled_observation(
        profile,
        observation,
        profile_path=args.profile_json,
        candidate_receipt_path=args.candidate_receipt_json,
        registry_jobs=registry_jobs,
    )
    _write_new_canonical_json(
        args.proof_output_json,
        proof.model_dump(mode="json"),
        label="authority ledger proof output",
    )
    _write_new_canonical_json(
        args.receipt_output_json,
        receipt.model_dump(mode="json"),
        label="regional scheduled observation receipt output",
    )
    print(
        "PASS: regional scheduled observation "
        f"authority={profile.authority.operational_scope} "
        f"plan={profile.execution_plan.plan_id} "
        f"machine={observation.machine_id} results={len(proof.runner_results)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
