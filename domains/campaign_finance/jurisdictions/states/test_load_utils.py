from __future__ import annotations

import importlib
import re
from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import fields
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import psycopg.errors
import pytest
from psycopg.pq import TransactionStatus

from core.db import (
    insert_address,
    insert_data_source,
    insert_entity_address,
    insert_entity_source,
    insert_person,
    insert_source_record,
)
from core.types.python.models import Address, DataSource, Person, SourceRecord
from domains.campaign_finance.jurisdictions._test_helpers import clear_state_loader_records
from domains.campaign_finance.jurisdictions.states import load_utils
from domains.campaign_finance.jurisdictions.states.load_utils import (
    LoadResult,
    commit_managed_transaction,
    ensure_data_source,
    ensure_transaction_open,
    iter_rows_with_limit,
    link_entity_source_and_optional_mailing_address,
    select_data_source_id,
    try_row_without_savepoint,
    validated_limit,
)


@pytest.mark.parametrize("limit", [None, 0, 1, 50])
def test_validated_limit_accepts_none_and_non_negative_values(limit: int | None) -> None:
    assert validated_limit(limit) == limit


def test_validated_limit_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="limit must be greater than or equal to 0"):
        validated_limit(-1)


def test_iter_rows_with_limit_yields_all_rows_without_a_limit() -> None:
    assert list(iter_rows_with_limit(["a", "b", "c"], None)) == ["a", "b", "c"]


def test_iter_rows_with_limit_zero_preserves_loader_side_effects() -> None:
    observed: list[str] = []

    def _rows():
        observed.append("before-row-1")
        yield "row-1"
        observed.append("before-row-2")
        yield "row-2"

    assert list(iter_rows_with_limit(_rows(), 0)) == []
    assert observed == ["before-row-1"]


def test_iter_rows_with_limit_yields_only_the_configured_number_of_rows() -> None:
    assert list(iter_rows_with_limit(["a", "b", "c"], 2)) == ["a", "b"]


def test_iter_rows_with_limit_rejects_negative_limit_values() -> None:
    with pytest.raises(ValueError, match="limit must be greater than or equal to 0"):
        list(iter_rows_with_limit(["a"], -1))


def test_ensure_transaction_open_starts_transaction_when_idle() -> None:
    conn = MagicMock()
    conn.info.transaction_status = TransactionStatus.IDLE

    ensure_transaction_open(conn)

    conn.execute.assert_called_once_with("BEGIN")


def test_ensure_transaction_open_noops_when_transaction_is_already_open() -> None:
    conn = MagicMock()
    conn.info.transaction_status = TransactionStatus.INTRANS

    ensure_transaction_open(conn)

    conn.execute.assert_not_called()


def test_commit_managed_transaction_commits_when_it_owns_active_transaction() -> None:
    conn = MagicMock()
    conn.info.transaction_status = TransactionStatus.INTRANS

    commit_managed_transaction(conn, manages_outer_transaction=True)

    conn.commit.assert_called_once_with()


@pytest.mark.parametrize(
    ("manages_outer_transaction", "status"),
    [
        (False, TransactionStatus.INTRANS),
        (True, TransactionStatus.IDLE),
    ],
)
def test_commit_managed_transaction_noops_when_not_owner_or_idle(
    manages_outer_transaction: bool,
    status: TransactionStatus,
) -> None:
    conn = MagicMock()
    conn.info.transaction_status = status

    commit_managed_transaction(conn, manages_outer_transaction=manages_outer_transaction)

    conn.commit.assert_not_called()


def test_try_row_without_savepoint_returns_result_on_success() -> None:
    """Happy path: callable succeeds, no savepoint needed."""
    conn = MagicMock()
    conn.info.transaction_status = TransactionStatus.IDLE

    result, was_db_error = try_row_without_savepoint(conn, lambda: True, manages_outer_transaction=True, label="test")

    assert result is True
    assert was_db_error is False
    # Should NOT create a savepoint (no conn.transaction() call)
    conn.transaction.assert_not_called()


def test_try_row_without_savepoint_handles_python_error_without_rollback() -> None:
    """Python-level errors (validation, extraction) should NOT break the transaction."""
    conn = MagicMock()
    conn.info.transaction_status = TransactionStatus.INTRANS

    def _bad_extraction():
        raise ValueError("bad zip code")

    result, was_db_error = try_row_without_savepoint(
        conn, _bad_extraction, manages_outer_transaction=True, label="test"
    )

    assert result is None
    assert was_db_error is False
    # Transaction should NOT be rolled back for Python errors
    conn.rollback.assert_not_called()


