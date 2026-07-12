"""PHL Carto SQL API downloader — paged JSON GET with httpx.

Source contract evidence: docs/reference/research/phl_campaign_finance_contract_2026_04_25.md.

The Carto SQL endpoint returns JSON with a top-level `rows` array. Large
result sets are paged via SQL `OFFSET` / `LIMIT` because the public
endpoint does not advertise a streaming or batched protocol.

This module owns ONLY the download/probe contract (URL builder + paged
fetcher + ZIP-style atomic temp-file write). Parsing rows into typed
records lives in `parse.py`; row-to-DB upsert lives in `load.py`.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import urlencode

import httpx

CARTO_SQL_ENDPOINT = "https://phl.carto.com/api/v2/sql"

# Per `docs/reference/research/phl_campaign_finance_contract_2026_04_25.md` —
# observed rate limit is 81 req/sec; default page size is the documented
# Carto safe-default. Larger pages reduce request count but risk timeouts
# on heavy filters.
DEFAULT_PAGE_SIZE = 5000

# Per `CLAUDE.md` "Data Volume — Load Only Recent History": insert only the
# past 5 years of data. For 2026 that is 2022-01-01 onwards.
RECENT_HISTORY_CUTOFF = "2022-01-01"

REQUEST_TIMEOUT_SECONDS = 120.0


class PHLCartoFetchError(RuntimeError):
    """Raised when the Carto SQL API returns an error or malformed response."""


@dataclass(frozen=True, slots=True)
class PHLCartoQuery:
    """Inputs for building a paged Carto SQL query.

    `where` is appended verbatim into the SQL after the canonical date
    filter. Callers must supply only well-formed SQL fragments — this is
    not a parameterized SQL builder and therefore must NEVER receive
    user input.
    """

    table: str
    where: str | None = None
    # Default ORDER BY MUST include a deterministic tiebreaker (cartodb_id)
    # so paging + small-limit re-runs return the same rows. Without it,
    # `LIMIT 5 ORDER BY transaction_date DESC` returns 5 different rows
    # each call when many rows share the same date (the 2026-03-30 cluster
    # has 578 contributions; a 5-row pull would be effectively random).
    order_by: str = "transaction_date DESC, cartodb_id DESC"
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0
    date_column: str = "transaction_date"
    cutoff_date: str = RECENT_HISTORY_CUTOFF


def build_carto_sql(query: PHLCartoQuery) -> str:
    """Build the SQL string for a Carto query, applying the recent-history filter.

    Per project policy the loader inserts only past-5-years rows (CLAUDE.md
    "Data Volume — Load Only Recent History"); the filter is applied at the
    SQL layer so the rows never round-trip through Python. Callers can
    extend with additional `where` predicates that are AND'd to the date
    filter.
    """
    if not query.table or not query.table.replace("_", "").isalnum():
        raise ValueError(f"Invalid Carto table name: {query.table!r}")
    where_clauses = [f"{query.date_column} >= '{query.cutoff_date}'"]
    if query.where:
        where_clauses.append(f"({query.where})")
    where_sql = " AND ".join(where_clauses)
    return (
        f"SELECT * FROM {query.table} "
        f"WHERE {where_sql} "
        f"ORDER BY {query.order_by} "
        f"LIMIT {int(query.limit)} OFFSET {int(query.offset)}"
    )


def build_carto_url(query: PHLCartoQuery, *, endpoint: str = CARTO_SQL_ENDPOINT) -> str:
    """Return the full Carto SQL API URL for the given query."""
    return f"{endpoint}?{urlencode({'q': build_carto_sql(query)})}"


def fetch_carto_page(
    query: PHLCartoQuery,
    *,
    client: httpx.Client | None = None,
    endpoint: str = CARTO_SQL_ENDPOINT,
) -> dict[str, object]:
    """Fetch one page of Carto SQL results as a parsed JSON dict.

    Raises PHLCartoFetchError on a non-2xx response, a non-JSON body, or
    a Carto-side `error` payload. Returns the full parsed response so
    callers can read both `rows` and metadata (`time`, `total_rows`,
    `fields`) without re-parsing.
    """
    url = build_carto_url(query, endpoint=endpoint)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = client.get(url)
    finally:
        if owns_client:
            client.close()
    if response.status_code != 200:
        raise PHLCartoFetchError(f"Carto SQL request returned HTTP {response.status_code}: {response.text[:200]}")
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise PHLCartoFetchError(f"Carto SQL response was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PHLCartoFetchError(f"Carto SQL response was not a JSON object (got {type(payload).__name__})")
    if "error" in payload:
        raise PHLCartoFetchError(f"Carto SQL error: {payload['error']!r}")
    if "rows" not in payload:
        raise PHLCartoFetchError("Carto SQL response missing required 'rows' key")
    return payload


def iter_all_rows(
    query: PHLCartoQuery,
    *,
    client: httpx.Client | None = None,
    endpoint: str = CARTO_SQL_ENDPOINT,
    total_limit: int | None = None,
) -> Iterator[dict[str, object]]:
    """Yield rows matching the query, paging by OFFSET until no rows return.

    `query.limit` is the **page size** for the SQL `LIMIT` clause.
    `total_limit` is the optional **TOTAL** number of rows to yield
    across all pages — once it is hit, iteration stops without
    requesting another page. Without `total_limit`, pagination
    continues until a partial page (< query.limit) signals end of data.

    The split exists because conflating page_size with total cap was a
    real bug: a CLI user passing `--limit 5` against the 1.19M-row PHL
    Carto table would otherwise paginate indefinitely (5 rows per page
    * 240,000 pages, hours of unbounded HTTP traffic).

    Owns its own httpx.Client when none is provided so it can be safely
    used in a one-shot context. When a caller passes an explicit client
    the iteration shares the connection pool across pages.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        offset = query.offset
        yielded = 0
        while True:
            if total_limit is not None and yielded >= total_limit:
                return
            page_query = PHLCartoQuery(
                table=query.table,
                where=query.where,
                order_by=query.order_by,
                limit=query.limit,
                offset=offset,
                date_column=query.date_column,
                cutoff_date=query.cutoff_date,
            )
            payload = fetch_carto_page(page_query, client=client, endpoint=endpoint)
            raw_rows = payload.get("rows")
            rows: list[dict[str, object]] = (
                [r for r in raw_rows if isinstance(r, dict)] if isinstance(raw_rows, list) else []
            )
            if not rows:
                return
            for row in rows:
                if total_limit is not None and yielded >= total_limit:
                    return
                yield row
                yielded += 1
            if len(rows) < query.limit:
                return
            offset += query.limit
    finally:
        if owns_client:
            client.close()


def write_rows_to_jsonl(
    query: PHLCartoQuery,
    dest_path: Path,
    *,
    client: httpx.Client | None = None,
    endpoint: str = CARTO_SQL_ENDPOINT,
    total_limit: int | None = None,
) -> int:
    """Stream rows to a JSONL file, one row per line. Returns row count.

    `total_limit` caps the total rows written across all pages — see
    iter_all_rows for the page_size vs total_limit distinction.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path_str = tempfile.mkstemp(
        prefix=".phl_carto_",
        suffix=".jsonl.part",
        dir=dest_path.parent,
    )
    os.close(fd)
    temp_path = Path(temp_path_str)
    row_count = 0
    try:
        with temp_path.open("w", encoding="utf-8") as fp:
            for row in iter_all_rows(query, client=client, endpoint=endpoint, total_limit=total_limit):
                fp.write(json.dumps(row, default=str) + "\n")
                row_count += 1
        temp_path.replace(dest_path)
        return row_count
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
