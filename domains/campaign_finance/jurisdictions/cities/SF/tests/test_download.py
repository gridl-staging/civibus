from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from domains.campaign_finance.jurisdictions.cities.SF.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_columns_for_data_type,
    _load_data_source_for_data_type,
    _load_sf_config,
)
from domains.campaign_finance.jurisdictions.cities.SF.scraper import download as sf_download
from domains.campaign_finance.jurisdictions.cities.SF.scraper.download import (
    SODA_ORDER_BY,
    SODA_PAGE_SIZE,
    build_sf_download_url,
    download_sf_csv,
)


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


def test_load_sf_config_and_transactions_source_from_yaml() -> None:
    config = _load_sf_config()
    data_source = _load_data_source_for_data_type("  TRANSACTIONS  ")

    assert config.jurisdiction.code == "SF"
    assert data_source.name == "SF Ethics Campaign Finance Transactions"


def test_load_columns_for_transactions_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("transactions")

    assert len(columns) >= 56
    assert columns[0] == "filing_id_number"
    assert columns[-1] == "loan_amount_8"


def test_load_bulk_download_url_for_transactions_uses_config() -> None:
    assert _load_bulk_download_url_for_data_type("transactions") == "https://data.sfgov.org/resource/pitq-e56w.csv"


def test_build_sf_download_url_uses_transactions_dataset_with_pagination() -> None:
    url = build_sf_download_url("transactions", limit=500, offset=1000)

    assert "pitq-e56w.csv" in url
    assert f"$order={SODA_ORDER_BY}" in url
    assert "$limit=500" in url
    assert "$offset=1000" in url


def test_soda_page_size_contract_is_locked() -> None:
    assert SODA_PAGE_SIZE == 50_000


def test_build_sf_download_url_rejects_unsupported_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported SF data type"):
        build_sf_download_url("pledges")


def test_download_sf_csv_merges_pages_header_once_and_names_destination(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    page_one = _make_streaming_response([b"id,amount\n1,100.00\n2,250.00\n"])
    page_two = _make_streaming_response([b"id,amount\n3,500.00\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=page_one), __exit__=MagicMock(return_value=False)),
            MagicMock(__enter__=MagicMock(return_value=page_two), __exit__=MagicMock(return_value=False)),
        ]
        with patch.object(sf_download, "SODA_PAGE_SIZE", 2):
            output_path = download_sf_csv("transactions", destination_dir)

    assert output_path == destination_dir / "sf_transactions.csv"
    assert output_path.read_text(encoding="utf-8") == "id,amount\n1,100.00\n2,250.00\n3,500.00\n"


def test_download_sf_csv_removes_partial_file_when_stream_raises(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    interrupted = httpx.ReadError("stream interrupted", request=MagicMock())
    failing_response = _make_failing_streaming_response([b"id,amount\n1,100.00\n"], interrupted)

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.return_value.__enter__.return_value = failing_response

        with pytest.raises(httpx.ReadError, match="stream interrupted"):
            download_sf_csv("transactions", destination_dir)

    assert list(destination_dir.iterdir()) == []


def test_download_sf_csv_paginates_by_csv_rows_with_quoted_newlines(tmp_path: Path) -> None:
    destination_dir = tmp_path / "downloads"
    page_one = _make_streaming_response(
        [b'id,description,amount\n1,"Line one\nLine two",100.00\n2,Simple row,200.00\n']
    )
    page_two = _make_streaming_response([b"id,description,amount\n3,Final row,300.00\n"])

    with patch("httpx.Client") as mock_client_type:
        mock_client = mock_client_type.return_value.__enter__.return_value
        mock_client.stream.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=page_one), __exit__=MagicMock(return_value=False)),
            MagicMock(__enter__=MagicMock(return_value=page_two), __exit__=MagicMock(return_value=False)),
        ]

        with patch.object(sf_download, "SODA_PAGE_SIZE", 2):
            output_path = download_sf_csv("transactions", destination_dir)

    stream_calls = mock_client.stream.call_args_list
    assert len(stream_calls) == 2
    assert "$offset=0" in stream_calls[0].args[1]
    assert "$offset=2" in stream_calls[1].args[1]
    assert output_path.read_text(encoding="utf-8") == (
        'id,description,amount\n1,"Line one\nLine two",100.00\n2,Simple row,200.00\n3,Final row,300.00\n'
    )


def test_build_sf_download_url_uses_compound_order_for_stable_offset_pagination() -> None:
    assert build_sf_download_url("transactions") == (
        "https://data.sfgov.org/resource/pitq-e56w.csv?$order=filing_id_number,transaction_id&$limit=50000&$offset=0"
    )
