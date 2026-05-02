"""IRS 527 dark money models — Form 8871 (political orgs) and Form 8872 (periodic reports).

Four record types from the IRS 527 pipe-delimited bulk file:
  - Type 1 → PoliticalOrganization527 (Form 8871 registration)
  - Type 2 → Filing8872 (Form 8872 periodic disclosure)
  - Type A → Contribution527 (Schedule A contribution)
  - Type B → Expenditure527 (Schedule B expenditure)

Field names are normalized from IRS layout doc (PolOrgsFileLayout.doc) to snake_case.
The IRS source uses "RECIEPIENT" (typo); we normalize to "recipient" in the model.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import Field, model_validator

from .models import CampaignFinanceBaseModel

EIN_REGEX = r"^\d{2}-?\d{7}$"


class Organization990(CampaignFinanceBaseModel):
    """Minimal placeholder for IRS 990 organizations.

    Stage 4 scope intentionally limits this to a lightweight model surface.
    Filtering/acquisition heuristics belong in research docs, not model code.
    """

    # Required identity fields
    ein: str = Field(pattern=EIN_REGEX)
    name: str

    # Optional placeholders informed by Stage 4 research
    ntee_code: Optional[str] = None
    total_revenue: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    political_expenditures: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)

    # Provenance
    source_record_id: Optional[UUID] = None


class PoliticalOrganization527(CampaignFinanceBaseModel):
    """IRS record type 1 — Form 8871 political organization registration.

    EIN is the natural unique key (latest 8871 wins on upsert).
    form_id_number is stored for D/R/E record linkage in later stages.
    """

    # Required fields
    form_type: str
    form_id_number: str
    ein: str = Field(pattern=EIN_REGEX)
    name: str

    # Mailing address
    mailing_address_1: Optional[str] = None
    mailing_address_2: Optional[str] = None
    mailing_address_city: Optional[str] = None
    mailing_address_state: Optional[str] = None
    mailing_address_zip: Optional[str] = None
    mailing_address_zip_ext: Optional[str] = None

    # Business address
    business_address_1: Optional[str] = None
    business_address_2: Optional[str] = None
    business_address_city: Optional[str] = None
    business_address_state: Optional[str] = None
    business_address_zip: Optional[str] = None
    business_address_zip_ext: Optional[str] = None

    # Contact info
    email_address: Optional[str] = None
    custodian_name: Optional[str] = None
    custodian_address_1: Optional[str] = None
    custodian_address_2: Optional[str] = None
    custodian_address_city: Optional[str] = None
    custodian_address_state: Optional[str] = None
    custodian_address_zip: Optional[str] = None
    custodian_address_zip_ext: Optional[str] = None
    contact_person_name: Optional[str] = None
    contact_address_1: Optional[str] = None
    contact_address_2: Optional[str] = None
    contact_address_city: Optional[str] = None
    contact_address_state: Optional[str] = None
    contact_address_zip: Optional[str] = None
    contact_address_zip_ext: Optional[str] = None

    # Organization details
    purpose: Optional[str] = None
    established_date: Optional[date] = None
    material_change_date: Optional[date] = None
    insert_datetime: Optional[str] = None

    # Report indicators (from 8871 filing)
    initial_report_indicator: Optional[bool] = None
    amended_report_indicator: Optional[bool] = None
    final_report_indicator: Optional[bool] = None

    # Exemption indicators
    exempt_8872_indicator: Optional[bool] = None
    exempt_state: Optional[str] = None
    exempt_990_indicator: Optional[bool] = None
    related_entity_bypass: Optional[str] = None
    eain_bypass: Optional[str] = None

    # Provenance
    source_record_id: Optional[UUID] = None


class Filing8872(CampaignFinanceBaseModel):
    """IRS record type 2 — Form 8872 periodic disclosure filing.

    form_id_number is the natural unique key (one filing per form_id_number).
    """

    # Required fields
    form_type: str
    form_id_number: str
    ein: str = Field(pattern=EIN_REGEX)
    period_begin_date: Optional[date] = None
    period_end_date: Optional[date] = None

    # Organization info (denormalized from the filing record)
    organization_name: Optional[str] = None
    mailing_address_1: Optional[str] = None
    mailing_address_2: Optional[str] = None
    mailing_address_city: Optional[str] = None
    mailing_address_state: Optional[str] = None
    mailing_address_zip: Optional[str] = None
    mailing_address_zip_ext: Optional[str] = None
    email_address: Optional[str] = None
    change_of_address_indicator: Optional[bool] = None
    org_formation_date: Optional[date] = None

    # Custodian
    custodian_name: Optional[str] = None
    custodian_address_1: Optional[str] = None
    custodian_address_2: Optional[str] = None
    custodian_address_city: Optional[str] = None
    custodian_address_state: Optional[str] = None
    custodian_address_zip: Optional[str] = None
    custodian_address_zip_ext: Optional[str] = None

    # Contact
    contact_person_name: Optional[str] = None
    contact_address_1: Optional[str] = None
    contact_address_2: Optional[str] = None
    contact_address_city: Optional[str] = None
    contact_address_state: Optional[str] = None
    contact_address_zip: Optional[str] = None
    contact_address_zip_ext: Optional[str] = None

    # Business address
    business_address_1: Optional[str] = None
    business_address_2: Optional[str] = None
    business_address_city: Optional[str] = None
    business_address_state: Optional[str] = None
    business_address_zip: Optional[str] = None
    business_address_zip_ext: Optional[str] = None

    # Report indicators
    initial_report_indicator: Optional[bool] = None
    amended_report_indicator: Optional[bool] = None
    final_report_indicator: Optional[bool] = None

    # Schedule/period indicators
    quarterly_indicator: Optional[bool] = None
    monthly_report_month: Optional[str] = None
    pre_election_type: Optional[str] = None
    pre_or_post_election_date: Optional[date] = None
    pre_or_post_election_state: Optional[str] = None

    # Schedule totals
    sched_a_indicator: Optional[bool] = None
    total_sched_a: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    sched_b_indicator: Optional[bool] = None
    total_sched_b: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    insert_datetime: Optional[str] = None

    # Provenance
    source_record_id: Optional[UUID] = None

    @model_validator(mode="after")
    def _validate_coverage_date_ordering(self) -> Filing8872:
        if self.period_begin_date is not None and self.period_end_date is not None:
            if self.period_begin_date > self.period_end_date:
                raise ValueError("period_begin_date must be <= period_end_date")
        return self


class Contribution527(CampaignFinanceBaseModel):
    """IRS record type A — Schedule A contribution to a 527 organization.

    sched_a_id is the natural unique key.
    """

    # Required fields
    form_id_number: str
    sched_a_id: str
    ein: str = Field(pattern=EIN_REGEX)
    contributor_name: str
    amount: Decimal = Field(max_digits=14, decimal_places=2)
    contribution_date: Optional[date] = None
    aggregate_ytd: Decimal = Field(max_digits=14, decimal_places=2)

    # Optional org name (denormalized)
    org_name: Optional[str] = None

    # Contributor address
    contributor_address_1: Optional[str] = None
    contributor_address_2: Optional[str] = None
    contributor_address_city: Optional[str] = None
    contributor_address_state: Optional[str] = None
    contributor_address_zip: Optional[str] = None
    contributor_address_zip_ext: Optional[str] = None

    # Contributor employment
    contributor_employer: Optional[str] = None
    contributor_occupation: Optional[str] = None

    # Provenance
    source_record_id: Optional[UUID] = None


class Expenditure527(CampaignFinanceBaseModel):
    """IRS record type B — Schedule B expenditure from a 527 organization.

    sched_b_id is the natural unique key.
    Note: IRS source uses "RECIEPIENT" (typo); normalized to "recipient" here.
    """

    # Required fields
    form_id_number: str
    sched_b_id: str
    ein: str = Field(pattern=EIN_REGEX)
    recipient_name: str
    amount: Decimal = Field(max_digits=14, decimal_places=2)
    expenditure_date: Optional[date] = None
    purpose: Optional[str] = None

    # Optional org name (denormalized)
    org_name: Optional[str] = None

    # Recipient address
    recipient_address_1: Optional[str] = None
    recipient_address_2: Optional[str] = None
    recipient_address_city: Optional[str] = None
    recipient_address_state: Optional[str] = None
    recipient_address_zip: Optional[str] = None
    recipient_address_zip_ext: Optional[str] = None

    # Recipient employment
    recipient_employer: Optional[str] = None
    recipient_occupation: Optional[str] = None

    # Provenance
    source_record_id: Optional[UUID] = None
