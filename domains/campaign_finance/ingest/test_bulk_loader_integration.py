from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.ingest.bulk_loader import (
    ensure_fec_bulk_data_source,
    load_candidate_committee_links,
    load_candidates,
    load_candidate_summaries,
    load_committees,
)
from domains.campaign_finance.ingest.bulk_parser import (
    CCL_COLUMNS,
    CM_COLUMNS,
    CN_COLUMNS,
    WEBALL_COLUMNS,
    read_bulk_file,
)


pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bulk"
_COMMITTEE_FIXTURE_PATH = _FIXTURE_DIR / "cm_sample.txt"
_CANDIDATE_FIXTURE_PATH = _FIXTURE_DIR / "cn_sample.txt"
_CCL_FIXTURE_PATH = _FIXTURE_DIR / "ccl_sample.txt"
_WEBALL_FIXTURE_PATH = _FIXTURE_DIR / "weball_sample.txt"

_BULK_SOURCE_DOMAIN = "campaign_finance"
_BULK_SOURCE_JURISDICTION = "federal/fec"
_BULK_SOURCE_NAME = "FEC Bulk Data"
_PRIMARY_CYCLE = 2024
_SECONDARY_CYCLE = 2026


@dataclass(frozen=True, slots=True)
class BulkLoaderFixtureSet:
    committee_path: Path
    candidate_path: Path
    ccl_path: Path
    weball_path: Path
    committee_rows: list[dict[str, str | None]]
    candidate_rows: list[dict[str, str | None]]
    ccl_rows: list[dict[str, str | None]]
    weball_rows: list[dict[str, str | None]]

    @property
    def committee_ids(self) -> list[str]:
        return [row["CMTE_ID"] for row in self.committee_rows if row["CMTE_ID"] is not None]

    @property
    def candidate_ids(self) -> list[str]:
        return [row["CAND_ID"] for row in self.candidate_rows if row["CAND_ID"] is not None]

    @property
    def linkage_ids(self) -> list[str]:
        return [row["LINKAGE_ID"] for row in self.ccl_rows if row["LINKAGE_ID"] is not None]

    def source_record_keys(self, cycles: Sequence[int]) -> list[str]:
        keys: list[str] = []
        for cycle in cycles:
            keys.extend(f"cm:{cycle}:{committee_id}" for committee_id in self.committee_ids)
            keys.extend(f"cn:{cycle}:{candidate_id}" for candidate_id in self.candidate_ids)
            keys.extend(f"ccl:{cycle}:{linkage_id}" for linkage_id in self.linkage_ids)
            keys.extend(f"weball:{cycle}:{candidate_id}" for candidate_id in self.candidate_ids)
        return keys

    def committee_source_record_keys(self, cycles: Sequence[int]) -> list[str]:
        keys: list[str] = []
        for cycle in cycles:
            keys.extend(f"cm:{cycle}:{committee_id}" for committee_id in self.committee_ids)
        return keys


@dataclass(frozen=True, slots=True)
class CandidateSummaryScenario:
    fixture_path: Path
    updated_fixture_path: Path
    weball_rows: list[dict[str, str | None]]
    updated_rows: list[dict[str, str | None]]
    expected_rows_by_candidate_id: dict[str, dict[str, str | None]]
    unresolved_candidate_id: str
    blank_self_funding_candidate_id: str
    changed_candidate_id: str


