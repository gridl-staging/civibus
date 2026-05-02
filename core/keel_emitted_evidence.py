
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jsonschema.validators import validator_for


@dataclass(frozen=True, slots=True)
class EmittedEvidenceRecord:
    produced_at_utc: datetime
    evidence_path: Path
    schema_valid: bool
    payload: dict[str, object]


def _load_json_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_json_payload(*, payload_path: Path, schema_path: Path) -> tuple[bool, dict[str, object] | None]:
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, None

    if not isinstance(payload, dict):
        return False, None

    schema = _load_json_schema(schema_path)
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    if list(validator.iter_errors(payload)):
        return False, payload
    return True, payload


def _parse_produced_at_utc(raw_value: object) -> datetime:
    if isinstance(raw_value, str):
        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)


def latest_emitted_payload_by_key(
    *,
    repo_root: Path,
    layer: dict,
    key_field: str,
    scope_filter_field: str | None = None,
    scope_filter_value: str | None = None,
) -> dict[str, EmittedEvidenceRecord]:
    """Return the latest emitted evidence per configured key for one layer."""
    evidence_root = repo_root / "evidence" / layer["id"]
    if not evidence_root.is_dir():
        return {}

    schema_path = repo_root / layer["required_evidence"]["schema"]
    latest_by_key: dict[str, EmittedEvidenceRecord] = {}
    for evidence_path in sorted(evidence_root.rglob("*.json")):
        schema_valid, payload = _validate_json_payload(payload_path=evidence_path, schema_path=schema_path)
        if payload is None:
            continue
        if scope_filter_field is not None and payload.get(scope_filter_field) != scope_filter_value:
            continue

        emitted_key = str(payload.get(key_field, "unknown"))
        produced_at_utc = _parse_produced_at_utc(payload.get("produced_at_utc"))
        current = latest_by_key.get(emitted_key)
        if current is not None and produced_at_utc < current.produced_at_utc:
            continue

        latest_by_key[emitted_key] = EmittedEvidenceRecord(
            produced_at_utc=produced_at_utc,
            evidence_path=evidence_path,
            schema_valid=schema_valid,
            payload=payload,
        )

    return latest_by_key
