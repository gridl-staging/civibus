from __future__ import annotations

import json
from pathlib import Path

import pytest

from domains.campaign_finance.coverage.registry import CoverageRegistry
from domains.campaign_finance.coverage.render_summary import (
    main,
    render_publication_markdown,
    render_summary_markdown,
)
from domains.campaign_finance.coverage.seed_registry import main as seed_registry_main
from domains.campaign_finance.coverage.seed_registry import merge_seed_registry
from domains.campaign_finance.coverage.validate_registry import main as validate_registry_main


def _row_payload(
    *,
    jurisdiction_code: str,
    name: str,
    jurisdiction_type: str = "state",
    best_update_frequency: str = "daily",
    best_last_verified_working: str | None = "2026-03-21",
    covers_sub_jurisdictions: bool = True,
    source_names: list[str] | None = None,
    runner_wired: bool = True,
    tier: str | None = "launch-support candidate",
    evidence_summary: str | None = "test",
    operational_reason: str | None = None,
    next_action: str | None = "test",
    evidence_date: str | None = "2026-03-25",
    parent_jurisdiction_code: str | None = None,
    municipal_audit_decision: str | None = None,
) -> dict[str, object]:
    resolved_source_names = source_names or ["A"]
    return {
        "jurisdiction_code": jurisdiction_code,
        "name": name,
        "jurisdiction_type": jurisdiction_type,
        "best_update_frequency": best_update_frequency,
        "best_last_verified_working": best_last_verified_working,
        "covers_sub_jurisdictions": covers_sub_jurisdictions,
        "source_count": len(resolved_source_names),
        "source_names": resolved_source_names,
        "runner_wired": runner_wired,
        "tier": tier,
        "evidence_summary": evidence_summary,
        "operational_reason": operational_reason,
        "next_action": next_action,
        "evidence_date": evidence_date,
        "parent_jurisdiction_code": parent_jurisdiction_code,
        "municipal_audit_decision": municipal_audit_decision,
    }


def _registry_from_rows(*rows: dict[str, object]) -> CoverageRegistry:
    return CoverageRegistry.model_validate({"rows": list(rows)})


def _write_registry_file(tmp_path: Path, registry: CoverageRegistry) -> Path:
    registry_path = tmp_path / "coverage-registry.json"
    registry_path.write_text(f"{registry.model_dump_json(indent=2)}\n", encoding="utf-8")
    return registry_path


def _publication_output_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    return (
        tmp_path / "coverage-registry-summary.md",
        tmp_path / "coverage-build-priority-queue.md",
        tmp_path / "2026-launch-support-matrix.md",
    )


def _assert_authority_note(markdown: str) -> None:
    assert "Authoritative source: `docs/reference/research/coverage-registry.json`." in markdown


def _assert_publication_date(markdown: str, expected_date: str) -> None:
    assert f"Date: {expected_date}" in markdown


def test_central_coverage_control_modules_do_not_ship_stub_or_todo_docstrings() -> None:
    project_root = Path(__file__).resolve().parents[3]
    paths = (
        project_root / "domains" / "campaign_finance" / "coverage" / "registry.py",
        project_root / "domains" / "campaign_finance" / "coverage" / "render_summary.py",
        project_root / "domains" / "campaign_finance" / "coverage" / "seed_registry.py",
        project_root / "domains" / "campaign_finance" / "coverage" / "validate_registry.py",
    )

    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "Stub summary for" not in source, path.name


def test_render_summary_markdown_matches_registry_rows() -> None:
    registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="CA",
            name="California",
            source_names=["A", "B"],
            evidence_summary=None,
            next_action=None,
            evidence_date=None,
        ),
        _row_payload(
            jurisdiction_code="OH",
            name="Ohio",
            best_update_frequency="annual",
            best_last_verified_working=None,
            source_names=["C", "D"],
            runner_wired=False,
            tier=None,
            evidence_summary=None,
            next_action=None,
            evidence_date=None,
        ),
    )

    markdown = render_summary_markdown(registry)

    assert "# Coverage Registry Summary (Derived)" in markdown
    _assert_authority_note(markdown)
    assert "| Jurisdiction | Tier | Best Cadence | Runner Wired | Source Count |" in markdown
    assert "| CA | launch-support candidate | daily | yes | 2 |" in markdown
    assert "| OH | unassigned | annual | no | 2 |" in markdown


