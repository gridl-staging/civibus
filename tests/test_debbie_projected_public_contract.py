from __future__ import annotations

from pathlib import Path

import pytest

from tests.ci.public_mirror_contract import expected_dev_repo_only_failure_nodes
from tests.test_debbie_post_sync_hook import (
    _collected_node_ids,
    _collection_diagnostics,
    _failed_node_ids,
    _pytest_collect_command_from_make_target,
    _run_projected_pytest,
    project_debbie_public_mirror,
)


@pytest.mark.projected_public_contract
@pytest.mark.timeout(900)
def test_projected_current_public_unit_selection_failures_are_classified(tmp_path: Path) -> None:
    projected_mirror = project_debbie_public_mirror(tmp_path)
    collect_command = _pytest_collect_command_from_make_target(projected_mirror.root, "test")
    assert collect_command[:7] == ["uv", "run", "--extra", "dev", "--extra", "entity-resolution", "pytest"]
    collected = _run_projected_pytest(projected_mirror, collect_command)
    collected_node_ids = _collected_node_ids(collected.stdout)

    assert collected.returncode == 0, _collection_diagnostics(collected)
    assert collected_node_ids, _collection_diagnostics(collected)

    run_command = [part for part in collect_command if part != "--collect-only"]
    run_command.append("--tb=no")
    completed = _run_projected_pytest(projected_mirror, run_command)
    reproduced_failure_nodes = _failed_node_ids(completed.stdout)
    expected_failure_nodes = expected_dev_repo_only_failure_nodes(collected_node_ids)

    assert completed.returncode != 0, _collection_diagnostics(completed)
    assert reproduced_failure_nodes == expected_failure_nodes, (
        f"missing={sorted(expected_failure_nodes - reproduced_failure_nodes)}\n"
        f"extra={sorted(reproduced_failure_nodes - expected_failure_nodes)}\n"
        f"{_collection_diagnostics(completed)}"
    )
