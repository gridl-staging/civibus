from __future__ import annotations

from collections.abc import Collection, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


PROJECTED_PUBLIC_CONTRACT_NODE_ID = (
    "tests/test_debbie_projected_public_contract.py"
    "::test_projected_current_public_unit_selection_failures_are_classified"
)


class PublicMirrorCategory(StrEnum):
    PRODUCT_RUNTIME = "product_runtime"
    DEV_REPO_ONLY = "dev_repo_only"


class PublicMirrorTestClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    category: PublicMirrorCategory
    private_asset: str | None = None
    owner: str | None = None

    @field_validator("node_id")
    @classmethod
    def _require_node_id(cls, value: str) -> str:
        if "::" not in value:
            raise ValueError("node_id must be an exact pytest node id")
        return _require_non_blank(value)

    @field_validator("private_asset", "owner")
    @classmethod
    def _require_optional_non_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_blank(value)

    @model_validator(mode="after")
    def _require_private_metadata_for_dev_repo_only(self) -> PublicMirrorTestClassification:
        if self.category == PublicMirrorCategory.DEV_REPO_ONLY:
            if self.private_asset is None or self.owner is None:
                raise ValueError("dev_repo_only entries require private_asset and owner")
            return self
        if self.private_asset is not None or self.owner is not None:
            raise ValueError("product_runtime entries must not carry private metadata")
        return self


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _entries(
    *,
    private_asset: str,
    owner: str,
    node_ids: tuple[str, ...],
) -> tuple[PublicMirrorTestClassification, ...]:
    return tuple(
        PublicMirrorTestClassification(
            node_id=node_id,
            category=PublicMirrorCategory.DEV_REPO_ONLY,
            private_asset=private_asset,
            owner=owner,
        )
        for node_id in node_ids
    )