@pytest.fixture
def bulk_loader_conn(committing_db_conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    yield committing_db_conn


@pytest.fixture
def bulk_loader_fixture_set(
    bulk_loader_conn: psycopg.Connection,
    tmp_path: Path,
) -> Iterator[BulkLoaderFixtureSet]:
    initial_data_source_id = _select_bulk_data_source_id(bulk_loader_conn)
    fixture_set = _materialize_bulk_loader_fixture_set(tmp_path)
    try:
        yield fixture_set
    finally:
        _cleanup_bulk_loader_rows(bulk_loader_conn, fixture_set, initial_data_source_id)
        bulk_loader_conn.commit()


def _select_bulk_data_source_id(conn: psycopg.Connection) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            LIMIT 1
            """,
            (_BULK_SOURCE_DOMAIN, _BULK_SOURCE_JURISDICTION, _BULK_SOURCE_NAME),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row[0]


def _read_fixture_rows(path: Path, file_type: str) -> list[dict[str, str | None]]:
    return [dict(row) for row in read_bulk_file(path, file_type)]


def _write_fixture_file(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[dict[str, str | None]],
) -> None:
    lines = ["|".join(row.get(column) or "" for column in columns) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")


def _parse_weball_date(raw_value: str) -> date:
    month, day, year = raw_value.split("/")
    return date(int(year), int(month), int(day))


def _decimal_or_none(raw_value: str | None) -> Decimal | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    return Decimal(raw_value)


def _build_fixture_prefix() -> str:
    return str(uuid4().int % 900 + 100)


def _rewrite_mailing_street(street_line_1: str | None, prefix: str) -> str | None:
    if street_line_1 is None:
        return None
    return f"{prefix} {street_line_1}"


def _materialize_bulk_loader_fixture_set(tmp_path: Path) -> BulkLoaderFixtureSet:
    fixture_prefix = _build_fixture_prefix()
    address_prefix = f"TEST-{fixture_prefix}"

    original_committee_rows = _read_fixture_rows(_COMMITTEE_FIXTURE_PATH, "cm")
    original_candidate_rows = _read_fixture_rows(_CANDIDATE_FIXTURE_PATH, "cn")
    original_ccl_rows = _read_fixture_rows(_CCL_FIXTURE_PATH, "ccl")
    original_weball_rows = _read_fixture_rows(_WEBALL_FIXTURE_PATH, "weball")

    committee_id_map = {
        row["CMTE_ID"]: f"C{fixture_prefix}{index:05d}"
        for index, row in enumerate(original_committee_rows, start=1)
        if row["CMTE_ID"] is not None
    }
    candidate_id_map = {
        row["CAND_ID"]: f"{row['CAND_ID'][0]}{fixture_prefix}{index:05d}"
        for index, row in enumerate(original_candidate_rows, start=1)
        if row["CAND_ID"] is not None
    }
    linkage_id_map = {
        row["LINKAGE_ID"]: f"{fixture_prefix}{index:09d}"
        for index, row in enumerate(original_ccl_rows, start=1)
        if row["LINKAGE_ID"] is not None
    }

    committee_rows = [
        {
            **row,
            "CMTE_ID": committee_id_map.get(row["CMTE_ID"], row["CMTE_ID"]),
            "CAND_ID": candidate_id_map.get(row["CAND_ID"], row["CAND_ID"]),
            "CMTE_ST1": _rewrite_mailing_street(row["CMTE_ST1"], address_prefix),
        }
        for row in original_committee_rows
    ]
    candidate_rows = [
        {
            **row,
            "CAND_ID": candidate_id_map.get(row["CAND_ID"], row["CAND_ID"]),
            "CAND_PCC": committee_id_map.get(row["CAND_PCC"], row["CAND_PCC"]),
            "CAND_ST1": _rewrite_mailing_street(row["CAND_ST1"], address_prefix),
        }
        for row in original_candidate_rows
    ]
    ccl_rows = [
        {
            **row,
            "CAND_ID": candidate_id_map.get(row["CAND_ID"], row["CAND_ID"]),
            "CMTE_ID": committee_id_map.get(row["CMTE_ID"], row["CMTE_ID"]),
            "LINKAGE_ID": linkage_id_map.get(row["LINKAGE_ID"], row["LINKAGE_ID"]),
        }
        for row in original_ccl_rows
    ]
    weball_rows = [
        {
            **row,
            "CAND_ID": candidate_id_map.get(row["CAND_ID"], row["CAND_ID"]),
        }
        for row in original_weball_rows
    ]

    committee_path = tmp_path / "cm_sample_unique.txt"
    candidate_path = tmp_path / "cn_sample_unique.txt"
    ccl_path = tmp_path / "ccl_sample_unique.txt"
    weball_path = tmp_path / "weball_sample_unique.txt"
    _write_fixture_file(committee_path, CM_COLUMNS, committee_rows)
    _write_fixture_file(candidate_path, CN_COLUMNS, candidate_rows)
    _write_fixture_file(ccl_path, CCL_COLUMNS, ccl_rows)
    _write_fixture_file(weball_path, WEBALL_COLUMNS, weball_rows)

    return BulkLoaderFixtureSet(
        committee_path=committee_path,
        candidate_path=candidate_path,
        ccl_path=ccl_path,
        weball_path=weball_path,
        committee_rows=committee_rows,
        candidate_rows=candidate_rows,
        ccl_rows=ccl_rows,
        weball_rows=weball_rows,
    )


def _select_source_record_ids(
    conn: psycopg.Connection,
    data_source_id: UUID | None,
    source_record_keys: Sequence[str],
) -> list[UUID]:
    if data_source_id is None or not source_record_keys:
        return []

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
            """,
            (data_source_id, list(source_record_keys)),
        )
        return [row[0] for row in cursor.fetchall()]


