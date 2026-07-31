"""FEC employer canonicalization and conservative industry mapping."""

from __future__ import annotations

from types import MappingProxyType
import unicodedata

UNKNOWN_INDUSTRY = "UNKNOWN_INDUSTRY"
JUNK_EMPLOYER_WEIGHT = 0.01
# The fixed sample covers 837 known-or-derived rows out of 14,324: 370 from
# employer mappings plus 467 from occupation fallback. The zero-row headroom
# makes any loss from either rule family fail the owner contract.
INDUSTRY_BY_EMPLOYER_MIN_COVERAGE = 837 / 14_324

_JUNK_EMPLOYER_REASONS: dict[str, str] = {
    "DISABLED": "FEC filer supplied disability status instead of an employer.",
    "ENTREPRENEUR": "FEC filer supplied an occupation instead of an employer.",
    "HOMEMAKER": "FEC filer supplied an occupation or status instead of an employer.",
    "RETIRED": "FEC filer supplied retirement status instead of an employer.",
    "SELF": "FEC filer supplied self-employment shorthand instead of an employer.",
    "SELF EMPLOYED": "FEC filer supplied self-employment status instead of an employer.",
    "NONE": "FEC filer supplied an explicit no-employer placeholder.",
    "N/A": "FEC filer supplied a not-applicable placeholder.",
    "NOT EMPLOYED": "FEC filer supplied employment status instead of an employer.",
    "UNEMPLOYED": "FEC filer supplied employment status instead of an employer.",
}
JUNK_EMPLOYERS = frozenset(_JUNK_EMPLOYER_REASONS)

_LEGAL_SUFFIX_REASONS: dict[str, str] = {
    "INC": "Common corporate suffix; not a distinguishing employer term.",
    "LLC": "Common legal-entity suffix; not a distinguishing employer term.",
    "CORP": "Common corporate suffix; not a distinguishing employer term.",
    "CO": "Common company suffix; not a distinguishing employer term.",
}
LEGAL_SUFFIXES = frozenset(_LEGAL_SUFFIX_REASONS)

_EMPLOYER_INDUSTRIES: dict[str, str] = {
    "ABBOTT": "Health Care",
    # The broad Amazon employer label is assigned to its consumer-commerce sector.
    "AMAZON": "Retail",
    "AMERICAN AIRLINES": "Transportation",
    "AFSCME INT L": "Labor",
    "ABBVIE": "Health Care",
    "ALTRIA GROUP DISTRIBUTION": "Tobacco",
    "AMGEN": "Health Care",
    "BNSF RAILWAY COMPANY": "Transportation",
    "APPLE": "Technology",
    "BANK OF AMERICA": "Finance",
    "BOEING": "Aerospace and Defense",
    "COMCAST CC OF WILLOW GROVE": "Telecommunications",
    "DELTA AIR LINES": "Transportation",
    "DELL TECHNOLOGIES": "Technology",
    "ELECTRICIANS LOCAL 98": "Labor",
    "FEDERAL GOVERNMENT": "Government",
    # Public agencies remain distinguishable from private transport operators.
    "FEDERAL AVIATION ADMINISTRATION": "Government",
    "FORD MOTOR COMPANY": "Automotive",
    "FRIAS TRANSPORTATION": "Transportation",
    "GENERAL MOTORS COMPANY": "Automotive",
    "GENENTECH USA": "Health Care",
    "GLAXOSMITHKLINE": "Health Care",
    "GOOGLE": "Technology",
    "HOME DEPOT U S A": "Retail",
    "IBM": "Technology",
    "JPMORGAN CHASE": "Finance",
    "LOCKHEED MARTIN": "Aerospace and Defense",
    "MICROSOFT": "Technology",
    "MORGAN STANLEY": "Finance",
    "NEW YORK LIFE INSURANCE COMPANY": "Insurance",
    "NORTHROP GRUMMAN CORPORATION": "Aerospace and Defense",
    "NOVO NORDISK": "Health Care",
    "PFIZER": "Health Care",
    "SOUTHWEST AIRLINES": "Transportation",
    "SPACE EXPLORATION TECHNOLOGIES": "Aerospace and Defense",
    "THE ELEVANCE HEALTH COMPANIES": "Health Care",
    "UNITED AIRLINES": "Transportation",
    "UNITED PARCEL SERVICE": "Transportation",
    "VERIZON": "Telecommunications",
    # USPS is an independent federal establishment, not a private carrier.
    "USPS": "Government",
    "VALERO SERVICES": "Energy",
    "WALMART": "Retail",
}

