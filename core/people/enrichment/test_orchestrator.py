from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from core.people.enrichment.models import CandidateEnrichmentRecord, CandidateEnrichmentTarget, PortraitBinaryMetadata
from core.people.enrichment.orchestrator import (
    NcScopeSelectionResult,
    NcScopeTarget,
    _apply_enrichment_for_targets,
    _build_enrichment_target,
    _build_enrichment_data_source,
    _build_enrichment_source_record,
    _rows_to_scope_targets,
    main,
    run_cf_candidate_enrichment,
    run_nc_enrichment,
    select_cf_candidate_scope_targets,
    select_nc_scope_targets,
)
from core.types.python.models import Person, SourceRecord


class _FakeChain:
    def __init__(self, record_factory: Callable[[CandidateEnrichmentTarget], CandidateEnrichmentRecord]) -> None:
        self._record_factory = record_factory
        self.calls: list[CandidateEnrichmentTarget] = []

    def enrich(self, target: CandidateEnrichmentTarget) -> CandidateEnrichmentRecord:
        self.calls.append(target)
        return self._record_factory(target)


def test_build_enrichment_provenance_uses_canonical_urls() -> None:
    data_source = _build_enrichment_data_source(scope="cf-candidate", state="nc")
    source_record = _build_enrichment_source_record(
        data_source_id=uuid4(),
        scope="cf-candidate",
        state="nc",
        cycle=2026,
    )

    assert data_source.source_url == "https://civibus.shareborough.com/provenance/people-enrichment"
    assert source_record.source_url is None


def test_select_nc_scope_targets_unions_and_dedupes_people_with_stable_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_a = uuid4()
    person_b = uuid4()
    person_c = uuid4()

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator._select_nc_candidacy_targets",
        lambda _conn, *, state, cycle: [
            NcScopeTarget(person_id=person_b, canonical_name="Casey Bell"),
            NcScopeTarget(person_id=person_a, canonical_name="Alex Able"),
        ],
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator._select_nc_current_officeholder_targets",
        lambda _conn, *, state: [
            NcScopeTarget(person_id=person_c, canonical_name="Dana Core"),
            NcScopeTarget(person_id=person_b, canonical_name="Casey Bell"),
        ],
    )

    selected = select_nc_scope_targets(object(), state="NC", cycle=2026)

    assert [target.person_id for target in selected.targets] == [person_a, person_b, person_c]
    assert selected.warnings == []
    assert selected.candidacy_count == 2
    assert selected.officeholder_count == 2


def test_select_nc_scope_targets_emits_warning_when_candidacy_scope_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator._select_nc_candidacy_targets",
        lambda _conn, *, state, cycle: [],
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator._select_nc_current_officeholder_targets",
        lambda _conn, *, state: [
            NcScopeTarget(person_id=person_id, canonical_name="Office Holder"),
        ],
    )

    selected = select_nc_scope_targets(object(), state="NC", cycle=2026)

    assert [target.person_id for target in selected.targets] == [person_id]
    assert selected.warnings == ["nc_candidacy_scope_empty"]


def test_select_cf_candidate_scope_targets_dedupes_and_orders_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_a = uuid4()
    person_b = uuid4()
    person_c = uuid4()

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator._select_cf_candidate_person_targets",
        lambda _conn, *, state: [
            NcScopeTarget(person_id=person_b, canonical_name="Casey Bell"),
            NcScopeTarget(person_id=person_a, canonical_name="Alex Able"),
            NcScopeTarget(person_id=person_b, canonical_name="Casey Bell"),
            NcScopeTarget(person_id=person_c, canonical_name="Dana Core"),
        ],
    )

    selected = select_cf_candidate_scope_targets(object(), state="NC")

    assert [target.person_id for target in selected.targets] == [person_a, person_b, person_c]
    assert selected.warnings == []
    assert selected.candidacy_count == 4
    assert selected.officeholder_count == 0


def test_rows_to_scope_targets_hydrates_roster_bio_url_from_identifiers() -> None:
    person_id = uuid4()
    scope_targets = _rows_to_scope_targets(
        [
            {
                "person_id": person_id,
                "canonical_name": "Casey Bell",
                "roster_bio_url": "https://www.ncleg.gov/Members/Biography/H/53",
            }
        ]
    )

    assert len(scope_targets) == 1
    assert scope_targets[0].person_id == person_id
    assert scope_targets[0].roster_bio_url == "https://www.ncleg.gov/Members/Biography/H/53"


