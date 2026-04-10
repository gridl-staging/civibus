from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.CO.scraper.download import (
    build_tracer_url,
    download_tracer_file,
    extract_csv_from_zip,
)

_CO_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class TestCODirectDownloadContract2026:
    """Lock CO TRACER URL templates and config verification for 2026 cycle.

    Regression guards: if CO TRACER changes its bulk download URL pattern or
    the config verification dates drift, these tests catch it.
    """

    def test_tracer_url_generates_2026_contribution_url(self) -> None:
        url = build_tracer_url(year=2026, data_type="Contribution")
        assert url == (
            "https://tracer.sos.colorado.gov/PublicSite/Docs/BulkDataDownloads/2026_ContributionData.csv.zip"
        )

    def test_tracer_url_generates_2026_expenditure_url(self) -> None:
        url = build_tracer_url(year=2026, data_type="Expenditure")
        assert url == ("https://tracer.sos.colorado.gov/PublicSite/Docs/BulkDataDownloads/2026_ExpenditureData.csv.zip")

    def test_tracer_url_generates_2026_loan_url(self) -> None:
        url = build_tracer_url(year=2026, data_type="Loan")
        assert url == ("https://tracer.sos.colorado.gov/PublicSite/Docs/BulkDataDownloads/2026_LoanData.csv.zip")

    def test_config_verified_for_2026_cycle(self) -> None:
        """All CO data sources must show a 2026-cycle verification date."""
        cycle_cutoff = date(2026, 3, 21)
        config = load_jurisdiction_config(_CO_CONFIG_PATH)
        for source in config.data_sources:
            assert source.last_verified_working is not None, f"{source.name} has no last_verified_working date"
            assert source.last_verified_working >= cycle_cutoff, (
                f"{source.name} last_verified_working={source.last_verified_working} is before {cycle_cutoff}"
            )


@pytest.mark.parametrize(
    ("year", "data_type", "expected_url"),
    [
        (
            2024,
            "Contribution",
            "https://tracer.sos.colorado.gov/PublicSite/Docs/BulkDataDownloads/2024_ContributionData.csv.zip",
        ),
        (
            2025,
            "Expenditure",
            "https://tracer.sos.colorado.gov/PublicSite/Docs/BulkDataDownloads/2025_ExpenditureData.csv.zip",
        ),
        (
            2024,
            "Loan",
            "https://tracer.sos.colorado.gov/PublicSite/Docs/BulkDataDownloads/2024_LoanData.csv.zip",
        ),
    ],
)
def test_build_tracer_url_returns_config_template_urls(year: int, data_type: str, expected_url: str):
    assert build_tracer_url(year=year, data_type=data_type) == expected_url


def test_build_tracer_url_accepts_plural_config_data_type_name():
    assert build_tracer_url(year=2024, data_type="Contributions").endswith("/2024_ContributionData.csv.zip")


def test_build_tracer_url_raises_for_unsupported_data_type():
    with pytest.raises(ValueError, match="Unsupported TRACER data type"):
        build_tracer_url(year=2024, data_type="Unknown")


def test_build_tracer_url_raises_for_partial_data_type_match():
    with pytest.raises(ValueError, match="Unsupported TRACER data type"):
        build_tracer_url(year=2024, data_type="Contrib")


def _make_streaming_response(chunks: list[bytes]) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = chunks
    return response


def _make_failing_streaming_response(chunks: list[bytes], error: httpx.HTTPError) -> MagicMock:
    def iter_bytes():
        yield from chunks
        raise error

    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.iter_bytes.return_value = iter_bytes()
    return response


