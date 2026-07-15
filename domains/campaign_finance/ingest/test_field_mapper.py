from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from domains.campaign_finance.entity_extractors.extract import extract_contribution
from domains.campaign_finance.ingest.bulk_parser import read_bulk_file
from domains.campaign_finance.ingest.field_mapper import (
    map_candidate_fields,
    map_candidate_summary_fields,
    map_ccl_fields,
    map_committee_fields,
    map_contribution_fields,
    parse_fec_amount,
    parse_fec_date,
)
from domains.campaign_finance.types import Candidate, CandidateCommitteeLink, Committee, ValidDateRange


_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bulk"

_EXPECTED_ITCONT_CONTRIBUTION_MAPPINGS = {
    "900000000000001": {
        "committee_id": "C00100001",
        "contributor_name": "GARCÍA, JOSE L",
        "entity_type": "IND",
        "contributor_state": "FL",
        "contributor_city": "MIAMI",
        "contributor_zip": "331010001",
        "contributor_employer": "ACME ENERGY",
        "contributor_occupation": "ENGINEER",
        "contribution_receipt_amount": 250.0,
        "contribution_receipt_date": "2024-01-15",
        "contribution_receipt_date_is_reliable": True,
        "sub_id": "900000000000001",
        "amendment_indicator": "N",
        "report_type": "Q1",
        "transaction_type": "15",
        "image_number": "202402019123456789",
        "file_number": "1900001",
        "memo_code": None,
        "memo_text": None,
        "transaction_identifier": "A1001",
        "other_id": None,
    },
    "900000000000002": {
        "committee_id": "C00100002",
        "contributor_name": "LEE, MAYA",
        "entity_type": "IND",
        "contributor_state": "TX",
        "contributor_city": "AUSTIN",
        "contributor_zip": "733010123",
        "contributor_employer": "LONE STAR TECH",
        "contributor_occupation": "ANALYST",
        "contribution_receipt_amount": 125.5,
        "contribution_receipt_date": "2024-02-12",
        "contribution_receipt_date_is_reliable": True,
        "sub_id": "900000000000002",
        "amendment_indicator": "N",
        "report_type": "Q1",
        "transaction_type": "15",
        "image_number": "202402029123456790",
        "file_number": "1900002",
        "memo_code": "X",
        "memo_text": "EARMARKED THROUGH PLATFORM",
        "transaction_identifier": "A1002",
        "other_id": None,
    },
    "900000000000003": {
        "committee_id": "C00100003",
        "contributor_name": "NATIONAL EDUCATORS PAC",
        "entity_type": "COM",
        "contributor_state": "OH",
        "contributor_city": "COLUMBUS",
        "contributor_zip": "430850000",
        "contributor_employer": None,
        "contributor_occupation": None,
        "contribution_receipt_amount": 5000.0,
        "contribution_receipt_date": "2024-02-20",
        "contribution_receipt_date_is_reliable": True,
        "sub_id": "900000000000003",
        "amendment_indicator": "N",
        "report_type": "Q1",
        "transaction_type": "15",
        "image_number": "202402039123456791",
        "file_number": "1900003",
        "memo_code": None,
        "memo_text": None,
        "transaction_identifier": "A1003",
        "other_id": "C00100004",
    },
    "900000000000004": {
        "committee_id": "C00100004",
        "contributor_name": "PATEL, RINA",
        "entity_type": "IND",
        "contributor_state": "NC",
        "contributor_city": "DURHAM",
        "contributor_zip": "277010555",
        "contributor_employer": "CIVIC DATA LLC",
        "contributor_occupation": "FOUNDER",
        "contribution_receipt_amount": 75.0,
        "contribution_receipt_date": "2024-03-01",
        "contribution_receipt_date_is_reliable": True,
        "sub_id": "900000000000004",
        "amendment_indicator": "N",
        "report_type": "Q1",
        "transaction_type": "15E",
        "image_number": "202402049123456792",
        "file_number": "1900004",
        "memo_code": None,
        "memo_text": None,
        "transaction_identifier": "A1004",
        "other_id": None,
    },
    "900000000000005": {
        "committee_id": "C00100005",
        "contributor_name": "CITIZENS FOR TRANSPARENCY",
        "entity_type": "COM",
        "contributor_state": "AZ",
        "contributor_city": "PHOENIX",
        "contributor_zip": "850040777",
        "contributor_employer": None,
        "contributor_occupation": None,
        "contribution_receipt_amount": -45.0,
        "contribution_receipt_date": "2024-03-05",
        "contribution_receipt_date_is_reliable": True,
        "sub_id": "900000000000005",
        "amendment_indicator": "A",
        "report_type": "Q1",
        "transaction_type": "22Y",
        "image_number": "202402059123456793",
        "file_number": "1900005",
        "memo_code": "X",
        "memo_text": "REFUND CHECK RETURNED",
        "transaction_identifier": "A1005",
        "other_id": "C00100002",
    },
    "900000000000006": {
        "committee_id": "C00100001",
        "contributor_name": "MORGAN, TAYLOR",
        "entity_type": "IND",
        "contributor_state": "FL",
        "contributor_city": "MIAMI",
        "contributor_zip": "331010001",
        "contributor_employer": "ACME ENERGY",
        "contributor_occupation": "ENGINEER",
        "contribution_receipt_amount": 10.0,
        "contribution_receipt_date": "2021-12-31",
        "contribution_receipt_date_is_reliable": True,
        "sub_id": "900000000000006",
        "amendment_indicator": "N",
        "report_type": "YE",
        "transaction_type": "15",
        "image_number": "202101319123456794",
        "file_number": "1900006",
        "memo_code": None,
        "memo_text": None,
        "transaction_identifier": "A1006",
        "other_id": None,
    },
}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("01012024", "2024-01-01"),
        ("02292024", "2024-02-29"),
        (None, None),
        ("", None),
        ("   ", None),
        ("00000000", None),
        ("1234567", None),
        ("13012024", None),
        ("02312024", None),
        ("02292023", None),
    ],
)
def test_parse_fec_date_valid_and_edge_cases(raw_value: str | None, expected: str | None) -> None:
    assert parse_fec_date(raw_value) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("250", 250.0),
        (" 125.50 ", 125.5),
        ("-45.00", -45.0),
        (None, None),
        ("", None),
        ("   ", None),
        ("12.3.4", None),
        ("abc", None),
    ],
)
def test_parse_fec_amount_valid_and_edge_cases(raw_value: str | None, expected: float | None) -> None:
    assert parse_fec_amount(raw_value) == expected


