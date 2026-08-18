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

# Display spellings for every jurisdiction CENSUS_STATE_FIPS_TO_USPS recognises.
# FEC bulk files carry only the two-letter code, so this is what turns a wire
# value like "NC" into the "North Carolina 9th Congressional District" a reader
# (and a search engine) can actually use. domains/civics/tests/test_constants.py
# pins coverage against the FIPS map so the two never drift apart.
USPS_TO_STATE_NAME: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "AS": "American Samoa",
    "GU": "Guam",
    "MP": "Northern Mariana Islands",
    "PR": "Puerto Rico",
    "VI": "U.S. Virgin Islands",
}

# FEC bulk files model every non-voting seat as House office code "H" with
# district "00", which is indistinguishable on the wire from a state's at-large
# district. These six are not congressional districts and must not be labelled
# as such: five send a Delegate, Puerto Rico sends a Resident Commissioner.
US_HOUSE_NON_VOTING_SEAT_TITLES: dict[str, str] = {
    "AS": "Delegate to the U.S. House",
    "DC": "Delegate to the U.S. House",
    "GU": "Delegate to the U.S. House",
    "MP": "Delegate to the U.S. House",
    "VI": "Delegate to the U.S. House",
    "PR": "Resident Commissioner",
}

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
