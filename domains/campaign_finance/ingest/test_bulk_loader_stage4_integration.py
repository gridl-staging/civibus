from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import insert_organization
from core.types.python.models import Organization
from domains.campaign_finance.ingest.bulk_loader import (
    ensure_fec_bulk_data_source,
    load_candidates,
    load_committee_transactions,
    load_committees,
    load_contributions,
)
from domains.campaign_finance.ingest.bulk_parser import ITCONT_COLUMNS, ITPAS2_COLUMNS
from domains.campaign_finance.ingest.test_bulk_loader_integration import (
    _COMMITTEE_FIXTURE_PATH,
    _CANDIDATE_FIXTURE_PATH,
    _PRIMARY_CYCLE,
    _delete_rows,
    _read_fixture_rows,
    _select_bulk_data_source_id,
    _select_source_record_ids,
    _write_fixture_file,
    BulkLoaderFixtureSet,
    bulk_loader_conn as _bulk_loader_conn_fixture,
    bulk_loader_fixture_set as _bulk_loader_fixture_set,
)

_SHARED_STAGE4_FIXTURES = (_bulk_loader_conn_fixture, _bulk_loader_fixture_set)

pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bulk"
_ITCONT_FIXTURE_PATH = _FIXTURE_DIR / "itcont_sample.txt"
_ITPAS2_FIXTURE_PATH = _FIXTURE_DIR / "itpas2_sample.txt"


@dataclass(frozen=True, slots=True)
class Stage4FixtureSet:
    itcont_path: Path
    itpas2_path: Path
    itcont_rows: list[dict[str, str | None]]
    itpas2_rows: list[dict[str, str | None]]

    @property
    def contribution_sub_ids(self) -> list[str]:
        return [row["SUB_ID"] for row in self.itcont_rows if row["SUB_ID"] is not None]

    @property
    def committee_transaction_sub_ids(self) -> list[str]:
        return [row["SUB_ID"] for row in self.itpas2_rows if row["SUB_ID"] is not None]


def _build_stage4_fixture_prefix() -> str:
    return str(uuid4().int % 900 + 100)


def _make_unique_sub_id(base_sub_id: str | None, fixture_prefix: str, row_index: int) -> str | None:
    if base_sub_id is None:
        return None
    if not base_sub_id.isdigit():
        return base_sub_id

    replacement_suffix = f"{fixture_prefix}{row_index:03d}"
    if len(base_sub_id) <= len(replacement_suffix):
        return replacement_suffix
    return f"{base_sub_id[: -len(replacement_suffix)]}{replacement_suffix}"


