from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
ENV_LIB_PATH = SCRIPTS_DIR / "env_lib.sh"
PRIORITY_WRAPPER_PATH = SCRIPTS_DIR / "refresh_priority.sh"
FEC_BULK_WRAPPER_PATH = SCRIPTS_DIR / "refresh_fec_bulk.sh"
ENV_PROD_EXAMPLE_PATH = REPO_ROOT / ".env.production.example"
INSTALLER_PATH = SCRIPTS_DIR / "install_refresh_cron.sh"
LOGROTATE_CONFIG_PATH = SCRIPTS_DIR / "civibus-refresh-logrotate.conf"
REFRESH_RUNBOOK_PATH = REPO_ROOT / "docs/operations/campaign-finance-refresh.md"

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

    assert "0 */6 * * *" in installer_text
    assert "0 3 * * *" in installer_text
    assert "/var/log/civibus/refresh-priority.log" in installer_text
    assert "/var/log/civibus/refresh-fec-bulk.log" in installer_text
    assert "infra/scripts/refresh_priority.sh" in installer_text
    assert "infra/scripts/refresh_fec_bulk.sh" in installer_text
    assert "crontab " in installer_text
    assert "install -m 0644" in installer_text
    assert "/etc/logrotate.d/civibus-refresh" in installer_text
    assert "civibus-refresh-logrotate.conf" in installer_text

    assert "0 */6 * * *" not in priority_script_text
    assert "0 */6 * * *" not in fec_bulk_script_text
    assert "0 3 * * *" not in priority_script_text
    assert "0 3 * * *" not in fec_bulk_script_text

    assert "/var/log/civibus/*.log" in logrotate_text
    assert "rotate " in logrotate_text
    assert "compress" in logrotate_text
    assert "copytruncate" in logrotate_text


def test_refresh_runbook_matches_production_cron_wrapper_contract() -> None:
    assert REFRESH_RUNBOOK_PATH.is_file(), "docs/operations/campaign-finance-refresh.md must exist"

    runbook_text = _read_text(REFRESH_RUNBOOK_PATH)

    assert "/root/civibus/civibus_dev" in runbook_text
    assert "0 */6 * * * bash /root/civibus/civibus_dev/infra/scripts/refresh_priority.sh" in runbook_text
    assert "0 3 * * * bash /root/civibus/civibus_dev/infra/scripts/refresh_fec_bulk.sh" in runbook_text
    assert "load literal `KEY=VALUE` assignments from `.env`" in runbook_text
    assert "POSTGRES_HOST=127.0.0.1" in runbook_text
    assert "POSTGRES_PORT=5432" in runbook_text
    assert 'PATH="$HOME/.local/bin:$PATH"' in runbook_text
    assert "FEC_BULK_CYCLE" in runbook_text
    assert "/var/lib/civibus/fec/bulk/${FEC_BULK_CYCLE}" in runbook_text
    assert "FEC_BULK_DIR" in runbook_text
    assert "make refresh-cf-priority" in runbook_text
    assert "make download-fec-bulk" in runbook_text
    assert "make ingest-fec-bulk" in runbook_text
    assert "_priority_source_names()" in runbook_text
    assert "## Priority membership (config-sourced)" not in runbook_text
