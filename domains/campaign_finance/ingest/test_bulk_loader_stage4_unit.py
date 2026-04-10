from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from domains.campaign_finance.ingest import bulk_loader, bulk_stage4_loader


@pytest.mark.unit
class TestStage4StreamingLoop:
    class _RecordingCursor:
        def __init__(self, statements: list[str]) -> None:
            self._statements = statements

        def __enter__(self) -> TestStage4StreamingLoop._RecordingCursor:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def execute(self, statement: str, params: object = None) -> None:
            del params
            self._statements.append(statement)

    class _RecordingConnection:
        def __init__(self) -> None:
            self.commit_count = 0
            self.statements: list[str] = []

        def cursor(self) -> TestStage4StreamingLoop._RecordingCursor:
            return TestStage4StreamingLoop._RecordingCursor(self.statements)

        def commit(self) -> None:
            self.commit_count += 1

    @staticmethod
    def _build_stage4_rows(count: int) -> list[dict[str, str]]:
        return [
            {
                "SUB_ID": f"SUB-{index}",
                "CMTE_ID": f"C{index:08d}",
            }
            for index in range(1, count + 1)
        ]

    @staticmethod
    def _map_row(raw_row: dict[str, str]) -> dict[str, object]:
        return {
            "sub_id": raw_row["SUB_ID"],
            "committee_id": raw_row["CMTE_ID"],
        }

    def test_row_level_failure_uses_savepoint_and_continues_loading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(3)

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_loader,
            "find_organization_by_identifier",
            lambda *args, **kwargs: object(),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_id_by_fec_id",
            lambda *args, **kwargs: uuid4(),
        )

        load_results = iter([True, RuntimeError("broken row"), True])

        def load_contribution_side_effect(*args: object, **kwargs: object) -> bool:
            del args, kwargs
            next_result = next(load_results)
            if isinstance(next_result, Exception):
                raise next_result
            return next_result

        monkeypatch.setattr(bulk_stage4_loader, "load_contribution", load_contribution_side_effect)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            batch_size=100,
        )

        assert (result.inserted, result.skipped, result.errors) == (2, 0, 1)
        assert conn.commit_count == 1
        assert conn.statements.count("SAVEPOINT stage4_row") == 3
        assert conn.statements.count("RELEASE SAVEPOINT stage4_row") == 3
        assert conn.statements.count("ROLLBACK TO SAVEPOINT stage4_row") == 1

    def test_commit_cadence_commits_every_batch_and_at_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(5)

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_loader,
            "find_organization_by_identifier",
            lambda *args, **kwargs: object(),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_id_by_fec_id",
            lambda *args, **kwargs: uuid4(),
        )
        monkeypatch.setattr(bulk_stage4_loader, "load_contribution", lambda *args, **kwargs: True)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            batch_size=2,
        )

        assert (result.inserted, result.skipped, result.errors) == (5, 0, 0)
        assert conn.commit_count == 3

    def test_commit_cadence_commits_at_eof_on_exact_batch_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(4)

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_loader,
            "find_organization_by_identifier",
            lambda *args, **kwargs: object(),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_id_by_fec_id",
            lambda *args, **kwargs: uuid4(),
        )
        monkeypatch.setattr(bulk_stage4_loader, "load_contribution", lambda *args, **kwargs: True)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            batch_size=2,
        )

        assert (result.inserted, result.skipped, result.errors) == (4, 0, 0)
        assert conn.commit_count == 3

    def test_progress_logging_emits_at_ten_thousand_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(10000)

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_loader,
            "find_organization_by_identifier",
            lambda *args, **kwargs: object(),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_id_by_fec_id",
            lambda *args, **kwargs: uuid4(),
        )
        monkeypatch.setattr(bulk_stage4_loader, "load_contribution", lambda *args, **kwargs: True)

        caplog.set_level("INFO")

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            batch_size=50000,
        )

        assert (result.inserted, result.skipped, result.errors) == (10000, 0, 0)
        assert "Processed 10000 itcont rows" in caplog.text

    def test_unresolved_committee_id_skips_row_before_shared_persistence(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(1)
        load_contribution_calls: list[tuple[object, ...]] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(bulk_loader, "find_organization_by_identifier", lambda *args, **kwargs: None)
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: load_contribution_calls.append(args) or True,
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            batch_size=100,
        )

        assert (result.inserted, result.skipped, result.errors) == (0, 0, 1)
        assert conn.commit_count == 1
        assert load_contribution_calls == []
        assert conn.statements == []

    def test_placeholder_organization_without_committee_preload_skips_row_before_shared_persistence(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(1)
        load_contribution_calls: list[tuple[object, ...]] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(bulk_loader, "find_organization_by_identifier", lambda *args, **kwargs: object())
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: load_contribution_calls.append(args) or True,
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            batch_size=100,
        )

        assert (result.inserted, result.skipped, result.errors) == (0, 0, 1)
        assert conn.commit_count == 1
        assert load_contribution_calls == []
        assert conn.statements == []

    def test_committee_transactions_use_mapped_candidate_fec_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        raw_row = {"SUB_ID": "SUB-1", "CMTE_ID": "C00000001", "CAND_ID": "RAW-CAND-1"}
        captured_contribution_records: list[dict[str, object]] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter([raw_row]))
        monkeypatch.setattr(
            bulk_stage4_loader,
            "map_contribution_fields",
            lambda row: {
                "sub_id": row["SUB_ID"],
                "committee_id": row["CMTE_ID"],
                "candidate_fec_id": "MAPPED-CAND-1",
            },
        )
        monkeypatch.setattr(
            bulk_loader,
            "find_organization_by_identifier",
            lambda *args, **kwargs: object(),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_id_by_fec_id",
            lambda *args, **kwargs: uuid4(),
        )

        def _capture_contribution(
            conn: object,
            data_source_id: object,
            contribution: dict[str, object],
            *,
            graph_enabled: bool = False,
        ) -> bool:
            del conn, data_source_id, graph_enabled
            captured_contribution_records.append(contribution)
            return True

        monkeypatch.setattr(bulk_stage4_loader, "load_contribution", _capture_contribution)

        result = bulk_loader.load_committee_transactions(
            conn,
            Path("/tmp/itpas2.txt"),
            data_source_id=uuid4(),
            batch_size=100,
        )

        assert (result.inserted, result.skipped, result.errors) == (1, 0, 0)
        assert captured_contribution_records[0]["candidate_fec_id"] == "MAPPED-CAND-1"

    def test_with_transactions_counts_backfill_insert_when_provenance_exists(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(1)
        relational_calls: list[tuple[str, object]] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: uuid4())
        monkeypatch.setattr(bulk_stage4_loader, "load_contribution", lambda *args, **kwargs: False)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_load_stage4_relational_row",
            lambda *args, **kwargs: relational_calls.append(("called", kwargs["source_record_key"])) or True,
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            batch_size=100,
            with_transactions=True,
        )

        assert (result.inserted, result.skipped, result.errors) == (1, 0, 0)
        assert relational_calls == [("called", "SUB-1")]

    def test_with_transactions_relational_failure_rolls_back_row_and_records_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(1)

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: uuid4())
        monkeypatch.setattr(bulk_stage4_loader, "load_contribution", lambda *args, **kwargs: True)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_load_stage4_relational_row",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("relational write failed")),
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            batch_size=100,
            with_transactions=True,
        )

        assert (result.inserted, result.skipped, result.errors) == (0, 0, 1)
        assert conn.statements.count("SAVEPOINT stage4_row") == 1
        assert conn.statements.count("ROLLBACK TO SAVEPOINT stage4_row") == 1
        assert conn.statements.count("RELEASE SAVEPOINT stage4_row") == 1