def _materialize_stage4_fixture_set(tmp_path: Path, bulk_fixture_set: BulkLoaderFixtureSet) -> Stage4FixtureSet:
    fixture_prefix = _build_stage4_fixture_prefix()

    original_committee_rows = _read_fixture_rows(_COMMITTEE_FIXTURE_PATH, "cm")
    original_candidate_rows = _read_fixture_rows(_CANDIDATE_FIXTURE_PATH, "cn")

    committee_id_map = {
        original_row["CMTE_ID"]: unique_row["CMTE_ID"]
        for original_row, unique_row in zip(original_committee_rows, bulk_fixture_set.committee_rows, strict=True)
        if original_row["CMTE_ID"] is not None and unique_row["CMTE_ID"] is not None
    }
    candidate_id_map = {
        original_row["CAND_ID"]: unique_row["CAND_ID"]
        for original_row, unique_row in zip(original_candidate_rows, bulk_fixture_set.candidate_rows, strict=True)
        if original_row["CAND_ID"] is not None and unique_row["CAND_ID"] is not None
    }

    original_itcont_rows = _read_fixture_rows(_ITCONT_FIXTURE_PATH, "itcont")
    original_itpas2_rows = _read_fixture_rows(_ITPAS2_FIXTURE_PATH, "itpas2")

    itcont_rows = [
        {
            **row,
            "CMTE_ID": committee_id_map.get(row["CMTE_ID"], row["CMTE_ID"]),
            "OTHER_ID": committee_id_map.get(row["OTHER_ID"], row["OTHER_ID"]),
            "SUB_ID": _make_unique_sub_id(row["SUB_ID"], fixture_prefix, index),
        }
        for index, row in enumerate(original_itcont_rows, start=1)
    ]

    itpas2_rows = [
        {
            **row,
            "CMTE_ID": committee_id_map.get(row["CMTE_ID"], row["CMTE_ID"]),
            "CAND_ID": candidate_id_map.get(row["CAND_ID"], row["CAND_ID"]),
            "OTHER_ID": committee_id_map.get(row["OTHER_ID"], row["OTHER_ID"]),
            "SUB_ID": _make_unique_sub_id(row["SUB_ID"], fixture_prefix, index),
        }
        for index, row in enumerate(original_itpas2_rows, start=1)
    ]

    itcont_path = tmp_path / "itcont_stage4_unique.txt"
    itpas2_path = tmp_path / "itpas2_stage4_unique.txt"
    _write_fixture_file(itcont_path, ITCONT_COLUMNS, itcont_rows)
    _write_fixture_file(itpas2_path, ITPAS2_COLUMNS, itpas2_rows)

    return Stage4FixtureSet(
        itcont_path=itcont_path,
        itpas2_path=itpas2_path,
        itcont_rows=itcont_rows,
        itpas2_rows=itpas2_rows,
    )


def _select_entity_ids_by_source(
    conn: psycopg.Connection,
    source_record_ids: Sequence[UUID],
    *,
    entity_type: str,
) -> list[UUID]:
    if not source_record_ids:
        return []

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT entity_id
            FROM core.entity_source
            WHERE entity_type = %s
              AND source_record_id = ANY(%s)
            """,
            (entity_type, list(source_record_ids)),
        )
        return [row[0] for row in cursor.fetchall()]


def _delete_stage4_entity_rows(conn: psycopg.Connection, source_record_ids: Sequence[UUID]) -> None:
    if not source_record_ids:
        return

    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM cf.transaction WHERE source_record_id = ANY(%s)", (list(source_record_ids),))
        cursor.execute("DELETE FROM cf.filing WHERE source_record_id = ANY(%s)", (list(source_record_ids),))
        cursor.execute("DELETE FROM core.entity_address WHERE source_record_id = ANY(%s)", (list(source_record_ids),))
        cursor.execute("DELETE FROM core.entity_source WHERE source_record_id = ANY(%s)", (list(source_record_ids),))
        cursor.execute("DELETE FROM core.source_record WHERE id = ANY(%s)", (list(source_record_ids),))


def _count_stage4_relational_rows(conn: psycopg.Connection, source_record_ids: Sequence[UUID]) -> tuple[int, int]:
    if not source_record_ids:
        return 0, 0

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS row_count FROM cf.filing WHERE source_record_id = ANY(%s)",
            (list(source_record_ids),),
        )
        filing_count = cursor.fetchone()["row_count"]
        cursor.execute(
            "SELECT COUNT(*) AS row_count FROM cf.transaction WHERE source_record_id = ANY(%s)",
            (list(source_record_ids),),
        )
        transaction_count = cursor.fetchone()["row_count"]
    return filing_count, transaction_count


def _select_stage4_transaction_links(
    conn: psycopg.Connection,
    source_record_ids: Sequence[UUID],
) -> list[dict[str, object]]:
    if not source_record_ids:
        return []

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT transaction_row.id AS transaction_id,
                   transaction_row.source_record_id AS transaction_source_record_id,
                   filing.id AS filing_id,
                   filing.source_record_id AS filing_source_record_id
            FROM cf.transaction transaction_row
            JOIN cf.filing filing
              ON filing.id = transaction_row.filing_id
            WHERE transaction_row.source_record_id = ANY(%s)
            ORDER BY transaction_row.source_record_id
            """,
            (list(source_record_ids),),
        )
        return list(cursor.fetchall())


