from __future__ import annotations

from pathlib import Path

import pytest

from core.types.python.models import Address, Organization, Person
from domains.campaign_finance.jurisdictions.states.CO.scraper.extract import (
    extract_address,
    extract_committee,
    extract_co_expenditure,
    extract_contributor_org,
    extract_co_contribution,
    extract_person,
)
from domains.campaign_finance.jurisdictions.states.CO.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)


@pytest.fixture(scope="module")
def contribution_rows() -> list[dict[str, str | None]]:
    fixture_path = Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"
    return list(parse_contributions(fixture_path))


@pytest.fixture(scope="module")
def expenditure_rows() -> list[dict[str, str | None]]:
    fixture_path = Path(__file__).parent / "test_fixtures" / "sample_expenditures.csv"
    return list(parse_expenditures(fixture_path))


def fixture_row(rows: list[dict[str, str | None]], row_number: int) -> dict[str, str | None]:
    return rows[row_number - 1]


class TestPersonExtraction:
    def test_extract_person_from_individual_row(self, contribution_rows: list[dict[str, str | None]]):
        person = extract_person(fixture_row(contribution_rows, 1))

        assert person is not None
        assert person.canonical_name == "Jane Doe"
        assert person.first_name == "Jane"
        assert person.last_name == "Doe"
        assert person.identifiers["employer"] == "Acme Corp"
        assert person.identifiers["occupation"] == "Engineer"

    def test_extract_person_business_row_returns_none(self, contribution_rows: list[dict[str, str | None]]):
        assert extract_person(fixture_row(contribution_rows, 2)) is None

    def test_extract_person_llc_member_includes_llc_identifier(self, contribution_rows: list[dict[str, str | None]]):
        person = extract_person(fixture_row(contribution_rows, 3))

        assert person is not None
        assert person.identifiers["llc_name"] == "HOWES WOLF LLC"

    def test_extract_person_normalizes_padded_contributor_type(
        self,
        contribution_rows: list[dict[str, str | None]],
    ):
        row = dict(fixture_row(contribution_rows, 1))
        row["ContributorType"] = "  Individual  "

        person = extract_person(row)

        assert person is not None
        assert person.canonical_name == "Jane Doe"

    def test_extract_person_normalizes_name_fields(
        self,
        contribution_rows: list[dict[str, str | None]],
    ):
        row = dict(fixture_row(contribution_rows, 1))
        row["FirstName"] = " Jane "
        row["MI"] = " Q "
        row["LastName"] = " Doe "
        row["Suffix"] = " Jr "

        person = extract_person(row)

        assert person is not None
        assert person.canonical_name == "Jane Q Doe Jr"
        assert person.first_name == "Jane"
        assert person.middle_name == "Q"
        assert person.last_name == "Doe"
        assert person.suffix == "Jr"

    def test_extract_person_strips_identifier_whitespace_and_skips_blank_values(
        self,
        contribution_rows: list[dict[str, str | None]],
    ):
        row = dict(fixture_row(contribution_rows, 1))
        row["Employer"] = "  Acme Corp  "
        row["Occupation"] = "   "
        row["OccupationComments"] = "  Works nights  "

        person = extract_person(row)

        assert person is not None
        assert person.identifiers == {
            "employer": "Acme Corp",
            "occupation_comments": "Works nights",
        }

    def test_extract_person_with_middle_initial_and_suffix(self, contribution_rows: list[dict[str, str | None]]):
        person = extract_person(fixture_row(contribution_rows, 9))

        assert person is not None
        assert person.canonical_name == "Pat Q Johnson Jr"

    def test_extract_person_non_itemized_row_returns_none(self, contribution_rows: list[dict[str, str | None]]):
        assert extract_person(fixture_row(contribution_rows, 6)) is None


class TestOrganizationExtraction:
    def test_extract_committee(self, contribution_rows: list[dict[str, str | None]]):
        committee = extract_committee(fixture_row(contribution_rows, 1))

        assert committee.canonical_name == "Friends of Example"
        assert committee.org_type == "candidate committee"
        assert committee.identifiers == {"co_committee_id": "20155000001"}

    def test_extract_committee_omits_missing_id_and_normalizes_whitespace(
        self,
        contribution_rows: list[dict[str, str | None]],
    ):
        row = dict(fixture_row(contribution_rows, 1))
        row["CommitteeName"] = "  Friends of Example  "
        row["CommitteeType"] = "  Candidate Committee  "
        row["CO_ID"] = None

        committee = extract_committee(row)

        assert committee.canonical_name == "Friends of Example"
        assert committee.org_type == "candidate committee"
        assert committee.identifiers == {}

    def test_extract_contributor_org_business_row(self, contribution_rows: list[dict[str, str | None]]):
        contributor_org = extract_contributor_org(fixture_row(contribution_rows, 2))

        assert contributor_org is not None
        assert contributor_org.canonical_name == "HOWES WOLF LLC"

    def test_extract_contributor_org_normalizes_padded_contributor_type(
        self,
        contribution_rows: list[dict[str, str | None]],
    ):
        row = dict(fixture_row(contribution_rows, 2))
        row["ContributorType"] = "  Business  "

        contributor_org = extract_contributor_org(row)

        assert contributor_org is not None
        assert contributor_org.canonical_name == "HOWES WOLF LLC"

    def test_extract_contributor_org_for_corporation_and_committee_rows(
        self,
        contribution_rows: list[dict[str, str | None]],
    ):
        corporation = extract_contributor_org(fixture_row(contribution_rows, 7))
        political_committee = extract_contributor_org(fixture_row(contribution_rows, 8))

        assert corporation is not None
        assert political_committee is not None

    def test_extract_contributor_org_individual_row_returns_none(
        self,
        contribution_rows: list[dict[str, str | None]],
    ):
        assert extract_contributor_org(fixture_row(contribution_rows, 1)) is None


