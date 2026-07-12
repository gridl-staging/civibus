from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import core.keel_gate_l11 as keel_gate_l11


def _copy_owner_files_to_tmp_repo(*, repo_root: Path, destination_root: Path) -> None:
    for relative_path in keel_gate_l11.L11_OWNER_FILES:
        destination_path = destination_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_text((repo_root / relative_path).read_text(encoding="utf-8"), encoding="utf-8")


def test_collect_editorial_rows_uses_only_explicit_owner_files_and_emits_user_facing_copy(tmp_path: Path) -> None:
    source_repo_root = Path(__file__).resolve().parents[2]
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _copy_owner_files_to_tmp_repo(repo_root=source_repo_root, destination_root=repo_root)

    collection = keel_gate_l11.collect_editorial_rows(repo_root=repo_root)

    assert collection.scope == keel_gate_l11.L11_SCOPE
    assert collection.owner_files == list(keel_gate_l11.L11_OWNER_FILES)
    assert {row.owner_file for row in collection.rows} <= set(keel_gate_l11.L11_OWNER_FILES)
    # `web/src/lib/config/app.ts` owns APP_SHELL copy; these rows anchor the federal-first v1 scope.
    expected_rows = [
        (
            "app-shell-static-routes-home-title",
            "web/src/lib/config/app.ts",
            "Civibus | Federal public-records intelligence",
        ),
        (
            "app-shell-static-routes-home-description",
            "web/src/lib/config/app.ts",
            "Browse federal-first Civibus profiles for Congress and the White House with source-linked FEC money summaries and independent expenditures.",
        ),
        ("app-shell-landing-eyebrow", "web/src/lib/config/app.ts", "Federal-first public records"),
        (
            "app-shell-landing-heading",
            "web/src/lib/config/app.ts",
            "Follow money around Congress and the White House.",
        ),
        (
            "app-shell-landing-body",
            "web/src/lib/config/app.ts",
            "Civibus v1 covers 543 elected federal officials: 435 House members, 100 senators, 6 non-voting delegates, the President, and the Vice President. Each profile is intended to connect photo, short bio, office, FEC campaign-finance summary, and Schedule E independent expenditures for and against.",
        ),
        ("app-shell-landing-coverage-heading", "web/src/lib/config/app.ts", "Federal scope"),
        (
            "app-shell-landing-coverage-summary",
            "web/src/lib/config/app.ts",
            "Current launch scope is the 543 elected federal officials only, with source-linked photos, bios, offices, FEC money summaries, and Schedule E independent expenditures. State, city, property, candidate-list, and committee-list breadth is not advertised from the homepage.",
        ),
        ("app-shell-landing-cta-label", "web/src/lib/config/app.ts", "Browse Congress"),
        (
            "app-shell-landing-cta-description",
            "web/src/lib/config/app.ts",
            "Open the federal directory for members of Congress and delegates.",
        ),
        ("app-shell-landing-action-001-label", "web/src/lib/config/app.ts", "Search"),
        (
            "app-shell-landing-action-001-description",
            "web/src/lib/config/app.ts",
            "Search source-linked federal people, offices, committees, and filings.",
        ),
        ("app-shell-landing-action-002-label", "web/src/lib/config/app.ts", "Methodology"),
        (
            "app-shell-landing-action-002-description",
            "web/src/lib/config/app.ts",
            "Read source, refresh, and coverage methods for the federal-first dataset.",
        ),
        ("app-shell-methodology-heading", "web/src/lib/config/app.ts", "Methodology"),
        (
            "app-shell-methodology-coverage-summary",
            "web/src/lib/config/app.ts",
            "Civibus combines campaign-finance, civic office, and property records in one search experience. Coverage varies by jurisdiction and is refreshed based on source cadence.",
        ),
        ("app-shell-methodology-section-001-heading", "web/src/lib/config/app.ts", "Data freshness policy"),
        (
            "app-shell-methodology-section-001-body",
            "web/src/lib/config/app.ts",
            "Production support requires data that can be refreshed at least weekly near elections, with daily updates preferred. Sources that only publish annual or quarterly exports are not treated as fully launch-ready without a supplementary path.",
        ),
        ("app-shell-methodology-section-002-heading", "web/src/lib/config/app.ts", "Entity resolution methodology"),
        (
            "app-shell-methodology-section-002-body",
            "web/src/lib/config/app.ts",
            "Entity resolution uses probabilistic matching with confidence tiers derived from model scores. High-confidence matches can be auto-merged while lower-confidence links remain reviewable so users can inspect uncertainty.",
        ),
        ("app-shell-methodology-section-003-heading", "web/src/lib/config/app.ts", "Source-linking and evidence"),
        (
            "app-shell-methodology-section-003-body",
            "web/src/lib/config/app.ts",
            "Every surfaced record is tied to provenance metadata and source links so users can trace claims back to official filings or source systems. Civibus prioritizes verifiable evidence over inferred narrative summaries. Person-page Top employers aggregate raw employer names from itemized individual contributions; they are not industry- or sector-coded.",
        ),
        (
            "app-shell-methodology-confidence-heading",
            "web/src/lib/config/app.ts",
            "Entity resolution confidence labels",
        ),
        ("app-shell-methodology-confidence-label-001-label", "web/src/lib/config/app.ts", "match"),
        (
            "app-shell-methodology-confidence-label-001-description",
            "web/src/lib/config/app.ts",
            "Confidence >= 0.95. Auto-merge threshold.",
        ),
        ("app-shell-methodology-confidence-label-002-label", "web/src/lib/config/app.ts", "probable_match"),
        (
            "app-shell-methodology-confidence-label-002-description",
            "web/src/lib/config/app.ts",
            "Confidence from 0.80 to <0.95. Likely same entity and review-worthy.",
        ),
        ("app-shell-methodology-confidence-label-003-label", "web/src/lib/config/app.ts", "possible_match"),
        (
            "app-shell-methodology-confidence-label-003-description",
            "web/src/lib/config/app.ts",
            "Confidence from 0.60 to <0.80. Candidate link with lower confidence.",
        ),
        (
            "outside-spending-unavailable",
            "web/src/lib/campaign-finance-detail/presentation.ts",
            "Outside-spending data is not yet available for this candidate. Coverage may be incomplete.",
        ),
        (
            "al-freshness-note",
            "web/src/lib/detail-trust/presentation.ts",
            "Alabama campaign finance production data is currently a narrow committee-state slice; totals may be incomplete.",
        ),
        (
            "ga-freshness-note",
            "web/src/lib/detail-trust/presentation.ts",
            "Georgia campaign finance production data is currently a narrow committee-state slice; totals may be incomplete.",
        ),
        (
            "contest-candidate-list-warning",
            "web/src/lib/civic-detail/presentation.ts",
            "Candidate list coverage is incomplete for this contest.",
        ),
        ("landing-take-action-heading", "web/src/routes/+page.svelte", "Take action"),
    ]
    actual_rows = [(row.copy_id, row.owner_file, row.text) for row in collection.rows]
    assert actual_rows == expected_rows
    assert all(not row.text.startswith("/") for row in collection.rows)
    assert all(not row.text.startswith("mailto:") for row in collection.rows)
    assert all(row.text != "slug-collision" for row in collection.rows)


