from __future__ import annotations

import pytest

from core.types.python.models import Address, Organization, Person
from domains.campaign_finance.jurisdictions.states.CA.scraper import (
    _load_column_for_semantic_path,
)
from domains.campaign_finance.jurisdictions.states.CA.scraper import extract as ca_extract_module
from domains.campaign_finance.jurisdictions.states.CA.scraper.extract import (
    build_ca_data_source,
    extract_address,
    extract_ca_contribution,
    extract_ca_expenditure,
    extract_ca_loan,
    extract_committee_from_cvr,
    extract_counterparty_org,
    extract_counterparty_person,
)


def _rcpt_row(**overrides: str | None) -> dict[str, str | None]:
    """Build a minimal RCPT_CD row with sensible defaults."""
    base: dict[str, str | None] = {
        "FILING_ID": "12345",
        "AMEND_ID": "0",
        "TRAN_ID": "T001",
        "ENTITY_CD": "IND",
        "CTRIB_NAML": "Doe",
        "CTRIB_NAMF": "Jane",
        "CTRIB_NAMT": None,
        "CTRIB_NAMS": None,
        "CTRIB_CITY": "Sacramento",
        "CTRIB_ST": "CA",
        "CTRIB_ZIP4": "95814",
        "CTRIB_EMP": "Acme Corp",
        "CTRIB_OCC": "Engineer",
        "RCPT_DATE": "2025-01-15",
        "AMOUNT": "500.00",
        "FORM_TYPE": "A",
        "TRAN_TYPE": "X",
    }
    base.update(overrides)
    return base


def _expn_row(**overrides: str | None) -> dict[str, str | None]:
    """Build a minimal EXPN_CD row with sensible defaults."""
    base: dict[str, str | None] = {
        "FILING_ID": "12346",
        "AMEND_ID": "0",
        "TRAN_ID": "T002",
        "ENTITY_CD": "IND",
        "PAYEE_NAML": "Smith",
        "PAYEE_NAMF": "John",
        "PAYEE_NAMT": None,
        "PAYEE_NAMS": None,
        "PAYEE_CITY": "Los Angeles",
        "PAYEE_ST": "CA",
        "PAYEE_ZIP4": "90001",
        "EXPN_DATE": "2025-02-01",
        "AMOUNT": "250.00",
        "FORM_TYPE": "E",
        "EXPN_CODE": "CMP",
        "EXPN_DSCR": "Campaign materials",
    }
    base.update(overrides)
    return base


def _loan_row(**overrides: str | None) -> dict[str, str | None]:
    """Build a minimal LOAN_CD row with sensible defaults."""
    base: dict[str, str | None] = {
        "FILING_ID": "12347",
        "AMEND_ID": "0",
        "TRAN_ID": "T003",
        "ENTITY_CD": "IND",
        "LNDR_NAML": "Wells",
        "LNDR_NAMF": "Mary",
        "LNDR_NAMT": None,
        "LNDR_NAMS": None,
        "LNDR_CITY": "San Francisco",
        "LNDR_ST": "CA",
        "LNDR_ZIP4": "94102",
        "LOAN_DATE1": "2025-03-01",
        "LOAN_AMT1": "10000.00",
        "LOAN_RATE": "5.0",
        "FORM_TYPE": "B1",
        "LOAN_TYPE": None,
    }
    base.update(overrides)
    return base


def _cvr_row(**overrides: str | None) -> dict[str, str | None]:
    """Build a minimal CVR_CAMPAIGN_DISCLOSURE_CD row."""
    base: dict[str, str | None] = {
        "FILER_ID": "1234567",
        "FILING_ID": "12345",
        "AMEND_ID": "0",
        "RPT_DATE": "2025-01-31",
        "FILER_NAML": "Friends of Example",
        "FILER_NAMF": None,
        "FILER_NAMT": None,
        "FILER_NAMS": None,
        "ENTITY_CD": "COM",
        "OFFICE_CD": "GOV",
        "OFFIC_DSCR": None,
        "JURIS_CD": "STW",
        "JURIS_DSCR": None,
        "FORM_TYPE": "F460",
        "STMT_TYPE": "10001",
    }
    base.update(overrides)
    return base


# --- Person extraction ---


