from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest

from core import db as core_db
from core.people.enrichment.models import CandidateEnrichmentRecord, CandidateEnrichmentTarget, PortraitBinaryMetadata
from core.people.enrichment.orchestrator import (
    ScopeSelectionResult,
    ScopeTarget,
    _apply_enrichment_for_targets,
    _build_enrichment_data_source,
    _build_enrichment_source_record,
    _build_enrichment_target,
    _rows_to_scope_targets,
    main,
    run_cf_candidate_enrichment,
    run_federal_enrichment,
    run_nc_enrichment,
    select_cf_candidate_scope_targets,
    select_federal_scope_targets,
    select_nc_scope_targets,
)
from core.people.enrichment.strategy_chain import StrategyChain
from core.people.enrichment.strategy_sboe import SboeEnrichmentStrategy
from core.types.python.models import Person, SourceRecord, ValidDateRange
from domains.civics.ingest import upsert_office, upsert_officeholding
from domains.civics.types.models import Office, Officeholding


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


def test_build_enrichment_provenance_keeps_state_jurisdiction_unchanged() -> None:
    data_source = _build_enrichment_data_source(scope="nc", state="nc")
    source_record = _build_enrichment_source_record(
        data_source_id=uuid4(),
        scope="nc",
        state="nc",
        cycle=2026,
    )

    assert data_source.jurisdiction == "state/NC"
    assert data_source.name == "people-enrichment-nc-NC"
    assert source_record.source_record_key == "people-enrichment:nc:NC:2026"
    assert source_record.raw_fields["state"] == "NC"


def test_build_enrichment_provenance_uses_federal_jurisdiction_without_fake_state() -> None:
    data_source = _build_enrichment_data_source(scope="federal")
    source_record = _build_enrichment_source_record(
        data_source_id=uuid4(),
        scope="federal",
        cycle=None,
        effective_limit=5,
    )

    assert data_source.jurisdiction == "federal/congress"
    assert data_source.name == "people-enrichment-federal-congress"
    assert source_record.source_record_key == "people-enrichment:federal:federal-congress:all:limit-5"
    assert source_record.raw_fields["jurisdiction"] == "federal/congress"
    assert "state" not in source_record.raw_fields


def test_select_nc_scope_targets_unions_and_dedupes_people_with_stable_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_a = uuid4()
    person_b = uuid4()
    person_c = uuid4()

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator._select_nc_candidacy_targets",
        lambda _conn, *, state, cycle: [
            ScopeTarget(person_id=person_b, canonical_name="Casey Bell"),
            ScopeTarget(person_id=person_a, canonical_name="Alex Able"),
        ],
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator._select_nc_current_officeholder_targets",
        lambda _conn, *, state: [
            ScopeTarget(person_id=person_c, canonical_name="Dana Core"),
            ScopeTarget(person_id=person_b, canonical_name="Casey Bell"),
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
            ScopeTarget(person_id=person_id, canonical_name="Office Holder"),
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
            ScopeTarget(person_id=person_b, canonical_name="Casey Bell"),
            ScopeTarget(person_id=person_a, canonical_name="Alex Able"),
            ScopeTarget(person_id=person_b, canonical_name="Casey Bell"),
            ScopeTarget(person_id=person_c, canonical_name="Dana Core"),
        ],
    )

    selected = select_cf_candidate_scope_targets(object(), state="NC")

    assert [target.person_id for target in selected.targets] == [person_a, person_b, person_c]
    assert selected.warnings == []
    assert selected.candidacy_count == 4
    assert selected.officeholder_count == 0


def _insert_officeholder_scope_row(
    db_conn,
    *,
    person: Person,
    office: Office,
    valid_period: ValidDateRange | None = None,
) -> None:
    person_id = core_db.insert_person(db_conn, person)
    office_id = upsert_office(db_conn, office)
    upsert_officeholding(
        db_conn,
        Officeholding(
            person_id=person_id,
            office_id=office_id,
            valid_period=valid_period or ValidDateRange(start_date=date(2025, 1, 3), end_date=None),
        ),
    )


