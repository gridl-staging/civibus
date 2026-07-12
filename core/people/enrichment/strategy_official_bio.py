"""
Stub summary for jun04_3pm_5_launch_gate_and_golive/civibus_dev/core/people/enrichment/strategy_official_bio.py.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from core.people.enrichment.models import CandidateEnrichmentRecord, CandidateEnrichmentTarget, EnrichmentAttempt
from core.people.enrichment.strategy_shared import DEFAULT_HTTP_HEADERS

_BIOGRAPHY_CONTAINER_PATTERN = re.compile(
    r"""<div\b[^>]*class=["'][^"']*nchouseBiography[^"']*["'][^>]*>(.*?)</div>""",
    re.IGNORECASE | re.DOTALL,
)
_ARTICLE_CONTAINER_PATTERN = re.compile(
    r"<article\b[^>]*>(.*?)</article>",
    re.IGNORECASE | re.DOTALL,
)
_PARAGRAPH_PATTERN = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_CAMPAIGN_DOMAIN_TOKENS = ("for", "elect", "vote")
_ALLOWED_BIO_HOST_SUFFIXES = ("ncleg.gov", "congress.gov", "wikipedia.org", "ballotpedia.org")


class OfficialBioStrategy:

    source_name = "official_bio"

    def __init__(
        self,
        *,
        html_fetcher: Callable[[str], str | None] | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._html_fetcher = html_fetcher or (lambda url: self._fetch_html(url, timeout_seconds=timeout_seconds))

    def fetch(
        self,
        target: CandidateEnrichmentTarget,
        missing_fields: tuple[str, ...],
    ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        if "biography" not in missing_fields:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.skipped(
                source=self.source_name,
                requested_fields=missing_fields,
                skip_reason="biography_not_requested",
            )

        roster_bio_url = (target.roster_bio_url or "").strip()
        if roster_bio_url == "":
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )
        if not _is_allowed_bio_source_url(roster_bio_url):
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

        try:
            html = self._html_fetcher(roster_bio_url)
        except Exception as error:  # noqa: BLE001 - strategy must return structured failures.
            return CandidateEnrichmentRecord(), EnrichmentAttempt.failed(
                source=self.source_name,
                requested_fields=missing_fields,
                error_message=str(error),
            )

        if not isinstance(html, str) or html.strip() == "":
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

        biography = _extract_biography_text(html)
        if biography is None:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

        return (
            CandidateEnrichmentRecord(
                biography=biography,
                bio_source_url=roster_bio_url,
                bio_license=_license_for_url(roster_bio_url),
            ),
            EnrichmentAttempt.success(
                source=self.source_name,
                requested_fields=missing_fields,
                contributed_fields=("biography",),
            ),
        )

    def _fetch_html(self, url: str, *, timeout_seconds: float) -> str | None:
        response = httpx.get(
            url,
            headers=DEFAULT_HTTP_HEADERS,
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        if response.status_code in {202, 403, 404, 410, 429}:
            return None
        response.raise_for_status()
        return response.text


def _extract_biography_text(html: str) -> str | None:
    block_match = _BIOGRAPHY_CONTAINER_PATTERN.search(html)
    if block_match is None:
        block_match = _ARTICLE_CONTAINER_PATTERN.search(html)
    if block_match is None:
        return None

    paragraphs: list[str] = []
    for paragraph in _PARAGRAPH_PATTERN.findall(block_match.group(1)):
        cleaned = re.sub(r"\s+", " ", _TAG_PATTERN.sub(" ", paragraph)).strip()
        if cleaned != "":
            paragraphs.append(cleaned)
    return "\n\n".join(paragraphs) if paragraphs else None


def _license_for_url(source_url: str) -> str:
    hostname = (urlparse(source_url).hostname or "").casefold()
    if hostname.endswith(".gov"):
        return "public_domain"
    if hostname.endswith("wikipedia.org") or hostname.endswith("ballotpedia.org"):
        return "licensed"
    if any(token in hostname for token in _CAMPAIGN_DOMAIN_TOKENS):
        return "restricted"
    return "unknown"


def _is_allowed_bio_source_url(source_url: str) -> bool:
    parsed = urlparse(source_url)
    if parsed.scheme.casefold() != "https":
        return False
    hostname = (parsed.hostname or "").casefold()
    if hostname == "":
        return False
    try:
        parsed_ip = ipaddress.ip_address(hostname)
        if parsed_ip.is_private or parsed_ip.is_loopback or parsed_ip.is_link_local:
            return False
    except ValueError:
        pass
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in _ALLOWED_BIO_HOST_SUFFIXES)
