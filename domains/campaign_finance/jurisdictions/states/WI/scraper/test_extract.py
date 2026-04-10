from __future__ import annotations

from domains.campaign_finance.jurisdictions.states.WI.scraper.extract import extract_wi_transaction


def test_extract_wi_transaction_maps_individual_contributor_to_person() -> None:
    extracted = extract_wi_transaction(
        {
            "Contributor Name (-> Related Payer Name if applicable)": "Jane A. Donor",
            "Contributor Entity Type": "Individual",
            "Contributor Occupation": "Teacher",
            "Contributor Address 1": "123 Main St",
            "Contributor City": "Madison",
            "Contributor State": "WI",
            "Contributor Zip": "53703",
            "Registrant ID": "0100001",
            "Registrant Name": "Friends of Good Government",
            "Registrant Type": "State Candidate",
        }
    )

    assert extracted["contributor_person"] is not None
    assert extracted["contributor_org"] is None
    assert extracted["committee"].identifiers["wi_registrant_id"] == "0100001"
    assert extracted["address"] is not None


def test_extract_wi_transaction_maps_non_individual_contributor_to_organization() -> None:
    extracted = extract_wi_transaction(
        {
            "Contributor Name (-> Related Payer Name if applicable)": "Wisconsin Builders PAC",
            "Contributor Entity Type": "Registrant",
            "Contributor Occupation": "",
            "Contributor Address 1": "100 Capitol Sq",
            "Contributor City": "Madison",
            "Contributor State": "WI",
            "Contributor Zip": "53703",
            "Registrant ID": "0100002",
            "Registrant Name": "Committee for Growth",
            "Registrant Type": "Political Action Committee",
        }
    )

    assert extracted["contributor_person"] is None
    assert extracted["contributor_org"] is not None
    assert extracted["contributor_org"].canonical_name == "Wisconsin Builders PAC"


def test_extract_wi_transaction_normalizes_full_state_name_to_two_letter_code() -> None:
    extracted = extract_wi_transaction(
        {
            "Contributor Name (-> Related Payer Name if applicable)": "Jane A. Donor",
            "Contributor Entity Type": "Individual",
            "Contributor Occupation": "Teacher",
            "Contributor Address 1": "123 Main St",
            "Contributor City": "Madison",
            "Contributor State": "Wisconsin",
            "Contributor Zip": "53703",
            "Registrant ID": "0100001",
            "Registrant Name": "Friends of Good Government",
            "Registrant Type": "State Candidate",
        }
    )

    assert extracted["address"] is not None
    assert extracted["address"].state == "WI"
