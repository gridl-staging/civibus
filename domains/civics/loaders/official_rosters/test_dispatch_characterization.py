from __future__ import annotations

# Stage 1 characterization suite: locks the dispatch contract for
# parse_roster_rows(...) and _resolve_target(...) before Stage 2/3 refactors
# rewire internal dispatch. Assertions are deliberately concrete (exact values,
# not shapes) so a behavior change in either dispatch seam fails this file.

from uuid import uuid4

import pytest

from domains.civics.loaders.official_rosters._test_fixtures import read_fixture
from domains.civics.loaders.official_rosters.loader import _ROSTER_ARTIFACT_DIR, _resolve_target
from domains.civics.loaders.official_rosters.parsers import (
    NormalizedRosterRow,
    parse_roster_rows,
)


_DURHAM_BODY_KEY = "durham_city_council"
_NC_HOUSE_BODY_KEY = "nc_house"
_NC_MUNICIPAL_COUNCIL_BODY_KEY = "nc_municipal_council"
_NC_SCHOOL_BOARD_BODY_KEY = "nc_school_board"
_DURHAM_SOURCE_URL = "https://www.durhamnc.gov/1396/City-Council-Members"
_HOUSE_SOURCE_URL = "https://www.ncleg.gov/Members/MemberList/H"
_APEX_SOURCE_URL = "https://www.apexnc.org/780/Meet-Your-Town-Council"
_WCPSS_SOURCE_URL = "https://www.wcpss.net/fs/pages/571"
_STAGE2_ARTIFACT_DIR = _ROSTER_ARTIFACT_DIR


def _read_stage2_artifact(name: str) -> str:
    return (_STAGE2_ARTIFACT_DIR / name).read_text(encoding="utf-8")


# ----- parser dispatch: durham_city_council -----------------------------------


def test_parse_roster_rows_durham_first_row_concrete_field_values() -> None:
    rows = parse_roster_rows(
        body_key=_DURHAM_BODY_KEY,
        source_url=_DURHAM_SOURCE_URL,
        html=read_fixture("nc_durham_city_council.html"),
    )

    assert len(rows) == 3

    first = rows[0]
    assert first.member_name == "Leonardo Williams"
    assert first.role_label == "Mayor"
    assert first.district_number is None
    assert first.bio_url == "https://www.durhamnc.gov/1329/About-the-Mayor"
    assert first.portrait_url == ("https://www.durhamnc.gov/ImageRepository/Document?documentID=41709&thumbnailSize=2")


def test_parse_roster_rows_durham_council_member_row_role_label_dispatch() -> None:
    # Locks the description-based "City Council Member" override path: link text
    # does not start with "Mayor ", but the description contains "council member".
    rows = parse_roster_rows(
        body_key=_DURHAM_BODY_KEY,
        source_url=_DURHAM_SOURCE_URL,
        html=read_fixture("nc_durham_city_council.html"),
    )

    second = rows[1]
    assert second.member_name == "Javiera Caballero"
    assert second.role_label == "City Council Member"
    assert second.district_number is None
    assert second.bio_url == "https://www.durhamnc.gov/3286/Javiera-Caballero"
    assert second.portrait_url == ("https://www.durhamnc.gov/ImageRepository/Document?documentID=53769&thumbnailSize=2")


# ----- parser dispatch: nc_house ---------------------------------------------


def test_parse_roster_rows_nc_house_first_row_concrete_field_values() -> None:
    rows = parse_roster_rows(
        body_key=_NC_HOUSE_BODY_KEY,
        source_url=_HOUSE_SOURCE_URL,
        html=read_fixture("nc_general_assembly_house.html"),
    )

    assert len(rows) == 3

    first = rows[0]
    assert first.member_name == "Julia C. Howard"
    assert first.role_label == "State Representative District 77"
    assert first.district_number == "77"
    assert first.bio_url == "https://www.ncleg.gov/Members/Biography/H/53"
    assert first.portrait_url == "https://www.ncleg.gov/Members/MemberImage/H/53/Low"


def test_parse_roster_rows_nc_house_role_label_includes_each_district() -> None:
    # Lock the f"State Representative District {n}" formatting for every row,
    # so a refactor that drops the district suffix would fail here.
    rows = parse_roster_rows(
        body_key=_NC_HOUSE_BODY_KEY,
        source_url=_HOUSE_SOURCE_URL,
        html=read_fixture("nc_general_assembly_house.html"),
    )

    assert [(row.member_name, row.district_number, row.role_label) for row in rows] == [
        ("Julia C. Howard", "77", "State Representative District 77"),
        ("Mitchell S. Setzer", "89", "State Representative District 89"),
        ("Becky Carney", "102", "State Representative District 102"),
    ]


# ----- parser dispatch: failure path -----------------------------------------


