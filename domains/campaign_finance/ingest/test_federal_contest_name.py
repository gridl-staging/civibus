"""Unit tests for the federal contest display-name owner.

Why this exists: `civic.contest` keys on (office, electoral_division, date,
type), so all 52 California House races are distinct rows — but the stored
`name` used to omit the district, rendering every one of them as the identical
string "H CA General 2026". Election lists, search results, page titles and
structured data all read that one column, so a non-unique name made the whole
race surface unusable.

These are pure-function tests deliberately kept out of the integration tier:
the naming rules are closed and hand-checkable, and a fast red/green loop is
what keeps them honest.
"""

from __future__ import annotations

import pytest

from domains.campaign_finance.ingest.fec_canonical_loader import federal_contest_display_name


class TestHouseDistrictNames:
    """A district number is the only thing distinguishing two House races in a state."""

    @pytest.mark.parametrize(
        ("district", "expected"),
        (
            ("01", "North Carolina 1st Congressional District — 2024 General Election"),
            ("02", "North Carolina 2nd Congressional District — 2024 General Election"),
            ("03", "North Carolina 3rd Congressional District — 2024 General Election"),
            ("04", "North Carolina 4th Congressional District — 2024 General Election"),
            ("09", "North Carolina 9th Congressional District — 2024 General Election"),
            # 11th/12th/13th are the ordinal suffix trap: they take "th", not
            # "st"/"nd"/"rd", even though they end in 1/2/3.
            ("11", "North Carolina 11th Congressional District — 2024 General Election"),
            ("12", "North Carolina 12th Congressional District — 2024 General Election"),
            ("13", "North Carolina 13th Congressional District — 2024 General Election"),
            ("21", "North Carolina 21st Congressional District — 2024 General Election"),
            ("22", "North Carolina 22nd Congressional District — 2024 General Election"),
            ("23", "North Carolina 23rd Congressional District — 2024 General Election"),
        ),
    )
    def test_district_ordinals(self, district: str, expected: str) -> None:
        assert (
            federal_contest_display_name(office_code="H", state="NC", district=district, election_year=2024) == expected
        )

    def test_unpadded_district_matches_padded(self) -> None:
        """FEC rows carry both "1" and "01"; both name the same seat."""
        padded = federal_contest_display_name(office_code="H", state="CA", district="01", election_year=2026)
        unpadded = federal_contest_display_name(office_code="H", state="CA", district="1", election_year=2026)
        assert padded == unpadded == "California 1st Congressional District — 2026 General Election"

    def test_every_california_house_district_gets_a_distinct_name(self) -> None:
        """The defect this owner exists to prevent, asserted directly."""
        names = {
            federal_contest_display_name(office_code="H", state="CA", district=f"{number:02d}", election_year=2026)
            for number in range(1, 53)
        }
        assert len(names) == 52


class TestAtLargeAndNonVotingSeats:
    def test_state_at_large_district_is_named_at_large(self) -> None:
        """Single-district states file as district 00."""
        assert (
            federal_contest_display_name(office_code="H", state="WY", district="00", election_year=2026)
            == "Wyoming At-Large Congressional District — 2026 General Election"
        )

    def test_missing_district_falls_back_to_at_large(self) -> None:
        assert (
            federal_contest_display_name(office_code="H", state="AK", district=None, election_year=2026)
            == "Alaska At-Large Congressional District — 2026 General Election"
        )

    def test_delegate_seats_are_not_called_congressional_districts(self) -> None:
        """DC/AS/GU/MP/VI send Delegates; calling their seat a district is false."""
        assert (
            federal_contest_display_name(office_code="H", state="DC", district="00", election_year=2026)
            == "District of Columbia Delegate to the U.S. House — 2026 General Election"
        )

    def test_puerto_rico_seat_is_the_resident_commissioner(self) -> None:
        assert (
            federal_contest_display_name(office_code="H", state="PR", district="00", election_year=2026)
            == "Puerto Rico Resident Commissioner — 2026 General Election"
        )


class TestSenateAndPresident:
    def test_senate_name_is_statewide(self) -> None:
        assert (
            federal_contest_display_name(office_code="S", state="GA", district=None, election_year=2026)
            == "Georgia U.S. Senate — 2026 General Election"
        )

    def test_senate_ignores_a_stray_district_value(self) -> None:
        """Senate seats are statewide; a district on the row is noise, not identity."""
        assert federal_contest_display_name(
            office_code="S", state="GA", district="07", election_year=2026
        ) == federal_contest_display_name(office_code="S", state="GA", district=None, election_year=2026)

    def test_president_has_no_state(self) -> None:
        assert (
            federal_contest_display_name(office_code="P", state="US", district=None, election_year=2028)
            == "U.S. President — 2028 General Election"
        )


class TestDegradedInputs:
    """Names must stay distinct even when the FEC row is incomplete."""

    def test_unknown_state_code_is_preserved_verbatim(self) -> None:
        """An unmapped code still identifies the race; dropping it would collide."""
        assert (
            federal_contest_display_name(office_code="H", state="ZZ", district="04", election_year=2026)
            == "ZZ 4th Congressional District — 2026 General Election"
        )

    def test_missing_state_keeps_the_chamber(self) -> None:
        assert (
            federal_contest_display_name(office_code="S", state=None, district=None, election_year=2026)
            == "U.S. Senate — 2026 General Election"
        )

    def test_unknown_office_code_still_produces_a_dated_name(self) -> None:
        assert (
            federal_contest_display_name(office_code="X", state="NC", district=None, election_year=2026)
            == "North Carolina X — 2026 General Election"
        )
