from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.ingest.bulk_stage4_loader import LoadResult
from domains.campaign_finance.ingest.dark_money import loader as loader_module
from domains.campaign_finance.ingest.dark_money.download import extract_irs_527_txt
from domains.campaign_finance.ingest.dark_money.loader import (
    _json_compatible_raw_fields,
    _source_record_key,
    _validate_batch_size,
    ensure_irs_527_data_source,
    load_irs_527_records,
)
from domains.campaign_finance.ingest.dark_money.parser import read_irs_527_records
from domains.campaign_finance.types import Contribution527, Expenditure527, Filing8872, PoliticalOrganization527

_FIXTURE_ZIP = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "bulk" / "irs_527_sample.zip"
_EXPECTED_FIXTURE_MODEL_COUNTS = {
    "political_organization_527": 2,
    "filing_8872": 1,
    "contribution_527": 1,
    "expenditure_527": 1,
}


class Irs527LoadEnv(NamedTuple):
    conn: psycopg.Connection
    txt_path: Path
    key_sets: dict[str, list[str]]
    data_source_id: UUID


@pytest.fixture
def irs_527_conn(committing_db_conn: psycopg.Connection) -> psycopg.Connection:
    yield committing_db_conn


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


@pytest.fixture
def irs_527_load_env(irs_527_conn: psycopg.Connection, tmp_path: Path) -> Irs527LoadEnv:
    """Common setup/teardown for integration tests that load IRS 527 fixture data."""
    txt_path = _extract_fixture_txt(tmp_path)
    key_sets = _sample_key_sets(txt_path)
    data_source_id = ensure_irs_527_data_source(irs_527_conn)
    irs_527_conn.commit()
    _cleanup_loaded_rows(irs_527_conn, data_source_id=data_source_id, key_sets=key_sets)
    try:
        yield Irs527LoadEnv(conn=irs_527_conn, txt_path=txt_path, key_sets=key_sets, data_source_id=data_source_id)
    finally:
        _cleanup_loaded_rows(irs_527_conn, data_source_id=data_source_id, key_sets=key_sets)


@pytest.mark.unit
@pytest.mark.parametrize("batch_size", [0, -1])
def test_validate_batch_size_rejects_non_positive_values(batch_size: int) -> None:
    with pytest.raises(ValueError, match="batch_size must be greater than zero"):
        _validate_batch_size(batch_size)


@pytest.mark.unit
def test_source_record_key_raises_type_error_for_unsupported_record_type() -> None:
    class UnsupportedRecord:
        pass

    with pytest.raises(TypeError, match="Unsupported IRS 527 record type"):
        _source_record_key(UnsupportedRecord())  # type: ignore[arg-type]


@pytest.mark.unit
def test_json_compatible_raw_fields_coerces_decimal_and_date_types() -> None:
    record = Contribution527(
        form_id_number="200000001",
        sched_a_id="A00001",
        ein="12-3456789",
        contributor_name="JANE DONOR",
        amount=Decimal("5000.00"),
        contribution_date=date(2025, 3, 15),
        aggregate_ytd=Decimal("10000.00"),
    )

    raw_fields = _json_compatible_raw_fields(record)

    assert raw_fields["amount"] == "5000.00"
    assert raw_fields["aggregate_ytd"] == "10000.00"
    assert raw_fields["contribution_date"] == "2025-03-15"


@pytest.mark.integration
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


@pytest.mark.integration
def test_load_irs_527_records_inserts_fixture_rows(irs_527_load_env: Irs527LoadEnv) -> None:
    env = irs_527_load_env
    records = list(read_irs_527_records(env.txt_path))

    result = load_irs_527_records(
        env.conn,
        env.txt_path,
        data_source_id=env.data_source_id,
        batch_size=2,
        limit=None,
    )

    assert isinstance(result, LoadResult)
    assert result.inserted == len(records)
    assert result.skipped == 0
    assert result.errors == 0

    with env.conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS count FROM cf.political_organization_527 WHERE ein = ANY(%s)",
            (env.key_sets["eins"],),
        )
        org_count = cursor.fetchone()["count"]

        cursor.execute(
            "SELECT COUNT(*) AS count FROM cf.filing_8872 WHERE form_id_number = ANY(%s)",
            (env.key_sets["form_ids"],),
        )
        filing_count = cursor.fetchone()["count"]

        cursor.execute(
            "SELECT COUNT(*) AS count FROM cf.contribution_527 WHERE sched_a_id = ANY(%s)",
            (env.key_sets["sched_a_ids"],),
        )
        contribution_count = cursor.fetchone()["count"]

        cursor.execute(
            "SELECT COUNT(*) AS count FROM cf.expenditure_527 WHERE sched_b_id = ANY(%s)",
            (env.key_sets["sched_b_ids"],),
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
                env.data_source_id,
                env.key_sets["eins"],
                env.key_sets["form_ids"],
                env.key_sets["sched_a_ids"],
                env.key_sets["sched_b_ids"],
            ),
        )
        source_record_count = cursor.fetchone()["count"]

    assert org_count == _EXPECTED_FIXTURE_MODEL_COUNTS["political_organization_527"]
    assert filing_count == _EXPECTED_FIXTURE_MODEL_COUNTS["filing_8872"]
    assert contribution_count == _EXPECTED_FIXTURE_MODEL_COUNTS["contribution_527"]
    assert expenditure_count == _EXPECTED_FIXTURE_MODEL_COUNTS["expenditure_527"]

    assert org_count == len(env.key_sets["eins"])
    assert filing_count == len(env.key_sets["form_ids"])
    assert contribution_count == len(env.key_sets["sched_a_ids"])
    assert expenditure_count == len(env.key_sets["sched_b_ids"])
    assert source_record_count == len(records)


