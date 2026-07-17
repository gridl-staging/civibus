from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

import api.queries as campaign_finance_queries
import api.queries.campaign_finance as campaign_finance_query_module
from api.queries import (
    fetch_candidate_public_money_summaries,
    fetch_candidate_summary,
    fetch_committee_fundraising_summary,
)
from api.queries.campaign_finance import (
    CANDIDATE_IE_OUTLIER_CEILING,
    COMMITTEE_FUNDRAISING_SUMMARY_SQL,
    DISBURSEMENT_TYPE_PREFIX,
    _COUNTY_PROXY_QUALIFYING_TRANSACTIONS_CTE,
    fetch_candidate_ie_summaries,
)
from api.test_campaign_finance_support import (
    CandidateCommitteeLinkSeed,
    CandidateRowSeed,
    CommitteeSummaryRowSeed,
    CountySummaryFixtureContext,
    CommitteeRowSeed,
    FilingRowSeed,
    SummaryTestContext,
    TransactionRowSeed,
    insert_candidate_committee_link_row,
    insert_candidate_row,
    insert_committee_row,
    insert_committee_summary_row,
    insert_data_source_for_test,
    insert_electoral_division_row,
    insert_filing_breakdown_transaction,
    insert_filing_row,
    insert_office_row,
    insert_officeholding_row,
    insert_source_record_for_test,
    insert_summary_transaction,
    insert_transaction_row,
    insert_zcta_district_row,
    seed_county_summary_recipient,
    seed_county_summary_fixture,
    seed_committee_for_filing_breakdown,
    seed_committee_for_summary,
    seed_transactions_for_filters,
)
from core.db import insert_entity_source, insert_organization, insert_person
from core.types.python.models import Organization, Person
from domains.civics.constants import LAUNCH_SCOPE_USPS_STATES
from domains.campaign_finance.ingest.filing_loader import upsert_filing
from domains.campaign_finance.types.models import Filing

pytestmark = pytest.mark.integration

PrincipalCommitteeFallbackShape = Literal["selected_cycle_fallback", "production_missing_self_funding_columns"]


def _stage3_uuid(index: int) -> UUID:
    return UUID(f"e3000000-0000-0000-0000-{index:012d}")


def _assert_selected_cycle_payload(
    payload: dict[str, object],
    *,
    selected_cycle: int,
    coverage_start_date: str,
    coverage_end_date: str,
) -> None:
    assert payload["selected_cycle"] == selected_cycle
    assert payload["coverage_start_date"] == coverage_start_date
    assert payload["coverage_end_date"] == coverage_end_date
    assert payload["available_cycles"] == [2022, 2024, 2026]


def _database_current_date(db_conn: psycopg.Connection) -> date:
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT CURRENT_DATE")
        current_date = cursor.fetchone()[0]
    assert isinstance(current_date, date)
    return current_date


def _expected_complete_2026_monthly_totals(today: date) -> list[dict[str, object]]:
    expected_months = [
        ("2025-01", "0.00", 0),
        ("2025-02", "0.00", 0),
        ("2025-03", "0.00", 0),
        ("2025-04", "0.00", 0),
        ("2025-05", "0.00", 0),
        ("2025-06", "0.00", 0),
        ("2025-07", "0.00", 0),
        ("2025-08", "0.00", 0),
        ("2025-09", "0.00", 0),
        ("2025-10", "0.00", 0),
        ("2025-11", "0.00", 0),
        ("2025-12", "0.00", 0),
        ("2026-01", "200.00", 1),
        ("2026-02", "700.00", 2),
        ("2026-03", "1499.99", 2),
        ("2026-04", "0.00", 0),
        ("2026-05", "2999.99", 2),
        ("2026-06", "0.00", 0),
        ("2026-07", "1800.00", 2),
        ("2026-08", "0.00", 0),
        ("2026-09", "0.00", 0),
        ("2026-10", "0.00", 0),
        ("2026-11", "0.00", 0),
        ("2026-12", "0.00", 0),
    ]
    last_month = min(today, date(2026, 12, 31)).strftime("%Y-%m")
    return [
        {"month": month, "total_amount": total_amount, "transaction_count": transaction_count}
        for month, total_amount, transaction_count in expected_months
        if month <= last_month
    ]


def _seed_person_contribution_insights_fixture(
    db_conn: psycopg.Connection,
    *,
    office_name: str = "us_house",
    office_title: str = "Representative",
    candidate_office: str = "H",
    candidate_fec_id: str = "H0NC01077",
    include_summary: bool = True,
    include_zcta: bool = True,
    include_itemized_receipts: bool = True,
) -> tuple[UUID, UUID]:
    person = Person(canonical_name="Insights House Member")
    insert_person(db_conn, person)

    division_id = UUID("d1000000-0000-0000-0000-000000000001")
    office_id = UUID("d1000000-0000-0000-0000-000000000002")
    insert_electoral_division_row(
        db_conn,
        division_id=division_id,
        name="NC Congressional District 01",
        division_type="congressional_district",
        state="NC",
        district_number="01",
    )
    office_division_id = division_id if office_name in {"us_house", "us_delegate"} else None
    holding_division_id = division_id if office_name in {"us_house", "us_delegate"} else None
    insert_office_row(
        db_conn,
        office_id=office_id,
        name=office_name,
        title=office_title,
        state="NC",
        electoral_division_id=office_division_id,
    )
    insert_officeholding_row(
        db_conn,
        officeholding_id=UUID("d1000000-0000-0000-0000-000000000003"),
        person_id=person.id,
        office_id=office_id,
        electoral_division_id=holding_division_id,
    )
    if include_zcta:
        insert_zcta_district_row(db_conn, zcta5="27701", state_fips="37", cd_geoid="3701", district_number="01")
        insert_zcta_district_row(db_conn, zcta5="27709", state_fips="37", cd_geoid="3701", district_number="01")
        insert_zcta_district_row(db_conn, zcta5="22201", state_fips="51", cd_geoid="5108", district_number="08")

    committee_id = UUID("d1000000-0000-0000-0000-000000000004")
    candidate_id = UUID("d1000000-0000-0000-0000-000000000005")
    filing_id = UUID("d1000000-0000-0000-0000-000000000006")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C77770001",
            name="Insights House Committee",
            state="NC",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id=candidate_fec_id,
            name="Insights House Candidate",
            office=candidate_office,
            person_id=person.id,
            state="NC",
            district="01",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("d1000000-0000-0000-0000-000000000007"),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_filing_row(
        db_conn, FilingRowSeed(id=filing_id, filing_fec_id="insights-house-filing", committee_id=committee_id)
    )
    if include_summary:
        insert_committee_summary_row(
            db_conn,
            CommitteeSummaryRowSeed(
                committee_id=committee_id,
                cycle=2024,
                individual_itemized_contributions=Decimal("551.00"),
                individual_unitemized_contributions=Decimal("300.00"),
                coverage_start_date=date(2023, 1, 1),
                coverage_end_date=date(2024, 12, 31),
            ),
        )
        insert_committee_summary_row(
            db_conn,
            CommitteeSummaryRowSeed(
                committee_id=committee_id,
                cycle=2026,
                individual_itemized_contributions=Decimal("7199.98"),
                individual_unitemized_contributions=Decimal("200.00"),
                coverage_start_date=date(2025, 1, 1),
                coverage_end_date=date(2026, 12, 31),
            ),
        )

    data_source = insert_data_source_for_test(db_conn, jurisdiction="federal/fec", name_suffix="insights-house")
    live_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("d1000000-0000-0000-0000-000000000008"),
        data_source_id=data_source.id,
        source_record_key="insights-live",
        source_url="https://example.org/record/insights-live",
        pull_date=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    superseding_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("d1000000-0000-0000-0000-000000000009"),
        data_source_id=data_source.id,
        source_record_key="insights-superseding",
        source_url="https://example.org/record/insights-superseding",
        pull_date=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
    )
    superseded_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("d1000000-0000-0000-0000-000000000010"),
        data_source_id=data_source.id,
        source_record_key="insights-superseded",
        source_url="https://example.org/record/insights-superseded",
        pull_date=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        superseded_by=superseding_source.id,
    )

    def insert_receipt(
        transaction_id: str,
        amount: str,
        transaction_date: date | None,
        contributor_state: str | None,
        contributor_zip: str | None,
        *,
        transaction_type: str = "15",
        entity_type: str | None = "IND",
        amendment_indicator: str = "N",
        is_memo: bool = False,
        source_record_id: UUID | None = live_source.id,
    ) -> None:
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=UUID(transaction_id),
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type=transaction_type,
                amount=Decimal(amount),
                amendment_indicator=amendment_indicator,
                source_record_id=source_record_id,
                transaction_date=transaction_date,
                contributor_name_raw=f"Donor {transaction_id[-4:]}",
                contributor_entity_type=entity_type,
                contributor_state=contributor_state,
                contributor_zip=contributor_zip,
                is_memo=is_memo,
                memo_code="X" if is_memo else None,
            ),
        )

    if include_itemized_receipts:
        insert_receipt("d1000000-0000-0000-0000-000000000011", "50.00", date(2024, 2, 3), "NC", "27701")
        insert_receipt("d1000000-0000-0000-0000-000000000012", "200.00", date(2024, 2, 20), "NC", "27709")
        insert_receipt("d1000000-0000-0000-0000-000000000013", "201.00", date(2024, 3, 1), "VA", "22201")
        insert_receipt("d1000000-0000-0000-0000-000000000039", "200.00", date(2026, 1, 11), "NC", "27701")
        insert_receipt("d1000000-0000-0000-0000-000000000040", "200.01", date(2026, 2, 5), "NC", "27709")
        insert_receipt("d1000000-0000-0000-0000-000000000041", "499.99", date(2026, 2, 6), "NC", "27709")
        insert_receipt("d1000000-0000-0000-0000-000000000042", "500.00", date(2026, 3, 7), "NC", "27701")
        insert_receipt("d1000000-0000-0000-0000-000000000043", "999.99", date(2026, 3, 8), "NC", "27701")
        insert_receipt("d1000000-0000-0000-0000-000000000044", "1000.00", date(2026, 5, 9), "NC", "27709")
        insert_receipt("d1000000-0000-0000-0000-000000000045", "1999.99", date(2026, 5, 10), "NC", "27709")
        insert_receipt("d1000000-0000-0000-0000-000000000046", "2000.00", date(2026, 7, 11), "NC", "27701")
        insert_receipt("d1000000-0000-0000-0000-000000000047", "-200.00", date(2026, 7, 12), "NC", "27701")
        insert_receipt(
            "d1000000-0000-0000-0000-000000000014",
            "100.00",
            date(2024, 3, 4),
            "NC",
            "27701",
        )
        insert_receipt("d1000000-0000-0000-0000-000000000015", "999.00", date(2021, 12, 31), "NC", "27701")
        insert_receipt(
            "d1000000-0000-0000-0000-000000000016",
            "888.00",
            date(2024, 3, 5),
            "NC",
            "27701",
            entity_type="ORG",
        )
        insert_receipt(
            "d1000000-0000-0000-0000-000000000017",
            "777.00",
            date(2024, 3, 6),
            "NC",
            "27701",
            transaction_type="20",
        )
        insert_receipt("d1000000-0000-0000-0000-000000000018", "666.00", None, "NC", "27701")
        insert_receipt(
            "d1000000-0000-0000-0000-000000000019",
            "555.00",
            date(2024, 3, 7),
            "NC",
            "27701",
            amendment_indicator="T",
        )
        insert_receipt(
            "d1000000-0000-0000-0000-000000000020",
            "444.00",
            date(2024, 3, 8),
            "NC",
            "27701",
            source_record_id=superseded_source.id,
        )
    return person.id, candidate_id


