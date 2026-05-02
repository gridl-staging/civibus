from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from core.people.enrichment.models import CandidateEnrichmentTarget
from core.people.enrichment.strategy_official_bio import OfficialBioStrategy, _license_for_url


def _fixture_text(name: str) -> str:
    fixture_path = Path(__file__).with_name("test_fixtures") / name
    return fixture_path.read_text(encoding="utf-8")


def test_official_bio_strategy_happy_path_parse() -> None:
    strategy = OfficialBioStrategy(
        html_fetcher=lambda _url: _fixture_text("official_bio_happy.html"),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jordan Lee",
        roster_bio_url="https://www.ncleg.gov/Members/Biography/H/149",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "succeeded"
    assert record.biography == "Rep. Jordan Lee has served three terms and previously worked as a teacher."
    assert record.bio_source_url == "https://www.ncleg.gov/Members/Biography/H/149"
    assert record.bio_license == "public_domain"


def test_official_bio_strategy_missing_bio_block_returns_no_data() -> None:
    strategy = OfficialBioStrategy(
        html_fetcher=lambda _url: _fixture_text("official_bio_missing_block.html"),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jordan Lee",
        roster_bio_url="https://www.ncleg.gov/Members/Biography/H/149",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert record == record.__class__()
    assert attempt.status == "no_data"


def test_official_bio_strategy_unexpected_html_fallback_returns_no_data() -> None:
    strategy = OfficialBioStrategy(
        html_fetcher=lambda _url: _fixture_text("official_bio_unexpected_layout.html"),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jordan Lee",
        roster_bio_url="https://www.example.com/candidate/jordan",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert record == record.__class__()
    assert attempt.status == "no_data"


def test_official_bio_strategy_missing_url_returns_no_data_instead_of_throwing() -> None:
    strategy = OfficialBioStrategy(html_fetcher=lambda _url: "")

    record, attempt = strategy.fetch(CandidateEnrichmentTarget(canonical_name="Jordan Lee"), missing_fields=("biography",))

    assert record == record.__class__()
    assert attempt.status == "no_data"


def test_official_bio_strategy_rejects_non_allowlisted_bio_url_without_network_fetch() -> None:
    strategy = OfficialBioStrategy(
        html_fetcher=lambda _url: (_ for _ in ()).throw(AssertionError("fetcher should not be called")),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jordan Lee",
        roster_bio_url="https://169.254.169.254/latest/meta-data",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert record == record.__class__()
    assert attempt.status == "no_data"


def test_official_bio_strategy_transport_failure_returns_failed_attempt() -> None:
    strategy = OfficialBioStrategy(
        html_fetcher=lambda _url: (_ for _ in ()).throw(httpx.ConnectError("dns failure")),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jordan Lee",
        roster_bio_url="https://www.ncleg.gov/Members/Biography/H/149",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert record == record.__class__()
    assert attempt.status == "failed"
    assert attempt.source == "official_bio"
    assert attempt.error_message not in (None, "")


def test_official_bio_strategy_preserves_multi_paragraph_biographies() -> None:
    strategy = OfficialBioStrategy(
        html_fetcher=lambda _url: _fixture_text("official_bio_multi_paragraph.html"),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jordan Lee",
        roster_bio_url="https://www.ncleg.gov/Members/Biography/H/149",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert attempt.status == "succeeded"
    assert "three terms" in record.biography
    assert "UNC Chapel Hill" in record.biography
    assert "Appropriations and Education committees" in record.biography
    paragraphs = record.biography.split("\n\n")
    assert len(paragraphs) == 3, f"Expected 3 paragraphs, got {len(paragraphs)}: {record.biography!r}"


@pytest.mark.parametrize(
    ("url", "expected_license"),
    [
        ("https://www.ncleg.gov/Members/Biography/H/149", "public_domain"),
        ("https://www.house.gov/representatives/", "public_domain"),
        ("https://en.wikipedia.org/wiki/Jordan_Lee", "licensed"),
        ("https://ballotpedia.org/Jordan_Lee", "licensed"),
        ("https://jordanleeforcongress.com/about", "restricted"),
        ("https://electjordan.org/bio", "restricted"),
        ("https://votejordan.com/bio", "restricted"),
        ("https://www.example.com/candidate/jordan", "unknown"),
        ("https://linkedin.com/in/jordanlee", "unknown"),
    ],
)
def test_license_for_url_classifies_each_branch(url: str, expected_license: str) -> None:
    assert _license_for_url(url) == expected_license


def test_official_bio_strategy_http_5xx_failure_returns_failed_attempt() -> None:
    request = httpx.Request("GET", "https://www.ncleg.gov/Members/Biography/H/149")
    response = httpx.Response(503, request=request)
    strategy = OfficialBioStrategy(
        html_fetcher=lambda _url: (_ for _ in ()).throw(
            httpx.HTTPStatusError("server error", request=request, response=response)
        ),
    )
    target = CandidateEnrichmentTarget(
        canonical_name="Jordan Lee",
        roster_bio_url="https://www.ncleg.gov/Members/Biography/H/149",
    )

    record, attempt = strategy.fetch(target, missing_fields=("biography",))

    assert record == record.__class__()
    assert attempt.status == "failed"
    assert attempt.source == "official_bio"
    assert attempt.error_message not in (None, "")
