"""Contracts for the validated DB-backed integration-test quarantine."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

import conftest as root_conftest


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_GATE_CONTRACT_PATH = REPO_ROOT / "tests" / "ci" / "test_db_backed_suite_is_gated.py"


def _load_db_backed_target_paths() -> tuple[str, ...]:
    module_spec = importlib.util.spec_from_file_location("db_backed_suite_gate_contract", SUITE_GATE_CONTRACT_PATH)
    assert module_spec is not None and module_spec.loader is not None
    suite_gate_contract = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(suite_gate_contract)
    return suite_gate_contract.DB_BACKED_TARGET_PATHS


DB_BACKED_TARGET_PATHS = _load_db_backed_target_paths()


def _write_quarantine(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _entry(node_id: str) -> root_conftest._DbBackedQuarantineEntry:
    return root_conftest._DbBackedQuarantineEntry(
        node_id=node_id,
        reason="Seeded database exposes unresolved fixture isolation",
        owner="Federal people-spine assembly owner",
    )


@pytest.mark.parametrize(
    "entry_line",
    [
        pytest.param("not JSON", id="invalid-json"),
        pytest.param('{"node_id": "api/test_example.py::test_case"}', id="missing-fields"),
        pytest.param(
            '{"node_id": "api/test_example.py::test_case", "reason": "gap", "owner": "lane", "extra": true}',
            id="unknown-field",
        ),
    ],
)
def test_quarantine_loader_rejects_malformed_entries(tmp_path: Path, entry_line: str) -> None:
    quarantine_path = _write_quarantine(tmp_path / "quarantine.md", entry_line)

    with pytest.raises(pytest.UsageError, match=r"quarantine\.md:1"):
        root_conftest._load_db_backed_quarantine(quarantine_path)


@pytest.mark.parametrize(
    "owner_value",
    [
        pytest.param("Federal ROADMAP.md follow-up", id="canonical-casing"),
        pytest.param("federal roadmap.md follow-up", id="lowercase-casing"),
    ],
)
def test_quarantine_loader_rejects_roadmap_owner(tmp_path: Path, owner_value: str) -> None:
    entry_line = f'{{"node_id": "api/test_example.py::test_case", "reason": "seed gap", "owner": "{owner_value}"}}'
    quarantine_path = _write_quarantine(tmp_path / "quarantine.md", entry_line)

    with pytest.raises(
        pytest.UsageError,
        match=r"Invalid DB-backed quarantine entry at .*quarantine\.md:1",
    ):
        root_conftest._load_db_backed_quarantine(quarantine_path)


def test_quarantine_loader_rejects_duplicate_node_ids(tmp_path: Path) -> None:
    entry_line = '{"node_id": "api/test_example.py::test_case", "reason": "seed gap", "owner": "L2"}'
    quarantine_path = _write_quarantine(tmp_path / "quarantine.md", entry_line, entry_line)

    with pytest.raises(pytest.UsageError, match=r"duplicate node_id.*api/test_example\.py::test_case"):
        root_conftest._load_db_backed_quarantine(quarantine_path)


@pytest.mark.parametrize("field_name", ["node_id", "reason", "owner"])
def test_quarantine_loader_rejects_blank_required_fields(tmp_path: Path, field_name: str) -> None:
    fields = {
        "node_id": "api/test_example.py::test_case",
        "reason": "Seed is incomplete",
        "owner": "Federal people-spine assembly owner",
    }
    fields[field_name] = "   "
    entry_line = f'{{"node_id": "{fields["node_id"]}", "reason": "{fields["reason"]}", "owner": "{fields["owner"]}"}}'
    quarantine_path = _write_quarantine(tmp_path / "quarantine.md", entry_line)

    with pytest.raises(pytest.UsageError, match=field_name):
        root_conftest._load_db_backed_quarantine(quarantine_path)


def _assert_entries_resolve_once(
    entries: tuple[root_conftest._DbBackedQuarantineEntry, ...],
    collected_node_ids: tuple[str, ...],
) -> None:
    collected_counts = Counter(collected_node_ids)
    entry_node_ids = {entry.node_id for entry in entries}
    unknown_node_ids = [node_id for node_id in entry_node_ids if collected_counts[node_id] == 0]
    multiply_collected_node_ids = [node_id for node_id in entry_node_ids if collected_counts[node_id] > 1]

    assert not unknown_node_ids, f"Unknown DB-backed quarantine node IDs: {unknown_node_ids}"
    assert not multiply_collected_node_ids, (
        f"DB-backed quarantine node IDs resolved to multiple collected items: {multiply_collected_node_ids}"
    )
    resolved_node_ids = {node_id for node_id in collected_node_ids if node_id in entry_node_ids}
    assert resolved_node_ids == entry_node_ids


def _assert_quarantined_selection_matches_registry(
    entries: tuple[root_conftest._DbBackedQuarantineEntry, ...],
    selected_node_ids: tuple[str, ...],
) -> None:
    registered_node_ids = {entry.node_id for entry in entries}
    selected_node_id_set = set(selected_node_ids)
    missing_node_ids = sorted(registered_node_ids - selected_node_id_set)
    unexpected_node_ids = sorted(selected_node_id_set - registered_node_ids)

    assert selected_node_id_set == registered_node_ids, (
        "Quarantined DB-backed marker selection differs from registry: "
        f"missing={missing_node_ids}, unexpected={unexpected_node_ids}"
    )


def test_full_scope_validator_rejects_unknown_node_ids() -> None:
    entries = (_entry("api/test_example.py::test_missing"),)

    with pytest.raises(AssertionError, match="Unknown DB-backed quarantine node IDs"):
        _assert_entries_resolve_once(entries, ("api/test_example.py::test_other",))


def test_full_scope_validator_rejects_one_entry_resolving_multiple_items() -> None:
    duplicated_node_id = "api/test_example.py::test_duplicate"
    entries = (_entry(duplicated_node_id),)

    with pytest.raises(AssertionError, match="resolved to multiple collected items"):
        _assert_entries_resolve_once(entries, (duplicated_node_id, duplicated_node_id))


@pytest.mark.parametrize(
    ("registered_node_ids", "selected_node_ids", "error_pattern"),
    [
        pytest.param(
            ("api/test_example.py::test_registered", "api/test_example.py::test_missing"),
            ("api/test_example.py::test_registered",),
            r"missing=.*test_missing",
            id="missing-registered-entry",
        ),
        pytest.param(
            ("api/test_example.py::test_registered",),
            ("api/test_example.py::test_registered", "api/test_example.py::test_unexpected"),
            r"unexpected=.*test_unexpected",
            id="unexpected-selected-node",
        ),
    ],
)
def test_quarantined_selection_validator_rejects_exact_set_drift(
    registered_node_ids: tuple[str, ...],
    selected_node_ids: tuple[str, ...],
    error_pattern: str,
) -> None:
    entries = tuple(_entry(node_id) for node_id in registered_node_ids)

    with pytest.raises(AssertionError, match=error_pattern):
        _assert_quarantined_selection_matches_registry(entries, selected_node_ids)


class _FakeItem:
    def __init__(self, node_id: str) -> None:
        self.nodeid = node_id
        self.marker_names: list[str] = []

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.marker_names.append(marker.name)

    def get_closest_marker(self, name: str) -> None:
        # The hook consults the projected-public-contract marker during its
        # deselection pass; fake items carry no markers of their own.
        return None


class _FakeConfig:
    """Just the config surface the collection hook touches."""

    def __init__(self, invocation_args: tuple[str, ...] = ()) -> None:
        self.invocation_params = SimpleNamespace(args=tuple(invocation_args))
        self.deselected_items: list[object] = []
        self.hook = SimpleNamespace(pytest_deselected=lambda items: self.deselected_items.extend(items))


def test_collection_hook_marks_only_exact_node_id_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    exact_node_id = "api/test_example.py::test_case[param]"
    monkeypatch.setattr(root_conftest, "_load_db_backed_quarantine", lambda: (_entry(exact_node_id),))
    exact_item = _FakeItem(exact_node_id)
    prefix_item = _FakeItem("api/test_example.py::test_case")
    longer_item = _FakeItem(f"{exact_node_id}extra")

    root_conftest.pytest_collection_modifyitems(config=_FakeConfig(), items=[exact_item, prefix_item, longer_item])

    assert exact_item.marker_names == ["quarantined"]
    assert prefix_item.marker_names == []
    assert longer_item.marker_names == []


def _collect_quarantined_db_backed_node_ids() -> tuple[str, ...]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-m",
        "quarantined",
    ]
    command.extend(DB_BACKED_TARGET_PATHS)
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"DB-backed collection failed with exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    collected_node_ids = tuple(line.strip() for line in result.stdout.splitlines() if "::" in line)
    assert collected_node_ids, "Quarantined DB-backed collection was vacuous"
    return collected_node_ids


@pytest.fixture(scope="module")
def quarantined_db_backed_node_ids() -> tuple[str, ...]:
    return _collect_quarantined_db_backed_node_ids()


def test_quarantine_entries_resolve_one_to_one_in_complete_db_backed_scope(
    quarantined_db_backed_node_ids: tuple[str, ...],
) -> None:
    entries = root_conftest._load_db_backed_quarantine()

    _assert_entries_resolve_once(entries, quarantined_db_backed_node_ids)


def test_quarantine_marker_is_applied_before_builtin_marker_deselection(
    quarantined_db_backed_node_ids: tuple[str, ...],
) -> None:
    entries = root_conftest._load_db_backed_quarantine()

    assert quarantined_db_backed_node_ids, "Quarantined DB-backed collection was vacuous"
    _assert_quarantined_selection_matches_registry(entries, quarantined_db_backed_node_ids)
    assert root_conftest.pytest_collection_modifyitems.pytest_impl["tryfirst"] is True
