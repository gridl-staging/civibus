
from __future__ import annotations

from typing import Any

from core.people.enrichment.models import (
    CandidateEnrichmentRecord,
    CandidateEnrichmentStrategy,
    CandidateEnrichmentTarget,
)
from core.people.enrichment.strategy_ballotpedia import BallotpediaEnrichmentStrategy
from core.people.enrichment.strategy_bioguide_portrait import BioguidePortraitStrategy
from core.people.enrichment.strategy_campaign_site import CampaignSiteEnrichmentStrategy
from core.people.enrichment.strategy_official_bio import OfficialBioStrategy
from core.people.enrichment.strategy_official_roster_cache import OfficialRosterCacheStrategy
from core.people.enrichment.strategy_sboe import SboeEnrichmentStrategy
from core.people.enrichment.strategy_wikidata import WikidataEnrichmentStrategy
from core.people.enrichment.strategy_wikipedia_bio import WikipediaBioStrategy


class StrategyChain:
    """Deterministic source-priority merge chain for candidate enrichment."""

    def __init__(self, strategies: tuple[CandidateEnrichmentStrategy, ...]) -> None:
        self._strategies = strategies

    @classmethod
    def default(cls, *, conn: Any | None = None) -> StrategyChain:
        return cls(
            (
                OfficialRosterCacheStrategy(conn=conn),
                OfficialBioStrategy(),
                SboeEnrichmentStrategy(),
                BallotpediaEnrichmentStrategy(),
                WikidataEnrichmentStrategy(),
                CampaignSiteEnrichmentStrategy(),
            )
        )

    @classmethod
    def federal(cls, *, conn: Any | None = None) -> StrategyChain:
        return cls(
            (
                OfficialRosterCacheStrategy(conn=conn),
                WikipediaBioStrategy(),
                OfficialBioStrategy(),
                BioguidePortraitStrategy(),
            )
        )

    def enrich(self, target: CandidateEnrichmentTarget) -> CandidateEnrichmentRecord:
        merged_record = CandidateEnrichmentRecord()

        for strategy in self._strategies:
            missing_fields = self._requested_fields_for_strategy(merged_record, strategy=strategy)
            if not missing_fields:
                break

            partial_record, attempt = strategy.fetch(target, missing_fields)
            merged_fields = merged_record.merge_missing_fields(partial_record, source=strategy.source_name)

            if attempt.status == "succeeded" and not attempt.contributed_fields:
                attempt = attempt.model_copy(update={"contributed_fields": merged_fields})

            merged_record.add_attempt(attempt)

        return merged_record

    @staticmethod
    def _requested_fields_for_strategy(
        merged_record: CandidateEnrichmentRecord,
        *,
        strategy: CandidateEnrichmentStrategy,
    ) -> tuple[str, ...]:
        missing_fields = merged_record.missing_fields()
        # Once the roster cache has supplied an active portrait, downstream HTTP
        # strategies should only be asked for still-missing non-portrait fields.
        if strategy.source_name != OfficialRosterCacheStrategy.source_name and (
            merged_record.field_provenance.get("portrait_image_url") == OfficialRosterCacheStrategy.source_name
        ):
            return tuple(field_name for field_name in missing_fields if field_name != "portrait_image_url")
        return missing_fields
