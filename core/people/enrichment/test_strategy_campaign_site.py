from __future__ import annotations

import json
from pathlib import Path

from core.people.enrichment.models import CandidateEnrichmentTarget
from core.people.enrichment.strategy_campaign_site import CampaignSiteEnrichmentStrategy


def _fixture(name: str) -> dict[str, object]:
    fixture_path = Path(__file__).with_name("test_fixtures") / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_campaign_site_strategy_extracts_expected_fields() -> None:
    strategy = CampaignSiteEnrichmentStrategy(http_fetcher=lambda _url: _fixture("campaign_site_success.json"))

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(
            canonical_name="Jamie Chen", verified_campaign_site_url="https://jamiechen.example.com"
        ),
        missing_fields=("biography", "campaign_website_url"),
    )

    assert attempt.status == "succeeded"
    assert record.biography == "Jamie Chen is focused on transit and school funding."
    assert record.campaign_website_url == "https://jamiechen.example.com"


def test_campaign_site_strategy_returns_no_data_attempt() -> None:
    strategy = CampaignSiteEnrichmentStrategy(http_fetcher=lambda _url: _fixture("campaign_site_no_data.json"))

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="No Site", verified_campaign_site_url="https://nosite.example.com"),
        missing_fields=("biography",),
    )

    assert record == record.__class__()
    assert attempt.status == "no_data"


def test_campaign_site_strategy_treats_blank_verified_url_as_no_data() -> None:
    strategy = CampaignSiteEnrichmentStrategy(http_fetcher=lambda _url: _fixture("campaign_site_success.json"))

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Blank Site", verified_campaign_site_url="   "),
        missing_fields=("biography",),
    )

    assert record == record.__class__()
    assert attempt.status == "no_data"
