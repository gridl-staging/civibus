"""Contract tests for IRS 527 refresh job wiring in build_refresh_plan()."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from core.refresh import job_builders
from core.refresh.job_builders import build_refresh_plan
from core.refresh.runner import RefreshJob, RunnerParameters, build_argument_parser
from domains.civics.loaders.ncsbe_candidate_listing import _NCSBE_DATA_SOURCE_NAME
from domains.civics.loaders.ncsbe_results import collect_ncsbe_refresh_raw_csv_paths
from domains.civics.loaders.official_rosters.source_templates import (
    civic_roster_refresh_templates,
    roster_source_templates,
)
from domains.civics.loaders.official_rosters.source_registry import (
    list_nc_roster_source_metadata,
)
from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.NC.scraper import _CONFIG_PATH as _NC_CONFIG_PATH
from domains.campaign_finance.jurisdictions.states.NC.scraper.load_support import (
    NC_COMMITTEE_DOCUMENT_SOURCE_NAME,
)

_EXPECTED_STAGE2_CIVIC_ROSTER_KEYS = (
    "civic-rosters-us-house-nc",
    "civic-rosters-us-senate-nc-ii",
    "civic-rosters-us-senate-nc-iii",
    "civic-rosters-nc-senate",
    "civic-rosters-council-of-state-gov",
    "civic-rosters-council-of-state-lt-gov",
    "civic-rosters-council-of-state-ag",
    "civic-rosters-council-of-state-sos",
    "civic-rosters-council-of-state-treasurer",
    "civic-rosters-council-of-state-auditor",
    "civic-rosters-council-of-state-supt",
    "civic-rosters-council-of-state-ag-comm",
    "civic-rosters-council-of-state-ins-comm",
    "civic-rosters-council-of-state-labor-comm",
    "civic-rosters-nc-supreme",
    "civic-rosters-nc-appeals",
)

_EXPECTED_CAMPAIGN_FINANCE_KEYS = (
    "city-la-transactions",
    "city-nyc-transactions",
    "city-phl-contributions",
    "city-phl-expenditures",
    "city-sf-transactions",
    "federal-congress-spine",
    "federal-fec-committee-summary",
    "federal-fec-masters",
    "federal-fec-schedule-a",
    "federal-fec-schedule-b",
    "federal-fec-schedule-e",
    "federal-irs-527",
    "state-al-contributions",
    "state-al-expenditures",
    "state-ca-refresh",
    "state-co-contributions",
    "state-co-expenditures",
    "state-fl-contributions",
    "state-fl-expenditures",
    "state-fl-other",
    "state-fl-transfers",
    "state-ga-contributions",
    "state-ga-expenditures",
    "state-il-contributions",
    "state-il-expenditures",
    "state-in-contributions",
    "state-in-expenditures",
    "state-ky-contributions-11-5-2024",
    "state-ky-contributions-11-7-2023",
    "state-ky-contributions-11-8-2022",
    "state-ky-contributions-5-16-2023",
    "state-ky-contributions-5-17-2022",
    "state-ky-contributions-5-19-2026",
    "state-ky-contributions-5-21-2024",
    "state-ky-expenditures",
    "state-la-contributions",
    "state-la-expenditures",
    "state-la-loans",
    "state-ma-contributions",
    "state-ma-expenditures",
    "state-mn-contributions",
    "state-mn-expenditures",
    "state-mn-independent_expenditures",
    "state-nc-committee-discovery",
    "state-ne-contributions",
    "state-ne-expenditures",
    "state-ne-loans",
    "state-nj-contributions",
    "state-ny-contributions",
    "state-ny-expenditures",
    "state-ny-independent_expenditures",
    "state-or-contributions",
    "state-or-expenditures",
    "state-pa-contributions",
    "state-pa-debts",
    "state-pa-expenditures",
    "state-pa-receipts",
    "state-tx-contributions",
    "state-tx-expenditures",
    "state-tx-loans",
    "state-va-contributions",
    "state-va-expenditures",
    "state-wa-contributions",
    "state-wa-expenditures",
    "state-wa-independent_expenditures",
    "state-wa-loans",
    "state-wi-transactions",
)


@pytest.mark.unit
class TestIRS527JobContract:
    """Contract: build_refresh_plan() must produce a federal-irs-527 job."""

    def _find_irs_527_job(self, jobs: list[RefreshJob]) -> RefreshJob:
        matches = [j for j in jobs if j.key == "federal-irs-527"]
        assert len(matches) == 1, (
            f"Expected exactly 1 job with key 'federal-irs-527', found {len(matches)} in {[j.key for j in jobs]}"
        )
        return matches[0]

    def test_plan_contains_irs_527_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan()
        job = self._find_irs_527_job(jobs)

        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "federal/irs_527"
        assert job.cadence == "continuous"
        assert "IRS Form 8872 Political Organizations" in job.data_source_names

    def test_key_prefix_filter_isolates_irs_527_job(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("federal-irs-527",))

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "federal-irs-527"
        assert not any(j.key.startswith(("fec-", "state-", "city-")) for j in jobs), (
            "Filtering by federal-irs-527 must exclude FEC, state, and city jobs"
        )

    def test_run_callable_is_zero_arg_callable(self) -> None:
        jobs = build_refresh_plan()
        job = self._find_irs_527_job(jobs)

        assert callable(job.run_callable)
        sig = inspect.signature(job.run_callable)
        required_params = [
            p
            for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert len(required_params) == 0, (
            f"run_callable must accept zero positional arguments, "
            f"but has required params: {[p.name for p in required_params]}"
        )


@pytest.mark.unit
class TestFederalEnrichmentJobContract:
    def _find_federal_enrichment_job(self) -> RefreshJob:
        jobs = build_refresh_plan(job_key_prefixes=("federal-enrichment",))
        assert len(jobs) == 1
        return jobs[0]

    def test_federal_enrichment_runs_after_fec_masters_and_congress_spine(self) -> None:
        jobs = build_refresh_plan(
            job_key_prefixes=(
                "federal-fec-masters",
                "federal-congress-spine",
                "federal-enrichment",
            ),
        )

        assert tuple(job.key for job in jobs) == (
            "federal-fec-masters",
            "federal-congress-spine",
            "federal-enrichment",
        )
        assert [job.key for job in jobs].count("federal-enrichment") == 1

    def test_federal_enrichment_job_metadata_matches_people_enrichment_source(self) -> None:
        job = self._find_federal_enrichment_job()

        assert job.key == "federal-enrichment"
        assert job.domain == "people_enrichment"
        assert job.jurisdiction == "federal/congress"
        assert job.cadence == "weekly"
        assert job.data_source_names == ("people-enrichment-federal-congress",)

    def test_priority_scope_includes_federal_spine_before_weekly_enrichment(self) -> None:
        jobs = build_refresh_plan(
            scope="priority",
            job_key_prefixes=("federal-congress-spine", "federal-enrichment"),
        )

        assert tuple(job.key for job in jobs) == (
            "federal-congress-spine",
            "federal-enrichment",
        )
        assert tuple(job.cadence for job in jobs) == ("weekly", "weekly")

    def test_federal_enrichment_run_callable_commits_and_closes_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connection = MagicMock()
        enrichment_summary = {"updated": 3}
        get_connection = MagicMock(return_value=connection)
        run_federal_enrichment = MagicMock(return_value=enrichment_summary)
        monkeypatch.setattr(job_builders, "get_connection", get_connection)
        monkeypatch.setattr(job_builders, "run_federal_enrichment", run_federal_enrichment)
        job = self._find_federal_enrichment_job()

        result = job.run_callable()

        assert result == enrichment_summary
        get_connection.assert_called_once_with()
        run_federal_enrichment.assert_called_once_with(connection)
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_federal_enrichment_run_callable_rolls_back_closes_and_reraises_on_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connection = MagicMock()
        error = RuntimeError("enrichment failed")
        get_connection = MagicMock(return_value=connection)
        run_federal_enrichment = MagicMock(side_effect=error)
        monkeypatch.setattr(job_builders, "get_connection", get_connection)
        monkeypatch.setattr(job_builders, "run_federal_enrichment", run_federal_enrichment)
        job = self._find_federal_enrichment_job()

        with pytest.raises(RuntimeError, match="enrichment failed"):
            job.run_callable()

        get_connection.assert_called_once_with()
        run_federal_enrichment.assert_called_once_with(connection)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()


_EXPECTED_FEDERAL_JOB_KEYS = (
    "federal-fec-masters",
    "federal-fec-schedule-a",
    "federal-fec-committee-summary",
    "federal-congress-spine",
    "federal-fec-schedule-b",
    "federal-fec-schedule-e",
    "federal-enrichment",
    "federal-irs-527",
)


@pytest.mark.unit
class TestJobKeyPrefixFiltering:
    """Validates _filter_jobs_by_key_prefixes error path."""

    def test_nonexistent_prefix_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="No refresh jobs matched"):
            build_refresh_plan(job_key_prefixes=("nonexistent-prefix",))

    def test_repeated_prefixes_preserve_plan_order_without_duplicate_jobs(self) -> None:
        jobs = build_refresh_plan(
            job_key_prefixes=(
                "federal-fec-masters",
                "federal-congress-spine",
                "federal-enrichment",
                "federal-congress-spine",
            ),
        )

        assert tuple(job.key for job in jobs) == (
            "federal-fec-masters",
            "federal-congress-spine",
            "federal-enrichment",
        )
        assert [job.key for job in jobs].count("federal-congress-spine") == 1


@pytest.mark.unit
class TestFederalPrefixFilterContract:
    """Stage 2 contract: filtering by `federal-` selects exactly the federal
    slice the Stage 2 refresh lane targets, drops every state-, city-, and
    civic- job, deduplicates repeated prefixes, and preserves the plan order
    emitted by build_refresh_plan(). The exact federal key inventory lives
    only here — peer tests must not duplicate it."""

    def _expected_federal_order(self) -> tuple[str, ...]:
        full_plan_keys = [job.key for job in build_refresh_plan(scope="all")]
        return tuple(key for key in full_plan_keys if key in set(_EXPECTED_FEDERAL_JOB_KEYS))

    def test_expected_federal_key_inventory_matches_plan_order(self) -> None:
        assert _EXPECTED_FEDERAL_JOB_KEYS == self._expected_federal_order()

    def test_federal_prefix_selects_exact_federal_set_in_plan_order(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("federal-",))

        actual_keys = tuple(job.key for job in jobs)
        assert set(actual_keys) == set(_EXPECTED_FEDERAL_JOB_KEYS)
        assert actual_keys == self._expected_federal_order()
        for actual_key in actual_keys:
            assert not actual_key.startswith(("state-", "city-", "civic-", "civics-"))

    def test_repeated_and_overlapping_federal_prefixes_return_each_job_once(self) -> None:
        jobs = build_refresh_plan(
            job_key_prefixes=("federal-", "federal-fec-masters", "federal-"),
        )

        actual_keys = tuple(job.key for job in jobs)
        assert actual_keys == self._expected_federal_order()
        for federal_key in _EXPECTED_FEDERAL_JOB_KEYS:
            assert actual_keys.count(federal_key) == 1

    def test_federal_scope_selects_exact_federal_set_in_plan_order(self) -> None:
        jobs = build_refresh_plan(scope="federal")

        actual_keys = tuple(job.key for job in jobs)
        assert actual_keys == _EXPECTED_FEDERAL_JOB_KEYS
        assert actual_keys == self._expected_federal_order()
        assert not any(job.key.startswith(("state-", "city-", "civic-", "civics-")) for job in jobs)


@pytest.mark.unit
class TestRunnerFECDefaultOwnership:
    def test_runner_parameters_default_fec_cycle_is_current_cycle(self) -> None:
        assert RunnerParameters().fec_cycle == 2026

    def test_argument_parser_default_fec_cycle_is_current_cycle(self) -> None:
        assert build_argument_parser().parse_args([]).fec_cycle == 2026


@pytest.mark.unit
class TestFECCommitteeSummaryJobContract:
    def _find_committee_summary_job(self, *, fec_cycle: int = 2024) -> RefreshJob:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(fec_cycle=fec_cycle),
            job_key_prefixes=("federal-fec-committee-summary",),
        )
        assert len(jobs) == 1
        return jobs[0]

    def test_committee_summary_job_metadata_has_dedicated_weekly_history_key(self) -> None:
        job = self._find_committee_summary_job()

        assert job.key == "federal-fec-committee-summary"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "federal/fec"
        assert job.cadence == "weekly"
        assert job.data_source_names == (job_builders.FEC_BULK_DATA_SOURCE_NAME,)
        assert job.refresh_history_key == "federal-fec-committee-summary"

    def test_fec_cycle_2026_resolves_active_committee_summary_cycles_oldest_first(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        downloaded_cycles = self._run_committee_summary_job_and_capture_cycles(monkeypatch, fec_cycle=2026)

        assert downloaded_cycles == (2022, 2024, 2026)

    def test_fec_cycle_2024_resolves_only_current_active_committee_summary_cycle(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        downloaded_cycles = self._run_committee_summary_job_and_capture_cycles(monkeypatch, fec_cycle=2024)

        assert downloaded_cycles == (2024,)

    def test_committee_summary_job_schedules_recent_history_2022_cycle_by_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        downloaded_cycles = self._run_committee_summary_job_and_capture_cycles(monkeypatch, fec_cycle=2026)

        assert 2022 in downloaded_cycles

    def test_committee_summary_run_callable_downloads_and_dispatches_each_active_cycle(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connection = MagicMock()
        data_source_id = UUID("6f93a177-c7ca-4a16-88e6-932245a1ddaf")
        load_results = [object(), object(), object()]
        aggregate_result = 12
        urlretrieve = MagicMock()
        ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
        dispatch_load = MagicMock(side_effect=load_results)
        get_connection = MagicMock(return_value=connection)
        populate_derived_aggregates = MagicMock(return_value=aggregate_result)

        monkeypatch.setattr(job_builders, "urlretrieve", urlretrieve)
        monkeypatch.setattr(job_builders, "get_connection", get_connection)
        monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
        monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)
        monkeypatch.setattr(
            job_builders,
            "populate_committee_summary_derived_aggregates",
            populate_derived_aggregates,
        )

        job = self._find_committee_summary_job(fec_cycle=2026)
        result = job.run_callable()

        assert result == [*load_results, aggregate_result]
        assert [call.args[0] for call in urlretrieve.call_args_list] == [
            job_builders.fec_committee_summary_url(2022),
            job_builders.fec_committee_summary_url(2024),
            job_builders.fec_committee_summary_url(2026),
        ]
        downloaded_paths = [Path(call.args[1]) for call in urlretrieve.call_args_list]
        assert [path.name for path in downloaded_paths] == [
            "committee_summary_2022.csv",
            "committee_summary_2024.csv",
            "committee_summary_2026.csv",
        ]

        get_connection.assert_called_once_with()
        connection.transaction.assert_called_once_with()
        ensure_fec_bulk_data_source.assert_called_once_with(connection)
        connection.close.assert_called_once_with()

        assert dispatch_load.call_count == 3
        assert [call.kwargs["conn"] for call in dispatch_load.call_args_list] == [connection, connection, connection]
        assert [call.kwargs["data_source_id"] for call in dispatch_load.call_args_list] == [
            data_source_id,
            data_source_id,
            data_source_id,
        ]

        for cycle, path, call in zip((2022, 2024, 2026), downloaded_paths, dispatch_load.call_args_list):
            assert call.kwargs["config"] == job_builders.CliConfig(
                mode="single",
                cycle=cycle,
                file_type="committee_summary",
                path=path,
                directory=None,
                batch_size=1000,
                limit=None,
                graph_enabled=False,
                with_transactions=False,
            )
            assert call.kwargs["request"] == job_builders.LoadRequest(
                file_type="committee_summary",
                path=path,
            )

        populate_derived_aggregates.assert_called_once_with(connection, cycles=(2022, 2024, 2026))

    def _run_committee_summary_job_and_capture_cycles(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        fec_cycle: int,
    ) -> tuple[int, ...]:
        monkeypatch.setattr(job_builders, "urlretrieve", MagicMock())
        monkeypatch.setattr(job_builders, "get_connection", MagicMock(return_value=MagicMock()))
        monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", MagicMock(return_value=UUID(int=0)))
        monkeypatch.setattr(job_builders, "dispatch_load", MagicMock())

        self._find_committee_summary_job(fec_cycle=fec_cycle).run_callable()

        return tuple(call.kwargs["config"].cycle for call in job_builders.dispatch_load.call_args_list)


@pytest.mark.unit
class TestFECScheduleAJobContract:
    def _find_schedule_a_job(self, *, fec_cycle: int = 2024, fec_limit: int = 100) -> RefreshJob:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(fec_cycle=fec_cycle, fec_limit=fec_limit),
            job_key_prefixes=("federal-fec-schedule-a",),
        )
        assert len(jobs) == 1
        return jobs[0]

    def test_schedule_a_run_callable_dispatches_each_active_fec_cycle_oldest_first(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        connection = MagicMock()
        data_source_id = UUID("7d9153fd-a974-4984-963d-64d811892e24")
        load_results = [object(), object()]
        archive_paths = {
            2024: Path("/tmp/itcont_2024.zip"),
            2026: Path("/tmp/itcont_2026.zip"),
        }
        download_fec_bulk_file_to_cache = MagicMock(
            side_effect=lambda _repo_root, *, cycle, **_kwargs: archive_paths[cycle]
        )
        ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
        dispatch_load = MagicMock(side_effect=load_results)
        get_connection = MagicMock(return_value=connection)

        monkeypatch.setattr(job_builders, "download_fec_bulk_file_to_cache", download_fec_bulk_file_to_cache)
        monkeypatch.setattr(job_builders, "get_connection", get_connection)
        monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
        monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

        result = self._find_schedule_a_job(fec_cycle=2026, fec_limit=50).run_callable()

        assert result == load_results
        assert [call.kwargs["cycle"] for call in download_fec_bulk_file_to_cache.call_args_list] == [2024, 2026]
        assert [call.kwargs["file_type"] for call in download_fec_bulk_file_to_cache.call_args_list] == [
            "itcont",
            "itcont",
        ]
        assert [call.kwargs["downloader"] for call in download_fec_bulk_file_to_cache.call_args_list] == [
            job_builders.urlretrieve,
            job_builders.urlretrieve,
        ]

        get_connection.assert_called_once_with()
        connection.transaction.assert_called_once_with()
        ensure_fec_bulk_data_source.assert_called_once_with(connection)
        connection.close.assert_called_once_with()

        assert dispatch_load.call_count == 2
        assert [call.kwargs["conn"] for call in dispatch_load.call_args_list] == [connection, connection]
        assert [call.kwargs["data_source_id"] for call in dispatch_load.call_args_list] == [
            data_source_id,
            data_source_id,
        ]

        for cycle, call in zip((2024, 2026), dispatch_load.call_args_list):
            archive_path = archive_paths[cycle]
            assert call.kwargs["config"] == job_builders.CliConfig(
                mode="single",
                cycle=cycle,
                file_type="itcont",
                path=archive_path,
                directory=None,
                batch_size=1000,
                limit=50,
                graph_enabled=False,
                with_transactions=False,
                transactions_only=True,
                spine_only=True,
                min_date=job_builders.date(2022, 1, 1),
            )
            assert call.kwargs["request"] == job_builders.LoadRequest(file_type="itcont", path=archive_path)


@pytest.mark.unit
class TestNCIEDocumentIndexJobContract:
    def test_plan_contains_nc_ie_document_index_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-document-index",),
        )

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "state-nc-ie-document-index"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "state/NC"
        assert "North Carolina SBoE IE Document Index" in job.data_source_names

    def test_nc_ie_job_run_callable_is_zero_arg_callable(self) -> None:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-document-index",),
        )
        job = jobs[0]
        assert callable(job.run_callable)
        signature = inspect.signature(job.run_callable)
        required_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert required_params == []


@pytest.mark.unit
class TestNCCommitteeDiscoveryJobContract:
    def test_plan_contains_nc_committee_discovery_job_with_config_owned_metadata(self) -> None:
        config = load_jurisdiction_config(_NC_CONFIG_PATH)
        source_config = next(
            source for source in config.data_sources if source.name == NC_COMMITTEE_DOCUMENT_SOURCE_NAME
        )
        jobs = build_refresh_plan(job_key_prefixes=("state-nc-committee-discovery",))

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "state-nc-committee-discovery"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "state/NC"
        assert job.data_source_names == (source_config.name,)
        assert job.cadence == source_config.update_frequency


@pytest.mark.unit
class TestNCIEDetailTransactionJobContract:
    def test_plan_contains_nc_ie_transaction_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-transactions",),
        )

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "state-nc-ie-transactions"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "state/NC"
        assert "North Carolina SBoE IE Document Index" in job.data_source_names

    def test_nc_ie_transaction_job_run_callable_is_zero_arg_callable(self) -> None:
        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-transactions",),
        )

        assert len(jobs) == 1
        job = jobs[0]
        assert callable(job.run_callable)
        signature = inspect.signature(job.run_callable)
        required_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert required_params == []

    def test_nc_ie_transaction_job_run_callable_uses_run_nc_refresh_ie_transactions(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        run_nc_refresh = MagicMock()
        monkeypatch.setattr(job_builders, "run_nc_refresh", run_nc_refresh)

        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                nc_ie_document_index_path=Path("/tmp/nc-ie-document-index.csv"),
            ),
            job_key_prefixes=("state-nc-ie-transactions",),
        )
        assert len(jobs) == 1

        jobs[0].run_callable()

        run_nc_refresh.assert_called_once_with(data_type="ie-transactions")

    def test_plan_does_not_emit_nc_ie_transactions_job_without_ie_document_index_path(self) -> None:
        with pytest.raises(ValueError, match="No refresh jobs matched"):
            build_refresh_plan(job_key_prefixes=("state-nc-ie-transactions",))


@pytest.mark.unit
class TestPHLCityJobContract:
    """Contract: build_refresh_plan() must produce city-phl-contributions and
    city-phl-expenditures jobs (PHL has two distinct Carto SQL tables)."""

    def test_plan_contains_phl_contributions_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("city-phl-contributions",))
        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "city-phl-contributions"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "municipality/PHL"
        assert "PHL Campaign Finance Contributions" in job.data_source_names

    def test_plan_contains_phl_expenditures_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("city-phl-expenditures",))
        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "city-phl-expenditures"
        assert job.domain == "campaign_finance"
        assert job.jurisdiction == "municipality/PHL"
        assert "PHL Campaign Finance Expenditures" in job.data_source_names

    def test_phl_jobs_run_callables_are_zero_arg(self) -> None:
        for prefix in ("city-phl-contributions", "city-phl-expenditures"):
            jobs = build_refresh_plan(job_key_prefixes=(prefix,))
            assert len(jobs) == 1, f"missing job for prefix {prefix!r}"
            job = jobs[0]
            assert callable(job.run_callable)
            sig = inspect.signature(job.run_callable)
            required = [
                p
                for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ]
            assert required == [], (
                f"{prefix} run_callable must be zero-arg; required params: {[p.name for p in required]}"
            )


@pytest.mark.unit
class TestNCCivicCandidateListingJobContract:
    def test_plan_contains_civic_candidate_listing_job_with_correct_metadata(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civic-nc-candidate-listing",))

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "civic-nc-candidate-listing"
        assert job.domain == "civics"
        assert job.jurisdiction == "state/NC"
        assert job.data_source_names == (_NCSBE_DATA_SOURCE_NAME,)

    def test_civic_candidate_listing_job_run_callable_is_zero_arg_callable(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civic-nc-candidate-listing",))
        job = jobs[0]

        assert callable(job.run_callable)
        signature = inspect.signature(job.run_callable)
        required_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert required_params == []

    def test_civic_candidate_listing_job_run_callable_threads_year_and_optional_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        load_candidate_listing_from_source = MagicMock()
        monkeypatch.setattr(
            job_builders,
            "load_candidate_listing_from_source",
            load_candidate_listing_from_source,
        )
        candidate_listing_path = Path("/tmp/nc-candidate-listing-fixture.csv")

        jobs = build_refresh_plan(
            parameters=RunnerParameters(
                year_from=2024,
                candidate_listing_path=candidate_listing_path,
            ),
            job_key_prefixes=("civic-nc-candidate-listing",),
        )
        assert len(jobs) == 1

        jobs[0].run_callable()

        load_candidate_listing_from_source.assert_called_once_with(
            year_from=2024,
            candidate_listing_path=candidate_listing_path,
        )

    @pytest.mark.parametrize(
        ("now", "expected_cadence"),
        [
            (datetime(2025, 12, 18, 12, 0, tzinfo=timezone.utc), "daily"),
            (datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc), "quarterly"),
        ],
    )
    def test_civic_candidate_listing_job_cadence_tracks_nc_filing_window(
        self,
        now: datetime,
        expected_cadence: str,
    ) -> None:
        jobs = build_refresh_plan(
            now=now,
            job_key_prefixes=("civic-nc-candidate-listing",),
        )
        assert len(jobs) == 1
        assert jobs[0].cadence == expected_cadence

    @pytest.mark.parametrize(
        ("now", "expected_cadence"),
        [
            (datetime(2025, 12, 18, 12, 0, tzinfo=timezone.utc), "daily"),
            (datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc), "quarterly"),
        ],
    )
    def test_priority_scope_includes_civic_candidate_listing_with_calendar_cadence(
        self,
        now: datetime,
        expected_cadence: str,
    ) -> None:
        jobs = build_refresh_plan(
            scope="priority",
            now=now,
            job_key_prefixes=("civic-nc-candidate-listing",),
        )
        assert len(jobs) == 1
        assert jobs[0].key == "civic-nc-candidate-listing"
        assert jobs[0].cadence == expected_cadence

    def test_civic_candidate_listing_job_resolves_cadence_using_explicit_calendar_year(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        resolve_candidate_listing_refresh_cadence = MagicMock(return_value="daily")
        monkeypatch.setattr(
            job_builders,
            "resolve_candidate_listing_refresh_cadence",
            resolve_candidate_listing_refresh_cadence,
        )

        now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
        build_refresh_plan(
            now=now,
            job_key_prefixes=("civic-nc-candidate-listing",),
        )

        resolve_candidate_listing_refresh_cadence.assert_called_once_with(
            year=2026,
            on_date=now.date(),
        )

    def test_civic_candidate_listing_job_december_run_does_not_require_missing_next_year_calendar(
        self,
    ) -> None:
        jobs = build_refresh_plan(
            now=datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc),
            job_key_prefixes=("civic-nc-candidate-listing",),
        )

        assert len(jobs) == 1
        assert jobs[0].key == "civic-nc-candidate-listing"
        assert jobs[0].cadence == "quarterly"

    def test_civic_candidate_listing_job_pre_december_uses_upcoming_election_calendar(
        self,
    ) -> None:
        """Pre-December runs in the year before an election must bind cadence
        to the upcoming election year's calendar — not the wall-clock year
        that has no calendar file on disk."""
        jobs = build_refresh_plan(
            now=datetime(2025, 11, 30, 12, 0, tzinfo=timezone.utc),
            job_key_prefixes=("civic-nc-candidate-listing",),
        )

        assert len(jobs) == 1
        assert jobs[0].key == "civic-nc-candidate-listing"
        # Nov 30 2025 falls outside the 2026 calendar's filing window
        # (candidate_filing_open=2025-12-01), so cadence is quarterly.
        assert jobs[0].cadence == "quarterly"

    def test_civic_candidate_listing_job_pre_december_resolves_cadence_using_upcoming_election_year(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        resolve_candidate_listing_refresh_cadence = MagicMock(return_value="quarterly")
        monkeypatch.setattr(
            job_builders,
            "resolve_candidate_listing_refresh_cadence",
            resolve_candidate_listing_refresh_cadence,
        )

        now = datetime(2025, 11, 30, 12, 0, tzinfo=timezone.utc)
        build_refresh_plan(
            now=now,
            job_key_prefixes=("civic-nc-candidate-listing",),
        )

        resolve_candidate_listing_refresh_cadence.assert_called_once_with(
            year=2026,
            on_date=now.date(),
        )


@pytest.mark.unit
class TestNCPastResultsJobContract:
    _EXPECTED_NC_PAST_RESULTS_SOURCE_NAMES = (
        "NCSBE ENRS nc_ncsbe_enrs_2022_11_08_general",
        "NCSBE ENRS nc_ncsbe_enrs_2024_03_05_primary",
        "NCSBE ENRS nc_ncsbe_enrs_2024_11_05_general",
    )

    def test_plan_contains_canonical_nc_past_results_job(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civics-nc-past-results-2022-2024",))

        assert len(jobs) == 1
        job = jobs[0]
        assert job.key == "civics-nc-past-results-2022-2024"
        assert job.domain == "civics"
        assert job.jurisdiction == "us/nc"
        assert job.data_source_names == self._EXPECTED_NC_PAST_RESULTS_SOURCE_NAMES

    def test_nc_past_results_job_run_callable_is_zero_arg(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civics-nc-past-results-2022-2024",))

        assert len(jobs) == 1
        signature = inspect.signature(jobs[0].run_callable)
        required_parameters = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert required_parameters == []

    def test_nc_past_results_job_filters_runtime_inputs_to_2022_and_2024_fixtures_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runnable_paths = collect_ncsbe_refresh_raw_csv_paths()
        jobs = build_refresh_plan(job_key_prefixes=("civics-nc-past-results-2022-2024",))
        job = jobs[0]

        selected_fixtures = sorted(path.name for path in runnable_paths)
        assert selected_fixtures == [
            "enrs_2022_11_08_general_sample.csv",
            "enrs_2024_03_05_primary_sample.csv",
            "enrs_2024_11_05_general_sample.csv",
        ]
        assert "enrs_2020_11_03_general_sample.csv" not in selected_fixtures
        assert callable(job.run_callable)

        from domains.civics.loaders import ncsbe_results

        monkeypatch.setattr(
            ncsbe_results,
            "_refresh_sources_2022_2024",
            lambda: [
                ncsbe_results.NcsbeSourceMetadata(
                    source_id="nc_ncsbe_enrs_2024_11_05_general",
                    election_date="2024-11-05",
                    election_label="General Election",
                    fixture_file="../escaped.csv",
                    source_url="https://example.test/escaped.csv",
                )
            ],
        )

        with pytest.raises(ValueError, match="must stay within the canonical raw-extract directory"):
            ncsbe_results.collect_ncsbe_refresh_raw_csv_paths()


@pytest.mark.unit
class TestCivicRosterJobContract:
    def test_stage2_civic_roster_prefix_filter_emits_exact_job_keys(self) -> None:
        jobs = build_refresh_plan(job_key_prefixes=("civic-rosters",))

        assert tuple(sorted(job.key for job in jobs)) == tuple(sorted(_EXPECTED_STAGE2_CIVIC_ROSTER_KEYS))

    def test_campaign_finance_keys_remain_unchanged_after_civic_roster_wiring(self) -> None:
        all_jobs = build_refresh_plan()
        campaign_finance_keys = tuple(sorted(job.key for job in all_jobs if job.domain == "campaign_finance"))

        assert campaign_finance_keys == _EXPECTED_CAMPAIGN_FINANCE_KEYS

    def test_civic_roster_templates_keep_data_source_and_job_jurisdictions_aligned(self) -> None:
        for template in civic_roster_refresh_templates():
            assert template.refresh_jurisdiction is not None
            assert template.data_source_jurisdiction == template.refresh_jurisdiction


@pytest.mark.unit
class TestOfficialRosterJobContract:
    """Contract: build_refresh_plan() must emit one roster refresh job per registered source."""

    def _expected_roster_metadata_by_key(self) -> dict[str, object]:
        return {f"civics-roster-{metadata.source_id}": metadata for metadata in list_nc_roster_source_metadata()}

    def test_plan_contains_one_roster_job_for_each_registered_roster_source(self) -> None:
        expected_by_key = self._expected_roster_metadata_by_key()
        jobs = build_refresh_plan()
        roster_jobs = [job for job in jobs if job.key.startswith("civics-roster-")]

        assert len(roster_jobs) == len(expected_by_key)
        assert {job.key for job in roster_jobs} == set(expected_by_key)

    def test_key_prefix_filter_isolates_roster_jobs(self) -> None:
        expected_by_key = self._expected_roster_metadata_by_key()
        jobs = build_refresh_plan(job_key_prefixes=("civics-roster-",))

        assert len(jobs) == len(expected_by_key)
        assert all(job.key.startswith("civics-roster-") for job in jobs)
        assert {job.key for job in jobs} == set(expected_by_key)

    def test_roster_job_metadata_matches_registered_roster_source_metadata(self) -> None:
        expected_by_key = self._expected_roster_metadata_by_key()
        jobs = build_refresh_plan(job_key_prefixes=("civics-roster-",))

        for job in jobs:
            metadata = expected_by_key[job.key]
            assert job.domain == "civics"
            assert job.jurisdiction == metadata.jurisdiction
            assert job.cadence == metadata.cadence
            assert job.data_source_names == (metadata.name,)
            assert callable(job.run_callable)

            signature = inspect.signature(job.run_callable)
            required_params = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.default is inspect.Parameter.empty
                and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ]
            assert required_params == []

    def test_roster_source_templates_include_all_registered_roster_sources(self) -> None:
        registered_source_ids = {metadata.source_id for metadata in list_nc_roster_source_metadata()}
        template_source_ids = {template.registry_source_id for template in roster_source_templates()}

        assert registered_source_ids <= template_source_ids
