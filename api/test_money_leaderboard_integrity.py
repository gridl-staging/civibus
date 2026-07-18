from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

import psycopg
import pytest

import api.queries.campaign_finance as campaign_finance_queries
from api.queries.civics import fetch_current_federal_members
from api.routes.public_federal import (
    _candidate_matches_current_member,
    _select_public_money_candidate,
    _selected_public_money_candidates_by_person,
)
from api.test_campaign_finance_support import (
    CandidateCommitteeLinkSeed,
    CandidateRowSeed,
    CommitteeRowSeed,
    CommitteeSummaryRowSeed,
    insert_candidate_committee_link_row,
    insert_candidate_row,
    insert_committee_row,
    insert_committee_summary_row,
)
from api.test_civics import _seed_current_federal_members_mix

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OPENFEC_KNOWN_TOTALS_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "money" / "fec_known_totals_2026.json"
_OPENFEC_KNOWN_TOTALS_CYCLE = 2026
_OPENFEC_SENTINEL_NAMES = {
    "Sullivan, Dan",
    "Ossoff, T. Jonathan",
    "Trump, Donald J.",
    "Mercer, Lee",
}
_DECIMAL_STRING_PATTERN = re.compile(r"^-?\d+(\.\d+)?$")
_FEC_COMMITTEE_ID_PATTERN = re.compile(r"^C[0-9]{8}$")


@dataclass(frozen=True)
class _FallbackCommitteeCase:
    slug: str
    fec_candidate_id: str
    committee_type: str
    committee_designation: str
    total_receipts: Decimal
    expected_total_raised: Decimal
    expected_summary_source: str


def _load_openfec_known_totals_fixture() -> dict[str, Any]:
    data = json.loads(_OPENFEC_KNOWN_TOTALS_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert data["cycle"] == _OPENFEC_KNOWN_TOTALS_CYCLE
    fetch_date = datetime.fromisoformat(data["fetch_date"].replace("Z", "+00:00"))
    assert fetch_date.tzinfo == timezone.utc

    source = data["source"]
    assert source["url_template"] == "https://api.open.fec.gov/v1/candidate/{candidate_id}/totals/"
    assert source["query"] == {"cycle": _OPENFEC_KNOWN_TOTALS_CYCLE}
    assert "api_key" not in json.dumps(source).lower()

    rows = data["candidates"]
    assert isinstance(rows, list)
    served_rows = [row for row in rows if row.get("served_roster_member") is True]
    assert len(rows) >= 20
    assert sum(row["office"] == "H" for row in served_rows) >= 15
    assert sum(row["office"] == "S" for row in served_rows) >= 15
    assert _OPENFEC_SENTINEL_NAMES.issubset({row["name"] for row in rows})

    for row in rows:
        assert set(row) >= {
            "fec_candidate_id",
            "name",
            "office",
            "served_roster_member",
            "receipts",
            "source_url",
            "cycle",
        }
        assert row["cycle"] == _OPENFEC_KNOWN_TOTALS_CYCLE
        assert row["office"] in {"H", "S", "P"}
        assert isinstance(row["served_roster_member"], bool)
        assert isinstance(row["receipts"], str)
        assert _DECIMAL_STRING_PATTERN.match(row["receipts"])
        Decimal(row["receipts"])
        assert row["source_url"].startswith(f"https://api.open.fec.gov/v1/candidate/{row['fec_candidate_id']}/totals/")
        assert "api_key" not in row["source_url"].lower()
    return data


def _known_total_candidate_id(index: int) -> UUID:
    return uuid5(NAMESPACE_DNS, f"civibus-openfec-known-total-candidate-{index}")


def _known_total_committee_id(index: int) -> UUID:
    return uuid5(NAMESPACE_DNS, f"civibus-openfec-known-total-committee-{index}")


def _known_total_person_id(index: int) -> UUID:
    return uuid5(NAMESPACE_DNS, f"civibus-openfec-known-total-person-{index}")


def _known_total_committee_fec_id(index: int) -> str:
    return f"C{7500000 + index:08d}"


def _known_total_link_id(index: int) -> UUID:
    return uuid5(NAMESPACE_DNS, f"civibus-openfec-known-total-link-{index}")


def _divergent_committee_receipts(openfec_receipts: Decimal) -> Decimal:
    return max(
        openfec_receipts * Decimal("4"),
        openfec_receipts + Decimal("1000000.00"),
        Decimal("1000000.00"),
    )


def _seed_fallback_committee_case(
    db_conn: psycopg.Connection,
    *,
    index: int,
    committee_case: _FallbackCommitteeCase,
) -> tuple[UUID, str]:
    candidate_id = UUID(f"72000000-0000-0000-0000-0000000001{index:02d}")
    committee_id = UUID(f"72000000-0000-0000-0000-0000000002{index:02d}")
    candidate_name = f"D EXCLUSION PRESERVES {committee_case.slug.upper()}"
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id=committee_case.fec_candidate_id,
            name=candidate_name,
            office="S",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id=f"C71000{index:03d}",
            name=f"D EXCLUSION {committee_case.slug.upper()} COMMITTEE",
            committee_type=committee_case.committee_type,
            committee_designation=committee_case.committee_designation,
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=committee_case.total_receipts,
            total_disbursements=Decimal("0.00"),
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID(f"72000000-0000-0000-0000-0000000003{index:02d}"),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2025-01-01,2027-01-01)",
            designation=committee_case.committee_designation,
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    return candidate_id, candidate_name


