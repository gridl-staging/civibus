"""Casual-mode per-layer summary collector tests.

The interpretation mapping table in `core/keel_status._interpret_scope_rows`
is the **contract** the casual rollup relies on. The string assertions here
are deliberate contract verification, NOT string-duplication smell — they
ensure the casual-mode taxonomy stays stable.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import core.keel_status as keel_status
from core.keel_status import (
    LayerSummary,
    StatusRow,
    _interpret_scope_rows,
    collect_layer_summaries,
)


# --------------------------------------------------------------------------- #
# Synthetic StatusRow factory
# --------------------------------------------------------------------------- #


def _row(*, layer: str = "LX", scope: str = "s1", status: str, detail: str | None = None) -> StatusRow:
    return StatusRow(
        layer_id=layer,
        scope=scope,
        status=status,
        evidence_path=None,
        produced_at_utc=None,
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# Branch coverage of the interpretation mapping table.
# Each test corresponds to one row in the table in the plan (Stage 1).
# --------------------------------------------------------------------------- #


def test_interpret_branch_0_session_summary_short_circuits() -> None:
    # Branch 0: session_summary scope_strategy must be intercepted by callers
    # BEFORE any row inspection. The helper signals this by accepting a
    # `scope_strategy_type` arg; when it is "session_summary", scope_rows
    # MUST be empty (callers do not run the scope walk for L12-style layers).
    out = _interpret_scope_rows(scope_rows=[], scope_strategy_type="session_summary")
    assert out == "per-session summary; no snapshot evidence"


def test_interpret_branch_1_no_evidence_emitted() -> None:
    out = _interpret_scope_rows(scope_rows=[], scope_strategy_type="fixed_scope")
    assert out == "no evidence emitted yet"


def test_interpret_branch_2_all_pass() -> None:
    rows = [_row(status="pass"), _row(scope="s2", status="pass")]
    assert _interpret_scope_rows(scope_rows=rows, scope_strategy_type="emitted_by_gate") == "all expected scopes pass"


def test_interpret_branch_3_all_stale() -> None:
    rows = [_row(status="stale"), _row(scope="s2", status="stale")]
    assert _interpret_scope_rows(scope_rows=rows, scope_strategy_type="fixed_scope") == "all evidence stale"


def test_interpret_branch_4_all_error() -> None:
    rows = [_row(status="error"), _row(scope="s2", status="error"), _row(scope="s3", status="error")]
    assert _interpret_scope_rows(scope_rows=rows, scope_strategy_type="emitted_by_gate") == "all 3 scopes errored"


def test_interpret_branch_5_all_waived() -> None:
    rows = [_row(status="waived"), _row(scope="s2", status="waived")]
    assert _interpret_scope_rows(scope_rows=rows, scope_strategy_type="fixed_scope") == "all 2 scopes waived"


def test_interpret_branch_6_first_match_wins_over_branch_7() -> None:
    # Mix of pass + error-with-detail="missing evidence".
    # Branch 6 must take precedence over the catch-all distribution
    # (branch 7). The first such missing-evidence row's scope is reported.
    rows = [
        _row(scope="alpha", status="pass"),
        _row(scope="beta", status="error", detail="missing evidence"),
        _row(scope="gamma", status="error", detail="missing evidence"),
    ]
    out = _interpret_scope_rows(scope_rows=rows, scope_strategy_type="emitted_by_gate")
    assert out == "missing emitted scope: beta"


def test_interpret_branch_7_distribution_pass_stale_error() -> None:
    # Mixed pass/stale/error with NO detail="missing evidence" — must fall
    # through to catch-all distribution rendering (branch 7).
    rows = [
        _row(scope="a", status="pass"),
        _row(scope="b", status="stale"),
        _row(scope="c", status="error", detail="schema-invalid evidence"),
    ]
    assert _interpret_scope_rows(scope_rows=rows, scope_strategy_type="emitted_by_gate") == "1 pass, 1 stale, 1 error"


def test_interpret_branch_7_omits_zero_count_buckets() -> None:
    rows = [_row(scope="a", status="pass"), _row(scope="b", status="stale")]
    assert _interpret_scope_rows(scope_rows=rows, scope_strategy_type="emitted_by_gate") == "1 pass, 1 stale"


def test_interpret_branch_7_passthrough_other_bucket() -> None:
    # Payload statuses outside the four canonical values bucket under "other".
    rows = [
        _row(scope="a", status="pass"),
        _row(scope="b", status="warn"),
        _row(scope="c", status="fail"),
    ]
    assert _interpret_scope_rows(scope_rows=rows, scope_strategy_type="emitted_by_gate") == "1 pass, 2 other"


def test_interpret_branch_4_all_error_does_not_get_caught_by_missing_first() -> None:
    # Branch ordering check: all-error with detail="missing evidence" still
    # reports the homogeneous "all N scopes errored" message (branch 4 is
    # checked before branch 6).
    rows = [
        _row(scope="x", status="error", detail="missing evidence"),
        _row(scope="y", status="error", detail="missing evidence"),
    ]
    assert _interpret_scope_rows(scope_rows=rows, scope_strategy_type="emitted_by_gate") == "all 2 scopes errored"


def test_interpret_is_deterministic_and_returns_expected_distribution() -> None:
    # Tightened to assert the actual value, not just that two calls agree —
    # otherwise a bug that returns "" both times would pass spuriously.
    rows = [_row(scope="a", status="pass"), _row(scope="b", status="error", detail="boom")]
    a = _interpret_scope_rows(scope_rows=rows, scope_strategy_type="fixed_scope")
    b = _interpret_scope_rows(scope_rows=rows, scope_strategy_type="fixed_scope")
    assert a == b == "1 pass, 1 error"


# --------------------------------------------------------------------------- #
# collect_layer_summaries — exercises the live repo's layers.yaml.
# --------------------------------------------------------------------------- #


def _live_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_collect_layer_summaries_includes_all_layers_from_live_yaml() -> None:
    """L12 (introduced status, session_summary strategy) must NOT be filtered.

    `collect_status_rows` filters to piloted/enforced layers; casual mode
    deliberately diverges so the LLM is reminded of every layer including
    introduced-status ones.

    This test reads layers.yaml directly to derive the expected list so
    legitimate layer additions don't break it. The test still catches
    the real defect class: a status filter sneaking back in (would
    drop L12 or any future `introduced` layer).
    """
    import yaml

    layers_yaml = yaml.safe_load((_live_repo_root() / "layers.yaml").read_text(encoding="utf-8"))
    expected_ids = [layer["id"] for layer in layers_yaml["layers"]]

    summaries = collect_layer_summaries(repo_root=_live_repo_root(), today_utc=date(2026, 4, 26))
    actual_ids = [s.layer_id for s in summaries]

    assert actual_ids == expected_ids, (
        "casual mode must include EVERY layers.yaml entry in declared order, "
        "regardless of the layer's lifecycle status (introduced/piloted/enforced). "
        f"expected={expected_ids} actual={actual_ids}"
    )
    # Defensive: confirm at least one introduced-status layer survives the
    # walk. If the live yaml ever loses all introduced layers, this assertion
    # becomes a no-op and we should re-add a synthetic-repo case.
    assert any(layer["status"] == "introduced" for layer in layers_yaml["layers"]), (
        "live layers.yaml has no `introduced` layer; this test no longer "
        "exercises the casual-vs-strict status-filter divergence — replace "
        "with a synthetic-repo fixture if introduced layers are gone for good."
    )


def test_collect_layer_summaries_l12_short_circuits_session_summary() -> None:
    """L12 must NOT crash with `Unsupported scope strategy: session_summary`.

    The pre-casual `collect_status_rows` raises ValueError when L12 hits the
    dispatch (it never does, because _active_layers filters it out).
    Casual mode must intercept session_summary before the dispatch.
    """
    summaries = collect_layer_summaries(repo_root=_live_repo_root(), today_utc=date(2026, 4, 26))
    l12 = next(s for s in summaries if s.layer_id == "L12")
    assert l12.scope_rows == []
    assert l12.interpretation == "per-session summary; no snapshot evidence"
    assert l12.status == "introduced"
    assert l12.name == "session_output_summary"


def test_layer_summary_dataclass_shape() -> None:
    """LayerSummary must expose layer_id, name, status, scope_rows, interpretation."""
    summaries = collect_layer_summaries(repo_root=_live_repo_root(), today_utc=date(2026, 4, 26))
    for s in summaries:
        assert isinstance(s, LayerSummary)
        assert isinstance(s.layer_id, str) and s.layer_id
        assert isinstance(s.name, str) and s.name
        assert isinstance(s.status, str) and s.status
        assert isinstance(s.scope_rows, list)
        assert isinstance(s.interpretation, str) and s.interpretation


# --------------------------------------------------------------------------- #
# main(["--summary"]) — text rollup + recurring-reviews block.
# --------------------------------------------------------------------------- #


_LAYERS_YAML_FIXTURE = """schema_version: 1
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
    gate_command: make gate-L1 JURISDICTION={scope}
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
    gate_command: uv run python -m core.keel_session_output
