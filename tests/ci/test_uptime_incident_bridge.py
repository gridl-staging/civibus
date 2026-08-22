"""Contract tests for the local uptime-incident to Bead bridge."""

import json

from pathlib import Path

import pytest

from test_support.uptime_incident_bridge_support import (
    CLOSURE_MARKER,
    HEARTBEAT_MARKER,
    PROD_EXTERNAL_REF,
    PROD_REPO,
    STAGING_EXTERNAL_REF,
    STAGING_REPO,
    TODAY_ISO,
    FakeCommandRunner,
    FakeResult,
    _assert_bd_comment_read,
    _assert_bd_comment_read_after,
    _assert_bd_lookup,
    _assert_bd_lookup_after,
    _assert_bd_lookup_before,
    _assert_complete_incident_read_set_was_attempted,
    _assert_create_call,
    _assert_gh_issue_list_call,
    _assert_gh_issue_list_call_before,
    _bd_comment_calls,
    _bd_lookup_argv,
    _bead,
    _bead_list_row,
    _comment,
    _count_bd_create_calls,
    _count_calls,
    _gh_issue_list_argv,
    _issue,
    _opaque_lookup_bead_id,
    _option_value,
    _run_bridge,
)

pytestmark = pytest.mark.dev_repo_only(
    private_asset="scripts/uptime_incident_bridge.py",
    owner="uptime incident bridge contract",
)


def test_new_open_incidents_create_beads_for_allowlisted_mirrors(tmp_path: Path) -> None:
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [_issue(number=6, repo=STAGING_REPO, title="Staging health check red")],
            (PROD_REPO, "open"): [_issue(number=3, repo=PROD_REPO, title="Production health check red")],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [],
        }
    )

    assert _run_bridge(runner, lock_path=tmp_path) == 0

    _assert_gh_issue_list_call(runner, repo=STAGING_REPO, state="open")
    _assert_gh_issue_list_call(runner, repo=PROD_REPO, state="open")
    _assert_bd_lookup(runner, STAGING_EXTERNAL_REF)
    _assert_bd_lookup(runner, PROD_EXTERNAL_REF)
    _assert_create_call(
        runner,
        external_ref=STAGING_EXTERNAL_REF,
        title=f"[BUG {TODAY_ISO}] uptime incident: Staging health check red",
        issue_url="https://github.com/gridl-staging/civibus/issues/6",
        latest_probe="2026-08-15T18:30:00Z red probe: HTTP 500 /health",
        old_probe="2026-08-15T18:00:00Z red probe: HTTP 503 /health",
    )
    _assert_create_call(
        runner,
        external_ref=PROD_EXTERNAL_REF,
        title=f"[BUG {TODAY_ISO}] uptime incident: Production health check red",
        issue_url="https://github.com/gridl-hq/civibus/issues/3",
        latest_probe="2026-08-15T18:30:00Z red probe: HTTP 500 /health",
        old_probe="2026-08-15T18:00:00Z red probe: HTTP 503 /health",
    )
    assert runner.calls[-1] == ["bd", "dolt", "push"]
    assert _count_bd_create_calls(runner) == 2
    assert _count_calls(runner, ["bd", "dolt", "push"]) == 1


def test_new_open_incident_without_comments_uses_issue_body_red_probe_evidence(tmp_path: Path) -> None:
    initial_red_evidence = """The https://staging.civibus.example production uptime probe detected red surface(s): /api/health/content returned 503.

The https://staging.civibus.example content health probe failed.

**Status:** 503
**Detail:** required content rows are stale
**Probe time:** 2026-08-15T17:45:00Z
**Workflow run:** https://github.com/gridl-staging/civibus/actions/runs/333

- Endpoint: https://staging.civibus.example/api/health/content
- Owner: api/health_content.py + api/main.py:186
"""
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [
                _issue(
                    number=6,
                    repo=STAGING_REPO,
                    title="Staging health check red",
                    body=initial_red_evidence,
                    comments=[],
                )
            ],
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [],
        }
    )

    assert _run_bridge(runner, lock_path=tmp_path) == 0

    _assert_gh_issue_list_call(runner, repo=STAGING_REPO, state="open")
    create_call = next(call for call in runner.calls if call[:2] == ["bd", "create"])
    description = _option_value(create_call, "--description")
    assert "https://github.com/gridl-staging/civibus/issues/6" in description
    assert initial_red_evidence in description
    assert _count_bd_create_calls(runner) == 1
    assert runner.calls[-1] == ["bd", "dolt", "push"]


