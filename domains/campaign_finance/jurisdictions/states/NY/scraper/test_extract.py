"""Tests for NY entity extraction."""

from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions.states.NY.scraper.extract import (
    extract_ny_contribution,
    extract_ny_expenditure,
)
from domains.campaign_finance.jurisdictions.states.NY.scraper.parse import (
    parse_contributions,
    parse_expenditures,
    parse_independent_expenditures,
)

_FIXTURES_DIR = Path(__file__).parent / "test_fixtures"


class TestNYContributionExtraction:
    """Test entity extraction from contribution rows."""

    def test_individual_contribution_extracts_person(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        row = next(iter(parser))
        extracted = extract_ny_contribution(row)

        # First row has cntrbr_type_desc="Individual" with first/last name.
        assert extracted["donor_person"] is not None
        assert extracted["donor_person"].first_name == "John"
        assert extracted["donor_person"].last_name == "Doe"
        assert extracted["donor_org"] is None

    def test_corporate_contribution_extracts_organization(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        rows = list(parser)
        # Second row: cntrbr_type_desc="Corporation", flng_ent_name="ACME Corp"
        extracted = extract_ny_contribution(rows[1])

        assert extracted["donor_org"] is not None
        assert "ACME Corp" in extracted["donor_org"].canonical_name
        assert extracted["donor_person"] is None

    def test_committee_is_always_present(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        row = next(iter(parser))
        extracted = extract_ny_contribution(row)

        assert extracted["committee"] is not None
        assert "Friends of Jane Smith" in extracted["committee"].canonical_name
        assert extracted["committee"].identifiers.get("ny_filer_id") == "12345"

    def test_address_extracted_when_present(self) -> None:
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        row = next(iter(parser))
        extracted = extract_ny_contribution(row)

        assert extracted["address"] is not None
        assert extracted["address"].city == "Albany"
        assert extracted["address"].state == "NY"
        assert extracted["address"].zip5 == "12201"

    def test_empty_address_returns_none(self) -> None:
        # Construct a row with all address fields empty.
        parser = parse_contributions(_FIXTURES_DIR / "sample_contributions.csv")
        row = dict(next(iter(parser)))
        row["flng_ent_add1"] = None
        row["flng_ent_city"] = None
        row["flng_ent_state"] = None
        row["flng_ent_zip"] = None
        extracted = extract_ny_contribution(row)
        assert extracted["address"] is None


class TestNYExpenditureExtraction:
    """Test entity extraction from expenditure rows."""

    def test_org_payee_extracts_organization(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_expenditures.csv")
        row = next(iter(parser))
        extracted = extract_ny_expenditure(row)

        # First expenditure: flng_ent_name="Print Shop Inc" (no last name)
        assert extracted["payee_org"] is not None
        assert "Print Shop" in extracted["payee_org"].canonical_name
        assert extracted["payee_person"] is None

    def test_individual_payee_extracts_person(self) -> None:
        parser = parse_expenditures(_FIXTURES_DIR / "sample_expenditures.csv")
        rows = list(parser)
        # Second row: flng_ent_last_name="Brown", not org-like
        extracted = extract_ny_expenditure(rows[1])

        assert extracted["payee_person"] is not None
        assert extracted["payee_person"].last_name == "Brown"
        assert extracted["payee_org"] is None

    def test_ie_org_payee_extracts_organization(self) -> None:
        parser = parse_independent_expenditures(_FIXTURES_DIR / "sample_ie.csv")
        row = next(iter(parser))
        extracted = extract_ny_expenditure(row)

        assert extracted["payee_org"] is not None
        assert "Metro Media Group" in extracted["payee_org"].canonical_name
        assert extracted["payee_person"] is None

    def test_ie_individual_payee_extracts_person(self) -> None:
        parser = parse_independent_expenditures(_FIXTURES_DIR / "sample_ie.csv")
        rows = list(parser)
        extracted = extract_ny_expenditure(rows[1])

        assert extracted["payee_person"] is not None
        assert extracted["payee_person"].first_name == "Robert"
        assert extracted["payee_person"].last_name == "Jones"
        assert extracted["payee_org"] is None
