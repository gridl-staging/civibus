from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path


def _load_stage_close_gate_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "stage_close_gate.py"
    spec = importlib.util.spec_from_file_location("stage_close_gate", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


stage_close_gate = _load_stage_close_gate_module()


def _write_layers_yaml(
    repo_root: Path,
    *,
    l1_status: str = "piloted",
    l10_status: str = "piloted",
    include_l3: bool = False,
    include_l7: bool = False,
    include_l12: bool = False,
) -> None:
    l3_block = (
        """
  - id: L3
    name: source_status_machine
    status: piloted
    scope: per_source
    scope_strategy:
      type: emitted_by_gate
      field: source_id
      missing_label: source_id values
      expected_scopes:
        - nc_transactions
        - nc_committee_documents
        - nc_ie_document_index
        - nc_durham_city_council_roster
        - nc_general_assembly_house_roster
      scope_filter_field: scope
      scope_filter_value: NC
    triggered_by:
      - source_registry
    required_evidence:
      schema: evidence_schemas/L3.json
    file_path_triggers:
      - layers.yaml
      - sources.yaml
      - core/keel_gate_l3.py
    gate_command: make gate-L3 JURISDICTION=NC
"""
        if include_l3
        else ""
    )
    l7_block = (
        """
  - id: L7
    name: cross_source_reconciliation
    status: piloted
    scope: global
    scope_strategy:
      type: fixed_scope
      value: global
    triggered_by:
      - entity_reconciliation
    required_evidence:
      schema: evidence_schemas/L7.json
    file_path_triggers:
      - layers.yaml
      - core/keel_gate_l7.py
    gate_command: make gate-L7
"""
        if include_l7
        else ""
    )
    l12_block = (
        """
  - id: L12
    name: session_output_summary
    status: introduced
    scope: per_session
    scope_strategy:
      type: session_summary
      field: session_id
    triggered_by:
      - session_close
    required_evidence:
      schema: evidence_schemas/L12.json
    file_path_triggers:
      - layers.yaml
      - core/keel_session_output.py
      - scripts/stage_close_gate.py
      - scripts/matt_stage_close.sh
      - evidence_schemas/L12.json
    gate_command: uv run python -m core.keel_session_output
"""
        if include_l12
        else ""
    )

    (repo_root / "layers.yaml").write_text(
        f"""schema_version: 1
layers:
  - id: L1
    name: jurisdiction_anchors
    status: {l1_status}
    scope: per_jurisdiction
    scope_strategy:
      type: fixed_scope
      value: NC
    triggered_by:
      - anchor_research
    required_evidence:
      schema: evidence_schemas/L1.json
    file_path_triggers:
      - layers.yaml
      - core/keel_gate_l1.py
      - docs/anchors/**
      - domains/campaign_finance/jurisdictions/states/NC/scraper/**
    gate_command: make gate-L1 JURISDICTION={{scope}}
  - id: L5
    name: runner_level_determinism
    status: piloted
    scope: global
    scope_strategy:
      type: fixed_scope
      value: global
    triggered_by:
      - refresh_runner
    required_evidence:
      schema: evidence_schemas/L5.json
    file_path_triggers:
      - layers.yaml
      - core/refresh/**
      - domains/campaign_finance/jurisdictions/states/NC/scraper/**
      - infra/scripts/install_refresh_cron.sh
    gate_command: make gate-L5
  - id: L6
    name: temporal_integrity
    status: piloted
    scope: per_load
    scope_strategy:
      type: emitted_by_gate
      field: scope
      expected_scopes:
        - NC_transactions
        - NC_committee_documents
        - NC_ie_document_index
    triggered_by:
      - loader_change
    required_evidence:
      schema: evidence_schemas/L6.json
    file_path_triggers:
      - layers.yaml
      - core/keel_gate_l6.py
      - domains/campaign_finance/jurisdictions/states/NC/scraper/**
    gate_command: make gate-L6
  - id: L10
    name: ui_completeness_honesty
    status: {l10_status}
    scope: per_jurisdiction
    scope_strategy:
      type: fixed_scope
      value: NC
    triggered_by:
      - detail_ui
    required_evidence:
      schema: evidence_schemas/L10.json
    file_path_triggers:
      - layers.yaml
      - web/src/lib/campaign-finance-detail/**
    gate_command: make gate-L10
{l3_block}
{l7_block}
{l12_block}
""",
        encoding="utf-8",
    )


def _write_schema_files(repo_root: Path) -> None:
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    (schema_root / "L1.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "layer",
                    "scope",
                    "schema_version",
                    "produced_at_utc",
                    "repo_sha",
                    "gate_command",
                    "status",
                ],
                "properties": {
                    "layer": {"const": "L1"},
                    "scope": {"type": "string"},
                    "schema_version": {"const": 1},
                    "produced_at_utc": {"type": "string", "format": "date-time"},
                    "repo_sha": {"type": "string"},
                    "gate_command": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (schema_root / "L5.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "layer",
                    "scope",
                    "schema_version",
                    "produced_at_utc",
                    "repo_sha",
                    "gate_command",
                    "status",
                ],
                "properties": {
                    "layer": {"const": "L5"},
                    "scope": {"type": "string"},
                    "schema_version": {"const": 1},
                    "produced_at_utc": {"type": "string", "format": "date-time"},
                    "repo_sha": {"type": "string"},
                    "gate_command": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (schema_root / "L6.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "layer",
                    "scope",
                    "schema_version",
                    "produced_at_utc",
                    "repo_sha",
                    "gate_command",
                    "status",
                ],
                "properties": {
                    "layer": {"const": "L6"},
                    "scope": {"type": "string"},
                    "schema_version": {"const": 1},
                    "produced_at_utc": {"type": "string", "format": "date-time"},
                    "repo_sha": {"type": "string"},
                    "gate_command": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (schema_root / "L10.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "layer",
                    "scope",
                    "schema_version",
                    "produced_at_utc",
                    "repo_sha",
                    "gate_command",
                    "status",
                ],
                "properties": {
                    "layer": {"const": "L10"},
                    "scope": {"type": "string"},
                    "schema_version": {"const": 1},
                    "produced_at_utc": {"type": "string", "format": "date-time"},
                    "repo_sha": {"type": "string"},
                    "gate_command": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (schema_root / "L3.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "layer",
                    "scope",
                    "schema_version",
                    "produced_at_utc",
                    "repo_sha",
                    "gate_command",
                    "status",
                    "source_id",
                    "current_state",
                    "transition_date",
                    "linked_evidence",
                    "validation_checks",
                ],
                "properties": {
                    "layer": {"const": "L3"},
                    "scope": {"type": "string"},
                    "schema_version": {"const": 1},
                    "produced_at_utc": {"type": "string", "format": "date-time"},
                    "repo_sha": {"type": "string"},
                    "gate_command": {"type": "string"},
                    "status": {"type": "string"},
                    "source_id": {"type": "string"},
                    "current_state": {"type": "string"},
                    "transition_date": {"type": "string", "format": "date"},
                    "linked_evidence": {"type": "array"},
                    "validation_checks": {"type": "array"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (schema_root / "L7.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "layer",
                    "scope",
                    "schema_version",
                    "produced_at_utc",
                    "repo_sha",
                    "gate_command",
                    "status",
                ],
                "properties": {
                    "layer": {"const": "L7"},
                    "scope": {"type": "string"},
                    "schema_version": {"const": 1},
                    "produced_at_utc": {"type": "string", "format": "date-time"},
                    "repo_sha": {"type": "string"},
                    "gate_command": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (schema_root / "L12.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "layer",
                    "scope",
                    "schema_version",
                    "produced_at_utc",
                    "repo_sha",
                    "gate_command",
                    "status",
                    "session_id",
                    "changed_files",
                    "touched_layers",
                    "produced_evidence_layers",
                    "row_count_deltas",
                    "anchor_ratio_deltas",
                ],
                "properties": {
                    "layer": {"const": "L12"},
                    "scope": {"type": "string"},
                    "schema_version": {"const": 1},
                    "produced_at_utc": {"type": "string", "format": "date-time"},
                    "repo_sha": {"type": "string"},
                    "gate_command": {"type": "string"},
                    "status": {"type": "string"},
                    "session_id": {"type": "string"},
                    "changed_files": {"type": "array", "items": {"type": "string"}},
                    "touched_layers": {"type": "array", "items": {"type": "string"}},
                    "produced_evidence_layers": {"type": "array", "items": {"type": "string"}},
                    "row_count_deltas": {"type": "array"},
                    "anchor_ratio_deltas": {"type": "array"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (schema_root / "waiver.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "layer",
                    "scope",
                    "reason",
                    "created_at_utc",
                    "expires_at_utc",
                    "owner",
                    "evidence_path",
                    "followup_ticket",
                ],
                "properties": {
                    "layer": {"type": "string"},
                    "scope": {"type": "string"},
                    "reason": {"type": "string"},
                    "created_at_utc": {"type": "string", "format": "date-time"},
                    "expires_at_utc": {"type": "string", "format": "date-time"},
                    "owner": {"type": "string"},
                    "evidence_path": {"type": "string"},
                    "followup_ticket": {"type": "string"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_fixed_scope_evidence(
    repo_root: Path,
    *,
    layer: str,
    scope: str,
    evidence_date: date,
    produced_at: datetime,
    status: str = "pass",
    include_required_fields: bool = True,
) -> Path:
    evidence_path = repo_root / "evidence" / layer / scope / f"{evidence_date.isoformat()}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "layer": layer,
        "scope": scope,
        "schema_version": 1,
        "produced_at_utc": produced_at.isoformat(),
        "repo_sha": "abc1234",
        "gate_command": f"make gate-{layer}",
        "status": status,
    }
    if not include_required_fields:
        payload.pop("produced_at_utc")
    evidence_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return evidence_path


def _write_l6_evidence(
    repo_root: Path,
    *,
    scope: str,
    file_name: str,
    produced_at: datetime,
    status: str = "pass",
) -> Path:
    evidence_path = repo_root / "evidence" / "L6" / file_name
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "layer": "L6",
        "scope": scope,
        "schema_version": 1,
        "produced_at_utc": produced_at.isoformat(),
        "repo_sha": "abc1234",
        "gate_command": "make gate-L6 JURISDICTION=NC",
        "status": status,
    }
    evidence_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return evidence_path


def _write_l3_evidence(
    repo_root: Path,
    *,
    jurisdiction: str,
    source_id: str,
    produced_at: datetime,
    status: str = "pass",
) -> Path:
    evidence_path = repo_root / "evidence" / "L3" / jurisdiction / source_id / "validated_2026-04-24.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "layer": "L3",
        "scope": jurisdiction,
        "schema_version": 1,
        "produced_at_utc": produced_at.isoformat(),
        "repo_sha": "abc1234",
        "gate_command": f"make gate-L3 JURISDICTION={jurisdiction}",
        "status": status,
        "source_id": source_id,
        "current_state": "validated",
        "transition_date": "2026-04-24",
        "linked_evidence": [],
        "validation_checks": [],
    }
    evidence_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return evidence_path


def _write_repo_contract(
    repo_root: Path,
    *,
    include_l3: bool = False,
    include_l7: bool = False,
    include_l12: bool = False,
) -> None:
    _write_layers_yaml(repo_root, include_l3=include_l3, include_l7=include_l7, include_l12=include_l12)
    _write_schema_files(repo_root)


def _write_waiver(
    repo_root: Path,
    *,
    layer: str,
    scope: str,
    waiver_date: date,
    evidence_path: str,
    expires_at: datetime,
    created_at: datetime | None = None,
) -> Path:
    waiver_path = repo_root / "waivers" / f"{layer}_{scope}_{waiver_date.isoformat()}.yaml"
    waiver_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "layer": layer,
        "scope": scope,
        "reason": "Temporary calibration window for failing evidence.",
        "created_at_utc": (created_at or datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc)).isoformat(),
        "expires_at_utc": expires_at.isoformat(),
        "owner": "keel-test",
        "evidence_path": evidence_path,
        "followup_ticket": "KEEL-123",
    }
    waiver_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return waiver_path


def _write_l12_summary(
    repo_root: Path,
    *,
    session_id: str,
    produced_at: datetime,
    changed_files: list[str],
    touched_layers: list[str],
    produced_evidence_layers: list[str],
    status: str = "pass",
) -> Path:
    summary_path = repo_root / "evidence" / "L12" / session_id / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "layer": "L12",
        "scope": session_id,
        "schema_version": 1,
        "produced_at_utc": produced_at.isoformat(),
        "repo_sha": "abc1234",
        "gate_command": "uv run python scripts/stage_close_gate.py",
        "status": status,
        "session_id": session_id,
        "changed_files": changed_files,
        "touched_layers": touched_layers,
        "produced_evidence_layers": produced_evidence_layers,
        "row_count_deltas": [],
        "anchor_ratio_deltas": [],
    }
    summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return summary_path


def test_stage_close_gate_passes_when_touched_layers_have_fresh_valid_evidence(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    today = date(2026, 4, 24)
    produced_at = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    _write_fixed_scope_evidence(repo_root, layer="L10", scope="NC", evidence_date=today, produced_at=produced_at)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["web/src/lib/campaign-finance-detail/presentation.ts"],
        today_utc=today,
    )

    assert result.exit_code == 0
    assert result.touched_layers == ["L10"]
    assert result.failures == []


def test_stage_close_gate_ignores_touched_layers_that_are_only_introduced(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_layers_yaml(repo_root, l10_status="introduced")
    _write_schema_files(repo_root)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["web/src/lib/campaign-finance-detail/presentation.ts"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 0
    assert result.touched_layers == ["L10"]
    assert result.failures == []


def test_stage_close_gate_blocks_when_touched_layer_evidence_is_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["web/src/lib/campaign-finance-detail/presentation.ts"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.failures == ["L10: missing fresh evidence for fixed scope 'NC'"]


def test_stage_close_gate_treats_l1_gate_code_as_l1_trigger(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["core/keel_gate_l1.py"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.touched_layers == ["L1"]
    assert result.failures == ["L1: missing fresh evidence for fixed scope 'NC'"]


def test_stage_close_gate_requires_fresh_l7_evidence_when_l7_owner_changes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root, include_l7=True)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["core/keel_gate_l7.py"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.touched_layers == ["L7"]
    assert result.failures == ["L7: missing fresh evidence for fixed scope 'global'"]


def test_stage_close_gate_treats_layers_yaml_as_control_plane_for_all_phase1_layers(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["layers.yaml"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.touched_layers == ["L1", "L5", "L6", "L10"]
    assert result.failures == [
        "L1: missing fresh evidence for fixed scope 'NC'",
        "L5: missing fresh evidence for fixed scope 'global'",
        "L6: missing fresh emitted evidence for scopes NC_transactions, NC_committee_documents, NC_ie_document_index",
        "L10: missing fresh evidence for fixed scope 'NC'",
    ]


def test_stage_close_gate_does_not_trigger_l6_for_non_nc_loader_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["domains/campaign_finance/jurisdictions/states/TX/load.py"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 0
    assert result.touched_layers == []
    assert result.failures == []


def test_stage_close_gate_blocks_when_expected_l6_scope_is_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    produced_at = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    _write_l6_evidence(
        repo_root,
        scope="NC_transactions",
        file_name="nc-transactions-20260424T120000Z.json",
        produced_at=produced_at,
    )
    _write_l6_evidence(
        repo_root,
        scope="NC_committee_documents",
        file_name="nc-committee-documents-20260424T120000Z.json",
        produced_at=produced_at,
    )

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["domains/campaign_finance/jurisdictions/states/NC/scraper/parse.py"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.touched_layers == ["L1", "L5", "L6"]
    assert result.failures == [
        "L1: missing fresh evidence for fixed scope 'NC'",
        "L5: missing fresh evidence for fixed scope 'global'",
        "L6: missing fresh emitted evidence for scopes NC_ie_document_index",
    ]


def test_stage_close_gate_requires_l1_l5_and_l6_for_nc_loader_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["domains/campaign_finance/jurisdictions/states/NC/scraper/load.py"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.touched_layers == ["L1", "L5", "L6"]
    assert result.failures == [
        "L1: missing fresh evidence for fixed scope 'NC'",
        "L5: missing fresh evidence for fixed scope 'global'",
        "L6: missing fresh emitted evidence for scopes NC_transactions, NC_committee_documents, NC_ie_document_index",
    ]


def test_stage_close_gate_blocks_when_touched_layer_evidence_is_stale(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    _write_fixed_scope_evidence(
        repo_root,
        layer="L10",
        scope="NC",
        evidence_date=date(2026, 4, 23),
        produced_at=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
    )

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["web/src/lib/campaign-finance-detail/presentation.ts"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.failures == ["L10: stale evidence for fixed scope 'NC' (latest is 2026-04-23)"]


def test_stage_close_gate_blocks_when_touched_layer_evidence_is_schema_invalid(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    _write_fixed_scope_evidence(
        repo_root,
        layer="L10",
        scope="NC",
        evidence_date=date(2026, 4, 24),
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        include_required_fields=False,
    )

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["web/src/lib/campaign-finance-detail/presentation.ts"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.failures == ["L10: schema-invalid evidence at evidence/L10/NC/2026-04-24.json"]


def test_stage_close_gate_accepts_unexpired_waiver_for_non_passing_evidence(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    evidence_path = _write_fixed_scope_evidence(
        repo_root,
        layer="L10",
        scope="NC",
        evidence_date=date(2026, 4, 24),
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        status="fail",
    )
    _write_waiver(
        repo_root,
        layer="L10",
        scope="NC",
        waiver_date=date(2026, 4, 24),
        evidence_path=str(evidence_path.relative_to(repo_root)),
        expires_at=datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(stage_close_gate, "_now_utc", lambda: datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc))

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["web/src/lib/campaign-finance-detail/presentation.ts"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 0
    assert result.touched_layers == ["L10"]
    assert result.failures == []


def test_stage_close_gate_blocks_when_waiver_is_expired(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    evidence_path = _write_fixed_scope_evidence(
        repo_root,
        layer="L10",
        scope="NC",
        evidence_date=date(2026, 4, 24),
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        status="fail",
    )
    _write_waiver(
        repo_root,
        layer="L10",
        scope="NC",
        waiver_date=date(2026, 4, 24),
        evidence_path=str(evidence_path.relative_to(repo_root)),
        expires_at=datetime(2026, 4, 23, 23, 59, tzinfo=timezone.utc),
    )

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["web/src/lib/campaign-finance-detail/presentation.ts"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.failures == ["L10: expired waiver at waivers/L10_NC_2026-04-24.yaml"]


def test_stage_close_gate_blocks_when_waiver_expired_earlier_today(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    evidence_path = _write_fixed_scope_evidence(
        repo_root,
        layer="L10",
        scope="NC",
        evidence_date=date(2026, 4, 24),
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        status="fail",
    )
    _write_waiver(
        repo_root,
        layer="L10",
        scope="NC",
        waiver_date=date(2026, 4, 24),
        evidence_path=str(evidence_path.relative_to(repo_root)),
        expires_at=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(stage_close_gate, "_now_utc", lambda: datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc))

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["web/src/lib/campaign-finance-detail/presentation.ts"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.failures == ["L10: expired waiver at waivers/L10_NC_2026-04-24.yaml"]


def test_stage_close_gate_rejects_keel_disable_in_committing_context(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    _write_fixed_scope_evidence(
        repo_root,
        layer="L10",
        scope="NC",
        evidence_date=date(2026, 4, 24),
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setenv("KEEL_DISABLE", "L10")

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["web/src/lib/campaign-finance-detail/presentation.ts"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.failures == ["KEEL_DISABLE is not allowed during stage-close; use a committed waiver instead"]


def test_stage_close_gate_blocks_when_changed_judge_prompt_is_missing_required_contract(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    prompt_path = repo_root / "prompts" / "judge" / "portal_investigation_review.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("## Goal\n\nMissing frontmatter.\n", encoding="utf-8")

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["prompts/judge/portal_investigation_review.md"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.failures == ["judge prompt prompts/judge/portal_investigation_review.md: missing YAML frontmatter"]


def test_stage_close_gate_requires_fresh_l3_evidence_for_sources_registry_changes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root, include_l3=True)
    produced_at = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    _write_l3_evidence(
        repo_root,
        jurisdiction="NC",
        source_id="nc_transactions",
        produced_at=produced_at,
    )
    _write_l3_evidence(
        repo_root,
        jurisdiction="NC",
        source_id="nc_committee_documents",
        produced_at=produced_at,
    )
    _write_l3_evidence(
        repo_root,
        jurisdiction="SC",
        source_id="nc_ie_document_index",
        produced_at=produced_at,
    )

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["sources.yaml"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.touched_layers == ["L3"]
    assert result.failures == [
        "L3: missing fresh emitted evidence for source_id values "
        "nc_ie_document_index, nc_durham_city_council_roster, nc_general_assembly_house_roster"
    ]


def test_latest_emitted_payload_by_key_honors_l3_source_id_scope_filter(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root, include_l3=True)
    produced_at = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    _write_l3_evidence(
        repo_root,
        jurisdiction="NC",
        source_id="nc_transactions",
        produced_at=produced_at,
    )
    _write_l3_evidence(
        repo_root,
        jurisdiction="NC",
        source_id="nc_committee_documents",
        produced_at=produced_at,
    )
    _write_l3_evidence(
        repo_root,
        jurisdiction="SC",
        source_id="nc_ie_document_index",
        produced_at=produced_at,
    )

    l3_layer = next(layer for layer in stage_close_gate._load_yaml(repo_root / "layers.yaml")["layers"] if layer["id"] == "L3")
    latest_payload_by_source_id = stage_close_gate._latest_emitted_payload_by_key(
        repo_root=repo_root,
        layer=l3_layer,
        key_field="source_id",
        scope_filter_field="scope",
        scope_filter_value="NC",
    )

    assert sorted(latest_payload_by_source_id) == ["nc_committee_documents", "nc_transactions"]
    for source_id, (evidence_path, schema_valid, payload) in latest_payload_by_source_id.items():
        assert evidence_path.relative_to(repo_root).as_posix() == f"evidence/L3/NC/{source_id}/validated_2026-04-24.json"
        assert schema_valid is True
        assert payload is not None
        assert payload["scope"] == "NC"
        assert payload["source_id"] == source_id


def test_latest_emitted_payload_by_key_skips_nonobject_json_payloads(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root, include_l3=True)
    payload_dir = repo_root / "evidence" / "L3" / "NC" / "nc_transactions"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "validated_2026-04-24.json").write_text(json.dumps(["not", "an", "object"]) + "\n", encoding="utf-8")

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["sources.yaml"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 1
    assert result.touched_layers == ["L3"]
    assert result.failures == [
        "L3: missing fresh emitted evidence for source_id values "
        "nc_transactions, nc_committee_documents, nc_ie_document_index, "
        "nc_durham_city_council_roster, nc_general_assembly_house_roster"
    ]


def test_stage_close_gate_passes_when_sources_registry_has_fresh_l3_evidence_for_all_sources(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root, include_l3=True)
    produced_at = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
    for source_id in (
        "nc_transactions",
        "nc_committee_documents",
        "nc_ie_document_index",
        "nc_durham_city_council_roster",
        "nc_general_assembly_house_roster",
    ):
        _write_l3_evidence(
            repo_root,
            jurisdiction="NC",
            source_id=source_id,
            produced_at=produced_at,
        )

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["sources.yaml"],
        today_utc=date(2026, 4, 24),
    )

    assert result.exit_code == 0
    assert result.touched_layers == ["L3"]
    assert result.failures == []


def test_stage_close_gate_touches_l12_for_summary_owner_changes_without_check_layer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root, include_l12=True)
    _write_l12_summary(
        repo_root,
        session_id="session-123",
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        changed_files=["core/keel_session_output.py"],
        touched_layers=["L12"],
        produced_evidence_layers=["L12"],
    )

    original_check_layer = stage_close_gate.check_layer

    def _check_layer_without_l12(*, repo_root: Path, layer: dict, today_utc: date) -> stage_close_gate.LayerCheck:
        assert layer["id"] != "L12"
        return original_check_layer(repo_root=repo_root, layer=layer, today_utc=today_utc)

    monkeypatch.setattr(stage_close_gate, "check_layer", _check_layer_without_l12)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["core/keel_session_output.py"],
        today_utc=date(2026, 4, 24),
        session_id="session-123",
    )

    assert result.exit_code == 0
    assert result.touched_layers == ["L12"]
    assert result.failures == []


def test_stage_close_gate_requires_fresh_l12_summary_when_session_id_provided(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["docs/keel/checklist.md"],
        today_utc=date(2026, 4, 24),
        session_id="session-123",
    )

    assert result.exit_code == 1
    assert result.touched_layers == []
    assert result.failures == ["L12: missing session summary at evidence/L12/session-123/summary.json"]


def test_stage_close_gate_rejects_l12_summary_with_mismatched_touched_layers(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    _write_l12_summary(
        repo_root,
        session_id="session-123",
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        changed_files=["docs/keel/checklist.md"],
        touched_layers=["L10"],
        produced_evidence_layers=["L12"],
    )

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["docs/keel/checklist.md"],
        today_utc=date(2026, 4, 24),
        session_id="session-123",
    )

    assert result.exit_code == 1
    assert result.failures == ["L12: touched_layers mismatch in evidence/L12/session-123/summary.json"]


def test_stage_close_gate_accepts_valid_l12_summary_for_non_layer_changes(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    _write_l12_summary(
        repo_root,
        session_id="session-123",
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        changed_files=["docs/keel/checklist.md"],
        touched_layers=[],
        produced_evidence_layers=["L12"],
    )

    result = stage_close_gate.evaluate_stage_close(
        repo_root=repo_root,
        changed_files=["docs/keel/checklist.md"],
        today_utc=date(2026, 4, 24),
        session_id="session-123",
    )

    assert result.exit_code == 0
    assert result.touched_layers == []
    assert result.failures == []
