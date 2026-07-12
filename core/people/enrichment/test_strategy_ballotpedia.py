from __future__ import annotations

import json
from pathlib import Path

from core.people.enrichment.models import CandidateEnrichmentTarget
from core.people.enrichment.strategy_ballotpedia import (
    BallotpediaEnrichmentStrategy,
    _ballotpedia_url_for_target,
    _extract_payload_from_html,
)


def _fixture(name: str) -> dict[str, object]:
    fixture_path = Path(__file__).with_name("test_fixtures") / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_ballotpedia_strategy_extracts_expected_fields() -> None:
    strategy = BallotpediaEnrichmentStrategy(fetcher=lambda _target: _fixture("ballotpedia_success.json"))

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Alex Rivera"), missing_fields=("biography", "wikipedia_url")
    )

    assert attempt.status == "succeeded"
    assert record.biography == "Alex Rivera served on the county board before running statewide."
    assert record.wikipedia_url == "https://en.wikipedia.org/wiki/Alex_Rivera"


def test_ballotpedia_strategy_returns_no_data_attempt() -> None:
    strategy = BallotpediaEnrichmentStrategy(fetcher=lambda _target: _fixture("ballotpedia_no_data.json"))

    record, attempt = strategy.fetch(CandidateEnrichmentTarget(canonical_name="No Page"), missing_fields=("biography",))

    assert record == record.__class__()
    assert attempt.status == "no_data"


def test_ballotpedia_policy_guard_skips_when_robots_disallow() -> None:
    strategy = BallotpediaEnrichmentStrategy(
        fetcher=lambda _target: _fixture("ballotpedia_success.json"),
        policy_guard=lambda _target: (False, "robots-disallow:/Candidate:Alex_Rivera"),
    )

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Alex Rivera"), missing_fields=("biography",)
    )

    assert record == record.__class__()
    assert attempt.status == "skipped"
    assert attempt.skip_reason == "robots-disallow:/Candidate:Alex_Rivera"


def test_ballotpedia_url_defaults_to_name_slug() -> None:
    target = CandidateEnrichmentTarget(canonical_name="Alex Rivera")
    assert _ballotpedia_url_for_target(target) == "https://ballotpedia.org/Alex_Rivera"


def test_extract_payload_from_html_reads_og_image_and_first_paragraph() -> None:
    html = """
    <html>
      <head>
        <title>Alex Rivera - Ballotpedia</title>
        <meta property="og:image" content="https://images.example.org/alex-rivera.jpg" />
      </head>
      <body>
        <p>Alex Rivera served on the county board before running statewide.</p>
        <p>Second paragraph should not be needed.</p>
      </body>
    </html>
    """

    payload = _extract_payload_from_html(html, canonical_name="Alex Rivera")

    assert payload == {
        "portrait_image_url": "https://images.example.org/alex-rivera.jpg",
        "biography": "Alex Rivera served on the county board before running statewide.",
    }


def test_extract_payload_from_html_rejects_unrelated_title_or_boilerplate_paragraphs() -> None:
    html = """
    <html>
      <head>
        <title>Generic Contact Form - Ballotpedia</title>
        <meta property="og:image" content="https://images.example.org/generic.jpg" />
      </head>
      <body>
        <p>Email *</p>
        <p>Phone Number *</p>
      </body>
    </html>
    """

    assert _extract_payload_from_html(html, canonical_name="Alex Rivera") is None
