

from __future__ import annotations

import re
from collections.abc import Callable

import httpx

from core.people.enrichment.models import (
    CandidateEnrichmentRecord,
    CandidateEnrichmentTarget,
    EnrichmentAttempt,
    JsonLikeMapping,
)
from core.people.enrichment.strategy_shared import DEFAULT_HTTP_HEADERS, fetch_bytes_via_http, run_strategy_fetch


PolicyGuard = Callable[[CandidateEnrichmentTarget], tuple[bool, str | None]]
_OG_IMAGE_PATTERN = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_TITLE_PATTERN = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_PARAGRAPH_PATTERN = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")


class BallotpediaEnrichmentStrategy:
    source_name = "ballotpedia"

    def __init__(
        self,
        *,
        fetcher: Callable[[CandidateEnrichmentTarget], JsonLikeMapping | None] | None = None,
        policy_guard: PolicyGuard | None = None,
        timeout_seconds: float = 15.0,
        portrait_fetcher: Callable[[str], bytes | None] | None = None,
    ) -> None:
        self._fetcher = fetcher or (lambda target: self._fetch_from_http(target, timeout_seconds=timeout_seconds))
        self._portrait_fetcher = portrait_fetcher or (
            lambda url: fetch_bytes_via_http(url, timeout_seconds=timeout_seconds)
        )
        self._policy_guard = policy_guard or _default_policy_guard

    def fetch(
        self,
        target: CandidateEnrichmentTarget,
        missing_fields: tuple[str, ...],
    ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        allowed, skip_reason = self._policy_guard(target)
        if not allowed:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.skipped(
                source=self.source_name,
                requested_fields=missing_fields,
                skip_reason=skip_reason or "source-policy-skip",
            )

        return run_strategy_fetch(
            source_name=self.source_name,
            missing_fields=missing_fields,
            fetch_payload=lambda: self._fetcher(target),
            fetch_portrait_bytes=self._portrait_fetcher,
        )

    def _fetch_from_http(self, target: CandidateEnrichmentTarget, *, timeout_seconds: float) -> JsonLikeMapping | None:
        page_url = _ballotpedia_url_for_target(target)
        response = httpx.get(
            page_url,
            headers=DEFAULT_HTTP_HEADERS,
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        if _is_waf_challenge(response) or response.status_code == 404:
            return None
        response.raise_for_status()
        return _extract_payload_from_html(response.text, canonical_name=target.canonical_name)


def _default_policy_guard(_target: CandidateEnrichmentTarget) -> tuple[bool, str | None]:
    return True, None


def _ballotpedia_url_for_target(target: CandidateEnrichmentTarget) -> str:
    if target.ballotpedia_url not in (None, ""):
        return target.ballotpedia_url
    slug = re.sub(r"\s+", "_", target.canonical_name.strip())
    return f"https://ballotpedia.org/{slug}"


def _is_waf_challenge(response: httpx.Response) -> bool:
    return response.status_code == 202 and response.headers.get("x-amzn-waf-action") == "challenge"


def _extract_payload_from_html(html: str, *, canonical_name: str | None = None) -> JsonLikeMapping | None:
    payload: dict[str, str] = {}
    normalized_name_tokens = _normalized_name_tokens(canonical_name)

    if normalized_name_tokens:
        title_match = _TITLE_PATTERN.search(html)
        if title_match is None:
            return None
        title_text = _clean_html_text(title_match.group(1))
        normalized_title = title_text.casefold()
        if not any(token in normalized_title for token in normalized_name_tokens):
            return None

    image_match = _OG_IMAGE_PATTERN.search(html)
    if image_match is not None:
        payload["portrait_image_url"] = image_match.group(1).strip()

    for match in _PARAGRAPH_PATTERN.finditer(html):
        paragraph_text = _clean_html_text(match.group(1))
        if paragraph_text == "":
            continue
        if normalized_name_tokens:
            normalized_paragraph = paragraph_text.casefold()
            if len(paragraph_text) < 40:
                continue
            if not any(token in normalized_paragraph for token in normalized_name_tokens):
                continue
            payload["biography"] = paragraph_text
            break

    return payload or None


def _clean_html_text(value: str) -> str:
    return re.sub(r"\s+", " ", _TAG_PATTERN.sub(" ", value)).strip()


def _normalized_name_tokens(canonical_name: str | None) -> tuple[str, ...]:
    if canonical_name in (None, ""):
        return ()
    tokens = [token.casefold() for token in re.findall(r"[A-Za-z0-9]+", canonical_name) if len(token) >= 3]
    return tuple(tokens)
