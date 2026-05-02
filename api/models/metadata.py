from __future__ import annotations

from datetime import datetime
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
