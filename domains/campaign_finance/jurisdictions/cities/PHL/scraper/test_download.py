"""Unit tests for PHL Carto SQL download module.

Tests are network-free: httpx is fully mocked. The actual live source
contract is captured in `tests/fixtures/campfin_*_sample_2026_04_25.json`
and re-verified by the integration test in `tests/test_live_carto_contract.py`
(when the test environment allows live HTTP).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from domains.campaign_finance.jurisdictions.cities.PHL.scraper.download import (
    CARTO_SQL_ENDPOINT,
    DEFAULT_PAGE_SIZE,
    PHLCartoFetchError,
    PHLCartoQuery,
    RECENT_HISTORY_CUTOFF,
    build_carto_sql,
    build_carto_url,
    fetch_carto_page,
    iter_all_rows,
    write_rows_to_jsonl,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
_CONTRIBUTIONS_FIXTURE = FIXTURES_DIR / "campfin_contributions_sample_2026_04_25.json"


def test_build_carto_sql_default_order_by_has_deterministic_tiebreaker() -> None:
    """ORDER BY transaction_date DESC alone is non-deterministic for ties
    (Mar 30 has 578 PHL contributions, so a `LIMIT 5` returns a random
    5 each call). The default ORDER BY MUST add cartodb_id DESC as a
    tiebreaker so paging + small-limit pulls are reproducible.

    Live evidence 2026-04-26: a `--limit 5` PHL refresh re-run reported
    `inserted=5 skipped=0` instead of the expected `inserted=0 skipped=5`
    because Carto returned 5 different rows for the second call."""
    sql = build_carto_sql(PHLCartoQuery(table="campfin_contributions"))
    assert "transaction_date DESC" in sql
    assert "cartodb_id DESC" in sql, (
        f"ORDER BY must include cartodb_id tiebreaker for deterministic paging; got: {sql!r}"
    )


def test_build_carto_sql_applies_recent_history_cutoff() -> None:
    """Per CLAUDE.md "Data Volume — Load Only Recent History", the past-5-years
    filter MUST be applied at the SQL layer so old rows never round-trip
    through Python."""
    sql = build_carto_sql(PHLCartoQuery(table="campfin_contributions"))
    assert f"transaction_date >= '{RECENT_HISTORY_CUTOFF}'" in sql
    assert "campfin_contributions" in sql
    assert "ORDER BY transaction_date DESC" in sql
    assert f"LIMIT {DEFAULT_PAGE_SIZE}" in sql
    assert "OFFSET 0" in sql


def test_build_carto_sql_appends_caller_where_with_AND() -> None:
    """Caller-supplied where MUST be ANDed to the canonical date filter, not
    replace it; preserves the date filter as a hard floor."""
    sql = build_carto_sql(PHLCartoQuery(table="campfin_expenditures", where="filer_state = 'PA'"))
    assert f"transaction_date >= '{RECENT_HISTORY_CUTOFF}'" in sql
    assert "(filer_state = 'PA')" in sql
    assert " AND " in sql


def test_build_carto_sql_rejects_table_with_punctuation() -> None:
    """SQL builder must reject obviously unsafe table identifiers."""
    with pytest.raises(ValueError, match="table"):
        build_carto_sql(PHLCartoQuery(table="campfin; DROP TABLE foo;"))


def test_build_carto_url_uses_carto_sql_endpoint() -> None:
    url = build_carto_url(PHLCartoQuery(table="campfin_contributions"))
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "phl.carto.com"
    assert parsed.path == "/api/v2/sql"
    qs = parse_qs(parsed.query)
    assert "campfin_contributions" in qs["q"][0]


def test_fetch_carto_page_returns_parsed_payload_on_200() -> None:
    """Happy-path: well-formed JSON 200 -> parsed dict including rows + metadata."""
    sample = json.loads(_CONTRIBUTIONS_FIXTURE.read_text(encoding="utf-8"))
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json = MagicMock(return_value=sample)
    response.text = json.dumps(sample)
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(return_value=response)

    payload = fetch_carto_page(PHLCartoQuery(table="campfin_contributions"), client=client)
    assert isinstance(payload, dict)
    assert "rows" in payload
    assert isinstance(payload["rows"], list)
    assert len(payload["rows"]) == 5

    # Each call must use the canonical Carto endpoint URL
    actual_url = client.get.call_args[0][0]
    assert actual_url.startswith(CARTO_SQL_ENDPOINT + "?q=")


def test_fetch_carto_page_raises_on_non_200() -> None:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 502
    response.text = "Bad Gateway"
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(return_value=response)
    with pytest.raises(PHLCartoFetchError, match="HTTP 502"):
        fetch_carto_page(PHLCartoQuery(table="campfin_contributions"), client=client)


def test_fetch_carto_page_raises_on_carto_error_payload() -> None:
    """Carto signals SQL/auth errors with HTTP 200 + {"error": [...]}."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json = MagicMock(return_value={"error": ['relation "x" does not exist']})
    response.text = '{"error":["relation x does not exist"]}'
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(return_value=response)
    with pytest.raises(PHLCartoFetchError, match="error"):
        fetch_carto_page(PHLCartoQuery(table="campfin_contributions"), client=client)


