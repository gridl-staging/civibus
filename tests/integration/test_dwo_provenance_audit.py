from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

import psycopg
import pytest

from api.queries._common import fetch_campaign_finance_provenance, fetch_entity_provenance
from core.db import insert_data_source, insert_entity_source, insert_organization, insert_person, insert_source_record
from core.types.python.models import DataSource, Organization, Person, SourceRecord
from domains.civics.ingest import upsert_candidacy, upsert_contest, upsert_office
from domains.civics.types.models import Candidacy, Contest, Office

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class ProvenanceSample:
    entity_type: str
    entity_id: UUID
    table_name: str
    fetch_mode: Literal["campaign_finance", "entity"]
    row_source_record_id: UUID | None = None
    canonical_entity_type: str | None = None
    canonical_entity_id: UUID | None = None


@dataclass(frozen=True)
class SurfaceSeedResult:
    samples: list[ProvenanceSample]
    expected_failures: list[str]


@dataclass(frozen=True)
class CandidateLinkedSeed:
    person_id: UUID
    candidate_id: UUID
    stored_source_record_id: UUID
    source_record_key: str
    source_url: str | None
    fec_candidate_id: str
    candidate_name: str
    last_name: str
    sample_row_source_record_id: UUID | None = None


@dataclass(frozen=True)
class CandidateUnlinkedSeed:
    person_id: UUID
    candidate_id: UUID
    fec_candidate_id: str
    candidate_name: str
    last_name: str


def _seed_data_source(conn: psycopg.Connection, *, suffix: str) -> UUID:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction="state/NC",
        name=f"dwo_provenance_audit_{suffix}",
        source_url=f"https://example.org/source/{suffix}",
    )
    insert_data_source(conn, data_source)
    return data_source.id


def _seed_source_record(
    conn: psycopg.Connection,
    *,
    source_record_id: UUID,
    data_source_id: UUID,
    source_record_key: str,
    source_url: str | None,
) -> UUID:
    insert_source_record(
        conn,
        SourceRecord(
            id=source_record_id,
            data_source_id=data_source_id,
            source_record_key=source_record_key,
            source_url=source_url,
            raw_fields={"fixture": "dwo_provenance_audit"},
            pull_date=datetime(2026, 4, 30, 16, 0, tzinfo=timezone.utc),
        ),
    )
    return source_record_id


