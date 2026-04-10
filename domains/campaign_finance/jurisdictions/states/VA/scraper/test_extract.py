"""Tests for Virginia entity extraction.

Tests individual vs. org detection using the VA IsIndividual field,
address extraction, and committee metadata extraction from parsed rows.
"""

from __future__ import annotations

from domains.campaign_finance.jurisdictions.states.VA.scraper.extract import (
    extract_va_contribution,
    extract_va_expenditure,
)


# --- Contribution extraction tests ---


def test_extract_contribution_maps_individual_donor_to_person() -> None:
    """When IsIndividual is 'True', should produce a Person with name parts."""
    extracted = extract_va_contribution(
        {
            "ReportId": "297173",
            "CommitteeContactId": "897310",
            "FirstName": "LaVonne",
            "MiddleName": "",
            "LastOrCompanyName": "Benton",
            "Prefix": "Mr.",
            "Suffix": "",
            "NameOfEmployer": "Retired",
            "OccupationOrTypeOfBusiness": "Retired",
            "PrimaryCityAndStateOfEmploymentOrBusiness": "Retired",
            "AddressLine1": "5 Muir Ct",
            "AddressLine2": "",
            "City": "Hampton",
            "StateCode": "VA",
            "ZipCode": "23666",
            "IsIndividual": "True",
            "TransactionDate": "08/24/2022",
            "Amount": "200.00",
            "TotalToDate": "1200.00",
            "ScheduleAId": "9379108",
            "ScheduleId": "",
            "ReportUID": "{75F88EFA-7ECB-BCDE-8FD5-11972ACA3162}",
        }
    )

    # Individual should produce a person, not an org
    assert extracted["donor_person"] is not None
    assert extracted["donor_org"] is None
    assert extracted["donor_person"].first_name == "LaVonne"
    assert extracted["donor_person"].last_name == "Benton"
    # Occupation should be captured in identifiers
    assert extracted["donor_person"].identifiers.get("occupation") == "Retired"


def test_extract_contribution_maps_org_donor_when_not_individual() -> None:
    """When IsIndividual is 'False', should produce an Organization."""
    extracted = extract_va_contribution(
        {
            "ReportId": "100000",
            "CommitteeContactId": "200000",
            "FirstName": "",
            "MiddleName": "",
            "LastOrCompanyName": "Dominion Energy PAC",
            "Prefix": "",
            "Suffix": "",
            "NameOfEmployer": "",
            "OccupationOrTypeOfBusiness": "",
            "PrimaryCityAndStateOfEmploymentOrBusiness": "",
            "AddressLine1": "701 E Cary St",
            "AddressLine2": "",
            "City": "Richmond",
            "StateCode": "VA",
            "ZipCode": "23219",
            "IsIndividual": "False",
            "TransactionDate": "01/15/2026",
            "Amount": "5000.00",
            "TotalToDate": "10000.00",
            "ScheduleAId": "9999999",
            "ScheduleId": "",
            "ReportUID": "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}",
        }
    )

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "Dominion Energy PAC"


def test_extract_contribution_builds_address() -> None:
    """Address extraction should populate city, state, and zip5."""
    extracted = extract_va_contribution(
        {
            "ReportId": "297173",
            "CommitteeContactId": "905071",
            "FirstName": "Beatrice",
            "MiddleName": "",
            "LastOrCompanyName": "Phillips",
            "Prefix": "",
            "Suffix": "",
            "NameOfEmployer": "Sentara",
            "OccupationOrTypeOfBusiness": "Instructor",
            "PrimaryCityAndStateOfEmploymentOrBusiness": "Hampton, Virginia",
            "AddressLine1": "434 Warner Hall Pl.",
            "AddressLine2": "",
            "City": "Newport News",
            "StateCode": "VA",
            "ZipCode": "23608",
            "IsIndividual": "True",
            "TransactionDate": "07/30/2022",
            "Amount": "100.00",
            "TotalToDate": "200.00",
            "ScheduleAId": "9379109",
            "ScheduleId": "",
            "ReportUID": "{75F88EFA-7ECB-BCDE-8FD5-11972ACA3162}",
        }
    )

    assert extracted["address"] is not None
    assert extracted["address"].city == "Newport News"
    assert extracted["address"].state == "VA"
    assert extracted["address"].zip5 == "23608"


def test_extract_contribution_returns_none_address_when_all_fields_empty() -> None:
    """When all address fields are empty, address should be None."""
    extracted = extract_va_contribution(
        {
            "ReportId": "100000",
            "CommitteeContactId": "200000",
            "FirstName": "Test",
            "MiddleName": "",
            "LastOrCompanyName": "Person",
            "Prefix": "",
            "Suffix": "",
            "NameOfEmployer": "",
            "OccupationOrTypeOfBusiness": "",
            "PrimaryCityAndStateOfEmploymentOrBusiness": "",
            "AddressLine1": "",
            "AddressLine2": "",
            "City": "",
            "StateCode": "",
            "ZipCode": "",
            "IsIndividual": "True",
            "TransactionDate": "01/01/2026",
            "Amount": "50.00",
            "TotalToDate": "50.00",
            "ScheduleAId": "1111111",
            "ScheduleId": "",
            "ReportUID": "{00000000-0000-0000-0000-000000000000}",
        }
    )

    assert extracted["address"] is None