def test_build_enrichment_target_threads_roster_bio_url() -> None:
    target = NcScopeTarget(
        person_id=uuid4(),
        canonical_name="Casey Bell",
        roster_bio_url="https://www.ncleg.gov/Members/Biography/H/149",
    )

    enrichment_target = _build_enrichment_target(target, state="NC")

    assert enrichment_target.person_id == target.person_id
    assert enrichment_target.canonical_name == "Casey Bell"
    assert enrichment_target.roster_bio_url == "https://www.ncleg.gov/Members/Biography/H/149"


def test_run_nc_enrichment_uses_strategy_chain_and_persists_portrait_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()
    selected_target = NcScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_nc_scope_targets",
        lambda _conn, *, state, cycle: NcScopeSelectionResult(
            targets=[selected_target],
            warnings=[],
            candidacy_count=1,
            officeholder_count=0,
        ),
    )

    person = Person(id=person_id, canonical_name="Morgan Candidate")
    monkeypatch.setattr("core.people.enrichment.orchestrator.db.select_person", lambda _conn, _person_id: person)

    bio_updates: list[tuple[UUID, str | None, str | None, str | None, str | None, str | None]] = []

    def _capture_bio_update(
        _conn: object,
        *,
        person_id: UUID,
        occupation: str | None,
        education: str | None,
        bio_text: str | None,
        bio_source_url: str | None,
        bio_license: str | None,
    ) -> tuple[str, ...]:
        bio_updates.append((person_id, occupation, education, bio_text, bio_source_url, bio_license))
        updated_fields: list[str] = []
        if occupation is not None:
            updated_fields.append("occupation")
        if education is not None:
            updated_fields.append("education")
        if bio_text is not None:
            updated_fields.append("bio_text")
        if bio_source_url is not None:
            updated_fields.append("bio_source_url")
        if bio_license is not None:
            updated_fields.append("bio_license")
        return tuple(updated_fields)

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        _capture_bio_update,
        raising=False,
    )

    inserted_portraits: list[object] = []

    def _capture_insert_person_portrait(_conn: object, portrait: object) -> UUID:
        inserted_portraits.append(portrait)
        return uuid4()

    monkeypatch.setattr("core.people.enrichment.orchestrator.db.insert_person_portrait", _capture_insert_person_portrait)

    provenance_calls: list[tuple[str, str, UUID]] = []

    def _capture_field_provenance(
        _conn: object,
        entity_type: str,
        entity_id: UUID,
        field_name: str,
        field_value: str,
        source_record_id: UUID,
    ) -> UUID:
        provenance_calls.append((entity_type, field_name, source_record_id))
        return uuid4()

    monkeypatch.setattr("core.people.enrichment.orchestrator.db_ingest.insert_field_provenance", _capture_field_provenance)
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_source_record",
        lambda _conn, _record_id: SourceRecord(
            id=source_record_id,
            data_source_id=uuid4(),
            source_record_key="people-enrichment:nc:NC:2026",
            source_url="https://example.org/people-enrichment/nc",
            raw_fields={"scope": "nc", "state": "NC"},
            pull_date=datetime(2026, 4, 27, 21, 0, tzinfo=timezone.utc),
        ),
    )
    bio_source_record_id = uuid4()
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.try_insert_source_record",
        lambda _conn, source_record: bio_source_record_id
        if source_record.source_url == "https://www.ncleg.gov/Members/Biography/H/149"
        else uuid4(),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
    )

    fake_chain = _FakeChain(
        lambda _target: CandidateEnrichmentRecord(
            occupation="Teacher",
            biography="Morgan Candidate served on the school board.",
            bio_source_url="https://www.ncleg.gov/Members/Biography/H/149",
            bio_license="public_domain",
            portrait_image_url="https://images.example.org/morgan.jpg",
            portrait_metadata=PortraitBinaryMetadata(
                image_hash="a" * 64,
                mime_type="image/jpeg",
                width_px=800,
                height_px=600,
                source_image_url="https://images.example.org/morgan.jpg",
            ),
            field_provenance={"occupation": "wikidata"},
        )
    )

    summary = run_nc_enrichment(
        object(),
        chain=fake_chain,
        source_record_id=source_record_id,
        state="NC",
        cycle=2026,
    )

    assert len(fake_chain.calls) == 1
    assert fake_chain.calls[0].canonical_name == "Morgan Candidate"
    assert fake_chain.calls[0].person_id == person_id
    assert len(inserted_portraits) == 1
    assert bio_updates == [
        (
            person_id,
            "Teacher",
            None,
            "Morgan Candidate served on the school board.",
            "https://www.ncleg.gov/Members/Biography/H/149",
            "public_domain",
        )
    ]
    assert provenance_calls == [
        ("person", "occupation", source_record_id),
        ("person", "bio_text", bio_source_record_id),
        ("person", "bio_license", bio_source_record_id),
    ]
    assert summary["processed"] == 1
    assert summary["warnings"] == []


