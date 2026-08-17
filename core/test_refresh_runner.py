from __future__ import annotations

import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import psycopg
import pytest

from core.refresh import job_builders, runner
from core.refresh.test_job_builders import _EXPECTED_WEEKLY_FEDERAL_SCOPE_JOB_KEYS
from domains.campaign_finance.ingest.candidate_summary_loader import update_candidate_person_link
from domains.campaign_finance.ingest.federal_spine_loader import SpineLoadResult
from domains.civics.loaders.ncsbe_results import NcsbeResultsLoadSummary
from domains.civics.loaders.official_rosters.source_registry import list_nc_roster_source_metadata
from test_support.donor_search_fixture import (
    cleanup_donor_search_fixture,
    fetch_full_scope_donor_search_counts,
    seed_full_scope_skewed_donor_search_fixture,
)


def _job_for_tests(
    *,
    key: str,
    run_callable: MagicMock | None = None,
    refresh_history_key: str | None = None,
    activity_denominator_result_field: str | None = None,
) -> runner.RefreshJob:
    return runner.RefreshJob(
        key=key,
        domain="campaign_finance",
        jurisdiction="state/CO",
        cadence="daily",
        data_source_names=("TRACER Bulk Download — Contributions",),
        run_callable=run_callable or MagicMock(),
        refresh_history_key=refresh_history_key,
        activity_denominator_result_field=activity_denominator_result_field,
    )


def _download_job_call(
    state_code: str,
    data_types: tuple[str, ...],
    refresh_callable: object,
    **refresh_kwargs: object,
) -> dict[str, object]:
    return {
        "jurisdiction": f"state/{state_code}",
        "key_prefix": f"state-{state_code.lower()}",
        "data_types": data_types,
        "refresh_callable": refresh_callable,
        **refresh_kwargs,
    }


def test_build_refresh_plan_all_scope_emits_canonical_stage6_job_keys() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    job_keys = {job.key for job in jobs}
    expected_job_keys = {
        "federal-fec-schedule-a",
        "federal-fec-masters",
        "federal-fec-schedule-b",
        "federal-fec-committee-summary",
        "federal-fec-races",
        "federal-congress-spine",
        "federal-donor-search-rollup",
        "federal-enrichment",
        "federal-fec-schedule-e",
        "federal-irs-527",
        "federal-geometry-probe",
        "state-al-contributions",
        "state-al-expenditures",
        "state-ca-refresh",
        "state-co-contributions",
        "state-co-expenditures",
        "state-fl-contributions",
        "state-fl-expenditures",
        "state-fl-transfers",
        "state-fl-other",
        "state-ga-contributions",
        "state-ga-expenditures",
        "state-il-contributions",
        "state-il-expenditures",
        "state-in-contributions",
        "state-in-expenditures",
        "state-ky-expenditures",
        "state-ky-contributions-5-17-2022",
        "state-ky-contributions-11-8-2022",
        "state-ky-contributions-5-16-2023",
        "state-ky-contributions-11-7-2023",
        "state-ky-contributions-5-21-2024",
        "state-ky-contributions-11-5-2024",
        "state-ky-contributions-5-19-2026",
        "state-la-contributions",
        "state-la-expenditures",
        "state-la-loans",
        "state-ma-contributions",
        "state-ma-expenditures",
        "state-mn-contributions",
        "state-mn-expenditures",
        "state-mn-independent_expenditures",
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
        "state-pa-expenditures",
        "state-pa-debts",
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
        "city-la-transactions",
        "city-nyc-transactions",
        "city-phl-contributions",
        "city-phl-expenditures",
        "city-sf-transactions",
        "state-nc-committee-discovery",
        "civic-nc-candidate-listing",
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
    }
    expected_job_keys.update({f"civics-roster-{metadata.source_id}" for metadata in list_nc_roster_source_metadata()})

    assert job_keys == expected_job_keys

    assert len(job_keys) == 115
    assert "state-nc-ie-transactions" not in job_keys
    assert "state-nc-transactions" not in job_keys
    assert "state-nc-ie-document-index" not in job_keys
    assert "civics-nc-past-results-2022-2024" not in job_keys


def test_federal_plan_wires_committee_summary_after_schedule_a() -> None:
    job_keys = tuple(job.key for job in job_builders.build_refresh_plan(scope="federal"))

    assert job_keys.index("federal-fec-schedule-a") < job_keys.index("federal-fec-committee-summary")


def test_build_refresh_plan_adds_nc_jobs_from_independent_input_paths() -> None:
    committee_docs_path = Path("/tmp/stage5_nc_committee_docs_27075.csv")
    ie_document_index_path = Path("/tmp/stage5_nc_ie_document_index_27075.csv")

    jobs_without_nc = job_builders.build_refresh_plan(scope="all")
    jobs_with_transaction_nc = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="STA-C3219N-C-001",
            nc_committee_name="NC REALTORS PAC",
        ),
    )
    jobs_with_ie_nc = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_ie_document_index_path=ie_document_index_path,
        ),
    )
    jobs_with_both_nc = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="STA-C3219N-C-001",
            nc_committee_name="NC REALTORS PAC",
            nc_ie_document_index_path=ie_document_index_path,
        ),
    )

    job_keys_without_nc = {job.key for job in jobs_without_nc}
    job_keys_with_transaction_nc = {job.key for job in jobs_with_transaction_nc}
    job_keys_with_ie_nc = {job.key for job in jobs_with_ie_nc}
    job_keys_with_both_nc = {job.key for job in jobs_with_both_nc}

    assert len(job_keys_without_nc) == 115
    assert len(job_keys_with_transaction_nc) == 116
    assert len(job_keys_with_ie_nc) == 117
    assert len(job_keys_with_both_nc) == 118
    assert "state-nc-ie-transactions" not in job_keys_without_nc
    assert "state-nc-ie-transactions" not in job_keys_with_transaction_nc
    assert "state-nc-ie-transactions" in job_keys_with_ie_nc
    assert "state-nc-ie-transactions" in job_keys_with_both_nc
    assert "state-nc-ie-document-index" not in job_keys_without_nc
    assert "state-nc-ie-document-index" not in job_keys_with_transaction_nc
    assert "state-nc-ie-document-index" in job_keys_with_ie_nc
    assert "state-nc-ie-document-index" in job_keys_with_both_nc
    assert "state-nc-transactions" not in job_keys_without_nc
    assert "state-nc-transactions" in job_keys_with_transaction_nc
    assert "state-nc-transactions" not in job_keys_with_ie_nc
    assert "state-nc-transactions" in job_keys_with_both_nc
    assert "civics-nc-past-results-2022-2024" not in job_keys_without_nc
    assert "civics-nc-past-results-2022-2024" not in job_keys_with_transaction_nc
    assert "civics-nc-past-results-2022-2024" not in job_keys_with_ie_nc
    assert "civics-nc-past-results-2022-2024" not in job_keys_with_both_nc


def test_build_refresh_plan_wires_stage_locked_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    run_co_refresh = MagicMock()
    run_pa_refresh = MagicMock()
    run_ne_refresh = MagicMock()
    run_la_refresh = MagicMock()
    run_ga_refresh = MagicMock()
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(job_builders, "run_co_refresh", run_co_refresh)
    monkeypatch.setattr(job_builders, "run_pa_refresh", run_pa_refresh)
    monkeypatch.setattr(job_builders, "run_ne_refresh", run_ne_refresh)
    monkeypatch.setattr(job_builders, "run_la_refresh", run_la_refresh)
    monkeypatch.setattr(job_builders, "run_ga_refresh", run_ga_refresh)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            fec_cycle=2024,
            fec_limit=50,
            co_year=2026,
            pa_year=2025,
            ga_candidate="Hatfield",
            ga_date_start="01/01/2025",
            ga_date_end="12/31/2025",
        ),
        now=now,
    )
    jobs_by_key = {job.key: job for job in jobs}

    jobs_by_key["state-co-contributions"].run_callable()
    jobs_by_key["state-pa-contributions"].run_callable()
    jobs_by_key["state-ne-contributions"].run_callable()
    jobs_by_key["state-la-contributions"].run_callable()
    jobs_by_key["state-ga-contributions"].run_callable()

    run_co_refresh.assert_called_once_with(year=2026, data_type="contributions", download=True, allow_insecure_tls=True)
    run_pa_refresh.assert_called_once_with(year=2025, data_type="contributions", download=True)
    run_ne_refresh.assert_called_once_with(year=2026, data_type="contributions", download=True)
    run_la_refresh.assert_called_once_with(year=2026, data_type="contributions", download=True)
    run_ga_refresh.assert_called_once_with(
        candidate="Hatfield",
        date_start="01/01/2025",
        date_end="12/31/2025",
        data_type="contributions",
        download=True,
    )


