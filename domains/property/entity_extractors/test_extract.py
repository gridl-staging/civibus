"""Tests for property entity extraction from Durham ArcGIS parcel records."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from uuid import uuid4

from core.types.python.extraction import EntityExtraction
from core.types.python.models import Address, Organization, Person

from domains.property.entity_extractors.extract import (
    extract_entities,
    extract_owner,
)


# ---------------------------------------------------------------------------
# Sprint 1 contract tests (preserved)
# ---------------------------------------------------------------------------


def test_property_extractors_depend_on_shared_entity_extraction_contract() -> None:
    assert EntityExtraction.__module__ == "core.types.python.extraction"

    extractor_directory = Path(__file__).resolve().parent
    extractor_files = sorted(
        file_path
        for file_path in extractor_directory.glob("*.py")
        if file_path.name not in {"__init__.py", Path(__file__).name}
    )

    for extractor_file in extractor_files:
        extractor_source = extractor_file.read_text(encoding="utf-8")
        assert "class EntityExtraction(" not in extractor_source, (
            f"{extractor_file.name} must import core.types.python.extraction.EntityExtraction"
        )


# ---------------------------------------------------------------------------
# Test data builders
# ---------------------------------------------------------------------------

_BASE_DURHAM_RECORD: dict[str, object] = {
    "REID": "100001",
    "PIN": "0822537639",
    "LOCATION_ADDR": "922 LANCASTER ST",
    "PROPERTY_OWNER": "SMITH JOHN",
    "OWNER_MAIL_1": "922 LANCASTER ST",
    "OWNER_MAIL_2": "",
    "OWNER_MAIL_3": "",
    "OWNER_MAIL_CITY": "DURHAM",
    "OWNER_MAIL_STATE": "NC",
    "OWNER_MAIL_ZIP": "27701",
}


def _build_record(**overrides: object) -> dict[str, object]:
    record = dict(_BASE_DURHAM_RECORD)
    record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# Extract owner (core model objects)
# ---------------------------------------------------------------------------


class TestExtractOwnerPerson:
    """Single individual owner returns Person + Address."""

    def test_returns_person_for_individual(self) -> None:
        result = extract_owner(_build_record())
        assert result["person"] is not None
        assert isinstance(result["person"], Person)

    def test_person_canonical_name_is_title_cased(self) -> None:
        result = extract_owner(_build_record())
        person = result["person"]
        assert person is not None
        assert person.canonical_name == "Smith John"

    def test_person_identifiers_include_owner_name_as_filed(self) -> None:
        result = extract_owner(_build_record())
        person = result["person"]
        assert person is not None
        assert person.identifiers == {"owner_name_as_filed": "SMITH JOHN"}

    def test_organization_is_none_for_individual(self) -> None:
        result = extract_owner(_build_record())
        assert result["organization"] is None


class TestExtractOwnerOrganization:
    """Organization owner returns Organization, no Person."""

    def test_returns_organization_for_corp(self) -> None:
        result = extract_owner(_build_record(PROPERTY_OWNER="SCANLON REALTY CORP"))
        assert result["organization"] is not None
        assert isinstance(result["organization"], Organization)

    def test_organization_canonical_name(self) -> None:
        result = extract_owner(_build_record(PROPERTY_OWNER="DUKE UNIVERSITY"))
        org = result["organization"]
        assert org is not None
        assert org.canonical_name == "Duke University"

    def test_organization_identifiers_has_owner_name_as_filed(self) -> None:
        result = extract_owner(_build_record(PROPERTY_OWNER="DUKE UNIVERSITY"))
        org = result["organization"]
        assert org is not None
        assert org.identifiers == {"owner_name_as_filed": "DUKE UNIVERSITY"}

    def test_person_is_none_for_organization(self) -> None:
        result = extract_owner(_build_record(PROPERTY_OWNER="SCANLON REALTY CORP"))
        assert result["person"] is None

    def test_returns_organization_for_corp_with_period(self) -> None:
        result = extract_owner(_build_record(PROPERTY_OWNER="SCANLON REALTY CORP."))
        assert result["organization"] is not None
        assert result["person"] is None


class TestExtractOwnerJoint:
    """Joint owners produce multiple Person results."""

    def test_joint_ampersand_returns_two_persons(self) -> None:
        result = extract_owner(_build_record(PROPERTY_OWNER="SMITH JOHN & SMITH JANE"))
        persons = result["persons"]
        assert len(persons) == 2

    def test_joint_owner_names_are_title_cased(self) -> None:
        result = extract_owner(_build_record(PROPERTY_OWNER="DOE JOHN & DOE JANE"))
        names = [p.canonical_name for p in result["persons"]]
        assert names == ["Doe John", "Doe Jane"]

    def test_single_person_also_in_persons_list(self) -> None:
        result = extract_owner(_build_record())
        assert len(result["persons"]) == 1
        assert result["persons"][0].canonical_name == "Smith John"


class TestExtractOwnerAddress:
    """Mailing address extraction from OWNER_MAIL_* fields."""

    def test_returns_address_with_full_mailing(self) -> None:
        result = extract_owner(_build_record())
        assert result["address"] is not None
        assert isinstance(result["address"], Address)

    def test_address_fields_populated(self) -> None:
        result = extract_owner(_build_record())
        addr = result["address"]
        assert addr is not None
        assert addr.city == "Durham"
        assert addr.state == "NC"
        assert addr.zip5 == "27701"

    def test_address_geometry_is_none(self) -> None:
        result = extract_owner(_build_record())
        addr = result["address"]
        assert addr is not None
        assert addr.geometry is None

    def test_address_none_when_all_mail_fields_blank(self) -> None:
        result = extract_owner(
            _build_record(
                OWNER_MAIL_1="",
                OWNER_MAIL_2="",
                OWNER_MAIL_3="",
                OWNER_MAIL_CITY="",
                OWNER_MAIL_STATE="",
                OWNER_MAIL_ZIP="",
            )
        )
        assert result["address"] is None


# ---------------------------------------------------------------------------
# Plugin contract: extract_entities()
# ---------------------------------------------------------------------------


class TestExtractEntities:
    """Contract-compatible extract_entities() for property records."""

    def test_individual_returns_person_entity(self) -> None:
        entities = extract_entities(_build_record())
        person_entities = [e for e in entities if e["entity_type"] == "person"]
        assert len(person_entities) == 1
        assert person_entities[0]["name"] == "Smith John"

    def test_organization_returns_org_entity(self) -> None:
        entities = extract_entities(_build_record(PROPERTY_OWNER="DUKE UNIVERSITY"))
        org_entities = [e for e in entities if e["entity_type"] == "organization"]
        assert len(org_entities) == 1
        assert org_entities[0]["name"] == "Duke University"

    def test_joint_owners_return_multiple_person_entities(self) -> None:
        entities = extract_entities(_build_record(PROPERTY_OWNER="DOE JOHN & DOE JANE"))
        person_entities = [e for e in entities if e["entity_type"] == "person"]
        assert len(person_entities) == 2

    def test_person_entities_include_owner_name_as_filed_identifier(self) -> None:
        entities = extract_entities(_build_record(PROPERTY_OWNER="DOE JOHN & DOE JANE"))
        person_entities = [e for e in entities if e["entity_type"] == "person"]

        assert [entity["identifiers"] for entity in person_entities] == [
            {"owner_name_as_filed": "DOE JOHN"},
            {"owner_name_as_filed": "DOE JANE"},
        ]

    def test_entity_address_populated(self) -> None:
        entities = extract_entities(_build_record())
        for entity in entities:
            assert entity["address"] is not None
            assert "Durham" in entity["address"]

    def test_entity_address_none_when_no_mailing(self) -> None:
        entities = extract_entities(
            _build_record(
                OWNER_MAIL_1="",
                OWNER_MAIL_2="",
                OWNER_MAIL_3="",
                OWNER_MAIL_CITY="",
                OWNER_MAIL_STATE="",
                OWNER_MAIL_ZIP="",
            )
        )
        for entity in entities:
            assert entity["address"] is None

    def test_identifiers_do_not_contain_reid_or_pin(self) -> None:
        entities = extract_entities(_build_record())
        for entity in entities:
            assert "reid" not in entity["identifiers"]
            assert "REID" not in entity["identifiers"]
            assert "pin" not in entity["identifiers"]
            assert "PIN" not in entity["identifiers"]


# ---------------------------------------------------------------------------
# Provenance regressions
# ---------------------------------------------------------------------------


class TestProvenanceRegressions:
    """Stage 4 boundary: provenance, geometry, no ingest coupling."""

    def test_source_record_id_preserved(self) -> None:
        sid = uuid4()
        entities = extract_entities(_build_record(source_record_id=str(sid)))
        for entity in entities:
            assert entity["source_record_id"] == sid

    def test_source_record_id_none_when_absent(self) -> None:
        entities = extract_entities(_build_record())
        for entity in entities:
            assert entity["source_record_id"] is None

    def test_address_geometry_stays_none(self) -> None:
        result = extract_owner(_build_record())
        if result["address"] is not None:
            assert result["address"].geometry is None

    def test_extractor_does_not_import_core_db(self) -> None:
        extract_module = inspect.getmodule(extract_entities)
        assert extract_module is not None
        source_path = Path(inspect.getfile(extract_module))
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_name = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module
                elif isinstance(node, ast.Import):
                    module_name = ", ".join(alias.name for alias in node.names)
                assert "core.db" not in module_name, (
                    "Stage 4 extractor must not import core.db (reserved for Stage 5 ingest)"
                )

    def test_extractor_does_not_import_ingest(self) -> None:
        extract_module = inspect.getmodule(extract_entities)
        assert extract_module is not None
        source_path = Path(inspect.getfile(extract_module))
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_name = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module
                elif isinstance(node, ast.Import):
                    module_name = ", ".join(alias.name for alias in node.names)
                assert "ingest" not in module_name, "Stage 4 extractor must not import ingest modules"