def test_try_row_without_savepoint_rolls_back_on_db_error() -> None:
    """DB errors put the connection in error state — must rollback."""
    conn = MagicMock()
    conn.info.transaction_status = TransactionStatus.INTRANS

    def _db_failure():
        raise psycopg.errors.UniqueViolation("duplicate key")

    result, was_db_error = try_row_without_savepoint(conn, _db_failure, manages_outer_transaction=True, label="test")

    assert result is None
    assert was_db_error is True
    conn.rollback.assert_called_once()


def test_try_row_without_savepoint_opens_transaction_when_idle() -> None:
    """When managing the outer transaction, should BEGIN if IDLE."""
    conn = MagicMock()
    conn.info.transaction_status = TransactionStatus.IDLE

    try_row_without_savepoint(conn, lambda: 42, manages_outer_transaction=True, label="test")

    conn.execute.assert_called_once_with("BEGIN")


def test_try_row_without_savepoint_skips_begin_when_not_managing() -> None:
    """When not managing, should not issue BEGIN."""
    conn = MagicMock()
    conn.info.transaction_status = TransactionStatus.INTRANS

    try_row_without_savepoint(conn, lambda: 42, manages_outer_transaction=False, label="test")

    conn.execute.assert_not_called()


def test_link_entity_source_and_optional_mailing_address_only_links_source_without_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    entity_id = uuid4()
    source_record_id = uuid4()
    insert_entity_source = MagicMock()
    insert_entity_address = MagicMock()

    monkeypatch.setattr(load_utils, "insert_entity_source", insert_entity_source)
    monkeypatch.setattr(load_utils, "insert_entity_address", insert_entity_address)

    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="organization",
        entity_id=entity_id,
        source_record_id=source_record_id,
        extraction_role="recipient",
        address_id=None,
    )

    insert_entity_source.assert_called_once_with(
        conn,
        "organization",
        entity_id,
        source_record_id,
        "recipient",
    )
    insert_entity_address.assert_not_called()


def test_link_entity_source_and_optional_mailing_address_links_source_and_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    entity_id = uuid4()
    source_record_id = uuid4()
    address_id = uuid4()
    insert_entity_source = MagicMock()
    insert_entity_address = MagicMock()

    monkeypatch.setattr(load_utils, "insert_entity_source", insert_entity_source)
    monkeypatch.setattr(load_utils, "insert_entity_address", insert_entity_address)

    link_entity_source_and_optional_mailing_address(
        conn,
        entity_type="person",
        entity_id=entity_id,
        source_record_id=source_record_id,
        extraction_role="donor",
        address_id=address_id,
    )

    insert_entity_source.assert_called_once_with(
        conn,
        "person",
        entity_id,
        source_record_id,
        "donor",
    )
    insert_entity_address.assert_called_once_with(
        conn,
        "person",
        entity_id,
        address_id,
        source_record_id,
        "mailing",
    )


# ---------------------------------------------------------------------------
# select_data_source_id
# ---------------------------------------------------------------------------


def _mock_conn_with_fetchone(return_value):
    """Build a MagicMock connection whose cursor().fetchone() returns *return_value*."""
    conn = MagicMock(spec=psycopg.Connection)
    cursor = MagicMock()
    cursor.fetchone.return_value = return_value
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn, cursor


class TestSelectDataSourceId:
    def test_returns_uuid_when_row_exists(self) -> None:
        expected_id = uuid4()
        conn, cursor = _mock_conn_with_fetchone((expected_id,))

        result = select_data_source_id(conn, "campaign_finance", "state/NC", "NC SBoE")

        assert result == expected_id
        cursor.execute.assert_called_once()
        # Verify the query uses the three lookup columns
        sql = cursor.execute.call_args[0][0]
        assert "domain" in sql
        assert "jurisdiction" in sql
        assert "name" in sql
        # Verify params passed correctly
        params = cursor.execute.call_args[0][1]
        assert params == ("campaign_finance", "state/NC", "NC SBoE")

    def test_returns_none_when_no_row(self) -> None:
        conn, _ = _mock_conn_with_fetchone(None)

        result = select_data_source_id(conn, "campaign_finance", "state/XX", "nonexistent")

        assert result is None

    def test_uses_null_safe_jurisdiction_comparison(self) -> None:
        expected_id = uuid4()
        conn, cursor = _mock_conn_with_fetchone((expected_id,))

        result = select_data_source_id(conn, "campaign_finance", None, "National Feed")

        assert result == expected_id
        query, params = cursor.execute.call_args.args
        assert "jurisdiction IS NOT DISTINCT FROM %s" in query
        assert params == ("campaign_finance", None, "National Feed")


