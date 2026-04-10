from __future__ import annotations

from pathlib import Path

import pytest

from core.types.python.models import Address, Organization, Person
from domains.campaign_finance.jurisdictions.states.GA.scraper.extract import (
    _build_title_cased_name,
    _normalized_text,
    build_ga_data_source,
    extract_address,
    extract_candidate,
    extract_committee,
    extract_donor_org,
    extract_donor_person,
    extract_ga_contribution,
    extract_ga_expenditure,
    extract_payee_org,
    extract_payee_person,
)
from domains.campaign_finance.jurisdictions.states.GA.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
GA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "GA"
CONTRIBUTION_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "contribution_export_sample.xls"
EXPENDITURE_FIXTURE_PATH = GA_DIR / "tests" / "fixtures" / "expenditure_export_sample.xls"


@pytest.fixture(scope="module")
def contribution_rows() -> list[dict[str, object]]:
    return list(parse_contributions(CONTRIBUTION_FIXTURE_PATH))


@pytest.fixture(scope="module")
def expenditure_rows() -> list[dict[str, object]]:
    return list(parse_expenditures(EXPENDITURE_FIXTURE_PATH))


def fixture_row(rows: list[dict[str, object]], row_number: int) -> dict[str, object]:
    return rows[row_number - 1]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("  hello  ", "hello"),
    ],
)
def test_normalized_text(raw: str | None, expected: str | None) -> None:
    assert _normalized_text(raw) == expected


def test_build_title_cased_name_skips_none_parts() -> None:
    assert _build_title_cased_name("  waycross", None, "bank & trust  ") == "Waycross Bank & Trust"


class TestDonorExtraction:
    def test_extract_donor_person_from_contribution_row(self, contribution_rows: list[dict[str, object]]) -> None:
        row = dict(fixture_row(contribution_rows, 1))
        row["LastName"] = "doe"
        row["FirstName"] = "jane"

        person = extract_donor_person(row)

        assert person is not None
        assert person.canonical_name == "Jane Doe"
        assert person.first_name == "Jane"
        assert person.last_name == "Doe"

    def test_extract_donor_person_builds_non_blank_identifiers_only(
        self,
        contribution_rows: list[dict[str, object]],
    ) -> None:
        row = dict(fixture_row(contribution_rows, 1))
        row["LastName"] = "doe"
        row["FirstName"] = "jane"
        row["Employer"] = "  Acme Corp "
        row["Occupation"] = "   "

        person = extract_donor_person(row)

        assert person is not None
        assert person.identifiers == {"employer": "Acme Corp"}

    def test_extract_donor_person_returns_none_for_organization(
        self, contribution_rows: list[dict[str, object]]
    ) -> None:
        assert extract_donor_person(fixture_row(contribution_rows, 1)) is None

    def test_extract_donor_org_from_contribution_row(self, contribution_rows: list[dict[str, object]]) -> None:
        org = extract_donor_org(fixture_row(contribution_rows, 1))

        assert org is not None
        assert org.canonical_name == "Waycross Bank & Trust"

    def test_extract_donor_org_returns_none_for_person(self, contribution_rows: list[dict[str, object]]) -> None:
        row = dict(fixture_row(contribution_rows, 1))
        row["LastName"] = "doe"
        row["FirstName"] = "jane"

        assert extract_donor_org(row) is None

    def test_extract_donor_org_returns_none_when_both_names_blank(
        self,
        contribution_rows: list[dict[str, object]],
    ) -> None:
        row = dict(fixture_row(contribution_rows, 1))
        row["LastName"] = ""
        row["FirstName"] = ""

        assert extract_donor_org(row) is None


class TestPayeeExtraction:
    def test_extract_payee_person_builds_empty_identifiers(self, expenditure_rows: list[dict[str, object]]) -> None:
        row = dict(fixture_row(expenditure_rows, 1))
        row["LastName"] = "doe"
        row["FirstName"] = "jane"
        row["Occupation_or_Employer"] = "Some value"

        person = extract_payee_person(row)

        assert person is not None
        assert person.canonical_name == "Jane Doe"
        assert person.identifiers == {}

    def test_extract_payee_org_from_expenditure_row(self, expenditure_rows: list[dict[str, object]]) -> None:
        org = extract_payee_org(fixture_row(expenditure_rows, 1))

        assert org is not None
        assert org.canonical_name == "Waycross Bank & Trust"