def _seed_candidate_row(
    conn: psycopg.Connection,
    *,
    candidate_id: UUID,
    person_id: UUID,
    source_record_id: UUID | None,
    fec_candidate_id: str,
    candidate_name: str,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.candidate (id, fec_candidate_id, name, person_id, office, state, source_record_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (candidate_id, fec_candidate_id, candidate_name, person_id, "H", "NC", source_record_id),
        )


def _seed_committee_row(
    conn: psycopg.Connection,
    *,
    committee_id: UUID,
    organization_id: UUID,
    source_record_id: UUID,
    fec_committee_id: str,
    committee_name: str,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.committee (id, fec_committee_id, name, organization_id, source_record_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (committee_id, fec_committee_id, committee_name, organization_id, source_record_id),
        )


def _load_provenance_rows(conn: psycopg.Connection, sample: ProvenanceSample) -> list[dict[str, Any]]:
    if sample.fetch_mode == "campaign_finance":
        assert sample.canonical_entity_type is not None
        return fetch_campaign_finance_provenance(
            conn,
            row_source_record_id=sample.row_source_record_id,
            canonical_entity_type=sample.canonical_entity_type,
            canonical_entity_id=sample.canonical_entity_id,
        )

    return fetch_entity_provenance(conn, sample.entity_type, sample.entity_id)


def _collect_audit_failures(conn: psycopg.Connection, samples: list[ProvenanceSample]) -> list[str]:
    failures: list[str] = []
    for sample in samples:
        if (
            sample.fetch_mode == "campaign_finance"
            and sample.row_source_record_id is not None
            and not _row_source_record_resolves(conn, sample)
        ):
            failures.append(
                f"{sample.entity_type}:{sample.entity_id} [{sample.table_name}] "
                f"dangling row source_record_id={sample.row_source_record_id}"
            )

        provenance_rows = _load_provenance_rows(conn, sample)
        if not provenance_rows:
            failures.append(f"{sample.entity_type}:{sample.entity_id} [{sample.table_name}] missing provenance rows")
            continue

        for provenance_row in provenance_rows:
            record_url = provenance_row["record_url"]
            if isinstance(record_url, str):
                record_url = record_url.strip()
            if record_url:
                continue
            failures.append(
                (
                    f"{sample.entity_type}:{sample.entity_id} [{sample.table_name}] "
                    f"missing source_url for source_record_key={provenance_row['source_record_key']}"
                )
            )
    return failures


def _row_source_record_resolves(conn: psycopg.Connection, sample: ProvenanceSample) -> bool:
    assert sample.row_source_record_id is not None
    row_only_rows = fetch_campaign_finance_provenance(
        conn,
        row_source_record_id=sample.row_source_record_id,
        canonical_entity_type=sample.canonical_entity_type or "",
        canonical_entity_id=None,
    )
    return bool(row_only_rows)


def _seed_linked_candidate_sample(
    conn: psycopg.Connection,
    data_source_id: UUID,
    seed: CandidateLinkedSeed,
) -> ProvenanceSample:
    person = Person(
        id=seed.person_id,
        canonical_name=seed.candidate_name,
        first_name="DWO",
        last_name=seed.last_name,
    )
    insert_person(conn, person)
    _seed_source_record(
        conn,
        source_record_id=seed.stored_source_record_id,
        data_source_id=data_source_id,
        source_record_key=seed.source_record_key,
        source_url=seed.source_url,
    )
    _seed_candidate_row(
        conn,
        candidate_id=seed.candidate_id,
        person_id=seed.person_id,
        source_record_id=seed.stored_source_record_id,
        fec_candidate_id=seed.fec_candidate_id,
        candidate_name=seed.candidate_name,
    )
    insert_entity_source(conn, "person", seed.person_id, seed.stored_source_record_id, "candidate")
    return ProvenanceSample(
        entity_type="candidate",
        entity_id=seed.candidate_id,
        table_name="cf.candidate",
        fetch_mode="campaign_finance",
        row_source_record_id=seed.sample_row_source_record_id or seed.stored_source_record_id,
        canonical_entity_type="person",
        canonical_entity_id=seed.person_id,
    )


def _seed_unlinked_candidate_sample(conn: psycopg.Connection, seed: CandidateUnlinkedSeed) -> ProvenanceSample:
    person = Person(
        id=seed.person_id,
        canonical_name=seed.candidate_name,
        first_name="DWO",
        last_name=seed.last_name,
    )
    insert_person(conn, person)
    _seed_candidate_row(
        conn,
        candidate_id=seed.candidate_id,
        person_id=seed.person_id,
        source_record_id=None,
        fec_candidate_id=seed.fec_candidate_id,
        candidate_name=seed.candidate_name,
    )
    return ProvenanceSample(
        entity_type="candidate",
        entity_id=seed.candidate_id,
        table_name="cf.candidate",
        fetch_mode="campaign_finance",
        row_source_record_id=None,
        canonical_entity_type="person",
        canonical_entity_id=seed.person_id,
    )


def _seed_candidate_surface(conn: psycopg.Connection, data_source_id: UUID) -> SurfaceSeedResult:
    candidate_good = _seed_linked_candidate_sample(
        conn,
        data_source_id,
        CandidateLinkedSeed(
            person_id=UUID("11111111-1111-1111-1111-111111111101"),
            candidate_id=UUID("31111111-1111-1111-1111-111111111101"),
            stored_source_record_id=UUID("21111111-1111-1111-1111-111111111101"),
            source_record_key="candidate-good",
            source_url="https://example.org/record/candidate-good",
            fec_candidate_id="H0NC10001",
            candidate_name="DWO Candidate Good",
            last_name="CandidateGood",
        ),
    )
    candidate_bad = _seed_linked_candidate_sample(
        conn,
        data_source_id,
        CandidateLinkedSeed(
            person_id=UUID("11111111-1111-1111-1111-111111111102"),
            candidate_id=UUID("31111111-1111-1111-1111-111111111102"),
            stored_source_record_id=UUID("21111111-1111-1111-1111-111111111102"),
            source_record_key="candidate-bad",
            source_url="",
            fec_candidate_id="H0NC10002",
            candidate_name="DWO Candidate Broken",
            last_name="CandidateBroken",
        ),
    )
    candidate_dangling = _seed_linked_candidate_sample(
        conn,
        data_source_id,
        CandidateLinkedSeed(
            person_id=UUID("11111111-1111-1111-1111-111111111104"),
            candidate_id=UUID("31111111-1111-1111-1111-111111111104"),
            stored_source_record_id=UUID("21111111-1111-1111-1111-111111111104"),
            sample_row_source_record_id=UUID("21111111-1111-1111-1111-111111111105"),
            source_record_key="candidate-dangling-fallback",
            source_url="https://example.org/record/candidate-dangling-fallback",
            fec_candidate_id="H0NC10004",
            candidate_name="DWO Candidate Dangling Row Source",
            last_name="CandidateDanglingRowSource",
        ),
    )
    candidate_unresolved = _seed_unlinked_candidate_sample(
        conn,
        CandidateUnlinkedSeed(
            person_id=UUID("11111111-1111-1111-1111-111111111103"),
            candidate_id=UUID("31111111-1111-1111-1111-111111111103"),
            fec_candidate_id="H0NC10003",
            candidate_name="DWO Candidate Missing Provenance",
            last_name="CandidateMissingProvenance",
        ),
    )

    return SurfaceSeedResult(
        samples=[candidate_good, candidate_bad, candidate_dangling, candidate_unresolved],
        expected_failures=[
            f"candidate:{candidate_bad.entity_id} [cf.candidate] missing source_url for source_record_key=candidate-bad",
            (
                f"candidate:{candidate_dangling.entity_id} [cf.candidate] "
                f"dangling row source_record_id={candidate_dangling.row_source_record_id}"
            ),
            f"candidate:{candidate_unresolved.entity_id} [cf.candidate] missing provenance rows",
        ],
    )


def _seed_committee_surface(conn: psycopg.Connection, data_source_id: UUID) -> SurfaceSeedResult:
    organization_good = Organization(
        id=UUID("12222222-2222-2222-2222-222222222201"),
        canonical_name="DWO Committee Good Org",
    )
    insert_organization(conn, organization_good)
    committee_good_source_record_id = _seed_source_record(
        conn,
        source_record_id=UUID("22222222-2222-2222-2222-222222222201"),
        data_source_id=data_source_id,
        source_record_key="committee-good",
        source_url="https://example.org/record/committee-good",
    )
    committee_good_id = UUID("32222222-2222-2222-2222-222222222201")
    _seed_committee_row(
        conn,
        committee_id=committee_good_id,
        organization_id=organization_good.id,
        source_record_id=committee_good_source_record_id,
        fec_committee_id="C10000001",
        committee_name="DWO Committee Good",
    )
    insert_entity_source(conn, "organization", organization_good.id, committee_good_source_record_id, "committee")

    organization_bad = Organization(
        id=UUID("12222222-2222-2222-2222-222222222202"),
        canonical_name="DWO Committee Broken Org",
    )
    insert_organization(conn, organization_bad)
    committee_bad_source_record_id = _seed_source_record(
        conn,
        source_record_id=UUID("22222222-2222-2222-2222-222222222202"),
        data_source_id=data_source_id,
        source_record_key="committee-bad",
        source_url="",
    )
    committee_bad_id = UUID("32222222-2222-2222-2222-222222222202")
    _seed_committee_row(
        conn,
        committee_id=committee_bad_id,
        organization_id=organization_bad.id,
        source_record_id=committee_bad_source_record_id,
        fec_committee_id="C10000002",
        committee_name="DWO Committee Broken",
    )
    insert_entity_source(conn, "organization", organization_bad.id, committee_bad_source_record_id, "committee")

    return SurfaceSeedResult(
        samples=[
            ProvenanceSample(
                entity_type="committee",
                entity_id=committee_good_id,
                table_name="cf.committee",
                fetch_mode="campaign_finance",
                row_source_record_id=committee_good_source_record_id,
                canonical_entity_type="organization",
                canonical_entity_id=organization_good.id,
            ),
            ProvenanceSample(
                entity_type="committee",
                entity_id=committee_bad_id,
                table_name="cf.committee",
                fetch_mode="campaign_finance",
                row_source_record_id=committee_bad_source_record_id,
                canonical_entity_type="organization",
                canonical_entity_id=organization_bad.id,
            ),
        ],
        expected_failures=[
            f"committee:{committee_bad_id} [cf.committee] missing source_url for source_record_key=committee-bad"
        ],
    )


def _seed_contest_surface(conn: psycopg.Connection, data_source_id: UUID) -> SurfaceSeedResult:
    office_good_id, office_bad_id = _seed_office_rows(conn, data_source_id)
    contest_good_id, contest_bad_id = _seed_contest_rows(conn, data_source_id, office_good_id, office_bad_id)
    candidacy_good_id, candidacy_bad_id = _seed_candidacy_rows(conn, data_source_id, contest_good_id, contest_bad_id)

    return SurfaceSeedResult(
        samples=[
            ProvenanceSample(entity_type="contest", entity_id=contest_good_id, table_name="civic.contest", fetch_mode="entity"),
            ProvenanceSample(entity_type="contest", entity_id=contest_bad_id, table_name="civic.contest", fetch_mode="entity"),
            ProvenanceSample(
                entity_type="candidacy", entity_id=candidacy_good_id, table_name="civic.candidacy", fetch_mode="entity"
            ),
            ProvenanceSample(
                entity_type="candidacy", entity_id=candidacy_bad_id, table_name="civic.candidacy", fetch_mode="entity"
            ),
            ProvenanceSample(entity_type="office", entity_id=office_good_id, table_name="civic.office", fetch_mode="entity"),
            ProvenanceSample(entity_type="office", entity_id=office_bad_id, table_name="civic.office", fetch_mode="entity"),
        ],
        expected_failures=[
            f"contest:{contest_bad_id} [civic.contest] missing source_url for source_record_key=contest-bad",
            f"candidacy:{candidacy_bad_id} [civic.candidacy] missing source_url for source_record_key=candidacy-bad",
            f"office:{office_bad_id} [civic.office] missing source_url for source_record_key=office-bad",
        ],
    )


def _seed_office_rows(conn: psycopg.Connection, data_source_id: UUID) -> tuple[UUID, UUID]:
    office_good_source_record_id = _seed_source_record(
        conn,
        source_record_id=UUID("23333333-3333-3333-3333-333333333301"),
        data_source_id=data_source_id,
        source_record_key="office-good",
        source_url="https://example.org/record/office-good",
    )
    office_bad_source_record_id = _seed_source_record(
        conn,
        source_record_id=UUID("23333333-3333-3333-3333-333333333302"),
        data_source_id=data_source_id,
        source_record_key="office-bad",
        source_url="",
    )
    office_good_id = upsert_office(
        conn,
        Office(
            id=UUID("33333333-3333-3333-3333-333333333301"),
            name="DWO Office Good",
            office_level="state",
            title="Representative",
            state="NC",
            source_record_id=office_good_source_record_id,
        ),
    )
    office_bad_id = upsert_office(
        conn,
        Office(
            id=UUID("33333333-3333-3333-3333-333333333302"),
            name="DWO Office Broken",
            office_level="state",
            title="Representative",
            state="NC",
            source_record_id=office_bad_source_record_id,
        ),
    )
    return office_good_id, office_bad_id


def _seed_contest_rows(
    conn: psycopg.Connection,
    data_source_id: UUID,
    office_good_id: UUID,
    office_bad_id: UUID,
) -> tuple[UUID, UUID]:

    contest_good_source_record_id = _seed_source_record(
        conn,
        source_record_id=UUID("23333333-3333-3333-3333-333333333311"),
        data_source_id=data_source_id,
        source_record_key="contest-good",
        source_url="https://example.org/record/contest-good",
    )
    contest_bad_source_record_id = _seed_source_record(
        conn,
        source_record_id=UUID("23333333-3333-3333-3333-333333333312"),
        data_source_id=data_source_id,
        source_record_key="contest-bad",
        source_url="",
    )
    contest_good_id = upsert_contest(
        conn,
        Contest(
            id=UUID("33333333-3333-3333-3333-333333333311"),
            name="DWO Contest Good",
            election_date=date(2026, 11, 3),
            election_type="general",
            office_id=office_good_id,
            source_record_id=contest_good_source_record_id,
        ),
    )
    contest_bad_id = upsert_contest(
        conn,
        Contest(
            id=UUID("33333333-3333-3333-3333-333333333312"),
            name="DWO Contest Broken",
            election_date=date(2026, 11, 3),
            election_type="general",
            office_id=office_bad_id,
            source_record_id=contest_bad_source_record_id,
        ),
    )
    return contest_good_id, contest_bad_id


def _seed_candidacy_rows(
    conn: psycopg.Connection,
    data_source_id: UUID,
    contest_good_id: UUID,
    contest_bad_id: UUID,
) -> tuple[UUID, UUID]:

    candidacy_good_source_record_id = _seed_source_record(
        conn,
        source_record_id=UUID("23333333-3333-3333-3333-333333333321"),
        data_source_id=data_source_id,
        source_record_key="candidacy-good",
        source_url="https://example.org/record/candidacy-good",
    )
    candidacy_bad_source_record_id = _seed_source_record(
        conn,
        source_record_id=UUID("23333333-3333-3333-3333-333333333322"),
        data_source_id=data_source_id,
        source_record_key="candidacy-bad",
        source_url="",
    )

    contest_person_good = Person(
        id=UUID("13333333-3333-3333-3333-333333333321"),
        canonical_name="DWO Contest Person Good",
        first_name="DWO",
        last_name="ContestGood",
    )
    contest_person_bad = Person(
        id=UUID("13333333-3333-3333-3333-333333333322"),
        canonical_name="DWO Contest Person Broken",
        first_name="DWO",
        last_name="ContestBroken",
    )
    insert_person(conn, contest_person_good)
    insert_person(conn, contest_person_bad)

    candidacy_good_id = upsert_candidacy(
        conn,
        Candidacy(
            id=UUID("33333333-3333-3333-3333-333333333321"),
            person_id=contest_person_good.id,
            contest_id=contest_good_id,
            party="DEM",
            status="qualified",
            source_record_id=candidacy_good_source_record_id,
        ),
    )
    candidacy_bad_id = upsert_candidacy(
        conn,
        Candidacy(
            id=UUID("33333333-3333-3333-3333-333333333322"),
            person_id=contest_person_bad.id,
            contest_id=contest_bad_id,
            party="REP",
            status="qualified",
            source_record_id=candidacy_bad_source_record_id,
        ),
    )
    return candidacy_good_id, candidacy_bad_id


def _assert_surface_failures(db_conn: psycopg.Connection, seed_result: SurfaceSeedResult) -> None:
    assert _collect_audit_failures(db_conn, seed_result.samples) == seed_result.expected_failures


def test_dwo_provenance_audit_candidate_surface_reports_exact_failure(db_conn: psycopg.Connection) -> None:
    data_source_id = _seed_data_source(db_conn, suffix="nc_detail_pages_candidate")
    _assert_surface_failures(db_conn, _seed_candidate_surface(db_conn, data_source_id))


def test_dwo_provenance_audit_committee_surface_reports_exact_failure(db_conn: psycopg.Connection) -> None:
    data_source_id = _seed_data_source(db_conn, suffix="nc_detail_pages_committee")
    _assert_surface_failures(db_conn, _seed_committee_surface(db_conn, data_source_id))


def test_dwo_provenance_audit_contest_surface_reports_exact_failures(db_conn: psycopg.Connection) -> None:
    data_source_id = _seed_data_source(db_conn, suffix="nc_detail_pages_contest")
    _assert_surface_failures(db_conn, _seed_contest_surface(db_conn, data_source_id))


def test_dwo_provenance_audit_mixed_surfaces_report_deterministic_aggregate_failures(
    db_conn: psycopg.Connection,
) -> None:
    data_source_id = _seed_data_source(db_conn, suffix="nc_detail_pages_mixed_surface_aggregate")
    candidate_seed = _seed_candidate_surface(db_conn, data_source_id)
    committee_seed = _seed_committee_surface(db_conn, data_source_id)
    contest_seed = _seed_contest_surface(db_conn, data_source_id)

    all_samples = candidate_seed.samples + committee_seed.samples + contest_seed.samples
    failures = _collect_audit_failures(db_conn, all_samples)

    assert failures == [
        "candidate:31111111-1111-1111-1111-111111111102 [cf.candidate] missing source_url for source_record_key=candidate-bad",
        "candidate:31111111-1111-1111-1111-111111111104 [cf.candidate] dangling row source_record_id=21111111-1111-1111-1111-111111111105",
        "candidate:31111111-1111-1111-1111-111111111103 [cf.candidate] missing provenance rows",
        "committee:32222222-2222-2222-2222-222222222202 [cf.committee] missing source_url for source_record_key=committee-bad",
        "contest:33333333-3333-3333-3333-333333333312 [civic.contest] missing source_url for source_record_key=contest-bad",
        "candidacy:33333333-3333-3333-3333-333333333322 [civic.candidacy] missing source_url for source_record_key=candidacy-bad",
        "office:33333333-3333-3333-3333-333333333302 [civic.office] missing source_url for source_record_key=office-bad",
    ]
