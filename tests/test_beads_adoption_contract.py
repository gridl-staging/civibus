"""Structural Beads-adoption contract for the civibus_dev repository.

Baseline stage of the two-stage adoption contract from
``BEADS_QA_TRANSITION.md``: it proves structure, privacy, bootstrap hardening,
roadmap freeze, and refusal wiring without depending on canary IDs that can
only exist after adoption completes. Live-ledger and remote-ref proof
(``bd prime``/``bd ready``/``refs/dolt/data``) is deliberately NOT here: Batman
merge worktrees materialize tracked files only, so a pytest node that needs the
ignored runtime database would fail for locality, not for a defect. Those
checks live in the controller-owned ``scripts/tests/beads_adoption_contract_live.sh``.

Every node in this module is classified ``dev_repo_only`` in
``tests/ci/public_mirror_contract.py`` except the ones that only read publicly
synced files; the public projection intentionally carries neither ``.beads/``
nor the frozen ``ROADMAP.md``.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
import tomllib
from pathlib import Path

import conftest as quarantine_loader_owner
import pytest
from tests.ci.public_mirror_contract import DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID

REPO_ROOT = Path(__file__).resolve().parents[1]

# One bounded guard per subprocess: these commands answer from local state and
# a hang means a broken toolchain, not a slow legitimate run.
_SUBPROCESS_TIMEOUT_SECONDS = 60

# The adoption pin. v1.2.1 was retracted after an accidental untested schema
# migration; v1.2.3+ changes storage/CLI behavior this contract has not
# validated. The trailing space prevents "bd version 1.2.20" from passing.
_PINNED_BD_VERSION_PREFIX = "bd version 1.2.2 "

_TRACKED_BEADS_PATHS = (
    ".beads/.gitignore",
    ".beads/README.md",
    ".beads/metadata.json",
    "scripts/bootstrap_beads.sh",
)

# Clone-local runtime state that must never be tracked. bd v1.2.2 persists the
# git-derived sync.remote into config.yaml during init/bootstrap and then
# refuses that same repository URL as a bootstrap source in the next clone, so
# a tracked config.yaml breaks fresh-clone recovery.
_IGNORED_BEADS_PATHS = (".beads/config.yaml",)

_DEBBIE_PHYSICAL_PROJECTION_NODE_ID = (
    "tests/test_debbie_post_sync_hook.py"
    "::test_debbie_projection_excludes_private_ledger_and_planning_docs_from_physical_tree"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
        **kwargs,
    )


def test_pinned_bd_cli_version_is_exact() -> None:
    """The workflow is validated against exactly the approved bd fleet window."""
    # Anchor to the private ledger identity first so this node fails on the
    # missing dev-repo asset in the projected public mirror instead of
    # depending on which CLIs happen to be on the validating host's PATH.
    assert (REPO_ROOT / ".beads" / "metadata.json").is_file(), (
        "the bd pin is only meaningful in the adopted dev repository"
    )
    completed = _run(["bd", "--version"])
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith(_PINNED_BD_VERSION_PREFIX), completed.stdout
    live_contract = _read(REPO_ROOT / "scripts" / "tests" / "beads_adoption_contract_live.sh")
    assert _PINNED_BD_VERSION_PREFIX in live_contract, (
        "live Beads contract must require the same pinned bd release as pytest"
    )
    assert "bd version 1.2.1 " not in live_contract


def test_beads_tracked_and_ignored_boundary() -> None:
    """Track only identity/recovery files; runtime state stays clone-local."""
    for relative_path in _TRACKED_BEADS_PATHS:
        tracked = _run(
            ["git", "ls-files", "--error-unmatch", "--", relative_path],
            cwd=REPO_ROOT,
        )
        assert tracked.returncode == 0, f"{relative_path} must be tracked"

    for relative_path in _IGNORED_BEADS_PATHS:
        tracked = _run(
            ["git", "ls-files", "--error-unmatch", "--", relative_path],
            cwd=REPO_ROOT,
        )
        assert tracked.returncode != 0, f"{relative_path} must remain ignored clone-local runtime state"
        # check-ignore proves the ignore RULE exists, not merely that nobody
        # has added the file yet.
        ignored = _run(["git", "check-ignore", "--quiet", "--", relative_path], cwd=REPO_ROOT)
        assert ignored.returncode == 0, f"{relative_path} must match an ignore rule so bootstrap cannot dirty a clone"


def test_beads_marker_is_physical_directory() -> None:
    """Batman's work-ledger classification refuses symlinked markers."""
    marker = REPO_ROOT / ".beads"
    marker_stat = marker.lstat()
    assert stat.S_ISDIR(marker_stat.st_mode), ".beads must be a physical directory"
    assert not stat.S_ISLNK(marker_stat.st_mode)


