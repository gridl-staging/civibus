"""Stage 4 regression tests for the SF city pipeline surface."""

from __future__ import annotations

from pathlib import Path

from core.refresh import job_builders


_SF_SCRAPER_DIR = Path(__file__).resolve().parent.parent / "scraper"


def test_sf_loader_module_exists() -> None:
    assert (_SF_SCRAPER_DIR / "load.py").is_file()


def test_sf_cli_module_exists() -> None:
    assert (_SF_SCRAPER_DIR / "cli.py").is_file()


def test_sf_loader_exports_public_api() -> None:
    from domains.campaign_finance.jurisdictions.cities.SF.scraper.load import (
        LoadResult,
        ensure_sf_data_source,
        load_sf_transactions_with_filings,
    )

    assert callable(ensure_sf_data_source)
    assert callable(load_sf_transactions_with_filings)
    assert LoadResult is not None


def test_sf_cli_exports_public_api() -> None:
    from domains.campaign_finance.jurisdictions.cities.SF.scraper.cli import (
        main,
        run_sf_refresh,
    )

    assert callable(run_sf_refresh)
    assert callable(main)


def test_build_refresh_plan_all_scope_includes_sf_city_job() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    job_keys = {job.key for job in jobs}

    assert "city-sf-transactions" in job_keys


def test_sf_city_job_metadata_matches_config() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    sf_jobs = [job for job in jobs if job.key == "city-sf-transactions"]

    assert len(sf_jobs) == 1
    sf_job = sf_jobs[0]
    assert sf_job.domain == "campaign_finance"
    assert sf_job.jurisdiction == "municipality/SF"
    assert sf_job.cadence == "daily"
    assert sf_job.data_source_names == ("SF Ethics Campaign Finance Transactions",)
