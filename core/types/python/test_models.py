from datetime import date, datetime, timezone
from math import nan
from typing import get_args
from uuid import UUID, uuid4

import pytest

from core.types.python.models import (
    Address,
    ContactPoint,
    Jurisdiction,
    Organization,
    Person,
    PersonPortrait,
    PortraitRightsStatus,
    ValidDateRange,
)


class TestPersonModel:
    def test_person_creation_minimum_fields_uses_defaults(self) -> None:
        person = Person(canonical_name="Jane Doe")

        assert isinstance(person.id, UUID)
        assert person.canonical_name == "Jane Doe"
        assert person.name_variants == []
        assert person.identifiers == {}
        assert isinstance(person.created_at, datetime)
        assert isinstance(person.updated_at, datetime)
        assert person.created_at.tzinfo is not None
        assert person.updated_at.tzinfo is not None

    def test_person_optional_fields_default_to_none(self) -> None:
        person = Person(canonical_name="Jane Doe")

        assert person.first_name is None
        assert person.middle_name is None
        assert person.last_name is None
        assert person.suffix is None
        assert person.bio_text is None
        assert person.bio_source_url is None
        assert person.bio_license is None
        assert person.bio_pulled_at is None
        assert person.date_of_birth is None
        assert person.year_of_birth is None
        assert person.primary_address_id is None
        assert person.er_cluster_id is None
        assert person.er_confidence is None

    def test_person_accepts_stage5_bio_fields_when_populated(self) -> None:
        pulled_at = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        person = Person(
            canonical_name="Jane Doe",
            bio_text="Jane Doe is a public servant.",
            bio_source_url="https://example.com/bio/jane-doe",
            bio_license="licensed",
            bio_pulled_at=pulled_at,
        )

        assert person.bio_text == "Jane Doe is a public servant."
        assert person.bio_source_url == "https://example.com/bio/jane-doe"
        assert person.bio_license == "licensed"
        assert person.bio_pulled_at == pulled_at

    @pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
    def test_person_er_confidence_accepts_range(self, confidence: float) -> None:
        person = Person(canonical_name="Jane Doe", er_confidence=confidence)

        assert person.er_confidence == confidence

    @pytest.mark.parametrize("confidence", [-0.01, 1.01, nan])
    def test_person_er_confidence_rejects_out_of_range(self, confidence: float) -> None:
        with pytest.raises(ValueError):
            Person(canonical_name="Jane Doe", er_confidence=confidence)

    def test_person_model_dump_round_trip_and_json_mode(self) -> None:
        original = Person(
            canonical_name="Jane Doe",
            name_variants=["J. Doe"],
            first_name="Jane",
            middle_name="A",
            last_name="Doe",
            suffix="Jr",
            date_of_birth=date(1990, 4, 3),
            year_of_birth=1990,
            identifiers={"fec_id": "P123"},
        )

        dumped = original.model_dump()
        recreated = Person(**dumped)

        assert recreated == original
        assert isinstance(dumped["created_at"], datetime)
        assert isinstance(dumped["updated_at"], datetime)
        assert dumped["created_at"].tzinfo is not None
        assert dumped["updated_at"].tzinfo is not None

        json_dumped = original.model_dump(mode="json")
        assert isinstance(json_dumped["id"], str)
        assert isinstance(json_dumped["created_at"], str)
        assert isinstance(json_dumped["updated_at"], str)

    def test_person_identifiers_rejects_non_string_values(self) -> None:
        with pytest.raises(ValueError):
            Person(canonical_name="Jane Doe", identifiers={"fec_id": 123})

    def test_person_identifiers_rejects_non_string_key(self) -> None:
        with pytest.raises(ValueError):
            Person(canonical_name="Jane Doe", identifiers={1: "P123"})  # type: ignore[arg-type]