def test_second_consecutive_run_against_unchanged_input_is_noop(tmp_path: Path) -> None:
    # One stateful fake, run twice: the first run must heartbeat an already-open
    # incident bead and propose closure on a recovered one; the second run must
    # observe those persisted comments and perform zero further writes. This
    # proves non-spamming (no duplicate heartbeats, no repeated closure spam)
    # rather than merely proving a single run is quiet.
    staging_bead_id = _opaque_lookup_bead_id("staging")
    prod_bead_id = _opaque_lookup_bead_id("prod")
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [_issue(number=6, repo=STAGING_REPO, title="Staging health check red")],
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [
                _issue(
                    number=3,
                    repo=PROD_REPO,
                    title="Production health check recovered",
                    comments=[
                        _comment(
                            "2026-08-15T18:30:00Z red probe: HTTP 500 /health",
                            repo=PROD_REPO,
                            issue_number=3,
                            comment_id=43,
                        ),
                        _comment(
                            "Probe at 2026-08-15T19:00:00Z returned 200 healthy. Endpoint recovered. Closing.",
                            repo=PROD_REPO,
                            issue_number=3,
                            comment_id=44,
                            created_at="2026-08-15T19:00:00Z",
                        ),
                    ],
                )
            ],
        },
        beads_by_external_ref={
            STAGING_EXTERNAL_REF: [_bead(staging_bead_id, status="open")],
            PROD_EXTERNAL_REF: [_bead(prod_bead_id, status="open")],
        },
    )

    assert _run_bridge(runner, lock_path=tmp_path) == 0

    # First run acted on both replay paths, so the no-op below is a genuine
    # second-run property and not a bridge that never writes anything.
    first_run_writes = list(runner.bd_write_calls)
    assert _count_bd_create_calls(runner) == 0
    assert any(HEARTBEAT_MARKER in " ".join(call[4:]) for call in _bd_comment_calls(runner))
    assert any(CLOSURE_MARKER in " ".join(call[4:]) for call in _bd_comment_calls(runner))
    assert ["bd", "dolt", "push"] in first_run_writes

    second_run_start = len(runner.calls)
    assert _run_bridge(runner, lock_path=tmp_path) == 0

    _assert_bd_lookup_after(runner, STAGING_EXTERNAL_REF, start_index=second_run_start)
    _assert_bd_lookup_after(runner, PROD_EXTERNAL_REF, start_index=second_run_start)
    _assert_bd_comment_read_after(runner, staging_bead_id, start_index=second_run_start)
    _assert_bd_comment_read_after(runner, prod_bead_id, start_index=second_run_start)

    # No new bd create / comments add / dolt push calls on the second run.
    assert runner.bd_write_calls == first_run_writes


def test_existing_open_bridge_bead_receives_one_dated_heartbeat_comment_only(tmp_path: Path) -> None:
    lookup_bead_id = _opaque_lookup_bead_id("heartbeat")
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [_issue(number=6, repo=STAGING_REPO, title="Staging health check red")],
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [],
        },
        beads_by_external_ref={STAGING_EXTERNAL_REF: [_bead(lookup_bead_id, status="open")]},
    )

    assert _run_bridge(runner, lock_path=tmp_path) == 0

    _assert_bd_comment_read(runner, lookup_bead_id)
    comment_calls = _bd_comment_calls(runner)
    assert len(comment_calls) == 1
    assert comment_calls[0][:4] == ["bd", "comments", "add", lookup_bead_id]
    comment_text = " ".join(comment_calls[0][4:])
    assert HEARTBEAT_MARKER in comment_text
    assert "https://github.com/gridl-staging/civibus/issues/6" in comment_text
    assert _count_bd_create_calls(runner) == 0
    assert runner.calls[-1] == ["bd", "dolt", "push"]
    assert _count_calls(runner, ["bd", "dolt", "push"]) == 1