def test_apply_enrichment_reuses_roster_cached_portrait_without_duplicate_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()
    selected_target = NcScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")
    person = Person(id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr("core.people.enrichment.orchestrator.db.select_person", lambda _conn, _person_id: person)
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **_kwargs: ("occupation",),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
    )

    inserted_portraits: list[object] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.insert_person_portrait",
        lambda _conn, portrait: inserted_portraits.append(portrait) or uuid4(),
    )

    provenance_calls: list[tuple[str, UUID, str, str, UUID]] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda _conn, entity_type, entity_id, field_name, field_value, observed_source_record_id: provenance_calls.append(
            (entity_type, entity_id, field_name, field_value, observed_source_record_id)
        )
        or uuid4(),
    )

    class _CacheAwareChain:
        def __init__(self) -> None:
            self.calls: list[CandidateEnrichmentTarget] = []

        def enrich(self, target: CandidateEnrichmentTarget) -> CandidateEnrichmentRecord:
            self.calls.append(target)
            return CandidateEnrichmentRecord(
                occupation="Teacher",
                portrait_image_url="https://images.example.org/roster.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="f" * 64,
                    mime_type="image/jpeg",
                    width_px=640,
                    height_px=480,
                    source_image_url="https://images.example.org/roster.jpg",
                ),
                field_provenance={
                    "occupation": "sboe",
                    "portrait_image_url": "official_roster_cache",
                },
            )

    fake_chain = _CacheAwareChain()
    summary = _apply_enrichment_for_targets(
        object(),
        strategy_chain=fake_chain,
        scope_targets=[selected_target],
        source_record_id=source_record_id,
        state="NC",
        summary={
            "processed": 0,
            "portrait_writes": 0,
            "bio_updates": 0,
            "field_provenance_writes": 0,
        },
        dry_run=False,
    )

    assert len(fake_chain.calls) == 1
    assert fake_chain.calls[0].person_id == person_id
    assert inserted_portraits == []
    assert summary["portrait_writes"] == 0
    assert summary["bio_updates"] == 1
    assert provenance_calls == [("person", person_id, "occupation", "Teacher", source_record_id)]


def test_apply_enrichment_skips_bio_provenance_when_no_new_bio_text_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()
    selected_target = NcScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")
    person = Person(id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr("core.people.enrichment.orchestrator.db.select_person", lambda _conn, _person_id: person)
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **_kwargs: ("occupation",),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.insert_person_portrait",
        lambda _conn, portrait: uuid4(),
    )

    source_record_calls: list[SourceRecord] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.try_insert_source_record",
        lambda _conn, source_record: source_record_calls.append(source_record) or uuid4(),
    )

    provenance_calls: list[tuple[str, UUID, str, str, UUID]] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda _conn, entity_type, entity_id, field_name, field_value, observed_source_record_id: provenance_calls.append(
            (entity_type, entity_id, field_name, field_value, observed_source_record_id)
        )
        or uuid4(),
    )

    summary = _apply_enrichment_for_targets(
        object(),
        strategy_chain=_FakeChain(
            lambda _target: CandidateEnrichmentRecord(
                occupation="Teacher",
                biography="Biography text that should not be written this run.",
                bio_source_url="https://www.ncleg.gov/Members/Biography/H/149",
                bio_license="public_domain",
            )
        ),
        scope_targets=[selected_target],
        source_record_id=source_record_id,
        state="NC",
        summary={
            "processed": 0,
            "portrait_writes": 0,
            "bio_updates": 0,
            "field_provenance_writes": 0,
        },
        dry_run=False,
    )

    assert summary["bio_updates"] == 1
    assert summary["field_provenance_writes"] == 1
    assert provenance_calls == [("person", person_id, "occupation", "Teacher", source_record_id)]
    assert source_record_calls == []