def test_render_summary_handles_mixed_state_and_municipality_rows() -> None:
    """Renderer produces separate sections for state-equivalent and municipality layers."""
    registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="CA",
            name="California",
            source_names=["A", "B"],
        ),
        _row_payload(
            jurisdiction_code="MN",
            name="Minnesota",
            best_update_frequency="quarterly",
            covers_sub_jurisdictions=False,
            source_names=["E"],
            tier="freshness-limited",
        ),
        _row_payload(
            jurisdiction_code="CA_LOS_ANGELES",
            name="Los Angeles",
            jurisdiction_type="municipality",
            best_last_verified_working="2026-03-25",
            covers_sub_jurisdictions=False,
            source_names=["Inherited from CA"],
            runner_wired=False,
            evidence_summary="Covered by CA",
            next_action="Inherits parent",
            parent_jurisdiction_code="CA",
            municipal_audit_decision="covered_by_parent",
        ),
        _row_payload(
            jurisdiction_code="MN_MINNEAPOLIS",
            name="Minneapolis",
            jurisdiction_type="municipality",
            best_update_frequency="quarterly",
            best_last_verified_working=None,
            covers_sub_jurisdictions=False,
            source_names=["Independent"],
            runner_wired=False,
            tier="freshness-limited",
            evidence_summary="MN does not cover subs",
            next_action="Investigate city portal",
            parent_jurisdiction_code="MN",
            municipal_audit_decision="independent_target",
        ),
    )

    markdown = render_summary_markdown(registry)

    # State layer header and rows present
    assert "## State / Federal Layer" in markdown
    assert "| CA |" in markdown
    assert "| MN |" in markdown

    # Municipality layer header and rows present
    assert "## Municipality Layer" in markdown
    assert "| CA_LOS_ANGELES |" in markdown
    assert "| MN_MINNEAPOLIS |" in markdown

    # Municipality table has parent and decision columns
    assert "| Parent |" in markdown
    assert "| Decision |" in markdown
    assert "| covered_by_parent |" in markdown
    assert "| independent_target |" in markdown


def test_render_summary_rejects_non_municipality_local_rows() -> None:
    registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="CA",
            name="California",
            source_names=["A", "B"],
        ),
        _row_payload(
            jurisdiction_code="HENNEPIN",
            name="Hennepin County",
            jurisdiction_type="county",
            best_update_frequency="weekly",
            covers_sub_jurisdictions=False,
            source_names=["County export"],
            runner_wired=False,
            tier="freshness-limited",
        ),
    )

    with pytest.raises(ValueError, match="Unsupported local jurisdiction_type"):
        render_summary_markdown(registry)


