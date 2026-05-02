from __future__ import annotations

from dataclasses import dataclass

from core.people.enrichment.models import CandidateEnrichmentRecord, CandidateEnrichmentTarget, EnrichmentAttempt
from core.people.enrichment.strategy_chain import StrategyChain


@dataclass
class _FakeStrategy:
    source_name: str
    record: CandidateEnrichmentRecord
    expected_missing_fields: tuple[str, ...] | None = None
    call_count: int = 0

    def fetch(self, target: CandidateEnrichmentTarget, missing_fields: tuple[str, ...]) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        self.call_count += 1
        if self.expected_missing_fields is not None:
            assert missing_fields == self.expected_missing_fields
        return self.record, EnrichmentAttempt.success(source=self.source_name)



def test_chain_short_circuits_when_sboe_record_is_complete() -> None:
    target = CandidateEnrichmentTarget(canonical_name="Jane Doe")
    sboe_record = CandidateEnrichmentRecord(
        occupation="Attorney",
        education="UNC",
        biography="State profile",
        portrait_image_url="https://example.org/sboe.jpg",
        campaign_website_url="https://jane.example.org",
        wikipedia_url="https://en.wikipedia.org/wiki/Jane_Doe",
    )
    sboe = _FakeStrategy(source_name="sboe", record=sboe_record)
    ballotpedia = _FakeStrategy(source_name="ballotpedia", record=CandidateEnrichmentRecord())
    wikidata = _FakeStrategy(source_name="wikidata", record=CandidateEnrichmentRecord())
    campaign_site = _FakeStrategy(source_name="campaign_site", record=CandidateEnrichmentRecord())

    result = StrategyChain((sboe, ballotpedia, wikidata, campaign_site)).enrich(target)

    assert result.biography == "State profile"
    assert result.field_provenance["biography"] == "sboe"
    assert sboe.call_count == 1
    assert ballotpedia.call_count == 0
    assert wikidata.call_count == 0
    assert campaign_site.call_count == 0


def test_chain_falls_through_with_only_missing_fields() -> None:
    target = CandidateEnrichmentTarget(canonical_name="Taylor Smith")
    sboe = _FakeStrategy(
        source_name="sboe",
        record=CandidateEnrichmentRecord(biography="SBoE biography"),
    )
    ballotpedia = _FakeStrategy(
        source_name="ballotpedia",
        expected_missing_fields=("occupation", "education", "portrait_image_url", "campaign_website_url", "wikipedia_url"),
        record=CandidateEnrichmentRecord(portrait_image_url="https://images.example.org/portrait.jpg"),
    )
    wikidata = _FakeStrategy(
        source_name="wikidata",
        expected_missing_fields=("occupation", "education", "campaign_website_url", "wikipedia_url"),
        record=CandidateEnrichmentRecord(wikipedia_url="https://en.wikipedia.org/wiki/Taylor_Smith"),
    )
    campaign_site = _FakeStrategy(
        source_name="campaign_site",
        expected_missing_fields=("occupation", "education", "campaign_website_url"),
        record=CandidateEnrichmentRecord(campaign_website_url="https://taylorsmith.example.com"),
    )

    result = StrategyChain((sboe, ballotpedia, wikidata, campaign_site)).enrich(target)

    assert result.biography == "SBoE biography"
    assert result.portrait_image_url == "https://images.example.org/portrait.jpg"
    assert result.wikipedia_url == "https://en.wikipedia.org/wiki/Taylor_Smith"
    assert result.campaign_website_url == "https://taylorsmith.example.com"
    assert result.field_provenance == {
        "biography": "sboe",
        "portrait_image_url": "ballotpedia",
        "wikipedia_url": "wikidata",
        "campaign_website_url": "campaign_site",
    }
    assert [attempt.source for attempt in result.attempts] == ["sboe", "ballotpedia", "wikidata", "campaign_site"]


def test_default_chain_uses_expected_strategy_order() -> None:
    chain = StrategyChain.default()
    assert [strategy.source_name for strategy in chain._strategies] == [
        "official_roster_cache",
        "official_bio",
        "sboe",
        "ballotpedia",
        "wikidata",
        "campaign_site",
    ]


