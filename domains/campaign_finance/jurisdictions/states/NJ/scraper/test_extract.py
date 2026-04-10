from __future__ import annotations

from domains.campaign_finance.jurisdictions.states.NJ.scraper.extract import extract_nj_contribution


def test_extract_nj_contribution_maps_individual_to_person() -> None:
    extracted = extract_nj_contribution(
        {
            "IsIndividual": "True",
            "FirstName": "Jane",
            "MI": "A",
            "LastName": "Donor",
            "Suffix": "",
            "NonIndName": "",
            "Street": "123 Main St",
            "City": "Trenton",
            "State": "NJ",
            "ZIP": "08608",
            "EmpName": "State University",
            "OccupationName": "Professor",
            "ContributorType": "Individual",
            "EntityName": "Friends of Good Government",
        }
    )

    assert extracted["contributor_person"] is not None
    assert extracted["contributor_person"].first_name == "Jane"
    assert extracted["contributor_person"].last_name == "Donor"
    assert extracted["contributor_org"] is None
    assert extracted["committee"].canonical_name == "Friends of Good Government"
    assert extracted["address"] is not None
    assert extracted["address"].city == "Trenton"


def test_extract_nj_contribution_maps_non_individual_to_organization() -> None:
    extracted = extract_nj_contribution(
        {
            "IsIndividual": "False",
            "FirstName": "",
            "MI": "",
            "LastName": "",
            "Suffix": "",
            "NonIndName": "NJ Builders PAC",
            "Street": "100 Capitol Ave",
            "City": "Trenton",
            "State": "NJ",
            "ZIP": "08608",
            "EmpName": "",
            "OccupationName": "",
            "ContributorType": "PAC",
            "EntityName": "Committee for Growth",
        }
    )

    assert extracted["contributor_person"] is None
    assert extracted["contributor_org"] is not None
    assert extracted["contributor_org"].canonical_name == "NJ Builders PAC"
    assert extracted["committee"].canonical_name == "Committee for Growth"


def test_extract_nj_contribution_handles_missing_address_fields() -> None:
    extracted = extract_nj_contribution(
        {
            "IsIndividual": "True",
            "FirstName": "John",
            "MI": "",
            "LastName": "Smith",
            "Suffix": "",
            "NonIndName": "",
            "Street": "",
            "City": "",
            "State": "",
            "ZIP": "",
            "EmpName": "",
            "OccupationName": "",
            "ContributorType": "Individual",
            "EntityName": "Test Committee",
        }
    )

    assert extracted["contributor_person"] is not None
    assert extracted["address"] is None
