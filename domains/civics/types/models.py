
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, computed_field, field_validator

from core.types.python.models import (
    DatePrecisionLiteral,
    ValidDateRange,
    utc_now,
    validate_json_dictionary,
    validate_optional_state_code,
)


OfficeLevelLiteral = Literal[
    "federal",
    "state",
    "county",
    "municipal",
    "judicial",
    "school_board",
    "special_district",
]

DivisionTypeLiteral = Literal[
    "congressional_district",
    "state_legislative_upper",
    "state_legislative_lower",
    "county",
    "municipal",
    "judicial_district",
    "school_district",
    "special_district",
    "at_large",
    "statewide",
]

ElectionTypeLiteral = Literal[
    "general",
    "primary",
    "runoff",
    "special",
    "recall",
]

OfficeIncompleteDataStateLiteral = Literal[
    "no_officeholder",
    "no_active_contest",
]

OfficeholdingStatusLiteral = Literal[
    "elected",
    "appointed",
    "acting",
    "former",
]

JurisdictionScopeLiteral = Literal[
    "federal",
    "state",
    "county",
    "municipal",
    "judicial",
    "school_district",
    "special_district",
]

FilingDeadlineKindLiteral = Literal[
    "candidate_filing_open",
    "candidate_filing",
    "candidate_withdrawal",
    "ballot_access",
]

ReportingDisclosureKindLiteral = Literal[
    "periodic",
    "pre_election",
    "post_election",
    "special",
]


