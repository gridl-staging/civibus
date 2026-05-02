from __future__ import annotations

import json
from pathlib import Path

from core.people.enrichment.models import CandidateEnrichmentTarget
from core.people.enrichment.strategy_wikidata import (
    WikidataEnrichmentStrategy,
    _build_query,
    _payload_from_bindings,
)


def _fixture(name: str) -> dict[str, object]:
    fixture_path = Path(__file__).with_name("test_fixtures") / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))



def test_wikidata_strategy_extracts_expected_fields() -> None:
    strategy = WikidataEnrichmentStrategy(fetcher=lambda _target: _fixture("wikidata_success.json"))

    record, attempt = strategy.fetch(CandidateEnrichmentTarget(canonical_name="Morgan Patel"), missing_fields=("wikipedia_url", "portrait_image_url"))

    assert attempt.status == "succeeded"
    assert record.wikipedia_url == "https://en.wikipedia.org/wiki/Morgan_Patel"
    assert record.portrait_image_url == "https://upload.wikimedia.org/morgan.jpg"



def test_wikidata_strategy_returns_no_data_attempt() -> None:
    strategy = WikidataEnrichmentStrategy(fetcher=lambda _target: _fixture("wikidata_no_data.json"))

    record, attempt = strategy.fetch(CandidateEnrichmentTarget(canonical_name="Unknown"), missing_fields=("wikipedia_url",))

    assert record == record.__class__()
    assert attempt.status == "no_data"


def test_build_query_escapes_name_and_requests_expected_fields() -> None:
    query = _build_query('Alex "Ace" Rivera')

    assert '\\"Ace\\"' in query
    assert "P18" in query
    assert "P69" in query
    assert "P106" in query
    assert "P856" in query


def test_payload_from_bindings_prefers_binding_with_most_supported_fields() -> None:
    bindings = [
        {
            "article": {"value": "https://en.wikipedia.org/wiki/Alex_Rivera"},
        },
        {
            "image": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/Alex%20Rivera.jpg"},
            "article": {"value": "https://en.wikipedia.org/wiki/Alex_Rivera"},
            "website": {"value": "https://alexrivera.example.org"},
            "occupations": {"value": "lawyer; politician"},
            "educations": {"value": "Duke University"},
        },
    ]

    payload = _payload_from_bindings(bindings)

    assert payload == {
        "portrait_image_url": "http://commons.wikimedia.org/wiki/Special:FilePath/Alex%20Rivera.jpg",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Alex_Rivera",
        "campaign_website_url": "https://alexrivera.example.org",
        "occupation": "lawyer; politician",
        "education": "Duke University",
    }
