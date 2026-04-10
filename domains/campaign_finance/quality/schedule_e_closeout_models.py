"""Pydantic models for Schedule E independent-expenditure closeout evidence."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from domains.campaign_finance.quality.closeout_evidence_base import (
    CloseoutEvidenceMixin,
    utc_now,
)
from domains.campaign_finance.quality.models import QualityReport


class ScheduleECloseoutEvidence(CloseoutEvidenceMixin, BaseModel, extra="forbid"):
    """Closeout artifact for Schedule E quality verification.

    Lighter than FecCloseoutEvidence — Schedule E closeout validates
    already-loaded data rather than orchestrating a full ingest cycle.
    """

    generated_at: datetime = Field(default_factory=utc_now)
    cycle: int
    jurisdiction: str = "federal/fec"
    data_source_id: str
    source_record_count: int
    quality_report: QualityReport
    known_limitations: list[dict[str, object]] = Field(default_factory=list)
