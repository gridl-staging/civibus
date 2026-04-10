from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import get_connection
from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.dark_money.download import extract_irs_527_txt
from domains.campaign_finance.ingest.dark_money.loader import ensure_irs_527_data_source, load_irs_527_records
from domains.campaign_finance.ingest.dark_money.parser import read_irs_527_records
from domains.campaign_finance.types import Contribution527, Expenditure527, Filing8872, PoliticalOrganization527

pytestmark = pytest.mark.integration

_FIXTURE_ZIP = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "bulk" / "irs_527_sample.zip"
_POSTGRES_UNAVAILABLE_PREFIX = "Unable to connect to PostgreSQL at "


@pytest.fixture
def irs_527_conn() -> psycopg.Connection:
    os.environ.setdefault("POSTGRES_PASSWORD", "civibus_dev")
    try:
        connection = get_connection()
    except RuntimeError as error:
        if str(error).startswith(_POSTGRES_UNAVAILABLE_PREFIX):
            pytest.skip(str(error))
        raise
    try:
        yield connection
    finally:
        connection.close()


def _extract_fixture_txt(tmp_path: Path) -> Path:
    return extract_irs_527_txt(_FIXTURE_ZIP, tmp_path)


def _sample_key_sets(txt_path: Path) -> dict[str, list[str]]:
    eins: list[str] = []
    form_ids: list[str] = []
    sched_a_ids: list[str] = []
    sched_b_ids: list[str] = []

    for record in read_irs_527_records(txt_path):
        if isinstance(record, PoliticalOrganization527):
            eins.append(record.ein)
        elif isinstance(record, Filing8872):
            form_ids.append(record.form_id_number)
        elif isinstance(record, Contribution527):
            sched_a_ids.append(record.sched_a_id)
        elif isinstance(record, Expenditure527):
            sched_b_ids.append(record.sched_b_id)

    return {
        "eins": sorted(set(eins)),
        "form_ids": sorted(set(form_ids)),
        "sched_a_ids": sorted(set(sched_a_ids)),
        "sched_b_ids": sorted(set(sched_b_ids)),
    }


def _cleanup_loaded_rows(
    conn: psycopg.Connection,
    *,
    data_source_id: object,
    key_sets: dict[str, list[str]],
) -> None:
    with conn.cursor() as cursor:
        if key_sets["sched_b_ids"]:
            cursor.execute(
                "DELETE FROM cf.expenditure_527 WHERE sched_b_id = ANY(%s)",
                (key_sets["sched_b_ids"],),
            )
        if key_sets["sched_a_ids"]:
            cursor.execute(
                "DELETE FROM cf.contribution_527 WHERE sched_a_id = ANY(%s)",
                (key_sets["sched_a_ids"],),
            )
        if key_sets["form_ids"]:
            cursor.execute(
                "DELETE FROM cf.filing_8872 WHERE form_id_number = ANY(%s)",
                (key_sets["form_ids"],),
            )
        if key_sets["eins"]:
            cursor.execute(
                "DELETE FROM cf.political_organization_527 WHERE ein = ANY(%s)",
                (key_sets["eins"],),
            )

        cursor.execute(
            """
            DELETE FROM core.source_record
            WHERE data_source_id = %s
              AND (
                (raw_fields ? 'ein' AND raw_fields->>'ein' = ANY(%s))
                OR (raw_fields ? 'form_id_number' AND raw_fields->>'form_id_number' = ANY(%s))
                OR (raw_fields ? 'sched_a_id' AND raw_fields->>'sched_a_id' = ANY(%s))
                OR (raw_fields ? 'sched_b_id' AND raw_fields->>'sched_b_id' = ANY(%s))
              )
            """,
            (
                data_source_id,
                key_sets["eins"],
                key_sets["form_ids"],
                key_sets["sched_a_ids"],
                key_sets["sched_b_ids"],
            ),
        )
    conn.commit()


def test_ensure_irs_527_data_source_is_idempotent(db_conn: psycopg.Connection) -> None:
    first_id = ensure_irs_527_data_source(db_conn)
    second_id = ensure_irs_527_data_source(db_conn)

    assert first_id == second_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT domain, jurisdiction, name, source_url, source_format
            FROM core.data_source
            WHERE id = %s
            """,
            (first_id,),
        )
        row = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.data_source
            WHERE domain = 'campaign_finance'
              AND jurisdiction = 'federal/irs_527'
              AND name = 'IRS Form 8872 Political Organizations'
            """,
        )
        count_row = cursor.fetchone()

    assert row is not None
    assert row["domain"] == "campaign_finance"
    assert row["jurisdiction"] == "federal/irs_527"
    assert row["name"] == "IRS Form 8872 Political Organizations"
    assert row["source_url"] == "https://forms.irs.gov/app/pod/dataDownload/fullData"
    assert row["source_format"] == "pipe_delimited"
    assert count_row["count"] == 1


