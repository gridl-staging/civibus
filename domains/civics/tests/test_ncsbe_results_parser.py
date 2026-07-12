"""Red tests for future NCSBE ENRS past-results parser implementation."""

from __future__ import annotations

from importlib import import_module
from typing import Callable

import pytest


def _load_parser() -> Callable[..., list[dict[str, object]]]:
    module = import_module("domains.civics.loaders.ncsbe_results_parser")
    parser = getattr(module, "parse_ncsbe_results", None)
    if parser is None:
        pytest.fail("Expected parse_ncsbe_results callable in domains.civics.loaders.ncsbe_results_parser")
    return parser


def test_parser_contract_returns_exact_certified_values(
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    parser = _load_parser()

    parsed_rows = parser(ncsbe_contract_rows_by_file)

    expected_rows = [
        {
            "election_date": "2020-11-03",
            "election_label": "General Election",
            "jurisdiction_name": "Wake",
            "contest_name": "US PRESIDENT",
            "contest_external_id": "1001",
            "candidate_name": "JOSEPH R BIDEN",
            "party": "DEM",
            "votes": 410425,
            "vote_pct": 54.22,
            "is_certified": True,
        },
        {
            "election_date": "2022-11-08",
            "election_label": "General Election",
            "jurisdiction_name": "Wake",
            "contest_name": "US SENATE",
            "contest_external_id": "2001",
            "candidate_name": "TED BUDD",
            "party": "REP",
            "votes": 361304,
            "vote_pct": 53.15,
            "is_certified": True,
        },
        {
            "election_date": "2024-03-05",
            "election_label": "Primary Election",
            "jurisdiction_name": "Wake",
            "contest_name": "ATTORNEY GENERAL DEM",
            "contest_external_id": "3001",
            "candidate_name": "JEFF JACKSON",
            "party": "DEM",
            "votes": 97751,
            "vote_pct": 64.87,
            "is_certified": True,
        },
        {
            "election_date": "2024-11-05",
            "election_label": "General Election",
            "jurisdiction_name": "Wake",
            "contest_name": "NC GOVERNOR",
            "contest_external_id": "4001",
            "candidate_name": "JOSH STEIN",
            "party": "DEM",
            "votes": 452111,
            "vote_pct": 51.12,
            "is_certified": True,
        },
    ]

    observed_rows_by_key = {(str(row["contest_external_id"]), str(row["candidate_name"])): row for row in parsed_rows}
    assert len(observed_rows_by_key) == len(parsed_rows), "Parser emitted duplicate contest/candidate rows"

    for expected in expected_rows:
        expected_key = (expected["contest_external_id"], expected["candidate_name"])
        assert expected_key in observed_rows_by_key
        observed = observed_rows_by_key[expected_key]
        for field_name, expected_value in expected.items():
            assert observed[field_name] == expected_value


def test_fixture_contract_contains_four_elections_and_unresolved_row(
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    assert sorted(ncsbe_contract_rows_by_file) == [
        "enrs_2020_11_03_general_sample.csv",
        "enrs_2022_11_08_general_sample.csv",
        "enrs_2024_03_05_primary_sample.csv",
        "enrs_2024_11_05_general_sample.csv",
    ]

    total_rows = sum(len(rows) for rows in ncsbe_contract_rows_by_file.values())
    assert total_rows == 9

    unresolved_contests = [
        row
        for rows in ncsbe_contract_rows_by_file.values()
        for row in rows
        if row["contest_id"] == "9999" and row["contest_name"] == "UNMAPPED SAMPLE CONTEST"
    ]
    assert len(unresolved_contests) == 1


def test_parser_hard_fails_on_unresolved_contest_mapping(
    ncsbe_contract_rows_by_file: dict[str, list[dict[str, str]]],
) -> None:
    parser = _load_parser()

    with pytest.raises(ValueError, match="Unresolved contest mapping"):
        parser(ncsbe_contract_rows_by_file, require_contest_mapping=True)
