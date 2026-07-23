from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from domains.campaign_finance.ingest import bulk_loader
from domains.campaign_finance.ingest import bulk_stage4_loader


class _RecordingCursor:
    def __init__(self, statements: list[str]) -> None:
        self._statements = statements

    def __enter__(self) -> _RecordingCursor:
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

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self.statements)

    def commit(self) -> None:
        self.commit_count += 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("loader_name", "file_type"),
    [
        ("load_committees", "cm"),
        ("load_candidates", "cn"),
        ("load_candidate_committee_links", "ccl"),
    ],
)
def test_stage3_loaders_forward_limit_to_read_bulk_file(
    loader_name: str,
    file_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_limits: list[int | None] = []

    def _read_bulk_file(path: str | Path, selected_file_type: str, limit: int | None = None):
        del path
        captured_limits.append(limit)
        assert selected_file_type == file_type
        return iter(())

    monkeypatch.setattr(bulk_loader, "read_bulk_file", _read_bulk_file)

    loader = getattr(bulk_loader, loader_name)
    result = loader(
        _RecordingConnection(),
        Path(f"/tmp/{file_type}_sample.txt"),
        cycle=2024,
        data_source_id=uuid4(),
        batch_size=2,
        limit=17,
    )

    assert captured_limits == [17]
    assert (result.inserted, result.skipped, result.errors) == (0, 0, 0)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("loader_name", "file_type"),
    [
        ("load_contributions", "itcont"),
        ("load_committee_transactions", "itpas2"),
    ],
)
def test_stage4_loaders_forward_limit_and_graph_enabled(
    loader_name: str,
    file_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _RecordingConnection()
    captured_limits: list[int | None] = []
    captured_graph_flags: list[bool] = []

    raw_row = {
        "SUB_ID": "SUB-1",
        "CMTE_ID": "C00000001",
        "CAND_ID": "H0ZZ00001",
    }

    def _read_bulk_file(path: str | Path, selected_file_type: str, limit: int | None = None):
        del path
        captured_limits.append(limit)
        assert selected_file_type == file_type
        return iter([raw_row])

    def _map_contribution_fields(row: dict[str, str]) -> dict[str, object]:
        return {
            "sub_id": row["SUB_ID"],
            "committee_id": row["CMTE_ID"],
            "candidate_fec_id": row.get("CAND_ID"),
        }

    def _load_contribution(
        conn: object,
        data_source_id: UUID,
        contribution: dict[str, object],
        *,
        graph_enabled: bool,
    ) -> bool:
        del conn, data_source_id, contribution
        captured_graph_flags.append(graph_enabled)
        return True

    monkeypatch.setattr(bulk_stage4_loader, "read_bulk_file", _read_bulk_file)
    monkeypatch.setattr(bulk_stage4_loader, "map_contribution_fields", _map_contribution_fields)
    monkeypatch.setattr(bulk_stage4_loader, "find_committee_id_by_fec_id", lambda conn, committee_id: uuid4())
    monkeypatch.setattr(bulk_stage4_loader, "load_contribution", _load_contribution)

    loader = getattr(bulk_loader, loader_name)
    result = loader(
        connection,
        Path(f"/tmp/{file_type}_sample.txt"),
        data_source_id=uuid4(),
        batch_size=2,
        limit=11,
        graph_enabled=True,
    )

    # The streaming stage4 loader reads the source unbounded (limit=None) and
    # enforces the caller's limit downstream via _stage4_limit_reached early-break,
    # rather than forwarding the limit into read_bulk_file. Asserting [None] pins
    # that throughput contract: forwarding a concrete limit here would signal a
    # regression back to the pre-throughput eager-read design.
    assert captured_limits == [None]
    assert captured_graph_flags == [True]
    assert (result.inserted, result.skipped, result.errors) == (1, 0, 0)


@pytest.mark.unit
def test_normalize_optional_state_code_drops_invalid_real_fec_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")

    assert bulk_loader._normalize_optional_state_code("14") is None
    assert "Dropping invalid FEC state code '14'" in caplog.text


@pytest.mark.unit
def test_build_fec_mailing_address_omits_invalid_state_code() -> None:
    address = bulk_loader._build_fec_mailing_address(
        "1901 BUTTERFIELD RD",
        "STE 120",
        "DOWNERS GROVE",
        "14",
        "60515",
    )

    assert address is not None
    assert address.state is None
    assert address.city == "DOWNERS GROVE"
    assert address.zip5 == "60515"
    assert address.raw_address == "1901 BUTTERFIELD RD, STE 120, DOWNERS GROVE 60515"


@pytest.mark.unit
def test_load_committees_progress_logging_emits_at_ten_thousand_rows(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = _RecordingConnection()
    raw_rows = [{"CMTE_ID": f"C{index:08d}", "CMTE_NM": f"Committee {index}"} for index in range(1, 10001)]

    monkeypatch.setattr(bulk_loader, "read_bulk_file", lambda path, file_type, limit=None: iter(raw_rows))
    monkeypatch.setattr(
        bulk_loader,
        "map_committee_fields",
        lambda row: {
            "fec_committee_id": row["CMTE_ID"],
            "name": row["CMTE_NM"],
            "committee_type": None,
            "committee_designation": None,
            "party": None,
            "state": None,
            "city": None,
            "zip_code": None,
            "treasurer_name": None,
        },
    )
    monkeypatch.setattr(bulk_loader, "_try_insert_bulk_source_record", lambda *args, **kwargs: uuid4())
    monkeypatch.setattr(bulk_loader, "find_organization_by_identifier", lambda *args, **kwargs: uuid4())
    monkeypatch.setattr(bulk_loader, "insert_entity_source", lambda *args, **kwargs: uuid4())
    monkeypatch.setattr(bulk_loader, "_link_row_mailing_address", lambda *args, **kwargs: None)
    monkeypatch.setattr(bulk_loader, "_upsert_committee", lambda *args, **kwargs: None)

    caplog.set_level("INFO")

    result = bulk_loader.load_committees(
        connection,
        Path("/tmp/cm.txt"),
        cycle=2024,
        data_source_id=uuid4(),
        batch_size=50000,
    )

    assert (result.inserted, result.skipped, result.errors) == (10000, 0, 0)
    assert "Processed 10000 cm rows" in caplog.text
