"""Tests for entity extraction from FEC contribution records."""

import json
from pathlib import Path
from typing import get_type_hints
from uuid import uuid4

from domains.campaign_finance.entity_extractors.extract import extract_contribution, extract_entities

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "fec_sample_response.json"

_BASE_CONTRIBUTION = {
    "entity_type": "IND",
    "contributor_name": "DOE, JOHN A",
    "contributor_first_name": "JOHN",
    "contributor_last_name": "DOE",
    "contributor_middle_name": "A",
    "contributor_suffix": None,
    "contributor_employer": "ACME INC",
    "contributor_occupation": "ENGINEER",
    "contributor_street_1": "123 MAIN ST",
    "contributor_street_2": None,
    "contributor_city": "DURHAM",
    "contributor_state": "NC",
    "contributor_zip": "27701",
    "committee_id": "C00123456",
    "committee_name": "TEST PAC",
    "committee": {
        "name": "TEST PAC",
        "committee_type": "Q",
        "committee_type_full": "PAC - Qualified",
    },
}


def _build_contribution(**overrides) -> dict:
    contribution = dict(_BASE_CONTRIBUTION)
    contribution["committee"] = dict(_BASE_CONTRIBUTION["committee"])

    if "committee" in overrides:
        committee_override = overrides.pop("committee")
        if committee_override is None:
            contribution.pop("committee", None)
        else:
            contribution["committee"] = committee_override

    contribution.update(overrides)
    return contribution


def _load_fixture() -> list[dict]:
    with open(FIXTURE_PATH) as fixture_file:
        return json.load(fixture_file)["results"]


class TestPersonExtraction:
    def test_individual_with_pre_parsed_names(self):
        result = extract_contribution(_build_contribution())
        person = result["person"]

        assert person is not None
        assert person.canonical_name == "John A Doe"
        assert person.first_name == "JOHN"
        assert person.last_name == "DOE"
        assert person.middle_name == "A"
        assert person.suffix is None
        assert person.identifiers == {"employer": "ACME INC", "occupation": "ENGINEER"}

    def test_fallback_to_parse_fec_name_when_all_preparsed_null(self):
        result = extract_contribution(
            _build_contribution(
                contributor_name="SMITH, JANE B",
                contributor_first_name=None,
                contributor_last_name=None,
                contributor_middle_name=None,
                contributor_suffix=None,
                contributor_employer=None,
                contributor_occupation=None,
            )
        )
        person = result["person"]

        assert person is not None
        assert person.canonical_name == "Jane B Smith"
        assert person.first_name == "JANE"
        assert person.last_name == "SMITH"
        assert person.middle_name == "B"

    def test_partial_preparsed_names_fill_missing_parts_from_raw_name(self):
        result = extract_contribution(
            _build_contribution(
                contributor_name="DOE, JOHN A",
                contributor_first_name=None,
                contributor_last_name="DOE",
                contributor_middle_name=None,
                contributor_suffix=None,
            )
        )
        person = result["person"]

        assert person is not None
        assert person.canonical_name == "John A Doe"
        assert person.first_name == "JOHN"
        assert person.middle_name == "A"
        assert person.last_name == "DOE"

    def test_partial_preparsed_middle_and_suffix_fill_from_raw_name(self):
        result = extract_contribution(
            _build_contribution(
                contributor_name="DOE, JOHN A JR",
                contributor_first_name="JOHN",
                contributor_last_name="DOE",
                contributor_middle_name=None,
                contributor_suffix=None,
            )
        )
        person = result["person"]

        assert person is not None
        assert person.canonical_name == "John A Doe"
        assert person.first_name == "JOHN"
        assert person.middle_name == "A"
        assert person.last_name == "DOE"
        assert person.suffix == "JR"


