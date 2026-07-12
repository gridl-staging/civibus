"""Unit + integration tests for the congress-legislators YAML row adapter.

The adapter transforms entries from
https://github.com/unitedstates/congress-legislators (legislators-current.yaml +
executive.yaml) into the row-dict contract consumed by
federal_officeholder_loader.load_federal_house_officeholders /
load_federal_senate_officeholders, plus distinct delegate / president / VP buckets
for Stage 3 spine ingest.
"""

from __future__ import annotations

import subprocess
from datetime import date

import pytest

from domains.campaign_finance.ingest import congress_legislators_adapter as adapter_module
from domains.campaign_finance.ingest.congress_legislators_adapter import (
    AdaptedLegislators,
    HistoricalPredecessors,
    adapt_legislators_yaml,
    select_most_recent_vacancy_predecessors,
)
from domains.campaign_finance.ingest.federal_officeholder_loader import (
    OFFICE_US_HOUSE_DELEGATE,
)


# ---------------------------------------------------------------------------
# Hand-built fixture dicts shaped like the live YAML
# ---------------------------------------------------------------------------


def _house_member_fixture() -> dict:
    # Real-world example: a House rep with bioguide + two FEC IDs.
    return {
        "id": {
            "bioguide": "P000197",
            "fec": ["H8CA08049", "H0CA12041"],
            "govtrack": 400314,
            "wikidata": "Q170581",
        },
        "name": {
            "first": "Nancy",
            "last": "Pelosi",
            "official_full": "Nancy Pelosi",
        },
        "bio": {"birthday": "1940-03-26", "gender": "F"},
        "terms": [
            {
                "type": "rep",
                "start": "1987-06-02",
                "end": "1989-01-03",
                "state": "CA",
                "district": 5,
                "party": "Democrat",
            },
            {
                "type": "rep",
                "start": "2023-01-03",
                # Far-future sentinel so the wall-clock filter in _current_term
                # cannot silently rot this fixture out of the "current" bucket.
                "end": "2099-01-03",
                "state": "CA",
                "district": 11,
                "party": "Democrat",
                "phone": "202-225-4965",
                "url": "https://pelosi.house.gov",
            },
        ],
    }


def _senate_member_fixture() -> dict:
    # Real-world shape: senator with class + state_rank, url field.
    return {
        "id": {
            "bioguide": "C000127",
            "fec": ["S8WA00194", "H2WA01054"],
            "govtrack": 300018,
            "wikidata": "Q22250",
        },
        "name": {
            "first": "Maria",
            "last": "Cantwell",
            "official_full": "Maria Cantwell",
        },
        "bio": {"birthday": "1958-10-13", "gender": "F"},
        "terms": [
            {
                "type": "sen",
                "start": "2025-01-03",
                "end": "2099-01-03",
                "state": "WA",
                "class": 1,
                "state_rank": "senior",
                "party": "Democrat",
                "phone": "202-224-3441",
                "url": "https://www.cantwell.senate.gov",
                "address": "511 Hart Senate Office Building Washington DC 20510",
                "contact_form": "https://www.cantwell.senate.gov/contact",
            },
        ],
    }


def _delegate_fixture() -> dict:
    # DC delegate: type=rep but state is a territory code.
    return {
        "id": {
            "bioguide": "N000147",
            "fec": ["H0DC00043"],
            "govtrack": 400295,
            "wikidata": "Q461748",
        },
        "name": {
            "first": "Eleanor",
            "last": "Norton",
            "official_full": "Eleanor Holmes Norton",
        },
        "bio": {"birthday": "1937-06-13", "gender": "F"},
        "terms": [
            {
                "type": "rep",
                "start": "2025-01-03",
                "end": "2099-01-03",
                "state": "DC",
                "district": 0,
                "party": "Democrat",
                "phone": "202-225-8050",
                "url": "https://norton.house.gov",
            },
        ],
    }


def _president_fixture_no_bioguide() -> dict:
    # Trump's executive.yaml entry has no bioguide ID — only an FEC ID.
    return {
        "id": {"fec": ["P80001571"]},
        "name": {
            "first": "Donald",
            "last": "Trump",
            "official_full": "Donald J. Trump",
        },
        "bio": {"birthday": "1946-06-14", "gender": "M"},
        "terms": [
            {
                "type": "prez",
                "start": "2017-01-20",
                "end": "2021-01-20",
                "party": "Republican",
            },
            {
                "type": "prez",
                "start": "2025-01-20",
                "end": "2099-01-20",
                "party": "Republican",
            },
        ],
    }