def _assert_decimal_within_one_percent(*, actual: Decimal, expected: Decimal) -> None:
    if expected == 0:
        assert actual == expected
        return
    assert abs(actual - expected) <= abs(expected) * Decimal("0.01")


def _fixture_row_member_state(row: dict[str, Any]) -> str | None:
    fec_candidate_id = row["fec_candidate_id"]
    if row["office"] in {"H", "S"} and len(fec_candidate_id) >= 4:
        return fec_candidate_id[2:4]
    return None


def _fixture_row_member_chamber(row: dict[str, Any]) -> str:
    if row["office"] == "S":
        return "Senate"
    if row["office"] == "P":
        return "Executive"
    return "House"


def _fixture_row_member(row: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "person_id": _known_total_person_id(index),
        "person_name": row["name"],
        "chamber": _fixture_row_member_chamber(row),
        "state": _fixture_row_member_state(row),
        "district": None,
    }


def _fixture_row_candidate(row: dict[str, Any], index: int) -> dict[str, Any]:
    candidate_id = _known_total_candidate_id(index)
    return {
        "id": candidate_id,
        "fec_candidate_id": row["fec_candidate_id"],
        "name": row["name"],
        "office": row["office"],
        "state": _fixture_row_member_state(row),
        "district": None,
        "source_record_id": None,
    }


def _selected_fixture_candidate_refs(
    fixture_candidate_rows: list[tuple[int, dict[str, Any]]],
) -> list[tuple[UUID, str]]:
    members = [_fixture_row_member(row, index) for index, row in fixture_candidate_rows if row["served_roster_member"]]
    candidates_by_person = {
        _known_total_person_id(index): [_fixture_row_candidate(row, index)]
        for index, row in fixture_candidate_rows
        if row["served_roster_member"]
    }
    selected_candidates_by_person = _selected_public_money_candidates_by_person(members, candidates_by_person)
    assert len(selected_candidates_by_person) == len(members)

    selected_refs = [(candidate["id"], candidate["name"]) for candidate in selected_candidates_by_person.values()]
    non_served_refs = [
        (_known_total_candidate_id(index), row["name"])
        for index, row in fixture_candidate_rows
        if not row["served_roster_member"]
    ]
    return selected_refs + non_served_refs


@pytest.mark.parametrize(
    ("candidate", "ceiling"),
    [
        (
            CandidateRowSeed(
                id=UUID("71000000-0000-0000-0000-000000000001"),
                fec_candidate_id="H0ZZ00001",
                name="H RECEIPTS CEILING TEST",
                office="H",
                total_receipts=Decimal("60000000.01"),
                total_disbursements=Decimal("0.00"),
                summary_coverage_end_date=date(2026, 3, 31),
            ),
            Decimal("60000000.00"),
        ),
        (
            CandidateRowSeed(
                id=UUID("71000000-0000-0000-0000-000000000002"),
                fec_candidate_id="S0ZZ00002",
                name="S RECEIPTS CEILING TEST",
                office="S",
                total_receipts=Decimal("150000000.01"),
                total_disbursements=Decimal("0.00"),
                summary_coverage_end_date=date(2026, 3, 31),
            ),
            Decimal("150000000.00"),
        ),
        (
            CandidateRowSeed(
                id=UUID("71000000-0000-0000-0000-000000000003"),
                fec_candidate_id="P0ZZ00003",
                name="P RECEIPTS CEILING TEST",
                office="P",
                total_receipts=Decimal("2000000000.01"),
                total_disbursements=Decimal("0.00"),
                summary_coverage_end_date=date(2026, 3, 31),
            ),
            Decimal("2000000000.00"),
        ),
    ],
)
def test_receipts_ceiling_flags_over_chamber_max(
    db_conn: psycopg.Connection,
    candidate: CandidateRowSeed,
    ceiling: Decimal,
) -> None:
    insert_candidate_row(db_conn, candidate)

    summary = campaign_finance_queries.fetch_candidate_public_money_summaries(
        db_conn,
        [(candidate.id, candidate.name)],
    )[candidate.id]

    assert candidate.total_receipts == ceiling + Decimal("0.01")
    assert summary["total_raised"] == candidate.total_receipts
    assert summary["summary_source"] == "fec_weball"
    assert campaign_finance_queries.exceeds_receipts_ceiling(candidate.office, ceiling) is False
    assert campaign_finance_queries.exceeds_receipts_ceiling(candidate.office, summary["total_raised"]) is True


