
from __future__ import annotations

import csv
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from core.db import get_connection
from domains.campaign_finance.jurisdictions.states.CO.scraper.load import (
    _co_is_electioneering,
)
from domains.campaign_finance.jurisdictions.states.CO.scraper.parse import (
    parse_co_date,
    parse_contributions,
    parse_expenditures,
)

SAMPLE_CONTRIBUTIONS_PATH = Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"
SAMPLE_EXPENDITURES_PATH = Path(__file__).parent / "test_fixtures" / "sample_expenditures.csv"


def parsed_fixture_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(SAMPLE_CONTRIBUTIONS_PATH))


def parsed_expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(SAMPLE_EXPENDITURES_PATH))


def build_unique_fixture_row() -> dict[str, str | None]:
    row = dict(parsed_fixture_rows()[0])
    unique_suffix = uuid4().hex[:8]
    street_number = str(int(unique_suffix, 16) % 90_000 + 10_000)
    row["RecordID"] = f"review-{unique_suffix}"
    row["FirstName"] = f"Case{unique_suffix[:4]}"
    row["LastName"] = f"Reviewer{unique_suffix}"
    row["Address1"] = f"{street_number} Review Ave"
    row["Zip"] = "80999"
    row["CommitteeName"] = f"Review Committee {unique_suffix}"
    row["CO_ID"] = f"review-committee-{unique_suffix}"
    return row


def write_fixture_rows(path: Path, rows: list[dict[str, str | None]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})


def build_co_expected_filing_fec_id(row: dict[str, str | None], data_type: str) -> str:
    co_id = row.get("CO_ID")
    assert co_id is not None
    filed_date = parse_co_date(row.get("FiledDate"))
    assert filed_date is not None
    calendar_year = filed_date.split("-", maxsplit=1)[0]
    return f"CO-{co_id}-{calendar_year}-{data_type}"


def expected_co_expenditure_transaction_type(row: dict[str, str | None]) -> str:
    expenditure_type = row.get("ExpenditureType")
    assert expenditure_type is not None
    return "Independent Expenditure" if _co_is_electioneering(row) else expenditure_type


def fetch_source_record_id(
    conn: psycopg.Connection,
    data_source_id: UUID,
    record_id: str | None,
) -> UUID:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (data_source_id, record_id),
        )
        source_record = cursor.fetchone()

    assert source_record is not None
    return source_record["id"]


def fetch_entity_source_count(
    conn: psycopg.Connection,
    source_record_id: UUID,
    entity_type: str,
    extraction_role: str,
) -> int:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = %s
              AND extraction_role = %s
            """,
            (source_record_id, entity_type, extraction_role),
        )
        row = cursor.fetchone()

    return row["count"]


def collect_loaded_entity_ids(
    cursor: psycopg.Cursor[dict[str, object]],
    source_record_ids: list[UUID],
) -> tuple[set[UUID], set[UUID], set[UUID]]:
    person_ids: set[UUID] = set()
    organization_ids: set[UUID] = set()
    address_ids: set[UUID] = set()

    for sr_id in source_record_ids:
        cursor.execute(
            """
            SELECT entity_type, entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
            """,
            (sr_id,),
        )
        for row in cursor.fetchall():
            if row["entity_type"] == "person":
                person_ids.add(row["entity_id"])
            elif row["entity_type"] == "organization":
                organization_ids.add(row["entity_id"])
            elif row["entity_type"] == "address":
                address_ids.add(row["entity_id"])

        cursor.execute(
            """
            SELECT address_id
            FROM core.entity_address
            WHERE source_record_id = %s
            """,
            (sr_id,),
        )
        address_ids.update(row["address_id"] for row in cursor.fetchall())

    return person_ids, organization_ids, address_ids


def cleanup_loaded_data_source(data_source_id: UUID) -> None:
    cleanup_conn = get_connection()

    try:
        with cleanup_conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id
                FROM core.source_record
                WHERE data_source_id = %s
                """,
                (data_source_id,),
            )
            sr_ids = [row["id"] for row in cursor.fetchall()]
            person_ids, organization_ids, address_ids = collect_loaded_entity_ids(cursor, sr_ids)

            for sr_id in sr_ids:
                cursor.execute("DELETE FROM core.entity_address WHERE source_record_id = %s", (sr_id,))
                cursor.execute("DELETE FROM core.entity_source WHERE source_record_id = %s", (sr_id,))

            cursor.execute("DELETE FROM core.source_record WHERE data_source_id = %s", (data_source_id,))

            for person_id in person_ids:
                cursor.execute("DELETE FROM core.person WHERE id = %s", (person_id,))
            for organization_id in organization_ids:
                cursor.execute("DELETE FROM core.organization WHERE id = %s", (organization_id,))
            for address_id in address_ids:
                cursor.execute("DELETE FROM core.address WHERE id = %s", (address_id,))

            cursor.execute("DELETE FROM core.data_source WHERE id = %s", (data_source_id,))

        cleanup_conn.commit()
    except Exception:
        cleanup_conn.rollback()
        raise
    finally:
        cleanup_conn.close()