def test_closed_incident_with_open_bridge_bead_adds_closure_proposal_without_closing_bead(tmp_path: Path) -> None:
    lookup_bead_id = _opaque_lookup_bead_id("closure")
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [],
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [
                _issue(
                    number=6,
                    repo=STAGING_REPO,
                    title="Staging health check recovered",
                    comments=[
                        _comment(
                            "2026-08-15T18:30:00Z red probe: HTTP 500 /health",
                            repo=STAGING_REPO,
                            issue_number=6,
                            comment_id=43,
                        ),
                        _comment(
                            "Probe at 2026-08-15T19:00:00Z returned 200 healthy. Endpoint recovered. Closing.",
                            repo=STAGING_REPO,
                            issue_number=6,
                            comment_id=44,
                            created_at="2026-08-15T19:00:00Z",
                        ),
                    ],
                )
            ],
            (PROD_REPO, "closed"): [],
        },
        beads_by_external_ref={STAGING_EXTERNAL_REF: [_bead(lookup_bead_id, status="open")]},
    )

    assert _run_bridge(runner, lock_path=tmp_path) == 0

    _assert_bd_comment_read(runner, lookup_bead_id)
    comment_calls = _bd_comment_calls(runner)
    assert len(comment_calls) == 1
    assert comment_calls[0][:4] == ["bd", "comments", "add", lookup_bead_id]
    comment_text = " ".join(comment_calls[0][4:])
    assert CLOSURE_MARKER in comment_text
    assert "https://github.com/gridl-staging/civibus/issues/6#issuecomment-44" in comment_text
    assert "actions/runs/" not in comment_text
    assert not any(call[:3] == ["bd", "close", lookup_bead_id] for call in runner.calls)
    assert runner.calls[-1] == ["bd", "dolt", "push"]


def test_gh_issue_list_failure_fails_closed_without_bd_write_calls(tmp_path: Path) -> None:
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [],
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [],
        },
        gh_failures={
            (STAGING_REPO, "open"): FakeResult(
                args=[],
                returncode=2,
                stderr="gh auth required",
            )
        },
    )

    assert _run_bridge(runner, lock_path=tmp_path) != 0

    _assert_gh_issue_list_call(runner, repo=STAGING_REPO, state="open")
    assert runner.bd_write_calls == []


def test_malformed_or_indeterminate_issue_json_fails_closed_without_bd_write_calls(tmp_path: Path) -> None:
    malformed_runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): "{not-json",
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [],
        }
    )
    missing_fields_runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [{"number": 6, "title": "missing comments"}],
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [],
        }
    )

    assert _run_bridge(malformed_runner, lock_path=tmp_path) != 0
    assert _run_bridge(missing_fields_runner, lock_path=tmp_path) != 0

    _assert_gh_issue_list_call(malformed_runner, repo=STAGING_REPO, state="open")
    _assert_gh_issue_list_call(missing_fields_runner, repo=STAGING_REPO, state="open")
    assert malformed_runner.bd_write_calls == []
    assert missing_fields_runner.bd_write_calls == []


