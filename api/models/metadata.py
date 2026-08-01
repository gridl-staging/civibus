from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class DataSourceMetadataResponse(BaseModel):
    data_source_id: UUID
    domain: str
    jurisdiction: str | None = None
    name: str
    source_url: str
    update_frequency: str | None = None
    last_pull_at: datetime | None = None
    last_pull_status: str | None = None
    record_count: int | None = None
    latest_source_record_id: UUID | None = None
    latest_source_record_key: str | None = None
    latest_source_record_url: str | None = None
    latest_source_pull_date: datetime | None = None


class CoverageRegistryResponse(BaseModel):
    domain: str
    jurisdiction: str | None = None
    data_source_count: int
    latest_data_source_pull_at: datetime | None = None
    latest_source_pull_date: datetime | None = None


class PublicRateLimitPolicy(BaseModel):
    """The effective per-client request limit published on the public surface."""

    max_requests: int
    window_seconds: int


class PublicEmployerIndustryCoverage(BaseModel):
    """Fixed industry-classification benchmark for contributor employers.

    ``sampled_coverage_percentage`` is derived from the two counts, so the ratio
    can never drift from ``classified_count`` and ``unknown_count``.
    """

    classified_count: int
    unknown_count: int
    sampled_coverage_percentage: Decimal


class PublicFederalCoverage(BaseModel):
    """Honest qualifications on the federal-first coverage the public surface serves."""

    current_officeholder_count: int
    officeholder_denominator_is_fixed: bool
    employer_industry: PublicEmployerIndustryCoverage
    donor_identity_resolution: str


class PublicFederalMetadataResponse(BaseModel):
    """Machine-readable freshness, request-limit, and coverage contract."""

    data_sources: list[DataSourceMetadataResponse]
    rate_limit: PublicRateLimitPolicy
    coverage: PublicFederalCoverage