def _assert_no_stage4_relational_leakage(
    conn: psycopg.Connection,
    stage4_fixture_set: Stage4FixtureSet,
) -> None:
    data_source_id = _select_bulk_data_source_id(conn)
    if data_source_id is None:
        return

    source_record_ids = _select_source_record_ids(
        conn,
        data_source_id,
        [*stage4_fixture_set.contribution_sub_ids, *stage4_fixture_set.committee_transaction_sub_ids],
    )
    filing_count, transaction_count = _count_stage4_relational_rows(conn, source_record_ids)
    assert filing_count == 0
    assert transaction_count == 0


def _delete_orphan_people(conn: psycopg.Connection, person_ids: Sequence[UUID]) -> None:
    if not person_ids:
        return

    with conn.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM core.person person
            WHERE person.id = ANY(%s)
              AND NOT EXISTS (
                  SELECT 1
                  FROM core.entity_source entity_source
                  WHERE entity_source.entity_type = 'person'
                    AND entity_source.entity_id = person.id
              )
            """,
            (list(person_ids),),
        )


def _delete_orphan_addresses(conn: psycopg.Connection, address_ids: Sequence[UUID]) -> None:
    if not address_ids:
        return

    with conn.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM core.address address
            WHERE address.id = ANY(%s)
              AND NOT EXISTS (
                  SELECT 1
                  FROM core.entity_source entity_source
                  WHERE entity_source.entity_type = 'address'
                    AND entity_source.entity_id = address.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM core.entity_address entity_address
                  WHERE entity_address.address_id = address.id
              )
            """,
            (list(address_ids),),
        )


