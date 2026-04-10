"""RED tests for FecClient — FEC Schedule A API client."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

# These imports will fail until GREEN implementation exists.
from domains.campaign_finance.ingest.fec_client import FecApiError, FecClient

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "fec_sample_response.json"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Construction: API key resolution
# ---------------------------------------------------------------------------


class TestFecClientConstruction:
    def test_uses_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("FEC_API_KEY", "my-env-key")
        client = FecClient()
        assert client._api_key == "my-env-key"

    def test_falls_back_to_demo_key(self, monkeypatch):
        monkeypatch.delenv("FEC_API_KEY", raising=False)
        client = FecClient()
        assert client._api_key == "DEMO_KEY"

    def test_caller_supplied_key_overrides(self, monkeypatch):
        monkeypatch.setenv("FEC_API_KEY", "my-env-key")
        client = FecClient(api_key="explicit-key")
        assert client._api_key == "explicit-key"


# ---------------------------------------------------------------------------
# Single-page fetch
# ---------------------------------------------------------------------------


def _make_ok_response(data: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


_EMPTY_PAGE = {"api_version": "1.0", "pagination": {"last_indexes": None, "per_page": 10}, "results": []}


class TestFetchContributionsSinglePage:
    def test_returns_results_list(self):
        fixture = _load_fixture()
        responses = [_make_ok_response(fixture), _make_ok_response(_EMPTY_PAGE)]

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.side_effect = responses

            client = FecClient(api_key="test-key")
            results = client.fetch_contributions(state="NC", cycle=2024)

        assert len(results) == 10
        assert results == fixture["results"]

    def test_request_url_and_params(self):
        fixture = _load_fixture()
        responses = [_make_ok_response(fixture), _make_ok_response(_EMPTY_PAGE)]

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.side_effect = responses

            client = FecClient(api_key="test-key")
            client.fetch_contributions(state="NC", cycle=2024, per_page=10)

        # Check the first request's URL and params
        call_args = mock_client_instance.get.call_args_list[0]
        url = call_args[0][0] if call_args[0] else call_args[1].get("url")
        params = call_args[1].get("params", call_args[0][1] if len(call_args[0]) > 1 else {})

        assert "api.open.fec.gov" in url
        assert "/v1/schedules/schedule_a/" in url
        assert params["api_key"] == "test-key"
        assert params["per_page"] == 10
        assert params["sort_null_only"] == "false"
        assert params["sort"] == "-contribution_receipt_date"
        assert params["contributor_state"] == "NC"
        assert params["two_year_transaction_period"] == 2024


# ---------------------------------------------------------------------------
# Cursor-based pagination
# ---------------------------------------------------------------------------


class TestCursorPagination:
    def test_follows_cursor_across_pages(self):
        page1_data = {
            "api_version": "1.0",
            "pagination": {
                "last_indexes": {
                    "last_index": "123456",
                    "last_contribution_receipt_date": "2024-06-15",
                },
                "per_page": 2,
            },
            "results": [{"id": "a"}, {"id": "b"}],
        }
        page2_data = {
            "api_version": "1.0",
            "pagination": {
                "last_indexes": {
                    "last_index": "789012",
                    "last_contribution_receipt_date": "2024-06-14",
                },
                "per_page": 2,
            },
            "results": [],
        }

        responses = []
        for data in [page1_data, page2_data]:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = data
            resp.raise_for_status = MagicMock()
            responses.append(resp)

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.side_effect = responses

            client = FecClient(api_key="test-key")
            results = client.fetch_contributions()

        assert results == [{"id": "a"}, {"id": "b"}]
        assert mock_client_instance.get.call_count == 2

        # Second call should include cursor params
        second_call_params = mock_client_instance.get.call_args_list[1][1]["params"]
        assert second_call_params["last_index"] == "123456"
        assert second_call_params["last_contribution_receipt_date"] == "2024-06-15"

    def test_limit_truncates_results(self):
        page_data = {
            "api_version": "1.0",
            "pagination": {
                "last_indexes": {
                    "last_index": "999",
                    "last_contribution_receipt_date": "2024-01-01",
                },
                "per_page": 10,
            },
            "results": [{"id": i} for i in range(10)],
        }
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = page_data
        resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = resp

            client = FecClient(api_key="test-key")
            results = client.fetch_contributions(limit=5)

        assert len(results) == 5


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------


class TestHttpErrorHandling:
    def _make_error_response(self, status_code):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.text = f"Error {status_code}"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"{status_code}", request=MagicMock(), response=resp
        )
        return resp

    def test_429_raises_rate_limit_error(self):
        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = self._make_error_response(429)

            client = FecClient(api_key="test-key")
            with pytest.raises(FecApiError, match="(?i)rate.limit"):
                client.fetch_contributions()

    def test_403_raises_api_key_error(self):
        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = self._make_error_response(403)

            client = FecClient(api_key="bad-key")
            with pytest.raises(FecApiError, match="(?i)(api.key|invalid|forbidden)"):
                client.fetch_contributions()

    def test_500_raises_with_status_code(self):
        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = self._make_error_response(500)

            client = FecClient(api_key="test-key")
            with pytest.raises(FecApiError, match="500"):
                client.fetch_contributions()

    def test_transport_error_is_wrapped_as_fec_api_error(self):
        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.side_effect = httpx.ReadTimeout("timed out", request=MagicMock())

            client = FecClient(api_key="test-key")
            with pytest.raises(FecApiError, match="(?i)request failed"):
                client.fetch_contributions()

    def test_invalid_json_response_is_wrapped_as_fec_api_error(self):
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.side_effect = json.JSONDecodeError("Expecting value", "not-json", 0)

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MockClient.return_value.__enter__.return_value
            mock_client_instance.get.return_value = response

            client = FecClient(api_key="test-key")
            with pytest.raises(FecApiError, match="invalid JSON"):
                client.fetch_contributions()