def test_render_publication_markdown_uses_registry_fields_for_queue_ordering() -> None:
    registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="CA",
            name="California",
            next_action="Run CA proof",
        ),
        _row_payload(
            jurisdiction_code="MN_MINNEAPOLIS",
            name="Minneapolis",
            jurisdiction_type="municipality",
            best_update_frequency="quarterly",
            best_last_verified_working=None,
            covers_sub_jurisdictions=False,
            source_names=["B"],
            runner_wired=False,
            tier="freshness-limited",
            next_action="Investigate city source",
            parent_jurisdiction_code="MN",
            municipal_audit_decision="independent_target",
        ),
        _row_payload(
            jurisdiction_code="OH",
            name="Ohio",
            best_update_frequency="annual",
            best_last_verified_working=None,
            source_names=["C"],
            runner_wired=False,
            tier="deferred/blocked",
            operational_reason="blocked",
            next_action="Fix portal access",
        ),
    )

    publication = render_publication_markdown(
        registry,
        implemented_jurisdiction_codes={"CA", "OH"},
    )

    queue_lines = [
        line
        for line in publication.queue_markdown.splitlines()
        if line.startswith("| ") and "Jurisdiction |" not in line and "---" not in line
    ]
    assert (
        "| Queue Group | Jurisdiction | Type | Runner Wired | Municipal Decision | Best Cadence | Next Action |"
        in publication.queue_markdown
    )
    assert queue_lines[0].startswith("| launch-support candidate")
    assert "| CA | state | yes | state_equivalent | daily | Run CA proof |" in queue_lines[0]
    assert queue_lines[1].startswith("| freshness-limited")
    assert (
        "| MN_MINNEAPOLIS | municipality | no | independent_target | quarterly | Investigate city source |"
        in queue_lines[1]
    )
    assert queue_lines[2].startswith("| deferred/blocked")
    assert "| OH | state | no | state_equivalent | annual | Fix portal access |" in queue_lines[2]
    assert "Date: 2026-03-25" in publication.queue_markdown
    assert "Date: 2026-03-25" in publication.matrix_markdown
    assert "Authoritative source: `docs/reference/research/coverage-registry.json`." in publication.summary_markdown
    assert "Authoritative source: `docs/reference/research/coverage-registry.json`." in publication.queue_markdown
    assert "Authoritative source: `docs/reference/research/coverage-registry.json`." in publication.matrix_markdown
    assert "| CA | state | launch-support candidate | daily | yes | Run CA proof |" in publication.matrix_markdown
    assert "| OH | state | deferred/blocked | annual | no | Fix portal access |" in publication.matrix_markdown
    assert "MN_MINNEAPOLIS" not in publication.matrix_markdown


def test_main_publishes_summary_queue_and_matrix_from_single_registry_input(tmp_path: Path) -> None:
    registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="CA",
            name="California",
            next_action="Run CA proof",
        ),
        _row_payload(
            jurisdiction_code="FL",
            name="Florida",
            best_update_frequency="daily",
            best_last_verified_working="2026-03-25",
            source_names=[
                "FL DOS Campaign Finance - Contributions",
                "FL DOS Campaign Finance - Expenditures",
                "FL DOS Campaign Finance - Transfers",
                "FL DOS Campaign Finance - Other Disbursements",
            ],
            runner_wired=True,
            tier="implemented but unproven",
            operational_reason="Implementation exists; production execution not yet proven.",
            next_action="Run live FL refresh and verify CGI export path in production runbook.",
        ),
    )
    registry_path = _write_registry_file(tmp_path, registry)
    summary_output, queue_output, matrix_output = _publication_output_paths(tmp_path)

    exit_code = main(
        [
            "--path",
            str(registry_path),
            "--summary-output",
            str(summary_output),
            "--queue-output",
            str(queue_output),
            "--matrix-output",
            str(matrix_output),
        ]
    )

    assert exit_code == 0
    assert summary_output.exists()
    assert queue_output.exists()
    assert matrix_output.exists()

    summary_markdown = summary_output.read_text(encoding="utf-8")
    queue_markdown = queue_output.read_text(encoding="utf-8")
    matrix_markdown = matrix_output.read_text(encoding="utf-8")

    _assert_publication_date(summary_markdown, "2026-03-25")
    _assert_authority_note(summary_markdown)
    _assert_publication_date(queue_markdown, "2026-03-25")
    _assert_publication_date(matrix_markdown, "2026-03-25")
    _assert_authority_note(queue_markdown)
    _assert_authority_note(matrix_markdown)
    assert "| CA | state | launch-support candidate | daily | yes | Run CA proof |" in matrix_markdown
    assert (
        "| FL | state | implemented but unproven | daily | yes | Run live FL refresh and verify CGI export path in production runbook. |"
        in matrix_markdown
    )