def _select_address_ids(conn: psycopg.Connection, source_record_ids: Sequence[UUID]) -> list[UUID]:
    if not source_record_ids:
        return []

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT entity_id
            FROM core.entity_source
            WHERE entity_type = 'address'
              AND source_record_id = ANY(%s)
            """,
            (list(source_record_ids),),
        )
        return [row[0] for row in cursor.fetchall()]


def _delete_rows(conn: psycopg.Connection, sql: str, values: Sequence[UUID | str]) -> None:
    if not values:
        return
    with conn.cursor() as cursor:
        cursor.execute(sql, (list(values),))


def _delete_bulk_data_source_if_created_by_test(
    conn: psycopg.Connection,
    initial_data_source_id: UUID | None,
    current_data_source_id: UUID | None,
) -> None:
    if initial_data_source_id is not None or current_data_source_id is None:
        return

    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM core.source_record WHERE data_source_id = %s", (current_data_source_id,))
        remaining_source_records = cursor.fetchone()[0]
        if remaining_source_records == 0:
            cursor.execute("DELETE FROM core.data_source WHERE id = %s", (current_data_source_id,))


def _cleanup_bulk_loader_rows(
    conn: psycopg.Connection,
    fixture_set: BulkLoaderFixtureSet,
    initial_data_source_id: UUID | None,
) -> None:
    current_data_source_id = _select_bulk_data_source_id(conn)
    source_record_ids = _select_source_record_ids(
        conn,
        current_data_source_id,
        fixture_set.source_record_keys((_PRIMARY_CYCLE, _SECONDARY_CYCLE)),
    )
    address_ids = _select_address_ids(conn, source_record_ids)

    _delete_rows(conn, "DELETE FROM cf.candidate_committee_link WHERE source_record_id = ANY(%s)", source_record_ids)
    _delete_rows(conn, "DELETE FROM cf.candidate WHERE fec_candidate_id = ANY(%s)", fixture_set.candidate_ids)
    _delete_rows(conn, "DELETE FROM cf.committee WHERE fec_committee_id = ANY(%s)", fixture_set.committee_ids)
    _delete_rows(conn, "DELETE FROM core.entity_address WHERE source_record_id = ANY(%s)", source_record_ids)
    _delete_rows(conn, "DELETE FROM core.address WHERE id = ANY(%s)", address_ids)
    _delete_rows(
        conn,
        "DELETE FROM core.person WHERE identifiers ->> 'fec_candidate_id' = ANY(%s)",
        fixture_set.candidate_ids,
    )
    _delete_rows(
        conn,
        "DELETE FROM core.organization WHERE identifiers ->> 'fec_committee_id' = ANY(%s)",
        fixture_set.committee_ids,
    )
    _delete_rows(conn, "DELETE FROM core.entity_source WHERE source_record_id = ANY(%s)", source_record_ids)
    _delete_rows(conn, "DELETE FROM core.source_record WHERE id = ANY(%s)", source_record_ids)
    _delete_bulk_data_source_if_created_by_test(conn, initial_data_source_id, current_data_source_id)


def _assert_committee_rows(conn: psycopg.Connection, expected_rows: Sequence[dict[str, str | None]]) -> None:
    committee_ids = [row["CMTE_ID"] for row in expected_rows if row["CMTE_ID"] is not None]
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT fec_committee_id, name, committee_type
            FROM cf.committee
            WHERE fec_committee_id = ANY(%s)
            ORDER BY fec_committee_id
            """,
            (committee_ids,),
        )
        committee_rows = cursor.fetchall()

    assert len(committee_rows) == len(expected_rows)
    committee_by_id = {row["fec_committee_id"]: row for row in committee_rows}
    for expected_row in expected_rows:
        committee_row = committee_by_id[expected_row["CMTE_ID"]]
        assert committee_row["name"] == expected_row["CMTE_NM"]
        assert committee_row["committee_type"] == expected_row["CMTE_TP"]


def _assert_organization_rows(conn: psycopg.Connection, expected_rows: Sequence[dict[str, str | None]]) -> None:
    committee_ids = [row["CMTE_ID"] for row in expected_rows if row["CMTE_ID"] is not None]
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT identifiers ->> 'fec_committee_id' AS fec_committee_id,
                   canonical_name
            FROM core.organization
            WHERE identifiers ->> 'fec_committee_id' = ANY(%s)
            ORDER BY identifiers ->> 'fec_committee_id'
            """,
            (committee_ids,),
        )
        organization_rows = cursor.fetchall()

    assert len(organization_rows) == len(expected_rows)
    organization_by_id = {row["fec_committee_id"]: row for row in organization_rows}
    for expected_row in expected_rows:
        assert organization_by_id[expected_row["CMTE_ID"]]["canonical_name"] == expected_row["CMTE_NM"]


def _assert_committee_addresses(conn: psycopg.Connection, expected_rows: Sequence[dict[str, str | None]]) -> None:
    committee_ids = [row["CMTE_ID"] for row in expected_rows if row["CMTE_ID"] is not None]
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT organization.identifiers ->> 'fec_committee_id' AS fec_committee_id,
                   address.raw_address,
                   address.city,
                   address.state,
                   address.zip5,
                   address.zip4
            FROM core.entity_address entity_address
            JOIN core.organization organization
              ON entity_address.entity_type = 'organization'
             AND organization.id = entity_address.entity_id
            JOIN core.address address
              ON address.id = entity_address.address_id
            WHERE organization.identifiers ->> 'fec_committee_id' = ANY(%s)
            ORDER BY organization.identifiers ->> 'fec_committee_id'
            """,
            (committee_ids,),
        )
        address_rows = cursor.fetchall()

    assert len(address_rows) == len(expected_rows)
    address_by_id = {row["fec_committee_id"]: row for row in address_rows}
    for expected_row in expected_rows:
        expected_zip = expected_row["CMTE_ZIP"] or ""
        address_row = address_by_id[expected_row["CMTE_ID"]]
        assert expected_row["CMTE_ST1"] in address_row["raw_address"]
        assert address_row["city"] == expected_row["CMTE_CITY"]
        assert address_row["state"] == expected_row["CMTE_ST"]
        assert address_row["zip5"] == expected_zip[:5]
        assert address_row["zip4"] == expected_zip[5:] or None


