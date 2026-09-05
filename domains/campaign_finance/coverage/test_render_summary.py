from __future__ import annotations

import json
from pathlib import Path

import pytest

from domains.campaign_finance.coverage.registry import DEFAULT_REGISTRY_PATH, CoverageRegistry, load_registry
from domains.campaign_finance.coverage import render_summary
from domains.campaign_finance.coverage.render_summary import (
    _derive_implemented_city_jurisdiction_codes,
    config_identity_for_coverage_identity,
    coverage_identity_for_config_identity,
    derive_implemented_jurisdiction_codes,
    main,
    render_publication_markdown,
    render_summary_markdown,
)
from domains.campaign_finance.jurisdictions.refresh_registry import load_validated_refresh_registrations
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
    assert ("Filing-authority decision source of truth: `docs/reference/research/coverage-registry.json`.") in markdown


def _assert_publication_date(markdown: str, expected_date: str) -> None:
    assert f"Date: {expected_date}" in markdown


def _configured_supported_city_codes() -> set[str]:
    project_root = Path(__file__).resolve().parents[3]
    return {
        code
        for jurisdiction_type, code in (item.identity for item in load_validated_refresh_registrations(project_root))
        if jurisdiction_type == "municipality"
    }


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


def test_render_summary_has_no_private_runner_supported_code_owner() -> None:
    source_path = Path(__file__).with_name("render_summary.py")
    source = source_path.read_text(encoding="utf-8")

    assert "_SUPPORTED_STATE_CODES" not in source
    assert "_SUPPORTED_CITY_CODES" not in source


def test_derive_implemented_jurisdiction_codes_preserves_unwired_oh_and_supported_cities() -> None:
    configured_city_codes = _configured_supported_city_codes()
    expected_registry_codes = {
        coverage_identity_for_config_identity(("municipality", city_code))[1] for city_code in configured_city_codes
    }

    implemented_codes = derive_implemented_jurisdiction_codes()

    assert configured_city_codes == {"LA", "NYC", "PHL", "SF"}
    assert expected_registry_codes <= implemented_codes
    assert "OH" in implemented_codes
    assert "DC" not in implemented_codes


def test_launch_support_matrix_uses_canonical_membership_for_supported_city_packages() -> None:
    city_registry_codes = {
        "CA_LOS_ANGELES",
        "CA_SAN_FRANCISCO",
        "NY_NEW_YORK",
        "PA_PHILADELPHIA",
    }
    registry = _registry_from_rows(
        *(
            _row_payload(
                jurisdiction_code=code,
                name=code,
                jurisdiction_type="municipality",
                covers_sub_jurisdictions=False,
                parent_jurisdiction_code=code.split("_", maxsplit=1)[0],
                municipal_audit_decision="independent_target",
            )
            for code in sorted(city_registry_codes)
        )
    )

    matrix = render_publication_markdown(
        registry,
        implemented_jurisdiction_codes=derive_implemented_jurisdiction_codes(),
    ).matrix_markdown

    assert "`render_summary.derive_implemented_jurisdiction_codes()`" in matrix
    for code in city_registry_codes:
        assert f"| {code} | municipality |" in matrix


def test_config_coverage_identity_translation_is_typed_and_round_trips() -> None:
    assert coverage_identity_for_config_identity(("state", "LA")) == ("state", "LA")
    assert coverage_identity_for_config_identity(("municipality", "LA")) == (
        "municipality",
        "CA_LOS_ANGELES",
    )
    assert config_identity_for_coverage_identity(("municipality", "CA_SAN_FRANCISCO")) == (
        "municipality",
        "SF",
    )
    assert config_identity_for_coverage_identity(("state", "LA")) == ("state", "LA")

    synthetic_registry = CoverageRegistry.model_validate(
        {
            "identity_translations": [
                {
                    "geographic_subject": {
                        "domain": "geographic_subject",
                        "kind": "municipality",
                        "value": "ZZ_TEST_CITY",
                    },
                    "acquisition_scope": {
                        "domain": "acquisition_scope",
                        "kind": "municipality",
                        "value": "TEST",
                    },
                }
            ],
            "rows": [
                _row_payload(
                    jurisdiction_code="ZZ_TEST_CITY",
                    name="Synthetic Test City",
                    jurisdiction_type="municipality",
                    parent_jurisdiction_code="ZZ",
                    municipal_audit_decision="independent_target",
                )
            ],
        }
    )
    assert coverage_identity_for_config_identity(
        ("municipality", "TEST"),
        registry=synthetic_registry,
    ) == ("municipality", "ZZ_TEST_CITY")
    assert config_identity_for_coverage_identity(
        ("municipality", "ZZ_TEST_CITY"),
        registry=synthetic_registry,
    ) == ("municipality", "TEST")
    assert not hasattr(render_summary, "_CITY_CONFIG_TO_REGISTRY_IDENTITY")


