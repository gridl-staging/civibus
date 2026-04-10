from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from domains.campaign_finance.entity_extractors.extract import extract_contribution
from domains.campaign_finance.ingest.bulk_parser import read_bulk_file
from domains.campaign_finance.ingest.field_mapper import (
    map_candidate_fields,
    map_ccl_fields,
    map_committee_fields,
    map_contribution_fields,
    parse_fec_amount,
    parse_fec_date,
)
from domains.campaign_finance.types import Candidate, CandidateCommitteeLink, Committee, ValidDateRange


_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bulk"


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
def test_map_contribution_fields_itpas2_adds_candidate_fec_id() -> None:
    row = next(read_bulk_file(_FIXTURE_DIR / "itpas2_sample.txt", "itpas2"))

    mapped = map_contribution_fields(row)

    assert mapped["candidate_fec_id"] == row["CAND_ID"]
    assert mapped["contribution_receipt_amount"] == 1000.0
    assert mapped["contribution_receipt_date"] == "2024-02-01"
    assert mapped["sub_id"] == row["SUB_ID"]

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

        candidate_payload = {key: mapped[key] for key in Candidate.model_fields if key in mapped}
        candidate_payload["principal_committee_id"] = uuid4()
        candidate = Candidate.model_validate(candidate_payload)
        assert candidate.fec_candidate_id == mapped["fec_candidate_id"]
        assert candidate.office.value == mapped["office"]


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