def test_select_federal_scope_targets_returns_only_active_federal_officeholders(db_conn) -> None:
    baseline_selected = select_federal_scope_targets(db_conn)
    baseline_ids = {target.person_id for target in baseline_selected.targets}

    active_federal = Person(canonical_name="Casey Federal")
    active_state = Person(canonical_name="State Exclusion")
    historical_federal = Person(canonical_name="Former Federal")

    _insert_officeholder_scope_row(
        db_conn,
        person=active_federal,
        office=Office(name="United States Senate", office_level="federal", title="Senator"),
    )
    _insert_officeholder_scope_row(
        db_conn,
        person=active_state,
        office=Office(name="North Carolina House", office_level="state", state="NC", title="Representative"),
    )
    _insert_officeholder_scope_row(
        db_conn,
        person=historical_federal,
        office=Office(name="United States House", office_level="federal", title="Representative"),
        valid_period=ValidDateRange(start_date=date(2021, 1, 3), end_date=date(2023, 1, 3)),
    )

    selected = select_federal_scope_targets(db_conn)
    selected_ids = {target.person_id for target in selected.targets}

    assert selected_ids == baseline_ids | {active_federal.id}
    assert active_federal.id in selected_ids
    assert active_state.id not in selected_ids
    assert historical_federal.id not in selected_ids
    assert selected.warnings == []
    assert selected.candidacy_count == 0
    assert selected.officeholder_count == baseline_selected.officeholder_count + 1


def test_select_federal_scope_targets_hydrates_identifiers_and_orders_deterministically(db_conn) -> None:
    baseline_selected = select_federal_scope_targets(db_conn)
    first_person = Person(
        canonical_name="Alex Federal",
        identifiers={
            "roster_bio_url": "https://bioguide.congress.gov/search/bio/F000001",
            "wikidata_id": "Q111",
            "bioguide_id": "F000001",
        },
    )
    second_person = Person(
        canonical_name="Alex Federal",
        identifiers={
            "roster_bio_url": "https://bioguide.congress.gov/search/bio/F000002",
            "wikidata_id": "Q222",
            "bioguide_id": "F000002",
        },
    )
    expected_people = sorted((first_person, second_person), key=lambda person: str(person.id))

    for person in reversed(expected_people):
        _insert_officeholder_scope_row(
            db_conn,
            person=person,
            office=Office(
                name=f"Federal Seat {person.id}",
                office_level="federal",
                title="Representative",
            ),
        )

    selected = select_federal_scope_targets(db_conn)

    inserted_targets = [
        (
            target.person_id,
            target.canonical_name,
            target.roster_bio_url,
            target.wikidata_entity_id,
            target.bioguide_id,
        )
        for target in selected.targets
        if target.person_id in {person.id for person in expected_people}
    ]

    assert inserted_targets == [
        (
            person.id,
            person.canonical_name,
            person.identifiers["roster_bio_url"],
            person.identifiers["wikidata_id"],
            person.identifiers["bioguide_id"],
        )
        for person in expected_people
    ]
    assert selected.officeholder_count == baseline_selected.officeholder_count + 2


def test_select_federal_scope_targets_delegates_shared_officeholder_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    executed_sql: list[str] = []

    class _Cursor:
        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def execute(self, sql: str) -> None:
            executed_sql.append(sql)

        def fetchall(self) -> list[dict[str, object]]:
            return [
                {
                    "person_id": person_id,
                    "canonical_name": "Shared Federal",
                    "roster_bio_url": None,
                    "wikidata_entity_id": "Q999",
                    "bioguide_id": "S000999",
                }
            ]

    class _Connection:
        def cursor(self, *, row_factory: object = None) -> _Cursor:
            del row_factory
            return _Cursor()

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.federal_officeholder_targets_sql",
        lambda: "SELECT 'shared-federal-officeholder-targets' AS marker",
    )

    selected = select_federal_scope_targets(_Connection())

    assert "shared-federal-officeholder-targets" in executed_sql[0]
    assert selected.targets == [
        ScopeTarget(
            person_id=person_id,
            canonical_name="Shared Federal",
            wikidata_entity_id="Q999",
            bioguide_id="S000999",
        )
    ]