def test_run_cf_candidate_enrichment_skips_portrait_insert_for_takedown_requested_source_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()
    selected_target = NcScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: NcScopeSelectionResult(
            targets=[selected_target],
            warnings=[],
            candidacy_count=1,
            officeholder_count=0,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_person",
        lambda _conn, _person_id: Person(id=person_id, canonical_name="Morgan Candidate"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **_kwargs: tuple(),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: person_id == selected_target.person_id
        and source_image_url == "https://images.example.org/morgan.jpg",
        raising=False,
    )

    inserted_portraits: list[object] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.insert_person_portrait",
        lambda _conn, portrait: inserted_portraits.append(portrait) or uuid4(),
    )

    summary = run_cf_candidate_enrichment(
        object(),
        chain=_FakeChain(
            lambda _target: CandidateEnrichmentRecord(
                portrait_image_url="https://images.example.org/morgan.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="e" * 64,
                    mime_type="image/jpeg",
                    width_px=800,
                    height_px=600,
                    source_image_url="https://images.example.org/morgan.jpg",
                ),
            )
        ),
        source_record_id=source_record_id,
        state="NC",
    )

    assert summary["processed"] == 1
    assert summary["portrait_writes"] == 0
    assert inserted_portraits == []


def test_run_cf_candidate_enrichment_bootstraps_source_record_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    data_source_id = uuid4()
    source_record_id = uuid4()
    selected_target = NcScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: NcScopeSelectionResult(
            targets=[selected_target],
            warnings=[],
            candidacy_count=1,
            officeholder_count=0,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_person",
        lambda _conn, _person_id: Person(id=person_id, canonical_name="Morgan Candidate"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **_kwargs: ("occupation",),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
        raising=False,
    )
    monkeypatch.setattr("core.people.enrichment.orchestrator.db.insert_person_portrait", lambda *_args, **_kwargs: uuid4())
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.ensure_data_source",
        lambda _conn, _data_source: data_source_id,
        raising=False,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.try_insert_source_record",
        lambda _conn, _source_record: source_record_id,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_source_record",
        lambda _conn, record_id: SourceRecord(
            id=record_id,
            data_source_id=data_source_id,
            source_record_key="cf-candidate-NC",
            source_url="https://example.org/people-enrichment/cf-candidate/NC",
            raw_fields={"scope": "cf-candidate", "state": "NC"},
            pull_date=datetime(2026, 4, 27, 21, 0, tzinfo=timezone.utc),
        ),
    )

    provenance_calls: list[UUID] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda _conn, _entity_type, _entity_id, _field_name, _field_value, observed_source_record_id: provenance_calls.append(
            observed_source_record_id
        )
        or uuid4(),
    )

    summary = run_cf_candidate_enrichment(
        object(),
        chain=_FakeChain(
            lambda _target: CandidateEnrichmentRecord(
                occupation="Teacher",
                portrait_image_url="https://images.example.org/morgan.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="e" * 64,
                    mime_type="image/jpeg",
                    width_px=800,
                    height_px=600,
                    source_image_url="https://images.example.org/morgan.jpg",
                ),
            )
        ),
        state="NC",
    )

    assert summary["processed"] == 1
    assert provenance_calls == [source_record_id]
    assert summary["source_record_id"] == source_record_id
    assert summary["data_source_id"] == data_source_id