def test_download_tracer_file_streams_to_dest_dir_and_returns_path(tmp_path: Path):
    destination_dir = tmp_path / "downloads"
    mock_response = _make_streaming_response([b"PK", b"\x03\x04"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        saved_path = download_tracer_file(year=2024, data_type="Contribution", dest_dir=destination_dir)

    assert saved_path == destination_dir / "2024_ContributionData.csv.zip"
    assert saved_path.read_bytes() == b"PK\x03\x04"
    assert saved_path.exists()


def test_download_tracer_file_removes_partial_file_when_stream_fails(tmp_path: Path):
    destination_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("stream interrupted", request=MagicMock())
    mock_response = _make_failing_streaming_response([b"PK"], error=read_error)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            download_tracer_file(year=2024, data_type="Contribution", dest_dir=destination_dir)

    assert list(destination_dir.iterdir()) == []


def test_download_tracer_file_avoids_preexisting_part_symlink_clobber(tmp_path: Path):
    destination_dir = tmp_path / "downloads"
    destination_dir.mkdir(parents=True, exist_ok=True)
    expected_destination_path = destination_dir / "2024_ContributionData.csv.zip"
    expected_part_path = expected_destination_path.with_name(f"{expected_destination_path.name}.part")
    victim_path = tmp_path / "victim.txt"
    victim_path.write_bytes(b"do-not-overwrite")
    expected_part_path.symlink_to(victim_path)

    mock_response = _make_streaming_response([b"PK", b"\x03\x04"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response

        saved_path = download_tracer_file(year=2024, data_type="Contribution", dest_dir=destination_dir)

    assert saved_path == expected_destination_path
    assert saved_path.read_bytes() == b"PK\x03\x04"
    assert victim_path.read_bytes() == b"do-not-overwrite"


def test_download_tracer_file_retries_with_verify_false_for_ssl_cert_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    destination_dir = tmp_path / "downloads"
    ssl_error = httpx.ConnectError("CERTIFICATE_VERIFY_FAILED", request=MagicMock())
    monkeypatch.setenv("CIVIBUS_ALLOW_INSECURE_TLS_RETRY", "1")

    first_client = MagicMock()
    first_client.stream.side_effect = ssl_error
    first_context_manager = MagicMock()
    first_context_manager.__enter__.return_value = first_client
    first_context_manager.__exit__.return_value = False

    second_client = MagicMock()
    second_response = _make_streaming_response([b"PK\x03\x04"])
    second_client.stream.return_value.__enter__.return_value = second_response
    second_context_manager = MagicMock()
    second_context_manager.__enter__.return_value = second_client
    second_context_manager.__exit__.return_value = False

    with patch("httpx.Client", side_effect=[first_context_manager, second_context_manager]) as mock_client_type:
        with pytest.warns(UserWarning, match="SSL"):
            saved_path = download_tracer_file(
                year=2024,
                data_type="Contribution",
                dest_dir=destination_dir,
                allow_insecure_tls=True,
            )

    assert saved_path == destination_dir / "2024_ContributionData.csv.zip"
    assert saved_path.exists()
    assert mock_client_type.call_count == 2
    assert mock_client_type.call_args_list[1].kwargs["verify"] is False


def test_download_tracer_file_rejects_insecure_retry_without_break_glass_env(tmp_path: Path):
    destination_dir = tmp_path / "downloads"
    ssl_error = httpx.ConnectError("CERTIFICATE_VERIFY_FAILED", request=MagicMock())

    first_client = MagicMock()
    first_client.stream.side_effect = ssl_error
    first_context_manager = MagicMock()
    first_context_manager.__enter__.return_value = first_client
    first_context_manager.__exit__.return_value = False

    with patch("httpx.Client", return_value=first_context_manager) as mock_client_type:
        with pytest.raises(RuntimeError, match="break-glass override is disabled"):
            download_tracer_file(
                year=2024,
                data_type="Contribution",
                dest_dir=destination_dir,
                allow_insecure_tls=True,
            )

    assert mock_client_type.call_count == 1


def test_download_tracer_file_does_not_retry_ssl_errors_without_opt_in(tmp_path: Path):
    destination_dir = tmp_path / "downloads"
    ssl_error = httpx.ConnectError("CERTIFICATE_VERIFY_FAILED", request=MagicMock())

    first_client = MagicMock()
    first_client.stream.side_effect = ssl_error
    first_context_manager = MagicMock()
    first_context_manager.__enter__.return_value = first_client
    first_context_manager.__exit__.return_value = False

    with patch("httpx.Client", return_value=first_context_manager) as mock_client_type:
        with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
            download_tracer_file(year=2024, data_type="Contribution", dest_dir=destination_dir)

    assert mock_client_type.call_count == 1


def test_download_tracer_file_does_not_retry_non_ssl_transport_errors(tmp_path: Path):
    destination_dir = tmp_path / "downloads"
    transport_error = httpx.ConnectError("Connection reset", request=MagicMock())

    first_client = MagicMock()
    first_client.stream.side_effect = transport_error
    first_context_manager = MagicMock()
    first_context_manager.__enter__.return_value = first_client
    first_context_manager.__exit__.return_value = False

    with patch("httpx.Client", return_value=first_context_manager) as mock_client_type:
        with pytest.raises(httpx.ConnectError, match="Connection reset"):
            download_tracer_file(year=2024, data_type="Contribution", dest_dir=destination_dir)

    assert mock_client_type.call_count == 1


@pytest.mark.integration
def test_download_tracer_file_integration_downloads_real_zip(tmp_path: Path):
    try:
        zip_path = download_tracer_file(year=2024, data_type="Contribution", dest_dir=tmp_path)
    except httpx.HTTPError as exc:
        pytest.skip(f"TRACER unavailable during integration test: {exc}")

    assert zip_path.exists()
    assert zipfile.is_zipfile(zip_path)


def _write_zip_file(zip_path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(zip_path, mode="w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def test_extract_csv_from_zip_extracts_single_csv_to_default_directory(tmp_path: Path):
    zip_path = tmp_path / "input.zip"
    _write_zip_file(zip_path, {"records.csv": b"a,b\n1,2\n"})

    extracted_csv = extract_csv_from_zip(zip_path)

    assert extracted_csv == tmp_path / "records.csv"
    assert extracted_csv.exists()
    assert extracted_csv.read_text() == "a,b\n1,2\n"


def test_extract_csv_from_zip_extracts_single_csv_to_custom_directory(tmp_path: Path):
    zip_path = tmp_path / "input.zip"
    destination_dir = tmp_path / "extracted"
    _write_zip_file(zip_path, {"records.csv": b"a,b\n1,2\n"})

    extracted_csv = extract_csv_from_zip(zip_path, dest_dir=destination_dir)

    assert extracted_csv == destination_dir / "records.csv"
    assert extracted_csv.exists()


def test_extract_csv_from_zip_raises_when_no_csv_exists(tmp_path: Path):
    zip_path = tmp_path / "input.zip"
    _write_zip_file(zip_path, {"readme.txt": b"no csv"})

    with pytest.raises(ValueError, match="exactly one CSV"):
        extract_csv_from_zip(zip_path)


def test_extract_csv_from_zip_raises_when_multiple_csv_exist(tmp_path: Path):
    zip_path = tmp_path / "input.zip"
    _write_zip_file(zip_path, {"a.csv": b"id\n1\n", "b.csv": b"id\n2\n"})

    with pytest.raises(ValueError, match="exactly one CSV"):
        extract_csv_from_zip(zip_path)


def test_extract_csv_from_zip_rejects_path_traversal_member(tmp_path: Path):
    zip_path = tmp_path / "input.zip"
    _write_zip_file(zip_path, {"../records.csv": b"a,b\n1,2\n"})

    with pytest.raises(ValueError, match="unsafe CSV path"):
        extract_csv_from_zip(zip_path, dest_dir=tmp_path / "extracted")
