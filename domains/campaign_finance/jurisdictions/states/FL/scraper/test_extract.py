from __future__ import annotations

from pathlib import Path

from domains.campaign_finance.jurisdictions.states.FL.scraper.parse import (
    parse_contributions,
    parse_expenditures,
    parse_other,
    parse_transfers,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.txt"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.txt"
_SAMPLE_TRANSFERS_PATH = _FIXTURE_DIR / "sample_transfers.txt"
_SAMPLE_OTHER_PATH = _FIXTURE_DIR / "sample_other.txt"


def _contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH))


def _expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH))


def _transfer_rows() -> list[dict[str, str | None]]:
    return list(parse_transfers(_SAMPLE_TRANSFERS_PATH))


def _other_rows() -> list[dict[str, str | None]]:
    return list(parse_other(_SAMPLE_OTHER_PATH))


# -- Lazy import to let tests fail cleanly if extract.py is missing --
def _import_extract():
    from domains.campaign_finance.jurisdictions.states.FL.scraper.extract import (
        extract_fl_contribution,
        extract_fl_expenditure,
        extract_fl_other,
        extract_fl_transfer,
    )

    return extract_fl_contribution, extract_fl_expenditure, extract_fl_transfer, extract_fl_other


# --- Contribution tests ---


def test_contribution_person_with_quoted_name_parses_correctly() -> None:
    """Row 0: '"STAATS, MD" NANCY' -> Person with last=Staats, first=Nancy."""
    extract_fl_contribution, *_ = _import_extract()
    row = _contribution_rows()[0]

    extracted = extract_fl_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].last_name == "Staats"
    assert extracted["donor_person"].first_name == "Nancy"
    # Suffix "MD" should be captured
    assert extracted["donor_person"].suffix == "MD"
    assert extracted["donor_person"].identifiers.get("occupation") == "PHYSICIAN"
    assert extracted["donor_org"] is None


def test_contribution_org_name_routes_to_organization() -> None:
    """Row 1: '1 SOUTH DADE' -> Organization (not a person name)."""
    extract_fl_contribution, *_ = _import_extract()
    row = _contribution_rows()[1]

    extracted = extract_fl_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert extracted["donor_org"].canonical_name == "1 SOUTH DADE"


def test_contribution_city_state_zip_parsed() -> None:
    """Row 0: 'ATLANTIC BEACH, FL 32233' -> Address with city/state/zip5."""
    extract_fl_contribution, *_ = _import_extract()
    row = _contribution_rows()[0]

    extracted = extract_fl_contribution(row)

    assert extracted["address"] is not None
    assert extracted["address"].city == "ATLANTIC BEACH"
    assert extracted["address"].state == "FL"
    assert extracted["address"].zip5 == "32233"


def test_contribution_committee_is_organization() -> None:
    extract_fl_contribution, *_ = _import_extract()
    row = _contribution_rows()[0]

    extracted = extract_fl_contribution(row)

    assert extracted["committee"].canonical_name == "Florida Data Director Council Inc (PAC)"


# --- Expenditure tests ---


def test_expenditure_builds_payee_and_committee() -> None:
    _, extract_fl_expenditure, *_ = _import_extract()
    row = _expenditure_rows()[0]

    extracted = extract_fl_expenditure(row)

    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "1845 GROUP LLC"
    assert extracted["committee"].canonical_name == "Last Line Of Defense Fund (PAC)"
    assert extracted["address"] is not None
    assert extracted["address"].city == "PONTE VEDRA"
    assert extracted["address"].state == "FL"
    assert extracted["address"].zip5 == "32081"


# --- Transfer tests ---


def test_transfer_builds_target_committee_and_source() -> None:
    _, _, extract_fl_transfer, _ = _import_extract()
    row = _transfer_rows()[0]

    extracted = extract_fl_transfer(row)

    assert extracted["target_org"] is not None
    assert extracted["target_org"].canonical_name == "TRUIST BANK - MMA"
    assert extracted["committee"].canonical_name == "Conservatives for Good Government (PAC)"
    assert extracted["address"] is not None
    assert extracted["address"].state == "FL"


# --- Other disbursement tests ---


def test_other_builds_payee_and_committee() -> None:
    *_, extract_fl_other = _import_extract()
    row = _other_rows()[0]

    extracted = extract_fl_other(row)

    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "AIR CANADA"
    assert extracted["committee"].canonical_name == "Friends of Ed Hooper (PAC)"
    assert extracted["address"] is not None
    # XC is a non-US state code but should still be captured
    assert extracted["address"].city == "SAINT-LAURENT"


def test_other_second_row_parses_florida_address() -> None:
    *_, extract_fl_other = _import_extract()
    row = _other_rows()[1]

    extracted = extract_fl_other(row)

    assert extracted["payee_org"] is not None
    assert extracted["payee_org"].canonical_name == "AJ'S FLORIST"
    assert extracted["address"] is not None
    assert extracted["address"].state == "FL"
    assert extracted["address"].zip5 == "33908"
