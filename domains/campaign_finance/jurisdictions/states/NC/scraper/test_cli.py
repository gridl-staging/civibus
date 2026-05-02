from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from domains.campaign_finance.jurisdictions.states.NC.scraper import cli
from domains.campaign_finance.jurisdictions.states.NC.scraper.cli_test_support import (
    SAMPLE_COMMITTEE_DOCS,
    SAMPLE_IE_DOCUMENT_INDEX,
    SAMPLE_TRANSACTIONS,
    build_committee_document_path_args,
    build_download_transaction_args,
    build_ie_document_index_path_args,
    build_orchestrate_args,
    build_transaction_path_args,
    patch_download_resolution,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.download import (
    TransactionSearchCriteria,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.committee_registry import (
    NCCommitteeRegistryRow,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import LoadResult


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=7,
        skipped=2,
        quarantined=1,
        superseded=0,
        errors=0,
        elapsed_seconds=0.5,
    )


@pytest.fixture(autouse=True)
def _stub_l6_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "build_load_id", MagicMock(return_value="nc-transactions-test-load"))
    monkeypatch.setattr(
        cli,
        "run_l6_gate_for_nc_load",
        MagicMock(
            return_value=SimpleNamespace(
                load_id="nc-transactions-test-load",
                total_rows=5,
                out_of_range_rows=0,
                example_rows=[],
                evidence_path=Path("/tmp/l6.json"),
                status="pass",
            )
        ),
    )


def test_main_dry_run_transactions_prints_summary_without_db_connection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    exit_code = cli.main(build_transaction_path_args("--dry-run"))
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "parsed=5" in captured.out
    assert "quarantined=0" in captured.out
    assert captured.err == ""
    get_connection.assert_not_called()


def test_main_download_dry_run_downloads_then_prints_summary_without_db(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    class _FakeParser:
        skipped = 0

        def __iter__(self):
            yield {"row": "1"}

    download_mock, downloaded_path = patch_download_resolution(
        monkeypatch,
        tmp_path,
        cli_module=cli,
    )
    get_connection = MagicMock()
    parse_transactions = MagicMock(return_value=_FakeParser())

    monkeypatch.setattr(cli, "get_connection", get_connection)
    monkeypatch.setattr(cli, "parse_transactions", parse_transactions)

    exit_code = cli.main(build_download_transaction_args("--dry-run", output_path=str(downloaded_path)))
    captured = capsys.readouterr()

    assert exit_code == 0
    download_mock.assert_called_once_with(
        TransactionSearchCriteria(
            date_from="01/01/2024",
            date_to="01/31/2024",
            committee_id="C12345",
        ),
        downloaded_path,
    )
    assert "parsed=1" in captured.out
    assert captured.err == ""
    get_connection.assert_not_called()
    parse_transactions.assert_called_once_with(downloaded_path)


def test_main_dry_run_committee_documents_routes_to_committee_parser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    class _FakeParser:
        def __init__(self) -> None:
            self.skipped = 3

        def __iter__(self):
            yield {"row": "1"}
            yield {"row": "2"}

    parser = _FakeParser()
    parse_committee_docs = MagicMock(return_value=parser)
    parse_transactions = MagicMock()
    get_connection = MagicMock()

    monkeypatch.setattr(cli, "parse_committee_docs", parse_committee_docs)
    monkeypatch.setattr(cli, "parse_transactions", parse_transactions)
    monkeypatch.setattr(cli, "get_connection", get_connection)

    exit_code = cli.main(build_committee_document_path_args("--dry-run"))
    captured = capsys.readouterr()

    assert exit_code == 0
    parse_committee_docs.assert_called_once_with(SAMPLE_COMMITTEE_DOCS)
    parse_transactions.assert_not_called()
    get_connection.assert_not_called()
    assert "parsed=2" in captured.out
    assert "quarantined=3" in captured.out
    assert captured.err == ""


def test_main_dry_run_ie_document_index_routes_to_committee_parser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    class _FakeParser:
        def __init__(self) -> None:
            self.skipped = 1

        def __iter__(self):
            yield {"row": "1"}

    parser = _FakeParser()
    parse_committee_docs = MagicMock(return_value=parser)
    parse_transactions = MagicMock()
    get_connection = MagicMock()

    monkeypatch.setattr(cli, "parse_committee_docs", parse_committee_docs)
    monkeypatch.setattr(cli, "parse_transactions", parse_transactions)
    monkeypatch.setattr(cli, "get_connection", get_connection)

    exit_code = cli.main(build_ie_document_index_path_args("--dry-run"))
    captured = capsys.readouterr()

    assert exit_code == 0
    parse_committee_docs.assert_called_once_with(SAMPLE_IE_DOCUMENT_INDEX)
    parse_transactions.assert_not_called()
    get_connection.assert_not_called()
    assert "parsed=1" in captured.out
    assert "quarantined=1" in captured.out
    assert captured.err == ""


def test_main_dry_run_limit_zero_matches_loader_counting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    class _FakeParser:
        def __init__(self) -> None:
            self.skipped = 0

        def __iter__(self):
            self.skipped = 2
            yield {"row": "1"}
            yield {"row": "2"}

    parser = _FakeParser()

    monkeypatch.setattr(cli, "parse_transactions", MagicMock(return_value=parser))
    monkeypatch.setattr(cli, "get_connection", MagicMock())

    exit_code = cli.main(build_transaction_path_args("--dry-run", "--limit", "0"))
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "parsed=0" in captured.out
    assert "quarantined=2" in captured.out
    assert captured.err == ""


def test_main_loads_transactions_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    data_source_id = UUID("2d9a99f3-fb34-4fbc-8a99-9f86b6244f31")
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock(return_value=data_source_id))
    load_nc_transactions = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    exit_code = cli.main(build_transaction_path_args())
    captured = capsys.readouterr()

    assert exit_code == 0
    load_nc_transactions.assert_called_once_with(
        connection,
        SAMPLE_TRANSACTIONS,
        data_source_id=data_source_id,
        limit=None,
    )
    assert "inserted=7" in captured.out
    assert "skipped=2" in captured.out
    assert "quarantined=1" in captured.out
    assert "superseded=0" in captured.out
    assert "errors=0" in captured.out
    assert "--committee-docs-path not provided" in captured.err
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once()


def test_main_aborts_before_load_when_l6_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    load_nc_transactions = MagicMock()

    monkeypatch.setattr(
        cli,
        "run_l6_gate_for_nc_load",
        MagicMock(
            return_value=SimpleNamespace(
                load_id="nc-transactions-20260424T000000Z",
                total_rows=1,
                out_of_range_rows=1,
                example_rows=[],
                evidence_path=Path("/tmp/l6.json"),
                status="fail",
            )
        ),
    )
    monkeypatch.setattr(cli, "get_connection", MagicMock())
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    exit_code = cli.main(build_transaction_path_args())
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "NC ingest failed: L6 temporal gate failed" in captured.err
    load_nc_transactions.assert_not_called()


def test_main_passes_limit_to_transaction_loader(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    data_source_id = UUID("16cd95a6-f458-4b72-a970-75ed70760b40")
    load_result = _build_load_result()
    load_nc_transactions = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    exit_code = cli.main(build_transaction_path_args("--limit", "2"))
    captured = capsys.readouterr()

    assert exit_code == 0
    assert load_nc_transactions.call_args.kwargs["limit"] == 2
    assert "--committee-docs-path not provided" in captured.err


def test_main_routes_to_with_filings_when_committee_docs_path_provided(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    ensure_nc_data_source = MagicMock()
    ensure_nc_committee_document_data_source = MagicMock()
    load_nc_committee_documents = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", ensure_nc_data_source)
    monkeypatch.setattr(
        cli,
        "ensure_nc_committee_document_data_source",
        ensure_nc_committee_document_data_source,
    )
    monkeypatch.setattr(cli, "load_nc_committee_documents", load_nc_committee_documents)
    load_nc_transactions_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_nc_transactions_with_filings", load_nc_transactions_with_filings)
    load_nc_transactions = MagicMock()
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    exit_code = cli.main(build_transaction_path_args("--committee-docs-path", str(SAMPLE_COMMITTEE_DOCS)))
    captured = capsys.readouterr()

    assert exit_code == 0
    load_nc_transactions_with_filings.assert_called_once_with(
        connection,
        SAMPLE_TRANSACTIONS,
        SAMPLE_COMMITTEE_DOCS,
        limit=None,
    )
    load_nc_transactions.assert_not_called()
    ensure_nc_data_source.assert_not_called()
    ensure_nc_committee_document_data_source.assert_not_called()
    load_nc_committee_documents.assert_not_called()
    assert "inserted=7" in captured.out
    assert captured.err == ""
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once()


def test_main_download_routes_to_with_filings_when_committee_docs_path_provided(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    download_mock, downloaded_path = patch_download_resolution(
        monkeypatch,
        tmp_path,
        cli_module=cli,
    )

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_nc_transactions_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_nc_transactions_with_filings", load_nc_transactions_with_filings)
    monkeypatch.setattr(cli, "load_nc_transactions", MagicMock())
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock())

    exit_code = cli.main(
        build_download_transaction_args(
            "--committee-docs-path",
            str(SAMPLE_COMMITTEE_DOCS),
            "--trans-type",
            "exp",
            output_path=str(downloaded_path),
        )
    )

    assert exit_code == 0
    download_mock.assert_called_once_with(
        TransactionSearchCriteria(
            trans_type="exp",
            date_from="01/01/2024",
            date_to="01/31/2024",
            committee_id="C12345",
        ),
        downloaded_path,
    )
    load_nc_transactions_with_filings.assert_called_once_with(
        connection,
        downloaded_path,
        SAMPLE_COMMITTEE_DOCS,
        limit=None,
    )


def test_main_download_routes_to_provenance_fallback_when_committee_docs_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    data_source_id = UUID("1a0fccd3-f580-4ed0-93d8-e529f301ca2f")
    download_mock, downloaded_path = patch_download_resolution(
        monkeypatch,
        tmp_path,
        cli_module=cli,
    )
    load_nc_transactions = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    exit_code = cli.main(build_download_transaction_args(output_path=str(downloaded_path)))
    captured = capsys.readouterr()

    assert exit_code == 0
    download_mock.assert_called_once()
    load_nc_transactions.assert_called_once_with(
        connection,
        downloaded_path,
        data_source_id=data_source_id,
        limit=None,
    )
    assert "--committee-docs-path not provided" in captured.err


def test_main_download_maps_committee_name_into_search_criteria(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    data_source_id = UUID("b2add46f-eb3a-4fdb-a0bc-cdce30f32a8d")
    download_mock, downloaded_path = patch_download_resolution(
        monkeypatch,
        tmp_path,
        cli_module=cli,
    )
    load_nc_transactions = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    exit_code = cli.main(
        build_download_transaction_args(
            committee_id=None,
            committee_name="Example Committee",
            output_path=str(downloaded_path),
        )
    )

    assert exit_code == 0
    download_mock.assert_called_once_with(
        TransactionSearchCriteria(
            committee_name="Example Committee",
            date_from="01/01/2024",
            date_to="01/31/2024",
        ),
        downloaded_path,
    )
    load_nc_transactions.assert_called_once_with(
        connection,
        downloaded_path,
        data_source_id=data_source_id,
        limit=None,
    )


def test_main_download_maps_both_committee_filters_into_search_criteria(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    data_source_id = UUID("9f32c50d-cd25-46b7-b55f-a29a3a19dbe1")
    download_mock, downloaded_path = patch_download_resolution(
        monkeypatch,
        tmp_path,
        cli_module=cli,
    )
    load_nc_transactions = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    exit_code = cli.main(
        build_download_transaction_args(
            committee_name="Example Committee",
            output_path=str(downloaded_path),
        )
    )

    assert exit_code == 0
    download_mock.assert_called_once_with(
        TransactionSearchCriteria(
            committee_name="Example Committee",
            committee_id="C12345",
            date_from="01/01/2024",
            date_to="01/31/2024",
        ),
        downloaded_path,
    )
    load_nc_transactions.assert_called_once_with(
        connection,
        downloaded_path,
        data_source_id=data_source_id,
        limit=None,
    )


def test_main_download_preserves_2026_cycle_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()
    data_source_id = UUID("c7d0b4a4-d86a-46cb-a592-93db61525796")
    download_mock, downloaded_path = patch_download_resolution(
        monkeypatch,
        tmp_path,
        cli_module=cli,
    )
    load_nc_transactions = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    exit_code = cli.main(
        build_download_transaction_args(
            committee_name="Example Committee",
            output_path=str(downloaded_path),
            date_from="01/01/2026",
            date_to="03/14/2026",
        )
    )

    assert exit_code == 0
    download_mock.assert_called_once_with(
        TransactionSearchCriteria(
            committee_name="Example Committee",
            committee_id="C12345",
            date_from="01/01/2026",
            date_to="03/14/2026",
        ),
        downloaded_path,
    )
    load_nc_transactions.assert_called_once_with(
        connection,
        downloaded_path,
        data_source_id=data_source_id,
        limit=None,
    )


def test_main_routes_to_with_filings_forwards_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    load_nc_transactions_with_filings = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_nc_transactions_with_filings", load_nc_transactions_with_filings)

    exit_code = cli.main(
        build_transaction_path_args(
            "--committee-docs-path",
            str(SAMPLE_COMMITTEE_DOCS),
            "--limit",
            "5",
        )
    )

    assert exit_code == 0
    assert load_nc_transactions_with_filings.call_args.kwargs["limit"] == 5


def test_main_committee_documents_loads_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    committee_doc_source_id = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "ensure_nc_committee_document_data_source",
        MagicMock(return_value=committee_doc_source_id),
    )
    load_nc_committee_documents = MagicMock(return_value=(load_result, {}))
    monkeypatch.setattr(cli, "load_nc_committee_documents", load_nc_committee_documents)

    exit_code = cli.main(build_committee_document_path_args())
    captured = capsys.readouterr()

    assert exit_code == 0
    load_nc_committee_documents.assert_called_once_with(
        connection,
        SAMPLE_COMMITTEE_DOCS,
        data_source_id=committee_doc_source_id,
        limit=None,
    )
    assert "inserted=7" in captured.out
    assert captured.err == ""
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once()


def test_main_ie_document_index_loads_and_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    ie_source_id = UUID("f0e5a9da-0567-43a1-b57f-4ad04567495f")
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "ensure_nc_ie_document_index_data_source",
        MagicMock(return_value=ie_source_id),
    )
    load_nc_ie_document_index = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_nc_ie_document_index", load_nc_ie_document_index)
    load_nc_transactions = MagicMock()
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    exit_code = cli.main(build_ie_document_index_path_args())
    captured = capsys.readouterr()

    assert exit_code == 0
    load_nc_ie_document_index.assert_called_once_with(
        connection,
        SAMPLE_IE_DOCUMENT_INDEX,
        data_source_id=ie_source_id,
        limit=None,
    )
    load_nc_transactions.assert_not_called()
    assert "inserted=7" in captured.out
    assert captured.err == ""
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once()


def test_main_ie_document_index_passes_limit_to_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    ie_source_id = UUID("f0e5a9da-0567-43a1-b57f-4ad04567495f")
    load_result = _build_load_result()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "ensure_nc_ie_document_index_data_source",
        MagicMock(return_value=ie_source_id),
    )
    load_nc_ie_document_index = MagicMock(return_value=load_result)
    monkeypatch.setattr(cli, "load_nc_ie_document_index", load_nc_ie_document_index)

    exit_code = cli.main(build_ie_document_index_path_args("--limit", "10"))

    assert exit_code == 0
    assert load_nc_ie_document_index.call_args.kwargs["limit"] == 10


def test_main_returns_error_and_closes_connection_when_load_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    error = RuntimeError("load exploded")

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock(return_value=UUID(int=1)))
    monkeypatch.setattr(cli, "load_nc_transactions", MagicMock(side_effect=error))

    exit_code = cli.main(build_transaction_path_args())
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "NC ingest failed: load exploded" in captured.err
    connection.commit.assert_not_called()
    connection.close.assert_called_once()


def test_main_returns_error_when_download_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "retained-download.csv"
    download_mock = MagicMock(side_effect=RuntimeError("download exploded"))
    monkeypatch.setattr(
        cli,
        "download_transaction_export_playwright",
        download_mock,
    )
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    exit_code = cli.main(build_download_transaction_args(output_path=str(output_path)))
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "NC ingest failed: download exploded" in captured.err
    download_mock.assert_called_once_with(
        TransactionSearchCriteria(
            date_from="01/01/2024",
            date_to="01/31/2024",
            committee_id="C12345",
        ),
        output_path,
    )
    get_connection.assert_not_called()


def test_main_returns_error_and_keeps_user_download_output_path_when_load_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    download_mock, downloaded_path = patch_download_resolution(
        monkeypatch,
        tmp_path,
        cli_module=cli,
    )

    def _write_downloaded_file(_criteria: TransactionSearchCriteria, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("TRAN_ID\n1\n")

    download_mock.side_effect = _write_downloaded_file
    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock(return_value=UUID(int=1)))
    monkeypatch.setattr(
        cli,
        "load_nc_transactions",
        MagicMock(side_effect=RuntimeError("load exploded")),
    )

    exit_code = cli.main(build_download_transaction_args(output_path=str(downloaded_path)))
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "NC ingest failed: load exploded" in captured.err
    connection.close.assert_called_once_with()
    assert downloaded_path.exists()


def test_main_returns_error_and_closes_connection_when_committee_document_load_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    error = RuntimeError("committee doc load failed")

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "ensure_nc_committee_document_data_source",
        MagicMock(return_value=UUID(int=2)),
    )
    monkeypatch.setattr(cli, "load_nc_committee_documents", MagicMock(side_effect=error))

    exit_code = cli.main(build_committee_document_path_args())
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "NC ingest failed: committee doc load failed" in captured.err
    connection.commit.assert_not_called()
    connection.close.assert_called_once()


