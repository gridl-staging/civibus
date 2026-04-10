from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SourceInfo(BaseModel):
    domain: str
    jurisdiction: str | None = None
    data_source_name: str
    data_source_url: str
    source_record_key: str | None = None
    record_url: str | None = None
    pull_date: datetime