def _delete_orphan_organizations(conn: psycopg.Connection, organization_ids: Sequence[UUID]) -> None:
    if not organization_ids:
        return

    with conn.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM core.organization organization
            WHERE organization.id = ANY(%s)
              AND NOT EXISTS (
                  SELECT 1
                  FROM core.entity_source entity_source
                  WHERE entity_source.entity_type = 'organization'
                    AND entity_source.entity_id = organization.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM core.entity_address entity_address
                  WHERE entity_address.entity_type = 'organization'
                    AND entity_address.entity_id = organization.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM cf.committee committee
                  WHERE committee.organization_id = organization.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM cf.transaction transaction_row
                  WHERE transaction_row.contributor_organization_id = organization.id
              )
            """,
            (list(organization_ids),),
        )


def _cleanup_stage4_rows(
    conn: psycopg.Connection,
    stage4_fixture_set: Stage4FixtureSet,
) -> None:
    data_source_id = _select_bulk_data_source_id(conn)
    source_record_ids = _select_source_record_ids(
        conn,
        data_source_id,
        [*stage4_fixture_set.contribution_sub_ids, *stage4_fixture_set.committee_transaction_sub_ids],
    )

    person_ids = _select_entity_ids_by_source(conn, source_record_ids, entity_type="person")
    address_ids = _select_entity_ids_by_source(conn, source_record_ids, entity_type="address")
    organization_ids = _select_entity_ids_by_source(conn, source_record_ids, entity_type="organization")

    _delete_stage4_entity_rows(conn, source_record_ids)
    _delete_orphan_people(conn, person_ids)
    _delete_orphan_addresses(conn, address_ids)
    _delete_orphan_organizations(conn, organization_ids)


@pytest.fixture
def bulk_loader_conn_fixture(request: pytest.FixtureRequest) -> psycopg.Connection:
    return request.getfixturevalue("_bulk_loader_conn_fixture")


@pytest.fixture
def bulk_loader_fixture_set_fixture(request: pytest.FixtureRequest) -> BulkLoaderFixtureSet:
    return request.getfixturevalue("_bulk_loader_fixture_set")


@pytest.fixture(name="bulk_loader_conn")
def _bulk_loader_conn_alias(
    bulk_loader_conn_fixture: psycopg.Connection,
) -> psycopg.Connection:
    return bulk_loader_conn_fixture


@pytest.fixture(name="bulk_loader_fixture_set")
def _bulk_loader_fixture_set_alias(
    bulk_loader_fixture_set_fixture: BulkLoaderFixtureSet,
) -> BulkLoaderFixtureSet:
    return bulk_loader_fixture_set_fixture


@pytest.fixture
def stage4_fixture_set(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    tmp_path: Path,
) -> Iterator[Stage4FixtureSet]:
    fixture_set = _materialize_stage4_fixture_set(tmp_path, bulk_loader_fixture_set)
    try:
        yield fixture_set
    finally:
        _cleanup_stage4_rows(bulk_loader_conn, fixture_set)
        bulk_loader_conn.commit()


def _load_stage3_committees(
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


def _load_stage3_committees_and_candidates(
    conn: psycopg.Connection,
    fixture_set: BulkLoaderFixtureSet,
    data_source_id: UUID,
) -> None:
    _load_stage3_committees(conn, fixture_set, data_source_id)
    load_candidates(
        conn,
        fixture_set.candidate_path,
        cycle=_PRIMARY_CYCLE,
        data_source_id=data_source_id,
        batch_size=2,
    )


def test_cleanup_stage4_rows_deletes_orphan_organizations(monkeypatch: pytest.MonkeyPatch) -> None:
    stage4_integration = sys.modules[__name__]
    conn = pytest.importorskip("unittest.mock").MagicMock()
    source_record_ids = [uuid4()]
    person_ids = [uuid4()]
    address_ids = [uuid4()]
    organization_ids = [uuid4(), uuid4()]
    stage4_fixture_set = Stage4FixtureSet(
        itcont_path=Path("itcont.txt"),
        itpas2_path=Path("itpas2.txt"),
        itcont_rows=[{"SUB_ID": "11"}],
        itpas2_rows=[{"SUB_ID": "22"}],
    )
    delete_stage4_entity_rows = pytest.importorskip("unittest.mock").MagicMock()
    delete_orphan_people = pytest.importorskip("unittest.mock").MagicMock()
    delete_orphan_addresses = pytest.importorskip("unittest.mock").MagicMock()
    delete_orphan_organizations = pytest.importorskip("unittest.mock").MagicMock()
    requested_entity_types: list[str] = []

    monkeypatch.setattr(
        stage4_integration,
        "_select_bulk_data_source_id",
        lambda _conn: uuid4(),
    )
    monkeypatch.setattr(
        stage4_integration,
        "_select_source_record_ids",
        lambda _conn, _data_source_id, _source_record_keys: source_record_ids,
    )

    def _fake_select_entity_ids_by_source(
        _conn: psycopg.Connection,
        _source_record_ids: Sequence[UUID],
        *,
        entity_type: str,
    ) -> list[UUID]:
        requested_entity_types.append(entity_type)
        if entity_type == "person":
            return person_ids
        if entity_type == "address":
            return address_ids
        if entity_type == "organization":
            return organization_ids
        raise AssertionError(f"Unexpected entity type: {entity_type}")

    monkeypatch.setattr(stage4_integration, "_select_entity_ids_by_source", _fake_select_entity_ids_by_source)
    monkeypatch.setattr(stage4_integration, "_delete_stage4_entity_rows", delete_stage4_entity_rows)
    monkeypatch.setattr(stage4_integration, "_delete_orphan_people", delete_orphan_people)
    monkeypatch.setattr(stage4_integration, "_delete_orphan_addresses", delete_orphan_addresses)
    monkeypatch.setattr(stage4_integration, "_delete_orphan_organizations", delete_orphan_organizations)

    _cleanup_stage4_rows(conn, stage4_fixture_set)

    assert requested_entity_types == ["person", "address", "organization"]
    delete_stage4_entity_rows.assert_called_once_with(conn, source_record_ids)
    delete_orphan_people.assert_called_once_with(conn, person_ids)
    delete_orphan_addresses.assert_called_once_with(conn, address_ids)
    delete_orphan_organizations.assert_called_once_with(conn, organization_ids)


def test_load_contributions_is_idempotent(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    _load_stage3_committees(bulk_loader_conn, bulk_loader_fixture_set, data_source_id)

    first_result = load_contributions(
        bulk_loader_conn,
        stage4_fixture_set.itcont_path,
        data_source_id=data_source_id,
        batch_size=2,
    )
    second_result = load_contributions(
        bulk_loader_conn,
        stage4_fixture_set.itcont_path,
        data_source_id=data_source_id,
        batch_size=2,
    )

    expected_row_count = len(stage4_fixture_set.itcont_rows)
    assert (first_result.inserted, first_result.skipped, first_result.errors) == (expected_row_count, 0, 0)
    assert (second_result.inserted, second_result.skipped, second_result.errors) == (0, expected_row_count, 0)

    source_record_ids = _select_source_record_ids(
        bulk_loader_conn,
        data_source_id,
        stage4_fixture_set.contribution_sub_ids,
    )
    assert len(source_record_ids) == expected_row_count


def test_load_contributions_reuses_preloaded_committee_organizations(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    _load_stage3_committees(bulk_loader_conn, bulk_loader_fixture_set, data_source_id)

    load_contributions(
        bulk_loader_conn,
        stage4_fixture_set.itcont_path,
        data_source_id=data_source_id,
        batch_size=2,
    )

    expected_names_by_committee_id = {
        row["CMTE_ID"]: row["CMTE_NM"]
        for row in bulk_loader_fixture_set.committee_rows
        if row["CMTE_ID"] is not None and row["CMTE_NM"] is not None
    }
    committee_ids = [row["CMTE_ID"] for row in stage4_fixture_set.itcont_rows if row["CMTE_ID"] is not None]

    with bulk_loader_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT identifiers ->> 'fec_committee_id' AS fec_committee_id,
                   COUNT(*) AS organization_count,
                   MIN(canonical_name) AS canonical_name
            FROM core.organization
            WHERE identifiers ->> 'fec_committee_id' = ANY(%s)
            GROUP BY identifiers ->> 'fec_committee_id'
            ORDER BY identifiers ->> 'fec_committee_id'
            """,
            (committee_ids,),
        )
        organization_rows = cursor.fetchall()

    assert len(organization_rows) == len(set(committee_ids))
    for organization_row in organization_rows:
        committee_id = organization_row["fec_committee_id"]
        assert organization_row["organization_count"] == 1
        assert organization_row["canonical_name"] == expected_names_by_committee_id[committee_id]
        assert organization_row["canonical_name"] != ""


