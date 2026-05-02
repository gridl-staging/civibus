"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/MAR18_cross_domain_er_and_property_graph/civibus_dev/core/entity_resolution/cli.py.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg

from core.db import get_connection
from core.entity_resolution.blocking import count_blocked_pairs, describe_blocking_rules
from core.entity_resolution.clustering import cluster_scored_pairs
from core.entity_resolution.confidence import (
    classify_scored_pairs,
    resolve_auto_merge_threshold,
)
from core.entity_resolution.extract import extract_rows_for_matching
from core.entity_resolution.graph_edges import materialize_er_edges
from core.entity_resolution.persist import (
    log_splink_run_complete,
    log_splink_run_failed,
    log_splink_run_start,
    persist_auto_merge_clusters,
    persist_match_decisions,
)
from core.entity_resolution.scoring import score_entities
from core.entity_resolution.splink_config import get_probabilistic_settings
from core.entity_resolution.splink_runtime import (
    get_splink_runtime,
    require_probabilistic_settings,
)
from core.entity_resolution.transaction_counterparty_resolver import resolve_nc_transaction_counterparties
from core.graph import age_post_connect, ensure_graph

_ENTITY_TYPE_CHOICES = ("person", "organization")
_ACTION_CHOICES = ("run", "block", "score", "cluster", "resolve-transaction-counterparties")
_ACTIONS_REQUIRING_SPLINK = frozenset(_ACTION_CHOICES)
_ACTIONS_REQUIRING_ENTITY_TYPE = frozenset(("run", "block", "score", "cluster"))
_DECISION_TIERS = ("match", "probable_match", "possible_match", "no_match")
_EDGE_DECISIONS = {"probable_match", "possible_match"}
_THRESHOLD_ACTIONS = frozenset(("run", "score", "cluster"))
_RUN_EXECUTION_SAVEPOINT = "splink_run_execute"


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run entity resolution scoring, diagnostics, and persistence actions.")
    parser.add_argument(
        "--entity-type",
        required=False,
        choices=_ENTITY_TYPE_CHOICES,
        help="Entity type to resolve.",
    )
    parser.add_argument(
        "--action",
        default="run",
        choices=_ACTION_CHOICES,
        help="CLI action to execute (default: run).",
    )
    parser.add_argument(
        "--min-threshold",
        type=float,
        default=None,
        help="Optional auto-merge threshold override for confidence classification.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute pipeline without commit or run-audit log writes.",
    )
    return parser


def _require_splink_runtime_available(action: str, entity_type: str | None) -> None:
    if action not in _ACTIONS_REQUIRING_SPLINK:
        return

    get_splink_runtime()
    if action == "resolve-transaction-counterparties":
        for runtime_entity_type in _ENTITY_TYPE_CHOICES:
            require_probabilistic_settings(
                get_probabilistic_settings(runtime_entity_type),
                entity_type=runtime_entity_type,
            )
        return

    if entity_type is None:
        raise ValueError("--entity-type is required for this action.")

    require_probabilistic_settings(
        get_probabilistic_settings(entity_type),
        entity_type=entity_type,
    )


def _validate_required_entity_type(action: str, entity_type: str | None) -> str | None:
    if action in _ACTIONS_REQUIRING_ENTITY_TYPE and entity_type is None:
        raise ValueError("--entity-type is required for this action.")
    return entity_type


def _validate_threshold_arguments(
    *,
    action: str,
    auto_merge_threshold: float | None,
) -> float | None:
    if auto_merge_threshold is None:
        return None

    if action not in _THRESHOLD_ACTIONS:
        raise ValueError("--min-threshold is only supported for 'run', 'score', and 'cluster' actions.")

    resolve_auto_merge_threshold(auto_merge_threshold)
    return auto_merge_threshold


def _resolve_splink_version() -> str:
    try:
        import splink  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError):
        return "unknown"
    module_version = getattr(splink, "__version__", None)
    if module_version:
        return str(module_version)

    try:
        from importlib import metadata
    except ImportError:
        return "unknown"

    try:
        distribution_version = metadata.version("splink")
    except metadata.PackageNotFoundError:
        return "unknown"
    if distribution_version:
        return str(distribution_version)
    return "unknown"


