from __future__ import annotations

import pytest
import httpx

from core.people.enrichment.models import CandidateEnrichmentTarget
from core.people.enrichment import strategy_wikipedia_bio as wikipedia_bio_module
from core.people.enrichment.strategy_wikipedia_bio import (
    WikipediaBioStrategy,
    batch_fetch_wikipedia_summaries,
    batch_fetch_wikipedia_titles,
)


def test_happy_path_returns_biography_and_provenance() -> None:
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: "Nancy_Pelosi",
        summary_fetcher=lambda _title: {
            "extract": "Nancy Patricia Pelosi is an American politician who served as the 52nd speaker.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Nancy_Pelosi"}},
        },
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Nancy Pelosi",
        wikidata_entity_id="Q170581",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "succeeded"
    assert record.biography == "Nancy Patricia Pelosi is an American politician who served as the 52nd speaker."
    assert record.bio_source_url == "https://en.wikipedia.org/wiki/Nancy_Pelosi"
    assert record.bio_license == "licensed"


def test_missing_wikidata_entity_id_returns_skipped() -> None:
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: (_ for _ in ()).throw(AssertionError("should not be called")),
        summary_fetcher=lambda _title: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    target = CandidateEnrichmentTarget(canonical_name="John Doe")

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "skipped"
    assert attempt.skip_reason == "missing_wikidata_entity_id"
    assert record.biography is None


def test_invalid_wikidata_entity_id_returns_skipped() -> None:
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: (_ for _ in ()).throw(AssertionError("should not be called")),
        summary_fetcher=lambda _title: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="John Doe",
        wikidata_entity_id="not-a-qid",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "skipped"
    assert attempt.skip_reason == "missing_wikidata_entity_id"


def test_no_wikipedia_title_returns_no_data() -> None:
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: None,
        summary_fetcher=lambda _title: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jane Smith",
        wikidata_entity_id="Q99999999",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "no_data"
    assert record.biography is None


def test_empty_extract_returns_no_data() -> None:
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: "Some_Title",
        summary_fetcher=lambda _title: {"extract": "", "content_urls": {}},
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jane Smith",
        wikidata_entity_id="Q12345",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "no_data"
    assert record.biography is None


def test_summary_fetcher_returns_none_returns_no_data() -> None:
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: "Some_Title",
        summary_fetcher=lambda _title: None,
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jane Smith",
        wikidata_entity_id="Q12345",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "no_data"


def test_title_fetcher_transport_error_returns_failed() -> None:
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: (_ for _ in ()).throw(RuntimeError("dns failure")),
        summary_fetcher=lambda _title: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="John Doe",
        wikidata_entity_id="Q170581",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "failed"
    assert attempt.source == "wikipedia_bio"
    assert "dns failure" in attempt.error_message


def test_summary_fetcher_transport_error_returns_failed() -> None:
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: "Nancy_Pelosi",
        summary_fetcher=lambda _title: (_ for _ in ()).throw(RuntimeError("timeout")),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Nancy Pelosi",
        wikidata_entity_id="Q170581",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "failed"
    assert "timeout" in attempt.error_message


def test_biography_not_in_missing_fields_still_fetches() -> None:
    """Strategy fetches regardless of missing_fields; the chain merge controls what sticks."""
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: "Nancy_Pelosi",
        summary_fetcher=lambda _title: {
            "extract": "Some bio text.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Nancy_Pelosi"}},
        },
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Nancy Pelosi",
        wikidata_entity_id="Q170581",
    )

    record, attempt = strategy.fetch(target, missing_fields=("occupation",))

    assert attempt.status == "succeeded"
    assert record.biography == "Some bio text."


def test_extracts_wikipedia_url_from_content_urls() -> None:
    strategy = WikipediaBioStrategy(
        title_fetcher=lambda _qid: "Chuck_Schumer",
        summary_fetcher=lambda _title: {
            "extract": "Charles Ellis Schumer is an American politician.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Chuck_Schumer"}},
        },
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Chuck Schumer",
        wikidata_entity_id="Q380900",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography", "wikipedia_url"))

    assert record.wikipedia_url == "https://en.wikipedia.org/wiki/Chuck_Schumer"


def test_qid_normalization_accepts_lowercase() -> None:
    fetched_qids: list[str] = []

    def capture_qid(qid: str) -> str:
        fetched_qids.append(qid)
        return "Test_Title"

    strategy = WikipediaBioStrategy(
        title_fetcher=capture_qid,
        summary_fetcher=lambda _title: {
            "extract": "Bio.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Test"}},
        },
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Test",
        wikidata_entity_id="q12345",
    )

    strategy.fetch(target, missing_fields=("biography",))

    assert fetched_qids == ["Q12345"]