def test_collect_editorial_rows_uses_top_level_methodology_when_nested_methodology_exists(tmp_path: Path) -> None:
    source_repo_root = Path(__file__).resolve().parents[2]
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _copy_owner_files_to_tmp_repo(repo_root=source_repo_root, destination_root=repo_root)

    app_owner_path = repo_root / "web/src/lib/config/app.ts"
    app_source = app_owner_path.read_text(encoding="utf-8")
    app_shell_suffix = "\n} as const;"
    app_shell_prefix, separator, app_shell_tail = app_source.rpartition(app_shell_suffix)
    assert separator == app_shell_suffix
    assert app_shell_tail == "\n"

    app_owner_path.write_text(
        app_shell_prefix
        + """,
  auditTrail: {
    methodology: {
      heading: "Nested methodology should never be selected",
      coverageSummary: "Nested methodology coverage summary",
      sections: [],
      confidenceHeading: "Nested methodology confidence heading",
      confidenceLabels: []
    }
  }
} as const;
""",
        encoding="utf-8",
    )
    app_source_with_nested_methodology = app_owner_path.read_text(encoding="utf-8")
    top_level_methodology_anchor = "\n  methodology: {\n"
    app_shell_prefix, separator, app_shell_suffix = app_source_with_nested_methodology.rpartition(
        top_level_methodology_anchor
    )
    assert separator == top_level_methodology_anchor
    app_owner_path.write_text(
        app_shell_prefix
        + "\n  /* methodology: { comment anchor that must be ignored } */\n"
        + separator
        + app_shell_suffix.replace(
            "\n    sections: [\n",
            "\n    /* sections: [ comment anchor that must be ignored ] */\n    sections: [\n",
            1,
        ).replace(
            "\n    confidenceLabels: [\n",
            "\n    // confidenceLabels: [ comment anchor that must be ignored ]\n    confidenceLabels: [\n",
            1,
        ),
        encoding="utf-8",
    )

    collection = keel_gate_l11.collect_editorial_rows(repo_root=repo_root)
    rows_by_copy_id = {row.copy_id: row.text for row in collection.rows}

    assert rows_by_copy_id["app-shell-methodology-heading"] == "Methodology"
    assert rows_by_copy_id["app-shell-methodology-confidence-label-001-label"] == "match"
    assert all("Nested methodology" not in row.text for row in collection.rows)


