from pathlib import Path
import importlib

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "evidence"
LAYERS_PATH = REPO_ROOT / "layers.yaml"
EXPECTED_LAYER_IDS = ["L1", "L5", "L6", "L10", "L3", "L7", "L12"]
EXPECTED_LAYER_STATUS_BY_ID = {
    "L1": "piloted",
    "L5": "piloted",
    "L6": "piloted",
    "L10": "piloted",
    "L3": "piloted",
    "L7": "piloted",
    "L12": "introduced",
}
JSONSCHEMA_VALIDATORS = importlib.import_module("jsonschema.validators")
COMMON_METADATA_FIELDS = {
    "layer",
    "scope",
    "schema_version",
    "produced_at_utc",
    "repo_sha",
    "gate_command",
    "status",
}
WAIVER_SCHEMA_PATH = REPO_ROOT / "evidence_schemas" / "waiver.json"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_schema(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_phase1_evidence_dir_exists() -> None:
    assert EVIDENCE_DIR.is_dir(), "Phase 1 Keel pilot needs a committed root evidence/ directory"


def test_layers_yaml_declares_landed_layers_in_order_with_honest_statuses() -> None:
    payload = _load_yaml(LAYERS_PATH)
    layers = payload["layers"]

    layer_ids = [layer["id"] for layer in layers]
    assert layer_ids == EXPECTED_LAYER_IDS
    assert {layer["id"]: layer["status"] for layer in layers} == EXPECTED_LAYER_STATUS_BY_ID


def test_phase1_layer_schemas_exist_and_validate_as_json_schema() -> None:
    payload = _load_yaml(LAYERS_PATH)

    for layer in payload["layers"]:
        schema_path = REPO_ROOT / layer["required_evidence"]["schema"]
        assert schema_path.is_file(), f"{layer['id']} schema is missing at {schema_path}"

        schema = _load_schema(schema_path)
        validator_cls = JSONSCHEMA_VALIDATORS.validator_for(schema)
        validator_cls.check_schema(schema)

        required = set(schema.get("required", []))
        assert COMMON_METADATA_FIELDS.issubset(required), (
            f"{layer['id']} schema must require the common Keel metadata fields"
        )
        assert schema["properties"]["status"]["enum"] == ["pass", "fail", "error", "waived", "stale"]


def test_phase1_waiver_schema_exists_and_covers_required_fields() -> None:
    assert WAIVER_SCHEMA_PATH.is_file(), "Phase 1 needs a committed waiver schema"

    schema = _load_schema(WAIVER_SCHEMA_PATH)
    validator_cls = JSONSCHEMA_VALIDATORS.validator_for(schema)
    validator_cls.check_schema(schema)

    assert set(schema["required"]) == {
        "layer",
        "scope",
        "reason",
        "created_at_utc",
        "expires_at_utc",
        "owner",
        "evidence_path",
        "followup_ticket",
    }