def _vp_fixture() -> dict:
    return {
        "id": {
            "bioguide": "V000137",
            "fec": ["S6OH00163"],
        },
        "name": {"first": "JD", "last": "Vance"},
        "bio": {"birthday": "1984-08-02", "gender": "M"},
        "terms": [
            {
                "type": "viceprez",
                "start": "2025-01-20",
                "end": "2099-01-20",
                "party": "Republican",
            },
        ],
    }


def _expired_only_fixture() -> dict:
    # A historical legislator whose last term ended well in the past.
    # Should not appear in any "current" output bucket.
    return {
        "id": {"bioguide": "X000001", "fec": []},
        "name": {"first": "Past", "last": "Person"},
        "bio": {},
        "terms": [
            {
                "type": "rep",
                "start": "1995-01-03",
                "end": "1997-01-03",
                "state": "TX",
                "district": 1,
                "party": "Republican",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


HOUSE_ROW_KEYS = {
    "bioguide_id",
    "member_name",
    "first_name",
    "last_name",
    "state",
    "district",
    "party",
    "phone",
    "sworn_date",
    "fec_ids",
    "wikidata_id",
    "govtrack_id",
    "elected_date",
    "office_building",
    "office_room",
    "office_zip",
}

SENATE_ROW_KEYS = {
    "bioguide_id",
    "member_full",
    "first_name",
    "last_name",
    "state",
    "party",
    "class",
    "phone",
    "email",
    "website",
    "address",
    "fec_ids",
    "wikidata_id",
    "govtrack_id",
    "appointed",
}


def test_adapt_house_member_row_contract() -> None:
    result = adapt_legislators_yaml([_house_member_fixture()])
    assert isinstance(result, AdaptedLegislators)
    assert len(result.house_rows) == 1
    row = result.house_rows[0]
    assert set(row.keys()) == HOUSE_ROW_KEYS
    assert row["bioguide_id"] == "P000197"
    assert row["member_name"] == "Nancy Pelosi"
    assert row["first_name"] == "Nancy"
    assert row["last_name"] == "Pelosi"
    assert row["state"] == "CA"
    assert row["district"] == "11"
    assert row["party"] == "Democrat"
    assert row["phone"] == "202-225-4965"
    assert row["sworn_date"] == "2023-01-03"
    assert row["fec_ids"] == ["H8CA08049", "H0CA12041"]
    assert row["wikidata_id"] == "Q170581"
    assert row["govtrack_id"] == "400314"
    # YAML lacks these; passthrough as empty.
    assert row["elected_date"] == ""
    assert row["office_building"] == ""
    assert row["office_room"] == ""
    assert row["office_zip"] == ""


def test_adapt_senate_member_row_contract() -> None:
    result = adapt_legislators_yaml([_senate_member_fixture()])
    assert len(result.senate_rows) == 1
    row = result.senate_rows[0]
    assert set(row.keys()) == SENATE_ROW_KEYS
    assert row["bioguide_id"] == "C000127"
    assert row["member_full"] == "Maria Cantwell"
    assert row["first_name"] == "Maria"
    assert row["last_name"] == "Cantwell"
    assert row["state"] == "WA"
    assert row["party"] == "Democrat"
    assert row["class"] == "1"
    assert row["phone"] == "202-224-3441"
    assert row["website"] == "https://www.cantwell.senate.gov"
    assert row["address"] == "511 Hart Senate Office Building Washington DC 20510"
    assert row["fec_ids"] == ["S8WA00194", "H2WA01054"]
    assert row["wikidata_id"] == "Q22250"
    assert row["govtrack_id"] == "300018"
    # YAML terms carry contact_form, not email; YAML has no appointed flag.
    assert row["email"] == ""
    assert row["appointed"] == ""


def test_delegate_routed_to_delegate_bucket() -> None:
    # A type=rep with DC state must NOT appear in the House bucket.
    result = adapt_legislators_yaml([_delegate_fixture()])
    assert result.house_rows == []
    assert len(result.delegate_rows) == 1
    row = result.delegate_rows[0]
    assert row["state"] == "DC"
    assert row["bioguide_id"] == "N000147"
    assert row["office_id"] == OFFICE_US_HOUSE_DELEGATE
    assert row["fec_ids"] == ["H0DC00043"]
    assert row["wikidata_id"] == "Q461748"
    assert row["govtrack_id"] == "400295"


def test_president_and_vp_row_dicts() -> None:
    result = adapt_legislators_yaml([_president_fixture_no_bioguide(), _vp_fixture()])
    assert len(result.president_rows) == 1
    assert len(result.vp_rows) == 1
    pres = result.president_rows[0]
    vp = result.vp_rows[0]
    assert pres["office_type"] == "president"
    assert vp["office_type"] == "vice_president"
    assert "bioguide_id" in pres and "bioguide_id" in vp
    assert "fec_ids" in pres and "fec_ids" in vp
    assert pres["first_name"] == "Donald"
    assert pres["last_name"] == "Trump"
    assert pres["party"] == "Republican"
    assert vp["first_name"] == "JD"
    assert vp["last_name"] == "Vance"
    assert vp["party"] == "Republican"


def test_missing_bioguide_uses_empty_string() -> None:
    result = adapt_legislators_yaml([_president_fixture_no_bioguide()])
    assert len(result.president_rows) == 1
    row = result.president_rows[0]
    assert row["bioguide_id"] == ""
    assert row["fec_ids"] == ["P80001571"]


def test_expired_only_entry_excluded() -> None:
    # A person whose only term ended long ago should not appear anywhere.
    result = adapt_legislators_yaml([_expired_only_fixture()])
    assert result.house_rows == []
    assert result.senate_rows == []
    assert result.delegate_rows == []
    assert result.president_rows == []
    assert result.vp_rows == []


def test_fetch_legislators_entries_downloads_and_combines_yaml_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = {
        adapter_module.LEGISLATORS_CURRENT_YAML_URL: """
- id:
    bioguide: H000001
  name:
    first: House
    last: Person
  terms:
    - type: rep
      start: "2025-01-03"
      end: "2099-01-03"
      state: NY
      district: 1
- id:
    bioguide: S000001
  name:
    first: Senate
    last: Person
  terms:
    - type: sen
      start: "2025-01-03"
      end: "2099-01-03"
      state: WA
      class: 1
""",
        adapter_module.EXECUTIVE_YAML_URL: """
- id:
    fec:
      - P80001571
  name:
    first: Donald
    last: Trump
  terms:
    - type: prez
      start: "2025-01-20"
      end: "2099-01-20"
      party: Republican
""",
    }
    requested_urls: list[str] = []

    def fake_fetch_yaml_payload(client: object, url: str) -> str:
        requested_urls.append(url)
        return payloads[url]

    monkeypatch.setattr(
        adapter_module,
        "_fetch_yaml_payload",
        fake_fetch_yaml_payload,
        raising=False,
    )

    entries = adapter_module.fetch_legislators_entries()

    assert requested_urls == [
        adapter_module.LEGISLATORS_CURRENT_YAML_URL,
        adapter_module.EXECUTIVE_YAML_URL,
    ]
    assert len(entries) == 3
    assert entries[2]["id"]["fec"] == ["P80001571"]


def test_adapter_exports_congress_legislators_source_contract() -> None:
    assert adapter_module.LEGISLATORS_CURRENT_YAML_URL == (
        "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
    )
    assert adapter_module.EXECUTIVE_YAML_URL == (
        "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/executive.yaml"
    )
    assert {
        "LEGISLATORS_CURRENT_YAML_URL",
        "EXECUTIVE_YAML_URL",
        "fetch_legislators_entries",
    }.issubset(set(adapter_module.__all__))


# ---------------------------------------------------------------------------
# Live-data integration probes
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_yaml_endpoint_reachable() -> None:
    for url in (
        adapter_module.LEGISLATORS_CURRENT_YAML_URL,
        adapter_module.EXECUTIVE_YAML_URL,
    ):
        completed = subprocess.run(
            [
                "bash",
                "-c",
                f'curl -sIL -m 30 "{url}" | grep -i "^HTTP" | tail -1',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "200" in completed.stdout, (
            f"upstream not HTTP 200 for {url}; stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )


@pytest.mark.integration
def test_live_adapter_count_sanity() -> None:
    entries = adapter_module.fetch_legislators_entries()
    result = adapt_legislators_yaml(entries)
    assert 425 <= len(result.house_rows) <= 440, f"House row count {len(result.house_rows)} outside expected band"
    assert len(result.senate_rows) == 100, f"Senate row count {len(result.senate_rows)} != 100"
    assert len(result.delegate_rows) == 6, f"Delegate row count {len(result.delegate_rows)} != 6"
    assert len(result.president_rows) >= 1
    assert len(result.vp_rows) >= 1


# ---------------------------------------------------------------------------
# Vacancy predecessor tests
# ---------------------------------------------------------------------------


def _historical_predecessor_fixture(
    *,
    bioguide: str,
    state: str,
    district: int,
    term_end: str,
    first: str = "Former",
    last: str = "Member",
    fec: list[str] | None = None,
) -> dict:
    return {
        "id": {
            "bioguide": bioguide,
            "fec": fec or [],
            "govtrack": 99999,
            "wikidata": f"Q{bioguide}",
        },
        "name": {"first": first, "last": last},
        "terms": [
            {
                "type": "rep",
                "start": "2020-01-03",
                "end": term_end,
                "state": state,
                "district": district,
                "party": "Independent",
            },
        ],
    }


def test_vacancy_predecessor_selects_most_recent_holder() -> None:
    current = adapt_legislators_yaml([_house_member_fixture()])
    assert len(current.house_rows) == 1

    older = _historical_predecessor_fixture(
        bioguide="OLD001",
        state="TX",
        district=23,
        term_end="2021-01-03",
        first="Old",
        last="Holder",
    )
    newer = _historical_predecessor_fixture(
        bioguide="NEW001",
        state="TX",
        district=23,
        term_end="2026-04-14",
        first="New",
        last="Holder",
        fec=["H0TX35015"],
    )

    result = select_most_recent_vacancy_predecessors(
        current,
        [older, newer],
        min_term_end=date(2020, 1, 1),
    )
    assert isinstance(result, HistoricalPredecessors)
    assert len(result.house_predecessors) == 1

    pred = result.house_predecessors[0]
    assert pred.bioguide_id == "NEW001"
    assert pred.state == "TX"
    assert pred.district == "23"
    assert pred.term_end == "2026-04-14"
    assert pred.fec_ids == ["H0TX35015"]
    assert pred.first_name == "New"
    assert pred.last_name == "Holder"


def test_vacancy_predecessor_ignores_filled_seats() -> None:
    current = adapt_legislators_yaml([_house_member_fixture()])
    ca_11 = current.house_rows[0]

    historical = _historical_predecessor_fixture(
        bioguide="PREV01",
        state=ca_11["state"],
        district=int(ca_11["district"]),
        term_end="2025-01-03",
    )
    result = select_most_recent_vacancy_predecessors(
        current,
        [historical],
        min_term_end=date(2020, 1, 1),
    )
    assert result.house_predecessors == []


def test_vacancy_predecessor_ignores_territory_delegates() -> None:
    current = adapt_legislators_yaml([_house_member_fixture()])
    territory_hist = _historical_predecessor_fixture(
        bioguide="DC0001",
        state="DC",
        district=0,
        term_end="2025-01-03",
    )
    result = select_most_recent_vacancy_predecessors(
        current,
        [territory_hist],
        min_term_end=date(2020, 1, 1),
    )
    assert result.house_predecessors == []


def test_vacancy_predecessor_filters_defunct_districts() -> None:
    current = adapt_legislators_yaml([_house_member_fixture()])
    defunct = _historical_predecessor_fixture(
        bioguide="OLD999",
        state="PA",
        district=35,
        term_end="1933-03-03",
    )
    result = select_most_recent_vacancy_predecessors(
        current,
        [defunct],
        min_term_end=date(2020, 1, 1),
    )
    assert result.house_predecessors == []


def test_vacancy_predecessor_empty_when_no_historical() -> None:
    current = adapt_legislators_yaml([_house_member_fixture()])
    result = select_most_recent_vacancy_predecessors(current, [])
    assert isinstance(result, HistoricalPredecessors)
    assert result.house_predecessors == []


_ = date