class TestAddressExtraction:
    def test_extract_address_from_normal_row(self, contribution_rows: list[dict[str, str | None]]):
        address = extract_address(fixture_row(contribution_rows, 1))

        assert address is not None
        assert address.raw_address == "123 Main St, Denver, CO, 80202"
        assert address.city == "Denver"
        assert address.state == "CO"
        assert address.zip5 == "80202"
        assert address.zip4 is None
        assert address.street_number == "123"

    def test_extract_address_splits_zip_plus4(self, contribution_rows: list[dict[str, str | None]]):
        address = extract_address(fixture_row(contribution_rows, 10))

        assert address is not None
        assert address.zip5 == "80241"
        assert address.zip4 == "1234"

    def test_extract_address_normalizes_whitespace(self, contribution_rows: list[dict[str, str | None]]):
        row = dict(fixture_row(contribution_rows, 1))
        row["Address1"] = "  123 Main St  "
        row["City"] = "  Denver  "
        row["State"] = "  co  "
        row["Zip"] = "  80202-1234  "

        address = extract_address(row)

        assert address is not None
        assert address.raw_address == "123 Main St, Denver, CO, 80202-1234"
        assert address.state == "CO"
        assert address.zip5 == "80202"
        assert address.zip4 == "1234"

    def test_extract_address_includes_address2_when_present(self, contribution_rows: list[dict[str, str | None]]):
        address = extract_address(fixture_row(contribution_rows, 9))

        assert address is not None
        assert address.raw_address == "222 Elm St, Apt 4, Fort Collins, CO, 80521"

    def test_extract_address_with_empty_city_and_state_returns_none(
        self,
        contribution_rows: list[dict[str, str | None]],
    ):
        row = dict(fixture_row(contribution_rows, 1))
        row["City"] = None
        row["State"] = None

        assert extract_address(row) is None

    @pytest.mark.parametrize(
        "raw_zip, expected_zip5",
        [
            ("80521", "80521"),
            ("6371", None),  # 4-digit international postal code
            ("5403", None),
            ("180202", None),  # 6-digit postal code
            ("8401", None),
            ("80521-1234", "80521"),  # zip+4 still works
            ("", None),
            (None, None),
        ],
    )
    def test_extract_address_handles_non_5_digit_zip_gracefully(
        self,
        contribution_rows: list[dict[str, str | None]],
        raw_zip: str | None,
        expected_zip5: str | None,
    ):
        """Regression: live TRACER data includes international postal codes that are
        not 5-digit US zips. extract_address must not raise on these."""
        row = dict(fixture_row(contribution_rows, 1))
        row["Zip"] = raw_zip

        address = extract_address(row)

        assert address is not None
        assert address.zip5 == expected_zip5


class TestFullRecordExtraction:
    def test_extract_co_contribution_individual_row(self, contribution_rows: list[dict[str, str | None]]):
        extracted = extract_co_contribution(fixture_row(contribution_rows, 1))

        assert set(extracted.keys()) == {"person", "committee", "contributor_org", "address"}
        assert isinstance(extracted["person"], Person)
        assert isinstance(extracted["committee"], Organization)
        assert extracted["contributor_org"] is None
        assert isinstance(extracted["address"], Address)

    def test_extract_co_contribution_business_row(self, contribution_rows: list[dict[str, str | None]]):
        extracted = extract_co_contribution(fixture_row(contribution_rows, 2))

        assert extracted["person"] is None
        assert isinstance(extracted["contributor_org"], Organization)


class TestExpenditureExtraction:
    def test_extract_co_expenditure_individual_payee(self, expenditure_rows: list[dict[str, str | None]]) -> None:
        row = dict(fixture_row(expenditure_rows, 1))
        row["Employer"] = "Ignored Employer"
        row["Occupation"] = "Ignored Occupation"

        extracted = extract_co_expenditure(row)

        assert extracted["payee_person"] is not None
        assert extracted["payee_person"].canonical_name == "Elena Garcia"
        assert extracted["payee_person"].identifiers == {}
        assert extracted["payee_org"] is None

    def test_extract_co_expenditure_normalizes_payee_name_fields(
        self,
        expenditure_rows: list[dict[str, str | None]],
    ) -> None:
        row = dict(fixture_row(expenditure_rows, 1))
        row["FirstName"] = " Elena "
        row["MI"] = " Q "
        row["LastName"] = " Garcia "
        row["Suffix"] = " Jr "

        extracted = extract_co_expenditure(row)

        assert extracted["payee_person"] is not None
        assert extracted["payee_person"].canonical_name == "Elena Q Garcia Jr"
        assert extracted["payee_person"].first_name == "Elena"
        assert extracted["payee_person"].middle_name == "Q"
        assert extracted["payee_person"].last_name == "Garcia"
        assert extracted["payee_person"].suffix == "Jr"

    def test_extract_co_expenditure_business_payee(self, expenditure_rows: list[dict[str, str | None]]) -> None:
        extracted = extract_co_expenditure(fixture_row(expenditure_rows, 2))

        assert extracted["payee_person"] is None
        assert extracted["payee_org"] is not None
        assert extracted["payee_org"].canonical_name == "ACME PRINTING LLC"

    def test_extract_co_expenditure_committee_always_has_identifier(
        self,
        expenditure_rows: list[dict[str, str | None]],
    ) -> None:
        individual_extraction = extract_co_expenditure(fixture_row(expenditure_rows, 1))
        business_extraction = extract_co_expenditure(fixture_row(expenditure_rows, 2))

        assert individual_extraction["committee"].identifiers["co_committee_id"] == "20155000001"
        assert business_extraction["committee"].identifiers["co_committee_id"] == "20155000002"
