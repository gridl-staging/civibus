"""
Stub summary for jun04_3pm_3_member_photo_bio_enrichment/civibus_dev/api/models/entities.py.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from api.models.provenance import SourceInfo


class PersonPortraitResponse(BaseModel):
    status: str
    rights_status: str
    source_image_url: str | None = None
    mime_type: str | None = None
    width_px: int | None = None
    height_px: int | None = None


class CurrentOfficeResponse(BaseModel):
    officeholding_id: UUID
    office_id: UUID
    office_name: str
    office_level: str
    state: str | None = None


class PersonCandidacyResponse(BaseModel):
    """One race a person is a candidate in, with linkable contest identity.

    Backed by ``fetch_candidacies_for_person`` (api/queries/civics.py), which
    resolves through BOTH ``civic.candidacy.person_id`` and the person's
    ``cf.candidate.fec_candidate_id`` rows — the shadow-person join rule
    (civibus-x8b). ``fec_candidate_id`` is the candidacy's source-assigned
    ``candidate_number``; it may be null for non-FEC candidacies.
    """

    candidacy_id: UUID
    contest_id: UUID
    contest_name: str
    election_date: date | None = None
    election_type: str
    office_id: UUID
    office_name: str
    office_level: str
    party: str | None = None
    status: str | None = None
    incumbent_challenge: str | None = None
    fec_candidate_id: str | None = None


class PersonResponse(BaseModel):
    id: UUID
    canonical_name: str
    name_variants: list[str] = Field(default_factory=list)
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    suffix: str | None = None
    occupation: str | None = None
    education: str | None = None
    bio_text: str | None = None
    bio_source_url: str | None = None
    bio_license: str | None = None
    bio_pulled_at: datetime | None = None
    date_of_birth: date | None = None
    year_of_birth: int | None = None
    identifiers: dict[str, str | list[str]] = Field(default_factory=dict)
    primary_address_id: UUID | None = None
    er_cluster_id: UUID | None = None
    er_confidence: float | None = None
    portrait: PersonPortraitResponse | None = None
    current_office: CurrentOfficeResponse | None = None
    # The races this person is a candidate in, nearest election first
    # (civibus-x8b). Empty list — never omitted — when no candidacy resolves.
    candidacies: list[PersonCandidacyResponse] = Field(default_factory=list)
    sources: list[SourceInfo]


class PersonSlugResult(BaseModel):
    id: UUID
    canonical_name: str
    first_name: str | None = None
    last_name: str | None = None
    suffix: str | None = None


class OrgResponse(BaseModel):
    id: UUID
    canonical_name: str
    name_variants: list[str] = Field(default_factory=list)
    org_type: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    registered_state: str | None = None
    formation_date: date | None = None
    dissolution_date: date | None = None
    primary_address_id: UUID | None = None
    er_cluster_id: UUID | None = None
    er_confidence: float | None = None
    sources: list[SourceInfo]
