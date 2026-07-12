"""Contract tests for NC candidate-listing parser/summary.

Stage 1 contract scope only: parser/summary behavior follows the nc_calendar loader-style
summary seam, and persistence ownership remains in domains/civics/ingest.py.
This module introduces no new persistence/helper boundary.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from domains.civics.loaders.ncsbe_candidate_listing import (
    CandidateListingParseSummary,
    parse_ncsbe_candidate_listing,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CSV_PATH = (
    REPO_ROOT
    / "docs"
    / "reference"
    / "research"
    / "artifacts"
    / "nc_2026_civic_calendar_probe_2026_04_25"
    / "local_candidate_listing_2026.csv"
)
EXPECTED_HEADERS = [
    "election_dt",
    "county_name",
    "contest_name",
    "name_on_ballot",
    "first_name",
    "middle_name",
    "last_name",
    "name_suffix_lbl",
    "nick_name",
    "street_address",
    "city",
    "state",
    "zip_code",
    "phone",
    "office_phone",
    "business_phone",
    "email",
    "candidacy_dt",
    "party_contest",
    "party_candidate",
    "is_unexpired",
    "has_primary",
    "is_partisan",
    "vote_for",
    "term",
]


def test_fixture_header_order_and_non_header_row_count_contract() -> None:
    parsed = parse_ncsbe_candidate_listing(CSV_PATH)

    assert parsed.header == EXPECTED_HEADERS
    assert parsed.summary.row_count == 7152


def test_known_answer_rows_for_durham_wake_orange() -> None:
    parsed = parse_ncsbe_candidate_listing(CSV_PATH)

    durham = parsed.require_row(
        county_name="DURHAM",
        contest_name="DURHAM COUNTY CLERK OF SUPERIOR COURT",
        name_on_ballot="A. Beverly Ellis-Maclin",
    )
    wake = parsed.require_row(
        county_name="WAKE",
        contest_name="WAKE COUNTY BOARD OF COMMISSIONERS AT-LARGE",
        name_on_ballot="Marguerite Creel",
    )
    orange = parsed.require_row(
        county_name="ORANGE",
        contest_name="ORANGE COUNTY BOARD OF COMMISSIONERS DISTRICT 01",
        name_on_ballot="Jamezetta Bedford",
    )

    assert durham.election_date.isoformat() == "2026-03-03"
    assert durham.candidate_display_name == "A. Beverly Ellis-Maclin"
    assert durham.party_candidate == "DEM"
    assert durham.has_primary is True
    assert durham.is_partisan is True
    assert durham.vote_for == 1

    assert wake.election_date.isoformat() == "2026-03-03"
    assert wake.candidate_display_name == "Marguerite Creel"
    assert wake.party_candidate == "DEM"
    assert wake.has_primary is True
    assert wake.is_partisan is True
    assert wake.vote_for == 2

    assert orange.election_date.isoformat() == "2026-03-03"
    assert orange.candidate_display_name == "Jamezetta Bedford"
    assert orange.party_candidate == "DEM"
    assert orange.has_primary is True
    assert orange.is_partisan is True
    assert orange.vote_for == 1


def test_summary_interface_shape_contract() -> None:
    parsed = parse_ncsbe_candidate_listing(CSV_PATH)
    summary = parsed.summary

    assert isinstance(summary, CandidateListingParseSummary)
    assert summary.row_count == 7152
    assert summary.county_count == 100
    assert summary.contest_count > 0
    assert summary.rows_by_county["DURHAM"] > 0
    assert summary.rows_by_county["WAKE"] > 0
    assert summary.rows_by_county["ORANGE"] > 0
    assert summary.rows_by_party_candidate["DEM"] > 0
    assert summary.rows_by_party_candidate["REP"] > 0


def test_known_answer_bool_date_and_integer_contracts() -> None:
    parsed = parse_ncsbe_candidate_listing(CSV_PATH)

    jessie = parsed.require_row(
        county_name="ALEXANDER",
        contest_name="NC DISTRICT COURT JUDGE DISTRICT 32 SEAT 06 (UNEXPIRED)",
        name_on_ballot="Jessie Conley",
    )
    shannon = parsed.require_row(
        county_name="ALAMANCE",
        contest_name="US SENATE",
        name_on_ballot="Shannon W. Bray",
    )
    katharine = parsed.require_row(
        county_name="ALAMANCE",
        contest_name="ALAMANCE-BURLINGTON BOARD OF EDUCATION",
        name_on_ballot="Katharine Frazier",
    )
    deborah = parsed.require_row(
        county_name="HERTFORD",
        contest_name="TOWN OF HARRELLSVILLE COUNCIL MEMBER",
        name_on_ballot="Deborah A. Baker",
    )

    assert isinstance(jessie.election_date, date)
    assert jessie.election_date.isoformat() == "2026-03-03"
    assert "(UNEXPIRED)" in jessie.contest_name
    assert shannon.has_primary is False
    assert katharine.is_partisan is False
    assert isinstance(deborah.vote_for, int)
    assert deborah.vote_for == 5


def test_county_name_semantics_contract() -> None:
    parsed = parse_ncsbe_candidate_listing(CSV_PATH)

    assert all(row.county_name.strip() != "" for row in parsed.rows)
    assert all(row.county_name == row.county_name.upper() for row in parsed.rows)
    assert parsed.summary.rows_by_county["DURHAM"] > 0
    assert parsed.summary.rows_by_county["WAKE"] > 0
    assert parsed.summary.rows_by_county["ORANGE"] > 0
    assert parsed.summary.county_count == 100
