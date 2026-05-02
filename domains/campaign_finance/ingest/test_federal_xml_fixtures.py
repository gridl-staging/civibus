from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "roster"
_HOUSE_FIXTURE = _FIXTURE_DIR / "us_house_member_data_sample.xml"
_SENATE_FIXTURE = _FIXTURE_DIR / "us_senate_contact_information_sample.xml"


@dataclass(frozen=True, slots=True)
class _HouseFixtureRow:
    bioguide_id: str
    member_name: str
    state: str
    district: str
    sworn_date: str
    phone: str


@dataclass(frozen=True, slots=True)
class _SenateFixtureRow:
    bioguide_id: str
    member_full: str
    state: str
    senate_class: str
    phone: str
    email: str
    appointed: str


def _load_root(path: Path) -> ElementTree.Element:
    return ElementTree.fromstring(path.read_text(encoding="utf-8"))


def _parse_house_rows(path: Path) -> list[_HouseFixtureRow]:
    root = _load_root(path)
    rows: list[_HouseFixtureRow] = []
    for node in root.findall("./member"):
        rows.append(
            _HouseFixtureRow(
                bioguide_id=(node.findtext("bioguide_id") or "").strip(),
                member_name=(node.findtext("member_name") or "").strip(),
                state=(node.findtext("state") or "").strip(),
                district=(node.findtext("district") or "").strip(),
                sworn_date=(node.findtext("sworn_date") or "").strip(),
                phone=(node.findtext("phone") or "").strip(),
            )
        )
    return rows


def _parse_senate_rows(path: Path) -> list[_SenateFixtureRow]:
    root = _load_root(path)
    rows: list[_SenateFixtureRow] = []
    for node in root.findall("./member"):
        rows.append(
            _SenateFixtureRow(
                bioguide_id=(node.findtext("bioguide_id") or "").strip(),
                member_full=(node.findtext("member_full") or "").strip(),
                state=(node.findtext("state") or "").strip(),
                senate_class=(node.findtext("class") or "").strip(),
                phone=(node.findtext("phone") or "").strip(),
                email=(node.findtext("email") or "").strip(),
                appointed=(node.findtext("appointed") or "").strip(),
            )
        )
    return rows


def test_house_fixture_exists_and_provides_expected_contract_fields() -> None:
    assert _HOUSE_FIXTURE.exists()

    rows = _parse_house_rows(_HOUSE_FIXTURE)
    assert len(rows) == 2
    assert rows[0] == _HouseFixtureRow(
        bioguide_id="B001234",
        member_name="BROWN, Casey",
        state="NC",
        district="12",
        sworn_date="2025-01-03",
        phone="202-225-1001",
    )
    assert rows[1].member_name == "VACANT"
    assert rows[1].bioguide_id == ""


def test_senate_fixture_exists_and_provides_expected_contract_fields() -> None:
    assert _SENATE_FIXTURE.exists()

    rows = _parse_senate_rows(_SENATE_FIXTURE)
    assert len(rows) == 2
    assert rows[0] == _SenateFixtureRow(
        bioguide_id="S009999",
        member_full="Pat Smith",
        state="GA",
        senate_class="2",
        phone="202-224-1001",
        email="pat_smith@senate.gov",
        appointed="false",
    )
    assert rows[1].member_full == "VACANT"
    assert rows[1].bioguide_id == ""