def test_beads_metadata_pins_embedded_dolt_database() -> None:
    payload = json.loads(_read(REPO_ROOT / ".beads" / "metadata.json"))
    assert payload["database"] == "dolt"
    assert payload["backend"] == "dolt"
    assert payload["dolt_mode"] == "embedded"
    assert payload["dolt_database"] == "civibus"
    # project_id is minted by bd init; any non-empty stable value is valid.
    assert payload["project_id"].strip()


def test_beads_runtime_ignore_rules_cover_clone_local_state() -> None:
    ignore_text = _read(REPO_ROOT / ".beads" / ".gitignore")
    for required_rule in (
        "config.yaml",
        "embeddeddolt/",
        "proxieddb/",
        ".beads-credential-key",
        "proxied_server_client_info.json",
        "*.gate.lock*",
    ):
        assert required_rule in ignore_text.split(), f".beads/.gitignore must ignore {required_rule}"


def test_root_gitignore_covers_beads_gate_lock() -> None:
    """bd bootstrap drops a repo-root gate lock outside .beads/."""
    ignore_lines = _read(REPO_ROOT / ".gitignore").splitlines()
    assert "/.beads.gate.lock*" in ignore_lines


def test_beads_readme_documents_recovery_and_pin() -> None:
    readme_text = _read(REPO_ROOT / ".beads" / "README.md")
    assert "scripts/bootstrap_beads.sh" in readme_text
    assert "bd bootstrap --yes" in readme_text
    assert "Pinned CLI: v1.2.2" in readme_text
    assert "v1.2.1" not in readme_text
    assert "refs/dolt/data" in readme_text
    assert "JSONL is not authoritative" in readme_text


@pytest.mark.dev_repo_only(
    private_asset="scripts/tests/beads_adoption_contract_live.sh",
    owner="Beads adoption contract",
)
def test_live_contract_uses_pinned_bd_info_text_contract() -> None:
    """bd v1.2.2 advertises info --json but emits text; the live guard must match reality."""
    live_contract = _read(REPO_ROOT / "scripts" / "tests" / "beads_adoption_contract_live.sh")
    assert "info --json" not in live_contract
    assert "info --schema" in live_contract
    assert "Detected Prefix:" in live_contract
    assert "Mode:" in live_contract
    assert "Issue Count:" in live_contract


