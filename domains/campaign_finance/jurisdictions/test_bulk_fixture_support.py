from contextlib import ExitStack
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from domains.campaign_finance.jurisdictions import _bulk_fixture_support


def test_bulk_fixture_exposes_neutral_input_path_and_committee_id() -> None:
    fixture = _bulk_fixture_support.BulkFixture(
        input_path=Path("fixture.csv"),
        jurisdiction="VA",
        run_suffix="abc123",
        committee_native_id="VABATCHabc123",
        source_record_keys=["va-contributions-1"],
    )

    assert fixture.input_path == Path("fixture.csv")
    assert fixture.committee_fec_id == "C84934448"


def test_seed_written_bulk_fixture_writes_then_delegates_shared_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    resources = ExitStack()
    db_conn = object()
    fixture = _bulk_fixture_support.BulkFixture(
        input_path=Path("fixture.csv"),
        jurisdiction="VA",
        run_suffix="abc123",
        committee_native_id="VABATCHabc123",
        source_record_keys=["va-contributions-1", "va-contributions-2"],
    )
    write_fixture = MagicMock(return_value=fixture)
    seed_bulk_fixture = MagicMock()
    monkeypatch.setattr(_bulk_fixture_support, "seed_bulk_fixture", seed_bulk_fixture)

    result = _bulk_fixture_support.seed_written_bulk_fixture(
        resources,
        db_conn,
        write_fixture,
        row_count=2,
    )

    assert result == fixture
    write_fixture.assert_called_once_with()
    seed_bulk_fixture.assert_called_once_with(
        resources,
        db_conn,
        fixture,
        expected_unique_source_record_keys=2,
    )


def test_suppress_first_writes_delegates_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    loader_module = ModuleType("fixture_loader")
    delegated_values: list[str] = []

    def _write(value: str) -> str:
        delegated_values.append(value)
        return value.upper()

    loader_module.write = _write

    attempts = _bulk_fixture_support.suppress_first_writes(
        monkeypatch,
        loader_module,
        "write",
        suppress_first=2,
    )

    assert loader_module.write("first") is None
    assert loader_module.write("second") is None
    assert loader_module.write("third") == "THIRD"
    assert attempts == {"attempts": 3}
    assert delegated_values == ["third"]


def test_suppress_first_writes_rejects_negative_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    loader_module = ModuleType("fixture_loader")
    loader_module.write = lambda: None

    with pytest.raises(ValueError, match="suppress_first must be non-negative"):
        _bulk_fixture_support.suppress_first_writes(
            monkeypatch,
            loader_module,
            "write",
            suppress_first=-1,
        )
