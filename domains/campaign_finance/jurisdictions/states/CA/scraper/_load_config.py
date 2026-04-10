"""CA pipeline load configuration: data classes, constants, entity role mappings, and field loaders.

Extracted from load.py to keep both modules under the 800-line file-size limit.
These are pure data definitions and cached config lookups with no DB or IO dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable
from uuid import UUID

from core.types.python.models import Address, Organization
from domains.campaign_finance.jurisdictions.states import load_utils as _shared_load_utils

from . import _load_column_for_semantic_path
from .extract import (
    extract_ca_contribution,
    extract_ca_expenditure,
    extract_ca_loan,
)

# --- Domain constants ---

_CA_DOMAIN = "campaign_finance"
_CA_JURISDICTION = "state/CA"
_CA_DATA_SOURCE_NAME = "CAL-ACCESS Raw Data Export"
_CVR_TABLE = "CVR_CAMPAIGN_DISCLOSURE_CD"
_FILERNAME_TABLE = "FILERNAME_CD"
_FILERS_TABLE = "FILERS_CD"
_TRANSACTION_TABLES = ("RCPT_CD", "EXPN_CD", "LOAN_CD")


# --- Data classes ---

LoadResult = _shared_load_utils.LoadResult


@dataclass(slots=True)
class CALoadCounts:
    inserted: int = 0
    skipped: int = 0
    quarantined: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class CAEntityRoles:
    person: str
    organization: str
    committee: str
    address: str
    person_lookup_roles: tuple[str, ...]
    organization_lookup_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CATransactionTableConfig:
    table_name: str
    extract_row: Callable[[dict[str, str | None]], dict[str, object]]
    entity_roles: CAEntityRoles


@dataclass(frozen=True, slots=True)
class CAFilerProfile:
    canonical_name: str | None
    filer_type: str | None
    status: str | None
    address: Address | None


@dataclass(frozen=True, slots=True)
class CACommitteeProfile:
    organization: Organization
    address: Address | None


@dataclass(frozen=True, slots=True)
class CAFilingLookupEntry:
    filing_id: UUID
    committee_id: UUID
    committee_organization_id: UUID
    amendment_indicator: str
    source_record_id: UUID
    form_type: str | None = None


# --- Entity role configurations ---

_RCPT_ENTITY_ROLES = CAEntityRoles(
    person="donor",
    organization="contributor",
    committee="recipient",
    address="donor_address",
    person_lookup_roles=("donor",),
    organization_lookup_roles=("contributor",),
)
_EXPN_ENTITY_ROLES = CAEntityRoles(
    person="payee",
    organization="payee",
    committee="payer",
    address="payee_address",
    person_lookup_roles=("payee",),
    organization_lookup_roles=("payee",),
)
_LOAN_ENTITY_ROLES = CAEntityRoles(
    person="lender",
    organization="lender",
    committee="borrower",
    address="lender_address",
    person_lookup_roles=("lender",),
    organization_lookup_roles=("lender",),
)
TABLE_CONFIG_BY_NAME = {
    "RCPT_CD": CATransactionTableConfig("RCPT_CD", extract_ca_contribution, _RCPT_ENTITY_ROLES),
    "EXPN_CD": CATransactionTableConfig("EXPN_CD", extract_ca_expenditure, _EXPN_ENTITY_ROLES),
    "LOAN_CD": CATransactionTableConfig("LOAN_CD", extract_ca_loan, _LOAN_ENTITY_ROLES),
}


# --- Field loaders (config.yaml -> column name mappings) ---


@lru_cache(maxsize=1)
def load_cvr_fields() -> dict[str, str]:
    return {
        "filer_id": _load_column_for_semantic_path(_CVR_TABLE, "filer.id"),
        "filing_id": _load_column_for_semantic_path(_CVR_TABLE, "filing.id"),
        "amendment_id": _load_column_for_semantic_path(_CVR_TABLE, "filing.amendment_id"),
        "report_date": _load_column_for_semantic_path(_CVR_TABLE, "filing.report_date"),
        "form_type": _load_column_for_semantic_path(_CVR_TABLE, "filing.form_type"),
        "statement_type": _load_column_for_semantic_path(_CVR_TABLE, "filing.statement_type"),
    }


@lru_cache(maxsize=1)
def load_filername_fields() -> dict[str, str]:
    return {
        "filer_id": _load_column_for_semantic_path(_FILERNAME_TABLE, "filer.id"),
        "filer_type": _load_column_for_semantic_path(_FILERNAME_TABLE, "filer.type"),
        "name_last": _load_column_for_semantic_path(_FILERNAME_TABLE, "filer.name.last"),
        "name_first": _load_column_for_semantic_path(_FILERNAME_TABLE, "filer.name.first"),
        "name_title": _load_column_for_semantic_path(_FILERNAME_TABLE, "filer.name.title"),
        "name_suffix": _load_column_for_semantic_path(_FILERNAME_TABLE, "filer.name.suffix"),
        "city": _load_column_for_semantic_path(_FILERNAME_TABLE, "filer.address.city"),
        "state": _load_column_for_semantic_path(_FILERNAME_TABLE, "filer.address.state"),
        "zip": _load_column_for_semantic_path(_FILERNAME_TABLE, "filer.address.zip"),
    }


@lru_cache(maxsize=1)
def load_filers_fields() -> dict[str, str]:
    # Live FILERS_CD.TSV contains only FILER_ID; filer_type and status
    # are not present in the live export and come from FILERNAME_CD instead.
    return {
        "filer_id": _load_column_for_semantic_path(_FILERS_TABLE, "filer.id"),
    }


@lru_cache(maxsize=None)
def load_transaction_fields(table_name: str) -> dict[str, str]:
    return {
        "filing_id": _load_column_for_semantic_path(table_name, "filing.id"),
        "amendment_id": _load_column_for_semantic_path(table_name, "filing.amendment_id"),
        "transaction_id": _load_column_for_semantic_path(table_name, "transaction.id"),
        "transaction_date": _load_column_for_semantic_path(table_name, "transaction.date"),
        "amount": _load_column_for_semantic_path(table_name, "transaction.amount"),
        "transaction_type": _load_column_for_semantic_path(table_name, "transaction.type"),
        "form_type": _load_column_for_semantic_path(table_name, "transaction.form_type"),
    }