def _seed_principal_committee_fallback_fixture(
    db_conn: psycopg.Connection,
    *,
    row_shape: PrincipalCommitteeFallbackShape = "selected_cycle_fallback",
) -> tuple[UUID, UUID, UUID]:
    person = Person(canonical_name="Principal Committee Fallback Member")
    insert_person(db_conn, person)

    office_id = UUID("d2000000-0000-0000-0000-000000000002")
    insert_office_row(
        db_conn,
        office_id=office_id,
        name="us_senate",
        title="Senator",
        state="NC",
        electoral_division_id=None,
    )
    insert_officeholding_row(
        db_conn,
        officeholding_id=UUID("d2000000-0000-0000-0000-000000000003"),
        person_id=person.id,
        office_id=office_id,
        electoral_division_id=None,
    )

    committee_id = UUID("d2000000-0000-0000-0000-000000000004")
    candidate_id = UUID("d2000000-0000-0000-0000-000000000005")
    filing_id = UUID("d2000000-0000-0000-0000-000000000006")
    candidate_summary_coverage_end_date = (
        date(2026, 3, 31) if row_shape == "production_missing_self_funding_columns" else date(2024, 12, 31)
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C88880001",
            name="Principal Fallback Committee",
            state="NC",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="S4NC02024",
            name="Principal Fallback Candidate",
            office="S",
            person_id=person.id,
            principal_committee_id=committee_id,
            state="NC",
            total_receipts=Decimal("1234.00"),
            total_disbursements=Decimal("400.00"),
            cash_on_hand=Decimal("834.00"),
            candidate_contrib=Decimal("75.00"),
            candidate_loans=Decimal("25.00"),
            candidate_loan_repay=Decimal("10.00"),
            summary_coverage_end_date=candidate_summary_coverage_end_date,
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id="principal-fallback-filing",
            committee_id=committee_id,
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2024,
            total_receipts=Decimal("1234.00"),
            total_disbursements=Decimal("400.00"),
            cash_on_hand=Decimal("834.00"),
            individual_contributions=Decimal("800.00"),
            party_committee_contributions=Decimal("50.00"),
            other_committee_contributions=Decimal("200.00"),
            transfers_from_other_authorized_committees=Decimal("34.00"),
            debts_owed_by_committee=Decimal("33.00"),
            individual_itemized_contributions=Decimal("700.00"),
            individual_unitemized_contributions=Decimal("100.00"),
            candidate_contributions=Decimal("75.00"),
            candidate_loans=Decimal("25.00"),
            coverage_start_date=date(2023, 1, 1),
            coverage_end_date=date(2024, 12, 31),
        ),
    )
    for transaction_id, amount, transaction_date, contributor_zip in (
        (UUID("d2000000-0000-0000-0000-000000000007"), Decimal("200.00"), date(2024, 2, 3), "27701"),
        (UUID("d2000000-0000-0000-0000-000000000008"), Decimal("500.00"), date(2024, 3, 4), "27709"),
    ):
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=transaction_id,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="15",
                amount=amount,
                amendment_indicator="N",
                transaction_date=transaction_date,
                contributor_name_raw=f"Fallback Donor {contributor_zip}",
                contributor_entity_type="IND",
                contributor_state="NC",
                contributor_zip=contributor_zip,
            ),
        )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d2000000-0000-0000-0000-000000000009"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24A",
            amount=Decimal("400.00"),
            amendment_indicator="N",
            transaction_date=date(2024, 4, 5),
        ),
    )
    if row_shape == "production_missing_self_funding_columns":
        insert_candidate_committee_link_row(
            db_conn,
            CandidateCommitteeLinkSeed(
                id=UUID("d2000000-0000-0000-0000-000000000013"),
                candidate_id=candidate_id,
                committee_id=committee_id,
                valid_period="[2025-01-01,2027-01-01)",
                designation="P",
                candidate_election_year=2026,
                fec_election_year=2026,
            ),
        )
        insert_committee_summary_row(
            db_conn,
            CommitteeSummaryRowSeed(
                committee_id=committee_id,
                cycle=2026,
                total_receipts=Decimal("2222.00"),
                total_disbursements=Decimal("777.00"),
                cash_on_hand=Decimal("1445.00"),
                individual_contributions=Decimal("1200.00"),
                party_committee_contributions=Decimal("100.00"),
                other_committee_contributions=Decimal("300.00"),
                transfers_from_other_authorized_committees=Decimal("122.00"),
                debts_owed_by_committee=Decimal("44.00"),
                individual_itemized_contributions=Decimal("1000.00"),
                individual_unitemized_contributions=Decimal("200.00"),
                candidate_contributions=Decimal("400.00"),
                candidate_loans=Decimal("50.00"),
                coverage_start_date=date(2025, 1, 1),
                coverage_end_date=date(2026, 3, 31),
            ),
        )
        for transaction_id, amount, transaction_type, transaction_date in (
            (UUID("d2000000-0000-0000-0000-000000000014"), Decimal("1200.00"), "15", date(2026, 2, 3)),
            (UUID("d2000000-0000-0000-0000-000000000015"), Decimal("777.00"), "24A", date(2026, 3, 4)),
        ):
            insert_transaction_row(
                db_conn,
                TransactionRowSeed(
                    id=transaction_id,
                    filing_id=filing_id,
                    committee_id=committee_id,
                    transaction_type=transaction_type,
                    amount=amount,
                    amendment_indicator="N",
                    transaction_date=transaction_date,
                ),
            )
        with db_conn.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE cf.candidate
                    DROP COLUMN candidate_contrib,
                    DROP COLUMN candidate_loans,
                    DROP COLUMN candidate_loan_repay
                """
            )
    return person.id, candidate_id, committee_id


def _insert_stage3_geography_receipts(
    db_conn: psycopg.Connection,
    *,
    filing_id: UUID,
    committee_id: UUID,
) -> None:
    rows = [
        (31, "600.00", "NC", "27701", "In-district donor"),
        (32, "500.00", "NC", "27601", "Elsewhere NC donor"),
        (33, "400.00", "VA", "22201", "Virginia donor"),
        (34, "300.00", "CA", "94105", "California donor"),
        (35, "200.00", "TX", "73301", "Texas donor"),
        (36, "100.00", "FL", "33101", "Florida donor"),
        (37, "50.00", "WA", "98101", "Washington donor"),
        (38, "25.00", None, "27701", "Blank-state donor"),
        (39, "900.00", "NY", "12AB", "Invalid-zip donor"),
        (40, "70.00", "NC", "99999", "Unmapped-zip donor"),
    ]
    for row_index, amount, contributor_state, contributor_zip, contributor_name in rows:
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=_stage3_uuid(row_index),
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="15",
                amendment_indicator="N",
                transaction_date=date(2026, 3, row_index - 30),
                amount=Decimal(amount),
                contributor_name_raw=contributor_name,
                contributor_entity_type="IND",
                contributor_state=contributor_state,
                contributor_zip=contributor_zip,
            ),
        )


def _seed_stage3_geography_fixture(
    db_conn: psycopg.Connection,
    *,
    office_name: str,
    office_title: str,
    candidate_office: str,
    candidate_fec_id: str,
    office_state: str = "NC",
    office_district: str | None = "01",
) -> tuple[UUID, UUID, UUID]:
    person = Person(canonical_name=f"Stage 3 {office_title}")
    insert_person(db_conn, person)
    division_id = _stage3_uuid(1)
    office_id = _stage3_uuid(2)
    committee_id = _stage3_uuid(4)
    candidate_id = _stage3_uuid(5)
    filing_id = _stage3_uuid(6)
    if office_district is not None:
        insert_electoral_division_row(
            db_conn,
            division_id=division_id,
            name=f"{office_state} District {office_district}",
            division_type="congressional_district",
            state=office_state,
            district_number=office_district,
        )
    insert_office_row(
        db_conn,
        office_id=office_id,
        name=office_name,
        title=office_title,
        state=office_state,
        electoral_division_id=division_id if office_district is not None else None,
    )
    insert_officeholding_row(
        db_conn,
        officeholding_id=_stage3_uuid(3),
        person_id=person.id,
        office_id=office_id,
        electoral_division_id=division_id if office_district is not None else None,
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_id, fec_committee_id="C99300001", name=f"{office_title} Committee"),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id=candidate_fec_id,
            name=f"Stage 3 {office_title} Candidate",
            office=candidate_office,
            person_id=person.id,
            state=office_state,
            district=office_district,
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=_stage3_uuid(7),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2025-01-01,2027-01-01)",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_filing_row(db_conn, FilingRowSeed(id=filing_id, filing_fec_id="stage3-geography", committee_id=committee_id))
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            individual_itemized_contributions=Decimal("3145.00"),
            individual_unitemized_contributions=Decimal("0.00"),
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2026, 12, 31),
        ),
    )
    insert_zcta_district_row(
        db_conn,
        zcta5="27701",
        state_fips="37",
        cd_geoid=f"37{office_district or '01'}",
        district_number=office_district or "01",
    )
    insert_zcta_district_row(db_conn, zcta5="27601", state_fips="37", cd_geoid="3702", district_number="02")
    insert_zcta_district_row(db_conn, zcta5="22201", state_fips="51", cd_geoid="5108", district_number="08")
    insert_zcta_district_row(db_conn, zcta5="94105", state_fips="06", cd_geoid="0611", district_number="11")
    insert_zcta_district_row(db_conn, zcta5="73301", state_fips="48", cd_geoid="4837", district_number="37")
    insert_zcta_district_row(db_conn, zcta5="33101", state_fips="12", cd_geoid="1227", district_number="27")
    insert_zcta_district_row(db_conn, zcta5="98101", state_fips="53", cd_geoid="5307", district_number="07")
    _insert_stage3_geography_receipts(db_conn, filing_id=filing_id, committee_id=committee_id)
    return person.id, candidate_id, committee_id


def _stage3_expected_state_rows() -> list[dict[str, object]]:
    return [
        {"label": "NC", "total_amount": "1170.00", "transaction_count": 3},
        {"label": "VA", "total_amount": "400.00", "transaction_count": 1},
        {"label": "CA", "total_amount": "300.00", "transaction_count": 1},
        {"label": "TX", "total_amount": "200.00", "transaction_count": 1},
        {"label": "FL", "total_amount": "100.00", "transaction_count": 1},
        {"label": "Other states", "total_amount": "50.00", "transaction_count": 1},
        {"label": "Unknown", "total_amount": "925.00", "transaction_count": 2},
    ]


def _assert_stage3_geography_denominators(geography: dict[str, object]) -> None:
    assert geography["classified_amount"] == "2220.00"
    assert geography["classified_transaction_count"] == 8
    assert geography["unknown_amount"] == "925.00"
    assert geography["unknown_transaction_count"] == 2


def _assert_stage3_direct_sql_rows(
    db_conn: psycopg.Connection,
    *,
    committee_id: UUID,
    office_name: str,
    office_state: str,
    office_district: str,
    expected_district_rows: list[dict[str, object]],
) -> None:
    cycle = campaign_finance_query_module.resolve_selected_cycle(2026)
    unbounded_state_rows = campaign_finance_query_module._fetch_person_insights_rows(
        db_conn,
        campaign_finance_query_module._PERSON_CONTRIBUTION_INSIGHTS_STATE_SQL,
        [committee_id],
        cycle,
    )
    state_rows = campaign_finance_query_module._fetch_person_insights_itemized_rollups(
        db_conn,
        [committee_id],
        cycle,
        complete_summary_coverage=True,
    )["state_rows"]
    district_rows = campaign_finance_query_module._fetch_person_insights_rows(
        db_conn,
        campaign_finance_query_module._PERSON_CONTRIBUTION_INSIGHTS_DISTRICT_SQL,
        [committee_id],
        cycle,
        office_name,
        office_name,
        office_state,
        office_name,
        office_state,
        office_district,
        office_state,
    )
    assert unbounded_state_rows == [
        {"label": "NC", "total_amount": Decimal("1170.00"), "transaction_count": 3},
        {"label": "Unknown", "total_amount": Decimal("925.00"), "transaction_count": 2},
        {"label": "VA", "total_amount": Decimal("400.00"), "transaction_count": 1},
        {"label": "CA", "total_amount": Decimal("300.00"), "transaction_count": 1},
        {"label": "TX", "total_amount": Decimal("200.00"), "transaction_count": 1},
        {"label": "FL", "total_amount": Decimal("100.00"), "transaction_count": 1},
        {"label": "WA", "total_amount": Decimal("50.00"), "transaction_count": 1},
    ]
    assert [
        {**row, "total_amount": f"{row['total_amount']:.2f}"} for row in state_rows
    ] == _stage3_expected_state_rows()
    assert district_rows == expected_district_rows


def _seed_stage3_receipt_source_candidate(db_conn: psycopg.Connection) -> tuple[UUID, UUID, UUID]:
    candidate_id = _stage3_uuid(101)
    committee_a_id = _stage3_uuid(102)
    committee_b_id = _stage3_uuid(103)
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC03101",
            name="Stage 3 Receipt Candidate",
            office="H",
        ),
    )
    for committee_id, fec_committee_id, name, link_index in (
        (committee_a_id, "C99300102", "Stage 3 Receipt Committee A", 104),
        (committee_b_id, "C99300103", "Stage 3 Receipt Committee B", 105),
    ):
        insert_committee_row(db_conn, CommitteeRowSeed(id=committee_id, fec_committee_id=fec_committee_id, name=name))
        insert_candidate_committee_link_row(
            db_conn,
            CandidateCommitteeLinkSeed(
                id=_stage3_uuid(link_index),
                candidate_id=candidate_id,
                committee_id=committee_id,
                valid_period="[2023-01-01,2027-01-01)",
                candidate_election_year=2026,
                fec_election_year=2026,
            ),
        )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_a_id,
            cycle=2024,
            total_receipts=Decimal("9999.00"),
            total_disbursements=Decimal("1111.00"),
            coverage_start_date=date(2023, 1, 1),
            coverage_end_date=date(2024, 12, 31),
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_a_id,
            cycle=2026,
            total_receipts=Decimal("1000.00"),
            total_disbursements=Decimal("300.00"),
            cash_on_hand=Decimal("700.00"),
            individual_contributions=Decimal("500.00"),
            other_committee_contributions=Decimal("100.00"),
            party_committee_contributions=Decimal("50.00"),
            candidate_contributions=Decimal("75.00"),
            candidate_loans=Decimal("25.00"),
            transfers_from_other_authorized_committees=Decimal("100.00"),
            debts_owed_by_committee=Decimal("80.00"),
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2026, 12, 31),
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_b_id,
            cycle=2026,
            total_receipts=Decimal("500.00"),
            total_disbursements=Decimal("200.00"),
            cash_on_hand=Decimal("300.00"),
            individual_contributions=Decimal("200.00"),
            other_committee_contributions=Decimal("25.00"),
            party_committee_contributions=Decimal("25.00"),
            candidate_contributions=Decimal("10.00"),
            candidate_loans=Decimal("15.00"),
            transfers_from_other_authorized_committees=Decimal("50.00"),
            debts_owed_by_committee=Decimal("20.00"),
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2026, 12, 31),
        ),
    )
    return candidate_id, committee_a_id, committee_b_id


def _expected_receipt_source_composition() -> list[dict[str, str]]:
    return [
        {"label": "Individual contributions", "total_amount": "700.00", "source": "fec_committee_summary"},
        {"label": "PAC/other committee contributions", "total_amount": "125.00", "source": "fec_committee_summary"},
        {"label": "Party committee contributions", "total_amount": "75.00", "source": "fec_committee_summary"},
        {"label": "Candidate funding", "total_amount": "125.00", "source": "fec_committee_summary"},
        {
            "label": "Transfers from other authorized committees",
            "total_amount": "150.00",
            "source": "fec_committee_summary",
        },
        {"label": "Other receipts", "total_amount": "325.00", "source": "fec_committee_summary"},
    ]


def _seed_expired_person_contribution_insights_committee(
    db_conn: psycopg.Connection,
    *,
    candidate_id: UUID,
) -> None:
    expired_committee_id = UUID("d1000000-0000-0000-0000-000000000026")
    expired_filing_id = UUID("d1000000-0000-0000-0000-000000000027")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=expired_committee_id,
            fec_committee_id="C77770003",
            name="Insights Expired Committee",
            state="NC",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("d1000000-0000-0000-0000-000000000028"),
            candidate_id=candidate_id,
            committee_id=expired_committee_id,
            valid_period="[2000-01-01,2001-01-01)",
            designation="P",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=expired_filing_id,
            filing_fec_id="insights-expired-filing",
            committee_id=expired_committee_id,
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=expired_committee_id,
            cycle=2024,
            individual_unitemized_contributions=Decimal("800.00"),
            coverage_start_date=date(2023, 1, 1),
            coverage_end_date=date(2024, 12, 31),
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=expired_committee_id,
            cycle=2026,
            individual_unitemized_contributions=Decimal("900.00"),
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2026, 12, 31),
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d1000000-0000-0000-0000-000000000029"),
            filing_id=expired_filing_id,
            committee_id=expired_committee_id,
            transaction_type="15",
            amendment_indicator="N",
            transaction_date=date(2024, 4, 9),
            amount=Decimal("321.00"),
            contributor_name_raw="Expired Link Donor",
            contributor_entity_type="IND",
            contributor_state="NC",
            contributor_zip="27701",
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d1000000-0000-0000-0000-000000000030"),
            filing_id=expired_filing_id,
            committee_id=expired_committee_id,
            transaction_type="15",
            amendment_indicator="N",
            transaction_date=date(2026, 5, 10),
            amount=Decimal("75.00"),
            contributor_name_raw="Expired Small Donor",
            contributor_entity_type="IND",
            contributor_state="VA",
            contributor_zip="22201",
        ),
    )


def test_get_person_contribution_insights_returns_house_itemized_unitemized_geography_and_cycle_totals(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    _seed_expired_person_contribution_insights_committee(db_conn, candidate_id=candidate_id)

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["person_id"] == str(person_id)
    assert payload["has_data"] is True
    assert payload["metadata"] == {
        "selected_cycle": 2026,
        "coverage_start_date": "2025-01-01",
        "coverage_end_date": "2026-12-31",
        "available_cycles": [2022, 2024, 2026],
        "cycles_included": [2026],
        "committee_count": 1,
        "approximate_geography": True,
        "excluded_geography": None,
        "caveats": [],
    }
    assert payload["monthly_totals"] == _expected_complete_2026_monthly_totals(_database_current_date(db_conn))
    assert payload["itemized_size_buckets"] == [
        {
            "label": "$200 and under",
            "min_amount": "0.01",
            "max_amount": "200.00",
            "total_amount": "0.00",
            "transaction_count": 2,
        },
        {
            "label": "$200.01-$499.99",
            "min_amount": "200.01",
            "max_amount": "499.99",
            "total_amount": "700.00",
            "transaction_count": 2,
        },
        {
            "label": "$500-$999.99",
            "min_amount": "500.00",
            "max_amount": "999.99",
            "total_amount": "1499.99",
            "transaction_count": 2,
        },
        {
            "label": "$1,000-$1,999.99",
            "min_amount": "1000.00",
            "max_amount": "1999.99",
            "total_amount": "2999.99",
            "transaction_count": 2,
        },
        {
            "label": "$2,000 and over",
            "min_amount": "2000.00",
            "max_amount": None,
            "total_amount": "2000.00",
            "transaction_count": 1,
        },
    ]
    assert payload["dollars_by_size"] == [
        {"label": "Unitemized (<$200)", "total_amount": "200.00", "source": "committee_summary"},
        {"label": "$200 and under itemized", "total_amount": "0.00", "source": "transactions"},
        {"label": "$200.01-$499.99 itemized", "total_amount": "700.00", "source": "transactions"},
        {"label": "$500-$999.99 itemized", "total_amount": "1499.99", "source": "transactions"},
        {"label": "$1,000-$1,999.99 itemized", "total_amount": "2999.99", "source": "transactions"},
        {"label": "$2,000 and over itemized", "total_amount": "2000.00", "source": "transactions"},
    ]
    assert payload["cycle_totals"] == [
        {
            "cycle": 2026,
            "itemized_individual_contribution_amount": "7199.98",
            "itemized_transaction_count": 9,
            "unitemized_individual_contribution_amount": "200.00",
            "total_individual_contribution_amount": "7399.98",
            "source": "committee_summary",
        },
    ]
    assert payload["career_totals"] == {
        "itemized_individual_contribution_amount": "7199.98",
        "itemized_transaction_count": 9,
        "unitemized_individual_contribution_amount": "200.00",
        "total_individual_contribution_amount": "7399.98",
        "source": "committee_summary",
    }
    assert payload["geography"] == {
        "by_state": [
            {"label": "NC", "total_amount": "7199.98", "transaction_count": 9},
        ],
        "by_district": [
            {"label": "In district", "total_amount": "7199.98", "transaction_count": 9},
        ],
        "district_share": {
            "in_district_amount": "7199.98",
            "out_of_district_amount": "0.00",
            "unknown_district_amount": "0.00",
            "share": "1.0000",
            "available": True,
        },
        "geography_mode": "district",
        "classified_amount": "7199.98",
        "classified_transaction_count": 9,
        "unknown_amount": "0.00",
        "unknown_transaction_count": 0,
    }
    assert payload["small_dollar_share"] == {
        "small_dollar_amount": "200.00",
        "total_contribution_amount": "7399.98",
        "share": "0.0270",
        "available": True,
    }


def test_get_person_contribution_insights_uses_cycle_matching_principal_committee_fallback(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id, committee_id = _seed_principal_committee_fallback_fixture(db_conn)

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights?cycle=2024")

    assert response.status_code == 200
    payload = response.json()
    assert payload["person_id"] == str(person_id)
    assert payload["has_data"] is True
    assert payload["metadata"] == {
        "selected_cycle": 2024,
        "coverage_start_date": "2023-01-01",
        "coverage_end_date": "2024-12-31",
        "available_cycles": [2022, 2024, 2026],
        "cycles_included": [2024],
        "committee_count": 1,
        "approximate_geography": True,
        "excluded_geography": None,
        "caveats": [],
    }
    assert payload["metadata"]["excluded_geography"] != "no_linked_candidate"
    assert str(committee_id) == "d2000000-0000-0000-0000-000000000004"
    assert payload["itemized_size_buckets"] == [
        {
            "label": "$200 and under",
            "min_amount": "0.01",
            "max_amount": "200.00",
            "total_amount": "200.00",
            "transaction_count": 1,
        },
        {
            "label": "$200.01-$499.99",
            "min_amount": "200.01",
            "max_amount": "499.99",
            "total_amount": "0.00",
            "transaction_count": 0,
        },
        {
            "label": "$500-$999.99",
            "min_amount": "500.00",
            "max_amount": "999.99",
            "total_amount": "500.00",
            "transaction_count": 1,
        },
        {
            "label": "$1,000-$1,999.99",
            "min_amount": "1000.00",
            "max_amount": "1999.99",
            "total_amount": "0.00",
            "transaction_count": 0,
        },
        {
            "label": "$2,000 and over",
            "min_amount": "2000.00",
            "max_amount": None,
            "total_amount": "0.00",
            "transaction_count": 0,
        },
    ]
    assert payload["dollars_by_size"] == [
        {"label": "Unitemized (<$200)", "total_amount": "100.00", "source": "committee_summary"},
        {"label": "$200 and under itemized", "total_amount": "200.00", "source": "transactions"},
        {"label": "$200.01-$499.99 itemized", "total_amount": "0.00", "source": "transactions"},
        {"label": "$500-$999.99 itemized", "total_amount": "500.00", "source": "transactions"},
        {"label": "$1,000-$1,999.99 itemized", "total_amount": "0.00", "source": "transactions"},
        {"label": "$2,000 and over itemized", "total_amount": "0.00", "source": "transactions"},
    ]
    assert payload["cycle_totals"] == [
        {
            "cycle": 2024,
            "itemized_individual_contribution_amount": "700.00",
            "itemized_transaction_count": 2,
            "unitemized_individual_contribution_amount": "100.00",
            "total_individual_contribution_amount": "800.00",
            "source": "committee_summary",
        },
    ]
    assert payload["career_totals"] == {
        "itemized_individual_contribution_amount": "700.00",
        "itemized_transaction_count": 2,
        "unitemized_individual_contribution_amount": "100.00",
        "total_individual_contribution_amount": "800.00",
        "source": "committee_summary",
    }
    assert payload["small_dollar_share"] == {
        "small_dollar_amount": "300.00",
        "total_contribution_amount": "800.00",
        "share": "0.3750",
        "available": True,
    }


def test_selected_cycle_routes_default_and_accept_supported_cycle(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    committee_id = UUID("d1000000-0000-0000-0000-000000000004")

    default_insights = api_client.get(f"/v1/person/{person_id}/contribution-insights")
    assert default_insights.status_code == 200
    _assert_selected_cycle_payload(
        default_insights.json()["metadata"],
        selected_cycle=2026,
        coverage_start_date="2025-01-01",
        coverage_end_date="2026-12-31",
    )

    cycle_2024_expectations = [
        (
            f"/v1/person/{person_id}/contribution-insights?cycle=2024",
            ("metadata",),
        ),
        (f"/v1/candidates/{candidate_id}/summary?cycle=2024", ()),
        (f"/v1/committees/{committee_id}/summary?cycle=2024", ()),
        (f"/v1/candidates/{candidate_id}/independent-expenditures/summary?cycle=2024", ()),
    ]
    for path, metadata_path in cycle_2024_expectations:
        response = api_client.get(path)
        assert response.status_code == 200
        payload = response.json()
        selected_payload = payload["metadata"] if metadata_path else payload
        _assert_selected_cycle_payload(
            selected_payload,
            selected_cycle=2024,
            coverage_start_date="2023-01-01",
            coverage_end_date="2024-12-31",
        )

    accepted_list_paths = [
        f"/v1/person/{person_id}/top-donors?cycle=2024",
        f"/v1/person/{person_id}/top-employers?cycle=2024",
        f"/v1/candidates/{candidate_id}/independent-expenditures?cycle=2024",
        f"/v1/transactions?committee_id={committee_id}&cycle=2024",
    ]
    for path in accepted_list_paths:
        assert api_client.get(path).status_code == 200


@pytest.mark.parametrize("cycle", [2020, 2025])
@pytest.mark.parametrize(
    "path",
    [
        f"/v1/person/{uuid4()}/contribution-insights",
        f"/v1/person/{uuid4()}/top-donors",
        f"/v1/person/{uuid4()}/top-employers",
        f"/v1/candidates/{uuid4()}/summary",
        f"/v1/candidates/{uuid4()}/independent-expenditures",
        f"/v1/candidates/{uuid4()}/independent-expenditures/summary",
        f"/v1/committees/{uuid4()}/summary",
        f"/v1/transactions?committee_id={uuid4()}",
    ],
)
def test_selected_cycle_routes_reject_unsupported_cycle_before_query_execution(
    api_client: TestClient,
    path: str,
    cycle: int,
) -> None:
    separator = "&" if "?" in path else "?"
    response = api_client.get(f"{path}{separator}cycle={cycle}")

    assert response.status_code == 422
    assert str(cycle) in response.text


def test_get_person_contribution_insights_uses_latest_loaded_zcta_boundary_year(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    insert_zcta_district_row(
        db_conn,
        zcta5="27701",
        state_fips="37",
        cd_geoid="3702",
        district_number="02",
        boundary_year=2024,
    )
    insert_zcta_district_row(
        db_conn,
        zcta5="27709",
        state_fips="37",
        cd_geoid="3702",
        district_number="02",
        boundary_year=2024,
    )
    insert_zcta_district_row(
        db_conn,
        zcta5="22201",
        state_fips="51",
        cd_geoid="5108",
        district_number="08",
        boundary_year=2024,
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_district"] == [
        {"label": "Elsewhere in state", "total_amount": "7199.98", "transaction_count": 9},
    ]
    assert payload["geography"]["district_share"] == {
        "in_district_amount": "0.00",
        "out_of_district_amount": "7199.98",
        "unknown_district_amount": "0.00",
        "share": "0.0000",
        "available": True,
    }
    assert payload["metadata"]["caveats"] == []


def test_get_person_contribution_insights_keeps_unsupported_2022_cycle_itemized(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d1000000-0000-0000-0000-000000000048"),
            filing_id=UUID("d1000000-0000-0000-0000-000000000006"),
            committee_id=UUID("d1000000-0000-0000-0000-000000000004"),
            transaction_type="15",
            amendment_indicator="N",
            transaction_date=date(2022, 7, 4),
            amount=Decimal("125.00"),
            contributor_name_raw="Unsupported Cycle Donor",
            contributor_entity_type="IND",
            contributor_state="NC",
            contributor_zip="27701",
        ),
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["cycles_included"] == [2026]
    assert payload["metadata"]["caveats"] == []
    assert payload["cycle_totals"] == [
        {
            "cycle": 2026,
            "itemized_individual_contribution_amount": "7199.98",
            "itemized_transaction_count": 9,
            "unitemized_individual_contribution_amount": "200.00",
            "total_individual_contribution_amount": "7399.98",
            "source": "committee_summary",
        },
    ]
    assert payload["career_totals"] == {
        "itemized_individual_contribution_amount": "7199.98",
        "itemized_transaction_count": 9,
        "unitemized_individual_contribution_amount": "200.00",
        "total_individual_contribution_amount": "7399.98",
        "source": "committee_summary",
    }

    cycle_2022_response = api_client.get(f"/v1/person/{person_id}/contribution-insights?cycle=2022")

    assert cycle_2022_response.status_code == 200
    cycle_2022_payload = cycle_2022_response.json()
    _assert_selected_cycle_payload(
        cycle_2022_payload["metadata"],
        selected_cycle=2022,
        coverage_start_date="2021-01-01",
        coverage_end_date="2022-12-31",
    )
    assert cycle_2022_payload["metadata"]["cycles_included"] == []
    assert cycle_2022_payload["metadata"]["caveats"] == [
        "missing_committee_summary",
        "itemized_summary_reconciliation_unavailable",
        "itemized_only_cycle_totals",
        "current_district_approximation",
    ]
    assert cycle_2022_payload["cycle_totals"] == [
        {
            "cycle": 2022,
            "itemized_individual_contribution_amount": "1124.00",
            "itemized_transaction_count": 2,
            "unitemized_individual_contribution_amount": "0.00",
            "total_individual_contribution_amount": "1124.00",
            "source": "itemized_transactions",
        }
    ]
    assert cycle_2022_payload["career_totals"] == {
        "itemized_individual_contribution_amount": "1124.00",
        "itemized_transaction_count": 2,
        "unitemized_individual_contribution_amount": "0.00",
        "total_individual_contribution_amount": "1124.00",
        "source": "itemized_transactions",
    }


def test_get_person_contribution_insights_cycle_totals_fall_back_when_summary_missing(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(db_conn, include_summary=False)

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_data"] is True
    assert payload["metadata"]["cycles_included"] == []
    assert payload["metadata"]["caveats"] == [
        "missing_committee_summary",
        "itemized_summary_reconciliation_unavailable",
        "itemized_only_cycle_totals",
    ]
    assert payload["cycle_totals"] == [
        {
            "cycle": 2026,
            "itemized_individual_contribution_amount": "7199.98",
            "itemized_transaction_count": 9,
            "unitemized_individual_contribution_amount": "0.00",
            "total_individual_contribution_amount": "7199.98",
            "source": "itemized_transactions",
        },
    ]
    assert payload["career_totals"] == {
        "itemized_individual_contribution_amount": "7199.98",
        "itemized_transaction_count": 9,
        "unitemized_individual_contribution_amount": "0.00",
        "total_individual_contribution_amount": "7199.98",
        "source": "itemized_transactions",
    }
    assert [bucket["label"] for bucket in payload["dollars_by_size"]] == [
        "$200 and under itemized",
        "$200.01-$499.99 itemized",
        "$500-$999.99 itemized",
        "$1,000-$1,999.99 itemized",
        "$2,000 and over itemized",
    ]
    assert payload["small_dollar_share"] == {
        "small_dollar_amount": None,
        "total_contribution_amount": None,
        "share": None,
        "available": False,
    }


@pytest.mark.parametrize(
    ("summary_itemized_amount", "expected_caveats", "expected_available"),
    [
        (
            Decimal("7199.99"),
            [],
            True,
        ),
        (
            Decimal("7200.00"),
            [
                "itemized_summary_reconciliation_mismatch",
                "itemized_only_cycle_totals",
            ],
            False,
        ),
    ],
)
def test_get_person_contribution_insights_gates_unitemized_facts_on_itemized_summary_reconciliation(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    summary_itemized_amount: Decimal,
    expected_caveats: list[str],
    expected_available: bool,
) -> None:
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    db_conn.execute(
        """
        UPDATE cf.committee_summary
        SET individual_itemized_contributions = %s
        WHERE committee_id = %s AND cycle = 2026
        """,
        (summary_itemized_amount, UUID("d1000000-0000-0000-0000-000000000004")),
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["caveats"] == expected_caveats
    assert payload["small_dollar_share"]["available"] is expected_available
    if expected_available:
        assert payload["dollars_by_size"][0] == {
            "label": "Unitemized (<$200)",
            "total_amount": "200.00",
            "source": "committee_summary",
        }
        assert payload["cycle_totals"][0]["total_individual_contribution_amount"] == "7399.98"
    else:
        assert payload["dollars_by_size"][0] == {
            "label": "$200 and under itemized",
            "total_amount": "0.00",
            "source": "transactions",
        }
        assert payload["cycle_totals"][0]["total_individual_contribution_amount"] == "7199.98"


def test_get_person_contribution_insights_marks_null_itemized_summary_unavailable(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    db_conn.execute(
        """
        UPDATE cf.committee_summary
        SET individual_itemized_contributions = NULL
        WHERE committee_id = %s AND cycle = 2026
        """,
        (UUID("d1000000-0000-0000-0000-000000000004"),),
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["cycles_included"] == []
    assert payload["metadata"]["caveats"] == [
        "itemized_summary_reconciliation_unavailable",
        "itemized_only_cycle_totals",
    ]
    assert payload["dollars_by_size"][0] == {
        "label": "$200 and under itemized",
        "total_amount": "0.00",
        "source": "transactions",
    }
    assert payload["cycle_totals"][0] == {
        "cycle": 2026,
        "itemized_individual_contribution_amount": "7199.98",
        "itemized_transaction_count": 9,
        "unitemized_individual_contribution_amount": "0.00",
        "total_individual_contribution_amount": "7199.98",
        "source": "itemized_transactions",
    }
    assert payload["small_dollar_share"] == {
        "small_dollar_amount": None,
        "total_contribution_amount": None,
        "share": None,
        "available": False,
    }


def test_get_person_contribution_insights_marks_partial_committee_summary_unavailable(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    secondary_committee_id = UUID("d1000000-0000-0000-0000-000000000021")
    secondary_filing_id = UUID("d1000000-0000-0000-0000-000000000022")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=secondary_committee_id,
            fec_committee_id="C77770002",
            name="Insights Secondary Committee",
            state="NC",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("d1000000-0000-0000-0000-000000000023"),
            candidate_id=candidate_id,
            committee_id=secondary_committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="A",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=secondary_filing_id,
            filing_fec_id="insights-secondary-filing",
            committee_id=secondary_committee_id,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d1000000-0000-0000-0000-000000000024"),
            filing_id=secondary_filing_id,
            committee_id=secondary_committee_id,
            transaction_type="15",
            amendment_indicator="N",
            transaction_date=date(2024, 4, 2),
            amount=Decimal("49.00"),
            contributor_name_raw="Secondary Donor",
            contributor_entity_type="IND",
            contributor_state="NC",
            contributor_zip="27701",
        ),
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["committee_count"] == 2
    assert payload["metadata"]["coverage_end_date"] == "2026-12-31"
    assert payload["metadata"]["cycles_included"] == []
    assert payload["metadata"]["caveats"] == [
        "missing_committee_summary",
        "itemized_summary_reconciliation_unavailable",
        "itemized_only_cycle_totals",
    ]
    assert [bucket["label"] for bucket in payload["dollars_by_size"]] == [
        "$200 and under itemized",
        "$200.01-$499.99 itemized",
        "$500-$999.99 itemized",
        "$1,000-$1,999.99 itemized",
        "$2,000 and over itemized",
    ]
    assert payload["small_dollar_share"] == {
        "small_dollar_amount": None,
        "total_contribution_amount": None,
        "share": None,
        "available": False,
    }


def test_get_person_contribution_insights_cycle_totals_fall_back_when_summary_cycle_coverage_partial(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    secondary_committee_id = UUID("d1000000-0000-0000-0000-000000000031")
    secondary_filing_id = UUID("d1000000-0000-0000-0000-000000000032")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=secondary_committee_id,
            fec_committee_id="C77770003",
            name="Insights Partial Cycle Committee",
            state="NC",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("d1000000-0000-0000-0000-000000000033"),
            candidate_id=candidate_id,
            committee_id=secondary_committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="A",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=secondary_filing_id,
            filing_fec_id="insights-partial-cycle-filing",
            committee_id=secondary_committee_id,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d1000000-0000-0000-0000-000000000034"),
            filing_id=secondary_filing_id,
            committee_id=secondary_committee_id,
            transaction_type="15",
            amendment_indicator="N",
            transaction_date=date(2024, 4, 2),
            amount=Decimal("49.00"),
            contributor_name_raw="Partial Cycle Donor",
            contributor_entity_type="IND",
            contributor_state="NC",
            contributor_zip="27701",
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=secondary_committee_id,
            cycle=2026,
            individual_unitemized_contributions=Decimal("125.00"),
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2026, 6, 30),
        ),
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["committee_count"] == 2
    assert payload["metadata"]["coverage_end_date"] == "2026-12-31"
    assert payload["metadata"]["cycles_included"] == []
    assert payload["metadata"]["caveats"] == [
        "missing_committee_summary",
        "itemized_summary_reconciliation_unavailable",
        "itemized_only_cycle_totals",
    ]
    assert payload["cycle_totals"] == [
        {
            "cycle": 2026,
            "itemized_individual_contribution_amount": "7199.98",
            "itemized_transaction_count": 9,
            "unitemized_individual_contribution_amount": "0.00",
            "total_individual_contribution_amount": "7199.98",
            "source": "itemized_transactions",
        },
    ]
    assert payload["career_totals"] == {
        "itemized_individual_contribution_amount": "7199.98",
        "itemized_transaction_count": 9,
        "unitemized_individual_contribution_amount": "0.00",
        "total_individual_contribution_amount": "7199.98",
        "source": "itemized_transactions",
    }
    assert [bucket["label"] for bucket in payload["dollars_by_size"]] == [
        "$200 and under itemized",
        "$200.01-$499.99 itemized",
        "$500-$999.99 itemized",
        "$1,000-$1,999.99 itemized",
        "$2,000 and over itemized",
    ]
    assert payload["small_dollar_share"] == {
        "small_dollar_amount": None,
        "total_contribution_amount": None,
        "share": None,
        "available": False,
    }


def test_get_person_contribution_insights_surfaces_mixed_unknown_district_geography(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d1000000-0000-0000-0000-000000000025"),
            filing_id=UUID("d1000000-0000-0000-0000-000000000006"),
            committee_id=UUID("d1000000-0000-0000-0000-000000000004"),
            transaction_type="15",
            amendment_indicator="N",
            transaction_date=date(2024, 4, 3),
            amount=Decimal("75.00"),
            contributor_name_raw="Unmapped District Donor",
            contributor_entity_type="IND",
            contributor_state="NC",
            contributor_zip="99999",
        ),
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_district"] == [
        {"label": "In district", "total_amount": "7199.98", "transaction_count": 9},
    ]
    assert payload["geography"]["district_share"] == {
        "in_district_amount": "7199.98",
        "out_of_district_amount": "0.00",
        "unknown_district_amount": "0.00",
        "share": "1.0000",
        "available": True,
    }
    assert payload["metadata"]["caveats"] == []


def test_get_person_contribution_insights_preserves_state_when_zcta_district_missing(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(db_conn, include_zcta=False)

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_state"] == [
        {"label": "NC", "total_amount": "7199.98", "transaction_count": 9},
    ]
    assert payload["geography"]["by_district"] == []
    assert payload["geography"]["district_share"] == {
        "in_district_amount": None,
        "out_of_district_amount": None,
        "unknown_district_amount": None,
        "share": None,
        "available": False,
    }
    assert payload["metadata"]["approximate_geography"] is True
    assert payload["metadata"]["caveats"] == ["missing_zcta_district"]


def test_get_person_contribution_insights_omits_statewide_and_executive_district_geography(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(
        db_conn,
        office_name="us_senate",
        office_title="Senator",
        candidate_office="S",
        candidate_fec_id="S0NC01077",
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_district"] == [
        {"label": "In state", "total_amount": "7199.98", "transaction_count": 9},
    ]
    assert payload["geography"]["district_share"] == {
        "in_district_amount": "7199.98",
        "out_of_district_amount": "0.00",
        "unknown_district_amount": "0.00",
        "share": "1.0000",
        "available": True,
    }
    assert payload["geography"]["geography_mode"] == "statewide"
    assert payload["metadata"]["excluded_geography"] is None
    assert payload["metadata"]["approximate_geography"] is True

    db_conn.rollback()
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(
        db_conn,
        office_name="us_president",
        office_title="President",
        candidate_office="P",
        candidate_fec_id="P0US00077",
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_district"] == []
    assert payload["geography"]["district_share"] == {
        "in_district_amount": None,
        "out_of_district_amount": None,
        "unknown_district_amount": None,
        "share": None,
        "available": False,
    }
    assert payload["metadata"]["excluded_geography"] == "federal_executive"
    assert payload["metadata"]["approximate_geography"] is False
    assert payload["geography"]["geography_mode"] == "state_bars_only"


def test_get_person_contribution_insights_geography_house_uses_in_district_elsewhere_state_out_of_state_and_unknown(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id, committee_id = _seed_stage3_geography_fixture(
        db_conn,
        office_name="us_house",
        office_title="Representative",
        candidate_office="H",
        candidate_fec_id="H0NC03001",
    )
    expected_district_rows = [
        {"label": "In district", "total_amount": Decimal("600.00"), "transaction_count": 1},
        {"label": "Elsewhere in state", "total_amount": Decimal("500.00"), "transaction_count": 1},
        {"label": "Out of state", "total_amount": Decimal("1050.00"), "transaction_count": 5},
        {"label": "Unknown", "total_amount": Decimal("995.00"), "transaction_count": 3},
    ]

    _assert_stage3_direct_sql_rows(
        db_conn,
        committee_id=committee_id,
        office_name="us_house",
        office_state="NC",
        office_district="01",
        expected_district_rows=expected_district_rows,
    )
    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_state"] == _stage3_expected_state_rows()
    assert payload["geography"]["by_district"] == [
        {**row, "total_amount": f"{row['total_amount']:.2f}"} for row in expected_district_rows
    ]
    assert payload["geography"]["geography_mode"] == "district"
    _assert_stage3_geography_denominators(payload["geography"])
    assert payload["geography"]["district_share"] == {
        "in_district_amount": "600.00",
        "out_of_district_amount": "1550.00",
        "unknown_district_amount": "995.00",
        "share": "0.2791",
        "available": True,
    }
    assert payload["metadata"]["approximate_geography"] is True
    assert payload["metadata"]["excluded_geography"] is None
    assert payload["metadata"]["caveats"] == ["missing_zcta_district"]


def test_get_person_contribution_insights_geography_delegate_uses_at_large_district(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id, committee_id = _seed_stage3_geography_fixture(
        db_conn,
        office_name="us_delegate",
        office_title="Delegate",
        candidate_office="H",
        candidate_fec_id="H0NC03002",
        office_district="00",
    )
    expected_district_rows = [
        {"label": "In district", "total_amount": Decimal("600.00"), "transaction_count": 1},
        {"label": "Elsewhere in state", "total_amount": Decimal("500.00"), "transaction_count": 1},
        {"label": "Out of state", "total_amount": Decimal("1050.00"), "transaction_count": 5},
        {"label": "Unknown", "total_amount": Decimal("995.00"), "transaction_count": 3},
    ]

    _assert_stage3_direct_sql_rows(
        db_conn,
        committee_id=committee_id,
        office_name="us_delegate",
        office_state="NC",
        office_district="00",
        expected_district_rows=expected_district_rows,
    )
    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_state"] == _stage3_expected_state_rows()
    assert payload["geography"]["by_district"] == [
        {**row, "total_amount": f"{row['total_amount']:.2f}"} for row in expected_district_rows
    ]
    assert payload["geography"]["geography_mode"] == "district"
    _assert_stage3_geography_denominators(payload["geography"])
    assert payload["metadata"]["approximate_geography"] is True
    assert payload["metadata"]["excluded_geography"] is None
    assert payload["metadata"]["caveats"] == ["missing_zcta_district"]


def test_get_person_contribution_insights_geography_senate_uses_statewide_labels(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id, committee_id = _seed_stage3_geography_fixture(
        db_conn,
        office_name="us_senate",
        office_title="Senator",
        candidate_office="S",
        candidate_fec_id="S0NC03003",
        office_district=None,
    )
    expected_district_rows = [
        {"label": "In state", "total_amount": Decimal("1170.00"), "transaction_count": 3},
        {"label": "Out of state", "total_amount": Decimal("1050.00"), "transaction_count": 5},
        {"label": "Unknown", "total_amount": Decimal("925.00"), "transaction_count": 2},
    ]

    _assert_stage3_direct_sql_rows(
        db_conn,
        committee_id=committee_id,
        office_name="us_senate",
        office_state="NC",
        office_district="",
        expected_district_rows=expected_district_rows,
    )
    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_state"] == _stage3_expected_state_rows()
    assert payload["geography"]["by_district"] == [
        {**row, "total_amount": f"{row['total_amount']:.2f}"} for row in expected_district_rows
    ]
    assert payload["geography"]["geography_mode"] == "statewide"
    _assert_stage3_geography_denominators(payload["geography"])
    assert payload["metadata"]["approximate_geography"] is True
    assert payload["metadata"]["excluded_geography"] is None
    assert payload["metadata"]["caveats"] == []


def test_get_person_contribution_insights_geography_president_returns_top_five_other_and_unknown_state_bars(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id, _committee_id = _seed_stage3_geography_fixture(
        db_conn,
        office_name="us_president",
        office_title="President",
        candidate_office="P",
        candidate_fec_id="P0US03004",
        office_state="US",
        office_district=None,
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_state"] == _stage3_expected_state_rows()
    assert payload["geography"]["by_district"] == []
    assert payload["geography"]["district_share"] == {
        "in_district_amount": None,
        "out_of_district_amount": None,
        "unknown_district_amount": None,
        "share": None,
        "available": False,
    }
    assert payload["geography"]["geography_mode"] == "state_bars_only"
    _assert_stage3_geography_denominators(payload["geography"])
    assert payload["metadata"]["approximate_geography"] is False
    assert payload["metadata"]["excluded_geography"] == "federal_executive"
    assert payload["metadata"]["caveats"] == []


def test_get_person_contribution_insights_geography_invalid_zip_falls_to_unknown_without_polluting_state_rankings(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id, _committee_id = _seed_stage3_geography_fixture(
        db_conn,
        office_name="us_house",
        office_title="Representative",
        candidate_office="H",
        candidate_fec_id="H0NC03005",
    )

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights")

    assert response.status_code == 200
    state_rows = response.json()["geography"]["by_state"]
    assert state_rows == _stage3_expected_state_rows()
    assert "NY" not in {row["label"] for row in state_rows}
    assert state_rows[-1] == {"label": "Unknown", "total_amount": "925.00", "transaction_count": 2}


def test_get_person_contribution_insights_geography_prior_cycle_house_surfaces_current_district_approximation_caveat(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, _candidate_id = _seed_person_contribution_insights_fixture(db_conn)

    response = api_client.get(f"/v1/person/{person_id}/contribution-insights?cycle=2024")

    assert response.status_code == 200
    payload = response.json()
    assert payload["geography"]["by_state"] == [
        {"label": "NC", "total_amount": "350.00", "transaction_count": 3},
        {"label": "VA", "total_amount": "201.00", "transaction_count": 1},
    ]
    assert payload["geography"]["by_district"] == [
        {"label": "In district", "total_amount": "350.00", "transaction_count": 3},
        {"label": "Out of state", "total_amount": "201.00", "transaction_count": 1},
    ]
    assert payload["geography"]["geography_mode"] == "district"
    assert payload["geography"]["classified_amount"] == "551.00"
    assert payload["geography"]["classified_transaction_count"] == 4
    assert payload["geography"]["unknown_amount"] == "0.00"
    assert payload["geography"]["unknown_transaction_count"] == 0
    assert payload["metadata"]["approximate_geography"] is True
    assert payload["metadata"]["excluded_geography"] is None
    assert payload["metadata"]["caveats"] == ["current_district_approximation"]


def test_get_person_contribution_insights_cycle_totals_edge_case_payloads(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    no_candidate = Person(canonical_name="Insights No Candidate")
    insert_person(db_conn, no_candidate)

    response = api_client.get(f"/v1/person/{no_candidate.id}/contribution-insights")

    assert response.status_code == 200
    assert response.json() == {
        "person_id": str(no_candidate.id),
        "has_data": False,
        "metadata": {
            "selected_cycle": 2026,
            "coverage_start_date": "2025-01-01",
            "coverage_end_date": "2026-12-31",
            "available_cycles": [2022, 2024, 2026],
            "cycles_included": [],
            "committee_count": 0,
            "approximate_geography": False,
            "excluded_geography": "no_linked_candidate",
            "caveats": [],
        },
        "monthly_totals": [],
        "itemized_size_buckets": [],
        "dollars_by_size": [],
        "cycle_totals": [],
        "career_totals": {
            "itemized_individual_contribution_amount": "0.00",
            "itemized_transaction_count": 0,
            "unitemized_individual_contribution_amount": "0.00",
            "total_individual_contribution_amount": "0.00",
            "source": "none",
        },
        "geography": {
            "by_state": [],
            "by_district": [],
            "district_share": {
                "in_district_amount": None,
                "out_of_district_amount": None,
                "unknown_district_amount": None,
                "share": None,
                "available": False,
            },
            "geography_mode": "excluded",
            "classified_amount": "0.00",
            "classified_transaction_count": 0,
            "unknown_amount": "0.00",
            "unknown_transaction_count": 0,
        },
        "small_dollar_share": {
            "small_dollar_amount": None,
            "total_contribution_amount": None,
            "share": None,
            "available": False,
        },
    }


def test_get_person_contribution_insights_returns_404_only_for_missing_person(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/person/{uuid4()}/contribution-insights")

    assert response.status_code == 404
    assert response.json() == {"detail": "Person not found"}


def _seed_person_top_donors_second_committee(
    db_conn: psycopg.Connection,
    *,
    candidate_id: UUID,
) -> None:
    """Add a second ACTIVE linked committee with donor rows for top-donors coverage.

    Includes a donor name repeated from the first committee (same name/city/state so it
    sums across committees), a committee-only donor with a non-null city, and an
    ActBlue-style conduit row seeded as a non-IND entity so the qualifying-person
    semantics exclude it from the donor ranking.
    """
    second_committee_id = UUID("d1000000-0000-0000-0000-000000000031")
    second_filing_id = UUID("d1000000-0000-0000-0000-000000000032")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=second_committee_id,
            fec_committee_id="C77770004",
            name="Insights Second Committee",
            state="NC",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("d1000000-0000-0000-0000-000000000033"),
            candidate_id=candidate_id,
            committee_id=second_committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=second_filing_id,
            filing_fec_id="insights-second-filing",
            committee_id=second_committee_id,
        ),
    )
    # Same (name, city, state) as first-committee "Donor 0012" ($200) so the two
    # committees roll up to one ranked donor summed to $500 across two gifts.
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d1000000-0000-0000-0000-000000000034"),
            filing_id=second_filing_id,
            committee_id=second_committee_id,
            transaction_type="15",
            amendment_indicator="N",
            transaction_date=date(2024, 5, 1),
            amount=Decimal("300.00"),
            contributor_name_raw="Donor 0012",
            contributor_entity_type="IND",
            contributor_city=None,
            contributor_state="NC",
            contributor_zip="27709",
        ),
    )
    # Committee-only donor with a non-null city, proving the city field is surfaced.
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d1000000-0000-0000-0000-000000000035"),
            filing_id=second_filing_id,
            committee_id=second_committee_id,
            transaction_type="15",
            amendment_indicator="N",
            transaction_date=date(2024, 5, 2),
            amount=Decimal("150.00"),
            contributor_name_raw="Zeta Donor",
            contributor_entity_type="IND",
            contributor_city="Asheville",
            contributor_state="NC",
            contributor_zip="28801",
        ),
    )
    # ActBlue-style conduit row: non-IND entity, excluded by the qualifying-person CTE.
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d1000000-0000-0000-0000-000000000036"),
            filing_id=second_filing_id,
            committee_id=second_committee_id,
            transaction_type="15",
            amendment_indicator="N",
            transaction_date=date(2024, 5, 3),
            amount=Decimal("5000.00"),
            contributor_name_raw="ActBlue",
            contributor_entity_type="PAC",
            contributor_city="Somerville",
            contributor_state="MA",
            contributor_zip="02144",
        ),
    )


def _seed_person_top_employers_rows(
    db_conn: psycopg.Connection,
    *,
    candidate_id: UUID,
) -> None:
    first_committee_id = UUID("d1000000-0000-0000-0000-000000000004")
    first_filing_id = UUID("d1000000-0000-0000-0000-000000000006")
    second_committee_id = UUID("d1000000-0000-0000-0000-000000000041")
    second_filing_id = UUID("d1000000-0000-0000-0000-000000000042")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=second_committee_id,
            fec_committee_id="C77770005",
            name="Insights Employer Committee",
            state="NC",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("d1000000-0000-0000-0000-000000000043"),
            candidate_id=candidate_id,
            committee_id=second_committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=second_filing_id,
            filing_fec_id="insights-employer-filing",
            committee_id=second_committee_id,
        ),
    )

    # A superseded source record: any receipt backed by it must be excluded from
    # the qualifying-transactions anti-join, exactly like the live source-record
    # supersession semantics. This pins the anti-join on the top-employers path
    # (which shares the person-insights qualifying CTE) so a rewrite of the
    # LEFT JOIN + OR guard cannot silently start counting superseded receipts.
    employer_data_source = insert_data_source_for_test(
        db_conn, jurisdiction="federal/fec", name_suffix="insights-employer"
    )
    employer_superseding_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("d1000000-0000-0000-0000-000000000053"),
        data_source_id=employer_data_source.id,
        source_record_key="employer-superseding",
        source_url="https://example.org/record/employer-superseding",
        pull_date=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
    )
    employer_superseded_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("d1000000-0000-0000-0000-000000000054"),
        data_source_id=employer_data_source.id,
        source_record_key="employer-superseded",
        source_url="https://example.org/record/employer-superseded",
        pull_date=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        superseded_by=employer_superseding_source.id,
    )

    def insert_employer_receipt(
        transaction_id: str,
        amount: str,
        employer: str | None,
        *,
        second_committee: bool = False,
        entity_type: str = "IND",
        is_memo: bool = False,
        source_record_id: UUID | None = None,
    ) -> None:
        committee_id = second_committee_id if second_committee else first_committee_id
        filing_id = second_filing_id if second_committee else first_filing_id
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=UUID(transaction_id),
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="15",
                amendment_indicator="N",
                transaction_date=date(2024, 6, 1),
                amount=Decimal(amount),
                contributor_name_raw=f"Employer Donor {transaction_id[-4:]}",
                contributor_entity_type=entity_type,
                contributor_employer=employer,
                contributor_state="NC",
                contributor_zip="27701",
                is_memo=is_memo,
                memo_code="X" if is_memo else None,
                source_record_id=source_record_id,
            ),
        )

    employer_receipts: list[tuple[str, str, str | None, bool, str, bool]] = [
        ("d1000000-0000-0000-0000-000000000044", "100.00", "ACME CORP", False, "IND", False),
        ("d1000000-0000-0000-0000-000000000045", "150.00", "ACME CORP", True, "IND", False),
        ("d1000000-0000-0000-0000-000000000046", "50.00", "acme  corp ", True, "IND", False),
        ("d1000000-0000-0000-0000-000000000047", "40.00", "", False, "IND", False),
        ("d1000000-0000-0000-0000-000000000048", "30.00", None, True, "IND", False),
        ("d1000000-0000-0000-0000-000000000049", "20.00", "RETIRED", True, "IND", False),
        ("d1000000-0000-0000-0000-000000000052", "15.00", "SELF EMPLOYED", True, "IND", False),
        ("d1000000-0000-0000-0000-000000000050", "5000.00", "ACTBLUE", True, "PAC", False),
        ("d1000000-0000-0000-0000-000000000051", "700.00", "EXCLUDED EMPLOYER", True, "IND", True),
    ]
    for transaction_id, amount, employer, second_committee, entity_type, is_memo in employer_receipts:
        insert_employer_receipt(
            transaction_id,
            amount,
            employer,
            second_committee=second_committee,
            entity_type=entity_type,
            is_memo=is_memo,
        )

    # ACME CORP receipt backed by a superseded source record — must NOT be counted.
    insert_employer_receipt(
        "d1000000-0000-0000-0000-000000000055",
        "500.00",
        "ACME CORP",
        second_committee=True,
        source_record_id=employer_superseded_source.id,
    )


def test_get_person_top_donors_ranks_summed_donors_across_linked_committees(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    _seed_person_top_donors_second_committee(db_conn, candidate_id=candidate_id)

    response = api_client.get(f"/v1/person/{person_id}/top-donors")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "Donor 0039", "total_amount": "30.00", "transaction_count": 1, "city": None, "state": "NC"},
        {"name": "Donor 0040", "total_amount": "19.00", "transaction_count": 1, "city": None, "state": "NC"},
    ]


def test_get_person_top_donors_honors_limit(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, candidate_id = _seed_person_contribution_insights_fixture(db_conn)
    _seed_person_top_donors_second_committee(db_conn, candidate_id=candidate_id)

    response = api_client.get(f"/v1/person/{person_id}/top-donors?limit=2")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "Donor 0039", "total_amount": "30.00", "transaction_count": 1, "city": None, "state": "NC"},
        {"name": "Donor 0040", "total_amount": "19.00", "transaction_count": 1, "city": None, "state": "NC"},
    ]


def test_get_person_top_donors_returns_empty_for_person_without_linked_committees(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    no_candidate = Person(canonical_name="Top Donors No Candidate")
    insert_person(db_conn, no_candidate)

    response = api_client.get(f"/v1/person/{no_candidate.id}/top-donors")

    assert response.status_code == 200
    assert response.json() == []


def test_get_person_top_donors_returns_404_only_for_missing_person(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/person/{uuid4()}/top-donors")

    assert response.status_code == 404
    assert response.json() == {"detail": "Person not found"}


def test_get_person_top_employers_ranks_summed_employers_across_linked_committees(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, candidate_id = _seed_person_contribution_insights_fixture(db_conn, include_itemized_receipts=False)
    _seed_person_top_employers_rows(db_conn, candidate_id=candidate_id)

    response = api_client.get(f"/v1/person/{person_id}/top-employers?cycle=2024")

    assert response.status_code == 200
    assert response.json() == [
        {"employer": "ACME CORP", "total_amount": "300.00", "transaction_count": 3},
        {"employer": "Unclassified / not provided", "total_amount": "105.00", "transaction_count": 4},
    ]


def test_get_person_top_employers_honors_limit(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_id, candidate_id = _seed_person_contribution_insights_fixture(db_conn, include_itemized_receipts=False)
    _seed_person_top_employers_rows(db_conn, candidate_id=candidate_id)

    response = api_client.get(f"/v1/person/{person_id}/top-employers?limit=1&cycle=2024")

    assert response.status_code == 200
    assert response.json() == [{"employer": "ACME CORP", "total_amount": "300.00", "transaction_count": 3}]


def test_get_person_top_employers_returns_empty_for_person_without_linked_committees(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    no_candidate = Person(canonical_name="Top Employers No Candidate")
    insert_person(db_conn, no_candidate)

    response = api_client.get(f"/v1/person/{no_candidate.id}/top-employers")

    assert response.status_code == 200
    assert response.json() == []


def test_get_person_top_employers_returns_404_only_for_missing_person(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/person/{uuid4()}/top-employers")

    assert response.status_code == 404
    assert response.json() == {"detail": "Person not found"}


def test_get_committee_returns_direct_provenance(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    organization = Organization(canonical_name="Committee Org")
    insert_organization(db_conn, organization)

    data_source = insert_data_source_for_test(db_conn, jurisdiction="federal/fec", name_suffix=str(uuid4()))
    source_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000901"),
        data_source_id=data_source.id,
        source_record_key="committee-direct",
        source_url="https://example.org/record/committee-direct",
        pull_date=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
    )

    committee_id = UUID("00000000-0000-0000-0000-000000000900")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C12345678",
            name="Civibus Committee",
            organization_id=organization.id,
            source_record_id=source_record.id,
            committee_type="P",
            committee_designation="A",
            party="DEM",
            state="NC",
            city="Durham",
            zip_code="27701",
            treasurer_name="Alex Treasurer",
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(committee_id)
    assert payload["fec_committee_id"] == "C12345678"
    assert payload["name"] == "Civibus Committee"
    assert payload["organization_id"] == str(organization.id)
    assert payload["committee_type"] == "P"
    assert payload["committee_designation"] == "A"
    assert payload["party"] == "DEM"
    assert payload["state"] == "NC"
    assert payload["city"] == "Durham"
    assert payload["zip_code"] == "27701"
    assert payload["treasurer_name"] == "Alex Treasurer"
    assert payload["sources"] == [
        {
            "domain": "campaign_finance",
            "jurisdiction": "federal/fec",
            "data_source_name": data_source.name,
            "data_source_url": data_source.source_url,
            "source_record_key": "committee-direct",
            "record_url": "https://example.org/record/committee-direct",
            "pull_date": "2026-03-16T12:00:00Z",
        }
    ]
    assert "created_at" not in payload
    assert "updated_at" not in payload


def test_get_committee_falls_back_to_organization_entity_source_when_row_source_missing(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    organization = Organization(canonical_name="Fallback Committee Org")
    insert_organization(db_conn, organization)

    data_source = insert_data_source_for_test(db_conn, jurisdiction="state/co", name_suffix=str(uuid4()))
    newer_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000911"),
        data_source_id=data_source.id,
        source_record_key="committee-fallback-newer",
        source_url="https://example.org/record/committee-fallback-newer",
        pull_date=datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc),
    )
    tie_break_first = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000001"),
        data_source_id=data_source.id,
        source_record_key="committee-fallback-tie-a",
        source_url="https://example.org/record/committee-fallback-tie-a",
        pull_date=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
    )
    tie_break_second = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000002"),
        data_source_id=data_source.id,
        source_record_key="committee-fallback-tie-b",
        source_url="https://example.org/record/committee-fallback-tie-b",
        pull_date=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
    )
    insert_entity_source(db_conn, "organization", organization.id, newer_record.id, "committee")
    insert_entity_source(db_conn, "organization", organization.id, newer_record.id, "recipient")
    insert_entity_source(db_conn, "organization", organization.id, tie_break_first.id, "committee")
    insert_entity_source(db_conn, "organization", organization.id, tie_break_second.id, "committee")

    committee_id = UUID("00000000-0000-0000-0000-000000000910")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C12345679",
            name="Fallback Committee",
            organization_id=organization.id,
            source_record_id=None,
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}")

    assert response.status_code == 200
    payload = response.json()
    assert [source["source_record_key"] for source in payload["sources"]] == [
        "committee-fallback-newer",
        "committee-fallback-tie-a",
        "committee-fallback-tie-b",
    ]
    assert all(
        set(source)
        == {
            "domain",
            "jurisdiction",
            "data_source_name",
            "data_source_url",
            "source_record_key",
            "record_url",
            "pull_date",
        }
        for source in payload["sources"]
    )
    assert payload["sources"] == [
        {
            "domain": "campaign_finance",
            "jurisdiction": "state/co",
            "data_source_name": data_source.name,
            "data_source_url": data_source.source_url,
            "source_record_key": "committee-fallback-newer",
            "record_url": "https://example.org/record/committee-fallback-newer",
            "pull_date": "2026-03-16T10:00:00Z",
        },
        {
            "domain": "campaign_finance",
            "jurisdiction": "state/co",
            "data_source_name": data_source.name,
            "data_source_url": data_source.source_url,
            "source_record_key": "committee-fallback-tie-a",
            "record_url": "https://example.org/record/committee-fallback-tie-a",
            "pull_date": "2026-03-15T10:00:00Z",
        },
        {
            "domain": "campaign_finance",
            "jurisdiction": "state/co",
            "data_source_name": data_source.name,
            "data_source_url": data_source.source_url,
            "source_record_key": "committee-fallback-tie-b",
            "record_url": "https://example.org/record/committee-fallback-tie-b",
            "pull_date": "2026-03-15T10:00:00Z",
        },
    ]


def test_get_committee_unions_direct_and_entity_sources_without_duplicates(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    organization = Organization(canonical_name="Union Source Committee Org")
    insert_organization(db_conn, organization)

    data_source = insert_data_source_for_test(db_conn, jurisdiction="state/ga", name_suffix=str(uuid4()))
    direct_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000921"),
        data_source_id=data_source.id,
        source_record_key="committee-direct-older",
        source_url="https://example.org/record/committee-direct-older",
        pull_date=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc),
    )
    newer_entity_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000922"),
        data_source_id=data_source.id,
        source_record_key="committee-entity-newer",
        source_url="https://example.org/record/committee-entity-newer",
        pull_date=datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc),
    )
    insert_entity_source(db_conn, "organization", organization.id, direct_source.id, "committee")
    insert_entity_source(db_conn, "organization", organization.id, newer_entity_source.id, "committee")

    committee_id = UUID("00000000-0000-0000-0000-000000000920")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C12345680",
            name="Union Source Committee",
            organization_id=organization.id,
            source_record_id=direct_source.id,
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}")

    assert response.status_code == 200
    payload = response.json()
    assert [source["source_record_key"] for source in payload["sources"]] == [
        "committee-entity-newer",
        "committee-direct-older",
    ]


def test_get_committee_returns_404_for_missing_committee(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/committees/{uuid4()}")

    assert response.status_code == 404


def test_get_committee_rejects_malformed_uuid(api_client: TestClient) -> None:
    response = api_client.get("/v1/committees/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "committee_id"]


def test_get_candidate_returns_direct_provenance(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Candidate Person")
    insert_person(db_conn, person)

    committee_id = UUID("00000000-0000-0000-0000-000000000931")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C12345681",
            name="Principal Committee",
            organization_id=None,
            source_record_id=None,
        ),
    )

    data_source = insert_data_source_for_test(db_conn, jurisdiction="federal/fec", name_suffix=str(uuid4()))
    source_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000932"),
        data_source_id=data_source.id,
        source_record_key="candidate-direct",
        source_url="https://example.org/record/candidate-direct",
        pull_date=datetime(2026, 3, 16, 9, 30, tzinfo=timezone.utc),
    )

    candidate_id = UUID("00000000-0000-0000-0000-000000000930")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC01001",
            name="Jane Candidate",
            office="H",
            person_id=person.id,
            principal_committee_id=committee_id,
            source_record_id=source_record.id,
            party="DEM",
            state="NC",
            district="01",
            incumbent_challenge="I",
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(candidate_id)
    assert payload["fec_candidate_id"] == "H0NC01001"
    assert payload["name"] == "Jane Candidate"
    assert payload["person_id"] == str(person.id)
    assert payload["party"] == "DEM"
    assert payload["office"] == "H"
    assert payload["state"] == "NC"
    assert payload["district"] == "01"
    assert payload["incumbent_challenge"] == "I"
    assert payload["principal_committee_id"] == str(committee_id)
    assert payload["sources"] == [
        {
            "domain": "campaign_finance",
            "jurisdiction": "federal/fec",
            "data_source_name": data_source.name,
            "data_source_url": data_source.source_url,
            "source_record_key": "candidate-direct",
            "record_url": "https://example.org/record/candidate-direct",
            "pull_date": "2026-03-16T09:30:00Z",
        }
    ]
    assert "created_at" not in payload
    assert "updated_at" not in payload


def test_get_candidate_falls_back_to_person_entity_source_when_row_source_missing(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Fallback Candidate Person")
    insert_person(db_conn, person)

    data_source = insert_data_source_for_test(db_conn, jurisdiction="state/nc", name_suffix=str(uuid4()))
    newer_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000941"),
        data_source_id=data_source.id,
        source_record_key="candidate-fallback-newer",
        source_url="https://example.org/record/candidate-fallback-newer",
        pull_date=datetime(2026, 3, 16, 8, 0, tzinfo=timezone.utc),
    )
    older_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000942"),
        data_source_id=data_source.id,
        source_record_key="candidate-fallback-older",
        source_url="https://example.org/record/candidate-fallback-older",
        pull_date=datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc),
    )
    insert_entity_source(db_conn, "person", person.id, newer_record.id, "candidate")
    insert_entity_source(db_conn, "person", person.id, newer_record.id, "donor")
    insert_entity_source(db_conn, "person", person.id, older_record.id, "candidate")

    candidate_id = UUID("00000000-0000-0000-0000-000000000940")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC01002",
            name="Fallback Candidate",
            office="H",
            person_id=person.id,
            principal_committee_id=None,
            source_record_id=None,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}")

    assert response.status_code == 200
    payload = response.json()
    assert [source["source_record_key"] for source in payload["sources"]] == [
        "candidate-fallback-newer",
        "candidate-fallback-older",
    ]


def test_get_candidate_unions_direct_and_entity_sources_without_duplicates(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Union Source Candidate Person")
    insert_person(db_conn, person)

    data_source = insert_data_source_for_test(db_conn, jurisdiction="state/ga", name_suffix=str(uuid4()))
    direct_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000943"),
        data_source_id=data_source.id,
        source_record_key="candidate-direct-older",
        source_url="https://example.org/record/candidate-direct-older",
        pull_date=datetime(2026, 3, 10, 8, 0, tzinfo=timezone.utc),
    )
    newer_entity_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000944"),
        data_source_id=data_source.id,
        source_record_key="candidate-entity-newer",
        source_url="https://example.org/record/candidate-entity-newer",
        pull_date=datetime(2026, 3, 16, 8, 0, tzinfo=timezone.utc),
    )
    insert_entity_source(db_conn, "person", person.id, direct_source.id, "candidate")
    insert_entity_source(db_conn, "person", person.id, newer_entity_source.id, "candidate")

    candidate_id = UUID("00000000-0000-0000-0000-000000000945")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC01003",
            name="Union Source Candidate",
            office="H",
            person_id=person.id,
            source_record_id=direct_source.id,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}")

    assert response.status_code == 200
    payload = response.json()
    assert [source["source_record_key"] for source in payload["sources"]] == [
        "candidate-entity-newer",
        "candidate-direct-older",
    ]


def test_get_candidate_returns_404_for_missing_candidate(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/candidates/{uuid4()}")

    assert response.status_code == 404


def test_get_candidate_rejects_malformed_uuid(api_client: TestClient) -> None:
    response = api_client.get("/v1/candidates/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "candidate_id"]


def test_list_candidates_filters_by_person_id(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person_a = Person(canonical_name="Filtered Person A")
    person_b = Person(canonical_name="Filtered Person B")
    insert_person(db_conn, person_a)
    insert_person(db_conn, person_b)

    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("91000000-0000-0000-0000-000000000001"),
            fec_candidate_id="H0NC09001",
            name="Candidate For A",
            office="H",
            person_id=person_a.id,
            state="NC",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("92000000-0000-0000-0000-000000000001"),
            fec_candidate_id="H0NC09002",
            name="Candidate For B",
            office="H",
            person_id=person_b.id,
            state="NC",
        ),
    )

    response = api_client.get(f"/v1/candidates?person_id={person_a.id}&limit=10&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_next"] is False
    assert payload["offset"] == 0
    assert payload["limit"] == 10
    assert [row["id"] for row in payload["items"]] == ["91000000-0000-0000-0000-000000000001"]
    assert payload["items"][0]["person_id"] == str(person_a.id)


def test_get_candidate_summary_aggregates_multi_committee_totals(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("b0000000-0000-0000-0000-000000000101")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02001",
            name="Multi Committee Candidate",
            office="H",
            source_record_id=None,
        ),
    )

    committee_a_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("b1111111-1111-1111-1111-111111111111"),
        committee_name="Multi Committee A",
        fec_committee_id="C99000111",
        jurisdiction="state/nc",
        pull_date=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
    )
    committee_b_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("b2222222-2222-2222-2222-222222222222"),
        committee_name="Multi Committee B",
        fec_committee_id="C99000112",
        jurisdiction="state/co",
        pull_date=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
    )

    insert_summary_transaction(
        db_conn,
        context=committee_a_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000121"),
        transaction_type="15",
        amount=Decimal("100.00"),
        source_record_id=committee_a_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=committee_a_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000122"),
        transaction_type="24A",
        amount=Decimal("30.00"),
        source_record_id=committee_a_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=committee_b_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000123"),
        transaction_type="15",
        amount=Decimal("40.00"),
        source_record_id=committee_b_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=committee_b_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000124"),
        transaction_type="24A",
        amount=Decimal("10.00"),
        source_record_id=committee_b_context.source_record_id,
    )

    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000131"),
            candidate_id=candidate_id,
            committee_id=committee_a_context.committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
            source_record_id=None,
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000132"),
            candidate_id=candidate_id,
            committee_id=committee_b_context.committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="A",
            source_record_id=None,
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"] == str(candidate_id)
    assert payload["candidate_name"] == "Multi Committee Candidate"
    assert payload["total_raised"] == "140.00"
    assert payload["total_spent"] == "40.00"
    assert payload["net"] == "100.00"
    assert payload["transaction_count"] == 4
    assert [row["committee_id"] for row in payload["committees"]] == [
        str(committee_a_context.committee_id),
        str(committee_b_context.committee_id),
    ]
    assert payload["committees"][0]["committee_name"] == "Multi Committee A"
    assert payload["committees"][0]["total_raised"] == "100.00"
    assert payload["committees"][0]["total_spent"] == "30.00"
    assert payload["committees"][0]["net"] == "70.00"
    assert payload["committees"][0]["transaction_count"] == 2
    assert payload["committees"][0]["jurisdiction"] == "state/nc"
    assert payload["committees"][0]["data_through"] == "2026-03-20T12:00:00Z"
    assert payload["committees"][1]["committee_name"] == "Multi Committee B"
    assert payload["committees"][1]["total_raised"] == "40.00"
    assert payload["committees"][1]["total_spent"] == "10.00"
    assert payload["committees"][1]["net"] == "30.00"
    assert payload["committees"][1]["transaction_count"] == 2
    assert payload["committees"][1]["jurisdiction"] == "state/co"
    assert payload["committees"][1]["data_through"] == "2026-03-21T12:00:00Z"
    assert payload["summary_source"] == "derived"
    assert payload["cash_on_hand"] is None


def test_fetch_candidate_summary_reports_gross_receipt_source_composition(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("b0000000-0000-0000-0000-000000000701")
    committee_a_id = UUID("b7111111-1111-1111-1111-111111111111")
    committee_b_id = UUID("b7222222-2222-2222-2222-222222222222")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02701",
            name="Receipt Source Candidate",
            office="H",
        ),
    )
    for committee_id, fec_committee_id, committee_name, link_id in (
        (committee_a_id, "C99000711", "Receipt Committee A", UUID("b0000000-0000-0000-0000-000000000711")),
        (committee_b_id, "C99000722", "Receipt Committee B", UUID("b0000000-0000-0000-0000-000000000722")),
    ):
        insert_committee_row(
            db_conn,
            CommitteeRowSeed(id=committee_id, fec_committee_id=fec_committee_id, name=committee_name),
        )
        insert_candidate_committee_link_row(
            db_conn,
            CandidateCommitteeLinkSeed(
                id=link_id,
                candidate_id=candidate_id,
                committee_id=committee_id,
                valid_period="[2025-01-01,2027-01-01)",
                candidate_election_year=2026,
                fec_election_year=2026,
            ),
        )

    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_a_id,
            cycle=2026,
            total_receipts=Decimal("1000.00"),
            total_disbursements=Decimal("300.00"),
            cash_on_hand=Decimal("700.00"),
            individual_contributions=Decimal("500.00"),
            other_committee_contributions=Decimal("100.00"),
            party_committee_contributions=Decimal("50.00"),
            candidate_contributions=Decimal("75.00"),
            candidate_loans=Decimal("25.00"),
            transfers_from_other_authorized_committees=Decimal("100.00"),
            debts_owed_by_committee=Decimal("80.00"),
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2026, 12, 31),
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_b_id,
            cycle=2026,
            total_receipts=Decimal("500.00"),
            total_disbursements=Decimal("200.00"),
            cash_on_hand=Decimal("300.00"),
            individual_contributions=Decimal("200.00"),
            other_committee_contributions=Decimal("25.00"),
            party_committee_contributions=Decimal("25.00"),
            candidate_contributions=Decimal("10.00"),
            candidate_loans=Decimal("15.00"),
            transfers_from_other_authorized_committees=Decimal("50.00"),
            debts_owed_by_committee=Decimal("20.00"),
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2026, 12, 31),
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_source"] == "derived"
    assert payload["total_raised"] == "1500.00"
    assert payload["total_spent"] == "500.00"
    assert payload["selected_cycle_coverage_complete"] is True
    assert payload["can_render_share"] is True
    assert payload["receipt_source_caveats"] == []
    assert payload["debts_owed_by_committee"] == "100.00"
    assert payload["receipt_source_composition"] == [
        {"label": "Individual contributions", "total_amount": "700.00", "source": "fec_committee_summary"},
        {"label": "PAC/other committee contributions", "total_amount": "125.00", "source": "fec_committee_summary"},
        {"label": "Party committee contributions", "total_amount": "75.00", "source": "fec_committee_summary"},
        {"label": "Candidate funding", "total_amount": "125.00", "source": "fec_committee_summary"},
        {
            "label": "Transfers from other authorized committees",
            "total_amount": "150.00",
            "source": "fec_committee_summary",
        },
        {"label": "Other receipts", "total_amount": "325.00", "source": "fec_committee_summary"},
    ]


def test_fetch_candidate_summary_selected_cycle_metrics_report_completeness_debts_and_provenance(
    db_conn: psycopg.Connection,
) -> None:
    candidate_id, _committee_a_id, _committee_b_id = _seed_stage3_receipt_source_candidate(db_conn)

    payload = fetch_candidate_summary(db_conn, candidate_id, "Stage 3 Receipt Candidate")

    assert payload is not None
    assert payload["selected_cycle"] == 2026
    assert payload["coverage_start_date"] == date(2025, 1, 1)
    assert payload["coverage_end_date"] == date(2026, 12, 31)
    assert payload["available_cycles"] == [2022, 2024, 2026]
    assert payload["summary_source"] == "derived"
    assert payload["total_raised"] == Decimal("1500.00")
    assert payload["total_spent"] == Decimal("500.00")
    assert payload["net"] == Decimal("1000.00")
    assert payload["selected_cycle_coverage_complete"] is True
    assert payload["can_render_share"] is True
    assert payload["receipt_source_caveats"] == []
    assert payload["debts_owed_by_committee"] == Decimal("100.00")
    assert [
        {**component, "total_amount": f"{component['total_amount']:.2f}"}
        for component in payload["receipt_source_composition"]
    ] == _expected_receipt_source_composition()
    labels = {component["label"] for component in payload["receipt_source_composition"]}
    assert "Refunds" not in labels
    assert "Loan repayments" not in labels


def test_get_candidate_summary_exposes_selected_cycle_and_available_cycles(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id, _committee_a_id, _committee_b_id = _seed_stage3_receipt_source_candidate(db_conn)

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary?cycle=2026")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_cycle"] == 2026
    assert payload["coverage_start_date"] == "2025-01-01"
    assert payload["coverage_end_date"] == "2026-12-31"
    assert payload["available_cycles"] == [2022, 2024, 2026]
    assert payload["receipt_source_composition"] == _expected_receipt_source_composition()
    assert {component["source"] for component in payload["receipt_source_composition"]} == {"fec_committee_summary"}
    assert payload["debts_owed_by_committee"] == "100.00"


def test_get_candidate_summary_receipt_source_caveats_follow_coverage_and_reconciliation(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id, _committee_a_id, committee_b_id = _seed_stage3_receipt_source_candidate(db_conn)
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE cf.committee_summary
            SET coverage_end_date = %s
            WHERE committee_id = %s
              AND cycle = 2026
            """,
            (date(2026, 6, 30), committee_b_id),
        )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_cycle_coverage_complete"] is False
    assert payload["can_render_share"] is False
    assert payload["receipt_source_composition"] == []
    assert payload["receipt_source_caveats"] == [
        "missing_committee_summary",
        "incomplete_committee_summary_coverage",
    ]
    assert payload["debts_owed_by_committee"] is None


