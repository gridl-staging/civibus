from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.MN.scraper.download import (
    build_mn_download_url,
    download_mn_csv,
)

_MN_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
_MN_CANONICAL_URL_BY_DATA_TYPE = {
    "contributions": (
        "https://register.cfb.mn.gov/reports-and-data/self-help/data-downloads/campaign-finance/?download=-2113865252"
    ),
    "expenditures": (
        "https://register.cfb.mn.gov/reports-and-data/self-help/data-downloads/campaign-finance/?download=-1890073264"
    ),
    "independent_expenditures": (
        "https://register.cfb.mn.gov/reports-and-data/self-help/data-downloads/campaign-finance/?download=-617535497"
    ),
}
_MN_EXPECTED_LAST_VERIFIED_WORKING = date(2026, 3, 21)


def _load_mn_config():
    return load_jurisdiction_config(_MN_CONFIG_PATH)


def _source_data_type(source) -> str:
    transaction_types = tuple(source.coverage.transaction_types)
    assert len(transaction_types) == 1, "MN direct-download contract expects one transaction type per data source"
    return transaction_types[0]


@contextmanager
def _configure_streaming_client(mock_response: MagicMock):
    mock_client_type = patch("httpx.Client")
    with mock_client_type as mock_client_class:
        mock_client = mock_client_class.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = mock_response
        yield


class TestMNDirectDownloadContract2026:
    """Lock MN CFB download IDs and config verification for 2026 cycle."""

    def test_config_verified_for_2026_cycle(self) -> None:
        """All MN data sources must show a 2026-cycle verification date."""
        for source in _load_mn_config().data_sources:
            assert source.last_verified_working is not None, f"{source.name} has no last_verified_working date"
            assert source.last_verified_working >= _MN_EXPECTED_LAST_VERIFIED_WORKING, (
                f"{source.name} last_verified_working={source.last_verified_working} "
                f"is before {_MN_EXPECTED_LAST_VERIFIED_WORKING}"
            )

    def test_config_sources_preserve_quarterly_direct_download_contract(self) -> None:
        config = _load_mn_config()
        assert len(config.data_sources) == len(_MN_CANONICAL_URL_BY_DATA_TYPE), (
            "MN quarterly direct-download contract should expose exactly one source per canonical data type"
        )

        resolved_data_types = set()
        for source in config.data_sources:
            data_type = _source_data_type(source)
            assert data_type not in resolved_data_types, (
                f"MN quarterly direct-download contract should not duplicate data type {data_type!r}"
            )
            resolved_data_types.add(data_type)
            assert source.auth_required is False
            assert source.api_base_url is None
            assert source.update_frequency == "quarterly"
            assert source.last_verified_working == _MN_EXPECTED_LAST_VERIFIED_WORKING
            assert source.bulk_download_url == _MN_CANONICAL_URL_BY_DATA_TYPE[data_type]
            assert build_mn_download_url(data_type) == source.bulk_download_url
            assert any(
                "/reports/#/" in issue and "/reports/api/" in issue and "supplemental" in issue.lower()
                for issue in source.known_issues
            ), f"{source.name} should document /reports/#/ and /reports/api/ as supplemental-only evidence surfaces"

        assert resolved_data_types == set(_MN_CANONICAL_URL_BY_DATA_TYPE)


@pytest.mark.parametrize(
    ("data_type", "expected_url"),
    tuple(_MN_CANONICAL_URL_BY_DATA_TYPE.items()),
)
def test_build_mn_download_url_uses_configured_bulk_urls(data_type: str, expected_url: str) -> None:
    assert build_mn_download_url(data_type) == expected_url


def test_build_mn_download_url_raises_for_unsupported_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported MN data type"):
        build_mn_download_url("loans")


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


def test_download_mn_csv_streams_to_dest_dir_and_returns_path(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    mock_response = _make_streaming_response([b"Recipient reg num,Recipient\n", b"1,Committee\n"])

    with _configure_streaming_client(mock_response):
        saved_path = download_mn_csv(data_type="contributions", dest_dir=destination_dir)

    assert saved_path == destination_dir / "mn_contributions.csv"
    assert saved_path.read_text(encoding="utf-8") == "Recipient reg num,Recipient\n1,Committee\n"


def test_download_mn_csv_removes_partial_file_when_stream_fails(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    read_error = httpx.ReadError("stream interrupted", request=MagicMock())
    mock_response = _make_failing_streaming_response([b"Recipient reg num,Recipient\n"], error=read_error)

    with _configure_streaming_client(mock_response):
        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            download_mn_csv(data_type="contributions", dest_dir=destination_dir)

    assert list(destination_dir.iterdir()) == []
