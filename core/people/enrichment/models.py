

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ENRICHMENT_FIELDS: tuple[str, ...] = (
    "occupation",
    "education",
    "biography",
    "portrait_image_url",
    "campaign_website_url",
    "wikipedia_url",
)


PortraitQaStatus = Literal["active", "not_found", "too_small", "face_too_small", "rejected"]


class PortraitBinaryMetadata(BaseModel):
    """Deterministic binary metadata extracted from fetched portrait bytes."""

    model_config = ConfigDict(extra="forbid")

    image_hash: str
    mime_type: str
    width_px: int
    height_px: int
    source_image_url: str


class CandidateEnrichmentTarget(BaseModel):
    """Input target identity used by source-specific enrichment strategies."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    person_id: UUID | None = None
    state_code: str | None = None
    district: str | None = None
    sboe_candidate_id: str | None = None
    ballotpedia_url: str | None = None
    wikidata_entity_id: str | None = None
    verified_campaign_site_url: str | None = None
    roster_bio_url: str | None = None


class EnrichmentAttempt(BaseModel):
    """Structured per-source attempt metadata for later persistence."""

    model_config = ConfigDict(extra="forbid")

    source: str
    status: Literal["succeeded", "no_data", "skipped", "failed"]
    requested_fields: tuple[str, ...] = ()
    contributed_fields: tuple[str, ...] = ()
    skip_reason: str | None = None
    error_message: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    portrait_status: PortraitQaStatus | None = None
    portrait_metadata: PortraitBinaryMetadata | None = None

    @classmethod
    def success(
        cls,
        *,
        source: str,
        requested_fields: tuple[str, ...] = (),
        contributed_fields: tuple[str, ...] = (),
    ) -> EnrichmentAttempt:
        return cls(
            source=source,
            status="succeeded",
            requested_fields=requested_fields,
            contributed_fields=contributed_fields,
        )

    @classmethod
    def no_data(cls, *, source: str, requested_fields: tuple[str, ...] = ()) -> EnrichmentAttempt:
        return cls(source=source, status="no_data", requested_fields=requested_fields)

    @classmethod
    def skipped(
        cls,
        *,
        source: str,
        requested_fields: tuple[str, ...] = (),
        skip_reason: str,
    ) -> EnrichmentAttempt:
        return cls(
            source=source,
            status="skipped",
            requested_fields=requested_fields,
            skip_reason=skip_reason,
        )

    @classmethod
    def failed(
        cls,
        *,
        source: str,
        requested_fields: tuple[str, ...] = (),
        error_message: str,
    ) -> EnrichmentAttempt:
        return cls(
            source=source,
            status="failed",
            requested_fields=requested_fields,
            error_message=error_message,
        )


class CandidateEnrichmentRecord(BaseModel):
    """Merged enrichment output and field-level provenance."""

    model_config = ConfigDict(extra="forbid")

    occupation: str | None = None
    education: str | None = None
    biography: str | None = None
    bio_source_url: str | None = None
    bio_license: str | None = None
    portrait_image_url: str | None = None
    campaign_website_url: str | None = None
    wikipedia_url: str | None = None
    portrait_metadata: PortraitBinaryMetadata | None = None
    field_provenance: dict[str, str] = Field(default_factory=dict)
    attempts: list[EnrichmentAttempt] = Field(default_factory=list)

    def missing_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        for field_name in ENRICHMENT_FIELDS:
            value = getattr(self, field_name)
            if value is None or value == "":
                missing.append(field_name)
        return tuple(missing)

    def is_complete(self) -> bool:
        return len(self.missing_fields()) == 0

    def merge_missing_fields(
        self,
        incoming: CandidateEnrichmentRecord,
        *,
        source: str,
    ) -> tuple[str, ...]:
        merged_fields: list[str] = []
        for field_name in ENRICHMENT_FIELDS:
            current_value = getattr(self, field_name)
            if current_value not in (None, ""):
                continue

            incoming_value = getattr(incoming, field_name)
            if incoming_value in (None, ""):
                continue

            setattr(self, field_name, incoming_value)
            self.field_provenance[field_name] = source
            merged_fields.append(field_name)

        if self.portrait_metadata is None and incoming.portrait_metadata is not None:
            if self.portrait_image_url in (None, "", incoming.portrait_metadata.source_image_url):
                self.portrait_metadata = incoming.portrait_metadata

        # Biography provenance metadata is companion state for biography itself.
        # It should move atomically only when biography is newly merged.
        if "biography" in merged_fields:
            self.bio_source_url = incoming.bio_source_url
            self.bio_license = incoming.bio_license

        return tuple(merged_fields)

    def add_attempt(self, attempt: EnrichmentAttempt) -> None:
        self.attempts.append(attempt)


class CandidateEnrichmentStrategy(Protocol):
    source_name: str

    def fetch(
        self,
        target: CandidateEnrichmentTarget,
        missing_fields: tuple[str, ...],
    ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        ...


JsonLikeMapping = Mapping[str, object]
