from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.people.enrichment.models import CandidateEnrichmentRecord, CandidateEnrichmentTarget
from core.people.enrichment.strategy_sboe import (
    SboeEnrichmentStrategy,
    _extract_candidate_csv_url,
    _find_candidate_row,
)


def _fixture(name: str) -> dict[str, object]:
    fixture_path = Path(__file__).with_name("test_fixtures") / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_sboe_strategy_extracts_expected_fields() -> None:
    strategy = SboeEnrichmentStrategy(fetcher=lambda _target: _fixture("sboe_success.json"))

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Jordan Lee", state_code="NC"),
        missing_fields=("biography", "portrait_image_url"),
    )

    assert attempt.status == "succeeded"
    assert record.biography == "Jordan Lee is running for State Senate."
    assert record.portrait_image_url == "https://sboe.example.org/jordan_lee.jpg"


def test_sboe_strategy_returns_no_data_attempt() -> None:
    strategy = SboeEnrichmentStrategy(fetcher=lambda _target: _fixture("sboe_no_data.json"))

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Missing Person", state_code="NC"),
        missing_fields=("biography",),
    )

    assert record == record.__class__()
    assert attempt.status == "no_data"


def test_sboe_strategy_skips_unspecified_state_before_fetching() -> None:
    def _unexpected_fetch(_target: CandidateEnrichmentTarget) -> dict[str, object] | None:
        pytest.fail("SBOE must not query NC candidate data without an explicit NC target")

    strategy = SboeEnrichmentStrategy(fetcher=_unexpected_fetch)

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Federal Person", bioguide_id="F000001"),
        missing_fields=("biography",),
    )

    assert record == CandidateEnrichmentRecord()
    assert attempt.status == "skipped"
    assert attempt.skip_reason == "state_not_nc"


def test_extract_candidate_csv_url_prefers_requested_cycle() -> None:
    html = """
    <a href="https://s3.amazonaws.com/dl.ncsbe.gov/Elections/2025/Candidate%20Filing/Candidate_Listing_2025.csv">2025</a>
    <a href="https://s3.amazonaws.com/dl.ncsbe.gov/Elections/2026/Candidate%20Filing/Candidate_Listing_2026.csv">2026</a>
    """

    assert _extract_candidate_csv_url(html, preferred_year=2026) == (
        "https://s3.amazonaws.com/dl.ncsbe.gov/Elections/2026/Candidate%20Filing/Candidate_Listing_2026.csv"
    )


def test_find_candidate_row_matches_ballot_name_or_split_name_columns() -> None:
    csv_text = "\n".join(
        [
            '"name_on_ballot","first_name","middle_name","last_name","party_candidate"',
            '"Roy Cooper","ROY","ASBERRY","COOPER","DEM"',
            '"Shannon W. Bray","SHANNON","WILSON","BRAY","LIB"',
        ]
    )

    cooper_row = _find_candidate_row(csv_text, canonical_name="Roy Cooper")
    bray_row = _find_candidate_row(csv_text, canonical_name="Shannon Wilson Bray")

    assert cooper_row is not None
    assert cooper_row["party_candidate"] == "DEM"
    assert bray_row is not None
    assert bray_row["party_candidate"] == "LIB"