def test_build_refresh_plan_wires_federal_schedule_a_bulk_job_parameters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = tmp_path / "fec-cache-root"
    connection = MagicMock()
    data_source_id = UUID("6f93a177-c7ca-4a16-88e6-932245a1ddaf")
    load_result = object()

    def _fake_download(url: str, destination_path: Path) -> tuple[Path, object]:
        with zipfile.ZipFile(destination_path, "w") as archive:
            archive.writestr("itcont24.txt", "ignored")
        return destination_path, None

    urlretrieve = MagicMock(side_effect=_fake_download)
    ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
    dispatch_load = MagicMock(return_value=load_result)
    get_connection = MagicMock(return_value=connection)

    monkeypatch.setattr(job_builders, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(job_builders, "urlretrieve", urlretrieve)
    monkeypatch.setattr(job_builders, "get_connection", get_connection)
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    jobs_by_key = {job.key: job for job in jobs}
    job = jobs_by_key["federal-fec-schedule-a"]

    result = job.run_callable()

    assert result == load_result
    assert job.data_source_names == (job_builders.FEC_BULK_DATA_SOURCE_NAME,)
    assert urlretrieve.call_args.args[0] == job_builders.fec_baseline_url(2024, "itcont")
    assert Path(urlretrieve.call_args.args[1]).name == "itcont24.zip.part"

    get_connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    ensure_fec_bulk_data_source.assert_called_once_with(connection)
    connection.close.assert_called_once_with()

    dispatch_load.assert_called_once()
    dispatch_call = dispatch_load.call_args.kwargs
    config = dispatch_call["config"]
    request = dispatch_call["request"]

    assert dispatch_call["conn"] is connection
    assert dispatch_call["data_source_id"] == data_source_id
    assert config.mode == "single"
    assert config.cycle == 2024
    assert config.file_type == "itcont"
    assert config.batch_size == 1000
    assert config.limit == 50
    assert config.graph_enabled is False
    assert config.with_transactions is False
    assert config.transactions_only is True
    assert config.spine_only is True
    assert config.min_date == date(2022, 1, 1)
    assert request.file_type == "itcont"
    assert request.path == config.path
    assert request.path == repo_root / "data" / "fec" / "bulk" / "2024" / "itcont24.zip"


def test_federal_schedule_a_reuses_cached_bulk_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cached_file = tmp_path / "data" / "fec" / "bulk" / "2024" / "itcont24.zip"
    cached_file.parent.mkdir(parents=True)
    cached_file.write_bytes(b"cached")
    connection = MagicMock()

    monkeypatch.setattr(job_builders, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(job_builders, "urlretrieve", MagicMock())
    monkeypatch.setattr(job_builders, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", MagicMock(return_value=uuid4()))
    dispatch_load = MagicMock(return_value=object())
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    {job.key: job for job in jobs}["federal-fec-schedule-a"].run_callable()

    job_builders.urlretrieve.assert_not_called()
    assert dispatch_load.call_args.kwargs["request"].path == cached_file


def test_federal_schedule_a_uses_refresh_data_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    refresh_data_dir = tmp_path / "fly-data"
    connection = MagicMock()
    load_result = object()

    def _fake_download(url: str, destination_path: Path) -> tuple[Path, object]:
        with zipfile.ZipFile(destination_path, "w") as archive:
            archive.writestr("itcont24.txt", "ignored")
        return destination_path, None

    monkeypatch.setenv("CIVIBUS_REFRESH_DATA_DIR", str(refresh_data_dir))
    monkeypatch.setattr(job_builders, "urlretrieve", MagicMock(side_effect=_fake_download))
    monkeypatch.setattr(job_builders, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", MagicMock(return_value=uuid4()))
    dispatch_load = MagicMock(return_value=load_result)
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="federal",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    result = {job.key: job for job in jobs}["federal-fec-schedule-a"].run_callable()

    assert result == load_result
    assert dispatch_load.call_args.kwargs["request"].path == (
        refresh_data_dir / "fec" / "bulk" / "2024" / "itcont24.zip"
    )


def test_federal_temporary_refresh_directory_uses_refresh_data_dir_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    refresh_data_dir = tmp_path / "fly-data"
    monkeypatch.setenv("CIVIBUS_REFRESH_DATA_DIR", str(refresh_data_dir))

    with job_builders._temporary_refresh_directory(prefix="refresh-contract-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        assert temp_dir_path.parent == refresh_data_dir / "tmp"
        assert temp_dir_path.name.startswith("refresh-contract-")
        assert temp_dir_path.exists()

    assert not temp_dir_path.exists()


def test_build_refresh_plan_wires_federal_schedule_b_job_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    data_source_id = UUID("6f93a177-c7ca-4a16-88e6-932245a1ddaf")
    load_result = object()

    def _fake_download(url: str, destination_path: Path) -> tuple[Path, object]:
        with zipfile.ZipFile(destination_path, "w") as archive:
            archive.writestr("oppexp24.txt", "ignored")
        return destination_path, None

    urlretrieve = MagicMock(side_effect=_fake_download)
    ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
    dispatch_load = MagicMock(return_value=load_result)
    get_connection = MagicMock(return_value=connection)

    monkeypatch.setattr(job_builders, "urlretrieve", urlretrieve)
    monkeypatch.setattr(job_builders, "get_connection", get_connection)
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    jobs_by_key = {job.key: job for job in jobs}

    result = jobs_by_key["federal-fec-schedule-b"].run_callable()

    assert result is load_result
    assert urlretrieve.call_args.args[0] == job_builders.fec_schedule_b_url(2024)
    assert Path(urlretrieve.call_args.args[1]).name == "oppexp24.zip"

    get_connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    ensure_fec_bulk_data_source.assert_called_once_with(connection)
    connection.close.assert_called_once_with()

    dispatch_load.assert_called_once()
    dispatch_call = dispatch_load.call_args.kwargs
    config = dispatch_call["config"]
    request = dispatch_call["request"]

    assert dispatch_call["conn"] is connection
    assert dispatch_call["data_source_id"] == data_source_id
    assert config.mode == "single"
    assert config.cycle == 2024
    assert config.file_type == "schedule_b"
    assert config.batch_size == 1000
    assert config.limit == 50
    assert config.graph_enabled is False
    assert config.with_transactions is False
    assert request.file_type == "schedule_b"
    assert request.path == config.path


def test_build_refresh_plan_wires_federal_fec_masters_job_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    data_source_id = UUID("6f93a177-c7ca-4a16-88e6-932245a1ddaf")
    load_results = [object(), object(), object(), object()]
    downloaded_payloads = {
        "cm": "cm24.txt",
        "cn": "cn24.txt",
        "ccl": "ccl24.txt",
        "weball": "weball24.txt",
    }

    def _fake_download(url: str, destination_path: Path) -> tuple[Path, object]:
        file_type = destination_path.stem.removesuffix("24")
        with zipfile.ZipFile(destination_path, "w") as archive:
            archive.writestr(downloaded_payloads[file_type], "ignored")
        return destination_path, None

    urlretrieve = MagicMock(side_effect=_fake_download)
    ensure_fec_bulk_data_source = MagicMock(return_value=data_source_id)
    dispatch_load = MagicMock(side_effect=load_results)
    get_connection = MagicMock(return_value=connection)

    monkeypatch.setattr(job_builders, "urlretrieve", urlretrieve)
    monkeypatch.setattr(job_builders, "get_connection", get_connection)
    monkeypatch.setattr(job_builders, "ensure_fec_bulk_data_source", ensure_fec_bulk_data_source)
    monkeypatch.setattr(job_builders, "dispatch_load", dispatch_load)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(fec_cycle=2024, fec_limit=50),
    )
    job = {candidate.key: candidate for candidate in jobs}["federal-fec-masters"]

    result = job.run_callable()

    assert result == load_results
    assert job.domain == "campaign_finance"
    assert job.jurisdiction == "federal/fec"
    assert job.cadence == "weekly"
    assert job.data_source_names == (job_builders.FEC_BULK_DATA_SOURCE_NAME,)
    assert job.refresh_history_key == "federal-fec-masters"
    assert [call.args[0] for call in urlretrieve.call_args_list] == [
        job_builders.fec_baseline_url(2024, "cm"),
        job_builders.fec_baseline_url(2024, "cn"),
        job_builders.fec_baseline_url(2024, "ccl"),
        job_builders.fec_weball_url(2024),
    ]
    downloaded_paths = [Path(call.args[1]) for call in urlretrieve.call_args_list]
    assert [path.name for path in downloaded_paths] == ["cm24.zip", "cn24.zip", "ccl24.zip", "weball24.zip"]

    get_connection.assert_called_once_with()
    connection.transaction.assert_called_once_with()
    ensure_fec_bulk_data_source.assert_called_once_with(connection)
    connection.close.assert_called_once_with()

    assert dispatch_load.call_count == 4
    assert [call.kwargs["conn"] for call in dispatch_load.call_args_list] == [connection] * 4
    assert [call.kwargs["data_source_id"] for call in dispatch_load.call_args_list] == [data_source_id] * 4
    assert [call.kwargs["request"].file_type for call in dispatch_load.call_args_list] == [
        "cm",
        "cn",
        "ccl",
        "weball",
    ]
    assert [call.kwargs["request"].path for call in dispatch_load.call_args_list] == downloaded_paths

    for file_type, path, call in zip(("cm", "cn", "ccl", "weball"), downloaded_paths, dispatch_load.call_args_list):
        assert call.kwargs["config"] == job_builders.CliConfig(
            mode="single",
            cycle=2024,
            file_type=file_type,
            path=path,
            directory=None,
            batch_size=1000,
            limit=None,
            graph_enabled=False,
            with_transactions=False,
        )
        assert call.kwargs["request"].path == path


def test_build_refresh_plan_wires_federal_congress_spine_job_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    raw_entries = [{"id": {"bioguide": "A000001"}}]
    adapted_legislators = object()
    historical_entries = [{"id": {"bioguide": "OLD0001"}}]
    vacancy_predecessors = object()
    data_source_id = UUID("a5eb7397-d8c9-41ee-8a7a-4179114819c1")
    load_result = object()

    class _Transaction:
        def __enter__(self) -> None:
            events.append("transaction_enter")

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            events.append("transaction_exit")

    class _Connection:
        def transaction(self) -> _Transaction:
            events.append("transaction")
            return _Transaction()

        def close(self) -> None:
            events.append("close")

    connection = _Connection()

    def _fetch_legislators_entries() -> list[dict[str, object]]:
        events.append("fetch")
        return raw_entries

    def _adapt_legislators_yaml(entries: list[dict[str, object]]) -> object:
        events.append("adapt")
        assert entries is raw_entries
        return adapted_legislators

    def _fetch_historical_entries() -> list[dict[str, object]]:
        events.append("fetch_historical")
        return historical_entries

    def _select_most_recent_vacancy_predecessors(adapted: object, history: list[dict[str, object]]) -> object:
        events.append("select_vacancies")
        assert adapted is adapted_legislators
        assert history is historical_entries
        return vacancy_predecessors

    def _get_connection() -> _Connection:
        events.append("get_connection")
        return connection

    def _ensure_federal_spine_data_source(conn: _Connection) -> UUID:
        events.append("ensure_data_source")
        assert conn is connection
        return data_source_id

    def _load_federal_spine(conn: _Connection, adapted: object, *, data_source_id: UUID) -> object:
        events.append("load")
        assert conn is connection
        assert adapted is adapted_legislators
        assert data_source_id == UUID("a5eb7397-d8c9-41ee-8a7a-4179114819c1")
        return load_result

    def _load_vacancy_predecessors(conn: _Connection, predecessors: object, *, data_source_id: UUID) -> int:
        events.append("load_vacancies")
        assert conn is connection
        assert predecessors is vacancy_predecessors
        assert data_source_id == UUID("a5eb7397-d8c9-41ee-8a7a-4179114819c1")
        return 5

    monkeypatch.setattr(job_builders, "fetch_legislators_entries", _fetch_legislators_entries)
    monkeypatch.setattr(job_builders, "adapt_legislators_yaml", _adapt_legislators_yaml)
    monkeypatch.setattr(job_builders, "fetch_historical_entries", _fetch_historical_entries)
    monkeypatch.setattr(
        job_builders,
        "select_most_recent_vacancy_predecessors",
        _select_most_recent_vacancy_predecessors,
    )
    monkeypatch.setattr(job_builders, "get_connection", _get_connection)
    monkeypatch.setattr(job_builders, "ensure_federal_spine_data_source", _ensure_federal_spine_data_source)
    monkeypatch.setattr(job_builders, "load_federal_spine", _load_federal_spine)
    monkeypatch.setattr(job_builders, "load_vacancy_predecessors", _load_vacancy_predecessors)

    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-congress-spine",))[0]

    result = job.run_callable()

    assert result is load_result
    assert job.domain == "campaign_finance"
    assert job.jurisdiction == "federal/congress"
    assert job.cadence == "weekly"
    assert job.data_source_names == (job_builders.FEDERAL_SPINE_DATA_SOURCE_NAME,)
    assert events == [
        "fetch",
        "adapt",
        "fetch_historical",
        "select_vacancies",
        "get_connection",
        "transaction",
        "transaction_enter",
        "ensure_data_source",
        "load",
        "load_vacancies",
        "transaction_exit",
        "close",
    ]


def test_federal_congress_spine_job_closes_connection_when_load_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    load_error = RuntimeError("load failed")

    class _Transaction:
        def __enter__(self) -> None:
            events.append("transaction_enter")

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            events.append("transaction_exit")

    class _Connection:
        def transaction(self) -> _Transaction:
            events.append("transaction")
            return _Transaction()

        def close(self) -> None:
            events.append("close")

    connection = _Connection()

    monkeypatch.setattr(job_builders, "fetch_legislators_entries", lambda: [])
    monkeypatch.setattr(job_builders, "adapt_legislators_yaml", lambda entries: object())
    monkeypatch.setattr(job_builders, "fetch_historical_entries", lambda: [])
    monkeypatch.setattr(
        job_builders,
        "select_most_recent_vacancy_predecessors",
        lambda adapted, history: object(),
    )
    monkeypatch.setattr(job_builders, "get_connection", lambda: connection)
    monkeypatch.setattr(
        job_builders, "ensure_federal_spine_data_source", lambda conn: UUID("8878d325-f9f3-4e06-8f55-d5a7de1f7f67")
    )

    def _load_federal_spine(conn: _Connection, adapted: object, *, data_source_id: UUID) -> object:
        events.append("load")
        raise load_error

    monkeypatch.setattr(job_builders, "load_federal_spine", _load_federal_spine)
    monkeypatch.setattr(job_builders, "load_vacancy_predecessors", lambda conn, predecessors, *, data_source_id: 0)
    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-congress-spine",))[0]

    with pytest.raises(RuntimeError, match="load failed"):
        job.run_callable()

    assert events == ["transaction", "transaction_enter", "load", "transaction_exit", "close"]


def test_federal_fec_masters_uses_refresh_run_history_for_cadence_gate() -> None:
    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-fec-masters",))[0]
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),)

    latest_pull_at = runner._select_latest_pull_at(connection, job)

    assert latest_pull_at == datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    query = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "FROM core.refresh_run" in query
    assert "job_key = %s" in query
    assert "pull_status = ANY(%s)" in query
    assert params == ("federal-fec-masters", ["success"])


def test_refresh_history_key_cadence_gate_ignores_crashed_runs() -> None:
    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-fec-masters",))[0]
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (None,)

    latest_pull_at = runner._select_latest_pull_at(connection, job)

    assert latest_pull_at is None
    query = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "pull_status = ANY(%s)" in query
    assert params == ("federal-fec-masters", ["success"])


def test_federal_fec_masters_refresh_history_key_cadence_gate_ignores_degraded_runs() -> None:
    job = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-fec-masters",))[0]
    degraded_completed_at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def execute(self, query: str, params: tuple[str, list[str]]) -> None:
            self.query = query
            self.params = params

        def fetchone(self) -> tuple[datetime | None]:
            _, accepted_pull_statuses = self.params
            if "degraded" in accepted_pull_statuses:
                return (degraded_completed_at,)
            return (None,)

    class _Connection:
        def __init__(self) -> None:
            self.cursor_instance = _Cursor()

        def cursor(self) -> _Cursor:
            return self.cursor_instance

    connection = _Connection()

    latest_pull_at = runner._select_latest_pull_at(connection, job)  # type: ignore[arg-type]

    assert latest_pull_at is None
    assert "pull_status = ANY(%s)" in connection.cursor_instance.query
    assert connection.cursor_instance.params == ("federal-fec-masters", ["success"])


def test_build_refresh_plan_orders_federal_jobs_by_stage_critical_prerequisites() -> None:
    """Stage 2 prerequisite contract: federal-fec-masters must run before every
    federal job that depends on the FEC master tables, and federal-enrichment
    must run after the upstream federal jobs that produce the people, FEC
    transactions, and Schedule E rows it joins on.

    This test deliberately checks only stage-critical prerequisites — the full
    federal key inventory (and its incidental tuple order) is owned by the
    prefix-filter contract in core/refresh/test_job_builders.py.
    """
    job_keys = [job.key for job in job_builders.build_refresh_plan(scope="all")]
    job_index = {job_key: position for position, job_key in enumerate(job_keys)}

    masters_dependents = (
        "federal-fec-schedule-a",
        "federal-fec-committee-summary",
        "federal-congress-spine",
        "federal-fec-schedule-b",
        "federal-fec-schedule-e",
        "federal-enrichment",
    )
    for dependent_key in masters_dependents:
        assert dependent_key in job_index, (
            f"Stage 2 prerequisite contract requires federal job {dependent_key!r} in the plan"
        )
        assert job_index["federal-fec-masters"] < job_index[dependent_key], (
            f"federal-fec-masters must precede {dependent_key} so master tables exist before dependents run"
        )

    assert job_index["federal-fec-schedule-a"] < job_index["federal-fec-committee-summary"], (
        "federal-fec-schedule-a must precede committee-summary derived aggregate population "
        "so stored aggregates include the newest itemized transactions"
    )

    enrichment_prerequisites = (
        "federal-congress-spine",
        "federal-fec-schedule-b",
        "federal-fec-schedule-e",
    )
    for prerequisite_key in enrichment_prerequisites:
        assert job_index[prerequisite_key] < job_index["federal-enrichment"], (
            f"{prerequisite_key} must precede federal-enrichment so enrichment joins on populated upstream rows"
        )


def test_build_refresh_plan_federal_scope_emits_only_ordered_federal_jobs() -> None:
    jobs = job_builders.build_refresh_plan(scope="federal")
    job_keys = tuple(job.key for job in jobs)

    assert job_keys == _EXPECTED_WEEKLY_FEDERAL_SCOPE_JOB_KEYS
    assert not any(job_key.startswith(("state-", "city-", "civic-", "civics-")) for job_key in job_keys)


def test_build_refresh_plan_includes_fec_and_state_jobs() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")

    jurisdictions = {job.jurisdiction for job in jobs}
    jobs_by_key = {job.key: job for job in jobs}
    assert "federal/fec" in jurisdictions
    assert "state/AL" in jurisdictions
    assert "state/CA" in jurisdictions
    assert "state/CO" in jurisdictions
    assert "state/GA" in jurisdictions
    assert "state/IL" in jurisdictions
    assert "state/IN" in jurisdictions
    assert "state/KY" in jurisdictions
    assert "state/LA" in jurisdictions
    assert "state/MN" in jurisdictions
    assert "state/NE" in jurisdictions
    assert "state/OR" in jurisdictions
    assert "state/PA" in jurisdictions
    assert "state/TX" in jurisdictions
    assert "state/WA" in jurisdictions
    assert "state/WI" in jurisdictions
    assert "state/NJ" in jurisdictions
    assert "state/NC" in jurisdictions
    assert "federal/officeholder/house" in jurisdictions
    assert "federal/officeholder/senate" in jurisdictions

    assert jobs_by_key["state-tx-contributions"].data_source_names == ("TEC Campaign Finance — Contributions",)
    assert jobs_by_key["state-tx-expenditures"].data_source_names == ("TEC Campaign Finance — Expenditures",)
    assert jobs_by_key["state-tx-loans"].data_source_names == ("TEC Campaign Finance — Loans",)

    assert jobs_by_key["state-al-contributions"].data_source_names == ("AL FCPA Campaign Finance — Contributions",)
    assert jobs_by_key["state-al-expenditures"].data_source_names == ("AL FCPA Campaign Finance — Expenditures",)
    assert jobs_by_key["state-il-contributions"].data_source_names == ("IL SBE Campaign Disclosure — Receipts",)
    assert jobs_by_key["state-il-expenditures"].data_source_names == ("IL SBE Campaign Disclosure — Expenditures",)
    assert jobs_by_key["state-pa-contributions"].data_source_names == ("PA DOS Campaign Finance — Contributions",)
    assert jobs_by_key["state-pa-expenditures"].data_source_names == ("PA DOS Campaign Finance — Expenditures",)
    assert jobs_by_key["state-pa-debts"].data_source_names == ("PA DOS Campaign Finance — Debt",)
    assert jobs_by_key["state-pa-receipts"].data_source_names == ("PA DOS Campaign Finance — Receipts",)
    assert "state-pa-filings" not in jobs_by_key
    assert jobs_by_key["state-ne-contributions"].data_source_names == (
        "NE NADC Campaign Finance — Contributions and Loans",
    )
    assert jobs_by_key["state-ne-expenditures"].data_source_names == ("NE NADC Campaign Finance — Expenditures",)
    assert jobs_by_key["state-ne-loans"].data_source_names == ("NE NADC Campaign Finance — Contributions and Loans",)
    assert jobs_by_key["state-in-contributions"].data_source_names == ("IN IED Campaign Finance - Contributions",)
    assert jobs_by_key["state-in-expenditures"].data_source_names == ("IN IED Campaign Finance - Expenditures",)
    # KY contributions use election-date scoping — check one representative job
    assert jobs_by_key["state-ky-contributions-5-19-2026"].data_source_names == (
        "KY KREF Campaign Finance — Contributions",
    )
    assert jobs_by_key["state-ky-expenditures"].data_source_names == ("KY KREF Campaign Finance — Expenditures",)
    assert jobs_by_key["state-la-contributions"].data_source_names == ("LA Ethics Campaign Finance — Contributions",)
    assert jobs_by_key["state-la-expenditures"].data_source_names == ("LA Ethics Campaign Finance — Expenditures",)
    assert jobs_by_key["state-la-loans"].data_source_names == ("LA Ethics Campaign Finance — Loans",)
    assert jobs_by_key["state-ma-contributions"].data_source_names == (
        "MA OCPF Report Items (Contributions + Expenditures)",
    )
    assert jobs_by_key["state-ma-expenditures"].data_source_names == (
        "MA OCPF Report Items (Contributions + Expenditures)",
    )
    assert jobs_by_key["state-nj-contributions"].data_source_names == ("ELEC Reports and Data Search Export API",)
    assert jobs_by_key["state-ny-contributions"].data_source_names == ("NY BoE Contributions",)
    assert jobs_by_key["state-ny-expenditures"].data_source_names == ("NY BoE Expenditures",)
    assert jobs_by_key["state-or-contributions"].data_source_names == ("OR ORESTAR Campaign Finance — Contributions",)
    assert jobs_by_key["state-or-expenditures"].data_source_names == ("OR ORESTAR Campaign Finance — Expenditures",)


def test_build_refresh_plan_uses_config_cadence_values() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert cadence_by_source["CAL-ACCESS Raw Data Export"] == "daily"
    assert cadence_by_source["TRACER Bulk Download — Contributions"] == "weekly"
    assert cadence_by_source["Georgia Campaign Portal — Contributions Search Export"] == "continuous"
    assert cadence_by_source["IL SBE Campaign Disclosure — Receipts"] == "continuous"
    assert cadence_by_source["IL SBE Campaign Disclosure — Expenditures"] == "continuous"
    assert cadence_by_source["IN IED Campaign Finance - Contributions"] == "weekly"
    assert cadence_by_source["IN IED Campaign Finance - Expenditures"] == "weekly"
    assert cadence_by_source["AL FCPA Campaign Finance — Contributions"] == "daily"
    assert cadence_by_source["AL FCPA Campaign Finance — Expenditures"] == "daily"
    assert cadence_by_source["KY KREF Campaign Finance — Contributions"] == "weekly"
    assert cadence_by_source["KY KREF Campaign Finance — Expenditures"] == "weekly"
    assert cadence_by_source["LA Ethics Campaign Finance — Contributions"] == "daily"
    assert cadence_by_source["LA Ethics Campaign Finance — Expenditures"] == "daily"
    assert cadence_by_source["LA Ethics Campaign Finance — Loans"] == "daily"
    assert cadence_by_source["MA OCPF Report Items (Contributions + Expenditures)"] == "daily"
    assert cadence_by_source["MN CFB Contributions (All)"] == "quarterly"
    assert cadence_by_source["NE NADC Campaign Finance — Contributions and Loans"] == "weekly"
    assert cadence_by_source["NE NADC Campaign Finance — Expenditures"] == "weekly"
    assert cadence_by_source["NY BoE Contributions"] == "daily"
    assert cadence_by_source["NY BoE Expenditures"] == "daily"
    assert cadence_by_source["NY BoE Independent Expenditures"] == "daily"
    assert cadence_by_source["OR ORESTAR Campaign Finance — Contributions"] == "weekly"
    assert cadence_by_source["OR ORESTAR Campaign Finance — Expenditures"] == "weekly"
    assert cadence_by_source["WA PDC Contributions"] == "daily"
    assert cadence_by_source["ELEC Reports and Data Search Export API"] == "quarterly"


def test_build_refresh_plan_includes_nc_ie_with_dedicated_ie_path() -> None:
    ie_document_index_path = Path("/tmp/nc-ie-document-index.csv")

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_ie_document_index_path=ie_document_index_path,
        ),
    )

    jurisdictions = {job.jurisdiction for job in jobs}
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert "state/NC" in jurisdictions
    assert cadence_by_source["North Carolina SBoE IE Document Index"] == "weekly"