"""


_L1_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "layer", "scope", "schema_version", "produced_at_utc",
        "repo_sha", "gate_command", "status",
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
}


def _build_synthetic_repo(tmp_path: Path, *, with_schedule: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "layers.yaml").write_text(_LAYERS_YAML_FIXTURE, encoding="utf-8")
    schemas = repo / "evidence_schemas"
    schemas.mkdir()
    (schemas / "L1.json").write_text(json.dumps(_L1_SCHEMA, indent=2), encoding="utf-8")
    (schemas / "L12.json").write_text(json.dumps(_L1_SCHEMA, indent=2), encoding="utf-8")
    if with_schedule:
        (repo / "keel_reviews.yaml").write_text(
            "schema_version: 1\n"
            "reviews:\n"
            "  - review_id: calibration_audit\n"
            "    cadence: quarterly\n"
            "    primary_prompt: prompts/judge/calibration_audit.md\n"
            "    skeptic_prompt: prompts/judge/calibration_audit_skeptic.md\n"
            "    evidence_root: evidence/review/calibration_audit\n"
            "  - review_id: escalation_review\n"
            "    cadence: weekly\n"
            "    primary_prompt: prompts/judge/escalation_review.md\n"
            "    skeptic_prompt: prompts/judge/escalation_review_skeptic.md\n"
            "    evidence_root: evidence/review/escalation_review\n",
            encoding="utf-8",
        )
    return repo


def test_main_summary_emits_per_layer_block_then_recurring_reviews(tmp_path, capsys) -> None:
    repo = _build_synthetic_repo(tmp_path, with_schedule=True)
    rc = keel_status.main(["--summary", "--repo-root", str(repo), "--date", "2026-04-26"])
    assert rc == 0
    out = capsys.readouterr().out
    # Per-layer blocks, in declared order.
    l1_idx = out.index("L1")
    l12_idx = out.index("L12")
    reviews_idx = out.index("## Recurring reviews")
    assert l1_idx < l12_idx < reviews_idx
    # Interpretation strings present.
    # L1 (fixed_scope, no evidence written) → single error row → "all 1 scopes errored".
    assert "all 1 scopes errored" in out
    assert "per-session summary; no snapshot evidence" in out  # L12
    # Recurring-review block sourced from compute_review_status.
    assert "calibration_audit" in out
    assert "escalation_review" in out


def test_main_summary_handles_missing_schedule_gracefully(tmp_path, capsys) -> None:
    repo = _build_synthetic_repo(tmp_path, with_schedule=False)
    rc = keel_status.main(["--summary", "--repo-root", str(repo), "--date", "2026-04-26"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Recurring reviews" in out
    assert "(no recurring reviews configured)" in out


def test_main_status_default_path_unchanged(tmp_path, capsys) -> None:
    """The default `make keel-status` path (no --summary) must still emit the
    pre-existing per-row format with `scope=` / `status=` tokens. The casual
    mode must not regress strict-mode output."""
    repo = _build_synthetic_repo(tmp_path, with_schedule=False)
    rc = keel_status.main(["--repo-root", str(repo), "--date", "2026-04-26"])
    assert rc == 0
    out = capsys.readouterr().out
    # L1 row shows up in old shape; L12 is filtered out (introduced status).
    assert "L1 scope=NC status=" in out
    assert "L12" not in out