def test_fetch_candidate_summary_disables_receipt_source_share_for_incomplete_or_nonreconciling_summaries(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("b0000000-0000-0000-0000-000000000801")
    committee_id = UUID("b8111111-1111-1111-1111-111111111111")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02801",
            name="Negative Receipt Source Candidate",
            office="H",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_id, fec_committee_id="C99000811", name="Negative Receipt Committee"),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000811"),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2025-01-01,2027-01-01)",
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=Decimal("100.00"),
            total_disbursements=Decimal("0.00"),
            individual_contributions=Decimal("125.00"),
            other_committee_contributions=Decimal("0.00"),
            party_committee_contributions=Decimal("0.00"),
            candidate_contributions=Decimal("0.00"),
            candidate_loans=Decimal("0.00"),
            transfers_from_other_authorized_committees=Decimal("0.00"),
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2026, 12, 31),
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_cycle_coverage_complete"] is True
    assert payload["can_render_share"] is False
    assert payload["receipt_source_composition"] == []
    assert payload["receipt_source_caveats"] == ["negative_receipt_source_component"]
    assert payload["debts_owed_by_committee"] == "0.00"


def test_get_candidate_summary_uses_official_weball_totals_when_populated(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Stage 3 contract: when cf.candidate has weball totals, those win over derived sums."""
    candidate_id = UUID("b0000000-0000-0000-0000-000000000501")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02501",
            name="Official Totals Candidate",
            office="H",
            total_receipts=Decimal("9000.00"),
            total_disbursements=Decimal("3500.00"),
            cash_on_hand=Decimal("5500.00"),
            summary_coverage_end_date=date(2026, 12, 31),
        ),
    )

    # Link a committee whose derived totals would otherwise win.
    committee_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("b5111111-1111-1111-1111-111111111111"),
        committee_name="Official Totals Committee",
        fec_committee_id="C99000501",
    )
    insert_summary_transaction(
        db_conn,
        context=committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000521"),
        transaction_type="15",
        amount=Decimal("100.00"),
        source_record_id=committee_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000522"),
        transaction_type="24A",
        amount=Decimal("40.00"),
        source_record_id=committee_context.source_record_id,
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000531"),
            candidate_id=candidate_id,
            committee_id=committee_context.committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
            source_record_id=None,
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_source"] == "fec_weball"
    # Official totals win; net = receipts - disbursements.
    assert payload["total_raised"] == "9000.00"
    assert payload["total_spent"] == "3500.00"
    assert payload["net"] == "5500.00"
    assert payload["cash_on_hand"] == "5500.00"
    # Committee detail is still returned for downstream display, with its derived totals intact.
    assert [row["committee_id"] for row in payload["committees"]] == [
        str(committee_context.committee_id),
    ]
    assert payload["committees"][0]["total_raised"] == "100.00"
    assert payload["committees"][0]["total_spent"] == "40.00"


def test_get_candidate_summary_uses_cycle_matching_principal_committee_fallback(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _person_id, candidate_id, committee_id = _seed_principal_committee_fallback_fixture(db_conn)

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary?cycle=2024")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"] == str(candidate_id)
    assert payload["candidate_name"] == "Principal Fallback Candidate"
    assert payload["selected_cycle"] == 2024
    assert payload["coverage_start_date"] == "2023-01-01"
    assert payload["coverage_end_date"] == "2024-12-31"
    assert payload["available_cycles"] == [2022, 2024, 2026]
    assert payload["summary_source"] == "fec_weball"
    assert payload["total_raised"] == "1234.00"
    assert payload["total_spent"] == "400.00"
    assert payload["net"] == "834.00"
    assert payload["cash_on_hand"] == "834.00"
    assert payload["candidate_contrib"] == "75.00"
    assert payload["candidate_loans"] == "25.00"
    assert payload["candidate_loan_repay"] == "10.00"
    assert payload["net_self_funding"] == "90.00"
    assert payload["transaction_count"] == 3
    assert payload["itemized_transaction_count"] == 3
    assert len(payload["committees"]) == 1
    assert payload["committees"][0]["committee_id"] == str(committee_id)
    assert payload["committees"][0]["committee_name"] == "Principal Fallback Committee"
    assert payload["committees"][0]["total_raised"] == "1234.00"
    assert payload["committees"][0]["total_spent"] == "400.00"
    assert payload["committees"][0]["transaction_count"] == 3
    assert payload["committees"][0]["summary_source"] == "fec_committee_summary"
    assert payload["receipt_source_composition"] == [
        {"label": "Individual contributions", "total_amount": "800.00", "source": "fec_committee_summary"},
        {"label": "PAC/other committee contributions", "total_amount": "200.00", "source": "fec_committee_summary"},
        {"label": "Party committee contributions", "total_amount": "50.00", "source": "fec_committee_summary"},
        {"label": "Candidate funding", "total_amount": "100.00", "source": "fec_committee_summary"},
        {
            "label": "Transfers from other authorized committees",
            "total_amount": "34.00",
            "source": "fec_committee_summary",
        },
        {"label": "Other receipts", "total_amount": "50.00", "source": "fec_committee_summary"},
    ]
    receipt_denominator = sum(Decimal(row["total_amount"]) for row in payload["receipt_source_composition"])
    assert receipt_denominator == Decimal(payload["total_raised"])
    assert payload["selected_cycle_coverage_complete"] is True
    assert payload["can_render_share"] is True
    assert payload["receipt_source_caveats"] == []
    assert payload["debts_owed_by_committee"] == "33.00"


def test_get_candidate_summary_handles_production_shape_missing_candidate_self_funding_columns(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _person_id, candidate_id, committee_id = _seed_principal_committee_fallback_fixture(
        db_conn,
        row_shape="production_missing_self_funding_columns",
    )

    selected_cycle_response = api_client.get(f"/v1/candidates/{candidate_id}/summary?cycle=2024")
    default_cycle_response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert selected_cycle_response.status_code == 200
    selected_cycle_payload = selected_cycle_response.json()
    assert selected_cycle_payload["candidate_id"] == str(candidate_id)
    assert selected_cycle_payload["candidate_name"] == "Principal Fallback Candidate"
    assert selected_cycle_payload["selected_cycle"] == 2024
    assert selected_cycle_payload["coverage_start_date"] == "2023-01-01"
    assert selected_cycle_payload["coverage_end_date"] == "2024-12-31"
    assert selected_cycle_payload["available_cycles"] == [2022, 2024, 2026]
    assert selected_cycle_payload["summary_source"] == "derived"
    assert selected_cycle_payload["total_raised"] == "0.00"
    assert selected_cycle_payload["total_spent"] == "0.00"
    assert selected_cycle_payload["net"] == "0.00"
    assert selected_cycle_payload["cash_on_hand"] is None
    assert selected_cycle_payload["candidate_contrib"] is None
    assert selected_cycle_payload["candidate_loans"] is None
    assert selected_cycle_payload["candidate_loan_repay"] is None
    assert selected_cycle_payload["net_self_funding"] is None
    assert selected_cycle_payload["transaction_count"] == 0
    assert selected_cycle_payload["itemized_transaction_count"] == 0
    assert selected_cycle_payload["committees"] == []
    assert selected_cycle_payload["receipt_source_composition"] == []
    assert selected_cycle_payload["selected_cycle_coverage_complete"] is False
    assert selected_cycle_payload["can_render_share"] is False
    assert selected_cycle_payload["receipt_source_caveats"] == ["missing_committee_summary"]
    assert selected_cycle_payload["debts_owed_by_committee"] is None

    assert default_cycle_response.status_code == 200
    default_cycle_payload = default_cycle_response.json()
    assert default_cycle_payload["candidate_id"] == str(candidate_id)
    assert default_cycle_payload["candidate_name"] == "Principal Fallback Candidate"
    assert default_cycle_payload["selected_cycle"] == 2026
    assert default_cycle_payload["coverage_start_date"] == "2025-01-01"
    assert default_cycle_payload["coverage_end_date"] == "2026-12-31"
    assert default_cycle_payload["available_cycles"] == [2022, 2024, 2026]
    assert default_cycle_payload["summary_source"] == "derived"
    assert default_cycle_payload["total_raised"] == "2222.00"
    assert default_cycle_payload["total_spent"] == "777.00"
    assert default_cycle_payload["net"] == "1445.00"
    assert default_cycle_payload["cash_on_hand"] is None
    assert default_cycle_payload["candidate_contrib"] is None
    assert default_cycle_payload["candidate_loans"] is None
    assert default_cycle_payload["candidate_loan_repay"] is None
    assert default_cycle_payload["net_self_funding"] is None
    assert default_cycle_payload["transaction_count"] == 2
    assert default_cycle_payload["itemized_transaction_count"] == 2
    assert [row["committee_id"] for row in default_cycle_payload["committees"]] == [str(committee_id)]
    assert default_cycle_payload["committees"][0]["committee_name"] == "Principal Fallback Committee"
    assert default_cycle_payload["committees"][0]["total_raised"] == "2222.00"
    assert default_cycle_payload["committees"][0]["total_spent"] == "777.00"
    assert default_cycle_payload["committees"][0]["net"] == "1445.00"
    assert default_cycle_payload["committees"][0]["transaction_count"] == 2
    assert default_cycle_payload["committees"][0]["summary_source"] == "fec_committee_summary"
    assert default_cycle_payload["receipt_source_composition"] == []
    assert default_cycle_payload["selected_cycle_coverage_complete"] is False
    assert default_cycle_payload["can_render_share"] is False
    assert default_cycle_payload["receipt_source_caveats"] == [
        "missing_committee_summary",
        "incomplete_committee_summary_coverage",
    ]
    assert default_cycle_payload["debts_owed_by_committee"] is None


def test_get_candidate_summary_explicit_link_is_authoritative_over_principal_committee(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    _person_id, candidate_id, principal_committee_id = _seed_principal_committee_fallback_fixture(db_conn)
    explicit_committee_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d2000000-0000-0000-0000-000000000010"),
        committee_name="Explicit Link Committee",
        fec_committee_id="C88880002",
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=explicit_committee_context.committee_id,
            cycle=2024,
            total_receipts=Decimal("300.00"),
            total_disbursements=Decimal("25.00"),
            individual_contributions=Decimal("300.00"),
            individual_itemized_contributions=Decimal("300.00"),
            coverage_start_date=date(2023, 1, 1),
            coverage_end_date=date(2024, 12, 31),
        ),
    )
    insert_summary_transaction(
        db_conn,
        context=explicit_committee_context,
        transaction_id=UUID("d2000000-0000-0000-0000-000000000011"),
        transaction_type="15",
        amount=Decimal("300.00"),
        transaction_date=date(2024, 5, 6),
        source_record_id=explicit_committee_context.source_record_id,
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("d2000000-0000-0000-0000-000000000012"),
            candidate_id=candidate_id,
            committee_id=explicit_committee_context.committee_id,
            valid_period="[2023-01-01,2025-01-01)",
            designation="P",
            candidate_election_year=2024,
            fec_election_year=2024,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary?cycle=2024")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_source"] == "fec_weball"
    assert payload["total_raised"] == "1234.00"
    assert payload["transaction_count"] == 1
    assert [row["committee_id"] for row in payload["committees"]] == [str(explicit_committee_context.committee_id)]
    assert str(principal_committee_id) not in {row["committee_id"] for row in payload["committees"]}


def test_get_candidate_summary_principal_committee_requires_selected_cycle_official_coverage(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("d3000000-0000-0000-0000-000000000001")
    candidate_id = UUID("d3000000-0000-0000-0000-000000000002")
    filing_id = UUID("d3000000-0000-0000-0000-000000000003")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_id, fec_committee_id="C88880003", name="Stale Coverage Principal"),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H6NC03026",
            name="Stale Coverage Principal Candidate",
            office="H",
            principal_committee_id=committee_id,
            total_receipts=Decimal("9000.00"),
            total_disbursements=Decimal("1000.00"),
            cash_on_hand=Decimal("8000.00"),
            summary_coverage_end_date=date(2026, 12, 31),
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(id=filing_id, filing_fec_id="stale-principal-filing", committee_id=committee_id),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2024,
            total_receipts=Decimal("444.00"),
            total_disbursements=Decimal("111.00"),
            coverage_start_date=date(2023, 1, 1),
            coverage_end_date=date(2024, 12, 31),
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("d3000000-0000-0000-0000-000000000004"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="15",
            amount=Decimal("444.00"),
            amendment_indicator="N",
            transaction_date=date(2024, 6, 7),
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary?cycle=2024")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_source"] == "derived"
    assert payload["total_raised"] == "0.00"
    assert payload["total_spent"] == "0.00"
    assert payload["transaction_count"] == 0
    assert payload["committees"] == []
    assert payload["receipt_source_caveats"] == ["missing_committee_summary"]


def test_get_person_contribution_insights_missing_principal_committee_keeps_no_data_payload(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    person = Person(canonical_name="Missing Principal Committee Member")
    insert_person(db_conn, person)
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("d4000000-0000-0000-0000-000000000001"),
            fec_candidate_id="H4NC04024",
            name="Missing Principal Committee Candidate",
            office="H",
            person_id=person.id,
            total_receipts=Decimal("100.00"),
            total_disbursements=Decimal("25.00"),
            cash_on_hand=Decimal("75.00"),
            summary_coverage_end_date=date(2024, 12, 31),
        ),
    )

    response = api_client.get(f"/v1/person/{person.id}/contribution-insights?cycle=2024")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_data"] is False
    assert payload["metadata"]["selected_cycle"] == 2024
    assert payload["metadata"]["committee_count"] == 0
    assert payload["metadata"]["excluded_geography"] == "no_linked_candidate"
    assert payload["cycle_totals"] == []
    assert payload["career_totals"]["source"] == "none"


def test_get_candidate_summary_exposes_candidate_self_funding(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("e3000000-0000-0000-0000-000000000701")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC03701",
            name="Self Funding Contract Candidate",
            office="H",
            total_receipts=Decimal("5000.00"),
            total_disbursements=Decimal("1250.00"),
            cash_on_hand=Decimal("3750.00"),
            candidate_contrib=Decimal("1234.56"),
            candidate_loans=Decimal("345.67"),
            candidate_loan_repay=Decimal("89.01"),
            summary_coverage_end_date=date(2026, 12, 31),
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_contrib"] == "1234.56"
    assert payload["candidate_loans"] == "345.67"
    assert payload["candidate_loan_repay"] == "89.01"
    assert payload["net_self_funding"] == "1491.22"


@pytest.mark.parametrize(
    "self_funding_case",
    [
        (
            UUID("e3000000-0000-0000-0000-000000000711"),
            "H0NC03711",
            Decimal("110.11"),
            Decimal("220.22"),
            Decimal("30.03"),
            Decimal("300.30"),
        ),
        (UUID("e3000000-0000-0000-0000-000000000712"), "H0NC03712", None, None, None, None),
        (
            UUID("e3000000-0000-0000-0000-000000000713"),
            "H0NC03713",
            None,
            Decimal("77.77"),
            None,
            Decimal("77.77"),
        ),
        (
            UUID("e3000000-0000-0000-0000-000000000714"),
            "H0NC03714",
            Decimal("11.11"),
            Decimal("22.22"),
            Decimal("44.44"),
            Decimal("-11.11"),
        ),
    ],
    ids=["complete", "all_null", "one_component", "negative_net"],
)
def test_candidate_self_funding_detail_and_batch_parity(
    db_conn: psycopg.Connection,
    self_funding_case: tuple[UUID, str, Decimal | None, Decimal | None, Decimal | None, Decimal | None],
) -> None:
    (
        candidate_id,
        fec_candidate_id,
        candidate_contrib,
        candidate_loans,
        candidate_loan_repay,
        expected_net_self_funding,
    ) = self_funding_case
    candidate_name = f"Self Funding Parity {fec_candidate_id}"
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id=fec_candidate_id,
            name=candidate_name,
            office="H",
            total_receipts=Decimal("1000.00"),
            total_disbursements=Decimal("400.00"),
            cash_on_hand=Decimal("600.00"),
            candidate_contrib=candidate_contrib,
            candidate_loans=candidate_loans,
            candidate_loan_repay=candidate_loan_repay,
            summary_coverage_end_date=date(2026, 12, 31),
        ),
    )
    expected_self_funding = {
        "candidate_contrib": candidate_contrib,
        "candidate_loans": candidate_loans,
        "candidate_loan_repay": candidate_loan_repay,
        "net_self_funding": expected_net_self_funding,
    }

    detail_summary = fetch_candidate_summary(db_conn, candidate_id, candidate_name)
    batch_summary = fetch_candidate_public_money_summaries(db_conn, [(candidate_id, candidate_name)])[candidate_id]

    assert detail_summary is not None
    assert {key: detail_summary[key] for key in expected_self_funding} == expected_self_funding
    assert {key: batch_summary[key] for key in expected_self_funding} == expected_self_funding


def test_candidate_self_funding_is_null_for_non_selected_cycle(db_conn: psycopg.Connection) -> None:
    candidate_id = UUID("e3000000-0000-0000-0000-000000000721")
    candidate_name = "Prior Cycle Self Funding Candidate"
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC03721",
            name=candidate_name,
            office="H",
            total_receipts=Decimal("9000.00"),
            total_disbursements=Decimal("3500.00"),
            cash_on_hand=Decimal("5500.00"),
            candidate_contrib=Decimal("901.23"),
            candidate_loans=Decimal("456.78"),
            candidate_loan_repay=Decimal("123.45"),
            summary_coverage_end_date=date(2026, 12, 31),
        ),
    )
    expected_null_self_funding = {
        "candidate_contrib": None,
        "candidate_loans": None,
        "candidate_loan_repay": None,
        "net_self_funding": None,
    }

    detail_summary = fetch_candidate_summary(db_conn, candidate_id, candidate_name, selected_cycle=2024)
    batch_summary = fetch_candidate_public_money_summaries(
        db_conn, [(candidate_id, candidate_name)], selected_cycle=2024
    )[candidate_id]

    assert detail_summary is not None
    assert {key: detail_summary[key] for key in expected_null_self_funding} == expected_null_self_funding
    assert {key: batch_summary[key] for key in expected_null_self_funding} == expected_null_self_funding


def test_get_candidate_summary_ignores_official_weball_totals_for_non_selected_cycle(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """A selected cycle must not label another weball cycle's totals as its own."""
    candidate_id = UUID("b0000000-0000-0000-0000-000000000551")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02551",
            name="Prior Cycle Official Totals Candidate",
            office="H",
            total_receipts=Decimal("9000.00"),
            total_disbursements=Decimal("3500.00"),
            cash_on_hand=Decimal("5500.00"),
            summary_coverage_end_date=date(2026, 12, 31),
        ),
    )
    committee_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("b5666666-6666-6666-6666-666666666666"),
        committee_name="Prior Cycle Official Totals Committee",
        fec_committee_id="C99000551",
    )
    insert_summary_transaction(
        db_conn,
        context=committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000561"),
        transaction_type="15",
        amount=Decimal("125.00"),
        transaction_date=date(2024, 7, 15),
        source_record_id=committee_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000562"),
        transaction_type="24A",
        amount=Decimal("25.00"),
        transaction_date=date(2024, 8, 15),
        source_record_id=committee_context.source_record_id,
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000563"),
            candidate_id=candidate_id,
            committee_id=committee_context.committee_id,
            valid_period="[2023-01-01,2025-01-01)",
            designation="P",
            source_record_id=None,
            candidate_election_year=2024,
            fec_election_year=2024,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary?cycle=2024")

    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_cycle"] == 2024
    assert payload["coverage_start_date"] == "2023-01-01"
    assert payload["coverage_end_date"] == "2024-12-31"
    assert payload["summary_source"] == "derived"
    assert payload["total_raised"] == "125.00"
    assert payload["total_spent"] == "25.00"
    assert payload["net"] == "100.00"
    assert payload["cash_on_hand"] is None
    assert payload["transaction_count"] == 2


def test_get_candidate_summary_returns_zero_official_payload_when_no_linked_committees_direct_owner(
    db_conn: psycopg.Connection,
) -> None:
    """Direct query-owner assertion: fetch_candidate_summary must NOT return None.

    The route-level fallback previously hid the missing branch by substituting a zero
    payload; this test verifies the query owner returns the zero payload itself so
    the route fallback can be removed.
    """
    candidate_id = UUID("b0000000-0000-0000-0000-000000000601")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02601",
            name="No Link Direct Owner Candidate",
            office="H",
        ),
    )

    summary = fetch_candidate_summary(db_conn, candidate_id, "No Link Direct Owner Candidate")

    assert summary is not None
    assert summary["candidate_id"] == candidate_id
    assert summary["candidate_name"] == "No Link Direct Owner Candidate"
    assert summary["total_raised"] == Decimal("0.00")
    assert summary["total_spent"] == Decimal("0.00")
    assert summary["net"] == Decimal("0.00")
    assert summary["transaction_count"] == 0
    assert summary["committees"] == []
    assert summary["cash_on_hand"] is None
    # No official totals seeded -> derived fallback at zero.
    assert summary["summary_source"] == "derived"


