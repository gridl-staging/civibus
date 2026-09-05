"""Structural tests for infra/scripts/sync_to_prod_vm.sh.

The script replaces the historical "git pull on the VM with a PAT" pattern
with rsync over SSH. Tests assert the script's contract at PR time:

- safe-by-default (no --apply implies no changes)
- excludes secrets and per-machine env from the sync
- uses the canonical SSH key + canonical VM target
- has --dry-run + --apply + --help modes

These cannot exercise the actual rsync against the live VM (would require
SSH + state changes). The default-mode contract therefore executes a copied
script against a PATH-injected fake rsync and inspects its operative arguments.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "sync_to_prod_vm.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script_code(script_text: str) -> str:
    """Code-only view of the script (comment lines stripped).

    Same false-positive-prevention pattern as test_recover_apr30_volume_script.py
    and test_api_dockerfile_contract.py — a comment about a rule cannot
    satisfy an `in script_text` assertion if the rule's actual implementation
    is missing.
    """
    return "\n".join(line for line in script_text.splitlines() if not line.lstrip().startswith("#"))


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT_PATH.exists(), f"missing script at {SCRIPT_PATH}"
    assert os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be chmod +x"


def test_script_has_strict_bash(script_code: str) -> None:
    assert "set -euo pipefail" in script_code


def test_script_excludes_env_and_secret(script_code: str) -> None:
    """The cron jobs on the VM read /root/civibus/civibus_dev/.env. The VM
    has its own .env (with prod-specific values that don't exist on the dev
    machine — POSTGRES_PASSWORD, ORIGIN, etc.). Same for /root/civibus/civibus_dev/.secret/.
    rsync MUST NOT overwrite either, or the cron jobs and prod_compose.sh
    will fail next run.
    """
    assert "--exclude='.env'" in script_code, "must exclude .env so VM's prod env is preserved"
    assert "--exclude='.secret/'" in script_code, "must exclude .secret/ so VM's keys are preserved"


def test_script_excludes_dev_tooling(script_code: str) -> None:
    """Dev tooling state (matt sessions, claude config, build artifacts,
    cache dirs) is not needed on prod and would be noise. Most are large
    enough to slow down rsync materially.
    """
    for excluded in ("__pycache__/", ".venv/", "node_modules/", ".matt/", ".claude/"):
        assert f"--exclude='{excluded}'" in script_code, f"must exclude {excluded!r}"


def test_script_excludes_vm_local_runtime_artifacts(script_code: str) -> None:
    """Avoid deleting VM-local artifacts during repo sync dry-run/apply.

    The sync owner script is for tracked repo content. VM-local caches,
    local editor state, generated test outputs, and host-side data dumps
    should be preserved instead of being force-deleted by --delete-after.
    """
    for excluded in (
        ".coverage",
        ".hashbrown/",
        ".vscode/",
        ".batman.toml",
        "data/",
        "docs/reference/research/artifacts/",
        "docs/reference/research/portal_contracts/",
        "docs/reference/research/portal_contracts/runs/",
        "web/test-results/",
    ):
        assert f"--exclude='{excluded}'" in script_code, f"must exclude {excluded!r}"


def test_script_excludes_dot_git(script_code: str) -> None:
    """`.git/` is excluded deliberately — VM doesn't run git commands, and
    including it produces noisy delete-then-recreate diffs every time the
    two sides' git pack-files differ (different gc timing). The dev repo
    is the authoritative commit-state record; the VM's working tree is
    just deployed code.
    """
    assert "--exclude='.git/'" in script_code, "must exclude .git/ — see comment in source"


def test_script_uses_canonical_ssh_key(script_code: str) -> None:
    """The repo's canonical SSH key path (`.secret/hetzner_ssh_key.txt`)
    is the only one used elsewhere in infra/scripts and docs/reference/research.
    Hard-code it here so the script is reproducible.
    """
    assert "/.secret/hetzner_ssh_key.txt" in script_code or ".secret/hetzner_ssh_key.txt" in script_code


def test_script_targets_canonical_vm(script_code: str) -> None:
    """The Hetzner VM IP is canonical across the repo. Hard-coding it
    here means the script can't be silently retargeted at the wrong host.
    """
    assert "5.78.207.136" in script_code
    assert "/root/civibus/civibus_dev" in script_code


def test_default_invocation_is_dry_run(tmp_path: Path) -> None:
    """Default mode must pass the non-mutating flags to rsync without network I/O."""
    repo_root = tmp_path / "repo"
    copied_script = repo_root / "infra" / "scripts" / SCRIPT_PATH.name
    copied_script.parent.mkdir(parents=True)
    copied_script.write_text(SCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    copied_script.chmod(0o755)

    fake_key = repo_root / ".secret" / "hetzner_ssh_key.txt"
    fake_key.parent.mkdir(parents=True)
    fake_key.write_text("test-only-placeholder\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    rsync_args_path = tmp_path / "rsync_args.txt"
    fake_rsync = fake_bin / "rsync"
    fake_rsync.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nprintf \'%s\\n\' "$@" > "${RSYNC_ARGS_PATH:?}"\n',
        encoding="utf-8",
    )
    fake_rsync.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["RSYNC_ARGS_PATH"] = str(rsync_args_path)
    result = subprocess.run(
        [str(copied_script)],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout

    rsync_args = rsync_args_path.read_text(encoding="utf-8").splitlines()
    assert "--dry-run" in rsync_args, f"default invocation omitted --dry-run: {rsync_args}"
    assert "--itemize-changes" in rsync_args
    assert "--delete-after" in rsync_args
    assert rsync_args[-2:] == [
        f"{repo_root}/",
        "root@5.78.207.136:/root/civibus/civibus_dev/",
    ]
    ssh_argument_index = rsync_args.index("-e") + 1
    assert rsync_args[ssh_argument_index] == (f"ssh -i {fake_key} -o BatchMode=yes -o ConnectTimeout=15")


def test_help_runs_clean() -> None:
    result = subprocess.run(
        [str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        # Shared-host merge gates can take several seconds to schedule even
        # though this help path performs no I/O beyond rendering usage text.
        timeout=30,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--apply" in result.stdout
    # Help must NOT touch the network — confirm by absence of rsync output keywords.
    assert "DRY RUN" not in result.stdout, "--help must not perform a dry run"


def test_apply_mode_recognized(script_code: str) -> None:
    """The --apply flag is the explicit opt-in to actually perform the sync.
    Asserted in source so a refactor can't silently drop it.
    """
    assert "--apply" in script_code
    # And the mode dispatch must distinguish dry-run from apply.
    assert 'MODE="apply"' in script_code or "MODE='apply'" in script_code
