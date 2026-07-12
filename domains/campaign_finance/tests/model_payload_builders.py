
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4


def _payload_with_overrides(
    defaults: dict[str, object],
    overrides: dict[str, object],
) -> dict[str, object]:
    payload = defaults.copy()
    payload.update(overrides)
    return payload


def build_committee_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "fec_committee_id": "C12345678",
            "name": "Neighbors for Better Roads",
            "committee_type": "H",
            "state": "NC",
        },
        overrides,
    )


def build_committee_summary_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "committee_id": build_uuid_string(),
            "cycle": 2024,
            "link_image": "https://www.fec.gov/data/committee/C12345678/?cycle=2024",
            "committee_name": "Neighbors for Better Roads",
            "committee_type": "H",
            "committee_designation": "P",
            "committee_filing_frequency": "Q",
            "committee_street_1": "123 Main St",
            "committee_street_2": "Suite 4",
            "committee_city": "Raleigh",
            "committee_state": "NC",
            "committee_zip": "27601",
            "treasurer_name": "Jordan Smith",
            "coverage_start_date": date(2024, 1, 1),
            "coverage_end_date": date(2024, 12, 31),
            "total_receipts": Decimal("12345.67"),
            "total_disbursements": Decimal("7654.32"),
            "cash_on_hand": Decimal("4691.35"),
            "individual_itemized_contributions": Decimal("1000.10"),
            "individual_unitemized_contributions": Decimal("2000.20"),
            "independent_expenditures": Decimal("3000.30"),
        },
        overrides,
    )


def build_candidate_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "fec_candidate_id": "H1NC00001",
            "name": "ALEX TAYLOR",
            "office": "H",
            "state": "NC",
            "district": "01",
            "incumbent_challenge": "C",
        },
        overrides,
    )


def build_filing_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "filing_fec_id": "F1234567",
            "committee_id": build_uuid_string(),
            "amendment_indicator": "N",
        },
        overrides,
    )


def build_transaction_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "filing_id": build_uuid_string(),
            "committee_id": build_uuid_string(),
            "transaction_type": "CONTRIBUTION",
            "amount": Decimal("150.00"),
            "contributor_entity_type": None,
            "amendment_indicator": "N",
        },
        overrides,
    )


def build_candidate_committee_link_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "candidate_id": build_uuid_string(),
            "committee_id": build_uuid_string(),
            "valid_period": build_valid_period_payload(),
        },
        overrides,
    )


def build_valid_period_payload(
    start: date = date(2024, 1, 1),
    end: date = date(2024, 12, 31),
) -> dict[str, date]:
    return {"start_date": start, "end_date": end}


def build_election_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "office": "H",
            "jurisdiction_type": "federal",
            "jurisdiction_code": "us",
            "district": "01",
            "candidate_election_year": 2024,
            "fec_election_year": 2024,
            "valid_period": build_valid_period_payload(),
            "date_precision": "year",
        },
        overrides,
    )


def build_uuid_string() -> str:
    return str(uuid4())


# --- IRS 527 dark money payload builders ---


def build_political_org_527_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "form_type": "8871",
            "form_id_number": "12345678",
            "ein": "12-3456789",
            "name": "Americans for Good Things",
            "mailing_address_1": "123 Main St",
            "mailing_address_city": "Washington",
            "mailing_address_state": "DC",
            "mailing_address_zip": "20001",
        },
        overrides,
    )


def build_filing_8872_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "form_type": "8872",
            "form_id_number": "87654321",
            "ein": "12-3456789",
            "period_begin_date": date(2025, 1, 1),
            "period_end_date": date(2025, 6, 30),
        },
        overrides,
    )


def build_contribution_527_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "form_id_number": "87654321",
            "sched_a_id": "A00001",
            "ein": "12-3456789",
            "contributor_name": "Jane Donor",
            "amount": Decimal("5000.00"),
            "contribution_date": date(2025, 3, 15),
            "aggregate_ytd": Decimal("10000.00"),
        },
        overrides,
    )


def build_expenditure_527_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "form_id_number": "87654321",
            "sched_b_id": "B00001",
            "ein": "12-3456789",
            "recipient_name": "Ad Agency Inc",
            "amount": Decimal("25000.00"),
            "expenditure_date": date(2025, 4, 1),
            "purpose": "Television advertising",
        },
        overrides,
    )


def build_organization_990_payload(**overrides: object) -> dict[str, object]:
    return _payload_with_overrides(
        {
            "ein": "12-3456789",
            "name": "Civic Welfare Network",
        },
        overrides,
    )
