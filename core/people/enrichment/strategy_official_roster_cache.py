from __future__ import annotations

from typing import Any

from core import db
from core.people.enrichment.models import (
    CandidateEnrichmentRecord,
    CandidateEnrichmentStrategy,
    CandidateEnrichmentTarget,
    EnrichmentAttempt,
    PortraitBinaryMetadata,
)

ROSTER_CACHE_PORTRAIT_REUSE_METADATA_KEY = "portrait_reuse"
ROSTER_CACHE_PORTRAIT_REUSE_METADATA_VALUE = "active_roster_cache"


class OfficialRosterCacheStrategy(CandidateEnrichmentStrategy):
    """Read-only enrichment strategy that reuses active roster-sourced portraits."""

    source_name = "official_roster_cache"

    def __init__(self, *, conn: Any | None) -> None:
        self._conn = conn

    def fetch(
        self,
        target: CandidateEnrichmentTarget,
        missing_fields: tuple[str, ...],
    ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        """Return a portrait record only when a resolved roster-sourced portrait exists."""
        if target.person_id is None or self._conn is None:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

        cached_portrait = db.select_active_roster_portrait_for_person(
            self._conn,
            person_id=target.person_id,
        )
        if cached_portrait is None:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

        portrait_metadata = _portrait_binary_metadata_from_cached_portrait(cached_portrait)
        if portrait_metadata is None:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

        record = CandidateEnrichmentRecord(
            portrait_image_url=portrait_metadata.source_image_url,
            portrait_metadata=portrait_metadata,
        )
        contributed_fields = ("portrait_image_url",) if "portrait_image_url" in missing_fields else ()
        return record, EnrichmentAttempt.success(
            source=self.source_name,
            requested_fields=missing_fields,
            contributed_fields=contributed_fields,
        ).model_copy(
            update={
                "metadata": {
                    ROSTER_CACHE_PORTRAIT_REUSE_METADATA_KEY: ROSTER_CACHE_PORTRAIT_REUSE_METADATA_VALUE,
                }
            }
        )


def _portrait_binary_metadata_from_cached_portrait(cached_portrait: Any) -> PortraitBinaryMetadata | None:
    """Lift the DB portrait row into enrichment-side metadata only for reusable active rows."""
    if cached_portrait.status != "active":
        return None
    if (
        cached_portrait.mime_type in (None, "")
        or cached_portrait.width_px is None
        or cached_portrait.height_px is None
        or cached_portrait.source_image_url in (None, "")
    ):
        return None
    return PortraitBinaryMetadata(
        image_hash=cached_portrait.image_hash,
        mime_type=cached_portrait.mime_type,
        width_px=cached_portrait.width_px,
        height_px=cached_portrait.height_px,
        source_image_url=cached_portrait.source_image_url,
    )
