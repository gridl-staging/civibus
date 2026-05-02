from __future__ import annotations

from dataclasses import dataclass
import sys
import types
from uuid import UUID, uuid4

import pytest

from core.entity_resolution.cli import _build_argument_parser, _resolve_splink_version, main
from core.graph import age_post_connect


class _FakeConnection:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.close_calls = 0
        self.execute_calls: list[str] = []

    def commit(self) -> None:
        self.commit_calls += 1

    def execute(self, statement: str) -> None:
        self.execute_calls.append(statement)

    def close(self) -> None:
        self.close_calls += 1


def test_resolve_splink_version_returns_module_attribute_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "splink", types.SimpleNamespace(__version__="4.0.16"))
    assert _resolve_splink_version() == "4.0.16"


def test_resolve_splink_version_falls_back_to_unknown_when_metadata_has_no_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "splink", types.SimpleNamespace())
    monkeypatch.setattr("importlib.metadata.version", lambda _: None)
    assert _resolve_splink_version() == "unknown"


def _install_connection_hooks(
    monkeypatch: pytest.MonkeyPatch,
    conn: object,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def _fake_get_connection(*, post_connect: object) -> object:
        captured["post_connect"] = post_connect
        return conn

    def _fake_ensure_graph(connection: object) -> None:
        captured["ensure_graph_connection"] = connection

    monkeypatch.setattr("core.entity_resolution.cli.get_connection", _fake_get_connection)
    monkeypatch.setattr("core.entity_resolution.cli.ensure_graph", _fake_ensure_graph)
    return captured


def _classified_pair(
    entity_id_a: UUID,
    entity_id_b: UUID,
    *,
    confidence: float,
    decision: str,
) -> dict[str, object]:
    return {
        "entity_id_a": min(entity_id_a, entity_id_b),
        "entity_id_b": max(entity_id_a, entity_id_b),
        "confidence": confidence,
        "decision": decision,
        "decision_method": "probabilistic",
        "decided_by": "splink_v1",
    }


@dataclass
class _RunActionFixtureSet:
    entity_rows: list[dict[str, object]]
    scored_pairs: list[dict[str, object]]
    classified_pairs: list[dict[str, object]]
    clustered: dict[str, object]
    run_id: UUID
    call_order: list[str]
    completion_counts: dict[str, int]
    completion_duration: list[float]


def _build_run_action_fixture_set() -> _RunActionFixtureSet:
    entity_rows = [{"id": uuid4()}, {"id": uuid4()}, {"id": uuid4()}]
    scored_pairs = [
        {
            "entity_id_a": entity_rows[0]["id"],
            "entity_id_b": entity_rows[1]["id"],
            "confidence": 0.96,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]
    classified_pairs = [
        _classified_pair(
            entity_rows[0]["id"],
            entity_rows[1]["id"],
            confidence=0.97,
            decision="match",
        ),
        _classified_pair(
            entity_rows[1]["id"],
            entity_rows[2]["id"],
            confidence=0.82,
            decision="probable_match",
        ),
        _classified_pair(
            entity_rows[0]["id"],
            entity_rows[2]["id"],
            confidence=0.55,
            decision="no_match",
        ),
    ]
    clustered = {
        "auto_merge_clusters": [
            {
                "member_ids": {entity_rows[0]["id"], entity_rows[1]["id"]},
                "canonical_entity_id": entity_rows[0]["id"],
                "min_confidence": 0.97,
                "min_decision": "match",
                "links": [classified_pairs[0]],
            }
        ],
        "review_components": [
            {
                "member_ids": {entity_rows[1]["id"], entity_rows[2]["id"]},
                "min_confidence": 0.82,
                "min_decision": "probable_match",
                "links": [classified_pairs[1]],
            }
        ],
        "pairwise_decisions": classified_pairs,
    }
    return _RunActionFixtureSet(
        entity_rows=entity_rows,
        scored_pairs=scored_pairs,
        classified_pairs=classified_pairs,
        clustered=clustered,
        run_id=uuid4(),
        call_order=[],
        completion_counts={},
        completion_duration=[],
    )


def _patch_run_action_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    fixtures: _RunActionFixtureSet,
) -> None:
    monkeypatch.setattr(
        "core.entity_resolution.cli._require_splink_runtime_available",
        lambda *_: fixtures.call_order.append("require_runtime"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli._resolve_splink_version",
        lambda: "9.9.9",
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.log_splink_run_start",
        lambda *args, **kwargs: fixtures.call_order.append("log_start") or fixtures.run_id,
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.extract_rows_for_matching",
        lambda conn, entity_type: fixtures.call_order.append("extract_rows") or fixtures.entity_rows,
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.score_entities",
        lambda conn, entity_type: fixtures.call_order.append("score") or fixtures.scored_pairs,
    )

    def _fake_classify(
        pairs: list[dict[str, object]],
        *,
        auto_merge_threshold: float | None = None,
    ) -> list[dict[str, object]]:
        fixtures.call_order.append("classify")
        assert pairs == fixtures.scored_pairs
        assert auto_merge_threshold == pytest.approx(0.91)
        return fixtures.classified_pairs

    monkeypatch.setattr("core.entity_resolution.cli.classify_scored_pairs", _fake_classify)

    def _fake_cluster(pairs: object, rows: object) -> dict[str, object]:
        fixtures.call_order.append("cluster")
        assert pairs == fixtures.classified_pairs
        assert rows == fixtures.entity_rows
        return fixtures.clustered

    monkeypatch.setattr(
        "core.entity_resolution.cli.cluster_scored_pairs",
        _fake_cluster,
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.persist_match_decisions",
        lambda conn, pairs, entity_type: fixtures.call_order.append("persist_match"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.persist_auto_merge_clusters",
        lambda conn, clusters, entity_type: fixtures.call_order.append("persist_clusters"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.materialize_er_edges",
        lambda conn, pairs, entity_type: fixtures.call_order.append("materialize_edges"),
    )

    def _fake_log_complete(
        conn: object,
        in_run_id: UUID,
        *,
        completed_at: object,
        duration_seconds: float,
        counts: dict[str, int],
    ) -> None:
        fixtures.call_order.append("log_complete")
        assert in_run_id == fixtures.run_id
        fixtures.completion_counts.update(counts)
        fixtures.completion_duration.append(duration_seconds)

    monkeypatch.setattr("core.entity_resolution.cli.log_splink_run_complete", _fake_log_complete)
    monkeypatch.setattr(
        "core.entity_resolution.cli.log_splink_run_failed",
        lambda *args, **kwargs: pytest.fail("successful run should not log_splink_run_failed"),
    )


def _assert_run_action_pipeline_call_order(call_order: list[str]) -> None:
    assert call_order == [
        "require_runtime",
        "log_start",
        "extract_rows",
        "score",
        "classify",
        "cluster",
        "persist_match",
        "persist_clusters",
        "materialize_edges",
        "log_complete",
    ]


def _assert_run_action_completion_counts(completion_counts: dict[str, int]) -> None:
    assert completion_counts == {
        "input_record_count": 3,
        "pairs_compared": 3,
        "matches_found": 2,
        "auto_merged": 1,
        "probable_matches": 1,
        "possible_matches": 0,
    }


def _assert_run_action_summary_output(output: str) -> None:
    assert "Entity resolution run summary (person)" in output
    assert "auto_merge_clusters: 1" in output
    assert "review_components: 1" in output
    assert "age_edges_materialized: 1" in output


def test_build_argument_parser_accepts_expected_flags() -> None:
    parser = _build_argument_parser()

    defaults = parser.parse_args(["--entity-type", "person"])
    assert defaults.entity_type == "person"
    assert defaults.action == "run"
    assert defaults.min_threshold is None
    assert defaults.dry_run is False

    with_flags = parser.parse_args(
        [
            "--entity-type",
            "organization",
            "--action",
            "cluster",
            "--min-threshold",
            "0.91",
            "--dry-run",
        ]
    )
    assert with_flags.entity_type == "organization"
    assert with_flags.action == "cluster"
    assert with_flags.min_threshold == pytest.approx(0.91)
    assert with_flags.dry_run is True

    resolve_action = parser.parse_args(
        [
            "--entity-type",
            "person",
            "--action",
            "resolve-transaction-counterparties",
        ]
    )
    assert resolve_action.action == "resolve-transaction-counterparties"


def test_build_argument_parser_allows_resolve_transaction_counterparties_without_entity_type() -> None:
    parser = _build_argument_parser()

    args = parser.parse_args(["--action", "resolve-transaction-counterparties"])

    assert args.action == "resolve-transaction-counterparties"
    assert args.entity_type is None


@pytest.mark.parametrize(
    ("argv", "error_text"),
    [
        (["--entity-type", "committee"], "invalid choice"),
        (["--entity-type", "person", "--action", "merge"], "invalid choice"),
    ],
)
def test_build_argument_parser_rejects_invalid_choices(
    argv: list[str],
    error_text: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = _build_argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(argv)

    assert error_text in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "error_text"),
    [
        (
            ["--entity-type", "person", "--action", "run", "--min-threshold", "0.80"],
            "auto_merge_threshold must be greater than THRESHOLD_PROBABLE",
        ),
        (
            ["--entity-type", "person", "--action", "score", "--min-threshold", "nan"],
            "auto_merge_threshold must be a finite float.",
        ),
        (
            ["--entity-type", "person", "--action", "block", "--min-threshold", "0.91"],
            "--min-threshold is only supported for 'run', 'score', and 'cluster' actions.",
        ),
    ],
)
def test_main_rejects_invalid_min_threshold_arguments(
    argv: list[str],
    error_text: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail_get_connection(**_: object) -> object:
        pytest.fail("invalid threshold arguments should fail before opening a connection")

    monkeypatch.setattr(
        "core.entity_resolution.cli.get_connection",
        _fail_get_connection,
    )

    exit_code = main(argv)

    assert exit_code == 1
    assert error_text in capsys.readouterr().err


def test_main_action_block_prints_rule_and_pair_count_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection()
    hooks = _install_connection_hooks(monkeypatch, connection)

    rows = [{"id": uuid4(), "canonical_name": "Example"}]
    blocking_rules = [
        {"rule_index": 0, "blocking_rule": "l.last_name = r.last_name"},
        {"rule_index": 1, "blocking_rule": "l.zip5 = r.zip5"},
    ]
    pair_counts = [
        {"rule_index": 0, "blocking_rule": "l.last_name = r.last_name", "pair_count": 9},
        {"rule_index": 1, "blocking_rule": "l.zip5 = r.zip5", "pair_count": 4},
    ]
    call_order: list[str] = []

    monkeypatch.setattr(
        "core.entity_resolution.cli._require_splink_runtime_available",
        lambda action, entity_type: call_order.append("require_runtime"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.extract_rows_for_matching",
        lambda conn, entity_type: call_order.append("extract_rows") or rows,
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.describe_blocking_rules",
        lambda entity_type: call_order.append("describe_rules") or blocking_rules,
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.count_blocked_pairs",
        lambda in_rows, entity_type: call_order.append("count_pairs") or pair_counts,
    )

    exit_code = main(["--entity-type", "person", "--action", "block"])

    assert exit_code == 0
    assert call_order == ["require_runtime", "extract_rows", "describe_rules", "count_pairs"]
    assert hooks["post_connect"] is age_post_connect
    assert hooks["ensure_graph_connection"] is connection
    assert connection.commit_calls == 1
    assert connection.close_calls == 1

    output = capsys.readouterr().out
    assert "Blocking diagnostics (person)" in output
    assert "l.last_name = r.last_name" in output
    assert "pairs=9" in output
    assert "l.zip5 = r.zip5" in output
    assert "pairs=4" in output


def test_main_action_score_prints_decision_tier_breakdown(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection()
    _install_connection_hooks(monkeypatch, connection)

    scored_pairs = [
        {
            "entity_id_a": uuid4(),
            "entity_id_b": uuid4(),
            "confidence": 0.97,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]
    classified_pairs = [
        _classified_pair(uuid4(), uuid4(), confidence=0.98, decision="match"),
        _classified_pair(uuid4(), uuid4(), confidence=0.87, decision="probable_match"),
        _classified_pair(uuid4(), uuid4(), confidence=0.65, decision="possible_match"),
        _classified_pair(uuid4(), uuid4(), confidence=0.20, decision="no_match"),
    ]
    classify_call_args: list[object] = []

    monkeypatch.setattr("core.entity_resolution.cli._require_splink_runtime_available", lambda *_: None)
    monkeypatch.setattr("core.entity_resolution.cli.score_entities", lambda conn, entity_type: scored_pairs)

    def _fake_classify(
        pairs: list[dict[str, object]],
        *,
        auto_merge_threshold: float | None = None,
    ) -> list[dict[str, object]]:
        classify_call_args.append((pairs, auto_merge_threshold))
        return classified_pairs

    monkeypatch.setattr("core.entity_resolution.cli.classify_scored_pairs", _fake_classify)

    exit_code = main(["--entity-type", "organization", "--action", "score"])

    assert exit_code == 0
    assert classify_call_args == [(scored_pairs, None)]
    assert connection.commit_calls == 1
    assert connection.close_calls == 1

    output = capsys.readouterr().out
    assert "Scored-pair decision tiers (organization)" in output
    assert "match: 1" in output
    assert "probable_match: 1" in output
    assert "possible_match: 1" in output
    assert "no_match: 1" in output


def test_main_action_run_executes_full_pipeline_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection()
    _install_connection_hooks(monkeypatch, connection)
    fixtures = _build_run_action_fixture_set()
    _patch_run_action_dependencies(monkeypatch, fixtures)

    exit_code = main(
        [
            "--entity-type",
            "person",
            "--action",
            "run",
            "--min-threshold",
            "0.91",
        ]
    )

    assert exit_code == 0
    _assert_run_action_pipeline_call_order(fixtures.call_order)
    _assert_run_action_completion_counts(fixtures.completion_counts)
    assert fixtures.completion_duration and fixtures.completion_duration[0] >= 0.0
    assert connection.commit_calls == 1
    assert connection.close_calls == 1
    assert connection.execute_calls == ["SAVEPOINT splink_run_execute"]

    _assert_run_action_summary_output(capsys.readouterr().out)


def test_main_action_run_dry_run_skips_commit_and_splink_run_logging(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection()
    _install_connection_hooks(monkeypatch, connection)

    entity_rows = [{"id": uuid4()}, {"id": uuid4()}]
    scored_pairs = [
        {
            "entity_id_a": entity_rows[0]["id"],
            "entity_id_b": entity_rows[1]["id"],
            "confidence": 0.96,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]
    classified_pairs = [
        _classified_pair(
            entity_rows[0]["id"],
            entity_rows[1]["id"],
            confidence=0.96,
            decision="match",
        )
    ]
    clustered = {
        "auto_merge_clusters": [
            {
                "member_ids": {entity_rows[0]["id"], entity_rows[1]["id"]},
                "canonical_entity_id": entity_rows[0]["id"],
                "min_confidence": 0.96,
                "min_decision": "match",
                "links": [classified_pairs[0]],
            }
        ],
        "review_components": [],
        "pairwise_decisions": classified_pairs,
    }
    called: list[str] = []

    monkeypatch.setattr("core.entity_resolution.cli._require_splink_runtime_available", lambda *_: None)
    monkeypatch.setattr("core.entity_resolution.cli.extract_rows_for_matching", lambda *_: entity_rows)
    monkeypatch.setattr("core.entity_resolution.cli.score_entities", lambda *_: scored_pairs)
    monkeypatch.setattr("core.entity_resolution.cli.classify_scored_pairs", lambda *_, **__: classified_pairs)

    def _fake_cluster(pairs: object, rows: object) -> dict[str, object]:
        assert pairs == classified_pairs
        assert rows == entity_rows
        return clustered

    monkeypatch.setattr("core.entity_resolution.cli.cluster_scored_pairs", _fake_cluster)
    monkeypatch.setattr(
        "core.entity_resolution.cli.persist_match_decisions",
        lambda *args, **kwargs: called.append("persist_match"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.persist_auto_merge_clusters",
        lambda *args, **kwargs: called.append("persist_cluster"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.materialize_er_edges",
        lambda *args, **kwargs: called.append("materialize"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.log_splink_run_start",
        lambda *args, **kwargs: pytest.fail("dry-run should skip log_splink_run_start"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.log_splink_run_complete",
        lambda *args, **kwargs: pytest.fail("dry-run should skip log_splink_run_complete"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.log_splink_run_failed",
        lambda *args, **kwargs: pytest.fail("dry-run should skip log_splink_run_failed"),
    )

    exit_code = main(["--entity-type", "person", "--action", "run", "--dry-run"])

    assert exit_code == 0
    assert called == ["persist_match", "persist_cluster", "materialize"]
    assert connection.commit_calls == 0
    assert connection.close_calls == 1
    assert connection.execute_calls == []
    assert "Dry-run mode: no commit performed." in capsys.readouterr().out


def test_main_action_cluster_scores_classifies_and_clusters_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection()
    _install_connection_hooks(monkeypatch, connection)

    entity_rows = [{"id": uuid4()}, {"id": uuid4()}, {"id": uuid4()}]
    scored_pairs = [
        {
            "entity_id_a": entity_rows[0]["id"],
            "entity_id_b": entity_rows[1]["id"],
            "confidence": 0.83,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
    ]
    classified_pairs = [
        _classified_pair(
            entity_rows[0]["id"],
            entity_rows[1]["id"],
            confidence=0.83,
            decision="probable_match",
        )
    ]
    clustered = {
        "auto_merge_clusters": [],
        "review_components": [
            {
                "member_ids": {entity_rows[0]["id"], entity_rows[1]["id"]},
                "min_confidence": 0.83,
                "min_decision": "probable_match",
                "links": [classified_pairs[0]],
            }
        ],
        "pairwise_decisions": classified_pairs,
    }
    call_order: list[str] = []

    monkeypatch.setattr(
        "core.entity_resolution.cli._require_splink_runtime_available",
        lambda *_: call_order.append("require_runtime"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.extract_rows_for_matching",
        lambda *_: call_order.append("extract_rows") or entity_rows,
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.score_entities",
        lambda *_: call_order.append("score") or scored_pairs,
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.classify_scored_pairs",
        lambda *_, **__: call_order.append("classify") or classified_pairs,
    )

    def _fake_cluster(pairs: object, rows: object) -> dict[str, object]:
        call_order.append("cluster")
        assert pairs == classified_pairs
        assert rows == entity_rows
        return clustered

    monkeypatch.setattr(
        "core.entity_resolution.cli.cluster_scored_pairs",
        _fake_cluster,
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.persist_match_decisions",
        lambda *_: pytest.fail("--action cluster must not persist decisions"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.persist_auto_merge_clusters",
        lambda *_: pytest.fail("--action cluster must not persist clusters"),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.materialize_er_edges",
        lambda *_: pytest.fail("--action cluster must not materialize graph edges"),
    )

    exit_code = main(["--entity-type", "organization", "--action", "cluster"])

    assert exit_code == 0
    assert call_order == [
        "require_runtime",
        "extract_rows",
        "score",
        "classify",
        "cluster",
    ]
    assert connection.commit_calls == 1
    assert connection.close_calls == 1

    output = capsys.readouterr().out
    assert "Cluster preview (organization)" in output
    assert "auto_merge_clusters: 0" in output
    assert "review_components: 1" in output


@pytest.mark.parametrize("action", ["block", "score", "run", "cluster"])
def test_main_returns_error_when_splink_runtime_is_unavailable(
    action: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection()
    _install_connection_hooks(monkeypatch, connection)

    monkeypatch.setattr(
        "core.entity_resolution.cli._require_splink_runtime_available",
        lambda *_: (_ for _ in ()).throw(RuntimeError("Splink runtime is required for probabilistic scoring.")),
    )

    exit_code = main(["--entity-type", "person", "--action", action])

    assert exit_code == 1
    assert connection.commit_calls == 0
    assert connection.close_calls == 1
    assert (
        "Entity resolution CLI failed: Splink runtime is required for probabilistic scoring." in capsys.readouterr().err
    )


def test_main_action_run_logs_failed_audit_row_when_pipeline_raises(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection()
    _install_connection_hooks(monkeypatch, connection)
    run_id = uuid4()
    failed_audit: dict[str, object] = {}

    monkeypatch.setattr("core.entity_resolution.cli._require_splink_runtime_available", lambda *_: None)
    monkeypatch.setattr("core.entity_resolution.cli._resolve_splink_version", lambda: "9.9.9")
    monkeypatch.setattr("core.entity_resolution.cli.log_splink_run_start", lambda *args, **kwargs: run_id)
    monkeypatch.setattr(
        "core.entity_resolution.cli.extract_rows_for_matching",
        lambda *_: [{"id": uuid4(), "canonical_name": "Failure Example"}],
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.score_entities",
        lambda *_: (_ for _ in ()).throw(RuntimeError("boom during score")),
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.log_splink_run_complete",
        lambda *args, **kwargs: pytest.fail("failed run should not log_splink_run_complete"),
    )

    def _fake_log_failed(
        conn: object,
        in_run_id: UUID,
        *,
        completed_at: object,
        duration_seconds: float,
        error_message: str,
    ) -> None:
        failed_audit["run_id"] = in_run_id
        failed_audit["duration_seconds"] = duration_seconds
        failed_audit["error_message"] = error_message

    monkeypatch.setattr("core.entity_resolution.cli.log_splink_run_failed", _fake_log_failed)

    exit_code = main(["--entity-type", "person", "--action", "run"])

    assert exit_code == 1
    assert connection.commit_calls == 1
    assert connection.close_calls == 1
    assert connection.execute_calls == [
        "SAVEPOINT splink_run_execute",
        "ROLLBACK TO SAVEPOINT splink_run_execute",
    ]
    assert failed_audit["run_id"] == run_id
    assert failed_audit["error_message"] == "boom during score"
    assert failed_audit["duration_seconds"] >= 0.0
    assert "Entity resolution CLI failed: boom during score" in capsys.readouterr().err


def test_main_action_resolve_transaction_counterparties_dispatches_to_resolver(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FakeConnection()
    _install_connection_hooks(monkeypatch, connection)
    resolver_calls: list[float | None] = []

    monkeypatch.setattr("core.entity_resolution.cli._require_splink_runtime_available", lambda *_: None)

    def _fake_resolver(
        conn: object,
        *,
        auto_merge_threshold: float | None = None,
    ) -> dict[str, int]:
        assert conn is connection
        resolver_calls.append(auto_merge_threshold)
        return {
            "candidate_transactions": 3,
            "mutated_rows": 2,
            "matched_person_rows": 1,
            "matched_organization_rows": 1,
            "skipped_rows": 1,
            "ambiguous_rows": 1,
            "dual_match_rows": 0,
        }

    monkeypatch.setattr(
        "core.entity_resolution.cli.resolve_nc_transaction_counterparties",
        _fake_resolver,
    )

    exit_code = main(
        [
            "--entity-type",
            "person",
            "--action",
            "resolve-transaction-counterparties",
        ]
    )

    assert exit_code == 0
    assert resolver_calls == [None]
    assert connection.commit_calls == 1
    assert connection.close_calls == 1
    assert "NC transaction counterparty resolver summary" in capsys.readouterr().out


def test_main_action_resolve_transaction_counterparties_preflights_both_entity_runtimes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection()
    _install_connection_hooks(monkeypatch, connection)
    preflight_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "core.entity_resolution.cli.get_splink_runtime",
        lambda: object(),
    )

    def _fake_require_probabilistic_settings(settings: object, *, entity_type: str) -> None:
        preflight_calls.append((str(settings), entity_type))

    monkeypatch.setattr(
        "core.entity_resolution.cli.require_probabilistic_settings",
        _fake_require_probabilistic_settings,
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.get_probabilistic_settings",
        lambda entity_type: f"settings:{entity_type}",
    )
    monkeypatch.setattr(
        "core.entity_resolution.cli.resolve_nc_transaction_counterparties",
        lambda *_args, **_kwargs: {
            "candidate_transactions": 0,
            "mutated_rows": 0,
            "matched_person_rows": 0,
            "matched_organization_rows": 0,
            "skipped_rows": 0,
            "ambiguous_rows": 0,
            "dual_match_rows": 0,
        },
    )

    exit_code = main(["--action", "resolve-transaction-counterparties"])

    assert exit_code == 0
    assert preflight_calls == [
        ("settings:person", "person"),
        ("settings:organization", "organization"),
    ]