def test_official_total_wins_over_party_inflation(db_conn: psycopg.Connection) -> None:
    candidate_id = UUID("9a000000-0000-0000-0000-000000000101")
    candidate_name = "OFFICIAL TOTAL WINS, TEST"
    principal_id = UUID("9a000000-0000-0000-0000-0000000001c1")
    jfc_id = UUID("9a000000-0000-0000-0000-0000000001c3")
    party_id = UUID("9a000000-0000-0000-0000-0000000001c4")
    official_total = Decimal("6500847.42")
    committees = (
        (principal_id, "C90001001", "PRINCIPAL CAMPAIGN CTE", "S", "P", Decimal("6000000.00")),
        (jfc_id, "C90001003", "CANDIDATE VICTORY JFC", "N", "J", Decimal("2174403.69")),
        (party_id, "C90001004", "NATIONAL PARTY CTE", "Y", "U", Decimal("142102510.79")),
    )

    for committee_id, fec_id, name, committee_type, designation, _receipts in committees:
        insert_committee_row(
            db_conn,
            CommitteeRowSeed(
                id=committee_id,
                fec_committee_id=fec_id,
                name=name,
                committee_type=committee_type,
                committee_designation=designation,
            ),
        )

    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="S6AK01999",
            name=candidate_name,
            office="S",
            state="AK",
            principal_committee_id=principal_id,
            total_receipts=official_total,
            total_disbursements=Decimal("1505699.66"),
            cash_on_hand=Decimal("5000000.00"),
            summary_coverage_end_date=date(2026, 3, 31),
        ),
    )

    for index, (committee_id, _fec_id, _name, _committee_type, designation, receipts) in enumerate(committees):
        insert_committee_summary_row(
            db_conn,
            CommitteeSummaryRowSeed(
                committee_id=committee_id,
                cycle=2026,
                total_receipts=receipts,
                total_disbursements=Decimal("0.00"),
                coverage_start_date=date(2025, 1, 1),
                coverage_end_date=date(2026, 12, 31),
            ),
        )
        insert_candidate_committee_link_row(
            db_conn,
            CandidateCommitteeLinkSeed(
                id=UUID(f"9a000000-0000-0000-0000-0000000001{index:02d}"),
                candidate_id=candidate_id,
                committee_id=committee_id,
                valid_period="[2025-01-01,2027-01-01)",
                designation=designation,
                candidate_election_year=2026,
                fec_election_year=2026,
            ),
        )

    batch_summary = campaign_finance_queries.fetch_candidate_public_money_summaries(
        db_conn, [(candidate_id, candidate_name)]
    )[candidate_id]
    assert batch_summary["total_raised"] == official_total
    assert batch_summary["summary_source"] == "fec_weball"

    person_summary = campaign_finance_queries.fetch_candidate_public_money_summary(
        db_conn, candidate_id, candidate_name
    )
    assert person_summary is not None
    assert person_summary["total_raised"] == official_total
    assert person_summary["summary_source"] == "fec_weball"

    detail_summary = campaign_finance_queries.fetch_candidate_summary(db_conn, candidate_id, candidate_name)
    assert detail_summary is not None
    assert detail_summary["total_raised"] == official_total
    assert detail_summary["summary_source"] == "fec_weball"


def test_openfec_known_totals_fixture_contract() -> None:
    _load_openfec_known_totals_fixture()


def test_known_total_synthetic_committee_fec_ids_match_schema_contract() -> None:
    for index in range(1, 101):
        assert _FEC_COMMITTEE_ID_PATTERN.match(_known_total_committee_fec_id(index))


