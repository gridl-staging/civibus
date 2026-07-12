from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import psycopg


@dataclass(frozen=True, slots=True)
class SeededCommittee:
    id: UUID
    fec_committee_id: str
    organization_id: UUID


@dataclass(frozen=True, slots=True)
class SeededCandidate:
    id: UUID
    fec_candidate_id: str
    person_id: UUID


@dataclass(frozen=True, slots=True)
class ScheduleELinkageCounts:
    total: int
    with_support_oppose: int
    with_recipient_candidate: int


def seed_schedule_e_committee(
    conn: psycopg.Connection,
    fec_id: str,
    name: str = "Test Committee",
) -> SeededCommittee:
    """Insert a minimal committee + organization into the test DB."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, organization_id FROM cf.committee WHERE fec_committee_id = %s LIMIT 1",
            (fec_id,),
        )
        existing_committee_row = cur.fetchone()
        if existing_committee_row is not None:
            return SeededCommittee(
                id=existing_committee_row[0],
                fec_committee_id=fec_id,
                organization_id=existing_committee_row[1],
            )

        org_id = uuid4()
        committee_id = uuid4()
        cur.execute(
            "INSERT INTO core.organization (id, canonical_name, identifiers) VALUES (%s, %s, %s::jsonb)",
            (org_id, name, json.dumps({"fec_committee_id": fec_id})),
        )
        cur.execute(
            "INSERT INTO cf.committee (id, fec_committee_id, name, organization_id) VALUES (%s, %s, %s, %s)",
            (committee_id, fec_id, name, org_id),
        )
    conn.commit()
    return SeededCommittee(id=committee_id, fec_committee_id=fec_id, organization_id=org_id)


def seed_schedule_e_candidate(
    conn: psycopg.Connection,
    fec_id: str,
    name: str = "Test Candidate",
    office: str | None = None,
) -> SeededCandidate:
    """Insert a minimal candidate + person pair used by Schedule E linkage tests."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, person_id FROM cf.candidate WHERE fec_candidate_id = %s LIMIT 1",
            (fec_id,),
        )
        existing_candidate_row = cur.fetchone()
        if existing_candidate_row is not None:
            return SeededCandidate(
                id=existing_candidate_row[0],
                fec_candidate_id=fec_id,
                person_id=existing_candidate_row[1],
            )

        candidate_office = office if office is not None else fec_id[0]
        person_id = uuid4()
        candidate_id = uuid4()
        cur.execute(
            "INSERT INTO core.person (id, canonical_name, identifiers) VALUES (%s, %s, %s::jsonb)",
            (person_id, name, json.dumps({"fec_candidate_id": fec_id})),
        )
        cur.execute(
            "INSERT INTO cf.candidate (id, fec_candidate_id, name, person_id, office) VALUES (%s, %s, %s, %s, %s)",
            (candidate_id, fec_id, name, person_id, candidate_office),
        )
    conn.commit()
    return SeededCandidate(id=candidate_id, fec_candidate_id=fec_id, person_id=person_id)


def fetch_schedule_e_linkage_counts(
    conn: psycopg.Connection,
    *,
    candidate_fec_id: str,
) -> ScheduleELinkageCounts:
    """Count loaded Schedule E rows that retained support/opposition and candidate linkage."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE transaction_row.support_oppose IS NOT NULL),
                   COUNT(*) FILTER (WHERE transaction_row.recipient_candidate_id IS NOT NULL)
            FROM cf.transaction AS transaction_row
            JOIN cf.filing AS filing ON filing.id = transaction_row.filing_id
            LEFT JOIN cf.candidate AS candidate ON candidate.id = transaction_row.recipient_candidate_id
            WHERE filing.report_type = 'schedule_e'
              AND candidate.fec_candidate_id = %s
            """,
            (candidate_fec_id,),
        )
        row = cur.fetchone()
    assert row is not None
    return ScheduleELinkageCounts(
        total=row[0],
        with_support_oppose=row[1],
        with_recipient_candidate=row[2],
    )


def extract_schedule_e_committees(path: Path, *, limit: int | None = None) -> list[tuple[str, str]]:
    """Read unique (spe_id, spe_nam) committee pairs from a Schedule E CSV."""
    committees: list[tuple[str, str]] = []
    seen_committee_ids: set[str] = set()

    with path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for index, row in enumerate(reader):
            if limit is not None and index >= limit:
                break

            committee_fec_id = (row.get("spe_id") or "").strip()
            committee_name = (row.get("spe_nam") or "").strip()
            if not committee_fec_id or committee_fec_id in seen_committee_ids:
                continue

            seen_committee_ids.add(committee_fec_id)
            committees.append((committee_fec_id, committee_name))

    return committees
