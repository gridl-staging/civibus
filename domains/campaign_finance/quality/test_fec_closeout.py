"""Unit tests for federal FEC closeout orchestration CLI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.ingest.bulk_loader import LoadResult
from domains.campaign_finance.quality import fec_closeout
from domains.campaign_finance.quality.fec_closeout_models import (
    FecCloseoutEvidence,
    FecIngestMetadata,
)
from domains.campaign_finance.quality.models import CheckResult, JurisdictionSummary, QualityReport


def _evidence_with_status(status: str) -> FecCloseoutEvidence:
    return FecCloseoutEvidence(
        cycle=2024,
        jurisdiction="federal/fec",
        data_source_id=str(uuid4()),
        baseline_urls={},
        scoped_table_counts={},
        ingest_steps=[],
        ingest_metadata=FecIngestMetadata(record_count=0, last_pull_status="success", last_pull_at=None),
        quality_report=QualityReport(
            generated_at=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
            summaries=[
                JurisdictionSummary(jurisdiction="federal/fec", check_results=[CheckResult(name="x", status=status)])
            ],
        ),
    )


def _mock_run_fec_closeout_deps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    finalize_pull_status: str = "success",
    persisted_pull_status: str = "success",
) -> tuple[fec_closeout.FecCloseoutConfig, MagicMock]:
    """Shared setup for run_fec_closeout unit tests. Returns (config, connection)."""
    config = fec_closeout.FecCloseoutConfig(
        cycle=2024,
        directory=tmp_path,
        artifact_path=tmp_path / "closeout.json",
        batch_size=2,
        transaction_limit=None,
        graph_enabled=False,
    )
    connection = MagicMock()
    data_source_id = uuid4()
    load_summaries = [
        fec_closeout.bulk_cli.LoadStepSummary(
            file_type="cm",
            source_path=tmp_path / "cm_sample.txt",
            result=LoadResult(inserted=1, skipped=0, errors=0),
            elapsed_seconds=0.1,
        )
    ]

    monkeypatch.setattr(
        fec_closeout.bulk_cli,
        "resolve_full_cycle_directory",
        MagicMock(return_value={"cm": tmp_path / "cm_sample.txt"}),
    )
    monkeypatch.setattr(fec_closeout, "ensure_fec_bulk_data_source", MagicMock(return_value=data_source_id))
    monkeypatch.setattr(fec_closeout.bulk_cli, "load_full_cycle", MagicMock(return_value=load_summaries))
    monkeypatch.setattr(
        fec_closeout.bulk_cli,
        "finalize_full_cycle_metadata",
        MagicMock(
            return_value=fec_closeout.bulk_cli.FullCycleFinalizationOutcome(
                pull_status=finalize_pull_status, record_count=1
            )
        ),
    )
    monkeypatch.setattr(
        fec_closeout,
        "_fetch_data_source_metadata_snapshot",
        MagicMock(
            return_value=FecIngestMetadata(record_count=1, last_pull_status=persisted_pull_status, last_pull_at=None)
        ),
    )
    monkeypatch.setattr(
        fec_closeout,
        "_collect_scoped_table_counts",
        MagicMock(
            return_value={
                "cf.committee": 1,
                "cf.candidate": 0,
                "cf.candidate_committee_link": 0,
                "core.source_record_active": 1,
            }
        ),
    )
    monkeypatch.setattr(
        fec_closeout.quality_cli,
        "_discover_and_run",
        MagicMock(return_value=_evidence_with_status("pass").quality_report),
    )
    monkeypatch.setattr(
        fec_closeout.bulk_cli,
        "fec_baseline_urls",
        MagicMock(return_value={"cm": "https://www.fec.gov/files/bulk-downloads/2024/cm24.zip"}),
    )
    return config, connection


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [("pass", 0), ("warn", 0), ("fail", 1), ("error", 1)],
)
def test_main_preserves_quality_exit_code_semantics(
    status: str,
    expected_exit: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    monkeypatch.setattr(fec_closeout, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(fec_closeout, "run_fec_closeout", MagicMock(return_value=_evidence_with_status(status)))

    exit_code = fec_closeout.main(
        [
            "--cycle",
            "2024",
            "--directory",
            str(tmp_path),
            "--artifact-path",
            str(tmp_path / "closeout.json"),
        ]
    )

    assert exit_code == expected_exit
    connection.close.assert_called_once()


@pytest.mark.unit
def test_run_fec_closeout_never_calls_bulk_print_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, connection = _mock_run_fec_closeout_deps(tmp_path, monkeypatch)
    print_summary = MagicMock(side_effect=AssertionError("print_summary must not be used by closeout orchestration"))
    monkeypatch.setattr(fec_closeout.bulk_cli, "print_summary", print_summary)

    evidence = fec_closeout.run_fec_closeout(connection, config)

    assert evidence.cycle == 2024
    assert print_summary.call_count == 0


@pytest.mark.unit
def test_run_fec_closeout_uses_persisted_metadata_status_as_single_source_of_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, connection = _mock_run_fec_closeout_deps(
        tmp_path,
        monkeypatch,
        finalize_pull_status="partial",
        persisted_pull_status="success",
    )

    evidence = fec_closeout.run_fec_closeout(connection, config)

    assert evidence.ingest_metadata.last_pull_status == "success"


@pytest.mark.unit
def test_run_fec_closeout_surfaces_known_ingest_limitations_as_warn_anomalies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, connection = _mock_run_fec_closeout_deps(tmp_path, monkeypatch)

    evidence = fec_closeout.run_fec_closeout(connection, config)

    anomaly_names = {anomaly["name"] for anomaly in evidence.surfaced_anomalies()}
    assert anomaly_names == {"known_limitation_no_cf_transaction_population"}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("batch_size", "limit", "dir_exists", "error_substr"),
    [
        (0, None, True, "batch_size must be greater than zero"),
        (1000, 0, True, "limit must be greater than zero"),
        (1000, -1, True, "limit must be greater than zero"),
        (1000, None, False, "closeout requires a readable directory path"),
    ],
)
def test_build_cli_config_rejects_invalid_arguments(
    batch_size: int,
    limit: int | None,
    dir_exists: bool,
    error_substr: str,
    tmp_path: Path,
) -> None:
    import argparse

    directory = tmp_path if dir_exists else tmp_path / "nonexistent"
    args = argparse.Namespace(
        cycle=2024,
        directory=directory,
        artifact_path=None,
        batch_size=batch_size,
        limit=limit,
        graph=False,
    )
    with pytest.raises(ValueError, match=error_substr):
        fec_closeout._build_cli_config(args)


@pytest.mark.unit
def test_build_cli_config_rejects_unreadable_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import argparse

    args = argparse.Namespace(
        cycle=2024,
        directory=tmp_path,
        artifact_path=None,
        batch_size=1000,
        limit=None,
        graph=False,
    )
    monkeypatch.setattr(fec_closeout.os, "access", MagicMock(return_value=False))

    with pytest.raises(ValueError, match="readable directory"):
        fec_closeout._build_cli_config(args)


@pytest.mark.unit
def test_main_returns_two_on_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    exit_code = fec_closeout.main(["--cycle", "2024", "--directory", "/nonexistent/path", "--batch-size", "0"])
    assert exit_code == 2
    assert "batch_size" in capsys.readouterr().err


@pytest.mark.unit
def test_count_rows_for_scoped_table_rejects_unlisted_table_name() -> None:
    conn = MagicMock()
    with pytest.raises(ValueError, match="not in scoped-table allowlist"):
        fec_closeout._count_rows_for_scoped_table(conn, uuid4(), "evil; DROP TABLE")


@pytest.mark.unit
def test_default_artifact_path_includes_cycle_and_filename() -> None:
    path = fec_closeout._default_artifact_path(2024)
    assert "2024" in str(path)
    assert path.name == "closeout_evidence.json"


@pytest.mark.unit
def test_fetch_data_source_metadata_snapshot_raises_when_data_source_missing() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None

    with pytest.raises(RuntimeError, match="data_source not found"):
        fec_closeout._fetch_data_source_metadata_snapshot(connection, uuid4())


@pytest.mark.unit
def test_fetch_data_source_metadata_snapshot_maps_row_fields() -> None:
    connection = MagicMock()
    data_source_id = uuid4()
    pull_time = datetime(2026, 3, 16, 14, 0, tzinfo=timezone.utc)
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (123, "partial", pull_time)

    metadata = fec_closeout._fetch_data_source_metadata_snapshot(connection, data_source_id)

    assert metadata.record_count == 123
    assert metadata.last_pull_status == "partial"
    assert metadata.last_pull_at == pull_time
    cursor.execute.assert_called_once_with(
        "SELECT record_count, last_pull_status, last_pull_at FROM core.data_source WHERE id = %s",
        (data_source_id,),
    )


@pytest.mark.unit
def test_build_ingest_config_maps_closeout_options(tmp_path: Path) -> None:
    config = fec_closeout.FecCloseoutConfig(
        cycle=2024,
        directory=tmp_path,
        artifact_path=tmp_path / "closeout.json",
        batch_size=500,
        transaction_limit=2500,
        graph_enabled=True,
    )

    ingest_config = fec_closeout._build_ingest_config(config)

    assert ingest_config.mode == "full"
    assert ingest_config.cycle == 2024
    assert ingest_config.directory == tmp_path
    assert ingest_config.batch_size == 500
    assert ingest_config.limit == 2500
    assert ingest_config.graph_enabled is True


@pytest.mark.unit
def test_run_fec_closeout_rejects_missing_persisted_pull_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, connection = _mock_run_fec_closeout_deps(tmp_path, monkeypatch, persisted_pull_status="")

    with pytest.raises(RuntimeError, match="last_pull_status"):
        fec_closeout.run_fec_closeout(connection, config)


@pytest.mark.unit
def test_main_returns_one_when_closeout_run_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    connection = MagicMock()
    monkeypatch.setattr(fec_closeout, "get_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(fec_closeout, "run_fec_closeout", MagicMock(side_effect=RuntimeError("boom")))

    exit_code = fec_closeout.main(["--cycle", "2024", "--directory", str(tmp_path)])

    assert exit_code == 1
    assert "FEC closeout failed: boom" in capsys.readouterr().err
    connection.close.assert_called_once()


@pytest.mark.unit
def test_write_evidence_artifact_creates_parent_and_terminates_with_newline(tmp_path: Path) -> None:
    evidence = _evidence_with_status("pass")
    artifact_path = tmp_path / "nested" / "closeout_evidence.json"

    fec_closeout.write_evidence_artifact(evidence, artifact_path)

    assert artifact_path.exists()
    written = artifact_path.read_text(encoding="utf-8")
    assert written.endswith("\n")
    assert written == f"{evidence.to_json()}\n"


@pytest.mark.unit
def test_known_ingest_limitation_anomalies_are_deep_copied() -> None:
    first = fec_closeout._known_ingest_limitation_anomalies()
    first[0]["details"]["category"] = "mutated"

    second = fec_closeout._known_ingest_limitation_anomalies()

    assert second[0]["details"]["category"] == "accepted-limitation"