# ---------------------------------------------------------------------------
# ensure_data_source
# ---------------------------------------------------------------------------


class TestEnsureDataSource:
    @pytest.fixture()
    def data_source(self):
        from core.types.python.models import DataSource

        return DataSource(
            domain="campaign_finance",
            jurisdiction="state/NC",
            name="NC SBoE Transaction Search",
            source_url="https://cf.ncsbe.gov/CFTxnLkup/",
            source_format="csv",
        )

    def test_returns_existing_id_on_first_select(self, data_source, monkeypatch: pytest.MonkeyPatch) -> None:
        existing_id = uuid4()
        monkeypatch.setattr(
            load_utils,
            "select_data_source_id",
            MagicMock(return_value=existing_id),
        )
        mock_try_insert = MagicMock()
        monkeypatch.setattr(load_utils, "try_insert_data_source", mock_try_insert)

        result = ensure_data_source(MagicMock(), data_source)

        assert result == existing_id
        mock_try_insert.assert_not_called()

    def test_inserts_when_not_found_and_returns_new_id(self, data_source, monkeypatch: pytest.MonkeyPatch) -> None:
        new_id = uuid4()
        monkeypatch.setattr(
            load_utils,
            "select_data_source_id",
            MagicMock(return_value=None),
        )
        monkeypatch.setattr(
            load_utils,
            "try_insert_data_source",
            MagicMock(return_value=new_id),
        )

        result = ensure_data_source(MagicMock(), data_source)

        assert result == new_id

    def test_retries_select_after_conflict(self, data_source, monkeypatch: pytest.MonkeyPatch) -> None:
        # First select returns None, insert returns None (conflict),
        # second select returns the existing id
        existing_id = uuid4()
        monkeypatch.setattr(
            load_utils,
            "select_data_source_id",
            MagicMock(side_effect=[None, existing_id]),
        )
        monkeypatch.setattr(
            load_utils,
            "try_insert_data_source",
            MagicMock(return_value=None),
        )

        result = ensure_data_source(MagicMock(), data_source)

        assert result == existing_id

    def test_raises_when_conflict_and_reselect_fails(self, data_source, monkeypatch: pytest.MonkeyPatch) -> None:
        # Both selects return None, insert returns None (conflict)
        monkeypatch.setattr(
            load_utils,
            "select_data_source_id",
            MagicMock(return_value=None),
        )
        monkeypatch.setattr(
            load_utils,
            "try_insert_data_source",
            MagicMock(return_value=None),
        )

        with pytest.raises(RuntimeError, match="insert reported a conflict"):
            ensure_data_source(MagicMock(), data_source)

    def test_accepts_civics_roster_shaped_data_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        connection = MagicMock()
        civics_source = DataSource(
            domain="civics",
            jurisdiction="city/NC/Durham",
            name="Durham City Council Roster",
            source_url="https://www.durhamnc.gov/1396/City-Council-Members",
            source_format="html",
        )
        inserted_id = uuid4()
        select_mock = MagicMock(return_value=None)
        try_insert_mock = MagicMock(return_value=inserted_id)
        monkeypatch.setattr(load_utils, "select_data_source_id", select_mock)
        monkeypatch.setattr(load_utils, "try_insert_data_source", try_insert_mock)

        result = ensure_data_source(connection, civics_source)

        assert result == inserted_id
        select_mock.assert_called_once_with(connection, "civics", "city/NC/Durham", "Durham City Council Roster")
        try_insert_mock.assert_called_once()


# ---------------------------------------------------------------------------
# LoadResult
# ---------------------------------------------------------------------------


