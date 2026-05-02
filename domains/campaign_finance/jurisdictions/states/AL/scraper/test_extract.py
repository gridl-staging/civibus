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


def test_extract_contribution_individual_multi_word_name() -> None:
    """Multi-word CONTRIBUTOR name should extract as Person."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    row = _find_row(rows, key="CONTRIBUTOR", value="SARAH WILLIAMS")

    extracted = extract_al_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].first_name == "SARAH"
    assert extracted["donor_person"].last_name == "WILLIAMS"
    assert extracted["donor_org"] is None


def test_extract_contribution_organization_keyword() -> None:
    """CONTRIBUTOR name with org keyword should extract as Organization."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    row = _find_row(rows, key="CONTRIBUTOR", value="SOUTHERN STEEL CORPORATION")

    extracted = extract_al_contribution(row)

    assert extracted["donor_person"] is None
    assert extracted["donor_org"] is not None
    assert "SOUTHERN STEEL CORPORATION" in extracted["donor_org"].canonical_name


def test_extract_contribution_committee_has_al_org_id() -> None:
    """Committee should carry the al_org_id identifier from COMMITTEEID field."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    row = _find_row(rows, key="CONTRIBUTOR", value="SARAH WILLIAMS")

    extracted = extract_al_contribution(row)

    assert extracted["committee"].identifiers.get("al_org_id") == "CC2024-001"
    assert extracted["committee"].canonical_name == "Friends of Smith for Governor"


def test_extract_contribution_address_from_citystate() -> None:
    """Address should be parsed from combined CITYSTATE and ZIP fields."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    row = _find_row(rows, key="CONTRIBUTOR", value="SARAH WILLIAMS")

    extracted = extract_al_contribution(row)

    assert extracted["address"] is not None
    assert extracted["address"].city == "Montgomery"
    assert extracted["address"].state == "AL"
    assert extracted["address"].zip5 == "36104"


def test_extract_contribution_person_with_middle_name() -> None:
    """Person with middle initial in CONTRIBUTOR should include it."""
    rows = _load_fixture_rows(_SAMPLE_CONTRIBUTIONS_PATH)
    row = _find_row(rows, key="CONTRIBUTOR", value="ROBERT A JONES")

    extracted = extract_al_contribution(row)

    assert extracted["donor_person"] is not None
    assert extracted["donor_person"].first_name == "ROBERT"
    assert extracted["donor_person"].middle_name == "A"
    assert extracted["donor_person"].last_name == "JONES"


# ---------------------------------------------------------------------------
# Expenditure extraction tests
# ---------------------------------------------------------------------------


def test_extract_expenditure_payee_person() -> None:
    """Multi-word PAYEE name should extract as payee Person."""
    rows = _load_fixture_rows(_SAMPLE_EXPENDITURES_PATH)
    row = _find_row(rows, key="PAYEE", value="MARK DAVIS")

    extracted = extract_al_expenditure(row)

    assert extracted["payee_person"] is not None
    assert extracted["payee_person"].first_name == "MARK"
    assert extracted["payee_person"].last_name == "DAVIS"
    assert extracted["payee_org"] is None


def test_extract_expenditure_payee_organization() -> None:
    """PAYEE name with org keyword should extract as payee Organization."""
    rows = _load_fixture_rows(_SAMPLE_EXPENDITURES_PATH)
    row = _find_row(rows, key="PAYEE", value="BIRMINGHAM PRINTING COMPANY")

    extracted = extract_al_expenditure(row)

    assert extracted["payee_person"] is None
    assert extracted["payee_org"] is not None
    assert "BIRMINGHAM PRINTING" in extracted["payee_org"].canonical_name


def test_extract_expenditure_committee() -> None:
    """Expenditure committee should have correct name and al_org_id."""
    rows = _load_fixture_rows(_SAMPLE_EXPENDITURES_PATH)
    row = _find_row(rows, key="PAYEE", value="MARK DAVIS")

    extracted = extract_al_expenditure(row)

    assert extracted["committee"].canonical_name == "Friends of Smith for Governor"
    assert extracted["committee"].identifiers.get("al_org_id") == "CC2024-001"