def test_parse_roster_rows_raises_value_error_for_unsupported_body_key() -> None:
    with pytest.raises(ValueError, match=r"Unsupported body_key for official roster parsing"):
        parse_roster_rows(
            body_key="ca_assembly",
            source_url="https://example.invalid/",
            html="<html></html>",
        )


def test_parse_roster_rows_nc_municipal_council_apex_concrete_outcome() -> None:
    rows = parse_roster_rows(
        body_key=_NC_MUNICIPAL_COUNCIL_BODY_KEY,
        source_url=_APEX_SOURCE_URL,
        html=_read_stage2_artifact("apex_town_council.html"),
    )

    assert [(row.member_name, row.role_label, row.district_number, row.bio_url) for row in rows] == [
        ("Jacques Gilbert", "Mayor", "Apex", None),
        ("Terry Mahaffey", "Mayor Pro Tem", "Apex", None),
        ("Arno Zegerman", "Council Member", "Apex", None),
        ("Edward Gray", "Council Member", "Apex", None),
        ("Shane Reese", "Council Member", "Apex", None),
        ("Sue Mu", "Council Member", "Apex", None),
    ]


def test_parse_roster_rows_nc_school_board_wcpss_concrete_outcome() -> None:
    rows = parse_roster_rows(
        body_key=_NC_SCHOOL_BOARD_BODY_KEY,
        source_url=_WCPSS_SOURCE_URL,
        html=_read_stage2_artifact("wcpss_school_board.html"),
    )

    assert len(rows) == 9
    assert (rows[0].member_name, rows[0].role_label, rows[0].district_number, rows[0].bio_url) == (
        "Tyler Swanson",
        "Chair, District 9",
        "Wake County Public School System",
        "https://www.wcpss.net/board-member-by-school/post/district-9",
    )
    assert (rows[1].member_name, rows[1].role_label, rows[1].district_number, rows[1].bio_url) == (
        "Sam Hershey",
        "Vice-Chair, District 6",
        "Wake County Public School System",
        "https://www.wcpss.net/board-member-by-school/post/district-6",
    )
    assert (rows[2].member_name, rows[2].role_label, rows[2].district_number, rows[2].bio_url) == (
        "Cheryl Caulfield",
        "District 1",
        "Wake County Public School System",
        "https://www.wcpss.net/board-member-by-school/post/district-1",
    )


# ----- target resolution: durham_city_council --------------------------------


def _durham_mayor_row() -> NormalizedRosterRow:
    return NormalizedRosterRow(
        member_name="Leonardo Williams",
        role_label="Mayor",
        district_number=None,
        bio_url="https://www.durhamnc.gov/1329/About-the-Mayor",
        portrait_url=None,
    )


def _durham_council_row() -> NormalizedRosterRow:
    return NormalizedRosterRow(
        member_name="Javiera Caballero",
        role_label="City Council Member",
        district_number=None,
        bio_url="https://www.durhamnc.gov/3286/Javiera-Caballero",
        portrait_url=None,
    )


def test_resolve_target_durham_mayor_emits_mayor_office_and_municipal_division() -> None:
    source_record_id = uuid4()

    target = _resolve_target(_DURHAM_BODY_KEY, _durham_mayor_row(), source_record_id)

    assert target is not None
    assert target.office.name == "durham_nc_mayor"
    assert target.office.office_level == "municipal"
    assert target.office.title == "Mayor"
    assert target.office.state == "NC"
    assert target.office.number_of_seats == 1
    assert target.office.source_record_id == source_record_id

    assert target.electoral_division.name == "nc_municipal_durham"
    assert target.electoral_division.division_type == "municipal"
    assert target.electoral_division.state == "NC"
    assert target.electoral_division.district_number is None
    assert target.electoral_division.source_record_id == source_record_id


def test_resolve_target_durham_council_member_emits_council_office_with_six_seats() -> None:
    source_record_id = uuid4()

    target = _resolve_target(_DURHAM_BODY_KEY, _durham_council_row(), source_record_id)

    assert target is not None
    assert target.office.name == "durham_nc_city_council_member"
    assert target.office.office_level == "municipal"
    assert target.office.title == "City Council Member"
    assert target.office.state == "NC"
    assert target.office.number_of_seats == 6
    assert target.office.source_record_id == source_record_id

    # Council members share one division with the mayor.
    assert target.electoral_division.name == "nc_municipal_durham"
    assert target.electoral_division.division_type == "municipal"
    assert target.electoral_division.state == "NC"
    assert target.electoral_division.district_number is None
    assert target.electoral_division.source_record_id == source_record_id


# ----- target resolution: nc_house -------------------------------------------


def _nc_house_row(district_number: str | None) -> NormalizedRosterRow:
    return NormalizedRosterRow(
        member_name="Julia C. Howard",
        role_label=(
            "State Representative" if district_number is None else f"State Representative District {district_number}"
        ),
        district_number=district_number,
        bio_url="https://www.ncleg.gov/Members/Biography/H/53",
        portrait_url=None,
    )


