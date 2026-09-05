from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest

from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import (
    JurisdictionConfig,
    load_jurisdiction_config,
)
from domains.campaign_finance.jurisdictions.refresh_registry import (
    JURISDICTION_REFRESH_REGISTRATIONS,
    JurisdictionRefreshRegistration,
    RefreshJobsBuilder,
    build_registered_refresh_jobs,
    load_validated_refresh_registrations,
    registration_identities,
    validate_registrations,
)


_JURISDICTIONS_ROOT = Path(__file__).resolve().parent
_NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
_EXPECTED_IDENTITIES = (
    ("state", "AL"),
    ("state", "CA"),
    ("state", "CO"),
    ("state", "FL"),
    ("state", "GA"),
    ("state", "IL"),
    ("state", "IN"),
    ("state", "KY"),
    ("state", "LA"),
    ("state", "MA"),
    ("state", "MN"),
    ("state", "NC"),
    ("state", "NE"),
    ("state", "NJ"),
    ("state", "NY"),
    ("state", "OR"),
    ("state", "PA"),
    ("state", "TX"),
    ("state", "VA"),
    ("state", "WA"),
    ("state", "WI"),
    ("municipality", "LA"),
    ("municipality", "NYC"),
    ("municipality", "PHL"),
    ("municipality", "SF"),
)


def _load_config(jurisdiction_type: str, code: str) -> JurisdictionConfig:
    package_group = "states" if jurisdiction_type == "state" else "cities"
    return load_jurisdiction_config(_JURISDICTIONS_ROOT / package_group / code / "config.yaml")


def _registration(
    jurisdiction_type: str,
    code: str,
    *,
    builder: object | None = None,
) -> JurisdictionRefreshRegistration:
    resolved_builder = builder or (lambda config, parameters, now: [])
    return JurisdictionRefreshRegistration(
        jurisdiction_type=jurisdiction_type,
        jurisdiction_code=code,
        builder=cast(RefreshJobsBuilder, resolved_builder),
    )


def test_live_registry_has_exact_ordered_composite_identities() -> None:
    assert registration_identities(JURISDICTION_REFRESH_REGISTRATIONS) == _EXPECTED_IDENTITIES
    assert len(set(_EXPECTED_IDENTITIES)) == 25
    assert ("state", "OH") not in _EXPECTED_IDENTITIES
    assert ("state", "LA") in _EXPECTED_IDENTITIES
    assert ("municipality", "LA") in _EXPECTED_IDENTITIES


def test_live_registry_joins_each_registration_to_exactly_one_config() -> None:
    validated = load_validated_refresh_registrations(_JURISDICTIONS_ROOT)

    assert tuple(item.identity for item in validated) == _EXPECTED_IDENTITIES


def test_live_registered_jobs_preserve_distinct_la_scopes_and_configured_sources() -> None:
    validated = load_validated_refresh_registrations(_JURISDICTIONS_ROOT)

    jobs = build_registered_refresh_jobs(
        registrations=JURISDICTION_REFRESH_REGISTRATIONS,
        configs=(item.config for item in validated),
        parameters=RunnerParameters(),
        now=_NOW,
    )

    state_la_jobs = [job for job in jobs if job.jurisdiction == "state/LA"]
    city_la_jobs = [job for job in jobs if job.jurisdiction == "municipality/LA"]
    assert {job.key for job in state_la_jobs} == {
        "state-la-contributions",
        "state-la-expenditures",
        "state-la-loans",
    }
    assert [job.key for job in city_la_jobs] == ["city-la-transactions"]


def test_validate_registrations_rejects_missing_builder() -> None:
    registration = JurisdictionRefreshRegistration(
        jurisdiction_type="state",
        jurisdiction_code="CA",
        builder=cast(RefreshJobsBuilder, None),
    )

    with pytest.raises(ValueError, match=r"state/CA.*callable builder"):
        validate_registrations((registration,), (_load_config("state", "CA"),))


def test_validate_registrations_rejects_duplicate_composite_identity() -> None:
    registrations = (
        _registration("state", "LA"),
        _registration("state", "LA"),
    )

    with pytest.raises(ValueError, match=r"duplicate registration.*state/LA"):
        validate_registrations(registrations, (_load_config("state", "LA"),))