PUBLIC_MIRROR_TEST_CLASSIFICATIONS: tuple[PublicMirrorTestClassification, ...] = (
    *_entries(
        private_asset="private rendered coverage research artifacts under docs/reference/research/",
        owner="coverage research snapshot contracts",
        node_ids=(
            "domains/campaign_finance/coverage/test_lifecycle.py::test_current_lifecycle_summary_snapshot_matches_rendered_output",
            "domains/campaign_finance/coverage/test_registry_snapshot.py::test_stage3_probe_artifact_keeps_corrected_arizona_entrypoint",
            "domains/campaign_finance/coverage/test_registry_snapshot.py::test_stage5_census_artifact_excludes_non_incorporated_cdps",
            "domains/campaign_finance/coverage/test_registry_snapshot.py::test_render_outputs_match_committed_markdown_artifacts",
            "tests/test_stage5_cross_state_validation.py::test_stage5_in_verdict_is_launch_ready_in_registry_and_matrix",
        ),
    ),
    *_entries(
        # `tests/` syncs as a whole directory, but `scripts/` is a file allowlist and
        # `chats/icg/` never syncs at all. Without this the public mirror would carry
        # a test importing a script that is not there, scanning a corpus that is not
        # there. The checker is a dev-repo authoring tool by design.
        private_asset="chats/icg/ and scripts/lane_authoring_hazard_checker.py",
        owner="Lane-authoring hazard checker corpus",
        node_ids=(
            "tests/ci/test_lane_authoring_hazard_checker.py::test_clean_fixture_reports_no_findings",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_dirty_fixture_reports_exactly_the_three_expected_findings",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_prose_mentioning_the_env_var_does_not_clear_a_file",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_fenced_assignment_does_clear_a_file",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_named_test_file_targets_are_refined_out_but_still_counted_strictly",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_directory_level_pytest_target_is_a_refined_hit",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_zsh_word_splitting_fixture_reports_concrete_shell_hazard",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_grep_ended_pipeline_fixture_reports_concrete_shell_hazard",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_head_ended_pipeline_fixture_reports_concrete_shell_hazard",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_tail_ended_pipeline_fixture_reports_concrete_shell_hazard",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_tee_logging_pipeline_reports_no_shell_findings",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_grep_q_assertion_pipeline_reports_no_shell_findings",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_pipefail_pipeline_reports_no_shell_findings",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_pipestatus_pipeline_reports_no_shell_findings",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_repeated_preamble_constraint_with_different_wrapping_is_not_a_loss",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_missing_repeated_preamble_constraint_still_reports_loss",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_partially_repeated_wrapped_preamble_constraint_still_reports_loss",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_newly_introduced_hazard_reds_the_ratchet",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_modified_grandfathered_file_with_unchanged_findings_stays_green",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_zero_changed_files_path_still_checks_the_baseline",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_changed_checklist_paths_include_untracked_scratch_lanes",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_file_without_a_stages_heading_is_not_a_direct_mode_hit",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_slice_boundary_matches_direct_mode_semantics",
            "tests/ci/test_lane_authoring_hazard_checker.py::test_checker_runs_over_the_real_corpus_with_ratchet_semantics",
        ),
    ),
    *_entries(
        private_asset=".debbie.toml",
        owner="Debbie projection contract",
        node_ids=(
            "tests/test_donor_er_scale_spike.py::test_debbie_projection_includes_harness_script_and_tests_mirror",
            "tests/ci/test_api_dockerfile_contract.py::test_debbie_sync_includes_api_dockerfile_root_inputs",
            "tests/ci/test_refresh_cron_scripts_contract.py::test_debbie_sync_keeps_evidence_and_findings_private_by_default",
        ),
    ),
    *_entries(
        private_asset="docs/howto/operations/db-backup-runbook.md and Fly backup baseline evidence",
        owner="Fly backup and restore operations docs",
        node_ids=(
            "tests/ci/test_backup_restore_scripts_contract.py::test_db_backup_runbook_uses_current_fly_growth_floor_baseline",
            "tests/ci/test_refresh_cron_scripts_contract.py::test_db_backup_runbook_retains_throwaway_restore_contract",
        ),
    ),
    *_entries(
        private_asset="docs/howto/operations/fly_deployment_runbook.md",
        owner="Fly deployment operations docs",
        node_ids=(
            "tests/ci/test_deployed_surface_parity_contract.py::test_fly_runbook_documents_deployed_surface_parity_probe",
        ),
    ),
    *_entries(
        private_asset="private Fly ops docs and ledgers: ROADMAP.md, PROJECT_OVERVIEW.md, docs/live-state/",
        owner="Fly ops documentation and private open-work ledger",
        node_ids=(
            "tests/ci/test_fly_ops_docs_contract.py::test_fly_runbook_documents_current_refresh_machine_model",
            "tests/ci/test_fly_ops_docs_contract.py::test_fly_runbook_documents_current_deploy_workflow_model",
            "tests/ci/test_fly_ops_docs_contract.py::test_fly_runbook_password_guidance_points_to_pgpass_owners",
            "tests/ci/test_fly_ops_docs_contract.py::test_stage_owned_runnable_docs_do_not_publish_password_prefix_commands",
            "tests/ci/test_fly_ops_docs_contract.py::test_roadmap_tracks_only_unresolved_stage4_and_rotation_work",
            "tests/ci/test_fly_ops_docs_contract.py::test_scheduler_boundary_red_keeps_weekly_refresh_recheck_open",
            "tests/ci/test_fly_ops_docs_contract.py::test_project_overview_current_scope_matches_implemented_fly_refresh_model",
        ),
    ),
    *_entries(
        private_asset="private single-deploy recovery receipt under docs/live-state/",
        owner="single deploy recovery receipt contract",
        node_ids=(
            "tests/ci/test_single_deploy_receipt_contract.py::test_single_deploy_receipt_contains_fail_closed_recovery_chain",
        ),
    ),
    *_entries(
        private_asset="private July 30 single-deploy receipt under docs/live-state/",
        owner="single deploy recovery receipt contract",
        node_ids=(
            "tests/ci/test_single_deploy_receipt_contract.py::test_july_30_single_deploy_receipt_preserves_gated_chain_and_red_findings",
            "tests/ci/test_single_deploy_receipt_contract.py::test_july_30_receipt_guard_fails_when_db_probe_command_is_not_executable",
            "tests/ci/test_single_deploy_receipt_contract.py::test_july_30_receipt_guard_fails_when_secret_source_path_is_relative",
            "tests/ci/test_single_deploy_receipt_contract.py::test_july_30_receipt_guard_fails_when_db_proxy_readiness_wait_is_unbounded",
            "tests/ci/test_single_deploy_receipt_contract.py::test_july_30_receipt_guard_fails_when_db_probe_output_includes_impossible_proxy_lines",
            "tests/ci/test_single_deploy_receipt_contract.py::test_july_30_receipt_guard_fails_when_roadmap_disposition_overclaims",
        ),
    ),
    *_entries(
        private_asset="ROADMAP.md",
        owner="single deploy recovery receipt contract",
        node_ids=(
            "tests/ci/test_single_deploy_receipt_contract.py::test_roadmap_closes_only_authorized_single_deploy_rows",
            "tests/ci/test_single_deploy_receipt_contract.py::test_roadmap_guard_fails_when_extra_row_closes_on_single_deploy_date",
        ),
    ),
    *_entries(
        private_asset="private status docs: ROADMAP.md, .scrai/overview.md, CLAUDE.md, AGENTS.md",
        owner="backup status documentation contract",
        node_ids=(
            "tests/ci/test_refresh_cron_scripts_contract.py::test_backup_status_docs_keep_shipped_language_and_forbidden_slug_out",
        ),
    ),
    *_entries(
        private_asset="layers.yaml",
        owner="Keel layer metadata",
        node_ids=(
            "tests/ci/test_refresh_cron_scripts_contract.py::test_keel_gate_eligibility_is_derived_from_layers_metadata",
            "tests/keel/test_phase1_evidence_infrastructure.py::test_layers_yaml_declares_landed_layers_in_order_with_honest_statuses",
            "tests/keel/test_keel_summary.py::test_collect_layer_summaries_includes_all_layers_from_live_yaml",
            "tests/keel/test_keel_summary.py::test_collect_layer_summaries_l12_short_circuits_session_summary",
            "tests/keel/test_keel_summary.py::test_layer_summary_dataclass_shape",
        ),
    ),
    *_entries(
        private_asset="private detached-load docs under docs/howto/operations/, chats/, and ROADMAP.md",
        owner="detached load documentation contract",
        node_ids=(
            "tests/infra/test_detached_load_documentation.py::test_detached_load_docs_use_one_canonical_runner_contract",
            "tests/infra/test_detached_load_documentation.py::test_changed_detached_load_doc_links_resolve",
        ),
    ),
    *_entries(
        private_asset="docs/reference/keel/ and Keel evidence schemas",
        owner="Keel framework documentation and schema contracts",
        node_ids=(
            "tests/keel/test_casual_doc.py::test_casual_md_exists",
            "tests/keel/test_casual_doc.py::test_casual_md_under_250_lines",
            "tests/keel/test_casual_doc.py::test_casual_md_has_all_seven_numbered_sections",
            "tests/keel/test_casual_doc.py::test_casual_md_cross_link_integrity",
            "tests/keel/test_casual_doc.py::test_casual_md_does_not_reference_strict_only_artifacts",
            "tests/keel/test_casual_doc.py::test_casual_md_cross_links_to_enforcement_md",
            "tests/keel/test_casual_mode_doc_updates.py::test_checklist_references_casual_md",
            "tests/keel/test_casual_mode_doc_updates.py::test_checklist_parking_lot_names_activation_lane",
            "tests/keel/test_casual_mode_doc_updates.py::test_roadmap_has_casual_mode_section",
            "tests/keel/test_casual_mode_doc_updates.py::test_roadmap_references_casual_md",
            "tests/keel/test_casual_mode_doc_updates.py::test_checklist_session_log_has_today_entry",
            "tests/keel/test_judge_prompt_scaffold.py::test_repo_portal_investigation_prompt_pair_loads_with_shared_schema",
            "tests/keel/test_judge_prompt_scaffold.py::test_repo_editorial_prompt_pair_loads_with_shared_schema",
            "tests/keel/test_judge_prompt_scaffold.py::test_repo_coverage_prompt_pair_loads_with_shared_schema",
            "tests/keel/test_judge_prompt_scaffold.py::test_repo_er_threshold_prompt_pair_loads_with_shared_schema",
            "tests/keel/test_matt_stage_close_hook.py::test_matt_stage_close_hook_runs_gate_from_repo_root",
            "tests/keel/test_matt_stage_close_hook.py::test_matt_stage_close_hook_prefers_matt_project_dir_when_present",
            "tests/keel/test_phase1_evidence_infrastructure.py::test_phase1_layer_schemas_exist_and_validate_as_json_schema",
            "tests/keel/test_two_modes_crosslinks.py::test_readme_has_two_modes_section_heading",
            "tests/keel/test_two_modes_crosslinks.py::test_readme_names_both_modes",
            "tests/keel/test_two_modes_crosslinks.py::test_casual_md_forward_link_to_enforcement",
            "tests/keel/test_two_modes_crosslinks.py::test_enforcement_md_back_link_to_casual",
        ),
    ),
    *_entries(
        private_asset="evidence/ and docs/reference/anchors/",
        owner="Keel L1 anchor and emitted-evidence contracts",
        node_ids=(
            "tests/keel/test_gate_l1.py::test_nc_anchor_keeps_ie_filing_index_non_primary_and_contribution_total_primary",
            "tests/keel/test_gate_l1.py::test_load_anchor_file_parses_committed_federal_anchor",
            "tests/keel/test_gate_l1.py::test_repo_audited_anchor_files_are_schema_valid",
            "tests/keel/test_phase1_evidence_infrastructure.py::test_phase1_evidence_dir_exists",
            "tests/keel/test_sources_registry.py::test_sources_registry_evidence_refs_point_to_real_matching_artifacts",
        ),
    ),
    *_entries(
        private_asset="sources.yaml, layers.yaml, and Keel L3 emitted evidence",
        owner="Keel source registry contracts",
        node_ids=(
            "tests/keel/test_gate_l3.py::test_repo_sources_registry_registers_federal_chartered_sources",
            "tests/keel/test_gate_l3.py::test_repo_sources_registry_passes_current_nc_roster_state_mix_contract",
            "tests/keel/test_gate_l3.py::test_repo_sources_registry_passes_current_phl_deferred_contract",
            "tests/keel/test_gate_l3.py::test_repo_sources_registry_ca_emits_single_expected_l3_artifact",
            "tests/keel/test_gate_l3.py::test_repo_sources_registry_passes_stage1_minimal_in_mn_nj_contract[IN-in_ied_bulk_exports-prototyped-required_docs_scopes0]",
            "tests/keel/test_gate_l3.py::test_repo_sources_registry_passes_stage1_minimal_in_mn_nj_contract[MN-mn_cfb_bulk_exports-deferred-required_docs_scopes1]",
            "tests/keel/test_gate_l3.py::test_repo_sources_registry_passes_stage1_minimal_in_mn_nj_contract[NJ-nj_elec_contribution_exports-deferred-required_docs_scopes2]",
        ),
    ),
    *_entries(
        private_asset="keel_reviews.yaml and private review prompt docs",
        owner="Keel review schedule",
        node_ids=(
            "tests/keel/test_review_schedule.py::test_repo_owned_review_schedule_loads_and_lists_calibration_and_escalation",
            "tests/keel/test_review_schedule.py::test_review_schedule_carries_canonical_thresholds",
            "tests/keel/test_review_schedule.py::test_review_prompts_cite_yaml_threshold_fields_by_name",
        ),
    ),
    *_entries(
        private_asset=".debbie/post-sync.sh",
        owner="Debbie post-sync hook",
        node_ids=(
            "tests/test_debbie_post_sync_hook.py::test_projected_public_mirror_is_ruff_format_clean",
            "tests/test_debbie_post_sync_hook.py::test_post_sync_formats_only_debbie_target_root",
            "tests/test_debbie_post_sync_hook.py::test_projected_public_mirror_post_sync_is_idempotent",
            "tests/test_debbie_post_sync_hook.py::test_projected_public_mirror_make_lint_passes",
            "tests/test_debbie_post_sync_hook.py::test_post_sync_removes_todo_scaffolds_when_strip_is_noop",
            "tests/test_debbie_post_sync_hook.py::test_post_sync_uses_repo_virtualenv_python_when_python3_fails",
            PROJECTED_PUBLIC_CONTRACT_NODE_ID,
            "tests/test_debbie_post_sync_hook.py::test_projected_public_gate_matches_canonical_public_eligible_nodes",
        ),
    ),
    *_entries(
        private_asset="private repository docs outside the public projection",
        owner="documentation system contracts",
        node_ids=(
            "tests/test_doc_system_v2_layout.py::test_decisions_are_root_owned_with_frontmatter_and_line_budget",
            "tests/test_doc_system_v2_layout.py::test_docs_top_level_uses_only_v2_quadrants",
            "tests/test_doc_system_v2_layout.py::test_protocols_routes_resolve_to_v2_owners",
            "tests/test_stage1_fec_schedule_b_source_contract.py::TestDocumentationHygiene::test_research_doc_oppexp_fields_match_schedule_b_columns",
            "tests/test_stage1_fec_schedule_e_format_outputs.py::test_schedule_e_research_docs_stay_empirical_and_cross_referenced",
            "tests/test_stage1_phl_full_backfill_closeout_doc_contract.py::test_stage1_phl_closeout_pins_exact_probe_command_shape_and_prior_facts",
            "tests/test_stage1_phl_full_backfill_closeout_doc_contract.py::test_stage3_failure_evidence_section_present",
            "tests/test_stage1_phl_full_backfill_closeout_doc_contract.py::test_stage3_rerun_detached_probe_section_present",
            "tests/test_stage3_research_regressions.py::test_georgia_legal_access_section_records_tos_status_and_prohibition_findings",
            "tests/test_stage3_research_regressions.py::test_colorado_legal_access_section_records_fee_and_permission_constraints",
            "tests/test_stage3_research_regressions.py::test_colorado_scraping_guidance_records_blocking_and_capacity_controls",
            "tests/test_stage3_research_regressions.py::test_state_ie_audit_machine_readable_block_tracks_scope_and_ranking_contract",
            "tests/test_stage5_schedule_e_closeout_docs.py::test_stage5_docs_closeout_contract",
        ),
    ),
    *_entries(
        private_asset="eval/ graph database experiment scripts",
        owner="legacy graph evaluation contract",
        node_ids=("tests/test_stage1_infrastructure.py::test_graph_eval_script_targets_current_database_container",),
    ),
    *_entries(
        private_asset="parked state/city pipeline test trees",
        owner="parked-jurisdiction quarantine contract",
        node_ids=("tests/test_parked_suite_exclusion.py::test_escape_hatch_restores_parked_collection",),
    ),
)