def test_default_chain_roster_cache_hit_removes_portrait_field_from_downstream_requests(
    monkeypatch,
) -> None:
    constructed_conn: list[object] = []
    observed_missing_fields: dict[str, tuple[str, ...]] = {}

    class _FakeOfficialRosterCacheStrategy:
        source_name = "official_roster_cache"

        def __init__(self, *, conn: object | None = None) -> None:
            constructed_conn.append(conn if conn is not None else object())

        def fetch(
            self,
            target: CandidateEnrichmentTarget,
            missing_fields: tuple[str, ...],
        ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
            observed_missing_fields[self.source_name] = missing_fields
            return (
                CandidateEnrichmentRecord(portrait_image_url="https://images.example.org/roster.jpg"),
                EnrichmentAttempt.success(
                    source=self.source_name,
                    requested_fields=missing_fields,
                    contributed_fields=("portrait_image_url",),
                ),
            )

    class _FakeSboeStrategy:
        source_name = "sboe"

        def fetch(
            self,
            target: CandidateEnrichmentTarget,
            missing_fields: tuple[str, ...],
        ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
            observed_missing_fields[self.source_name] = missing_fields
            return CandidateEnrichmentRecord(occupation="Teacher"), EnrichmentAttempt.success(
                source=self.source_name,
                requested_fields=missing_fields,
                contributed_fields=("occupation",),
            )

    class _FakeNoDataStrategy:
        def __init__(self, source_name: str) -> None:
            self.source_name = source_name

        def fetch(
            self,
            target: CandidateEnrichmentTarget,
            missing_fields: tuple[str, ...],
        ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
            observed_missing_fields[self.source_name] = missing_fields
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

    monkeypatch.setattr(
        "core.people.enrichment.strategy_chain.OfficialRosterCacheStrategy",
        _FakeOfficialRosterCacheStrategy,
    )
    monkeypatch.setattr(
        "core.people.enrichment.strategy_chain.SboeEnrichmentStrategy",
        _FakeSboeStrategy,
    )
    monkeypatch.setattr(
        "core.people.enrichment.strategy_chain.BallotpediaEnrichmentStrategy",
        lambda: _FakeNoDataStrategy("ballotpedia"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.strategy_chain.WikidataEnrichmentStrategy",
        lambda: _FakeNoDataStrategy("wikidata"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.strategy_chain.CampaignSiteEnrichmentStrategy",
        lambda: _FakeNoDataStrategy("campaign_site"),
    )

    conn_marker = object()
    result = StrategyChain.default(conn=conn_marker).enrich(CandidateEnrichmentTarget(canonical_name="Jordan Doe"))

    assert constructed_conn == [conn_marker]
    assert observed_missing_fields["official_roster_cache"] == (
        "occupation",
        "education",
        "biography",
        "portrait_image_url",
        "campaign_website_url",
        "wikipedia_url",
    )
    assert "portrait_image_url" not in observed_missing_fields["sboe"]
    assert "occupation" in observed_missing_fields["sboe"]
    assert result.portrait_image_url == "https://images.example.org/roster.jpg"
    assert result.occupation == "Teacher"


def test_default_chain_uses_strategy_default_fetchers_without_placeholder_errors(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "core.people.enrichment.strategy_sboe.SboeEnrichmentStrategy._fetch_from_http",
        lambda self, target, *, timeout_seconds: {},
    )
    monkeypatch.setattr(
        "core.people.enrichment.strategy_ballotpedia.BallotpediaEnrichmentStrategy._fetch_from_http",
        lambda self, target, *, timeout_seconds: {},
    )
    monkeypatch.setattr(
        "core.people.enrichment.strategy_wikidata.WikidataEnrichmentStrategy._fetch_from_http",
        lambda self, target, *, timeout_seconds: {},
    )
    result = StrategyChain.default().enrich(CandidateEnrichmentTarget(canonical_name="Jordan Doe"))
    attempt_by_source = {attempt.source: attempt for attempt in result.attempts}

    assert attempt_by_source["sboe"].status == "no_data"
    assert attempt_by_source["ballotpedia"].status == "no_data"
    assert attempt_by_source["wikidata"].status == "no_data"


def test_chain_merges_bio_companion_metadata_atomically() -> None:
    target = CandidateEnrichmentTarget(canonical_name="Taylor Smith")
    official_bio = _FakeStrategy(
        source_name="official_bio",
        record=CandidateEnrichmentRecord(
            biography="Taylor Smith grew up in Raleigh.",
            bio_source_url="https://www.ncleg.gov/Members/Biography/H/149",
            bio_license="public_domain",
        ),
    )

    result = StrategyChain((official_bio,)).enrich(target)

    assert result.biography == "Taylor Smith grew up in Raleigh."
    assert result.bio_source_url == "https://www.ncleg.gov/Members/Biography/H/149"
    assert result.bio_license == "public_domain"
    assert result.field_provenance["biography"] == "official_bio"
