"""Tests for AL extract module."""

from __future__ import annotations

import json
from pathlib import Path

from domains.campaign_finance.jurisdictions.states.AL.scraper.extract import (
    extract_al_contribution,
    extract_al_expenditure,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.json"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.json"


def _load_fixture_rows(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["data"]


def _find_row(rows: list[dict], *, key: str, value: str) -> dict[str, str | None]:
    """Find a row by matching a key/value pair, normalizing empty strings to None."""
    for row in rows:
        normalized = {k: (v.strip() if isinstance(v, str) and v.strip() else None) for k, v in row.items()}
        if normalized.get(key) == value:
            return normalized
    raise AssertionError(f"missing fixture row for {key}={value}")


# ---------------------------------------------------------------------------
# Contribution extraction tests
# ---------------------------------------------------------------------------


def test_extract_contribution_individual_with_first_name() -> None:
    """Row with firstName should extract as Person, not Organization."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    # WILLIAMS row: individual with first/last name.
    row = _find_row(rows, key="lastName", value="WILLIAMS")

    extracted = extract_al_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].first_name == "SARAH"
    assert extracted["donor_person"].last_name == "WILLIAMS"
    assert extracted["donor_org"] is None


def test_extract_contribution_organization_without_first_name() -> None:
    """Row without firstName should extract as Organization."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    # SOUTHERN STEEL CORPORATION row: business with no firstName.
    row = _find_row(rows, key="sourceName", value="SOUTHERN STEEL CORPORATION")

    extracted = extract_al_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert "SOUTHERN STEEL CORPORATION" in extracted["donor_org"].canonical_name


def test_extract_contribution_committee_has_al_org_id() -> None:
    """Committee should carry the al_org_id identifier from orgId field."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    row = _find_row(rows, key="lastName", value="WILLIAMS")

    extracted = extract_al_contribution(row)

    assert extracted["committee"].identifiers.get("al_org_id") == "CC2024-001"
    assert extracted["committee"].canonical_name == "Friends of Smith for Governor"


def test_extract_contribution_address() -> None:
    """Address should be extracted with city, state, zip5."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    row = _find_row(rows, key="lastName", value="WILLIAMS")

    extracted = extract_al_contribution(row)

    assert extracted["address"] is not None
    assert extracted["address"].city == "Montgomery"
    assert extracted["address"].state == "AL"
    assert extracted["address"].zip5 == "36104"


def test_extract_contribution_person_with_middle_name() -> None:
    """Person with middleName should include it in canonical_name."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    row = _find_row(rows, key="lastName", value="JONES")

    extracted = extract_al_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].first_name == "ROBERT"
    assert extracted["donor_person"].middle_name == "A"
    assert "A" in extracted["donor_person"].canonical_name


# ---------------------------------------------------------------------------
# Expenditure extraction tests
# ---------------------------------------------------------------------------


def test_extract_expenditure_payee_person() -> None:
    """Expenditure row with firstName should extract as payee Person."""
    rows = _load_fixture_rows(_SAMPLE_EXPENDITURES_PATH)
    row = _find_row(rows, key="lastName", value="DAVIS")

    extracted = extract_al_expenditure(row)

    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].first_name == "MARK"
    assert extracted["payee_person"].last_name == "DAVIS"
    assert extracted["payee_org"] is None


def test_extract_expenditure_payee_organization() -> None:
    """Expenditure row without firstName should extract as payee Organization."""
    rows = _load_fixture_rows(_SAMPLE_EXPENDITURES_PATH)
    row = _find_row(rows, key="payeeName", value="BIRMINGHAM PRINTING CO")

    extracted = extract_al_expenditure(row)

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert "BIRMINGHAM PRINTING" in extracted["payee_org"].canonical_name


def test_extract_expenditure_committee() -> None:
    """Expenditure committee should have correct name and al_org_id."""
    rows = _load_fixture_rows(_SAMPLE_EXPENDITURES_PATH)
    row = _find_row(rows, key="lastName", value="DAVIS")

    extracted = extract_al_expenditure(row)

    assert extracted["committee"].canonical_name == "Friends of Smith for Governor"
    assert extracted["committee"].identifiers.get("al_org_id") == "CC2024-001"