def _assert_committee_source_record_counts(
    conn: psycopg.Connection,
    data_source_id: UUID,
    fixture_set: BulkLoaderFixtureSet,
) -> None:
    cycle_2024_keys = fixture_set.committee_source_record_keys((_PRIMARY_CYCLE,))
    cycle_2026_keys = fixture_set.committee_source_record_keys((_SECONDARY_CYCLE,))

    assert len(_select_source_record_ids(conn, data_source_id, cycle_2024_keys)) == len(cycle_2024_keys)
    assert len(_select_source_record_ids(conn, data_source_id, cycle_2026_keys)) == len(cycle_2026_keys)


def _assert_candidate_rows(conn: psycopg.Connection, expected_rows: Sequence[dict[str, str | None]]) -> None:
    candidate_ids = [row["CAND_ID"] for row in expected_rows if row["CAND_ID"] is not None]
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT candidate.fec_candidate_id,
                   candidate.name,
                   candidate.office,
                   candidate.state,
                   candidate.district,
                   candidate.incumbent_challenge,
                   principal.fec_committee_id AS principal_committee_fec_id
            FROM cf.candidate candidate
            LEFT JOIN cf.committee principal
              ON principal.id = candidate.principal_committee_id
            WHERE candidate.fec_candidate_id = ANY(%s)
            ORDER BY candidate.fec_candidate_id
            """,
            (candidate_ids,),
        )
        candidate_rows = cursor.fetchall()

    assert len(candidate_rows) == len(expected_rows)
    candidate_by_id = {row["fec_candidate_id"]: row for row in candidate_rows}
    for expected_row in expected_rows:
        candidate_row = candidate_by_id[expected_row["CAND_ID"]]
        assert candidate_row["name"] == expected_row["CAND_NAME"]
        assert candidate_row["office"] == expected_row["CAND_OFFICE"]
        assert candidate_row["state"] == expected_row["CAND_OFFICE_ST"]
        assert candidate_row["district"] == expected_row["CAND_OFFICE_DISTRICT"]
        assert candidate_row["incumbent_challenge"] == expected_row["CAND_ICI"]
        assert candidate_row["principal_committee_fec_id"] == expected_row["CAND_PCC"]


def _assert_person_rows(conn: psycopg.Connection, expected_rows: Sequence[dict[str, str | None]]) -> None:
    candidate_ids = [row["CAND_ID"] for row in expected_rows if row["CAND_ID"] is not None]
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT identifiers ->> 'fec_candidate_id' AS fec_candidate_id,
                   canonical_name
            FROM core.person
            WHERE identifiers ->> 'fec_candidate_id' = ANY(%s)
            ORDER BY identifiers ->> 'fec_candidate_id'
            """,
            (candidate_ids,),
        )
        person_rows = cursor.fetchall()

    assert len(person_rows) == len(expected_rows)
    person_by_id = {row["fec_candidate_id"]: row for row in person_rows}
    for expected_row in expected_rows:
        assert person_by_id[expected_row["CAND_ID"]]["canonical_name"] == expected_row["CAND_NAME"]