class TestOrganizationExtraction:
    def test_basic_organization(self):
        result = extract_contribution(_build_contribution(committee_name="FRIENDS OF DEMOCRACY PAC"))
        org = result["organization"]

        assert org.canonical_name == "FRIENDS OF DEMOCRACY PAC"
        assert org.identifiers == {"fec_committee_id": "C00123456"}
        assert org.org_type == "pac - qualified"

    def test_committee_name_from_nested_when_flat_is_none(self):
        result = extract_contribution(
            _build_contribution(
                committee_id="C00421230",
                committee_name=None,
                committee={
                    "name": "AIRBUS AMERICAS, INC. POLITICAL ACTION COMMITTEE",
                    "committee_type": "Q",
                    "committee_type_full": "PAC - Qualified",
                },
            )
        )

        assert result["organization"].canonical_name == "AIRBUS AMERICAS, INC. POLITICAL ACTION COMMITTEE"

    def test_no_nested_committee_type(self):
        result = extract_contribution(
            _build_contribution(
                committee_name="SOME PAC",
                committee={"name": "SOME PAC", "committee_type": "Q"},
            )
        )
        assert result["organization"].org_type is None

    def test_missing_committee_object(self):
        result = extract_contribution(_build_contribution(committee_name="SOME PAC", committee=None))
        org = result["organization"]

        assert org.org_type is None
        assert org.canonical_name == "SOME PAC"


class TestAddressExtraction:
    def test_full_address_with_9digit_zip(self):
        result = extract_contribution(_build_contribution(contributor_street_2="", contributor_zip="277011234"))
        addr = result["address"]

        assert addr is not None
        assert addr.city == "DURHAM"
        assert addr.state == "NC"
        assert addr.zip5 == "27701"
        assert addr.zip4 == "1234"
        assert addr.raw_address == "123 MAIN ST, DURHAM, NC 27701"

    def test_5digit_zip(self):
        result = extract_contribution(
            _build_contribution(
                contributor_street_1="456 OAK AVE",
                contributor_city="CHARLOTTE",
                contributor_zip="28202",
            )
        )
        addr = result["address"]

        assert addr.zip5 == "28202"
        assert addr.zip4 is None

    def test_street_2_included_in_raw(self):
        result = extract_contribution(
            _build_contribution(
                contributor_street_1="PALLADIAN CORPORATE CENTER",
                contributor_street_2="220 LEIGH FARM ROAD",
                contributor_zip="277078110",
            )
        )
        addr = result["address"]

        assert addr.raw_address == "PALLADIAN CORPORATE CENTER, 220 LEIGH FARM ROAD, DURHAM, NC 27707"

    def test_missing_street_raw_address_from_city_state_zip(self):
        result = extract_contribution(
            _build_contribution(
                contributor_street_1=None,
                contributor_street_2=None,
                contributor_city="RALEIGH",
                contributor_zip="27601",
            )
        )

        assert result["address"].raw_address == "RALEIGH, NC 27601"

    def test_missing_city(self):
        result = extract_contribution(_build_contribution(contributor_city=None))
        addr = result["address"]

        assert addr is not None
        assert addr.city is None
        assert addr.state == "NC"

    def test_alphanumeric_postal_code_preserves_raw_address_but_drops_zip_fields(self):
        result = extract_contribution(
            _build_contribution(
                contributor_city="TORONTO",
                contributor_state="ZZ",
                contributor_zip="M6C2V2",
            )
        )
        addr = result["address"]

        assert addr is not None
        assert addr.zip5 is None
        assert addr.zip4 is None
        assert addr.raw_address == "123 MAIN ST, TORONTO, ZZ M6C2V2"

    def test_alphanumeric_postal_code_with_five_digits_still_drops_zip_fields(self):
        result = extract_contribution(
            _build_contribution(
                contributor_city="PARIS",
                contributor_state="ZZ",
                contributor_zip="75008 CEDEX 01",
            )
        )
        addr = result["address"]

        assert addr is not None
        assert addr.zip5 is None
        assert addr.zip4 is None
        assert addr.raw_address == "123 MAIN ST, PARIS, ZZ 75008 CEDEX 01"


