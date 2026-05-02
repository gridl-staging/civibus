from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
ENV_LIB_PATH = SCRIPTS_DIR / "env_lib.sh"
PRIORITY_WRAPPER_PATH = SCRIPTS_DIR / "refresh_priority.sh"
FEC_BULK_WRAPPER_PATH = SCRIPTS_DIR / "refresh_fec_bulk.sh"
KEEL_GATES_WRAPPER_PATH = SCRIPTS_DIR / "run_keel_gates.sh"
NC_ORCHESTRATOR_WRAPPER_PATH = SCRIPTS_DIR / "refresh_nc_orchestrator.sh"
ENV_PROD_EXAMPLE_PATH = REPO_ROOT / ".env.production.example"
INSTALLER_PATH = SCRIPTS_DIR / "install_refresh_cron.sh"
LOGROTATE_CONFIG_PATH = SCRIPTS_DIR / "civibus-refresh-logrotate.conf"
REFRESH_RUNBOOK_PATH = REPO_ROOT / "docs/operations/campaign-finance-refresh.md"
DB_BACKUP_RUNBOOK_PATH = REPO_ROOT / "docs/operations/db-backup-runbook.md"
ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"
SCAI_OVERVIEW_PATH = REPO_ROOT / ".scrai/overview.md"
CLAUDE_GUIDE_PATH = REPO_ROOT / "CLAUDE.md"
AGENTS_GUIDE_PATH = REPO_ROOT / "AGENTS.md"
CERT_EXPIRY_WRAPPER_PATH = SCRIPTS_DIR / "check_cert_expiry.sh"
IN_FRESHNESS_POLLER_PATH = SCRIPTS_DIR / "poll_in_freshness.sh"
LAYERS_PATH = REPO_ROOT / "layers.yaml"
DEBBIE_CONFIG_PATH = REPO_ROOT / ".debbie.toml"