def _assert_candidate_addresses(conn: psycopg.Connection, expected_rows: Sequence[dict[str, str | None]]) -> None:
    candidate_ids = [row["CAND_ID"] for row in expected_rows if row["CAND_ID"] is not None]
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT person.identifiers ->> 'fec_candidate_id' AS fec_candidate_id,
                   address.raw_address,
                   address.city,
                   address.state,
                   address.zip5,
                   address.zip4
            FROM core.entity_address entity_address
            JOIN core.person person
              ON entity_address.entity_type = 'person'
             AND person.id = entity_address.entity_id
            JOIN core.address address
              ON address.id = entity_address.address_id
            WHERE person.identifiers ->> 'fec_candidate_id' = ANY(%s)
            ORDER BY person.identifiers ->> 'fec_candidate_id'
            """,
            (candidate_ids,),
        )
        address_rows = cursor.fetchall()

    assert len(address_rows) == len(expected_rows)
    address_by_candidate = {row["fec_candidate_id"]: row for row in address_rows}
    for expected_row in expected_rows:
        expected_zip = expected_row["CAND_ZIP"] or ""
        address_row = address_by_candidate[expected_row["CAND_ID"]]
        assert expected_row["CAND_ST1"] in address_row["raw_address"]
        assert address_row["city"] == expected_row["CAND_CITY"]
        assert address_row["state"] == expected_row["CAND_ST"]
        assert address_row["zip5"] == expected_zip[:5]
        assert address_row["zip4"] == expected_zip[5:] or None


def _fetch_link_rows(
    conn: psycopg.Connection, data_source_id: UUID, linkage_ids: Sequence[str]
) -> list[dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT candidate.fec_candidate_id,
                   committee.fec_committee_id,
                   link.designation,
                   link.candidate_election_year,
                   link.fec_election_year,
                   lower(link.valid_period) AS period_start,
                   upper(link.valid_period) AS period_end,
                   lower_inc(link.valid_period) AS lower_inclusive,
                   upper_inc(link.valid_period) AS upper_inclusive
            FROM cf.candidate_committee_link link
            JOIN cf.candidate candidate ON candidate.id = link.candidate_id
            JOIN cf.committee committee ON committee.id = link.committee_id
            JOIN core.source_record source_record ON source_record.id = link.source_record_id
            WHERE source_record.data_source_id = %s
              AND source_record.source_record_key = ANY(%s)
            ORDER BY link.id
            """,
            (data_source_id, [f"ccl:{_PRIMARY_CYCLE}:{linkage_id}" for linkage_id in linkage_ids]),
        )
        return cursor.fetchall()


def _build_candidate_summary_scenario(
    fixture_set: BulkLoaderFixtureSet,
    tmp_path: Path,
) -> CandidateSummaryScenario:
    weball_rows = [dict(row) for row in fixture_set.weball_rows]
    blank_self_funding_candidate_id = weball_rows[1]["CAND_ID"]
    for column_name in ("CAND_CONTRIB", "CAND_LOANS", "CAND_LOAN_REPAY"):
        weball_rows[1][column_name] = ""

    unresolved_candidate_id = f"H{uuid4().hex[:8].upper()}"
    weball_rows.append({**weball_rows[0], "CAND_ID": unresolved_candidate_id})
    fixture_path = tmp_path / "weball_with_unresolved_candidate.txt"
    _write_fixture_file(fixture_path, WEBALL_COLUMNS, weball_rows)

    updated_rows = [dict(row) for row in weball_rows]
    updated_rows[0]["TTL_RECEIPTS"] = "99999.01"
    updated_rows[0]["CAND_CONTRIB"] = "7654.32"
    updated_rows[0]["CAND_LOANS"] = "8765.43"
    updated_rows[0]["CAND_LOAN_REPAY"] = "987.65"
    updated_fixture_path = tmp_path / "weball_with_updated_summary.txt"
    _write_fixture_file(updated_fixture_path, WEBALL_COLUMNS, updated_rows)

    return CandidateSummaryScenario(
        fixture_path=fixture_path,
        updated_fixture_path=updated_fixture_path,
        weball_rows=weball_rows,
        updated_rows=updated_rows,
        expected_rows_by_candidate_id={
            row["CAND_ID"]: row for row in updated_rows if row["CAND_ID"] != unresolved_candidate_id
        },
        unresolved_candidate_id=unresolved_candidate_id,
        blank_self_funding_candidate_id=blank_self_funding_candidate_id,
        changed_candidate_id=updated_rows[0]["CAND_ID"],
    )