def test_build_refresh_plan_omits_nc_ie_transactions_without_manual_paths() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")

    jobs_by_key = {job.key: job for job in jobs}
    assert "state-nc-ie-transactions" not in jobs_by_key


def test_build_refresh_plan_includes_nc_transactions_with_committee_docs_path() -> None:
    committee_docs_path = Path("/tmp/nc-committee-docs.csv")

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="STA-C3219N-C-001",
            nc_committee_name="NC REALTORS PAC",
        ),
    )

    jurisdictions = {job.jurisdiction for job in jobs}
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert "state/NC" in jurisdictions
    assert cadence_by_source["North Carolina SBoE Transaction Search"] == "daily"


def test_build_refresh_plan_passes_committee_docs_path_to_nc_job(monkeypatch: pytest.MonkeyPatch) -> None:
    committee_docs_path = Path("/tmp/nc-committee-docs.csv")
    run_nc_refresh = MagicMock()
    monkeypatch.setattr(job_builders, "run_nc_refresh", run_nc_refresh)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="C12345",
            nc_committee_name="Example Committee",
            nc_date_from="01/01/2026",
            nc_date_to="03/31/2026",
            nc_trans_type="exp",
        ),
    )

    nc_job = next(job for job in jobs if job.key == "state-nc-transactions")
    nc_job.run_callable()

    run_nc_refresh.assert_called_once()
    assert run_nc_refresh.call_args.kwargs["committee_docs_path"] == committee_docs_path
    assert run_nc_refresh.call_args.kwargs["committee_id"] == "C12345"
    assert run_nc_refresh.call_args.kwargs["committee_name"] == "Example Committee"
    assert run_nc_refresh.call_args.kwargs["date_from"] == "01/01/2026"
    assert run_nc_refresh.call_args.kwargs["date_to"] == "03/31/2026"
    assert run_nc_refresh.call_args.kwargs["trans_type"] == "exp"
    assert run_nc_refresh.call_args.kwargs["output_path"].name == "transactions.csv"


