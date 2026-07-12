from __future__ import annotations

from uuid import uuid4

from core.people.enrichment.models import CandidateEnrichmentTarget
from core.people.enrichment.strategy_official_roster_cache import (
    OfficialRosterCacheStrategy,
    ROSTER_CACHE_PORTRAIT_REUSE_METADATA_KEY,
    ROSTER_CACHE_PORTRAIT_REUSE_METADATA_VALUE,
)
from core.types.python.models import PersonPortrait


def test_fetch_returns_succeeded_attempt_with_portrait_fields_when_active_roster_portrait_exists(
    monkeypatch,
) -> None:
    person_id = uuid4()
    strategy = OfficialRosterCacheStrategy(conn=object())
    cached_portrait = PersonPortrait(
        person_id=person_id,
        source_record_id=uuid4(),
        status="active",
        rights_status="public_domain",
        image_hash="a" * 64,
        mime_type="image/jpeg",
        width_px=640,
        height_px=480,
        source_image_url="https://www.example.org/portrait.jpg",
    )
    monkeypatch.setattr(
        "core.people.enrichment.strategy_official_roster_cache.db.select_active_roster_portrait_for_person",
        lambda _conn, *, person_id: cached_portrait if person_id == cached_portrait.person_id else None,
    )

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Jane Candidate", person_id=person_id),
        ("portrait_image_url", "occupation"),
    )

    assert attempt.status == "succeeded"
    assert attempt.source == "official_roster_cache"
    assert attempt.metadata == {ROSTER_CACHE_PORTRAIT_REUSE_METADATA_KEY: ROSTER_CACHE_PORTRAIT_REUSE_METADATA_VALUE}
    assert record.portrait_image_url == "https://www.example.org/portrait.jpg"
    assert record.portrait_metadata is not None
    assert record.portrait_metadata.image_hash == "a" * 64
    assert record.portrait_metadata.source_image_url == "https://www.example.org/portrait.jpg"
    assert record.portrait_metadata.rights_status == "public_domain"


def test_fetch_returns_no_data_without_mutation_when_no_active_roster_portrait_exists(
    monkeypatch,
) -> None:
    person_id = uuid4()
    strategy = OfficialRosterCacheStrategy(conn=object())
    monkeypatch.setattr(
        "core.people.enrichment.strategy_official_roster_cache.db.select_active_roster_portrait_for_person",
        lambda _conn, *, person_id: None,
    )

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="No Portrait", person_id=person_id),
        ("portrait_image_url", "occupation"),
    )

    assert record == record.__class__()
    assert attempt.status == "no_data"
    assert attempt.source == "official_roster_cache"


def test_fetch_returns_no_data_when_person_id_is_absent() -> None:
    strategy = OfficialRosterCacheStrategy(conn=object())

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Missing Person Id"),
        ("portrait_image_url",),
    )

    assert record == record.__class__()
    assert attempt.status == "no_data"
    assert attempt.source == "official_roster_cache"


def test_fetch_returns_no_data_for_non_active_roster_portrait_status(
    monkeypatch,
) -> None:
    person_id = uuid4()
    strategy = OfficialRosterCacheStrategy(conn=object())
    rejected_portrait = PersonPortrait(
        person_id=person_id,
        source_record_id=uuid4(),
        status="too_small",
        image_hash="c" * 64,
        mime_type="image/jpeg",
        width_px=120,
        height_px=120,
        source_image_url="https://www.example.org/too-small.jpg",
    )
    monkeypatch.setattr(
        "core.people.enrichment.strategy_official_roster_cache.db.select_active_roster_portrait_for_person",
        lambda _conn, *, person_id: rejected_portrait if person_id == rejected_portrait.person_id else None,
    )

    record, attempt = strategy.fetch(
        CandidateEnrichmentTarget(canonical_name="Small Portrait", person_id=person_id),
        ("portrait_image_url",),
    )

    assert record == record.__class__()
    assert attempt.status == "no_data"
    assert attempt.source == "official_roster_cache"
