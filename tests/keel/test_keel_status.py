from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import core.keel_status as keel_status


def _write_layers_yaml(repo_root: Path, *, include_l3: bool = False, include_l7: bool = False) -> None:
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

    (repo_root / "layers.yaml").write_text(
        f"""schema_version: 1
layers:
  - id: L1
    name: jurisdiction_anchors
    status: piloted
    scope: per_jurisdiction
    scope_strategy:
      type: fixed_scope
      value: NC
    triggered_by:
      - anchor_research
    required_evidence:
      schema: evidence_schemas/L1.json
    file_path_triggers:
      - docs/anchors/**
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
      - core/refresh/**
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
      - domains/campaign_finance/**/load.py
    gate_command: make gate-L6
  - id: L10
    name: ui_completeness_honesty
    status: piloted
    scope: per_jurisdiction
    scope_strategy:
      type: fixed_scope
      value: NC
    triggered_by:
      - detail_ui
    required_evidence:
      schema: evidence_schemas/L10.json
    file_path_triggers:
      - web/src/lib/campaign-finance-detail/**
    gate_command: make gate-L10
{l3_block}
{l7_block}
""",
        encoding="utf-8",
    )


def _write_schema(path: Path, *, layer: str, extra_required: list[str], extra_properties: dict[str, object]) -> None:
    payload = {
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
            *extra_required,
        ],
        "properties": {
            "layer": {"const": layer},
            "scope": {"type": "string"},
            "schema_version": {"const": 1},
            "produced_at_utc": {"type": "string", "format": "date-time"},
            "repo_sha": {"type": "string"},
            "gate_command": {"type": "string"},
            "status": {"type": "string", "enum": ["pass", "fail", "error", "waived", "stale"]},
            **extra_properties,
        },
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_schema_files(repo_root: Path, *, include_l3: bool = False, include_l7: bool = False) -> None:
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True)
    _write_schema(
        schema_root / "L1.json",
        layer="L1",
        extra_required=["current_total", "expected_range", "ratio", "anchor_path", "anchor_schema_version"],
        extra_properties={
            "current_total": {"type": "number"},
            "expected_range": {"type": "object"},
            "ratio": {"type": "number"},
            "anchor_path": {"type": "string"},
            "anchor_schema_version": {"type": "integer"},
        },
    )
    _write_schema(
        schema_root / "L5.json",
        layer="L5",
        extra_required=["total_runs", "status_counts"],
        extra_properties={
            "total_runs": {"type": "integer"},
            "status_counts": {"type": "object"},
        },
    )
    _write_schema(
        schema_root / "L6.json",
        layer="L6",
        extra_required=["load_id", "total_rows", "out_of_range_rows", "example_rows"],
        extra_properties={
            "load_id": {"type": "string"},
            "total_rows": {"type": "integer"},
            "out_of_range_rows": {"type": "integer"},
            "example_rows": {"type": "array"},
        },
    )
    _write_schema(
        schema_root / "L10.json",
        layer="L10",
        extra_required=["evaluated_routes", "empty_banner_cases", "deviation_banner_cases", "failing_routes"],
        extra_properties={
            "evaluated_routes": {"type": "integer"},
            "empty_banner_cases": {"type": "integer"},
            "deviation_banner_cases": {"type": "integer"},
            "failing_routes": {"type": "array"},
        },
    )
    if include_l3:
        _write_schema(
            schema_root / "L3.json",
            layer="L3",
            extra_required=["source_id", "current_state", "transition_date", "linked_evidence", "validation_checks"],
            extra_properties={
                "source_id": {"type": "string"},
                "current_state": {"type": "string"},
                "transition_date": {"type": "string", "format": "date"},
                "linked_evidence": {"type": "array"},
                "validation_checks": {"type": "array"},
            },
        )
    if include_l7:
        _write_schema(
            schema_root / "L7.json",
            layer="L7",
            extra_required=[
                "checked_clusters",
                "overlapping_clusters",
                "discrepancy_count",
                "discrepancies_by_field",
                "sample_discrepancies",
            ],
            extra_properties={
                "checked_clusters": {"type": "integer"},
                "overlapping_clusters": {"type": "integer"},
                "discrepancy_count": {"type": "integer"},
                "discrepancies_by_field": {"type": "object"},
                "sample_discrepancies": {"type": "array"},
            },
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


def _write_evidence(
    repo_root: Path,
    *,
    layer: str,
    scope: str,
    file_name: str,
    produced_at: datetime,
    status: str,
    extras: dict[str, object],
    evidence_subpath: str | None = None,
) -> Path:
    if evidence_subpath is not None:
        evidence_path = repo_root / "evidence" / layer / evidence_subpath / file_name
    elif layer == "L6":
        evidence_path = repo_root / "evidence" / layer / file_name
    else:
        evidence_path = repo_root / "evidence" / layer / scope / file_name
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "layer": layer,
        "scope": scope,
        "schema_version": 1,
        "produced_at_utc": produced_at.isoformat().replace("+00:00", "Z"),
        "repo_sha": "abc12345",
        "gate_command": f"make gate-{layer}",
        "status": status,
        **extras,
    }
    evidence_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return evidence_path