class TestLoadResult:
    def test_has_six_fields(self) -> None:
        field_names = [f.name for f in fields(LoadResult)]
        assert field_names == [
            "inserted",
            "skipped",
            "quarantined",
            "superseded",
            "errors",
            "elapsed_seconds",
        ]

    def test_uses_slots(self) -> None:
        assert hasattr(LoadResult, "__slots__")

    def test_construction(self) -> None:
        result = LoadResult(
            inserted=10,
            skipped=2,
            quarantined=1,
            superseded=0,
            errors=3,
            elapsed_seconds=1.5,
        )
        assert result.inserted == 10
        assert result.elapsed_seconds == 1.5


_SIX_FIELD_LOAD_RESULT_MODULES = [
    "domains.campaign_finance.jurisdictions.states.CA.scraper.load",
    "domains.campaign_finance.jurisdictions.states.CO.scraper.load",
    "domains.campaign_finance.jurisdictions.states.FL.scraper.load",
    "domains.campaign_finance.jurisdictions.states.IL.scraper.load",
    "domains.campaign_finance.jurisdictions.states.IN.scraper.load",
    "domains.campaign_finance.jurisdictions.states.MN.scraper.load",
    "domains.campaign_finance.jurisdictions.states.NC.scraper.load",
    "domains.campaign_finance.jurisdictions.states.NJ.scraper.load",
    "domains.campaign_finance.jurisdictions.states.OH.scraper.load",
    "domains.campaign_finance.jurisdictions.states.PA.scraper.load",
    "domains.campaign_finance.jurisdictions.states.TX.scraper.load",
    "domains.campaign_finance.jurisdictions.states.VA.scraper.load",
    "domains.campaign_finance.jurisdictions.states.WA.scraper.load",
    "domains.campaign_finance.jurisdictions.states.WI.scraper.load",
]


@pytest.mark.parametrize("module_path", _SIX_FIELD_LOAD_RESULT_MODULES)
def test_state_load_modules_reexport_shared_load_result(module_path: str) -> None:
    module = importlib.import_module(module_path)
    assert module.LoadResult is load_utils.LoadResult


_TARGET_HELPER_FILES = [
    "domains/campaign_finance/jurisdictions/states/CA/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/CO/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/FL/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/GA/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/IL/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/IN/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/MN/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/NC/scraper/load_support.py",
    "domains/campaign_finance/jurisdictions/states/NJ/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/OH/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/PA/scraper/load_support.py",
    "domains/campaign_finance/jurisdictions/states/TX/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/VA/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/WA/scraper/load.py",
    "domains/campaign_finance/jurisdictions/states/WI/scraper/load.py",
]


@pytest.mark.parametrize("relative_path", _TARGET_HELPER_FILES)
def test_state_helper_files_no_longer_call_try_insert_data_source(relative_path: str) -> None:
    file_content = Path(relative_path).read_text(encoding="utf-8")
    assert "try_insert_data_source(" not in file_content


@pytest.mark.parametrize("relative_path", _TARGET_HELPER_FILES)
def test_state_helper_files_no_longer_define_local_select_data_source_wrappers(relative_path: str) -> None:
    file_content = Path(relative_path).read_text(encoding="utf-8")
    assert re.search(r"def _select_[a-z_]+_data_source_id\(", file_content) is None


_STATE_LOADER_TEST_MODULES = [
    "domains/campaign_finance/jurisdictions/states/WA/scraper/test_load.py",
    "domains/campaign_finance/jurisdictions/states/FL/scraper/test_load.py",
    "domains/campaign_finance/jurisdictions/states/MN/scraper/test_load.py",
    "domains/campaign_finance/jurisdictions/states/TX/scraper/test_load.py",
    "domains/campaign_finance/jurisdictions/states/IN/scraper/test_load.py",
]

_SOURCE_RECORD_COUNT_TEST_MODULES = [
    "domains/campaign_finance/jurisdictions/states/WA/scraper/test_load.py",
    "domains/campaign_finance/jurisdictions/states/FL/scraper/test_load.py",
    "domains/campaign_finance/jurisdictions/states/MN/scraper/test_load.py",
]

_SHARED_HELPER_IMPORT_EXPECTATIONS = [
    (
        "domains/campaign_finance/jurisdictions/states/WA/scraper/test_load.py",
        ["_source_record_count", "clear_state_loader_records"],
    ),
    (
        "domains/campaign_finance/jurisdictions/states/FL/scraper/test_load.py",
        ["_source_record_count", "clear_state_loader_records"],
    ),
    (
        "domains/campaign_finance/jurisdictions/states/MN/scraper/test_load.py",
        ["_source_record_count", "clear_state_loader_records"],
    ),
    (
        "domains/campaign_finance/jurisdictions/states/TX/scraper/test_load.py",
        ["clear_state_loader_records"],
    ),
    (
        "domains/campaign_finance/jurisdictions/states/IN/scraper/test_load.py",
        ["clear_state_loader_records"],
    ),
]