def test_load_irs_527_records_inserts_fixture_rows(
    irs_527_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    txt_path = _extract_fixture_txt(tmp_path)
    key_sets = _sample_key_sets(txt_path)

    data_source_id = ensure_irs_527_data_source(irs_527_conn)
    irs_527_conn.commit()

    _cleanup_loaded_rows(irs_527_conn, data_source_id=data_source_id, key_sets=key_sets)

    try:
        records = list(read_irs_527_records(txt_path))

        result = load_irs_527_records(
            irs_527_conn,
            txt_path,
            data_source_id=data_source_id,
            batch_size=2,
            limit=None,
        )

        assert isinstance(result, LoadResult)
        assert result.inserted == len(records)
        assert result.skipped == 0
        assert result.errors == 0

        with irs_527_conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS count FROM cf.political_organization_527 WHERE ein = ANY(%s)",
                (key_sets["eins"],),
            )
            org_count = cursor.fetchone()["count"]

            cursor.execute(
                "SELECT COUNT(*) AS count FROM cf.filing_8872 WHERE form_id_number = ANY(%s)",
                (key_sets["form_ids"],),
            )
            filing_count = cursor.fetchone()["count"]

            cursor.execute(
                "SELECT COUNT(*) AS count FROM cf.contribution_527 WHERE sched_a_id = ANY(%s)",
                (key_sets["sched_a_ids"],),
            )
            contribution_count = cursor.fetchone()["count"]

            cursor.execute(
                "SELECT COUNT(*) AS count FROM cf.expenditure_527 WHERE sched_b_id = ANY(%s)",
                (key_sets["sched_b_ids"],),
            )
            expenditure_count = cursor.fetchone()["count"]

            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM core.source_record
                WHERE data_source_id = %s
                  AND (
                    (raw_fields ? 'ein' AND raw_fields->>'ein' = ANY(%s))
                    OR (raw_fields ? 'form_id_number' AND raw_fields->>'form_id_number' = ANY(%s))
                    OR (raw_fields ? 'sched_a_id' AND raw_fields->>'sched_a_id' = ANY(%s))
                    OR (raw_fields ? 'sched_b_id' AND raw_fields->>'sched_b_id' = ANY(%s))
                  )
                """,
                (
                    data_source_id,
                    key_sets["eins"],
                    key_sets["form_ids"],
                    key_sets["sched_a_ids"],
                    key_sets["sched_b_ids"],
                ),
            )
            source_record_count = cursor.fetchone()["count"]

        assert org_count == len(key_sets["eins"])
        assert filing_count == len(key_sets["form_ids"])
        assert contribution_count == len(key_sets["sched_a_ids"])
        assert expenditure_count == len(key_sets["sched_b_ids"])
        assert source_record_count == len(records)
    finally:
        _cleanup_loaded_rows(irs_527_conn, data_source_id=data_source_id, key_sets=key_sets)


def test_load_irs_527_records_counts_duplicate_natural_keys_as_skips(
    irs_527_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    txt_path = _extract_fixture_txt(tmp_path)
    base_records = list(read_irs_527_records(txt_path))
    duplicated_records = base_records + [record.model_copy() for record in base_records]
    key_sets = _sample_key_sets(txt_path)

    data_source_id = ensure_irs_527_data_source(irs_527_conn)
    irs_527_conn.commit()
    _cleanup_loaded_rows(irs_527_conn, data_source_id=data_source_id, key_sets=key_sets)

    monkeypatch.setattr(
        "domains.campaign_finance.ingest.dark_money.loader.read_irs_527_records",
        lambda _txt_path: iter(duplicated_records),
    )

    try:
        result = load_irs_527_records(
            irs_527_conn,
            txt_path,
            data_source_id=data_source_id,
            batch_size=100,
            limit=None,
        )

        assert result.inserted == len(base_records)
        assert result.skipped == len(base_records)
        assert result.errors == 0
    finally:
        _cleanup_loaded_rows(irs_527_conn, data_source_id=data_source_id, key_sets=key_sets)


def test_load_irs_527_records_updates_existing_org_on_changed_type_1_row(
    irs_527_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    txt_path = _extract_fixture_txt(tmp_path)
    base_records = list(read_irs_527_records(txt_path))
    original_org = next(record for record in base_records if isinstance(record, PoliticalOrganization527))
    amended_org = original_org.model_copy(update={"name": f"{original_org.name} AMENDED"})
    amended_records = base_records + [amended_org]
    key_sets = _sample_key_sets(txt_path)

    data_source_id = ensure_irs_527_data_source(irs_527_conn)
    irs_527_conn.commit()
    _cleanup_loaded_rows(irs_527_conn, data_source_id=data_source_id, key_sets=key_sets)

    monkeypatch.setattr(
        "domains.campaign_finance.ingest.dark_money.loader.read_irs_527_records",
        lambda _txt_path: iter(amended_records),
    )

    try:
        result = load_irs_527_records(
            irs_527_conn,
            txt_path,
            data_source_id=data_source_id,
            batch_size=100,
            limit=None,
        )

        assert result.inserted == len(amended_records)
        assert result.skipped == 0
        assert result.errors == 0

        source_record_key = f"irs_527:1:{original_org.ein}"
        with irs_527_conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT name, source_record_id
                FROM cf.political_organization_527
                WHERE ein = %s
                """,
                (original_org.ein,),
            )
            org_row = cursor.fetchone()
            cursor.execute(
                """
                SELECT id, raw_fields->>'name' AS name, superseded_by
                FROM core.source_record
                WHERE data_source_id = %s
                  AND source_record_key = %s
                ORDER BY created_at, id
                """,
                (data_source_id, source_record_key),
            )
            source_rows = cursor.fetchall()

        assert org_row is not None
        assert org_row["name"] == amended_org.name
        assert len(source_rows) == 2

        original_source_row, active_source_row = source_rows
        assert original_source_row["name"] == original_org.name
        assert original_source_row["superseded_by"] == active_source_row["id"]
        assert active_source_row["name"] == amended_org.name
        assert active_source_row["superseded_by"] is None
        assert org_row["source_record_id"] == active_source_row["id"]
    finally:
        _cleanup_loaded_rows(irs_527_conn, data_source_id=data_source_id, key_sets=key_sets)
