from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

import api.models as api_models
from api.models import (
    CandidateFundraisingSummary,
    CandidateListItem,
    CandidateResponse,
    CommitteeCycleSummary,
    CommitteeFilingBreakdown,
    ClusterMemberResponse,
    CommitteeFundraisingSummary,
    CommitteeIndependentExpenditureTarget,
    CommitteeResponse,
    PersonContributionInsights,
    DonorsWithPropertyParams,
    DonorsWithPropertyResult,
    ERClusterDetailResponse,
    ERClusterListParams,
    ERClusterSummaryResponse,
    ERSummaryResponse,
    FilingResponse,
    FilingPeriodSummary,
    IndependentExpenditureResponse,
    IndependentExpenditureSummary,
    MatchDecisionResponse,
    OrgResponse,
    ParcelDetailResponse,
    ParcelListParams,
    ParcelSummaryResponse,
    PersonResponse,
    PersonPortraitResponse,
    PersonSlugResult,
    PropertyAssessmentResponse,
    PropertyOwnershipResponse,
    ReceiptSourceComponent,
    SearchParams,
    SearchResult,
    StateCandidateTopEntry,
    StateCommitteeTopEntry,
    StateDetailResponse,
    StateIndependentExpenditureTopSpender,
    StateSummaryItem,
    SourceInfo,
    TopSpenderEntry,
    TransactionListParams,
    TransactionResponse,
)
from domains.campaign_finance.constants import FILING_BREAKDOWN_STORE_LIMIT


def _source_info_payload() -> dict[str, object]:
    return {
        "domain": "campaign_finance",
        "jurisdiction": None,
        "data_source_name": "FEC Bulk",
        "data_source_url": "https://example.org/fec",
        "source_record_key": None,
        "record_url": None,
        "pull_date": datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
    }


def _candidate_money_coverage_payload(
    *,
    activity_state: str = "populated",
    completeness: str = "complete",
    basis: str = "fec_official_candidate_summary",
) -> dict[str, str]:
    return {
        "activity_state": activity_state,
        "completeness": completeness,
        "basis": basis,
    }


def test_source_info_requires_domain() -> None:
    payload = _source_info_payload()
    payload.pop("domain")

    with pytest.raises(ValidationError):
        SourceInfo.model_validate(payload)


def test_source_info_serializes_optional_fields_as_null_and_round_trips() -> None:
    source = SourceInfo.model_validate(_source_info_payload())

    dumped = source.model_dump(mode="json")

    assert dumped["jurisdiction"] is None
    assert dumped["source_record_key"] is None
    assert dumped["record_url"] is None
    assert SourceInfo.model_validate(dumped).model_dump(mode="json") == dumped


def test_person_response_requires_canonical_name() -> None:
    payload = {
        "id": str(uuid4()),
        "name_variants": [],
        "identifiers": {},
        "sources": [_source_info_payload()],
    }

    with pytest.raises(ValidationError):
        PersonResponse.model_validate(payload)


