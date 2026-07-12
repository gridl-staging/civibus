from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema.validators import validator_for

import core.keel_session_output as keel_session_output


def test_build_session_summary_uses_l12_contract() -> None:
    summary = keel_session_output.build_session_summary(
        session_id="session-123",
        produced_at=datetime(2026, 4, 24, 22, 0, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python scripts/stage_close_gate.py --session-id session-123",
        changed_files=["docs/reference/keel/checklist.md"],
        touched_layers=[],
        produced_evidence_layers=["L12"],
    )

    assert summary["layer"] == "L12"
    assert summary["scope"] == "session-123"
    assert summary["status"] == "pass"
    assert summary["changed_files"] == ["docs/reference/keel/checklist.md"]
    assert summary["produced_evidence_layers"] == ["L12"]


def test_write_session_summary_emits_schema_valid_payload(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    schema_path = Path(__file__).resolve().parents[2] / "evidence_schemas" / "L12.json"
    schema_root.joinpath("L12.json").write_text(schema_path.read_text(encoding="utf-8"), encoding="utf-8")

    payload = keel_session_output.build_session_summary(
        session_id="session-123",
        produced_at=datetime(2026, 4, 24, 22, 0, tzinfo=UTC),
        repo_sha="abc1234",
        gate_command="uv run python scripts/stage_close_gate.py --session-id session-123",
        changed_files=["docs/reference/keel/checklist.md"],
        touched_layers=[],
        produced_evidence_layers=["L12"],
    )
    output_path = keel_session_output.write_session_summary(repo_root=repo_root, payload=payload)

    schema = json.loads((repo_root / "evidence_schemas" / "L12.json").read_text(encoding="utf-8"))
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    saved_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert output_path == repo_root / "evidence" / "L12" / "session-123" / "summary.json"
    assert list(validator.iter_errors(saved_payload)) == []