class TestCommitteeCandidateAddressExtraction:
    def test_extract_committee(self, contribution_rows: list[dict[str, object]]) -> None:
        committee = extract_committee(fixture_row(contribution_rows, 1))

        assert committee.canonical_name == "Hatfield For House"
        assert committee.org_type is None
        assert committee.identifiers == {"ga_filer_id": "C2006000122"}

    def test_extract_candidate(self, contribution_rows: list[dict[str, object]]) -> None:
        candidate = extract_candidate(fixture_row(contribution_rows, 1))

        assert candidate is not None
        assert candidate.canonical_name == "John Mark Hatfield"
        assert candidate.first_name == "John"
        assert candidate.middle_name == "Mark"
        assert candidate.last_name == "Hatfield"
        assert candidate.suffix is None
        assert candidate.identifiers == {}

    def test_extract_candidate_returns_none_for_blank_name(self, contribution_rows: list[dict[str, object]]) -> None:
        row = dict(fixture_row(contribution_rows, 1))
        row["Candidate_FirstName"] = ""
        row["Candidate_MiddleName"] = ""
        row["Candidate_LastName"] = ""
        row["Candidate_Suffix"] = ""

        assert extract_candidate(row) is None

    def test_extract_address_for_contribution_uses_shared_normalizer(
        self,
        contribution_rows: list[dict[str, object]],
    ) -> None:
        address = extract_address(fixture_row(contribution_rows, 1))

        assert address is not None
        assert address.raw_address == "501 Tebeau Street, Waycross, georgia, 31501"
        assert address.street_number == "501"
        assert address.street_name == "TEBEAU STREET"
        assert address.unit is None
        assert address.city == "WAYCROSS"
        assert address.state == "GA"
        assert address.zip5 == "31501"
        assert address.zip4 is None

    def test_extract_address_for_expenditure_uses_shared_normalizer(
        self,
        expenditure_rows: list[dict[str, object]],
    ) -> None:
        address = extract_address(fixture_row(expenditure_rows, 1))

        assert address is not None
        assert address.state == "GA"
        assert address.zip5 == "31501"
        assert address.street_number == "501"

    def test_extract_address_returns_none_when_city_and_state_blank(
        self,
        contribution_rows: list[dict[str, object]],
    ) -> None:
        row = dict(fixture_row(contribution_rows, 1))
        row["City"] = ""
        row["State"] = ""

        assert extract_address(row) is None


class TestDataSourceAndComposition:
    def test_build_ga_data_source_contributions(self) -> None:
        data_source = build_ga_data_source("contributions")

        assert data_source.domain == "campaign_finance"
        assert data_source.jurisdiction == "state/GA"
        assert data_source.name == "Georgia Campaign Portal — Contributions Search Export"
        assert data_source.source_url == "https://media.ethics.ga.gov/search/Campaign/Campaign_ByContributions.aspx"

    def test_build_ga_data_source_expenditures(self) -> None:
        data_source = build_ga_data_source("expenditures")

        assert data_source.domain == "campaign_finance"
        assert data_source.jurisdiction == "state/GA"
        assert data_source.name == "Georgia Campaign Portal — Expenditures Search Export"
        assert data_source.source_url == "https://media.ethics.ga.gov/search/Campaign/Campaign_ByExpenditures.aspx"

    def test_build_ga_data_source_unsupported_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported GA transaction type"):
            build_ga_data_source("invalid_transaction_type")

    def test_extract_ga_contribution_composes_sub_extractors(
        self,
        contribution_rows: list[dict[str, object]],
    ) -> None:
        extraction = extract_ga_contribution(fixture_row(contribution_rows, 1))

        assert set(extraction.keys()) == {"donor_person", "donor_org", "committee", "candidate", "address"}
        assert isinstance(extraction["committee"], Organization)
        assert isinstance(extraction["candidate"], Person)
        assert isinstance(extraction["address"], Address)
        assert (extraction["donor_person"] is None) != (extraction["donor_org"] is None)

    def test_extract_ga_expenditure_composes_sub_extractors(
        self,
        expenditure_rows: list[dict[str, object]],
    ) -> None:
        extraction = extract_ga_expenditure(fixture_row(expenditure_rows, 1))

        assert set(extraction.keys()) == {"payee_person", "payee_org", "committee", "candidate", "address"}
        assert isinstance(extraction["committee"], Organization)
        assert isinstance(extraction["candidate"], Person)
        assert isinstance(extraction["address"], Address)
        assert (extraction["payee_person"] is None) != (extraction["payee_org"] is None)
