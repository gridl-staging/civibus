
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.types.python.models import DatePrecisionLiteral, ValidDateRange


FEC_COMMITTEE_ID_REGEX = r"^C\d{8}$"
FEC_CANDIDATE_ID_REGEX = r"^[HSP]\d[A-Z0-9]{2}\d{5}$"
JurisdictionTypeLiteral = Literal["federal", "state", "other"]
IncumbentChallengeLiteral = Literal["I", "C", "O"]
AmendmentIndicatorLiteral = Literal["N", "A", "T"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CampaignFinanceBaseModel(BaseModel):
    """Shared constructor policy for domain records.

    Policy: `id`, `created_at`, and `updated_at` default in Python when omitted.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def _normalize_timestamp_to_utc(cls, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must include timezone information")
        return timestamp.astimezone(timezone.utc)


class CommitteeType(str, Enum):

    COMMUNICATION_COST = "C"
    DELEGATE_COMMITTEE = "D"
    ELECTIONEERING_COMMUNICATION = "E"
    HOUSE_CAMPAIGN = "H"
    INDEPENDENT_EXPENDITOR = "I"
    PAC_NONQUALIFIED = "N"
    SUPER_PAC = "O"
    PRESIDENTIAL_CAMPAIGN = "P"
    PAC_QUALIFIED = "Q"
    SENATE_CAMPAIGN = "S"
    SINGLE_CANDIDATE_INDEPENDENT_EXPENDITURE = "U"
    PAC_NONCONTRIBUTION_NONQUALIFIED = "V"
    PAC_NONCONTRIBUTION_QUALIFIED = "W"
    PARTY_NONQUALIFIED = "X"
    PARTY_QUALIFIED = "Y"
    NATIONAL_PARTY_NONFEDERAL_ACCOUNT = "Z"


class OfficeType(str, Enum):
    HOUSE = "H"
    SENATE = "S"
    PRESIDENT = "P"


class Committee(CampaignFinanceBaseModel):
    fec_committee_id: str = Field(pattern=FEC_COMMITTEE_ID_REGEX)
    name: str
    organization_id: Optional[UUID] = None
    committee_type: Optional[CommitteeType] = None
    committee_designation: Optional[str] = None
    party: Optional[str] = None
    state: Optional[str] = Field(default=None, min_length=2, max_length=2)
    city: Optional[str] = None
    zip_code: Optional[str] = None
    treasurer_name: Optional[str] = None
    source_record_id: Optional[UUID] = None


class Candidate(CampaignFinanceBaseModel):

    fec_candidate_id: str = Field(pattern=FEC_CANDIDATE_ID_REGEX)
    name: str
    person_id: Optional[UUID] = None
    party: Optional[str] = None
    office: OfficeType
    state: Optional[str] = Field(default=None, min_length=2, max_length=2)
    district: Optional[str] = Field(default=None, min_length=2, max_length=2)
    incumbent_challenge: Optional[IncumbentChallengeLiteral] = None
    principal_committee_id: Optional[UUID] = None
    source_record_id: Optional[UUID] = None

    @model_validator(mode="after")
    def _validate_office_prefix_matches_office(self) -> Candidate:
        candidate_id_office_prefix = self.fec_candidate_id[0]
        if candidate_id_office_prefix != self.office.value:
            raise ValueError("fec_candidate_id prefix must match office")
        return self


class Filing(CampaignFinanceBaseModel):

    filing_fec_id: str
    committee_id: UUID
    candidate_id: Optional[UUID] = None
    election_id: Optional[UUID] = None
    report_type: Optional[str] = None
    amendment_indicator: AmendmentIndicatorLiteral
    filing_name: Optional[str] = None
    coverage_start_date: Optional[date] = None
    coverage_end_date: Optional[date] = None
    due_date: Optional[date] = None
    receipt_date: Optional[date] = None
    accepted_date: Optional[date] = None
    amended_from_filing_id: Optional[UUID] = None
    source_record_id: Optional[UUID] = None
    is_amended: bool = False
    days_late: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _strip_derived_filing_fields(cls, raw_data: Any) -> Any:
        if isinstance(raw_data, dict):
            raw_data = dict(raw_data)
            raw_data.pop("is_amended", None)
            raw_data.pop("days_late", None)
        return raw_data

    @model_validator(mode="after")
    def _derive_generated_filing_fields(self) -> Filing:
        self.is_amended = self.amendment_indicator == "A"
        if self.receipt_date is None or self.due_date is None:
            self.days_late = None
        else:
            self.days_late = max(0, (self.receipt_date - self.due_date).days)
        return self

    @model_validator(mode="after")
    def _validate_coverage_dates_and_amendment_parent(self) -> Filing:
        if (
            self.coverage_start_date is not None
            and self.coverage_end_date is not None
            and self.coverage_start_date > self.coverage_end_date
        ):
            raise ValueError("coverage_start_date must be <= coverage_end_date")
        if self.amended_from_filing_id is not None and self.amendment_indicator not in {"A", "T"}:
            raise ValueError("amended_from_filing_id can only be set when amendment_indicator is A or T")
        return self


class Transaction(CampaignFinanceBaseModel):

    filing_id: UUID
    committee_id: UUID
    transaction_type: str
    transaction_identifier: Optional[str] = None
    back_ref_transaction_id: Optional[str] = None
    sub_id: Optional[int] = None
    transaction_date: Optional[date] = None
    amount: Decimal = Field(max_digits=14, decimal_places=2)
    contributor_name_raw: Optional[str] = None
    contributor_employer: Optional[str] = None
    contributor_occupation: Optional[str] = None
    contributor_city: Optional[str] = None
    contributor_state: Optional[str] = Field(default=None, min_length=2, max_length=2)
    contributor_zip: Optional[str] = None
    contributor_person_id: Optional[UUID] = None
    contributor_organization_id: Optional[UUID] = None
    contributor_address_id: Optional[UUID] = None
    recipient_candidate_id: Optional[UUID] = None
    recipient_committee_id: Optional[UUID] = None
    memo_code: Optional[str] = None
    memo_text: Optional[str] = None
    is_memo: bool = False
    amendment_indicator: AmendmentIndicatorLiteral
    amended_by_transaction_id: Optional[UUID] = None
    source_record_id: Optional[UUID] = None
    date_is_reliable: bool = True
    support_oppose: Optional[Literal["S", "O"]] = None
    dissemination_date: Optional[date] = None
    aggregate_amount: Optional[Decimal] = None

    @model_validator(mode="after")
    def _derive_is_memo_and_validate_contributor_ids(self) -> Transaction:
        if self.contributor_person_id is not None and self.contributor_organization_id is not None:
            raise ValueError("Only one contributor identifier may be provided")
        self.is_memo = self.memo_code in {"X", "x"}
        return self


class CandidateCommitteeLink(CampaignFinanceBaseModel):
    candidate_id: UUID
    committee_id: UUID
    election_id: Optional[UUID] = None
    designation: Optional[str] = None
    candidate_election_year: Optional[int] = None
    fec_election_year: Optional[int] = None
    valid_period: ValidDateRange
    date_precision: DatePrecisionLiteral = "year"
    source_record_id: Optional[UUID] = None


class Election(CampaignFinanceBaseModel):
    office: OfficeType
    jurisdiction_type: JurisdictionTypeLiteral
    jurisdiction_code: str
    district: Optional[str] = None
    candidate_election_year: Optional[int] = Field(default=None, ge=1900)
    fec_election_year: Optional[int] = None
    valid_period: ValidDateRange = Field(default_factory=ValidDateRange)
    date_precision: DatePrecisionLiteral = "year"
    source_record_id: Optional[UUID] = None
