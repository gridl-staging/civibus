from __future__ import annotations

from pathlib import Path

import pytest

from core.types.python.models import Address, Organization, Person
from domains.campaign_finance.jurisdictions.states.NC.scraper.extract import (
    extract_address,
    extract_committee,
    extract_contributor_org,
    extract_nc_transaction,
    extract_person,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import parse_transactions


@pytest.fixture(scope="module")
def transaction_rows() -> list[dict[str, str | None]]:
    fixture_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "transaction_export_sample.csv"
    return list(parse_transactions(fixture_path))


def fixture_row(rows: list[dict[str, str | None]], row_number: int) -> dict[str, str | None]:
    return rows[row_number - 1]


class TestPersonExtraction:
    def test_extract_person_parses_nc_name_field(self, transaction_rows: list[dict[str, str | None]]) -> None:
        row = dict(fixture_row(transaction_rows, 1))
        row["Name"] = "SMITH, JANE A"

        person = extract_person(row)

        assert person is not None
        assert person.first_name == "JANE"
        assert person.last_name == "SMITH"
        assert person.canonical_name == "Jane A Smith"

    def test_extract_person_non_person_transaction_returns_none(
        self,
        transaction_rows: list[dict[str, str | None]],
    ) -> None:
        row = fixture_row(transaction_rows, 5)

        assert extract_person(row) is None

    def test_extract_person_blank_name_returns_none(self, transaction_rows: list[dict[str, str | None]]) -> None:
        assert extract_person(fixture_row(transaction_rows, 1)) is None

    def test_extract_person_populates_identifiers_and_skips_blanks(
        self,
        transaction_rows: list[dict[str, str | None]],
    ) -> None:
        row_with_identifiers = dict(fixture_row(transaction_rows, 1))
        row_with_identifiers["Name"] = "SMITH, JANE"
        row_with_identifiers["Profession/Job Title"] = "Engineer"
        row_with_identifiers["Employer's Name/Specific Field"] = "Acme Corp"

        person_with_identifiers = extract_person(row_with_identifiers)

        assert person_with_identifiers is not None
        assert person_with_identifiers.identifiers == {
            "occupation": "Engineer",
            "employer": "Acme Corp",
        }

        row_with_blank_identifier = dict(row_with_identifiers)
        row_with_blank_identifier["Profession/Job Title"] = "   "

        person_with_blank_identifier = extract_person(row_with_blank_identifier)

        assert person_with_blank_identifier is not None
        assert person_with_blank_identifier.identifiers == {
            "employer": "Acme Corp",
        }


class TestCommitteeExtraction:
    def test_extract_committee_from_fixture(self, transaction_rows: list[dict[str, str | None]]) -> None:
        committee = extract_committee(fixture_row(transaction_rows, 1))

        assert committee.canonical_name == "CAROLINA LINK BROADBAND COOPERATIVE PAC"
        assert committee.identifiers == {"nc_sboe_id": "STA-C3352N-C-001"}

    def test_extract_committee_allows_blank_name_and_id(
        self,
        transaction_rows: list[dict[str, str | None]],
    ) -> None:
        row = dict(fixture_row(transaction_rows, 1))
        row["Committee Name"] = None
        row["Committee SBoE ID"] = ""

        committee = extract_committee(row)

        assert committee.canonical_name == ""
        assert committee.identifiers == {}


class TestContributorOrganizationExtraction:
    def test_extract_contributor_org_non_party_committee_and_individual(
        self,
        transaction_rows: list[dict[str, str | None]],
    ) -> None:
        non_party_committee_row = fixture_row(transaction_rows, 5)
        individual_row = fixture_row(transaction_rows, 1)

        contributor_org = extract_contributor_org(non_party_committee_row)

        assert contributor_org is not None
        assert (
            contributor_org.canonical_name
            == "NORTH CAROLINA FARM BUREAU FEDERATION INC POL ACT CMTE INC (AKA) NC FARM BUREAU"
        )
        assert extract_contributor_org(individual_row) is None

    @pytest.mark.parametrize("missing_type", [None, " "])
    def test_extract_contributor_org_returns_none_when_transaction_type_blank(
        self,
        transaction_rows: list[dict[str, str | None]],
        missing_type: str | None,
    ) -> None:
        row = dict(fixture_row(transaction_rows, 5))
        row["Transction Type"] = missing_type

        assert extract_contributor_org(row) is None


class TestAddressExtraction:
    def test_extract_address_from_entity_columns(self, transaction_rows: list[dict[str, str | None]]) -> None:
        address = extract_address(fixture_row(transaction_rows, 1))

        assert address is not None
        assert address.city == "Shallotte"
        assert address.state == "NC"
        assert address.zip5 == "28470"
        assert address.street_number == "4"
        assert address.raw_address == "4 Kings Grant Ct, Shallotte, NC, 28470-9999"

    def test_extract_address_filters_zip4_placeholder_and_preserves_real_zip4(
        self,
        transaction_rows: list[dict[str, str | None]],
    ) -> None:
        placeholder_zip_address = extract_address(fixture_row(transaction_rows, 1))

        assert placeholder_zip_address is not None
        assert placeholder_zip_address.zip5 == "28470"
        assert placeholder_zip_address.zip4 is None

        real_zip_row = dict(fixture_row(transaction_rows, 1))
        real_zip_row["Zip Code"] = "28411-1234"

        real_zip_address = extract_address(real_zip_row)

        assert real_zip_address is not None
        assert real_zip_address.zip5 == "28411"
        assert real_zip_address.zip4 == "1234"

    def test_extract_address_includes_street_line_2_when_present(
        self,
        transaction_rows: list[dict[str, str | None]],
    ) -> None:
        row = dict(fixture_row(transaction_rows, 1))
        row["Street Line 2"] = "Unit B"

        address = extract_address(row)

        assert address is not None
        assert address.raw_address == "4 Kings Grant Ct, Unit B, Shallotte, NC, 28470-9999"

    def test_extract_address_discards_zip4_when_zip5_missing(
        self,
        transaction_rows: list[dict[str, str | None]],
    ) -> None:
        row = dict(fixture_row(transaction_rows, 1))
        row["Zip Code"] = "-1234"

        address = extract_address(row)

        assert address is not None
        assert address.zip5 is None
        assert address.zip4 is None

    def test_extract_address_returns_none_when_city_and_state_blank(
        self,
        transaction_rows: list[dict[str, str | None]],
    ) -> None:
        row = dict(fixture_row(transaction_rows, 1))
        row["City"] = " "
        row["State"] = None

        assert extract_address(row) is None


class TestTopLevelExtraction:
    def test_extract_nc_transaction_returns_all_keys(
        self,
        transaction_rows: list[dict[str, str | None]],
    ) -> None:
        individual_extraction = extract_nc_transaction(fixture_row(transaction_rows, 1))
        non_party_committee_extraction = extract_nc_transaction(fixture_row(transaction_rows, 5))

        assert set(individual_extraction.keys()) == {"person", "committee", "contributor_org", "address"}
        assert individual_extraction["person"] is None
        assert isinstance(individual_extraction["committee"], Organization)
        assert individual_extraction["contributor_org"] is None
        assert isinstance(individual_extraction["address"], Address)

        assert non_party_committee_extraction["person"] is None
        assert isinstance(non_party_committee_extraction["contributor_org"], Organization)

        for value in (individual_extraction["person"], non_party_committee_extraction["person"]):
            assert value is None or isinstance(value, Person)
