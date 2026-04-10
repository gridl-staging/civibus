"""Pydantic models for Stage 3 state closeout evidence artifacts.

Mirrors the federal FEC closeout model structure but carries state-specific
evidence sections for CO, GA, and NC.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from domains.campaign_finance.quality.closeout_evidence_base import (
    CloseoutEvidenceMixin,
    utc_now,
)
from domains.campaign_finance.quality.models import QualityReport


class LoadResultSnapshot(BaseModel, extra="forbid"):
    """Portable snapshot of loader outcome counts."""

    inserted: int
    skipped: int
    quarantined: int | None = None
    superseded: int | None = None
    errors: int
    elapsed_seconds: float


class CoCloseoutSection(BaseModel, extra="forbid"):
    """Colorado-specific closeout evidence."""

    source_file: str
    raw_csv_row_count: int
    parser_skipped: int
    load_result: LoadResultSnapshot
    tracer_summary_notes: str | None = None


class GaCloseoutSection(BaseModel, extra="forbid"):
    """Georgia-specific closeout evidence."""

    source_file: str
    file_sha256: str
    file_byte_size: int
    query_candidate: str
    query_date_start: str
    query_date_end: str
    query_data_type: str
    load_result: LoadResultSnapshot
    portal_summary_notes: str | None = None


class NcCommitteeDocValidation(BaseModel, extra="forbid"):
    """Validation-only: committee-doc export was parsed but NOT loaded."""

    source_file: str
    file_sha256: str
    total_rows: int
    parse_skipped: int
    status: str = "validation_only"


class NcCloseoutSection(BaseModel, extra="forbid"):
    """North Carolina-specific closeout evidence."""

    transaction_source_file: str
    transaction_file_sha256: str
    transaction_file_byte_size: int
    acquisition_timestamp: str
    load_result: LoadResultSnapshot
    committee_doc_validation: NcCommitteeDocValidation | None = None


class StateCloseoutEvidence(CloseoutEvidenceMixin, BaseModel, extra="forbid"):
    """Structured state closeout artifact embedding the canonical QualityReport."""

    generated_at: datetime = Field(default_factory=utc_now)
    jurisdiction: str
    data_type: str
    data_source_id: str
    data_source_snapshot: dict[str, object] = Field(default_factory=dict)
    quality_report: QualityReport
    known_limitations: list[dict[str, object]] = Field(default_factory=list)
    co_evidence: CoCloseoutSection | None = None
    ga_evidence: GaCloseoutSection | None = None
    nc_evidence: NcCloseoutSection | None = None