def test_openfec_known_totals_hermetic_path_uses_public_federal_selection_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = {
        "candidates": [
            {
                "fec_candidate_id": "H6NC00001",
                "name": "SEAM EXERCISE, TEST",
                "office": "H",
                "served_roster_member": True,
                "receipts": "12345.67",
                "cycle": 2026,
                "source_url": "https://api.open.fec.gov/v1/candidate/H6NC00001/totals/?cycle=2026",
            }
        ]
    }
    selected_seam_calls = []
    original_selected_candidates = _selected_public_money_candidates_by_person

    def record_selected_candidates(
        members: list[dict[str, Any]],
        candidates_by_person: dict[UUID, list[dict[str, Any]]],
    ) -> dict[UUID, dict[str, Any]]:
        selected_seam_calls.append((members, candidates_by_person))
        return original_selected_candidates(members, candidates_by_person)

    def fake_fetch_candidate_public_money_summaries(
        _conn: object,
        candidate_refs: list[tuple[UUID, str]],
        *,
        selected_cycle: int | None = None,
    ) -> dict[UUID, dict[str, Any]]:
        assert selected_cycle == 2026
        return {
            candidate_id: {
                "total_raised": Decimal("12345.67"),
                "summary_source": "fec_weball",
            }
            for candidate_id, _name in candidate_refs
        }

    monkeypatch.setattr(
        "api.test_money_leaderboard_integrity._load_openfec_known_totals_fixture",
        lambda: fixture,
    )
    monkeypatch.setattr(
        "api.test_money_leaderboard_integrity.insert_committee_row",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "api.test_money_leaderboard_integrity.insert_candidate_row",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "api.test_money_leaderboard_integrity.insert_committee_summary_row",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "api.test_money_leaderboard_integrity.insert_candidate_committee_link_row",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        campaign_finance_queries,
        "fetch_candidate_public_money_summaries",
        fake_fetch_candidate_public_money_summaries,
    )
    monkeypatch.setattr(
        "api.test_money_leaderboard_integrity._selected_public_money_candidates_by_person",
        record_selected_candidates,
    )

    test_openfec_known_totals_drive_served_money_summaries(object())

    assert selected_seam_calls


def test_openfec_known_totals_drive_served_money_summaries(db_conn: psycopg.Connection) -> None:
    fixture = _load_openfec_known_totals_fixture()
    fixture_candidate_rows = list(enumerate(fixture["candidates"], start=1))

    for index, row in fixture_candidate_rows:
        candidate_id = _known_total_candidate_id(index)
        committee_id = _known_total_committee_id(index)
        receipts = Decimal(row["receipts"])
        divergent_committee_receipts = _divergent_committee_receipts(receipts)

        insert_committee_row(
            db_conn,
            CommitteeRowSeed(
                id=committee_id,
                fec_committee_id=_known_total_committee_fec_id(index),
                name=f"{row['name']} PRINCIPAL COMMITTEE FALLBACK CONTROL",
                committee_type=row["office"],
                committee_designation="P",
            ),
        )
        insert_candidate_row(
            db_conn,
            CandidateRowSeed(
                id=candidate_id,
                fec_candidate_id=row["fec_candidate_id"],
                name=row["name"],
                office=row["office"],
                principal_committee_id=committee_id,
                total_receipts=receipts,
                total_disbursements=Decimal("0.00"),
                summary_coverage_end_date=date(2026, 3, 31),
            ),
        )
        insert_committee_summary_row(
            db_conn,
            CommitteeSummaryRowSeed(
                committee_id=committee_id,
                cycle=2026,
                total_receipts=divergent_committee_receipts,
                total_disbursements=Decimal("0.00"),
                coverage_start_date=date(2025, 1, 1),
                coverage_end_date=date(2026, 12, 31),
            ),
        )
        insert_candidate_committee_link_row(
            db_conn,
            CandidateCommitteeLinkSeed(
                id=_known_total_link_id(index),
                candidate_id=candidate_id,
                committee_id=committee_id,
                valid_period="[2025-01-01,2027-01-01)",
                designation="P",
                candidate_election_year=2026,
                fec_election_year=2026,
            ),
        )
        assert abs(divergent_committee_receipts - receipts) >= Decimal("1000000.00")
        assert receipts == 0 or divergent_committee_receipts >= receipts * Decimal("3")

    candidate_refs = _selected_fixture_candidate_refs(fixture_candidate_rows)
    summaries = campaign_finance_queries.fetch_candidate_public_money_summaries(
        db_conn,
        candidate_refs,
        selected_cycle=2026,
    )

    assert len(summaries) == len(candidate_refs)
    for index, row in enumerate(fixture["candidates"], start=1):
        summary = summaries[_known_total_candidate_id(index)]
        expected_receipts = Decimal(row["receipts"])
        _assert_decimal_within_one_percent(actual=summary["total_raised"], expected=expected_receipts)
        assert summary["summary_source"] == "fec_weball"