class TestOrganizationModel:
    def test_organization_creation_minimum_fields_uses_defaults(self) -> None:
        organization = Organization(canonical_name="Civibus Action Fund")

        assert isinstance(organization.id, UUID)
        assert organization.canonical_name == "Civibus Action Fund"
        assert organization.name_variants == []
        assert organization.identifiers == {}
        assert isinstance(organization.created_at, datetime)
        assert isinstance(organization.updated_at, datetime)
        assert organization.created_at.tzinfo is not None
        assert organization.updated_at.tzinfo is not None

    def test_organization_optional_fields_default_to_none(self) -> None:
        organization = Organization(canonical_name="Civibus Action Fund")

        assert organization.org_type is None
        assert organization.registered_state is None
        assert organization.formation_date is None
        assert organization.dissolution_date is None
        assert organization.primary_address_id is None
        assert organization.er_cluster_id is None
        assert organization.er_confidence is None

    @pytest.mark.parametrize("state", ["NC", "CA"])
    def test_organization_registered_state_accepts_two_letter_codes(self, state: str) -> None:
        organization = Organization(canonical_name="Civibus Action Fund", registered_state=state)

        assert organization.registered_state == state

    @pytest.mark.parametrize("state", ["North Carolina", "X", "123", "nc"])
    def test_organization_registered_state_rejects_invalid_values(self, state: str) -> None:
        with pytest.raises(ValueError):
            Organization(canonical_name="Civibus Action Fund", registered_state=state)

    def test_organization_registered_state_allows_none(self) -> None:
        organization = Organization(canonical_name="Civibus Action Fund", registered_state=None)

        assert organization.registered_state is None

    def test_organization_model_dump_round_trip_and_json_mode(self) -> None:
        original = Organization(
            canonical_name="Civibus Action Fund",
            name_variants=["CAF"],
            org_type="pac",
            identifiers={"ein": "12-3456789"},
            registered_state="NC",
            formation_date=date(2011, 2, 5),
            dissolution_date=date(2020, 6, 1),
        )

        dumped = original.model_dump()
        recreated = Organization(**dumped)

        assert recreated == original

        json_dumped = original.model_dump(mode="json")
        assert isinstance(json_dumped["id"], str)
        assert isinstance(json_dumped["created_at"], str)
        assert isinstance(json_dumped["updated_at"], str)

    def test_organization_identifiers_rejects_non_string_values(self) -> None:
        with pytest.raises(ValueError):
            Organization(canonical_name="Civibus Action Fund", identifiers={"ein": 123456789})


class TestPersonPortraitModel:
    def test_person_portrait_derives_dedup_key_from_image_hash_only(self) -> None:
        source_record_id = UUID("00000000-0000-0000-0000-000000000111")
        image_hash = "7f63cb6d067972c3f34f094bb7e776a8f7f5bf3ce6f5f8a761fd72d4e95f94c4"
        portrait = PersonPortrait(
            person_id=UUID("00000000-0000-0000-0000-000000000222"),
            source_record_id=source_record_id,
            image_hash=image_hash,
        )
        portrait_with_different_source = PersonPortrait(
            person_id=UUID("00000000-0000-0000-0000-000000000222"),
            source_record_id=UUID("00000000-0000-0000-0000-000000000333"),
            image_hash=image_hash,
        )

        assert portrait.dedup_key is not None
        assert len(portrait.dedup_key) == 64
        assert portrait_with_different_source.dedup_key == portrait.dedup_key

    @pytest.mark.parametrize(
        "status",
        ["active", "not_found", "too_small", "face_too_small", "takedown_requested", "superseded", "rejected"],
    )
    def test_person_portrait_accepts_stage_status_values(self, status: str) -> None:
        portrait = PersonPortrait(
            person_id=UUID("00000000-0000-0000-0000-000000000222"),
            source_record_id=UUID("00000000-0000-0000-0000-000000000111"),
            status=status,
            image_hash="7f63cb6d067972c3f34f094bb7e776a8f7f5bf3ce6f5f8a761fd72d4e95f94c4",
        )

        assert portrait.status == status

    def test_person_portrait_rejects_invalid_image_hash(self) -> None:
        with pytest.raises(ValueError):
            PersonPortrait(
                person_id=UUID("00000000-0000-0000-0000-000000000222"),
                source_record_id=UUID("00000000-0000-0000-0000-000000000111"),
                image_hash="not-a-hash",
            )


