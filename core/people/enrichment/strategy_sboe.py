"""
Stub summary for jun04_3pm_3_member_photo_bio_enrichment/civibus_dev/core/people/enrichment/strategy_sboe.py.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from core.people.enrichment.models import (
    CandidateEnrichmentRecord,
    CandidateEnrichmentTarget,
    EnrichmentAttempt,
    JsonLikeMapping,
)
from core.people.enrichment.strategy_shared import DEFAULT_HTTP_HEADERS, fetch_bytes_via_http, run_strategy_fetch

_CANDIDATE_LISTS_PAGE_URL = "https://www.ncsbe.gov/results-data/candidate-lists"
_CSV_URL_PATTERN = re.compile(r'https://[^"\']+Candidate[^"\']+_(\d{4})\.csv')
_SBOE_STATE_CODE = "NC"
_NON_NC_TARGET_SKIP_REASON = "state_not_nc"


class SboeEnrichmentStrategy:

    source_name = "sboe"

    def __init__(
        self,
        *,
        fetcher: Callable[[CandidateEnrichmentTarget], JsonLikeMapping | None] | None = None,
        timeout_seconds: float = 15.0,
        portrait_fetcher: Callable[[str], bytes | None] | None = None,
    ) -> None:
        self._fetcher = fetcher or (lambda target: self._fetch_from_http(target, timeout_seconds=timeout_seconds))
        self._portrait_fetcher = portrait_fetcher or (
            lambda url: fetch_bytes_via_http(url, timeout_seconds=timeout_seconds)
        )

    def fetch(
        self,
        target: CandidateEnrichmentTarget,
        missing_fields: tuple[str, ...],
    ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        if not _is_nc_sboe_target(target):
            return CandidateEnrichmentRecord(), EnrichmentAttempt.skipped(
                source=self.source_name,
                requested_fields=missing_fields,
                skip_reason=_NON_NC_TARGET_SKIP_REASON,
            )

        return run_strategy_fetch(
            source_name=self.source_name,
            missing_fields=missing_fields,
            fetch_payload=lambda: self._fetcher(target),
            fetch_portrait_bytes=self._portrait_fetcher,
        )

    def _fetch_from_http(self, target: CandidateEnrichmentTarget, *, timeout_seconds: float) -> JsonLikeMapping | None:
        if not _is_nc_sboe_target(target):
            return None

        response = httpx.get(
            _CANDIDATE_LISTS_PAGE_URL,
            headers=DEFAULT_HTTP_HEADERS,
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        response.raise_for_status()

        csv_url = _extract_candidate_csv_url(response.text, preferred_year=2026)
        if csv_url is None:
            return None
        if not _is_allowed_candidate_csv_url(csv_url):
            return None

        csv_response = httpx.get(
            csv_url,
            headers=DEFAULT_HTTP_HEADERS,
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        csv_response.raise_for_status()

        matched_row = _find_candidate_row(csv_response.text, canonical_name=target.canonical_name)
        if matched_row is None:
            return None

        # The official candidate-list CSV exposes filing/party/contact fields but not the
        # portrait/occupation/education/website fields in the current enrichment DTO.
        return _payload_from_candidate_row(matched_row)


def _is_nc_sboe_target(target: CandidateEnrichmentTarget) -> bool:
    if target.state_code is None:
        return False
    return target.state_code.strip().upper() == _SBOE_STATE_CODE


def _extract_candidate_csv_url(html: str, *, preferred_year: int) -> str | None:
    matches = list(_CSV_URL_PATTERN.finditer(html))
    if not matches:
        return None

    for match in matches:
        if int(match.group(1)) == preferred_year:
            return match.group(0)

    latest_match = max(matches, key=lambda match: int(match.group(1)))
    return latest_match.group(0)


def _is_allowed_candidate_csv_url(csv_url: str) -> bool:
    parsed_url = urlparse(csv_url)
    if parsed_url.scheme != "https":
        return False
    if parsed_url.params or parsed_url.query or parsed_url.fragment:
        return False

    hostname = (parsed_url.hostname or "").lower()
    if hostname.endswith(".ncsbe.gov") or hostname == "ncsbe.gov":
        return True

    return hostname == "s3.amazonaws.com" and parsed_url.path.startswith("/dl.ncsbe.gov/")


def _normalize_candidate_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _find_candidate_row(csv_text: str, *, canonical_name: str) -> dict[str, str] | None:
    normalized_target = _normalize_candidate_name(canonical_name)
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        ballot_name = row.get("name_on_ballot")
        if ballot_name and _normalize_candidate_name(ballot_name) == normalized_target:
            return {key: value for key, value in row.items() if isinstance(key, str) and isinstance(value, str)}

        first_name = (row.get("first_name") or "").strip()
        middle_name = (row.get("middle_name") or "").strip()
        last_name = (row.get("last_name") or "").strip()
        combined_name = " ".join(part for part in (first_name, middle_name, last_name) if part != "")
        if combined_name and _normalize_candidate_name(combined_name) == normalized_target:
            return {key: value for key, value in row.items() if isinstance(key, str) and isinstance(value, str)}

    return None


def _payload_from_candidate_row(_row: dict[str, str]) -> JsonLikeMapping | None:
    return None