class CivicBaseModel(BaseModel):
    """Shared constructor policy for civic domain records."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def _normalize_timestamp_to_utc(cls, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must include timezone information")
        return timestamp.astimezone(timezone.utc)


class Office(CivicBaseModel):
    """A named governmental position (e.g., US House of Representatives, Governor)."""

    name: str = Field(min_length=1)
    office_level: OfficeLevelLiteral
    title: str | None = None
    jurisdiction_id: UUID | None = None
    state: str | None = None
    electoral_division_id: UUID | None = None
    is_elected: bool = True
    number_of_seats: int = Field(default=1, ge=1)
    source_record_id: UUID | None = None

    @field_validator("state")
    @classmethod
    def _validate_state(cls, value: str | None) -> str | None:
        return validate_optional_state_code(value, field_name="state")


class ElectoralDivision(CivicBaseModel):

    name: str = Field(min_length=1)
    division_type: DivisionTypeLiteral
    state: str | None = None
    district_number: str | None = None
    ocd_id: str | None = None
    # True for hierarchy-only grouping rows such as "wa_counties"; false for actual divisions.
    is_container: bool = False
    parent_id: UUID | None = None
    boundary_year: int | None = None
    geometry: dict[str, object] | None = None
    source_record_id: UUID | None = None

    @field_validator("state")
    @classmethod
    def _validate_state(cls, value: str | None) -> str | None:
        return validate_optional_state_code(value, field_name="state")

    @field_validator("ocd_id")
    @classmethod
    def _validate_ocd_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("ocd-division/"):
            raise ValueError("ocd_id must start with 'ocd-division/'")
        return value


class Contest(CivicBaseModel):
    """A specific race or ballot question in a specific election."""

    name: str = Field(min_length=1)
    election_date: date | None = None
    election_type: ElectionTypeLiteral
    office_id: UUID
    election_id: UUID | None = None
    electoral_division_id: UUID | None = None
    number_of_seats: int = Field(default=1, ge=1)
    filing_deadline: date | None = None
    is_partisan: bool = True
    # Loader-observed completeness signal: true means the contest exists but candidate roster is partial.
    candidate_list_incomplete: bool = False
    source_record_id: UUID | None = None


class Candidacy(CivicBaseModel):
    """A person's candidacy for a specific contest."""

    person_id: UUID
    contest_id: UUID
    party: str | None = None
    name_on_ballot: str | None = None
    is_unexpired_term: bool = False
    raw_fields: dict[str, object] = Field(default_factory=dict)
    committee_id: UUID | None = None
    filing_date: date | None = None
    status: str | None = None
    incumbent_challenge: str | None = None
    candidate_number: str | None = None
    name_on_ballot: str | None = None
    is_unexpired_term: bool = False
    raw_fields: dict[str, object] = Field(default_factory=dict)
    committee_id: UUID | None = None
    source_record_id: UUID | None = None

    @field_validator("name_on_ballot")
    @classmethod
    def _validate_name_on_ballot(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("name_on_ballot must not be blank")
        return value

    @field_validator("raw_fields", mode="before")
    @classmethod
    def _validate_raw_fields(cls, value: object) -> dict[str, object]:
        if value is None:
            return {}
        return validate_json_dictionary(value, field_name="candidacy.raw_fields")


class ContestResult(CivicBaseModel):
    """Historical result row for a contest and election date."""

    contest_id: UUID
    candidate_name_on_ballot: str = Field(min_length=1)
    election_date: date
    is_winner: bool = False
    source_record_id: UUID | None = None

    @field_validator("candidate_name_on_ballot")
    @classmethod
    def _validate_candidate_name_on_ballot(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("candidate_name_on_ballot must not be blank")
        return value


class Election(CivicBaseModel):
    """Canonical election event for a jurisdiction scope and cycle date."""

    jurisdiction_scope: JurisdictionScopeLiteral
    state: str | None = None
    county: str | None = None
    municipality: str | None = None
    election_date: date
    election_type: ElectionTypeLiteral
    # `election_type` names the election phase itself. `is_special` is a cross-cutting
    # qualifier and may be true for non-"special" phases (for example, a special primary).
    is_special: bool = False
    office_id: UUID | None = None
    electoral_division_id: UUID | None = None
    source_record_id: UUID | None = None

    @field_validator("state")
    @classmethod
    def _validate_state(cls, value: str | None) -> str | None:
        return validate_optional_state_code(value, field_name="state")


class FilingDeadline(CivicBaseModel):
    """Calendar deadlines tied to an election and optionally a division."""

    election_id: UUID
    office_id: UUID
    electoral_division_id: UUID | None = None
    jurisdiction_scope: JurisdictionScopeLiteral
    state: str | None = None
    county: str | None = None
    municipality: str | None = None
    deadline_date: date
    deadline_kind: FilingDeadlineKindLiteral
    source_record_id: UUID | None = None

    @field_validator("state")
    @classmethod
    def _validate_state(cls, value: str | None) -> str | None:
        return validate_optional_state_code(value, field_name="state")


class ReportingPeriod(CivicBaseModel):
    """Reporting period window and due date for an election."""

    election_id: UUID
    period_name: str = Field(min_length=1)
    period_start: date
    period_end: date
    report_due_date: date
    is_pre_election: bool = False
    is_post_election: bool = False
    disclosure_kind: ReportingDisclosureKindLiteral | None = None
    source_record_id: UUID | None = None

    @field_validator("period_end")
    @classmethod
    def _validate_period_end(
        cls,
        period_end: date,
        info: ValidationInfo,
    ) -> date:
        # Use sibling period_start when available to guarantee valid closed ranges.
        period_start = getattr(info, "data", {}).get("period_start")
        if period_start is not None and period_end < period_start:
            raise ValueError("period_end must be on or after period_start")
        return period_end


class Officeholding(CivicBaseModel):
    """Time-bounded record of who holds a governmental office."""

    person_id: UUID
    office_id: UUID
    electoral_division_id: UUID | None = None
    holder_status: OfficeholdingStatusLiteral = "elected"
    valid_period: ValidDateRange = Field(default_factory=ValidDateRange)
    date_precision: DatePrecisionLiteral = "day"
    source_record_id: UUID | None = None


class OfficeRosterLink(CivicBaseModel):
    """Canonical bridge between a civic office and its roster data source."""

    office_id: UUID
    data_source_id: UUID


class OfficeBrowseStatus(BaseModel):
    """Derived browse status for a known office based on presence of linked rows."""

    model_config = ConfigDict(extra="forbid")

    office_id: UUID
    has_officeholder: bool = True
    has_active_contest: bool = True

    @computed_field(return_type=tuple[OfficeIncompleteDataStateLiteral, ...])
    @property
    def incomplete_data_states(self) -> tuple[OfficeIncompleteDataStateLiteral, ...]:
        missing_states: list[OfficeIncompleteDataStateLiteral] = []
        if not self.has_officeholder:
            missing_states.append("no_officeholder")
        if not self.has_active_contest:
            missing_states.append("no_active_contest")
        return tuple(missing_states)