OCCUPATION_INDUSTRIES = MappingProxyType(
    {
        "ATTORNEY": "Legal",
        "PHYSICIAN": "Health Care",
        "TEACHER": "Education",
    }
)

_AMBIGUOUS_OCCUPATIONS = frozenset(
    {
        # These top-sample occupation strings describe role seniority or work mode,
        # not an industry with enough precision for product classification.
        "CONSULTANT",
        "MANAGER",
        "OWNER",
    }
)


def canonicalize_employer(raw_employer: str | None) -> str | None:
    """Return a deterministic employer key, or None for junk/non-employer values."""
    normalized_employer = _normalize_employer_text(raw_employer)
    if normalized_employer is None:
        return None

    canonical_employer = _strip_legal_suffix(normalized_employer)
    if canonical_employer is None or canonical_employer in JUNK_EMPLOYERS:
        return None
    return canonical_employer


def is_junk_employer(raw_employer: str | None) -> bool:
    """Return True when the raw value is an explicit non-employer placeholder."""
    normalized_employer = _normalize_employer_text(raw_employer)
    if normalized_employer is None:
        return True

    canonical_employer = _strip_legal_suffix(normalized_employer)
    return canonical_employer is None or canonical_employer in JUNK_EMPLOYERS


def employer_junk_weight(raw_employer: str | None) -> float:
    """Return a near-zero matching weight for junk employers and full weight otherwise."""
    if is_junk_employer(raw_employer):
        return JUNK_EMPLOYER_WEIGHT
    return 1.0


def industry_for_employer(raw_employer: str | None, *, occupation: str | None = None) -> str:
    """Return a curated employer industry, optional occupation fallback, or the unknown sentinel."""
    canonical_employer = canonicalize_employer(raw_employer)
    employer_industry = (
        UNKNOWN_INDUSTRY
        if canonical_employer is None
        else _EMPLOYER_INDUSTRIES.get(canonical_employer, UNKNOWN_INDUSTRY)
    )
    if employer_industry != UNKNOWN_INDUSTRY:
        return employer_industry

    # Employer text is the primary evidence; occupation is only a fallback when
    # the employer path cannot produce an industry.
    return _industry_for_occupation(occupation)


def _normalize_employer_text(raw_employer: str | None) -> str | None:
    if raw_employer is None:
        return None

    normalized_employer = raw_employer.strip()
    normalized_employer = unicodedata.normalize("NFC", normalized_employer)
    normalized_employer = normalized_employer.upper()
    if normalized_employer == "N/A":
        return normalized_employer

    normalized_employer = _compact_dotted_legal_suffixes(normalized_employer)
    normalized_employer = _replace_punctuation_with_spaces(normalized_employer)
    normalized_employer = " ".join(normalized_employer.split())
    return normalized_employer or None


def _compact_dotted_legal_suffixes(normalized_employer: str) -> str:
    """Compact covered dotted legal suffixes before periods become separators."""
    return normalized_employer.replace("L.L.C.", "LLC").replace("L.L.C", "LLC")


def _replace_punctuation_with_spaces(normalized_employer: str) -> str:
    return "".join(character if character.isalnum() else " " for character in normalized_employer)


def _industry_for_occupation(raw_occupation: str | None) -> str:
    canonical_occupation = canonicalize_employer(raw_occupation)
    if canonical_occupation is None or canonical_occupation in _AMBIGUOUS_OCCUPATIONS:
        return UNKNOWN_INDUSTRY
    return OCCUPATION_INDUSTRIES.get(canonical_occupation, UNKNOWN_INDUSTRY)


def _strip_legal_suffix(normalized_employer: str) -> str | None:
    employer_tokens = normalized_employer.split()
    if employer_tokens and employer_tokens[-1] in LEGAL_SUFFIXES:
        employer_tokens = employer_tokens[:-1]
    canonical_employer = " ".join(employer_tokens)
    return canonical_employer or None


__all__ = [
    "INDUSTRY_BY_EMPLOYER_MIN_COVERAGE",
    "JUNK_EMPLOYER_WEIGHT",
    "JUNK_EMPLOYERS",
    "LEGAL_SUFFIXES",
    "OCCUPATION_INDUSTRIES",
    "UNKNOWN_INDUSTRY",
    "canonicalize_employer",
    "employer_junk_weight",
    "industry_for_employer",
    "is_junk_employer",
]
