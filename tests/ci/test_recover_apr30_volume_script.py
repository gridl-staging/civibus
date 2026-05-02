"""Structural tests for the Apr 30 wrong-volume recovery script.

The script wraps the recovery sequence documented in
`docs/operations/apr30_volume_recovery_runbook.md` into a single
artifact with four verification gates (per `prod_ops_discipline.md`):

1. Bare-docker calls are NOT used — every container-lifecycle action
   must go through `prod_compose.sh`.
2. Volume-identity check before mount: `du -sh` on the canonical
   163 GB volume must report a sane size before the swap proceeds.
3. Post-action canary: the new container must pass the canary check
   before the script claims success.
4. No-auto-run guard: the script refuses to make state changes
   unless `--confirm` is explicitly passed.

These tests assert the contract at PR time. They cannot exercise the
script against the real Hetzner VM (would require live SSH + state
changes); the script's `--diagnose` mode is exercised in a separate
integration test category if/when wired.

The failure mode these tests catch: a future refactor silently drops
one of the four gates. That is the exact pattern the prod_ops
discipline names.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "recover_apr30_volume.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script_code(script_text: str) -> str:
    """Code-only view of the script: lines whose first non-whitespace char is `#`
    are stripped. Used by every grep-style assertion below so a comment about a
    gate cannot pass for the gate's actual implementation. (The Apr 30 incident
    is exactly the kind of failure that loose comment-vs-code grepping helps
    hide; a false-positive test would be its own version of that.)
    """
    return "\n".join(line for line in script_text.splitlines() if not line.lstrip().startswith("#"))


def test_script_file_exists() -> None:
    assert SCRIPT_PATH.exists(), f"missing recovery script at {SCRIPT_PATH}"


def test_script_is_executable() -> None:
    assert os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be chmod +x — operators run this directly via SSH"


def test_script_has_strict_bash_options(script_code: str) -> None:
    # `set -euo pipefail` is the standard prelude for safety-critical bash.
    # Without it, a failed `du -sh` or SSH call could be silently ignored
    # and the script would proceed to mount the wrong volume. Asserted
    # against script_code (comments stripped) to avoid a comment about
    # the option satisfying the test when the actual `set` line is gone.
    assert "set -euo pipefail" in script_code, "script must `set -euo pipefail` so a failed pre-check halts execution"


def test_script_rejects_bare_docker_compose(script_code: str) -> None:
    """Gate 1: bare `docker compose` invocations are forbidden.

    The Apr 30 incident was caused by a bare `docker compose up` from
    `infra/` picking up the dev compose. The recovery script must not
    repeat that pattern. Compose lifecycle commands must go through
    `prod_compose.sh` (which pins `-f docker-compose.prod.yml`).

    Direct `docker stop <name>` / `docker rm <name>` against a specific
    NAMED container is permitted — see prod_ops_discipline.md. Those
    forms cannot trigger the Apr 30 failure mode.
    """
    forbidden_patterns = [
        "docker compose up",
        "docker compose -f docker-compose.yml",
        "docker compose down",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in script_code, (
            f"forbidden bare-docker-compose pattern {pattern!r} appears in script source — "
            f"use infra/scripts/prod_compose.sh instead"
        )


def test_script_uses_prod_compose_wrapper(script_code: str) -> None:
    """Gate 1 (positive form): the wrapper must be invoked at least once for compose lifecycle."""
    assert "prod_compose.sh" in script_code, (
        "recovery script must invoke infra/scripts/prod_compose.sh for compose-lifecycle actions"
    )


def test_script_checks_required_env_var(script_code: str) -> None:
    """Gate 0: required env var on the prod VM must be checked BEFORE state changes.

    The prod compose fails fast on missing CIVIBUS_DB_DATA_PATH — but only
    after step 3 would have stopped/removed the wrong-volume db container.
    Without this pre-flight gate, a partial recovery would leave the stack
    with no db. This test asserts the script verifies the env var.
    """
    assert "CIVIBUS_DB_DATA_PATH" in script_code, (
        "script must verify CIVIBUS_DB_DATA_PATH is set on the VM before any state change"
    )
    assert "/mnt/HC_Volume_105390322/pgdata" in script_code, (
        "script must compare env var to the canonical canonical volume path"
    )


def test_script_checks_canonical_volume_size(script_code: str) -> None:
    """Gate 2: `du -sh` on the canonical volume before any mount."""
    # `du` family is the only practical way to get directory size. We accept
    # `du -s` (any unit flag) and the human-readable `du -sh` form, since
    # the implementation may switch units to make threshold comparison easier.
    assert "du -s" in script_code, "script must `du -s` (or `du -sh`) the target volume before mount"
    assert "/mnt/HC_Volume_105390322/pgdata" in script_code, (
        "script must reference the canonical Hetzner volume path explicitly"
    )


def test_script_refuses_empty_volume(script_code: str) -> None:
    """Gate 2 (refusal arm): if the canonical volume is empty, halt.

    The Apr 30 fingerprint is precisely an empty volume mounted as
    Postgres data. The recovery must refuse to proceed if the volume
    we're about to mount has the same shape as the broken state.
    """
    # The script must define a minimum acceptable size threshold AND have an
    # explicit halt path. Both checks run against script_code (comments
    # stripped) so prose about the threshold cannot rescue a missing
    # implementation.
    assert any(marker in script_code for marker in ("MIN_VOLUME_BYTES", "MIN_VOLUME_GB", "100G", "100M")), (
        "script must define a minimum acceptable canonical-volume size"
    )
    assert "exit 1" in script_code or "abort" in script_code or "die " in script_code, (
        "script must have an explicit halt path on volume-size precondition fail"
    )


def test_script_runs_canary_after_swap(script_code: str) -> None:
    """Gate 3: post-action canary check must run before declaring success."""
    # The canary endpoint is /api/health/content (per api/health_content.py).
    # The script must hit it after restoring the volume, either by curling
    # localhost from the api container or via the public hostname. Asserted
    # against script_code so a doc-comment mentioning the path cannot pass.
    assert "/api/health/content" in script_code or "canary_check" in script_code, (
        "script must verify content health endpoint or run canary_check.py after restoring the volume"
    )


def test_script_refuses_to_run_without_confirm(script_code: str) -> None:
    """Gate 4: the dangerous arm must require an explicit --confirm flag.

    Diagnose-only invocation must be the default. State changes happen
    only when the operator/agent passes --confirm.
    """
    assert "--confirm" in script_code, "script must require an explicit --confirm flag to perform state changes"
    # The default-no-op behavior: state-change paths must be gated on a
    # CONFIRM variable so a missing flag fails fast rather than silently
    # running the destructive arm.
    assert any(guard in script_code for guard in ("CONFIRM=", "$CONFIRM", '"$CONFIRM"', "${CONFIRM}")), (
        "script must gate state changes on a CONFIRM variable"
    )


def test_script_supports_diagnose_mode(script_code: str) -> None:
    """The diagnose mode lets agents probe state without changing it."""
    assert "--diagnose" in script_code, "script must support a --diagnose mode for read-only state probing"


def test_help_runs_without_state_change() -> None:
    """Sanity: invoking the script with --help returns non-zero/zero quickly
    and emits text to stdout. No SSH, no docker, no state change.
    """
    # `--help` is a strict subset of `--diagnose`: it should exit before any
    # SSH calls. We assert it completes within 5 seconds and produces output.
    result = subprocess.run(
        [str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    # Help output should appear on stdout and the exit code should be 0
    # (POSIX convention for explicit --help).
    assert result.stdout.strip(), "--help must print usage text to stdout"
    assert result.returncode == 0, f"--help must exit 0; got {result.returncode}; stderr={result.stderr!r}"


def test_default_invocation_is_safe() -> None:
    """Sanity: running the script with no flags must not perform state changes.

    It should print usage / diagnose hints and exit non-zero (because the
    operator/agent did not pick a mode).
    """
    result = subprocess.run(
        [str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    # Non-zero is correct — "you must pass --diagnose, --plan, or --confirm"
    assert result.returncode != 0, "no-flag invocation must exit non-zero so a missing-mode mistake fails fast"