def test_fetch_carto_page_raises_on_missing_rows_key() -> None:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json = MagicMock(return_value={"time": 0.1})
    response.text = '{"time":0.1}'
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(return_value=response)
    with pytest.raises(PHLCartoFetchError, match="rows"):
        fetch_carto_page(PHLCartoQuery(table="campfin_contributions"), client=client)


def test_iter_all_rows_stops_at_total_limit_not_page_size() -> None:
    """When the user specifies a total cap (PHLCartoQuery.limit alongside an
    explicit `total_limit` to iter_all_rows), pagination MUST stop after that
    many rows have been yielded.

    Live evidence 2026-04-26: the CLI's `--limit 5` invocation hung
    indefinitely against the live PHL Carto endpoint because iter_all_rows
    paginated indefinitely (5 rows per page * page-after-page until the
    1.19M-row table was exhausted, ~33h estimated). The page_size and the
    user-facing total cap are different concepts; this test pins the
    distinction.
    """
    page_1 = {"rows": [{"transaction_id": str(i)} for i in range(1, 6)]}
    page_2 = {"rows": [{"transaction_id": str(i)} for i in range(6, 11)]}
    response_1 = MagicMock(spec=httpx.Response)
    response_1.status_code = 200
    response_1.json = MagicMock(return_value=page_1)
    response_1.text = ""
    response_2 = MagicMock(spec=httpx.Response)
    response_2.status_code = 200
    response_2.json = MagicMock(return_value=page_2)
    response_2.text = ""
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(side_effect=[response_1, response_2])

    rows = list(
        iter_all_rows(
            PHLCartoQuery(table="campfin_contributions", limit=5),
            client=client,
            total_limit=5,
        )
    )
    assert len(rows) == 5
    assert [r["transaction_id"] for r in rows] == ["1", "2", "3", "4", "5"]
    # Critically: iter_all_rows must NOT request page 2 once the total cap
    # is hit. Anything more is unbounded pagination, which is the bug.
    assert client.get.call_count == 1, (
        f"iter_all_rows should stop after total_limit rows; called Carto {client.get.call_count} times (expected 1)"
    )


def test_iter_all_rows_pages_until_empty() -> None:
    """iter_all_rows MUST advance OFFSET by `limit` and stop when a page has fewer than `limit` rows."""
    page_size = 2
    page_1 = {"rows": [{"transaction_id": "1"}, {"transaction_id": "2"}]}
    page_2 = {"rows": [{"transaction_id": "3"}]}  # less than page_size — last page

    response_1 = MagicMock(spec=httpx.Response)
    response_1.status_code = 200
    response_1.json = MagicMock(return_value=page_1)
    response_1.text = ""
    response_2 = MagicMock(spec=httpx.Response)
    response_2.status_code = 200
    response_2.json = MagicMock(return_value=page_2)
    response_2.text = ""
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(side_effect=[response_1, response_2])

    rows = list(
        iter_all_rows(
            PHLCartoQuery(table="campfin_contributions", limit=page_size),
            client=client,
        )
    )
    assert [r["transaction_id"] for r in rows] == ["1", "2", "3"]
    assert client.get.call_count == 2

    # Second call must use OFFSET=2 (the page_size advance)
    second_url = client.get.call_args_list[1].args[0]
    assert "OFFSET+2" in second_url or "OFFSET%202" in second_url or "OFFSET 2" in second_url


def test_iter_all_rows_terminates_when_first_page_has_fewer_than_limit() -> None:
    """Single-page result set MUST not issue a second request."""
    page_1 = {"rows": [{"transaction_id": "only"}]}
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json = MagicMock(return_value=page_1)
    response.text = ""
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(return_value=response)

    rows = list(
        iter_all_rows(
            PHLCartoQuery(table="campfin_contributions", limit=10),
            client=client,
        )
    )
    assert len(rows) == 1
    assert client.get.call_count == 1


def test_write_rows_to_jsonl_writes_expected_row_count(tmp_path: Path) -> None:
    """End-to-end stream: every yielded row should land in the JSONL file
    on a separate line. Row order must match iter_all_rows order."""
    page_1 = {"rows": [{"transaction_id": "1", "x": 1}, {"transaction_id": "2", "x": 2}]}
    page_2 = {"rows": [{"transaction_id": "3", "x": 3}]}
    response_1 = MagicMock(spec=httpx.Response)
    response_1.status_code = 200
    response_1.json = MagicMock(return_value=page_1)
    response_1.text = ""
    response_2 = MagicMock(spec=httpx.Response)
    response_2.status_code = 200
    response_2.json = MagicMock(return_value=page_2)
    response_2.text = ""
    client = MagicMock(spec=httpx.Client)
    client.get = MagicMock(side_effect=[response_1, response_2])

    dest = tmp_path / "out.jsonl"
    count = write_rows_to_jsonl(
        PHLCartoQuery(table="campfin_contributions", limit=2),
        dest,
        client=client,
    )
    assert count == 3
    assert dest.exists()
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    # Each line must be a valid JSON object preserving the row identity.
    parsed = [json.loads(line) for line in lines]
    assert [r["transaction_id"] for r in parsed] == ["1", "2", "3"]