def _fetch_candidate_summary_rows(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    candidate_ids: Sequence[str],
    unresolved_candidate_id: str,
) -> tuple[list[dict[str, object]], int, int, int]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT fec_candidate_id,
                   total_receipts,
                   total_disbursements,
                   cash_on_hand,
                   candidate_contrib,
                   candidate_loans,
                   candidate_loan_repay,
                   summary_coverage_end_date,
                   name,
                   office,
                   person_id,
                   candidate_source.source_record_key AS candidate_source_record_key
            FROM cf.candidate
            JOIN core.source_record candidate_source
              ON candidate_source.id = candidate.source_record_id
            WHERE fec_candidate_id = ANY(%s)
            ORDER BY fec_candidate_id
            """,
            (candidate_ids,),
        )
        summary_rows = cursor.fetchall()
        cursor.execute(
            "SELECT COUNT(*) AS candidate_count FROM cf.candidate WHERE fec_candidate_id = %s",
            (unresolved_candidate_id,),
        )
        unresolved_candidate_count = cursor.fetchone()["candidate_count"]
        cursor.execute(
            "SELECT COUNT(*) AS person_count FROM core.person WHERE identifiers ->> 'fec_candidate_id' = %s",
            (unresolved_candidate_id,),
        )
        unresolved_person_count = cursor.fetchone()["person_count"]
        cursor.execute(
            "SELECT COUNT(*) AS source_record_count FROM core.source_record WHERE data_source_id = %s AND source_record_key = %s",
            (data_source_id, f"weball:{_PRIMARY_CYCLE}:{candidate_ids[0]}"),
        )
        updated_source_record_count = cursor.fetchone()["source_record_count"]
    return summary_rows, unresolved_candidate_count, unresolved_person_count, updated_source_record_count


def _fetch_weball_source_record_rows(
    conn: psycopg.Connection,
    *,
    data_source_id: UUID,
    candidate_id: str,
) -> list[dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id,
                   superseded_by,
                   raw_fields ->> 'CAND_CONTRIB' AS candidate_contrib,
                   raw_fields ->> 'CAND_LOANS' AS candidate_loans,
                   raw_fields ->> 'CAND_LOAN_REPAY' AS candidate_loan_repay
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            ORDER BY created_at, id
            """,
            (data_source_id, f"weball:{_PRIMARY_CYCLE}:{candidate_id}"),
        )
        return cursor.fetchall()


def _assert_candidate_summary_rows(
    *,
    summary_rows: Sequence[dict[str, object]],
    fixture_set: BulkLoaderFixtureSet,
    scenario: CandidateSummaryScenario,
) -> dict[str, dict[str, object]]:
    assert len(summary_rows) == len(fixture_set.weball_rows)
    summary_by_candidate_id = {row["fec_candidate_id"]: row for row in summary_rows}
    for expected_row in scenario.weball_rows[:-1]:
        candidate_row = summary_by_candidate_id[expected_row["CAND_ID"]]
        original_candidate = next(
            row for row in fixture_set.candidate_rows if row["CAND_ID"] == expected_row["CAND_ID"]
        )
        expected_summary_row = scenario.expected_rows_by_candidate_id[expected_row["CAND_ID"]]
        assert candidate_row["total_receipts"] == Decimal(expected_summary_row["TTL_RECEIPTS"])
        assert candidate_row["total_disbursements"] == Decimal(expected_summary_row["TTL_DISB"])
        assert candidate_row["cash_on_hand"] == Decimal(expected_summary_row["COH_COP"])
        assert candidate_row["candidate_contrib"] == _decimal_or_none(expected_summary_row["CAND_CONTRIB"])
        assert candidate_row["candidate_loans"] == _decimal_or_none(expected_summary_row["CAND_LOANS"])
        assert candidate_row["candidate_loan_repay"] == _decimal_or_none(expected_summary_row["CAND_LOAN_REPAY"])
        assert candidate_row["summary_coverage_end_date"] == _parse_weball_date(expected_summary_row["CVG_END_DT"])
        assert candidate_row["name"] == original_candidate["CAND_NAME"]
        assert candidate_row["office"] == original_candidate["CAND_OFFICE"]
        assert candidate_row["person_id"] is not None
        assert candidate_row["candidate_source_record_key"] == f"cn:{_PRIMARY_CYCLE}:{expected_row['CAND_ID']}"
    return summary_by_candidate_id


def _assert_changed_weball_source_records(
    *,
    source_rows: Sequence[dict[str, object]],
    scenario: CandidateSummaryScenario,
) -> None:
    assert len(source_rows) == 2
    old_source_row = next(row for row in source_rows if row["superseded_by"] is not None)
    active_source_row = next(row for row in source_rows if row["superseded_by"] is None)
    assert old_source_row["superseded_by"] == active_source_row["id"]
    assert old_source_row["candidate_contrib"] == scenario.weball_rows[0]["CAND_CONTRIB"]
    assert old_source_row["candidate_loans"] == scenario.weball_rows[0]["CAND_LOANS"]
    assert old_source_row["candidate_loan_repay"] == scenario.weball_rows[0]["CAND_LOAN_REPAY"]
    assert active_source_row["candidate_contrib"] == scenario.updated_rows[0]["CAND_CONTRIB"]
    assert active_source_row["candidate_loans"] == scenario.updated_rows[0]["CAND_LOANS"]
    assert active_source_row["candidate_loan_repay"] == scenario.updated_rows[0]["CAND_LOAN_REPAY"]


def _load_committees_and_candidates(
    conn: psycopg.Connection,
    fixture_set: BulkLoaderFixtureSet,
    data_source_id: UUID,
) -> None:
    load_committees(
        conn,
        fixture_set.committee_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )
    load_candidates(
        conn,
        fixture_set.candidate_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )


