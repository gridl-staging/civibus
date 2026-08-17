"""Shared stateful fakes and assertions for uptime-incident bridge contracts."""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

ISSUE_JSON_FIELDS = "number,title,url,createdAt,body,comments"
STAGING_REPO = "gridl-staging/civibus"
PROD_REPO = "gridl-hq/civibus"
STAGING_EXTERNAL_REF = "gh-staging-6"
PROD_EXTERNAL_REF = "gh-prod-3"
TRUSTED_COMMENT_AUTHOR = "github-actions"
BRIDGE_TODAY = date(2026, 8, 15)
TODAY_ISO = BRIDGE_TODAY.isoformat()
HEARTBEAT_MARKER = f"{TODAY_ISO} uptime incident heartbeat"
CLOSURE_MARKER = "closure proposal"


@dataclass(frozen=True)
class FakeResult:
    args: list[str]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeCommandRunner:
    """Stateful fake ledger with the pinned bd v1.2.1 read boundaries.

    ``bd list --json`` exposes ``comment_count`` but not comment bodies. Replay
    markers therefore have to come from the supported ``bd comments <id>
    --json`` read. Writes mutate the same internal records so a second bridge
    run observes the first run's comments without inventing bridge-only state.
    """

    def __init__(
        self,
        *,
        issues_by_repo_and_state: dict[tuple[str, str], Any],
        beads_by_external_ref: dict[str, list[dict[str, Any]]] | None = None,
        gh_failures: dict[tuple[str, str], FakeResult] | None = None,
        bd_read_results_by_argv: dict[tuple[str, ...], FakeResult] | None = None,
        push_results: list[FakeResult] | None = None,
    ) -> None:
        self.issues_by_repo_and_state = issues_by_repo_and_state
        self.beads_by_external_ref = beads_by_external_ref or {}
        self.gh_failures = gh_failures or {}
        self.bd_read_results_by_argv = bd_read_results_by_argv or {}
        self.push_results = list(push_results or [])
        self.calls: list[list[str]] = []
        self.ledger_path = (Path.cwd() / ".beads").resolve()

    def run(self, argv: list[str]) -> FakeResult:
        self.calls.append(argv)
        if argv == ["bd", "where", "--json"]:
            return FakeResult(args=argv, stdout=json.dumps({"path": str(self.ledger_path)}))
        if argv[:3] == ["gh", "issue", "list"]:
            repo = _option_value(argv, "-R")
            state = _option_value(argv, "--state")
            failure = self.gh_failures.get((repo, state))
            if failure is not None:
                return FakeResult(args=argv, returncode=failure.returncode, stderr=failure.stderr)
            payload = self.issues_by_repo_and_state[(repo, state)]
            return FakeResult(args=argv, stdout=payload if isinstance(payload, str) else json.dumps(payload))
        override = self.bd_read_results_by_argv.get(tuple(argv))
        if override is not None:
            return FakeResult(
                args=argv,
                returncode=override.returncode,
                stdout=override.stdout,
                stderr=override.stderr,
            )
        if argv[:2] == ["bd", "list"]:
            external_ref = _option_value(argv, "--external-ref")
            beads = self.beads_by_external_ref.get(external_ref, [])
            if "--all" not in argv:
                beads = [bead for bead in beads if bead["status"] != "closed"]
            return FakeResult(args=argv, stdout=json.dumps([_bead_list_row(bead) for bead in beads]))
        if len(argv) == 4 and argv[:2] == ["bd", "comments"] and argv[3] == "--json":
            bead_id = argv[2]
            return FakeResult(args=argv, stdout=json.dumps(self._comments_for(bead_id)))
        if argv[:2] == ["bd", "create"]:
            external_ref = _option_value(argv, "--external-ref")
            bead_id = f"bead-{external_ref}"
            self.beads_by_external_ref.setdefault(external_ref, []).append(
                {"id": bead_id, "status": "open", "comments": []}
            )
            return FakeResult(args=argv, stdout=bead_id)
        if argv[:3] == ["bd", "comments", "add"]:
            bead_id = argv[3]
            body = " ".join(argv[4:])
            self._append_comment(bead_id, body)
            return FakeResult(args=argv, stdout="")
        if argv == ["bd", "dolt", "push"]:
            if self.push_results:
                push_result = self.push_results.pop(0)
                return FakeResult(
                    args=argv,
                    returncode=push_result.returncode,
                    stdout=push_result.stdout,
                    stderr=push_result.stderr,
                )
            return FakeResult(args=argv, stdout="")
        raise AssertionError(f"unexpected command: {argv}")

    def _append_comment(self, bead_id: str, body: str) -> None:
        for beads in self.beads_by_external_ref.values():
            for bead in beads:
                if bead.get("id") == bead_id:
                    comments = bead.setdefault("comments", [])
                    comments.append(_bead_comment(bead_id, body, sequence=len(comments) + 1))
                    return
        raise AssertionError(f"bd comments add targeted unknown bead: {bead_id}")

    def _comments_for(self, bead_id: str) -> list[dict[str, str]]:
        for beads in self.beads_by_external_ref.values():
            for bead in beads:
                if bead.get("id") == bead_id:
                    return list(bead.get("comments", []))
        raise AssertionError(f"bd comments targeted unknown bead: {bead_id}")

    @property
    def bd_write_calls(self) -> list[list[str]]:
        return [call for call in self.calls if _is_bd_write_call(call)]