@pytest.mark.integration
def test_load_irs_527_records_counts_duplicate_natural_keys_as_skips(
    irs_527_load_env: Irs527LoadEnv,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = irs_527_load_env
    base_records = list(read_irs_527_records(env.txt_path))
    duplicated_records = base_records + [record.model_copy() for record in base_records]

    monkeypatch.setattr(
        "domains.campaign_finance.ingest.dark_money.loader.read_irs_527_records",
        lambda _txt_path: iter(duplicated_records),
    )

    result = load_irs_527_records(
        env.conn,
        env.txt_path,
        data_source_id=env.data_source_id,
        batch_size=100,
        limit=None,
    )

    assert result.inserted == len(base_records)
    assert result.skipped == len(base_records)
    assert result.errors == 0


@pytest.mark.integration
def test_load_irs_527_records_inserts_fresh_fixture_without_row_source_record_writes(
    irs_527_load_env: Irs527LoadEnv,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = irs_527_load_env
    records = list(read_irs_527_records(env.txt_path))

    def fail_row_source_record_insert(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("fresh unique rows must use the batch source-record insert path")

    monkeypatch.setattr(loader_module, "try_insert_source_record", fail_row_source_record_insert)

    result = load_irs_527_records(
        env.conn,
        env.txt_path,
        data_source_id=env.data_source_id,
        batch_size=100,
        limit=None,
    )

    assert result.inserted == len(records)
    assert result.skipped == 0
    assert result.errors == 0


@pytest.mark.integration
def test_load_irs_527_records_rerun_skips_identical_source_records_before_row_insert(
    irs_527_load_env: Irs527LoadEnv,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = irs_527_load_env
    records = list(read_irs_527_records(env.txt_path))
    first_result = load_irs_527_records(
        env.conn,
        env.txt_path,
        data_source_id=env.data_source_id,
        batch_size=100,
        limit=None,
    )
    assert first_result.inserted == len(records)

    def fail_row_source_record_insert(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("identical reruns must skip before row-level source-record writes")

    monkeypatch.setattr(loader_module, "try_insert_source_record", fail_row_source_record_insert)

    second_result = load_irs_527_records(
        env.conn,
        env.txt_path,
        data_source_id=env.data_source_id,
        batch_size=100,
        limit=None,
    )

    assert second_result.inserted == 0
    assert second_result.skipped == len(records)
    assert second_result.errors == 0


@pytest.mark.integration
def test_load_irs_527_records_updates_existing_org_on_changed_type_1_row(
    irs_527_load_env: Irs527LoadEnv,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = irs_527_load_env
    base_records = list(read_irs_527_records(env.txt_path))
    original_org = next(record for record in base_records if isinstance(record, PoliticalOrganization527))
    amended_org = original_org.model_copy(update={"name": f"{original_org.name} AMENDED"})
    amended_records = base_records + [amended_org]

    monkeypatch.setattr(
        "domains.campaign_finance.ingest.dark_money.loader.read_irs_527_records",
        lambda _txt_path: iter(amended_records),
    )

    result = load_irs_527_records(
        env.conn,
        env.txt_path,
        data_source_id=env.data_source_id,
        batch_size=100,
        limit=None,
    )

    assert result.inserted == len(amended_records)
    assert result.skipped == 0
    assert result.errors == 0

    source_record_key = f"irs_527:1:{original_org.ein}"
    with env.conn.cursor(row_factory=dict_row) as cursor:
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
            (env.data_source_id, source_record_key),
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


@pytest.mark.integration
def test_load_irs_527_records_rolls_back_failed_row_and_continues_ingest(
    irs_527_load_env: Irs527LoadEnv,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = irs_527_load_env
    organization_records = [
        record for record in read_irs_527_records(env.txt_path) if isinstance(record, PoliticalOrganization527)
    ]
    assert len(organization_records) >= 2
    failed_record = organization_records[0]
    succeeding_record = organization_records[1]

    original_insert = loader_module._insert_irs_527_row
    should_fail_first_row = True

    def flaky_insert_irs_527_row(
        conn: psycopg.Connection,
        record: loader_module.Irs527Record,
        *,
        source_record_id: object,
    ) -> bool:
        nonlocal should_fail_first_row
        if should_fail_first_row:
            should_fail_first_row = False
            raise RuntimeError("forced row failure")
        return original_insert(conn, record, source_record_id=source_record_id)

    monkeypatch.setattr(
        "domains.campaign_finance.ingest.dark_money.loader.read_irs_527_records",
        lambda _txt_path: iter([failed_record, succeeding_record]),
    )
    monkeypatch.setattr(
        "domains.campaign_finance.ingest.dark_money.loader._insert_irs_527_row",
        flaky_insert_irs_527_row,
    )
    monkeypatch.setattr(
        "domains.campaign_finance.ingest.dark_money.loader._insert_source_records_bulk",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("forced bulk fallback")),
    )

    result = load_irs_527_records(
        env.conn,
        env.txt_path,
        data_source_id=env.data_source_id,
        batch_size=100,
        limit=None,
    )

    assert result.inserted == 1
    assert result.skipped == 0
    assert result.errors == 1

    with env.conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT ein
            FROM cf.political_organization_527
            WHERE ein = ANY(%s)
            ORDER BY ein
            """,
            ([failed_record.ein, succeeding_record.ein],),
        )
        persisted_org_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT source_record_key
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
            ORDER BY source_record_key
            """,
            (
                env.data_source_id,
                [
                    _source_record_key(failed_record),
                    _source_record_key(succeeding_record),
                ],
            ),
        )
        source_record_rows = cursor.fetchall()

    assert persisted_org_rows == [{"ein": succeeding_record.ein}]
    assert source_record_rows == [{"source_record_key": _source_record_key(succeeding_record)}]