def _write_fake_bd(fake_bin: Path, calls_log: Path) -> None:
    """A recording bd stand-in; FAKE_BD_FAIL_MATCH makes one call fail."""
    fake_bd = fake_bin / "bd"
    fake_bd.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            printf '%s\\n' "$*" >> "$FAKE_BD_CALLS_LOG"
            if [[ -n "${FAKE_BD_FAIL_MATCH:-}" && "$*" == *"$FAKE_BD_FAIL_MATCH"* ]]; then
              exit 37
            fi
            """
        ),
        encoding="utf-8",
    )
    fake_bd.chmod(0o755)
    assert calls_log.parent.is_dir()


def _bootstrap_env(fake_bin: Path, calls_log: Path, fixture_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_BD_CALLS_LOG"] = str(calls_log)
    env["CIVIBUS_BEADS_REPO_ROOT"] = str(fixture_root)
    return env


def test_bootstrap_wrapper_issues_exact_hardened_sequence(tmp_path: Path) -> None:
    """The wrapper must pin permissions, seed portable config, then run bd."""
    fixture_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    calls_log = tmp_path / "bd.calls"
    (fixture_root / ".beads").mkdir(parents=True)
    (fixture_root / ".beads").chmod(0o755)
    fake_bin.mkdir()
    calls_log.write_text("", encoding="utf-8")
    _write_fake_bd(fake_bin, calls_log)

    completed = _run(
        ["bash", str(REPO_ROOT / "scripts" / "bootstrap_beads.sh")],
        env=_bootstrap_env(fake_bin, calls_log, fixture_root),
    )
    assert completed.returncode == 0, completed.stderr

    expected_calls = "\n".join(
        [
            f"-C {fixture_root} bootstrap --yes",
            f"-C {fixture_root} config set import.auto false",
            f"-C {fixture_root} config set export.auto false",
            f"-C {fixture_root} config set export.git-add false",
        ]
    )
    assert calls_log.read_text(encoding="utf-8").strip() == expected_calls

    mode = stat.S_IMODE((fixture_root / ".beads").stat().st_mode)
    assert mode == 0o700, f".beads permissions must tighten to 700, got {oct(mode)}"

    seeded_config_path = fixture_root / ".beads" / "config.yaml"
    seeded_config = seeded_config_path.read_text(encoding="utf-8")
    assert seeded_config == ("import:\n  auto: false\nexport:\n  auto: false\n  git-add: false\n")
    # The umask 077 subshell is what keeps the seeded runtime config private;
    # asserting the resulting mode is what makes deleting it a red test.
    seeded_mode = stat.S_IMODE(seeded_config_path.stat().st_mode)
    assert seeded_mode == 0o600, f"seeded config must be 600, got {oct(seeded_mode)}"


def test_bootstrap_wrapper_refuses_symlinked_beads_directory(tmp_path: Path) -> None:
    """A symlinked .beads marker would redirect the private runtime elsewhere."""
    fixture_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    calls_log = tmp_path / "bd.calls"
    fixture_root.mkdir()
    external_beads = tmp_path / "external_beads"
    external_beads.mkdir()
    (fixture_root / ".beads").symlink_to(external_beads, target_is_directory=True)
    fake_bin.mkdir()
    calls_log.write_text("", encoding="utf-8")
    _write_fake_bd(fake_bin, calls_log)

    completed = _run(
        ["bash", str(REPO_ROOT / "scripts" / "bootstrap_beads.sh")],
        env=_bootstrap_env(fake_bin, calls_log, fixture_root),
    )
    assert completed.returncode != 0
    assert "physical .beads directory" in completed.stderr
    assert calls_log.read_text(encoding="utf-8").strip() == "", "wrapper must refuse before invoking bd at all"


def test_bootstrap_wrapper_fails_closed_on_config_set_failure(tmp_path: Path) -> None:
    """A failed hardening step must abort the wrapper, not be swallowed."""
    fixture_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    calls_log = tmp_path / "bd.calls"
    (fixture_root / ".beads").mkdir(parents=True)
    fake_bin.mkdir()
    calls_log.write_text("", encoding="utf-8")
    _write_fake_bd(fake_bin, calls_log)

    env = _bootstrap_env(fake_bin, calls_log, fixture_root)
    env["FAKE_BD_FAIL_MATCH"] = "config set import.auto false"
    completed = _run(["bash", str(REPO_ROOT / "scripts" / "bootstrap_beads.sh")], env=env)
    assert completed.returncode == 37, f"wrapper must propagate the failing bd exit (got {completed.returncode})"
    # errexit must stop at the failed call: nothing after it may run.
    assert calls_log.read_text(encoding="utf-8").strip() == "\n".join(
        [
            f"-C {fixture_root} bootstrap --yes",
            f"-C {fixture_root} config set import.auto false",
        ]
    )


def test_bootstrap_wrapper_refuses_symlinked_runtime_config(tmp_path: Path) -> None:
    """A symlinked config.yaml could redirect the seeded settings elsewhere."""
    fixture_root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    calls_log = tmp_path / "bd.calls"
    (fixture_root / ".beads").mkdir(parents=True)
    fake_bin.mkdir()
    calls_log.write_text("", encoding="utf-8")
    _write_fake_bd(fake_bin, calls_log)
    external_target = tmp_path / "external_config.yaml"
    external_target.write_text("", encoding="utf-8")
    (fixture_root / ".beads" / "config.yaml").symlink_to(external_target)

    completed = _run(
        ["bash", str(REPO_ROOT / "scripts" / "bootstrap_beads.sh")],
        env=_bootstrap_env(fake_bin, calls_log, fixture_root),
    )
    assert completed.returncode != 0
    assert "symlink" in completed.stderr.lower()
    assert calls_log.read_text(encoding="utf-8").strip() == "", "wrapper must refuse before invoking bd at all"


def test_debbie_projection_excludes_ledger_and_planning_docs() -> None:
    """The private ledger and frozen roadmap must never reach public mirrors.

    ``.debbie.toml`` is a strict whitelist, so absence from the sync lists is
    the projection guarantee; this pins that absence so a future edit cannot
    quietly start publishing task text.
    """
    payload = tomllib.loads(_read(REPO_ROOT / ".debbie.toml"))
    synced_files = payload["sync"]["files"]
    synced_dirs = [entry["path"].rstrip("/") for entry in payload["sync"]["dirs"]]

    for private_path in ("ROADMAP.md", "BEADS_QA_TRANSITION.md", "CAPABILITIES.md", ".beads"):
        for synced_file in synced_files:
            # Equality alone is evadable at file granularity: whitelisting
            # ".beads/issues.jsonl" would publish ledger content with every
            # guard green, so anything under a private path is rejected too.
            assert synced_file != private_path and not synced_file.startswith(private_path + "/"), (
                f"{synced_file} must not publish private path {private_path}"
            )
        for synced_dir in synced_dirs:
            assert not private_path.startswith(synced_dir + "/"), (
                f"{private_path} must not fall inside synced dir {synced_dir}"
            )
        assert private_path not in synced_dirs


def test_roadmap_is_frozen_read_only_archive() -> None:
    roadmap_text = _read(REPO_ROOT / "ROADMAP.md")
    assert "READ-ONLY HISTORICAL ARCHIVE" in roadmap_text
    # The banner must appear before any content row so no reader can miss it.
    banner_index = roadmap_text.index("READ-ONLY HISTORICAL ARCHIVE")
    first_table_index = roadmap_text.index("| Priority |")
    assert banner_index < first_table_index


def test_current_work_authority_routes_to_beads() -> None:
    """No current-work authority may remain outside Beads after the cutover."""
    required_literals = {
        "PROJECT_OVERVIEW.md": (
            "Beads is the sole ledger for new open and planned work",
            "ROADMAP.md is a read-only historical archive",
        ),
        "README.md": ("Historical roadmap archive",),
        ".scrai/rules.md": (
            "### Beads Work Ledger",
            "Use pinned `bd` v1.2.2",
        ),
        # Generated outputs must carry the assembled section; catching drift
        # here means a hand-edit or stale assembly fails the union, including
        # the exact bd pin.
        "CLAUDE.md": (
            "### Beads Work Ledger",
            "Use pinned `bd` v1.2.2",
        ),
        "AGENTS.md": (
            "### Beads Work Ledger",
            "Use pinned `bd` v1.2.2",
        ),
        ".beads/README.md": ("Beads is the private source of truth",),
    }
    for relative_path, literals in required_literals.items():
        document_text = _read(REPO_ROOT / relative_path)
        for literal in literals:
            assert literal in document_text, f"{relative_path} missing: {literal}"
    for relative_path in (".scrai/rules.md", "CLAUDE.md", "AGENTS.md", ".beads/README.md"):
        assert "v1.2.1" not in _read(REPO_ROOT / relative_path), (
            f"{relative_path} must not authorize retracted bd v1.2.1"
        )

    retired_literals = {
        "PROJECT_OVERVIEW.md": (
            "`ROADMAP.md` owns the open-work ledger",
            "Open-work ledger and current priorities: `ROADMAP.md`",
        ),
        "README.md": ("`ROADMAP.md` is the project SSOT for open work",),
        ".scrai/rules.md": (
            "`ROADMAP.md` owns open work and priority ordering.",
            "active scope is tracked in `ROADMAP.md`",
        ),
        ".scrai/overview.md": ("as tracked in `ROADMAP.md`",),
        ".scrai/highest_level_priorities.md": ("open work: `ROADMAP.md`",),
        "CLAUDE.md": ("`ROADMAP.md` owns open work and priority ordering.",),
        "AGENTS.md": ("`ROADMAP.md` owns open work and priority ordering.",),
    }
    for relative_path, literals in retired_literals.items():
        document_text = _read(REPO_ROOT / relative_path)
        for literal in literals:
            assert literal not in document_text, f"{relative_path} retains retired current-work authority: {literal}"


def test_canonical_db_backed_quarantine_loads_without_roadmap_owners() -> None:
    """The live quarantine ledger never routes ownership back to the frozen roadmap.

    Rejection of a malformed or roadmap-owned entry is the loader's own contract
    (tests/ci/test_db_backed_quarantine_contract.py owns those specimens). This
    pins the adoption-side policy against the canonical ledger, and the explicit
    owner sweep keeps it red even if that validator is ever relaxed.
    """
    entries = quarantine_loader_owner._load_db_backed_quarantine()

    assert entries
    roadmap_owned_node_ids = [entry.node_id for entry in entries if "roadmap.md" in entry.owner.casefold()]
    assert not roadmap_owned_node_ids, (
        f"quarantine entries name the frozen ROADMAP.md as owner: {roadmap_owned_node_ids}"
    )


def test_debbie_physical_projection_node_stays_dev_repo_only() -> None:
    entry = DEV_REPO_ONLY_CLASSIFICATIONS_BY_NODE_ID[_DEBBIE_PHYSICAL_PROJECTION_NODE_ID]

    assert entry.private_asset == "private Beads ledger (.beads/), frozen ROADMAP.md, and BEADS_QA_TRANSITION.md"
    assert entry.owner == "Debbie projection contract"


def test_batman_roadmap_mutation_refuses_adopted_repo() -> None:
    """Roadmap commands must refuse (exit 4) once .beads/ classifies this repo.

    Exit 4 is ``batman.roadmap.exit_codes.ExitCode.REFUSED``; any other exit
    means the legacy roadmap machinery still accepts this repository.
    """
    # Same private-asset anchor as the bd pin: fail on the missing marker in
    # the projected mirror, deterministically, before consulting host CLIs.
    assert (REPO_ROOT / ".beads").is_dir(), "refusal is only meaningful once .beads/ classifies this repository"
    completed = _run(["batman", "roadmap", "lint", "--json"], cwd=REPO_ROOT)
    assert completed.returncode == 4, (
        f"expected REFUSED exit 4, got {completed.returncode}: {completed.stdout}{completed.stderr}"
    )