def test_get_candidate_summary_single_committee_common_case(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("b0000000-0000-0000-0000-000000000201")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02002",
            name="Single Committee Candidate",
            office="H",
        ),
    )

    committee_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("b1211111-1111-1111-1111-111111111111"),
        committee_name="Single Committee",
        fec_committee_id="C99000211",
    )
    insert_summary_transaction(
        db_conn,
        context=committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000221"),
        transaction_type="15",
        amount=Decimal("75.00"),
        source_record_id=committee_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000222"),
        transaction_type="24A",
        amount=Decimal("25.00"),
        source_record_id=committee_context.source_record_id,
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000231"),
            candidate_id=candidate_id,
            committee_id=committee_context.committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
            source_record_id=None,
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"] == str(candidate_id)
    assert payload["candidate_name"] == "Single Committee Candidate"
    assert payload["total_raised"] == "75.00"
    assert payload["total_spent"] == "25.00"
    assert payload["net"] == "50.00"
    assert payload["transaction_count"] == 2
    assert [row["committee_id"] for row in payload["committees"]] == [str(committee_context.committee_id)]
    assert payload["committees"][0]["committee_name"] == "Single Committee"


def test_get_candidate_summary_returns_zero_totals_when_no_linked_committees(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("b0000000-0000-0000-0000-000000000301")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02003",
            name="No Committee Candidate",
            office="H",
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "candidate_id": str(candidate_id),
        "candidate_name": "No Committee Candidate",
        "selected_cycle": 2026,
        "coverage_start_date": "2025-01-01",
        "coverage_end_date": "2026-12-31",
        "available_cycles": [2022, 2024, 2026],
        "total_raised": "0.00",
        "total_spent": "0.00",
        "net": "0.00",
        "transaction_count": 0,
        "itemized_transaction_count": 0,
        "committees": [],
        "cash_on_hand": None,
        "candidate_contrib": None,
        "candidate_loans": None,
        "candidate_loan_repay": None,
        "net_self_funding": None,
        "summary_source": "derived",
        "receipt_source_composition": [],
        "selected_cycle_coverage_complete": False,
        "can_render_share": False,
        "receipt_source_caveats": ["missing_committee_summary"],
        "debts_owed_by_committee": None,
    }


def test_get_candidate_summary_keeps_linked_committee_with_zero_qualifying_transactions(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("b0000000-0000-0000-0000-000000000351")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02031",
            name="Zero Qualifying Candidate",
            office="H",
        ),
    )

    committee_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("b3555555-5555-5555-5555-555555555555"),
        committee_name="Zero Qualifying Committee",
        fec_committee_id="C99000351",
    )
    insert_summary_transaction(
        db_conn,
        context=committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000361"),
        transaction_type="15",
        amount=Decimal("90.00"),
        source_record_id=committee_context.source_record_id,
        is_memo=True,
    )
    insert_summary_transaction(
        db_conn,
        context=committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000362"),
        transaction_type="24A",
        amount=Decimal("15.00"),
        source_record_id=committee_context.source_record_id,
        amendment_indicator="T",
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000371"),
            candidate_id=candidate_id,
            committee_id=committee_context.committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
            source_record_id=None,
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    assert response.json() == {
        "candidate_id": str(candidate_id),
        "candidate_name": "Zero Qualifying Candidate",
        "selected_cycle": 2026,
        "coverage_start_date": "2025-01-01",
        "coverage_end_date": "2026-12-31",
        "available_cycles": [2022, 2024, 2026],
        "total_raised": "0.00",
        "total_spent": "0.00",
        "net": "0.00",
        "transaction_count": 0,
        "itemized_transaction_count": 0,
        "committees": [
            {
                "committee_id": str(committee_context.committee_id),
                "committee_name": "Zero Qualifying Committee",
                "selected_cycle": 2026,
                "coverage_start_date": "2025-01-01",
                "coverage_end_date": "2026-12-31",
                "available_cycles": [2022, 2024, 2026],
                "total_raised": "0.00",
                "total_spent": "0.00",
                "net": "0.00",
                "transaction_count": 0,
                "jurisdiction": None,
                "data_through": None,
                "cash_receipts_total": "0.00",
                "in_kind_receipts_total": "0.00",
                "loan_receipts_total": "0.00",
                "contribution_receipts_total": "0.00",
                "top_donors": [],
                "top_vendors": [],
                "spend_categories": None,
                "itemized_transaction_count": 0,
                "cycle_summaries": [],
                "summary_source": "derived",
                "receipt_source_composition": [],
                "selected_cycle_coverage_complete": False,
                "can_render_share": False,
                "receipt_source_caveats": ["missing_committee_summary"],
                "debts_owed_by_committee": None,
            }
        ],
        "cash_on_hand": None,
        "candidate_contrib": None,
        "candidate_loans": None,
        "candidate_loan_repay": None,
        "net_self_funding": None,
        "summary_source": "derived",
        "receipt_source_composition": [],
        "selected_cycle_coverage_complete": False,
        "can_render_share": False,
        "receipt_source_caveats": ["missing_committee_summary"],
        "debts_owed_by_committee": None,
    }


def test_get_candidate_summary_excludes_expired_candidate_committee_links(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("b0000000-0000-0000-0000-000000000401")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02004",
            name="Filtered Link Candidate",
            office="H",
        ),
    )

    active_committee_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("b3333333-3333-3333-3333-333333333333"),
        committee_name="Active Committee",
        fec_committee_id="C99000411",
    )
    expired_committee_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("b4444444-4444-4444-4444-444444444444"),
        committee_name="Expired Committee",
        fec_committee_id="C99000412",
    )

    insert_summary_transaction(
        db_conn,
        context=active_committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000421"),
        transaction_type="15",
        amount=Decimal("125.00"),
        source_record_id=active_committee_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=expired_committee_context,
        transaction_id=UUID("b0000000-0000-0000-0000-000000000422"),
        transaction_type="15",
        amount=Decimal("900.00"),
        source_record_id=expired_committee_context.source_record_id,
    )

    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000431"),
            candidate_id=candidate_id,
            committee_id=active_committee_context.committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
            source_record_id=None,
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000432"),
            candidate_id=candidate_id,
            committee_id=expired_committee_context.committee_id,
            valid_period="[2000-01-01,2001-01-01)",
            designation="A",
            source_record_id=None,
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_raised"] == "125.00"
    assert payload["total_spent"] == "0.00"
    assert payload["net"] == "125.00"
    assert payload["transaction_count"] == 1
    assert [row["committee_id"] for row in payload["committees"]] == [str(active_committee_context.committee_id)]
    assert payload["committees"][0]["committee_name"] == "Active Committee"