def test_rows_to_scope_targets_hydrates_roster_bio_url_from_identifiers() -> None:
    person_id = uuid4()
    scope_targets = _rows_to_scope_targets(
        [
            {
                "person_id": person_id,
                "canonical_name": "Casey Bell",
                "roster_bio_url": "https://www.ncleg.gov/Members/Biography/H/53",
                "wikidata_entity_id": "Q123",
                "bioguide_id": "B000123",
            }
        ]
    )

    assert len(scope_targets) == 1
    assert scope_targets[0].person_id == person_id
    assert scope_targets[0].roster_bio_url == "https://www.ncleg.gov/Members/Biography/H/53"
    assert scope_targets[0].wikidata_entity_id == "Q123"
    assert scope_targets[0].bioguide_id == "B000123"


def test_build_enrichment_target_threads_scope_identifiers() -> None:
    target = ScopeTarget(
        person_id=uuid4(),
        canonical_name="Casey Bell",
        roster_bio_url="https://www.ncleg.gov/Members/Biography/H/149",
        wikidata_entity_id="Q149",
        bioguide_id="B000149",
    )

    enrichment_target = _build_enrichment_target(target, state="NC")

    assert enrichment_target.person_id == target.person_id
    assert enrichment_target.canonical_name == "Casey Bell"
    assert enrichment_target.roster_bio_url == "https://www.ncleg.gov/Members/Biography/H/149"
    assert enrichment_target.wikidata_entity_id == "Q149"
    assert enrichment_target.bioguide_id == "B000149"

    federal_target = ScopeTarget(
        person_id=uuid4(),
        canonical_name="Casey Federal",
        bioguide_id=" f000197 ",
    )
    federal_enrichment_target = _build_enrichment_target(federal_target, state=None)

    assert federal_enrichment_target.person_id == federal_target.person_id
    assert federal_enrichment_target.state_code is None
    assert federal_enrichment_target.roster_bio_url == "https://bioguide.congress.gov/search/bio/F000197"
    assert federal_enrichment_target.bioguide_id == " f000197 "


def test_run_nc_enrichment_uses_strategy_chain_and_persists_portrait_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()
    selected_target = ScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_nc_scope_targets",
        lambda _conn, *, state, cycle: ScopeSelectionResult(
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

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.insert_person_portrait", _capture_insert_person_portrait
    )

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

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance", _capture_field_provenance
    )
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
        lambda _conn, source_record: (
            bio_source_record_id
            if source_record.source_url == "https://www.ncleg.gov/Members/Biography/H/149"
            else uuid4()
        ),
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
                rights_status="public_domain",
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
    assert inserted_portraits[0].rights_status == "public_domain"
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
    selected_target = ScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")
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
        lambda _conn, entity_type, entity_id, field_name, field_value, observed_source_record_id: (
            provenance_calls.append((entity_type, entity_id, field_name, field_value, observed_source_record_id))
            or uuid4()
        ),
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
    selected_target = ScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")
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
        lambda _conn, entity_type, entity_id, field_name, field_value, observed_source_record_id: (
            provenance_calls.append((entity_type, entity_id, field_name, field_value, observed_source_record_id))
            or uuid4()
        ),
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