class TestAddressModel:
    def test_address_creation_minimum_fields_uses_defaults(self) -> None:
        address = Address(raw_address="123 Main St, Durham, NC 27701")

        assert isinstance(address.id, UUID)
        assert address.raw_address == "123 Main St, Durham, NC 27701"
        assert address.normalized_address is None
        assert address.street_number is None
        assert address.street_name is None
        assert address.unit is None
        assert address.city is None
        assert address.state is None
        assert address.zip5 is None
        assert address.zip4 is None
        assert address.county_fips is None
        assert address.geometry is None
        assert address.geocode_confidence is None
        assert address.geocode_source is None
        assert address.geocoded_at is None
        assert isinstance(address.created_at, datetime)
        assert isinstance(address.updated_at, datetime)
        assert address.created_at.tzinfo is not None
        assert address.updated_at.tzinfo is not None

    @pytest.mark.parametrize("zip5", ["27701"])
    def test_address_zip5_accepts_five_digits(self, zip5: str) -> None:
        address = Address(raw_address="123 Main St", zip5=zip5)

        assert address.zip5 == zip5

    @pytest.mark.parametrize("zip5", ["2770", "277011", "abcde", "\u0662\u0667\u0667\u0660\u0661"])
    def test_address_zip5_rejects_invalid_values(self, zip5: str) -> None:
        with pytest.raises(ValueError):
            Address(raw_address="123 Main St", zip5=zip5)

    def test_address_zip5_allows_none(self) -> None:
        address = Address(raw_address="123 Main St", zip5=None)

        assert address.zip5 is None

    @pytest.mark.parametrize("zip4", ["0001", "1234"])
    def test_address_zip4_accepts_four_digits(self, zip4: str) -> None:
        address = Address(raw_address="123 Main St", zip4=zip4)

        assert address.zip4 == zip4

    @pytest.mark.parametrize("zip4", ["123", "12345", "abcd"])
    def test_address_zip4_rejects_invalid_values(self, zip4: str) -> None:
        with pytest.raises(ValueError):
            Address(raw_address="123 Main St", zip4=zip4)

    def test_address_zip4_allows_none(self) -> None:
        address = Address(raw_address="123 Main St", zip4=None)

        assert address.zip4 is None

    @pytest.mark.parametrize("county_fips", ["37063", "01001"])
    def test_address_county_fips_accepts_five_digits(self, county_fips: str) -> None:
        address = Address(raw_address="123 Main St", county_fips=county_fips)

        assert address.county_fips == county_fips

    @pytest.mark.parametrize("county_fips", ["3706", "370630", "abcde"])
    def test_address_county_fips_rejects_invalid_values(self, county_fips: str) -> None:
        with pytest.raises(ValueError):
            Address(raw_address="123 Main St", county_fips=county_fips)

    def test_address_county_fips_allows_none(self) -> None:
        address = Address(raw_address="123 Main St", county_fips=None)

        assert address.county_fips is None

    @pytest.mark.parametrize("state", ["NC", "CA"])
    def test_address_state_accepts_two_letter_codes(self, state: str) -> None:
        address = Address(raw_address="123 Main St", state=state)

        assert address.state == state

    @pytest.mark.parametrize("state", ["North Carolina", "X", "123", "nc"])
    def test_address_state_rejects_invalid_values(self, state: str) -> None:
        with pytest.raises(ValueError):
            Address(raw_address="123 Main St", state=state)

    def test_address_state_allows_none(self) -> None:
        address = Address(raw_address="123 Main St", state=None)

        assert address.state is None

    @pytest.mark.parametrize("confidence", [0.0, 0.25, 1.0])
    def test_address_geocode_confidence_accepts_range(self, confidence: float) -> None:
        address = Address(raw_address="123 Main St", geocode_confidence=confidence)

        assert address.geocode_confidence == confidence

    @pytest.mark.parametrize("confidence", [-0.1, 1.1, nan])
    def test_address_geocode_confidence_rejects_out_of_range(self, confidence: float) -> None:
        with pytest.raises(ValueError):
            Address(raw_address="123 Main St", geocode_confidence=confidence)

    def test_address_geocode_confidence_allows_none(self) -> None:
        address = Address(raw_address="123 Main St", geocode_confidence=None)

        assert address.geocode_confidence is None

    def test_address_geometry_accepts_none_only_for_now(self) -> None:
        address = Address(raw_address="123 Main St", geometry=None)

        assert address.geometry is None

    def test_address_geometry_rejects_coordinates_for_stage_two(self) -> None:
        with pytest.raises(ValueError):
            Address(raw_address="123 Main St", geometry=(-78.8986, 35.9940))

    def test_address_model_dump_round_trip_and_json_mode(self) -> None:
        original = Address(
            raw_address="123 Main St, Durham, NC 27701",
            normalized_address="123 MAIN ST DURHAM NC 27701",
            street_number="123",
            street_name="Main St",
            unit="Apt 4",
            city="Durham",
            state="NC",
            zip5="27701",
            zip4="1234",
            county_fips="37063",
            geocode_confidence=0.95,
            geocode_source="census",
            geocoded_at=datetime.now().astimezone(),
        )

        dumped = original.model_dump()
        recreated = Address(**dumped)

        assert recreated == original

        json_dumped = original.model_dump(mode="json")
        assert isinstance(json_dumped["id"], str)
        assert isinstance(json_dumped["created_at"], str)
        assert isinstance(json_dumped["updated_at"], str)
        assert isinstance(json_dumped["geocoded_at"], str)