def test_batch_fetch_wikipedia_summaries_maps_extracts_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "query": {
                    "redirects": [
                        {"from": "Nancy_Pelosi", "to": "Nancy Pelosi"},
                    ],
                    "pages": {
                        "1": {
                            "title": "Nancy Pelosi",
                            "extract": "Nancy Pelosi is an American politician.",
                            "fullurl": "https://en.wikipedia.org/wiki/Nancy_Pelosi",
                        },
                        "2": {
                            "title": "Chuck Schumer",
                            "extract": "Chuck Schumer is an American politician.",
                            "fullurl": "https://en.wikipedia.org/wiki/Chuck_Schumer",
                        },
                    },
                }
            }

    def _fake_get(_url: str, **kwargs: object) -> _Response:
        requests.append(kwargs["params"])
        return _Response()

    monkeypatch.setattr(wikipedia_bio_module.httpx, "get", _fake_get)

    summaries = batch_fetch_wikipedia_summaries(
        ["Nancy_Pelosi", "Chuck Schumer"],
        batch_size=50,
        inter_batch_delay=0.0,
    )

    assert requests == [
        {
            "action": "query",
            "prop": "extracts|info",
            "inprop": "url",
            "exintro": 1,
            "exlimit": "max",
            "explaintext": 1,
            "redirects": 1,
            "format": "json",
            "titles": "Nancy_Pelosi|Chuck Schumer",
        }
    ]
    assert summaries["Nancy_Pelosi"]["extract"] == "Nancy Pelosi is an American politician."
    assert summaries["Nancy_Pelosi"]["content_urls"] == {
        "desktop": {"page": "https://en.wikipedia.org/wiki/Nancy_Pelosi"}
    }
    assert summaries["Chuck Schumer"]["extract"] == "Chuck Schumer is an American politician."


def test_batch_fetch_wikipedia_summaries_follows_extract_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []
    responses = iter(
        [
            {
                "continue": {"excontinue": 1, "continue": "||info"},
                "query": {
                    "pages": {
                        "1": {
                            "title": "First Member",
                            "extract": "First member biography.",
                            "fullurl": "https://en.wikipedia.org/wiki/First_Member",
                        }
                    }
                },
            },
            {
                "query": {
                    "pages": {
                        "2": {
                            "title": "Second Member",
                            "extract": "Second member biography.",
                            "fullurl": "https://en.wikipedia.org/wiki/Second_Member",
                        }
                    }
                }
            },
        ]
    )

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return next(responses)

    def _fake_get(_url: str, **kwargs: object) -> _Response:
        requests.append(dict(kwargs["params"]))
        return _Response()

    monkeypatch.setattr(wikipedia_bio_module.httpx, "get", _fake_get)

    summaries = batch_fetch_wikipedia_summaries(
        ["First Member", "Second Member"],
        batch_size=50,
        inter_batch_delay=0.0,
    )

    assert len(requests) == 2
    assert requests[1]["excontinue"] == 1
    assert requests[1]["continue"] == "||info"
    assert summaries["First Member"]["extract"] == "First member biography."
    assert summaries["Second Member"]["extract"] == "Second member biography."


def test_batch_fetch_wikipedia_summaries_preserves_extracts_across_repeated_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            {
                "continue": {"excontinue": 1, "continue": "||info"},
                "query": {
                    "pages": {
                        "1": {
                            "title": "First Member",
                            "extract": "First member biography.",
                            "fullurl": "https://en.wikipedia.org/wiki/First_Member",
                        },
                        "2": {
                            "title": "Second Member",
                            "fullurl": "https://en.wikipedia.org/wiki/Second_Member",
                        },
                    }
                },
            },
            {
                "query": {
                    "pages": {
                        "1": {
                            "title": "First Member",
                            "fullurl": "https://en.wikipedia.org/wiki/First_Member",
                        },
                        "2": {
                            "title": "Second Member",
                            "extract": "Second member biography.",
                            "fullurl": "https://en.wikipedia.org/wiki/Second_Member",
                        },
                    }
                },
            },
        ]
    )

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return next(responses)

    monkeypatch.setattr(wikipedia_bio_module.httpx, "get", lambda *_args, **_kwargs: _Response())

    summaries = batch_fetch_wikipedia_summaries(
        ["First Member", "Second Member"],
        batch_size=2,
        inter_batch_delay=0.0,
    )

    assert summaries["First Member"]["extract"] == "First member biography."
    assert summaries["Second Member"]["extract"] == "Second member biography."


def test_batch_fetch_wikipedia_titles_keeps_successful_batches_when_later_batch_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _fake_fetch_titles_batch(qids: list[str], *, timeout_seconds: float) -> dict[str, str]:
        calls.append(qids)
        if qids == ["Q3"]:
            request = httpx.Request("GET", "https://www.wikidata.org/w/api.php")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return {qid: f"Title {qid}" for qid in qids}

    monkeypatch.setattr(wikipedia_bio_module, "_fetch_titles_batch", _fake_fetch_titles_batch)

    titles = batch_fetch_wikipedia_titles(["Q1", "Q2", "Q3"], batch_size=2, inter_batch_delay=0.0)

    assert calls == [["Q1", "Q2"], ["Q3"]]
    assert titles == {"Q1": "Title Q1", "Q2": "Title Q2"}


def test_batch_fetch_wikipedia_summaries_keeps_successful_batches_when_later_batch_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _fake_fetch_summaries_batch(titles: list[str], *, timeout_seconds: float) -> dict[str, dict[str, object]]:
        calls.append(titles)
        if titles == ["Title Q3"]:
            request = httpx.Request("GET", "https://en.wikipedia.org/w/api.php")
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return {title: {"extract": f"Extract {title}"} for title in titles}

    monkeypatch.setattr(wikipedia_bio_module, "_fetch_summaries_batch", _fake_fetch_summaries_batch)

    summaries = batch_fetch_wikipedia_summaries(
        ["Title Q1", "Title Q2", "Title Q3"], batch_size=2, inter_batch_delay=0.0
    )

    assert calls == [["Title Q1", "Title Q2"], ["Title Q3"]]
    assert summaries == {
        "Title Q1": {"extract": "Extract Title Q1"},
        "Title Q2": {"extract": "Extract Title Q2"},
    }