def test_get_candidate_summary_returns_404_for_missing_candidate(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/candidates/{uuid4()}/summary")

    assert response.status_code == 404
    assert response.json() == {"detail": "Candidate not found"}


def test_get_committee_ie_activity_aggregates_targets_with_provenance(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("c9000000-0000-0000-0000-000000000101")
    target_alpha_id = UUID("c9000000-0000-0000-0000-000000000102")
    target_beta_id = UUID("c9000000-0000-0000-0000-000000000103")
    target_gamma_id = UUID("c9000000-0000-0000-0000-000000000104")
    target_other_id = UUID("c9000000-0000-0000-0000-000000000105")
    filing_id = UUID("c9000000-0000-0000-0000-000000000111")
    person_alpha = Person(canonical_name="Committee IE Alpha")
    insert_person(db_conn, person_alpha)

    data_source = insert_data_source_for_test(db_conn, jurisdiction="federal/fec", name_suffix="committee-ie")
    source_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("c9000000-0000-0000-0000-000000000121"),
        data_source_id=data_source.id,
        source_record_key="committee-ie-source",
        source_url="https://example.org/record/committee-ie-source",
        pull_date=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )

    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_id, fec_committee_id="C90900101", name="Committee IE Spender"),
    )
    for candidate_id, fec_candidate_id, name, person_id, state, district in (
        (target_alpha_id, "H0NC09101", "Committee IE Alpha", person_alpha.id, "NC", "01"),
        (target_beta_id, "S0NC09102", "Committee IE Beta", None, "NC", None),
        (target_gamma_id, "H0VA09103", "Committee IE Gamma", None, "VA", "03"),
        (target_other_id, "H0NC09104", "Committee IE Other", None, "NC", "04"),
    ):
        insert_candidate_row(
            db_conn,
            CandidateRowSeed(
                id=candidate_id,
                fec_candidate_id=fec_candidate_id,
                name=name,
                office=fec_candidate_id[0],
                person_id=person_id,
                state=state,
                district=district,
            ),
        )
    insert_filing_row(
        db_conn,
        FilingRowSeed(id=filing_id, filing_fec_id="COMMITTEE-IE-FILING", committee_id=committee_id),
    )

    rows = [
        (UUID("c9000000-0000-0000-0000-000000000131"), target_alpha_id, "S", "500.00"),
        (UUID("c9000000-0000-0000-0000-000000000132"), target_alpha_id, "O", "75.00"),
        (UUID("c9000000-0000-0000-0000-000000000133"), target_beta_id, "O", "350.00"),
        (UUID("c9000000-0000-0000-0000-000000000134"), target_gamma_id, "S", "100.00"),
    ]
    for transaction_id, candidate_id, support_oppose, amount in rows:
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=transaction_id,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="24E",
                amount=Decimal(amount),
                amendment_indicator="N",
                recipient_candidate_id=candidate_id,
                support_oppose=support_oppose,
                source_record_id=source_record.id,
            ),
        )

    # Excluded by missing candidate target, missing support/oppose, memo row, terminated amendment, and committee mismatch.
    for transaction_id, candidate_id, support_oppose, is_memo, amendment_indicator, amount in (
        (UUID("c9000000-0000-0000-0000-000000000135"), None, "S", False, "N", "999.00"),
        (UUID("c9000000-0000-0000-0000-000000000136"), target_other_id, None, False, "N", "888.00"),
        (UUID("c9000000-0000-0000-0000-000000000137"), target_other_id, "S", True, "N", "777.00"),
        (UUID("c9000000-0000-0000-0000-000000000138"), target_other_id, "O", False, "T", "666.00"),
    ):
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=transaction_id,
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="24E",
                amount=Decimal(amount),
                amendment_indicator=amendment_indicator,
                recipient_candidate_id=candidate_id,
                support_oppose=support_oppose,
                source_record_id=source_record.id,
                is_memo=is_memo,
            ),
        )
    other_committee_id = UUID("c9000000-0000-0000-0000-000000000106")
    other_filing_id = UUID("c9000000-0000-0000-0000-000000000112")
    insert_committee_row(
        db_conn, CommitteeRowSeed(id=other_committee_id, fec_committee_id="C90900106", name="Other IE Spender")
    )
    insert_filing_row(
        db_conn, FilingRowSeed(id=other_filing_id, filing_fec_id="OTHER-IE-FILING", committee_id=other_committee_id)
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("c9000000-0000-0000-0000-000000000139"),
            filing_id=other_filing_id,
            committee_id=other_committee_id,
            transaction_type="24E",
            amount=Decimal("555.00"),
            amendment_indicator="N",
            recipient_candidate_id=target_other_id,
            support_oppose="S",
            source_record_id=source_record.id,
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}/independent-expenditures-made")

    assert response.status_code == 200
    payload = response.json()
    assert payload["committee_id"] == str(committee_id)
    assert payload["support_total"] == "600.00"
    assert payload["oppose_total"] == "425.00"
    assert payload["ie_transaction_count"] == 4
    assert payload["excluded_outlier_count"] == 0
    assert [row["candidate_id"] for row in payload["targets"]] == [
        str(target_alpha_id),
        str(target_beta_id),
        str(target_gamma_id),
    ]
    assert payload["targets"] == [
        {
            "candidate_id": str(target_alpha_id),
            "fec_candidate_id": "H0NC09101",
            "candidate_name": "Committee IE Alpha",
            "person_id": str(person_alpha.id),
            "party": None,
            "office": "H",
            "state": "NC",
            "district": "01",
            "slug": "committee-ie-alpha",
            "slug_is_unique": True,
            "support_total": "500.00",
            "oppose_total": "75.00",
            "transaction_count": 2,
            "sources": [
                {
                    "domain": "campaign_finance",
                    "jurisdiction": "federal/fec",
                    "data_source_name": data_source.name,
                    "data_source_url": data_source.source_url,
                    "source_record_key": "committee-ie-source",
                    "record_url": "https://example.org/record/committee-ie-source",
                    "pull_date": "2026-07-01T12:00:00Z",
                }
            ],
        },
        {
            "candidate_id": str(target_beta_id),
            "fec_candidate_id": "S0NC09102",
            "candidate_name": "Committee IE Beta",
            "person_id": None,
            "party": None,
            "office": "S",
            "state": "NC",
            "district": None,
            "slug": "committee-ie-beta",
            "slug_is_unique": True,
            "support_total": "0.00",
            "oppose_total": "350.00",
            "transaction_count": 1,
            "sources": [
                {
                    "domain": "campaign_finance",
                    "jurisdiction": "federal/fec",
                    "data_source_name": data_source.name,
                    "data_source_url": data_source.source_url,
                    "source_record_key": "committee-ie-source",
                    "record_url": "https://example.org/record/committee-ie-source",
                    "pull_date": "2026-07-01T12:00:00Z",
                }
            ],
        },
        {
            "candidate_id": str(target_gamma_id),
            "fec_candidate_id": "H0VA09103",
            "candidate_name": "Committee IE Gamma",
            "person_id": None,
            "party": None,
            "office": "H",
            "state": "VA",
            "district": "03",
            "slug": "committee-ie-gamma",
            "slug_is_unique": True,
            "support_total": "100.00",
            "oppose_total": "0.00",
            "transaction_count": 1,
            "sources": [
                {
                    "domain": "campaign_finance",
                    "jurisdiction": "federal/fec",
                    "data_source_name": data_source.name,
                    "data_source_url": data_source.source_url,
                    "source_record_key": "committee-ie-source",
                    "record_url": "https://example.org/record/committee-ie-source",
                    "pull_date": "2026-07-01T12:00:00Z",
                }
            ],
        },
    ]


def test_get_committee_ie_activity_returns_404_for_missing_committee(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/committees/{uuid4()}/independent-expenditures-made")

    assert response.status_code == 404
    assert response.json() == {"detail": "Committee not found"}


def test_get_committee_ie_activity_returns_empty_payload_for_known_committee(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("c9000000-0000-0000-0000-000000000201")
    candidate_id = UUID("c9000000-0000-0000-0000-000000000202")
    filing_id = UUID("c9000000-0000-0000-0000-000000000203")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_id, fec_committee_id="C90900201", name="Empty Committee IE Spender"),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(id=candidate_id, fec_candidate_id="H0NC09202", name="Empty Committee IE Target", office="H"),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(id=filing_id, filing_fec_id="EMPTY-COMMITTEE-IE-FILING", committee_id=committee_id),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("c9000000-0000-0000-0000-000000000204"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24E",
            amount=Decimal("125.00"),
            amendment_indicator="N",
            recipient_candidate_id=candidate_id,
            support_oppose=None,
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}/independent-expenditures-made")

    assert response.status_code == 200
    assert response.json() == {
        "committee_id": str(committee_id),
        "support_total": "0.00",
        "oppose_total": "0.00",
        "ie_transaction_count": 0,
        "excluded_outlier_count": 0,
        "targets": [],
    }


def test_get_committee_ie_activity_excludes_outliers_from_aggregates(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("c9000000-0000-0000-0000-000000000301")
    candidate_id = UUID("c9000000-0000-0000-0000-000000000302")
    filing_id = UUID("c9000000-0000-0000-0000-000000000303")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_id, fec_committee_id="C90900301", name="Outlier Committee IE Spender"),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(id=candidate_id, fec_candidate_id="H0NC09302", name="Outlier Committee IE Target", office="H"),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(id=filing_id, filing_fec_id="OUTLIER-COMMITTEE-IE-FILING", committee_id=committee_id),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("c9000000-0000-0000-0000-000000000304"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24E",
            amount=Decimal("250.00"),
            amendment_indicator="N",
            recipient_candidate_id=candidate_id,
            support_oppose="S",
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("c9000000-0000-0000-0000-000000000305"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24E",
            amount=Decimal("500000000.00"),
            amendment_indicator="N",
            recipient_candidate_id=candidate_id,
            support_oppose="S",
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}/independent-expenditures-made")

    assert response.status_code == 200
    payload = response.json()
    assert payload["support_total"] == "250.00"
    assert payload["oppose_total"] == "0.00"
    assert payload["ie_transaction_count"] == 1
    assert payload["excluded_outlier_count"] == 1
    assert payload["targets"] == [
        {
            "candidate_id": str(candidate_id),
            "fec_candidate_id": "H0NC09302",
            "candidate_name": "Outlier Committee IE Target",
            "person_id": None,
            "party": None,
            "office": "H",
            "state": None,
            "district": None,
            "slug": "outlier-committee-ie-target",
            "slug_is_unique": True,
            "support_total": "250.00",
            "oppose_total": "0.00",
            "transaction_count": 1,
            "sources": [],
        }
    ]


def test_get_candidate_independent_expenditures_returns_paginated_rows(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("c0000000-0000-0000-0000-000000000101")
    other_candidate_id = UUID("c0000000-0000-0000-0000-000000000102")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC03001",
            name="IE Target Candidate",
            office="H",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=other_candidate_id,
            fec_candidate_id="H0NC03002",
            name="Other Candidate",
            office="H",
        ),
    )

    committee_a = UUID("c1111111-1111-1111-1111-111111111111")
    committee_b = UUID("c2222222-2222-2222-2222-222222222222")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_a, fec_committee_id="C99800101", name="Committee Alpha"),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_b, fec_committee_id="C99800102", name="Committee Beta"),
    )

    filing_a = UUID("c0000000-0000-0000-0000-000000000111")
    filing_b = UUID("c0000000-0000-0000-0000-000000000112")
    insert_filing_row(
        db_conn,
        FilingRowSeed(id=filing_a, filing_fec_id="IE-FILING-A", committee_id=committee_a),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(id=filing_b, filing_fec_id="IE-FILING-B", committee_id=committee_b),
    )

    transaction_1 = UUID("c0000000-0000-0000-0000-000000000121")
    transaction_2 = UUID("c0000000-0000-0000-0000-000000000122")
    transaction_3 = UUID("c0000000-0000-0000-0000-000000000123")
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=transaction_1,
            filing_id=filing_a,
            committee_id=committee_a,
            transaction_type="24E",
            amount=Decimal("500.00"),
            amendment_indicator="N",
            transaction_date=datetime(2026, 3, 20, tzinfo=timezone.utc).date(),
            memo_text="Digital ad buy",
            recipient_candidate_id=candidate_id,
            support_oppose="S",
            dissemination_date=datetime(2026, 3, 19, tzinfo=timezone.utc).date(),
            aggregate_amount=Decimal("750.00"),
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=transaction_2,
            filing_id=filing_b,
            committee_id=committee_b,
            transaction_type="24E",
            amount=Decimal("300.00"),
            amendment_indicator="N",
            transaction_date=datetime(2026, 3, 19, tzinfo=timezone.utc).date(),
            memo_text=None,
            recipient_candidate_id=candidate_id,
            support_oppose="O",
            dissemination_date=None,
            aggregate_amount=None,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=transaction_3,
            filing_id=filing_a,
            committee_id=committee_a,
            transaction_type="24E",
            amount=Decimal("300.00"),
            amendment_indicator="N",
            transaction_date=datetime(2026, 3, 18, tzinfo=timezone.utc).date(),
            memo_text="TV ad buy",
            recipient_candidate_id=candidate_id,
            support_oppose="S",
            dissemination_date=datetime(2026, 3, 17, tzinfo=timezone.utc).date(),
            aggregate_amount=Decimal("900.00"),
        ),
    )

    # Excluded by support_oppose IS NULL
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000124"),
            filing_id=filing_a,
            committee_id=committee_a,
            transaction_type="24E",
            amount=Decimal("999.99"),
            amendment_indicator="N",
            recipient_candidate_id=candidate_id,
            support_oppose=None,
        ),
    )
    # Excluded by recipient_candidate_id mismatch
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000125"),
            filing_id=filing_b,
            committee_id=committee_b,
            transaction_type="24E",
            amount=Decimal("888.88"),
            amendment_indicator="N",
            recipient_candidate_id=other_candidate_id,
            support_oppose="O",
        ),
    )

    response = api_client.get(
        f"/v1/candidates/{candidate_id}/independent-expenditures",
        params={"limit": 2, "offset": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [row["id"] for row in payload] == [str(transaction_2), str(transaction_3)]
    assert payload[0]["committee_name"] == "Committee Beta"
    assert payload[0]["purpose"] is None
    assert payload[0]["support_oppose"] == "O"
    assert payload[0]["dissemination_date"] is None
    assert payload[0]["aggregate_amount"] is None
    assert payload[1]["committee_name"] == "Committee Alpha"
    assert payload[1]["purpose"] == "TV ad buy"
    assert payload[1]["support_oppose"] == "S"
    assert payload[1]["dissemination_date"] == "2026-03-17"
    assert payload[1]["aggregate_amount"] == pytest.approx(900.00)
    assert "memo_text" not in payload[0]


def test_get_candidate_independent_expenditures_summary_aggregates_and_ranks_spenders(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("c0000000-0000-0000-0000-000000000201")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC03003",
            name="IE Summary Candidate",
            office="H",
        ),
    )

    committee_a = UUID("c3333333-3333-3333-3333-333333333333")
    committee_b = UUID("c4444444-4444-4444-4444-444444444444")
    committee_c = UUID("c5555555-5555-5555-5555-555555555555")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_a, fec_committee_id="C99800201", name="Committee A"),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_b, fec_committee_id="C99800202", name="Committee B"),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_c, fec_committee_id="C99800203", name="Committee C"),
    )

    filing_a = UUID("c0000000-0000-0000-0000-000000000211")
    filing_b = UUID("c0000000-0000-0000-0000-000000000212")
    filing_c = UUID("c0000000-0000-0000-0000-000000000213")
    insert_filing_row(db_conn, FilingRowSeed(id=filing_a, filing_fec_id="IE-SUM-FILING-A", committee_id=committee_a))
    insert_filing_row(db_conn, FilingRowSeed(id=filing_b, filing_fec_id="IE-SUM-FILING-B", committee_id=committee_b))
    insert_filing_row(db_conn, FilingRowSeed(id=filing_c, filing_fec_id="IE-SUM-FILING-C", committee_id=committee_c))

    rows = [
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000221"),
            filing_id=filing_a,
            committee_id=committee_a,
            transaction_type="24E",
            amount=Decimal("300.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 1, 10),
            recipient_candidate_id=candidate_id,
            support_oppose="S",
        ),
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000222"),
            filing_id=filing_a,
            committee_id=committee_a,
            transaction_type="24E",
            amount=Decimal("50.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 1, 11),
            recipient_candidate_id=candidate_id,
            support_oppose="S",
        ),
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000223"),
            filing_id=filing_a,
            committee_id=committee_a,
            transaction_type="24E",
            amount=Decimal("40.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 1, 12),
            recipient_candidate_id=candidate_id,
            support_oppose="O",
        ),
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000224"),
            filing_id=filing_b,
            committee_id=committee_b,
            transaction_type="24E",
            amount=Decimal("200.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 1, 13),
            recipient_candidate_id=candidate_id,
            support_oppose="O",
        ),
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000225"),
            filing_id=filing_b,
            committee_id=committee_b,
            transaction_type="24E",
            amount=Decimal("75.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 1, 14),
            recipient_candidate_id=candidate_id,
            support_oppose="O",
        ),
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000226"),
            filing_id=filing_c,
            committee_id=committee_c,
            transaction_type="24E",
            amount=Decimal("125.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 1, 15),
            recipient_candidate_id=candidate_id,
            support_oppose="S",
        ),
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000227"),
            filing_id=filing_c,
            committee_id=committee_c,
            transaction_type="24E",
            amount=Decimal("125.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 1, 16),
            recipient_candidate_id=candidate_id,
            support_oppose="O",
        ),
    ]
    for row in rows:
        insert_transaction_row(db_conn, row)

    response = api_client.get(f"/v1/candidates/{candidate_id}/independent-expenditures/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"] == str(candidate_id)
    assert payload["support_total"] == "475.00"
    assert payload["oppose_total"] == "440.00"
    assert payload["support_count"] == 3
    assert payload["oppose_count"] == 4
    assert payload["top_spenders"] == [
        {
            "committee_id": str(committee_a),
            "committee_name": "Committee A",
            "support_oppose": "S",
            "total_amount": "350.00",
            "transaction_count": 2,
        },
        {
            "committee_id": str(committee_b),
            "committee_name": "Committee B",
            "support_oppose": "O",
            "total_amount": "275.00",
            "transaction_count": 2,
        },
        {
            "committee_id": str(committee_c),
            "committee_name": "Committee C",
            "support_oppose": "O",
            "total_amount": "125.00",
            "transaction_count": 1,
        },
        {
            "committee_id": str(committee_c),
            "committee_name": "Committee C",
            "support_oppose": "S",
            "total_amount": "125.00",
            "transaction_count": 1,
        },
        {
            "committee_id": str(committee_a),
            "committee_name": "Committee A",
            "support_oppose": "O",
            "total_amount": "40.00",
            "transaction_count": 1,
        },
    ]


def test_get_candidate_independent_expenditure_endpoints_exclude_memo_rows(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("c0000000-0000-0000-0000-000000000251")
    committee_id = UUID("c6666666-6666-6666-6666-666666666666")
    filing_id = UUID("c0000000-0000-0000-0000-000000000252")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC03005",
            name="IE Memo Candidate",
            office="H",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(id=committee_id, fec_committee_id="C99800204", name="Memo Filter Committee"),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(id=filing_id, filing_fec_id="IE-MEMO-FILING", committee_id=committee_id),
    )

    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000253"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24E",
            amount=Decimal("125.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            recipient_candidate_id=candidate_id,
            support_oppose="S",
            memo_text="Broadcast ad buy",
            is_memo=False,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("c0000000-0000-0000-0000-000000000254"),
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24E",
            amount=Decimal("900.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            recipient_candidate_id=candidate_id,
            support_oppose="O",
            memo_code="X",
            memo_text="Memo row should be excluded",
            is_memo=True,
        ),
    )

    list_response = api_client.get(f"/v1/candidates/{candidate_id}/independent-expenditures")
    summary_response = api_client.get(f"/v1/candidates/{candidate_id}/independent-expenditures/summary")

    assert list_response.status_code == 200
    assert list_response.json() == [
        {
            "id": "c0000000-0000-0000-0000-000000000253",
            "filing_id": "c0000000-0000-0000-0000-000000000252",
            "committee_id": "c6666666-6666-6666-6666-666666666666",
            "committee_name": "Memo Filter Committee",
            "amount": 125.0,
            "transaction_date": "2026-03-15",
            "purpose": "Broadcast ad buy",
            "dissemination_date": None,
            "aggregate_amount": None,
            "support_oppose": "S",
        }
    ]
    assert summary_response.status_code == 200
    assert summary_response.json() == {
        "candidate_id": str(candidate_id),
        "support_total": "125.00",
        "oppose_total": "0.00",
        "support_count": 1,
        "oppose_count": 0,
        "selected_cycle": 2026,
        "coverage_start_date": "2025-01-01",
        "coverage_end_date": "2026-12-31",
        "available_cycles": [2022, 2024, 2026],
        "top_spenders": [
            {
                "committee_id": str(committee_id),
                "committee_name": "Memo Filter Committee",
                "support_oppose": "S",
                "total_amount": "125.00",
                "transaction_count": 1,
            }
        ],
        "excluded_outlier_count": 0,
    }


@pytest.mark.parametrize(
    "endpoint_suffix",
    [
        "/independent-expenditures",
        "/independent-expenditures/summary",
    ],
)
def test_get_candidate_independent_expenditure_endpoints_return_404_for_missing_candidate(
    api_client: TestClient,
    endpoint_suffix: str,
) -> None:
    response = api_client.get(f"/v1/candidates/{uuid4()}{endpoint_suffix}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Candidate not found"}


def test_get_candidate_independent_expenditure_endpoints_return_empty_state(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    candidate_id = UUID("c0000000-0000-0000-0000-000000000301")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC03004",
            name="IE Empty Candidate",
            office="H",
        ),
    )

    list_response = api_client.get(f"/v1/candidates/{candidate_id}/independent-expenditures")
    summary_response = api_client.get(f"/v1/candidates/{candidate_id}/independent-expenditures/summary")

    assert list_response.status_code == 200
    assert list_response.json() == []
    assert summary_response.status_code == 200
    assert summary_response.json() == {
        "candidate_id": str(candidate_id),
        "support_total": "0.00",
        "oppose_total": "0.00",
        "support_count": 0,
        "oppose_count": 0,
        "selected_cycle": 2026,
        "coverage_start_date": "2025-01-01",
        "coverage_end_date": "2026-12-31",
        "available_cycles": [2022, 2024, 2026],
        "top_spenders": [],
        "excluded_outlier_count": 0,
    }


def test_get_state_summary_returns_all_states_with_ranked_totals_and_registry_flags(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    nc_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d1111111-1111-1111-1111-111111111111"),
        committee_name="North Carolina Committee",
        fec_committee_id="C99700111",
        state="NC",
        jurisdiction="state/nc",
        pull_date=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
    )
    nc_newer_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("d1000000-0000-0000-0000-000000000101"),
        data_source_id=nc_context.data_source_id,
        source_record_key="summary-nc-newer",
        source_url="https://example.org/record/summary-nc-newer",
        pull_date=datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc),
    )
    ca_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d2222222-2222-2222-2222-222222222222"),
        committee_name="California Committee",
        fec_committee_id="C99700222",
        state="CA",
        jurisdiction="state/ca",
        pull_date=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
    )

    insert_summary_transaction(
        db_conn,
        context=nc_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000111"),
        transaction_type="15",
        amount=Decimal("250.00"),
        source_record_id=nc_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=nc_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000112"),
        transaction_type="24A",
        amount=Decimal("50.00"),
        source_record_id=nc_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=nc_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000113"),
        transaction_type="24E",
        amount=Decimal("40.00"),
        source_record_id=nc_context.source_record_id,
        support_oppose="S",
        aggregate_amount=Decimal("40.00"),
    )
    insert_summary_transaction(
        db_conn,
        context=nc_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000114"),
        transaction_type="15",
        amount=Decimal("25.00"),
        source_record_id=nc_newer_source.id,
    )
    insert_summary_transaction(
        db_conn,
        context=ca_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000121"),
        transaction_type="15",
        amount=Decimal("100.00"),
        source_record_id=ca_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=ca_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000122"),
        transaction_type="24A",
        amount=Decimal("20.00"),
        source_record_id=ca_context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=ca_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000123"),
        transaction_type="24E",
        amount=Decimal("10.00"),
        source_record_id=ca_context.source_record_id,
        support_oppose="O",
        aggregate_amount=Decimal("10.00"),
    )

    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("d0000000-0000-0000-0000-000000000131"),
            fec_candidate_id="H0NC99001",
            name="NC Candidate 1",
            office="H",
            state="NC",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("d0000000-0000-0000-0000-000000000132"),
            fec_candidate_id="S0NC99002",
            name="NC Candidate 2",
            office="S",
            state="NC",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("d0000000-0000-0000-0000-000000000133"),
            fec_candidate_id="H0CA99003",
            name="CA Candidate 1",
            office="H",
            state="CA",
        ),
    )

    response = api_client.get("/v1/campaign-finance/states/summary")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == len(LAUNCH_SCOPE_USPS_STATES)
    assert {row["state_code"] for row in payload} == set(LAUNCH_SCOPE_USPS_STATES)
    assert [row["state_code"] for row in payload[:2]] == ["NC", "CA"]

    rows_by_state = {row["state_code"]: row for row in payload}
    nc_row = rows_by_state["NC"]
    ca_row = rows_by_state["CA"]
    dc_row = rows_by_state["DC"]

    assert nc_row["total_raised"] == "275.00"
    assert nc_row["total_spent"] == "90.00"
    assert nc_row["net"] == "185.00"
    assert nc_row["committee_count"] == 1
    assert nc_row["transaction_count"] == 4
    assert nc_row["federal_candidate_count"] == 2
    assert nc_row["ie_support_total"] == "40.00"
    assert nc_row["ie_oppose_total"] == "0.00"
    assert nc_row["ie_support_count"] == 1
    assert nc_row["ie_oppose_count"] == 0
    assert nc_row["data_through"] == "2026-03-23T12:00:00Z"
    assert nc_row["supported"] is True

    assert ca_row["total_raised"] == "100.00"
    assert ca_row["total_spent"] == "30.00"
    assert ca_row["net"] == "70.00"
    assert ca_row["committee_count"] == 1
    assert ca_row["transaction_count"] == 3
    assert ca_row["federal_candidate_count"] == 1
    assert ca_row["ie_support_total"] == "0.00"
    assert ca_row["ie_oppose_total"] == "10.00"
    assert ca_row["ie_support_count"] == 0
    assert ca_row["ie_oppose_count"] == 1
    assert ca_row["supported"] is True

    assert dc_row["total_raised"] == "0.00"
    assert dc_row["total_spent"] == "0.00"
    assert dc_row["net"] == "0.00"
    assert dc_row["committee_count"] == 0
    assert dc_row["transaction_count"] == 0
    assert dc_row["federal_candidate_count"] == 0
    assert dc_row["ie_support_total"] is None
    assert dc_row["ie_oppose_total"] is None
    assert dc_row["ie_support_count"] is None
    assert dc_row["ie_oppose_count"] is None
    assert dc_row["data_through"] is None
    assert dc_row["supported"] is False


