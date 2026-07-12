"""
Stub summary for MAR18_state_expansion_batch_2/civibus_dev/domains/campaign_finance/normalize/addresses.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STATE_ABBREVIATIONS: dict[str, str] = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
    "AMERICAN SAMOA": "AS",
    "GUAM": "GU",
    "NORTHERN MARIANA ISLANDS": "MP",
    "PUERTO RICO": "PR",
    "VIRGIN ISLANDS": "VI",
}

JUNK_VALUES = frozenset(
    {
        "N/A",
        "NONE",
        "INFORMATION REQUESTED",
        "INFORMATION REQUESTED PER BEST EFFORTS",
        "UNKNOWN",
        "SAME",
    }
)

UNIT_INDICATORS = ("APT", "STE", "SUITE", "UNIT", "#", "BLDG", "FL", "RM", "LOT")

_STATE_CODES = frozenset(STATE_ABBREVIATIONS.values())
_UNIT_WORD_INDICATORS = frozenset(token for token in UNIT_INDICATORS if token != "#")
_PACKED_ZIP_PATTERN = re.compile(r"^\d{9}$")
_HYPHENATED_ZIP_PATTERN = re.compile(r"^(\d{5})-(\d{4})$")
_FIVE_DIGIT_ZIP_PATTERN = re.compile(r"^\d{5}$")
_STREET_NUMBER_PATTERN = re.compile(r"^\d+[A-Z]?$")


def is_valid_zip5(value: str | None) -> bool:
    """Return True when *value* is exactly a 5-digit US ZIP code."""
    return value is not None and _FIVE_DIGIT_ZIP_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True)
class NormalizedAddress:
    street_number: str | None = None
    street_name: str | None = None
    unit: str | None = None
    city: str | None = None
    state: str | None = None
    zip5: str | None = None
    zip4: str | None = None


def normalize_state(raw: str | None) -> str | None:
    normalized = _normalize_spaced_upper_text(raw)
    if normalized is None:
        return None

    if normalized in _STATE_CODES:
        return normalized

    return STATE_ABBREVIATIONS.get(normalized)


def normalize_address(
    *,
    street: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip: str | None = None,
) -> NormalizedAddress:
    street_number, street_name, unit = _split_street(street)
    zip5, zip4 = _split_zip(zip)
    return NormalizedAddress(
        street_number=street_number,
        street_name=street_name,
        unit=unit,
        city=_normalize_city(city),
        state=normalize_state(state),
        zip5=zip5,
        zip4=zip4,
    )


def _clean_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _normalize_spaced_upper_text(raw: str | None) -> str | None:
    cleaned = _clean_text(raw)
    if cleaned is None:
        return None
    return _collapse_whitespace(cleaned.upper())


def _normalize_city(raw_city: str | None) -> str | None:
    return _normalize_spaced_upper_text(raw_city)


def _split_zip(raw_zip: str | None) -> tuple[str | None, str | None]:
    cleaned = _clean_text(raw_zip)
    if cleaned is None:
        return None, None

    compact = cleaned.replace(" ", "")
    if _FIVE_DIGIT_ZIP_PATTERN.fullmatch(compact):
        return compact, None

    if _PACKED_ZIP_PATTERN.fullmatch(compact):
        return compact[:5], compact[5:]

    hyphen_match = _HYPHENATED_ZIP_PATTERN.fullmatch(compact)
    if hyphen_match is not None:
        return hyphen_match.group(1), hyphen_match.group(2)

    return None, None


def _split_street(raw_street: str | None) -> tuple[str | None, str | None, str | None]:
    cleaned = _clean_text(raw_street)
    if cleaned is None:
        return None, None, None

    normalized = _collapse_whitespace(cleaned.upper())
    if normalized in JUNK_VALUES:
        return None, None, None

    tokens = normalized.split()
    street_tokens, unit = _separate_unit(tokens)
    if not street_tokens:
        return None, None, unit

    first_street_token = street_tokens[0]
    if _STREET_NUMBER_PATTERN.fullmatch(first_street_token) is None:
        return None, " ".join(street_tokens), unit

    street_number = first_street_token
    street_name = " ".join(street_tokens[1:]) or None
    return street_number, street_name, unit


def _separate_unit(tokens: list[str]) -> tuple[list[str], str | None]:
    for index, token in enumerate(tokens):
        if token.startswith("#"):
            return tokens[:index], _normalize_hash_unit_token(token=token, trailing_tokens=tokens[index + 1 :])

        if token in _UNIT_WORD_INDICATORS:
            unit_parts = [token, *tokens[index + 1 :]]
            return tokens[:index], " ".join(unit_parts)

    return tokens, None


def _normalize_hash_unit_token(*, token: str, trailing_tokens: list[str]) -> str:
    unit_parts = ["#"]
    suffix = token[1:]
    if suffix:
        unit_parts.append(suffix)
    unit_parts.extend(trailing_tokens)
    return " ".join(unit_parts)