_WRAPPER_FORBIDDEN_FRAGMENTS = (
    "docker compose",
    "python -m core.refresh.runner",
    "python -m domains.campaign_finance.ingest.bulk_cli",
    "psql ",
    "curl ",
    "run_fec_refresh",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_required_text(path: Path, missing_message: str) -> str:
    assert path.is_file(), missing_message
    return _read_text(path)


def _read_required_layers() -> list[dict[str, object]]:
    layers_text = _read_required_text(
        LAYERS_PATH,
        "layers.yaml must exist",
    )
    payload = yaml.safe_load(layers_text)
    layers = payload.get("layers")
    assert isinstance(layers, list), "layers.yaml must define a top-level layers list"
    return layers


def _is_unattended_global_gate(layer: dict[str, object]) -> bool:
    gate_command = str(layer.get("gate_command", "")).strip()
    gate_command_parts = gate_command.split()
    return (
        layer.get("status") in {"piloted", "enforced"}
        and layer.get("scope") == "global"
        and len(gate_command_parts) == 2
        and gate_command_parts[0] == "make"
        and gate_command_parts[1].startswith("gate-")
    )


# ---------- env_lib.sh shared library contract ----------


def test_env_lib_contains_shared_env_loading_contract() -> None:
    """env_lib.sh must contain the shared .env parsing and common env setup."""
    lib_text = _read_required_text(
        ENV_LIB_PATH,
        "infra/scripts/env_lib.sh must exist — shared .env loading library",
    )

    # Core parser function
    assert "load_env_assignments() {" in lib_text
    assert 'while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do' in lib_text
    assert "Invalid .env assignment: ${raw_line}" in lib_text
    assert "Load literal KEY=VALUE pairs without executing shell syntax from .env." in lib_text

    # Convenience wrapper that sets common exports
    assert "load_civibus_env() {" in lib_text
    assert "Missing required env file:" in lib_text
    assert 'export PATH="${HOME}/.local/bin:${PATH}"' in lib_text
    assert "POSTGRES_PASSWORD must be set" in lib_text
    assert 'export POSTGRES_HOST="127.0.0.1"' in lib_text
    assert 'export POSTGRES_PORT="5432"' in lib_text
    # System CA bundle for government site SSL chains
    assert "SSL_CERT_FILE" in lib_text

    # Must NOT execute .env via bash source
    assert 'source "${env_file}"' not in lib_text


# ---------- common wrapper contract ----------


def _assert_common_wrapper_contract(script_text: str) -> None:
    """Verify each wrapper sources env_lib.sh and delegates env loading."""
    assert "set -euo pipefail" in script_text
    assert 'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in script_text
    assert 'repo_root="$(cd "${script_dir}/../.." && pwd)"' in script_text

    # Must source the shared library, not inline the parser
    assert 'source "${script_dir}/env_lib.sh"' in script_text
    assert "load_civibus_env" in script_text

    # Must NOT duplicate the parser inline
    assert "load_env_assignments() {" not in script_text

    assert 'cd "${repo_root}"' in script_text

    for fragment in _WRAPPER_FORBIDDEN_FRAGMENTS:
        assert fragment not in script_text


def _read_wrapper_text(path: Path, missing_message: str) -> str:
    script_text = _read_required_text(path, missing_message)
    _assert_common_wrapper_contract(script_text)
    return script_text


def _extract_managed_cron_line(installer_text: str, line_marker: str) -> str:
    for line in installer_text.splitlines():
        stripped = line.strip()
        if stripped.startswith('echo "') and line_marker in stripped:
            return stripped.removeprefix('echo "').removesuffix('"')
    assert False, f"Managed cron entry for {line_marker} must exist in installer"


def _extract_runbook_cron_line(runbook_text: str, wrapper_fragment: str) -> str:
    for line in runbook_text.splitlines():
        stripped = line.strip()
        if wrapper_fragment in stripped and " >> /var/log/civibus/" in stripped:
            return stripped
    assert False, f"Runbook cron entry for {wrapper_fragment} must exist"


# ---------- individual wrapper tests ----------


def test_priority_wrapper_is_thin_make_wrapper_with_required_overrides() -> None:
    priority_script_text = _read_wrapper_text(
        PRIORITY_WRAPPER_PATH,
        "infra/scripts/refresh_priority.sh must exist",
    )

    assert 'refresh_cf_args=""' in priority_script_text
    assert 'if [[ -n "${NC_COMMITTEE_DOCS_PATH:-}" ]]; then' in priority_script_text
    assert 'resolved_nc_committee_docs_path="${NC_COMMITTEE_DOCS_PATH}"' in priority_script_text
    assert 'resolved_nc_committee_docs_path="${repo_root}/${resolved_nc_committee_docs_path}"' in priority_script_text
    assert "NC_COMMITTEE_DOCS_PATH does not exist: ${resolved_nc_committee_docs_path}" in priority_script_text
    assert "NC_COMMITTEE_DOCS_PATH must be set in .env or the shell environment" not in priority_script_text
    assert "make refresh-cf-priority" in priority_script_text
    assert "REFRESH_CF_ARGS=" in priority_script_text
    assert "printf -v refresh_cf_args '%q '" in priority_script_text
    assert "--nc-committee-docs-path" in priority_script_text
    assert "--candidate-listing-path" in priority_script_text
    assert "NC_CANDIDATE_LISTING_PATH" in priority_script_text
    assert "CIVICS_YEAR_FROM" in priority_script_text
    assert "--year-from" in priority_script_text
    assert "--dry-run" not in priority_script_text
    assert "--force" not in priority_script_text
    # CO SSL break-glass env var is wrapper-specific, not shared
    assert "CIVIBUS_ALLOW_INSECURE_TLS_RETRY" in priority_script_text


def test_fec_bulk_wrapper_downloads_before_ingest_with_vm_directory_override() -> None:
    fec_bulk_script_text = _read_wrapper_text(
        FEC_BULK_WRAPPER_PATH,
        "infra/scripts/refresh_fec_bulk.sh must exist",
    )

    assert "FEC_BULK_CYCLE must be set in .env or the shell environment" in fec_bulk_script_text
    assert "FEC_BULK_DIR" in fec_bulk_script_text
    assert "/var/lib/civibus/fec/bulk" in fec_bulk_script_text
    assert "2024" not in fec_bulk_script_text
    assert "make download-fec-bulk" in fec_bulk_script_text
    assert "make ingest-fec-bulk" in fec_bulk_script_text
    assert fec_bulk_script_text.index("make download-fec-bulk") < fec_bulk_script_text.index("make ingest-fec-bulk")


def test_nc_orchestrator_wrapper_delegates_to_nc_cli_with_rolling_window() -> None:
    nc_orchestrator_script_text = _read_wrapper_text(
        NC_ORCHESTRATOR_WRAPPER_PATH,
        "infra/scripts/refresh_nc_orchestrator.sh must exist",
    )

    assert "WINDOW_START" in nc_orchestrator_script_text
    assert "WINDOW_END" in nc_orchestrator_script_text
    assert "date -u" in nc_orchestrator_script_text
    assert "--data-type transactions" in nc_orchestrator_script_text
    assert "--orchestrate-committees" in nc_orchestrator_script_text
    assert "--window-start" in nc_orchestrator_script_text
    assert "--window-end" in nc_orchestrator_script_text
    assert "python -m domains.campaign_finance.jurisdictions.states.NC.scraper.cli" in nc_orchestrator_script_text
    assert "--download" not in nc_orchestrator_script_text


def test_env_example_mirrors_fec_bulk_wrapper_runtime_contract() -> None:
    fec_bulk_script_text = _read_required_text(
        FEC_BULK_WRAPPER_PATH,
        "infra/scripts/refresh_fec_bulk.sh must exist",
    )
    env_example_text = _read_required_text(
        ENV_PROD_EXAMPLE_PATH,
        ".env.production.example must exist",
    )

    default_dir_match = re.search(
        r'export FEC_BULK_DIR="\$\{FEC_BULK_DIR:-([^"]+)\}"',
        fec_bulk_script_text,
    )
    assert default_dir_match, "FEC_BULK_DIR default contract must be declared in wrapper"
    default_bulk_dir = default_dir_match.group(1)

    assert "FEC_BULK_CYCLE must be set in .env or the shell environment" in fec_bulk_script_text
    assert "FEC_BULK_CYCLE=" in env_example_text
    assert "# FEC_BULK_DIR=" in env_example_text
    assert default_bulk_dir in env_example_text


def test_installer_and_logrotate_are_repo_controlled_single_source_artifacts() -> None:
    installer_text = _read_required_text(
        INSTALLER_PATH,
        "infra/scripts/install_refresh_cron.sh must exist",
    )
    logrotate_text = _read_required_text(
        LOGROTATE_CONFIG_PATH,
        "infra/scripts/civibus-refresh-logrotate.conf must exist",
    )
    priority_script_text = _read_required_text(
        PRIORITY_WRAPPER_PATH,
        "infra/scripts/refresh_priority.sh must exist",
    )
    fec_bulk_script_text = _read_required_text(
        FEC_BULK_WRAPPER_PATH,
        "infra/scripts/refresh_fec_bulk.sh must exist",
    )
    nc_orchestrator_script_text = _read_required_text(
        NC_ORCHESTRATOR_WRAPPER_PATH,
        "infra/scripts/refresh_nc_orchestrator.sh must exist",
    )

    assert "0 */6 * * *" in installer_text
    assert "0 3 * * *" in installer_text
    assert "30 2 * * *" in installer_text
    assert "20 */6 * * *" in installer_text
    assert "/var/log/civibus/refresh-priority.log" in installer_text
    assert "/var/log/civibus/refresh-fec-bulk.log" in installer_text
    assert "/var/log/civibus/refresh-nc-orchestrator.log" in installer_text
    assert "/var/log/civibus/backup.log" in installer_text
    assert "/var/log/civibus/keel-gates.log" in installer_text
    assert "infra/scripts/refresh_priority.sh" in installer_text
    assert "infra/scripts/refresh_fec_bulk.sh" in installer_text
    assert "infra/scripts/refresh_nc_orchestrator.sh" in installer_text
    assert "infra/scripts/backup_to_b2.sh" in installer_text
    assert "infra/scripts/run_keel_gates.sh" in installer_text
    assert "crontab " in installer_text
    assert "install -m 0644" in installer_text
    assert "/etc/logrotate.d/civibus-refresh" in installer_text
    assert "civibus-refresh-logrotate.conf" in installer_text

    assert "0 */6 * * *" not in priority_script_text
    assert "0 */6 * * *" not in fec_bulk_script_text
    assert "0 3 * * *" not in priority_script_text
    assert "0 3 * * *" not in fec_bulk_script_text

    nc_orchestrator_cron_line = _extract_managed_cron_line(
        installer_text,
        "refresh-nc-orchestrator.log",
    )
    assert "/var/log/civibus/refresh-nc-orchestrator.log" in nc_orchestrator_cron_line
    assert nc_orchestrator_cron_line not in nc_orchestrator_script_text

    assert "/var/log/civibus/*.log" in logrotate_text
    assert "rotate " in logrotate_text
    assert "compress" in logrotate_text
    assert "copytruncate" in logrotate_text


def test_refresh_runbook_matches_production_cron_wrapper_contract() -> None:
    assert REFRESH_RUNBOOK_PATH.is_file(), "docs/operations/campaign-finance-refresh.md must exist"

    runbook_text = _read_text(REFRESH_RUNBOOK_PATH)
    installer_text = _read_required_text(
        INSTALLER_PATH,
        "infra/scripts/install_refresh_cron.sh must exist",
    )
    nc_orchestrator_cron_line = _extract_managed_cron_line(
        installer_text,
        "refresh-nc-orchestrator.log",
    )
    runbook_nc_orchestrator_line = _extract_runbook_cron_line(
        runbook_text,
        "infra/scripts/refresh_nc_orchestrator.sh",
    )
    installer_schedule = nc_orchestrator_cron_line.split(" bash ", maxsplit=1)[0]
    runbook_schedule = runbook_nc_orchestrator_line.split(" bash ", maxsplit=1)[0]

    assert "/root/civibus/civibus_dev" in runbook_text
    assert "0 */6 * * * bash /root/civibus/civibus_dev/infra/scripts/refresh_priority.sh" in runbook_text
    assert "20 */6 * * * bash /root/civibus/civibus_dev/infra/scripts/run_keel_gates.sh" in runbook_text
    assert "0 3 * * * bash /root/civibus/civibus_dev/infra/scripts/refresh_fec_bulk.sh" in runbook_text
    assert installer_schedule == runbook_schedule
    assert runbook_nc_orchestrator_line.endswith(" >> /var/log/civibus/refresh-nc-orchestrator.log 2>&1")
    assert "30 2 * * * bash /root/civibus/civibus_dev/infra/scripts/backup_to_b2.sh" in runbook_text
    assert "0 6 * * * bash /root/civibus/civibus_dev/infra/scripts/check_cert_expiry.sh" in runbook_text
    assert "load literal `KEY=VALUE` assignments from `.env`" in runbook_text
    assert "POSTGRES_HOST=127.0.0.1" in runbook_text
    assert "POSTGRES_PORT=5432" in runbook_text
    assert 'PATH="$HOME/.local/bin:$PATH"' in runbook_text
    assert "FEC_BULK_CYCLE" in runbook_text
    assert "/var/lib/civibus/fec/bulk/${FEC_BULK_CYCLE}" in runbook_text
    assert "/var/log/civibus/backup.log" in runbook_text
    assert "/var/log/civibus/check-cert.log" in runbook_text
    assert "FEC_BULK_DIR" in runbook_text
    assert "make refresh-cf-priority" in runbook_text
    assert "make gate-L5" in runbook_text
    assert "make gate-L7" in runbook_text
    assert "make download-fec-bulk" in runbook_text
    assert "make ingest-fec-bulk" in runbook_text
    assert "_priority_source_names()" in runbook_text
    assert "## Priority membership (config-sourced)" not in runbook_text


def test_backup_status_docs_keep_shipped_language_and_forbidden_slug_out() -> None:
    roadmap_text = _read_required_text(
        ROADMAP_PATH,
        "ROADMAP.md must exist",
    )
    overview_text = _read_required_text(
        SCAI_OVERVIEW_PATH,
        ".scrai/overview.md must exist",
    )
    claude_text = _read_required_text(
        CLAUDE_GUIDE_PATH,
        "CLAUDE.md must exist",
    )
    agents_text = _read_required_text(
        AGENTS_GUIDE_PATH,
        "AGENTS.md must exist",
    )

    forbidden_slug = "apr18_pm_1_db_backup_activation_and_ca_tempdir_investigation"
    assert forbidden_slug not in roadmap_text
    assert forbidden_slug not in overview_text
    assert forbidden_slug not in claude_text
    assert forbidden_slug not in agents_text

    assert "DB backup to B2 — CLOSED/PASS." in roadmap_text
    assert "Production deploy live since March 25, 2026" in overview_text
    assert "Production deploy live since March 25, 2026" in claude_text
    assert "Production deploy live since March 25, 2026" in agents_text


def test_db_backup_runbook_retains_throwaway_restore_contract() -> None:
    runbook_text = _read_required_text(
        DB_BACKUP_RUNBOOK_PATH,
        "docs/operations/db-backup-runbook.md must exist",
    )

    assert "docker build -t civibus-db-verify -f infra/db/Dockerfile ." in runbook_text
    assert "scratch_root=/mnt/HC_Volume_105390322/backup-restore-smoke-" in runbook_text
    assert "--network none" in runbook_text
    assert "-e PGDATA=/var/lib/postgresql/data" in runbook_text
    assert "COUNT(*)" in runbook_text
    assert "n_live_tup" in runbook_text
    assert "postgres:18" not in runbook_text


def test_cert_expiry_wrapper_derives_public_hostname_and_uses_openssl_contract() -> None:
    cert_script_text = _read_wrapper_text(
        CERT_EXPIRY_WRAPPER_PATH,
        "infra/scripts/check_cert_expiry.sh must exist",
    )

    assert "ORIGIN must be set in .env or the shell environment" in cert_script_text
    assert 'origin_without_scheme="${ORIGIN#*://}"' in cert_script_text
    assert 'origin_authority="${origin_without_scheme%%/*}"' in cert_script_text
    assert 'export PUBLIC_HOSTNAME="${origin_authority%%:*}"' in cert_script_text
    assert 'openssl s_client -connect "${PUBLIC_HOSTNAME}:443" -servername "${PUBLIC_HOSTNAME}"' in cert_script_text
    assert "-checkend" in cert_script_text
    assert "604800" in cert_script_text


def test_cert_check_cron_schedule_is_installer_owned_single_source_of_truth() -> None:
    installer_text = _read_required_text(
        INSTALLER_PATH,
        "infra/scripts/install_refresh_cron.sh must exist",
    )
    cert_script_text = _read_required_text(
        CERT_EXPIRY_WRAPPER_PATH,
        "infra/scripts/check_cert_expiry.sh must exist",
    )

    assert "0 6 * * *" in installer_text
    assert "infra/scripts/check_cert_expiry.sh" in installer_text
    assert "/var/log/civibus/check-cert.log" in installer_text
    assert "0 6 * * *" not in cert_script_text


def test_keel_gate_eligibility_is_derived_from_layers_metadata() -> None:
    """Only piloted/enforced global make-gate commands are eligible for unattended cron."""
    layers = _read_required_layers()
    layers_by_id = {str(layer["id"]): layer for layer in layers}

    eligible_layer_ids = sorted(
        str(layer["id"])
        for layer in layers
        if _is_unattended_global_gate(layer)
    )
    assert eligible_layer_ids == ["L5", "L7"]

    # L12 remains intentionally excluded from unattended cron execution:
    # it is introduced-only and writes a per-session summary rather than global gate output.
    l12 = layers_by_id["L12"]
    assert l12["status"] == "introduced"
    assert l12["scope"] == "per_session"
    assert l12["gate_command"] == "uv run python -m core.keel_session_output"
    assert not _is_unattended_global_gate(l12)


def test_keel_gates_wrapper_is_thin_common_contract_wrapper() -> None:
    keel_gates_script_text = _read_wrapper_text(
        KEEL_GATES_WRAPPER_PATH,
        "infra/scripts/run_keel_gates.sh must exist",
    )

    assert "make gate-L5" in keel_gates_script_text
    assert "make gate-L7" in keel_gates_script_text
    assert keel_gates_script_text.index("make gate-L5") < keel_gates_script_text.index("make gate-L7")


def test_debbie_sync_keeps_evidence_and_findings_private_by_default() -> None:
    debbie_text = _read_required_text(
        DEBBIE_CONFIG_PATH,
        ".debbie.toml must exist",
    )
    debbie_payload = tomllib.loads(debbie_text)

    sync_payload = debbie_payload.get("sync", {})
    sync_files = sync_payload.get("files", [])
    sync_dirs = sync_payload.get("dirs", [])

    assert all(
        not (entry == "evidence" or entry.startswith("evidence/") or entry == "findings" or entry.startswith("findings/"))
        for entry in sync_files
    )
    assert all(
        str(sync_dir.get("path", "")).rstrip("/") not in {"evidence", "findings"}
        for sync_dir in sync_dirs
    )


def test_in_freshness_poller_coerces_null_contribution_dates_to_empty_strings() -> None:
    poller_text = _read_required_text(
        IN_FRESHNESS_POLLER_PATH,
        "infra/scripts/poll_in_freshness.sh must exist",
    )

    assert "value = row.get('ContributionDate')" in poller_text
    assert "if value is None:" in poller_text
    assert "d = str(value)[:10]" in poller_text
