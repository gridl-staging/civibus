"""Tests for Durham property owner normalization."""

from __future__ import annotations

from domains.property.normalize.owners import (
    OwnerKind,
    classify_owner,
    normalize_mailing_address,
    normalize_owner_name,
    split_joint_owners,
)


# ---------------------------------------------------------------------------
# Owner-kind classification
# ---------------------------------------------------------------------------


class TestClassifyOwner:
    """Classify PROPERTY_OWNER strings as person vs organization."""

    def test_individual_simple_name(self) -> None:
        assert classify_owner("JOHN DOE") == OwnerKind.PERSON

    def test_organization_llc(self) -> None:
        assert classify_owner("SCANLON REALTY LLC") == OwnerKind.ORGANIZATION

    def test_organization_inc(self) -> None:
        assert classify_owner("ACME HOLDINGS INC") == OwnerKind.ORGANIZATION

    def test_organization_corp(self) -> None:
        assert classify_owner("SCANLON REALTY CORP") == OwnerKind.ORGANIZATION

    def test_organization_trust(self) -> None:
        assert classify_owner("SMITH FAMILY TRUST") == OwnerKind.ORGANIZATION

    def test_organization_university(self) -> None:
        assert classify_owner("DUKE UNIVERSITY") == OwnerKind.ORGANIZATION

    def test_organization_church(self) -> None:
        assert classify_owner("FIRST BAPTIST CHURCH") == OwnerKind.ORGANIZATION

    def test_organization_county(self) -> None:
        assert classify_owner("DURHAM COUNTY") == OwnerKind.ORGANIZATION

    def test_organization_city_of(self) -> None:
        assert classify_owner("CITY OF DURHAM") == OwnerKind.ORGANIZATION

    def test_organization_state_of(self) -> None:
        assert classify_owner("STATE OF NORTH CAROLINA") == OwnerKind.ORGANIZATION

    def test_organization_association(self) -> None:
        assert classify_owner("HOMEOWNERS ASSOCIATION") == OwnerKind.ORGANIZATION

    def test_organization_lp(self) -> None:
        assert classify_owner("DURHAM PARTNERS LP") == OwnerKind.ORGANIZATION

    def test_organization_ltd(self) -> None:
        assert classify_owner("BRIER CREEK LTD") == OwnerKind.ORGANIZATION

    def test_joint_owner_ampersand_still_person(self) -> None:
        assert classify_owner("JOHN & JANE DOE") == OwnerKind.PERSON

    def test_blank_returns_person(self) -> None:
        assert classify_owner("") == OwnerKind.PERSON

    def test_whitespace_only_returns_person(self) -> None:
        assert classify_owner("   ") == OwnerKind.PERSON


class TestClassifyOwnerFalsePositiveRegressions:
    """Regression tests for common misclassification traps."""

    def test_llc_in_org_stays_organization(self) -> None:
        assert classify_owner("TRIANGLE DEVELOPMENT LLC") == OwnerKind.ORGANIZATION

    def test_inc_with_trailing_period_stays_organization(self) -> None:
        assert classify_owner("RALEIGH BUILDERS INC.") == OwnerKind.ORGANIZATION

    def test_corp_with_trailing_period_stays_organization(self) -> None:
        assert classify_owner("SCANLON REALTY CORP.") == OwnerKind.ORGANIZATION

    def test_inc_in_org_stays_organization(self) -> None:
        assert classify_owner("RALEIGH BUILDERS INC") == OwnerKind.ORGANIZATION

    def test_trust_stays_organization(self) -> None:
        assert classify_owner("JONES REVOCABLE TRUST") == OwnerKind.ORGANIZATION

    def test_university_stays_organization(self) -> None:
        assert classify_owner("NORTH CAROLINA CENTRAL UNIVERSITY") == OwnerKind.ORGANIZATION

    def test_family_joint_owner_not_misclassified_as_company(self) -> None:
        assert classify_owner("SMITH JOHN & SMITH JANE") == OwnerKind.PERSON

    def test_individual_with_suffix_not_org(self) -> None:
        assert classify_owner("JOHNSON ROBERT JR") == OwnerKind.PERSON

    def test_individual_with_roman_numeral_not_org(self) -> None:
        assert classify_owner("WILLIAMS JAMES III") == OwnerKind.PERSON

    def test_heirs_is_organization(self) -> None:
        assert classify_owner("SMITH HEIRS") == OwnerKind.ORGANIZATION

    def test_estate_is_organization(self) -> None:
        assert classify_owner("JONES ESTATE") == OwnerKind.ORGANIZATION


# ---------------------------------------------------------------------------
# Joint-owner splitting
# ---------------------------------------------------------------------------