def test_ensure_fec_bulk_data_source_is_idempotent(bulk_loader_conn: psycopg.Connection) -> None:
    initial_data_source_id = _select_bulk_data_source_id(bulk_loader_conn)
    try:
        first_id = ensure_fec_bulk_data_source(bulk_loader_conn)
        second_id = ensure_fec_bulk_data_source(bulk_loader_conn)

        assert first_id == second_id

        with bulk_loader_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM core.data_source
                WHERE domain = %s
                  AND jurisdiction = %s
                  AND name = %s
                """,
                (_BULK_SOURCE_DOMAIN, _BULK_SOURCE_JURISDICTION, _BULK_SOURCE_NAME),
            )
            assert cursor.fetchone()[0] == 1
    finally:
        _delete_bulk_data_source_if_created_by_test(
            bulk_loader_conn,
            initial_data_source_id,
            _select_bulk_data_source_id(bulk_loader_conn),
        )
        bulk_loader_conn.commit()


def test_load_committees_is_idempotent_per_cycle_and_cross_cycle_source_records(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)

    first_result = load_committees(
        bulk_loader_conn,
        bulk_loader_fixture_set.committee_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )
    second_result = load_committees(
        bulk_loader_conn,
        bulk_loader_fixture_set.committee_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )
    third_result = load_committees(
        bulk_loader_conn,
        bulk_loader_fixture_set.committee_path,
        cycle=_SECONDARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )

    assert (first_result.inserted, first_result.skipped, first_result.errors) == (5, 0, 0)
    assert (second_result.inserted, second_result.skipped, second_result.errors) == (0, 5, 0)
    assert (third_result.inserted, third_result.skipped, third_result.errors) == (5, 0, 0)

    _assert_committee_rows(bulk_loader_conn, bulk_loader_fixture_set.committee_rows)
    _assert_organization_rows(bulk_loader_conn, bulk_loader_fixture_set.committee_rows)
    _assert_committee_addresses(bulk_loader_conn, bulk_loader_fixture_set.committee_rows)
    _assert_committee_source_record_counts(bulk_loader_conn, data_source_id, bulk_loader_fixture_set)


def test_amendment_within_single_batch(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    original_row = dict(bulk_loader_fixture_set.committee_rows[0])
    amended_row = {
        **original_row,
        "CMTE_NM": f"{original_row['CMTE_NM']} AMENDED",
        "CMTE_ST1": _rewrite_mailing_street(original_row["CMTE_ST1"], "AMENDMENT"),
    }
    fixture_path = tmp_path / "cm_single_batch_amendment.txt"
    _write_fixture_file(fixture_path, CM_COLUMNS, [original_row, amended_row])

    result = load_committees(
        bulk_loader_conn,
        fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=100,
    )
    source_record_key = f"cm:{_PRIMARY_CYCLE}:{original_row['CMTE_ID']}"

    with bulk_loader_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, superseded_by, raw_fields ->> 'CMTE_NM' AS committee_name
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            ORDER BY created_at, id
            """,
            (data_source_id, source_record_key),
        )
        source_rows = cursor.fetchall()

    assert (result.inserted, result.skipped, result.errors) == (2, 0, 0)
    assert len(source_rows) == 2

    superseded_row = next(row for row in source_rows if row["superseded_by"] is not None)
    active_row = next(row for row in source_rows if row["superseded_by"] is None)
    assert superseded_row["superseded_by"] == active_row["id"]
    assert superseded_row["committee_name"] == original_row["CMTE_NM"]
    assert active_row["committee_name"] == amended_row["CMTE_NM"]


