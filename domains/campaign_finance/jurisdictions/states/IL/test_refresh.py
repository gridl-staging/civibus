from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

from core.refresh.runner import RunnerParameters
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.IL.refresh import build_refresh_jobs
from domains.campaign_finance.jurisdictions.states.IL.scraper.cli import run_il_refresh


CONFIG = load_jurisdiction_config(Path(__file__).with_name("config.yaml"))
NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)


def test_build_refresh_jobs_preserves_metadata_order_and_callable_arguments() -> None:
    jobs = build_refresh_jobs(CONFIG, RunnerParameters(), NOW)

    assert [(job.key, job.domain, job.jurisdiction, job.cadence, job.data_source_names) for job in jobs] == [
        (
            "state-il-contributions",
            "campaign_finance",
            "state/IL",
            "continuous",
            ("IL SBE Campaign Disclosure — Receipts",),
        ),
        (
            "state-il-expenditures",
            "campaign_finance",
            "state/IL",
            "continuous",
            ("IL SBE Campaign Disclosure — Expenditures",),
        ),
    ]
    assert [job.run_callable.func for job in jobs] == [run_il_refresh, run_il_refresh]
    assert [job.run_callable.args for job in jobs] == [(), ()]
    assert [job.run_callable.keywords for job in jobs] == [
        {"data_type": "contributions", "download": True},
        {"data_type": "expenditures", "download": True},
    ]
    for job in jobs:
        inspect.signature(job.run_callable).bind()


def test_build_refresh_jobs_emits_only_jobs_with_matching_sources() -> None:
    expected_key_by_source_name = {
        "IL SBE Campaign Disclosure — Receipts": "state-il-contributions",
        "IL SBE Campaign Disclosure — Expenditures": "state-il-expenditures",
    }
    for source_name, expected_key in expected_key_by_source_name.items():
        selected_sources = [source for source in CONFIG.data_sources if source.name == source_name]
        selected_config = CONFIG.model_copy(update={"data_sources": selected_sources})

        jobs = build_refresh_jobs(selected_config, RunnerParameters(), NOW)

        assert [(job.key, job.data_source_names) for job in jobs] == [(expected_key, (source_name,))]

    config_without_sources = CONFIG.model_copy(update={"data_sources": []})
    assert build_refresh_jobs(config_without_sources, RunnerParameters(), NOW) == []
