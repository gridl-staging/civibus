from __future__ import annotations

from collections import Counter
from typing import Any

from core.entity_resolution.extract import (
    RowDict,
    prepare_rows_for_probabilistic_scoring,
    prediction_record_restores_same_entity,
)
from core.entity_resolution.splink_config import (
    get_probabilistic_settings,
)
from core.entity_resolution.splink_runtime import (
    build_splink_linker,
    get_splink_runtime,
    prediction_records,
    require_probabilistic_settings,
)

BlockingRuleMetadata = dict[str, Any]


def _rule_to_readable_sql(rule: Any) -> str:
    """Extract a human-readable SQL string from a Splink blocking rule object."""
    sql = getattr(rule, "blocking_rule_sql", None)
    if sql is not None:
        return str(sql)
    # Splink 4 BlockingRuleCreator — resolve via get_blocking_rule().
    get_rule = getattr(rule, "get_blocking_rule", None)
    if get_rule is not None:
        resolved = get_rule("duckdb")
        sql = getattr(resolved, "blocking_rule_sql", None)
        if sql is not None:
            return str(sql)
    return str(rule)


def _probabilistic_settings(entity_type: str) -> Any:
    return require_probabilistic_settings(
        get_probabilistic_settings(entity_type),
        entity_type=entity_type,
    )


def _blocking_rule_metadata(settings: Any) -> list[BlockingRuleMetadata]:
    rules = getattr(settings, "blocking_rules_to_generate_predictions", [])
    return [
        {
            "rule_index": rule_index,
            "blocking_rule": _rule_to_readable_sql(rule),
        }
        for rule_index, rule in enumerate(rules)
    ]


def _pair_counts_by_rule(
    rule_metadata: list[BlockingRuleMetadata],
    counts_by_rule: Counter[str] | None = None,
) -> list[BlockingRuleMetadata]:
    match_counts = counts_by_rule or Counter()
    return [
        {
            "rule_index": rule["rule_index"],
            "blocking_rule": rule["blocking_rule"],
            "pair_count": match_counts.get(str(rule["rule_index"]), 0),
        }
        for rule in rule_metadata
    ]


def describe_blocking_rules(entity_type: str) -> list[BlockingRuleMetadata]:
    """Return blocking-rule metadata from Splink settings."""
    return _blocking_rule_metadata(_probabilistic_settings(entity_type))


def count_blocked_pairs(
    rows: list[RowDict],
    entity_type: str,
) -> list[BlockingRuleMetadata]:
    """Count candidate-pair volumes by Splink blocking rule using predict()."""
    settings = _probabilistic_settings(entity_type)
    rule_metadata = _blocking_rule_metadata(settings)
    prepared_rows = prepare_rows_for_probabilistic_scoring(rows)
    if not prepared_rows:
        return _pair_counts_by_rule(rule_metadata)

    linker = build_splink_linker(
        prepared_rows,
        settings,
        runtime_resolver=get_splink_runtime,
    )
    predictions = linker.inference.predict()
    match_keys = [
        str(record["match_key"])
        for record in prediction_records(predictions)
        if record.get("match_key") is not None and not prediction_record_restores_same_entity(record)
    ]
    counts_by_rule = Counter(match_keys)
    return _pair_counts_by_rule(rule_metadata, counts_by_rule)