def test_build_refresh_plan_wires_nc_ie_transaction_job_to_pathless_run_nc_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    committee_docs_path = Path("/tmp/nc-committee-docs.csv")
    ie_document_index_path = Path("/tmp/nc-ie-document-index.csv")
    run_nc_refresh = MagicMock()
    monkeypatch.setattr(job_builders, "run_nc_refresh", run_nc_refresh)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="C12345",
            nc_committee_name="Example Committee",
            nc_date_from="01/01/2026",
            nc_date_to="03/31/2026",
            nc_trans_type="exp",
            nc_ie_document_index_path=ie_document_index_path,
        ),
    )

    nc_job_keys = [job.key for job in jobs if job.key.startswith("state-nc")]
    assert nc_job_keys == [
        "state-nc-ie-document-index",
        "state-nc-ie-transactions",
        "state-nc-committee-discovery",
        "state-nc-transactions",
    ]

    ie_transactions_job = next(job for job in jobs if job.key == "state-nc-ie-transactions")
    ie_transactions_job.run_callable()

    run_nc_refresh.assert_called_once_with(data_type="ie-transactions")


def test_build_refresh_plan_rejects_nc_runner_request_without_explicit_committee_scope() -> None:
    committee_docs_path = Path("/tmp/nc-committee-docs.csv")

    with pytest.raises(ValueError, match="requires both nc_committee_id and nc_committee_name"):
        job_builders.build_refresh_plan(
            scope="all",
            parameters=runner.RunnerParameters(nc_committee_docs_path=committee_docs_path),
        )


def test_build_refresh_plan_wires_al_ky_or_tx_pa_il_in_la_and_ne_run_callables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_al_refresh = MagicMock()
    run_ky_refresh = MagicMock()
    run_or_refresh = MagicMock()
    run_tx_refresh = MagicMock()
    run_pa_refresh = MagicMock()
    run_il_refresh = MagicMock()
    run_in_refresh = MagicMock()
    run_la_refresh = MagicMock()
    run_ne_refresh = MagicMock()
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(job_builders, "run_al_refresh", run_al_refresh)
    monkeypatch.setattr(job_builders, "run_ky_refresh", run_ky_refresh)
    monkeypatch.setattr(job_builders, "run_or_refresh", run_or_refresh)
    monkeypatch.setattr(job_builders, "run_tx_refresh", run_tx_refresh)
    monkeypatch.setattr(job_builders, "run_pa_refresh", run_pa_refresh)
    monkeypatch.setattr(job_builders, "run_il_refresh", run_il_refresh)
    monkeypatch.setattr(job_builders, "run_in_refresh", run_in_refresh)
    monkeypatch.setattr(job_builders, "run_la_refresh", run_la_refresh)
    monkeypatch.setattr(job_builders, "run_ne_refresh", run_ne_refresh)

    jobs = job_builders.build_refresh_plan(scope="all", now=now)
    jobs_by_key = {job.key: job for job in jobs}

    jobs_by_key["state-al-contributions"].run_callable()
    jobs_by_key["state-al-expenditures"].run_callable()
    # KY uses election-date scoped contribution jobs — run the 2026 primary one
    jobs_by_key["state-ky-contributions-5-19-2026"].run_callable()
    jobs_by_key["state-ky-expenditures"].run_callable()
    jobs_by_key["state-or-contributions"].run_callable()
    jobs_by_key["state-or-expenditures"].run_callable()
    jobs_by_key["state-tx-contributions"].run_callable()
    jobs_by_key["state-tx-expenditures"].run_callable()
    jobs_by_key["state-tx-loans"].run_callable()

    jobs_by_key["state-pa-contributions"].run_callable()
    jobs_by_key["state-pa-expenditures"].run_callable()
    jobs_by_key["state-pa-debts"].run_callable()
    jobs_by_key["state-pa-receipts"].run_callable()
    jobs_by_key["state-il-contributions"].run_callable()
    jobs_by_key["state-il-expenditures"].run_callable()
    jobs_by_key["state-in-contributions"].run_callable()
    jobs_by_key["state-in-expenditures"].run_callable()
    jobs_by_key["state-la-contributions"].run_callable()
    jobs_by_key["state-la-expenditures"].run_callable()
    jobs_by_key["state-la-loans"].run_callable()
    jobs_by_key["state-ne-contributions"].run_callable()
    jobs_by_key["state-ne-expenditures"].run_callable()
    jobs_by_key["state-ne-loans"].run_callable()

    assert [call.kwargs for call in run_al_refresh.call_args_list] == [
        {"year_from": 2022, "data_type": "contributions", "download": True},
        {"year_from": 2022, "data_type": "expenditures", "download": True},
    ]
    # KY uses election-date scoping for contributions; we only ran the 2026 primary job
    assert [call.kwargs for call in run_ky_refresh.call_args_list] == [
        {"year_from": 2022, "data_type": "contributions", "download": True, "election_date": "5/19/2026 12:00:00 AM"},
        {"year_from": 2022, "data_type": "expenditures", "download": True},
    ]
    assert [call.kwargs for call in run_or_refresh.call_args_list] == [
        {"year_from": 2022, "data_type": "contributions", "download": True},
        {"year_from": 2022, "data_type": "expenditures", "download": True},
    ]
    assert [call.kwargs for call in run_tx_refresh.call_args_list] == [
        {"data_type": "contributions", "download": True, "year_from": 2022},
        {"data_type": "expenditures", "download": True, "year_from": 2022},
        {"data_type": "loans", "download": True, "year_from": 2022},
    ]
    assert [call.kwargs for call in run_pa_refresh.call_args_list] == [
        {"year": 2026, "data_type": "contributions", "download": True},
        {"year": 2026, "data_type": "expenditures", "download": True},
        {"year": 2026, "data_type": "debts", "download": True},
        {"year": 2026, "data_type": "receipts", "download": True},
    ]
    assert [call.kwargs for call in run_il_refresh.call_args_list] == [
        {"data_type": "contributions", "download": True},
        {"data_type": "expenditures", "download": True},
    ]
    assert [call.kwargs for call in run_in_refresh.call_args_list] == [
        {"year": 2026, "data_type": "contributions", "download": True},
        {"year": 2026, "data_type": "expenditures", "download": True},
    ]
    assert [call.kwargs for call in run_la_refresh.call_args_list] == [
        {"year": 2026, "data_type": "contributions", "download": True},
        {"year": 2026, "data_type": "expenditures", "download": True},
        {"year": 2026, "data_type": "loans", "download": True},
    ]
    assert [call.kwargs for call in run_ne_refresh.call_args_list] == [
        {"year": 2026, "data_type": "contributions", "download": True},
        {"year": 2026, "data_type": "expenditures", "download": True},
        {"year": 2026, "data_type": "loans", "download": True},
    ]


def test_build_refresh_plan_wires_wi_run_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    run_wi_refresh = MagicMock()
    monkeypatch.setattr(job_builders, "run_wi_refresh", run_wi_refresh)

    jobs = job_builders.build_refresh_plan(scope="all")
    jobs_by_key = {job.key: job for job in jobs}

    assert "state-wi-transactions" in jobs_by_key
    assert jobs_by_key["state-wi-transactions"].data_source_names == ("WI Sunshine Transactions Export",)
    assert jobs_by_key["state-wi-transactions"].cadence == "daily"

    jobs_by_key["state-wi-transactions"].run_callable()
    run_wi_refresh.assert_called_once_with(data_type="transactions", download=True)


def test_build_refresh_plan_uses_pa_year_override(monkeypatch: pytest.MonkeyPatch) -> None:
    run_co_refresh = MagicMock()
    run_pa_refresh = MagicMock()
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(job_builders, "run_co_refresh", run_co_refresh)
    monkeypatch.setattr(job_builders, "run_pa_refresh", run_pa_refresh)

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(pa_year=2025),
        now=now,
    )
    jobs_by_key = {job.key: job for job in jobs}

    jobs_by_key["state-co-contributions"].run_callable()
    jobs_by_key["state-pa-contributions"].run_callable()

    run_co_refresh.assert_called_once_with(year=2026, data_type="contributions", download=True, allow_insecure_tls=True)
    run_pa_refresh.assert_called_once_with(year=2025, data_type="contributions", download=True)


def test_build_refresh_plan_includes_fl_jobs_in_all_scope() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")

    jurisdictions = {job.jurisdiction for job in jobs}
    jobs_by_key = {job.key: job for job in jobs}

    assert "state/FL" in jurisdictions

    assert jobs_by_key["state-fl-contributions"].data_source_names == ("FL DOS Campaign Finance - Contributions",)
    assert jobs_by_key["state-fl-expenditures"].data_source_names == ("FL DOS Campaign Finance - Expenditures",)
    assert jobs_by_key["state-fl-transfers"].data_source_names == ("FL DOS Campaign Finance - Transfers",)
    assert jobs_by_key["state-fl-other"].data_source_names == ("FL DOS Campaign Finance - Other Disbursements",)

    assert jobs_by_key["state-fl-contributions"].cadence == "daily"
    assert jobs_by_key["state-fl-expenditures"].cadence == "daily"
    assert jobs_by_key["state-fl-transfers"].cadence == "daily"
    assert jobs_by_key["state-fl-other"].cadence == "daily"
    assert {job.key for job in jobs if job.jurisdiction == "state/FL"} == {
        "state-fl-contributions",
        "state-fl-expenditures",
        "state-fl-transfers",
        "state-fl-other",
    }


def test_build_refresh_plan_excludes_fl_officeholder_directory_sources() -> None:
    jobs = job_builders.build_refresh_plan(scope="all")
    fl_source_names = {
        source_name for job in jobs if job.jurisdiction == "state/FL" for source_name in job.data_source_names
    }

    assert "FL Senate Officeholder Directory" not in fl_source_names
    assert "FL House Representatives Directory (Blocked in Datacenter)" not in fl_source_names


def test_build_refresh_plan_wires_fl_run_callables(monkeypatch: pytest.MonkeyPatch) -> None:
    run_fl_refresh = MagicMock()
    monkeypatch.setattr(job_builders, "run_fl_refresh", run_fl_refresh)

    jobs = job_builders.build_refresh_plan(scope="all")
    jobs_by_key = {job.key: job for job in jobs}

    jobs_by_key["state-fl-contributions"].run_callable()
    jobs_by_key["state-fl-expenditures"].run_callable()
    jobs_by_key["state-fl-transfers"].run_callable()
    jobs_by_key["state-fl-other"].run_callable()

    assert [call.kwargs for call in run_fl_refresh.call_args_list] == [
        {"data_type": "contributions", "download": True},
        {"data_type": "expenditures", "download": True},
        {"data_type": "transfers", "download": True},
        {"data_type": "other", "download": True},
    ]


def test_build_refresh_plan_priority_scope_excludes_fl() -> None:
    jobs = job_builders.build_refresh_plan(scope="priority")
    jurisdictions = {job.jurisdiction for job in jobs}
    source_names = {source_name for job in jobs for source_name in job.data_source_names}

    assert "state/FL" not in jurisdictions
    for fl_source in (
        "FL DOS Campaign Finance - Contributions",
        "FL DOS Campaign Finance - Expenditures",
        "FL DOS Campaign Finance - Transfers",
        "FL DOS Campaign Finance - Other Disbursements",
    ):
        assert fl_source not in source_names


def test_build_refresh_plan_priority_scope_includes_tx_and_excludes_non_priority_sources() -> None:
    jobs = job_builders.build_refresh_plan(scope="priority")
    source_names = {source_name for job in jobs for source_name in job.data_source_names}
    jurisdictions = {job.jurisdiction for job in jobs}
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert source_names == {
        "AL FCPA Campaign Finance — Contributions",
        "AL FCPA Campaign Finance — Expenditures",
        "CAL-ACCESS Raw Data Export",
        "KY KREF Campaign Finance — Contributions",
        "KY KREF Campaign Finance — Expenditures",
        "LA Ethics Campaign Finance — Contributions",
        "LA Ethics Campaign Finance — Expenditures",
        "LA Ethics Campaign Finance — Loans",
        "NE NADC Campaign Finance — Contributions and Loans",
        "NE NADC Campaign Finance — Expenditures",
        "OR ORESTAR Campaign Finance — Contributions",
        "OR ORESTAR Campaign Finance — Expenditures",
        "TRACER Bulk Download — Contributions",
        "TRACER Bulk Download — Expenditures",
        "Georgia Campaign Portal — Contributions Search Export",
        "Georgia Campaign Portal — Expenditures Search Export",
        "TEC Campaign Finance — Contributions",
        "TEC Campaign Finance — Expenditures",
        "TEC Campaign Finance — Loans",
        job_builders.FEDERAL_SPINE_DATA_SOURCE_NAME,
        job_builders.FEDERAL_ENRICHMENT_DATA_SOURCE_NAME,
        "ncsbe_candidate_listing_2026",
    }
    assert "federal/congress" in jurisdictions
    assert "state/TX" in jurisdictions
    assert "state/NC" in jurisdictions
    assert set(cadence_by_source.values()) == {"daily", "quarterly", "weekly"}

    for excluded_source in (
        "FEC Schedule A API",
        "MN CFB Contributions (All)",
        "PA DOS Campaign Finance — Contributions",
        "WA PDC Contributions",
        "TRACER Bulk Download — Loans",
    ):
        assert excluded_source not in source_names


