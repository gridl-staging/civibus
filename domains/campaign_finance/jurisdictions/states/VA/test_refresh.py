from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.VA.refresh import build_refresh_jobs
from domains.campaign_finance.jurisdictions.states.VA.scraper.cli import run_va_refresh


CONFIG = load_jurisdiction_config(Path(__file__).with_name("config.yaml"))
NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)


def test_build_refresh_jobs_preserves_metadata_order_and_year_month_override() -> None:
    import pytest

    jobs = build_refresh_jobs(CONFIG, RunnerParameters(va_year_month="2026_07"), NOW)

    assert [(job.key, job.domain, job.jurisdiction, job.cadence, job.data_source_names) for job in jobs] == [
        (
            "state-va-contributions",
            "campaign_finance",
            "state/VA",
            "daily",
            ("VA SBE Contributions Export (ScheduleA)",),
        ),
        (
            "state-va-expenditures",
            "campaign_finance",
            "state/VA",
            "daily",
            ("VA SBE Expenditures Export (ScheduleD)",),
        ),
    ]
    assert [job.run_callable.func for job in jobs] == [run_va_refresh, run_va_refresh]
    assert [job.run_callable.args for job in jobs] == [(), ()]
    assert [job.run_callable.keywords for job in jobs] == [
        {"data_type": "contributions", "download": True, "year_month": "2026_07"},
        {"data_type": "expenditures", "download": True, "year_month": "2026_07"},
    ]
    for job in jobs:
        inspect.signature(job.run_callable).bind()

    empty_override_jobs = build_refresh_jobs(CONFIG, RunnerParameters(va_year_month=""), NOW)
    assert [job.run_callable.keywords["year_month"] for job in empty_override_jobs] == ["", ""]

    with pytest.raises(ValueError, match="YYYY_MM"):
        build_refresh_jobs(CONFIG, RunnerParameters(va_year_month="../../outside"), NOW)


def test_build_refresh_jobs_uses_current_year_month_fallback() -> None:
    jobs = build_refresh_jobs(CONFIG, RunnerParameters(), NOW)

    assert [job.run_callable.keywords["year_month"] for job in jobs] == ["2026_08", "2026_08"]


def test_build_refresh_jobs_emits_only_jobs_with_matching_sources() -> None:
    expected_key_by_source_name = {
        "VA SBE Contributions Export (ScheduleA)": "state-va-contributions",
        "VA SBE Expenditures Export (ScheduleD)": "state-va-expenditures",
    }
    for source_name, expected_key in expected_key_by_source_name.items():
        selected_sources = [source for source in CONFIG.data_sources if source.name == source_name]
        selected_config = CONFIG.model_copy(update={"data_sources": selected_sources})

        jobs = build_refresh_jobs(selected_config, RunnerParameters(va_year_month="2026_07"), NOW)

        assert [(job.key, job.data_source_names) for job in jobs] == [(expected_key, (source_name,))]

    config_without_matching_sources = CONFIG.model_copy(
        update={
            "data_sources": [source for source in CONFIG.data_sources if source.name not in expected_key_by_source_name]
        }
    )
    assert build_refresh_jobs(config_without_matching_sources, RunnerParameters(), NOW) == []