@pytest.mark.parametrize(
    ("bio_license", "expected_bio_text"),
    [
        ("public_domain", "Licensed biography text."),
        ("licensed", "Licensed biography text."),
        ("restricted", None),
        ("unknown", None),
    ],
)
def test_apply_enrichment_only_writes_bio_text_for_reusable_licenses(
    monkeypatch: pytest.MonkeyPatch,
    bio_license: str,
    expected_bio_text: str | None,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()
    selected_target = ScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")
    person = Person(id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr("core.people.enrichment.orchestrator.db.select_person", lambda _conn, _person_id: person)

    bio_updates: list[tuple[str | None, str | None, str | None]] = []

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
        bio_updates.append((bio_text, bio_source_url, bio_license))
        return tuple()

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        _capture_bio_update,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
    )

    _apply_enrichment_for_targets(
        object(),
        strategy_chain=_FakeChain(
            lambda _target: CandidateEnrichmentRecord(
                biography="Licensed biography text.",
                bio_source_url="https://www.ncleg.gov/Members/Biography/H/149",
                bio_license=bio_license,
            )
        ),
        scope_targets=[selected_target],
        source_record_id=source_record_id,
        state="NC",
        summary={"processed": 0, "portrait_writes": 0, "bio_updates": 0, "field_provenance_writes": 0},
        dry_run=False,
    )

    assert bio_updates == [(expected_bio_text, "https://www.ncleg.gov/Members/Biography/H/149", bio_license)]


def test_apply_enrichment_keeps_bio_metadata_and_uses_bio_source_record_provenance_when_bio_text_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()
    run_data_source_id = uuid4()
    bio_source_record_id = uuid4()
    selected_target = ScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")
    person = Person(id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr("core.people.enrichment.orchestrator.db.select_person", lambda _conn, _person_id: person)

    captured_updates: list[tuple[str | None, str | None, str | None]] = []

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
        captured_updates.append((bio_text, bio_source_url, bio_license))
        return ("bio_source_url", "bio_license")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        _capture_bio_update,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_source_record",
        lambda _conn, record_id: SourceRecord(
            id=record_id,
            data_source_id=run_data_source_id,
            source_record_key="people-enrichment:nc:NC:2026",
            source_url=None,
            raw_fields={"scope": "nc", "state": "NC"},
            pull_date=datetime(2026, 4, 27, 21, 0, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
    )
    source_record_writes: list[SourceRecord] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.try_insert_source_record",
        lambda _conn, source_record: source_record_writes.append(source_record) or bio_source_record_id,
    )
    provenance_calls: list[tuple[str, UUID]] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda _conn, _entity_type, _entity_id, field_name, _field_value, observed_source_record_id: (
            provenance_calls.append((field_name, observed_source_record_id)) or uuid4()
        ),
    )

    summary = _apply_enrichment_for_targets(
        object(),
        strategy_chain=_FakeChain(
            lambda _target: CandidateEnrichmentRecord(
                biography="Restricted biography text.",
                bio_source_url="https://www.ncleg.gov/Members/Biography/H/149",
                bio_license="restricted",
            )
        ),
        scope_targets=[selected_target],
        source_record_id=source_record_id,
        state="NC",
        summary={"processed": 0, "portrait_writes": 0, "bio_updates": 0, "field_provenance_writes": 0},
        dry_run=False,
    )

    assert captured_updates == [(None, "https://www.ncleg.gov/Members/Biography/H/149", "restricted")]
    assert len(source_record_writes) == 1
    assert source_record_writes[0].data_source_id == run_data_source_id
    assert source_record_writes[0].source_record_key == "https://www.ncleg.gov/Members/Biography/H/149"
    assert source_record_writes[0].source_url == "https://www.ncleg.gov/Members/Biography/H/149"
    assert source_record_writes[0].raw_fields["field"] == "bio_license"
    assert provenance_calls == [("bio_license", bio_source_record_id)]
    assert summary["bio_updates"] == 2
    assert summary["field_provenance_writes"] == 1


def test_run_cf_candidate_enrichment_skips_portrait_insert_for_takedown_requested_source_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()
    selected_target = ScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: ScopeSelectionResult(
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
        lambda _conn, *, person_id, source_image_url: (
            person_id == selected_target.person_id and source_image_url == "https://images.example.org/morgan.jpg"
        ),
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
    selected_target = ScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: ScopeSelectionResult(
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
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.insert_person_portrait", lambda *_args, **_kwargs: uuid4()
    )
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
        lambda _conn, _entity_type, _entity_id, _field_name, _field_value, observed_source_record_id: (
            provenance_calls.append(observed_source_record_id) or uuid4()
        ),
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
        ScopeTarget(person_id=person_id, canonical_name="Morgan Candidate"),
        ScopeTarget(person_id=uuid4(), canonical_name="Taylor Candidate"),
    ]
    captured_source_records: list[SourceRecord] = []

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: ScopeSelectionResult(
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
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.insert_person_portrait", lambda *_args, **_kwargs: uuid4()
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.ensure_data_source",
        lambda _conn, _data_source: data_source_id,
        raising=False,
    )

    def _capture_source_record(_conn: object, source_record: SourceRecord) -> UUID:
        captured_source_records.append(source_record)
        return source_record_id

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.try_insert_source_record", _capture_source_record
    )

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
    selected_target = ScopeTarget(person_id=person_id, canonical_name="Morgan Candidate")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_cf_candidate_scope_targets",
        lambda _conn, *, state: ScopeSelectionResult(
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
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.insert_person_portrait", lambda *_args, **_kwargs: uuid4()
    )
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
        lambda _conn, *, data_source_id, source_record_key: (
            selector_calls.append((data_source_id, source_record_key))
            or SourceRecord(
                id=active_source_record_id,
                data_source_id=data_source_id,
                source_record_key=source_record_key,
                source_url=None,
                raw_fields={"scope": "cf-candidate", "state": "NC"},
                pull_date=datetime(2026, 4, 27, 21, 0, tzinfo=timezone.utc),
            )
        ),
    )

    provenance_calls: list[UUID] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda _conn, _entity_type, _entity_id, _field_name, _field_value, observed_source_record_id: (
            provenance_calls.append(observed_source_record_id) or uuid4()
        ),
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
        lambda _conn, *, state: ScopeSelectionResult(
            targets=[ScopeTarget(person_id=uuid4(), canonical_name="Dry Run Candidate")],
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


def test_run_federal_enrichment_dry_run_uses_federal_scope_without_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_federal_scope_targets",
        lambda _conn: ScopeSelectionResult(
            targets=[ScopeTarget(person_id=uuid4(), canonical_name="Dry Run Federal")],
            warnings=[],
            candidacy_count=0,
            officeholder_count=1,
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

    summary = run_federal_enrichment(
        object(),
        chain=_FakeChain(lambda _target: CandidateEnrichmentRecord(occupation="Teacher")),
        dry_run=True,
    )

    assert summary["scope"] == "federal"
    assert summary["jurisdiction"] == "federal/congress"
    assert summary["selected"] == 1
    assert summary["processed"] == 0
    assert summary["source_record_id"] is None
    assert summary["data_source_id"] is None


def test_run_federal_enrichment_degrades_when_wikipedia_title_prefetch_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.people.enrichment.models import EnrichmentAttempt

    person_id = uuid4()
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_federal_scope_targets",
        lambda _conn: ScopeSelectionResult(
            targets=[
                ScopeTarget(
                    person_id=person_id,
                    canonical_name="Has Wikidata Id",
                    wikidata_entity_id="Q12345",
                )
            ],
            warnings=[],
            candidacy_count=0,
            officeholder_count=1,
        ),
    )

    class _NoOpStrategy:
        source_name = "noop"

        def fetch(
            self,
            target: CandidateEnrichmentTarget,
            missing_fields: tuple[str, ...],
        ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

    def _fake_federal_builder(*, conn: object | None = None) -> StrategyChain:
        return StrategyChain((_NoOpStrategy(),))

    monkeypatch.setattr(StrategyChain, "federal", staticmethod(_fake_federal_builder), raising=False)

    def _raising_batch(_qids, **_kwargs):
        raise RuntimeError("upstream wikidata unreachable")

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.batch_fetch_wikipedia_titles",
        _raising_batch,
    )

    summary = run_federal_enrichment(object(), dry_run=True)

    assert summary["scope"] == "federal"
    assert summary["selected"] == 1
    prefetch_warnings = [
        warning
        for warning in summary["warnings"]
        if isinstance(warning, str) and warning.startswith("wikipedia_title_prefetch_failed")
    ]
    assert prefetch_warnings, summary["warnings"]
    assert "RuntimeError" in prefetch_warnings[0]
    assert "upstream wikidata unreachable" in prefetch_warnings[0]


def test_run_federal_enrichment_prefetches_large_wikipedia_title_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.people.enrichment.models import EnrichmentAttempt

    targets = [
        ScopeTarget(
            person_id=uuid4(),
            canonical_name=f"Federal Member {index}",
            wikidata_entity_id=f"Q{100000 + index}",
        )
        for index in range(101)
    ]
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_federal_scope_targets",
        lambda _conn: ScopeSelectionResult(
            targets=targets,
            warnings=[],
            candidacy_count=0,
            officeholder_count=len(targets),
        ),
    )

    class _NoOpStrategy:
        source_name = "noop"

        def fetch(
            self,
            target: CandidateEnrichmentTarget,
            missing_fields: tuple[str, ...],
        ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

    def _fake_federal_builder(*, conn: object | None = None) -> StrategyChain:
        return StrategyChain((_NoOpStrategy(),))

    captured_qids: list[str] = []
    captured_titles: list[str] = []

    def _capturing_batch(qids, **_kwargs):
        captured_qids.extend(qids)
        return {qid: f"Title_{qid}" for qid in qids}

    def _capturing_summary_batch(titles, **_kwargs):
        captured_titles.extend(titles)
        return {
            title: {
                "extract": f"Biography for {title}.",
                "content_urls": {"desktop": {"page": f"https://en.wikipedia.org/wiki/{title}"}},
            }
            for title in titles
        }

    monkeypatch.setattr(StrategyChain, "federal", staticmethod(_fake_federal_builder), raising=False)
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.batch_fetch_wikipedia_titles",
        _capturing_batch,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.batch_fetch_wikipedia_summaries",
        _capturing_summary_batch,
    )

    summary = run_federal_enrichment(object(), dry_run=True)

    assert summary["selected"] == 101
    assert captured_qids == [f"Q{100000 + index}" for index in range(101)]
    assert captured_titles == [f"Title_Q{100000 + index}" for index in range(101)]
    assert summary["warnings"] == []