def test_fallback_excludes_leadership_pac_designation_d(db_conn: psycopg.Connection) -> None:
    candidate_id = UUID("72000000-0000-0000-0000-000000000001")
    committee_id = UUID("72000000-0000-0000-0000-000000000002")
    candidate_name = "LEADERSHIP PAC FALLBACK TEST"
    leadership_pac_receipts = Decimal("9876543.21")

    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="S0ZZ00004",
            name=candidate_name,
            office="S",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C70000001",
            name="LEADERSHIP PAC DESIGNATION D",
            committee_designation="D",
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=leadership_pac_receipts,
            total_disbursements=Decimal("123.45"),
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("72000000-0000-0000-0000-000000000003"),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2025-01-01,2027-01-01)",
            designation="P",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )

    summary = campaign_finance_queries.fetch_candidate_public_money_summaries(
        db_conn, [(candidate_id, candidate_name)]
    )[candidate_id]

    assert (summary["total_raised"], summary["summary_source"]) == (Decimal("0.00"), "derived")


def test_d_exclusion_preserves_legitimate_fallback_committees(db_conn: psycopg.Connection) -> None:
    cases = (
        _FallbackCommitteeCase(
            "p_only", "H0ZZ10001", "H", "P", Decimal("100.11"), Decimal("100.11"), "fec_committee_summary"
        ),
        _FallbackCommitteeCase(
            "a_only", "H0ZZ10002", "H", "A", Decimal("200.22"), Decimal("200.22"), "fec_committee_summary"
        ),
        _FallbackCommitteeCase(
            "non_pa", "S0ZZ10003", "H", "U", Decimal("300.33"), Decimal("300.33"), "fec_committee_summary"
        ),
        _FallbackCommitteeCase("d_only", "S0ZZ10004", "H", "D", Decimal("400.44"), Decimal("0.00"), "derived"),
        _FallbackCommitteeCase(
            "mixed", "S0ZZ10005", "H", "U", Decimal("600.66"), Decimal("600.66"), "fec_committee_summary"
        ),
    )
    candidate_refs = [
        _seed_fallback_committee_case(db_conn, index=index, committee_case=committee_case)
        for index, committee_case in enumerate(cases, start=1)
    ]

    mixed_candidate_id, _mixed_candidate_name = candidate_refs[-1]
    mixed_d_committee_id = UUID("72000000-0000-0000-0000-000000000206")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=mixed_d_committee_id,
            fec_committee_id="C71000006",
            name="D EXCLUSION MIXED LEADERSHIP PAC",
            committee_type="H",
            committee_designation="D",
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=mixed_d_committee_id,
            cycle=2026,
            total_receipts=Decimal("700.77"),
            total_disbursements=Decimal("0.00"),
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("72000000-0000-0000-0000-000000000306"),
            candidate_id=mixed_candidate_id,
            committee_id=mixed_d_committee_id,
            valid_period="[2025-01-01,2027-01-01)",
            designation="D",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )

    summaries = campaign_finance_queries.fetch_candidate_public_money_summaries(db_conn, candidate_refs)

    for (candidate_id, _candidate_name), committee_case in zip(
        candidate_refs,
        cases,
        strict=True,
    ):
        assert summaries[candidate_id]["total_raised"] == committee_case.expected_total_raised
        assert summaries[candidate_id]["summary_source"] == committee_case.expected_summary_source


