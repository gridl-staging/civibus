from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


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
        private_asset=".debbie.toml",
        owner="Debbie projection contract",
        node_ids=(
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
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_supports_non_l4_pair_with_layer_schema",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_supports_l12_pair_with_layer_summary_schema",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_supports_l11_pair_with_layer_summary_schema",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_supports_l14_pair_with_layer_summary_schema",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_non_l4_uses_primary_for_one_sided_required_fields",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_rejects_missing_required_l4_criterion",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_rejects_l4_criterion_set_with_duplicate_id",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_rejects_duplicate_skeptic_l4_criteria",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_supports_l8_threshold_review",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_rejects_missing_required_l8_criterion",
            "tests/keel/test_adversarial_pair.py::test_build_pair_run_plan_rejects_non_er_threshold_scope_for_l8",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_rejects_plan_scope_mismatch_with_verdict_scope",
            "tests/keel/test_adversarial_pair.py::test_summarize_pair_run_resolves_summary_schema_path_from_l8_layer",
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
            "tests/keel/test_gate_l11.py::test_main_writes_l11_evidence_with_explicit_owner_files",
            "tests/keel/test_gate_l13.py::test_schema_canary_validates_l13_schema_and_generated_payload",
            "tests/keel/test_gate_l14.py::test_l14_schema_civics_status_nullable_enum_uses_anyof",
            "tests/keel/test_gate_l15.py::test_write_l15_evidence_emits_schema_valid_payload",
            "tests/keel/test_gate_l8.py::test_l8_schema_round_trip_for_contract_payload",
            "tests/keel/test_gate_l8.py::test_l8_gate_writes_evidence_summary",
            "tests/keel/test_gate_l8.py::test_l8_gate_records_pair_level_results",
            "tests/keel/test_gate_l8.py::test_l8_gate_inversion_failure_surfaces_named_nc_case",
            "tests/keel/test_gate_l8.py::test_l8_gate_false_positive_summary_is_stable",
            "tests/keel/test_gate_l8.py::test_l8_gate_resolves_threshold_override_once_and_threads_to_every_classification_call",
            "tests/keel/test_gate_l8.py::test_l8_gate_threads_explicit_probabilistic_settings_only_to_person_cases",
            "tests/keel/test_gate_l9.py::test_l9_evidence_schema_round_trip_for_stage1_contract",
            "tests/keel/test_judge_prompt_scaffold.py::test_repo_portal_investigation_prompt_pair_loads_with_shared_schema",
            "tests/keel/test_judge_prompt_scaffold.py::test_repo_editorial_prompt_pair_loads_with_shared_schema",
            "tests/keel/test_judge_prompt_scaffold.py::test_repo_coverage_prompt_pair_loads_with_shared_schema",
            "tests/keel/test_judge_prompt_scaffold.py::test_repo_er_threshold_prompt_pair_loads_with_shared_schema",
            "tests/keel/test_matt_stage_close_hook.py::test_matt_stage_close_hook_runs_gate_from_repo_root",
            "tests/keel/test_matt_stage_close_hook.py::test_matt_stage_close_hook_prefers_matt_project_dir_when_present",
            "tests/keel/test_phase1_evidence_infrastructure.py::test_phase1_layer_schemas_exist_and_validate_as_json_schema",
            "tests/keel/test_phase1_evidence_infrastructure.py::test_phase1_waiver_schema_exists_and_covers_required_fields",
            "tests/keel/test_session_output.py::test_write_session_summary_emits_schema_valid_payload",
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
            "tests/keel/test_gate_l14.py::test_main_returns_non_zero_when_nc_geometry_summary_mismatches",
            "tests/keel/test_gate_l14.py::test_main_writes_l14_evidence_from_registry_lifecycle_projection",
            "tests/keel/test_gate_l14.py::test_main_reads_roster_sources_from_selected_repo_root",
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
            "tests/keel/test_gate_l3.py::test_emitted_deferred_l3_evidence_validates_against_real_repo_schema",
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
            "tests/test_debbie_post_sync_hook.py::test_projected_current_public_unit_selection_failures_are_classified",
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
