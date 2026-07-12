from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.ingest import bulk_cli
from domains.campaign_finance.ingest.bulk_loader import LoadResult


class TestFecBaselineUrl:
    """Tests for per-file FEC bulk download URL derivation."""

    @pytest.mark.unit
    def test_derives_correct_urls_for_cycle_2024(self) -> None:
        expected = {
            "cm": "https://www.fec.gov/files/bulk-downloads/2024/cm24.zip",
            "cn": "https://www.fec.gov/files/bulk-downloads/2024/cn24.zip",
            "ccl": "https://www.fec.gov/files/bulk-downloads/2024/ccl24.zip",
            "itcont": "https://www.fec.gov/files/bulk-downloads/2024/indiv24.zip",
            "itpas2": "https://www.fec.gov/files/bulk-downloads/2024/pas224.zip",
        }
        for file_type, expected_url in expected.items():
            assert bulk_cli.fec_baseline_url(2024, file_type) == expected_url

    @pytest.mark.unit
    def test_derives_correct_urls_for_cycle_2020(self) -> None:
        assert bulk_cli.fec_baseline_url(2020, "cm") == "https://www.fec.gov/files/bulk-downloads/2020/cm20.zip"
        assert bulk_cli.fec_baseline_url(2020, "itcont") == "https://www.fec.gov/files/bulk-downloads/2020/indiv20.zip"

    @pytest.mark.unit
    def test_rejects_unknown_file_type(self) -> None:
        with pytest.raises(ValueError, match="Unknown FEC file type"):
            bulk_cli.fec_baseline_url(2024, "unknown")

    @pytest.mark.unit
    def test_baseline_urls_returns_complete_mapping(self) -> None:
        urls = bulk_cli.fec_baseline_urls(2024)
        assert set(urls.keys()) == set(bulk_cli.FULL_CYCLE_FILE_ORDER)
        assert all(url.startswith("https://www.fec.gov/files/bulk-downloads/2024/") for url in urls.values())


@pytest.mark.unit
def test_committee_summary_url_is_separate_from_baseline_bulk_urls() -> None:
    assert (
        bulk_cli.fec_committee_summary_url(2024)
        == "https://www.fec.gov/files/bulk-downloads/2024/committee_summary_2024.csv"
    )
    assert "committee_summary" not in bulk_cli.fec_baseline_urls(2024)


class TestEffectiveLimitForDispatch:
    """Tests for selective limit: cm/cn/ccl unlimited, itcont/itpas2 capped in full-cycle mode."""

    def _build_config(self, *, mode: str, limit: int | None) -> bulk_cli.CliConfig:
        return bulk_cli.CliConfig(
            mode=mode,
            cycle=2024,
            file_type=None if mode == "full" else "cm",
            path=None,
            directory=None,
            batch_size=1000,
            limit=limit,
            graph_enabled=False,
        )

    @pytest.mark.unit
    def test_full_mode_leaves_reference_files_unlimited(self) -> None:
        config = self._build_config(mode="full", limit=50000)
        for file_type in ("cm", "cn", "ccl"):
            assert bulk_cli.effective_limit_for_dispatch(file_type, config) is None

    @pytest.mark.unit
    def test_full_mode_applies_limit_to_transaction_files(self) -> None:
        config = self._build_config(mode="full", limit=50000)
        for file_type in ("itcont", "itpas2"):
            assert bulk_cli.effective_limit_for_dispatch(file_type, config) == 50000

    @pytest.mark.unit
    def test_single_mode_applies_limit_to_all_file_types(self) -> None:
        config = self._build_config(mode="single", limit=100)
        for file_type in bulk_cli.FULL_CYCLE_FILE_ORDER:
            assert bulk_cli.effective_limit_for_dispatch(file_type, config) == 100

    @pytest.mark.unit
    def test_returns_none_when_no_limit_configured(self) -> None:
        config = self._build_config(mode="full", limit=None)
        for file_type in bulk_cli.FULL_CYCLE_FILE_ORDER:
            assert bulk_cli.effective_limit_for_dispatch(file_type, config) is None


class TestDerivePullStatus:
    """Tests for derive_pull_status helper."""

    def _summary(self, inserted: int, errors: int, *, skipped: int = 0) -> bulk_cli.LoadStepSummary:
        return bulk_cli.LoadStepSummary(
            file_type="cm",
            source_path=Path("/tmp/cm.txt"),
            result=LoadResult(inserted=inserted, skipped=skipped, errors=errors),
            elapsed_seconds=0.1,
        )

    @pytest.mark.unit
    def test_success_when_no_errors(self) -> None:
        summaries = [self._summary(10, 0), self._summary(5, 0)]
        assert bulk_cli.derive_pull_status(summaries) == "success"

    @pytest.mark.unit
    def test_partial_when_errors_and_inserts(self) -> None:
        summaries = [self._summary(10, 0), self._summary(3, 2)]
        assert bulk_cli.derive_pull_status(summaries) == "partial"

    @pytest.mark.unit
    def test_partial_when_errors_and_only_skips(self) -> None:
        summaries = [self._summary(0, 0, skipped=4), self._summary(0, 2, skipped=3)]
        assert bulk_cli.derive_pull_status(summaries) == "partial"

    @pytest.mark.unit
    def test_failed_when_only_errors(self) -> None:
        summaries = [self._summary(0, 5), self._summary(0, 3)]
        assert bulk_cli.derive_pull_status(summaries) == "failed"


@pytest.mark.unit
def test_finalize_full_cycle_metadata_derives_pull_status_and_syncs_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = object()
    data_source_id = uuid4()
    summaries = [
        bulk_cli.LoadStepSummary(
            file_type="cm",
            source_path=Path("/tmp/cm.txt"),
            result=LoadResult(inserted=1, skipped=0, errors=0),
            elapsed_seconds=0.1,
        )
    ]
    derive_pull_status = MagicMock(return_value="success")
    sync_data_source_metadata = MagicMock(return_value=12)

    monkeypatch.setattr(bulk_cli, "derive_pull_status", derive_pull_status)
    monkeypatch.setattr(bulk_cli, "sync_data_source_metadata", sync_data_source_metadata)

    outcome = bulk_cli.finalize_full_cycle_metadata(connection, data_source_id, summaries)

    derive_pull_status.assert_called_once_with(summaries)
    sync_data_source_metadata.assert_called_once_with(connection, data_source_id, pull_status="success")
    assert outcome.pull_status == "success"
    assert outcome.record_count == 12
