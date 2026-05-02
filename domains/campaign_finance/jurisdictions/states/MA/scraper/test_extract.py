"""Tests for MA entity extraction."""

from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions.states.MA.scraper.extract import (
    extract_ma_contribution,
    extract_ma_expenditure,
)
from domains.campaign_finance.jurisdictions.states.MA.scraper.parse import (
    parse_contributions,
    parse_expenditures,
)

_FIXTURES_DIR = Path(__file__).parent / "test_fixtures"


class TestMAContributionExtraction:
    """Test entity extraction from contribution rows."""

    def test_individual_contribution_extracts_person(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_report_items.txt")
        row = next(iter(parser))
        extracted = extract_ma_contribution(row)

        # First row: First_Name="John", Name="Smith" -> individual.
        assert extracted["donor_person"] is not None
        assert extracted["donor_person"].first_name == "John"
        assert extracted["donor_person"].last_name == "Smith"
        assert extracted["donor_org"] is None

    def test_corporate_contribution_extracts_organization(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_report_items.txt")
        rows = list(parser)
        # Second row: First_Name is empty, Name="ACME Corp" -> organization.
        extracted = extract_ma_contribution(rows[1])

        assert extracted["donor_org"] is not None
        assert "ACME Corp" in extracted["donor_org"].canonical_name
        assert extracted["donor_person"] is None

    def test_committee_uses_cpf_id(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_report_items.txt")
        row = next(iter(parser))
        extracted = extract_ma_contribution(row)

        assert extracted["committee"] is not None
        assert "10001" in extracted["committee"].identifiers.get("ma_cpf_id", "")

    def test_address_extracted_when_present(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_report_items.txt")
        row = next(iter(parser))
        extracted = extract_ma_contribution(row)

        assert extracted["address"] is not None
        assert extracted["address"].city == "Boston"
        assert extracted["address"].state == "MA"
        assert extracted["address"].zip5 == "02101"


class TestMAExpenditureExtraction:
    """Test entity extraction from expenditure rows."""

    def test_org_payee_extracts_organization(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_report_items.txt")
        row = next(iter(parser))
        extracted = extract_ma_expenditure(row)

        # First expenditure: Name="Print Shop Inc", no First_Name.
        assert extracted["payee_org"] is not None
        assert "Print Shop" in extracted["payee_org"].canonical_name
        assert extracted["payee_person"] is None

    def test_individual_payee_extracts_person(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_report_items.txt")
        rows = list(parser)
        # Second row: First_Name="Alice", Name="Brown".
        extracted = extract_ma_expenditure(rows[1])

        assert extracted["payee_person"] is not None
        assert extracted["payee_person"].first_name == "Alice"
        assert extracted["payee_person"].last_name == "Brown"


class TestMAFIPSStateCodeHandling:
    """OCPF data sometimes has FIPS numeric state codes instead of abbreviations."""

    def test_fips_state_code_yields_none_address_state(self) -> None:
        """Rows with numeric state (e.g. '25' for MA) should not crash extraction."""
        row = {
            "Item_ID": "999",
            "Report_ID": "100",
            "Record_Type_ID": "201",
            "Date": "01/15/2025",
            "Amount": "100.00",
            "Name": "Smith",
            "First_Name": "Jane",
            "Street_Address": "123 Main St",
            "City": "Boston",
            "State": "25",
            "Zip": "02101",
            "Description": None,
            "Related_CPF_ID": "10001",
            "Occupation": None,
            "Employer": None,
            "Principal_Officer": None,
            "Tender_Type_ID": None,
            "Clarified_Name": None,
            "Clarified_Purpose": None,
            "Is_Supported": None,
            "Is_Previous_Year_Receipt": None,
        }
        extracted = extract_ma_contribution(row)
        assert extracted["address"] is not None
        assert extracted["address"].state is None
        assert extracted["address"].city == "Boston"

    def test_single_char_state_code_yields_none(self) -> None:
        """Single-char state like 'M' (truncated) should not crash extraction."""
        row = {
            "Item_ID": "998",
            "Report_ID": "100",
            "Record_Type_ID": "201",
            "Date": "01/15/2025",
            "Amount": "50.00",
            "Name": "Doe",
            "First_Name": "John",
            "Street_Address": "456 Elm St",
            "City": "Cambridge",
            "State": "M",
            "Zip": "02139",
            "Description": None,
            "Related_CPF_ID": "10002",
            "Occupation": None,
            "Employer": None,
            "Principal_Officer": None,
            "Tender_Type_ID": None,
            "Clarified_Name": None,
            "Clarified_Purpose": None,
            "Is_Supported": None,
            "Is_Previous_Year_Receipt": None,
        }
        extracted = extract_ma_contribution(row)
        assert extracted["address"] is not None
        assert extracted["address"].state is None
        assert extracted["address"].city == "Cambridge"