@pytest.mark.unit
def test_map_contribution_fields_itcont_contract_and_extractor_compatibility() -> None:
    row = next(read_bulk_file(_FIXTURE_DIR / "itcont_sample.txt", "itcont"))

    mapped = map_contribution_fields(row)

    expected_keys = {
        "committee_id",
        "contributor_name",
        "entity_type",
        "contributor_state",
        "contributor_city",
        "contributor_zip",
        "contributor_employer",
        "contributor_occupation",
        "contribution_receipt_amount",
        "contribution_receipt_date",
        "contribution_receipt_date_is_reliable",
        "sub_id",
        "amendment_indicator",
        "report_type",
        "transaction_type",
        "image_number",
        "file_number",
        "memo_code",
        "memo_text",
        "transaction_identifier",
        "other_id",
    }
    assert set(mapped.keys()) == expected_keys
    assert mapped["contribution_receipt_amount"] == 250.0
    assert mapped["contribution_receipt_date"] == "2024-01-15"
    assert mapped["sub_id"] == row["SUB_ID"]
    assert "candidate_fec_id" not in mapped
    assert "committee_name" not in mapped
    assert "committee" not in mapped

    extracted = extract_contribution(mapped)
    assert extracted["organization"].identifiers["fec_committee_id"] == mapped["committee_id"]


@pytest.mark.unit
def test_map_contribution_fields_itcont_contract_rows_have_exact_typed_values() -> None:
    rows = list(read_bulk_file(_FIXTURE_DIR / "itcont_sample.txt", "itcont"))

    mapped_by_sub_id = {row["SUB_ID"]: map_contribution_fields(row) for row in rows}

    assert mapped_by_sub_id == _EXPECTED_ITCONT_CONTRIBUTION_MAPPINGS
    assert mapped_by_sub_id["900000000000001"]["contributor_zip"] == "331010001"
    assert mapped_by_sub_id["900000000000005"]["contribution_receipt_amount"] == -45.0


@pytest.mark.unit
def test_map_contribution_fields_itpas2_adds_candidate_fec_id() -> None:
    row = next(read_bulk_file(_FIXTURE_DIR / "itpas2_sample.txt", "itpas2"))

    mapped = map_contribution_fields(row)

    assert mapped["candidate_fec_id"] == row["CAND_ID"]
    assert mapped["contribution_receipt_amount"] == 1000.0
    assert mapped["contribution_receipt_date"] == "2024-02-01"


