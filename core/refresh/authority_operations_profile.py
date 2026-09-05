"""Strict authority-scoped refresh operations profile and receipt helpers."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from core.refresh.authority_execution_plan import (
    AuthorityExecutionPlan,
    AuthorityIdentity,
    expected_runner_command,
    validate_disjoint_execution_plans,
)


_FLY_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_REGIONAL_ENV = {
    "CIVIBUS_ENV": "production",
    "CIVIBUS_REFRESH_DATA_DIR": "/tmp/civibus-refresh-data",
    "CIVIBUS_STARTUP_CANARY": "skip",
    "POSTGRES_DB": "civibus",
    "POSTGRES_HOST": "civibus-db.internal",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "civibus",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonicalSource(_StrictModel):
    receipt_git_sha: str
    source_git_sha: str
    tree_git_sha: str

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        if any(
            _HEX_40.fullmatch(value) is None for value in (self.receipt_git_sha, self.source_git_sha, self.tree_git_sha)
        ):
            raise ValueError("canonical source identities must be lowercase 40-character Git hashes")
        return self


class CanaryContract(_StrictModel):
    command: tuple[str, ...]
    execution_origin: Literal["operator_attended"]
    job_key: str
    schedule: None
    stop_on_failure: Literal[True]


class CleanupContract(_StrictModel):
    app_rollback: Literal["destroy_only_task_created_app_after_exact_machine_absence_and_empty_inventory"]
    normal_terminal: Literal["retain_exact_machine_stopped"]
    prestart_failure: Literal["nonforce_destroy_only_exact_owned_stopped_machine_and_verify_absent"]
    indeterminate: Literal["handoff_without_mutation_or_retry"]
    started_rollback: Literal["stop_once_exact_owned_machine_then_nonforce_destroy_and_verify_absent"]
    volume_cleanup: Literal["not_applicable_no_volume"]


class ImageContract(_StrictModel):
    qualification: Literal["candidate_receipt_must_bind_exact_tagged_digest_to_descendant_source_git_sha_and_tree"]
    repository: str
    tagged_digest: None


class MachineGuest(_StrictModel):
    cpu_kind: Literal["shared"]
    cpus: Literal[1]
    memory_mb: Literal[1024]


class MachineRestart(_StrictModel):
    policy: Literal["no"]


class MachineInit(_StrictModel):
    cmd: tuple[str, ...]


class MachineConfig(_StrictModel):
    auto_destroy: Literal[False]
    env: dict[str, str]
    files: tuple[Any, ...]
    guest: MachineGuest
    init: MachineInit
    metadata: dict[str, str]
    mounts: tuple[Any, ...]
    restart: MachineRestart
    schedule: Literal["daily", "weekly"]
    services: tuple[Any, ...]

    @model_validator(mode="after")
    def validate_nonsecret_shape(self) -> Self:
        if self.env != _REGIONAL_ENV:
            raise ValueError("authority Machine environment mismatch")
        if self.files or self.mounts or self.services:
            raise ValueError("authority Machine profile must not deliver files, mounts, or services")
        return self


class MachineContract(_StrictModel):
    config: MachineConfig
    config_sha256: str
    default_state: Literal["stopped"]
    id: None
    name: str
    region: str
    volume_policy: Literal["none_ephemeral_system_tmp_only"]


class SecretDeliveryContract(_StrictModel):
    machine_config_env_names: tuple[str, ...]
    machine_config_files: tuple[str, ...]
    names: tuple[str, ...]
    provider: Literal["fly_app_secret"]
    values_in_profile: Literal[False]

    @model_validator(mode="after")
    def validate_delivery(self) -> Self:
        if self.machine_config_env_names or self.machine_config_files:
            raise ValueError("secret delivery must not place secret names or files in Machine config")
        if self.names != ("POSTGRES_PASSWORD",):
            raise ValueError("secret delivery must name only the existing database credential")
        return self


class ResourceOwnership(_StrictModel):
    app: str
    authority: str
    machine: str
    plan: str


class AuthorityOperationsProfile(_StrictModel):
    schema_version: Literal[3]
    app: str
    canonical_source: CanonicalSource
    canary: CanaryContract
    cleanup: CleanupContract
    execution_plan: AuthorityExecutionPlan
    image: ImageContract
    organization: str
    organization_id: str
    machine: MachineContract
    profile_id: str
    provisioning_state: Literal["unprovisioned"]
    resource_ownership: ResourceOwnership
    secret_delivery: SecretDeliveryContract

    @model_validator(mode="after")
    def validate_identity_and_plan_bindings(self) -> Self:
        if _FLY_NAME.fullmatch(self.app) is None or _FLY_NAME.fullmatch(self.machine.name) is None:
            raise ValueError("authority profile app and Machine names must be safe Fly identities")
        if self.profile_id != self.execution_plan.plan_id:
            raise ValueError("authority profile id must equal execution plan id")
        if self.canary.command != expected_runner_command(self.execution_plan, mode="canary"):
            raise ValueError("authority profile canary command does not match execution plan")
        if self.canary.job_key != self.execution_plan.canary.job_keys[0]:
            raise ValueError("authority profile canary job does not match execution plan")
        if self.canary.execution_origin != self.execution_plan.canary.execution_origin:
            raise ValueError("authority profile canary origin does not match execution plan")
        if self.machine.config.init.cmd != expected_runner_command(self.execution_plan, mode="scheduled"):
            raise ValueError("authority Machine command does not match execution plan")
        if self.machine.config.schedule != self.execution_plan.scheduled.schedule:
            raise ValueError("authority Machine schedule does not match execution plan")
        expected_metadata = {
            "civibus_authority": self.execution_plan.authority.operational_scope,
            "civibus_execution_plan": self.execution_plan.plan_id,
            "civibus_profile": self.profile_id,
        }
        if self.machine.config.metadata != expected_metadata:
            raise ValueError("authority Machine metadata does not bind exact plan ownership")
        expected_ownership = ResourceOwnership(
            app=self.app,
            authority=self.execution_plan.authority.operational_scope,
            machine=self.machine.name,
            plan=self.execution_plan.plan_id,
        )
        if self.resource_ownership != expected_ownership:
            raise ValueError("authority resource ownership does not match profile identities")
        if self.machine.config_sha256 != canonical_sha256(self.machine.config.model_dump(mode="json")):
            raise ValueError("authority Machine config digest mismatch")
        return self

    @property
    def authority(self) -> AuthorityIdentity:
        return self.execution_plan.authority


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def read_strict_json(path: Path | str, *, label: str) -> object:
    resolved = Path(path)
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError(f"{label} contains a duplicate object key")
            payload[key] = value
        return payload

    try:
        return json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"{label} contains non-finite number {value}")
            ),
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable strict JSON") from error


def load_authority_operations_profile(path: Path | str) -> AuthorityOperationsProfile:
    return AuthorityOperationsProfile.model_validate(read_strict_json(path, label="profile JSON"))


def validate_disjoint_operations_profiles(profiles: Iterable[AuthorityOperationsProfile]) -> None:
    resolved = tuple(profiles)
    validate_disjoint_execution_plans(profile.execution_plan for profile in resolved)
    for label, values in (
        ("authority", (profile.authority.operational_scope for profile in resolved)),
        ("app", (profile.app for profile in resolved)),
        ("Machine", (profile.machine.name for profile in resolved)),
        ("plan", (profile.execution_plan.plan_id for profile in resolved)),
    ):
        counts = Counter(values)
        shared = sorted(value for value, count in counts.items() if count > 1)
        if shared:
            raise ValueError(f"authority operations profiles share {label} ownership: {shared!r}")


def expected_image_plan_proof(
    profile: AuthorityOperationsProfile,
    *,
    build_version: dict[str, str],
) -> dict[str, object]:
    plan = profile.execution_plan
    return {
        "authority": plan.authority.model_dump(mode="json"),
        "build_version": build_version,
        "cadence_clock": plan.cadence_clock.model_dump(mode="json"),
        "canary": plan.canary.model_dump(mode="json"),
        "concurrency": plan.concurrency.model_dump(mode="json"),
        "execution_plan_id": plan.plan_id,
        "execution_plan_sha256": canonical_sha256(plan.model_dump(mode="json")),
        "scheduled": plan.scheduled.model_dump(mode="json"),
    }