def validate_public_mirror_classifications(
    entries: tuple[PublicMirrorTestClassification, ...] = PUBLIC_MIRROR_TEST_CLASSIFICATIONS,
) -> tuple[PublicMirrorTestClassification, ...]:
    node_ids = [entry.node_id for entry in entries]
    duplicates = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate public mirror classification node IDs: {duplicates}")
    return entries


DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID = {
    entry.node_id: entry
    for entry in validate_public_mirror_classifications()
    if entry.category == PublicMirrorCategory.DEV_REPO_ONLY
}


def expected_dev_repo_only_failure_nodes(selected_node_ids: Collection[str]) -> set[str]:
    """Return classified dev-repo-only failures reachable through a selection."""
    return set(selected_node_ids) & DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID.keys()


# Non-collapse floors for the public-eligible pytest selection.
#
# These are FLOORS, deliberately not equalities. They exist to catch a collapse —
# a broken `-m` selector, a swallowed collection error, a mis-scoped `.debbie.toml`
# projection — that reduces the canonical and projected node sets by the SAME
# amount and therefore slips past the exact `canonical == projected` clause.
#
# They were exact equalities until 2026-07-29. That made every merge that added a
# public-eligible test fail post-merge validation until a human hand-bumped the
# literal: 19 of the 49 commits touching this module and its consumer between
# 2026-07-24 and 2026-07-29 were pure ratchet bumps (3336 -> 3346 -> 3363 -> 3403),
# and with N parallel test-adding lanes the second lane to merge was stale again.
# Adding tests must never require editing these numbers. Deliberately REMOVING
# enough tests to cross a floor should require a deliberate edit here, which is
# the behaviour an equality was standing in for.
MINIMUM_PUBLIC_ELIGIBLE_NODE_TOTAL = 3403
MINIMUM_PUBLIC_NODE_PREFIX_TOTALS = {"api/": 263, "core/": 688, "domains/": 1748, "tests/": 700}