def test_build_refresh_plan_priority_scope_includes_federal_congress_spine() -> None:
    jobs = job_builders.build_refresh_plan(scope="priority")
    spine_jobs = [job for job in jobs if job.key == "federal-congress-spine"]

    assert len(spine_jobs) == 1
    spine_job = spine_jobs[0]
    assert spine_job.domain == "campaign_finance"
    assert spine_job.jurisdiction == "federal/congress"
    assert spine_job.cadence == "weekly"
    assert spine_job.data_source_names == (job_builders.FEDERAL_SPINE_DATA_SOURCE_NAME,)


def test_build_refresh_plan_priority_scope_includes_nc_ie_with_dedicated_ie_path() -> None:
    ie_document_index_path = Path("/tmp/nc-ie-document-index.csv")

    jobs = job_builders.build_refresh_plan(
        scope="priority",
        parameters=runner.RunnerParameters(
            nc_ie_document_index_path=ie_document_index_path,
        ),
    )
    source_names = {source_name for job in jobs for source_name in job.data_source_names}
    jurisdictions = {job.jurisdiction for job in jobs}
    cadence_by_source = {source_name: job.cadence for job in jobs for source_name in job.data_source_names}

    assert "North Carolina SBoE IE Document Index" in source_names
    assert "state/NC" in jurisdictions
    assert cadence_by_source["North Carolina SBoE IE Document Index"] == "daily"


def test_build_refresh_plan_can_be_filtered_to_wa_job_prefix() -> None:
    jobs = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("state-wa",))

    assert [job.key for job in jobs] == [
        "state-wa-contributions",
        "state-wa-expenditures",
        "state-wa-independent_expenditures",
        "state-wa-loans",
    ]


def test_build_refresh_plan_can_be_filtered_to_federal_congress_spine_job() -> None:
    jobs = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("federal-congress-spine",))

    assert [job.key for job in jobs] == ["federal-congress-spine"]


def test_build_refresh_plan_job_key_prefix_filter_preserves_matching_fec_and_nc_jobs() -> None:
    committee_docs_path = Path("/tmp/nc-committee-docs.csv")
    ie_document_index_path = Path("/tmp/nc-ie-document-index.csv")

    jobs = job_builders.build_refresh_plan(
        scope="all",
        parameters=runner.RunnerParameters(
            nc_committee_docs_path=committee_docs_path,
            nc_committee_id="STA-C3219N-C-001",
            nc_committee_name="NC REALTORS PAC",
            nc_ie_document_index_path=ie_document_index_path,
        ),
        job_key_prefixes=("federal-fec", "state-nc"),
    )

    assert [job.key for job in jobs] == [
        "federal-fec-masters",
        "federal-fec-schedule-a",
        "federal-fec-committee-summary",
        "federal-fec-races",
        "federal-fec-schedule-b",
        "federal-fec-schedule-e",
        "state-nc-ie-document-index",
        "state-nc-ie-transactions",
        "state-nc-committee-discovery",
        "state-nc-transactions",
    ]


def test_build_refresh_plan_job_key_prefix_filter_rejects_empty_match() -> None:
    with pytest.raises(ValueError, match="No refresh jobs matched job_key_prefixes"):
        job_builders.build_refresh_plan(scope="all", job_key_prefixes=("state-zz",))


def test_should_run_job_honors_daily_cadence_window() -> None:
    now = datetime(2026, 3, 21, 16, 0, tzinfo=timezone.utc)
    job = _job_for_tests(key="co-contributions")

    assert runner.should_run_job(job, last_pull_at=None, now=now) is True
    assert runner.should_run_job(job, last_pull_at=now - timedelta(hours=12), now=now) is False
    assert runner.should_run_job(job, last_pull_at=now - timedelta(days=2), now=now) is True


_PARTIAL_RUN_MANUAL_RECOVERY_AT = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
_PARTIAL_RUN_STALE_MASTERS_AT = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
_PARTIAL_RUN_SCHEDULED_AT = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
_FULL_SCOPE_OFFICEHOLDER_MONEY_COVERAGE = 518


def _cleanup_refresh_runner_partial_run_fixture(
    connection: psycopg.Connection,
    *,
    job_keys: list[str],
    started_at: datetime,
) -> None:
    connection.execute(
        "DELETE FROM core.refresh_run WHERE job_key = ANY(%s) AND started_at = %s",
        (job_keys, started_at),
    )


def _successful_single_update_loader_result() -> SimpleNamespace:
    return SimpleNamespace(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0)


def _build_real_plan_with_inert_callables(
    *,
    masters_run_callable: MagicMock,
) -> tuple[list[runner.RefreshJob], dict[str, MagicMock]]:
    jobs = job_builders.build_refresh_plan(scope="federal")
    assert tuple(job.key for job in jobs) == _EXPECTED_WEEKLY_FEDERAL_SCOPE_JOB_KEYS

    callables_by_key: dict[str, MagicMock] = {}
    replaced_jobs: list[runner.RefreshJob] = []
    for job in jobs:
        run_callable = (
            masters_run_callable
            if job.key == "federal-fec-masters"
            else MagicMock(name=job.key, return_value=_successful_loader_result())
        )
        callables_by_key[job.key] = run_callable
        replaced_jobs.append(replace(job, run_callable=run_callable))
    return replaced_jobs, callables_by_key


def _partial_run_last_pull_by_key(
    jobs: list[runner.RefreshJob],
    *,
    now: datetime,
) -> dict[str, datetime]:
    return {
        job.key: now - timedelta(days=8) if job.key == "federal-fec-masters" else now - timedelta(days=1)
        for job in jobs
    }


def _expected_masters_partial_run_eligibility(jobs: list[runner.RefreshJob]) -> dict[str, bool]:
    return {job.key: job.key == "federal-fec-masters" or job.cadence == "continuous" for job in jobs}


def _assert_real_plan_call_counts(
    jobs: list[runner.RefreshJob],
    callables_by_key: dict[str, MagicMock],
) -> None:
    callables_by_key["federal-fec-masters"].assert_called_once_with()
    for job in jobs:
        run_callable = callables_by_key[job.key]
        if job.key == "federal-fec-masters":
            continue
        if job.cadence == "continuous":
            run_callable.assert_called_once_with()
        else:
            run_callable.assert_not_called()


def _assert_masters_partial_run_results(results: list[runner.RefreshRunResult]) -> None:
    assert [(result.key, result.status) for result in results] == [
        ("federal-fec-masters", "success"),
        ("federal-fec-schedule-a", "success"),
        ("federal-fec-committee-summary", "skipped"),
        ("federal-congress-spine", "skipped"),
        ("federal-fec-races", "skipped"),
        ("federal-donor-search-rollup", "skipped"),
        ("federal-fec-schedule-b", "success"),
        ("federal-fec-schedule-e", "success"),
        ("federal-enrichment", "skipped"),
        ("federal-geometry-probe", "skipped"),
        ("federal-fec-masters", "failed"),
    ]
    spine_result = results[3]
    alarm = results[-1]
    assert spine_result.key == "federal-congress-spine"
    assert spine_result.status == "skipped"
    assert alarm.status == "failed"
    assert "federal-fec-masters" in alarm.message
    assert "federal-congress-spine" in alarm.message
    assert int(any(result.status in runner._FAILING_STATUSES for result in results)) == 1


def _federal_masters_and_spine_jobs() -> tuple[runner.RefreshJob, runner.RefreshJob]:
    jobs = job_builders.build_refresh_plan(
        scope="all",
        job_key_prefixes=("federal-fec-masters", "federal-congress-spine"),
    )
    assert tuple(job.key for job in jobs) == ("federal-fec-masters", "federal-congress-spine")
    return jobs[0], jobs[1]


def _weekly_pair_eligibility_by_key(
    last_pull_by_key: dict[str, datetime | None],
    *,
    now: datetime = _PARTIAL_RUN_SCHEDULED_AT,
) -> dict[str, bool]:
    return {
        job.key: runner.should_run_job(job, last_pull_at=last_pull_by_key[job.key], now=now)
        for job in _federal_masters_and_spine_jobs()
    }


def _successful_loader_result() -> SimpleNamespace:
    return SimpleNamespace(inserted=3, skipped=0, quarantined=0, superseded=0, errors=0)


def _run_weekly_pair_main(
    monkeypatch: pytest.MonkeyPatch,
    *,
    last_pull_by_key: dict[str, datetime | None],
) -> tuple[int, list[runner.RefreshRunResult], dict[str, MagicMock]]:
    callables_by_key: dict[str, MagicMock] = {}
    jobs = []
    for job in _federal_masters_and_spine_jobs():
        run_callable = MagicMock(return_value=_successful_loader_result())
        callables_by_key[job.key] = run_callable
        jobs.append(replace(job, run_callable=run_callable))

    streamed_results: list[runner.RefreshRunResult] = []
    original_format_result_line = runner._format_result_line

    class _Connection:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    def _capture_result_line(result: runner.RefreshRunResult) -> str:
        streamed_results.append(result)
        return original_format_result_line(result)

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: jobs)
    monkeypatch.setattr(runner, "get_connection", lambda: _Connection())
    monkeypatch.setattr(runner, "_utc_now", lambda: _PARTIAL_RUN_SCHEDULED_AT)
    monkeypatch.setattr(runner, "_select_latest_pull_at", lambda connection, job: last_pull_by_key[job.key])
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "_select_data_source_id", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_record_refresh_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_format_result_line", _capture_result_line)

    exit_code = runner.main(
        [
            "--no-lock",
            "--job-key-prefix",
            "federal-fec-masters",
            "--job-key-prefix",
            "federal-congress-spine",
        ]
    )

    return exit_code, streamed_results, callables_by_key


@pytest.mark.integration
def test_masters_with_spine_skipped_preserves_officeholder_money_coverage(
    monkeypatch: pytest.MonkeyPatch,
    committing_db_conn: psycopg.Connection,
) -> None:
    fixed_run_at = datetime(2099, 1, 11, 12, 0, tzinfo=timezone.utc)
    fixture_ids = None
    plan_job_keys = list(_EXPECTED_WEEKLY_FEDERAL_SCOPE_JOB_KEYS)

    try:
        committing_db_conn.rollback()
        cleanup_donor_search_fixture(committing_db_conn)
        _cleanup_refresh_runner_partial_run_fixture(
            committing_db_conn,
            job_keys=plan_job_keys,
            started_at=fixed_run_at,
        )
        committing_db_conn.commit()

        fixture_ids = seed_full_scope_skewed_donor_search_fixture(committing_db_conn)
        officeholder_money_coverage = fetch_full_scope_donor_search_counts(committing_db_conn).linked_people
        assert fixture_ids.counts.linked_people == _FULL_SCOPE_OFFICEHOLDER_MONEY_COVERAGE
        assert officeholder_money_coverage == _FULL_SCOPE_OFFICEHOLDER_MONEY_COVERAGE
        assert officeholder_money_coverage > 0
        committing_db_conn.commit()

        def _run_masters_link_update() -> SimpleNamespace:
            assert fixture_ids is not None
            update_candidate_person_link(
                committing_db_conn,
                fec_candidate_id="S6NC00000",
                person_id=fixture_ids.secondary_recipient.person_id,
            )
            return _successful_single_update_loader_result()

        masters_run_callable = MagicMock(side_effect=_run_masters_link_update)
        jobs, callables_by_key = _build_real_plan_with_inert_callables(
            masters_run_callable=masters_run_callable,
        )
        last_pull_by_key = _partial_run_last_pull_by_key(jobs, now=fixed_run_at)

        assert {
            job.key: runner.should_run_job(job, last_pull_at=last_pull_by_key[job.key], now=fixed_run_at)
            for job in jobs
        } == _expected_masters_partial_run_eligibility(jobs)

        monkeypatch.setattr(runner, "_utc_now", lambda: fixed_run_at)
        monkeypatch.setattr(runner, "_select_latest_pull_at", lambda connection, job: last_pull_by_key[job.key])
        results = runner.run_all_jobs(committing_db_conn, jobs, now=fixed_run_at)

        officeholder_money_coverage = fetch_full_scope_donor_search_counts(committing_db_conn).linked_people
        assert officeholder_money_coverage == _FULL_SCOPE_OFFICEHOLDER_MONEY_COVERAGE
        _assert_masters_partial_run_results(results)
        _assert_real_plan_call_counts(jobs, callables_by_key)
    finally:
        committing_db_conn.rollback()
        cleanup_donor_search_fixture(committing_db_conn)
        _cleanup_refresh_runner_partial_run_fixture(
            committing_db_conn,
            job_keys=plan_job_keys,
            started_at=fixed_run_at,
        )
        committing_db_conn.commit()