def test_extract_contribution_captures_report_id() -> None:
    """The report_id field should be extracted for filing linkage."""
    extracted = extract_va_contribution(
        {
            "ReportId": "297173",
            "CommitteeContactId": "905907",
            "FirstName": "Patricia",
            "MiddleName": "",
            "LastOrCompanyName": "Burnham",
            "Prefix": "",
            "Suffix": "",
            "NameOfEmployer": "Retired",
            "OccupationOrTypeOfBusiness": "Retired",
            "PrimaryCityAndStateOfEmploymentOrBusiness": "Retired",
            "AddressLine1": "11430 Jefferson Ave",
            "AddressLine2": "124",
            "City": "Newport News",
            "StateCode": "VA",
            "ZipCode": "23601",
            "IsIndividual": "True",
            "TransactionDate": "08/01/2022",
            "Amount": "100.00",
            "TotalToDate": "200.00",
            "ScheduleAId": "9379112",
            "ScheduleId": "",
            "ReportUID": "{75F88EFA-7ECB-BCDE-8FD5-11972ACA3162}",
        }
    )

    assert extracted["report_id"] == "297173"


# --- Expenditure extraction tests ---


def test_extract_expenditure_maps_individual_payee_to_person() -> None:
    """When IsIndividual is 'True' for an expenditure, produce a Person."""
    extracted = extract_va_expenditure(
        {
            "ScheduleDId": "3991396",
            "ReportId": "297173",
            "CommitteeContactId": "904705",
            "FirstName": "Jennifer",
            "MiddleName": "",
            "LastOrCompanyName": "Brooks",
            "Prefix": "",
            "Suffix": "",
            "AddressLine1": "2244 Executive Dr",
            "AddressLine2": "",
            "City": "Hampton",
            "StateCode": "VA",
            "ZipCode": "23666",
            "IsIndividual": "True",
            "TransactionDate": "08/02/2022",
            "Amount": "250.00",
            "AuthorizingName": "Willard Maxwell",
            "ItemOrService": "Campaign Consulting",
            "ScheduleId": "",
            "ReportUID": "{75F88EFA-7ECB-BCDE-8FD5-11972ACA3162}",
        }
    )

    assert extracted["payee_person"] is not None
    assert extracted["payee_org"] is None
    assert extracted["payee_person"].first_name == "Jennifer"
    assert extracted["payee_person"].last_name == "Brooks"


def test_extract_expenditure_maps_org_payee_when_not_individual() -> None:
    """When IsIndividual is 'False' for an expenditure, produce an Organization."""
    extracted = extract_va_expenditure(
        {
            "ScheduleDId": "3991398",
            "ReportId": "297173",
            "CommitteeContactId": "905120",
            "FirstName": "",
            "MiddleName": "",
            "LastOrCompanyName": "Cardwell Printing",
            "Prefix": "",
            "Suffix": "",
            "AddressLine1": "15470 Warwick Blvd",
            "AddressLine2": "",
            "City": "Newport News",
            "StateCode": "VA",
            "ZipCode": "23608",
            "IsIndividual": "False",
            "TransactionDate": "07/09/2022",
            "Amount": "465.42",
            "AuthorizingName": "Willard Maxwell Jr.",
            "ItemOrService": "Palm Cards",
            "ScheduleId": "",
            "ReportUID": "{75F88EFA-7ECB-BCDE-8FD5-11972ACA3162}",
        }
    )

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "Cardwell Printing"


def test_extract_expenditure_captures_item_or_service() -> None:
    """The item_or_service field should be extracted for transaction description."""
    extracted = extract_va_expenditure(
        {
            "ScheduleDId": "3991400",
            "ReportId": "297173",
            "CommitteeContactId": "905120",
            "FirstName": "",
            "MiddleName": "",
            "LastOrCompanyName": "Cardwell Printing",
            "Prefix": "",
            "Suffix": "",
            "AddressLine1": "15470 Warwick Blvd",
            "AddressLine2": "",
            "City": "Newport News",
            "StateCode": "VA",
            "ZipCode": "23608",
            "IsIndividual": "False",
            "TransactionDate": "08/04/2022",
            "Amount": "457.00",
            "AuthorizingName": "Willard Maxwell",
            "ItemOrService": "Palm Cards/Door Hangers",
            "ScheduleId": "",
            "ReportUID": "{75F88EFA-7ECB-BCDE-8FD5-11972ACA3162}",
        }
    )

    assert extracted["item_or_service"] == "Palm Cards/Door Hangers"
    assert extracted["report_id"] == "297173"
