"""CA campaign finance entity extraction — maps raw CAL-ACCESS rows to core entity models."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import TypedDict

from core.types.python.models import Address, DataSource, Organization, Person

from . import _get_raw_data_source, _load_column_for_semantic_path

# ENTITY_CD values that map to organizations (non-individual entities)
_ORG_ENTITY_CODES = frozenset({"COM", "OTH", "PTY", "SCC"})

# Config semantic paths for counterparty/address extraction
_COUNTERPARTY_SEMANTIC_PATHS: dict[str, dict[str, str]] = {
    "RCPT_CD": {
        "entity": "donor.entity_type",
        "last": "donor.name.last",
        "first": "donor.name.first",
        "title": "donor.name.title",
        "suffix": "donor.name.suffix",
        "city": "donor.address.city",
        "state": "donor.address.state",
        "zip": "donor.address.zip",
        "employer": "donor.employer",
        "occupation": "donor.occupation",
    },
    "EXPN_CD": {
        "entity": "payee.entity_type",
        "last": "payee.name.last",
        "first": "payee.name.first",
        "title": "payee.name.title",
        "suffix": "payee.name.suffix",
        "city": "payee.address.city",
        "state": "payee.address.state",
        "zip": "payee.address.zip",
    },
    "LOAN_CD": {
        "entity": "lender.entity_type",
        "last": "lender.name.last",
        "first": "lender.name.first",
        "title": "lender.name.title",
        "suffix": "lender.name.suffix",
        "city": "lender.address.city",
        "state": "lender.address.state",
        "zip": "lender.address.zip",
    },
}

_CVR_SEMANTIC_PATHS = {
    "filer_id": "filer.id",
    "name_last": "filer.name.last",
}


@lru_cache(maxsize=None)
def _load_counterparty_fields(table: str) -> dict[str, str]:
    semantic_paths = _COUNTERPARTY_SEMANTIC_PATHS.get(table)
    if semantic_paths is None:
        raise ValueError(f"Unsupported CA counterparty table: {table!r}")
    return {
        field_name: _load_column_for_semantic_path(table, semantic_path)
        for field_name, semantic_path in semantic_paths.items()
    }


@lru_cache(maxsize=1)
def _load_cvr_fields() -> dict[str, str]:
    return {
        field_name: _load_column_for_semantic_path("CVR_CAMPAIGN_DISCLOSURE_CD", semantic_path)
        for field_name, semantic_path in _CVR_SEMANTIC_PATHS.items()
    }


class CAContributionExtraction(TypedDict):
    donor_person: Person | None
    donor_org: Organization | None
    address: Address | None


class CAExpenditureExtraction(TypedDict):
    payee_person: Person | None
    payee_org: Organization | None
    address: Address | None


class CALoanExtraction(TypedDict):
    lender_person: Person | None
    lender_org: Organization | None
    address: Address | None


def extract_counterparty_person(
    row: dict[str, str | None],
    *,
    table: str,
) -> Person | None:
    fields = _load_counterparty_fields(table)
    entity_cd = row.get(fields["entity"])
    if entity_cd != "IND":
        return None

    first_name = _normalized_text(row.get(fields["first"]))
    last_name = _normalized_text(row.get(fields["last"]))
    suffix = _normalized_text(row.get(fields["suffix"]))

    canonical = _build_canonical_name(first_name, last_name)

    identifiers: dict[str, str] = {}
    # Only RCPT_CD has employer/occupation
    if "employer" in fields:
        employer = _normalized_text(row.get(fields["employer"]))
        if employer:
            identifiers["employer"] = employer
        occupation = _normalized_text(row.get(fields["occupation"]))
        if occupation:
            identifiers["occupation"] = occupation

    return Person(
        canonical_name=canonical,
        first_name=first_name,
        last_name=last_name,
        suffix=suffix,
        identifiers=identifiers,
    )


def extract_counterparty_org(
    row: dict[str, str | None],
    *,
    table: str,
) -> Organization | None:
    """Extract an Organization from a CA row if the entity is non-individual."""
    fields = _load_counterparty_fields(table)
    entity_cd = row.get(fields["entity"])
    if entity_cd not in _ORG_ENTITY_CODES:
        return None

    name = _normalized_text(row.get(fields["last"]))
    if name is None:
        return None

    # Title-case for COM entities (e.g. "Big PAC" -> "Big Pac"), preserve for OTH
    canonical = name.title() if entity_cd == "COM" else name

    return Organization(canonical_name=canonical)


def extract_committee_from_cvr(row: dict[str, str | None]) -> Organization:
    """Extract a committee Organization from a CVR_CAMPAIGN_DISCLOSURE_CD row."""
    cvr_fields = _load_cvr_fields()
    name = _normalized_text(row.get(cvr_fields["name_last"])) or ""
    canonical = name.title()

    identifiers: dict[str, str] = {}
    filer_id = _normalized_text(row.get(cvr_fields["filer_id"]))
    if filer_id:
        identifiers["ca_filer_id"] = filer_id

    return Organization(
        canonical_name=canonical,
        identifiers=identifiers,
    )


def extract_address(
    row: dict[str, str | None],
    *,
    table: str,
) -> Address | None:
    """Extract an Address from a CA row using table-specific field prefixes."""
    fields = _load_counterparty_fields(table)
    city = _normalized_text(row.get(fields["city"]))
    state = _normalize_state_code(row.get(fields["state"]))

    if not city and not state:
        return None

    raw_zip = _normalized_text(row.get(fields["zip"]))
    zip5, zip4 = _split_zip(raw_zip)

    # Uppercase city for consistency
    city_upper = city.upper() if city else None

    raw_parts = [p for p in (city_upper, state, raw_zip) if p]
    raw_address = ", ".join(raw_parts)

    return Address(
        raw_address=raw_address,
        city=city_upper,
        state=state,
        zip5=zip5,
        zip4=zip4,
    )


def extract_ca_contribution(row: dict[str, str | None]) -> CAContributionExtraction:
    """Extract donor person/org and address from a RCPT_CD row."""
    return {
        "donor_person": extract_counterparty_person(row, table="RCPT_CD"),
        "donor_org": extract_counterparty_org(row, table="RCPT_CD"),
        "address": extract_address(row, table="RCPT_CD"),
    }


def extract_ca_expenditure(row: dict[str, str | None]) -> CAExpenditureExtraction:
    """Extract payee person/org and address from an EXPN_CD row."""
    return {
        "payee_person": extract_counterparty_person(row, table="EXPN_CD"),
        "payee_org": extract_counterparty_org(row, table="EXPN_CD"),
        "address": extract_address(row, table="EXPN_CD"),
    }


def extract_ca_loan(row: dict[str, str | None]) -> CALoanExtraction:
    """Extract lender person/org and address from a LOAN_CD row."""
    return {
        "lender_person": extract_counterparty_person(row, table="LOAN_CD"),
        "lender_org": extract_counterparty_org(row, table="LOAN_CD"),
        "address": extract_address(row, table="LOAN_CD"),
    }


def build_ca_data_source() -> DataSource:
    """Build a DataSource record for the CA CAL-ACCESS raw data export."""
    raw = _get_raw_data_source()
    return DataSource(
        domain="campaign_finance",
        jurisdiction="state/CA",
        name=raw.name,
        source_url=raw.url,
        source_format="TSV (tab-delimited, ZIP archive)",
    )


# --- Internal helpers ---


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_state_code(value: str | None) -> str | None:
    normalized = _normalized_text(value)
    if normalized is None:
        return None
    upper = normalized.upper()
    # Only accept 2-letter alpha state codes; live data has numeric junk
    if len(upper) != 2 or not upper.isalpha():
        return None
    return upper


def _build_canonical_name(first: str | None, last: str | None) -> str:
    parts = [p for p in (first, last) if p]
    return " ".join(parts)


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    """Split raw zip into (zip5, zip4), returning None for invalid components.

    Live CA data contains a wide variety of formats: 5-digit, 9-digit without
    hyphen, hyphenated ZIP+4, and short/malformed values. Only return zip5 if
    it's exactly 5 digits; only return zip4 if it's exactly 4 digits.
    """
    normalized_zip = _normalized_text(raw_zip)
    if normalized_zip is None:
        return None, None
    zip5: str | None = None
    zip4: str | None = None
    if "-" in normalized_zip:
        z5, z4 = normalized_zip.split("-", maxsplit=1)
        zip5 = _normalized_text(z5)
        zip4 = _normalized_text(z4)
    elif len(normalized_zip) == 9 and normalized_zip.isdigit():
        zip5 = normalized_zip[:5]
        zip4 = normalized_zip[5:]
    else:
        zip5 = normalized_zip
    # Only accept structurally valid zip5 (5 digits) and zip4 (4 digits)
    if zip5 is not None and (len(zip5) != 5 or not zip5.isdigit()):
        zip5 = None
    if zip4 is not None and (len(zip4) != 4 or not zip4.isdigit()):
        zip4 = None
    return zip5, zip4


def extract_name_raw(extracted: Mapping[str, object]) -> str | None:
    for key in ("donor_person", "payee_person", "lender_person"):
        person = extracted.get(key)
        if person is not None:
            return person.canonical_name  # type: ignore[return-value]
    for key in ("donor_org", "payee_org", "lender_org"):
        organization = extracted.get(key)
        if organization is not None:
            return organization.canonical_name  # type: ignore[return-value]
    return None


def extract_employer(extracted: Mapping[str, object]) -> str | None:
    donor_person = extracted.get("donor_person")
    if donor_person is None:
        return None
    return donor_person.identifiers.get("employer")  # type: ignore[return-value]


def extract_occupation(extracted: Mapping[str, object]) -> str | None:
    donor_person = extracted.get("donor_person")
    if donor_person is None:
        return None
    return donor_person.identifiers.get("occupation")  # type: ignore[return-value]