class TestEdgeCases:
    def test_missing_employer_and_occupation(self):
        result = extract_contribution(_build_contribution(contributor_employer=None, contributor_occupation=None))
        assert result["person"].identifiers == {}

    def test_non_individual_entity_type_returns_none_person(self):
        for entity_type in ["COM", "ORG"]:
            result = extract_contribution(
                _build_contribution(
                    entity_type=entity_type,
                    contributor_name="WELLS FARGO PAC ACCOUNT",
                    contributor_first_name=None,
                    contributor_last_name=None,
                    contributor_middle_name=None,
                    contributor_suffix=None,
                    committee_name=None,
                )
            )
            assert result["person"] is None, f"entity_type={entity_type} should yield person=None"

    def test_missing_state_returns_none_address(self):
        result = extract_contribution(_build_contribution(contributor_state=None))
        assert result["address"] is None

    def test_empty_zip(self):
        result = extract_contribution(_build_contribution(contributor_zip=None))
        addr = result["address"]

        assert addr.zip5 is None
        assert addr.zip4 is None

    def test_ind_with_null_pre_parsed_but_contributor_name_set(self):
        result = extract_contribution(
            _build_contribution(
                contributor_name="JONES, ALICE M SR",
                contributor_first_name=None,
                contributor_last_name=None,
                contributor_middle_name=None,
                contributor_suffix=None,
                contributor_employer="TECH CORP",
                contributor_occupation="DEVELOPER",
                contributor_city="APEX",
                contributor_zip="27502",
                committee_id="C00999999",
                committee_name=None,
                committee={
                    "name": "TECH PAC",
                    "committee_type": "Q",
                    "committee_type_full": "PAC - Qualified",
                },
            )
        )
        person = result["person"]

        assert person is not None
        assert person.canonical_name == "Alice M Jones"
        assert person.first_name == "ALICE"
        assert person.last_name == "JONES"
        assert person.middle_name == "M"
        assert person.suffix == "SR"

    def test_blank_preparsed_names_do_not_produce_empty_person_when_raw_parse_fails(self):
        result = extract_contribution(
            _build_contribution(
                contributor_name="NOT A VALID FEC NAME",
                contributor_first_name="",
                contributor_last_name="",
                contributor_middle_name="",
                contributor_suffix="",
            )
        )

        assert result["person"] is None


class TestEndToEndFixtureExtraction:
    def test_all_fixture_records(self):
        records = _load_fixture()

        for index, record in enumerate(records):
            result = extract_contribution(record)

            org = result["organization"]
            assert org.canonical_name, f"Record {index}: org should have a canonical_name"
            assert "fec_committee_id" in org.identifiers, f"Record {index}: org should have fec_committee_id"

            if record.get("entity_type") == "IND":
                person = result["person"]
                assert person is not None, f"Record {index}: IND should produce a Person"
                assert person.canonical_name, f"Record {index}: person should have a canonical_name"

            if record.get("contributor_state"):
                addr = result["address"]
                assert addr is not None, f"Record {index}: should produce an Address when state is present"
                assert len(addr.state) == 2, f"Record {index}: state should be 2-letter code"
                assert addr.state == addr.state.upper(), f"Record {index}: state should be uppercase"
                assert addr.raw_address, f"Record {index}: raw_address should be non-empty"


class TestPluginContractAdapter:
    def test_extract_entities_uses_shared_entity_extraction_contract(self):
        from core.types.python.extraction import EntityExtraction as SharedEntityExtraction
        from domains.campaign_finance.entity_extractors import extract as extractor_module

        assert get_type_hints(extractor_module.extract_entities)["return"] == list[SharedEntityExtraction]

    def test_extract_entities_returns_person_and_organization_for_individual(self):
        source_record_id = uuid4()
        entities = extract_entities(_build_contribution(source_record_id=str(source_record_id)))

        assert len(entities) == 2
        by_type = {entity["entity_type"]: entity for entity in entities}
        assert by_type["person"]["name"] == "John A Doe"
        assert by_type["person"]["source_record_id"] == source_record_id
        assert by_type["organization"]["name"] == "TEST PAC"
        assert by_type["organization"]["source_record_id"] == source_record_id

    def test_extract_entities_returns_organization_only_for_non_individual(self):
        entities = extract_entities(_build_contribution(entity_type="COM"))

        assert [entity["entity_type"] for entity in entities] == ["organization"]
