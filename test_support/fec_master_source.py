from __future__ import annotations

from uuid import UUID

import psycopg

from core.db import try_insert_source_record
from core.types.python.models import SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.fec_lookup import build_committee_master_source_record_key


def fec_committee_master_source_key(cycle: int, fec_committee_id: str) -> str:
    return build_committee_master_source_record_key(cycle=cycle, fec_committee_id=fec_committee_id)


def seed_fec_committee_master_source_record(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    cycle: int,
    fec_committee_id: str,
    name: str,
) -> None:
    raw_fields = {"CMTE_ID": fec_committee_id, "CMTE_NM": name}
    try_insert_source_record(
        conn,
        SourceRecord(
            data_source_id=data_source_id,
            source_record_key=fec_committee_master_source_key(cycle, fec_committee_id),
            raw_fields=raw_fields,
            pull_date=utc_now(),
            record_hash=compute_record_hash(raw_fields),
        ),
    )
    conn.commit()


def select_fec_committee_master_source_keys(
    conn: psycopg.Connection,
    *,
    cycle: int,
    committee_fec_ids: list[str],
) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_record_key
            FROM core.source_record
            WHERE source_record_key = ANY(%s)
              AND superseded_by IS NULL
            """,
            ([fec_committee_master_source_key(cycle, committee_id) for committee_id in committee_fec_ids],),
        )
        return {row[0] for row in cur.fetchall()}


def delete_fec_committee_master_source_records(
    conn: psycopg.Connection,
    *,
    cycle: int,
    committee_fec_ids: list[str],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM core.source_record WHERE source_record_key = ANY(%s)",
            ([fec_committee_master_source_key(cycle, committee_id) for committee_id in committee_fec_ids],),
        )
    conn.commit()
