"""
Stub summary for MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/ingest/fec_client.py.
"""

import os

import httpx

FEC_BASE_URL = "https://api.open.fec.gov/v1/schedules/schedule_a/"
FEC_ELECTION_DATES_URL = "https://api.open.fec.gov/v1/election-dates/"
FEC_REQUEST_TIMEOUT_SECONDS = 10.0


class FecApiError(Exception):
    """Raised on non-2xx responses from the OpenFEC API."""


class FecClient:
    """Synchronous client for fetching FEC Schedule A individual contributions."""

    def __init__(self, api_key: str | None = None):
        if api_key is not None:
            self._api_key = api_key
        else:
            self._api_key = os.environ.get("FEC_API_KEY")
            if not self._api_key:
                raise ValueError("FEC_API_KEY environment variable is required")

    def fetch_contributions(
        self,
        *,
        state: str | None = None,
        cycle: int | None = None,
        per_page: int = 20,
        limit: int | None = None,
    ) -> list[dict]:
        """Fetch Schedule A contributions, following cursor-based pagination.

        Returns the concatenated results list. Raises FecApiError on non-2xx.
        """
        all_results: list[dict] = []
        cursor_params: dict[str, str] = {}

        with httpx.Client(timeout=FEC_REQUEST_TIMEOUT_SECONDS) as http:
            while True:
                params: dict[str, str | int] = {
                    "api_key": self._api_key,
                    "per_page": per_page,
                    "sort_null_only": "false",
                    "sort": "-contribution_receipt_date",
                }
                if state is not None:
                    params["contributor_state"] = state
                if cycle is not None:
                    params["two_year_transaction_period"] = cycle
                params.update(cursor_params)

                data = self._fetch_page(http, FEC_BASE_URL, params)
                results = data["results"]

                if not results:
                    break

                all_results.extend(results)

                if limit is not None and len(all_results) >= limit:
                    return all_results[:limit]

                # Advance cursor for next page
                next_cursor_params = self._extract_cursor_params(data)
                if next_cursor_params is None:
                    break
                cursor_params = next_cursor_params

        return all_results

    def fetch_election_dates(
        self,
        *,
        office: str | None = None,
        state: str | None = None,
        district: str | None = None,
        election_year: int | None = None,
        per_page: int = 20,
        limit: int | None = None,
    ) -> list[dict]:
        """Fetch OpenFEC ``/election-dates/`` rows, following page-based pagination.

        Unlike Schedule A's seek cursor, the election-dates endpoint uses standard
        ``page``/``per_page`` pagination and reports the total page count under
        ``pagination.pages``. Returns the concatenated results list; raises
        FecApiError on transport, HTTP, or envelope errors.
        """
        all_results: list[dict] = []

        with httpx.Client(timeout=FEC_REQUEST_TIMEOUT_SECONDS) as http:
            page = 1
            while True:
                params: dict[str, str | int] = {
                    "api_key": self._api_key,
                    "per_page": per_page,
                    "page": page,
                    "sort": "election_date",
                }
                if office is not None:
                    params["office_sought"] = office
                if state is not None:
                    params["election_state"] = state
                if district is not None:
                    params["election_district"] = district
                if election_year is not None:
                    params["election_year"] = election_year

                data = self._fetch_page(http, FEC_ELECTION_DATES_URL, params)
                results = data["results"]

                if not results:
                    break

                all_results.extend(results)

                if limit is not None and len(all_results) >= limit:
                    return all_results[:limit]

                total_pages = self._total_pages(data)
                if page >= total_pages:
                    break
                page += 1

        return all_results

    def _fetch_page(
        self,
        http: httpx.Client,
        url: str,
        params: dict[str, str | int],
    ) -> dict[str, object]:
        """Issue one GET and return the validated envelope, mapping errors to FecApiError.

        Shared by every endpoint so transport wrapping, non-2xx handling, and
        envelope validation stay identical; per-endpoint pagination advancement
        stays with the caller.
        """
        try:
            response = http.get(url, params=params)
        except httpx.RequestError as error:
            raise FecApiError(f"FEC API request failed: {error}") from None
        self._check_response(response)
        return self._load_page_data(response)

    def _load_page_data(self, response: httpx.Response) -> dict[str, object]:
        try:
            data = response.json()
        except ValueError:
            raise FecApiError("FEC API returned invalid JSON") from None

        if not isinstance(data, dict):
            raise FecApiError("FEC API response must be a JSON object")

        results = data.get("results")
        if not isinstance(results, list):
            raise FecApiError("FEC API response missing results list")

        return data

    def _extract_cursor_params(self, response_data: dict[str, object]) -> dict[str, str] | None:
        pagination = response_data.get("pagination")
        if not isinstance(pagination, dict):
            return None

        last_indexes = pagination.get("last_indexes")
        if not last_indexes:
            return None

        if not isinstance(last_indexes, dict):
            raise FecApiError("FEC API pagination last_indexes must be a JSON object")

        last_index = last_indexes.get("last_index")
        last_contribution_receipt_date = last_indexes.get("last_contribution_receipt_date")
        if not isinstance(last_index, str) or not isinstance(last_contribution_receipt_date, str):
            raise FecApiError("FEC API pagination response missing cursor fields")

        return {
            "last_index": last_index,
            "last_contribution_receipt_date": last_contribution_receipt_date,
        }

    def _total_pages(self, response_data: dict[str, object]) -> int:
        """Return the total page count from a page-based ``pagination`` envelope.

        Raises ``FecApiError`` when the envelope is missing or malformed rather
        than silently truncating multi-page responses.
        """
        pagination = response_data.get("pagination")
        if not isinstance(pagination, dict):
            raise FecApiError("FEC API response missing pagination envelope")
        pages = pagination.get("pages")
        if not isinstance(pages, int) or isinstance(pages, bool):
            raise FecApiError("FEC API pagination.pages must be an integer")
        return pages

    def _check_response(self, response: httpx.Response) -> None:
        """Raise FecApiError with a descriptive message on non-2xx responses."""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            status = response.status_code
            if status == 429:
                raise FecApiError("Rate limit exceeded (HTTP 429). Slow down requests.") from None
            elif status == 403:
                raise FecApiError("Forbidden (HTTP 403). Check your API key.") from None
            else:
                raise FecApiError(f"FEC API error (HTTP {status}): {response.text}") from None