def test_resolve_target_nc_house_emits_district_specific_division() -> None:
    source_record_id = uuid4()

    target = _resolve_target(_NC_HOUSE_BODY_KEY, _nc_house_row("77"), source_record_id)

    assert target is not None
    assert target.office.name == "nc_house_member"
    assert target.office.office_level == "state"
    assert target.office.title == "State Representative"
    assert target.office.state == "NC"
    assert target.office.number_of_seats == 120
    assert target.office.source_record_id == source_record_id

    assert target.electoral_division.name == "nc_house_district_77"
    assert target.electoral_division.division_type == "state_legislative_lower"
    assert target.electoral_division.state == "NC"
    assert target.electoral_division.district_number == "77"
    assert target.electoral_division.source_record_id == source_record_id


def test_resolve_target_nc_house_returns_none_when_district_number_is_missing() -> None:
    # Locks the unresolved-row contract: missing district must produce None,
    # never an Office/ElectoralDivision pair with a blank district.
    source_record_id = uuid4()

    assert _resolve_target(_NC_HOUSE_BODY_KEY, _nc_house_row(None), source_record_id) is None


def test_resolve_target_nc_house_returns_none_when_district_number_is_blank_whitespace() -> None:
    source_record_id = uuid4()

    blank_row = NormalizedRosterRow(
        member_name="Julia C. Howard",
        role_label="State Representative",
        district_number="   ",
        bio_url="https://www.ncleg.gov/Members/Biography/H/53",
        portrait_url=None,
    )

    assert _resolve_target(_NC_HOUSE_BODY_KEY, blank_row, source_record_id) is None


# ----- target resolution: launch-scope deterministic normalization ----------


@pytest.mark.parametrize(
    ("body_key", "district_number", "expected_office_name", "expected_division_name"),
    (
        ("nc_county_commissioners", "durham", "nc_county_commissioner", "nc_county_durham"),
        ("nc_municipal_council", "raleigh", "nc_municipal_council_member", "nc_municipal_raleigh"),
        (
            "nc_school_board",
            "wake county public school system",
            "nc_school_board_member",
            "nc_school_district_wake_county_public_school_system",
        ),
    ),
)
def test_resolve_target_launch_scope_division_matching_is_case_insensitive(
    body_key: str,
    district_number: str,
    expected_office_name: str,
    expected_division_name: str,
) -> None:
    source_record_id = uuid4()
    row = NormalizedRosterRow(
        member_name="Placeholder Member",
        role_label="Placeholder Role",
        district_number=district_number,
        bio_url=None,
        portrait_url=None,
    )

    target = _resolve_target(body_key, row, source_record_id)

    assert target is not None
    assert target.office.name == expected_office_name
    assert target.electoral_division.name == expected_division_name
    assert target.electoral_division.source_record_id == source_record_id
    assert target.office.source_record_id == source_record_id


def test_resolve_target_nc_municipal_council_apex_source_specific_outcome() -> None:
    source_record_id = uuid4()
    row = NormalizedRosterRow(
        member_name="Jacques Gilbert",
        role_label="Mayor",
        district_number="Apex",
        bio_url=None,
        portrait_url=None,
    )

    target = _resolve_target(_NC_MUNICIPAL_COUNCIL_BODY_KEY, row, source_record_id)

    assert target is not None
    assert target.office.name == "nc_municipal_council_member"
    assert target.office.title == "Council Member"
    assert target.office.office_level == "municipal"
    assert target.office.number_of_seats == 6
    assert target.electoral_division.name == "nc_municipal_apex"
    assert target.electoral_division.division_type == "municipal"
    assert target.electoral_division.state == "NC"
    assert target.electoral_division.district_number == "Apex"


def test_resolve_target_nc_school_board_wcpss_source_specific_outcome() -> None:
    source_record_id = uuid4()
    row = NormalizedRosterRow(
        member_name="Tyler Swanson",
        role_label="Chair, District 9",
        district_number="Wake County Public School System",
        bio_url="https://www.wcpss.net/board-member-by-school/post/district-9",
        portrait_url=None,
    )

    target = _resolve_target(_NC_SCHOOL_BOARD_BODY_KEY, row, source_record_id)

    assert target is not None
    assert target.office.name == "nc_school_board_member"
    assert target.office.title == "School Board Member"
    assert target.office.office_level == "school_board"
    assert target.office.number_of_seats == 9
    assert target.electoral_division.name == "nc_school_district_wake_county_public_school_system"
    assert target.electoral_division.division_type == "school_district"
    assert target.electoral_division.state == "NC"
    assert target.electoral_division.district_number == "Wake County Public School System"


# ----- target resolution: failure path ---------------------------------------


def test_resolve_target_raises_value_error_for_unsupported_body_key() -> None:
    source_record_id = uuid4()

    with pytest.raises(ValueError, match=r"Unsupported body_key target mapping"):
        _resolve_target(
            "ca_assembly",
            _nc_house_row("1"),
            source_record_id,
        )
