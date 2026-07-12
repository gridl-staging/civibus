
from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from urllib.parse import quote

import httpx

from core.people.enrichment.models import (
    CandidateEnrichmentRecord,
    CandidateEnrichmentTarget,
    EnrichmentAttempt,
)
from core.people.enrichment.strategy_shared import DEFAULT_HTTP_HEADERS

_WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
_WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
_WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"
_WIKIDATA_BATCH_SIZE = 50
_WIKIPEDIA_SUMMARY_BATCH_SIZE = 50
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0
_INTER_BATCH_DELAY = 3.0


class WikipediaBioStrategy:

    source_name = "wikipedia_bio"

    def __init__(
        self,
        *,
        title_fetcher: Callable[[str], str | None] | None = None,
        summary_fetcher: Callable[[str], Mapping[str, object] | None] | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._title_fetcher = title_fetcher or (
            lambda qid: _fetch_wikipedia_title(qid, timeout_seconds=timeout_seconds)
        )
        self._summary_fetcher = summary_fetcher or (
            lambda title: _fetch_wikipedia_summary(title, timeout_seconds=timeout_seconds)
        )

    def install_prefetch_cache(
        self,
        *,
        title_cache: Mapping[str, str],
        summary_cache: Mapping[str, Mapping[str, object]],
    ) -> None:
        """Wrap the existing fetchers with cache lookups, falling back to live fetch on miss."""
        original_title_fetcher = self._title_fetcher
        original_summary_fetcher = self._summary_fetcher

        def title_fetcher(qid: str) -> str | None:
            cached_title = title_cache.get(qid)
            if cached_title is not None:
                return cached_title
            return original_title_fetcher(qid)

        def summary_fetcher(title: str) -> Mapping[str, object] | None:
            cached_summary = summary_cache.get(title)
            if cached_summary is not None:
                return cached_summary
            return original_summary_fetcher(title)

        self._title_fetcher = title_fetcher
        self._summary_fetcher = summary_fetcher

    def fetch(
        self,
        target: CandidateEnrichmentTarget,
        missing_fields: tuple[str, ...],
    ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        qid = _normalize_qid(target.wikidata_entity_id)
        if qid is None:
            return (
                CandidateEnrichmentRecord(),
                EnrichmentAttempt.skipped(
                    source=self.source_name,
                    requested_fields=missing_fields,
                    skip_reason="missing_wikidata_entity_id",
                ),
            )

        try:
            title = self._title_fetcher(qid)
        except Exception as exc:  # noqa: BLE001
            return (
                CandidateEnrichmentRecord(),
                EnrichmentAttempt.failed(
                    source=self.source_name,
                    requested_fields=missing_fields,
                    error_message=str(exc),
                ),
            )

        if title is None:
            return (
                CandidateEnrichmentRecord(),
                EnrichmentAttempt.no_data(source=self.source_name, requested_fields=missing_fields),
            )

        try:
            summary = self._summary_fetcher(title)
        except Exception as exc:  # noqa: BLE001
            return (
                CandidateEnrichmentRecord(),
                EnrichmentAttempt.failed(
                    source=self.source_name,
                    requested_fields=missing_fields,
                    error_message=str(exc),
                ),
            )

        if summary is None:
            return (
                CandidateEnrichmentRecord(),
                EnrichmentAttempt.no_data(source=self.source_name, requested_fields=missing_fields),
            )

        extract = _extract_text(summary, "extract")
        if not extract:
            return (
                CandidateEnrichmentRecord(),
                EnrichmentAttempt.no_data(source=self.source_name, requested_fields=missing_fields),
            )

        wikipedia_url = _extract_wikipedia_url(summary)

        record = CandidateEnrichmentRecord(
            biography=extract,
            bio_source_url=wikipedia_url,
            bio_license="licensed",
            wikipedia_url=wikipedia_url,
        )
        contributed = tuple(f for f in ("biography", "wikipedia_url") if getattr(record, f) not in (None, ""))
        return (
            record,
            EnrichmentAttempt.success(
                source=self.source_name,
                requested_fields=missing_fields,
                contributed_fields=contributed,
            ),
        )


def _normalize_qid(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    if len(stripped) < 2:
        return None
    if stripped[0].upper() != "Q":
        return None
    if not stripped[1:].isdecimal():
        return None
    return f"Q{stripped[1:]}"


def _extract_text(summary: Mapping[str, object], key: str) -> str | None:
    value = summary.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _extract_wikipedia_url(summary: Mapping[str, object]) -> str | None:
    content_urls = summary.get("content_urls")
    if not isinstance(content_urls, Mapping):
        return None
    desktop = content_urls.get("desktop")
    if not isinstance(desktop, Mapping):
        return None
    page = desktop.get("page")
    if isinstance(page, str) and page.strip():
        return page.strip()
    return None


def batch_fetch_wikipedia_titles(
    qids: list[str],
    *,
    timeout_seconds: float = 15.0,
    batch_size: int | None = None,
    inter_batch_delay: float | None = None,
) -> dict[str, str]:
    """Batch-resolve Wikidata QIDs to English Wikipedia article titles.

    Uses the Wikidata API's multi-entity endpoint (up to 50 IDs per request)
    to avoid per-entity rate limiting.
    """
    bs = batch_size if batch_size is not None else _WIKIDATA_BATCH_SIZE
    delay = inter_batch_delay if inter_batch_delay is not None else _INTER_BATCH_DELAY
    result: dict[str, str] = {}
    for batch_index, batch_start in enumerate(range(0, len(qids), bs)):
        if batch_index > 0:
            time.sleep(delay)
        batch = qids[batch_start : batch_start + bs]
        try:
            batch_result = _fetch_titles_batch(batch, timeout_seconds=timeout_seconds)
        except httpx.HTTPError:
            continue
        result.update(batch_result)
    return result


def batch_fetch_wikipedia_summaries(
    titles: list[str],
    *,
    timeout_seconds: float = 15.0,
    batch_size: int | None = None,
    inter_batch_delay: float | None = None,
) -> dict[str, Mapping[str, object]]:
    """Batch-resolve English Wikipedia lead extracts keyed by requested title."""
    bs = batch_size if batch_size is not None else _WIKIPEDIA_SUMMARY_BATCH_SIZE
    delay = inter_batch_delay if inter_batch_delay is not None else _INTER_BATCH_DELAY
    result: dict[str, Mapping[str, object]] = {}
    for batch_index, batch_start in enumerate(range(0, len(titles), bs)):
        if batch_index > 0:
            time.sleep(delay)
        batch = titles[batch_start : batch_start + bs]
        try:
            result.update(_fetch_summaries_batch(batch, timeout_seconds=timeout_seconds))
        except httpx.HTTPError:
            continue
    return result


def _fetch_titles_batch(
    qids: list[str],
    *,
    timeout_seconds: float,
) -> dict[str, str]:
    ids_param = "|".join(qids)
    for attempt in range(_MAX_RETRIES):
        try:
            response = httpx.get(
                _WIKIDATA_API_URL,
                params={
                    "action": "wbgetentities",
                    "ids": ids_param,
                    "sites": "enwiki",
                    "props": "sitelinks",
                    "format": "json",
                },
                headers=DEFAULT_HTTP_HEADERS,
                timeout=timeout_seconds,
            )
            if response.status_code == 429:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_BASE_DELAY * (2**attempt))
                    continue
            response.raise_for_status()
            break
        except httpx.HTTPStatusError:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BASE_DELAY * (2**attempt))
                continue
            raise

    data = response.json()
    if not isinstance(data, dict):
        return {}

    entities = data.get("entities", {})
    titles: dict[str, str] = {}
    for qid in qids:
        entity = entities.get(qid, {})
        if not isinstance(entity, dict):
            continue
        sitelinks = entity.get("sitelinks", {})
        if not isinstance(sitelinks, dict):
            continue
        enwiki = sitelinks.get("enwiki", {})
        if not isinstance(enwiki, dict):
            continue
        title = enwiki.get("title")
        if isinstance(title, str) and title.strip():
            titles[qid] = title.strip()
    return titles


def _fetch_summaries_batch(
    titles: list[str],
    *,
    timeout_seconds: float,
) -> dict[str, Mapping[str, object]]:
    titles_param = "|".join(titles)
    base_params: dict[str, object] = {
        "action": "query",
        "prop": "extracts|info",
        "inprop": "url",
        "exintro": 1,
        "exlimit": "max",
        "explaintext": 1,
        "redirects": 1,
        "format": "json",
        "titles": titles_param,
    }
    pages: dict[str, object] = {}
    redirects: list[object] = []
    continuation_params: dict[str, object] = {}

    while True:
        response = None
        for attempt in range(_MAX_RETRIES):
            response = httpx.get(
                _WIKIPEDIA_API_URL,
                params={**base_params, **continuation_params},
                headers={**DEFAULT_HTTP_HEADERS, "Accept": "application/json"},
                timeout=timeout_seconds,
            )
            if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BASE_DELAY * (2**attempt))
                continue
            response.raise_for_status()
            break

        if response is None:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            return {}
        query = payload.get("query")
        if isinstance(query, dict):
            raw_pages = query.get("pages")
            if isinstance(raw_pages, dict):
                _merge_pages(pages, raw_pages)
            raw_redirects = query.get("redirects")
            if isinstance(raw_redirects, list):
                redirects.extend(raw_redirects)
        raw_continue = payload.get("continue")
        if not isinstance(raw_continue, dict):
            break
        continuation_params = dict(raw_continue)

    if not pages:
        return {}

    requested_titles = {_normalize_title_key(title): title for title in titles}
    redirect_aliases = _redirect_aliases(redirects)
    summaries: dict[str, Mapping[str, object]] = {}
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        title = page.get("title")
        extract = page.get("extract")
        page_url = page.get("fullurl")
        if not isinstance(title, str) or not isinstance(extract, str) or not extract.strip():
            continue
        if not isinstance(page_url, str) or not page_url.strip():
            page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
        summary = {
            "extract": extract.strip(),
            "content_urls": {"desktop": {"page": page_url.strip()}},
        }
        canonical_key = _normalize_title_key(title)
        requested_title = requested_titles.get(canonical_key)
        if requested_title is not None:
            summaries[requested_title] = summary
        for alias in redirect_aliases.get(canonical_key, ()):
            requested_alias = requested_titles.get(_normalize_title_key(alias))
            if requested_alias is not None:
                summaries[requested_alias] = summary
    return summaries


