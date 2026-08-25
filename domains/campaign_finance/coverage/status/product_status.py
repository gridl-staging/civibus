"""Read-only ``product-status`` projection for the deployed federal product.

The view owns no facts. It projects the deployed API and web version probes,
``PublicFederalMetadataResponse``, the FEC coverage-registry row, and the capability
document and proof receipt as they exist at the deployed revision. It never falls
back to the local working-tree revision or file timestamps.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Annotated, Final, Literal, Union

import httpx
from pydantic import Field, ValidationError, field_validator

from api.models.metadata import PublicFederalMetadataResponse
from domains.campaign_finance.coverage.registry import (
    DEFAULT_REGISTRY_PATH,
    CoverageRegistryRow,
    load_registry,
)
from domains.campaign_finance.coverage.status.models import (
    NOT_APPLICABLE,
    FieldProvenance,
    ObservationInput,
    ProjectedField,
    ProjectionReport,
    Refusal,
    StatusProjectionModel,
    UnknownFact,
    refuse,
)
from domains.campaign_finance.coverage.status.registry_fields import project_evidence_dated_field

DEFAULT_PRODUCT_BASE_URL: Final[str] = "https://civibus.shareborough.com"
VERSION_PROBES_OWNER: Final[str] = "deployed /api/health/version and /version.json probes"
METADATA_OWNER: Final[str] = "PublicFederalMetadataResponse"
CAPABILITIES_OWNER: Final[str] = "CAPABILITIES.md"

_API_VERSION_PATH: Final[str] = "/api/health/version"
_WEB_VERSION_PATH: Final[str] = "/version.json"
_METADATA_PATH: Final[str] = "/api/public/v1/federal/metadata"
_CAPABILITIES_PATH: Final[str] = "CAPABILITIES.md"
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
_CAPABILITY_SET_UNKNOWN_REASON: Final[str] = "CAPABILITIES.md is judgment prose, not a machine-readable capability set"
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_CAPABILITY_PIN_PATTERN = re.compile(r"\bcommit\s+`([0-9a-f]{7,40})`", re.IGNORECASE)
_PRODUCTION_SECTION_PATTERN = re.compile(
    r"^## Production \(verified [^)]+\)\s*$([\s\S]*?)(?=^## |\Z)",
    re.MULTILINE,
)
_PROOF_REFERENCE_PATTERN = re.compile(r"`((?:docs/live-state|infra)/[^`]+)`")
_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")

ProjectionValueOrUnknown = Annotated[
    Union[ProjectedField, UnknownFact],
    Field(discriminator="status"),
]


class VersionPayload(StatusProjectionModel):
    """Strict deployed version-probe payload."""

    git_sha: str
    built_at: str

    @field_validator("git_sha")
    @classmethod
    def _validate_git_sha(cls, value: str) -> str:
        if value == "unknown" or _SHA_PATTERN.fullmatch(value):
            return value
        raise ValueError("git_sha must be a 40-character lowercase hexadecimal SHA or 'unknown'")

    @field_validator("built_at")
    @classmethod
    def _validate_built_at(cls, value: str) -> str:
        if value == "unknown":
            return value
        parsed = _parse_timestamp(value)
        if parsed is None:
            raise ValueError("built_at must be a timezone-aware ISO 8601 timestamp or 'unknown'")
        return value


class CapabilityScope(StatusProjectionModel):
    """Deterministic deployed-document reference, without parsing capability claims."""

    reference: ProjectionValueOrUnknown
    capability_set: UnknownFact


class GeographicCoverage(StatusProjectionModel):
    """Federal geographic coverage, kept separate from proof and source freshness."""

    current_officeholder_count: ProjectedField
    officeholder_denominator_is_fixed: ProjectedField
    federal_public_tier: ProjectedField


class ProductStatusReport(ProjectionReport):
    """Successfully projected product-status report."""

    status: Literal["product"] = "product"
    deployed_revision: ProjectionValueOrUnknown
    deployed_built_at: ProjectionValueOrUnknown
    revision_parity: ProjectionValueOrUnknown
    capability_scope: CapabilityScope
    last_proof_at: ProjectionValueOrUnknown
    proof_age: ProjectionValueOrUnknown
    source_freshness: list[ProjectionValueOrUnknown]
    geographic_coverage: GeographicCoverage
    request_limit: ProjectedField
    donor_identity_resolution: ProjectedField


def build_product_status_report(
    *,
    version_payloads: tuple[VersionPayload, VersionPayload],
    metadata: PublicFederalMetadataResponse,
    fec_registry_row: CoverageRegistryRow,
    capabilities_text: str | None,
    revision_file_loader: Callable[[str], str | None],
    calculated_at: datetime,
) -> ProductStatusReport | Refusal:
    """Project one report from already-loaded canonical inputs."""

    api_version, web_version = version_payloads
    split_field = _split_revision_field(api_version, web_version)
    if split_field is not None:
        return refuse(
            scope="product-status",
            reason=f"split-revision deployment: API and web {split_field} values disagree",
            canonical_owner=VERSION_PROBES_OWNER,
        )

    envelope = ProjectionReport(calculated_at=calculated_at)
    deployed_revision = _project_version_value(
        envelope,
        value=api_version.git_sha,
        field_name="git_sha",
        source_observed_at=NOT_APPLICABLE,
    )
    built_at_observation = _parse_timestamp(api_version.built_at)
    deployed_built_at = _project_version_value(
        envelope,
        value=api_version.built_at,
        field_name="built_at",
        source_observed_at=built_at_observation,
    )
    revision_parity = _project_revision_parity(envelope, api_version, web_version)
    capability_reference, proof_path = _resolve_capability_reference(
        envelope,
        deployed_sha=api_version.git_sha,
        capabilities_text=capabilities_text,
    )
    if isinstance(capability_reference, UnknownFact):
        last_proof_at: ProjectionValueOrUnknown = UnknownFact(
            reason=f"product proof unavailable: {capability_reference.reason}"
        )
    else:
        last_proof_at = _project_last_proof_at(envelope, proof_path, revision_file_loader)
    proof_age = _project_proof_age(envelope, last_proof_at)

    return ProductStatusReport(
        calculated_at=envelope.calculated_at,
        deployed_revision=deployed_revision,
        deployed_built_at=deployed_built_at,
        revision_parity=revision_parity,
        capability_scope=CapabilityScope(
            reference=capability_reference,
            capability_set=UnknownFact(reason=_CAPABILITY_SET_UNKNOWN_REASON),
        ),
        last_proof_at=last_proof_at,
        proof_age=proof_age,
        source_freshness=_project_source_freshness(envelope, metadata),
        geographic_coverage=_project_geographic_coverage(envelope, metadata, fec_registry_row),
        request_limit=envelope.project_field(
            value=metadata.rate_limit.model_dump(mode="json"),
            provenance=FieldProvenance(
                owner="PublicRateLimitPolicy",
                read_path="api/middleware/access.py::public_rate_limit_policy",
                origin="direct",
            ),
            source_observed_at=NOT_APPLICABLE,
        ),
        donor_identity_resolution=envelope.project_field(
            value=metadata.coverage.donor_identity_resolution,
            provenance=FieldProvenance(
                owner="PublicFederalCoverage.donor_identity_resolution",
                read_path="api/queries/campaign_finance.py::public_top_donors_identity_resolution_status",
                origin="direct",
            ),
            source_observed_at=NOT_APPLICABLE,
        ),
    )


def _split_revision_field(api_version: VersionPayload, web_version: VersionPayload) -> str | None:
    for field_name in ("git_sha", "built_at"):
        api_value = getattr(api_version, field_name)
        web_value = getattr(web_version, field_name)
        if "unknown" not in (api_value, web_value) and api_value != web_value:
            return field_name
    return None


def _project_version_value(
    report: ProjectionReport,
    *,
    value: str,
    field_name: str,
    source_observed_at: ObservationInput,
) -> ProjectionValueOrUnknown:
    if value == "unknown":
        return UnknownFact(reason=f"{_API_VERSION_PATH} {field_name} is unknown")
    return report.project_field(
        value=value,
        provenance=FieldProvenance(
            owner=_API_VERSION_PATH,
            read_path="api/health_version.py::build_version_payload",
            origin="direct",
        ),
        source_observed_at=source_observed_at,
    )


def _project_revision_parity(
    report: ProjectionReport,
    api_version: VersionPayload,
    web_version: VersionPayload,
) -> ProjectionValueOrUnknown:
    if "unknown" in (
        api_version.git_sha,
        api_version.built_at,
        web_version.git_sha,
        web_version.built_at,
    ):
        return UnknownFact(reason="API and web revision parity cannot be proven with unknown probe values")
    return report.project_field(
        value=True,
        provenance=FieldProvenance(
            owner=VERSION_PROBES_OWNER,
            read_path=f"{_API_VERSION_PATH} and {_WEB_VERSION_PATH}",
            origin="direct",
        ),
        source_observed_at=NOT_APPLICABLE,
    )


def _resolve_capability_reference(
    report: ProjectionReport,
    *,
    deployed_sha: str,
    capabilities_text: str | None,
) -> tuple[ProjectionValueOrUnknown, str | None]:
    if deployed_sha == "unknown":
        return UnknownFact(reason="deployed revision is unknown"), None
    if capabilities_text is None:
        return UnknownFact(reason="CAPABILITIES.md is unreadable at deployed revision"), None

    pins = set(_CAPABILITY_PIN_PATTERN.findall(capabilities_text))
    if len(pins) != 1 or not deployed_sha.startswith(next(iter(pins), "")):
        return UnknownFact(reason="CAPABILITIES.md commit pin does not cover deployed revision"), None
    sections = _PRODUCTION_SECTION_PATTERN.findall(capabilities_text)
    if len(sections) != 1:
        return UnknownFact(reason="CAPABILITIES.md has no single deployed Production section"), None
    proof_paths = sorted(set(_PROOF_REFERENCE_PATTERN.findall(sections[0])))
    proof_path = proof_paths[0] if len(proof_paths) == 1 else None
    reference = report.project_field(
        value=f"CAPABILITIES.md@{deployed_sha}",
        provenance=FieldProvenance(
            owner=CAPABILITIES_OWNER,
            read_path=f"git show {deployed_sha}:{_CAPABILITIES_PATH}",
            origin="direct",
        ),
        source_observed_at=NOT_APPLICABLE,
    )
    return reference, proof_path


def _project_last_proof_at(
    report: ProjectionReport,
    proof_path: str | None,
    revision_file_loader: Callable[[str], str | None],
) -> ProjectionValueOrUnknown:
    if proof_path is None:
        return UnknownFact(reason="CAPABILITIES.md does not name exactly one deployed proof receipt")
    receipt = revision_file_loader(proof_path)
    if receipt is None:
        return UnknownFact(reason=f"{proof_path} is unreadable at deployed revision")
    timestamps = {_parse_timestamp(value) for value in _TIMESTAMP_PATTERN.findall(receipt)}
    timestamps.discard(None)
    if len(timestamps) != 1:
        return UnknownFact(reason=f"{proof_path} does not contain exactly one machine-readable proof timestamp")
    observed_at = next(iter(timestamps))
    assert observed_at is not None
    return report.project_field(
        value={"receipt": proof_path, "observed_at": observed_at},
        provenance=FieldProvenance(
            owner=proof_path,
            read_path=f"deployed revision:{proof_path}",
            origin="direct",
        ),
        source_observed_at=observed_at,
    )


def _project_proof_age(
    report: ProjectionReport,
    last_proof_at: ProjectionValueOrUnknown,
) -> ProjectionValueOrUnknown:
    if isinstance(last_proof_at, UnknownFact):
        return UnknownFact(reason="proof age unavailable without a deterministic product proof timestamp")
    return report.project_field(
        value=last_proof_at.model_dump(mode="json")["age"],
        provenance=FieldProvenance(
            owner="derived",
            read_path="status/product_status.py::_project_proof_age",
            origin="direct",
        ),
        source_observed_at=last_proof_at.source_observed_at,
    )


def _project_source_freshness(
    report: ProjectionReport,
    metadata: PublicFederalMetadataResponse,
) -> list[ProjectionValueOrUnknown]:
    if not metadata.data_sources:
        return [UnknownFact(reason="PublicFederalMetadataResponse.data_sources is empty")]
    return [
        report.project_field(
            value={
                "data_source_id": str(source.data_source_id),
                "name": source.name,
                "last_pull_at": source.last_pull_at,
                "last_pull_status": source.last_pull_status,
                "record_count": source.record_count,
            },
            provenance=FieldProvenance(
                owner="PublicFederalMetadataResponse.data_sources",
                read_path="api/queries/metadata.py::fetch_public_federal_data_sources",
                origin="direct",
            ),
            source_observed_at=source.last_pull_at,
        )
        for source in metadata.data_sources
    ]


def _project_geographic_coverage(
    report: ProjectionReport,
    metadata: PublicFederalMetadataResponse,
    fec_registry_row: CoverageRegistryRow,
) -> GeographicCoverage:
    coverage_provenance = FieldProvenance(
        owner="PublicFederalCoverage",
        read_path="get_public_federal_metadata -> fetch_current_federal_members",
        origin="direct",
    )
    return GeographicCoverage(
        current_officeholder_count=report.project_field(
            value=metadata.coverage.current_officeholder_count,
            provenance=coverage_provenance,
            source_observed_at=NOT_APPLICABLE,
        ),
        officeholder_denominator_is_fixed=report.project_field(
            value=metadata.coverage.officeholder_denominator_is_fixed,
            provenance=coverage_provenance,
            source_observed_at=NOT_APPLICABLE,
        ),
        federal_public_tier=project_evidence_dated_field(
            report,
            value=fec_registry_row.tier,
            origin="direct",
            evidence_date=fec_registry_row.evidence_date,
        ),
    )


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _fetch_json(base_url: str, path: str) -> object:
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        response = client.get(f"{base_url.rstrip('/')}{path}")
        response.raise_for_status()
        return response.json()


def _read_revision_file(sha: str, path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "show", f"{sha}:{path}"],
            cwd=_REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project deployed product status as JSON")
    parser.add_argument("--base-url", default=DEFAULT_PRODUCT_BASE_URL)
    parser.add_argument("--registry-path", type=Path, default=DEFAULT_REGISTRY_PATH)
    return parser


def _print_refusal(reason: str, canonical_owner: str) -> int:
    print(
        refuse(
            scope="product-status",
            reason=reason,
            canonical_owner=canonical_owner,
        ).model_dump_json(indent=2)
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        api_version = VersionPayload.model_validate(_fetch_json(args.base_url, _API_VERSION_PATH))
        web_version = VersionPayload.model_validate(_fetch_json(args.base_url, _WEB_VERSION_PATH))
    except (httpx.HTTPError, ValidationError, TypeError, ValueError, json.JSONDecodeError):
        return _print_refusal(
            "required deployed probe is unreachable or unparseable",
            VERSION_PROBES_OWNER,
        )

    try:
        metadata = PublicFederalMetadataResponse.model_validate(_fetch_json(args.base_url, _METADATA_PATH))
    except (httpx.HTTPError, ValidationError, TypeError, ValueError, json.JSONDecodeError):
        return _print_refusal(
            "required federal metadata snapshot is unreachable or unparseable",
            METADATA_OWNER,
        )

    try:
        registry = load_registry(args.registry_path)
        fec_rows = [row for row in registry.rows if row.jurisdiction_code == "FEC"]
        if len(fec_rows) != 1:
            raise ValueError("coverage registry must contain exactly one FEC row")
    except (OSError, ValueError):
        return _print_refusal("required FEC coverage-registry row is unreadable", "coverage-registry")

    capabilities_text = (
        None if api_version.git_sha == "unknown" else _read_revision_file(api_version.git_sha, _CAPABILITIES_PATH)
    )
    report = build_product_status_report(
        version_payloads=(api_version, web_version),
        metadata=metadata,
        fec_registry_row=fec_rows[0],
        capabilities_text=capabilities_text,
        revision_file_loader=lambda path: _read_revision_file(api_version.git_sha, path),
        calculated_at=datetime.now(timezone.utc),
    )
    print(report.model_dump_json(indent=2))
    return 1 if isinstance(report, Refusal) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