def test_main_flags_weekly_federal_partial_run_when_masters_runs_without_congress_spine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_STALE_MASTERS_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }

    assert _weekly_pair_eligibility_by_key(last_pull_by_key) == {
        "federal-fec-masters": True,
        "federal-congress-spine": False,
    }

    exit_code, results, callables_by_key = _run_weekly_pair_main(
        monkeypatch,
        last_pull_by_key=last_pull_by_key,
    )

    assert [(result.key, result.status) for result in results] == [
        ("federal-fec-masters", "success"),
        ("federal-congress-spine", "skipped"),
        ("federal-fec-masters", "failed"),
    ]
    callables_by_key["federal-fec-masters"].assert_called_once_with()
    callables_by_key["federal-congress-spine"].assert_not_called()
    assert exit_code == 1, (
        "runner.main() must fail the federal result family when weekly federal prerequisites split: "
        "federal-fec-masters ran but federal-congress-spine stayed inside the 2026-07-25 recovery freshness window"
    )


def test_weekly_federal_partial_run_alarm_names_jobs_and_cadence_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_STALE_MASTERS_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }

    _, results, _ = _run_weekly_pair_main(
        monkeypatch,
        last_pull_by_key=last_pull_by_key,
    )

    alarm = results[-1]
    assert alarm.status == "failed"
    assert "federal-fec-masters" in alarm.message
    assert "federal-congress-spine" in alarm.message
    assert _PARTIAL_RUN_STALE_MASTERS_AT.isoformat() in alarm.message
    assert _PARTIAL_RUN_MANUAL_RECOVERY_AT.isoformat() in alarm.message
    assert alarm.error == alarm.message


def test_weekly_federal_partial_run_alarm_status_drives_main_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert runner._FAILING_STATUSES == frozenset({"crashed", "degraded", "empty", "failed"})

    jobs = [
        replace(job, run_callable=MagicMock(return_value=_successful_loader_result()))
        for job in _federal_masters_and_spine_jobs()
    ]
    connection = MagicMock()
    record_refresh_run = MagicMock()
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_STALE_MASTERS_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }
    monkeypatch.setattr(runner, "_utc_now", lambda: _PARTIAL_RUN_SCHEDULED_AT)
    monkeypatch.setattr(runner, "_record_refresh_run", record_refresh_run)

    alarm = runner._record_repair_pair_alarm(
        connection,
        jobs[0],
        jobs[1],
        last_pull_at_by_key=last_pull_by_key,
    )

    assert alarm.status == "failed"
    assert alarm.status in runner._FAILING_STATUSES
    record_refresh_run.assert_called_once()
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()

    failing_connection = MagicMock()
    monkeypatch.setattr(runner, "_record_refresh_run", MagicMock(side_effect=RuntimeError("ledger write boom")))

    failed_alarm = runner._record_repair_pair_alarm(
        failing_connection,
        jobs[0],
        jobs[1],
        last_pull_at_by_key=last_pull_by_key,
    )

    assert failed_alarm.status == "failed"
    assert failed_alarm.status in runner._FAILING_STATUSES
    assert "alarm ledger recording failed: ledger write boom" in failed_alarm.error
    failing_connection.commit.assert_not_called()
    failing_connection.rollback.assert_called_once_with()


def test_weekly_federal_partial_run_alarm_records_failed_zero_activity_ledger_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = [
        replace(job, run_callable=MagicMock(return_value=_successful_loader_result()))
        for job in _federal_masters_and_spine_jobs()
    ]
    connection = MagicMock()
    insert_refresh_run = MagicMock()
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_STALE_MASTERS_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }
    monkeypatch.setattr(runner, "_utc_now", lambda: _PARTIAL_RUN_SCHEDULED_AT)
    monkeypatch.setattr(runner, "_select_latest_pull_at", lambda connection, job: last_pull_by_key[job.key])
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "_select_data_source_id", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    results = runner.run_all_jobs(
        connection,
        jobs,
        now=_PARTIAL_RUN_SCHEDULED_AT,
    )

    alarm = results[-1]
    alarm_run = insert_refresh_run.call_args_list[-1].args[1]
    assert alarm.status == "failed"
    assert alarm_run.job_key == "federal-fec-masters"
    assert alarm_run.domain == jobs[0].domain
    assert alarm_run.jurisdiction == jobs[0].jurisdiction
    assert alarm_run.data_source_names == list(jobs[0].data_source_names)
    assert alarm_run.pull_status == "failed"
    assert alarm_run.inserted_count == 0
    assert alarm_run.skipped_count == 0
    assert alarm_run.quarantined_count == 0
    assert alarm_run.superseded_count == 0
    assert alarm_run.error_count == 0
    assert alarm_run.metadata_updates == 0
    assert alarm_run.message == alarm.message
    assert alarm_run.error == alarm.error == alarm.message