def test_state_summary_and_detail_return_null_ie_for_supported_state_without_ie_lane(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """A launch-support state whose registry evidence shows no IE coverage must return null IE totals.

    Louisiana is the canonical example: the state pipeline is launch-support
    candidate, but `docs/reference/research/coverage-registry.json` documents that the
    bulk export carries no independent-expenditure schedule. Even when the DB
    happens to contain IE-flagged transactions for an LA committee, the API
    must serialize null IE totals/counts so the frontend cannot render
    misleading zeroes for outside-spending coverage.
    """
    la_context = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d6666666-6666-6666-6666-666666666666"),
        committee_name="Louisiana Committee",
        fec_committee_id="C99700666",
        state="LA",
        jurisdiction="state/la",
        pull_date=datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc),
    )

    insert_summary_transaction(
        db_conn,
        context=la_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000601"),
        transaction_type="15",
        amount=Decimal("400.00"),
        source_record_id=la_context.source_record_id,
    )
    # Even with IE-classified rows present in the DB, the registry evidence says
    # LA has no IE coverage in the current bulk export, so the API contract is
    # null IE totals (not zero, not the seeded amount).
    insert_summary_transaction(
        db_conn,
        context=la_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000602"),
        transaction_type="24E",
        amount=Decimal("75.00"),
        source_record_id=la_context.source_record_id,
        support_oppose="S",
        aggregate_amount=Decimal("75.00"),
    )
    insert_summary_transaction(
        db_conn,
        context=la_context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000603"),
        transaction_type="24E",
        amount=Decimal("25.00"),
        source_record_id=la_context.source_record_id,
        support_oppose="O",
        aggregate_amount=Decimal("25.00"),
    )

    summary_response = api_client.get("/v1/campaign-finance/states/summary")
    assert summary_response.status_code == 200

    rows_by_state = {row["state_code"]: row for row in summary_response.json()}
    la_summary_row = rows_by_state["LA"]

    assert la_summary_row["supported"] is True
    assert la_summary_row["total_raised"] == "400.00"
    assert la_summary_row["transaction_count"] == 3
    assert la_summary_row["warning_text"] == "Independent expenditure data is incomplete for this state."
    assert la_summary_row["ie_support_total"] is None
    assert la_summary_row["ie_oppose_total"] is None
    assert la_summary_row["ie_support_count"] is None
    assert la_summary_row["ie_oppose_count"] is None

    detail_response = api_client.get("/v1/campaign-finance/states/LA")
    assert detail_response.status_code == 200

    la_detail_payload = detail_response.json()
    assert la_detail_payload["state_code"] == "LA"
    assert la_detail_payload["supported"] is True
    assert la_detail_payload["warning_text"] == "Independent expenditure data is incomplete for this state."
    assert la_detail_payload["ie_support_total"] is None
    assert la_detail_payload["ie_oppose_total"] is None
    assert la_detail_payload["ie_support_count"] is None
    assert la_detail_payload["ie_oppose_count"] is None
    # The state has no IE coverage, so the detail panel must not surface
    # any top-IE-spender entries derived from incidental DB rows.
    assert la_detail_payload["top_ie_spenders"] == []


def test_get_state_detail_returns_aggregate_panels_and_validation_behavior(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    nc_committee_a = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d3333333-3333-3333-3333-333333333333"),
        committee_name="NC Committee A",
        fec_committee_id="C99700333",
        state="NC",
        jurisdiction="state/nc",
        pull_date=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
    )
    nc_committee_b = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d4444444-4444-4444-4444-444444444444"),
        committee_name="NC Committee B",
        fec_committee_id="C99700444",
        state="NC",
        jurisdiction="state/nc",
        pull_date=datetime(2026, 3, 26, 12, 0, tzinfo=timezone.utc),
    )
    ca_committee = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d5555555-5555-5555-5555-555555555555"),
        committee_name="CA Committee A",
        fec_committee_id="C99700555",
        state="CA",
        jurisdiction="state/ca",
        pull_date=datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc),
    )

    nc_candidate_one = UUID("d0000000-0000-0000-0000-000000000211")
    nc_candidate_two = UUID("d0000000-0000-0000-0000-000000000212")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=nc_candidate_one,
            fec_candidate_id="H0NC99011",
            name="NC Candidate One",
            office="H",
            state="NC",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=nc_candidate_two,
            fec_candidate_id="H0NC99012",
            name="NC Candidate Two",
            office="H",
            state="NC",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=UUID("d0000000-0000-0000-0000-000000000213"),
            fec_candidate_id="H0CA99013",
            name="CA Candidate One",
            office="H",
            state="CA",
        ),
    )

    insert_summary_transaction(
        db_conn,
        context=nc_committee_a,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000221"),
        transaction_type="15",
        amount=Decimal("200.00"),
        source_record_id=nc_committee_a.source_record_id,
        recipient_candidate_id=nc_candidate_one,
    )
    insert_summary_transaction(
        db_conn,
        context=nc_committee_a,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000222"),
        transaction_type="15",
        amount=Decimal("70.00"),
        source_record_id=nc_committee_a.source_record_id,
        recipient_candidate_id=nc_candidate_two,
    )
    insert_summary_transaction(
        db_conn,
        context=nc_committee_b,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000223"),
        transaction_type="15",
        amount=Decimal("120.00"),
        source_record_id=nc_committee_b.source_record_id,
        recipient_candidate_id=nc_candidate_two,
    )
    insert_summary_transaction(
        db_conn,
        context=nc_committee_a,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000224"),
        transaction_type="24A",
        amount=Decimal("30.00"),
        source_record_id=nc_committee_a.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=nc_committee_b,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000225"),
        transaction_type="24E",
        amount=Decimal("80.00"),
        source_record_id=nc_committee_b.source_record_id,
        support_oppose="O",
        aggregate_amount=Decimal("80.00"),
    )
    insert_summary_transaction(
        db_conn,
        context=nc_committee_a,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000226"),
        transaction_type="24E",
        amount=Decimal("20.00"),
        source_record_id=nc_committee_a.source_record_id,
        support_oppose="S",
        aggregate_amount=Decimal("20.00"),
    )
    insert_summary_transaction(
        db_conn,
        context=ca_committee,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000227"),
        transaction_type="15",
        amount=Decimal("55.00"),
        source_record_id=ca_committee.source_record_id,
    )

    nc_response = api_client.get("/v1/campaign-finance/states/NC")
    ca_response = api_client.get("/v1/campaign-finance/states/CA")
    missing_response = api_client.get("/v1/campaign-finance/states/ZZ")
    lowercase_response = api_client.get("/v1/campaign-finance/states/nc")

    assert nc_response.status_code == 200
    nc_payload = nc_response.json()
    assert nc_payload["state_code"] == "NC"
    assert nc_payload["total_raised"] == "390.00"
    assert nc_payload["total_spent"] == "130.00"
    assert nc_payload["net"] == "260.00"
    assert nc_payload["transaction_count"] == 6
    assert nc_payload["committee_count"] == 2
    assert nc_payload["federal_candidate_count"] == 2
    assert nc_payload["ie_support_total"] == "20.00"
    assert nc_payload["ie_oppose_total"] == "80.00"
    assert nc_payload["ie_support_count"] == 1
    assert nc_payload["ie_oppose_count"] == 1
    assert nc_payload["supported"] is True
    assert nc_payload["data_through"] == "2026-03-26T12:00:00Z"
    assert nc_payload["top_candidates"] == [
        {
            "candidate_id": str(nc_candidate_one),
            "candidate_name": "NC Candidate One",
            "total_raised": "200.00",
        },
        {
            "candidate_id": str(nc_candidate_two),
            "candidate_name": "NC Candidate Two",
            "total_raised": "190.00",
        },
    ]
    assert nc_payload["top_committees"] == [
        {
            "committee_id": str(nc_committee_a.committee_id),
            "committee_name": "NC Committee A",
            "total_raised": "270.00",
        },
        {
            "committee_id": str(nc_committee_b.committee_id),
            "committee_name": "NC Committee B",
            "total_raised": "120.00",
        },
    ]
    assert nc_payload["top_ie_spenders"] == [
        {
            "committee_id": str(nc_committee_b.committee_id),
            "committee_name": "NC Committee B",
            "total_amount": "80.00",
        },
        {
            "committee_id": str(nc_committee_a.committee_id),
            "committee_name": "NC Committee A",
            "total_amount": "20.00",
        },
    ]
    assert [source["source_record_key"] for source in nc_payload["sources"]] == [
        f"summary-sr-{nc_committee_b.committee_id}",
        f"summary-sr-{nc_committee_a.committee_id}",
    ]
    assert all(
        set(source)
        == {
            "domain",
            "jurisdiction",
            "data_source_name",
            "data_source_url",
            "source_record_key",
            "record_url",
            "pull_date",
        }
        for source in nc_payload["sources"]
    )
    assert all(source["jurisdiction"] == "state/nc" for source in nc_payload["sources"])

    assert ca_response.status_code == 200
    ca_payload = ca_response.json()
    assert ca_payload["state_code"] == "CA"
    assert [source["source_record_key"] for source in ca_payload["sources"]] == [
        f"summary-sr-{ca_committee.committee_id}"
    ]
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "State not found"}
    assert lowercase_response.status_code == 422
    assert lowercase_response.json()["detail"][0]["loc"] == ["path", "state_code"]


def test_state_ie_aggregate_excludes_outlier_spenders_and_reports_count(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    normal_committee = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d7777701-7777-7777-7777-777777777701"),
        committee_name="NC Normal IE Spender",
        fec_committee_id="C99707771",
        state="NC",
        jurisdiction="state/nc",
        pull_date=datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc),
    )
    ceiling_committee = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d7777702-7777-7777-7777-777777777702"),
        committee_name="NC Ceiling IE Spender",
        fec_committee_id="C99707772",
        state="NC",
        jurisdiction="state/nc",
        pull_date=datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc),
    )
    outlier_committee = seed_committee_for_summary(
        db_conn,
        committee_id=UUID("d7777703-7777-7777-7777-777777777703"),
        committee_name="NC Outlier IE Spender",
        fec_committee_id="C99707773",
        state="NC",
        jurisdiction="state/nc",
        pull_date=datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc),
    )

    seeded_contexts = (normal_committee, ceiling_committee, outlier_committee)
    transaction_seeds = (
        (normal_committee, UUID("d0000000-0000-0000-0000-000000000701"), "S", Decimal("20.00")),
        (ceiling_committee, UUID("d0000000-0000-0000-0000-000000000702"), "O", Decimal("100000000.00")),
        (outlier_committee, UUID("d0000000-0000-0000-0000-000000000703"), "S", Decimal("9980000000.00")),
    )
    transaction_ids = [transaction_id for _, transaction_id, _, _ in transaction_seeds]

    try:
        for context, transaction_id, support_oppose, amount in transaction_seeds:
            insert_summary_transaction(
                db_conn,
                context=context,
                transaction_id=transaction_id,
                transaction_type="24E",
                amount=amount,
                source_record_id=context.source_record_id,
                support_oppose=support_oppose,
                aggregate_amount=amount,
            )

        response = api_client.get("/v1/campaign-finance/states/NC")
    finally:
        with db_conn.cursor() as cursor:
            cursor.execute("DELETE FROM cf.transaction WHERE id = ANY(%s)", (transaction_ids,))
            cursor.execute(
                "DELETE FROM cf.filing WHERE id = ANY(%s)",
                ([UUID(f"20000000-0000-0000-0000-{context.committee_id.hex[:12]}") for context in seeded_contexts],),
            )
            cursor.execute(
                "DELETE FROM core.source_record WHERE id = ANY(%s)",
                ([context.source_record_id for context in seeded_contexts],),
            )
            cursor.execute(
                "DELETE FROM core.data_source WHERE id = ANY(%s)",
                ([context.data_source_id for context in seeded_contexts],),
            )
            cursor.execute(
                "DELETE FROM cf.committee WHERE id = ANY(%s)",
                ([context.committee_id for context in seeded_contexts],),
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["excluded_outlier_count"] == 1
    assert payload["top_ie_spenders"] == [
        {
            "committee_id": str(ceiling_committee.committee_id),
            "committee_name": "NC Ceiling IE Spender",
            "total_amount": "100000000.00",
        },
        {
            "committee_id": str(normal_committee.committee_id),
            "committee_name": "NC Normal IE Spender",
            "total_amount": "20.00",
        },
    ]


def test_get_filing_returns_direct_provenance(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    organization = Organization(canonical_name="Filing Committee Organization")
    insert_organization(db_conn, organization)
    person = Person(canonical_name="Filing Candidate Person")
    insert_person(db_conn, person)

    candidate_id = UUID("00000000-0000-0000-0000-000000000971")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC01004",
            name="Filing Candidate",
            office="H",
            person_id=person.id,
        ),
    )

    committee_data_source = insert_data_source_for_test(db_conn, jurisdiction="state/co", name_suffix=str(uuid4()))
    committee_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000972"),
        data_source_id=committee_data_source.id,
        source_record_key="filing-committee-source",
        source_url="https://example.org/record/filing-committee-source",
        pull_date=datetime(2026, 3, 14, 11, 0, tzinfo=timezone.utc),
    )
    insert_entity_source(db_conn, "organization", organization.id, committee_source.id, "committee")

    committee_id = UUID("00000000-0000-0000-0000-000000000973")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C12345684",
            name="Filing Committee",
            organization_id=organization.id,
            source_record_id=committee_source.id,
        ),
    )

    filing_data_source = insert_data_source_for_test(db_conn, jurisdiction="federal/fec", name_suffix=str(uuid4()))
    filing_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000974"),
        data_source_id=filing_data_source.id,
        source_record_key="filing-direct-source",
        source_url="https://example.org/record/filing-direct-source",
        pull_date=datetime(2026, 3, 16, 11, 0, tzinfo=timezone.utc),
    )

    original_filing_id = UUID("00000000-0000-0000-0000-000000000975")
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=original_filing_id,
            filing_fec_id="FILING-ORIGINAL-0001",
            committee_id=committee_id,
            amendment_indicator="N",
        ),
    )

    filing_id = UUID("00000000-0000-0000-0000-000000000970")
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id="FILING-DIRECT-0001",
            committee_id=committee_id,
            candidate_id=candidate_id,
            report_type="Q1",
            amendment_indicator="A",
            filing_name="Quarterly Filing",
            coverage_start_date=datetime(2026, 1, 1, tzinfo=timezone.utc).date(),
            coverage_end_date=datetime(2026, 3, 31, tzinfo=timezone.utc).date(),
            due_date=datetime(2026, 4, 15, tzinfo=timezone.utc).date(),
            receipt_date=datetime(2026, 4, 17, tzinfo=timezone.utc).date(),
            accepted_date=datetime(2026, 4, 18, tzinfo=timezone.utc).date(),
            amended_from_filing_id=original_filing_id,
            source_record_id=filing_source.id,
        ),
    )

    response = api_client.get(f"/v1/filings/{filing_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(filing_id)
    assert payload["filing_fec_id"] == "FILING-DIRECT-0001"
    assert payload["committee_id"] == str(committee_id)
    assert payload["candidate_id"] == str(candidate_id)
    assert payload["report_type"] == "Q1"
    assert payload["amendment_indicator"] == "A"
    assert payload["filing_name"] == "Quarterly Filing"
    assert payload["coverage_start_date"] == "2026-01-01"
    assert payload["coverage_end_date"] == "2026-03-31"
    assert payload["due_date"] == "2026-04-15"
    assert payload["receipt_date"] == "2026-04-17"
    assert payload["accepted_date"] == "2026-04-18"
    assert payload["is_amended"] is True
    assert payload["amended_from_filing_id"] == str(original_filing_id)
    assert payload["days_late"] == 2
    assert payload["sources"] == [
        {
            "domain": "campaign_finance",
            "jurisdiction": "federal/fec",
            "data_source_name": filing_data_source.name,
            "data_source_url": filing_data_source.source_url,
            "source_record_key": "filing-direct-source",
            "record_url": "https://example.org/record/filing-direct-source",
            "pull_date": "2026-03-16T11:00:00Z",
        }
    ]
    assert "source_record_id" not in payload
    assert "created_at" not in payload
    assert "updated_at" not in payload


def test_get_filing_falls_back_to_committee_provenance_when_row_source_missing(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    organization = Organization(canonical_name="Fallback Filing Organization")
    insert_organization(db_conn, organization)

    data_source = insert_data_source_for_test(db_conn, jurisdiction="state/nc", name_suffix=str(uuid4()))
    committee_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000981"),
        data_source_id=data_source.id,
        source_record_key="filing-fallback-committee-shared",
        source_url="https://example.org/record/filing-fallback-committee-shared",
        pull_date=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
    )
    entity_newer_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("00000000-0000-0000-0000-000000000982"),
        data_source_id=data_source.id,
        source_record_key="filing-fallback-entity-newer",
        source_url="https://example.org/record/filing-fallback-entity-newer",
        pull_date=datetime(2026, 3, 16, 10, 0, tzinfo=timezone.utc),
    )
    insert_entity_source(db_conn, "organization", organization.id, committee_source.id, "committee")
    insert_entity_source(db_conn, "organization", organization.id, committee_source.id, "recipient")
    insert_entity_source(db_conn, "organization", organization.id, entity_newer_source.id, "committee")

    committee_id = UUID("00000000-0000-0000-0000-000000000980")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C12345685",
            name="Fallback Filing Committee",
            organization_id=organization.id,
            source_record_id=committee_source.id,
        ),
    )

    filing_id = UUID("00000000-0000-0000-0000-000000000983")
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id="FILING-FALLBACK-0001",
            committee_id=committee_id,
            source_record_id=None,
        ),
    )

    response = api_client.get(f"/v1/filings/{filing_id}")

    assert response.status_code == 200
    payload = response.json()
    assert [source["source_record_key"] for source in payload["sources"]] == [
        "filing-fallback-entity-newer",
        "filing-fallback-committee-shared",
    ]


def test_get_filing_returns_404_for_missing_filing(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/filings/{uuid4()}")

    assert response.status_code == 404


def test_get_filing_rejects_malformed_uuid(api_client: TestClient) -> None:
    response = api_client.get("/v1/filings/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "filing_id"]


def test_list_transactions_returns_empty_result_set(api_client: TestClient) -> None:
    response = api_client.get("/v1/transactions", params={"committee_id": str(uuid4())})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    ("params", "message_fragment", "expected_ctx_error"),
    [
        (
            {"min_date": "2026-03-16", "max_date": "2026-03-15"},
            "min_date must be less than or equal to max_date",
            "min_date must be less than or equal to max_date",
        ),
        (
            {"min_amount": "200", "max_amount": "100"},
            "min_amount must be less than or equal to max_amount",
            "min_amount must be less than or equal to max_amount",
        ),
        ({"limit": "0"}, "greater than or equal to 1", None),
        ({"offset": "-1"}, "greater than or equal to 0", None),
    ],
)
def test_list_transactions_rejects_invalid_query_ranges_and_bounds(
    api_client: TestClient,
    params: dict[str, str],
    message_fragment: str,
    expected_ctx_error: str | None,
) -> None:
    response = api_client.get("/v1/transactions", params=params)

    assert response.status_code == 422
    payload = response.json()
    assert message_fragment in response.text
    assert payload["detail"][0]["msg"].endswith(message_fragment)
    if expected_ctx_error is None:
        assert payload["detail"][0].get("ctx") is None or "error" not in payload["detail"][0]["ctx"]
    else:
        assert payload["detail"][0]["ctx"]["error"] == expected_ctx_error


def test_list_transactions_uses_deterministic_default_sort_and_stable_pagination(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    # Integration DBs may contain preloaded transactions; clear table scope so pagination
    # assertions validate only this fixture's deterministic ordering guarantees.
    db_conn.execute("DELETE FROM cf.transaction")
    fixture_ids = seed_transactions_for_filters(db_conn)

    first_page = api_client.get("/v1/transactions", params={"limit": 2, "offset": 0})
    second_page = api_client.get("/v1/transactions", params={"limit": 2, "offset": 2})

    assert first_page.status_code == 200
    assert second_page.status_code == 200

    first_page_payload = first_page.json()
    second_page_payload = second_page.json()

    assert [row["id"] for row in first_page_payload] == [
        str(fixture_ids["transaction_a"]),
        str(fixture_ids["transaction_b"]),
    ]
    assert [row["id"] for row in second_page_payload] == [
        str(fixture_ids["transaction_c"]),
        str(fixture_ids["transaction_d"]),
    ]
    assert "sub_id" not in first_page_payload[0]
    assert "memo_code" not in first_page_payload[0]
    assert "amended_by_transaction_id" not in first_page_payload[0]
    assert "created_at" not in first_page_payload[0]
    assert "updated_at" not in first_page_payload[0]

    # IE row (transaction_a) returns populated IE fields
    ie_row = first_page_payload[0]
    assert ie_row["support_oppose"] == "O"
    assert ie_row["dissemination_date"] == "2026-03-10"
    assert ie_row["aggregate_amount"] == pytest.approx(5000.00)

    # Non-IE row (transaction_b) returns null IE fields
    non_ie_row = first_page_payload[1]
    assert non_ie_row["support_oppose"] is None
    assert non_ie_row["dissemination_date"] is None
    assert non_ie_row["aggregate_amount"] is None


def test_list_transactions_filters_by_committee_and_inclusive_ranges(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_transactions_for_filters(db_conn)

    response = api_client.get(
        "/v1/transactions",
        params={
            "committee_id": str(fixture_ids["committee_a"]),
            "min_date": "2026-03-14",
            "max_date": "2026-03-15",
            "min_amount": "100",
            "max_amount": "120",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [row["id"] for row in payload] == [str(fixture_ids["transaction_a"])]


def test_list_transactions_filters_by_jurisdiction_via_source_record_chain(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_transactions_for_filters(db_conn)

    response = api_client.get("/v1/transactions", params={"jurisdiction": "state/co"})

    assert response.status_code == 200
    payload = response.json()
    assert [row["id"] for row in payload] == [
        str(fixture_ids["transaction_a"]),
        str(fixture_ids["transaction_c"]),
    ]


def test_list_transactions_includes_null_source_rows_when_unfiltered_but_excludes_them_when_jurisdiction_filtered(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture_ids = seed_transactions_for_filters(db_conn)

    unfiltered = api_client.get("/v1/transactions")
    jurisdiction_filtered = api_client.get("/v1/transactions", params={"jurisdiction": "state/co"})

    assert unfiltered.status_code == 200
    assert jurisdiction_filtered.status_code == 200

    unfiltered_ids = [row["id"] for row in unfiltered.json()]
    filtered_ids = [row["id"] for row in jurisdiction_filtered.json()]

    assert str(fixture_ids["transaction_d"]) in unfiltered_ids
    assert str(fixture_ids["transaction_d"]) not in filtered_ids


# ---------------------------------------------------------------------------
# Committee fundraising summary aggregation
# ---------------------------------------------------------------------------

SUMMARY_COMMITTEE_ID = UUID("a0000000-0000-0000-0000-000000000001")


def test_summary_aggregates_raised_spent_net_and_count(
    db_conn: psycopg.Connection,
) -> None:
    """Receipts (type prefix '1') go to total_raised, disbursements ('2') to total_spent."""
    source_record_id = UUID(f"10000000-0000-0000-0000-{SUMMARY_COMMITTEE_ID.hex[:12]}")
    ctx = seed_committee_for_summary(db_conn, committee_id=SUMMARY_COMMITTEE_ID)

    # Two receipts, one disbursement
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",  # receipt
        amount=Decimal("1000.00"),
        source_record_id=source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15E",  # receipt
        amount=Decimal("500.50"),
        source_record_id=source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="24A",  # disbursement
        amount=Decimal("200.25"),
        source_record_id=source_record_id,
    )

    result = fetch_committee_fundraising_summary(db_conn, SUMMARY_COMMITTEE_ID)

    assert result is not None
    assert result["total_raised"] == Decimal("1500.50")
    assert result["total_spent"] == Decimal("200.25")
    assert result["net"] == Decimal("1300.25")
    assert str(result["total_raised"]) == "1500.50"
    assert str(result["total_spent"]) == "200.25"
    assert str(result["net"]) == "1300.25"
    assert result["transaction_count"] == 3
    assert result["committee_name"] == "Summary Test Committee"


def test_summary_computes_stage4_receipt_splits_rankings_and_spend_categories(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000008")
    ctx = seed_committee_for_summary(db_conn, committee_id=committee_id, fec_committee_id="C99990008")
    summary_filing_id = UUID(f"20000000-0000-0000-0000-{committee_id.hex[:12]}")

    seeded_transactions = (
        TransactionRowSeed(
            id=UUID("a0000000-0000-0000-0000-000000000801"),
            filing_id=summary_filing_id,
            committee_id=committee_id,
            transaction_type="15",
            amount=Decimal("100.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            source_record_id=ctx.source_record_id,
            contributor_name_raw="Donor One",
        ),
        TransactionRowSeed(
            id=UUID("a0000000-0000-0000-0000-000000000802"),
            filing_id=summary_filing_id,
            committee_id=committee_id,
            transaction_type="15",
            amount=Decimal("25.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            source_record_id=ctx.source_record_id,
            contributor_name_raw="Donor One",
        ),
        TransactionRowSeed(
            id=UUID("a0000000-0000-0000-0000-000000000803"),
            filing_id=summary_filing_id,
            committee_id=committee_id,
            transaction_type="15Z",
            amount=Decimal("30.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            source_record_id=ctx.source_record_id,
            contributor_name_raw="Donor Two",
        ),
        TransactionRowSeed(
            id=UUID("a0000000-0000-0000-0000-000000000804"),
            filing_id=summary_filing_id,
            committee_id=committee_id,
            transaction_type="16G",
            amount=Decimal("20.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            source_record_id=ctx.source_record_id,
            contributor_name_raw="Lender LLC",
        ),
        TransactionRowSeed(
            id=UUID("a0000000-0000-0000-0000-000000000805"),
            filing_id=summary_filing_id,
            committee_id=committee_id,
            transaction_type="24A",
            amount=Decimal("40.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            source_record_id=ctx.source_record_id,
            contributor_name_raw="Vendor Alpha",
            memo_text="Media",
        ),
        TransactionRowSeed(
            id=UUID("a0000000-0000-0000-0000-000000000806"),
            filing_id=summary_filing_id,
            committee_id=committee_id,
            transaction_type="24E",
            amount=Decimal("15.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            source_record_id=ctx.source_record_id,
            contributor_name_raw="Vendor Beta",
            memo_text="Field",
        ),
        TransactionRowSeed(
            id=UUID("a0000000-0000-0000-0000-000000000807"),
            filing_id=summary_filing_id,
            committee_id=committee_id,
            transaction_type="24A",
            amount=Decimal("10.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            source_record_id=ctx.source_record_id,
            contributor_name_raw="Vendor Alpha",
            memo_text="Media",
        ),
        TransactionRowSeed(
            id=UUID("a0000000-0000-0000-0000-000000000808"),
            filing_id=summary_filing_id,
            committee_id=committee_id,
            transaction_type="24A",
            amount=Decimal("5.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            source_record_id=ctx.source_record_id,
            contributor_name_raw="Vendor Alpha",
            memo_text=None,
        ),
    )
    for transaction in seeded_transactions:
        insert_transaction_row(db_conn, transaction)

    result = fetch_committee_fundraising_summary(db_conn, committee_id)

    assert result is not None
    assert result["cash_receipts_total"] == Decimal("125.00")
    assert result["in_kind_receipts_total"] == Decimal("30.00")
    assert result["loan_receipts_total"] == Decimal("20.00")
    assert result["contribution_receipts_total"] == Decimal("155.00")
    assert result["top_donors"] == [
        {"name": "Donor One", "total_amount": Decimal("125.00"), "transaction_count": 2},
        {"name": "Donor Two", "total_amount": Decimal("30.00"), "transaction_count": 1},
        {"name": "Lender LLC", "total_amount": Decimal("20.00"), "transaction_count": 1},
    ]
    assert result["top_vendors"] == [
        {"name": "Vendor Alpha", "total_amount": Decimal("55.00"), "transaction_count": 3},
        {"name": "Vendor Beta", "total_amount": Decimal("15.00"), "transaction_count": 1},
    ]
    assert result["spend_categories"] == [
        {"category": "media", "total_amount": Decimal("50.00"), "transaction_count": 2},
        {"category": "field", "total_amount": Decimal("15.00"), "transaction_count": 1},
    ]


def test_summary_excludes_memo_transactions(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000002")
    source_record_id = UUID(f"10000000-0000-0000-0000-{committee_id.hex[:12]}")
    ctx = seed_committee_for_summary(db_conn, committee_id=committee_id, fec_committee_id="C99990002")

    # Normal receipt
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("1000.00"),
        source_record_id=source_record_id,
    )
    # Memo receipt — should be excluded
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("9999.99"),
        source_record_id=source_record_id,
        is_memo=True,
    )

    result = fetch_committee_fundraising_summary(db_conn, committee_id)

    assert result is not None
    assert result["total_raised"] == Decimal("1000.00")
    assert result["transaction_count"] == 1


def test_summary_excludes_terminated_amendment_transactions(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000003")
    source_record_id = UUID(f"10000000-0000-0000-0000-{committee_id.hex[:12]}")
    ctx = seed_committee_for_summary(db_conn, committee_id=committee_id, fec_committee_id="C99990003")

    # Normal receipt
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("500.00"),
        source_record_id=source_record_id,
    )
    # Terminated amendment — should be excluded
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("7777.77"),
        source_record_id=source_record_id,
        amendment_indicator="T",
    )

    result = fetch_committee_fundraising_summary(db_conn, committee_id)

    assert result is not None
    assert result["total_raised"] == Decimal("500.00")
    assert result["transaction_count"] == 1


def test_summary_derives_jurisdiction_and_data_through_from_provenance_chain(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000004")
    pull = datetime(2026, 3, 19, 8, 30, tzinfo=timezone.utc)
    source_record_id = UUID(f"10000000-0000-0000-0000-{committee_id.hex[:12]}")
    ctx = seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        fec_committee_id="C99990004",
        jurisdiction="state/nc",
        pull_date=pull,
    )

    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("100.00"),
        source_record_id=source_record_id,
    )

    result = fetch_committee_fundraising_summary(db_conn, committee_id)

    assert result is not None
    assert result["jurisdiction"] == "state/nc"
    assert result["data_through"] == pull


def test_state_summary_derives_data_through_from_latest_qualifying_provenance_chain(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("d6666666-6666-6666-6666-666666666666")
    old_pull = datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc)
    new_pull = datetime(2026, 3, 24, 9, 0, tzinfo=timezone.utc)
    context = seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        committee_name="NC State Summary Provenance",
        fec_committee_id="C99700666",
        state="NC",
        jurisdiction="state/nc",
        pull_date=old_pull,
    )
    new_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("d1000000-0000-0000-0000-000000000301"),
        data_source_id=context.data_source_id,
        source_record_key="state-summary-provenance-new",
        source_url="https://example.org/record/state-summary-provenance-new",
        pull_date=new_pull,
    )
    superseded_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("d1000000-0000-0000-0000-000000000302"),
        data_source_id=context.data_source_id,
        source_record_key="state-summary-provenance-superseded",
        source_url="https://example.org/record/state-summary-provenance-superseded",
        pull_date=datetime(2026, 3, 25, 9, 0, tzinfo=timezone.utc),
        superseded_by=new_source.id,
    )

    insert_summary_transaction(
        db_conn,
        context=context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000311"),
        transaction_type="15",
        amount=Decimal("100.00"),
        source_record_id=context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000312"),
        transaction_type="15",
        amount=Decimal("50.00"),
        source_record_id=new_source.id,
    )
    insert_summary_transaction(
        db_conn,
        context=context,
        transaction_id=UUID("d0000000-0000-0000-0000-000000000313"),
        transaction_type="15",
        amount=Decimal("250.00"),
        source_record_id=superseded_source.id,
    )

    assert hasattr(campaign_finance_queries, "fetch_state_campaign_finance_summaries")
    summary_rows = campaign_finance_queries.fetch_state_campaign_finance_summaries(db_conn)
    nc_row = next(row for row in summary_rows if row["state_code"] == "NC")

    assert nc_row["total_raised"] == Decimal("150.00")
    assert nc_row["transaction_count"] == 2
    assert nc_row["data_through"] == new_pull


def test_summary_aggregates_mixed_provenance_rows_without_dropping_transactions(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000005")
    source_record_id = UUID(f"10000000-0000-0000-0000-{committee_id.hex[:12]}")
    pull = datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc)
    ctx = seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        fec_committee_id="C99990005",
        jurisdiction="state/co",
        pull_date=pull,
    )

    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("100.00"),
        source_record_id=None,
    )
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("50.00"),
        source_record_id=source_record_id,
    )

    result = fetch_committee_fundraising_summary(db_conn, committee_id)

    assert result is not None
    assert result["total_raised"] == Decimal("150.00")
    assert result["total_spent"] == Decimal("0.00")
    assert result["net"] == Decimal("150.00")
    assert result["transaction_count"] == 2
    assert result["jurisdiction"] == "state/co"
    assert result["data_through"] == pull


def test_summary_excludes_transactions_backed_by_superseded_source_records(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000007")
    superseded_source_record_id = UUID("10000000-0000-0000-0000-000000000777")
    pull = datetime(2026, 3, 20, 11, 0, tzinfo=timezone.utc)
    ctx = seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        fec_committee_id="C99990007",
        jurisdiction="state/nc",
        pull_date=pull,
    )
    insert_source_record_for_test(
        db_conn,
        source_record_id=superseded_source_record_id,
        data_source_id=ctx.data_source_id,
        source_record_key=f"summary-sr-{committee_id}",
        source_url="https://example.org/summary-superseded",
        pull_date=datetime(2026, 3, 18, 11, 0, tzinfo=timezone.utc),
        superseded_by=ctx.source_record_id,
    )

    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("100.00"),
        source_record_id=ctx.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("250.00"),
        source_record_id=superseded_source_record_id,
    )

    result = fetch_committee_fundraising_summary(db_conn, committee_id)

    assert result is not None
    assert result["total_raised"] == Decimal("100.00")
    assert result["total_spent"] == Decimal("0.00")
    assert result["net"] == Decimal("100.00")
    assert result["transaction_count"] == 1
    assert result["jurisdiction"] == "state/nc"
    assert result["data_through"] == pull


def test_summary_data_through_is_latest_non_superseded_pull_date(
    db_conn: psycopg.Connection,
) -> None:
    """``data_through`` is the MAX pull_date across the committee's non-superseded
    qualifying source records — and a superseded record is ignored even when it
    carries the newest pull_date. Guards the ``latest_provenance`` rewrite so it
    cannot silently pick the wrong (or a superseded) provenance row.
    """
    committee_id = UUID("a0000000-0000-0000-0000-000000000009")
    older_pull = datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc)
    newer_pull = datetime(2026, 3, 22, 8, 0, tzinfo=timezone.utc)
    ctx = seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        fec_committee_id="C99990009",
        jurisdiction="state/nc",
        pull_date=older_pull,
    )
    newer_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("10000000-0000-0000-0000-000000000909"),
        data_source_id=ctx.data_source_id,
        source_record_key=f"summary-newer-{committee_id}",
        source_url="https://example.org/summary-newer",
        pull_date=newer_pull,
    )
    superseding_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("10000000-0000-0000-0000-000000000910"),
        data_source_id=ctx.data_source_id,
        source_record_key=f"summary-superseding-{committee_id}",
        source_url="https://example.org/summary-superseding",
        pull_date=datetime(2026, 3, 30, 8, 0, tzinfo=timezone.utc),
    )
    superseded_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("10000000-0000-0000-0000-000000000911"),
        data_source_id=ctx.data_source_id,
        source_record_key=f"summary-superseded-{committee_id}",
        source_url="https://example.org/summary-superseded",
        # Newest pull_date of all, but superseded — must be excluded from data_through.
        pull_date=datetime(2026, 3, 31, 8, 0, tzinfo=timezone.utc),
        superseded_by=superseding_source.id,
    )

    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("100.00"),
        source_record_id=ctx.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("50.00"),
        source_record_id=newer_source.id,
    )
    insert_summary_transaction(
        db_conn,
        context=ctx,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=Decimal("999.00"),
        source_record_id=superseded_source.id,
    )

    result = fetch_committee_fundraising_summary(db_conn, committee_id)

    assert result is not None
    # Superseded 999.00 receipt excluded; only the two non-superseded receipts count.
    assert result["total_raised"] == Decimal("150.00")
    assert result["transaction_count"] == 2
    assert result["jurisdiction"] == "state/nc"
    # MAX pull_date across the two non-superseded source records (not the superseded newest).
    assert result["data_through"] == newer_pull