def test_comment_read_failure_or_indeterminate_json_fails_closed_without_bd_write_calls(tmp_path: Path) -> None:
    issues = {
        (STAGING_REPO, "open"): [_issue(number=6, repo=STAGING_REPO, title="Staging health check red")],
        (PROD_REPO, "open"): [_issue(number=3, repo=PROD_REPO, title="Production health check red")],
        (STAGING_REPO, "closed"): [],
        (PROD_REPO, "closed"): [],
    }
    failed_read_bead_id = _opaque_lookup_bead_id("failed-read")
    indeterminate_read_bead_id = _opaque_lookup_bead_id("malformed-read")
    semantic_read_bead_id = _opaque_lookup_bead_id("semantic-read")
    beads = {PROD_EXTERNAL_REF: [_bead(failed_read_bead_id, status="open")]}
    failed_read_runner = FakeCommandRunner(
        issues_by_repo_and_state=issues,
        beads_by_external_ref=beads,
        bd_read_results_by_argv={
            ("bd", "comments", failed_read_bead_id, "--json"): FakeResult(
                args=[], returncode=2, stderr="comment read failed"
            )
        },
    )
    indeterminate_read_runner = FakeCommandRunner(
        issues_by_repo_and_state=issues,
        beads_by_external_ref={PROD_EXTERNAL_REF: [_bead(indeterminate_read_bead_id, status="open")]},
        bd_read_results_by_argv={
            ("bd", "comments", indeterminate_read_bead_id, "--json"): FakeResult(args=[], stdout="{not-json")
        },
    )
    semantic_indeterminate_runner = FakeCommandRunner(
        issues_by_repo_and_state=issues,
        beads_by_external_ref={PROD_EXTERNAL_REF: [_bead(semantic_read_bead_id, status="open")]},
        bd_read_results_by_argv={
            ("bd", "comments", semantic_read_bead_id, "--json"): FakeResult(
                args=[],
                stdout=json.dumps(
                    [
                        {
                            "id": "comment-1",
                            "issue_id": semantic_read_bead_id,
                            "author": "uptime-incident-bridge",
                            "created_at": f"{TODAY_ISO}T12:00:00Z",
                        }
                    ]
                ),
            )
        },
    )

    assert _run_bridge(failed_read_runner, lock_path=tmp_path) != 0
    assert _run_bridge(indeterminate_read_runner, lock_path=tmp_path) != 0
    assert _run_bridge(semantic_indeterminate_runner, lock_path=tmp_path) != 0

    for runner, lookup_bead_id in (
        (failed_read_runner, failed_read_bead_id),
        (indeterminate_read_runner, indeterminate_read_bead_id),
        (semantic_indeterminate_runner, semantic_read_bead_id),
    ):
        # The later prod comment read must have happened, and the earlier staging
        # incident must have reached its valid create-candidate point before it:
        # staging's open query succeeded and its idempotency lookup found no
        # existing bead. Pinning this ordering proves the run withholds an
        # already-discovered staging write when a *subsequent* prod read fails,
        # rather than failing on prod before any candidate ever existed.
        _assert_bd_comment_read(runner, lookup_bead_id)
        comment_read_index = runner.calls.index(["bd", "comments", lookup_bead_id, "--json"])
        _assert_gh_issue_list_call_before(runner, repo=STAGING_REPO, state="open", end_index=comment_read_index)
        _assert_bd_lookup_before(runner, STAGING_EXTERNAL_REF, end_index=comment_read_index)
        assert runner.beads_by_external_ref.get(STAGING_EXTERNAL_REF) is None
        assert runner.bd_write_calls == []


def test_bead_lookup_failure_or_indeterminate_json_fails_closed_without_bd_write_calls(tmp_path: Path) -> None:
    issues = {
        (STAGING_REPO, "open"): [_issue(number=6, repo=STAGING_REPO, title="Staging health check red")],
        (PROD_REPO, "open"): [_issue(number=3, repo=PROD_REPO, title="Production health check red")],
        (STAGING_REPO, "closed"): [],
        (PROD_REPO, "closed"): [],
    }
    duplicate_rows = [
        {**_bead_list_row(_bead(_opaque_lookup_bead_id(label), status="open")), "external_ref": PROD_EXTERNAL_REF}
        for label in ("duplicate-one", "duplicate-two")
    ]
    invalid_results = (
        FakeResult(args=[], returncode=2, stderr="bead lookup failed"),
        FakeResult(args=[], stdout="{not-json"),
        FakeResult(args=[], stdout=json.dumps([{"status": "open", "comment_count": 0}])),
        FakeResult(args=[], stdout=json.dumps(duplicate_rows)),
    )

    for invalid_result in invalid_results:
        runner = FakeCommandRunner(
            issues_by_repo_and_state=issues,
            bd_read_results_by_argv={tuple(_bd_lookup_argv(PROD_EXTERNAL_REF)): invalid_result},
        )

        assert _run_bridge(runner, lock_path=tmp_path) != 0

        staging_lookup = _bd_lookup_argv(STAGING_EXTERNAL_REF)
        prod_lookup = _bd_lookup_argv(PROD_EXTERNAL_REF)
        assert runner.calls.index(staging_lookup) < runner.calls.index(prod_lookup)
        assert runner.beads_by_external_ref.get(STAGING_EXTERNAL_REF) is None
        assert runner.bd_write_calls == []


