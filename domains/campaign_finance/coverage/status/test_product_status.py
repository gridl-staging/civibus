"""Recorded-payload tests for the read-only ``product-status`` projection."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import subprocess
from uuid import UUID
from unittest.mock import MagicMock

import httpx

from api.models.metadata import (
    DataSourceMetadataResponse,
    PublicEmployerIndustryCoverage,
    PublicFederalCoverage,
    PublicFederalMetadataResponse,
    PublicRateLimitPolicy,
)
from domains.campaign_finance.coverage.status import product_status
from domains.campaign_finance.coverage.status.models import Refusal
from domains.campaign_finance.coverage.status.product_status import (
    VersionPayload,
    build_product_status_report,
    main,
)
from domains.campaign_finance.coverage.status.test_municipality import _registry_row

_DEPLOYED_SHA = "a" * 40
_BUILT_AT = "2026-08-21T00:50:05Z"
_CALCULATED_AT = datetime(2026, 8, 22, 3, 50, tzinfo=timezone.utc)
_RECEIPT_PATH = "docs/live-state/product_proof.md"


def _data_source(last_pull_at: datetime | None) -> DataSourceMetadataResponse:
    return DataSourceMetadataResponse(
        data_source_id=UUID("00000000-0000-0000-0000-000000000001"),
        domain="campaign_finance",
        jurisdiction="federal/fec",
        name="FEC transactions",
        source_url="https://example.invalid/fec",
        update_frequency="weekly",
        last_pull_at=last_pull_at,
        last_pull_status="success",
        record_count=123,
    )


def _metadata(
    *,
    last_pull_at: datetime | None = datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc),
    data_sources: list[DataSourceMetadataResponse] | None = None,
):
    return PublicFederalMetadataResponse(
        data_sources=[_data_source(last_pull_at)] if data_sources is None else data_sources,
        rate_limit=PublicRateLimitPolicy(max_requests=60, window_seconds=60),
        coverage=PublicFederalCoverage(
            current_officeholder_count=539,
            officeholder_denominator_is_fixed=False,
            employer_industry=PublicEmployerIndustryCoverage(
                classified_count=3076,
                unknown_count=13487,
                sampled_coverage_percentage=Decimal("18.57"),
            ),
            donor_identity_resolution="unresolved",
        ),
    )


def _capabilities(*, sha: str = _DEPLOYED_SHA, production_body: str | None = None) -> str:
    body = production_body if production_body is not None else f"The single product proof is `{_RECEIPT_PATH}`."
    return f"""# Capabilities

Product truth at commit `{sha}`.

## Production (verified 2026-08-21)

{body}