@pytest.mark.integration
def test_weekly_federal_partial_run_alarm_persists_to_real_refresh_run_table(
    monkeypatch: pytest.MonkeyPatch,
    db_conn: psycopg.Connection,
) -> None:
    alarm_at = datetime(2099, 1, 10, 12, 0, tzinfo=timezone.utc)
    last_pull_by_key = {
        "federal-fec-masters": datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc),
        "federal-congress-spine": datetime(2099, 1, 9, 12, 0, tzinfo=timezone.utc),
    }
    jobs = [
        replace(job, run_callable=MagicMock(return_value=_successful_loader_result()))
        for job in _federal_masters_and_spine_jobs()
    ]
    monkeypatch.setattr(runner, "_utc_now", lambda: alarm_at)
    monkeypatch.setattr(runner, "_select_latest_pull_at", lambda connection, job: last_pull_by_key[job.key])
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "_select_data_source_id", lambda *args, **kwargs: None)

    try:
        results = runner.run_all_jobs(db_conn, jobs, now=alarm_at)

        with db_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT pull_status, inserted_count, skipped_count,
                       quarantined_count, superseded_count, error_count,
                       metadata_updates, message, error
                FROM core.refresh_run
                WHERE job_key = 'federal-fec-masters'
                  AND started_at = %s
                  AND pull_status = 'failed'
                """,
                (alarm_at,),
            )
            alarm_row = cursor.fetchone()

        assert alarm_row == (
            "failed",
            0,
            0,
            0,
            0,
            0,
            0,
            results[-1].message,
            results[-1].message,
        )
    finally:
        db_conn.execute(
            "DELETE FROM core.refresh_run WHERE job_key = ANY(%s) AND started_at = %s",
            (["federal-fec-masters", "federal-congress-spine"], alarm_at),
        )
        db_conn.commit()


def test_main_allows_weekly_federal_pair_when_both_jobs_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_pull_by_key = {
        "federal-fec-masters": None,
        "federal-congress-spine": None,
    }

    assert _weekly_pair_eligibility_by_key(last_pull_by_key) == {
        "federal-fec-masters": True,
        "federal-congress-spine": True,
    }

    exit_code, results, callables_by_key = _run_weekly_pair_main(
        monkeypatch,
        last_pull_by_key=last_pull_by_key,
    )

    assert [(result.key, result.status) for result in results] == [
        ("federal-fec-masters", "success"),
        ("federal-congress-spine", "success"),
    ]
    callables_by_key["federal-fec-masters"].assert_called_once_with()
    callables_by_key["federal-congress-spine"].assert_called_once_with()
    assert exit_code == 0


def test_main_allows_weekly_federal_pair_when_both_jobs_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_pull_by_key = {
        "federal-fec-masters": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
        "federal-congress-spine": _PARTIAL_RUN_MANUAL_RECOVERY_AT,
    }

    assert _weekly_pair_eligibility_by_key(last_pull_by_key) == {
        "federal-fec-masters": False,
        "federal-congress-spine": False,
    }

    exit_code, results, callables_by_key = _run_weekly_pair_main(
        monkeypatch,
        last_pull_by_key=last_pull_by_key,
    )

    assert [(result.key, result.status) for result in results] == [
        ("federal-fec-masters", "skipped"),
        ("federal-congress-spine", "skipped"),
    ]
    callables_by_key["federal-fec-masters"].assert_not_called()
    callables_by_key["federal-congress-spine"].assert_not_called()
    assert exit_code == 0


def test_run_job_dry_run_skips_callable_and_metadata_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock()
    job = _job_for_tests(key="dry-run-job", run_callable=run_callable)
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)

    result = runner.run_job(connection, job, dry_run=True)

    assert result.status == "dry_run"
    assert result.metadata_updates == 0
    run_callable.assert_not_called()
    sync_data_source_metadata.assert_not_called()


def test_run_job_syncs_metadata_through_shared_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock()
    job = _job_for_tests(key="metadata-job", run_callable=run_callable)
    data_source_id = UUID("baf6456e-cf99-47c1-8738-b77f8cfb3f82")
    select_data_source_id = MagicMock(return_value=data_source_id)
    sync_data_source_metadata = MagicMock(return_value=42)

    monkeypatch.setattr(runner, "_select_data_source_id", select_data_source_id)
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.metadata_updates == 1
    run_callable.assert_called_once_with()
    select_data_source_id.assert_called_once_with(
        connection,
        domain="campaign_finance",
        jurisdiction="state/CO",
        name="TRACER Bulk Download — Contributions",
    )
    sync_data_source_metadata.assert_called_once_with(connection, data_source_id, pull_status="success")


def test_civic_roster_job_cadence_gate_and_metadata_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    jobs = job_builders.build_refresh_plan(scope="all", job_key_prefixes=("civic-rosters-us-house-nc",))
    roster_job = jobs[0]
    connection = MagicMock()
    run_callable = MagicMock(return_value=SimpleNamespace(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0))
    hydrated_job = runner.RefreshJob(
        key=roster_job.key,
        domain=roster_job.domain,
        jurisdiction=roster_job.jurisdiction,
        cadence=roster_job.cadence,
        data_source_names=roster_job.data_source_names,
        run_callable=run_callable,
    )
    data_source_id = UUID("89ce5ea6-6cff-45f8-8bdb-ac840a4d3b6a")
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_record_refresh_run", MagicMock())
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)

    skipped_result = runner._run_gated_job(
        connection,
        hydrated_job,
        last_pull_at=now - timedelta(days=1),
        now=now,
    )
    assert skipped_result.status == "skipped"
    run_callable.assert_not_called()
    sync_data_source_metadata.assert_not_called()

    run_result = runner._run_gated_job(
        connection,
        hydrated_job,
        last_pull_at=now - timedelta(days=8),
        now=now,
    )
    assert run_result.status == "success"
    run_callable.assert_called_once_with()
    runner._select_data_source_id.assert_called_with(
        connection,
        domain="civics",
        jurisdiction="federal/officeholder/house",
        name="US House Officeholder Directory (NC)",
    )
    sync_data_source_metadata.assert_called_once_with(connection, data_source_id, pull_status="success")


def test_run_job_includes_loader_counts_in_success_message(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=SimpleNamespace(inserted=12, skipped=3, quarantined=1, superseded=0, errors=0)
    )
    job = _job_for_tests(key="counted-job", run_callable=run_callable)

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=12 skipped=3 quarantined=1 superseded=0 errors=0"


def test_run_job_records_federal_spine_result_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    spine_result = SpineLoadResult()
    spine_result.house.inserted = 435
    spine_result.senate.inserted = 100
    spine_result.delegate.inserted = 6
    spine_result.delegate.skipped = 1
    spine_result.vice_president.errors = 1
    run_callable = MagicMock(return_value=spine_result)
    job = _job_for_tests(key="federal-congress-spine", run_callable=run_callable)
    insert_refresh_run = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "degraded"
    assert (
        result.message
        == "Refresh job completed with loader errors: inserted=541 skipped=1 quarantined=0 superseded=0 errors=1"
    )
    refresh_run = insert_refresh_run.call_args.args[1]
    assert refresh_run.pull_status == "degraded"
    assert refresh_run.inserted_count == 541
    assert refresh_run.skipped_count == 1
    assert refresh_run.quarantined_count == 0
    assert refresh_run.superseded_count == 0
    assert refresh_run.error_count == 1


def test_run_job_keeps_generic_success_message_when_callable_returns_non_loader_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    run_callable = MagicMock(return_value=object())
    job = _job_for_tests(key="generic-job", run_callable=run_callable)

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded"


def test_run_job_maps_ncsbe_refresh_summary_to_loader_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=NcsbeResultsLoadSummary(
            source_record_count=3,
            result_row_count=14,
            contest_count=5,
            source_record_ids_by_file={},
        )
    )
    job = _job_for_tests(key="ncsbe-summary-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=14 skipped=0 quarantined=0 superseded=0 errors=0"
    refresh_run = insert_refresh_run.call_args.args[1]
    assert refresh_run.inserted_count == 14
    assert refresh_run.skipped_count == 0
    assert refresh_run.quarantined_count == 0
    assert refresh_run.superseded_count == 0
    assert refresh_run.error_count == 0


def test_run_job_maps_dictionary_loader_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(return_value={"inserted": 4, "skipped": 2, "quarantined": 0, "superseded": 0, "errors": 0})
    job = _job_for_tests(key="mapping-counts-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=4 skipped=2 quarantined=0 superseded=0 errors=0"
    refresh_run = insert_refresh_run.call_args.args[1]
    assert refresh_run.inserted_count == 4
    assert refresh_run.skipped_count == 2


def test_run_job_aggregates_loader_counts_from_multi_file_result(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=[
            SimpleNamespace(inserted=10, skipped=1, quarantined=0, superseded=0, errors=0),
            SimpleNamespace(inserted=20, skipped=2, quarantined=1, superseded=0, errors=0),
            SimpleNamespace(inserted=30, skipped=3, quarantined=0, superseded=1, errors=1),
        ]
    )
    job = _job_for_tests(key="multi-file-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "degraded"
    assert (
        result.message
        == "Refresh job completed with loader errors: inserted=60 skipped=6 quarantined=1 superseded=1 errors=1"
    )
    refresh_run = insert_refresh_run.call_args.args[1]
    assert refresh_run.pull_status == "degraded"
    assert refresh_run.inserted_count == 60
    assert refresh_run.skipped_count == 6
    assert refresh_run.quarantined_count == 1
    assert refresh_run.superseded_count == 1
    assert refresh_run.error_count == 1


def test_run_job_records_empty_pull_status_for_zero_activity_loader_result(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(return_value=SimpleNamespace(inserted=0, skipped=0, quarantined=0, superseded=0, errors=0))
    job = _job_for_tests(key="empty-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "empty"
    assert result.message == "Refresh job completed with no inserted rows"
    assert insert_refresh_run.call_args.args[1].pull_status == "empty"
    # Honest reruns must NOT backfill a fake success state into core.data_source.
    sync_data_source_metadata.assert_not_called()


def test_run_job_records_success_pull_status_for_skipped_only_loader_result(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=SimpleNamespace(inserted=0, skipped=37, quarantined=0, superseded=0, errors=0)
    )
    job = _job_for_tests(key="skipped-only-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", MagicMock(return_value=[120, 140, 160]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=0 skipped=37 quarantined=0 superseded=0 errors=0"
    refresh_run = insert_refresh_run.call_args.args[1]
    assert refresh_run.pull_status == "success"
    assert refresh_run.inserted_count == 0
    assert refresh_run.skipped_count == 37


def test_recent_nonempty_activity_counts_include_processed_non_insert_rows() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(40_589,), (21_836,)]
    job = _job_for_tests(key="federal-fec-masters")
    completed_after = datetime(2026, 6, 24, tzinfo=timezone.utc)

    activity_counts = runner._recent_nonempty_activity_counts(
        connection,
        job,
        completed_after=completed_after,
    )

    assert activity_counts == [40_589, 21_836]
    query = " ".join(cursor.execute.call_args.args[0].split())
    assert (
        "SELECT inserted_count + skipped_count + quarantined_count + superseded_count FROM core.refresh_run"
    ) in query
    assert cursor.execute.call_args.args[1] == ("federal-fec-masters", completed_after)


def test_recent_nonempty_activity_counts_uses_job_key_for_historical_volume_fallback() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(526,)]
    job = _job_for_tests(key="generic-materialization-job")
    completed_after = datetime(2026, 6, 24, tzinfo=timezone.utc)

    activity_counts = runner._recent_nonempty_activity_counts(
        connection,
        job,
        completed_after=completed_after,
    )

    assert activity_counts == [526]
    assert cursor.execute.call_args.args[1] == ("generic-materialization-job", completed_after)


def test_run_job_records_degraded_when_loader_reports_errors_even_with_bulk_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=SimpleNamespace(inserted=175, skipped=40_414, quarantined=0, superseded=0, errors=1)
    )
    job = _job_for_tests(key="federal-fec-masters", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", MagicMock(return_value=[21_836]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "degraded"
    assert result.message == (
        "Refresh job completed with loader errors: inserted=175 skipped=40414 quarantined=0 superseded=0 errors=1"
    )
    sync_data_source_metadata.assert_not_called()
    assert insert_refresh_run.call_args.args[1].pull_status == "degraded"


def test_run_job_records_degraded_pull_status_when_activity_is_below_recent_median(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    run_callable = MagicMock(
        return_value=SimpleNamespace(inserted=80, skipped=5, quarantined=0, superseded=0, errors=0)
    )
    job = _job_for_tests(key="degraded-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", MagicMock(return_value=[180, 200, 220]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "degraded"
    assert result.message == "Refresh job completed below historical volume threshold: activity=85 median=200"
    sync_data_source_metadata.assert_not_called()
    assert insert_refresh_run.call_args.args[1].pull_status == "degraded"


def test_derive_pull_status_compares_incremental_enrichment_with_like_for_like_history() -> None:
    """Federal enrichment uses the selected population as its current workload."""
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="selected",
    )
    execution_result = {
        "selected": 540,
        "inserted": 525,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result=execution_result,
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "success"
    assert counts == {
        "inserted": 525,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == (
        "Refresh job succeeded: inserted=525 skipped=0 quarantined=0 superseded=0 errors=0 activity=525 denominator=540"
    )


def test_derive_pull_status_degrades_incremental_enrichment_below_selected_denominator() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="selected",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "selected": 200,
            "inserted": 85,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 85,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job completed below configured volume threshold: activity=85 denominator=200"


def test_derive_pull_status_fails_closed_for_invalid_configured_denominator() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="selected",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "inserted": 525,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 525,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job configured invalid activity denominator: field=selected"


def test_derive_pull_status_fails_closed_for_configured_denominator_without_loader_counts() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="selected",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={"selected": 540},
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 0,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job configured activity denominator but loader counts are unavailable: field=selected"


def test_derive_pull_status_fails_closed_for_empty_counts_with_invalid_configured_denominator() -> None:
    connection = MagicMock()
    job = _job_for_tests(
        key="federal-enrichment",
        activity_denominator_result_field="selected",
    )

    status, counts, message = runner._derive_pull_status(
        connection,
        job,
        execution_error=None,
        execution_result={
            "selected": 0,
            "inserted": 0,
            "skipped": 0,
            "quarantined": 0,
            "superseded": 0,
            "errors": 0,
        },
        completed_at=datetime(2026, 7, 25, 3, 21, 16, tzinfo=timezone.utc),
    )

    connection.cursor.assert_not_called()
    assert status == "degraded"
    assert counts == {
        "inserted": 0,
        "skipped": 0,
        "quarantined": 0,
        "superseded": 0,
        "errors": 0,
    }
    assert message == "Refresh job configured invalid activity denominator: field=selected"


def test_run_job_records_crashed_pull_status_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    run_callable = MagicMock(side_effect=RuntimeError("boom"))
    job = _job_for_tests(key="crashed-job", run_callable=run_callable)
    insert_refresh_run = MagicMock()
    sync_data_source_metadata = MagicMock()

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "crashed"
    assert result.error == "boom"
    sync_data_source_metadata.assert_not_called()
    assert insert_refresh_run.call_args.args[1].pull_status == "crashed"


def test_run_all_jobs_isolates_failures_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    first_callable = MagicMock(side_effect=RuntimeError("boom"))
    second_callable = MagicMock()
    first_job = _job_for_tests(key="first", run_callable=first_callable)
    second_job = _job_for_tests(key="second", run_callable=second_callable)

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())

    results = runner.run_all_jobs(connection, [first_job, second_job], dry_run=False, force=True)

    assert [result.status for result in results] == ["crashed", "success"]
    first_callable.assert_called_once_with()
    second_callable.assert_called_once_with()


def test_run_all_jobs_stops_after_failure_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    first_job = _job_for_tests(key="first")
    second_job = _job_for_tests(key="second")
    first_result = runner.RefreshRunResult(
        key="first",
        status="degraded",
        metadata_updates=0,
        message="below historical threshold",
    )
    second_result = runner.RefreshRunResult(
        key="second",
        status="success",
        metadata_updates=1,
        message="should not run",
    )
    run_job = MagicMock(side_effect=[first_result, second_result])
    streamed: list[runner.RefreshRunResult] = []

    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(
        connection,
        [first_job, second_job],
        dry_run=False,
        force=True,
        on_result=streamed.append,
        stop_on_failure=True,
    )

    assert results == [first_result]
    assert streamed == [first_result]
    run_job.assert_called_once_with(connection, first_job, dry_run=False)
    connection.commit.assert_called_once_with()


def test_run_all_jobs_continues_after_quarantined_activity_when_stop_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    quarantined_callable = MagicMock(
        return_value=SimpleNamespace(inserted=0, skipped=0, quarantined=1, superseded=0, errors=0)
    )
    next_callable = MagicMock(
        return_value=SimpleNamespace(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0)
    )
    jobs = [
        _job_for_tests(key="quarantined", run_callable=quarantined_callable),
        _job_for_tests(key="next", run_callable=next_callable),
    ]

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "_recent_nonempty_activity_counts", MagicMock(return_value=[]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", MagicMock())

    results = runner.run_all_jobs(connection, jobs, force=True, stop_on_failure=True)

    assert [result.status for result in results] == ["success", "success"]
    assert results[0].message == "Refresh job succeeded: inserted=0 skipped=0 quarantined=1 superseded=0 errors=0"
    quarantined_callable.assert_called_once_with()
    next_callable.assert_called_once_with()


def test_run_all_jobs_stops_after_loader_errors_when_stop_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    error_callable = MagicMock(
        return_value=SimpleNamespace(inserted=0, skipped=0, quarantined=0, superseded=0, errors=1)
    )
    next_callable = MagicMock(
        return_value=SimpleNamespace(inserted=1, skipped=0, quarantined=0, superseded=0, errors=0)
    )
    jobs = [
        _job_for_tests(key="loader-error", run_callable=error_callable),
        _job_for_tests(key="next", run_callable=next_callable),
    ]

    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=None))
    monkeypatch.setattr(runner, "sync_data_source_metadata", MagicMock())
    monkeypatch.setattr(runner, "insert_refresh_run", MagicMock())

    results = runner.run_all_jobs(connection, jobs, force=True, stop_on_failure=True)

    assert [result.status for result in results] == ["degraded"]
    assert results[0].message == (
        "Refresh job completed with loader errors: inserted=0 skipped=0 quarantined=0 superseded=0 errors=1"
    )
    error_callable.assert_called_once_with()
    next_callable.assert_not_called()


def test_run_all_jobs_commits_after_successful_job(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    job = _job_for_tests(key="commit-check")
    result = runner.RefreshRunResult(
        key="commit-check",
        status="success",
        metadata_updates=1,
        message="Refresh job succeeded",
    )
    run_job = MagicMock(return_value=result)
    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(connection, [job], dry_run=False, force=True)

    assert [item.status for item in results] == ["success"]
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()


def test_run_all_jobs_rolls_back_failed_job_result(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    job = _job_for_tests(key="rollback-check")
    result = runner.RefreshRunResult(
        key="rollback-check",
        status="failed",
        metadata_updates=0,
        message="Refresh-run recording failed",
        error="boom",
    )
    run_job = MagicMock(return_value=result)
    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(connection, [job], dry_run=False, force=True)

    assert [item.status for item in results] == ["failed"]
    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()


def test_run_all_jobs_isolates_gating_failures_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    first_job = _job_for_tests(key="first")
    second_job = _job_for_tests(key="second")
    second_result = runner.RefreshRunResult(
        key="second",
        status="success",
        metadata_updates=1,
        message="Refresh job succeeded",
    )
    select_latest_pull_at = MagicMock(side_effect=[RuntimeError("metadata read failed"), None])
    run_job = MagicMock(return_value=second_result)

    monkeypatch.setattr(runner, "_select_latest_pull_at", select_latest_pull_at)
    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(connection, [first_job, second_job], dry_run=False, force=False)

    assert [result.status for result in results] == ["failed", "success"]
    assert results[0].message == "Refresh orchestration failed"
    assert results[0].error == "metadata read failed"
    run_job.assert_called_once_with(connection, second_job, dry_run=False)


def test_run_all_jobs_streams_results_via_on_result_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    job_a = _job_for_tests(key="job-a")
    job_b = _job_for_tests(key="job-b")
    result_a = runner.RefreshRunResult(key="job-a", status="success", metadata_updates=1, message="ok")
    result_b = runner.RefreshRunResult(key="job-b", status="failed", metadata_updates=0, message="err", error="boom")
    run_job = MagicMock(side_effect=[result_a, result_b])
    monkeypatch.setattr(runner, "run_job", run_job)

    streamed: list[runner.RefreshRunResult] = []
    results = runner.run_all_jobs(connection, [job_a, job_b], force=True, on_result=streamed.append)

    assert streamed == results
    assert [r.key for r in streamed] == ["job-a", "job-b"]


def test_run_all_jobs_force_skips_cadence_lookup_and_executes_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    first_job = _job_for_tests(key="first")
    second_job = _job_for_tests(key="second")
    first_result = runner.RefreshRunResult(
        key="first",
        status="success",
        metadata_updates=1,
        message="Refresh job succeeded",
    )
    second_result = runner.RefreshRunResult(
        key="second",
        status="success",
        metadata_updates=1,
        message="Refresh job succeeded",
    )
    select_latest_pull_at = MagicMock(side_effect=RuntimeError("should not be called in force mode"))
    run_job = MagicMock(side_effect=[first_result, second_result])

    monkeypatch.setattr(runner, "_select_latest_pull_at", select_latest_pull_at)
    monkeypatch.setattr(runner, "run_job", run_job)

    results = runner.run_all_jobs(connection, [first_job, second_job], dry_run=False, force=True)

    assert [result.status for result in results] == ["success", "success"]
    select_latest_pull_at.assert_not_called()
    assert run_job.call_count == 2


def test_build_refresh_plan_wires_nj_run_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    run_nj_refresh = MagicMock()
    monkeypatch.setattr(job_builders, "run_nj_refresh", run_nj_refresh)

    jobs = job_builders.build_refresh_plan(scope="all")
    jobs_by_key = {job.key: job for job in jobs}

    assert "state-nj-contributions" in jobs_by_key
    assert jobs_by_key["state-nj-contributions"].data_source_names == ("ELEC Reports and Data Search Export API",)
    assert jobs_by_key["state-nj-contributions"].cadence == "quarterly"

    jobs_by_key["state-nj-contributions"].run_callable()
    run_nj_refresh.assert_called_once_with(data_type="contributions", download=True)


def test_build_state_jobs_download_states_call_download_builder_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    configs_by_state_code = job_builders._discover_configs_by_state_code()
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    parameters = runner.RunnerParameters()
    build_download_transaction_jobs = MagicMock(return_value=[])
    monkeypatch.setattr(job_builders, "_build_download_transaction_jobs", build_download_transaction_jobs)

    for state_code in (
        "AL",
        "CO",
        "FL",
        "IN",
        "KY",
        "LA",
        "MA",
        "MN",
        "NE",
        "NJ",
        "NY",
        "OR",
        "PA",
        "TX",
        "VA",
        "WA",
        "WI",
    ):
        job_builders._build_state_jobs(configs_by_state_code[state_code], parameters=parameters, now=now)

    assert [call.kwargs for call in build_download_transaction_jobs.call_args_list] == [
        _download_job_call(
            "AL",
            job_builders.AL_LOADABLE_REFRESH_DATA_TYPES,
            job_builders.run_al_refresh,
            year_from=2022,
        ),
        _download_job_call(
            "CO",
            ("contributions", "expenditures"),
            job_builders.run_co_refresh,
            year=2026,
            allow_insecure_tls=True,
        ),
        _download_job_call("FL", job_builders.FL_LOADABLE_REFRESH_DATA_TYPES, job_builders.run_fl_refresh),
        _download_job_call("IN", ("contributions", "expenditures"), job_builders.run_in_refresh, year=2026),
        # KY now uses _build_ky_jobs with election-date scoping — does not call
        # _build_download_transaction_jobs, so it doesn't appear in this list.
        _download_job_call("LA", job_builders.LA_LOADABLE_REFRESH_DATA_TYPES, job_builders.run_la_refresh, year=2026),
        _download_job_call("MA", ("contributions", "expenditures"), job_builders.run_ma_refresh),
        _download_job_call(
            "MN",
            ("contributions", "expenditures", "independent_expenditures"),
            job_builders.run_mn_refresh,
        ),
        _download_job_call("NE", job_builders.NE_LOADABLE_REFRESH_DATA_TYPES, job_builders.run_ne_refresh, year=2026),
        _download_job_call("NJ", ("contributions",), job_builders.run_nj_refresh),
        _download_job_call(
            "NY",
            ("contributions", "expenditures", "independent_expenditures"),
            job_builders.run_ny_refresh,
        ),
        _download_job_call(
            "OR",
            job_builders.OR_LOADABLE_REFRESH_DATA_TYPES,
            job_builders.run_or_refresh,
            year_from=2022,
        ),
        _download_job_call("PA", job_builders.PA_LOADABLE_REFRESH_DATA_TYPES, job_builders.run_pa_refresh, year=2026),
        _download_job_call(
            "TX",
            ("contributions", "expenditures", "loans"),
            job_builders.run_tx_refresh,
            year_from=2022,
        ),
        _download_job_call(
            "VA",
            ("contributions", "expenditures"),
            job_builders.run_va_refresh,
            year_month="2026_06",
        ),
        _download_job_call(
            "WA",
            ("contributions", "expenditures", "independent_expenditures", "loans"),
            job_builders.run_wa_refresh,
        ),
        _download_job_call("WI", ("transactions",), job_builders.run_wi_refresh),
    ]


def test_build_argument_parser_accepts_civic_candidate_listing_flags() -> None:
    parser = runner.build_argument_parser()

    args = parser.parse_args(
        [
            "--dry-run",
            "--job-key-prefix",
            "civic-nc-candidate-listing",
            "--job-key-prefix",
            "state-nc",
            "--year-from",
            "2023",
            "--candidate-listing-path",
            "/tmp/nc-candidate-listing.csv",
        ]
    )

    assert args.job_key_prefixes == ["civic-nc-candidate-listing", "state-nc"]
    assert args.year_from == 2023
    assert args.candidate_listing_path == Path("/tmp/nc-candidate-listing.csv")


def test_build_argument_parser_accepts_federal_scope() -> None:
    parser = runner.build_argument_parser()

    args = parser.parse_args(["--scope", "federal"])

    assert args.scope == "federal"


def test_main_threads_civic_candidate_listing_parameters_to_runner_and_job_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_build_refresh_plan(*, scope: str, parameters: runner.RunnerParameters, job_key_prefixes: tuple[str, ...]):
        captured["scope"] = scope
        captured["parameters"] = parameters
        captured["job_key_prefixes"] = job_key_prefixes
        return []

    monkeypatch.setattr(job_builders, "build_refresh_plan", _fake_build_refresh_plan)
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: [])

    exit_code = runner.main(
        [
            "--dry-run",
            "--job-key-prefix",
            "civic-nc-candidate-listing",
            "--year-from",
            "2022",
            "--candidate-listing-path",
            "/tmp/candidate_listing_fixture.csv",
        ]
    )

    assert exit_code == 0
    assert captured["scope"] == "all"
    assert captured["job_key_prefixes"] == ("civic-nc-candidate-listing",)
    parameters = captured["parameters"]
    assert isinstance(parameters, runner.RunnerParameters)
    assert parameters.year_from == 2022
    assert parameters.candidate_listing_path == Path("/tmp/candidate_listing_fixture.csv")


def _federal_result(key: str, status: str) -> runner.RefreshRunResult:
    return runner.RefreshRunResult(key=key, status=status, metadata_updates=0, message=f"{status} for {key}")


def test_main_threads_federal_prefix_to_build_refresh_plan_and_exits_zero_on_all_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    all_success_results = [
        _federal_result("federal-fec-schedule-a", "success"),
        _federal_result("federal-fec-masters", "success"),
        _federal_result("federal-congress-spine", "success"),
        _federal_result("federal-fec-schedule-b", "success"),
        _federal_result("federal-fec-schedule-e", "success"),
        _federal_result("federal-enrichment", "success"),
        _federal_result("federal-irs-527", "success"),
    ]

    def _fake_build_refresh_plan(*, scope: str, parameters: runner.RunnerParameters, job_key_prefixes: tuple[str, ...]):
        captured["scope"] = scope
        captured["parameters"] = parameters
        captured["job_key_prefixes"] = job_key_prefixes
        return []

    monkeypatch.setattr(job_builders, "build_refresh_plan", _fake_build_refresh_plan)
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: all_success_results)

    exit_code = runner.main(["--dry-run", "--force", "--job-key-prefix", "federal-"])

    assert exit_code == 0
    assert captured["job_key_prefixes"] == ("federal-",)
    assert captured["scope"] == "all"


def test_main_threads_federal_scope_to_build_refresh_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_build_refresh_plan(*, scope: str, parameters: runner.RunnerParameters, job_key_prefixes: tuple[str, ...]):
        captured["scope"] = scope
        captured["parameters"] = parameters
        captured["job_key_prefixes"] = job_key_prefixes
        return []

    monkeypatch.setattr(job_builders, "build_refresh_plan", _fake_build_refresh_plan)
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: [])

    exit_code = runner.main(["--dry-run", "--scope", "federal"])

    assert exit_code == 0
    assert captured["scope"] == "federal"
    assert captured["job_key_prefixes"] == ()
    assert isinstance(captured["parameters"], runner.RunnerParameters)


def test_main_enables_fail_fast_for_federal_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    job = _job_for_tests(key="federal-fec-masters")

    class FakeConnection:
        def close(self) -> None:
            pass

    def _fake_run_all_jobs(*args: object, **kwargs: object) -> list[runner.RefreshRunResult]:
        captured["jobs"] = args[1]
        captured["stop_on_failure"] = kwargs["stop_on_failure"]
        return [runner.RefreshRunResult(key=job.key, status="success", metadata_updates=0, message="ok")]

    monkeypatch.setattr(job_builders, "build_refresh_plan", lambda **kwargs: [job])
    monkeypatch.setattr(runner, "get_connection", lambda: FakeConnection())
    monkeypatch.setattr(runner, "run_all_jobs", _fake_run_all_jobs)

    exit_code = runner.main(["--scope", "federal", "--no-lock"])

    assert exit_code == 0
    assert captured["jobs"] == [job]
    assert captured["stop_on_failure"] is True


@pytest.mark.parametrize("failing_status", ["empty", "degraded", "failed", "crashed"])
def test_main_returns_non_zero_when_any_federal_result_is_failing(
    monkeypatch: pytest.MonkeyPatch,
    failing_status: str,
) -> None:
    mixed_results = [
        _federal_result("federal-fec-schedule-a", "success"),
        _federal_result("federal-fec-masters", failing_status),
        _federal_result("federal-congress-spine", "success"),
    ]
    monkeypatch.setattr(
        job_builders,
        "build_refresh_plan",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(runner, "run_all_jobs", lambda *args, **kwargs: mixed_results)

    exit_code = runner.main(["--dry-run", "--force", "--job-key-prefix", "federal-"])

    assert exit_code == 1, (
        f"runner.main() must exit non-zero when any federal result is {failing_status!r} so an honest "
        "rerun cannot silently look successful"
    )
