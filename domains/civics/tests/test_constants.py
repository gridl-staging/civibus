"""Contract tests for shared civic domain constants.

``USPS_TO_STATE_NAME`` exists so federal contest display names can read
"North Carolina 9th Congressional District" instead of the FEC wire code
``NC``. It is only trustworthy if it covers exactly the same jurisdictions the
repo already recognises, so the coverage invariant is pinned against the
long-standing FIPS map rather than restated as a second hand-written list.
"""

from __future__ import annotations

from domains.civics.constants import (
    CENSUS_STATE_FIPS_TO_USPS,
    US_HOUSE_NON_VOTING_SEAT_TITLES,
    USPS_TO_STATE_NAME,
)


def test_state_name_map_covers_exactly_the_recognised_usps_codes() -> None:
    """Every jurisdiction the FIPS map knows has a display name, and no extras."""
    fips_map_codes = {usps for _fips, usps in CENSUS_STATE_FIPS_TO_USPS}

    assert set(USPS_TO_STATE_NAME) == fips_map_codes
    assert len(USPS_TO_STATE_NAME) == 56


def test_state_names_are_the_official_spellings() -> None:
    """Spot-check the values that federal contest names render most often."""
    assert USPS_TO_STATE_NAME["NC"] == "North Carolina"
    assert USPS_TO_STATE_NAME["CA"] == "California"
    assert USPS_TO_STATE_NAME["DC"] == "District of Columbia"
    assert USPS_TO_STATE_NAME["PR"] == "Puerto Rico"
    assert USPS_TO_STATE_NAME["MP"] == "Northern Mariana Islands"


def test_non_voting_seat_titles_cover_the_six_delegate_jurisdictions() -> None:
    """FEC files delegates as House district 00; their seat titles differ from a state's.

    Calling Puerto Rico's seat a "Congressional District" would be factually
    wrong on a site whose pitch is source-linked accuracy, so the six
    non-voting jurisdictions carry their real seat titles.
    """
    assert set(US_HOUSE_NON_VOTING_SEAT_TITLES) == {"AS", "DC", "GU", "MP", "PR", "VI"}
    assert US_HOUSE_NON_VOTING_SEAT_TITLES["PR"] == "Resident Commissioner"
    assert US_HOUSE_NON_VOTING_SEAT_TITLES["DC"] == "Delegate to the U.S. House"