def test_validate_registrations_keeps_state_la_and_municipality_la_distinct() -> None:
    registrations = (
        _registration("state", "LA"),
        _registration("municipality", "LA"),
    )
    configs = (
        _load_config("state", "LA"),
        _load_config("municipality", "LA"),
    )

    validated = validate_registrations(registrations, configs)

    assert tuple(item.identity for item in validated) == (
        ("state", "LA"),
        ("municipality", "LA"),
    )


@pytest.mark.parametrize(
    ("configs", "expected_count"),
    (
        ((), 0),
        ((_load_config("state", "CA"), _load_config("state", "CA")), 2),
    ),
)
def test_validate_registrations_rejects_zero_or_multiple_config_joins(
    configs: tuple[JurisdictionConfig, ...],
    expected_count: int,
) -> None:
    with pytest.raises(
        ValueError,
        match=rf"state/CA.*exactly one discovered config.*found {expected_count}",
    ):
        validate_registrations((_registration("state", "CA"),), configs)


def test_validate_registrations_rejects_config_identity_mismatch() -> None:
    with pytest.raises(ValueError, match=r"state/CA.*found 0"):
        validate_registrations(
            (_registration("state", "CA"),),
            (_load_config("municipality", "LA"),),
        )


def test_build_registered_refresh_jobs_rejects_duplicate_job_key() -> None:
    def _duplicate_key_builder(
        config: JurisdictionConfig,
        parameters: RunnerParameters,
        now: datetime,
    ) -> list[RefreshJob]:
        del parameters, now
        return [
            RefreshJob(
                key="duplicate-key",
                domain="campaign_finance",
                jurisdiction=f"{config.jurisdiction.type}/{config.jurisdiction.code}",
                cadence="daily",
                data_source_names=(config.data_sources[0].name,),
                run_callable=lambda: None,
            )
        ]

    registrations = (
        _registration("state", "CA", builder=_duplicate_key_builder),
        _registration("state", "CO", builder=_duplicate_key_builder),
    )
    configs = (_load_config("state", "CA"), _load_config("state", "CO"))

    with pytest.raises(ValueError, match=r"duplicate refresh job key.*duplicate-key"):
        build_registered_refresh_jobs(
            registrations=registrations,
            configs=configs,
            parameters=RunnerParameters(),
            now=_NOW,
        )


def _single_job_builder(*, jurisdiction: str, source_name: str) -> RefreshJobsBuilder:
    def build_jobs(
        config: JurisdictionConfig,
        parameters: RunnerParameters,
        now: datetime,
    ) -> list[RefreshJob]:
        del config, parameters, now
        return [
            RefreshJob(
                key="identity-probe",
                domain="campaign_finance",
                jurisdiction=jurisdiction,
                cadence="daily",
                data_source_names=(source_name,),
                run_callable=lambda: None,
            )
        ]

    return build_jobs


def test_build_registered_refresh_jobs_refuses_cross_la_operational_scope() -> None:
    config = _load_config("municipality", "LA")
    builder = _single_job_builder(
        jurisdiction="state/LA",
        source_name=config.data_sources[0].name,
    )

    with pytest.raises(ValueError, match=r"municipality/LA.*emitted operational scope 'state/LA'"):
        build_registered_refresh_jobs(
            registrations=(_registration("municipality", "LA", builder=builder),),
            configs=(config,),
            parameters=RunnerParameters(),
            now=_NOW,
        )


def test_build_registered_refresh_jobs_refuses_unknown_config_source_identity() -> None:
    config = _load_config("state", "LA")
    builder = _single_job_builder(
        jurisdiction="state/LA",
        source_name="Los Angeles source must not match Louisiana",
    )

    with pytest.raises(ValueError, match=r"state/LA.*source name.*found 0"):
        build_registered_refresh_jobs(
            registrations=(_registration("state", "LA", builder=builder),),
            configs=(config,),
            parameters=RunnerParameters(),
            now=_NOW,
        )
