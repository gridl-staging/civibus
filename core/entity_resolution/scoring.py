from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from core.entity_resolution.extract import (
    RowDict,
    extract_rows_for_matching,
    prepare_rows_for_probabilistic_scoring,
    prediction_record_restores_same_entity,
    restore_entity_pair_from_prediction_record,
)
from core.entity_resolution.splink_config import (
    get_blocking_rule_sqls,
    get_deterministic_rules,
    get_probabilistic_settings,
)
from core.entity_resolution.splink_runtime import (
    build_splink_linker,
    get_splink_runtime,
    prediction_records,
    require_probabilistic_settings,
    train_linker,
)

ScoredPair = dict[str, Any]


def _ordered_rule_labels(rule_labels: list[str]) -> list[str]:
    return list(dict.fromkeys(rule_labels))


def _deterministic_decider(rule_labels: list[str]) -> str:
    if len(rule_labels) == 1:
        return rule_labels[0]
    return "deterministic_multi_rule"


def run_deterministic_rules(
    conn: psycopg.Connection,
    entity_type: str,
) -> list[ScoredPair]:
    """Execute deterministic matching rules from splink_config.py.

    Pairs matched by multiple rules collapse to one result. ``decided_by`` stays a
    schema-compatible string while ``matched_rule_names`` preserves full attribution.
    """
    rules = get_deterministic_rules(entity_type)

    # Collect matches keyed by canonical pair -> list of rule labels
    pair_rules: dict[tuple[UUID, UUID], list[str]] = {}

    with conn.cursor(row_factory=dict_row) as cursor:
        for rule in rules:
            cursor.execute(rule["sql"])  # type: ignore[arg-type]  # trusted SQL from splink_config
            for row in cursor.fetchall():
                pair_key = (row["entity_id_a"], row["entity_id_b"])
                label = f"deterministic_{rule['name']}"
                pair_rules.setdefault(pair_key, []).append(label)

    deterministic_pairs: list[ScoredPair] = []
    for key, rule_labels in pair_rules.items():
        matched_rule_names = _ordered_rule_labels(rule_labels)
        deterministic_pairs.append(
            {
                "entity_id_a": key[0],
                "entity_id_b": key[1],
                "confidence": 1.0,
                "decision_method": "deterministic",
                "decided_by": _deterministic_decider(matched_rule_names),
                "matched_rule_names": matched_rule_names,
            }
        )

    return deterministic_pairs


def filter_unresolved_rows(
    rows: list[RowDict],
    deterministic_pairs: list[ScoredPair],
) -> list[RowDict]:
    """Remove entities already matched at confidence 1.0 from the input rows."""
    matched_ids: set[UUID] = set()
    for pair in deterministic_pairs:
        matched_ids.add(pair["entity_id_a"])
        matched_ids.add(pair["entity_id_b"])

    return [row for row in rows if row["id"] not in matched_ids]


def _canonical_pair(entity_id_a: Any, entity_id_b: Any) -> tuple[Any, Any]:
    try:
        if entity_id_a < entity_id_b:
            return entity_id_a, entity_id_b
    except TypeError:
        if str(entity_id_a) < str(entity_id_b):
            return entity_id_a, entity_id_b

    return entity_id_b, entity_id_a


def _record_entity_ids(record: dict[str, Any]) -> tuple[Any, Any]:
    return _canonical_pair(
        *restore_entity_pair_from_prediction_record(record),
    )


def score_with_splink(
    rows: list[RowDict],
    entity_type: str,
    *,
    probabilistic_settings: Any | None = None,
) -> list[ScoredPair]:
    """Run probabilistic matching with Splink and return Stage 3 scored-pair contract."""
    settings = require_probabilistic_settings(
        probabilistic_settings if probabilistic_settings is not None else get_probabilistic_settings(entity_type),
        entity_type=entity_type,
    )
    runtime = get_splink_runtime()
    prepared_rows = prepare_rows_for_probabilistic_scoring(rows)
    if not prepared_rows:
        return []

    if probabilistic_settings is None:
        blocking_rules = get_blocking_rule_sqls(entity_type)
    else:
        blocking_rules = get_blocking_rule_sqls(entity_type, probabilistic_settings=settings)
    linker = build_splink_linker(
        prepared_rows,
        settings,
        runtime_resolver=lambda: runtime,
    )
    train_linker(linker, blocking_rules)
    predictions = linker.inference.predict()

    scores_by_pair: dict[tuple[Any, Any], float] = {}
    for record in prediction_records(predictions):
        if prediction_record_restores_same_entity(record):
            continue
        pair_key = _record_entity_ids(record)
        confidence = float(record["match_probability"])
        current_confidence = scores_by_pair.get(pair_key)
        if current_confidence is None or confidence > current_confidence:
            scores_by_pair[pair_key] = confidence

    return [
        {
            "entity_id_a": pair_key[0],
            "entity_id_b": pair_key[1],
            "confidence": confidence,
            "decision_method": "probabilistic",
            "decided_by": "splink_v1",
        }
        for pair_key, confidence in scores_by_pair.items()
    ]


def score_rows(
    rows: list[RowDict],
    entity_type: str,
    *,
    deterministic_pairs: list[ScoredPair] | None = None,
    probabilistic_settings: Any | None = None,
) -> list[ScoredPair]:
    """Score already-materialized ER rows through the standard deterministic/probabilistic pipeline.

    This keeps curated fixture evaluation on the same scoring path as DB-backed
    runs without requiring a live extraction query.
    """
    resolved_deterministic_pairs = list(deterministic_pairs or [])
    unresolved_rows = filter_unresolved_rows(rows, resolved_deterministic_pairs)
    if not unresolved_rows:
        return resolved_deterministic_pairs

    if probabilistic_settings is None:
        probabilistic_pairs = score_with_splink(unresolved_rows, entity_type)
    else:
        probabilistic_pairs = score_with_splink(
            unresolved_rows,
            entity_type,
            probabilistic_settings=probabilistic_settings,
        )
    return resolved_deterministic_pairs + probabilistic_pairs


def score_entities(
    conn: psycopg.Connection,
    entity_type: str,
    *,
    probabilistic_settings: Any | None = None,
) -> list[ScoredPair]:
    """Stage 2 scoring entry point: deterministic tier then probabilistic tier."""
    rows = extract_rows_for_matching(conn, entity_type)
    deterministic_pairs = run_deterministic_rules(conn, entity_type)
    return score_rows(
        rows,
        entity_type,
        deterministic_pairs=deterministic_pairs,
        probabilistic_settings=probabilistic_settings,
    )