def _insert_stage_one_summary_transactions(
    db_conn: psycopg.Connection,
    *,
    context: SummaryTestContext,
    newer_source_id: UUID,
) -> None:
    filing_id = UUID(f"20000000-0000-0000-0000-{context.committee_id.hex[:12]}")
    row_specs = [
        ("000000000901", "15", "125.00", context.source_record_id, "Donor Alpha", None),
        ("000000000902", "15", "75.00", newer_source_id, "Donor Alpha", None),
        ("000000000903", "15", "50.00", newer_source_id, "Donor Beta", None),
        ("000000000904", "24A", "40.00", newer_source_id, "Vendor Alpha", "Media"),
        ("000000000905", "24A", "10.00", context.source_record_id, "Vendor Beta", "Field"),
    ]
    for suffix, transaction_type, amount, source_record_id, contributor_name, memo_text in row_specs:
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=UUID(f"a0000000-0000-0000-0000-{suffix}"),
                filing_id=filing_id,
                committee_id=context.committee_id,
                transaction_type=transaction_type,
                amount=Decimal(amount),
                amendment_indicator="N",
                transaction_date=date(2026, 3, 15),
                source_record_id=source_record_id,
                contributor_name_raw=contributor_name,
                memo_text=memo_text,
            ),
        )


def _insert_stage_one_official_cycle_rows(db_conn: psycopg.Connection, committee_id: UUID) -> None:
    cycle_specs = [
        (2024, "1000.00", "300.00", "700.00", date(2023, 1, 1), date(2024, 12, 31)),
        (2026, "2000.00", "700.00", "1300.00", date(2025, 1, 1), date(2026, 6, 30)),
    ]
    for cycle, receipts, disbursements, cash_on_hand, coverage_start, coverage_end in cycle_specs:
        insert_committee_summary_row(
            db_conn,
            CommitteeSummaryRowSeed(
                committee_id=committee_id,
                cycle=cycle,
                total_receipts=Decimal(receipts),
                total_disbursements=Decimal(disbursements),
                cash_on_hand=Decimal(cash_on_hand),
                coverage_start_date=coverage_start,
                coverage_end_date=coverage_end,
            ),
        )


def test_fetch_committee_summary_preserves_official_totals_rankings_categories_and_latest_provenance(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000901")
    older_pull = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    newer_pull = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    context = seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        committee_name="Stage One Official Totals Committee",
        fec_committee_id="C99990901",
        jurisdiction="federal/fec",
        pull_date=older_pull,
    )
    newer_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("10000000-0000-0000-0000-000000000901"),
        data_source_id=context.data_source_id,
        source_record_key=f"stage-one-newer-{committee_id}",
        source_url="https://example.org/stage-one/newer",
        pull_date=newer_pull,
    )
    _insert_stage_one_summary_transactions(db_conn, context=context, newer_source_id=newer_source.id)
    _insert_stage_one_official_cycle_rows(db_conn, committee_id)

    result = fetch_committee_fundraising_summary(db_conn, committee_id)

    assert result is not None
    assert result["summary_source"] == "fec_committee_summary"
    assert result["total_raised"] == Decimal("2000.00")
    assert result["total_spent"] == Decimal("700.00")
    assert result["net"] == Decimal("1300.00")
    assert result["transaction_count"] == 5
    assert result["itemized_transaction_count"] == 5
    assert result["data_through"] == newer_pull
    assert result["top_donors"][:2] == [
        {"name": "Donor Alpha", "total_amount": Decimal("200.00"), "transaction_count": 2},
        {"name": "Donor Beta", "total_amount": Decimal("50.00"), "transaction_count": 1},
    ]
    assert result["top_vendors"][:2] == [
        {"name": "Vendor Alpha", "total_amount": Decimal("40.00"), "transaction_count": 1},
        {"name": "Vendor Beta", "total_amount": Decimal("10.00"), "transaction_count": 1},
    ]
    assert result["spend_categories"] == [
        {"category": "media", "total_amount": Decimal("40.00"), "transaction_count": 1},
        {"category": "field", "total_amount": Decimal("10.00"), "transaction_count": 1},
    ]
    assert result["cycle_summaries"] == [
        {
            "cycle": 2026,
            "total_receipts": Decimal("2000.00"),
            "total_disbursements": Decimal("700.00"),
            "cash_on_hand": Decimal("1300.00"),
            "coverage_start_date": date(2025, 1, 1),
            "coverage_end_date": date(2026, 6, 30),
        },
    ]


def test_fetch_committee_summary_reads_refresh_backed_derived_aggregate(
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000921")
    data_through = datetime(2026, 7, 12, 9, 30, tzinfo=timezone.utc)
    seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        committee_name="Refresh Backed Committee",
        fec_committee_id="C99990921",
        jurisdiction="federal/fec",
        pull_date=data_through,
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=Decimal("1000.00"),
            total_disbursements=Decimal("250.00"),
            cash_on_hand=Decimal("750.00"),
            coverage_start_date=date(2025, 1, 1),
            coverage_end_date=date(2026, 6, 30),
        ),
    )
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE cf.committee_summary
            SET derived_total_raised = 610.00,
                derived_total_spent = 210.00,
                derived_net = 400.00,
                derived_transaction_count = 7,
                derived_cash_receipts_total = 500.00,
                derived_in_kind_receipts_total = 40.00,
                derived_loan_receipts_total = 70.00,
                derived_contribution_receipts_total = 540.00,
                derived_jurisdiction = 'federal/fec',
                derived_data_through = %s
            WHERE committee_id = %s
              AND cycle = 2026
            """,
            (data_through, committee_id),
        )

    result = fetch_committee_fundraising_summary(db_conn, committee_id)

    assert result is not None
    assert result["summary_source"] == "fec_committee_summary"
    assert result["total_raised"] == Decimal("1000.00")
    assert result["total_spent"] == Decimal("250.00")
    assert result["net"] == Decimal("750.00")
    assert result["transaction_count"] == 7
    assert result["itemized_transaction_count"] == 7
    assert result["cash_receipts_total"] == Decimal("500.00")
    assert result["in_kind_receipts_total"] == Decimal("40.00")
    assert result["loan_receipts_total"] == Decimal("70.00")
    assert result["contribution_receipts_total"] == Decimal("540.00")
    assert result["jurisdiction"] == "federal/fec"
    assert result["data_through"] == data_through
    assert result["top_donors"] == []
    assert result["top_vendors"] == []
    assert result["spend_categories"] is None


def _committee_money_aggregate_calculation_scopes(sql: str) -> list[str]:
    scopes: list[str] = []
    for total_raised_alias in re.finditer(r"\bAS\s+total_raised\b", sql, flags=re.IGNORECASE):
        select_start = sql.rfind("SELECT", 0, total_raised_alias.start())
        if select_start == -1:
            continue

        group_by = re.search(r"\bGROUP\s+BY\b", sql[total_raised_alias.end() :], flags=re.IGNORECASE)
        scope_end = total_raised_alias.end() + group_by.start() if group_by is not None else len(sql)
        scope = sql[select_start:scope_end]
        if "SUM(" in scope.upper():
            scopes.append(scope)
    return scopes


def test_committee_fundraising_summary_sql_keeps_provenance_out_of_money_aggregate() -> None:
    aggregate_scopes = _committee_money_aggregate_calculation_scopes(COMMITTEE_FUNDRAISING_SUMMARY_SQL)

    assert aggregate_scopes
    assert not any("latest_provenance" in scope for scope in aggregate_scopes)


def test_committee_summary_top_lists_share_one_qualifying_transaction_scan() -> None:
    top_lists_sql = getattr(campaign_finance_query_module, "COMMITTEE_TOP_LISTS_SQL", "")

    assert top_lists_sql
    assert top_lists_sql.count("FROM cf.transaction t") == 1
    assert "qualifying_transactions AS MATERIALIZED" in top_lists_sql
    assert all(name in top_lists_sql for name in ("top_donors", "top_vendors", "spend_categories"))


def test_contribution_insights_itemized_rollups_share_one_qualifying_transaction_scan() -> None:
    rollups_sql = getattr(campaign_finance_query_module, "_PERSON_CONTRIBUTION_INSIGHTS_ITEMIZED_ROLLUPS_SQL", "")
    district_sql = getattr(campaign_finance_query_module, "_PERSON_CONTRIBUTION_INSIGHTS_DISTRICT_SQL", "")

    assert rollups_sql
    assert rollups_sql.count("FROM cf.transaction t") == 1
    assert "qualifying_transactions AS MATERIALIZED" in rollups_sql
    assert all(
        name in rollups_sql
        for name in (
            "monthly_totals",
            "state_totals",
            "totals",
            "itemized_size_buckets",
            "itemized_cycle_totals",
            "district_totals",
        )
    )
    assert rollups_sql.count("LEFT JOIN civic.zcta_district") == 1
    assert rollups_sql.count("SELECT MAX(boundary_year)") == 1
    assert district_sql.count("FROM cf.transaction t") == 1
    assert district_sql.count("CASE\n                WHEN") == 1
    assert district_sql.count("LEFT JOIN civic.zcta_district") == 1
    assert district_sql.count("SELECT MAX(boundary_year)") == 1


def test_get_committee_summary_returns_404_for_missing_committee(api_client: TestClient) -> None:
    response = api_client.get(f"/v1/committees/{uuid4()}/summary")

    assert response.status_code == 404
    assert response.json() == {"detail": "Committee not found"}


def test_get_committee_summary_returns_zero_totals_when_no_qualifying_transactions(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000006")
    committee_name = "No Summary Transactions Committee"
    seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        committee_name=committee_name,
        fec_committee_id="C99990006",
        jurisdiction="state/nc",
        pull_date=datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc),
    )

    response = api_client.get(f"/v1/committees/{committee_id}/summary")

    assert response.status_code == 200
    assert response.json() == {
        "committee_id": str(committee_id),
        "committee_name": committee_name,
        "selected_cycle": 2026,
        "coverage_start_date": "2025-01-01",
        "coverage_end_date": "2026-12-31",
        "available_cycles": [2022, 2024, 2026],
        "total_raised": "0.00",
        "total_spent": "0.00",
        "net": "0.00",
        "transaction_count": 0,
        "jurisdiction": None,
        "data_through": None,
        "cash_receipts_total": "0.00",
        "in_kind_receipts_total": "0.00",
        "loan_receipts_total": "0.00",
        "contribution_receipts_total": "0.00",
        "top_donors": [],
        "top_vendors": [],
        "spend_categories": None,
        "itemized_transaction_count": 0,
        "cycle_summaries": [],
        "summary_source": "derived",
    }


def _seed_nc_county_summary_three_transaction_fixture(
    db_conn: psycopg.Connection,
) -> CountySummaryFixtureContext:
    context = seed_county_summary_fixture(
        db_conn,
        committee_id=UUID("a2000000-0000-0000-0000-000000000001"),
        committee_name="Wake Forward PAC",
        recipient_committee_id=UUID("a2000000-0000-0000-0000-000000000002"),
        recipient_committee_name="NC Action Committee",
        candidate_id=UUID("a2000000-0000-0000-0000-000000000003"),
        candidate_name="Jordan Candidate",
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("a2000000-0000-0000-0000-000000000011"),
            filing_id=context.filing_id,
            committee_id=context.committee_id,
            transaction_type="24A",
            amount=Decimal("100.00"),
            amendment_indicator="N",
            recipient_committee_id=context.recipient_committee_id,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("a2000000-0000-0000-0000-000000000012"),
            filing_id=context.filing_id,
            committee_id=context.committee_id,
            transaction_type="15",
            amount=Decimal("999.00"),
            amendment_indicator="N",
            recipient_committee_id=context.recipient_committee_id,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("a2000000-0000-0000-0000-000000000013"),
            filing_id=context.filing_id,
            committee_id=context.committee_id,
            transaction_type="15",
            amount=Decimal("777.00"),
            amendment_indicator="T",
            recipient_committee_id=context.recipient_committee_id,
        ),
    )
    return context


def test_county_qualifying_transactions_cte_uses_disbursement_prefix_value() -> None:
    expected_like_clause = f"t.transaction_type LIKE '{DISBURSEMENT_TYPE_PREFIX}%%'"
    assert expected_like_clause in _COUNTY_PROXY_QUALIFYING_TRANSACTIONS_CTE
    assert "{DISBURSEMENT_TYPE_PREFIX}" not in _COUNTY_PROXY_QUALIFYING_TRANSACTIONS_CTE


def test_get_county_campaign_finance_summary_returns_aggregated_proxy_totals_for_mapped_county(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    context = _seed_nc_county_summary_three_transaction_fixture(db_conn)

    response = api_client.get("/v1/counties/nc/wake/campaign-finance-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "nc"
    assert payload["county_slug"] == "wake"
    assert payload["donor_total_cents"] == 10000
    assert payload["transaction_count"] == 1
    assert payload["top_recipient_committees"] == [
        {
            "committee_id": str(context.recipient_committee_id),
            "committee_name": "NC Action Committee",
            "donor_total_cents": 10000,
            "transaction_count": 1,
        }
    ]
    assert payload["top_linked_candidates"] == [
        {
            "candidate_id": str(context.candidate_id),
            "candidate_name": "Jordan Candidate",
            "donor_total_cents": 10000,
            "transaction_count": 1,
        }
    ]
    assert payload["sources"] == []


def test_get_county_campaign_finance_summary_ranks_recipients_and_candidates_with_tiebreakers(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    context = seed_county_summary_fixture(
        db_conn,
        committee_id=UUID("a2100000-0000-0000-0000-000000000001"),
        committee_name="Wake Outflow Committee",
        recipient_committee_id=UUID("a2100000-0000-0000-0000-000000000010"),
        recipient_committee_name="Recipient Seed",
        candidate_id=UUID("a2100000-0000-0000-0000-000000000020"),
        candidate_name="Candidate Seed",
    )
    recipient_alpha = seed_county_summary_recipient(
        db_conn,
        recipient_committee_id=UUID("a2100000-0000-0000-0000-000000000011"),
        recipient_committee_name="Recipient Alpha",
        recipient_committee_fec_id="C21000011",
        candidate_id=UUID("a2100000-0000-0000-0000-000000000021"),
        candidate_name="Candidate Alpha",
        candidate_fec_id="H0NC21001",
        link_id=UUID("a2100000-0000-0000-0000-000000000101"),
    )
    recipient_beta = seed_county_summary_recipient(
        db_conn,
        recipient_committee_id=UUID("a2100000-0000-0000-0000-000000000012"),
        recipient_committee_name="Recipient Beta",
        recipient_committee_fec_id="C21000012",
        candidate_id=UUID("a2100000-0000-0000-0000-000000000022"),
        candidate_name="Candidate Beta",
        candidate_fec_id="H0NC21002",
        link_id=UUID("a2100000-0000-0000-0000-000000000102"),
    )
    recipient_gamma = seed_county_summary_recipient(
        db_conn,
        recipient_committee_id=UUID("a2100000-0000-0000-0000-000000000013"),
        recipient_committee_name="Recipient Gamma",
        recipient_committee_fec_id="C21000013",
        candidate_id=UUID("a2100000-0000-0000-0000-000000000023"),
        candidate_name="Candidate Gamma",
        candidate_fec_id="H0NC21003",
        link_id=UUID("a2100000-0000-0000-0000-000000000103"),
    )
    filing_id = context.filing_id
    seeded_rows = [
        (UUID("a2100000-0000-0000-0000-000000000111"), recipient_alpha.recipient_committee_id, Decimal("80.00")),
        (UUID("a2100000-0000-0000-0000-000000000112"), recipient_alpha.recipient_committee_id, Decimal("40.00")),
        (UUID("a2100000-0000-0000-0000-000000000113"), recipient_beta.recipient_committee_id, Decimal("60.00")),
        (UUID("a2100000-0000-0000-0000-000000000114"), recipient_beta.recipient_committee_id, Decimal("60.00")),
        (UUID("a2100000-0000-0000-0000-000000000115"), recipient_gamma.recipient_committee_id, Decimal("120.00")),
    ]
    for transaction_id, recipient_committee_id, amount in seeded_rows:
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=transaction_id,
                filing_id=filing_id,
                committee_id=context.committee_id,
                transaction_type="24A",
                amount=amount,
                amendment_indicator="N",
                recipient_committee_id=recipient_committee_id,
            ),
        )

    response = api_client.get("/v1/counties/nc/wake/campaign-finance-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["donor_total_cents"] == 36000
    assert payload["transaction_count"] == 5
    assert payload["top_recipient_committees"] == [
        {
            "committee_id": str(recipient_alpha.recipient_committee_id),
            "committee_name": "Recipient Alpha",
            "donor_total_cents": 12000,
            "transaction_count": 2,
        },
        {
            "committee_id": str(recipient_beta.recipient_committee_id),
            "committee_name": "Recipient Beta",
            "donor_total_cents": 12000,
            "transaction_count": 2,
        },
        {
            "committee_id": str(recipient_gamma.recipient_committee_id),
            "committee_name": "Recipient Gamma",
            "donor_total_cents": 12000,
            "transaction_count": 1,
        },
    ]
    assert payload["top_linked_candidates"] == [
        {
            "candidate_id": str(recipient_alpha.candidate_id),
            "candidate_name": "Candidate Alpha",
            "donor_total_cents": 12000,
            "transaction_count": 2,
        },
        {
            "candidate_id": str(recipient_beta.candidate_id),
            "candidate_name": "Candidate Beta",
            "donor_total_cents": 12000,
            "transaction_count": 2,
        },
        {
            "candidate_id": str(recipient_gamma.candidate_id),
            "candidate_name": "Candidate Gamma",
            "donor_total_cents": 12000,
            "transaction_count": 1,
        },
    ]
    assert payload["sources"] == []


def test_get_county_campaign_finance_summary_excludes_memo_terminated_and_superseded_rows(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    context = seed_county_summary_fixture(
        db_conn,
        committee_id=UUID("a2200000-0000-0000-0000-000000000001"),
        committee_name="Wake Filter Committee",
        recipient_committee_id=UUID("a2200000-0000-0000-0000-000000000002"),
        recipient_committee_name="Wake Recipient",
        candidate_id=UUID("a2200000-0000-0000-0000-000000000003"),
        candidate_name="Filter Candidate",
    )
    filing_id = context.filing_id
    data_source = insert_data_source_for_test(db_conn, jurisdiction="state/nc", name_suffix="county-filter")
    replacement_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("a2200000-0000-0000-0000-000000000101"),
        data_source_id=data_source.id,
        source_record_key="county-filter-replacement",
        source_url="https://example.org/record/county-filter-replacement",
        pull_date=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
    )
    superseded_record = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("a2200000-0000-0000-0000-000000000102"),
        data_source_id=data_source.id,
        source_record_key="county-filter-superseded",
        source_url="https://example.org/record/county-filter-superseded",
        pull_date=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
        superseded_by=replacement_record.id,
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("a2200000-0000-0000-0000-000000000201"),
            filing_id=filing_id,
            committee_id=context.committee_id,
            transaction_type="24A",
            amount=Decimal("75.00"),
            amendment_indicator="N",
            source_record_id=replacement_record.id,
            recipient_committee_id=context.recipient_committee_id,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("a2200000-0000-0000-0000-000000000202"),
            filing_id=filing_id,
            committee_id=context.committee_id,
            transaction_type="24A",
            amount=Decimal("999.00"),
            amendment_indicator="N",
            recipient_committee_id=context.recipient_committee_id,
            memo_code="X",
            is_memo=True,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("a2200000-0000-0000-0000-000000000203"),
            filing_id=filing_id,
            committee_id=context.committee_id,
            transaction_type="24A",
            amount=Decimal("888.00"),
            amendment_indicator="T",
            recipient_committee_id=context.recipient_committee_id,
        ),
    )
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=UUID("a2200000-0000-0000-0000-000000000204"),
            filing_id=filing_id,
            committee_id=context.committee_id,
            transaction_type="24A",
            amount=Decimal("777.00"),
            amendment_indicator="N",
            recipient_committee_id=context.recipient_committee_id,
            source_record_id=superseded_record.id,
        ),
    )

    response = api_client.get("/v1/counties/nc/wake/campaign-finance-summary")

    assert response.status_code == 200
    assert response.json() == {
        "state": "nc",
        "county_slug": "wake",
        "donor_total_cents": 7500,
        "transaction_count": 1,
        "top_recipient_committees": [
            {
                "committee_id": str(context.recipient_committee_id),
                "committee_name": "Wake Recipient",
                "donor_total_cents": 7500,
                "transaction_count": 1,
            }
        ],
        "top_linked_candidates": [
            {
                "candidate_id": str(context.candidate_id),
                "candidate_name": "Filter Candidate",
                "donor_total_cents": 7500,
                "transaction_count": 1,
            }
        ],
        "sources": [
            {
                "domain": "campaign_finance",
                "jurisdiction": "state/nc",
                "data_source_name": data_source.name,
                "data_source_url": data_source.source_url,
                "source_record_key": "county-filter-replacement",
                "record_url": "https://example.org/record/county-filter-replacement",
                "pull_date": "2026-04-01T10:00:00Z",
            }
        ],
    }


def test_get_county_campaign_finance_summary_returns_404_for_unknown_county_slug(
    api_client: TestClient,
) -> None:
    response = api_client.get("/v1/counties/nc/not-a-county/campaign-finance-summary")

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown county slug for state: nc/not-a-county"}


def test_get_county_campaign_finance_summary_returns_zero_totals_for_mapped_county_without_transactions(
    api_client: TestClient,
) -> None:
    response = api_client.get("/v1/counties/nc/wake/campaign-finance-summary")

    assert response.status_code == 200
    assert response.json() == {
        "state": "nc",
        "county_slug": "wake",
        "donor_total_cents": 0,
        "transaction_count": 0,
        "top_recipient_committees": [],
        "top_linked_candidates": [],
        "sources": [],
    }


def test_get_committee_filings_summary_returns_sorted_totals_and_keeps_zero_transaction_filings(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000021")
    committee_name = "Filing Breakdown Test Committee"
    context = seed_committee_for_filing_breakdown(
        db_conn,
        committee_id=committee_id,
        committee_name=committee_name,
        fec_committee_id="C99992021",
    )

    filing_recent_low_id = UUID("a0000000-0000-0000-0000-000000000110")
    filing_recent_high_id = UUID("a0000000-0000-0000-0000-000000000111")
    filing_older = UUID("a0000000-0000-0000-0000-000000000112")
    filing_no_transactions = UUID("a0000000-0000-0000-0000-000000000113")
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_recent_low_id,
            filing_fec_id="FILING-RECENT-LOW",
            committee_id=context.committee_id,
            report_type="Q2",
            amendment_indicator="N",
            filing_name="Recent Filing A",
            coverage_start_date=datetime(2026, 4, 1, tzinfo=timezone.utc).date(),
            coverage_end_date=datetime(2026, 6, 30, tzinfo=timezone.utc).date(),
            receipt_date=datetime(2026, 7, 20, tzinfo=timezone.utc).date(),
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_recent_high_id,
            filing_fec_id="FILING-RECENT-HIGH",
            committee_id=context.committee_id,
            report_type="Q2",
            amendment_indicator="N",
            filing_name="Recent Filing B",
            coverage_start_date=datetime(2026, 4, 1, tzinfo=timezone.utc).date(),
            coverage_end_date=datetime(2026, 6, 30, tzinfo=timezone.utc).date(),
            receipt_date=datetime(2026, 7, 20, tzinfo=timezone.utc).date(),
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_older,
            filing_fec_id="FILING-OLDER",
            committee_id=context.committee_id,
            report_type="Q1",
            amendment_indicator="A",
            filing_name="Older Filing",
            coverage_start_date=datetime(2026, 1, 1, tzinfo=timezone.utc).date(),
            coverage_end_date=datetime(2026, 3, 31, tzinfo=timezone.utc).date(),
            receipt_date=datetime(2026, 4, 15, tzinfo=timezone.utc).date(),
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_no_transactions,
            filing_fec_id="FILING-NO-TRANSACTIONS",
            committee_id=context.committee_id,
            report_type="YE",
            amendment_indicator="N",
            filing_name="No Transactions Filing",
            coverage_start_date=None,
            coverage_end_date=None,
            receipt_date=None,
        ),
    )

    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=filing_recent_low_id,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000201"),
        transaction_type="15",
        amount=Decimal("100.00"),
        amendment_indicator="N",
    )
    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=filing_recent_low_id,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000202"),
        transaction_type="24A",
        amount=Decimal("30.00"),
        amendment_indicator="N",
    )
    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=filing_recent_high_id,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000203"),
        transaction_type="15",
        amount=Decimal("50.00"),
        amendment_indicator="N",
    )
    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=filing_older,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000204"),
        transaction_type="15",
        amount=Decimal("40.00"),
        amendment_indicator="A",
    )
    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=filing_older,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000205"),
        transaction_type="15",
        amount=Decimal("999.00"),
        amendment_indicator="T",
    )
    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=filing_older,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000206"),
        transaction_type="15",
        amount=Decimal("888.00"),
        amendment_indicator="N",
        is_memo=True,
    )

    response = api_client.get(f"/v1/committees/{context.committee_id}/filings/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["committee_id"] == str(context.committee_id)
    assert payload["committee_name"] == committee_name
    assert [row["filing_id"] for row in payload["filings"]] == [
        str(filing_recent_low_id),
        str(filing_recent_high_id),
        str(filing_older),
        str(filing_no_transactions),
    ]
    assert payload["filings"][0]["total_raised"] == "100.00"
    assert payload["filings"][0]["total_spent"] == "30.00"
    assert payload["filings"][0]["net"] == "70.00"
    assert payload["filings"][0]["transaction_count"] == 2
    assert payload["filings"][0]["cash_on_hand"] == "110.00"
    assert payload["filings"][0]["row_id"] == f"{filing_recent_low_id}:N"
    assert payload["filings"][1]["total_raised"] == "50.00"
    assert payload["filings"][1]["total_spent"] == "0.00"
    assert payload["filings"][1]["net"] == "50.00"
    assert payload["filings"][1]["transaction_count"] == 1
    assert payload["filings"][1]["cash_on_hand"] == "160.00"
    assert payload["filings"][1]["row_id"] == f"{filing_recent_high_id}:N"
    assert payload["filings"][2]["total_raised"] == "40.00"
    assert payload["filings"][2]["total_spent"] == "0.00"
    assert payload["filings"][2]["net"] == "40.00"
    assert payload["filings"][2]["transaction_count"] == 1
    assert payload["filings"][2]["cash_on_hand"] == "40.00"
    assert payload["filings"][2]["row_id"] == f"{filing_older}:A"
    assert payload["filings"][3]["total_raised"] == "0.00"
    assert payload["filings"][3]["total_spent"] == "0.00"
    assert payload["filings"][3]["net"] == "0.00"
    assert payload["filings"][3]["transaction_count"] == 0
    assert payload["filings"][3]["cash_on_hand"] == "160.00"
    assert payload["filings"][3]["row_id"] == f"{filing_no_transactions}:N"


def test_get_committee_filings_summary_excludes_transactions_backed_by_superseded_source_records(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000023")
    context = seed_committee_for_filing_breakdown(
        db_conn,
        committee_id=committee_id,
        committee_name="Filing Superseded Source Committee",
        fec_committee_id="C99992023",
    )
    filing_id = UUID("a0000000-0000-0000-0000-000000000114")
    current_source_record_id = UUID("10000000-0000-0000-0000-000000000723")
    superseded_source_record_id = UUID("10000000-0000-0000-0000-000000000724")

    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id="FILING-SUPERSEDED-SOURCE",
            committee_id=context.committee_id,
            report_type="Q2",
            amendment_indicator="N",
            filing_name="Superseded Source Filing",
            coverage_start_date=datetime(2026, 4, 1, tzinfo=timezone.utc).date(),
            coverage_end_date=datetime(2026, 6, 30, tzinfo=timezone.utc).date(),
            receipt_date=datetime(2026, 7, 18, tzinfo=timezone.utc).date(),
        ),
    )

    data_source = insert_data_source_for_test(
        db_conn,
        jurisdiction="state/nc",
        name_suffix="filing-superseded-source",
    )
    insert_source_record_for_test(
        db_conn,
        source_record_id=current_source_record_id,
        data_source_id=data_source.id,
        source_record_key="filing-superseded-source-current",
        source_url="https://example.org/record/filing-superseded-source-current",
        pull_date=datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc),
    )
    insert_source_record_for_test(
        db_conn,
        source_record_id=superseded_source_record_id,
        data_source_id=data_source.id,
        source_record_key="filing-superseded-source-old",
        source_url="https://example.org/record/filing-superseded-source-old",
        pull_date=datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
        superseded_by=current_source_record_id,
    )

    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=filing_id,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000213"),
        transaction_type="15",
        amount=Decimal("100.00"),
        source_record_id=current_source_record_id,
        amendment_indicator="N",
    )
    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=filing_id,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000214"),
        transaction_type="15",
        amount=Decimal("250.00"),
        source_record_id=superseded_source_record_id,
        amendment_indicator="N",
    )

    response = api_client.get(f"/v1/committees/{context.committee_id}/filings/summary")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["filings"]) == 1
    filing_summary = payload["filings"][0]
    assert filing_summary["filing_id"] == str(filing_id)
    assert filing_summary["total_raised"] == "100.00"
    assert filing_summary["total_spent"] == "0.00"
    assert filing_summary["net"] == "100.00"
    assert filing_summary["transaction_count"] == 1
    assert filing_summary["cash_on_hand"] == "100.00"
    assert filing_summary["row_id"] == f"{filing_id}:N"


def test_get_committee_filings_summary_uses_canonical_row_after_filing_upsert_replacement(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    committee_id = UUID("a0000000-0000-0000-0000-000000000022")
    context = seed_committee_for_filing_breakdown(
        db_conn,
        committee_id=committee_id,
        committee_name="Filing Upsert Replacement Committee",
        fec_committee_id="C99992022",
    )
    filing_fec_id = "FILING-UPSERT-CANONICAL-001"
    canonical_filing_id = UUID("a0000000-0000-0000-0000-000000000120")

    first_upsert_id = upsert_filing(
        db_conn,
        Filing(
            id=canonical_filing_id,
            filing_fec_id=filing_fec_id,
            committee_id=context.committee_id,
            report_type="Q1",
            amendment_indicator="N",
            filing_name="Quarterly Filing Original",
            coverage_start_date=datetime(2026, 1, 1, tzinfo=timezone.utc).date(),
            coverage_end_date=datetime(2026, 3, 31, tzinfo=timezone.utc).date(),
            receipt_date=datetime(2026, 4, 15, tzinfo=timezone.utc).date(),
        ),
    )
    assert first_upsert_id == canonical_filing_id

    replacement_upsert_id = upsert_filing(
        db_conn,
        Filing(
            id=UUID("a0000000-0000-0000-0000-000000000121"),
            filing_fec_id=filing_fec_id,
            committee_id=context.committee_id,
            report_type="Q1A",
            amendment_indicator="A",
            filing_name="Quarterly Filing Amended",
            coverage_start_date=datetime(2026, 1, 1, tzinfo=timezone.utc).date(),
            coverage_end_date=datetime(2026, 3, 31, tzinfo=timezone.utc).date(),
            receipt_date=datetime(2026, 4, 20, tzinfo=timezone.utc).date(),
        ),
    )
    assert replacement_upsert_id == canonical_filing_id

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, report_type, amendment_indicator, filing_name, receipt_date
            FROM cf.filing
            WHERE filing_fec_id = %s
            """,
            (filing_fec_id,),
        )
        filing_rows = cursor.fetchall()
    assert len(filing_rows) == 1
    assert filing_rows[0] == (
        canonical_filing_id,
        "Q1A",
        "A",
        "Quarterly Filing Amended",
        datetime(2026, 4, 20, tzinfo=timezone.utc).date(),
    )

    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=canonical_filing_id,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000211"),
        transaction_type="15",
        amount=Decimal("125.00"),
        amendment_indicator="N",
    )
    insert_filing_breakdown_transaction(
        db_conn,
        committee_id=context.committee_id,
        filing_id=canonical_filing_id,
        transaction_id=UUID("a0000000-0000-0000-0000-000000000212"),
        transaction_type="24A",
        amount=Decimal("20.00"),
        amendment_indicator="N",
    )

    response = api_client.get(f"/v1/committees/{context.committee_id}/filings/summary")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["filings"]) == 1
    filing_summary = payload["filings"][0]
    assert filing_summary["filing_id"] == str(canonical_filing_id)
    assert filing_summary["filing_fec_id"] == filing_fec_id
    assert filing_summary["report_type"] == "Q1A"
    assert filing_summary["amendment_indicator"] == "A"
    assert filing_summary["filing_name"] == "Quarterly Filing Amended"
    assert filing_summary["receipt_date"] == "2026-04-20"
    assert filing_summary["total_raised"] == "125.00"
    assert filing_summary["total_spent"] == "20.00"
    assert filing_summary["net"] == "105.00"
    assert filing_summary["transaction_count"] == 2


