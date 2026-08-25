"""Load structured contribution-limit rules from jurisdiction configs into PostgreSQL.

A thin adapter between two owners that already exist: ``config_schema`` owns YAML
parsing, validation, and config discovery, and ``cf.contribution_limit_rules``
(``domains/campaign_finance/schema/tables.sql``) owns the persisted shape. Nothing here
re-derives legal semantics, and no region gets a branch — a rule's identity comes from
the validated model, and its jurisdiction comes from the enclosing config rather than
from the config's path.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict

from core.db import get_connection
from domains.campaign_finance.jurisdictions.config_schema import (
    ContributionLimitRule,
    JurisdictionConfig,
    discover_jurisdiction_configs,
    load_jurisdiction_config,
)


RULE_COLUMNS = (
    "donor_type",
    "recipient_type",
    "office_level",
    "election_type",
    "limit_status",
    "limit_amount",
    "limit_basis",
    "source_citation",
    "effective_date",
    "sunset_date",
    "research_observed_date",
    "local_override_allowed",
    "note",
    "metadata",
)
ROW_COLUMNS = ("jurisdiction_fips", *RULE_COLUMNS)
"""The non-audit columns of ``cf.contribution_limit_rules``; ``id`` and the timestamps
are database-owned defaults and are never projected from a config."""

_JSONB_COLUMNS = frozenset({"metadata"})

_DELETE_STATEMENT = "DELETE FROM cf.contribution_limit_rules WHERE jurisdiction_fips = ANY(%s)"
_INSERT_STATEMENT = (
    f"INSERT INTO cf.contribution_limit_rules ({', '.join(ROW_COLUMNS)}) "
    f"VALUES ({', '.join(['%s'] * len(ROW_COLUMNS))})"
)


class ContributionLimitRuleReplacementSummary(BaseModel):
    """What one jurisdiction-scoped replacement did, so callers never recount rows."""

    model_config = ConfigDict(frozen=True)

    included_jurisdiction_count: int
    deleted_row_count: int
    inserted_row_count: int


def _project_rule_row(jurisdiction_fips: str, rule: ContributionLimitRule) -> dict[str, object]:
    """Flatten one validated rule onto the table's columns without branching on status.

    Every ``limit_status`` variant either declares a field or exposes a ``None`` property
    for the columns it cannot carry, so a JSON-mode dump plus a missing-key default covers
    all four statuses. The dump also renders dates as ISO strings and metadata items as
    plain dictionaries, which is exactly the shape the JSONB column and the callers want.
    """
    dumped_rule = rule.model_dump(mode="json")
    return {
        "jurisdiction_fips": jurisdiction_fips,
        **{column: dumped_rule.get(column) for column in RULE_COLUMNS},
    }


def project_contribution_limit_rule_rows(config: JurisdictionConfig) -> list[dict[str, object]]:
    """Project one config's contribution-limit rules onto ``ROW_COLUMNS``."""
    jurisdiction_fips = config.jurisdiction.fips
    return [_project_rule_row(jurisdiction_fips, rule) for rule in config.laws.contribution_limit_rules or []]


def _to_database_parameters(row: dict[str, object]) -> tuple[object, ...]:
    """Order a projected row by column and wrap the one value PostgreSQL cannot infer."""
    return tuple(Jsonb(row[column]) if column in _JSONB_COLUMNS else row[column] for column in ROW_COLUMNS)


def _delete_rules_for_jurisdictions(
    connection: psycopg.Connection,
    jurisdiction_fips_values: Sequence[str],
) -> int:
    if not jurisdiction_fips_values:
        return 0
    with connection.cursor() as cursor:
        cursor.execute(_DELETE_STATEMENT, (list(jurisdiction_fips_values),))
        return cursor.rowcount


def _insert_rule_rows(connection: psycopg.Connection, rows: Sequence[dict[str, object]]) -> int:
    if not rows:
        return 0
    with connection.cursor() as cursor:
        cursor.executemany(_INSERT_STATEMENT, [_to_database_parameters(row) for row in rows])
        return cursor.rowcount if cursor.rowcount >= 0 else len(rows)


def replace_contribution_limit_rules(
    connection: psycopg.Connection,
    config_paths: Sequence[Path],
) -> ContributionLimitRuleReplacementSummary:
    """Replace the rules of exactly the jurisdictions named by ``config_paths``.

    Deletion is scoped to the FIPS values the given configs declare, so a partial config
    root never removes a jurisdiction it did not load. The delete and the insert share one
    ``connection.transaction()`` block: a real transaction for a standalone call, and a
    savepoint when the caller already owns one, so a failed load never leaves a
    jurisdiction with its old rules deleted and its new rules missing.
    """
    configs = [load_jurisdiction_config(config_path) for config_path in config_paths]
    included_jurisdiction_fips = sorted({config.jurisdiction.fips for config in configs})
    rows = [row for config in configs for row in project_contribution_limit_rule_rows(config)]
    if not rows:
        raise ValueError("refusing to replace contribution-limit rules with an empty projection")

    with connection.transaction():
        deleted_row_count = _delete_rules_for_jurisdictions(connection, included_jurisdiction_fips)
        inserted_row_count = _insert_rule_rows(connection, rows)

    return ContributionLimitRuleReplacementSummary(
        included_jurisdiction_count=len(included_jurisdiction_fips),
        deleted_row_count=deleted_row_count,
        inserted_row_count=inserted_row_count,
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load jurisdiction contribution-limit rules into PostgreSQL")
    parser.add_argument(
        "--config-root",
        type=Path,
        required=True,
        help="Directory to discover jurisdiction config.yaml files under",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report discovered configs and projected rows without opening a database connection",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Report or apply the rules discovered under ``--config-root``.

    Dry-run answers "what would this load?" entirely from the configs, so it never opens
    PostgreSQL. Writing mode owns only the connection and the report; the transaction,
    the scoped delete, and the insert stay in the shared replacement function, and the
    printed counts are the summary's rather than a second, independently derived tally.
    """
    parsed_argv = argv if argv is not None else []
    argument_parser = _build_argument_parser()
    arguments = argument_parser.parse_args(parsed_argv)
    config_paths = discover_jurisdiction_configs(arguments.config_root)
    if not config_paths:
        argument_parser.error(f"no jurisdiction config.yaml files found under {arguments.config_root}")

    projected_row_count = sum(
        len(project_contribution_limit_rule_rows(load_jurisdiction_config(config_path))) for config_path in config_paths
    )
    if arguments.dry_run:
        print(f"Discovered configs: {len(config_paths)}")
        print(f"Projected contribution-limit rules: {projected_row_count}")
        return 0
    if projected_row_count == 0:
        argument_parser.error("refusing to replace contribution-limit rules with an empty projection")

    with get_connection() as connection:
        summary = replace_contribution_limit_rules(connection, config_paths)

    print(f"Included jurisdictions: {summary.included_jurisdiction_count}")
    print(f"Deleted contribution-limit rules: {summary.deleted_row_count}")
    print(f"Inserted contribution-limit rules: {summary.inserted_row_count}")
    return 0


__all__ = [
    "ROW_COLUMNS",
    "RULE_COLUMNS",
    "ContributionLimitRuleReplacementSummary",
    "main",
    "project_contribution_limit_rule_rows",
    "replace_contribution_limit_rules",
]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