def _count_rows(
    db_conn: psycopg.Connection,
    query: str,
    params: tuple[object, ...],
) -> int:
    with db_conn.cursor() as cursor:
        cursor.execute(query, params)
        result = cursor.fetchone()
    assert result is not None
    return result[0]


def _insert_state_loader_cleanup_rows(
    db_conn: psycopg.Connection,
    *,
    label: str,
    state_code: str,
    source_record_id,
    committee_id,
    candidate_id,
    filing_id,
    transaction_id,
    link_id,
) -> None:
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.committee (id, fec_committee_id, name, state, source_record_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                committee_id,
                f"C{committee_id.int % 100_000_000:08d}",
                f"{label} committee",
                state_code,
                source_record_id,
            ),
        )
        cursor.execute(
            """
            INSERT INTO cf.candidate (
                id, fec_candidate_id, name, office, state, district, principal_committee_id, source_record_id
            )
            VALUES (%s, %s, %s, 'H', %s, '01', %s, %s)
            """,
            (
                candidate_id,
                f"H{candidate_id.int % 10}{state_code}{candidate_id.int % 100_000:05d}",
                f"{label} candidate",
                state_code,
                committee_id,
                source_record_id,
            ),
        )
        cursor.execute(
            """
            INSERT INTO cf.filing (
                id, filing_fec_id, committee_id, candidate_id, amendment_indicator, source_record_id
            )
            VALUES (%s, %s, %s, %s, 'N', %s)
            """,
            (filing_id, f"{label}-filing", committee_id, candidate_id, source_record_id),
        )
        cursor.execute(
            """
            INSERT INTO cf.transaction (
                id, filing_id, committee_id, transaction_type, amount,
                amendment_indicator, source_record_id, recipient_candidate_id, transaction_identifier
            )
            VALUES (%s, %s, %s, 'contribution', %s, 'N', %s, %s, %s)
            """,
            (
                transaction_id,
                filing_id,
                committee_id,
                Decimal("10.00"),
                source_record_id,
                candidate_id,
                f"{label}-transaction",
            ),
        )
        cursor.execute(
            """
            INSERT INTO cf.candidate_committee_link (
                id, candidate_id, committee_id, designation,
                candidate_election_year, fec_election_year, valid_period, source_record_id
            )
            VALUES (%s, %s, %s, 'P', 2026, 2026, daterange('2026-01-01', NULL, '[)'), %s)
            """,
            (link_id, candidate_id, committee_id, source_record_id),
        )


def _seed_state_loader_cleanup_fixture(
    db_conn: psycopg.Connection,
    *,
    jurisdiction: str,
    state_code: str,
    label: str,
) -> dict[str, object]:
    data_source = DataSource(
        domain="campaign_finance",
        jurisdiction=jurisdiction,
        name=f"stage2-clear-helper-{label}-{uuid4()}",
        source_url=f"https://example.com/{label}",
    )
    source_record = SourceRecord(
        data_source_id=data_source.id,
        source_record_key=f"{label}-record",
        raw_fields={"label": label},
        pull_date=datetime(2026, 3, 29, tzinfo=timezone.utc),
    )
    person = Person(canonical_name=f"{label} person")
    address = Address(raw_address=f"{label} 1 Main St, {state_code} 00000")
    fixture_ids = {
        "committee_id": uuid4(),
        "candidate_id": uuid4(),
        "filing_id": uuid4(),
        "transaction_id": uuid4(),
        "link_id": uuid4(),
    }

    insert_data_source(db_conn, data_source)
    insert_source_record(db_conn, source_record)
    insert_person(db_conn, person)
    insert_address(db_conn, address)
    insert_entity_source(db_conn, "person", person.id, source_record.id, "donor")
    insert_entity_address(db_conn, "person", person.id, address.id, source_record.id, "mailing")
    _insert_state_loader_cleanup_rows(
        db_conn,
        label=label,
        state_code=state_code,
        source_record_id=source_record.id,
        **fixture_ids,
    )

    return {
        "data_source_id": data_source.id,
        "source_record_id": source_record.id,
        **fixture_ids,
    }