def test_get_committee_filings_summary_returns_404_for_missing_committee(
    api_client: TestClient,
) -> None:
    response = api_client.get(f"/v1/committees/{uuid4()}/filings/summary")

    assert response.status_code == 404
    assert response.json() == {"detail": "Committee not found"}


# ---------------------------------------------------------------------------
# Stage 5: committee summary official/derived reconciliation
# ---------------------------------------------------------------------------


def _seed_committee_with_derived_transactions(
    db_conn: psycopg.Connection,
    *,
    committee_id: UUID,
    committee_name: str,
    fec_committee_id: str,
    receipt_amount: Decimal,
    disbursement_amount: Decimal,
) -> None:
    """Seed one receipt and one disbursement so derived totals differ from official."""
    context = seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        committee_name=committee_name,
        fec_committee_id=fec_committee_id,
    )
    insert_summary_transaction(
        db_conn,
        context=context,
        transaction_id=uuid4(),
        transaction_type="15",
        amount=receipt_amount,
        source_record_id=context.source_record_id,
    )
    insert_summary_transaction(
        db_conn,
        context=context,
        transaction_id=uuid4(),
        transaction_type="24A",
        amount=disbursement_amount,
        source_record_id=context.source_record_id,
    )


class _CommitteeSummaryOfficialOnlyCursor:
    def __enter__(self) -> _CommitteeSummaryOfficialOnlyCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, *_args: object) -> None:
        return None

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[dict[str, object]]:
        return []


class _CommitteeSummaryOfficialOnlyConnection:
    def cursor(self, *_args: object, **_kwargs: object) -> _CommitteeSummaryOfficialOnlyCursor:
        return _CommitteeSummaryOfficialOnlyCursor()


def test_fetch_committee_summary_official_only_rows_include_committee_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage 5 regression: query owner names official-only summary shells."""
    committee_id = UUID("a5000000-0000-0000-0000-000000000005")
    monkeypatch.setattr(
        campaign_finance_query_module,
        "_fetch_committee_cycle_summaries",
        lambda _conn, _committee_id, _selected_cycle: [
            {
                "cycle": 2026,
                "total_receipts": Decimal("1234.00"),
                "total_disbursements": Decimal("234.00"),
                "cash_on_hand": Decimal("1000.00"),
                "coverage_start_date": None,
                "coverage_end_date": None,
            }
        ],
    )
    monkeypatch.setattr(
        campaign_finance_query_module,
        "_fetch_committee_name",
        lambda _conn, _committee_id: "Official Only Committee",
        raising=False,
    )
    monkeypatch.setattr(
        campaign_finance_query_module,
        "_fetch_committee_top_lists",
        lambda _conn, _committee_id, _selected_cycle: {"top_donors": [], "top_vendors": [], "spend_categories": []},
    )

    summary = fetch_committee_fundraising_summary(_CommitteeSummaryOfficialOnlyConnection(), committee_id)

    assert summary is not None
    assert summary["committee_id"] == committee_id
    assert summary["committee_name"] == "Official Only Committee"
    assert summary["summary_source"] == "fec_committee_summary"
    assert summary["total_raised"] == Decimal("1234.00")
    assert summary["total_spent"] == Decimal("234.00")
    assert summary["transaction_count"] == 0
    assert summary["itemized_transaction_count"] == 0


def test_get_committee_summary_uses_official_committee_summary_totals_when_present(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Stage 5: cf.committee_summary rows override derived totals for supported cycles."""
    committee_id = UUID("a5000000-0000-0000-0000-000000000001")
    _seed_committee_with_derived_transactions(
        db_conn,
        committee_id=committee_id,
        committee_name="Official Totals Committee",
        fec_committee_id="C55550001",
        receipt_amount=Decimal("100.00"),
        disbursement_amount=Decimal("40.00"),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2024,
            total_receipts=Decimal("9000.00"),
            total_disbursements=Decimal("3500.00"),
            cash_on_hand=Decimal("5500.00"),
        ),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=Decimal("1000.00"),
            total_disbursements=Decimal("500.00"),
            cash_on_hand=Decimal("6000.00"),
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_source"] == "fec_committee_summary"
    # Official totals win for the selected cycle.
    assert payload["total_raised"] == "1000.00"
    assert payload["total_spent"] == "500.00"
    assert payload["net"] == "500.00"
    # Derived counts stay truthful next to official totals.
    assert payload["transaction_count"] == 2
    assert payload["itemized_transaction_count"] == 2
    # Per-cycle rows preserve the selected cycle.
    assert payload["cycle_summaries"] == [
        {
            "cycle": 2026,
            "total_receipts": "1000.00",
            "total_disbursements": "500.00",
            "cash_on_hand": "6000.00",
            "coverage_start_date": None,
            "coverage_end_date": None,
        },
    ]


def test_get_committee_summary_uses_committee_name_for_official_only_rows(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Stage 5 regression: official-only summaries still need the committee name."""
    committee_id = UUID("a5000000-0000-0000-0000-000000000004")
    context = seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        committee_name="Official Only Committee",
        fec_committee_id="C55550004",
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=Decimal("1234.00"),
            total_disbursements=Decimal("234.00"),
            cash_on_hand=Decimal("1000.00"),
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["committee_name"] == context.committee_name
    assert payload["summary_source"] == "fec_committee_summary"
    assert payload["total_raised"] == "1234.00"
    assert payload["total_spent"] == "234.00"
    assert payload["net"] == "1000.00"
    assert payload["transaction_count"] == 0
    assert payload["itemized_transaction_count"] == 0
    assert payload["cycle_summaries"] == [
        {
            "cycle": 2026,
            "total_receipts": "1234.00",
            "total_disbursements": "234.00",
            "cash_on_hand": "1000.00",
            "coverage_start_date": None,
            "coverage_end_date": None,
        }
    ]


def test_get_candidate_summary_keeps_official_only_linked_committee_name(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Stage 5 regression: nested official-only committee summaries validate."""
    candidate_id = UUID("b0000000-0000-0000-0000-000000000451")
    committee_id = UUID("b4555555-5555-5555-5555-555555555555")
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id="H0NC02451",
            name="Official Only Linked Candidate",
            office="H",
        ),
    )
    committee_context = seed_committee_for_summary(
        db_conn,
        committee_id=committee_id,
        committee_name="Official Only Linked Committee",
        fec_committee_id="C99000451",
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2026,
            total_receipts=Decimal("2500.00"),
            total_disbursements=Decimal("750.00"),
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("b0000000-0000-0000-0000-000000000471"),
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
            source_record_id=None,
            candidate_election_year=2026,
            fec_election_year=2026,
        ),
    )

    response = api_client.get(f"/v1/candidates/{candidate_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_source"] == "derived"
    assert payload["total_raised"] == "2500.00"
    assert payload["total_spent"] == "750.00"
    assert payload["transaction_count"] == 0
    assert payload["itemized_transaction_count"] == 0
    assert payload["committees"][0]["committee_name"] == committee_context.committee_name
    assert payload["committees"][0]["summary_source"] == "fec_committee_summary"
    assert payload["committees"][0]["itemized_transaction_count"] == 0


def test_get_committee_summary_falls_back_to_derived_when_no_official_rows(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Stage 5: no cf.committee_summary rows -> derived totals + summary_source=derived."""
    committee_id = UUID("a5000000-0000-0000-0000-000000000002")
    _seed_committee_with_derived_transactions(
        db_conn,
        committee_id=committee_id,
        committee_name="Derived Only Committee",
        fec_committee_id="C55550002",
        receipt_amount=Decimal("75.00"),
        disbursement_amount=Decimal("25.00"),
    )

    response = api_client.get(f"/v1/committees/{committee_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_source"] == "derived"
    assert payload["total_raised"] == "75.00"
    assert payload["total_spent"] == "25.00"
    assert payload["net"] == "50.00"
    assert payload["transaction_count"] == 2
    assert payload["itemized_transaction_count"] == 2
    assert payload["cycle_summaries"] == []


def test_get_committee_summary_ignores_committee_summary_rows_outside_supported_cycles(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Stage 5: pre-2024 cycles are excluded from top-level totals and cycle_summaries."""
    committee_id = UUID("a5000000-0000-0000-0000-000000000003")
    _seed_committee_with_derived_transactions(
        db_conn,
        committee_id=committee_id,
        committee_name="Old Cycle Committee",
        fec_committee_id="C55550003",
        receipt_amount=Decimal("50.00"),
        disbursement_amount=Decimal("10.00"),
    )
    insert_committee_summary_row(
        db_conn,
        CommitteeSummaryRowSeed(
            committee_id=committee_id,
            cycle=2020,
            total_receipts=Decimal("500000.00"),
            total_disbursements=Decimal("400000.00"),
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}/summary")

    assert response.status_code == 200
    payload = response.json()
    # Out-of-window rows do not overwrite derived totals.
    assert payload["summary_source"] == "derived"
    assert payload["total_raised"] == "50.00"
    assert payload["total_spent"] == "10.00"
    assert payload["cycle_summaries"] == []


# ---------------------------------------------------------------------------
# Stage 5: committee detail linked_candidates
# ---------------------------------------------------------------------------


def test_get_committee_detail_exposes_active_linked_candidates_shape(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Stage 5: linked_candidates uses the CandidateListItem shape and drops expired links."""
    committee_id = UUID("a6000000-0000-0000-0000-000000000001")
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id="C66660001",
            name="Linked Candidates Committee",
        ),
    )
    person_id_alpha = uuid4()
    candidate_alpha = UUID("a6000000-0000-0000-0000-000000000101")
    candidate_beta = UUID("a6000000-0000-0000-0000-000000000102")
    candidate_expired = UUID("a6000000-0000-0000-0000-000000000103")
    insert_person(db_conn, Person(id=person_id_alpha, canonical_name="Alpha Candidate"))
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_alpha,
            fec_candidate_id="H0NC66001",
            name="Alpha Candidate",
            office="H",
            person_id=person_id_alpha,
            party="DEM",
            state="NC",
            district="01",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_beta,
            fec_candidate_id="H0NC66002",
            name="Beta Candidate",
            office="H",
        ),
    )
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_expired,
            fec_candidate_id="H0NC66003",
            name="Expired Candidate",
            office="H",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("a6000000-0000-0000-0000-000000000201"),
            candidate_id=candidate_alpha,
            committee_id=committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="P",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("a6000000-0000-0000-0000-000000000202"),
            candidate_id=candidate_beta,
            committee_id=committee_id,
            valid_period="[2000-01-01,2100-01-01)",
            designation="A",
        ),
    )
    insert_candidate_committee_link_row(
        db_conn,
        CandidateCommitteeLinkSeed(
            id=UUID("a6000000-0000-0000-0000-000000000203"),
            candidate_id=candidate_expired,
            committee_id=committee_id,
            valid_period="[2000-01-01,2001-01-01)",
            designation="A",
        ),
    )

    response = api_client.get(f"/v1/committees/{committee_id}")

    assert response.status_code == 200
    payload = response.json()
    linked = payload["linked_candidates"]
    # Expired link excluded; ordered by candidate name for deterministic UI.
    assert [row["id"] for row in linked] == [str(candidate_alpha), str(candidate_beta)]
    alpha_row = linked[0]
    # Reuses CandidateListItem shape, including person_id for Stage 6 routing.
    assert set(alpha_row.keys()) == {
        "id",
        "fec_candidate_id",
        "name",
        "person_id",
        "party",
        "office",
        "state",
        "district",
        "slug",
        "slug_is_unique",
    }
    assert alpha_row["person_id"] == str(person_id_alpha)
    assert alpha_row["fec_candidate_id"] == "H0NC66001"
    assert alpha_row["party"] == "DEM"
    assert alpha_row["office"] == "H"
    assert alpha_row["state"] == "NC"
    assert alpha_row["district"] == "01"
    assert alpha_row["slug"] == "alpha-candidate"
    assert alpha_row["slug_is_unique"] is True


# ---------------------------------------------------------------------------
# Stage 5: IE outlier exclusion in aggregate summary only
# ---------------------------------------------------------------------------


def _seed_candidate_and_committee_for_ie(
    db_conn: psycopg.Connection,
    *,
    candidate_id: UUID,
    committee_id: UUID,
    filing_id: UUID,
    candidate_fec_id: str,
    committee_fec_id: str,
    committee_name: str,
) -> None:
    insert_candidate_row(
        db_conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id=candidate_fec_id,
            name="Outlier IE Candidate",
            office="H",
        ),
    )
    insert_committee_row(
        db_conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id=committee_fec_id,
            name=committee_name,
        ),
    )
    insert_filing_row(
        db_conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id=f"filing-{committee_fec_id}",
            committee_id=committee_id,
        ),
    )


def _insert_superseded_candidate_ie_source(db_conn: psycopg.Connection) -> UUID:
    data_source = insert_data_source_for_test(
        db_conn,
        jurisdiction="federal/fec",
        name_suffix="candidate-ie-summaries",
    )
    superseding_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("a7100000-0000-0000-0000-000000000030"),
        data_source_id=data_source.id,
        source_record_key="candidate-ie-summaries-current",
        source_url="https://example.org/record/candidate-ie-summaries-current",
        pull_date=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
    )
    superseded_source = insert_source_record_for_test(
        db_conn,
        source_record_id=UUID("a7100000-0000-0000-0000-000000000031"),
        data_source_id=data_source.id,
        source_record_key="candidate-ie-summaries-superseded",
        source_url="https://example.org/record/candidate-ie-summaries-superseded",
        pull_date=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        superseded_by=superseding_source.id,
    )
    return superseded_source.id


def _seed_candidate_ie_summaries_fixture(
    db_conn: psycopg.Connection,
) -> tuple[UUID, UUID, UUID]:
    populated_candidate_id = UUID("a7100000-0000-0000-0000-000000000001")
    empty_candidate_id = UUID("a7100000-0000-0000-0000-000000000002")
    unrequested_candidate_id = UUID("a7100000-0000-0000-0000-000000000003")
    committee_id = UUID("a7100000-0000-0000-0000-000000000010")
    filing_id = UUID("a7100000-0000-0000-0000-000000000020")
    _seed_candidate_and_committee_for_ie(
        db_conn,
        candidate_id=populated_candidate_id,
        committee_id=committee_id,
        filing_id=filing_id,
        candidate_fec_id="H0NC71001",
        committee_fec_id="C71000001",
        committee_name="Batch IE Committee",
    )
    for candidate_id, fec_candidate_id in (
        (empty_candidate_id, "H0NC71002"),
        (unrequested_candidate_id, "H0NC71003"),
    ):
        insert_candidate_row(
            db_conn,
            CandidateRowSeed(
                id=candidate_id,
                fec_candidate_id=fec_candidate_id,
                name=f"Batch IE Candidate {fec_candidate_id}",
                office="H",
            ),
        )

    superseded_source_id = _insert_superseded_candidate_ie_source(db_conn)

    transaction_rows = (
        (populated_candidate_id, Decimal("40000000.00"), date(2023, 1, 1), "N", False, "S", None),
        (populated_candidate_id, CANDIDATE_IE_OUTLIER_CEILING, date(2024, 12, 31), "N", False, "S", None),
        (populated_candidate_id, Decimal("250.25"), date(2024, 6, 1), "N", False, "O", None),
        (populated_candidate_id, Decimal("9980000000.00"), date(2024, 6, 2), "N", False, "S", None),
        (
            populated_candidate_id,
            CANDIDATE_IE_OUTLIER_CEILING + Decimal("0.01"),
            date(2024, 6, 3),
            "N",
            False,
            "O",
            None,
        ),
        (populated_candidate_id, Decimal("1000.00"), date(2022, 12, 31), "N", False, "S", None),
        (populated_candidate_id, Decimal("2000.00"), date(2025, 1, 1), "N", False, "O", None),
        (populated_candidate_id, Decimal("3000.00"), date(2024, 6, 4), "N", True, "S", None),
        (populated_candidate_id, Decimal("4000.00"), date(2024, 6, 5), "T", False, "O", None),
        (populated_candidate_id, Decimal("5000.00"), date(2024, 6, 6), "N", False, None, None),
        (
            populated_candidate_id,
            Decimal("6000.00"),
            date(2024, 6, 7),
            "N",
            False,
            "O",
            superseded_source_id,
        ),
        (unrequested_candidate_id, Decimal("7000.00"), date(2024, 6, 8), "N", False, "S", None),
    )
    for index, (candidate_id, amount, transaction_date, amendment, is_memo, stance, source_id) in enumerate(
        transaction_rows,
        start=101,
    ):
        insert_transaction_row(
            db_conn,
            TransactionRowSeed(
                id=UUID(f"a7100000-0000-0000-0000-{index:012d}"),
                filing_id=filing_id,
                committee_id=committee_id,
                transaction_type="24E",
                amount=amount,
                amendment_indicator=amendment,
                source_record_id=source_id,
                transaction_date=transaction_date,
                recipient_candidate_id=candidate_id,
                is_memo=is_memo,
                support_oppose=stance,
            ),
        )
    return populated_candidate_id, empty_candidate_id, unrequested_candidate_id


def test_fetch_candidate_ie_summaries_applies_cycle_qualification_and_outlier_rules(
    db_conn: psycopg.Connection,
) -> None:
    populated_candidate_id, empty_candidate_id, unrequested_candidate_id = _seed_candidate_ie_summaries_fixture(db_conn)

    summaries = fetch_candidate_ie_summaries(
        db_conn,
        [populated_candidate_id, empty_candidate_id],
        selected_cycle=2024,
    )

    assert summaries == {
        populated_candidate_id: {
            "candidate_id": populated_candidate_id,
            "selected_cycle": 2024,
            "coverage_start_date": date(2023, 1, 1),
            "coverage_end_date": date(2024, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "support_total": Decimal("140000000.00"),
            "oppose_total": Decimal("250.25"),
            "support_count": 2,
            "oppose_count": 1,
            "top_spenders": [],
            "excluded_outlier_count": 2,
        },
        empty_candidate_id: {
            "candidate_id": empty_candidate_id,
            "selected_cycle": 2024,
            "coverage_start_date": date(2023, 1, 1),
            "coverage_end_date": date(2024, 12, 31),
            "available_cycles": [2022, 2024, 2026],
            "support_total": Decimal("0.00"),
            "oppose_total": Decimal("0.00"),
            "support_count": 0,
            "oppose_count": 0,
            "top_spenders": [],
            "excluded_outlier_count": 0,
        },
    }
    assert unrequested_candidate_id not in summaries


def test_candidate_ie_summary_excludes_outliers_while_list_endpoint_stays_source_faithful(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    """Stage 5: rows above the summary outlier ceiling are filtered from the aggregate,
    but the raw list endpoint still returns every source-faithful row.
    """
    candidate_id = UUID("a7000000-0000-0000-0000-000000000001")
    committee_id = UUID("a7000000-0000-0000-0000-000000000010")
    filing_id = UUID("a7000000-0000-0000-0000-000000000020")
    _seed_candidate_and_committee_for_ie(
        db_conn,
        candidate_id=candidate_id,
        committee_id=committee_id,
        filing_id=filing_id,
        candidate_fec_id="H0NC77001",
        committee_fec_id="C77770001",
        committee_name="Outlier IE Committee",
    )
    normal_row_id = UUID("a7000000-0000-0000-0000-000000000101")
    outlier_row_id = UUID("a7000000-0000-0000-0000-000000000102")
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=normal_row_id,
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24E",
            amount=Decimal("250.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            recipient_candidate_id=candidate_id,
            support_oppose="S",
        ),
    )
    # Known malformed Schedule E shape: $9.98B / row. Above the $100M ceiling.
    insert_transaction_row(
        db_conn,
        TransactionRowSeed(
            id=outlier_row_id,
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="24E",
            amount=Decimal("9980000000.00"),
            amendment_indicator="N",
            transaction_date=date(2026, 3, 15),
            recipient_candidate_id=candidate_id,
            support_oppose="S",
        ),
    )

    list_response = api_client.get(f"/v1/candidates/{candidate_id}/independent-expenditures")
    summary_response = api_client.get(f"/v1/candidates/{candidate_id}/independent-expenditures/summary")

    assert list_response.status_code == 200
    # Raw list is source-faithful: both rows appear.
    assert {row["id"] for row in list_response.json()} == {
        str(normal_row_id),
        str(outlier_row_id),
    }
    outlier_list_row = next(row for row in list_response.json() if row["id"] == str(outlier_row_id))
    assert Decimal(str(outlier_list_row["amount"])) == Decimal("9980000000.00")

    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    # Aggregate excludes the outlier: totals + counts come from the one normal row only.
    assert summary_payload["support_total"] == "250.00"
    assert summary_payload["support_count"] == 1
    assert summary_payload["oppose_total"] == "0.00"
    assert summary_payload["oppose_count"] == 0
    assert summary_payload["excluded_outlier_count"] == 1
    # Top-spenders never reflect the outlier row's committee total.
    assert summary_payload["top_spenders"] == [
        {
            "committee_id": str(committee_id),
            "committee_name": "Outlier IE Committee",
            "support_oppose": "S",
            "total_amount": "250.00",
            "transaction_count": 1,
        }
    ]
