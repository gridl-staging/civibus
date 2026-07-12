from __future__ import annotations

from hashlib import sha256

import pytest

from core.people.enrichment.models import CandidateEnrichmentTarget
from core.people.enrichment.strategy_bioguide_portrait import BioguidePortraitStrategy


PNG_400X400 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x01\x90\x00\x00\x01\x90\x08\x02\x00\x00\x00"
    b"\x0f\xdd\xa1\x9b"
    b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb1"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_bioguide_portrait_fetches_expected_url_and_attaches_public_domain_metadata() -> None:
    fetched_urls: list[str] = []

    def _fetch_portrait(url: str) -> bytes:
        fetched_urls.append(url)
        return PNG_400X400

    record, attempt = BioguidePortraitStrategy(portrait_fetcher=_fetch_portrait).fetch(
        CandidateEnrichmentTarget(canonical_name="Nancy Pelosi", bioguide_id="P000197"),
        ("portrait_image_url",),
    )

    expected_url = "https://unitedstates.github.io/images/congress/450x550/P000197.jpg"
    assert fetched_urls == [expected_url]
    assert record.portrait_image_url == expected_url
    assert record.portrait_metadata is not None
    assert record.portrait_metadata.image_hash == sha256(PNG_400X400).hexdigest()
    assert record.portrait_metadata.mime_type == "image/png"
    assert record.portrait_metadata.width_px == 400
    assert record.portrait_metadata.height_px == 400
    assert record.portrait_metadata.rights_status == "public_domain"
    assert attempt.status == "succeeded"
    assert attempt.portrait_status == "active"
    assert attempt.portrait_metadata == record.portrait_metadata


def test_bioguide_portrait_normalizes_padded_lowercase_bioguide_id() -> None:
    fetched_urls: list[str] = []

    BioguidePortraitStrategy(portrait_fetcher=lambda url: fetched_urls.append(url) or PNG_400X400).fetch(
        CandidateEnrichmentTarget(canonical_name="Nancy Pelosi", bioguide_id=" p000197 "),
        ("portrait_image_url",),
    )

    assert fetched_urls == ["https://unitedstates.github.io/images/congress/450x550/P000197.jpg"]


@pytest.mark.parametrize("bioguide_id", [None, "", "   "])
def test_bioguide_portrait_skips_without_bioguide_id(bioguide_id: str | None) -> None:
    fetch_calls: list[str] = []

    record, attempt = BioguidePortraitStrategy(portrait_fetcher=fetch_calls.append).fetch(
        CandidateEnrichmentTarget(canonical_name="Missing Bioguide", bioguide_id=bioguide_id),
        ("portrait_image_url",),
    )

    assert fetch_calls == []
    assert record == record.__class__()
    assert attempt.status == "skipped"
    assert attempt.skip_reason == "missing_bioguide_id"
    assert attempt.portrait_status is None
    assert attempt.portrait_metadata is None


def test_bioguide_portrait_marks_not_found_without_metadata_when_image_is_absent() -> None:
    record, attempt = BioguidePortraitStrategy(portrait_fetcher=lambda _url: None).fetch(
        CandidateEnrichmentTarget(canonical_name="Nancy Pelosi", bioguide_id="P000197"),
        ("portrait_image_url",),
    )

    assert record.portrait_image_url == "https://unitedstates.github.io/images/congress/450x550/P000197.jpg"
    assert record.portrait_metadata is None
    assert attempt.status == "succeeded"
    assert attempt.portrait_status == "not_found"
    assert attempt.portrait_metadata is None
