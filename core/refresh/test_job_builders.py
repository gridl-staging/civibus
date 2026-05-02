"""Contract tests for IRS 527 refresh job wiring in build_refresh_plan()."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.refresh import job_builders
from core.refresh.job_builders import build_refresh_plan
from core.refresh.runner import RefreshJob, RunnerParameters
from domains.civics.loaders.ncsbe_candidate_listing import _NCSBE_DATA_SOURCE_NAME
from domains.civics.loaders.ncsbe_results import collect_ncsbe_refresh_raw_csv_paths
from domains.civics.loaders.official_rosters.source_templates import civic_roster_refresh_templates
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
class TestJobKeyPrefixFiltering:
    """Validates _filter_jobs_by_key_prefixes error path."""

    def test_nonexistent_prefix_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="No refresh jobs matched"):
            build_refresh_plan(job_key_prefixes=("nonexistent-prefix",))


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
                p for p in sig.parameters.values()
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
        campaign_finance_keys = tuple(
            sorted(job.key for job in all_jobs if job.domain == "campaign_finance")
        )

        assert campaign_finance_keys == _EXPECTED_CAMPAIGN_FINANCE_KEYS

    def test_civic_roster_templates_keep_data_source_and_job_jurisdictions_aligned(self) -> None:
        for template in civic_roster_refresh_templates():
            assert template.refresh_jurisdiction is not None
            assert template.data_source_jurisdiction == template.refresh_jurisdiction


@pytest.mark.unit
class TestOfficialRosterJobContract:
    """Contract: build_refresh_plan() must emit one roster refresh job per registered source."""

    def _expected_roster_metadata_by_key(self) -> dict[str, object]:
        return {
            f"civics-roster-{metadata.source_id}": metadata
            for metadata in list_nc_roster_source_metadata()
        }

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