## Parked
"""


def _capabilities_with_production_sections(section_count: int) -> str:
    sections = "".join(
        f"## Production (verified 2026-08-2{index})\n\nThe single product proof is `{_RECEIPT_PATH}`.\n\n"
        for index in range(section_count)
    )
    return f"# Capabilities\n\nProduct truth at commit `{_DEPLOYED_SHA}`.\n\n{sections}## Parked\n"


def _build(**overrides: object):
    default_api_version = VersionPayload(git_sha=_DEPLOYED_SHA, built_at=_BUILT_AT)
    default_web_version = VersionPayload(git_sha=_DEPLOYED_SHA, built_at=_BUILT_AT)
    api_version = overrides.pop("api_version", default_api_version)
    web_version = overrides.pop("web_version", default_web_version)
    arguments = {
        "version_payloads": (api_version, web_version),
        "metadata": _metadata(),
        "fec_registry_row": _registry_row(
            "FEC",
            "Federal Election Commission",
            tier="launch-support candidate",
        ),
        "capabilities_text": _capabilities(),
        "revision_file_loader": lambda path: '{"verified_at":"2026-08-21T03:50:00Z"}',
        "calculated_at": _CALCULATED_AT,
    }
    arguments.update(overrides)
    return build_product_status_report(**arguments)


def _payload(report: object) -> dict[str, object]:
    return json.loads(report.model_dump_json())


def test_product_status_projects_recorded_deployment_metadata_and_proof_exactly() -> None:
    from inspect import signature

    assert len(signature(build_product_status_report).parameters) <= 6
    payload = _payload(_build())

    assert payload["status"] == "product"
    assert payload["deployed_revision"]["value"] == _DEPLOYED_SHA
    assert payload["deployed_built_at"]["value"] == _BUILT_AT
    assert payload["revision_parity"]["value"] is True
    assert payload["capability_scope"]["reference"]["value"] == f"CAPABILITIES.md@{_DEPLOYED_SHA}"
    assert payload["capability_scope"]["capability_set"] == {
        "status": "unknown",
        "reason": "CAPABILITIES.md is judgment prose, not a machine-readable capability set",
    }
    assert payload["last_proof_at"]["value"] == {
        "receipt": _RECEIPT_PATH,
        "observed_at": "2026-08-21T03:50:00Z",
    }
    assert payload["proof_age"]["value"] == "P1D"
    assert payload["source_freshness"][0]["value"] == {
        "data_source_id": "00000000-0000-0000-0000-000000000001",
        "name": "FEC transactions",
        "last_pull_at": "2026-08-21T02:00:00Z",
        "last_pull_status": "success",
        "record_count": 123,
    }
    assert payload["geographic_coverage"]["current_officeholder_count"]["value"] == 539
    assert payload["geographic_coverage"]["officeholder_denominator_is_fixed"]["value"] is False
    assert payload["geographic_coverage"]["federal_public_tier"]["value"] == "launch-support candidate"
    assert payload["request_limit"]["value"] == {"max_requests": 60, "window_seconds": 60}
    assert payload["donor_identity_resolution"]["value"] == "unresolved"


def test_product_status_refuses_split_revision_on_sha_or_build_timestamp() -> None:
    sha_split = _build(web_version=VersionPayload(git_sha="b" * 40, built_at=_BUILT_AT))
    time_split = _build(web_version=VersionPayload(git_sha=_DEPLOYED_SHA, built_at="2026-08-21T00:51:05Z"))

    for result, field in ((sha_split, "git_sha"), (time_split, "built_at")):
        assert result == Refusal(
            scope="product-status",
            reason=f"split-revision deployment: API and web {field} values disagree",
            canonical_owner="deployed /api/health/version and /version.json probes",
        )


def test_product_status_keeps_unknown_version_and_missing_freshness_unknown() -> None:
    payload = _payload(
        _build(
            api_version=VersionPayload(git_sha="unknown", built_at="unknown"),
            web_version=VersionPayload(git_sha="unknown", built_at="unknown"),
            metadata=_metadata(last_pull_at=None),
            capabilities_text=None,
        )
    )

    assert payload["deployed_revision"] == {
        "status": "unknown",
        "reason": "/api/health/version git_sha is unknown",
    }
    assert payload["deployed_built_at"] == {
        "status": "unknown",
        "reason": "/api/health/version built_at is unknown",
    }
    assert payload["revision_parity"]["status"] == "unknown"
    assert payload["capability_scope"]["reference"]["status"] == "unknown"
    assert payload["last_proof_at"]["status"] == "unknown"
    assert payload["proof_age"]["status"] == "unknown"
    assert payload["source_freshness"][0]["source_observed_at"] == "UNKNOWN"
    assert payload["source_freshness"][0]["age"] == "UNKNOWN"


def test_product_status_does_not_machine_parse_capabilities_without_exact_revision_pin() -> None:
    payload = _payload(_build(capabilities_text=_capabilities(sha="b" * 40)))

    assert payload["capability_scope"]["reference"] == {
        "status": "unknown",
        "reason": "CAPABILITIES.md commit pin does not cover deployed revision",
    }
    assert payload["last_proof_at"]["status"] == "unknown"


def test_product_status_proof_is_unknown_when_receipt_timestamp_is_ambiguous() -> None:
    payload = _payload(
        _build(
            revision_file_loader=lambda path: (
                '{"started_at":"2026-08-21T03:31:00Z","finished_at":"2026-08-21T03:50:00Z"}'
            )
        )
    )

    assert payload["last_proof_at"] == {
        "status": "unknown",
        "reason": f"{_RECEIPT_PATH} does not contain exactly one machine-readable proof timestamp",
    }
    assert payload["proof_age"]["status"] == "unknown"


def test_product_status_cli_refuses_unreachable_required_probe_without_local_fallback(
    capsys: object,
    monkeypatch: object,
) -> None:
    request = httpx.Request("GET", "https://example.invalid/api/health/version")
    monkeypatch.setattr(
        product_status,
        "_fetch_json",
        MagicMock(side_effect=httpx.ConnectError("unreachable", request=request)),
    )

    assert main(["--base-url", "https://example.invalid"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "refuse",
        "scope": "product-status",
        "reason": "required deployed probe is unreachable or unparseable",
        "canonical_owner": "deployed /api/health/version and /version.json probes",
    }


def test_product_status_cli_refuses_unparseable_required_metadata(
    capsys: object,
    monkeypatch: object,
) -> None:
    payloads = {
        "/api/health/version": {"git_sha": _DEPLOYED_SHA, "built_at": _BUILT_AT},
        "/version.json": {"git_sha": _DEPLOYED_SHA, "built_at": _BUILT_AT},
        "/api/public/v1/federal/metadata": {"data_sources": []},
    }
    monkeypatch.setattr(product_status, "_fetch_json", lambda base_url, path: payloads[path])

    assert main(["--base-url", "https://example.invalid"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "refuse",
        "scope": "product-status",
        "reason": "required federal metadata snapshot is unreachable or unparseable",
        "canonical_owner": "PublicFederalMetadataResponse",
    }


def test_product_status_cli_uses_injected_recorded_payloads_without_network(
    tmp_path: Path,
    capsys: object,
    monkeypatch: object,
) -> None:
    payloads = {
        "/api/health/version": {"git_sha": _DEPLOYED_SHA, "built_at": _BUILT_AT},
        "/version.json": {"git_sha": _DEPLOYED_SHA, "built_at": _BUILT_AT},
        "/api/public/v1/federal/metadata": _metadata().model_dump(mode="json"),
    }
    monkeypatch.setattr(product_status, "_fetch_json", lambda base_url, path: payloads[path])
    monkeypatch.setattr(
        product_status,
        "_read_revision_file",
        lambda sha, path: _capabilities() if path == "CAPABILITIES.md" else '{"verified_at":"2026-08-21T03:50:00Z"}',
    )
    monkeypatch.setattr(
        product_status,
        "load_registry",
        lambda path: MagicMock(rows=[_registry_row("FEC", "Federal", tier="launch-support candidate")]),
    )

    assert main(["--base-url", "https://example.invalid"]) == 0
    assert json.loads(capsys.readouterr().out)["deployed_revision"]["value"] == _DEPLOYED_SHA

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "uv").symlink_to("/bin/echo")
    environment = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    repo_root = Path(__file__).resolve().parents[4]
    for target, variable in (("product-status", "BASE_URL"), ("region-status", "REGION")):
        marker = tmp_path / f"{variable.lower()}_was_evaluated"
        raw_value = f"$(shell touch {marker})sentinel"
        result = subprocess.run(
            ["make", target, f"{variable}={raw_value}"],
            cwd=repo_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert raw_value in result.stdout
        assert not marker.exists(), f"Make expanded the untrusted {variable} value"


def test_product_status_proof_is_unknown_unless_capabilities_names_exactly_one_receipt() -> None:
    unnamed = _payload(_build(capabilities_text=_capabilities(production_body="Verified by hand.")))
    ambiguous = _payload(
        _build(
            capabilities_text=_capabilities(
                production_body=(f"Proofs are `{_RECEIPT_PATH}` and `infra/second_product_proof.json`.")
            )
        )
    )

    expected = {
        "status": "unknown",
        "reason": "CAPABILITIES.md does not name exactly one deployed proof receipt",
    }
    for payload in (unnamed, ambiguous):
        assert payload["capability_scope"]["reference"]["value"] == f"CAPABILITIES.md@{_DEPLOYED_SHA}"
        assert payload["last_proof_at"] == expected
        assert payload["proof_age"]["status"] == "unknown"


def test_product_status_proof_is_unknown_when_receipt_is_unreadable_at_deployed_revision() -> None:
    payload = _payload(_build(revision_file_loader=lambda path: None))

    assert payload["last_proof_at"] == {
        "status": "unknown",
        "reason": f"{_RECEIPT_PATH} is unreadable at deployed revision",
    }
    assert payload["proof_age"]["status"] == "unknown"


def test_product_status_capability_reference_needs_exactly_one_production_section() -> None:
    expected = {
        "status": "unknown",
        "reason": "CAPABILITIES.md has no single deployed Production section",
    }

    for section_count in (0, 2):
        payload = _payload(_build(capabilities_text=_capabilities_with_production_sections(section_count)))
        assert payload["capability_scope"]["reference"] == expected
        assert payload["last_proof_at"] == {
            "status": "unknown",
            "reason": f"product proof unavailable: {expected['reason']}",
        }


def test_product_status_capability_reference_is_unknown_when_capabilities_is_unreadable(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(product_status.subprocess, "run", MagicMock(side_effect=OSError("git unavailable")))
    assert product_status._read_revision_file(_DEPLOYED_SHA, "CAPABILITIES.md") is None

    payload = _payload(_build(capabilities_text=None))

    assert payload["capability_scope"]["reference"] == {
        "status": "unknown",
        "reason": "CAPABILITIES.md is unreadable at deployed revision",
    }
    assert payload["last_proof_at"] == {
        "status": "unknown",
        "reason": "product proof unavailable: CAPABILITIES.md is unreadable at deployed revision",
    }


def test_product_status_source_freshness_is_unknown_when_metadata_lists_no_data_sources() -> None:
    payload = _payload(_build(metadata=_metadata(data_sources=[])))

    assert payload["source_freshness"] == [
        {
            "status": "unknown",
            "reason": "PublicFederalMetadataResponse.data_sources is empty",
        }
    ]


def test_product_status_federal_tier_carries_registry_evidence_date_provenance() -> None:
    dated = _payload(
        _build(
            fec_registry_row=_registry_row(
                "FEC",
                "Federal Election Commission",
                tier="launch-support candidate",
                evidence_date=date(2026, 8, 20),
            )
        )
    )["geographic_coverage"]["federal_public_tier"]
    undated = _payload(_build())["geographic_coverage"]["federal_public_tier"]

    assert dated["owner"] == "coverage-registry"
    assert dated["read_path"] == "registry.py::CoverageRegistryRow"
    assert dated["origin"] == "direct"
    assert dated["source_observed_at"] == "2026-08-20"
    assert dated["age"] == "P2DT3H50M"
    assert undated["source_observed_at"] == "UNKNOWN"
    assert undated["age"] == "UNKNOWN"
    assert undated["observation_unknown_reason"] == "coverage-registry evidence_date absent"