def test_collect_editorial_rows_is_delegated_to_helpers_within_size_limit() -> None:
    collector_source = inspect.getsource(keel_gate_l11.collect_editorial_rows)
    app_shell_source = inspect.getsource(keel_gate_l11._collect_app_shell_rows)
    collector_source_lines = collector_source.splitlines()
    app_shell_source_lines = app_shell_source.splitlines()

    assert len(collector_source_lines) <= 100
    assert len(app_shell_source_lines) <= 100


def test_main_writes_l11_evidence_with_explicit_owner_files(tmp_path: Path, monkeypatch) -> None:
    source_repo_root = Path(__file__).resolve().parents[2]
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _copy_owner_files_to_tmp_repo(repo_root=source_repo_root, destination_root=repo_root)
    schema_root = repo_root / "evidence_schemas"
    schema_root.mkdir(parents=True, exist_ok=True)
    (schema_root / "L11.json").write_text(
        (source_repo_root / "evidence_schemas" / "L11.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    monkeypatch.setattr(keel_gate_l11, "_repo_sha", lambda repo_root: "6a78078d")
    monkeypatch.setattr(keel_gate_l11, "_utc_now", lambda: datetime(2026, 4, 24, 13, 30, tzinfo=UTC))

    exit_code = keel_gate_l11.main(
        [
            "--repo-root",
            str(repo_root),
            "--date",
            "2026-04-24",
        ]
    )

    evidence_path = repo_root / "evidence" / "L11" / keel_gate_l11.L11_SCOPE / "2026-04-24.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["layer"] == "L11"
    assert payload["scope"] == keel_gate_l11.L11_SCOPE
    assert payload["status"] == "pass"
    assert payload["owner_files"] == list(keel_gate_l11.L11_OWNER_FILES)
    assert any(row["copy_id"] == "app-shell-methodology-heading" for row in payload["rows"])
    assert any(row["copy_id"] == "al-freshness-note" for row in payload["rows"])
    assert any(row["copy_id"] == "ga-freshness-note" for row in payload["rows"])
    assert any(row["text"] == "Take action" for row in payload["rows"])
    assert any(row["owner_file"] == "web/src/routes/+page.svelte" for row in payload["rows"])
