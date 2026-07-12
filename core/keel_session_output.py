
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema.validators import validator_for


def build_session_summary(
    *,
    session_id: str,
    produced_at: datetime,
    repo_sha: str,
    gate_command: str,
    changed_files: list[str],
    touched_layers: list[str],
    produced_evidence_layers: list[str],
    row_count_deltas: list[dict[str, object]] | None = None,
    anchor_ratio_deltas: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "layer": "L12",
        "scope": session_id,
        "schema_version": 1,
        "produced_at_utc": produced_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "repo_sha": repo_sha,
        "gate_command": gate_command,
        "status": "pass",
        "session_id": session_id,
        "changed_files": changed_files,
        "touched_layers": touched_layers,
        "produced_evidence_layers": produced_evidence_layers,
        "row_count_deltas": row_count_deltas or [],
        "anchor_ratio_deltas": anchor_ratio_deltas or [],
    }


def validate_session_summary(*, repo_root: Path, payload: dict[str, object]) -> None:
    schema = json.loads((repo_root / "evidence_schemas" / "L12.json").read_text(encoding="utf-8"))
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = list(validator.iter_errors(payload))
    if errors:
        raise ValueError(errors[0].message)


def write_session_summary(*, repo_root: Path, payload: dict[str, object]) -> Path:
    validate_session_summary(repo_root=repo_root, payload=payload)
    output_path = repo_root / "evidence" / "L12" / str(payload["session_id"]) / "summary.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write a Keel L12 session summary")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--repo-sha", required=True)
    parser.add_argument("--gate-command", required=True)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--touched-layer", action="append", default=[])
    parser.add_argument("--produced-evidence-layer", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    payload = build_session_summary(
        session_id=args.session_id,
        produced_at=datetime.now(UTC),
        repo_sha=args.repo_sha,
        gate_command=args.gate_command,
        changed_files=args.changed_file,
        touched_layers=args.touched_layer,
        produced_evidence_layers=args.produced_evidence_layer,
    )
    output_path = write_session_summary(repo_root=args.repo_root.resolve(), payload=payload)
    print(output_path.relative_to(args.repo_root.resolve()).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