@pytest.mark.unit
def test_map_contribution_fields_marks_invalid_transaction_date_unreliable() -> None:
    mapped = map_contribution_fields(
        {
            "CMTE_ID": "C00100001",
            "TRANSACTION_DT": "13012024",
            "TRANSACTION_AMT": "25.00",
            "SUB_ID": "1",
        }
    )

    assert mapped["contribution_receipt_date"] is None
    assert mapped["contribution_receipt_date_is_reliable"] is False
    assert mapped["sub_id"] == "1"

    extracted = extract_contribution(mapped)
    assert extracted["organization"].identifiers["fec_committee_id"] == mapped["committee_id"]


@pytest.mark.unit
def test_map_committee_fields_creates_committee_compatible_rows_and_covers_expected_types() -> None:
    source_rows = list(read_bulk_file(_FIXTURE_DIR / "cm_sample.txt", "cm"))
    mapped_rows = [map_committee_fields(row) for row in source_rows]

    committee_types = set()
    for source_row, mapped_row in zip(source_rows, mapped_rows, strict=True):
        committee_types.add(mapped_row["committee_type"])
        committee_payload = {key: mapped_row[key] for key in Committee.model_fields if key in mapped_row}
        committee = Committee.model_validate(committee_payload)
        assert committee.fec_committee_id == mapped_row["fec_committee_id"]
        assert committee.name == mapped_row["name"]
        assert mapped_row["candidate_fec_id"] == source_row["CAND_ID"]
        assert mapped_row["connected_organization_name"] == source_row["CONNECTED_ORG_NM"]

    assert committee_types == {"H", "S", "P", "Q", "N"}


@pytest.mark.unit
def test_map_candidate_fields_creates_candidate_compatible_rows_with_principal_committee_fec_id() -> None:
    candidate_rows = list(read_bulk_file(_FIXTURE_DIR / "cn_sample.txt", "cn"))
    selected_candidate_rows = [candidate_rows[0], candidate_rows[2], candidate_rows[4]]

    for row in selected_candidate_rows:
        mapped = map_candidate_fields(row)
        assert mapped["principal_committee_fec_id"] == row["CAND_PCC"]
        assert mapped["candidate_election_year"] == int(row["CAND_ELECTION_YR"])
        assert mapped["candidate_status"] == row["CAND_STATUS"]

        candidate_payload = {key: mapped[key] for key in Candidate.model_fields if key in mapped}
        candidate_payload["principal_committee_id"] = uuid4()
        candidate = Candidate.model_validate(candidate_payload)
        assert candidate.fec_candidate_id == mapped["fec_candidate_id"]
        assert candidate.office.value == mapped["office"]


@pytest.mark.parametrize("candidate_election_year", ["", "   ", "not-a-year"])
@pytest.mark.unit
def test_map_candidate_fields_returns_none_for_missing_or_invalid_candidate_election_year(
    candidate_election_year: str,
) -> None:
    row = {
        "CAND_ID": "H0NC01001",
        "CAND_NAME": "RIVERS, ALEX",
        "CAND_PTY_AFFILIATION": "DEM",
        "CAND_ELECTION_YR": candidate_election_year,
        "CAND_OFFICE_ST": "NC",
        "CAND_OFFICE": "H",
        "CAND_OFFICE_DISTRICT": "01",
        "CAND_ICI": "C",
        "CAND_STATUS": "C",
        "CAND_PCC": "C00100001",
    }

    mapped = map_candidate_fields(row)

    assert mapped["candidate_election_year"] is None


@pytest.mark.parametrize("candidate_status", ["", "   "])
@pytest.mark.unit
def test_map_candidate_fields_returns_none_for_blank_candidate_status(candidate_status: str) -> None:
    row = {
        "CAND_ID": "H0NC01001",
        "CAND_NAME": "RIVERS, ALEX",
        "CAND_PTY_AFFILIATION": "DEM",
        "CAND_ELECTION_YR": "2024",
        "CAND_OFFICE_ST": "NC",
        "CAND_OFFICE": "H",
        "CAND_OFFICE_DISTRICT": "01",
        "CAND_ICI": "C",
        "CAND_STATUS": candidate_status,
        "CAND_PCC": "C00100001",
    }

    mapped = map_candidate_fields(row)

    assert mapped["candidate_status"] is None


