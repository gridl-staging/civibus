"""Contract tests for the jurisdiction refresh job extraction seam."""

from __future__ import annotations

from types import ModuleType
from unittest.mock import MagicMock

import pytest

from core.refresh.runner import RefreshJob
from domains.campaign_finance.jurisdictions.config_schema import (
    ContributionLimitsConfig,
    DataSourceConfig,
    DataSourceCoverageConfig,
    JurisdictionConfig,
    JurisdictionIdentity,
    LawsConfig,
    ReportingConfig,
    StatusConfig,
    UpdateFrequencyLiteral,
)


def _load_jurisdiction_jobs() -> ModuleType:
    from core.refresh import jurisdiction_jobs

    return jurisdiction_jobs


def _data_source(
    name: str,
    transaction_types: tuple[str, ...],
    update_frequency: UpdateFrequencyLiteral,
) -> DataSourceConfig:
    return DataSourceConfig(
        name=name,
        url=f"https://example.test/{name.lower().replace(' ', '-')}",
        bulk_download_url=None,
        api_base_url=None,
        format="csv",
        auth_required=False,
        update_frequency=update_frequency,
        coverage=DataSourceCoverageConfig(
            start_year=2020,
            covers_sub_jurisdictions=False,
            office_levels=["state"],
            transaction_types=list(transaction_types),
        ),
        field_mappings={},
        scraper=None,
        last_successful_pull=None,
        last_verified_working=None,
        known_issues=[],
    )


def _jurisdiction_config(*data_sources: DataSourceConfig) -> JurisdictionConfig:
    return JurisdictionConfig(
        jurisdiction=JurisdictionIdentity(
            name="Test State",
            code="TS",
            type="state",
            fips="99",
            parent=None,
        ),
        data_sources=list(data_sources),
        laws=LawsConfig(
            source_url="https://example.test/law",
            last_verified=None,
            contribution_limits=ContributionLimitsConfig(
                individual_to_candidate=1_000,
                pac_to_candidate=2_000,
                corporate_direct=0,
                union_direct=0,
                party_to_candidate=5_000,
            ),
            itemization_threshold=50,
            reporting=ReportingConfig(
                periods=["quarterly"],
                electronic_filing_required="required",
            ),
            public_financing=False,
            notes=[],
        ),
        status=StatusConfig(
            discovery="complete",
            scraper="complete",
            normalization="complete",
            entity_resolution="complete",
            last_full_update=None,
        ),
    )


@pytest.mark.unit
class TestJurisdictionJobs:
    def test_build_transaction_jobs_emits_exact_metadata_and_run_callables(self) -> None:
        jurisdiction_jobs = _load_jurisdiction_jobs()
        contributions_run = MagicMock(return_value="contributions refreshed")
        expenditures_run = MagicMock(return_value="expenditures refreshed")
        run_callables = {
            "contributions": contributions_run,
            "expenditures": expenditures_run,
        }
        config = _jurisdiction_config(
            _data_source("Contribution Source", ("contributions",), "daily"),
            _data_source("Expenditure Source", ("expenditures",), "weekly"),
        )

        jobs = jurisdiction_jobs._build_transaction_jobs(
            config,
            jurisdiction="state/test",
            key_prefix="state-ts",
            data_types=("contributions", "expenditures"),
            build_run_callable=run_callables.__getitem__,
        )

        assert all(isinstance(job, RefreshJob) for job in jobs)
        assert [
            (
                job.key,
                job.domain,
                job.jurisdiction,
                job.cadence,
                job.data_source_names,
                job.refresh_history_key,
                job.activity_denominator_result_field,
                job.side_effects_repaired_by_job_key,
            )
            for job in jobs
        ] == [
            (
                "state-ts-contributions",
                "campaign_finance",
                "state/test",
                "daily",
                ("Contribution Source",),
                None,
                None,
                None,
            ),
            (
                "state-ts-expenditures",
                "campaign_finance",
                "state/test",
                "weekly",
                ("Expenditure Source",),
                None,
                None,
                None,
            ),
        ]
        assert jobs[0].run_callable is contributions_run
        assert jobs[1].run_callable is expenditures_run
        assert jobs[0].run_callable() == "contributions refreshed"
        assert jobs[1].run_callable() == "expenditures refreshed"
        contributions_run.assert_called_once_with()
        expenditures_run.assert_called_once_with()

    def test_build_transaction_jobs_omits_a_missing_transaction_type(self) -> None:
        jurisdiction_jobs = _load_jurisdiction_jobs()
        config = _jurisdiction_config(
            _data_source("Contribution Source", ("contributions",), "daily"),
        )

        jobs = jurisdiction_jobs._build_transaction_jobs(
            config,
            jurisdiction="state/test",
            key_prefix="state-ts",
            data_types=("contributions", "loans"),
            build_run_callable=lambda data_type: lambda: data_type,
        )

        assert [job.key for job in jobs] == ["state-ts-contributions"]

    def test_build_transaction_jobs_rejects_duplicate_matching_sources(self) -> None:
        jurisdiction_jobs = _load_jurisdiction_jobs()
        config = _jurisdiction_config(
            _data_source("Primary Contribution Source", ("contributions",), "daily"),
            _data_source("Backup Contribution Source", ("contributions",), "weekly"),
        )

        with pytest.raises(RuntimeError) as error:
            jurisdiction_jobs._build_transaction_jobs(
                config,
                jurisdiction="state/test",
                key_prefix="state-ts",
                data_types=("contributions",),
                build_run_callable=lambda data_type: lambda: data_type,
            )

        assert str(error.value) == (
            "Refresh runner expected one data source for TS transaction type 'contributions', found 2"
        )

    def test_find_data_source_by_name_returns_none_for_missing_name(self) -> None:
        jurisdiction_jobs = _load_jurisdiction_jobs()
        config = _jurisdiction_config(
            _data_source("Contribution Source", ("contributions",), "daily"),
        )

        source = jurisdiction_jobs._find_data_source_by_name(
            config,
            source_name="Missing Source",
        )

        assert source is None

    def test_find_data_source_by_name_rejects_duplicate_exact_names(self) -> None:
        jurisdiction_jobs = _load_jurisdiction_jobs()
        config = _jurisdiction_config(
            _data_source("Duplicate Source", ("contributions",), "daily"),
        ).model_copy(
            update={
                "data_sources": [
                    _data_source("Duplicate Source", ("contributions",), "daily"),
                    _data_source("Duplicate Source", ("expenditures",), "weekly"),
                ]
            }
        )

        with pytest.raises(RuntimeError, match=r"TS.*source name 'Duplicate Source'.*found 2"):
            jurisdiction_jobs._find_data_source_by_name(config, source_name="Duplicate Source")

    def test_unsupported_transaction_types_are_omitted_without_reordering_jobs(self) -> None:
        jurisdiction_jobs = _load_jurisdiction_jobs()
        config = _jurisdiction_config(
            _data_source("Contribution Source", ("contributions",), "daily"),
            _data_source("Expenditure Source", ("expenditures",), "weekly"),
        )

        jobs = jurisdiction_jobs._build_transaction_jobs(
            config,
            jurisdiction="state/test",
            key_prefix="state-ts",
            data_types=("expenditures", "transfers", "contributions", "loans"),
            build_run_callable=lambda data_type: lambda: data_type,
        )

        assert [job.key for job in jobs] == [
            "state-ts-expenditures",
            "state-ts-contributions",
        ]
        assert [job.run_callable() for job in jobs] == ["expenditures", "contributions"]
