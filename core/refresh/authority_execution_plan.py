"""Typed authority-scoped plans over the existing refresh-job registry.

This module owns selection and invocation semantics only.  Job registration stays in
``domains.campaign_finance.jurisdictions.refresh_registry`` and scheduling stays with
the existing Fly Machine profile; an authority plan is not another registry or
scheduler.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from domains.campaign_finance.jurisdictions.config_schema import FilingAuthorityKindLiteral


ExecutionPlanMode = Literal["scheduled", "canary"]
ExecutionOrigin = Literal["scheduled", "operator_attended"]
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_SAFE_AUTHORITY_CODE = re.compile(r"[A-Z0-9][A-Z0-9_-]*")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityIdentity(_StrictModel):
    kind: FilingAuthorityKindLiteral
    code: str

    @model_validator(mode="after")
    def validate_code(self) -> Self:
        if _SAFE_AUTHORITY_CODE.fullmatch(self.code) is None:
            raise ValueError("authority code must be an uppercase stable identity token")
        return self

    @property
    def operational_scope(self) -> str:
        return f"{self.kind}/{self.code}"


class ExecutionModePlan(_StrictModel):
    execution_origin: ExecutionOrigin
    job_keys: tuple[str, ...]
    schedule: Literal["daily", "weekly"] | None
    stop_on_failure: bool

    @model_validator(mode="after")
    def validate_job_keys(self) -> Self:
        if not self.job_keys:
            raise ValueError("execution mode requires at least one refresh job key")
        if any(_SAFE_ID.fullmatch(job_key) is None for job_key in self.job_keys):
            raise ValueError("execution mode contains an invalid refresh job key")
        duplicates = sorted(key for key, count in Counter(self.job_keys).items() if count > 1)
        if duplicates:
            raise ValueError(f"execution mode contains duplicate refresh job keys: {duplicates!r}")
        return self


class ExecutionConcurrency(_StrictModel):
    max_parallel_jobs: Literal[1]
    same_host_lock: Literal["exact_authority_and_job_key_flock"]
    cross_host_lock: Literal["exact_authority_and_job_key_postgres_advisory_lock"]


class ExecutionCadenceClock(_StrictModel):
    scheduler: Literal["machine_schedule"]
    job_due: Literal["refresh_history_or_data_source_per_job"]
    force_allowed: Literal[False]


class AuthorityExecutionPlan(_StrictModel):
    schema_version: Literal[1]
    plan_id: str
    contract_path: str
    authority: AuthorityIdentity
    scheduled: ExecutionModePlan
    canary: ExecutionModePlan
    concurrency: ExecutionConcurrency
    cadence_clock: ExecutionCadenceClock

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if _SAFE_ID.fullmatch(self.plan_id) is None:
            raise ValueError("execution plan id must be a stable identity token")
        contract = Path(self.contract_path)
        if (
            contract.is_absolute()
            or not self.contract_path.endswith(".json")
            or not self.contract_path
            or ".." in contract.parts
        ):
            raise ValueError("execution plan contract_path must be a safe repository-relative JSON path")
        if self.scheduled.execution_origin != "scheduled" or self.scheduled.schedule is None:
            raise ValueError("scheduled mode requires scheduled origin and an explicit Machine cadence")
        if self.canary.execution_origin != "operator_attended" or self.canary.schedule is not None:
            raise ValueError("canary mode requires operator-attended origin and no schedule")
        if not self.canary.stop_on_failure or len(self.canary.job_keys) != 1:
            raise ValueError("canary mode must be a stop-on-failure singleton")
        if not set(self.canary.job_keys).issubset(self.scheduled.job_keys):
            raise ValueError("canary job must be owned by the scheduled authority plan")
        return self

    @property
    def ownership_lock_key(self) -> str:
        return f"authority-plan:{self.authority.operational_scope}"

    def mode(self, mode: ExecutionPlanMode) -> ExecutionModePlan:
        return self.scheduled if mode == "scheduled" else self.canary


class RefreshJobLike(Protocol):
    key: str
    domain: str
    jurisdiction: str


def _read_strict_json(path: Path) -> object:
    if not path.is_file() or path.is_symlink():
        raise ValueError("authority execution plan must be a regular non-symlink JSON file")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"authority execution plan contains duplicate object key: {key}")
            payload[key] = value
        return payload

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"authority execution plan contains non-finite number: {value}")
            ),
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("authority execution plan is not readable strict JSON") from error


def load_authority_execution_plan(path: Path | str) -> AuthorityExecutionPlan:
    """Load the typed plan nested in one authority-scoped operations profile."""

    payload = _read_strict_json(Path(path))
    if not isinstance(payload, dict) or "execution_plan" not in payload:
        raise ValueError("authority operations profile must contain execution_plan")
    return AuthorityExecutionPlan.model_validate(payload["execution_plan"])


def select_execution_plan_jobs(
    registry_jobs: Sequence[RefreshJobLike],
    plan: AuthorityExecutionPlan,
    *,
    mode: ExecutionPlanMode,
) -> list[RefreshJobLike]:
    """Select the mode's exact ordered keys and refuse incomplete or cross-owner plans."""

    registry_counts = Counter(job.key for job in registry_jobs)
    duplicates = sorted(key for key, count in registry_counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"authority execution plan found duplicate registry job keys: {duplicates!r}")
    registry_by_key = {job.key: job for job in registry_jobs}
    mode_plan = plan.mode(mode)
    # Canary execution still proves the complete scheduled plan is present in the
    # image registry.  Otherwise a singleton could pass immediately before a
    # recurrence Machine whose downstream jobs are missing or cross-owned.
    missing = [key for key in plan.scheduled.job_keys if key not in registry_by_key]
    if missing:
        raise ValueError(f"authority execution plan has missing registered job keys: {missing!r}")

    owned_plan_jobs = [registry_by_key[key] for key in plan.scheduled.job_keys]
    crossed = [
        job.key
        for job in owned_plan_jobs
        if job.domain != "campaign_finance" or job.jurisdiction != plan.authority.operational_scope
    ]
    if crossed:
        raise ValueError(
            f"authority execution plan crosses authority ownership {plan.authority.operational_scope}: {crossed!r}"
        )
    return [registry_by_key[key] for key in mode_plan.job_keys]


