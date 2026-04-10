from __future__ import annotations

from domains.campaign_finance.jurisdictions.states.IL.scraper.extract import (
    extract_il_contribution,
    extract_il_expenditure,
)


def test_extract_il_contribution_builds_person_and_committee_placeholder() -> None:
    row = {
        "CommitteeID": "10353",
        "LastOnlyName": "Bacon",
        "FirstName": "Donald",
        "Occupation": "Teacher",
        "Employer": "District 99",
        "Address1": "16 Bruarckuff",
        "Address2": None,
        "City": "Bourbonnais",
        "State": "IL",
        "Zip": "60914      ",
    }

    extracted = extract_il_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].canonical_name == "Donald Bacon"
    assert extracted["donor_org"] is None
    assert extracted["committee"].identifiers["il_committee_id"] == "10353"
    assert extracted["address"] is not None
    assert extracted["address"].zip5 == "60914"


def test_extract_il_contribution_builds_organization_when_first_name_missing() -> None:
    row = {
        "CommitteeID": "10353",
        "LastOnlyName": "Cable Television & Commission Pac",
        "FirstName": None,
        "Occupation": None,
        "Employer": None,
        "Address1": "2400 E Devon Ave Ste 317",
        "Address2": None,
        "City": "Des Plaines",
        "State": "IL",
        "Zip": "60018      ",
    }

    extracted = extract_il_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Cable Television & Commission Pac"


def test_extract_il_expenditure_builds_payee_org_for_business_row() -> None:
    row = {
        "CommitteeID": "12478",
        "LastOnlyName": "Regular Cicero Democratic Organization",
        "FirstName": None,
        "Address1": "5838 W. Cermak Rd.",
        "Address2": None,
        "City": "Cicero",
        "State": "IL",
        "Zip": "60804      ",
    }

    extracted = extract_il_expenditure(row)

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "Regular Cicero Democratic Organization"
    assert extracted["committee"].identifiers["il_committee_id"] == "12478"