def test_main_returns_nonzero_for_unsupported_local_registry_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="CA",
            name="California",
            next_action="Run CA proof",
        ),
        _row_payload(
            jurisdiction_code="HENNEPIN",
            name="Hennepin County",
            jurisdiction_type="county",
            best_update_frequency="weekly",
            covers_sub_jurisdictions=False,
            source_names=["County export"],
            runner_wired=False,
            tier="freshness-limited",
            next_action="Design county renderer",
        ),
    )
    registry_path = _write_registry_file(tmp_path, registry)
    summary_output, queue_output, matrix_output = _publication_output_paths(tmp_path)

    exit_code = main(
        [
            "--path",
            str(registry_path),
            "--summary-output",
            str(summary_output),
            "--queue-output",
            str(queue_output),
            "--matrix-output",
            str(matrix_output),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAIL: Unsupported local jurisdiction_type in coverage summary: county." in captured.err
    assert not summary_output.exists()
    assert not queue_output.exists()
    assert not matrix_output.exists()


def test_render_publication_markdown_uses_registry_date_not_wall_clock() -> None:
    registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="CA",
            name="California",
            tier="implemented but unproven",
            next_action="Run CA proof",
            evidence_date="2026-01-12",
        ),
        _row_payload(
            jurisdiction_code="OH",
            name="Ohio",
            best_update_frequency="annual",
            best_last_verified_working="2026-03-24",
            source_names=["B"],
            runner_wired=False,
            tier="deferred/blocked",
            operational_reason="blocked",
            next_action="Fix portal access",
            evidence_date="2026-02-03",
        ),
    )

    publication = render_publication_markdown(
        registry,
        implemented_jurisdiction_codes={"CA", "OH"},
    )

    assert "Date: 2026-02-03" in publication.queue_markdown
    assert "Date: 2026-02-03" in publication.matrix_markdown


def test_merge_seed_registry_preserves_curated_fields_and_municipal_rows() -> None:
    existing_registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="FEC",
            name="Federal Election Commission",
            jurisdiction_type="federal",
            best_update_frequency="continuous",
            best_last_verified_working=None,
            covers_sub_jurisdictions=False,
            source_names=["Old FEC Source"],
            runner_wired=False,
            tier="implemented but unproven",
            evidence_summary="Keep FEC narrative",
            operational_reason="Keep FEC reason",
            next_action="Keep FEC action",
        ),
        _row_payload(
            jurisdiction_code="FL",
            name="Florida",
            best_update_frequency="quarterly",
            source_names=["Old FL Source"],
            runner_wired=False,
            tier="implemented but unproven",
            evidence_summary="Keep FL narrative",
            operational_reason="Keep FL reason",
            next_action="Keep FL action",
        ),
        _row_payload(
            jurisdiction_code="FL_MIAMI",
            name="Miami",
            jurisdiction_type="municipality",
            best_update_frequency="continuous",
            covers_sub_jurisdictions=False,
            source_names=["Inherited from FL"],
            runner_wired=False,
            tier="deferred/blocked",
            evidence_summary="Municipality row must survive reseeding",
            next_action="Keep municipal action",
            parent_jurisdiction_code="FL",
            municipal_audit_decision="covered_by_parent",
        ),
    )
    seeded_registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="FEC",
            name="Federal Election Commission",
            jurisdiction_type="federal",
            best_update_frequency="continuous",
            best_last_verified_working=None,
            covers_sub_jurisdictions=False,
            source_names=["FEC Schedule A API", "FEC Bulk Data", "FEC Schedule E/IE"],
            runner_wired=True,
            tier=None,
            evidence_summary=None,
            operational_reason=None,
            next_action=None,
            evidence_date=None,
        ),
        _row_payload(
            jurisdiction_code="FL",
            name="Florida",
            source_names=[
                "FL DOS Campaign Finance - Contributions",
                "FL DOS Campaign Finance - Expenditures",
                "FL DOS Campaign Finance - Transfers",
                "FL DOS Campaign Finance - Other Disbursements",
            ],
            runner_wired=True,
            tier=None,
            evidence_summary=None,
            operational_reason=None,
            next_action=None,
            evidence_date=None,
        ),
    )

    merged_registry = merge_seed_registry(existing_registry, seeded_registry)
    merged_rows = {row.jurisdiction_code: row for row in merged_registry.rows}

    assert set(merged_rows) == {"FEC", "FL", "FL_MIAMI"}
    assert merged_rows["FEC"].runner_wired is True
    assert merged_rows["FEC"].source_count == 3
    assert merged_rows["FEC"].evidence_summary == "Keep FEC narrative"
    assert merged_rows["FL"].runner_wired is True
    assert merged_rows["FL"].source_count == 4
    assert merged_rows["FL"].best_update_frequency == "quarterly"
    assert merged_rows["FL"].next_action == "Keep FL action"
    assert merged_rows["FL_MIAMI"].evidence_summary == "Municipality row must survive reseeding"


