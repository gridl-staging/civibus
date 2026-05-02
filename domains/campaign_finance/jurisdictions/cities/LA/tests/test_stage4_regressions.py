"""Stage 4 regression tests for the LA city pipeline surface."""

from __future__ import annotations

from pathlib import Path

from core.refresh import job_builders


_LA_SCRAPER_DIR = Path(__file__).resolve().parent.parent / "scraper"


def test_la_loader_module_exists() -> None:
    assert (_LA_SCRAPER_DIR / "load.py").is_file()


def test_la_cli_module_exists() -> None:
    assert (_LA_SCRAPER_DIR / "cli.py").is_file()


def test_la_loader_exports_public_api() -> None:
    from domains.campaign_finance.jurisdictions.cities.LA.scraper.load import (
        LoadResult,
        ensure_la_data_source,
        load_la_transactions_with_filings,
    )

    assert callable(ensure_la_data_source)
    assert callable(load_la_transactions_with_filings)
    assert LoadResult is not None


def test_la_cli_exports_public_api() -> None:
    from domains.campaign_finance.jurisdictions.cities.LA.scraper.cli import (
        main,
        run_la_refresh,
    )

    assert callable(run_la_refresh)
    assert callable(main)


def test_build_refresh_plan_all_scope_includes_la_city_job() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    job_keys = {job.key for job in jobs}

    assert "city-la-transactions" in job_keys


def test_la_city_job_metadata_matches_config() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    la_jobs = [job for job in jobs if job.key == "city-la-transactions"]

    assert len(la_jobs) == 1
    la_job = la_jobs[0]
    assert la_job.domain == "campaign_finance"
    assert la_job.jurisdiction == "municipality/LA"
    assert la_job.cadence == "daily"
    assert la_job.data_source_names == ("LA Ethics Campaign Contributions",)