class TestSplitJointOwners:
    """Split combined owner strings into individual names."""

    def test_single_owner_unchanged(self) -> None:
        assert split_joint_owners("JOHN DOE") == ["JOHN DOE"]

    def test_ampersand_delimiter(self) -> None:
        assert split_joint_owners("JOHN DOE & JANE DOE") == ["JOHN DOE", "JANE DOE"]

    def test_and_delimiter(self) -> None:
        assert split_joint_owners("JOHN DOE AND JANE DOE") == ["JOHN DOE", "JANE DOE"]

    def test_strips_whitespace(self) -> None:
        assert split_joint_owners("  JOHN DOE  &  JANE DOE  ") == ["JOHN DOE", "JANE DOE"]

    def test_empty_string_returns_empty_list(self) -> None:
        assert split_joint_owners("") == []

    def test_organization_not_split_on_ampersand(self) -> None:
        # "S&W" should not be split — the & is mid-word
        assert split_joint_owners("S&W PROPERTIES LLC") == ["S&W PROPERTIES LLC"]

    def test_et_al_treated_as_single_owner(self) -> None:
        assert split_joint_owners("SMITH JOHN ET AL") == ["SMITH JOHN ET AL"]


# ---------------------------------------------------------------------------
# Owner-name cleanup
# ---------------------------------------------------------------------------


class TestNormalizeOwnerName:
    """Clean and title-case raw Durham PROPERTY_OWNER strings."""

    def test_title_case_simple(self) -> None:
        assert normalize_owner_name("JOHN DOE") == "John Doe"

    def test_title_case_hyphenated(self) -> None:
        assert normalize_owner_name("SMITH-JONES MARY") == "Smith-Jones Mary"

    def test_preserves_org_name_as_title_case(self) -> None:
        assert normalize_owner_name("DUKE UNIVERSITY") == "Duke University"

    def test_strips_surrounding_whitespace(self) -> None:
        assert normalize_owner_name("  JOHN DOE  ") == "John Doe"

    def test_collapses_internal_whitespace(self) -> None:
        assert normalize_owner_name("JOHN   DOE") == "John Doe"

    def test_empty_string(self) -> None:
        assert normalize_owner_name("") == ""


# ---------------------------------------------------------------------------
# Mailing-address normalization
# ---------------------------------------------------------------------------


class TestNormalizeMailingAddress:
    """Assemble structured address from Durham OWNER_MAIL_* fields."""

    def test_full_mailing_address(self) -> None:
        result = normalize_mailing_address(
            mail_1="2200 WEST MAIN ST, STE 300",
            mail_2="",
            mail_3="",
            city="DURHAM",
            state="NC",
            zip_code="27701",
        )
        assert result is not None
        assert result["raw_address"] == "2200 West Main St, Ste 300, Durham, NC 27701"
        assert result["city"] == "Durham"
        assert result["state"] == "NC"
        assert result["zip5"] == "27701"

    def test_blank_mail_2_and_3_excluded(self) -> None:
        result = normalize_mailing_address(
            mail_1="123 OAK ST",
            mail_2="",
            mail_3="",
            city="SOUTHPORT",
            state="NC",
            zip_code="28461",
        )
        assert result is not None
        assert "123 Oak St" in result["raw_address"]
        assert result["city"] == "Southport"

    def test_mail_2_included_when_present(self) -> None:
        result = normalize_mailing_address(
            mail_1="ATTN: PROPERTY MANAGER",
            mail_2="500 ELM AVENUE",
            mail_3="",
            city="RALEIGH",
            state="NC",
            zip_code="27601",
        )
        assert result is not None
        assert "Attn: Property Manager" in result["raw_address"]
        assert "500 Elm Avenue" in result["raw_address"]

    def test_zip5_extracted_from_9digit(self) -> None:
        result = normalize_mailing_address(
            mail_1="100 MAIN ST",
            mail_2="",
            mail_3="",
            city="DURHAM",
            state="NC",
            zip_code="277011234",
        )
        assert result is not None
        assert result["zip5"] == "27701"

    def test_zip5_from_hyphenated(self) -> None:
        result = normalize_mailing_address(
            mail_1="100 MAIN ST",
            mail_2="",
            mail_3="",
            city="DURHAM",
            state="NC",
            zip_code="27701-1234",
        )
        assert result is not None
        assert result["zip5"] == "27701"

    def test_state_uppercase_output(self) -> None:
        result = normalize_mailing_address(
            mail_1="100 MAIN ST",
            mail_2="",
            mail_3="",
            city="DURHAM",
            state="nc",
            zip_code="27701",
        )
        assert result is not None
        assert result["state"] == "NC"

    def test_all_blank_returns_none(self) -> None:
        result = normalize_mailing_address(
            mail_1="",
            mail_2="",
            mail_3="",
            city="",
            state="",
            zip_code="",
        )
        assert result is None

    def test_none_inputs_returns_none(self) -> None:
        result = normalize_mailing_address(
            mail_1=None,
            mail_2=None,
            mail_3=None,
            city=None,
            state=None,
            zip_code=None,
        )
        assert result is None

    def test_city_only_returns_partial(self) -> None:
        result = normalize_mailing_address(
            mail_1="",
            mail_2="",
            mail_3="",
            city="DURHAM",
            state="",
            zip_code="",
        )
        assert result is not None
        assert result["city"] == "Durham"
        assert result["state"] is None
        assert result["zip5"] is None

    def test_invalid_zip_returns_none_zip5(self) -> None:
        result = normalize_mailing_address(
            mail_1="100 MAIN ST",
            mail_2="",
            mail_3="",
            city="DURHAM",
            state="NC",
            zip_code="ABC",
        )
        assert result is not None
        assert result["zip5"] is None
