"""Shared civic domain constants."""

from __future__ import annotations

CENSUS_STATE_FIPS_TO_USPS: tuple[tuple[str, str], ...] = (
    ("01", "AL"),
    ("02", "AK"),
    ("04", "AZ"),
    ("05", "AR"),
    ("06", "CA"),
    ("08", "CO"),
    ("09", "CT"),
    ("10", "DE"),
    ("11", "DC"),
    ("12", "FL"),
    ("13", "GA"),
    ("15", "HI"),
    ("16", "ID"),
    ("17", "IL"),
    ("18", "IN"),
    ("19", "IA"),
    ("20", "KS"),
    ("21", "KY"),
    ("22", "LA"),
    ("23", "ME"),
    ("24", "MD"),
    ("25", "MA"),
    ("26", "MI"),
    ("27", "MN"),
    ("28", "MS"),
    ("29", "MO"),
    ("30", "MT"),
    ("31", "NE"),
    ("32", "NV"),
    ("33", "NH"),
    ("34", "NJ"),
    ("35", "NM"),
    ("36", "NY"),
    ("37", "NC"),
    ("38", "ND"),
    ("39", "OH"),
    ("40", "OK"),
    ("41", "OR"),
    ("42", "PA"),
    ("44", "RI"),
    ("45", "SC"),
    ("46", "SD"),
    ("47", "TN"),
    ("48", "TX"),
    ("49", "UT"),
    ("50", "VT"),
    ("51", "VA"),
    ("53", "WA"),
    ("54", "WV"),
    ("55", "WI"),
    ("56", "WY"),
    ("60", "AS"),
    ("66", "GU"),
    ("69", "MP"),
    ("72", "PR"),
    ("78", "VI"),
)

# Canonical launch scope for state geometry coverage: 50 states + DC.
# Territories are intentionally excluded.
LAUNCH_SCOPE_STATE_FIPS_TO_USPS: tuple[tuple[str, str], ...] = tuple(
    (fips, usps) for fips, usps in CENSUS_STATE_FIPS_TO_USPS if fips not in {"60", "66", "69", "72", "78"}
)
LAUNCH_SCOPE_STATE_FIPS: frozenset[str] = frozenset(fips for fips, _ in LAUNCH_SCOPE_STATE_FIPS_TO_USPS)
LAUNCH_SCOPE_USPS_STATES: tuple[str, ...] = tuple(usps for _, usps in LAUNCH_SCOPE_STATE_FIPS_TO_USPS)
CENSUS_STATE_FIPS_TO_USPS_MAP: dict[str, str] = dict(CENSUS_STATE_FIPS_TO_USPS)

# Canonical office.name values that make up the federal Congress + executive
# directory. The civics ingest layer accepts arbitrary names at
# office_level='federal', so callers presenting the Congress directory MUST
# restrict membership to this set rather than every federal office row.
CANONICAL_FEDERAL_DIRECTORY_OFFICE_NAMES: tuple[str, ...] = (
    "us_house",
    "us_senate",
    "us_house_delegate",
    "us_president",
    "us_vice_president",
)


def congressional_boundary_year(election_year: int) -> int:
    """Return the congressional district boundary cycle in effect for a federal election year."""
    return election_year - ((election_year - 2) % 10)


def congressional_boundary_year_for_congress(congress_number: int) -> int:
    """Return the boundary cycle for the election that seated a numbered Congress."""
    if congress_number < 1:
        raise ValueError("congress_number must be positive")
    election_year = 1788 + (2 * (congress_number - 1))
    return congressional_boundary_year(election_year)