@pytest.mark.unit
def test_map_candidate_summary_fields_uses_exact_decimal_totals_and_coverage_date() -> None:
    row = {
        **next(read_bulk_file(_FIXTURE_DIR / "weball_sample.txt", "weball")),
        "CAND_CONTRIB": "250.01",
        "CAND_LOANS": "125.02",
        "CAND_LOAN_REPAY": "75.03",
    }

    mapped = map_candidate_summary_fields(row)

    assert mapped == {
        "fec_candidate_id": "H0NC01001",
        "total_receipts": Decimal("12345.67"),
        "total_disbursements": Decimal("8910.11"),
        "cash_on_hand": Decimal("3535.56"),
        "candidate_contrib": Decimal("250.01"),
        "candidate_loans": Decimal("125.02"),
        "candidate_loan_repay": Decimal("75.03"),
        "summary_coverage_end_date": "2024-12-31",
    }

    candidate = Candidate.model_validate(
        {
            "fec_candidate_id": "H0NC01001",
            "name": "RIVERS, ALEX",
            "office": "H",
            "total_receipts": mapped["total_receipts"],
            "total_disbursements": mapped["total_disbursements"],
            "cash_on_hand": mapped["cash_on_hand"],
            "candidate_contrib": mapped["candidate_contrib"],
            "candidate_loans": mapped["candidate_loans"],
            "candidate_loan_repay": mapped["candidate_loan_repay"],
            "summary_coverage_end_date": mapped["summary_coverage_end_date"],
        }
    )
    assert candidate.total_receipts == Decimal("12345.67")
    assert candidate.total_disbursements == Decimal("8910.11")
    assert candidate.cash_on_hand == Decimal("3535.56")
    assert candidate.candidate_contrib == Decimal("250.01")
    assert candidate.candidate_loans == Decimal("125.02")
    assert candidate.candidate_loan_repay == Decimal("75.03")
    assert candidate.summary_coverage_end_date == date(2024, 12, 31)


@pytest.mark.unit
def test_map_candidate_summary_fields_maps_blank_self_funding_values_to_none() -> None:
    mapped = map_candidate_summary_fields(
        {
            "CAND_ID": "H0NC01001",
            "TTL_RECEIPTS": "100.00",
            "TTL_DISB": "25.00",
            "COH_COP": "75.00",
            "CAND_CONTRIB": "",
            "CAND_LOANS": "   ",
            "CAND_LOAN_REPAY": None,
            "CVG_END_DT": "12/31/2024",
        }
    )

    assert mapped["candidate_contrib"] is None
    assert mapped["candidate_loans"] is None
    assert mapped["candidate_loan_repay"] is None


@pytest.mark.unit
def test_map_ccl_fields_creates_loader_friendly_values_and_model_compatible_payload() -> None:
    row = next(read_bulk_file(_FIXTURE_DIR / "ccl_sample.txt", "ccl"))

    mapped = map_ccl_fields(row)

    assert mapped["candidate_fec_id"] == row["CAND_ID"]
    assert mapped["committee_fec_id"] == row["CMTE_ID"]
    assert mapped["committee_type"] == row["CMTE_TP"]
    assert mapped["linkage_id"] == row["LINKAGE_ID"]
    assert mapped["candidate_election_year"] == 2024
    assert mapped["fec_election_year"] == 2024

    link_payload = {key: mapped[key] for key in CandidateCommitteeLink.model_fields if key in mapped}
    link_payload["candidate_id"] = uuid4()
    link_payload["committee_id"] = uuid4()
    link_payload["valid_period"] = ValidDateRange(start_date=date(2024, 1, 1), end_date=date(2025, 1, 1))
    link = CandidateCommitteeLink.model_validate(link_payload)
    assert link.designation == mapped["designation"]
    assert link.candidate_election_year == mapped["candidate_election_year"]
    assert link.fec_election_year == mapped["fec_election_year"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("file_type", "fixture_name", "mapper"),
    [
        ("itcont", "itcont_sample.txt", map_contribution_fields),
        ("itpas2", "itpas2_sample.txt", map_contribution_fields),
        ("cm", "cm_sample.txt", map_committee_fields),
        ("cn", "cn_sample.txt", map_candidate_fields),
        ("ccl", "ccl_sample.txt", map_ccl_fields),
        ("weball", "weball_sample.txt", map_candidate_summary_fields),
    ],
)
def test_end_to_end_stage1_row_to_stage2_mapper_contract(
    file_type: str,
    fixture_name: str,
    mapper: Callable[[dict[str, str | None]], dict[str, object]],
) -> None:
    row = next(read_bulk_file(_FIXTURE_DIR / fixture_name, file_type))
    mapped = mapper(row)
    assert mapped
