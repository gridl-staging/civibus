from __future__ import annotations

import zipfile
from datetime import datetime, timedelta, timezone
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from core.refresh import job_builders, runner
from core.refresh.test_job_builders import _EXPECTED_FEDERAL_JOB_KEYS
from domains.campaign_finance.ingest.federal_spine_loader import SpineLoadResult
from domains.civics.loaders.ncsbe_results import NcsbeResultsLoadSummary
from domains.civics.loaders.official_rosters.source_registry import list_nc_roster_source_metadata


def _job_for_tests(*, key: str, run_callable: MagicMock | None = None) -> runner.RefreshJob:
    return runner.RefreshJob(
        key=key,
        domain="campaign_finance",
        jurisdiction="state/CO",
        cadence="daily",
        data_source_names=("TRACER Bulk Download — Contributions",),
        run_callable=run_callable or MagicMock(),
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
        "federal-congress-spine",
        "federal-enrichment",
        "federal-fec-schedule-e",
        "federal-irs-527",
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

    assert len(job_keys) == 112
    assert "state-nc-ie-transactions" not in job_keys
    assert "state-nc-transactions" not in job_keys
    assert "state-nc-ie-document-index" not in job_keys
    assert "civics-nc-past-results-2022-2024" not in job_keys


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

    assert len(job_keys_without_nc) == 112
    assert len(job_keys_with_transaction_nc) == 113
    assert len(job_keys_with_ie_nc) == 114
    assert len(job_keys_with_both_nc) == 115
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

    assert job_keys == _EXPECTED_FEDERAL_JOB_KEYS
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
        "federal-fec-committee-summary",
        "federal-fec-schedule-a",
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

    monkeypatch.setattr(runner, "_select_latest_pull_at", MagicMock(return_value=now - timedelta(days=1)))
    monkeypatch.setattr(runner, "_record_refresh_run", MagicMock())
    monkeypatch.setattr(runner, "_select_data_source_id", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)

    skipped_result = runner._run_gated_job(connection, hydrated_job, force=False, now=now)
    assert skipped_result.status == "skipped"
    run_callable.assert_not_called()
    sync_data_source_metadata.assert_not_called()

    runner._select_latest_pull_at.return_value = now - timedelta(days=8)
    run_result = runner._run_gated_job(connection, hydrated_job, force=False, now=now)
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

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=541 skipped=1 quarantined=0 superseded=0 errors=1"
    refresh_run = insert_refresh_run.call_args.args[1]
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

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=60 skipped=6 quarantined=1 superseded=1 errors=1"
    refresh_run = insert_refresh_run.call_args.args[1]
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
    monkeypatch.setattr(runner, "_recent_nonempty_insert_counts", MagicMock(return_value=[120, 140, 160]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "success"
    assert result.message == "Refresh job succeeded: inserted=0 skipped=37 quarantined=0 superseded=0 errors=0"
    refresh_run = insert_refresh_run.call_args.args[1]
    assert refresh_run.pull_status == "success"
    assert refresh_run.inserted_count == 0
    assert refresh_run.skipped_count == 37


def test_run_job_records_degraded_pull_status_when_inserted_count_is_below_recent_median(
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
    monkeypatch.setattr(runner, "_recent_nonempty_insert_counts", MagicMock(return_value=[180, 200, 220]))
    monkeypatch.setattr(runner, "sync_data_source_metadata", sync_data_source_metadata)
    monkeypatch.setattr(runner, "insert_refresh_run", insert_refresh_run)

    result = runner.run_job(connection, job)

    assert result.status == "degraded"
    assert result.message == "Refresh job completed below historical volume threshold: inserted=80 median=200"
    sync_data_source_metadata.assert_not_called()
    assert insert_refresh_run.call_args.args[1].pull_status == "degraded"


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
