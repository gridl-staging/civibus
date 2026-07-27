from __future__ import annotations

from typing import Any

from core.entity_resolution.extract import (
    RowDict,
    prepare_rows_for_probabilistic_scoring,
)
from core.entity_resolution.splink_config import (
    get_blocking_rule_sqls,
    get_probabilistic_settings,
)
from core.entity_resolution.splink_runtime import (
    BoundedConnectionFactory,
    get_splink_runtime,
    require_probabilistic_settings,
)

try:
    from splink.blocking_analysis import (
        cumulative_comparisons_to_be_scored_from_blocking_rules_data,
        n_largest_blocks,
    )
except (ImportError, ModuleNotFoundError) as import_error:
    cumulative_comparisons_to_be_scored_from_blocking_rules_data = None
    n_largest_blocks = None
    _BLOCKING_ANALYSIS_IMPORT_ERROR = import_error
else:
    _BLOCKING_ANALYSIS_IMPORT_ERROR = None

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


def _zero_counts_by_rule(
    rule_metadata: list[BlockingRuleMetadata],
) -> list[BlockingRuleMetadata]:
    return [
        {
            "rule_index": rule["rule_index"],
            "blocking_rule": rule["blocking_rule"],
            "exclusive_pair_count": 0,
            "cumulative_pair_count": 0,
            "max_block_size": 0,
        }
        for rule in rule_metadata
    ]


def describe_blocking_rules(entity_type: str) -> list[BlockingRuleMetadata]:
    """Return blocking-rule metadata from Splink settings."""
    return _blocking_rule_metadata(_probabilistic_settings(entity_type))


def count_blocked_pairs(
    rows: list[RowDict],
    entity_type: str,
    *,
    bounded_connection_factory: BoundedConnectionFactory | None = None,
) -> list[BlockingRuleMetadata]:
    """Count candidate-pair volumes by Splink public blocking-analysis APIs."""
    settings = _probabilistic_settings(entity_type)
    rule_metadata = _blocking_rule_metadata(settings)
    blocking_rules = get_blocking_rule_sqls(entity_type, probabilistic_settings=settings)
    if not blocking_rules:
        return _zero_counts_by_rule(rule_metadata)

    _, DuckDBAPI = get_splink_runtime()
    cumulative_counts, largest_blocks = _require_blocking_analysis_functions()
    prepared_rows = prepare_rows_for_probabilistic_scoring(rows)
    if not prepared_rows:
        return _zero_counts_by_rule(rule_metadata)
    connection = bounded_connection_factory() if bounded_connection_factory is not None else None
    try:
        db_api = _duckdb_api(DuckDBAPI, connection)
        cumulative_records = _blocking_analysis_records(
            cumulative_counts(
                table_or_tables=[prepared_rows],
                blocking_rules=blocking_rules,
                link_type="dedupe_only",
                db_api=db_api,
                unique_id_column_name="id",
            )
        )
        return _blocking_counts_from_analysis(
            rule_metadata,
            blocking_rules,
            cumulative_records,
            prepared_rows=prepared_rows,
            db_api=db_api,
            largest_blocks=largest_blocks,
        )
    finally:
        if connection is not None:
            connection.close()


def _duckdb_api(duckdb_api_type: type[Any], connection: Any | None) -> Any:
    if connection is None:
        return duckdb_api_type()
    return duckdb_api_type(connection=connection)


def _require_blocking_analysis_functions() -> tuple[Any, Any]:
    if callable(cumulative_comparisons_to_be_scored_from_blocking_rules_data) and callable(n_largest_blocks):
        return cumulative_comparisons_to_be_scored_from_blocking_rules_data, n_largest_blocks

    message = (
        "Splink blocking-analysis APIs are required for blocking diagnostics. "
        "Install a compatible Splink release with `pip install splink duckdb`."
    )
    if _BLOCKING_ANALYSIS_IMPORT_ERROR is None:
        raise RuntimeError(message)
    raise RuntimeError(message) from _BLOCKING_ANALYSIS_IMPORT_ERROR


def _blocking_counts_from_analysis(
    rule_metadata: list[BlockingRuleMetadata],
    blocking_rules: list[Any],
    cumulative_records: list[dict[str, Any]],
    *,
    prepared_rows: list[RowDict],
    db_api: Any,
    largest_blocks: Any,
) -> list[BlockingRuleMetadata]:
    records_by_index = {_rule_index_from_record(record): record for record in cumulative_records}
    counts: list[BlockingRuleMetadata] = []
    for rule in rule_metadata:
        record = records_by_index.get(rule["rule_index"])
        cumulative_pair_count = _cumulative_pair_count(record)
        counts.append(
            {
                "rule_index": rule["rule_index"],
                "blocking_rule": rule["blocking_rule"],
                "exclusive_pair_count": _exclusive_pair_count(record),
                "cumulative_pair_count": cumulative_pair_count,
                "max_block_size": _max_block_size_for_rule(
                    prepared_rows,
                    blocking_rules[rule["rule_index"]],
                    db_api=db_api,
                    largest_blocks=largest_blocks,
                ),
            }
        )
    return counts


def _blocking_analysis_records(output: Any) -> list[dict[str, Any]]:
    if hasattr(output, "to_dict"):
        return list(output.to_dict(orient="records"))
    if hasattr(output, "as_record_dict"):
        return list(output.as_record_dict())
    if isinstance(output, list):
        return [dict(record) for record in output]
    raise RuntimeError("Unsupported Splink blocking-analysis output format.")


def _rule_index_from_record(record: dict[str, Any]) -> int:
    return _required_record_int(record, "match_key", "rule index")


def _exclusive_pair_count(record: dict[str, Any] | None) -> int:
    if record is None:
        raise RuntimeError("Splink blocking analysis omitted a blocking-rule record.")
    return _required_record_int(record, "row_count", "exclusive pair count")


def _cumulative_pair_count(record: dict[str, Any] | None) -> int:
    if record is None:
        raise RuntimeError("Splink blocking analysis omitted a blocking-rule record.")
    return _required_record_int(record, "cumulative_rows", "cumulative pair count")


def _max_block_size_for_rule(
    prepared_rows: list[RowDict],
    blocking_rule: Any,
    *,
    db_api: Any,
    largest_blocks: Any,
) -> int:
    largest_records = _blocking_analysis_records(
        largest_blocks(
            table_or_tables=[prepared_rows],
            blocking_rule=blocking_rule,
            link_type="dedupe_only",
            db_api=db_api,
            n_largest=1,
        )
    )
    if not largest_records:
        return 0
    return _required_record_int(largest_records[0], "block_count", "maximum block size")


def _required_record_int(record: dict[str, Any], key: str, field_description: str) -> int:
    if key not in record or record[key] is None:
        columns = ", ".join(sorted(record)) or "<none>"
        raise RuntimeError(
            "Splink blocking-analysis output is missing the required "
            f"{field_description} column {key!r}; received columns: {columns}."
        )
    return int(record[key])
