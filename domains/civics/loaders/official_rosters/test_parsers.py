from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

import pytest

from domains.civics.loaders.official_rosters.parsers import parse_roster_rows
from domains.civics.loaders.official_rosters.loader import _ROSTER_ARTIFACT_DIR
from domains.civics.tests.statewide_roster_stage5_support import (
    EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE,
    fixture_for_source_id,
    stage5_sources_by_id,
)


_DURHAM_SOURCE_URL = "https://www.durhamnc.gov/1396/City-Council-Members"
_HOUSE_SOURCE_URL = "https://www.ncleg.gov/Members/MemberList/H"
_NC_SHERIFFS_SOURCE_URL = "https://ncsheriffs.org/find-a-sheriff"
_FIXTURE_DIR = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "roster"
_STAGE2_ARTIFACT_DIR = _ROSTER_ARTIFACT_DIR
_MANIFEST_PATH = _STAGE2_ARTIFACT_DIR / "canonical_seat_manifest.json"
_EXPECTED_STAGE5_SINGLETON_NAMES = {
    "nc_gov": "Josh Stein",
    "nc_lt_gov": "Rachel Hunt",
    "nc_attorney_general": "Jeff Jackson",
    "nc_sec_of_state": "Elaine Marshall",
    "nc_treasurer": "Bradford B. Briner",
    "nc_auditor": "Dave Boliek",
    "nc_supt_pub_instr": "Maurice “Mo” Green",
    "nc_ag_commissioner": "Steve Troxler",
    "nc_ins_commissioner": "Mike Causey",
    "nc_labor_commissioner": "Luke Farley",
}
_EXPECTED_STAGE5_JUDICIAL_NAMES = {
    "nc_supreme_court": {"Paul Newby", "Anita Earls", "Philip Berger Jr", "Tamara Barringer"},
    "nc_court_of_appeals": {"John Tyson", "John Arrowood", "Chris Dillon", "Donna Stroud"},
}
_NORMALIZED_ROSTER_ROW_CONTRACT_KEYS = (
    "bio_url",
    "bioguide_id",
    "district_number",
    "member_name",
    "portrait_url",
    "role_label",
)