def evaluate_public_node_expectations(
    canonical_nodes: Collection[str],
    projected_nodes: Collection[str],
    *,
    minimum_total: int = MINIMUM_PUBLIC_ELIGIBLE_NODE_TOTAL,
    minimum_prefix_totals: Mapping[str, int] = MINIMUM_PUBLIC_NODE_PREFIX_TOTALS,
) -> tuple[str, ...]:
    """Return violation messages for the public-mirror node expectations.

    Two independent clauses, both load-bearing:

    * **Projection fidelity** — the canonical repo and the projected public mirror
      must collect the identical node set. Exact, in both directions. This is the
      clause that proves `.debbie.toml` does not silently drop or add coverage.
    * **Non-collapse floors** — total and per-prefix counts must not fall below the
      recorded minimums. Set equality cannot see a symmetric collapse, so this is
      not redundant with the clause above.

    An empty side is reported by the floors rather than passing vacuously.

    Returns an empty tuple when every expectation holds.
    """
    canonical = set(canonical_nodes)
    projected = set(projected_nodes)
    violations: list[str] = []

    if canonical != projected:
        missing = sorted(canonical - projected)
        extra = sorted(projected - canonical)
        violations.append(
            f"public mirror projection drift: missing_from_projection={missing} extra_in_projection={extra}"
        )

    # Both sides are floored independently; a collapse confined to one side would
    # already trip the drift clause, but reporting it here keeps the diagnosis
    # pointed at the side that actually shrank.
    for label, nodes in (("canonical", canonical), ("projected", projected)):
        if len(nodes) < minimum_total:
            violations.append(f"{label} total below floor: collected {len(nodes)}, floor {minimum_total}")

    for prefix, minimum in sorted(minimum_prefix_totals.items()):
        for label, nodes in (("canonical", canonical), ("projected", projected)):
            observed = sum(1 for node_id in nodes if node_id.startswith(prefix))
            if observed < minimum:
                violations.append(f"{prefix} {label} below floor: collected {observed}, floor {minimum}")

    return tuple(violations)