@pytest.mark.parametrize(
    "unsafe_identity",
    (
        ("municipality", "06037"),
        ("municipality", "06075"),
        ("county", "06037"),
    ),
)
def test_config_coverage_identity_translation_refuses_county_shaped_fips(
    unsafe_identity: tuple[str, str],
) -> None:
    with pytest.raises(KeyError):
        coverage_identity_for_config_identity(unsafe_identity)


def test_city_membership_identity_bridge_refuses_supported_config_without_mapping() -> None:
    with pytest.raises(ValueError, match="Missing coverage-registry identity bridge"):
        _derive_implemented_city_jurisdiction_codes(
            configured_city_codes={"TEST_CITY"},
            supported_city_codes=("TEST_CITY",),
        )


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


def test_render_summary_supports_every_geographic_kind_and_named_other_authority() -> None:
    rows: list[dict[str, object]] = []
    for geographic_kind in (
        "federal",
        "state",
        "county",
        "school_district",
        "special_district",
    ):
        row = _row_payload(
            jurisdiction_code=f"SYNTH_{geographic_kind.upper()}",
            name=f"Synthetic {geographic_kind}",
            jurisdiction_type=geographic_kind,
        )
        row["authority_relation"] = {
            "relation": "independent",
            "authority": {
                "kind": geographic_kind,
                "code": row["jurisdiction_code"],
            },
        }
        rows.append(row)

    municipality = _row_payload(
        jurisdiction_code="SYNTH_MUNICIPALITY",
        name="Synthetic municipality",
        jurisdiction_type="municipality",
        parent_jurisdiction_code="SYNTH_STATE",
        municipal_audit_decision="independent_target",
    )
    municipality["authority_relation"] = {
        "relation": "independent",
        "authority": {"kind": "municipality", "code": "SYNTH_MUNICIPALITY"},
    }
    rows.append(municipality)

    named_other = _row_payload(
        jurisdiction_code="SYNTH_NAMED_OTHER_SUBJECT",
        name="Synthetic named-other subject",
        jurisdiction_type="special_district",
    )
    named_other["authority_relation"] = {
        "relation": "independent",
        "authority": {
            "kind": "named_other",
            "code": "SYNTH_ETHICS_BOARD",
            "name": "Synthetic Ethics Board",
        },
    }
    rows.append(named_other)

    markdown = render_summary_markdown(_registry_from_rows(*rows), publication_date="2026-08-28")

    assert "## County Layer" in markdown
    assert "## Municipality Layer" in markdown
    assert "## School District Layer" in markdown
    assert "## Special District Layer" in markdown
    assert "named_other/SYNTH_ETHICS_BOARD (Synthetic Ethics Board)" in markdown
    assert "| SYNTH_COUNTY | independent |" in markdown


def test_derived_summary_shows_accepted_overlaps_and_legacy_compatibility() -> None:
    markdown = render_summary_markdown(load_registry(DEFAULT_REGISTRY_PATH))

    assert (
        "| NY_NEW_YORK | NY | partitioned_overlapping | independent_target | "
        "state/NY, municipality/NY_NEW_YORK | implemented but unproven |" in markdown
    )
    assert (
        "| Jurisdiction | Authority Relation | Filing Authority | Tier | Best Cadence | Runner Wired | Source Count |"
        in markdown
    )
    assert "| CA | unresolved | state/CA | launch-support candidate | daily | yes | 2 |" in markdown
    assert "| OH | unresolved | state/OH | deferred/blocked | annual | no | 2 |" in markdown
    assert (
        "| WA_SEATTLE | WA | partitioned_overlapping | covered_by_parent | "
        "state/WA, named_other/WA_SEATTLE_CITY_CLERK (Seattle City Clerk), "
        "named_other/WA_SEEC (Seattle Ethics and Elections Commission) | launch-support candidate |" in markdown
    )


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

    # Municipality table keeps compatibility separate from the typed relation.
    assert "| Parent |" in markdown
    assert "| Authority Relation | Compatibility Decision |" in markdown
    assert "| covered_by_parent |" in markdown
    assert "| independent_target |" in markdown