class TestJurisdictionModel:
    def test_jurisdiction_state_creation_with_expected_types(self) -> None:
        jurisdiction = Jurisdiction(
            name="North Carolina",
            jurisdiction_type="state",
            fips="37",
            state="NC",
        )

        assert jurisdiction.name == "North Carolina"
        assert jurisdiction.jurisdiction_type == "state"
        assert jurisdiction.fips == "37"
        assert jurisdiction.state == "NC"
        assert isinstance(jurisdiction.id, UUID)
        assert isinstance(jurisdiction.created_at, datetime)
        assert isinstance(jurisdiction.updated_at, datetime)
        assert jurisdiction.created_at.tzinfo is not None
        assert jurisdiction.updated_at.tzinfo is not None

    def test_jurisdiction_county_accepts_parent_id(self) -> None:
        parent_jurisdiction_id = uuid4()
        jurisdiction = Jurisdiction(
            name="Durham County",
            jurisdiction_type="county",
            parent_id=parent_jurisdiction_id,
        )

        assert jurisdiction.parent_id == parent_jurisdiction_id

    def test_jurisdiction_federal_allows_none_fips(self) -> None:
        jurisdiction = Jurisdiction(
            name="United States",
            jurisdiction_type="federal",
            fips=None,
        )

        assert jurisdiction.fips is None

    @pytest.mark.parametrize("fips", ["37A", "abc", "", "\u0663\u0667"])
    def test_jurisdiction_fips_rejects_non_digit_values(self, fips: str) -> None:
        with pytest.raises(ValueError):
            Jurisdiction(name="North Carolina", jurisdiction_type="state", fips=fips)

    @pytest.mark.parametrize("fips", ["37", "37063"])
    def test_jurisdiction_fips_accepts_variable_length_digits(self, fips: str) -> None:
        jurisdiction = Jurisdiction(name="North Carolina", jurisdiction_type="state", fips=fips)

        assert jurisdiction.fips == fips

    @pytest.mark.parametrize("jurisdiction_type", ["invalid_kind", "city", ""])
    def test_jurisdiction_type_rejects_invalid_values(self, jurisdiction_type: str) -> None:
        with pytest.raises(ValueError):
            Jurisdiction(name="North Carolina", jurisdiction_type=jurisdiction_type)

    @pytest.mark.parametrize("state", ["North Carolina", "nc", "X"])
    def test_jurisdiction_state_rejects_invalid_values(self, state: str) -> None:
        with pytest.raises(ValueError):
            Jurisdiction(name="North Carolina", jurisdiction_type="state", state=state)

    @pytest.mark.parametrize("state", ["NC", "CA"])
    def test_jurisdiction_state_accepts_two_letter_codes(self, state: str) -> None:
        jurisdiction = Jurisdiction(name="North Carolina", jurisdiction_type="state", state=state)

        assert jurisdiction.state == state

    def test_jurisdiction_state_allows_none(self) -> None:
        jurisdiction = Jurisdiction(name="United States", jurisdiction_type="federal", state=None)

        assert jurisdiction.state is None

    def test_jurisdiction_optional_fields_default_to_none(self) -> None:
        jurisdiction = Jurisdiction(name="North Carolina", jurisdiction_type="state")

        assert jurisdiction.fips is None
        assert jurisdiction.parent_id is None
        assert jurisdiction.state is None
        assert jurisdiction.geometry is None
        assert jurisdiction.population is None

    def test_jurisdiction_geometry_rejects_non_none_values(self) -> None:
        with pytest.raises(ValueError):
            Jurisdiction(name="North Carolina", jurisdiction_type="state", geometry="not-none")

    def test_jurisdiction_model_dump_round_trip_and_json_mode(self) -> None:
        original = Jurisdiction(
            id=uuid4(),
            name="Durham County",
            jurisdiction_type="county",
            fips="37063",
            parent_id=uuid4(),
            state="NC",
            geometry=None,
            population=330000,
            created_at=datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 3, 4, 5, 6, tzinfo=timezone.utc),
        )

        dumped = original.model_dump()
        recreated = Jurisdiction(**dumped)
        assert recreated == original

        json_dumped = original.model_dump(mode="json")
        assert isinstance(json_dumped["id"], str)
        assert isinstance(json_dumped["created_at"], str)
        assert isinstance(json_dumped["updated_at"], str)


