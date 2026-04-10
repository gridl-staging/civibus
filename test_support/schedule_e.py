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