def test_run_federal_enrichment_falls_back_when_wikipedia_summary_prefetch_is_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.people.enrichment import strategy_wikipedia_bio as wikipedia_bio_module

    person_id = uuid4()
    captured_bio_texts: list[str | None] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_federal_scope_targets",
        lambda _conn: ScopeSelectionResult(
            targets=[
                ScopeTarget(
                    person_id=person_id,
                    canonical_name="Federal Partial Prefetch",
                    wikidata_entity_id="Q12345",
                )
            ],
            warnings=[],
            candidacy_count=0,
            officeholder_count=1,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_person",
        lambda _conn, _person_id: Person(id=person_id, canonical_name="Federal Partial Prefetch"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.strategy_official_roster_cache.db.select_active_roster_portrait_for_person",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **kwargs: captured_bio_texts.append(kwargs["bio_text"]) or ("bio_text",),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_source_record",
        lambda _conn, _source_record_id: SourceRecord(
            id=uuid4(),
            data_source_id=uuid4(),
            source_record_key="source",
            source_url=None,
            raw_fields={},
            pull_date=datetime.now(timezone.utc),
            record_hash="hash",
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.try_insert_source_record",
        lambda _conn, _source_record: uuid4(),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda *_args, **_kwargs: uuid4(),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.batch_fetch_wikipedia_titles",
        lambda _qids: {"Q12345": "Federal Bio"},
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.batch_fetch_wikipedia_summaries",
        lambda _titles: {},
    )
    monkeypatch.setattr(
        wikipedia_bio_module,
        "_fetch_wikipedia_summary",
        lambda _title, **_kwargs: {
            "extract": "Federal biography from per-target fallback.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Federal_Bio"}},
        },
    )

    summary = run_federal_enrichment(object(), source_record_id=uuid4())

    assert summary["processed"] == 1
    assert captured_bio_texts == ["Federal biography from per-target fallback."]


