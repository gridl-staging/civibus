from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import UUID

import psycopg

from core.types.python.models import Address, Organization, Person

_GARowLoader = Callable[[psycopg.Connection, Mapping[str, object], UUID], bool]


@dataclass(slots=True)
class LoadResult:
    inserted: int
    skipped: int
    errors: int
    elapsed_seconds: float


@dataclass(slots=True)
class _GALoadCounts:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class _GARowLoadConfig:
    load_row: _GARowLoader
    row_type_label: str
    data_source_id: UUID


@dataclass(frozen=True, slots=True)
class _GATransactionEntities:
    person: Person | None
    organization: Organization | None
    committee: Organization
    candidate: Person | None
    address: Address | None


@dataclass(frozen=True, slots=True)
class _GATransactionRoles:
    person: str
    organization: str
    committee: str
    candidate: str
    address: str


@dataclass(frozen=True, slots=True)
class _GAFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    source_record_id: UUID
