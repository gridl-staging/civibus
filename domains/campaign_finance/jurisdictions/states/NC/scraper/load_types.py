from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import UUID

import psycopg

from core.types.python.models import Address, Organization, Person
from domains.campaign_finance.jurisdictions.states import load_utils as _shared_load_utils

_NCRowLoader = Callable[[psycopg.Connection, Mapping[str, str | None], UUID], bool]
LoadResult = _shared_load_utils.LoadResult


@dataclass(slots=True)
class NCTransactionsLoadResult(LoadResult):
    year_filtered: int = 0


@dataclass(slots=True)
class _NCLoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


# Public alias for shared loader callers outside this module.
NCLoadCounts = _NCLoadCounts


@dataclass(frozen=True, slots=True)
class _NCRowLoadConfig:
    load_row: _NCRowLoader
    row_type_label: str
    data_source_id: UUID


@dataclass(frozen=True, slots=True)
class _NCTransactionEntities:
    person: Person | None
    contributor_org: Organization | None
    committee: Organization
    address: Address | None


@dataclass(frozen=True, slots=True)
class NCFilingLookupEntry:
    filing_id: UUID
    filing_fec_id: str
    committee_id: UUID
    amendment_indicator: str
    source_record_id: UUID
