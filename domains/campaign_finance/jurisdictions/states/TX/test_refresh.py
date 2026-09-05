from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import JurisdictionConfig, load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.TX import refresh as tx_refresh
from domains.campaign_finance.jurisdictions.states.TX.scraper.cli import run_tx_refresh

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
CONFIG_PATH = Path(__file__).with_name("config.yaml")
EXPECTED_JOBS = (
    ("state-tx-contributions", "contributions"),
    ("state-tx-expenditures", "expenditures"),
    ("state-tx-loans", "loans"),
)


def _load_config(*, jurisdiction_code: str | None = None) -> JurisdictionConfig:
    config = load_jurisdiction_config(CONFIG_PATH)
    if jurisdiction_code is None:
        return config
    jurisdiction = config.jurisdiction.model_copy(update={"code": jurisdiction_code})
    return config.model_copy(update={"jurisdiction": jurisdiction})


def _source_for_data_type(config: JurisdictionConfig, data_type: str):
    return next(source for source in config.data_sources if data_type in source.coverage.transaction_types)


def _without_data_type(config: JurisdictionConfig, data_type: str) -> JurisdictionConfig:
    omitted_source = _source_for_data_type(config, data_type)
    return config.model_copy(
        update={"data_sources": [source for source in config.data_sources if source != omitted_source]}
    )


def _assert_tx_jobs(
    config: JurisdictionConfig,
    parameters: RunnerParameters,
    now: datetime,
    year_from: int,
) -> None:
    jobs = tx_refresh.build_refresh_jobs(config, parameters, now)
    state_code = config.jurisdiction.code

    state_key_prefix = f"state-{state_code.lower()}-"
    assert [job.key for job in jobs] == [
        key.replace("state-tx-", state_key_prefix) for key, _data_type in EXPECTED_JOBS
    ]
    for job, (_key, data_type) in zip(jobs, EXPECTED_JOBS, strict=True):
        source = _source_for_data_type(config, data_type)
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == f"state/{state_code}"
        assert job.cadence == source.update_frequency
        assert job.data_source_names == (source.name,)
        assert job.run_callable.func is run_tx_refresh
        assert job.run_callable.keywords == {"data_type": data_type, "download": True, "year_from": year_from}


def test_build_refresh_jobs_matches_tx_package_api_default_year_from() -> None:
    _assert_tx_jobs(_load_config(), RunnerParameters(), NOW, 2022)
    _assert_tx_jobs(
        _load_config(jurisdiction_code="ZZ"),
        RunnerParameters(),
        NOW.replace(year=2031),
        2027,
    )


def test_build_refresh_jobs_uses_tx_year_from_override() -> None:
    _assert_tx_jobs(_load_config(), RunnerParameters(tx_year_from=2024), NOW, 2024)


def test_build_refresh_jobs_omits_only_missing_source() -> None:
    config = _load_config()
    jobs = tx_refresh.build_refresh_jobs(_without_data_type(config, "loans"), RunnerParameters(), NOW)

    assert [job.key for job in jobs] == ["state-tx-contributions", "state-tx-expenditures"]