def test_person_response_serializes_optional_fields_as_null_and_round_trips() -> None:
    person_id = uuid4()
    portrait_payload = PersonPortraitResponse.model_validate(
        {
            "status": "active",
            "rights_status": "licensed",
            "source_image_url": "https://images.example.org/jane-doe.jpg",
            "mime_type": "image/jpeg",
            "width_px": 640,
            "height_px": 480,
        }
    )
    response = PersonResponse.model_validate(
        {
            "id": person_id,
            "canonical_name": "Jane Doe",
            "name_variants": [],
            "portrait": portrait_payload,
            "identifiers": {},
            "sources": [_source_info_payload()],
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(person_id)
    assert dumped["first_name"] is None
    assert dumped["middle_name"] is None
    assert dumped["last_name"] is None
    assert dumped["suffix"] is None
    assert dumped["date_of_birth"] is None
    assert dumped["year_of_birth"] is None
    assert dumped["bio_text"] is None
    assert dumped["bio_source_url"] is None
    assert dumped["bio_license"] is None
    assert dumped["bio_pulled_at"] is None
    assert dumped["primary_address_id"] is None
    assert dumped["er_cluster_id"] is None
    assert dumped["er_confidence"] is None
    assert dumped["portrait"] == {
        "status": "active",
        "rights_status": "licensed",
        "source_image_url": "https://images.example.org/jane-doe.jpg",
        "mime_type": "image/jpeg",
        "width_px": 640,
        "height_px": 480,
    }
    assert PersonResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_org_response_requires_canonical_name() -> None:
    payload = {
        "id": str(uuid4()),
        "name_variants": [],
        "identifiers": {},
        "sources": [_source_info_payload()],
    }

    with pytest.raises(ValidationError):
        OrgResponse.model_validate(payload)


def test_org_response_serializes_optional_fields_as_null_and_round_trips() -> None:
    org_id = UUID("00000000-0000-0000-0000-000000000099")
    response = OrgResponse.model_validate(
        {
            "id": org_id,
            "canonical_name": "Civibus PAC",
            "name_variants": [],
            "identifiers": {},
            "sources": [_source_info_payload()],
            "formation_date": date(2012, 4, 2),
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(org_id)
    assert dumped["org_type"] is None
    assert dumped["registered_state"] is None
    assert dumped["dissolution_date"] is None
    assert dumped["primary_address_id"] is None
    assert dumped["er_cluster_id"] is None
    assert dumped["er_confidence"] is None
    assert OrgResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_committee_response_requires_fec_committee_id() -> None:
    payload = {
        "id": str(uuid4()),
        "name": "Civibus Committee",
        "sources": [_source_info_payload()],
    }

    with pytest.raises(ValidationError):
        CommitteeResponse.model_validate(payload)


def test_committee_response_serializes_optional_fields_as_null_and_round_trips() -> None:
    committee_id = uuid4()
    response = CommitteeResponse.model_validate(
        {
            "id": committee_id,
            "fec_committee_id": "C12345678",
            "name": "Civibus Committee",
            "slug": "civibus-committee",
            "slug_is_unique": True,
            "sources": [_source_info_payload()],
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(committee_id)
    assert dumped["slug"] == "civibus-committee"
    assert dumped["slug_is_unique"] is True
    assert dumped["organization_id"] is None
    assert dumped["committee_type"] is None
    assert dumped["committee_designation"] is None
    assert dumped["party"] is None
    assert dumped["state"] is None
    assert dumped["city"] is None
    assert dumped["zip_code"] is None
    assert dumped["treasurer_name"] is None
    assert "created_at" not in dumped
    assert "updated_at" not in dumped
    assert CommitteeResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_candidate_response_requires_office() -> None:
    payload = {
        "id": str(uuid4()),
        "fec_candidate_id": "H0NC01001",
        "name": "Jane Doe",
        "sources": [_source_info_payload()],
    }

    with pytest.raises(ValidationError):
        CandidateResponse.model_validate(payload)


def test_candidate_response_serializes_optional_fields_as_null_and_round_trips() -> None:
    candidate_id = uuid4()
    response = CandidateResponse.model_validate(
        {
            "id": candidate_id,
            "fec_candidate_id": "H0NC01001",
            "name": "Jane Doe",
            "slug": "jane-doe",
            "slug_is_unique": True,
            "identity_is_safe": True,
            "office": "H",
            "sources": [_source_info_payload()],
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(candidate_id)
    assert dumped["slug"] == "jane-doe"
    assert dumped["slug_is_unique"] is True
    assert dumped["identity_is_safe"] is True
    assert dumped["person_id"] is None
    assert dumped["party"] is None
    assert dumped["state"] is None
    assert dumped["district"] is None
    assert dumped["incumbent_challenge"] is None
    assert dumped["principal_committee_id"] is None
    assert "created_at" not in dumped
    assert "updated_at" not in dumped
    assert CandidateResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_candidate_response_round_trips_identity_is_safe_false() -> None:
    payload = {
        "id": str(uuid4()),
        "fec_candidate_id": "H0NC01002",
        "name": "212 N HALF  W. JOHN, RODNEY HOWARD MR.",
        "slug": "212-n-half-w-john-rodney-howard-mr",
        "slug_is_unique": True,
        "identity_is_safe": False,
        "office": "H",
        "sources": [_source_info_payload()],
    }

    dumped = CandidateResponse.model_validate(payload).model_dump(mode="json")

    assert dumped["identity_is_safe"] is False
    assert CandidateResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_candidate_response_requires_identity_is_safe() -> None:
    payload = {
        "id": str(uuid4()),
        "fec_candidate_id": "H0NC01001",
        "name": "Jane Doe",
        "slug": "jane-doe",
        "slug_is_unique": True,
        "office": "H",
        "sources": [_source_info_payload()],
    }

    with pytest.raises(ValidationError):
        CandidateResponse.model_validate(payload)


def test_person_contribution_insights_geography_round_trips_money_and_metadata() -> None:
    person_id = uuid4()
    response = PersonContributionInsights.model_validate(
        {
            "person_id": person_id,
            "has_data": True,
            "metadata": {
                "selected_cycle": 2026,
                "coverage_start_date": date(2025, 1, 1),
                "coverage_end_date": date(2026, 12, 31),
                "available_cycles": [2022, 2024, 2026],
                "cycles_included": [2024, 2026],
                "committee_count": 2,
                "approximate_geography": True,
                "excluded_geography": None,
                "caveats": ["missing_committee_summary"],
            },
            "monthly_totals": [{"month": "2024-02", "total_amount": Decimal("250.00"), "transaction_count": 2}],
            "itemized_size_buckets": [
                {
                    "label": "$200 and under",
                    "min_amount": Decimal("0.01"),
                    "max_amount": Decimal("200.00"),
                    "total_amount": Decimal("250.00"),
                    "transaction_count": 2,
                }
            ],
            "dollars_by_size": [
                {"label": "Unitemized (<$200)", "total_amount": Decimal("500.00"), "source": "committee_summary"}
            ],
            "geography": {
                "by_state": [{"label": "NC", "total_amount": Decimal("250.00"), "transaction_count": 2}],
                "by_district": [{"label": "In district", "total_amount": Decimal("250.00"), "transaction_count": 2}],
                "geography_mode": "district",
                "classified_amount": Decimal("250.00"),
                "classified_transaction_count": 2,
                "unknown_amount": Decimal("0.00"),
                "unknown_transaction_count": 0,
                "district_share": {
                    "in_district_amount": Decimal("250.00"),
                    "out_of_district_amount": Decimal("0.00"),
                    "unknown_district_amount": Decimal("0.00"),
                    "share": Decimal("1.0000"),
                    "available": True,
                },
            },
            "small_dollar_share": {
                "small_dollar_amount": Decimal("750.00"),
                "total_contribution_amount": Decimal("1000.00"),
                "share": Decimal("0.7500"),
                "available": True,
            },
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["person_id"] == str(person_id)
    assert dumped["metadata"]["selected_cycle"] == 2026
    assert dumped["metadata"]["coverage_start_date"] == "2025-01-01"
    assert dumped["metadata"]["coverage_end_date"] == "2026-12-31"
    assert dumped["metadata"]["available_cycles"] == [2022, 2024, 2026]
    assert dumped["monthly_totals"][0]["total_amount"] == "250.00"
    assert dumped["geography"]["geography_mode"] == "district"
    assert dumped["geography"]["classified_amount"] == "250.00"
    assert dumped["geography"]["district_share"]["share"] == "1.0000"
    assert dumped["small_dollar_share"]["share"] == "0.7500"
    assert PersonContributionInsights.model_validate(dumped).model_dump(mode="json") == dumped


@pytest.mark.parametrize("month", ["2024-2", "2024-02-01", "02-2024", "2024-13"])
def test_contribution_insights_monthly_total_rejects_non_backend_month_strings(month: str) -> None:
    with pytest.raises(ValidationError):
        PersonContributionInsights.model_validate(
            {
                "person_id": str(uuid4()),
                "has_data": True,
                "metadata": {
                    "selected_cycle": 2026,
                    "coverage_start_date": date(2025, 1, 1),
                    "coverage_end_date": date(2026, 12, 31),
                    "committee_count": 1,
                    "approximate_geography": False,
                },
                "monthly_totals": [{"month": month, "total_amount": Decimal("0.00"), "transaction_count": 0}],
                "geography": {
                    "district_share": {
                        "in_district_amount": None,
                        "out_of_district_amount": None,
                        "unknown_district_amount": None,
                        "share": None,
                        "available": False,
                    }
                },
                "small_dollar_share": {
                    "small_dollar_amount": None,
                    "total_contribution_amount": None,
                    "share": None,
                    "available": False,
                },
            }
        )


def test_filing_response_requires_required_fields() -> None:
    payload = {"id": str(uuid4())}

    with pytest.raises(ValidationError):
        FilingResponse.model_validate(payload)


def test_filing_response_serializes_optional_fields_as_null_and_round_trips() -> None:
    filing_id = UUID("00000000-0000-0000-0000-000000000211")
    committee_id = UUID("00000000-0000-0000-0000-000000000212")
    response = FilingResponse.model_validate(
        {
            "id": filing_id,
            "filing_fec_id": "1290024",
            "committee_id": committee_id,
            "amendment_indicator": "N",
            "is_amended": False,
            "sources": [_source_info_payload()],
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(filing_id)
    assert dumped["committee_id"] == str(committee_id)
    assert dumped["candidate_id"] is None
    assert dumped["election_id"] is None
    assert dumped["report_type"] is None
    assert dumped["filing_name"] is None
    assert dumped["coverage_start_date"] is None
    assert dumped["coverage_end_date"] is None
    assert dumped["due_date"] is None
    assert dumped["receipt_date"] is None
    assert dumped["accepted_date"] is None
    assert dumped["amended_from_filing_id"] is None
    assert dumped["days_late"] is None
    assert FilingResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_transaction_response_requires_required_fields() -> None:
    payload = {"id": str(uuid4())}

    with pytest.raises(ValidationError):
        TransactionResponse.model_validate(payload)


def test_transaction_response_serializes_optional_fields_as_null_and_round_trips() -> None:
    transaction_id = uuid4()
    filing_id = uuid4()
    committee_id = uuid4()
    response = TransactionResponse.model_validate(
        {
            "id": transaction_id,
            "filing_id": filing_id,
            "committee_id": committee_id,
            "transaction_type": "15",
            "transaction_identifier": None,
            "transaction_date": date(2026, 3, 15),
            "amount": 123.45,
            "contributor_name_raw": None,
            "contributor_employer": None,
            "contributor_occupation": None,
            "contributor_city": None,
            "contributor_state": None,
            "contributor_zip": None,
            "contributor_person_id": None,
            "contributor_organization_id": None,
            "contributor_address_id": None,
            "recipient_candidate_id": None,
            "recipient_committee_id": None,
            "memo_text": None,
            "is_memo": False,
            "amendment_indicator": "N",
            "date_is_reliable": True,
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(transaction_id)
    assert dumped["filing_id"] == str(filing_id)
    assert dumped["committee_id"] == str(committee_id)
    assert dumped["transaction_date"] == "2026-03-15"
    assert dumped["amount"] == pytest.approx(123.45)
    assert dumped["contributor_name_raw"] is None
    assert dumped["recipient_candidate_id"] is None
    assert dumped["memo_text"] is None
    # IE fields default to None for non-Schedule-E transactions
    assert dumped["support_oppose"] is None
    assert dumped["dissemination_date"] is None
    assert dumped["aggregate_amount"] is None
    assert "sub_id" not in dumped
    assert "memo_code" not in dumped
    assert "amended_by_transaction_id" not in dumped
    assert "created_at" not in dumped
    assert "updated_at" not in dumped
    assert TransactionResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_transaction_response_accepts_populated_ie_fields() -> None:
    """Prove TransactionResponse accepts IE values without breaking required-field expectations."""
    payload = {
        "id": str(uuid4()),
        "filing_id": str(uuid4()),
        "committee_id": str(uuid4()),
        "transaction_type": "24E",
        "transaction_date": "2026-03-15",
        "amount": 5000.00,
        "is_memo": False,
        "amendment_indicator": "N",
        "date_is_reliable": True,
        "support_oppose": "O",
        "dissemination_date": "2026-03-10",
        "aggregate_amount": 12500.50,
    }
    response = TransactionResponse.model_validate(payload)
    dumped = response.model_dump(mode="json")

    assert dumped["support_oppose"] == "O"
    assert dumped["dissemination_date"] == "2026-03-10"
    assert dumped["aggregate_amount"] == pytest.approx(12500.50)
    # Required fields still enforced
    assert dumped["transaction_type"] == "24E"
    assert dumped["is_memo"] is False
    assert dumped["amendment_indicator"] == "N"
    # Round-trip
    assert TransactionResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_ie_independent_expenditure_response_requires_required_fields() -> None:
    with pytest.raises(ValidationError):
        IndependentExpenditureResponse.model_validate({"id": str(uuid4())})


def test_ie_independent_expenditure_response_serializes_nullable_fields_and_round_trips() -> None:
    payload = {
        "id": str(uuid4()),
        "filing_id": None,
        "committee_id": str(uuid4()),
        "committee_name": "Independent Spenders PAC",
        "amount": 2345.67,
        "transaction_date": "2026-03-18",
        "purpose": None,
        "dissemination_date": None,
        "aggregate_amount": None,
        "support_oppose": "S",
    }

    response = IndependentExpenditureResponse.model_validate(payload)
    dumped = response.model_dump(mode="json")

    assert dumped["purpose"] is None
    assert dumped["filing_id"] is None
    assert dumped["dissemination_date"] is None
    assert dumped["aggregate_amount"] is None
    assert dumped["support_oppose"] == "S"
    assert "memo_text" not in dumped
    assert IndependentExpenditureResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_ie_independent_expenditure_response_rejects_invalid_support_oppose() -> None:
    with pytest.raises(ValidationError):
        IndependentExpenditureResponse.model_validate(
            {
                "id": str(uuid4()),
                "filing_id": str(uuid4()),
                "committee_id": str(uuid4()),
                "committee_name": "Independent Spenders PAC",
                "amount": 100.0,
                "transaction_date": "2026-03-18",
                "purpose": "Digital ad buy",
                "dissemination_date": "2026-03-17",
                "aggregate_amount": 1000.0,
                "support_oppose": "X",
            }
        )


def test_ie_independent_expenditure_summary_round_trips_with_ranked_top_spenders() -> None:
    summary = IndependentExpenditureSummary.model_validate(
        {
            "candidate_id": str(uuid4()),
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "support_total": Decimal("1200.50"),
            "oppose_total": Decimal("900.25"),
            "support_count": 3,
            "oppose_count": 2,
            "top_spenders": [
                {
                    "committee_id": str(uuid4()),
                    "committee_name": "Support Committee",
                    "support_oppose": "S",
                    "total_amount": Decimal("700.25"),
                    "transaction_count": 2,
                },
                {
                    "committee_id": str(uuid4()),
                    "committee_name": "Oppose Committee",
                    "support_oppose": "O",
                    "total_amount": Decimal("500.00"),
                    "transaction_count": 1,
                },
            ],
            "coverage": _candidate_money_coverage_payload(
                activity_state="populated",
                completeness="partial",
                basis="fec_schedule_e_transactions",
            ),
        }
    )

    dumped = summary.model_dump(mode="json")

    assert dumped["coverage"] == {
        "activity_state": "populated",
        "completeness": "partial",
        "basis": "fec_schedule_e_transactions",
    }
    assert dumped["support_total"] == "1200.50"
    assert dumped["selected_cycle"] == 2026
    assert dumped["coverage_start_date"] == "2025-01-01"
    assert dumped["coverage_end_date"] == "2026-12-31"
    assert dumped["available_cycles"] == [2022, 2024, 2026]
    assert dumped["oppose_total"] == "900.25"
    assert dumped["support_count"] == 3
    assert dumped["oppose_count"] == 2
    assert dumped["top_spenders"][0]["support_oppose"] == "S"
    assert dumped["top_spenders"][1]["support_oppose"] == "O"
    assert IndependentExpenditureSummary.model_validate(dumped).model_dump(mode="json") == dumped


def test_ie_independent_expenditure_summary_requires_closed_coverage_contract() -> None:
    payload = {
        "candidate_id": str(uuid4()),
        "selected_cycle": 2026,
        "coverage_start_date": date(2025, 1, 1),
        "coverage_end_date": date(2026, 12, 31),
        "available_cycles": [2022, 2024, 2026],
        "support_total": Decimal("0.00"),
        "oppose_total": Decimal("0.00"),
        "support_count": 0,
        "oppose_count": 0,
        "top_spenders": [],
    }

    with pytest.raises(ValidationError):
        IndependentExpenditureSummary.model_validate(payload)

    for field_name in ("activity_state", "completeness", "basis"):
        invalid_payload = {
            **payload,
            "coverage": {
                **_candidate_money_coverage_payload(
                    activity_state="not_loaded",
                    completeness="unknown",
                    basis="no_authoritative_load_evidence",
                ),
                field_name: "unexpected_value",
            },
        }
        with pytest.raises(ValidationError):
            IndependentExpenditureSummary.model_validate(invalid_payload)


def test_ie_top_spender_entry_rejects_invalid_support_oppose() -> None:
    with pytest.raises(ValidationError):
        TopSpenderEntry.model_validate(
            {
                "committee_id": str(uuid4()),
                "committee_name": "Invalid Entry Committee",
                "support_oppose": "N",
                "total_amount": Decimal("15.00"),
                "transaction_count": 1,
            }
        )


def test_transaction_list_params_defaults() -> None:
    params = TransactionListParams.model_validate({})

    dumped = params.model_dump(mode="json")
    assert dumped["committee_id"] is None
    assert dumped["jurisdiction"] is None
    assert dumped["min_date"] is None
    assert dumped["max_date"] is None
    assert dumped["min_amount"] is None
    assert dumped["max_amount"] is None
    assert dumped["limit"] == 50
    assert dumped["offset"] == 0


def test_transaction_list_params_accepts_inclusive_filters() -> None:
    params = TransactionListParams.model_validate(
        {
            "committee_id": str(uuid4()),
            "jurisdiction": "state/co",
            "min_date": "2026-03-01",
            "max_date": "2026-03-31",
            "min_amount": 10.5,
            "max_amount": 99.99,
            "limit": 200,
            "offset": 5,
        }
    )
    dumped = params.model_dump(mode="json")

    assert dumped["min_date"] == "2026-03-01"
    assert dumped["max_date"] == "2026-03-31"
    assert dumped["min_amount"] == pytest.approx(10.5)
    assert dumped["max_amount"] == pytest.approx(99.99)
    assert dumped["limit"] == 200
    assert dumped["offset"] == 5


@pytest.mark.parametrize(
    ("payload", "message_fragment"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 201}, "limit"),
        ({"offset": -1}, "offset"),
        ({"min_date": "2026-03-16", "max_date": "2026-03-15"}, "min_date must be less than or equal to max_date"),
        ({"min_amount": 200, "max_amount": 100}, "min_amount must be less than or equal to max_amount"),
    ],
)
def test_transaction_list_params_rejects_invalid_bounds(payload: dict[str, object], message_fragment: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        TransactionListParams.model_validate(payload)

    assert message_fragment in str(exc_info.value)


def test_parcel_summary_response_serializes_optional_fields_and_round_trips() -> None:
    parcel_id = uuid4()
    jurisdiction_id = uuid4()
    response = ParcelSummaryResponse.model_validate(
        {
            "id": parcel_id,
            "reid": "100000001",
            "pin": "0123456789",
            "site_address": "123 MAIN ST",
            "property_description": "Residential lot",
            "city": "Durham",
            "zoning_class": "R-20",
            "land_class": "Residential",
            "acreage": Decimal("1.2500"),
            "neighborhood": "Northside",
            "fire_district": "Durham",
            "is_pending": False,
            "deed_date": date(2020, 1, 1),
            "deed_book": "1234",
            "deed_page": "567",
            "jurisdiction_id": jurisdiction_id,
            "sources": [_source_info_payload()],
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(parcel_id)
    assert dumped["jurisdiction_id"] == str(jurisdiction_id)
    assert dumped["deed_date"] == "2020-01-01"
    assert dumped["acreage"] == "1.2500"
    assert "source_record_id" not in dumped
    assert "created_at" not in dumped
    assert "updated_at" not in dumped
    assert ParcelSummaryResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_property_assessment_response_serializes_decimal_fields_and_round_trips() -> None:
    assessment_id = uuid4()
    response = PropertyAssessmentResponse.model_validate(
        {
            "id": assessment_id,
            "tax_year": 2025,
            "land_assessed_value": Decimal("100000.00"),
            "improvement_assessed_value": Decimal("250000.00"),
            "total_assessed_value": Decimal("350000.00"),
            "assessed_at": date(2025, 1, 31),
            "heated_area": 2400,
            "exemption_description": "Homestead",
            "sources": [_source_info_payload()],
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(assessment_id)
    assert dumped["assessed_at"] == "2025-01-31"
    assert dumped["land_assessed_value"] == "100000.00"
    assert dumped["improvement_assessed_value"] == "250000.00"
    assert dumped["total_assessed_value"] == "350000.00"
    assert dumped["heated_area"] == 2400
    assert dumped["exemption_description"] == "Homestead"
    assert "source_record_id" not in dumped
    assert "created_at" not in dumped
    assert "updated_at" not in dumped
    assert PropertyAssessmentResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_property_ownership_response_serializes_timeline_and_links_and_round_trips() -> None:
    ownership_id = uuid4()
    person_id = uuid4()
    organization_id = uuid4()
    address_id = uuid4()
    response = PropertyOwnershipResponse.model_validate(
        {
            "id": ownership_id,
            "owner_name": "Jane Owner",
            "owner_mail_line1": "123 MAIN ST",
            "owner_mail_line2": None,
            "owner_mail_line3": "SUITE 10",
            "owner_mail_city": "Durham",
            "owner_mail_state": "NC",
            "owner_mail_zip5": "27701",
            "ownership_recorded_at": date(2024, 5, 1),
            "valid_period": "[2024-05-01,2025-05-01)",
            "date_precision": "day",
            "owner_person_id": person_id,
            "owner_organization_id": organization_id,
            "owner_address_id": address_id,
            "sources": [_source_info_payload()],
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(ownership_id)
    assert dumped["ownership_recorded_at"] == "2024-05-01"
    assert dumped["valid_period"] == "[2024-05-01,2025-05-01)"
    assert dumped["date_precision"] == "day"
    assert dumped["owner_mail_line3"] == "SUITE 10"
    assert dumped["owner_person_id"] == str(person_id)
    assert dumped["owner_organization_id"] == str(organization_id)
    assert dumped["owner_address_id"] == str(address_id)
    assert "source_record_id" not in dumped
    assert "created_at" not in dumped
    assert "updated_at" not in dumped
    assert PropertyOwnershipResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_parcel_detail_response_defaults_nested_lists_and_round_trips() -> None:
    parcel_id = uuid4()
    response = ParcelDetailResponse.model_validate(
        {
            "id": parcel_id,
            "reid": "100000001",
            "pin": "0123456789",
            "site_address": "123 MAIN ST",
            "is_pending": False,
            "sources": [_source_info_payload()],
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(parcel_id)
    assert dumped["assessments"] == []
    assert dumped["ownership"] == []
    assert "source_record_id" not in dumped
    assert ParcelDetailResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_parcel_list_params_defaults() -> None:
    params = ParcelListParams.model_validate({})
    dumped = params.model_dump(mode="json")

    assert dumped["city"] is None
    assert dumped["zoning_class"] is None
    assert dumped["min_acreage"] is None
    assert dumped["max_acreage"] is None
    assert dumped["limit"] == 50
    assert dumped["offset"] == 0


def test_parcel_list_params_accepts_inclusive_bounds() -> None:
    params = ParcelListParams.model_validate(
        {
            "city": "Durham",
            "zoning_class": "R-20",
            "min_acreage": "1.0",
            "max_acreage": "2.5",
            "limit": 200,
            "offset": 10,
        }
    )
    dumped = params.model_dump(mode="json")

    assert dumped["city"] == "Durham"
    assert dumped["zoning_class"] == "R-20"
    assert dumped["min_acreage"] == "1.0"
    assert dumped["max_acreage"] == "2.5"
    assert dumped["limit"] == 200
    assert dumped["offset"] == 10


@pytest.mark.parametrize(
    ("payload", "message_fragment"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 201}, "limit"),
        ({"offset": -1}, "offset"),
        ({"min_acreage": "3.0", "max_acreage": "2.0"}, "min_acreage must be less than or equal to max_acreage"),
    ],
)
def test_parcel_list_params_rejects_invalid_bounds(payload: dict[str, object], message_fragment: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ParcelListParams.model_validate(payload)

    assert message_fragment in str(exc_info.value)


def test_er_cluster_list_params_defaults_and_round_trips() -> None:
    params = ERClusterListParams.model_validate({})
    dumped = params.model_dump(mode="json")

    assert dumped["entity_type"] is None
    assert dumped["limit"] == 50
    assert dumped["offset"] == 0
    assert ERClusterListParams.model_validate(dumped).model_dump(mode="json") == dumped


@pytest.mark.parametrize(
    ("payload", "message_fragment"),
    [
        ({"entity_type": "org"}, "entity_type"),
        ({"limit": 0}, "limit"),
        ({"limit": 201}, "limit"),
        ({"offset": -1}, "offset"),
    ],
)
def test_er_cluster_list_params_rejects_invalid_values(payload: dict[str, object], message_fragment: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ERClusterListParams.model_validate(payload)

    assert message_fragment in str(exc_info.value)


def test_cluster_member_response_serializes_uuid_and_allows_null_name() -> None:
    entity_id = UUID("00000000-0000-0000-0000-000000000901")
    response = ClusterMemberResponse.model_validate(
        {
            "entity_type": "person",
            "entity_id": entity_id,
            "is_canonical": True,
            "canonical_name": None,
            "split_at": "2026-03-18T12:00:00Z",
        }
    )
    dumped = response.model_dump(mode="json")

    assert dumped["entity_id"] == str(entity_id)
    assert dumped["canonical_name"] is None
    assert "split_at" not in dumped
    assert ClusterMemberResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_er_cluster_summary_response_round_trips_and_drops_mutation_fields() -> None:
    cluster_id = UUID("00000000-0000-0000-0000-000000000902")
    canonical_entity_id = UUID("00000000-0000-0000-0000-000000000903")
    response = ERClusterSummaryResponse.model_validate(
        {
            "id": cluster_id,
            "entity_type": "organization",
            "canonical_entity_id": canonical_entity_id,
            "canonical_name": "Civibus Action LLC",
            "cluster_confidence": 0.875,
            "member_count": 2,
            "created_at": "2026-03-18T12:00:00Z",
            "updated_at": "2026-03-18T12:00:00Z",
        }
    )
    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(cluster_id)
    assert dumped["canonical_entity_id"] == str(canonical_entity_id)
    assert dumped["cluster_confidence"] == pytest.approx(0.875)
    assert "created_at" not in dumped
    assert "updated_at" not in dumped
    assert ERClusterSummaryResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_er_cluster_detail_response_round_trips_with_members() -> None:
    cluster_id = UUID("00000000-0000-0000-0000-000000000904")
    canonical_entity_id = UUID("00000000-0000-0000-0000-000000000905")
    noncanonical_entity_id = UUID("00000000-0000-0000-0000-000000000906")
    response = ERClusterDetailResponse.model_validate(
        {
            "id": cluster_id,
            "entity_type": "person",
            "canonical_entity_id": canonical_entity_id,
            "canonical_name": "Jane Doe",
            "cluster_confidence": 0.95,
            "member_count": 2,
            "members": [
                {
                    "entity_type": "person",
                    "entity_id": canonical_entity_id,
                    "is_canonical": True,
                    "canonical_name": "Jane Doe",
                },
                {
                    "entity_type": "person",
                    "entity_id": noncanonical_entity_id,
                    "is_canonical": False,
                    "canonical_name": "J. Doe",
                    "split_at": None,
                },
            ],
        }
    )
    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(cluster_id)
    assert dumped["members"][0]["entity_id"] == str(canonical_entity_id)
    assert dumped["members"][1]["entity_id"] == str(noncanonical_entity_id)
    assert dumped["members"][0]["is_canonical"] is True
    assert dumped["members"][1]["is_canonical"] is False
    assert "split_at" not in dumped["members"][1]
    assert ERClusterDetailResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_match_decision_response_round_trips_and_drops_mutation_fields() -> None:
    decision_id = UUID("00000000-0000-0000-0000-000000000907")
    entity_id_a = UUID("00000000-0000-0000-0000-000000000908")
    entity_id_b = UUID("00000000-0000-0000-0000-000000000909")
    response = MatchDecisionResponse.model_validate(
        {
            "id": decision_id,
            "entity_type": "person",
            "entity_id_a": entity_id_a,
            "entity_id_b": entity_id_b,
            "decision": "probable_match",
            "confidence": 0.82,
            "decided_by": "splink_v1",
            "decision_method": "probabilistic",
            "match_evidence": {"name_similarity": 0.9},
            "decided_at": "2026-03-18T12:00:00Z",
            "superseded_by": str(uuid4()),
            "superseded_at": "2026-03-18T13:00:00Z",
            "created_at": "2026-03-18T11:00:00Z",
        }
    )
    dumped = response.model_dump(mode="json")

    assert dumped["id"] == str(decision_id)
    assert dumped["entity_id_a"] == str(entity_id_a)
    assert dumped["entity_id_b"] == str(entity_id_b)
    assert dumped["confidence"] == pytest.approx(0.82)
    assert dumped["match_evidence"] == {"name_similarity": 0.9}
    assert "superseded_by" not in dumped
    assert "superseded_at" not in dumped
    assert "created_at" not in dumped
    assert MatchDecisionResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_er_summary_response_round_trips_with_decision_counts() -> None:
    response = ERSummaryResponse.model_validate(
        {
            "total_active_clusters": 3,
            "total_active_members": 8,
            "total_active_matches": 5,
            "decision_counts": {
                "match": 2,
                "probable_match": 1,
                "possible_match": 1,
                "no_match": 1,
            },
            "updated_at": "2026-03-18T11:00:00Z",
        }
    )
    dumped = response.model_dump(mode="json")

    assert dumped["total_active_clusters"] == 3
    assert dumped["total_active_members"] == 8
    assert dumped["total_active_matches"] == 5
    assert dumped["decision_counts"]["match"] == 2
    assert dumped["decision_counts"]["no_match"] == 1
    assert "updated_at" not in dumped
    assert ERSummaryResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_search_params_requires_q_with_minimum_length() -> None:
    with pytest.raises(ValidationError):
        SearchParams.model_validate({})

    with pytest.raises(ValidationError):
        SearchParams.model_validate({"q": "a"})


def test_search_params_defaults_and_optional_entity_type() -> None:
    params = SearchParams.model_validate({"q": "civ"})
    dumped = params.model_dump(mode="json")

    assert dumped["q"] == "civ"
    assert dumped["entity_type"] is None
    assert dumped["limit"] == 20
    assert dumped["offset"] == 0


@pytest.mark.parametrize(
    ("payload", "message_fragment"),
    [
        ({"q": "civ", "entity_type": "organization"}, "entity_type"),
        ({"q": "civ", "limit": 0}, "limit"),
        ({"q": "civ", "limit": 101}, "limit"),
        ({"q": "civ", "offset": -1}, "offset"),
        ({"q": "x" * 101}, "at most 100"),
    ],
)
def test_search_params_rejects_invalid_entity_type_and_bounds(
    payload: dict[str, object],
    message_fragment: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        SearchParams.model_validate(payload)

    assert message_fragment in str(exc_info.value)


def test_search_result_serializes_and_round_trips() -> None:
    result_id = UUID("00000000-0000-0000-0000-000000000123")
    result = SearchResult.model_validate(
        {
            "entity_type": "committee",
            "entity_id": result_id,
            "name": "Civibus Committee",
        }
    )

    dumped = result.model_dump(mode="json")
    assert dumped == {
        "entity_type": "committee",
        "entity_id": str(result_id),
        "name": "Civibus Committee",
        "state": None,
        "party": None,
        "office_name": None,
        "committee_type": None,
        "total_raised": None,
    }
    assert SearchResult.model_validate(dumped).model_dump(mode="json") == dumped


def test_search_result_minimal_payload_defaults_optional_fields_to_null() -> None:
    result_id = UUID("00000000-0000-0000-0000-000000000124")
    result = SearchResult.model_validate(
        {
            "entity_type": "person",
            "entity_id": result_id,
            "name": "Civibus Person",
        }
    )

    dumped = result.model_dump(mode="json")
    assert dumped == {
        "entity_type": "person",
        "entity_id": str(result_id),
        "name": "Civibus Person",
        "state": None,
        "party": None,
        "office_name": None,
        "committee_type": None,
        "total_raised": None,
    }
    assert SearchResult.model_validate(dumped).model_dump(mode="json") == dumped


def test_search_result_enriched_payload_round_trips() -> None:
    result_id = UUID("00000000-0000-0000-0000-000000000125")
    result = SearchResult.model_validate(
        {
            "entity_type": "candidate",
            "entity_id": result_id,
            "name": "Civibus Candidate",
            "state": "WA",
            "party": "DEM",
            "office_name": "Governor",
            "committee_type": "PAC",
            "total_raised": Decimal("12345.67"),
        }
    )

    dumped = result.model_dump(mode="json")
    assert dumped == {
        "entity_type": "candidate",
        "entity_id": str(result_id),
        "name": "Civibus Candidate",
        "state": "WA",
        "party": "DEM",
        "office_name": "Governor",
        "committee_type": "PAC",
        "total_raised": "12345.67",
    }
    assert SearchResult.model_validate(dumped).model_dump(mode="json") == dumped


def test_person_slug_result_requires_canonical_name() -> None:
    payload = {"id": str(uuid4())}

    with pytest.raises(ValidationError):
        PersonSlugResult.model_validate(payload)


def test_person_slug_result_serializes_optional_fields_as_null_and_round_trips() -> None:
    person_id = UUID("00000000-0000-0000-0000-000000000213")
    result = PersonSlugResult.model_validate(
        {
            "id": person_id,
            "canonical_name": "Alex Donor",
        }
    )

    dumped = result.model_dump(mode="json")

    assert dumped["id"] == str(person_id)
    assert dumped["first_name"] is None
    assert dumped["last_name"] is None
    assert dumped["suffix"] is None
    assert PersonSlugResult.model_validate(dumped).model_dump(mode="json") == dumped


def test_donors_with_property_params_defaults_and_optional_jurisdiction() -> None:
    params = DonorsWithPropertyParams.model_validate({})
    dumped = params.model_dump(mode="json")

    assert dumped["jurisdiction"] is None
    assert dumped["limit"] == 50
    assert dumped["offset"] == 0


@pytest.mark.parametrize(
    ("payload", "message_fragment"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 201}, "limit"),
        ({"offset": -1}, "offset"),
    ],
)
def test_donors_with_property_params_rejects_out_of_bounds_values(
    payload: dict[str, object],
    message_fragment: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        DonorsWithPropertyParams.model_validate(payload)

    assert message_fragment in str(exc_info.value)


def test_donors_with_property_result_requires_literal_match_type() -> None:
    payload = {
        "person_id": str(UUID("00000000-0000-0000-0000-000000000214")),
        "canonical_name": "Taylor Cluster",
        "match_type": "alias",
    }

    with pytest.raises(ValidationError):
        DonorsWithPropertyResult.model_validate(payload)


def test_donors_with_property_result_serializes_and_round_trips() -> None:
    person_id = UUID("00000000-0000-0000-0000-000000000215")
    result = DonorsWithPropertyResult.model_validate(
        {
            "person_id": person_id,
            "canonical_name": "Taylor Cluster",
            "match_type": "cluster",
        }
    )
    dumped = result.model_dump(mode="json")

    assert dumped["person_id"] == str(person_id)
    assert dumped["canonical_name"] == "Taylor Cluster"
    assert dumped["match_type"] == "cluster"
    assert DonorsWithPropertyResult.model_validate(dumped).model_dump(mode="json") == dumped


def test_committee_fundraising_summary_serializes_decimal_fields_and_round_trips() -> None:
    committee_id = uuid4()
    response = CommitteeFundraisingSummary.model_validate(
        {
            "committee_id": committee_id,
            "committee_name": "Civibus Victory Fund",
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "total_raised": Decimal("150000.50"),
            "total_spent": Decimal("75000.25"),
            "net": Decimal("75000.25"),
            "transaction_count": 42,
            "jurisdiction": "federal/fec",
            "data_through": datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc),
            "cash_receipts_total": Decimal("120000.00"),
            "in_kind_receipts_total": Decimal("20000.50"),
            "loan_receipts_total": Decimal("10000.00"),
            "contribution_receipts_total": Decimal("150000.50"),
            "top_donors": [{"name": "Donor One", "total_amount": Decimal("10000.00"), "transaction_count": 4}],
            "top_vendors": [{"name": "Vendor One", "total_amount": Decimal("5000.00"), "transaction_count": 2}],
            "spend_categories": [{"category": "media", "total_amount": Decimal("7000.00"), "transaction_count": 2}],
            "receipt_source_composition": [
                {
                    "label": "Individual contributions",
                    "total_amount": Decimal("100000.00"),
                    "source": "fec_committee_summary",
                }
            ],
            "selected_cycle_coverage_complete": True,
            "can_render_share": True,
            "receipt_source_caveats": [],
            "debts_owed_by_committee": Decimal("2500.00"),
        }
    )

    dumped = response.model_dump(mode="json")

    # Decimal fields serialize as strings (not floats) to preserve precision
    assert dumped["committee_id"] == str(committee_id)
    assert dumped["committee_name"] == "Civibus Victory Fund"
    assert dumped["selected_cycle"] == 2026
    assert dumped["coverage_start_date"] == "2025-01-01"
    assert dumped["coverage_end_date"] == "2026-12-31"
    assert dumped["available_cycles"] == [2022, 2024, 2026]
    assert dumped["total_raised"] == "150000.50"
    assert dumped["total_spent"] == "75000.25"
    assert dumped["net"] == "75000.25"
    assert dumped["transaction_count"] == 42
    assert dumped["jurisdiction"] == "federal/fec"
    assert dumped["data_through"] == "2026-03-15T12:00:00Z"
    assert dumped["cash_receipts_total"] == "120000.00"
    assert dumped["in_kind_receipts_total"] == "20000.50"
    assert dumped["loan_receipts_total"] == "10000.00"
    assert dumped["contribution_receipts_total"] == "150000.50"
    assert dumped["top_donors"][0]["name"] == "Donor One"
    assert dumped["top_vendors"][0]["name"] == "Vendor One"
    assert dumped["spend_categories"][0]["category"] == "media"
    assert dumped["receipt_source_composition"][0]["source"] == "fec_committee_summary"
    assert dumped["selected_cycle_coverage_complete"] is True
    assert dumped["can_render_share"] is True
    assert dumped["debts_owed_by_committee"] == "2500.00"
    assert CommitteeFundraisingSummary.model_validate(dumped).model_dump(mode="json") == dumped


def test_receipt_source_component_round_trips_and_rejects_invalid_receipt_source_values() -> None:
    component = ReceiptSourceComponent.model_validate(
        {
            "label": "Individual contributions",
            "total_amount": Decimal("125.50"),
            "source": "fec_committee_summary",
        }
    )

    assert component.model_dump(mode="json") == {
        "label": "Individual contributions",
        "total_amount": "125.50",
        "source": "fec_committee_summary",
    }

    with pytest.raises(ValidationError):
        ReceiptSourceComponent.model_validate(
            {"label": "Bad", "total_amount": Decimal("1.001"), "source": "fec_committee_summary"}
        )
    with pytest.raises(ValidationError):
        ReceiptSourceComponent.model_validate({"label": "Bad", "total_amount": Decimal("1.00"), "source": "derived"})


def test_committee_fundraising_summary_allows_null_jurisdiction_and_data_through() -> None:
    response = CommitteeFundraisingSummary.model_validate(
        {
            "committee_id": uuid4(),
            "committee_name": "Zero Committee",
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "total_raised": Decimal("0.00"),
            "total_spent": Decimal("0.00"),
            "net": Decimal("0.00"),
            "transaction_count": 0,
            "jurisdiction": None,
            "data_through": None,
            "cash_receipts_total": Decimal("0.00"),
            "in_kind_receipts_total": Decimal("0.00"),
            "loan_receipts_total": Decimal("0.00"),
            "contribution_receipts_total": Decimal("0.00"),
            "top_donors": [],
            "top_vendors": [],
            "spend_categories": None,
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["total_raised"] == "0.00"
    assert dumped["total_spent"] == "0.00"
    assert dumped["net"] == "0.00"
    assert dumped["transaction_count"] == 0
    assert dumped["jurisdiction"] is None
    assert dumped["data_through"] is None
    assert dumped["spend_categories"] is None
    assert CommitteeFundraisingSummary.model_validate(dumped).model_dump(mode="json") == dumped


def test_candidate_fundraising_summary_serializes_decimals_and_nested_committees_round_trip() -> None:
    candidate_id = uuid4()
    committee_id = uuid4()
    response = CandidateFundraisingSummary.model_validate(
        {
            "candidate_id": candidate_id,
            "candidate_name": "Candidate Summary Name",
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "total_raised": Decimal("1500.50"),
            "total_spent": Decimal("300.25"),
            "net": Decimal("1200.25"),
            "transaction_count": 4,
            "committees": [
                {
                    "committee_id": committee_id,
                    "committee_name": "Committee Summary Name",
                    "selected_cycle": 2026,
                    "coverage_start_date": date(2025, 1, 1),
                    "coverage_end_date": date(2026, 12, 31),
                    "available_cycles": [2022, 2024, 2026],
                    "total_raised": Decimal("1500.50"),
                    "total_spent": Decimal("300.25"),
                    "net": Decimal("1200.25"),
                    "transaction_count": 4,
                    "jurisdiction": "state/nc",
                    "data_through": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                }
            ],
            "summary_source": "derived",
            "receipt_source_composition": [
                {
                    "label": "Other receipts",
                    "total_amount": Decimal("25.00"),
                    "source": "fec_committee_summary",
                }
            ],
            "selected_cycle_coverage_complete": True,
            "can_render_share": True,
            "receipt_source_caveats": [],
            "debts_owed_by_committee": Decimal("100.00"),
            "coverage": _candidate_money_coverage_payload(),
        }
    )

    dumped = response.model_dump(mode="json")

    assert dumped["candidate_id"] == str(candidate_id)
    assert dumped["candidate_name"] == "Candidate Summary Name"
    assert dumped["selected_cycle"] == 2026
    assert dumped["coverage_start_date"] == "2025-01-01"
    assert dumped["coverage_end_date"] == "2026-12-31"
    assert dumped["available_cycles"] == [2022, 2024, 2026]
    assert dumped["total_raised"] == "1500.50"
    assert dumped["total_spent"] == "300.25"
    assert dumped["net"] == "1200.25"
    assert dumped["transaction_count"] == 4
    assert len(dumped["committees"]) == 1
    assert dumped["committees"][0]["committee_id"] == str(committee_id)
    assert dumped["committees"][0]["total_raised"] == "1500.50"
    assert dumped["committees"][0]["total_spent"] == "300.25"
    assert dumped["committees"][0]["net"] == "1200.25"
    assert dumped["committees"][0]["transaction_count"] == 4
    assert dumped["committees"][0]["jurisdiction"] == "state/nc"
    assert dumped["committees"][0]["data_through"] == "2026-03-20T12:00:00Z"
    assert dumped["cash_on_hand"] is None
    assert dumped["summary_source"] == "derived"
    assert dumped["receipt_source_composition"][0]["label"] == "Other receipts"
    assert dumped["selected_cycle_coverage_complete"] is True
    assert dumped["can_render_share"] is True
    assert dumped["debts_owed_by_committee"] == "100.00"
    assert dumped["coverage"] == {
        "activity_state": "populated",
        "completeness": "complete",
        "basis": "fec_official_candidate_summary",
    }
    assert CandidateFundraisingSummary.model_validate(dumped).model_dump(mode="json") == dumped


def test_candidate_fundraising_summary_requires_closed_coverage_contract() -> None:
    payload = {
        "candidate_id": str(uuid4()),
        "candidate_name": "Coverage Candidate",
        "selected_cycle": 2026,
        "coverage_start_date": date(2025, 1, 1),
        "coverage_end_date": date(2026, 12, 31),
        "available_cycles": [2022, 2024, 2026],
        "total_raised": Decimal("0.00"),
        "total_spent": Decimal("0.00"),
        "net": Decimal("0.00"),
        "transaction_count": 0,
        "committees": [],
        "summary_source": "derived",
    }

    with pytest.raises(ValidationError):
        CandidateFundraisingSummary.model_validate(payload)

    for field_name in ("activity_state", "completeness", "basis"):
        invalid_payload = {
            **payload,
            "coverage": {
                **_candidate_money_coverage_payload(
                    activity_state="not_loaded",
                    completeness="unknown",
                    basis="no_authoritative_load_evidence",
                ),
                field_name: "unexpected_value",
            },
        }
        with pytest.raises(ValidationError):
            CandidateFundraisingSummary.model_validate(invalid_payload)


def test_candidate_fundraising_summary_serializes_cash_on_hand_and_summary_source_literal() -> None:
    """Stage 3 contract: cash_on_hand is money-or-null and summary_source is 'fec_weball' / 'derived'."""
    candidate_id = uuid4()
    weball_summary = CandidateFundraisingSummary.model_validate(
        {
            "candidate_id": candidate_id,
            "candidate_name": "Weball Candidate",
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "total_raised": Decimal("9000.00"),
            "total_spent": Decimal("3500.00"),
            "net": Decimal("5500.00"),
            "transaction_count": 0,
            "committees": [],
            "cash_on_hand": Decimal("5500.00"),
            "summary_source": "fec_weball",
            "coverage": _candidate_money_coverage_payload(),
        }
    )

    dumped = weball_summary.model_dump(mode="json")

    assert dumped["cash_on_hand"] == "5500.00"
    assert dumped["summary_source"] == "fec_weball"
    # Round-trip preserves the literal and the money field.
    assert CandidateFundraisingSummary.model_validate(dumped).model_dump(mode="json") == dumped

    derived_summary = CandidateFundraisingSummary.model_validate(
        {
            "candidate_id": candidate_id,
            "candidate_name": "Derived Candidate",
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "total_raised": Decimal("0.00"),
            "total_spent": Decimal("0.00"),
            "net": Decimal("0.00"),
            "transaction_count": 0,
            "committees": [],
            "cash_on_hand": None,
            "summary_source": "derived",
            "coverage": _candidate_money_coverage_payload(
                activity_state="not_loaded",
                completeness="unknown",
                basis="no_authoritative_load_evidence",
            ),
        }
    )
    derived_dumped = derived_summary.model_dump(mode="json")
    assert derived_dumped["cash_on_hand"] is None
    assert derived_dumped["summary_source"] == "derived"

    # Invalid summary_source literal is rejected.
    with pytest.raises(ValidationError):
        CandidateFundraisingSummary.model_validate(
            {
                "candidate_id": candidate_id,
                "candidate_name": "Invalid",
                "total_raised": Decimal("0.00"),
                "total_spent": Decimal("0.00"),
                "net": Decimal("0.00"),
                "transaction_count": 0,
                "committees": [],
                "cash_on_hand": None,
                "summary_source": "not_a_valid_source",
            }
        )


def test_state_summary_item_serializes_decimal_date_and_nullable_ie_fields() -> None:
    summary_item = StateSummaryItem.model_validate(
        {
            "state_code": "NC",
            "total_raised": Decimal("275.00"),
            "total_spent": Decimal("90.00"),
            "net": Decimal("185.00"),
            "committee_count": 1,
            "transaction_count": 4,
            "federal_candidate_count": 2,
            "ie_support_total": Decimal("40.00"),
            "ie_oppose_total": Decimal("0.00"),
            "ie_support_count": 1,
            "ie_oppose_count": 0,
            "coverage_tier": "launch-support candidate",
            "support_status": "supported",
            "supported": True,
            "warning_text": None,
            "data_through": datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc),
        }
    )

    dumped = summary_item.model_dump(mode="json")

    assert dumped["state_code"] == "NC"
    assert dumped["total_raised"] == "275.00"
    assert dumped["total_spent"] == "90.00"
    assert dumped["net"] == "185.00"
    assert dumped["committee_count"] == 1
    assert dumped["transaction_count"] == 4
    assert dumped["federal_candidate_count"] == 2
    assert dumped["ie_support_total"] == "40.00"
    assert dumped["ie_oppose_total"] == "0.00"
    assert dumped["ie_support_count"] == 1
    assert dumped["ie_oppose_count"] == 0
    assert dumped["coverage_tier"] == "launch-support candidate"
    assert dumped["support_status"] == "supported"
    assert dumped["supported"] is True
    assert dumped["warning_text"] is None
    assert dumped["data_through"] == "2026-03-23T12:00:00Z"
    assert StateSummaryItem.model_validate(dumped).model_dump(mode="json") == dumped


def test_state_detail_response_round_trips_with_top_lists_and_null_ie_values() -> None:
    detail = StateDetailResponse.model_validate(
        {
            "state_code": "DC",
            "total_raised": Decimal("0.00"),
            "total_spent": Decimal("0.00"),
            "net": Decimal("0.00"),
            "committee_count": 0,
            "transaction_count": 0,
            "federal_candidate_count": 0,
            "ie_support_total": None,
            "ie_oppose_total": None,
            "ie_support_count": None,
            "ie_oppose_count": None,
            "coverage_tier": "freshness-limited",
            "support_status": "warning",
            "supported": False,
            "warning_text": "Observed cadence signal is below weekly launch threshold.",
            "data_through": None,
            "top_candidates": [
                {
                    "candidate_id": UUID("d0000000-0000-0000-0000-000000000211"),
                    "candidate_name": "NC Candidate One",
                    "total_raised": Decimal("200.00"),
                }
            ],
            "top_committees": [
                {
                    "committee_id": UUID("d3333333-3333-3333-3333-333333333333"),
                    "committee_name": "NC Committee A",
                    "total_raised": Decimal("270.00"),
                }
            ],
            "top_ie_spenders": [
                {
                    "committee_id": UUID("d4444444-4444-4444-4444-444444444444"),
                    "committee_name": "NC Committee B",
                    "total_amount": Decimal("80.00"),
                }
            ],
        }
    )

    dumped = detail.model_dump(mode="json")

    assert dumped["state_code"] == "DC"
    assert dumped["ie_support_total"] is None
    assert dumped["ie_oppose_total"] is None
    assert dumped["ie_support_count"] is None
    assert dumped["ie_oppose_count"] is None
    assert dumped["support_status"] == "warning"
    assert dumped["supported"] is False
    assert dumped["data_through"] is None
    assert dumped["top_candidates"][0]["total_raised"] == "200.00"
    assert dumped["top_committees"][0]["total_raised"] == "270.00"
    assert dumped["top_ie_spenders"][0]["total_amount"] == "80.00"
    assert StateDetailResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_state_top_entry_models_round_trip_and_preserve_decimal_precision() -> None:
    candidate_entry = StateCandidateTopEntry.model_validate(
        {
            "candidate_id": UUID("d0000000-0000-0000-0000-000000000211"),
            "candidate_name": "NC Candidate One",
            "total_raised": Decimal("200.00"),
        }
    )
    committee_entry = StateCommitteeTopEntry.model_validate(
        {
            "committee_id": UUID("d3333333-3333-3333-3333-333333333333"),
            "committee_name": "NC Committee A",
            "total_raised": Decimal("270.00"),
        }
    )
    ie_entry = StateIndependentExpenditureTopSpender.model_validate(
        {
            "committee_id": UUID("d4444444-4444-4444-4444-444444444444"),
            "committee_name": "NC Committee B",
            "total_amount": Decimal("80.00"),
        }
    )

    assert candidate_entry.model_dump(mode="json")["total_raised"] == "200.00"
    assert committee_entry.model_dump(mode="json")["total_raised"] == "270.00"
    assert ie_entry.model_dump(mode="json")["total_amount"] == "80.00"


def test_filing_period_summary_serializes_decimal_and_date_fields_and_round_trips() -> None:
    filing_id = uuid4()
    summary = FilingPeriodSummary.model_validate(
        {
            "filing_id": filing_id,
            "filing_fec_id": "FILING-0001",
            "filing_name": "Q1 Filing",
            "report_type": "Q1",
            "amendment_indicator": "A",
            "coverage_start_date": date(2026, 1, 1),
            "coverage_end_date": date(2026, 3, 31),
            "receipt_date": date(2026, 4, 17),
            "total_raised": Decimal("1250.50"),
            "total_spent": Decimal("500.25"),
            "net": Decimal("750.25"),
            "transaction_count": 3,
            "cash_on_hand": Decimal("750.25"),
            "row_id": f"{filing_id}:A",
        }
    )

    dumped = summary.model_dump(mode="json")

    assert dumped["filing_id"] == str(filing_id)
    assert dumped["filing_fec_id"] == "FILING-0001"
    assert dumped["filing_name"] == "Q1 Filing"
    assert dumped["report_type"] == "Q1"
    assert dumped["amendment_indicator"] == "A"
    assert dumped["coverage_start_date"] == "2026-01-01"
    assert dumped["coverage_end_date"] == "2026-03-31"
    assert dumped["receipt_date"] == "2026-04-17"
    assert dumped["total_raised"] == "1250.50"
    assert dumped["total_spent"] == "500.25"
    assert dumped["net"] == "750.25"
    assert dumped["transaction_count"] == 3
    assert dumped["cash_on_hand"] == "750.25"
    assert dumped["row_id"] == f"{filing_id}:A"
    assert FilingPeriodSummary.model_validate(dumped).model_dump(mode="json") == dumped


def test_committee_filing_breakdown_serializes_nested_filings_shape_and_round_trips() -> None:
    committee_id = uuid4()
    filing_id = uuid4()
    breakdown = CommitteeFilingBreakdown.model_validate(
        {
            "committee_id": committee_id,
            "committee_name": "Committee Filing Breakdown",
            "total_filings": 12,
            "store_limit": FILING_BREAKDOWN_STORE_LIMIT,
            "has_next": True,
            "offset": 10,
            "limit": 1,
            "filings": [
                {
                    "filing_id": filing_id,
                    "filing_fec_id": "FILING-0002",
                    "filing_name": None,
                    "report_type": None,
                    "amendment_indicator": "N",
                    "coverage_start_date": None,
                    "coverage_end_date": None,
                    "receipt_date": None,
                    "total_raised": Decimal("0.00"),
                    "total_spent": Decimal("0.00"),
                    "net": Decimal("0.00"),
                    "transaction_count": 0,
                    "cash_on_hand": None,
                    "row_id": f"{filing_id}:N",
                }
            ],
        }
    )

    dumped = breakdown.model_dump(mode="json")

    assert dumped["committee_id"] == str(committee_id)
    assert dumped["committee_name"] == "Committee Filing Breakdown"
    assert dumped["total_filings"] == 12
    assert dumped["store_limit"] == FILING_BREAKDOWN_STORE_LIMIT
    assert dumped["has_next"] is True
    assert dumped["offset"] == 10
    assert dumped["limit"] == 1
    assert len(dumped["filings"]) == 1
    assert dumped["filings"][0]["filing_id"] == str(filing_id)
    assert dumped["filings"][0]["total_raised"] == "0.00"
    assert dumped["filings"][0]["total_spent"] == "0.00"
    assert dumped["filings"][0]["net"] == "0.00"
    assert dumped["filings"][0]["coverage_end_date"] is None
    assert dumped["filings"][0]["receipt_date"] is None
    assert dumped["filings"][0]["transaction_count"] == 0
    assert dumped["filings"][0]["row_id"] == f"{filing_id}:N"
    assert CommitteeFilingBreakdown.model_validate(dumped).model_dump(mode="json") == dumped


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("total_filings", -1),
        ("store_limit", 0),
        ("limit", 0),
        ("limit", FILING_BREAKDOWN_STORE_LIMIT + 1),
        ("offset", -1),
    ],
)
def test_committee_filing_breakdown_rejects_invalid_pagination_metadata(
    field_name: str,
    invalid_value: int,
) -> None:
    payload = {
        "committee_id": uuid4(),
        "committee_name": "Committee Filing Breakdown",
        "total_filings": 0,
        "store_limit": FILING_BREAKDOWN_STORE_LIMIT,
        "has_next": False,
        "offset": 0,
        "limit": 50,
        "filings": [],
    }
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        CommitteeFilingBreakdown.model_validate(payload)


def test_committee_cycle_summary_round_trips_supported_cycle_row() -> None:
    """Stage 5: ``CommitteeCycleSummary`` carries per-cycle official totals."""
    cycle_row = CommitteeCycleSummary.model_validate(
        {
            "cycle": 2024,
            "total_receipts": Decimal("9000.00"),
            "total_disbursements": Decimal("3500.00"),
            "cash_on_hand": Decimal("5500.00"),
            "coverage_start_date": date(2023, 1, 1),
            "coverage_end_date": date(2024, 12, 31),
        }
    )
    dumped = cycle_row.model_dump(mode="json")

    assert dumped["cycle"] == 2024
    assert dumped["total_receipts"] == "9000.00"
    assert dumped["total_disbursements"] == "3500.00"
    assert dumped["cash_on_hand"] == "5500.00"
    assert dumped["coverage_start_date"] == "2023-01-01"
    assert dumped["coverage_end_date"] == "2024-12-31"
    assert CommitteeCycleSummary.model_validate(dumped).model_dump(mode="json") == dumped


def test_committee_fundraising_summary_round_trips_stage5_official_fields() -> None:
    """Stage 5: cycle_summaries + itemized_transaction_count + summary_source round-trip."""
    committee_id = uuid4()
    summary = CommitteeFundraisingSummary.model_validate(
        {
            "committee_id": committee_id,
            "committee_name": "Official Totals Committee",
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "total_raised": Decimal("10000.00"),
            "total_spent": Decimal("4000.00"),
            "net": Decimal("6000.00"),
            "transaction_count": 2,
            "itemized_transaction_count": 2,
            "cycle_summaries": [
                {
                    "cycle": 2024,
                    "total_receipts": Decimal("9000.00"),
                    "total_disbursements": Decimal("3500.00"),
                    "cash_on_hand": Decimal("5500.00"),
                },
                {
                    "cycle": 2026,
                    "total_receipts": Decimal("1000.00"),
                    "total_disbursements": Decimal("500.00"),
                },
            ],
            "summary_source": "fec_committee_summary",
        }
    )
    dumped = summary.model_dump(mode="json")

    assert dumped["itemized_transaction_count"] == 2
    assert dumped["summary_source"] == "fec_committee_summary"
    assert len(dumped["cycle_summaries"]) == 2
    assert dumped["cycle_summaries"][0]["cycle"] == 2024
    assert dumped["cycle_summaries"][0]["total_receipts"] == "9000.00"
    assert dumped["cycle_summaries"][1]["cash_on_hand"] is None
    assert CommitteeFundraisingSummary.model_validate(dumped).model_dump(mode="json") == dumped


def test_committee_fundraising_summary_rejects_invalid_summary_source_literal() -> None:
    with pytest.raises(ValidationError):
        CommitteeFundraisingSummary.model_validate(
            {
                "committee_id": uuid4(),
                "committee_name": "Invalid Source Committee",
                "total_raised": Decimal("0.00"),
                "total_spent": Decimal("0.00"),
                "net": Decimal("0.00"),
                "transaction_count": 0,
                "summary_source": "not_a_valid_source",
            }
        )


def test_committee_response_round_trips_linked_candidates_reusing_candidate_list_item_shape() -> None:
    """Stage 5: ``linked_candidates`` reuses ``CandidateListItem`` and carries person_id."""
    committee_id = uuid4()
    candidate_id = uuid4()
    person_id = uuid4()
    response = CommitteeResponse.model_validate(
        {
            "id": committee_id,
            "fec_committee_id": "C12345678",
            "name": "Linked Candidates Committee",
            "slug": "linked-candidates-committee",
            "slug_is_unique": True,
            "sources": [_source_info_payload()],
            "linked_candidates": [
                {
                    "id": candidate_id,
                    "fec_candidate_id": "H0NC01001",
                    "name": "Alpha Candidate",
                    "person_id": person_id,
                    "party": "DEM",
                    "office": "H",
                    "state": "NC",
                    "district": "01",
                    "slug": "alpha-candidate",
                    "slug_is_unique": True,
                    "identity_is_safe": True,
                }
            ],
        }
    )
    dumped = response.model_dump(mode="json")

    assert isinstance(response.linked_candidates[0], CandidateListItem)
    linked = dumped["linked_candidates"][0]
    assert linked["id"] == str(candidate_id)
    assert linked["person_id"] == str(person_id)
    assert linked["office"] == "H"
    assert linked["slug"] == "alpha-candidate"
    assert linked["slug_is_unique"] is True
    assert linked["identity_is_safe"] is True
    assert CommitteeResponse.model_validate(dumped).model_dump(mode="json") == dumped


def test_candidate_list_item_requires_and_round_trips_identity_is_safe() -> None:
    base_payload = {
        "id": uuid4(),
        "fec_candidate_id": "H0NC01001",
        "name": "Jane Doe",
        "office": "H",
        "state": "NC",
        "district": "01",
        "slug": "jane-doe",
        "slug_is_unique": True,
    }

    with pytest.raises(ValidationError):
        CandidateListItem.model_validate(base_payload)

    true_item = CandidateListItem.model_validate({**base_payload, "identity_is_safe": True})
    false_item = CandidateListItem.model_validate(
        {
            **base_payload,
            "id": uuid4(),
            "name": "212 N HALF  W. JOHN, RODNEY HOWARD MR.",
            "slug": "212-n-half-w-john-rodney-howard-mr",
            "identity_is_safe": False,
        }
    )

    assert true_item.model_dump(mode="json")["identity_is_safe"] is True
    assert false_item.model_dump(mode="json")["identity_is_safe"] is False
    assert (
        CandidateListItem.model_validate(false_item.model_dump(mode="json")).model_dump(mode="json")["identity_is_safe"]
        is False
    )


def test_committee_independent_expenditure_target_requires_and_round_trips_identity_is_safe() -> None:
    base_payload = {
        "candidate_id": uuid4(),
        "fec_candidate_id": "H0NC01001",
        "candidate_name": "Jane Doe",
        "party": "DEM",
        "office": "H",
        "state": "NC",
        "district": "01",
        "slug": "jane-doe",
        "slug_is_unique": True,
        "support_total": Decimal("10.00"),
        "oppose_total": Decimal("0.00"),
        "transaction_count": 1,
        "sources": [_source_info_payload()],
    }

    with pytest.raises(ValidationError):
        CommitteeIndependentExpenditureTarget.model_validate(base_payload)

    true_target = CommitteeIndependentExpenditureTarget.model_validate({**base_payload, "identity_is_safe": True})
    false_target = CommitteeIndependentExpenditureTarget.model_validate(
        {
            **base_payload,
            "candidate_id": uuid4(),
            "candidate_name": "375 ROB ROY DR, DAVID J SR SR",
            "slug": "375-rob-roy-dr-david-j-sr-sr",
            "identity_is_safe": False,
        }
    )

    assert true_target.model_dump(mode="json")["identity_is_safe"] is True
    assert false_target.model_dump(mode="json")["identity_is_safe"] is False
    assert (
        CommitteeIndependentExpenditureTarget.model_validate(false_target.model_dump(mode="json")).model_dump(
            mode="json"
        )["identity_is_safe"]
        is False
    )


def test_committee_response_linked_candidates_defaults_to_empty_list() -> None:
    response = CommitteeResponse.model_validate(
        {
            "id": uuid4(),
            "fec_committee_id": "C12345678",
            "name": "Empty Committee",
            "slug": "empty-committee",
            "slug_is_unique": True,
            "sources": [_source_info_payload()],
        }
    )
    assert response.linked_candidates == []
    dumped = response.model_dump(mode="json")
    assert dumped["linked_candidates"] == []


def test_candidate_fundraising_summary_round_trips_itemized_transaction_count() -> None:
    """Stage 5: ``itemized_transaction_count`` mirrors the derived transaction count."""
    summary = CandidateFundraisingSummary.model_validate(
        {
            "candidate_id": uuid4(),
            "candidate_name": "Weball Candidate",
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "total_raised": Decimal("9000.00"),
            "total_spent": Decimal("3500.00"),
            "net": Decimal("5500.00"),
            "transaction_count": 4,
            "itemized_transaction_count": 4,
            "committees": [],
            "cash_on_hand": Decimal("5500.00"),
            "summary_source": "fec_weball",
            "coverage": _candidate_money_coverage_payload(),
        }
    )
    dumped = summary.model_dump(mode="json")
    assert dumped["itemized_transaction_count"] == 4
    assert CandidateFundraisingSummary.model_validate(dumped).model_dump(mode="json") == dumped


def test_independent_expenditure_summary_round_trips_excluded_outlier_count() -> None:
    """Stage 5: ``excluded_outlier_count`` reports rows filtered from the aggregate."""
    summary = IndependentExpenditureSummary.model_validate(
        {
            "candidate_id": str(uuid4()),
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "support_total": Decimal("250.00"),
            "oppose_total": Decimal("0.00"),
            "support_count": 1,
            "oppose_count": 0,
            "top_spenders": [],
            "excluded_outlier_count": 3,
            "coverage": _candidate_money_coverage_payload(
                activity_state="populated",
                completeness="partial",
                basis="fec_schedule_e_transactions",
            ),
        }
    )
    dumped = summary.model_dump(mode="json")
    assert dumped["excluded_outlier_count"] == 3
    assert IndependentExpenditureSummary.model_validate(dumped).model_dump(mode="json") == dumped

    # Default is 0 when omitted.
    without_count = IndependentExpenditureSummary.model_validate(
        {
            "candidate_id": str(uuid4()),
            "selected_cycle": 2026,
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "support_total": Decimal("0.00"),
            "oppose_total": Decimal("0.00"),
            "support_count": 0,
            "oppose_count": 0,
            "top_spenders": [],
            "coverage": _candidate_money_coverage_payload(
                activity_state="not_loaded",
                completeness="unknown",
                basis="no_authoritative_load_evidence",
            ),
        }
    )
    assert without_count.excluded_outlier_count == 0


def test_models_package_reexports_public_response_and_params_models() -> None:
    expected_exports = {
        "SourceInfo",
        "PersonResponse",
        "PersonContributionInsights",
        "OrgResponse",
        "CommitteeFilingBreakdown",
        "CommitteeFundraisingSummary",
        "ContributionInsightsDistrictShare",
        "ContributionInsightsDollarsBucket",
        "ContributionInsightsGeography",
        "ContributionInsightsGeographyRow",
        "ContributionInsightsItemizedBucket",
        "ContributionInsightsMetadata",
        "ContributionInsightsMonthlyTotal",
        "ContributionInsightsSmallDollarShare",
        "CandidateFundraisingSummary",
        "CommitteeResponse",
        "CandidateResponse",
        "FilingResponse",
        "FilingPeriodSummary",
        "IndependentExpenditureResponse",
        "IndependentExpenditureSummary",
        "TopSpenderEntry",
        "TransactionResponse",
        "TransactionListParams",
        "PersonSlugResult",
        "ParcelSummaryResponse",
        "PropertyAssessmentResponse",
        "PropertyOwnershipResponse",
        "ParcelDetailResponse",
        "ParcelListParams",
        "DonorsWithPropertyParams",
        "DonorsWithPropertyResult",
        "ERClusterListParams",
        "ClusterMemberResponse",
        "ERClusterSummaryResponse",
        "ERClusterDetailResponse",
        "MatchDecisionResponse",
        "ERDecisionCounts",
        "ERSummaryResponse",
        "SearchParams",
        "SearchResult",
        "StateCandidateTopEntry",
        "StateCommitteeTopEntry",
        "StateDetailResponse",
        "StateIndependentExpenditureTopSpender",
        "StateSummaryItem",
        "GraphNeighbor",
        "EntityRelationshipsResponse",
    }

    assert expected_exports.issubset(set(api_models.__all__))
    for export_name in expected_exports:
        assert getattr(api_models, export_name).__name__ == export_name