def test_load_committees_drops_invalid_real_world_state_code(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    invalid_state_row = {
        **bulk_loader_fixture_set.committee_rows[0],
        "CMTE_ID": f"{bulk_loader_fixture_set.committee_rows[0]['CMTE_ID'][:4]}99999",
        "CMTE_ST1": _rewrite_mailing_street(bulk_loader_fixture_set.committee_rows[0]["CMTE_ST1"], "INVALID-STATE"),
        "CMTE_ST": "14",
    }
    committee_path = tmp_path / "cm_invalid_state.txt"
    _write_fixture_file(committee_path, CM_COLUMNS, [invalid_state_row])

    result = load_committees(
        bulk_loader_conn,
        committee_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )

    assert (result.inserted, result.skipped, result.errors) == (1, 0, 0)

    with bulk_loader_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT committee.state AS committee_state,
                   address.state AS address_state,
                   address.raw_address
            FROM cf.committee committee
            JOIN core.organization organization
              ON organization.id = committee.organization_id
            JOIN core.entity_address entity_address
              ON entity_address.entity_type = 'organization'
             AND entity_address.entity_id = organization.id
            JOIN core.address address
              ON address.id = entity_address.address_id
            WHERE committee.fec_committee_id = %s
            """,
            (invalid_state_row["CMTE_ID"],),
        )
        stored_row = cursor.fetchone()

    assert stored_row is not None
    assert stored_row["committee_state"] is None
    assert stored_row["address_state"] is None
    assert f"{invalid_state_row['CMTE_CITY']} 14 " not in stored_row["raw_address"]


def test_load_candidates_resolves_principal_committee_and_is_idempotent(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    load_committees(
        bulk_loader_conn,
        bulk_loader_fixture_set.committee_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )

    first_result = load_candidates(
        bulk_loader_conn,
        bulk_loader_fixture_set.candidate_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )
    second_result = load_candidates(
        bulk_loader_conn,
        bulk_loader_fixture_set.candidate_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )

    assert (first_result.inserted, first_result.skipped, first_result.errors) == (5, 0, 0)
    assert (second_result.inserted, second_result.skipped, second_result.errors) == (0, 5, 0)

    _assert_candidate_rows(bulk_loader_conn, bulk_loader_fixture_set.candidate_rows)
    _assert_person_rows(bulk_loader_conn, bulk_loader_fixture_set.candidate_rows)
    _assert_candidate_addresses(bulk_loader_conn, bulk_loader_fixture_set.candidate_rows)


def test_load_candidate_summaries_updates_existing_candidates_and_skips_unresolved(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    _load_committees_and_candidates(bulk_loader_conn, bulk_loader_fixture_set, data_source_id)
    scenario = _build_candidate_summary_scenario(bulk_loader_fixture_set, tmp_path)

    first_result = load_candidate_summaries(
        bulk_loader_conn,
        scenario.fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )
    second_result = load_candidate_summaries(
        bulk_loader_conn,
        scenario.fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )
    third_result = load_candidate_summaries(
        bulk_loader_conn,
        scenario.updated_fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )

    assert (first_result.inserted, first_result.skipped, first_result.errors) == (5, 1, 0)
    assert (second_result.inserted, second_result.skipped, second_result.errors) == (0, 6, 0)
    assert (third_result.inserted, third_result.skipped, third_result.errors) == (1, 5, 0)

    summary_result = _fetch_candidate_summary_rows(
        bulk_loader_conn,
        data_source_id=data_source_id,
        candidate_ids=bulk_loader_fixture_set.candidate_ids,
        unresolved_candidate_id=scenario.unresolved_candidate_id,
    )
    summary_rows, unresolved_candidate_count, unresolved_person_count, updated_source_record_count = summary_result
    changed_source_rows = _fetch_weball_source_record_rows(
        bulk_loader_conn,
        data_source_id=data_source_id,
        candidate_id=scenario.changed_candidate_id,
    )
    summary_by_candidate_id = _assert_candidate_summary_rows(
        summary_rows=summary_rows,
        fixture_set=bulk_loader_fixture_set,
        scenario=scenario,
    )

    assert unresolved_candidate_count == 0
    assert unresolved_person_count == 0
    assert updated_source_record_count == 2
    assert summary_by_candidate_id[scenario.blank_self_funding_candidate_id]["candidate_contrib"] is None
    assert summary_by_candidate_id[scenario.blank_self_funding_candidate_id]["candidate_loans"] is None
    assert summary_by_candidate_id[scenario.blank_self_funding_candidate_id]["candidate_loan_repay"] is None
    _assert_changed_weball_source_records(source_rows=changed_source_rows, scenario=scenario)


def test_load_candidate_committee_links_skips_unresolved_foreign_keys_and_is_idempotent(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    _load_committees_and_candidates(bulk_loader_conn, bulk_loader_fixture_set, data_source_id)

    ccl_rows = [dict(row) for row in bulk_loader_fixture_set.ccl_rows]
    unresolved_candidate_id = f"H{uuid4().hex[:8].upper()}"
    unresolved_linkage_id = f"{uuid4().int % 10**12:012d}"
    ccl_rows.append(
        {
            **ccl_rows[0],
            "CAND_ID": unresolved_candidate_id,
            "LINKAGE_ID": unresolved_linkage_id,
        }
    )
    fixture_path = tmp_path / "ccl_with_unresolved_fk.txt"
    _write_fixture_file(fixture_path, CCL_COLUMNS, ccl_rows)

    first_result = load_candidate_committee_links(
        bulk_loader_conn,
        fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )
    second_result = load_candidate_committee_links(
        bulk_loader_conn,
        fixture_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )

    assert (first_result.inserted, first_result.skipped, first_result.errors) == (5, 1, 0)
    assert (second_result.inserted, second_result.skipped, second_result.errors) == (0, 6, 0)

    link_rows = _fetch_link_rows(bulk_loader_conn, data_source_id, bulk_loader_fixture_set.linkage_ids)
    assert len(link_rows) == 5
    for row in link_rows:
        assert row["candidate_election_year"] == 2024
        assert row["fec_election_year"] == 2024
        assert row["period_start"] == date(2024, 1, 1)
        assert row["period_end"] == date(2025, 1, 1)
        assert row["lower_inclusive"] is True
        assert row["upper_inclusive"] is False