def test_run_nc_refresh_executes_typed_transaction_path_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    data_source_id = UUID("5dd6ca9d-d1a2-4a31-a8f7-85ea4f6b8ac2")
    load_result = _build_load_result()
    load_nc_transactions = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "ensure_nc_data_source", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(cli, "load_nc_transactions", load_nc_transactions)

    result = cli.run_nc_refresh(data_type="transactions", path=SAMPLE_TRANSACTIONS, limit=4)

    assert result == load_result
    load_nc_transactions.assert_called_once_with(
        connection,
        SAMPLE_TRANSACTIONS,
        data_source_id=data_source_id,
        limit=4,
    )
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_nc_refresh_executes_committee_discovery_crawler_and_registry_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    discovered_rows = {
        3970: NCCommitteeRegistryRow(
            org_group_id=3970,
            sboe_id="STA-C3672N-C-001",
            committee_name="01ST CONG DIST BLACK LEADERSHIP CAUCUS",
            status_desc="CLOSED",
            old_id="7940000",
            candidate_name="CIVIC",
        )
    }
    load_result = _build_load_result()
    crawl_committee_registry_httpx = MagicMock(return_value=discovered_rows)
    load_nc_committee_registry_rows = MagicMock(return_value=load_result)

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(cli, "crawl_committee_registry_httpx", crawl_committee_registry_httpx)
    monkeypatch.setattr(cli, "load_nc_committee_registry_rows", load_nc_committee_registry_rows)

    result = cli.run_nc_refresh(data_type="committee-discovery")

    assert result == load_result
    crawl_committee_registry_httpx.assert_called_once_with()
    load_nc_committee_registry_rows.assert_called_once()
    loaded_rows = tuple(load_nc_committee_registry_rows.call_args.args[1])
    assert loaded_rows == tuple(discovered_rows.values())
    assert load_nc_committee_registry_rows.call_args.kwargs["limit"] is None
    cli.build_load_id.assert_not_called()
    cli.run_l6_gate_for_nc_load.assert_not_called()
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_run_nc_refresh_executes_pathless_ie_transactions_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    ie_source_id = UUID("f9367f9d-35ea-48e7-a2fb-3d2683ce0016")
    load_result = _build_load_result()
    load_nc_ie_transactions = MagicMock(return_value=load_result)
    run_l6_gate_for_nc_load = MagicMock()

    monkeypatch.setattr(cli, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(
        cli,
        "ensure_nc_ie_document_index_data_source",
        MagicMock(return_value=ie_source_id),
    )
    monkeypatch.setattr(cli, "load_nc_ie_transactions", load_nc_ie_transactions, raising=False)
    monkeypatch.setattr(cli, "run_l6_gate_for_nc_load", run_l6_gate_for_nc_load)

    result = cli.run_nc_refresh(data_type="ie-transactions", limit=3)

    assert result == load_result
    load_nc_ie_transactions.assert_called_once_with(
        connection,
        data_source_id=ie_source_id,
        limit=3,
    )
    run_l6_gate_for_nc_load.assert_not_called()
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_main_dispatches_orchestrator_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    orchestrator_result = SimpleNamespace(
        seeded=3,
        reclaimed=1,
        claimed=2,
        completed=2,
        year_filtered=7,
        retryable_failures=0,
        permanent_failures=0,
    )
    run_nc_committee_orchestrator = MagicMock(return_value=orchestrator_result)
    run_nc_refresh = MagicMock()
    select_mvp_scope_committees = MagicMock(return_value=["STA-C0001", "STA-C0003"])
    get_connection = MagicMock()

    monkeypatch.setattr(cli, "run_nc_committee_orchestrator", run_nc_committee_orchestrator)
    monkeypatch.setattr(cli, "run_nc_refresh", run_nc_refresh)
    monkeypatch.setattr(cli, "select_mvp_scope_committees", select_mvp_scope_committees)
    monkeypatch.setattr(cli, "get_connection", get_connection)

    exit_code = cli.main(
        build_orchestrate_args(
            "--limit",
            "2",
            "--politeness-delay-seconds",
            "1.25",
            "--committees-from-query",
            "--year-from",
            "2022",
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    run_nc_committee_orchestrator.assert_called_once_with(
        window_start=date.fromisoformat("2025-01-01"),
        window_end=date.fromisoformat("2025-01-31"),
        limit=2,
        stale_after_minutes=60,
        politeness_delay_seconds=1.25,
        allowlist_sboe_ids=["STA-C0001", "STA-C0003"],
        year_from=2022,
    )
    get_connection.assert_called_once_with()
    select_mvp_scope_committees.assert_called_once()
    run_nc_refresh.assert_not_called()
    assert "NC committee orchestrator complete" in captured.out
    assert "completed=2" in captured.out
    assert "year_filtered=7" in captured.out
    assert captured.err == ""


def test_main_returns_error_when_orchestrator_mode_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    run_nc_committee_orchestrator = MagicMock(side_effect=RuntimeError("orchestrator exploded"))
    monkeypatch.setattr(cli, "run_nc_committee_orchestrator", run_nc_committee_orchestrator)

    exit_code = cli.main(build_orchestrate_args())
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "NC ingest failed: orchestrator exploded" in captured.err


@pytest.mark.parametrize(
    "kwargs",
    [
        {"download": True, "output_path": Path("/tmp/out.csv"), "date_from": "01/01/2024", "date_to": "01/31/2024"},
        {"committee_docs_path": SAMPLE_COMMITTEE_DOCS},
        {"committee_id": "C12345"},
        {"committee_name": "Example Committee"},
        {"date_from": "01/01/2024"},
        {"date_to": "01/31/2024"},
        {"trans_type": "exp"},
        {"output_path": Path("/tmp/out.csv")},
    ],
)
def test_run_nc_refresh_rejects_incompatible_ie_transaction_options(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
) -> None:
    get_connection = MagicMock()
    monkeypatch.setattr(cli, "get_connection", get_connection)

    with pytest.raises(ValueError, match="ie-transactions"):
        cli.run_nc_refresh(data_type="ie-transactions", **kwargs)

    get_connection.assert_not_called()