@pytest.mark.parametrize("relative_path", _STATE_LOADER_TEST_MODULES)
def test_state_loader_test_modules_no_longer_define_local_clear_records_helpers(relative_path: str) -> None:
    file_content = Path(relative_path).read_text(encoding="utf-8")
    assert re.search(r"def _clear_existing_[a-z_]+_records\(", file_content) is None


@pytest.mark.parametrize("relative_path", _SOURCE_RECORD_COUNT_TEST_MODULES)
def test_state_loader_test_modules_no_longer_define_local_source_record_count(relative_path: str) -> None:
    file_content = Path(relative_path).read_text(encoding="utf-8")
    assert "def _source_record_count(" not in file_content


@pytest.mark.parametrize(("relative_path", "helper_names"), _SHARED_HELPER_IMPORT_EXPECTATIONS)
def test_state_loader_test_modules_import_shared_db_helpers(relative_path: str, helper_names: list[str]) -> None:
    file_content = Path(relative_path).read_text(encoding="utf-8")
    assert "from domains.campaign_finance.jurisdictions._test_helpers import" in file_content
    for helper_name in helper_names:
        assert helper_name in file_content


def test_clear_state_loader_records_only_removes_target_state_rows(db_conn: psycopg.Connection) -> None:
    target = _seed_state_loader_cleanup_fixture(
        db_conn,
        jurisdiction="state/WA",
        state_code="WA",
        label="target",
    )
    control = _seed_state_loader_cleanup_fixture(
        db_conn,
        jurisdiction="state/OR",
        state_code="OR",
        label="control",
    )

    clear_state_loader_records(db_conn, jurisdiction="state/WA", state_code="WA")

    assert (
        _count_rows(db_conn, "SELECT COUNT(*) FROM core.source_record WHERE id = %s", (target["source_record_id"],))
        == 0
    )
    assert (
        _count_rows(db_conn, "SELECT COUNT(*) FROM core.source_record WHERE id = %s", (control["source_record_id"],))
        == 1
    )
    assert (
        _count_rows(
            db_conn,
            "SELECT COUNT(*) FROM core.entity_source WHERE source_record_id = %s",
            (target["source_record_id"],),
        )
        == 0
    )
    assert (
        _count_rows(
            db_conn,
            "SELECT COUNT(*) FROM core.entity_source WHERE source_record_id = %s",
            (control["source_record_id"],),
        )
        == 1
    )
    assert (
        _count_rows(
            db_conn,
            "SELECT COUNT(*) FROM core.entity_address WHERE source_record_id = %s",
            (target["source_record_id"],),
        )
        == 0
    )
    assert (
        _count_rows(
            db_conn,
            "SELECT COUNT(*) FROM core.entity_address WHERE source_record_id = %s",
            (control["source_record_id"],),
        )
        == 1
    )
    assert _count_rows(db_conn, "SELECT COUNT(*) FROM cf.committee WHERE id = %s", (target["committee_id"],)) == 0
    assert _count_rows(db_conn, "SELECT COUNT(*) FROM cf.committee WHERE id = %s", (control["committee_id"],)) == 1
    assert _count_rows(db_conn, "SELECT COUNT(*) FROM cf.candidate WHERE id = %s", (target["candidate_id"],)) == 0
    assert _count_rows(db_conn, "SELECT COUNT(*) FROM cf.candidate WHERE id = %s", (control["candidate_id"],)) == 1
    assert _count_rows(db_conn, "SELECT COUNT(*) FROM cf.filing WHERE id = %s", (target["filing_id"],)) == 0
    assert _count_rows(db_conn, "SELECT COUNT(*) FROM cf.filing WHERE id = %s", (control["filing_id"],)) == 1
    assert _count_rows(db_conn, "SELECT COUNT(*) FROM cf.transaction WHERE id = %s", (target["transaction_id"],)) == 0
    assert _count_rows(db_conn, "SELECT COUNT(*) FROM cf.transaction WHERE id = %s", (control["transaction_id"],)) == 1
    assert (
        _count_rows(db_conn, "SELECT COUNT(*) FROM cf.candidate_committee_link WHERE id = %s", (target["link_id"],))
        == 0
    )
    assert (
        _count_rows(db_conn, "SELECT COUNT(*) FROM cf.candidate_committee_link WHERE id = %s", (control["link_id"],))
        == 1
    )