def test_run_cf_candidate_enrichment_bootstrap_source_record_marks_partial_limit_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    data_source_id = uuid4()
    source_record_id = uuid4()
    selected_targets = [
        NcScopeTarget(person_id=person_id, canonical_name="Morgan Candidate"),
        NcScopeTarget(person_id=uuid4(), canonical_name="Taylor Candidate"),
    ]
    captured_source_records: list[SourceRecord] = []

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: NcScopeSelectionResult(
            targets=selected_targets,
            warnings=[],
            candidacy_count=2,
            officeholder_count=0,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_person",
        lambda _conn, _person_id: Person(id=person_id, canonical_name="Morgan Candidate"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **_kwargs: ("occupation",),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
        raising=False,
    )
    monkeypatch.setattr("core.people.enrichment.orchestrator.db.insert_person_portrait", lambda *_args, **_kwargs: uuid4())
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.ensure_data_source",
        lambda _conn, _data_source: data_source_id,
        raising=False,
    )

    def _capture_source_record(_conn: object, source_record: SourceRecord) -> UUID:
        captured_source_records.append(source_record)
        return source_record_id

    monkeypatch.setattr("core.people.enrichment.orchestrator.db_ingest.try_insert_source_record", _capture_source_record)

    def _selected_source_record(_conn: object, record_id: UUID) -> SourceRecord:
        asserted_source_record = captured_source_records[0]
        return SourceRecord(
            id=record_id,
            data_source_id=data_source_id,
            source_record_key=asserted_source_record.source_record_key,
            source_url=None,
            raw_fields=asserted_source_record.raw_fields,
            pull_date=datetime(2026, 4, 27, 21, 0, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("core.people.enrichment.orchestrator.db.select_source_record", _selected_source_record)
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda *_args, **_kwargs: uuid4(),
    )

    summary = run_cf_candidate_enrichment(
        object(),
        chain=_FakeChain(lambda _target: CandidateEnrichmentRecord(occupation="Teacher")),
        state="NC",
        limit=1,
    )

    assert summary["selected"] == 1
    assert len(captured_source_records) == 1
    assert captured_source_records[0].source_record_key == "people-enrichment:cf-candidate:NC:all:limit-1"
    assert captured_source_records[0].raw_fields["run_scope"] == "partial"
    assert captured_source_records[0].raw_fields["effective_limit"] == 1


def test_run_cf_candidate_enrichment_conflict_uses_shared_active_source_record_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    data_source_id = uuid4()
    active_source_record_id = uuid4()
    selected_target = NcScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: NcScopeSelectionResult(
            targets=[selected_target],
            warnings=[],
            candidacy_count=1,
            officeholder_count=0,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_person",
        lambda _conn, _person_id: Person(id=person_id, canonical_name="Morgan Candidate"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **_kwargs: ("occupation",),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
        raising=False,
    )
    monkeypatch.setattr("core.people.enrichment.orchestrator.db.insert_person_portrait", lambda *_args, **_kwargs: uuid4())
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.ensure_data_source",
        lambda _conn, _data_source: data_source_id,
        raising=False,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.try_insert_source_record",
        lambda _conn, _source_record: None,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_source_record",
        lambda _conn, _record_id: pytest.fail("conflict path must use core.db active selector, not direct id lookup"),
    )
    selector_calls: list[tuple[UUID, str]] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_active_source_record_by_key",
        lambda _conn, *, data_source_id, source_record_key: selector_calls.append((data_source_id, source_record_key))
        or SourceRecord(
            id=active_source_record_id,
            data_source_id=data_source_id,
            source_record_key=source_record_key,
            source_url=None,
            raw_fields={"scope": "cf-candidate", "state": "NC"},
            pull_date=datetime(2026, 4, 27, 21, 0, tzinfo=timezone.utc),
        ),
    )

    provenance_calls: list[UUID] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda _conn, _entity_type, _entity_id, _field_name, _field_value, observed_source_record_id: provenance_calls.append(
            observed_source_record_id
        )
        or uuid4(),
    )

    summary = run_cf_candidate_enrichment(
        object(),
        chain=_FakeChain(
            lambda _target: CandidateEnrichmentRecord(
                occupation="Teacher",
                portrait_image_url="https://images.example.org/morgan.jpg",
                portrait_metadata=PortraitBinaryMetadata(
                    image_hash="e" * 64,
                    mime_type="image/jpeg",
                    width_px=800,
                    height_px=600,
                    source_image_url="https://images.example.org/morgan.jpg",
                ),
            )
        ),
        state="NC",
    )

    assert summary["processed"] == 1
    assert selector_calls == [(data_source_id, "people-enrichment:cf-candidate:NC:all")]
    assert provenance_calls == [active_source_record_id]
    assert summary["source_record_id"] == active_source_record_id
    assert summary["data_source_id"] == data_source_id