def _decision_counts(classified_pairs: list[dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(_DECISION_TIERS, 0)
    for pair in classified_pairs:
        decision = str(pair.get("decision"))
        if decision in counts:
            counts[decision] += 1
    return counts


def _edge_materialization_count(classified_pairs: list[dict[str, Any]]) -> int:
    return sum(1 for pair in classified_pairs if pair.get("decision") in _EDGE_DECISIONS)


def _print_tier_summary(*, header: str, classified_pairs: list[dict[str, Any]]) -> None:
    counts = _decision_counts(classified_pairs)
    print(header)
    print(f"  match: {counts['match']}")
    print(f"  probable_match: {counts['probable_match']}")
    print(f"  possible_match: {counts['possible_match']}")
    print(f"  no_match: {counts['no_match']}")


def _print_blocking_summary(
    *,
    entity_type: str,
    blocking_rules: list[dict[str, Any]],
    blocked_pair_counts: list[dict[str, Any]],
) -> None:
    pair_counts_by_rule_index = {
        int(item["rule_index"]): int(item.get("pair_count", 0)) for item in blocked_pair_counts
    }
    print(f"Blocking diagnostics ({entity_type})")
    if not blocking_rules:
        print("  No blocking rules configured.")
        return

    for rule in blocking_rules:
        rule_index = int(rule["rule_index"])
        blocking_rule = str(rule["blocking_rule"])
        pair_count = pair_counts_by_rule_index.get(rule_index, 0)
        print(f"  rule[{rule_index}] {blocking_rule} | pairs={pair_count}")


def _score_and_classify_pairs(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    auto_merge_threshold: float | None,
) -> list[dict[str, Any]]:
    scored_pairs = score_entities(conn, entity_type)
    return classify_scored_pairs(
        scored_pairs,
        auto_merge_threshold=auto_merge_threshold,
    )


def _run_block_action(conn: psycopg.Connection, *, entity_type: str) -> None:
    entity_rows = extract_rows_for_matching(conn, entity_type)
    blocking_rules = describe_blocking_rules(entity_type)
    blocked_pair_counts = count_blocked_pairs(entity_rows, entity_type)
    _print_blocking_summary(
        entity_type=entity_type,
        blocking_rules=blocking_rules,
        blocked_pair_counts=blocked_pair_counts,
    )


def _run_score_action(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    auto_merge_threshold: float | None,
) -> list[dict[str, Any]]:
    classified_pairs = _score_and_classify_pairs(
        conn,
        entity_type=entity_type,
        auto_merge_threshold=auto_merge_threshold,
    )
    _print_tier_summary(
        header=f"Scored-pair decision tiers ({entity_type})",
        classified_pairs=classified_pairs,
    )
    return classified_pairs


def _score_and_cluster_pairs(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    auto_merge_threshold: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entity_rows = extract_rows_for_matching(conn, entity_type)
    classified_pairs = _score_and_classify_pairs(
        conn,
        entity_type=entity_type,
        auto_merge_threshold=auto_merge_threshold,
    )
    return entity_rows, cluster_scored_pairs(classified_pairs, entity_rows)


def _print_cluster_summary(
    *,
    header: str,
    clustered_pairs: dict[str, Any],
) -> None:
    pairwise_decisions = clustered_pairs["pairwise_decisions"]
    print(header)
    print(f"  auto_merge_clusters: {len(clustered_pairs['auto_merge_clusters'])}")
    print(f"  review_components: {len(clustered_pairs['review_components'])}")
    print(f"  age_edges_materialized: {_edge_materialization_count(pairwise_decisions)}")
    _print_tier_summary(header="Decision tiers:", classified_pairs=pairwise_decisions)


def _run_cluster_action(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    auto_merge_threshold: float | None,
) -> dict[str, Any]:
    _, clustered_pairs = _score_and_cluster_pairs(
        conn,
        entity_type=entity_type,
        auto_merge_threshold=auto_merge_threshold,
    )
    _print_cluster_summary(
        header=f"Cluster preview ({entity_type})",
        clustered_pairs=clustered_pairs,
    )
    return clustered_pairs


def _run_transaction_counterparty_resolution_action(
    conn: psycopg.Connection,
    *,
    auto_merge_threshold: float | None,
) -> dict[str, int]:
    summary = resolve_nc_transaction_counterparties(
        conn,
        auto_merge_threshold=auto_merge_threshold,
    )
    print("NC transaction counterparty resolver summary")
    print(f"  candidate_transactions: {summary['candidate_transactions']}")
    print(f"  mutated_rows: {summary['mutated_rows']}")
    print(f"  matched_person_rows: {summary['matched_person_rows']}")
    print(f"  matched_organization_rows: {summary['matched_organization_rows']}")
    print(f"  skipped_rows: {summary['skipped_rows']}")
    print(f"  ambiguous_rows: {summary['ambiguous_rows']}")
    print(f"  dual_match_rows: {summary['dual_match_rows']}")
    return summary


def _run_counts(
    *,
    entity_rows: list[dict[str, Any]],
    clustered_pairs: dict[str, Any],
) -> dict[str, int]:
    decisions = clustered_pairs["pairwise_decisions"]
    decision_counts = _decision_counts(decisions)
    matches_found = decision_counts["match"] + decision_counts["probable_match"] + decision_counts["possible_match"]
    return {
        "input_record_count": len(entity_rows),
        "pairs_compared": len(decisions),
        "matches_found": matches_found,
        "auto_merged": len(clustered_pairs["auto_merge_clusters"]),
        "probable_matches": decision_counts["probable_match"],
        "possible_matches": decision_counts["possible_match"],
    }


def _run_model_config(
    *,
    entity_type: str,
    auto_merge_threshold: float | None,
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "auto_merge_threshold": auto_merge_threshold,
    }


def _persist_cluster_results(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    clustered_pairs: dict[str, Any],
) -> None:
    pairwise_decisions = clustered_pairs["pairwise_decisions"]
    auto_merge_clusters = clustered_pairs["auto_merge_clusters"]
    persist_match_decisions(conn, pairwise_decisions, entity_type)
    persist_auto_merge_clusters(conn, auto_merge_clusters, entity_type)
    materialize_er_edges(conn, pairwise_decisions, entity_type)


def _record_run_completion(
    conn: psycopg.Connection,
    *,
    run_id: UUID | None,
    started_at: datetime | None,
    entity_rows: list[dict[str, Any]],
    clustered_pairs: dict[str, Any],
) -> None:
    if run_id is None or started_at is None:
        raise RuntimeError("Persisted ER run is missing required audit context.")

    completed_at = datetime.now(UTC)
    log_splink_run_complete(
        conn,
        run_id,
        completed_at=completed_at,
        duration_seconds=(completed_at - started_at).total_seconds(),
        counts=_run_counts(
            entity_rows=entity_rows,
            clustered_pairs=clustered_pairs,
        ),
    )


def _maybe_start_persisted_run(
    conn: psycopg.Connection,
    *,
    action: str,
    dry_run: bool,
    entity_type: str,
    auto_merge_threshold: float | None,
) -> tuple[UUID | None, datetime | None, bool, Exception | None]:
    if action != "run" or dry_run:
        return None, None, False, None

    started_at = datetime.now(UTC)
    run_id = log_splink_run_start(
        conn,
        entity_type=entity_type,
        splink_version=_resolve_splink_version(),
        model_config=_run_model_config(
            entity_type=entity_type,
            auto_merge_threshold=auto_merge_threshold,
        ),
        started_at=started_at,
    )
    try:
        conn.execute(f"SAVEPOINT {_RUN_EXECUTION_SAVEPOINT}")
    except Exception as error:  # pragma: no cover - exercised by integration tests
        return run_id, started_at, False, error
    return run_id, started_at, True, None


def _record_run_failure(
    conn: psycopg.Connection | None,
    *,
    run_id: UUID | None,
    started_at: datetime | None,
    execution_savepoint_created: bool,
    error: Exception,
) -> None:
    if conn is None or run_id is None or started_at is None:
        return

    completed_at = datetime.now(UTC)
    if execution_savepoint_created:
        conn.execute(f"ROLLBACK TO SAVEPOINT {_RUN_EXECUTION_SAVEPOINT}")
    log_splink_run_failed(
        conn,
        run_id,
        completed_at=completed_at,
        duration_seconds=(completed_at - started_at).total_seconds(),
        error_message=str(error),
    )
    conn.commit()


def _run_full_pipeline_action(
    conn: psycopg.Connection,
    *,
    entity_type: str,
    auto_merge_threshold: float | None,
    dry_run: bool,
    run_id: UUID | None,
    started_at: datetime | None,
) -> None:
    entity_rows, clustered_pairs = _score_and_cluster_pairs(
        conn,
        entity_type=entity_type,
        auto_merge_threshold=auto_merge_threshold,
    )

    _persist_cluster_results(
        conn,
        entity_type=entity_type,
        clustered_pairs=clustered_pairs,
    )

    _print_cluster_summary(
        header=f"Entity resolution run summary ({entity_type})",
        clustered_pairs=clustered_pairs,
    )

    if dry_run:
        print("Dry-run mode: no commit performed.")
        return

    _record_run_completion(
        conn,
        run_id=run_id,
        started_at=started_at,
        entity_rows=entity_rows,
        clustered_pairs=clustered_pairs,
    )


def _dispatch_action(
    conn: psycopg.Connection,
    *,
    action: str,
    entity_type: str,
    auto_merge_threshold: float | None,
    dry_run: bool,
    run_id: UUID | None = None,
    started_at: datetime | None = None,
) -> None:
    match action:
        case "block":
            _run_block_action(conn, entity_type=entity_type)
        case "score":
            _run_score_action(
                conn,
                entity_type=entity_type,
                auto_merge_threshold=auto_merge_threshold,
            )
        case "cluster":
            _run_cluster_action(
                conn,
                entity_type=entity_type,
                auto_merge_threshold=auto_merge_threshold,
            )
        case "resolve-transaction-counterparties":
            _run_transaction_counterparty_resolution_action(
                conn,
                auto_merge_threshold=auto_merge_threshold,
            )
        case _:
            _run_full_pipeline_action(
                conn,
                entity_type=entity_type,
                auto_merge_threshold=auto_merge_threshold,
                dry_run=dry_run,
                run_id=run_id,
                started_at=started_at,
            )


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    conn: psycopg.Connection | None = None
    run_id: UUID | None = None
    started_at: datetime | None = None
    execution_savepoint_created = False
    try:
        auto_merge_threshold = _validate_threshold_arguments(
            action=args.action,
            auto_merge_threshold=args.min_threshold,
        )
        entity_type = _validate_required_entity_type(args.action, args.entity_type)
        conn = get_connection(post_connect=age_post_connect)
        ensure_graph(conn)
        _require_splink_runtime_available(args.action, entity_type)
        run_id, started_at, execution_savepoint_created, start_error = _maybe_start_persisted_run(
            conn,
            action=args.action,
            dry_run=args.dry_run,
            entity_type=entity_type or "person",
            auto_merge_threshold=auto_merge_threshold,
        )
        if start_error is not None:
            raise start_error
        _dispatch_action(
            conn,
            action=args.action,
            entity_type=entity_type or "person",
            auto_merge_threshold=auto_merge_threshold,
            dry_run=args.dry_run,
            run_id=run_id,
            started_at=started_at,
        )
        if not args.dry_run:
            conn.commit()
    except Exception as error:
        _record_run_failure(
            conn,
            run_id=run_id,
            started_at=started_at,
            execution_savepoint_created=execution_savepoint_created,
            error=error,
        )
        print(f"Entity resolution CLI failed: {error}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
