

from __future__ import annotations

from collections.abc import Callable, Mapping

import httpx

from core.people.enrichment.models import (
    CandidateEnrichmentRecord,
    CandidateEnrichmentTarget,
    EnrichmentAttempt,
    JsonLikeMapping,
)
from core.people.enrichment.strategy_shared import DEFAULT_HTTP_HEADERS, fetch_bytes_via_http, run_strategy_fetch

_WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"


class WikidataEnrichmentStrategy:
    source_name = "wikidata"

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
        return run_strategy_fetch(
            source_name=self.source_name,
            missing_fields=missing_fields,
            fetch_payload=lambda: self._fetcher(target),
            fetch_portrait_bytes=self._portrait_fetcher,
        )

    def _fetch_from_http(self, target: CandidateEnrichmentTarget, *, timeout_seconds: float) -> JsonLikeMapping | None:
        response = httpx.get(
            _WIKIDATA_SPARQL_URL,
            headers={**DEFAULT_HTTP_HEADERS, "Accept": "application/sparql-results+json"},
            params={
                "format": "json",
                "query": _build_query(target.canonical_name),
            },
            timeout=timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None

        bindings = payload.get("results", {}).get("bindings", [])
        if not isinstance(bindings, list):
            return None
        return _payload_from_bindings(bindings)


def _build_query(canonical_name: str) -> str:
    escaped_name = canonical_name.replace("\\", "\\\\").replace('"', '\\"')
    return f"""
SELECT
  ?item
  ?itemLabel
  ?image
  ?article
  ?website
  (GROUP_CONCAT(DISTINCT ?occupationLabel; separator="; ") AS ?occupations)
  (GROUP_CONCAT(DISTINCT ?educationLabel; separator="; ") AS ?educations)
WHERE {{
  VALUES ?label {{ "{escaped_name}"@en }}
  ?item rdfs:label ?label .
  OPTIONAL {{ ?item wdt:P18 ?image . }}
  OPTIONAL {{ ?item wdt:P856 ?website . }}
  OPTIONAL {{
    ?item wdt:P106 ?occupation .
    ?occupation rdfs:label ?occupationLabel .
    FILTER(LANG(?occupationLabel) = "en")
  }}
  OPTIONAL {{
    ?item wdt:P69 ?education .
    ?education rdfs:label ?educationLabel .
    FILTER(LANG(?educationLabel) = "en")
  }}
  OPTIONAL {{
    ?article schema:about ?item ;
             schema:isPartOf <https://en.wikipedia.org/> .
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
GROUP BY ?item ?itemLabel ?image ?article ?website
LIMIT 10
""".strip()


def _payload_from_bindings(bindings: list[object]) -> JsonLikeMapping | None:
    scored_payloads: list[tuple[int, dict[str, str]]] = []
    for raw_binding in bindings:
        if not isinstance(raw_binding, Mapping):
            continue
        payload = _payload_from_binding(raw_binding)
        if not payload:
            continue
        scored_payloads.append((len(payload), payload))

    if not scored_payloads:
        return None

    scored_payloads.sort(key=lambda item: item[0], reverse=True)
    return scored_payloads[0][1]


def _payload_from_binding(binding: Mapping[str, object]) -> dict[str, str]:
    payload: dict[str, str] = {}

    image_url = _binding_value(binding, "image")
    article_url = _binding_value(binding, "article")
    website_url = _binding_value(binding, "website")
    occupations = _binding_value(binding, "occupations")
    educations = _binding_value(binding, "educations")

    if image_url:
        payload["portrait_image_url"] = image_url
    if article_url:
        payload["wikipedia_url"] = article_url
    if website_url:
        payload["campaign_website_url"] = website_url
    if occupations:
        payload["occupation"] = occupations
    if educations:
        payload["education"] = educations

    return payload


def _binding_value(binding: Mapping[str, object], key: str) -> str | None:
    raw_value = binding.get(key)
    if not isinstance(raw_value, Mapping):
        return None
    value = raw_value.get("value")
    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None