def test_run_cf_candidate_enrichment_dry_run_does_not_bootstrap_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: NcScopeSelectionResult(
            targets=[NcScopeTarget(person_id=uuid4(), canonical_name="Dry Run Candidate")],
            warnings=[],
            candidacy_count=1,
            officeholder_count=0,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.ensure_data_source",
        lambda _conn, _data_source: pytest.fail("dry-run must not bootstrap data sources"),
        raising=False,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.try_insert_source_record",
        lambda _conn, _source_record: pytest.fail("dry-run must not write source records"),
    )

    summary = run_cf_candidate_enrichment(
        object(),
        chain=_FakeChain(lambda _target: CandidateEnrichmentRecord(occupation="Teacher")),
        state="NC",
        dry_run=True,
    )

    assert summary["selected"] == 1
    assert summary["processed"] == 0
    assert summary["dry_run"] is True
    assert summary["source_record_id"] is None
    assert summary["data_source_id"] is None


def test_run_cf_candidate_enrichment_rejects_negative_limit_before_scope_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: pytest.fail("negative limit must fail before scope selection"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.ensure_data_source",
        lambda _conn, _data_source: pytest.fail("negative limit must fail before provenance bootstrap"),
        raising=False,
    )

    with pytest.raises(ValueError, match="limit must be greater than or equal to 0"):
        run_cf_candidate_enrichment(
            object(),
            chain=_FakeChain(lambda _target: CandidateEnrichmentRecord()),
            state="NC",
            limit=-1,
        )


def test_run_nc_enrichment_propagates_scope_warning_when_candidacy_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_nc_scope_targets",
        lambda _conn, *, state, cycle: NcScopeSelectionResult(
            targets=[],
            warnings=["nc_candidacy_scope_empty"],
            candidacy_count=0,
            officeholder_count=0,
        ),
    )

    summary = run_nc_enrichment(object(), chain=_FakeChain(lambda _target: CandidateEnrichmentRecord()), dry_run=True)

    assert summary["processed"] == 0
    assert summary["warnings"] == ["nc_candidacy_scope_empty"]


def test_run_nc_enrichment_rejects_negative_limit_before_scope_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_nc_scope_targets",
        lambda _conn, *, state, cycle: pytest.fail("negative limit must fail before scope selection"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.ensure_data_source",
        lambda _conn, _data_source: pytest.fail("negative limit must fail before provenance bootstrap"),
        raising=False,
    )

    with pytest.raises(ValueError, match="limit must be greater than or equal to 0"):
        run_nc_enrichment(
            object(),
            chain=_FakeChain(lambda _target: CandidateEnrichmentRecord()),
            state="NC",
            cycle=2026,
            limit=-1,
        )


def test_main_commits_successful_non_dry_run_before_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_record_id = uuid4()

    class _Connection:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.close_calls = 0

        def commit(self) -> None:
            self.commit_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    connection = _Connection()
    monkeypatch.setattr("core.people.enrichment.orchestrator.db.get_connection", lambda: connection)
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.run_nc_enrichment",
        lambda *args, **kwargs: {"processed": 1},
    )

    exit_code = main(["--source-record-id", str(source_record_id)])

    assert exit_code == 0
    assert connection.commit_calls == 1
    assert connection.close_calls == 1


def test_main_dispatches_cf_candidate_scope_to_cf_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_record_id = uuid4()

    class _Connection:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.close_calls = 0

        def commit(self) -> None:
            self.commit_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    connection = _Connection()
    nc_calls: list[dict[str, object]] = []
    cf_calls: list[dict[str, object]] = []

    monkeypatch.setattr("core.people.enrichment.orchestrator.db.get_connection", lambda: connection)
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.run_nc_enrichment",
        lambda *args, **kwargs: nc_calls.append(kwargs) or {"processed": 0},
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.run_cf_candidate_enrichment",
        lambda *args, **kwargs: cf_calls.append(kwargs) or {"processed": 1},
    )

    exit_code = main(
        [
            "--scope",
            "cf-candidate",
            "--state",
            "PA",
            "--limit",
            "5",
            "--source-record-id",
            str(source_record_id),
        ]
    )

    assert exit_code == 0
    assert len(cf_calls) == 1
    assert cf_calls[0]["state"] == "PA"
    assert cf_calls[0]["limit"] == 5
    assert cf_calls[0]["source_record_id"] == source_record_id
    assert nc_calls == []
    assert connection.commit_calls == 1
    assert connection.close_calls == 1