def test_wrong_candidate_selection_flagged(db_conn: psycopg.Connection) -> None:
    selected_candidate_id = UUID("73000000-0000-0000-0000-000000000001")
    member = {"chamber": "House", "state": "NC", "district": "01"}
    nonmatching_candidates = [
        {
            "id": selected_candidate_id,
            "name": "WRONG OFFICE CANDIDATE",
            "office": "S",
            "state": "NC",
            "district": None,
        },
        {
            "id": UUID("73000000-0000-0000-0000-000000000002"),
            "name": "WRONG STATE CANDIDATE",
            "office": "H",
            "state": "VA",
            "district": "01",
        },
        {
            "id": UUID("73000000-0000-0000-0000-000000000003"),
            "name": "WRONG DISTRICT CANDIDATE",
            "office": "H",
            "state": "NC",
            "district": "02",
        },
    ]
    mismatched_candidate_ids = [candidate["id"] for candidate in nonmatching_candidates]

    assert all(not _candidate_matches_current_member(candidate, member) for candidate in nonmatching_candidates)
    selected_candidate = _select_public_money_candidate(nonmatching_candidates, member)
    assert mismatched_candidate_ids == [
        UUID("73000000-0000-0000-0000-000000000001"),
        UUID("73000000-0000-0000-0000-000000000002"),
        UUID("73000000-0000-0000-0000-000000000003"),
    ]
    assert selected_candidate["id"] == selected_candidate_id

    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=selected_candidate_id,
            fec_candidate_id="S0ZZ00005",
            name=str(selected_candidate["name"]),
            office="S",
            state="NC",
            total_receipts=Decimal("123456.78"),
            total_disbursements=Decimal("23456.78"),
            summary_coverage_end_date=date(2026, 3, 31),
        ),
    )
    summary = campaign_finance_queries.fetch_candidate_public_money_summaries(
        db_conn,
        [(selected_candidate_id, str(selected_candidate["name"]))],
    )[selected_candidate_id]

    assert summary["total_raised"] == Decimal("123456.78")
    assert summary["summary_source"] == "fec_weball"


def test_populated_db_top_chamber_totals_match_openfec_golden(db_conn: psycopg.Connection) -> None:
    """L5 runs this read-only node against production with transaction read-only enforced."""
    with db_conn.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")

    members = fetch_current_federal_members(db_conn)
    if not members:
        pytest.skip("federal roster substrate is unpopulated")

    candidates_by_person = campaign_finance_queries.fetch_candidates_for_people(
        db_conn,
        [member["person_id"] for member in members],
    )
    selected_candidates_by_person = _selected_public_money_candidates_by_person(members, candidates_by_person)
    if not selected_candidates_by_person:
        pytest.skip("federal roster has no selected campaign-finance candidates")

    fixture = _load_openfec_known_totals_fixture()
    golden_served_rows = [
        row for row in fixture["candidates"] if row["served_roster_member"] is True and row["office"] in {"H", "S"}
    ]
    selected_candidates = list(selected_candidates_by_person.values())
    selected_candidate_refs = [(candidate["id"], candidate["name"]) for candidate in selected_candidates]
    summaries = campaign_finance_queries.fetch_candidate_public_money_summaries(
        db_conn,
        selected_candidate_refs,
        selected_cycle=2026,
    )
    selected_by_fec_id = {candidate["fec_candidate_id"]: candidate for candidate in selected_candidates}

    for row in golden_served_rows:
        candidate = selected_by_fec_id.get(row["fec_candidate_id"])
        assert candidate is not None, f"golden served candidate not selected: {row['name']}"
        summary = summaries[candidate["id"]]
        _assert_decimal_within_one_percent(
            actual=summary["total_raised"],
            expected=Decimal(row["receipts"]),
        )

    for candidate in selected_candidates:
        summary = summaries[candidate["id"]]
        assert not campaign_finance_queries.exceeds_receipts_ceiling(candidate["office"], summary["total_raised"])


def test_zero_money_sitting_officeholder_surfaced(db_conn: psycopg.Connection) -> None:
    officeholders = _seed_current_federal_members_mix(db_conn)
    officeholder = next(member for member in officeholders if member.person_name == "Alice Representative")
    candidate = CandidateRowSeed(
        id=UUID("74000000-0000-0000-0000-000000000001"),
        fec_candidate_id="H0NC00006",
        name=officeholder.person_name,
        office="H",
        person_id=officeholder.person_id,
        state=officeholder.state,
        district=officeholder.district,
    )
    insert_candidate_row(db_conn, candidate)

    candidates_by_person = campaign_finance_queries.fetch_candidates_for_people(db_conn, [officeholder.person_id])
    enumerated_candidates = candidates_by_person[officeholder.person_id]
    assert [row["id"] for row in enumerated_candidates] == [candidate.id]

    summary = campaign_finance_queries.fetch_candidate_public_money_summaries(
        db_conn, [(candidate.id, candidate.name)]
    )[candidate.id]
    assert summary["total_raised"] == Decimal("0.00")
    assert summary["summary_source"] == "derived"