def test_render_summary_supports_non_municipality_local_rows() -> None:
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

    markdown = render_summary_markdown(registry)

    assert "## County Layer" in markdown
    assert "| HENNEPIN | unresolved | county/HENNEPIN | freshness-limited | weekly | 1 |" in markdown


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
        "| Queue Group | Jurisdiction | Type | Runner Wired | Authority Relation | Compatibility Decision | "
        "Best Cadence | Next Action |" in publication.queue_markdown
    )
    assert queue_lines[0].startswith("| launch-support candidate")
    assert "| CA | state | yes | unresolved | not_applicable | daily | Run CA proof |" in queue_lines[0]
    assert queue_lines[1].startswith("| freshness-limited")
    assert (
        "| MN_MINNEAPOLIS | municipality | no | unresolved | independent_target | quarterly | "
        "Investigate city source |" in queue_lines[1]
    )
    assert queue_lines[2].startswith("| deferred/blocked")
    assert "| OH | state | no | unresolved | not_applicable | annual | Fix portal access |" in queue_lines[2]
    assert "Date: 2026-03-25" in publication.queue_markdown
    assert "Date: 2026-03-25" in publication.matrix_markdown
    authority_note = "Filing-authority decision source of truth: `docs/reference/research/coverage-registry.json`."
    assert authority_note in publication.summary_markdown
    assert authority_note in publication.queue_markdown
    assert authority_note in publication.matrix_markdown
    assert (
        "| CA | state | unresolved | launch-support candidate | daily | yes | Run CA proof |"
        in publication.matrix_markdown
    )
    assert (
        "| OH | state | unresolved | deferred/blocked | annual | no | Fix portal access |"
        in publication.matrix_markdown
    )
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
    assert "| CA | state | unresolved | launch-support candidate | daily | yes | Run CA proof |" in matrix_markdown
    assert (
        "| FL | state | unresolved | implemented but unproven | daily | yes | "
        "Run live FL refresh and verify CGI export path in production runbook. |" in matrix_markdown
    )


def test_main_publishes_non_municipality_local_registry_rows(tmp_path: Path) -> None:
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

    assert exit_code == 0
    assert "## County Layer" in summary_output.read_text(encoding="utf-8")
    assert "| HENNEPIN | county |" in queue_output.read_text(encoding="utf-8")
    assert matrix_output.exists()


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


def test_merge_seed_registry_preserves_typed_relation_and_identity_translation() -> None:
    existing_payload = _row_payload(
        jurisdiction_code="FL",
        name="Florida",
        source_names=["Old FL Source"],
    )
    existing_payload["authority_relation"] = {
        "relation": "independent",
        "authority": {"kind": "state", "code": "FL"},
    }
    existing_registry = CoverageRegistry.model_validate(
        {
            "identity_translations": [
                {
                    "geographic_subject": {
                        "domain": "geographic_subject",
                        "kind": "state",
                        "value": "FL",
                    },
                    "acquisition_scope": {
                        "domain": "acquisition_scope",
                        "kind": "state",
                        "value": "FL",
                    },
                }
            ],
            "rows": [existing_payload],
        }
    )
    seeded_registry = _registry_from_rows(
        _row_payload(
            jurisdiction_code="FL",
            name="Florida",
            source_names=["New FL Source"],
        )
    )

    merged = merge_seed_registry(existing_registry, seeded_registry)

    assert merged.rows[0].authority_relation.relation == "independent"
    assert merged.identity_translations == existing_registry.identity_translations


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
    assert "FAIL: row 'MN_MINNEAPOLIS': covered_by_parent municipality" in captured.out
    assert "Validation summary: checked=2" in captured.out
