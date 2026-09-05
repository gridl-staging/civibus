from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.CO.refresh import build_refresh_jobs
from domains.campaign_finance.jurisdictions.states.CO.scraper.cli import run_co_refresh


CONFIG = load_jurisdiction_config(Path(__file__).with_name("config.yaml"))
NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)


def test_build_refresh_jobs_preserves_metadata_order_and_year_override() -> None:
    jobs = build_refresh_jobs(CONFIG, RunnerParameters(co_year=2025), NOW)

    assert [(job.key, job.domain, job.jurisdiction, job.cadence, job.data_source_names) for job in jobs] == [
        (
            "state-co-contributions",
            "campaign_finance",
            "state/CO",
            "weekly",
            ("TRACER Bulk Download — Contributions",),
        ),
        (
            "state-co-expenditures",
            "campaign_finance",
            "state/CO",
            "weekly",
            ("TRACER Bulk Download — Expenditures",),
        ),
    ]
    assert [job.run_callable.func for job in jobs] == [run_co_refresh, run_co_refresh]
    assert [job.run_callable.args for job in jobs] == [(), ()]
    assert [job.run_callable.keywords for job in jobs] == [
        {"data_type": "contributions", "download": True, "year": 2025, "allow_insecure_tls": True},
        {"data_type": "expenditures", "download": True, "year": 2025, "allow_insecure_tls": True},
    ]
    for job in jobs:
        inspect.signature(job.run_callable).bind()

    fallback_jobs = build_refresh_jobs(CONFIG, RunnerParameters(), NOW)
    assert [job.run_callable.keywords["year"] for job in fallback_jobs] == [2026, 2026]


def test_build_refresh_jobs_emits_only_jobs_with_matching_sources() -> None:
    expected_key_by_source_name = {
        "TRACER Bulk Download — Contributions": "state-co-contributions",
        "TRACER Bulk Download — Expenditures": "state-co-expenditures",
    }
    for source_name, expected_key in expected_key_by_source_name.items():
        selected_sources = [source for source in CONFIG.data_sources if source.name == source_name]
        selected_config = CONFIG.model_copy(update={"data_sources": selected_sources})

        jobs = build_refresh_jobs(selected_config, RunnerParameters(co_year=2025), NOW)

        assert [(job.key, job.data_source_names) for job in jobs] == [(expected_key, (source_name,))]

    config_without_matching_sources = CONFIG.model_copy(
        update={
            "data_sources": [source for source in CONFIG.data_sources if source.name not in expected_key_by_source_name]
        }
    )
    assert build_refresh_jobs(config_without_matching_sources, RunnerParameters(co_year=2025), NOW) == []
