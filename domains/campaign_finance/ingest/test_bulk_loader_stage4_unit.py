from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from domains.campaign_finance.ingest import bulk_loader, bulk_stage4_loader, fec_lookup


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

    @staticmethod
    def _install_stage4_batch_pipeline_recorders(
        monkeypatch: pytest.MonkeyPatch,
        *,
        committee_id: object,
        source_record_ids: dict[str, object],
        filing_id_by_sub_id: dict[str, object],
        transaction_inserted_by_sub_id: dict[str, bool],
    ) -> SimpleNamespace:
        recorder = SimpleNamespace(
            provenance_writes=[], filing_builds=[], filing_upserts=[], transaction_builds=[], transaction_upserts=[]
        )

        def _insert_provenance(
            conn: object,
            *,
            data_source_id: object,
            contribution_record: dict[str, object],
        ) -> bool:
            del conn, data_source_id
            recorder.provenance_writes.append(
                (str(contribution_record["sub_id"]), str(contribution_record["committee_id"]))
            )
            return True

        def _insert_provenance_bulk(conn: object, source_records: list[object]) -> list[SimpleNamespace]:
            del conn
            results: list[SimpleNamespace] = []
            for source_record in source_records:
                source_key = str(source_record.source_record_key)
                recorder.provenance_writes.append((source_key, str(source_record.raw_fields["committee_id"])))
                results.append(SimpleNamespace(source_record_id=source_record_ids[source_key], inserted=True))
            return results

        def _build_filing(
            conn: object,
            contribution_record: dict[str, object],
            *,
            committee_id: object | None = None,
            source_record_id: object,
        ) -> SimpleNamespace:
            del conn
            recorder.filing_builds.append(
                (
                    str(contribution_record["sub_id"]),
                    str(contribution_record["committee_id"]),
                    source_record_id,
                )
            )
            return SimpleNamespace(
                committee_id=committee_id,
                sub_id=contribution_record["sub_id"],
                filing_fec_id=contribution_record["sub_id"],
            )

        def _upsert_filings_bulk(conn: object, filings: list[SimpleNamespace]) -> dict[str, object]:
            del conn
            recorder.filing_upserts.extend(filings)
            return {str(filing.filing_fec_id): filing_id_by_sub_id[str(filing.sub_id)] for filing in filings}

        monkeypatch.setattr(bulk_stage4_loader, "_insert_stage4_provenance_only", _insert_provenance)
        monkeypatch.setattr(bulk_stage4_loader, "try_insert_source_records_bulk", _insert_provenance_bulk)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "resolve_source_record_ids",
            lambda conn, data_source_id, source_record_keys: {
                source_record_key: source_record_ids[source_record_key] for source_record_key in source_record_keys
            },
        )
        monkeypatch.setattr(bulk_stage4_loader, "build_filing_from_contribution", _build_filing)
        monkeypatch.setattr(bulk_stage4_loader, "upsert_filings_bulk", _upsert_filings_bulk)
        TestStage4StreamingLoop._install_stage4_batch_transaction_recorders(
            monkeypatch,
            recorder=recorder,
            transaction_inserted_by_sub_id=transaction_inserted_by_sub_id,
        )
        return recorder

    @staticmethod
    def _install_stage4_batch_transaction_recorders(
        monkeypatch: pytest.MonkeyPatch,
        *,
        recorder: SimpleNamespace,
        transaction_inserted_by_sub_id: dict[str, bool],
    ) -> None:
        def _build_transaction(
            conn: object,
            contribution_record: dict[str, object],
            *,
            filing_id: object,
            committee_id: object,
            source_record_id: object,
            resolve_counterparty: bool = True,
            recipient_committee_id_by_fec_id: object = None,
        ) -> SimpleNamespace:
            del conn, resolve_counterparty, recipient_committee_id_by_fec_id
            recorder.transaction_builds.append(
                (
                    str(contribution_record["sub_id"]),
                    str(contribution_record["transaction_identifier"]),
                    filing_id,
                    committee_id,
                    source_record_id,
                )
            )
            return SimpleNamespace(
                sub_id=contribution_record["sub_id"],
                transaction_identifier=contribution_record["transaction_identifier"],
            )

        def _upsert_transactions_with_status_bulk(
            conn: object,
            transactions: list[SimpleNamespace],
        ) -> list[SimpleNamespace]:
            del conn
            results: list[SimpleNamespace] = []
            for transaction in transactions:
                inserted = transaction_inserted_by_sub_id[str(transaction.sub_id)]
                recorder.transaction_upserts.append(
                    (str(transaction.sub_id), str(transaction.transaction_identifier), inserted)
                )
                results.append(SimpleNamespace(transaction_id=uuid4(), inserted=inserted))
            return results

        monkeypatch.setattr(bulk_stage4_loader, "build_transaction_from_contribution", _build_transaction)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_transactions_with_status_bulk",
            _upsert_transactions_with_status_bulk,
        )

    @staticmethod
    def _forbid_stage4_row_writers(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_filing",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("batch path should bypass row filing upserts")
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_transaction_with_status",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("batch path should bypass row transaction upserts")
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("transactions-only should bypass entities")),
        )

    @staticmethod
    def _install_stale_stage4_checkpoint(
        monkeypatch: pytest.MonkeyPatch,
        *,
        data_source_id: object,
    ) -> list[bulk_stage4_loader.Stage4ResumeCheckpoint]:
        expected_identity = bulk_stage4_loader.build_stage4_resume_identity(
            data_source_id=data_source_id,
            cycle=2026,
            file_type="itcont",
        )
        writes: list[bulk_stage4_loader.Stage4ResumeCheckpoint] = []
        stale_checkpoint = bulk_stage4_loader.Stage4ResumeCheckpoint(
            resume_identity=expected_identity,
            archive_fingerprint="old-fingerprint",
            archive_member_name="old-itcont.txt",
            next_source_row_number=50_000,
        )

        monkeypatch.setattr(
            bulk_stage4_loader,
            "_build_stage4_archive_reference",
            lambda path, file_type: bulk_stage4_loader.Stage4ArchiveReference(
                archive_fingerprint="new-fingerprint",
                archive_member_name="new-itcont.txt",
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_select_stage4_resume_checkpoint",
            lambda conn, resume_identity: stale_checkpoint,
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_write_stage4_resume_checkpoint",
            lambda conn, checkpoint: writes.append(checkpoint),
        )
        return writes

    @staticmethod
    def _load_transactions_only(
        conn: object,
        *,
        data_source_id: object,
        batch_size: int = 100,
    ) -> object:
        return bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=data_source_id,
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=batch_size,
                with_transactions=True,
                entity_extraction=False,
            ),
        )

    def test_committee_lookup_is_cached_batch_owner_normalizes_ids(self) -> None:
        committee_id = uuid4()
        executed_params: list[list[str]] = []

        class _LookupCursor:
            def __enter__(self) -> _LookupCursor:
                return self

            def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            def execute(self, statement: str, params: tuple[list[str]]) -> None:
                del statement
                executed_params.append(params[0])

            def fetchall(self) -> list[tuple[str, object]]:
                return [("C00000001", committee_id)]

        class _LookupConnection:
            def cursor(self) -> _LookupCursor:
                return _LookupCursor()

        result = fec_lookup.find_committee_ids_by_fec_ids(
            _LookupConnection(),
            [" C00000001 ", "", "   ", "C00000001"],
        )

        assert result == {"C00000001": committee_id}
        assert executed_params == [["C00000001"]]

    def test_build_stage4_request_owns_resume_identity_tuple(self) -> None:
        data_source_id = uuid4()

        request = bulk_stage4_loader._build_stage4_request(
            file_type="itcont",
            path=Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            options=bulk_stage4_loader.Stage4LoadOptions(batch_size=100),
            legacy_kwargs={},
        )

        assert bulk_stage4_loader.STAGE4_RESUME_IDENTITY_COLUMNS == (
            "data_source_id",
            "cycle",
            "file_type",
        )
        assert request.resume_identity.as_key_tuple() == (data_source_id, 2026, "itcont")
        assert request.data_source_id == data_source_id
        assert request.cycle == 2026
        assert request.file_type == "itcont"

    def test_stage4_checkpoint_lookup_uses_request_resume_identity(self) -> None:
        data_source_id = uuid4()
        captured_params: list[tuple[object, ...]] = []

        class _CheckpointCursor:
            def __enter__(self) -> _CheckpointCursor:
                return self

            def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            def execute(self, statement: str, params: tuple[object, ...]) -> None:
                assert "cf.stage4_resume_checkpoint" in statement
                captured_params.append(params)

            def fetchone(self) -> dict[str, object]:
                return {
                    "archive_fingerprint": "fingerprint-a",
                    "archive_member_name": "itcont.txt",
                    "next_source_row_number": 2500,
                }

        class _CheckpointConnection:
            def cursor(self, *args: object, **kwargs: object) -> _CheckpointCursor:
                del args, kwargs
                return _CheckpointCursor()

        request = bulk_stage4_loader._build_stage4_request(
            file_type="itcont",
            path=Path("/tmp/itcont.txt"),
            cycle="2026",
            data_source_id=data_source_id,
            options=bulk_stage4_loader.Stage4LoadOptions(),
            legacy_kwargs={},
        )

        checkpoint = bulk_stage4_loader._select_stage4_resume_checkpoint(
            _CheckpointConnection(),
            request.resume_identity,
        )

        assert captured_params == [request.resume_identity.as_key_tuple()]
        assert checkpoint == bulk_stage4_loader.Stage4ResumeCheckpoint(
            resume_identity=request.resume_identity,
            archive_fingerprint="fingerprint-a",
            archive_member_name="itcont.txt",
            next_source_row_number=2500,
        )

    def test_stage4_stale_checkpoint_resets_with_same_loader_owned_identity(self) -> None:
        data_source_id = uuid4()
        request = bulk_stage4_loader._build_stage4_request(
            file_type="itcont",
            path=Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            options=bulk_stage4_loader.Stage4LoadOptions(),
            legacy_kwargs={},
            canonical_resume_enabled=True,
        )
        writes: list[bulk_stage4_loader.Stage4ResumeCheckpoint] = []

        stale_checkpoint = bulk_stage4_loader.Stage4ResumeCheckpoint(
            resume_identity=request.resume_identity,
            archive_fingerprint="old-fingerprint",
            archive_member_name="old-itcont.txt",
            next_source_row_number=100_000,
        )

        def _select_checkpoint(conn: object, resume_identity: object) -> object:
            del conn
            assert resume_identity == request.resume_identity
            return stale_checkpoint

        def _write_checkpoint(conn: object, checkpoint: bulk_stage4_loader.Stage4ResumeCheckpoint) -> None:
            del conn
            writes.append(checkpoint)

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(bulk_stage4_loader, "_select_stage4_resume_checkpoint", _select_checkpoint)
            monkeypatch.setattr(bulk_stage4_loader, "_write_stage4_resume_checkpoint", _write_checkpoint)

            start_row = bulk_stage4_loader._resolve_stage4_resume_start_row(
                object(),
                request=request,
                archive_fingerprint="new-fingerprint",
                archive_member_name="new-itcont.txt",
            )
        finally:
            monkeypatch.undo()

        assert start_row == 0
        assert writes == [
            bulk_stage4_loader.Stage4ResumeCheckpoint(
                resume_identity=request.resume_identity,
                archive_fingerprint="new-fingerprint",
                archive_member_name="new-itcont.txt",
                next_source_row_number=0,
            )
        ]

    def test_empty_itcont_load_commits_stale_stage4_checkpoint_reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        data_source_id = uuid4()
        conn = self._RecordingConnection()
        writes = self._install_stale_stage4_checkpoint(monkeypatch, data_source_id=data_source_id)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "read_bulk_file",
            lambda path, file_type, limit, **kwargs: iter(()),
        )

        result = bulk_stage4_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            canonical_resume_enabled=True,
        )

        assert result == bulk_stage4_loader.LoadResult()
        assert writes == [
            bulk_stage4_loader.Stage4ResumeCheckpoint(
                resume_identity=bulk_stage4_loader.build_stage4_resume_identity(
                    data_source_id=data_source_id,
                    cycle=2026,
                    file_type="itcont",
                ),
                archive_fingerprint="new-fingerprint",
                archive_member_name="new-itcont.txt",
                next_source_row_number=0,
            )
        ]
        assert conn.commit_count == 1

    def test_pre_loop_itcont_failure_commits_stale_stage4_checkpoint_reset(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        data_source_id = uuid4()
        conn = self._RecordingConnection()
        self._install_stale_stage4_checkpoint(monkeypatch, data_source_id=data_source_id)

        def _fail_before_streaming(path: object, file_type: object, limit: object, **kwargs: object) -> object:
            del path, file_type, limit, kwargs
            raise RuntimeError("parser failed before streaming rows")

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", _fail_before_streaming)

        with pytest.raises(RuntimeError, match="parser failed before streaming rows"):
            bulk_stage4_loader.load_contributions(
                conn,
                Path("/tmp/itcont.txt"),
                cycle=2026,
                data_source_id=data_source_id,
                canonical_resume_enabled=True,
            )

        assert conn.commit_count == 1

    def test_public_bulk_upserts_delegate_to_extracted_bulk_owner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from domains.campaign_finance.ingest import filing_loader, filing_loader_bulk

        filing_id = uuid4()
        filing_calls: list[object] = []
        transaction_calls: list[object] = []

        monkeypatch.setattr(
            filing_loader_bulk,
            "upsert_filings_bulk",
            lambda conn, filings: filing_calls.append((conn, filings)) or {"FILING-1": filing_id},
        )
        monkeypatch.setattr(
            filing_loader_bulk,
            "upsert_transactions_with_status_bulk",
            lambda conn, transactions: transaction_calls.append((conn, transactions)) or ["transaction-result"],
        )

        conn = object()
        assert filing_loader.upsert_filings_bulk(conn, ["filing"]) == {"FILING-1": filing_id}
        assert filing_calls == [(conn, ["filing"])]
        assert filing_loader.upsert_transactions_with_status_bulk(conn, ["transaction"]) == ["transaction-result"]
        assert transaction_calls == [(conn, ["transaction"])]

    def test_finalize_stage4_iteration_flushes_commits_and_logs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = self._RecordingConnection()
        request = bulk_stage4_loader.Stage4LoadRequest(
            file_type="itcont",
            path=Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(batch_size=2, with_transactions=True),
        )
        load_result = bulk_stage4_loader.LoadResult(inserted=1)
        pending_rows = [
            bulk_stage4_loader._PendingStage4Row(
                source_record_key="SUB-1",
                contribution_record={"committee_id": "C00000001"},
                processed_row_number=1,
            )
        ]
        progress_calls: list[tuple[str, int, int]] = []
        flushed_batches: list[list[bulk_stage4_loader._PendingStage4Row]] = []

        monkeypatch.setattr(
            bulk_stage4_loader,
            "_log_stage4_progress",
            lambda file_type, processed_rows, result: progress_calls.append(
                (file_type, processed_rows, result.inserted)
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_load_stage4_transactions_batch",
            lambda conn, *, request, load_result, rows: (
                flushed_batches.append(list(rows))
                or bulk_stage4_loader._Stage4BatchLoadResult(
                    row_outcomes=(
                        bulk_stage4_loader._Stage4RowLoadOutcome(
                            source_row_committable=True,
                        ),
                    )
                )
            ),
        )

        pending_rows, processed_since_commit = bulk_stage4_loader._finalize_stage4_iteration(
            conn,
            request=request,
            load_result=load_result,
            pending_rows=pending_rows,
            processed_rows=10_000,
            processed_since_commit=2,
        )

        assert pending_rows == []
        assert processed_since_commit == 0
        assert conn.commit_count == 1
        assert progress_calls == [("itcont", 10_000, 1)]
        assert flushed_batches == [
            [
                bulk_stage4_loader._PendingStage4Row(
                    source_record_key="SUB-1",
                    contribution_record={"committee_id": "C00000001"},
                    processed_row_number=1,
                )
            ]
        ]

    def test_batch_commit_appends_shared_progress_after_durable_checkpoint(self, tmp_path: Path) -> None:
        progress_path = tmp_path / "progress.jsonl"
        data_source_id = uuid4()
        conn = self._RecordingConnection()
        request = bulk_stage4_loader.Stage4LoadRequest(
            file_type="itcont",
            path=Path("/tmp/itcont.txt"),
            data_source_id=data_source_id,
            cycle=2026,
            options=bulk_stage4_loader.Stage4LoadOptions(batch_size=2, progress_file=progress_path),
            canonical_resume_enabled=True,
        )
        state = bulk_stage4_loader._Stage4StreamingState(
            load_result=bulk_stage4_loader.LoadResult(inserted=3, skipped=1),
            processed_since_commit=2,
            checkpoint_ready_rows=5,
        )
        checkpoint_context = bulk_stage4_loader._Stage4CheckpointContext(
            archive_reference=bulk_stage4_loader.Stage4ArchiveReference(
                archive_fingerprint="archive-fingerprint",
                archive_member_name="itcont.txt",
            ),
            start_row=100,
        )

        bulk_stage4_loader._commit_stage4_batch_progress(
            conn,
            request=request,
            state=state,
            checkpoint_context=checkpoint_context,
        )

        payload = json.loads(progress_path.read_text(encoding="utf-8"))
        assert set(payload) == {"ts", "source", "rows_total", "rows_delta", "checkpoint", "detail"}
        assert payload["source"] == "stage4_loader"
        assert payload["rows_total"] == 4
        assert payload["rows_delta"] == 4
        assert payload["checkpoint"] == {
            "data_source_id": str(data_source_id),
            "cycle": 2026,
            "file_type": "itcont",
            "next_source_row_number": 105,
        }
        assert payload["detail"] == {"file_type": "itcont"}
        assert state.checkpoint_written_rows == 5
        assert state.processed_since_commit == 0
        assert conn.commit_count == 1

    def test_final_commit_appends_shared_progress_without_fake_checkpoint(self, tmp_path: Path) -> None:
        progress_path = tmp_path / "progress.jsonl"
        conn = self._RecordingConnection()
        request = bulk_stage4_loader.Stage4LoadRequest(
            file_type="itpas2",
            path=Path("/tmp/itpas2.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(batch_size=10, progress_file=progress_path),
        )
        state = bulk_stage4_loader._Stage4StreamingState(
            load_result=bulk_stage4_loader.LoadResult(inserted=7, skipped=2),
            processed_since_commit=3,
            progress_rows_emitted=6,
        )

        assert (
            bulk_stage4_loader._commit_stage4_final_progress(
                conn,
                request=request,
                state=state,
                checkpoint_context=None,
            )
            is True
        )

        payload = json.loads(progress_path.read_text(encoding="utf-8"))
        assert set(payload) == {"ts", "source", "rows_total", "rows_delta", "detail"}
        assert payload["source"] == "stage4_loader"
        assert payload["rows_total"] == 9
        assert payload["rows_delta"] == 3
        assert payload["detail"] == {"file_type": "itpas2"}
        assert state.progress_rows_emitted == 9
        assert state.processed_since_commit == 0
        assert conn.commit_count == 1

    def test_transactions_only_large_batches_use_throughput_flush_floor(self) -> None:
        small_request = bulk_stage4_loader.Stage4LoadRequest(
            file_type="itcont",
            path=Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=2,
                with_transactions=True,
                entity_extraction=False,
            ),
        )
        throughput_request = bulk_stage4_loader.Stage4LoadRequest(
            file_type="itcont",
            path=Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=1000,
                with_transactions=True,
                entity_extraction=False,
            ),
        )
        entity_request = bulk_stage4_loader.Stage4LoadRequest(
            file_type="itcont",
            path=Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=1000,
                with_transactions=True,
                entity_extraction=True,
            ),
        )

        assert bulk_stage4_loader._stage4_flush_row_threshold(small_request) == 2
        assert bulk_stage4_loader._stage4_flush_row_threshold(throughput_request) == 2000
        assert bulk_stage4_loader._stage4_flush_row_threshold(entity_request) == 1000

    def test_replay_stage4_rows_after_batch_failure_updates_accounting(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        request = bulk_stage4_loader.Stage4LoadRequest(
            file_type="itcont",
            path=Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
        )
        load_result = bulk_stage4_loader.LoadResult()
        rows = [
            (
                0,
                bulk_stage4_loader._PendingStage4Row(
                    source_record_key="SUB-1",
                    contribution_record={"committee_id": "C00000001"},
                    processed_row_number=1,
                ),
                uuid4(),
            ),
            (
                1,
                bulk_stage4_loader._PendingStage4Row(
                    source_record_key="SUB-2",
                    contribution_record={"committee_id": "C00000002"},
                    processed_row_number=2,
                ),
                uuid4(),
            ),
            (
                2,
                bulk_stage4_loader._PendingStage4Row(
                    source_record_key="SUB-3",
                    contribution_record={"committee_id": "C00000003"},
                    processed_row_number=3,
                ),
                uuid4(),
            ),
        ]
        replay_outcomes = iter([(True, False), (False, False), RuntimeError("broken row")])

        def replay_row(*args: object, **kwargs: object) -> tuple[bool, bool]:
            del args, kwargs
            outcome = next(replay_outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(bulk_stage4_loader, "_load_stage4_row_with_savepoint", replay_row)

        bulk_stage4_loader._replay_stage4_rows_after_batch_failure(
            conn,
            request=request,
            load_result=load_result,
            row_count=3,
            resolved_rows=rows,
        )

        assert (load_result.inserted, load_result.skipped, load_result.errors) == (1, 1, 1)

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

    def test_relational_row_reports_no_insert_when_transaction_already_exists(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        source_record_id = uuid4()
        filing_id = uuid4()
        transaction_id = uuid4()
        contribution_record = {"sub_id": "SUB-1", "committee_id": "C00000001"}
        upsert_calls: list[object] = []

        monkeypatch.setattr(bulk_stage4_loader, "resolve_source_record_id", lambda *args, **kwargs: source_record_id)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "build_filing_from_contribution",
            lambda *args, **kwargs: SimpleNamespace(committee_id=uuid4()),
        )
        monkeypatch.setattr(bulk_stage4_loader, "upsert_filing", lambda *args, **kwargs: filing_id)
        monkeypatch.setattr(bulk_stage4_loader, "build_transaction_from_contribution", lambda *args, **kwargs: object())

        def _upsert_transaction_with_status(*args: object, **kwargs: object) -> SimpleNamespace:
            del kwargs
            upsert_calls.append(args)
            return SimpleNamespace(transaction_id=transaction_id, inserted=False)

        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_transaction_with_status",
            _upsert_transaction_with_status,
            raising=False,
        )

        inserted = bulk_stage4_loader._load_stage4_relational_row(
            conn,
            data_source_id=uuid4(),
            source_record_key="SUB-1",
            contribution_record=contribution_record,
        )

        assert inserted is False
        assert len(upsert_calls) == 1

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

    def test_transactions_only_bypasses_entity_extraction_but_still_loads_relational_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(1)
        provenance_calls: list[str] = []
        relational_calls: list[str] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_ids_by_fec_ids",
            lambda *args, **kwargs: {"C00000001": uuid4()},
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("entity extraction should be bypassed")),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_insert_stage4_provenance_only",
            lambda *args, **kwargs: provenance_calls.append(kwargs["contribution_record"]["sub_id"]) or True,
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "try_insert_source_records_bulk",
            lambda conn, source_records: [
                provenance_calls.append(str(source_record.source_record_key))
                or SimpleNamespace(source_record_id=uuid4(), inserted=True)
                for source_record in source_records
            ],
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "resolve_source_record_ids",
            lambda *args, **kwargs: {"SUB-1": uuid4()},
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "build_filing_from_contribution",
            lambda conn, contribution_record, **kwargs: SimpleNamespace(
                committee_id=uuid4(),
                filing_fec_id=contribution_record["sub_id"],
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_filings_bulk",
            lambda conn, filings: {str(filing.filing_fec_id): uuid4() for filing in filings},
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "build_transaction_from_contribution",
            lambda conn, contribution_record, **kwargs: SimpleNamespace(sub_id=contribution_record["sub_id"]),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_transactions_with_status_bulk",
            lambda conn, transactions: [
                relational_calls.append(str(transaction.sub_id))
                or SimpleNamespace(transaction_id=uuid4(), inserted=True)
                for transaction in transactions
            ],
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                with_transactions=True,
                entity_extraction=False,
            ),
        )

        assert (result.inserted, result.skipped, result.errors) == (1, 0, 0)
        assert provenance_calls == ["SUB-1"]
        assert relational_calls == ["SUB-1"]

    def test_batched_load_matches_per_row_rows_and_counts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        committee_id = uuid4()
        rows = [
            {"SUB_ID": " SUB-1 ", "TRAN_ID": " TRAN-1 ", "CMTE_ID": " C00000001 ", "DATE": "2024-01-15"},
            {"SUB_ID": "SUB-2", "TRAN_ID": "TRAN-2", "CMTE_ID": "C00000001", "DATE": "2021-12-31"},
            {"SUB_ID": "SUB-3", "TRAN_ID": "TRAN-3", "CMTE_ID": "C00000003", "DATE": "2024-02-20"},
            {"SUB_ID": "   ", "TRAN_ID": "TRAN-4", "CMTE_ID": "C00000001", "DATE": "2024-03-01"},
            {"SUB_ID": "SUB-5", "TRAN_ID": "TRAN-5", "CMTE_ID": " C00000001 ", "DATE": "2024-04-01"},
        ]
        source_record_ids = {"SUB-1": uuid4(), "SUB-5": uuid4()}
        filing_id_by_sub_id = {"SUB-1": uuid4(), "SUB-5": uuid4()}
        committee_lookup_calls: list[list[str]] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(
            bulk_stage4_loader,
            "map_contribution_fields",
            lambda row: {
                "sub_id": row["SUB_ID"],
                "transaction_identifier": row["TRAN_ID"].strip(),
                "committee_id": row["CMTE_ID"],
                "contribution_receipt_date": row["DATE"],
                "contribution_receipt_date_is_reliable": True,
            },
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_ids_by_fec_ids",
            lambda conn, committee_fec_ids: (
                committee_lookup_calls.append(list(committee_fec_ids)) or {"C00000001": committee_id}
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_id_by_fec_id",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("batch path should use batched committee lookup")
            ),
        )
        recorder = self._install_stage4_batch_pipeline_recorders(
            monkeypatch,
            committee_id=committee_id,
            source_record_ids=source_record_ids,
            filing_id_by_sub_id=filing_id_by_sub_id,
            transaction_inserted_by_sub_id={"SUB-1": True, "SUB-5": False},
        )
        self._forbid_stage4_row_writers(monkeypatch)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=2,
                with_transactions=True,
                entity_extraction=False,
                committee_fec_ids=frozenset({"C00000001"}),
                min_transaction_date=date(2022, 1, 1),
            ),
        )

        assert (result.inserted, result.skipped, result.errors) == (2, 2, 1)
        assert committee_lookup_calls == [["C00000001"], ["C00000001"]]
        assert recorder.provenance_writes == [("SUB-1", "C00000001"), ("SUB-5", "C00000001")]
        assert recorder.filing_builds == [
            ("SUB-1", "C00000001", source_record_ids["SUB-1"]),
            ("SUB-5", "C00000001", source_record_ids["SUB-5"]),
        ]
        assert len(recorder.filing_upserts) == 2
        assert recorder.transaction_builds == [
            ("SUB-1", "TRAN-1", filing_id_by_sub_id["SUB-1"], committee_id, source_record_ids["SUB-1"]),
            ("SUB-5", "TRAN-5", filing_id_by_sub_id["SUB-5"], committee_id, source_record_ids["SUB-5"]),
        ]
        assert recorder.transaction_upserts == [("SUB-1", "TRAN-1", True), ("SUB-5", "TRAN-5", False)]
        assert conn.commit_count == 3
        assert conn.statements.count("SAVEPOINT stage4_batch") == 2
        assert conn.statements.count("RELEASE SAVEPOINT stage4_batch") == 2
        assert conn.statements.count("SAVEPOINT stage4_row") == 0
        assert conn.statements.count("ROLLBACK TO SAVEPOINT stage4_row") == 0
        assert conn.statements.count("RELEASE SAVEPOINT stage4_row") == 0

    def test_batched_load_uses_bulk_provenance_without_row_savepoints(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        data_source_id = uuid4()
        committee_id = uuid4()
        source_record_ids = {"SUB-1": uuid4(), "SUB-2": uuid4()}
        filing_id_by_sub_id = {"SUB-1": uuid4(), "SUB-2": uuid4()}
        rows = [
            {"SUB_ID": "SUB-1", "TRAN_ID": "TRAN-1", "CMTE_ID": "C00000001", "DATE": "2024-01-15"},
            {"SUB_ID": "SUB-2", "TRAN_ID": "TRAN-2", "CMTE_ID": "C00000001", "DATE": "2024-01-16"},
        ]
        bulk_provenance_keys: list[str | None] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(
            bulk_stage4_loader,
            "map_contribution_fields",
            lambda row: {
                "sub_id": row["SUB_ID"],
                "transaction_identifier": row["TRAN_ID"],
                "committee_id": row["CMTE_ID"],
                "contribution_receipt_date": row["DATE"],
                "contribution_receipt_date_is_reliable": True,
            },
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_ids_by_fec_ids",
            lambda conn, committee_fec_ids: {"C00000001": committee_id},
        )
        recorder = self._install_stage4_batch_pipeline_recorders(
            monkeypatch,
            committee_id=committee_id,
            source_record_ids=source_record_ids,
            filing_id_by_sub_id=filing_id_by_sub_id,
            transaction_inserted_by_sub_id={"SUB-1": True, "SUB-2": False},
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_insert_stage4_provenance_only",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("clean batch path must use bulk provenance")),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "try_insert_source_records_bulk",
            lambda conn, source_records: [
                bulk_provenance_keys.append(source_record.source_record_key)
                or SimpleNamespace(
                    source_record_id=source_record_ids[str(source_record.source_record_key)], inserted=True
                )
                for source_record in source_records
            ],
            raising=False,
        )
        self._forbid_stage4_row_writers(monkeypatch)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=data_source_id,
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                with_transactions=True,
                entity_extraction=False,
                committee_fec_ids=frozenset({"C00000001"}),
                min_transaction_date=date(2022, 1, 1),
            ),
        )

        assert (result.inserted, result.skipped, result.errors) == (2, 0, 0)
        assert bulk_provenance_keys == ["SUB-1", "SUB-2"]
        assert recorder.provenance_writes == []
        assert recorder.filing_builds == [
            ("SUB-1", "C00000001", source_record_ids["SUB-1"]),
            ("SUB-2", "C00000001", source_record_ids["SUB-2"]),
        ]
        assert recorder.transaction_builds == [
            ("SUB-1", "TRAN-1", filing_id_by_sub_id["SUB-1"], committee_id, source_record_ids["SUB-1"]),
            ("SUB-2", "TRAN-2", filing_id_by_sub_id["SUB-2"], committee_id, source_record_ids["SUB-2"]),
        ]
        assert recorder.transaction_upserts == [("SUB-1", "TRAN-1", True), ("SUB-2", "TRAN-2", False)]
        assert conn.statements.count("SAVEPOINT stage4_batch") == 1
        assert conn.statements.count("RELEASE SAVEPOINT stage4_batch") == 1
        assert conn.statements.count("SAVEPOINT stage4_row") == 0
        assert conn.statements.count("ROLLBACK TO SAVEPOINT stage4_row") == 0
        assert conn.statements.count("RELEASE SAVEPOINT stage4_row") == 0

    def test_batch_with_one_bad_row_isolates_only_that_row(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(3)
        loaded_source_keys: list[str] = []
        committee_lookup_calls: list[list[str]] = []
        relational_outcomes = iter([True, RuntimeError("broken transaction row"), True])

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_ids_by_fec_ids",
            lambda conn, committee_fec_ids: (
                committee_lookup_calls.append(list(committee_fec_ids)) or {row["CMTE_ID"]: uuid4() for row in rows}
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_id_by_fec_id",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("transactions-only batch path should not call row committee lookup")
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_insert_stage4_provenance_only",
            lambda *args, **kwargs: loaded_source_keys.append(kwargs["contribution_record"]["sub_id"]) or True,
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "try_insert_source_records_bulk",
            lambda conn, source_records: [
                loaded_source_keys.append(str(source_record.source_record_key))
                or SimpleNamespace(source_record_id=uuid4(), inserted=True)
                for source_record in source_records
            ],
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_filings_bulk",
            lambda *args, **kwargs: {"SUB-1": uuid4(), "SUB-2": uuid4(), "SUB-3": uuid4()},
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "build_filing_from_contribution",
            lambda conn, contribution_record, **kwargs: SimpleNamespace(
                filing_fec_id=contribution_record["sub_id"],
                committee_id=uuid4(),
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "build_transaction_from_contribution",
            lambda conn, contribution_record, **kwargs: SimpleNamespace(sub_id=contribution_record["sub_id"]),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_transactions_with_status_bulk",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broken batch")),
        )

        def _load_relational_row(*args: object, **kwargs: object) -> bool:
            del args, kwargs
            next_outcome = next(relational_outcomes)
            if isinstance(next_outcome, Exception):
                raise next_outcome
            return next_outcome

        monkeypatch.setattr(bulk_stage4_loader, "_load_stage4_relational_row", _load_relational_row)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                with_transactions=True,
                entity_extraction=False,
            ),
        )

        assert (result.inserted, result.skipped, result.errors) == (2, 0, 1)
        assert committee_lookup_calls == [["C00000001", "C00000002", "C00000003"]]
        assert loaded_source_keys == ["SUB-1", "SUB-2", "SUB-3", "SUB-1", "SUB-2", "SUB-3"]
        assert conn.commit_count == 1
        assert conn.statements.count("SAVEPOINT stage4_batch") == 1
        assert conn.statements.count("ROLLBACK TO SAVEPOINT stage4_batch") == 1
        assert conn.statements.count("RELEASE SAVEPOINT stage4_batch") == 1
        assert conn.statements.count("SAVEPOINT stage4_row") == 3
        assert conn.statements.count("ROLLBACK TO SAVEPOINT stage4_row") == 1
        assert conn.statements.count("RELEASE SAVEPOINT stage4_row") == 3

    def test_duplicate_sub_id_is_skipped_not_double_inserted(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(2)
        source_id = uuid4()
        source_record_ids = {(str(source_id), row["SUB_ID"]): uuid4() for row in rows}
        inserted_source_keys: set[tuple[str, str]] = set()
        inserted_transaction_keys: set[str] = set()
        provenance_outcomes: list[tuple[str, str, bool]] = []
        transaction_outcomes: list[tuple[str, bool]] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_ids_by_fec_ids",
            lambda *args, **kwargs: {row["CMTE_ID"]: uuid4() for row in rows},
        )

        def _insert_provenance_result(data_source_id: object, source_key: str) -> SimpleNamespace:
            source_record_key = (str(data_source_id), source_key)
            inserted = source_record_key not in inserted_source_keys
            inserted_source_keys.add(source_record_key)
            provenance_outcomes.append((*source_record_key, inserted))
            return SimpleNamespace(source_record_id=source_record_ids[source_record_key], inserted=inserted)

        def _insert_provenance(
            conn: object,
            *,
            data_source_id: object,
            contribution_record: dict[str, object],
        ) -> bool:
            del conn
            source_key = str(contribution_record["sub_id"])
            return bool(_insert_provenance_result(data_source_id, source_key).inserted)

        def _insert_provenance_bulk(conn: object, source_records: list[object]) -> list[SimpleNamespace]:
            del conn
            return [
                _insert_provenance_result(source_record.data_source_id, str(source_record.source_record_key))
                for source_record in source_records
            ]

        def _upsert_transaction_with_status(conn: object, transaction: SimpleNamespace) -> SimpleNamespace:
            del conn
            inserted = transaction.sub_id not in inserted_transaction_keys
            inserted_transaction_keys.add(transaction.sub_id)
            transaction_outcomes.append((transaction.sub_id, inserted))
            return SimpleNamespace(transaction_id=uuid4(), inserted=inserted)

        monkeypatch.setattr(bulk_stage4_loader, "_insert_stage4_provenance_only", _insert_provenance)
        monkeypatch.setattr(bulk_stage4_loader, "try_insert_source_records_bulk", _insert_provenance_bulk)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "resolve_source_record_ids",
            lambda conn, data_source_id, source_record_keys: {
                source_record_key: source_record_ids[(str(data_source_id), source_record_key)]
                for source_record_key in source_record_keys
            },
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "build_filing_from_contribution",
            lambda conn, contribution_record, **kwargs: SimpleNamespace(
                committee_id=uuid4(),
                filing_fec_id=contribution_record["sub_id"],
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_filings_bulk",
            lambda conn, filings: {str(filing.filing_fec_id): uuid4() for filing in filings},
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "build_transaction_from_contribution",
            lambda conn, contribution_record, **kwargs: SimpleNamespace(sub_id=contribution_record["sub_id"]),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_transactions_with_status_bulk",
            lambda conn, transactions: [
                _upsert_transaction_with_status(conn, transaction) for transaction in transactions
            ],
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("transactions-only should bypass entities")),
        )

        first_result = self._load_transactions_only(conn, data_source_id=source_id)
        second_result = self._load_transactions_only(conn, data_source_id=source_id)

        assert (first_result.inserted, first_result.skipped, first_result.errors) == (2, 0, 0)
        assert (second_result.inserted, second_result.skipped, second_result.errors) == (0, 2, 0)
        assert provenance_outcomes == [
            (str(source_id), "SUB-1", True),
            (str(source_id), "SUB-2", True),
            (str(source_id), "SUB-1", False),
            (str(source_id), "SUB-2", False),
        ]
        assert transaction_outcomes == [
            ("SUB-1", True),
            ("SUB-2", True),
            ("SUB-1", False),
            ("SUB-2", False),
        ]

    def test_committee_lookup_is_cached(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = [
            {"SUB_ID": "SUB-1", "CMTE_ID": "C00000001"},
            {"SUB_ID": "SUB-2", "CMTE_ID": "C00000001"},
            {"SUB_ID": "SUB-3", "CMTE_ID": "C00000001"},
            {"SUB_ID": "SUB-4", "CMTE_ID": "C99999999"},
        ]
        committee_lookup_calls: list[str] = []
        provenance_calls: list[str] = []
        relational_calls: list[str] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)

        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_ids_by_fec_ids",
            lambda conn, committee_fec_ids: (
                committee_lookup_calls.extend(list(committee_fec_ids))
                or {
                    "C00000001": uuid4(),
                }
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_id_by_fec_id",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("transactions-only batch path should not call row committee lookup")
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_insert_stage4_provenance_only",
            lambda *args, **kwargs: provenance_calls.append(kwargs["contribution_record"]["sub_id"]) or True,
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "try_insert_source_records_bulk",
            lambda conn, source_records: [
                provenance_calls.append(str(source_record.source_record_key))
                or SimpleNamespace(source_record_id=uuid4(), inserted=True)
                for source_record in source_records
            ],
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "resolve_source_record_ids",
            lambda conn, data_source_id, source_record_keys: {
                source_record_key: uuid4() for source_record_key in source_record_keys
            },
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "build_filing_from_contribution",
            lambda conn, contribution_record, **kwargs: SimpleNamespace(
                committee_id=uuid4(),
                filing_fec_id=contribution_record["sub_id"],
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_filings_bulk",
            lambda conn, filings: {str(filing.filing_fec_id): uuid4() for filing in filings},
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "build_transaction_from_contribution",
            lambda conn, contribution_record, **kwargs: SimpleNamespace(sub_id=contribution_record["sub_id"]),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "upsert_transactions_with_status_bulk",
            lambda conn, transactions: [
                relational_calls.append(str(transaction.sub_id))
                or SimpleNamespace(transaction_id=uuid4(), inserted=True)
                for transaction in transactions
            ],
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                with_transactions=True,
                entity_extraction=False,
            ),
        )

        assert (result.inserted, result.skipped, result.errors) == (3, 0, 1)
        assert provenance_calls == ["SUB-1", "SUB-2", "SUB-3"]
        assert relational_calls == ["SUB-1", "SUB-2", "SUB-3"]
        assert committee_lookup_calls == ["C00000001", "C99999999"]

    def test_committee_and_date_filters_run_before_shared_persistence(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = [
            {"SUB_ID": "SUB-1", "CMTE_ID": "C00000001"},
            {"SUB_ID": "SUB-2", "CMTE_ID": "C00000002"},
        ]
        persisted_rows: list[str] = []

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(
            bulk_stage4_loader,
            "map_contribution_fields",
            lambda row: {
                "sub_id": row["SUB_ID"],
                "committee_id": row["CMTE_ID"],
                "contribution_receipt_date": "2021-12-31" if row["SUB_ID"] == "SUB-1" else "2024-01-15",
                "contribution_receipt_date_is_reliable": True,
            },
        )
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: uuid4())
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: persisted_rows.append(args[2]["sub_id"]) or True,
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                committee_fec_ids=frozenset({"C00000002"}),
                min_transaction_date=date(2022, 1, 1),
            ),
        )

        assert (result.inserted, result.skipped, result.errors) == (1, 1, 0)
        assert persisted_rows == ["SUB-2"]

    def test_limit_applies_after_committee_and_date_filters(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        committee_id = uuid4()
        rows = [
            {"SUB_ID": "SUB-1", "TRAN_ID": "TRAN-1", "CMTE_ID": "C00000001", "DATE": "2024-01-01"},
            {"SUB_ID": "SUB-2", "TRAN_ID": "TRAN-2", "CMTE_ID": "C00000002", "DATE": "2021-12-31"},
            {"SUB_ID": "SUB-3", "TRAN_ID": "TRAN-3", "CMTE_ID": "C00000002", "DATE": "2024-01-03"},
            {"SUB_ID": "SUB-4", "TRAN_ID": "TRAN-4", "CMTE_ID": "C00000003", "DATE": "2024-01-04"},
            {"SUB_ID": "SUB-5", "TRAN_ID": "TRAN-5", "CMTE_ID": "C00000002", "DATE": "2024-01-05"},
        ]
        parser_limits: list[int | None] = []
        source_record_ids = {"SUB-3": uuid4(), "SUB-5": uuid4()}
        filing_id_by_sub_id = {"SUB-3": uuid4(), "SUB-5": uuid4()}

        def _read_rows(path: object, file_type: str, limit: int | None = None) -> object:
            del path, file_type
            parser_limits.append(limit)
            return iter(rows)

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", _read_rows)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "map_contribution_fields",
            lambda row: {
                "sub_id": row["SUB_ID"],
                "transaction_identifier": row["TRAN_ID"],
                "committee_id": row["CMTE_ID"],
                "contribution_receipt_date": row["DATE"],
                "contribution_receipt_date_is_reliable": True,
            },
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_ids_by_fec_ids",
            lambda conn, committee_fec_ids: {"C00000002": committee_id},
        )
        recorder = self._install_stage4_batch_pipeline_recorders(
            monkeypatch,
            committee_id=committee_id,
            source_record_ids=source_record_ids,
            filing_id_by_sub_id=filing_id_by_sub_id,
            transaction_inserted_by_sub_id={"SUB-3": True, "SUB-5": True},
        )
        self._forbid_stage4_row_writers(monkeypatch)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                limit=2,
                with_transactions=True,
                entity_extraction=False,
                committee_fec_ids=frozenset({"C00000002"}),
                min_transaction_date=date(2022, 1, 1),
            ),
        )

        assert parser_limits == [None]
        assert (result.inserted, result.skipped, result.errors) == (2, 0, 0)
        assert recorder.provenance_writes == [("SUB-3", "C00000002"), ("SUB-5", "C00000002")]
        assert recorder.transaction_upserts == [("SUB-3", "TRAN-3", True), ("SUB-5", "TRAN-5", True)]

    def test_count_only_counts_filtered_rows_without_writes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        rows = self._build_stage4_rows(2)

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not write")),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_load_stage4_relational_row",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not write")),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "try_insert_source_record",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not write")),
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                count_only=True,
            ),
        )

        assert (result.inserted, result.skipped, result.errors) == (2, 0, 0)

    @pytest.mark.parametrize(
        ("options", "expected_result", "expected_loaded_sub_ids"),
        [
            pytest.param(
                bulk_stage4_loader.Stage4LoadOptions(batch_size=100),
                (2, 0, 0),
                ["SUB-1", "SUB-2"],
                id="unfiltered-single-file",
            ),
            pytest.param(
                bulk_stage4_loader.Stage4LoadOptions(batch_size=100, limit=1),
                (1, 0, 0),
                ["SUB-1"],
                id="bounded-limit",
            ),
            pytest.param(
                bulk_stage4_loader.Stage4LoadOptions(
                    batch_size=100,
                    committee_fec_ids=frozenset({"C00000002"}),
                ),
                (1, 1, 0),
                ["SUB-2"],
                id="committee-scope",
            ),
            pytest.param(
                bulk_stage4_loader.Stage4LoadOptions(
                    batch_size=100,
                    min_transaction_date=date(2022, 1, 1),
                ),
                (1, 1, 0),
                ["SUB-2"],
                id="date-scope",
            ),
            pytest.param(
                bulk_stage4_loader.Stage4LoadOptions(batch_size=100, count_only=True),
                (2, 0, 0),
                [],
                id="count-only",
            ),
        ],
    )
    def test_non_canonical_stage4_requests_do_not_touch_canonical_checkpoint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        options: bulk_stage4_loader.Stage4LoadOptions,
        expected_result: tuple[int, int, int],
        expected_loaded_sub_ids: list[str],
    ) -> None:
        conn = self._RecordingConnection()
        rows = [
            {"SUB_ID": "SUB-1", "CMTE_ID": "C00000001", "DATE": "2021-12-31"},
            {"SUB_ID": "SUB-2", "CMTE_ID": "C00000002", "DATE": "2024-01-01"},
        ]
        read_start_rows: list[int] = []
        loaded_sub_ids: list[str] = []

        monkeypatch.setattr(
            bulk_stage4_loader,
            "_build_stage4_archive_reference",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("non-canonical Stage 4 requests must not read checkpoint archive identity")
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_select_stage4_resume_checkpoint",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("non-canonical Stage 4 requests must not read the canonical checkpoint")
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_write_stage4_resume_checkpoint",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("non-canonical Stage 4 requests must not mutate the canonical checkpoint")
            ),
        )

        def _read_rows(
            path: object,
            file_type: str,
            limit: int | None = None,
            *,
            next_source_row_number: int = 0,
        ) -> object:
            del path, file_type, limit
            read_start_rows.append(next_source_row_number)
            return iter(rows[next_source_row_number:])

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", _read_rows)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "map_contribution_fields",
            lambda row: {
                "sub_id": row["SUB_ID"],
                "committee_id": row["CMTE_ID"],
                "contribution_receipt_date": row["DATE"],
                "contribution_receipt_date_is_reliable": True,
            },
        )
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: uuid4())
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda conn, data_source_id, contribution, **kwargs: loaded_sub_ids.append(contribution["sub_id"]) or True,
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=uuid4(),
            options=options,
        )

        assert read_start_rows == [0]
        assert loaded_sub_ids == expected_loaded_sub_ids
        assert (result.inserted, result.skipped, result.errors) == expected_result

    def test_load_contributions_threads_resume_cursor_to_parser(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        data_source_id = uuid4()
        identity = bulk_stage4_loader.build_stage4_resume_identity(
            data_source_id=data_source_id,
            cycle=2026,
            file_type="itcont",
        )
        rows = self._build_stage4_rows(4)
        read_calls: list[tuple[str, int | None, int]] = []
        persisted_rows: list[str] = []

        monkeypatch.setattr(
            bulk_stage4_loader,
            "_build_stage4_archive_reference",
            lambda path, file_type: bulk_stage4_loader.Stage4ArchiveReference(
                archive_fingerprint="fingerprint",
                archive_member_name=None,
            ),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_select_stage4_resume_checkpoint",
            lambda conn, resume_identity: bulk_stage4_loader.Stage4ResumeCheckpoint(
                resume_identity=identity,
                archive_fingerprint="fingerprint",
                archive_member_name=None,
                next_source_row_number=2,
            ),
        )

        def _read_rows(
            path: object,
            file_type: str,
            limit: int | None = None,
            *,
            next_source_row_number: int = 0,
        ) -> object:
            del path
            read_calls.append((file_type, limit, next_source_row_number))
            return iter(rows[next_source_row_number:])

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", _read_rows)
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: uuid4())
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda conn, data_source_id, contribution, **kwargs: persisted_rows.append(contribution["sub_id"]) or True,
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            canonical_resume_enabled=True,
            batch_size=100,
        )

        assert read_calls == [("itcont", None, 2)]
        assert persisted_rows == ["SUB-3", "SUB-4"]
        assert (result.inserted, result.skipped, result.errors) == (2, 0, 0)

    def test_stale_checkpoint_rewrite_commits_before_streaming(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        data_source_id = uuid4()
        events: list[str] = []
        writes = self._install_stale_stage4_checkpoint(monkeypatch, data_source_id=data_source_id)

        original_commit = conn.commit

        def _commit() -> None:
            events.append("commit")
            original_commit()

        def _read_rows(
            path: object,
            file_type: str,
            limit: int | None = None,
            *,
            next_source_row_number: int = 0,
        ) -> object:
            del path, file_type, limit, next_source_row_number
            events.append("stream")
            return iter(())

        conn.commit = _commit
        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", _read_rows)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            canonical_resume_enabled=True,
            batch_size=100,
        )

        assert (result.inserted, result.skipped, result.errors) == (0, 0, 0)
        assert [checkpoint.next_source_row_number for checkpoint in writes] == [0]
        assert events == ["commit", "stream"]

    def test_checkpoint_advances_after_successful_committed_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        data_source_id = uuid4()
        rows = self._build_stage4_rows(3)
        checkpoints: list[int] = []
        persisted_rows: list[str] = []

        monkeypatch.setattr(
            bulk_stage4_loader,
            "_build_stage4_archive_reference",
            lambda path, file_type: bulk_stage4_loader.Stage4ArchiveReference(
                archive_fingerprint="fingerprint",
                archive_member_name=None,
            ),
        )
        monkeypatch.setattr(bulk_stage4_loader, "_select_stage4_resume_checkpoint", lambda conn, resume_identity: None)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_write_stage4_resume_checkpoint",
            lambda conn, checkpoint: checkpoints.append(checkpoint.next_source_row_number),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "read_bulk_file",
            lambda path, file_type, limit=None, *, next_source_row_number=0: iter(rows[next_source_row_number:]),
        )
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: uuid4())
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda conn, data_source_id, contribution, **kwargs: persisted_rows.append(contribution["sub_id"]) or True,
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            canonical_resume_enabled=True,
            batch_size=2,
        )

        assert persisted_rows == ["SUB-1", "SUB-2", "SUB-3"]
        assert checkpoints == [2, 3]
        assert conn.commit_count == 2
        assert (result.inserted, result.skipped, result.errors) == (3, 0, 0)

    def test_transactions_only_checkpoint_advances_from_batch_commit_owner(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        data_source_id = uuid4()
        rows = self._build_stage4_rows(2)
        source_record_ids = {row["SUB_ID"]: uuid4() for row in rows}
        filing_id_by_sub_id = {row["SUB_ID"]: uuid4() for row in rows}
        checkpoints: list[int] = []

        monkeypatch.setattr(
            bulk_stage4_loader,
            "_build_stage4_archive_reference",
            lambda path, file_type: bulk_stage4_loader.Stage4ArchiveReference(
                archive_fingerprint="fingerprint",
                archive_member_name=None,
            ),
        )
        monkeypatch.setattr(bulk_stage4_loader, "_select_stage4_resume_checkpoint", lambda conn, resume_identity: None)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_write_stage4_resume_checkpoint",
            lambda conn, checkpoint: checkpoints.append(checkpoint.next_source_row_number),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "read_bulk_file",
            lambda path, file_type, limit=None, *, next_source_row_number=0: iter(rows[next_source_row_number:]),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "map_contribution_fields",
            lambda row: {
                "sub_id": row["SUB_ID"],
                "transaction_identifier": row["SUB_ID"],
                "committee_id": row["CMTE_ID"],
            },
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_ids_by_fec_ids",
            lambda conn, committee_fec_ids: {row["CMTE_ID"]: uuid4() for row in rows},
        )
        self._install_stage4_batch_pipeline_recorders(
            monkeypatch,
            committee_id=uuid4(),
            source_record_ids=source_record_ids,
            filing_id_by_sub_id=filing_id_by_sub_id,
            transaction_inserted_by_sub_id={row["SUB_ID"]: True for row in rows},
        )
        self._forbid_stage4_row_writers(monkeypatch)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=2,
                with_transactions=True,
                entity_extraction=False,
                canonical_resume_enabled=True,
            ),
        )

        assert checkpoints == [2]
        assert conn.commit_count == 2
        assert (result.inserted, result.skipped, result.errors) == (2, 0, 0)

    def test_checkpoint_does_not_advance_without_committed_work(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        data_source_id = uuid4()
        rows = self._build_stage4_rows(2)
        checkpoints: list[int] = []

        monkeypatch.setattr(
            bulk_stage4_loader,
            "_build_stage4_archive_reference",
            lambda path, file_type: bulk_stage4_loader.Stage4ArchiveReference(
                archive_fingerprint="fingerprint",
                archive_member_name=None,
            ),
        )
        monkeypatch.setattr(bulk_stage4_loader, "_select_stage4_resume_checkpoint", lambda conn, resume_identity: None)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_write_stage4_resume_checkpoint",
            lambda conn, checkpoint: checkpoints.append(checkpoint.next_source_row_number),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "read_bulk_file",
            lambda path, file_type, limit=None, *, next_source_row_number=0: iter(rows[next_source_row_number:]),
        )
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("filtered rows should not write")),
        )

        filtered_result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                committee_fec_ids=frozenset({"C99999999"}),
            ),
        )
        count_only_result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                count_only=True,
            ),
        )
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: None)
        failed_result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            batch_size=100,
        )

        assert (filtered_result.inserted, filtered_result.skipped, filtered_result.errors) == (0, 2, 0)
        assert (count_only_result.inserted, count_only_result.skipped, count_only_result.errors) == (2, 0, 0)
        assert (failed_result.inserted, failed_result.skipped, failed_result.errors) == (0, 0, 2)
        assert checkpoints == []

    def test_checkpoint_advances_after_idempotent_canonical_replay(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        data_source_id = uuid4()
        rows = self._build_stage4_rows(2)
        checkpoints: list[int] = []

        monkeypatch.setattr(
            bulk_stage4_loader,
            "_build_stage4_archive_reference",
            lambda path, file_type: bulk_stage4_loader.Stage4ArchiveReference(
                archive_fingerprint="fingerprint",
                archive_member_name=None,
            ),
        )
        monkeypatch.setattr(bulk_stage4_loader, "_select_stage4_resume_checkpoint", lambda conn, resume_identity: None)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_write_stage4_resume_checkpoint",
            lambda conn, checkpoint: checkpoints.append(checkpoint.next_source_row_number),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "read_bulk_file",
            lambda path, file_type, limit=None, *, next_source_row_number=0: iter(rows[next_source_row_number:]),
        )
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: uuid4())
        monkeypatch.setattr(bulk_stage4_loader, "load_contribution", lambda *args, **kwargs: False)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            canonical_resume_enabled=True,
            batch_size=100,
        )

        assert (result.inserted, result.skipped, result.errors) == (0, 2, 0)
        assert checkpoints == [2]
        assert conn.commit_count == 1

    def test_checkpoint_stops_at_first_failed_row_in_mixed_commit_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = self._RecordingConnection()
        data_source_id = uuid4()
        rows = self._build_stage4_rows(3)
        checkpoints: list[int] = []
        load_outcomes = iter([True, RuntimeError("broken row"), True])

        monkeypatch.setattr(
            bulk_stage4_loader,
            "_build_stage4_archive_reference",
            lambda path, file_type: bulk_stage4_loader.Stage4ArchiveReference(
                archive_fingerprint="fingerprint",
                archive_member_name=None,
            ),
        )
        monkeypatch.setattr(bulk_stage4_loader, "_select_stage4_resume_checkpoint", lambda conn, resume_identity: None)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_write_stage4_resume_checkpoint",
            lambda conn, checkpoint: checkpoints.append(checkpoint.next_source_row_number),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "read_bulk_file",
            lambda path, file_type, limit=None, *, next_source_row_number=0: iter(rows[next_source_row_number:]),
        )
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda *args, **kwargs: uuid4())

        def _load_contribution(*args: object, **kwargs: object) -> bool:
            del args, kwargs
            outcome = next(load_outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(bulk_stage4_loader, "load_contribution", _load_contribution)

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            cycle=2026,
            data_source_id=data_source_id,
            canonical_resume_enabled=True,
            batch_size=3,
        )

        assert (result.inserted, result.skipped, result.errors) == (2, 0, 1)
        assert checkpoints == [1]
        assert conn.commit_count == 2

    def test_count_only_honors_committee_scope_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Count-only must apply the committee_fec_ids filter before counting: 3 rows in, 1 in scope,
        so (inserted=1, skipped=2, errors=0) with no write-path calls."""
        conn = self._RecordingConnection()
        rows = [
            {"SUB_ID": "SUB-1", "CMTE_ID": "C00000001"},
            {"SUB_ID": "SUB-2", "CMTE_ID": "C00000002"},
            {"SUB_ID": "SUB-3", "CMTE_ID": "C00000003"},
        ]

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", self._map_row)
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not write")),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_load_stage4_relational_row",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not write")),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "try_insert_source_record",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not write")),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "find_committee_id_by_fec_id",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not resolve committees")),
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                count_only=True,
                committee_fec_ids=frozenset({"C00000002"}),
            ),
        )

        assert (result.inserted, result.skipped, result.errors) == (1, 2, 0)

    def test_count_only_honors_min_transaction_date_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Count-only must apply the min_transaction_date filter before counting: rows earlier than
        the cutoff are skipped, rows on/after are counted as inserted, and rows without
        a reliable parsed date are also skipped, with no writes."""
        conn = self._RecordingConnection()
        rows = [
            {"SUB_ID": "SUB-1", "CMTE_ID": "C00000001", "DATE": "2021-12-31", "RELIABLE": True},
            {"SUB_ID": "SUB-2", "CMTE_ID": "C00000001", "DATE": "2022-01-01", "RELIABLE": True},
            {"SUB_ID": "SUB-3", "CMTE_ID": "C00000001", "DATE": "2024-06-15", "RELIABLE": True},
            {"SUB_ID": "SUB-4", "CMTE_ID": "C00000001", "DATE": None, "RELIABLE": True},
            {"SUB_ID": "SUB-5", "CMTE_ID": "C00000001", "DATE": None, "RELIABLE": False},
        ]

        monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(rows))
        monkeypatch.setattr(
            bulk_stage4_loader,
            "map_contribution_fields",
            lambda row: {
                "sub_id": row["SUB_ID"],
                "committee_id": row["CMTE_ID"],
                "contribution_receipt_date": row["DATE"],
                "contribution_receipt_date_is_reliable": row["RELIABLE"],
            },
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "load_contribution",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not write")),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "_load_stage4_relational_row",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not write")),
        )
        monkeypatch.setattr(
            bulk_stage4_loader,
            "try_insert_source_record",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("count-only should not write")),
        )

        result = bulk_loader.load_contributions(
            conn,
            Path("/tmp/itcont.txt"),
            data_source_id=uuid4(),
            options=bulk_stage4_loader.Stage4LoadOptions(
                batch_size=100,
                count_only=True,
                min_transaction_date=date(2022, 1, 1),
            ),
        )

        assert (result.inserted, result.skipped, result.errors) == (2, 3, 0)