def test_seed_registry_main_merges_existing_authoritative_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="FL",
            name="Florida",
            source_names=["Old FL Source"],
            runner_wired=False,
            tier="implemented but unproven",
            evidence_summary="Keep FL narrative",
            next_action="Keep FL action",
        ),
        _row_payload(
            jurisdiction_code="FL_MIAMI",
            name="Miami",
            jurisdiction_type="municipality",
            best_update_frequency="continuous",
            covers_sub_jurisdictions=False,
            source_names=["Inherited from FL"],
            runner_wired=False,
            tier="deferred/blocked",
            evidence_summary="Municipality row must survive reseeding",
            next_action="Keep municipal action",
            parent_jurisdiction_code="FL",
            municipal_audit_decision="covered_by_parent",
        ),
    )
    seeded_registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="FL",
            name="Florida",
            source_names=[
                "FL DOS Campaign Finance - Contributions",
                "FL DOS Campaign Finance - Expenditures",
                "FL DOS Campaign Finance - Transfers",
                "FL DOS Campaign Finance - Other Disbursements",
            ],
            runner_wired=True,
            tier=None,
            evidence_summary=None,
            operational_reason=None,
            next_action=None,
            evidence_date=None,
        ),
    )
    registry_path = _write_registry_file(tmp_path, existing_registry)

    monkeypatch.setattr(
        "domains.campaign_finance.coverage.seed_registry.build_seed_registry",
        lambda: seeded_registry,
    )

    exit_code = seed_registry_main(["--path", str(registry_path)])

    assert exit_code == 0

    written_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    written_rows = {row["jurisdiction_code"]: row for row in written_registry["rows"]}
    assert set(written_rows) == {"FL", "FL_MIAMI"}
    assert written_rows["FL"]["runner_wired"] is True
    assert written_rows["FL"]["source_count"] == 4
    assert written_rows["FL"]["evidence_summary"] == "Keep FL narrative"
    assert written_rows["FL_MIAMI"]["evidence_summary"] == "Municipality row must survive reseeding"


def test_validate_registry_main_reports_cross_layer_linkage_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="MN",
            name="Minnesota",
            best_update_frequency="quarterly",
            covers_sub_jurisdictions=False,
            source_names=["MN source"],
            runner_wired=True,
            tier="freshness-limited",
        ),
        _row_payload(
            jurisdiction_code="MN_MINNEAPOLIS",
            name="Minneapolis",
            jurisdiction_type="municipality",
            best_update_frequency="quarterly",
            best_last_verified_working=None,
            covers_sub_jurisdictions=False,
            source_names=["Municipal source"],
            runner_wired=False,
            tier="freshness-limited",
            parent_jurisdiction_code="MN",
            municipal_audit_decision="covered_by_parent",
        ),
    )
    registry_path = _write_registry_file(tmp_path, registry)

    exit_code = validate_registry_main(["--path", str(registry_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "FAIL: row 'MN_MINNEAPOLIS': municipal_audit_decision is 'covered_by_parent'" in captured.out
    assert "Validation summary: checked=2" in captured.out