class TestContactPointModel:
    def test_contact_point_creation_minimum_fields_uses_defaults(self) -> None:
        cp = ContactPoint(type="email", value_raw="info@example.com", owner_type="person", owner_id=uuid4())

        assert isinstance(cp.id, UUID)
        assert cp.type == "email"
        assert cp.value_raw == "info@example.com"
        assert cp.value_normalized is None
        assert cp.role is None
        assert cp.owner_type == "person"
        assert isinstance(cp.owner_id, UUID)
        assert cp.source_record_id is None
        assert cp.last_verified_at is None
        assert cp.is_preferred is False
        assert isinstance(cp.valid_period, ValidDateRange)
        assert cp.valid_period.start_date is None
        assert cp.valid_period.end_date is None
        assert isinstance(cp.created_at, datetime)
        assert isinstance(cp.updated_at, datetime)
        assert cp.created_at.tzinfo is not None
        assert cp.updated_at.tzinfo is not None

    def test_contact_point_rejects_empty_value_raw(self) -> None:
        with pytest.raises(ValueError):
            ContactPoint(type="email", value_raw="", owner_type="person", owner_id=uuid4())

    def test_contact_point_rejects_whitespace_only_value_raw(self) -> None:
        with pytest.raises(ValueError):
            ContactPoint(type="phone", value_raw="   ", owner_type="person", owner_id=uuid4())

    @pytest.mark.parametrize("owner_type", ["person", "organization", "office", "officeholding", "candidacy"])
    def test_contact_point_accepts_valid_owner_types(self, owner_type: str) -> None:
        cp = ContactPoint(type="email", value_raw="a@b.com", owner_type=owner_type, owner_id=uuid4())

        assert cp.owner_type == owner_type

    def test_contact_point_accepts_official_directory_contact_owned_by_office(self) -> None:
        cp = ContactPoint(
            type="phone",
            value_raw="202-225-3121",
            role="official_directory",
            owner_type="office",
            owner_id=uuid4(),
        )
        assert cp.owner_type == "office"
        assert cp.role == "official_directory"

    def test_contact_point_accepts_personal_official_contact_owned_by_officeholding(self) -> None:
        cp = ContactPoint(
            type="email",
            value_raw="rep@example.gov",
            role="official_directory",
            owner_type="officeholding",
            owner_id=uuid4(),
        )
        assert cp.owner_type == "officeholding"
        assert cp.role == "official_directory"

    @pytest.mark.parametrize("owner_type", ["address", "contest", "electoral_division", "invalid", ""])
    def test_contact_point_rejects_invalid_owner_types(self, owner_type: str) -> None:
        with pytest.raises(ValueError):
            ContactPoint(type="email", value_raw="a@b.com", owner_type=owner_type, owner_id=uuid4())

    def test_contact_point_parses_string_owner_id_to_uuid(self) -> None:
        owner_uuid = uuid4()
        cp = ContactPoint(type="phone", value_raw="555-0100", owner_type="organization", owner_id=str(owner_uuid))

        assert cp.owner_id == owner_uuid

    def test_contact_point_preferred_defaults_to_false(self) -> None:
        cp = ContactPoint(type="email", value_raw="a@b.com", owner_type="person", owner_id=uuid4())

        assert cp.is_preferred is False

    def test_contact_point_preferred_can_be_set_true(self) -> None:
        cp = ContactPoint(type="email", value_raw="a@b.com", owner_type="person", owner_id=uuid4(), is_preferred=True)

        assert cp.is_preferred is True

    def test_contact_point_optional_temporal_fields(self) -> None:
        cp = ContactPoint(
            type="email",
            value_raw="a@b.com",
            owner_type="person",
            owner_id=uuid4(),
            valid_period={"start_date": date(2024, 1, 1), "end_date": date(2025, 1, 1)},
        )

        assert cp.valid_period.start_date == date(2024, 1, 1)
        assert cp.valid_period.end_date == date(2025, 1, 1)

    def test_contact_point_rejects_invalid_temporal_range(self) -> None:
        with pytest.raises(ValueError, match="valid_period must be non-empty"):
            ContactPoint(
                type="email",
                value_raw="a@b.com",
                owner_type="person",
                owner_id=uuid4(),
                valid_period={"start_date": date(2025, 1, 1), "end_date": date(2024, 1, 1)},
            )

    def test_contact_point_model_dump_round_trip_and_json_mode(self) -> None:
        original = ContactPoint(
            type="phone",
            value_raw="(555) 123-4567",
            value_normalized="+15551234567",
            role="campaign",
            owner_type="candidacy",
            owner_id=uuid4(),
            is_preferred=True,
            valid_period={"start_date": date(2024, 1, 1), "end_date": date(2026, 12, 31)},
        )

        dumped = original.model_dump()
        recreated = ContactPoint(**dumped)

        assert recreated == original

        json_dumped = original.model_dump(mode="json")
        assert isinstance(json_dumped["id"], str)
        assert isinstance(json_dumped["created_at"], str)
        assert isinstance(json_dumped["updated_at"], str)
        assert isinstance(json_dumped["owner_id"], str)
        assert json_dumped["valid_period"] == {"start_date": "2024-01-01", "end_date": "2026-12-31"}


