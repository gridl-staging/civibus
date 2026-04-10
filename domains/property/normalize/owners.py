"""Durham property owner normalization.

Small focused helpers for:
- Owner-kind classification (person vs organization)
- Joint-owner splitting
- Owner-name cleanup (title-casing, whitespace)
- Mailing-address normalization from OWNER_MAIL_* fields
"""

from __future__ import annotations

import re
from enum import Enum
from typing import TypedDict


class OwnerKind(Enum):
    PERSON = "person"
    ORGANIZATION = "organization"


# Suffixes that identify organizational owners.
# Matched as whole words (case-insensitive) against the PROPERTY_OWNER string.
_ORG_SUFFIXES = (
    "LLC",
    "INC",
    "CORP",
    "CORPORATION",
    "LTD",
    "LP",
    "LLP",
    "PLLC",
)

_ORG_KEYWORDS = (
    "TRUST",
    "UNIVERSITY",
    "COLLEGE",
    "CHURCH",
    "COUNTY",
    "ASSOCIATION",
    "FOUNDATION",
    "PARTNERS",
    "PARTNERSHIP",
    "COMPANY",
    "HOLDINGS",
    "PROPERTIES",
    "INVESTMENTS",
    "HEIRS",
    "ESTATE",
    "BANK",
    "SCHOOL",
    "DISTRICT",
    "HOUSING",
    "AUTHORITY",
    "MINISTRY",
    "MINISTRIES",
    "APARTMENTS",
    "CONDOMINIUMS",
)

_ORG_PREFIXES = (
    "CITY OF",
    "STATE OF",
    "COUNTY OF",
    "TOWN OF",
    "VILLAGE OF",
    "BOARD OF",
)

# Pre-compiled pattern for splitting joint owners on " & " or " AND "
# where the & is surrounded by spaces (not mid-word like "S&W").
_JOINT_SPLIT_RE = re.compile(r"\s+&\s+|\s+AND\s+", re.IGNORECASE)


def classify_owner(raw_owner: str) -> OwnerKind:
    """Classify a PROPERTY_OWNER string as person or organization."""
    normalized = raw_owner.strip().upper()
    if not normalized:
        return OwnerKind.PERSON

    # Check prefix patterns first (e.g. "CITY OF DURHAM")
    for prefix in _ORG_PREFIXES:
        if normalized.startswith(prefix):
            return OwnerKind.ORGANIZATION

    words = _owner_tokens(normalized)
    if not words:
        return OwnerKind.PERSON

    # Check if last word is an org suffix
    if words[-1] in _ORG_SUFFIXES:
        return OwnerKind.ORGANIZATION

    # Check for org keywords anywhere in the name
    for word in words:
        if word in _ORG_KEYWORDS:
            return OwnerKind.ORGANIZATION

    return OwnerKind.PERSON


def split_joint_owners(raw_owner: str) -> list[str]:
    """Split a combined owner string into individual owner names.

    Splits on " & " or " AND " (space-delimited, not mid-word).
    "ET AL" is not a split point — it's a single ownership reference.
    Returns empty list for blank input.
    """
    stripped = raw_owner.strip()
    if not stripped:
        return []

    parts = _JOINT_SPLIT_RE.split(stripped)
    return [p.strip() for p in parts if p.strip()]


def normalize_owner_name(raw_name: str) -> str:
    """Clean and title-case a raw Durham PROPERTY_OWNER string."""
    stripped = raw_name.strip()
    if not stripped:
        return ""

    # Collapse internal whitespace
    collapsed = re.sub(r"\s+", " ", stripped)
    return collapsed.title()


class NormalizedMailingAddress(TypedDict):
    raw_address: str
    city: str | None
    state: str | None
    zip5: str | None


def normalize_mailing_address(
    mail_1: str | None,
    mail_2: str | None,
    mail_3: str | None,
    city: str | None,
    state: str | None,
    zip_code: str | None,
) -> NormalizedMailingAddress | None:
    """Assemble a structured address from Durham OWNER_MAIL_* fields.

    Returns None when all inputs are blank/None.
    """
    clean_mail_1 = _clean_field(mail_1)
    clean_mail_2 = _clean_field(mail_2)
    clean_mail_3 = _clean_field(mail_3)
    clean_city = _clean_field(city)
    clean_state = _clean_field(state)
    clean_zip = _clean_field(zip_code)

    # If everything is blank, return None
    if not any([clean_mail_1, clean_mail_2, clean_mail_3, clean_city, clean_state, clean_zip]):
        return None

    zip5 = _extract_zip5(clean_zip)
    normalized_state = clean_state.upper() if clean_state else None
    normalized_city = clean_city.title() if clean_city else None

    # Build raw_address from non-empty parts
    address_parts: list[str] = []
    for mail_line in (clean_mail_1, clean_mail_2, clean_mail_3):
        if mail_line:
            address_parts.append(mail_line.title())

    if normalized_city:
        address_parts.append(normalized_city)

    # State + zip go together
    if normalized_state:
        state_zip = normalized_state
        if zip5:
            state_zip = f"{normalized_state} {zip5}"
        address_parts.append(state_zip)
    elif zip5:
        address_parts.append(zip5)

    raw_address = ", ".join(address_parts)

    return NormalizedMailingAddress(
        raw_address=raw_address,
        city=normalized_city,
        state=normalized_state,
        zip5=zip5,
    )


def _clean_field(value: str | None) -> str | None:
    """Strip and return None for blank values."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _owner_tokens(normalized_owner: str) -> list[str]:
    """Return uppercase owner tokens with trailing punctuation removed."""
    return [token.strip(".,;:") for token in normalized_owner.split() if token.strip(".,;:")]


def _extract_zip5(raw_zip: str | None) -> str | None:
    """Extract 5-digit ZIP from various formats (27701, 27701-1234, 277011234)."""
    if not raw_zip:
        return None

    # Remove hyphens for uniform processing
    digits_only = re.sub(r"[^0-9]", "", raw_zip)
    if len(digits_only) >= 5:
        return digits_only[:5]

    return None