def test_run_federal_enrichment_does_not_call_wikidata_after_wikipedia_bio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.people.enrichment.models import EnrichmentAttempt
    from core.people.enrichment.strategy_bioguide_portrait import BioguidePortraitStrategy
    from core.people.enrichment.strategy_official_bio import OfficialBioStrategy
    from core.people.enrichment.strategy_official_roster_cache import OfficialRosterCacheStrategy
    from core.people.enrichment.strategy_wikidata import WikidataEnrichmentStrategy

    person_id = uuid4()
    captured_bio_texts: list[str | None] = []
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_federal_scope_targets",
        lambda _conn: ScopeSelectionResult(
            targets=[
                ScopeTarget(
                    person_id=person_id,
                    canonical_name="Federal Wikipedia Bio",
                    wikidata_entity_id="Q12345",
                    bioguide_id="F000001",
                )
            ],
            warnings=[],
            candidacy_count=0,
            officeholder_count=1,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_person",
        lambda _conn, _person_id: Person(id=person_id, canonical_name="Federal Wikipedia Bio"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **kwargs: captured_bio_texts.append(kwargs["bio_text"]) or ("bio_text",),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda *_args, **_kwargs: uuid4(),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_source_record",
        lambda _conn, _source_record_id: SourceRecord(
            id=uuid4(),
            data_source_id=uuid4(),
            source_record_key="source",
            source_url=None,
            raw_fields={},
            pull_date=datetime.now(timezone.utc),
            record_hash="hash",
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.try_insert_source_record",
        lambda _conn, _source_record: uuid4(),
    )
    monkeypatch.setattr(
        OfficialRosterCacheStrategy,
        "fetch",
        lambda self, target, missing_fields: (
            CandidateEnrichmentRecord(),
            EnrichmentAttempt.no_data(source=self.source_name, requested_fields=missing_fields),
        ),
    )
    monkeypatch.setattr(
        OfficialBioStrategy,
        "fetch",
        lambda self, target, missing_fields: (
            CandidateEnrichmentRecord(),
            EnrichmentAttempt.no_data(source=self.source_name, requested_fields=missing_fields),
        ),
    )
    monkeypatch.setattr(
        BioguidePortraitStrategy,
        "fetch",
        lambda self, target, missing_fields: (
            CandidateEnrichmentRecord(),
            EnrichmentAttempt.no_data(source=self.source_name, requested_fields=missing_fields),
        ),
    )
    monkeypatch.setattr(
        WikidataEnrichmentStrategy,
        "fetch",
        lambda *_args, **_kwargs: pytest.fail("federal launch enrichment must not call per-target Wikidata SPARQL"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.batch_fetch_wikipedia_titles",
        lambda _qids: {"Q12345": "Federal Bio"},
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.batch_fetch_wikipedia_summaries",
        lambda _titles: {
            "Federal Bio": {
                "extract": "Federal biography from Wikipedia.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Federal_Bio"}},
            }
        },
    )

    summary = run_federal_enrichment(object(), source_record_id=uuid4())

    assert summary["processed"] == 1
    assert captured_bio_texts == ["Federal biography from Wikipedia."]


def test_run_federal_enrichment_uses_federal_chain_builder_unless_chain_is_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.people.enrichment.models import EnrichmentAttempt
    from core.people.enrichment.strategy_official_bio import OfficialBioStrategy

    conn_marker = object()
    person_id = uuid4()
    source_record_id = uuid4()
    federal_builder_conn: list[object] = []
    official_bio_targets: list[CandidateEnrichmentTarget] = []
    captured_bio_texts: list[str | None] = []

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_federal_scope_targets",
        lambda _conn: ScopeSelectionResult(
            targets=[
                ScopeTarget(
                    person_id=person_id,
                    canonical_name="Dry Run Federal",
                    bioguide_id="F000001",
                )
            ],
            warnings=[],
            candidacy_count=0,
            officeholder_count=1,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_person",
        lambda _conn, _person_id: Person(id=person_id, canonical_name="Dry Run Federal"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **kwargs: captured_bio_texts.append(kwargs["bio_text"]) or tuple(),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
        raising=False,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda *_args, **_kwargs: uuid4(),
    )

    class _FederalBuilderStrategy:
        source_name = "federal-builder"

        def fetch(
            self,
            target: CandidateEnrichmentTarget,
            missing_fields: tuple[str, ...],
        ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
            return CandidateEnrichmentRecord(), EnrichmentAttempt.no_data(
                source=self.source_name,
                requested_fields=missing_fields,
            )

    def _fake_federal_builder(*, conn: object | None = None) -> StrategyChain:
        assert conn is not None
        federal_builder_conn.append(conn)
        return StrategyChain((_FederalBuilderStrategy(), OfficialBioStrategy()))

    def _fake_official_bio_fetch(
        self,
        target: CandidateEnrichmentTarget,
        missing_fields: tuple[str, ...],
    ) -> tuple[CandidateEnrichmentRecord, EnrichmentAttempt]:
        official_bio_targets.append(target)
        assert target.roster_bio_url == "https://bioguide.congress.gov/search/bio/F000001"
        return (
            CandidateEnrichmentRecord(
                biography="Federal biography text.",
                bio_source_url=target.roster_bio_url,
                bio_license="public_domain",
            ),
            EnrichmentAttempt.success(
                source=self.source_name,
                requested_fields=missing_fields,
                contributed_fields=("biography",),
            ),
        )

    monkeypatch.setattr(StrategyChain, "federal", staticmethod(_fake_federal_builder), raising=False)
    monkeypatch.setattr(OfficialBioStrategy, "fetch", _fake_official_bio_fetch)

    run_federal_enrichment(conn_marker, source_record_id=source_record_id)
    injected_chain = _FakeChain(lambda _target: CandidateEnrichmentRecord(occupation="Injected"))
    run_federal_enrichment(conn_marker, chain=injected_chain, source_record_id=source_record_id)

    assert federal_builder_conn == [conn_marker]
    assert [target.person_id for target in official_bio_targets] == [person_id]
    assert captured_bio_texts == ["Federal biography text.", None]
    assert len(injected_chain.calls) == 1


def test_run_federal_enrichment_does_not_query_or_apply_sboe_candidate_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()
    sboe_queries: list[CandidateEnrichmentTarget] = []
    bio_update_occupations: list[str | None] = []

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_federal_scope_targets",
        lambda _conn: ScopeSelectionResult(
            targets=[
                ScopeTarget(
                    person_id=person_id,
                    canonical_name="Federal Same Name",
                    bioguide_id="F000001",
                )
            ],
            warnings=[],
            candidacy_count=0,
            officeholder_count=1,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_person",
        lambda _conn, _person_id: Person(id=person_id, canonical_name="Federal Same Name"),
    )

    def _capture_bio_update(_conn: object, **kwargs: object) -> tuple[str, ...]:
        occupation = kwargs["occupation"]
        assert occupation is None or isinstance(occupation, str)
        bio_update_occupations.append(occupation)
        return ("occupation",) if occupation else ()

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        _capture_bio_update,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.person_has_takedown_requested_portrait_source_image",
        lambda _conn, *, person_id, source_image_url: False,
        raising=False,
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda *_args, **_kwargs: uuid4(),
    )

    def _sboe_payload(target: CandidateEnrichmentTarget) -> dict[str, object]:
        sboe_queries.append(target)
        return {"occupation": "NC Candidate"}

    summary = run_federal_enrichment(
        object(),
        chain=StrategyChain((SboeEnrichmentStrategy(fetcher=_sboe_payload),)),
        source_record_id=source_record_id,
    )

    assert sboe_queries == []
    assert bio_update_occupations == [None]
    assert summary["bio_updates"] == 0


def test_run_federal_enrichment_summary_exposes_refresh_loader_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    source_record_id = uuid4()

    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.select_federal_scope_targets",
        lambda _conn: ScopeSelectionResult(
            targets=[ScopeTarget(person_id=person_id, canonical_name="Federal Counted")],
            warnings=[],
            candidacy_count=0,
            officeholder_count=1,
        ),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.select_person",
        lambda _conn, _person_id: Person(id=person_id, canonical_name="Federal Counted"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db.update_person_bio_fields_if_missing",
        lambda _conn, **_kwargs: ("occupation", "education"),
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.db_ingest.insert_field_provenance",
        lambda *_args, **_kwargs: uuid4(),
    )

    summary = run_federal_enrichment(
        object(),
        chain=_FakeChain(lambda _target: CandidateEnrichmentRecord(occupation="Teacher", education="BA")),
        source_record_id=source_record_id,
    )

    assert summary["inserted"] == 4
    assert summary["skipped"] == 0
    assert summary["quarantined"] == 0
    assert summary["superseded"] == 0
    assert summary["errors"] == 0


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
        lambda _conn, *, state, cycle: ScopeSelectionResult(
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


def test_main_dispatches_federal_scope_to_federal_runner(
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
    federal_calls: list[dict[str, object]] = []

    monkeypatch.setattr("core.people.enrichment.orchestrator.db.get_connection", lambda: connection)
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.run_nc_enrichment",
        lambda *args, **kwargs: nc_calls.append(kwargs) or {"processed": 0},
    )
    monkeypatch.setattr(
        "core.people.enrichment.orchestrator.run_federal_enrichment",
        lambda *args, **kwargs: federal_calls.append(kwargs) or {"processed": 0},
    )

    exit_code = main(
        [
            "--scope",
            "federal",
            "--limit",
            "5",
            "--dry-run",
            "--source-record-id",
            str(source_record_id),
        ]
    )

    assert exit_code == 0
    assert len(federal_calls) == 1
    assert federal_calls[0]["limit"] == 5
    assert federal_calls[0]["dry_run"] is True
    assert federal_calls[0]["source_record_id"] == source_record_id
    assert nc_calls == []
    assert connection.commit_calls == 0
    assert connection.close_calls == 1