def _read_fixture(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


def _manifest_sources() -> dict[str, dict[str, object]]:
    payload = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {source["source_id"]: source for source in payload["sources"]}


def _read_stage2_artifact(name: str) -> str:
    return (_STAGE2_ARTIFACT_DIR / name).read_text(encoding="utf-8")


def _manifest_sources_by_body_key(body_key: str) -> list[dict[str, object]]:
    return [source for source in _manifest_sources().values() if source.get("body_key") == body_key]


def _effective_port_from_url(value: str) -> int | None:
    parsed_value = urlparse(value)
    if parsed_value.port is not None:
        return parsed_value.port
    if parsed_value.scheme == "https":
        return 443
    if parsed_value.scheme == "http":
        return 80
    return None


def _assert_same_origin_url(value: str, *, source_url: str) -> None:
    parsed_value = urlparse(value)
    parsed_source = urlparse(source_url)
    assert parsed_value.scheme == parsed_source.scheme
    assert parsed_value.hostname == parsed_source.hostname
    assert _effective_port_from_url(value) == _effective_port_from_url(source_url)


def test_parse_durham_member_cards_to_shared_row_contract() -> None:
    rows = parse_roster_rows(
        body_key="durham_city_council",
        source_url=_DURHAM_SOURCE_URL,
        html=_read_fixture("nc_durham_city_council.html"),
    )

    assert len(rows) == 3
    assert {tuple(sorted(asdict(row).keys())) for row in rows} == {_NORMALIZED_ROSTER_ROW_CONTRACT_KEYS}
    assert rows[0].member_name == "Leonardo Williams"
    assert rows[0].role_label == "Mayor"
    assert rows[0].bio_url == "https://www.durhamnc.gov/1329/About-the-Mayor"
    assert rows[0].portrait_url == (
        "https://www.durhamnc.gov/ImageRepository/Document?documentID=41709&thumbnailSize=2"
    )
    assert rows[0].district_number is None
    _assert_same_origin_url(rows[0].bio_url, source_url=_DURHAM_SOURCE_URL)
    _assert_same_origin_url(rows[0].portrait_url, source_url=_DURHAM_SOURCE_URL)


def test_parse_durham_rows_drop_off_origin_profile_and_portrait_links() -> None:
    rows = parse_roster_rows(
        body_key="durham_city_council",
        source_url=_DURHAM_SOURCE_URL,
        html="""
        <li class="megaMenuItem widgetItem mediaLeft">
          <div class="widgetTitle">
            <a href="https://evil.example/profile">Mayor Jane Doe</a>
          </div>
          <p class="widgetDesc">Mayor</p>
          <img class="media" src="https://evil.example/portrait.jpg" />
        </li>
        """,
    )

    assert len(rows) == 1
    assert rows[0].bio_url is None
    assert rows[0].portrait_url is None


def test_parse_nc_house_rows_to_shared_row_contract_with_district() -> None:
    rows = parse_roster_rows(
        body_key="nc_house",
        source_url=_HOUSE_SOURCE_URL,
        html=_read_fixture("nc_general_assembly_house.html"),
    )

    assert len(rows) == 3
    assert {tuple(sorted(asdict(row).keys())) for row in rows} == {_NORMALIZED_ROSTER_ROW_CONTRACT_KEYS}
    assert rows[0].member_name == "Julia C. Howard"
    assert rows[0].role_label == "State Representative District 77"
    assert rows[0].district_number == "77"
    assert rows[0].bio_url == "https://www.ncleg.gov/Members/Biography/H/53"
    assert rows[0].portrait_url == "https://www.ncleg.gov/Members/MemberImage/H/53/Low"

    malicious_rows = parse_roster_rows(
        body_key="nc_house",
        source_url=_HOUSE_SOURCE_URL,
        html="""
        <div class="member-col">
          <div class="member-info-col">
            <a href="https://evil.example/Members/Biography/H/666">Injected Member</a>
            <a href="/Redistricting/DistrictPlanMap/77">District 77</a>
          </div>
          <div class="member-image-col">
            <img src="javascript:alert(1)" />
          </div>
        </div>
        """,
    )

    assert len(malicious_rows) == 1
    assert malicious_rows[0].bio_url is None
    assert malicious_rows[0].portrait_url is None


def test_parse_nc_sheriffs_rows_to_shared_row_contract_with_county_carried_in_district() -> None:
    rows = parse_roster_rows(
        body_key="nc_sheriffs",
        source_url=_NC_SHERIFFS_SOURCE_URL,
        html=_read_fixture("nc_sheriffs_directory.html"),
    )

    assert len(rows) >= 3
    assert {tuple(sorted(asdict(row).keys())) for row in rows} == {_NORMALIZED_ROSTER_ROW_CONTRACT_KEYS}
    assert rows[0].member_name == "Terry S. Johnson"
    assert rows[0].role_label == "Sheriff"
    assert rows[0].district_number == "Alamance"
    assert rows[0].bio_url == "https://ncsheriffs.org/people/terry-s-johnson"
    assert rows[0].portrait_url is None
    assert rows[1].member_name == "Chad Pennell"
    assert rows[1].district_number == "Alexander"
    assert rows[1].bio_url == "https://ncsheriffs.org/people/chad-pennell"
    assert rows[2].member_name == "Shane Glenn"
    assert rows[2].district_number == "Alleghany"
    assert rows[2].bio_url == "https://ncsheriffs.org/people/bryan-maines"


def test_parse_nc_sheriffs_rows_drop_off_origin_profile_links() -> None:
    rows = parse_roster_rows(
        body_key="nc_sheriffs",
        source_url=_NC_SHERIFFS_SOURCE_URL,
        html="""
        <div class="partial-container">
          <h2 class="title"><a class="link" href="https://evil.example/profile">Sheriff Jane Doe</a></h2>
          <p class="county">Wake</p>
        </div>
        """,
    )

    assert len(rows) == 1
    assert rows[0].member_name == "Jane Doe"
    assert rows[0].district_number == "Wake"
    assert rows[0].bio_url is None


def test_parse_stage2_registers_of_deeds_rows_use_manifest_member_count() -> None:
    source = _manifest_sources()["nc_registers_of_deeds_roster"]
    rows = parse_roster_rows(
        body_key=str(source["body_key"]),
        source_url=str(source["source_url"]),
        html=_read_stage2_artifact("nc_registers_of_deeds_directory.html"),
    )

    assert source["member_count"] == 100
    assert rows == []


def test_parse_stage2_county_commissioner_rows_from_three_counties() -> None:
    manifest_sources = _manifest_sources()
    expected = {
        "nc_durham_county_commissioners_roster": "Durham",
        "nc_wake_county_commissioners_roster": "Wake",
        "nc_orange_county_commissioners_roster": "Orange",
    }

    for source_id, county_name in expected.items():
        source = manifest_sources[source_id]
        html_name = Path(str(source["artifact_path"])).name
        rows = parse_roster_rows(
            body_key=str(source["body_key"]),
            source_url=str(source["source_url"]),
            html=_read_stage2_artifact(html_name),
        )

        assert len(rows) == source["member_count"]
        assert {tuple(sorted(asdict(row).keys())) for row in rows} == {_NORMALIZED_ROSTER_ROW_CONTRACT_KEYS}
        assert all(row.role_label == "County Commissioner" for row in rows)
        assert all(row.district_number == county_name for row in rows)

    orange_rows = parse_roster_rows(
        body_key=str(manifest_sources["nc_orange_county_commissioners_roster"]["body_key"]),
        source_url=str(manifest_sources["nc_orange_county_commissioners_roster"]["source_url"]),
        html=_read_stage2_artifact("orange_county_commissioners.html"),
    )
    assert [row.member_name for row in orange_rows] == [
        "Jean Hamilton",
        "Amy Fowler",
        "Jamezetta Bedford",
        "Marilyn Carter",
        "Sally Greene",
        "Earl McKee",
        "Phyllis Portie-Ascott",
    ]
    assert sum(1 for row in orange_rows if row.bio_url is None) == 1
    assert all(row.bio_url is None or row.bio_url.startswith("https://www.orangecountync.gov/") for row in orange_rows)


def test_parse_stage2_county_commissioner_rows_drop_off_origin_links() -> None:
    rows = parse_roster_rows(
        body_key="nc_county_commissioners",
        source_url="https://www.orangecountync.gov/953/Board-of-County-Commissioners-BOCC",
        html="""
        <h2>Meet the Commissioners</h2>
        <ul>
          <li><a href="https://evil.example/commissioners/jane-doe">Jane Doe, Chair</a></li>
        </ul>
        """,
    )

    assert len(rows) == 1
    assert rows[0].member_name == "Jane Doe"
    assert rows[0].district_number == "Orange"
    assert rows[0].bio_url is None


def test_parse_stage2_soil_water_rows_use_manifest_member_count_and_labels() -> None:
    source = _manifest_sources()["nc_soil_water_supervisors_roster"]
    rows = parse_roster_rows(
        body_key=str(source["body_key"]),
        source_url=str(source["source_url"]),
        html=_read_stage2_artifact("nc_soil_water_supervisors_directory.html"),
    )

    assert len(rows) == source["member_count"]
    assert all(row.role_label == "Soil and Water Supervisor" for row in rows)
    assert rows[0].district_number is not None
    assert rows[0].member_name == "David Michael Spruill"
    assert rows[1].member_name == "Richard N. Reid"
    assert rows[2].member_name == "Donna Vanhook"
    assert all("Supervisor " not in row.member_name for row in rows[:25])
    assert "George Tarkington" in {row.member_name for row in rows if row.district_number == "Camden"}
    assert "Abner Wayne Staples" in {row.member_name for row in rows if row.district_number == "Camden"}
    assert "Don Lee Keaton" in {row.member_name for row in rows if row.district_number == "Camden"}
    assert all(
        not row.member_name.startswith(("Secretary-Treasurer ", "Chair ", "Vice Chair ", "Vice-Chair ")) for row in rows
    )


def test_parse_roster_rows_rejects_unknown_body_key() -> None:
    with pytest.raises(ValueError, match="Unsupported body_key"):
        parse_roster_rows(body_key="unknown", source_url="https://example.com", html="<html></html>")


@pytest.mark.parametrize("source", _manifest_sources_by_body_key("nc_municipal_council"))
def test_parse_stage3_municipal_rows_from_manifest(source: dict[str, object]) -> None:
    html_name = Path(str(source["artifact_path"])).name
    rows = parse_roster_rows(
        body_key=str(source["body_key"]),
        source_url=str(source["source_url"]),
        html=_read_stage2_artifact(html_name),
    )

    assert len(rows) == int(source["member_count"])
    assert all("Council Seat " not in row.member_name for row in rows)
    assert all(row.role_label.strip() != "" for row in rows)
    assert all(row.district_number == str(source["division_name"]) for row in rows)
    for row in rows:
        if row.bio_url is None:
            continue
        _assert_same_origin_url(row.bio_url, source_url=str(source["source_url"]))
        assert Path(row.bio_url).name != ""


def test_parse_stage3_apex_municipal_rows_have_concrete_member_and_role_values() -> None:
    source = _manifest_sources()["nc_apex_town_council_roster"]
    html_name = Path(str(source["artifact_path"])).name
    rows = parse_roster_rows(
        body_key=str(source["body_key"]),
        source_url=str(source["source_url"]),
        html=_read_stage2_artifact(html_name),
    )

    assert len(rows) == int(source["member_count"]) == 6
    assert [(row.member_name, row.role_label, row.district_number) for row in rows] == [
        ("Jacques Gilbert", "Mayor", "Apex"),
        ("Terry Mahaffey", "Mayor Pro Tem", "Apex"),
        ("Arno Zegerman", "Council Member", "Apex"),
        ("Edward Gray", "Council Member", "Apex"),
        ("Shane Reese", "Council Member", "Apex"),
        ("Sue Mu", "Council Member", "Apex"),
    ]
    assert all(row.bio_url is None for row in rows)


@pytest.mark.parametrize("source", _manifest_sources_by_body_key("nc_school_board"))
def test_parse_stage3_school_board_rows_from_manifest(source: dict[str, object]) -> None:
    html_name = Path(str(source["artifact_path"])).name
    rows = parse_roster_rows(
        body_key=str(source["body_key"]),
        source_url=str(source["source_url"]),
        html=_read_stage2_artifact(html_name),
    )

    assert len(rows) == int(source["member_count"])
    assert all(" Board Seat " not in row.member_name for row in rows)
    assert all(row.role_label.strip() != "" for row in rows)
    assert all(row.district_number == str(source["division_name"]) for row in rows)
    if str(source["source_id"]) in {"nc_dps_school_board_roster", "nc_wcpss_school_board_roster"}:
        assert any("district" in row.role_label.lower() or "at-large" in row.role_label.lower() for row in rows)
    for row in rows:
        if row.bio_url is None:
            continue
        _assert_same_origin_url(row.bio_url, source_url=str(source["source_url"]))


def test_parse_stage3_wcpss_school_board_rows_have_concrete_member_and_role_values() -> None:
    source = _manifest_sources()["nc_wcpss_school_board_roster"]
    html_name = Path(str(source["artifact_path"])).name
    rows = parse_roster_rows(
        body_key=str(source["body_key"]),
        source_url=str(source["source_url"]),
        html=_read_stage2_artifact(html_name),
    )

    assert len(rows) == int(source["member_count"]) == 9
    assert [(row.member_name, row.role_label, row.district_number) for row in rows[:3]] == [
        ("Tyler Swanson", "Chair, District 9", "Wake County Public School System"),
        ("Sam Hershey", "Vice-Chair, District 6", "Wake County Public School System"),
        ("Cheryl Caulfield", "District 1", "Wake County Public School System"),
    ]
    assert rows[0].bio_url == "https://www.wcpss.net/board-member-by-school/post/district-9"
    assert rows[1].bio_url == "https://www.wcpss.net/board-member-by-school/post/district-6"
    assert rows[2].bio_url == "https://www.wcpss.net/board-member-by-school/post/district-1"


def test_parse_stage3_dps_school_board_rows_preserve_manifest_count_and_unicode_names() -> None:
    source = _manifest_sources()["nc_dps_school_board_roster"]
    html_name = Path(str(source["artifact_path"])).name
    rows = parse_roster_rows(
        body_key=str(source["body_key"]),
        source_url=str(source["source_url"]),
        html=_read_stage2_artifact(html_name),
    )

    assert len(rows) == int(source["member_count"])
    assert "Emily Chávez" in {row.member_name for row in rows}
    assert any("district" in row.role_label.lower() or "at-large" in row.role_label.lower() for row in rows)


@pytest.mark.parametrize(
    ("body_key", "source_url"),
    (
        ("nc_municipal_council", "https://raleighnc.gov/city-council"),
        ("nc_school_board", "https://www.wcpss.net/Page/117"),
    ),
)
def test_parse_stage3_rows_drop_off_origin_absolute_bio_links(body_key: str, source_url: str) -> None:
    rows = parse_roster_rows(
        body_key=body_key,
        source_url=source_url,
        html="""
        <a href="https://evil.example/bio">Council Member Jane Doe</a>
        """,
    )

    assert len(rows) == 1
    assert rows[0].bio_url is None


@pytest.mark.parametrize(
    ("body_key", "source_url", "candidate_link"),
    (
        (
            "nc_municipal_council",
            "https://raleighnc.gov/city-council",
            "https://raleighnc.gov:444/council/jane-doe",
        ),
        (
            "nc_school_board",
            "https://www.wcpss.net/Page/117",
            "https://www.wcpss.net:444/Page/member-bio",
        ),
    ),
)
def test_parse_stage3_rows_drop_same_host_alternate_port_bio_links(
    body_key: str, source_url: str, candidate_link: str
) -> None:
    rows = parse_roster_rows(
        body_key=body_key,
        source_url=source_url,
        html=f'<a href="{candidate_link}">Council Member Jane Doe</a>',
    )

    assert len(rows) == 1
    assert rows[0].bio_url is None


@pytest.mark.parametrize("source_id,expected_count", EXPECTED_OFFICEHOLDING_COUNTS_BY_SOURCE.items())
def test_parse_stage5_statewide_sources_match_expected_member_counts(
    source_id: str,
    expected_count: int,
    tmp_path: Path,
) -> None:
    template = stage5_sources_by_id()[source_id]
    fixture = fixture_for_source_id(source_id, tmp_path)
    rows = parse_roster_rows(
        body_key=template.body_key,
        source_url=template.source_url,
        html=fixture.read_text(encoding="utf-8"),
    )

    assert len(rows) == expected_count
    if source_id in _EXPECTED_STAGE5_SINGLETON_NAMES:
        assert [row.member_name for row in rows] == [_EXPECTED_STAGE5_SINGLETON_NAMES[source_id]]
    if source_id in _EXPECTED_STAGE5_JUDICIAL_NAMES:
        parsed_names = {row.member_name for row in rows}
        assert _EXPECTED_STAGE5_JUDICIAL_NAMES[source_id] <= parsed_names
    assert all(row.member_name.strip(".,;:") == row.member_name for row in rows)


# ----- federal roster parsing against REAL upstream XML structure --------------
# Stage 2 repair: the House Clerk and Senate contact feeds wrap members under
# <members> and encode the senate class as "Class II"/"Class III". These fixtures
# mirror the live upstream shape (not the synthetic snapshot shape) so the parser
# is verified against real external behavior rather than a hand-built stand-in.

_US_HOUSE_SOURCE_URL = "https://clerk.house.gov/xml/lists/MemberData.xml"
_US_SENATE_SOURCE_URL = "https://www.senate.gov/general/contact_information/senators_cfm.xml"

_REAL_HOUSE_MEMBER_DATA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MemberData>
  <members>
    <member>
      <statedistrict>NC01</statedistrict>
      <member-info>
        <bioguideID>D000230</bioguideID>
        <firstname>Donald</firstname>
        <lastname>Davis</lastname>
        <state postal-code="NC"><state-fullname>North Carolina</state-fullname></state>
        <district>1st</district>
      </member-info>
    </member>
    <member>
      <statedistrict>NC02</statedistrict>
      <member-info>
        <bioguideID>R000305</bioguideID>
        <firstname>Deborah</firstname>
        <lastname>Ross</lastname>
        <state postal-code="NC"><state-fullname>North Carolina</state-fullname></state>
        <district>2nd</district>
      </member-info>
    </member>
    <member>
      <statedistrict>VA01</statedistrict>
      <member-info>
        <bioguideID>W000825</bioguideID>
        <firstname>Robert</firstname>
        <lastname>Wittman</lastname>
        <state postal-code="VA"><state-fullname>Virginia</state-fullname></state>
        <district>1st</district>
      </member-info>
    </member>
  </members>
</MemberData>
"""

_REAL_SENATE_CONTACT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<contact_information>
  <member>
    <member_full>Tillis (R-NC)</member_full>
    <last_name>Tillis</last_name>
    <first_name>Thom</first_name>
    <party>R</party>
    <state>NC</state>
    <website>https://tillis.senate.gov</website>
    <class>Class II</class>
    <bioguide_id>T000476</bioguide_id>
  </member>
  <member>
    <member_full>Budd (R-NC)</member_full>
    <last_name>Budd</last_name>
    <first_name>Ted</first_name>
    <party>R</party>
    <state>NC</state>
    <website>https://budd.senate.gov</website>
    <class>Class III</class>
    <bioguide_id>B001305</bioguide_id>
  </member>
  <member>
    <member_full>Warner (D-VA)</member_full>
    <last_name>Warner</last_name>
    <first_name>Mark</first_name>
    <party>D</party>
    <state>VA</state>
    <website>https://warner.senate.gov</website>
    <class>Class II</class>
    <bioguide_id>W000805</bioguide_id>
  </member>
</contact_information>
"""


def test_parse_us_house_nc_rows_from_real_members_wrapper_structure() -> None:
    rows = parse_roster_rows(
        body_key="us_house_nc",
        source_url=_US_HOUSE_SOURCE_URL,
        html=_REAL_HOUSE_MEMBER_DATA_XML,
    )

    assert [(row.member_name, row.district_number, row.role_label, row.bioguide_id) for row in rows] == [
        ("Donald Davis", "1", "United States Representative District 1", "D000230"),
        ("Deborah Ross", "2", "United States Representative District 2", "R000305"),
    ]


def test_parse_us_senate_class_ii_row_from_real_class_label_structure() -> None:
    rows = parse_roster_rows(
        body_key="us_senate_nc_class_ii",
        source_url=_US_SENATE_SOURCE_URL,
        html=_REAL_SENATE_CONTACT_XML,
    )

    assert [(row.member_name, row.role_label, row.district_number, row.bioguide_id) for row in rows] == [
        ("Thom Tillis", "United States Senator", "Class 2", "T000476"),
    ]
    assert rows[0].bio_url == "https://tillis.senate.gov"

    unsafe_rows = parse_roster_rows(
        body_key="us_senate_nc_class_ii",
        source_url=_US_SENATE_SOURCE_URL,
        html=_REAL_SENATE_CONTACT_XML.replace("https://tillis.senate.gov", "javascript:alert(document.domain)"),
    )
    assert unsafe_rows[0].bio_url is None


def test_parse_us_senate_class_iii_row_from_real_class_label_structure() -> None:
    rows = parse_roster_rows(
        body_key="us_senate_nc_class_iii",
        source_url=_US_SENATE_SOURCE_URL,
        html=_REAL_SENATE_CONTACT_XML,
    )

    assert [(row.member_name, row.role_label, row.district_number, row.bioguide_id) for row in rows] == [
        ("Ted Budd", "United States Senator", "Class 3", "B001305"),
    ]


# ----- JS render-error shell rejection -----------------------------------------
# Some roster pages (Finalsite/Wix-style) are JS-rendered and return a 200 error
# shell to the static fetch path: "A required part of this site couldn't load...".
# The generic HTML parsers must not scrape that error paragraph as an officeholder,
# which previously manufactured a fake person and caused a name-only false merge
# across unrelated sources.

_DPS_RENDER_ERROR_SHELL_HTML = """
<html><body>
  <div class="card-content-container">
    <div class="card-heading">
      <h3>A required part of this site couldn’t load. This may be due to a browser extension, network issues, or browser settings.</h3>
    </div>
    <div class="card-text">School Board Member network issues</div>
  </div>
</body></html>
"""


def test_parse_school_board_rows_drop_js_render_error_shell_rows() -> None:
    rows = parse_roster_rows(
        body_key="nc_school_board",
        source_url="https://www.dpsnc.net/domain/71",
        html=_DPS_RENDER_ERROR_SHELL_HTML,
    )
    assert rows == []
