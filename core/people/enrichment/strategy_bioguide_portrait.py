"""Bioguide portrait enrichment from unitedstates/images."""

from __future__ import annotations

from collections.abc import Callable

from core.people.enrichment.models import (
    CandidateEnrichmentRecord,
    CandidateEnrichmentTarget,
    EnrichmentAttempt,
)
from core.people.enrichment.strategy_shared import fetch_bytes_via_http, run_strategy_fetch

_BIOGUIDE_IMAGE_BASE_URL = "https://unitedstates.github.io/images/congress/450x550"
_MISSING_BIOGUIDE_SKIP_REASON = "missing_bioguide_id"


class BioguidePortraitStrategy:
    """Fetch federal portrait images by Bioguide ID from unitedstates/images."""

    source_name = "unitedstates/images"

    def __init__(
        self,
        *,
        portrait_fetcher: Callable[[str], bytes | None] | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._portrait_fetcher = portrait_fetcher or (
            lambda url: fetch_bytes_via_http(url, timeout_seconds=timeout_seconds)
        )

    def fetch(
        self,
        target: CandidateEnrichmentTarget,
        missing_fields: tuple[str, ...],
    ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        """Return a portrait record for targets with a usable Bioguide ID."""
        portrait_url = _bioguide_portrait_url(target.bioguide_id)
        if portrait_url is None:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.skipped(
                source=self.source_name,
                requested_fields=missing_fields,
                skip_reason=_MISSING_BIOGUIDE_SKIP_REASON,
            )

        return run_strategy_fetch(
            source_name=self.source_name,
            missing_fields=missing_fields,
            fetch_payload=lambda: {"portrait_image_url": portrait_url},
            fetch_portrait_bytes=self._portrait_fetcher,
            portrait_rights_status="public_domain",
        )


def _bioguide_portrait_url(bioguide_id: str | None) -> str | None:
    normalized_bioguide_id = _normalize_bioguide_id(bioguide_id)
    if normalized_bioguide_id is None:
        return None
    return f"{_BIOGUIDE_IMAGE_BASE_URL}/{normalized_bioguide_id}.jpg"


def _normalize_bioguide_id(bioguide_id: str | None) -> str | None:
    if bioguide_id is None:
        return None
    normalized_bioguide_id = bioguide_id.strip().upper()
    if normalized_bioguide_id == "":
        return None
    return normalized_bioguide_id