class TestPersonExtraction:
    def test_extract_individual_donor_from_rcpt(self):
        person = extract_counterparty_person(_rcpt_row(), table="RCPT_CD")
        assert person is not None
        assert person.canonical_name == "Jane Doe"
        assert person.first_name == "Jane"
        assert person.last_name == "Doe"
        assert person.identifiers["employer"] == "Acme Corp"
        assert person.identifiers["occupation"] == "Engineer"

    def test_extract_person_returns_none_for_committee_entity(self):
        person = extract_counterparty_person(_rcpt_row(ENTITY_CD="COM"), table="RCPT_CD")
        assert person is None

    def test_extract_person_returns_none_for_other_entity(self):
        person = extract_counterparty_person(_rcpt_row(ENTITY_CD="OTH"), table="RCPT_CD")
        assert person is None

    def test_extract_person_with_title_and_suffix(self):
        person = extract_counterparty_person(
            _rcpt_row(CTRIB_NAMT="Dr", CTRIB_NAMS="Jr"),
            table="RCPT_CD",
        )
        assert person is not None
        assert person.suffix == "Jr"

    def test_extract_person_normalizes_whitespace(self):
        person = extract_counterparty_person(
            _rcpt_row(CTRIB_NAML="  Doe  ", CTRIB_NAMF="  Jane  "),
            table="RCPT_CD",
        )
        assert person is not None
        assert person.first_name == "Jane"
        assert person.last_name == "Doe"

    def test_extract_person_strips_blank_identifiers(self):
        person = extract_counterparty_person(
            _rcpt_row(CTRIB_EMP="  ", CTRIB_OCC=None),
            table="RCPT_CD",
        )
        assert person is not None
        assert "employer" not in person.identifiers
        assert "occupation" not in person.identifiers

    def test_extract_payee_person_from_expn(self):
        person = extract_counterparty_person(_expn_row(), table="EXPN_CD")
        assert person is not None
        assert person.canonical_name == "John Smith"
        assert person.identifiers == {}

    def test_extract_lender_person_from_loan(self):
        person = extract_counterparty_person(_loan_row(), table="LOAN_CD")
        assert person is not None
        assert person.canonical_name == "Mary Wells"


# --- Organization extraction ---


class TestOrgExtraction:
    def test_extract_org_from_committee_entity(self):
        org = extract_counterparty_org(_rcpt_row(ENTITY_CD="COM", CTRIB_NAML="Big PAC"), table="RCPT_CD")
        assert org is not None
        assert org.canonical_name == "Big Pac"

    def test_extract_org_from_other_entity(self):
        org = extract_counterparty_org(_rcpt_row(ENTITY_CD="OTH", CTRIB_NAML="Trust Fund"), table="RCPT_CD")
        assert org is not None
        assert org.canonical_name == "Trust Fund"

    def test_extract_org_returns_none_for_individual(self):
        org = extract_counterparty_org(_rcpt_row(ENTITY_CD="IND"), table="RCPT_CD")
        assert org is None

    def test_extract_payee_org_from_expn(self):
        org = extract_counterparty_org(
            _expn_row(ENTITY_CD="COM", PAYEE_NAML="Print Shop"),
            table="EXPN_CD",
        )
        assert org is not None
        assert org.canonical_name == "Print Shop"


# --- Committee extraction from CVR ---


class TestCommitteeExtraction:
    def test_extract_committee_from_cvr(self):
        committee = extract_committee_from_cvr(_cvr_row())
        assert committee.canonical_name == "Friends Of Example"
        assert committee.identifiers["ca_filer_id"] == "1234567"

    def test_extract_committee_missing_filer_id(self):
        committee = extract_committee_from_cvr(_cvr_row(FILER_ID=None))
        assert committee.canonical_name == "Friends Of Example"
        assert committee.identifiers == {}


# --- Address extraction ---


class TestAddressExtraction:
    def test_extract_address_from_rcpt(self):
        address = extract_address(_rcpt_row(), table="RCPT_CD")
        assert address is not None
        assert address.city == "SACRAMENTO"
        assert address.state == "CA"
        assert address.zip5 == "95814"

    def test_extract_address_from_expn(self):
        address = extract_address(_expn_row(), table="EXPN_CD")
        assert address is not None
        assert address.city == "LOS ANGELES"
        assert address.state == "CA"

    def test_extract_address_from_loan(self):
        address = extract_address(_loan_row(), table="LOAN_CD")
        assert address is not None
        assert address.city == "SAN FRANCISCO"

    def test_extract_address_returns_none_when_no_city_or_state(self):
        address = extract_address(
            _rcpt_row(CTRIB_CITY=None, CTRIB_ST=None),
            table="RCPT_CD",
        )
        assert address is None

    def test_extract_address_splits_zip_plus_4(self):
        address = extract_address(
            _rcpt_row(CTRIB_ZIP4="95814-1234"),
            table="RCPT_CD",
        )
        assert address is not None
        assert address.zip5 == "95814"
        assert address.zip4 == "1234"

    def test_extract_address_splits_unhyphenated_9digit_zip(self):
        """Live CA data contains 9-digit ZIP+4 without hyphens (e.g., 926562601)."""
        address = extract_address(
            _rcpt_row(CTRIB_ZIP4="926562601"),
            table="RCPT_CD",
        )
        assert address is not None
        assert address.zip5 == "92656"
        assert address.zip4 == "2601"

    def test_extract_address_rejects_numeric_state_code(self):
        """Live CA data has numeric junk (e.g., '92') in state fields."""
        address = extract_address(
            _rcpt_row(CTRIB_ST="92"),
            table="RCPT_CD",
        )
        assert address is not None
        assert address.state is None