class TestModelJsonSchemaSmoke:
    def test_model_json_schema_exports_for_all_models(self) -> None:
        person_schema = Person.model_json_schema()
        organization_schema = Organization.model_json_schema()
        address_schema = Address.model_json_schema()
        jurisdiction_schema = Jurisdiction.model_json_schema()
        contact_point_schema = ContactPoint.model_json_schema()
        person_portrait_schema = PersonPortrait.model_json_schema()

        person_fields = {
            "id",
            "canonical_name",
            "name_variants",
            "first_name",
            "middle_name",
            "last_name",
            "suffix",
            "occupation",
            "education",
            "bio_text",
            "bio_source_url",
            "bio_license",
            "bio_pulled_at",
            "date_of_birth",
            "year_of_birth",
            "identifiers",
            "primary_address_id",
            "er_cluster_id",
            "er_confidence",
            "created_at",
            "updated_at",
        }
        person_portrait_fields = {
            "id",
            "person_id",
            "source_record_id",
            "status",
            "rights_status",
            "image_hash",
            "dedup_key",
            "mime_type",
            "width_px",
            "height_px",
            "source_image_url",
            "storage_uri",
            "created_at",
            "updated_at",
        }
        organization_fields = {
            "id",
            "canonical_name",
            "name_variants",
            "org_type",
            "identifiers",
            "registered_state",
            "formation_date",
            "dissolution_date",
            "primary_address_id",
            "er_cluster_id",
            "er_confidence",
            "created_at",
            "updated_at",
        }
        address_fields = {
            "id",
            "raw_address",
            "normalized_address",
            "street_number",
            "street_name",
            "unit",
            "city",
            "state",
            "zip5",
            "zip4",
            "county_fips",
            "geometry",
            "geocode_confidence",
            "geocode_source",
            "geocoded_at",
            "created_at",
            "updated_at",
        }
        jurisdiction_fields = {
            "id",
            "name",
            "jurisdiction_type",
            "fips",
            "parent_id",
            "state",
            "geometry",
            "population",
            "created_at",
            "updated_at",
        }
        contact_point_fields = {
            "id",
            "type",
            "value_raw",
            "value_normalized",
            "role",
            "owner_type",
            "owner_id",
            "source_record_id",
            "last_verified_at",
            "is_preferred",
            "valid_period",
            "created_at",
            "updated_at",
        }

        assert set(person_schema["properties"]) == person_fields
        assert set(organization_schema["properties"]) == organization_fields
        assert set(address_schema["properties"]) == address_fields
        assert set(jurisdiction_schema["properties"]) == jurisdiction_fields
        assert set(contact_point_schema["properties"]) == contact_point_fields
        assert set(person_portrait_schema["properties"]) == person_portrait_fields

    def test_person_json_schema_bio_license_enum_matches_portrait_rights_status(self) -> None:
        person_schema = Person.model_json_schema()
        bio_license_variants = person_schema["properties"]["bio_license"]["anyOf"]
        enum_values = next(variant["enum"] for variant in bio_license_variants if "enum" in variant)

        assert set(enum_values) == set(get_args(PortraitRightsStatus))