def test_load_contributions_requires_preloaded_committees(
    bulk_loader_conn: psycopg.Connection,
    stage4_fixture_set: Stage4FixtureSet,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)

    result = load_contributions(
        bulk_loader_conn,
        stage4_fixture_set.itcont_path,
        data_source_id=data_source_id,
        batch_size=2,
    )

    expected_row_count = len(stage4_fixture_set.itcont_rows)
    committee_ids = [row["CMTE_ID"] for row in stage4_fixture_set.itcont_rows if row["CMTE_ID"] is not None]

    assert (result.inserted, result.skipped, result.errors) == (0, 0, expected_row_count)
    assert (
        _select_source_record_ids(
            bulk_loader_conn,
            data_source_id,
            stage4_fixture_set.contribution_sub_ids,
        )
        == []
    )

    with bulk_loader_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM core.organization
            WHERE identifiers ->> 'fec_committee_id' = ANY(%s)
            """,
            (committee_ids,),
        )
        organization_count = cursor.fetchone()[0]

    assert organization_count == 0


def test_load_contributions_rejects_blank_placeholder_committee_organization(
    bulk_loader_conn: psycopg.Connection,
    stage4_fixture_set: Stage4FixtureSet,
    tmp_path: Path,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    placeholder_row = stage4_fixture_set.itcont_rows[0]
    committee_id = placeholder_row["CMTE_ID"]
    sub_id = placeholder_row["SUB_ID"]

    assert committee_id is not None
    assert sub_id is not None

    placeholder_organization_id = insert_organization(
        bulk_loader_conn,
        Organization(canonical_name="", identifiers={"fec_committee_id": committee_id}),
    )
    placeholder_path = tmp_path / "itcont_placeholder_guard.txt"
    _write_fixture_file(placeholder_path, ITCONT_COLUMNS, [placeholder_row])
    bulk_loader_conn.commit()

    try:
        result = load_contributions(
            bulk_loader_conn,
            placeholder_path,
            data_source_id=data_source_id,
            batch_size=2,
        )

        assert (result.inserted, result.skipped, result.errors) == (0, 0, 1)
        assert _select_source_record_ids(bulk_loader_conn, data_source_id, [sub_id]) == []

        with bulk_loader_conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT canonical_name FROM core.organization WHERE id = %s", (placeholder_organization_id,))
            organization_row = cursor.fetchone()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM core.entity_source
                WHERE entity_type = 'organization'
                  AND entity_id = %s
                """,
                (placeholder_organization_id,),
            )
            entity_source_count = cursor.fetchone()["count"]

        assert organization_row is not None
        assert organization_row["canonical_name"] == ""
        assert entity_source_count == 0
    finally:
        _delete_rows(
            bulk_loader_conn,
            "DELETE FROM core.organization WHERE identifiers ->> 'fec_committee_id' = ANY(%s)",
            [committee_id],
        )
        bulk_loader_conn.commit()


