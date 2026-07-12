
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import string
import time
from typing import Any

import httpx

from domains.campaign_finance.jurisdictions.states.NC.scraper.committee_registry import (
    NCCommitteeRegistryRow,
)

CFORGLKUP_LANDING_URL = "https://cf.ncsbe.gov/CFOrgLkup/"
CFORGLKUP_RESULT_URL = "https://cf.ncsbe.gov/CFOrgLkup/CommitteeGeneralResult/"
EXPECTED_STATEWIDE_COMMITTEE_COUNT = 13612
POLITENESS_MIN_SECONDS = 1.0
OVERFLOW_LETTERS = ("A", "C", "E", "N", "O", "R")

_SEARCH_DEFAULTS: Mapping[str, str] = {
    "useOrgName": "true",
    "useCandName": "true",
    "useInHouseName": "true",
    "useAcronym": "false",
}


def build_committee_search_buckets() -> tuple[str, ...]:
    """Return Stage 1 committee-enumeration buckets in deterministic order.

    Strategy: non-overflow single letters + two-letter buckets for overflow
    letters + digit buckets 0-9.
    """
    buckets: list[str] = []
    overflow_set = set(OVERFLOW_LETTERS)

    for letter in string.ascii_uppercase:
        if letter in overflow_set:
            continue
        buckets.append(letter)

    for overflow_letter in OVERFLOW_LETTERS:
        for second_letter in string.ascii_uppercase:
            buckets.append(f"{overflow_letter}{second_letter}")

    buckets.extend(str(digit) for digit in range(10))
    return tuple(buckets)


def parse_result_rows(html_or_rows: str | Sequence[Mapping[str, Any]]) -> list[NCCommitteeRegistryRow]:
    """Parse CFOrgLkup rows into typed NC registry rows, deduped by OGID."""
    raw_rows = _extract_inline_json_rows(html_or_rows) if isinstance(html_or_rows, str) else list(html_or_rows)

    deduped_rows: dict[int, NCCommitteeRegistryRow] = {}
    for raw_row in raw_rows:
        row = _build_registry_row(raw_row)
        deduped_rows[row.org_group_id] = row

    return list(deduped_rows.values())


def crawl_committee_registry(
    fetch_bucket_html: Callable[[str], str],
    *,
    buckets: Sequence[str] | None = None,
    sleep_seconds: float = POLITENESS_MIN_SECONDS,
) -> dict[int, NCCommitteeRegistryRow]:
    """Run bucketed committee discovery and return deduped rows keyed by OGID."""
    if sleep_seconds < 0:
        raise ValueError("sleep_seconds must be non-negative")

    bucket_order = tuple(buckets) if buckets is not None else build_committee_search_buckets()
    discovered_by_org_group_id: dict[int, NCCommitteeRegistryRow] = {}

    for index, bucket in enumerate(bucket_order):
        html = fetch_bucket_html(bucket)
        for row in parse_result_rows(html):
            discovered_by_org_group_id[row.org_group_id] = row

        if sleep_seconds > 0 and index < len(bucket_order) - 1:
            time.sleep(max(sleep_seconds, POLITENESS_MIN_SECONDS))

    return discovered_by_org_group_id


def crawl_committee_registry_httpx(
    *,
    client: httpx.Client | None = None,
    buckets: Sequence[str] | None = None,
    sleep_seconds: float = POLITENESS_MIN_SECONDS,
    timeout_seconds: float = 60.0,
) -> dict[int, NCCommitteeRegistryRow]:
    """Run committee discovery against live CFOrgLkup using an httpx session."""

    def _fetch_bucket_html_with_client(bucket: str) -> str:
        params = dict(_SEARCH_DEFAULTS)
        params["Name"] = bucket
        response = active_client.get(
            CFORGLKUP_RESULT_URL,
            params=params,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response.text

    active_client: httpx.Client
    should_close_client = client is None
    active_client = client or httpx.Client(follow_redirects=True)
    try:
        landing_response = active_client.get(CFORGLKUP_LANDING_URL, timeout=timeout_seconds)
        landing_response.raise_for_status()
        return crawl_committee_registry(
            fetch_bucket_html=_fetch_bucket_html_with_client,
            buckets=buckets,
            sleep_seconds=sleep_seconds,
        )
    finally:
        if should_close_client:
            active_client.close()


def _build_registry_row(raw_row: Mapping[str, Any]) -> NCCommitteeRegistryRow:
    return NCCommitteeRegistryRow(
        org_group_id=int(raw_row.get("OrgGroupID")),
        sboe_id=str(raw_row.get("SBoEID") or ""),
        committee_name=str(raw_row.get("OrgName") or ""),
        status_desc=str(raw_row.get("StatusDesc") or ""),
        old_id=_normalize_optional_text(raw_row.get("OldID")),
        candidate_name=_normalize_optional_text(raw_row.get("CandName")),
    )


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_inline_json_rows(html: str) -> list[Mapping[str, Any]]:
    marker = "var data = ["
    start = html.find(marker)
    if start < 0:
        raise ValueError("Could not find inline committee JSON payload in HTML response")

    json_start = start + len("var data = ")
    depth = 0
    cursor = json_start
    while cursor < len(html):
        char = html[cursor]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                payload = html[json_start : cursor + 1]
                decoded_payload = json.loads(payload)
                return [row for row in decoded_payload if isinstance(row, dict)]
        elif char == '"':
            cursor += 1
            while cursor < len(html) and html[cursor] != '"':
                if html[cursor] == "\\":
                    cursor += 1
                cursor += 1
        cursor += 1

    raise ValueError("Inline committee JSON payload is unterminated")