def test_valid_earlier_repo_write_is_withheld_when_a_later_gh_query_fails(tmp_path: Path) -> None:
    # Staging carries a valid new-incident create candidate; the prod query
    # fails. The whole run must fail closed with zero writes, proving the bridge
    # commits nothing until every source has been read successfully rather than
    # writing per-repository as it goes.
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [_issue(number=6, repo=STAGING_REPO, title="Staging health check red")],
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [],
        },
        gh_failures={
            (PROD_REPO, "open"): FakeResult(args=[], returncode=2, stderr="gh auth required"),
        },
    )

    assert _run_bridge(runner, lock_path=tmp_path) != 0

    prod_open_call = _gh_issue_list_argv(PROD_REPO, "open")
    prod_open_index = runner.calls.index(prod_open_call)
    _assert_gh_issue_list_call_before(runner, repo=STAGING_REPO, state="open", end_index=prod_open_index)
    assert runner.bd_write_calls == []


def test_valid_earlier_repo_write_is_withheld_when_a_later_response_is_indeterminate(tmp_path: Path) -> None:
    # Staging carries a valid create candidate; prod returns malformed JSON. The
    # run must fail closed with zero writes across every repository.
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [_issue(number=6, repo=STAGING_REPO, title="Staging health check red")],
            (PROD_REPO, "open"): "{not-json",
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [],
        }
    )

    assert _run_bridge(runner, lock_path=tmp_path) != 0

    prod_open_call = _gh_issue_list_argv(PROD_REPO, "open")
    prod_open_index = runner.calls.index(prod_open_call)
    _assert_gh_issue_list_call_before(runner, repo=STAGING_REPO, state="open", end_index=prod_open_index)
    assert runner.bd_write_calls == []


def test_open_write_candidate_is_withheld_when_later_closed_query_fails(tmp_path: Path) -> None:
    # Both open reads and the earlier staging closed read succeed before the
    # final prod closed read fails. No open-incident create may escape before
    # the bridge has validated the complete incident read set.
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [_issue(number=6, repo=STAGING_REPO, title="Staging health check red")],
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): [],
        },
        gh_failures={
            (PROD_REPO, "closed"): FakeResult(args=[], returncode=2, stderr="gh auth required"),
        },
    )

    assert _run_bridge(runner, lock_path=tmp_path) != 0

    _assert_complete_incident_read_set_was_attempted(runner)
    assert runner.bd_write_calls == []


def test_open_write_candidate_is_withheld_when_later_closed_response_is_indeterminate(tmp_path: Path) -> None:
    # The final prod closed read returns malformed JSON only after every open
    # read and the staging closed read have succeeded. The run remains atomic.
    runner = FakeCommandRunner(
        issues_by_repo_and_state={
            (STAGING_REPO, "open"): [_issue(number=6, repo=STAGING_REPO, title="Staging health check red")],
            (PROD_REPO, "open"): [],
            (STAGING_REPO, "closed"): [],
            (PROD_REPO, "closed"): "{not-json",
        }
    )

    assert _run_bridge(runner, lock_path=tmp_path) != 0

    _assert_complete_incident_read_set_was_attempted(runner)
    assert runner.bd_write_calls == []