# --- Composite extraction ---


class TestCompositeExtraction:
    def test_extract_ca_contribution_individual(self):
        extraction = extract_ca_contribution(_rcpt_row())
        assert set(extraction.keys()) == {"donor_person", "donor_org", "address"}
        assert isinstance(extraction["donor_person"], Person)
        assert extraction["donor_org"] is None
        assert isinstance(extraction["address"], Address)

    def test_extract_ca_contribution_committee(self):
        extraction = extract_ca_contribution(_rcpt_row(ENTITY_CD="COM", CTRIB_NAML="Big PAC"))
        assert extraction["donor_person"] is None
        assert isinstance(extraction["donor_org"], Organization)

    def test_extract_ca_expenditure(self):
        extraction = extract_ca_expenditure(_expn_row())
        assert set(extraction.keys()) == {"payee_person", "payee_org", "address"}
        assert isinstance(extraction["payee_person"], Person)
        assert extraction["payee_org"] is None

    def test_extract_ca_loan(self):
        extraction = extract_ca_loan(_loan_row())
        assert set(extraction.keys()) == {"lender_person", "lender_org", "address"}
        assert isinstance(extraction["lender_person"], Person)
        assert extraction["lender_org"] is None


# --- Data source builder ---


class TestDataSource:
    def test_build_ca_data_source(self):
        ds = build_ca_data_source()
        assert ds.domain == "campaign_finance"
        assert ds.jurisdiction == "state/CA"
        assert ds.name == "CAL-ACCESS Raw Data Export"
        assert "sos.ca.gov" in ds.source_url


def test_extract_counterparty_fields_are_resolved_from_config_mapping(
    monkeypatch: pytest.MonkeyPatch,
):
    semantic_to_column = {
        ("RCPT_CD", "donor.entity_type"): "ENTITY_CODE_FROM_CONFIG",
        ("RCPT_CD", "donor.name.last"): "LAST_NAME_FROM_CONFIG",
        ("RCPT_CD", "donor.name.first"): "FIRST_NAME_FROM_CONFIG",
        ("RCPT_CD", "donor.name.title"): "TITLE_FROM_CONFIG",
        ("RCPT_CD", "donor.name.suffix"): "SUFFIX_FROM_CONFIG",
        ("RCPT_CD", "donor.address.city"): "CITY_FROM_CONFIG",
        ("RCPT_CD", "donor.address.state"): "STATE_FROM_CONFIG",
        ("RCPT_CD", "donor.address.zip"): "ZIP_FROM_CONFIG",
        ("RCPT_CD", "donor.employer"): "EMPLOYER_FROM_CONFIG",
        ("RCPT_CD", "donor.occupation"): "OCCUPATION_FROM_CONFIG",
    }

    def _fake_load_column_for_semantic_path(table_name: str, semantic_path: str) -> str:
        return semantic_to_column[(table_name, semantic_path)]

    monkeypatch.setattr(ca_extract_module, "_load_column_for_semantic_path", _fake_load_column_for_semantic_path)
    ca_extract_module._load_counterparty_fields.cache_clear()

    try:
        row = {
            "ENTITY_CODE_FROM_CONFIG": "IND",
            "LAST_NAME_FROM_CONFIG": "Doe",
            "FIRST_NAME_FROM_CONFIG": "Jane",
            "TITLE_FROM_CONFIG": None,
            "SUFFIX_FROM_CONFIG": None,
            "CITY_FROM_CONFIG": "Sacramento",
            "STATE_FROM_CONFIG": "ca",
            "ZIP_FROM_CONFIG": "95814",
            "EMPLOYER_FROM_CONFIG": "Acme Corp",
            "OCCUPATION_FROM_CONFIG": "Engineer",
        }

        person = extract_counterparty_person(row, table="RCPT_CD")
        address = extract_address(row, table="RCPT_CD")

        assert person is not None
        assert person.canonical_name == "Jane Doe"
        assert person.identifiers["employer"] == "Acme Corp"
        assert person.identifiers["occupation"] == "Engineer"
        assert address is not None
        assert address.city == "SACRAMENTO"
        assert address.state == "CA"
        assert address.zip5 == "95814"
    finally:
        ca_extract_module._load_counterparty_fields.cache_clear()


def test_column_for_semantic_path_raises_when_missing():
    with pytest.raises(RuntimeError, match="No CA field mapping found"):
        _load_column_for_semantic_path("RCPT_CD", "donor.address.street")
