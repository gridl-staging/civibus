from __future__ import annotations

import json
from pathlib import Path

import pytest

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

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Morgan Patel"), missing_fields=("wikipedia_url", "portrait_image_url")
    )

    assert attempt.status == "succeeded"
    assert record.wikipedia_url == "https://en.wikipedia.org/wiki/Morgan_Patel"
    assert record.portrait_image_url == "https://upload.wikimedia.org/morgan.jpg"


def test_wikidata_strategy_returns_no_data_attempt() -> None:
    strategy = WikidataEnrichmentStrategy(fetcher=lambda _target: _fixture("wikidata_no_data.json"))

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Unknown"), missing_fields=("wikipedia_url",)
    )

    assert record == record.__class__()
    assert attempt.status == "no_data"


@pytest.mark.parametrize("wikidata_entity_id", [None, "", "12345", "Qabc"])
def test_required_qid_mode_skips_without_fetching_name_query(
    wikidata_entity_id: str | None,
) -> None:
    def _fail_fetch(_target: CandidateEnrichmentTarget) -> dict[str, object]:
        pytest.fail("required-QID Wikidata must not fall back to name query")

    strategy = WikidataEnrichmentStrategy(fetcher=_fail_fetch, require_wikidata_entity_id=True)

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Wrong Same Name", wikidata_entity_id=wikidata_entity_id),
        missing_fields=("wikipedia_url",),
    )

    assert record == record.__class__()
    assert attempt.status == "skipped"
    assert attempt.skip_reason == "missing_valid_wikidata_entity_id"


def test_build_query_escapes_name_and_requests_expected_fields() -> None:
    query = _build_query('Alex "Ace" Rivera')

    assert '\\"Ace\\"' in query
    assert "P18" in query
    assert "P69" in query
    assert "P106" in query
    assert "P856" in query
    assert 'VALUES ?label { "Alex \\"Ace\\" Rivera"@en }' in query
    assert "?item rdfs:label ?label ." in query


def test_build_query_uses_direct_wikidata_entity_binding_for_qid() -> None:
    query = _build_query("Wrong Same Name", wikidata_entity_id="Q12345")

    assert "BIND(wd:Q12345 AS ?item)" in query
    assert "VALUES ?label" not in query
    assert "?item rdfs:label ?label ." not in query


def test_fetch_from_http_passes_target_wikidata_entity_id_to_query_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_query_args: list[tuple[str, str | None]] = []

    def _fake_build_query(canonical_name: str, wikidata_entity_id: str | None = None) -> str:
        observed_query_args.append((canonical_name, wikidata_entity_id))
        return "SELECT ?item WHERE { BIND(wd:Q12345 AS ?item) }"

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"results": {"bindings": []}}

    def _fake_get(*_args: object, **_kwargs: object) -> _Response:
        return _Response()

    monkeypatch.setattr("core.people.enrichment.strategy_wikidata._build_query", _fake_build_query)
    monkeypatch.setattr("core.people.enrichment.strategy_wikidata.httpx.get", _fake_get)

    strategy = WikidataEnrichmentStrategy()
    payload = strategy._fetch_from_http(
        CandidateEnrichmentTarget(canonical_name="Wrong Same Name", wikidata_entity_id="Q12345"),
        timeout_seconds=1.0,
    )

    assert payload is None
    assert observed_query_args == [("Wrong Same Name", "Q12345")]


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