class InterruptAfterMutationRunner(FakeCommandRunner):
    """Simulate process interruption after a local mutation has taken effect."""

    interrupt_after_next_mutation = True

    def run(self, argv: list[str]) -> FakeResult:
        result = super().run(argv)
        if self.interrupt_after_next_mutation and _is_local_bd_mutation(argv):
            self.interrupt_after_next_mutation = False
            raise KeyboardInterrupt("simulated interruption after local mutation")
        return result


class CustomPushRunner(FakeCommandRunner):
    """Accept a non-default push argv so tests can prove one push source is shared."""

    def __init__(self, *, expected_push_argv: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.expected_push_argv = expected_push_argv

    def run(self, argv: list[str]) -> FakeResult:
        if argv == self.expected_push_argv:
            self.calls.append(argv)
            return FakeResult(args=argv, stdout="")
        return super().run(argv)


def _run_bridge(
    runner: FakeCommandRunner,
    *,
    lock_path: Path,
    ledger_path: Path | None = None,
    today: date = BRIDGE_TODAY,
    argv: tuple[str, ...] = (),
) -> int:
    from scripts import uptime_incident_bridge

    lock_file = lock_path / "uptime_bridge.lock" if lock_path.is_dir() else lock_path
    main_arguments: dict[str, Any] = {
        "command_runner": runner.run,
        "today": today,
        "lock_path": lock_file,
        "argv": argv,
    }
    if ledger_path is not None:
        main_arguments["ledger_path"] = ledger_path
    return uptime_incident_bridge.main(
        **main_arguments,
    )


def _pending_push_journal_text(ledger_path: Path) -> str:
    return json.dumps({"ledger_path": str(_resolved_beads_ledger_path(ledger_path))}) + "\n"


def _resolved_beads_ledger_path(start_path: Path) -> Path:
    resolved_start = start_path.resolve()
    candidates = (resolved_start, *resolved_start.parents)
    for candidate in candidates:
        if candidate.name == ".beads" and candidate.is_dir():
            return candidate
        ledger_path = candidate / ".beads"
        if ledger_path.is_dir():
            return ledger_path.resolve()
    raise AssertionError(f"test checkout has no .beads ledger: {start_path}")


def _pending_push_marker_path(lock_path: Path, ledger_path: Path) -> Path:
    ledger_identity = str(_resolved_beads_ledger_path(ledger_path))
    identity_digest = hashlib.sha256(ledger_identity.encode("utf-8")).hexdigest()
    return lock_path.with_name(f"{lock_path.stem}.{identity_digest}.pending_push")


def _issue(
    *,
    number: int,
    repo: str,
    title: str,
    body: str | None = None,
    comments: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    # Mirrors exactly the fields requested by ISSUE_JSON_FIELDS. Openness /
    # closedness comes from the `gh --state <state>` query, not from any field
    # on the issue object, so no `state` member is emitted here.
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/{repo}/issues/{number}",
        "createdAt": "2026-08-15T17:45:00Z",
        "body": body
        if body is not None
        else (f"Initial red probe at 2026-08-15T17:45:00Z. Workflow run: https://github.com/{repo}/actions/runs/333"),
        "comments": comments
        if comments is not None
        else [
            _comment(
                "2026-08-15T18:00:00Z red probe: HTTP 503 /health",
                repo=repo,
                issue_number=number,
                comment_id=1,
            ),
            _comment(
                "2026-08-15T18:30:00Z red probe: HTTP 500 /health",
                repo=repo,
                issue_number=number,
                comment_id=2,
            ),
        ],
    }


def _comment(
    body: str,
    *,
    repo: str,
    issue_number: int,
    comment_id: int,
    created_at: str | None = None,
    author: str = TRUSTED_COMMENT_AUTHOR,
) -> dict[str, Any]:
    # Mirrors the shape of a ``gh issue list --json comments`` comment row, whose
    # author is a nested login object. Defaults to the trusted uptime-workflow
    # author; the untrusted-evidence contract overrides it.
    return {
        "body": body,
        "createdAt": created_at or body.split(" ", 1)[0],
        "url": f"https://github.com/{repo}/issues/{issue_number}#issuecomment-{comment_id}",
        "author": {"login": author},
    }


def _bead(
    bead_id: str,
    *,
    status: str,
    comments: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    # The bridge decides whether to heartbeat or propose closure by inspecting a
    # bead's persisted comments, so the fake bead carries comments only — no
    # synthetic heartbeat_at / closure_proposed_at fields that no recorded
    # `bd comments add` call would ever update.
    return {
        "id": bead_id,
        "status": status,
        "comments": list(comments) if comments else [],
    }


def _opaque_lookup_bead_id(label: str) -> str:
    """Return an id that a bridge can learn only from the fake ``bd list`` row."""
    return f"lookup-returned-{label}-{uuid4().hex}"


def _bead_list_row(bead: dict[str, Any]) -> dict[str, Any]:
    """Return the count-only issue shape emitted by pinned ``bd list --json``."""
    return {
        "id": bead["id"],
        "title": bead.get("title", "uptime incident bridge bead"),
        "description": bead.get("description", ""),
        "status": bead["status"],
        "priority": 1,
        "issue_type": "bug",
        "created_at": "2026-08-15T17:45:00Z",
        "updated_at": "2026-08-15T17:45:00Z",
        "dependency_count": 0,
        "dependent_count": 0,
        "comment_count": len(bead.get("comments", [])),
    }


def _bead_comment(bead_id: str, text: str, *, sequence: int) -> dict[str, str]:
    """Return the JSON object emitted by ``bd comments <id> --json``."""
    return {
        "id": f"comment-{sequence}",
        "issue_id": bead_id,
        "author": "uptime-incident-bridge",
        "text": text,
        "created_at": f"{TODAY_ISO}T12:00:00Z",
    }


def _option_value(argv: list[str], option: str) -> str:
    return argv[argv.index(option) + 1]


def _gh_issue_list_argv(repo: str, state: str) -> list[str]:
    argv = [
        "gh",
        "issue",
        "list",
        "-R",
        repo,
        "--label",
        "uptime-incident",
        "--state",
        state,
    ]
    if state == "closed":
        argv.extend(("--limit", "10"))
    return [*argv, "--json", ISSUE_JSON_FIELDS]


def _bd_lookup_argv(external_ref: str) -> list[str]:
    return ["bd", "list", "--external-ref", external_ref, "--all", "--json"]


def _assert_gh_issue_list_call(runner: FakeCommandRunner, *, repo: str, state: str) -> None:
    assert _gh_issue_list_argv(repo, state) in runner.calls


def _assert_gh_issue_list_call_before(runner: FakeCommandRunner, *, repo: str, state: str, end_index: int) -> None:
    assert _gh_issue_list_argv(repo, state) in runner.calls[:end_index]


def _assert_bd_lookup_before(runner: FakeCommandRunner, external_ref: str, *, end_index: int) -> None:
    assert _bd_lookup_argv(external_ref) in runner.calls[:end_index]


def _assert_complete_incident_read_set_was_attempted(runner: FakeCommandRunner) -> None:
    for repo in (STAGING_REPO, PROD_REPO):
        for state in ("open", "closed"):
            _assert_gh_issue_list_call(runner, repo=repo, state=state)


def _assert_bd_lookup(runner: FakeCommandRunner, external_ref: str) -> None:
    assert _bd_lookup_argv(external_ref) in runner.calls


def _assert_bd_lookup_after(runner: FakeCommandRunner, external_ref: str, *, start_index: int) -> None:
    assert _bd_lookup_argv(external_ref) in runner.calls[start_index:]


def _assert_bd_comment_read(runner: FakeCommandRunner, bead_id: str) -> None:
    assert ["bd", "comments", bead_id, "--json"] in runner.calls


def _assert_bd_comment_read_after(runner: FakeCommandRunner, bead_id: str, *, start_index: int) -> None:
    assert ["bd", "comments", bead_id, "--json"] in runner.calls[start_index:]


def _assert_create_call(
    runner: FakeCommandRunner,
    *,
    external_ref: str,
    title: str,
    issue_url: str,
    latest_probe: str,
    old_probe: str,
) -> None:
    create_call = next(call for call in runner.calls if call[:2] == ["bd", "create"] and external_ref in call)
    assert "--type" in create_call
    assert _option_value(create_call, "--type") == "bug"
    assert "--priority" in create_call
    assert _option_value(create_call, "--priority") == "1"
    assert "--title" in create_call
    assert _option_value(create_call, "--title") == title
    assert "--external-ref" in create_call
    assert _option_value(create_call, "--external-ref") == external_ref
    assert "--description" in create_call
    description = _option_value(create_call, "--description")
    assert issue_url in description
    assert latest_probe in description
    assert old_probe not in description


def _bd_comment_calls(runner: FakeCommandRunner) -> list[list[str]]:
    return [call for call in runner.calls if call[:3] == ["bd", "comments", "add"]]


def _count_bd_create_calls(runner: FakeCommandRunner) -> int:
    return sum(1 for call in runner.calls if call[:2] == ["bd", "create"])


def _count_calls(runner: FakeCommandRunner, expected_call: list[str]) -> int:
    return sum(1 for call in runner.calls if call == expected_call)


def shlex_join(argv: list[str]) -> str:

    return shlex.join(argv)


def _is_bd_write_call(call: list[str]) -> bool:
    return (
        call[:2] == ["bd", "create"]
        or call[:3] == ["bd", "comments", "add"]
        or call
        == [
            "bd",
            "dolt",
            "push",
        ]
    )


def _is_local_bd_mutation(call: list[str]) -> bool:
    return call[:2] == ["bd", "create"] or call[:3] == ["bd", "comments", "add"]