def test_person_portrait_accepts_stage3_binary_metadata_for_active_and_rejected() -> None:
    source_record_id = UUID("00000000-0000-0000-0000-000000000111")
    person_id = UUID("00000000-0000-0000-0000-000000000222")

    active_portrait = PersonPortrait(
        person_id=person_id,
        source_record_id=source_record_id,
        status="active",
        rights_status="licensed",
        image_hash="7f63cb6d067972c3f34f094bb7e776a8f7f5bf3ce6f5f8a761fd72d4e95f94c4",
        mime_type="image/jpeg",
        width_px=640,
        height_px=480,
    )
    rejected_portrait = PersonPortrait(
        person_id=person_id,
        source_record_id=source_record_id,
        status="rejected",
        rights_status="restricted",
        image_hash="5e538104ec4d5e8806cb6920e2c69ba70440e9504dcd0e8f2ab0d4e5b95d5f3d",
        mime_type="image/png",
        width_px=40,
        height_px=40,
    )

    assert active_portrait.status == "active"
    assert active_portrait.rights_status == "licensed"
    assert active_portrait.mime_type == "image/jpeg"
    assert active_portrait.width_px == 640
    assert active_portrait.height_px == 480

    assert rejected_portrait.status == "rejected"
    assert rejected_portrait.rights_status == "restricted"
    assert rejected_portrait.mime_type == "image/png"
    assert rejected_portrait.width_px == 40
    assert rejected_portrait.height_px == 40