def validate_disjoint_execution_plans(plans: Iterable[AuthorityExecutionPlan]) -> None:
    """Refuse plans that could claim the same authority, identity, or refresh job."""

    resolved = tuple(plans)
    authorities = Counter(plan.authority.operational_scope for plan in resolved)
    shared_authorities = sorted(key for key, count in authorities.items() if count > 1)
    if shared_authorities:
        raise ValueError(f"authority execution plans share authority ownership: {shared_authorities!r}")

    plan_ids = Counter(plan.plan_id for plan in resolved)
    shared_plan_ids = sorted(key for key, count in plan_ids.items() if count > 1)
    if shared_plan_ids:
        raise ValueError(f"authority execution plans share plan identity: {shared_plan_ids!r}")

    job_owners: Counter[str] = Counter()
    for plan in resolved:
        job_owners.update(plan.scheduled.job_keys)
    shared_jobs = sorted(key for key, count in job_owners.items() if count > 1)
    if shared_jobs:
        raise ValueError(f"authority execution plans share refresh job ownership: {shared_jobs!r}")


def expected_runner_command(
    plan: AuthorityExecutionPlan,
    *,
    mode: ExecutionPlanMode,
) -> tuple[str, ...]:
    """Return the only accepted runner command for a planned Machine invocation."""

    mode_plan = plan.mode(mode)
    return (
        "python",
        "-m",
        "core.refresh.runner",
        "--authority-plan-json",
        plan.contract_path,
        "--execution-mode",
        mode,
        "--execution-origin",
        mode_plan.execution_origin,
    )
