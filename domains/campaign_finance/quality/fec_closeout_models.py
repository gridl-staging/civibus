"""Pydantic models for Stage 2 federal FEC closeout evidence artifacts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from domains.campaign_finance.quality.closeout_evidence_base import (
    CloseoutEvidenceMixin,
    utc_now,
)
from domains.campaign_finance.quality.models import QualityReport


class FecIngestStepSummary(BaseModel, extra="forbid"):
    """Per-file ingest summary for one full-cycle phase."""

    file_type: str
    source_path: str
    baseline_url: str
    inserted: int
    skipped: int
    errors: int
    elapsed_seconds: float


class FecIngestMetadata(BaseModel, extra="forbid"):
    """Metadata snapshot persisted on core.data_source."""

    record_count: int
    last_pull_status: str
    last_pull_at: datetime | None


class FecCloseoutEvidence(CloseoutEvidenceMixin, BaseModel, extra="forbid"):
    """Structured closeout artifact embedding the canonical QualityReport contract."""

    generated_at: datetime = Field(default_factory=utc_now)
    cycle: int
    jurisdiction: str
    data_source_id: str
    transaction_limit: int | None = None
    baseline_urls: dict[str, str] = Field(default_factory=dict)
    scoped_table_counts: dict[str, int] = Field(default_factory=dict)
    ingest_steps: list[FecIngestStepSummary] = Field(default_factory=list)
    ingest_metadata: FecIngestMetadata
    quality_report: QualityReport
    known_limitations: list[dict[str, object]] = Field(default_factory=list)