def _write_waiver(
    repo_root: Path,
    *,
    layer: str,
    scope: str,
    evidence_path: Path,
    expires_at_utc: datetime,
) -> None:
    waiver_path = repo_root / "waivers" / f"{layer}_{scope}_2026-04-24.yaml"
    waiver_path.parent.mkdir(parents=True, exist_ok=True)
    waiver_path.write_text(
        json.dumps(
            {
                "layer": layer,
                "scope": scope,
                "reason": "Temporary pilot waiver.",
                "created_at_utc": "2026-04-24T11:00:00Z",
                "expires_at_utc": expires_at_utc.isoformat().replace("+00:00", "Z"),
                "owner": "keel-test",
                "evidence_path": evidence_path.relative_to(repo_root).as_posix(),
                "followup_ticket": "KEEL-123",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_repo_contract(repo_root: Path, *, include_l3: bool = False, include_l7: bool = False) -> None:
    _write_layers_yaml(repo_root, include_l3=include_l3, include_l7=include_l7)
    _write_schema_files(repo_root, include_l3=include_l3, include_l7=include_l7)


def test_collect_status_rows_reports_fixed_scope_pass_stale_and_missing_error(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)

    _write_evidence(
        repo_root,
        layer="L1",
        scope="NC",
        file_name="2026-04-24.json",
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        status="pass",
        extras={
            "current_total": 1500,
            "expected_range": {"minimum": 1000, "maximum": 2000},
            "ratio": 1.5,
            "anchor_path": "docs/anchors/NC.md",
            "anchor_schema_version": 1,
        },
    )
    _write_evidence(
        repo_root,
        layer="L10",
        scope="NC",
        file_name="2026-04-23.json",
        produced_at=datetime(2026, 4, 23, 12, 0, tzinfo=UTC),
        status="pass",
        extras={
            "evaluated_routes": 2,
            "empty_banner_cases": 1,
            "deviation_banner_cases": 1,
            "failing_routes": [],
        },
    )

    rows = keel_status.collect_status_rows(repo_root=repo_root, today_utc=date(2026, 4, 24))

    assert [(row.layer_id, row.scope, row.status) for row in rows] == [
        ("L1", "NC", "pass"),
        ("L5", "global", "error"),
        ("L6", "NC_transactions", "error"),
        ("L6", "NC_committee_documents", "error"),
        ("L6", "NC_ie_document_index", "error"),
        ("L10", "NC", "stale"),
    ]
    assert rows[0].evidence_path == Path("evidence/L1/NC/2026-04-24.json")
    assert rows[1].detail == "missing evidence"
    assert rows[2].detail == "missing evidence"
    assert rows[3].detail == "missing evidence"
    assert rows[4].detail == "missing evidence"
    assert rows[5].detail == "latest evidence date 2026-04-23"


def test_collect_status_rows_reports_emitted_scope_waived_and_schema_invalid_error(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    monkeypatch.setattr(keel_status, "_now_utc", lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC))

    waived_evidence_path = _write_evidence(
        repo_root,
        layer="L6",
        scope="NC_transactions",
        file_name="nc-load-1.json",
        produced_at=datetime(2026, 4, 24, 8, 30, tzinfo=UTC),
        status="fail",
        extras={
            "load_id": "nc-load-1",
            "total_rows": 10,
            "out_of_range_rows": 1,
            "example_rows": [{"record_id": "1", "field": "date", "value": "2099-01-01"}],
        },
    )
    _write_waiver(
        repo_root,
        layer="L6",
        scope="NC_transactions",
        evidence_path=waived_evidence_path,
        expires_at_utc=datetime(2026, 4, 25, 0, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(keel_status, "_now_utc", lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC))
    invalid_path = repo_root / "evidence" / "L6" / "tx-load-1.json"
    invalid_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_path.write_text(
        json.dumps(
            {
                "layer": "L6",
                "scope": "TX",
                "schema_version": 1,
                "repo_sha": "abc12345",
                "gate_command": "make gate-L6",
                "status": "pass",
                "load_id": "tx-load-1",
                "total_rows": 25,
                "out_of_range_rows": 0,
                "example_rows": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    rows = keel_status.collect_status_rows(repo_root=repo_root, today_utc=date(2026, 4, 24))

    assert [(row.layer_id, row.scope, row.status) for row in rows] == [
        ("L1", "NC", "error"),
        ("L5", "global", "error"),
        ("L6", "NC_committee_documents", "error"),
        ("L6", "NC_ie_document_index", "error"),
        ("L6", "NC_transactions", "waived"),
        ("L6", "TX", "error"),
        ("L10", "NC", "error"),
    ]
    assert rows[2].detail == "missing evidence"
    assert rows[3].detail == "missing evidence"
    assert rows[4].detail == "waiver active"
    assert rows[4].evidence_path == Path("evidence/L6/nc-load-1.json")
    assert rows[5].detail == "schema-invalid evidence"


def test_collect_status_rows_supports_nested_emitted_source_id_scope_filters(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root, include_l3=True)
    today_utc = date(2026, 4, 24)

    _write_evidence(
        repo_root,
        layer="L3",
        scope="NC",
        file_name="validated_2026-04-24.json",
        produced_at=datetime(2026, 4, 24, 9, 0, tzinfo=UTC),
        status="pass",
        extras={
            "source_id": "nc_transactions",
            "current_state": "validated",
            "transition_date": "2026-04-24",
            "linked_evidence": [],
            "validation_checks": [],
        },
        evidence_subpath="NC/nc_transactions",
    )
    _write_evidence(
        repo_root,
        layer="L3",
        scope="NC",
        file_name="validated_2026-04-24.json",
        produced_at=datetime(2026, 4, 24, 9, 10, tzinfo=UTC),
        status="pass",
        extras={
            "source_id": "nc_committee_documents",
            "current_state": "validated",
            "transition_date": "2026-04-24",
            "linked_evidence": [],
            "validation_checks": [],
        },
        evidence_subpath="NC/nc_committee_documents",
    )
    _write_evidence(
        repo_root,
        layer="L3",
        scope="SC",
        file_name="validated_2026-04-24.json",
        produced_at=datetime(2026, 4, 24, 9, 15, tzinfo=UTC),
        status="pass",
        extras={
            "source_id": "nc_ie_document_index",
            "current_state": "validated",
            "transition_date": "2026-04-24",
            "linked_evidence": [],
            "validation_checks": [],
        },
        evidence_subpath="SC/nc_ie_document_index",
    )

    l3_layer = next(layer for layer in keel_status._load_yaml(repo_root / "layers.yaml")["layers"] if layer["id"] == "L3")
    emitted_rows = keel_status._emitted_scope_rows(repo_root=repo_root, layer=l3_layer, today_utc=today_utc)
    collected_rows = [row for row in keel_status.collect_status_rows(repo_root=repo_root, today_utc=today_utc) if row.layer_id == "L3"]

    assert [(row.scope, row.status, row.detail) for row in emitted_rows] == [
        ("nc_ie_document_index", "error", "missing evidence"),
        ("nc_durham_city_council_roster", "error", "missing evidence"),
        ("nc_general_assembly_house_roster", "error", "missing evidence"),
        ("nc_transactions", "pass", None),
        ("nc_committee_documents", "pass", None),
    ]
    assert [(row.scope, row.status, row.detail) for row in collected_rows] == [
        ("nc_ie_document_index", "error", "missing evidence"),
        ("nc_durham_city_council_roster", "error", "missing evidence"),
        ("nc_general_assembly_house_roster", "error", "missing evidence"),
        ("nc_transactions", "pass", None),
        ("nc_committee_documents", "pass", None),
    ]
    assert collected_rows[3].evidence_path == Path("evidence/L3/NC/nc_transactions/validated_2026-04-24.json")
    assert collected_rows[4].evidence_path == Path("evidence/L3/NC/nc_committee_documents/validated_2026-04-24.json")


def test_collect_status_rows_handles_l7_registered_as_fixed_scope_global(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root, include_l7=True)
    _write_evidence(
        repo_root,
        layer="L7",
        scope="global",
        file_name="2026-04-24.json",
        produced_at=datetime(2026, 4, 24, 10, 0, tzinfo=UTC),
        status="pass",
        extras={
            "checked_clusters": 7,
            "overlapping_clusters": 3,
            "discrepancy_count": 0,
            "discrepancies_by_field": {"canonical_name": 0, "primary_address": 0},
            "sample_discrepancies": [],
        },
    )

    rows = keel_status.collect_status_rows(repo_root=repo_root, today_utc=date(2026, 4, 24))

    l7_rows = [row for row in rows if row.layer_id == "L7"]
    assert [(row.scope, row.status) for row in l7_rows] == [("global", "pass")]
    assert l7_rows[0].evidence_path == Path("evidence/L7/global/2026-04-24.json")


def test_collect_status_rows_treats_same_day_expired_waiver_as_error(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)

    waived_evidence_path = _write_evidence(
        repo_root,
        layer="L6",
        scope="NC_transactions",
        file_name="nc-load-1.json",
        produced_at=datetime(2026, 4, 24, 8, 30, tzinfo=UTC),
        status="fail",
        extras={
            "load_id": "nc-load-1",
            "total_rows": 10,
            "out_of_range_rows": 1,
            "example_rows": [{"record_id": "1", "field": "date", "value": "2099-01-01"}],
        },
    )
    _write_waiver(
        repo_root,
        layer="L6",
        scope="NC_transactions",
        evidence_path=waived_evidence_path,
        expires_at_utc=datetime(2026, 4, 24, 10, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(keel_status, "_now_utc", lambda: datetime(2026, 4, 24, 12, 0, tzinfo=UTC))

    rows = keel_status.collect_status_rows(repo_root=repo_root, today_utc=date(2026, 4, 24))

    l6_rows = [row for row in rows if row.layer_id == "L6"]
    assert [(row.scope, row.status, row.detail) for row in l6_rows] == [
        ("NC_committee_documents", "error", "missing evidence"),
        ("NC_ie_document_index", "error", "missing evidence"),
        ("NC_transactions", "error", "expired or invalid waiver"),
    ]


def test_collect_status_rows_reports_missing_expected_emitted_scope(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)

    _write_evidence(
        repo_root,
        layer="L6",
        scope="NC_transactions",
        file_name="nc-transactions-1.json",
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        status="pass",
        extras={
            "load_id": "nc-transactions-1",
            "total_rows": 10,
            "out_of_range_rows": 0,
            "example_rows": [],
        },
    )

    rows = keel_status.collect_status_rows(repo_root=repo_root, today_utc=date(2026, 4, 24))

    l6_rows = [row for row in rows if row.layer_id == "L6"]
    assert [(row.scope, row.status, row.detail) for row in l6_rows] == [
        ("NC_committee_documents", "error", "missing evidence"),
        ("NC_ie_document_index", "error", "missing evidence"),
        ("NC_transactions", "pass", None),
    ]


def test_main_prints_one_line_summary_per_status_row(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo_contract(repo_root)
    _write_evidence(
        repo_root,
        layer="L1",
        scope="NC",
        file_name="2026-04-24.json",
        produced_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        status="pass",
        extras={
            "current_total": 1500,
            "expected_range": {"minimum": 1000, "maximum": 2000},
            "ratio": 1.5,
            "anchor_path": "docs/anchors/NC.md",
            "anchor_schema_version": 1,
        },
    )

    exit_code = keel_status.main(["--repo-root", str(repo_root), "--date", "2026-04-24"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.splitlines() == [
        "L1 scope=NC status=pass produced_at=2026-04-24T12:00:00Z evidence=evidence/L1/NC/2026-04-24.json",
        "L5 scope=global status=error detail=missing evidence",
        "L6 scope=NC_transactions status=error detail=missing evidence",
        "L6 scope=NC_committee_documents status=error detail=missing evidence",
        "L6 scope=NC_ie_document_index status=error detail=missing evidence",
        "L10 scope=NC status=error detail=missing evidence",
    ]
