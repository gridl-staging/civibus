from __future__ import annotations

from pathlib import Path

import core.keel_evidence_commit as keel_evidence_commit


def _touch(path: Path, content: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_enumerate_publishable_accepts_evidence_and_findings_trees(tmp_path: Path) -> None:
    repo_root = tmp_path
    p1 = _touch(repo_root / "evidence" / "L7" / "global" / "2026-04-25.json")
    p2 = _touch(repo_root / "evidence" / "review" / "calibration_audit" / "2026-04-25.json")
    p3 = _touch(repo_root / "findings" / "2026-04-25.md", "# findings\n")

    result = keel_evidence_commit.enumerate_publishable(
        repo_root=repo_root, candidate_paths=[p1, p2, p3]
    )

    assert sorted(p.relative_to(repo_root).as_posix() for p in result.allowed) == [
        "evidence/L7/global/2026-04-25.json",
        "evidence/review/calibration_audit/2026-04-25.json",
        "findings/2026-04-25.md",
    ]
    assert result.rejected == []


def test_enumerate_publishable_rejects_paths_outside_allowlist(tmp_path: Path) -> None:
    repo_root = tmp_path
    inside = _touch(repo_root / "evidence" / "L7" / "global" / "2026-04-25.json")
    outside = _touch(repo_root / "core" / "keel_gate_l7.py", "# code\n")

    result = keel_evidence_commit.enumerate_publishable(
        repo_root=repo_root, candidate_paths=[inside, outside]
    )

    assert [p.relative_to(repo_root).as_posix() for p in result.allowed] == [
        "evidence/L7/global/2026-04-25.json"
    ]
    assert [p.relative_to(repo_root).as_posix() for p in result.rejected] == [
        "core/keel_gate_l7.py"
    ]


def test_enumerate_publishable_rejects_redaction_blocklist(tmp_path: Path) -> None:
    repo_root = tmp_path
    p_secret = _touch(repo_root / "evidence" / "L7" / "global" / "secret_token.json")
    p_env = _touch(repo_root / "evidence" / "L7" / "global" / ".env.local")
    p_ok = _touch(repo_root / "evidence" / "L7" / "global" / "2026-04-25.json")

    result = keel_evidence_commit.enumerate_publishable(
        repo_root=repo_root, candidate_paths=[p_secret, p_env, p_ok]
    )

    allowed_names = {p.name for p in result.allowed}
    rejected_names = {p.name for p in result.rejected}
    assert allowed_names == {"2026-04-25.json"}
    assert rejected_names == {"secret_token.json", ".env.local"}


def test_discover_candidate_paths_walks_evidence_and_findings_trees(tmp_path: Path) -> None:
    repo_root = tmp_path
    _touch(repo_root / "evidence" / "L7" / "global" / "2026-04-25.json")
    _touch(repo_root / "evidence" / "review" / "escalation_review" / "2026-04-26.json")
    _touch(repo_root / "findings" / "2026-04-25.md")
    # Files outside the publish tree should be ignored.
    _touch(repo_root / "core" / "keel_gate_l7.py")
    _touch(repo_root / "tests" / "test_x.py")

    discovered = keel_evidence_commit.discover_candidate_paths(repo_root=repo_root)

    relative = sorted(p.relative_to(repo_root).as_posix() for p in discovered)
    assert relative == [
        "evidence/L7/global/2026-04-25.json",
        "evidence/review/escalation_review/2026-04-26.json",
        "findings/2026-04-25.md",
    ]


def test_build_commit_message_is_deterministic_and_lists_relative_paths(tmp_path: Path) -> None:
    repo_root = tmp_path
    p1 = _touch(repo_root / "evidence" / "L7" / "global" / "2026-04-25.json")
    p2 = _touch(repo_root / "findings" / "2026-04-25.md")

    message = keel_evidence_commit.build_commit_message(repo_root=repo_root, paths=[p2, p1])

    # Deterministic ordering: paths appear sorted by their repo-relative form.
    expected_lines = [
        "evidence/continuous: publish L7 + findings artifacts",
        "",
        "Paths:",
        "- evidence/L7/global/2026-04-25.json",
        "- findings/2026-04-25.md",
    ]
    assert message.strip().splitlines() == expected_lines


def test_repo_owned_publish_script_exists_and_is_executable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "infra" / "scripts" / "commit_evidence.sh"
    assert script.is_file(), "commit_evidence.sh must exist for VM-side evidence publishing"
    assert script.stat().st_mode & 0o111, "commit_evidence.sh must be executable"


def test_run_keel_gates_uses_strict_equality_one_for_autopublish_opt_in() -> None:
    """Single source of truth for the autopublish opt-in is the bash conditional
    in run_keel_gates.sh. The check must be strict equality on the literal
    "1" \u2014 no truthy fuzzing on "true"/"yes"/non-empty \u2014 so an operator can
    read the crontab and immediately know what enables auto-push.

    This test catches drift toward looser checks like
    `[[ -n "${KEEL_AUTOPUBLISH_EVIDENCE:-}" ]]` that would let any non-empty
    value enable autopublish."""
    repo_root = Path(__file__).resolve().parents[2]
    runner = (repo_root / "infra" / "scripts" / "run_keel_gates.sh").read_text(encoding="utf-8")
    # Assert the FULL conditional pattern, not just the substrings. Substring
    # matching alone could be fooled by a stray comment containing `== "1"`.
    # The full bash conditional is harder to fake by comment text.
    expected_conditional = '[[ "${KEEL_AUTOPUBLISH_EVIDENCE:-}" == "1" ]]'
    assert expected_conditional in runner, (
        "runner must use the strict-equality opt-in conditional verbatim: "
        f"{expected_conditional}"
    )
    assert "commit_evidence.sh" in runner, "runner must reference commit_evidence.sh"


def test_runner_does_not_short_circuit_on_individual_gate_failure() -> None:
    """Real bug: under `set -euo pipefail`, a bare `make gate-L5` that exits
    non-zero (which happens routinely \u2014 a status=fail evidence emit returns
    exit 1, and DB connection issues are common) kills the whole script. That
    means gate-L7, keel-reviews-status, and autopublish never run on those
    days. Each gate invocation must rescue its exit code (|| pattern) so the
    runner reports overall failure at the end without short-circuiting earlier
    steps."""
    repo_root = Path(__file__).resolve().parents[2]
    runner = (repo_root / "infra" / "scripts" / "run_keel_gates.sh").read_text(encoding="utf-8")

    # Find every `make gate-X` and `make keel-reviews-status` invocation that
    # is a top-level command (not inside an `if`/`while`/etc. that already
    # captures the exit code). For our small runner these are the bare lines.
    # Explicit parentheses to avoid any operator-precedence ambiguity:
    # we want every line that starts with `make ` AND mentions either a gate
    # name or the keel-reviews-status target.
    invocation_lines = [
        line
        for line in runner.splitlines()
        if line.lstrip().startswith("make ")
        and ("gate-" in line or "keel-reviews-status" in line)
    ]
    assert len(invocation_lines) >= 3, (
        f"expected at least 3 make invocations (gate-L5, gate-L7, keel-reviews-status); "
        f"found {len(invocation_lines)}: {invocation_lines}"
    )

    # Each must use a rescue pattern so `set -e` does not abort the runner on
    # a routine fail-status exit. The autopublish call inside the if-block is
    # already conditional and not subject to short-circuit; only the bare
    # top-level invocations need the rescue.
    for line in invocation_lines:
        assert "||" in line, (
            f"gate invocation '{line.strip()}' will short-circuit under set -euo pipefail "
            f"when the gate emits status=fail (exit 1). Add a `|| overall_status=...` rescue "
            f"so subsequent steps still run."
        )
