"""Explicit ordered composition of campaign-finance jurisdiction refresh adapters."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.refresh.runner import RefreshJob, RunnerParameters
from domains.campaign_finance.jurisdictions.cities.LA.refresh import build_refresh_jobs as build_city_la_jobs
from domains.campaign_finance.jurisdictions.cities.NYC.refresh import build_refresh_jobs as build_city_nyc_jobs
from domains.campaign_finance.jurisdictions.cities.PHL.refresh import build_refresh_jobs as build_city_phl_jobs
from domains.campaign_finance.jurisdictions.cities.SF.refresh import build_refresh_jobs as build_city_sf_jobs
from domains.campaign_finance.jurisdictions.config_schema import (
    ConfigJurisdictionIdentity,
    JurisdictionConfig,
    JurisdictionTypeLiteral,
    discover_jurisdiction_configs,
    load_jurisdiction_config,
    operational_scope_for_config_identity,
)
from domains.campaign_finance.jurisdictions.states.AL.refresh import build_refresh_jobs as build_state_al_jobs
from domains.campaign_finance.jurisdictions.states.CA.refresh import build_refresh_jobs as build_state_ca_jobs
from domains.campaign_finance.jurisdictions.states.CO.refresh import build_refresh_jobs as build_state_co_jobs
from domains.campaign_finance.jurisdictions.states.FL.refresh import build_refresh_jobs as build_state_fl_jobs
from domains.campaign_finance.jurisdictions.states.GA.refresh import build_refresh_jobs as build_state_ga_jobs
from domains.campaign_finance.jurisdictions.states.IL.refresh import build_refresh_jobs as build_state_il_jobs
from domains.campaign_finance.jurisdictions.states.IN.refresh import build_refresh_jobs as build_state_in_jobs
from domains.campaign_finance.jurisdictions.states.KY.refresh import build_refresh_jobs as build_state_ky_jobs
from domains.campaign_finance.jurisdictions.states.LA.refresh import build_refresh_jobs as build_state_la_jobs
from domains.campaign_finance.jurisdictions.states.MA.refresh import build_refresh_jobs as build_state_ma_jobs
from domains.campaign_finance.jurisdictions.states.MN.refresh import build_refresh_jobs as build_state_mn_jobs
from domains.campaign_finance.jurisdictions.states.NC.refresh import build_refresh_jobs as build_state_nc_jobs
from domains.campaign_finance.jurisdictions.states.NE.refresh import build_refresh_jobs as build_state_ne_jobs
from domains.campaign_finance.jurisdictions.states.NJ.refresh import build_refresh_jobs as build_state_nj_jobs
from domains.campaign_finance.jurisdictions.states.NY.refresh import build_refresh_jobs as build_state_ny_jobs
from domains.campaign_finance.jurisdictions.states.OR.refresh import build_refresh_jobs as build_state_or_jobs
from domains.campaign_finance.jurisdictions.states.PA.refresh import build_refresh_jobs as build_state_pa_jobs
from domains.campaign_finance.jurisdictions.states.TX.refresh import build_refresh_jobs as build_state_tx_jobs
from domains.campaign_finance.jurisdictions.states.VA.refresh import build_refresh_jobs as build_state_va_jobs
from domains.campaign_finance.jurisdictions.states.WA.refresh import build_refresh_jobs as build_state_wa_jobs
from domains.campaign_finance.jurisdictions.states.WI.refresh import build_refresh_jobs as build_state_wi_jobs


JurisdictionRefreshIdentity = ConfigJurisdictionIdentity
RefreshJobsBuilder = Callable[[JurisdictionConfig, RunnerParameters, datetime], list[RefreshJob]]
_DEFAULT_JURISDICTIONS_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class JurisdictionRefreshRegistration:
    jurisdiction_type: JurisdictionTypeLiteral
    jurisdiction_code: str
    builder: RefreshJobsBuilder

    @property
    def identity(self) -> JurisdictionRefreshIdentity:
        return self.jurisdiction_type, self.jurisdiction_code


@dataclass(frozen=True, slots=True)
class ValidatedJurisdictionRefreshRegistration:
    registration: JurisdictionRefreshRegistration
    config: JurisdictionConfig

    @property
    def identity(self) -> JurisdictionRefreshIdentity:
        return self.registration.identity


JURISDICTION_REFRESH_REGISTRATIONS = (
    JurisdictionRefreshRegistration("state", "AL", build_state_al_jobs),
    JurisdictionRefreshRegistration("state", "CA", build_state_ca_jobs),
    JurisdictionRefreshRegistration("state", "CO", build_state_co_jobs),
    JurisdictionRefreshRegistration("state", "FL", build_state_fl_jobs),
    JurisdictionRefreshRegistration("state", "GA", build_state_ga_jobs),
    JurisdictionRefreshRegistration("state", "IL", build_state_il_jobs),
    JurisdictionRefreshRegistration("state", "IN", build_state_in_jobs),
    JurisdictionRefreshRegistration("state", "KY", build_state_ky_jobs),
    JurisdictionRefreshRegistration("state", "LA", build_state_la_jobs),
    JurisdictionRefreshRegistration("state", "MA", build_state_ma_jobs),
    JurisdictionRefreshRegistration("state", "MN", build_state_mn_jobs),
    JurisdictionRefreshRegistration("state", "NC", build_state_nc_jobs),
    JurisdictionRefreshRegistration("state", "NE", build_state_ne_jobs),
    JurisdictionRefreshRegistration("state", "NJ", build_state_nj_jobs),
    JurisdictionRefreshRegistration("state", "NY", build_state_ny_jobs),
    JurisdictionRefreshRegistration("state", "OR", build_state_or_jobs),
    JurisdictionRefreshRegistration("state", "PA", build_state_pa_jobs),
    JurisdictionRefreshRegistration("state", "TX", build_state_tx_jobs),
    JurisdictionRefreshRegistration("state", "VA", build_state_va_jobs),
    JurisdictionRefreshRegistration("state", "WA", build_state_wa_jobs),
    JurisdictionRefreshRegistration("state", "WI", build_state_wi_jobs),
    JurisdictionRefreshRegistration("municipality", "LA", build_city_la_jobs),
    JurisdictionRefreshRegistration("municipality", "NYC", build_city_nyc_jobs),
    JurisdictionRefreshRegistration("municipality", "PHL", build_city_phl_jobs),
    JurisdictionRefreshRegistration("municipality", "SF", build_city_sf_jobs),
)


def registration_identities(
    registrations: Iterable[JurisdictionRefreshRegistration] = JURISDICTION_REFRESH_REGISTRATIONS,
) -> tuple[JurisdictionRefreshIdentity, ...]:
    return tuple(registration.identity for registration in registrations)


def _display_identity(identity: JurisdictionRefreshIdentity) -> str:
    return "/".join(identity)


def validate_registrations(
    registrations: Iterable[JurisdictionRefreshRegistration],
    configs: Iterable[JurisdictionConfig],
) -> tuple[ValidatedJurisdictionRefreshRegistration, ...]:
    resolved_registrations = tuple(registrations)
    identities = registration_identities(resolved_registrations)

    for registration in resolved_registrations:
        if not callable(registration.builder):
            raise ValueError(
                f"Jurisdiction refresh registration {_display_identity(registration.identity)} needs a callable builder"
            )

    duplicate_identities = [identity for identity, count in Counter(identities).items() if count > 1]
    if duplicate_identities:
        duplicates = ", ".join(_display_identity(identity) for identity in duplicate_identities)
        raise ValueError(f"Jurisdiction refresh registry has duplicate registration(s): {duplicates}")

    configs_by_identity: dict[JurisdictionRefreshIdentity, list[JurisdictionConfig]] = defaultdict(list)
    for config in configs:
        identity = config.jurisdiction.identity
        configs_by_identity[identity].append(config)

    validated: list[ValidatedJurisdictionRefreshRegistration] = []
    for registration in resolved_registrations:
        matching_configs = configs_by_identity[registration.identity]
        if len(matching_configs) != 1:
            raise ValueError(
                f"Jurisdiction refresh registration {_display_identity(registration.identity)} expected exactly one "
                f"discovered config, found {len(matching_configs)}"
            )
        validated.append(
            ValidatedJurisdictionRefreshRegistration(
                registration=registration,
                config=matching_configs[0],
            )
        )
    return tuple(validated)


def load_validated_refresh_registrations(
    jurisdictions_root: Path | None = None,
    *,
    registrations: Iterable[JurisdictionRefreshRegistration] = JURISDICTION_REFRESH_REGISTRATIONS,
) -> tuple[ValidatedJurisdictionRefreshRegistration, ...]:
    root = jurisdictions_root or _DEFAULT_JURISDICTIONS_ROOT
    configs = tuple(load_jurisdiction_config(path) for path in discover_jurisdiction_configs(root))
    return validate_registrations(registrations, configs)


def build_registered_refresh_jobs(
    *,
    registrations: Iterable[JurisdictionRefreshRegistration],
    configs: Iterable[JurisdictionConfig],
    parameters: RunnerParameters,
    now: datetime,
) -> list[RefreshJob]:
    validated = validate_registrations(registrations, configs)
    jobs: list[RefreshJob] = []
    seen_job_keys: set[str] = set()
    for item in validated:
        for job in item.registration.builder(item.config, parameters, now):
            _validate_emitted_job_identity(item, job)
            if job.key in seen_job_keys:
                raise ValueError(f"Jurisdiction refresh registry generated duplicate refresh job key: {job.key}")
            seen_job_keys.add(job.key)
            jobs.append(job)
    return jobs


def _validate_emitted_job_identity(
    item: ValidatedJurisdictionRefreshRegistration,
    job: RefreshJob,
) -> None:
    expected_scope = operational_scope_for_config_identity(item.identity)
    if job.jurisdiction != expected_scope:
        raise ValueError(
            f"Jurisdiction refresh registration {_display_identity(item.identity)} emitted operational scope "
            f"{job.jurisdiction!r}; expected {expected_scope!r}"
        )

    # The NC adapter also emits one civics-owned candidate-listing job. Its source
    # identity is not owned by the campaign-finance config, but its regional scope must
    # still agree with the matched composite config identity above.
    if job.domain != "campaign_finance":
        return

    for source_name in job.data_source_names:
        match_count = sum(source.name == source_name for source in item.config.data_sources)
        if match_count != 1:
            raise ValueError(
                f"Jurisdiction refresh registration {_display_identity(item.identity)} expected exactly one "
                f"configured source name {source_name!r}, found {match_count}"
            )