def test_load_committee_transactions_is_idempotent_and_preserves_candidate_context(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
) -> None:
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    _load_stage3_committees_and_candidates(bulk_loader_conn, bulk_loader_fixture_set, data_source_id)

    first_result = load_committee_transactions(
        bulk_loader_conn,
        stage4_fixture_set.itpas2_path,
        data_source_id=data_source_id,
        batch_size=2,
    )
    second_result = load_committee_transactions(
        bulk_loader_conn,
        stage4_fixture_set.itpas2_path,
        data_source_id=data_source_id,
        batch_size=2,
    )

    expected_row_count = len(stage4_fixture_set.itpas2_rows)
    assert (first_result.inserted, first_result.skipped, first_result.errors) == (expected_row_count, 0, 0)
    assert (second_result.inserted, second_result.skipped, second_result.errors) == (0, expected_row_count, 0)

    with bulk_loader_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_record_key, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
            ORDER BY source_record_key
            """,
            (data_source_id, stage4_fixture_set.committee_transaction_sub_ids),
        )
        source_records = cursor.fetchall()

    expected_row_by_sub_id = {row["SUB_ID"]: row for row in stage4_fixture_set.itpas2_rows if row["SUB_ID"] is not None}
    assert len(source_records) == expected_row_count

    for source_record in source_records:
        expected_row = expected_row_by_sub_id[source_record["source_record_key"]]
        raw_fields = source_record["raw_fields"]
        assert raw_fields["candidate_fec_id"] == expected_row["CAND_ID"]
        assert raw_fields["other_id"] == expected_row["OTHER_ID"]
        assert raw_fields["transaction_type"] == expected_row["TRANSACTION_TP"]
        assert raw_fields["memo_code"] == expected_row["MEMO_CD"]
        assert raw_fields["memo_text"] == expected_row["MEMO_TEXT"]
        assert raw_fields["transaction_identifier"] == expected_row["TRAN_ID"]


def test_stage4_default_mode_does_not_write_filing_or_transaction_rows(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
) -> None:
    _assert_no_stage4_relational_leakage(bulk_loader_conn, stage4_fixture_set)
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    _load_stage3_committees_and_candidates(bulk_loader_conn, bulk_loader_fixture_set, data_source_id)

    contribution_result = load_contributions(
        bulk_loader_conn,
        stage4_fixture_set.itcont_path,
        data_source_id=data_source_id,
        batch_size=2,
    )
    committee_transaction_result = load_committee_transactions(
        bulk_loader_conn,
        stage4_fixture_set.itpas2_path,
        data_source_id=data_source_id,
        batch_size=2,
    )

    contribution_source_record_ids = _select_source_record_ids(
        bulk_loader_conn,
        data_source_id,
        stage4_fixture_set.contribution_sub_ids,
    )
    committee_transaction_source_record_ids = _select_source_record_ids(
        bulk_loader_conn,
        data_source_id,
        stage4_fixture_set.committee_transaction_sub_ids,
    )

    assert contribution_result.inserted == len(stage4_fixture_set.itcont_rows)
    assert committee_transaction_result.inserted == len(stage4_fixture_set.itpas2_rows)
    assert _count_stage4_relational_rows(bulk_loader_conn, contribution_source_record_ids) == (0, 0)
    assert _count_stage4_relational_rows(bulk_loader_conn, committee_transaction_source_record_ids) == (0, 0)


def test_stage4_transaction_backfill_reuses_existing_provenance_and_sets_source_record_links(
    bulk_loader_conn: psycopg.Connection,
    bulk_loader_fixture_set: BulkLoaderFixtureSet,
    stage4_fixture_set: Stage4FixtureSet,
) -> None:
    _assert_no_stage4_relational_leakage(bulk_loader_conn, stage4_fixture_set)
    data_source_id = ensure_fec_bulk_data_source(bulk_loader_conn)
    _load_stage3_committees_and_candidates(bulk_loader_conn, bulk_loader_fixture_set, data_source_id)

    load_contributions(
        bulk_loader_conn,
        stage4_fixture_set.itcont_path,
        data_source_id=data_source_id,
        batch_size=2,
    )
    load_committee_transactions(
        bulk_loader_conn,
        stage4_fixture_set.itpas2_path,
        data_source_id=data_source_id,
        batch_size=2,
    )

    contribution_backfill_result = load_contributions(
        bulk_loader_conn,
        stage4_fixture_set.itcont_path,
        data_source_id=data_source_id,
        batch_size=2,
        with_transactions=True,
    )
    committee_transaction_backfill_result = load_committee_transactions(
        bulk_loader_conn,
        stage4_fixture_set.itpas2_path,
        data_source_id=data_source_id,
        batch_size=2,
        with_transactions=True,
    )

    all_stage4_sub_ids = [*stage4_fixture_set.contribution_sub_ids, *stage4_fixture_set.committee_transaction_sub_ids]
    all_source_record_ids = _select_source_record_ids(
        bulk_loader_conn,
        data_source_id,
        all_stage4_sub_ids,
    )
    expected_stage4_row_count = len(all_stage4_sub_ids)
    filing_count, transaction_count = _count_stage4_relational_rows(bulk_loader_conn, all_source_record_ids)
    transaction_links = _select_stage4_transaction_links(bulk_loader_conn, all_source_record_ids)

    assert contribution_backfill_result.inserted == len(stage4_fixture_set.itcont_rows)
    assert committee_transaction_backfill_result.inserted == len(stage4_fixture_set.itpas2_rows)
    assert len(all_source_record_ids) == expected_stage4_row_count
    assert filing_count == expected_stage4_row_count
    assert transaction_count == expected_stage4_row_count
    assert len(transaction_links) == expected_stage4_row_count
    assert {row["transaction_source_record_id"] for row in transaction_links} == set(all_source_record_ids)
    assert {row["filing_source_record_id"] for row in transaction_links} == set(all_source_record_ids)