def _merge_pages(pages: dict[str, object], incoming_pages: dict[object, object]) -> None:
    for page_id, incoming_page in incoming_pages.items():
        if not isinstance(incoming_page, dict):
            pages[str(page_id)] = incoming_page
            continue
        existing_page = pages.get(str(page_id))
        if isinstance(existing_page, dict):
            pages[str(page_id)] = {**incoming_page, **existing_page}
        else:
            pages[str(page_id)] = incoming_page


def _redirect_aliases(raw_redirects: object) -> dict[str, list[str]]:
    aliases: dict[str, list[str]] = {}
    if not isinstance(raw_redirects, list):
        return aliases
    for redirect in raw_redirects:
        if not isinstance(redirect, dict):
            continue
        source = redirect.get("from")
        target = redirect.get("to")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        aliases.setdefault(_normalize_title_key(target), []).append(source)
    return aliases


def _normalize_title_key(title: str) -> str:
    return title.replace("_", " ").strip().casefold()


def _fetch_wikipedia_title(qid: str, *, timeout_seconds: float) -> str | None:
    titles = _fetch_titles_batch([qid], timeout_seconds=timeout_seconds)
    return titles.get(qid)


def _fetch_wikipedia_summary(title: str, *, timeout_seconds: float) -> Mapping[str, object] | None:
    encoded_title = quote(title, safe="")
    for attempt in range(_MAX_RETRIES):
        response = httpx.get(
            f"{_WIKIPEDIA_SUMMARY_URL}/{encoded_title}",
            headers={**DEFAULT_HTTP_HEADERS, "Accept": "application/json"},
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        if response.status_code == 429:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BASE_DELAY * (2**attempt))
                continue
        if response.status_code in {404, 410}:
            return None
        response.raise_for_status()
        break

    payload = response.json()
    if not isinstance(payload, dict):
        return None
    return payload
