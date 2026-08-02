"""Shared SQL fragments for active federal officeholder scope."""

from __future__ import annotations

import re


# Canonical seated-officeholder bounds: docs/reference/anchors/FEDERAL.md.
SEATED_FEDERAL_OFFICIALS_MIN = 535
SEATED_FEDERAL_OFFICIALS_MAX = 543

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_AS_OF_SQL = frozenset({"CURRENT_DATE", "%s::date"})


def _validated_sql_identifier(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not _SQL_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"invalid SQL identifier for {label}")
    return normalized


def _validated_as_of_sql(value: str) -> str:
    normalized = value.strip()
    if normalized not in _ALLOWED_AS_OF_SQL:
        raise ValueError("invalid as_of_sql expression")
    return normalized


def current_federal_officeholder_predicate(
    *,
    officeholding_alias: str = "oh",
    office_alias: str = "o",
    as_of_sql: str = "CURRENT_DATE",
) -> str:
    validated_officeholding_alias = _validated_sql_identifier(officeholding_alias, label="officeholding_alias")
    validated_office_alias = _validated_sql_identifier(office_alias, label="office_alias")
    validated_as_of_sql = _validated_as_of_sql(as_of_sql)
    return (
        f"{validated_office_alias}.office_level = 'federal' "
        f"AND {validated_officeholding_alias}.valid_period @> {validated_as_of_sql}"
    )


def federal_officeholder_targets_sql() -> str:
    return f"""
        SELECT
            oh.person_id,
            p.canonical_name,
            p.identifiers->>'roster_bio_url' AS roster_bio_url,
            p.identifiers->>'wikidata_id' AS wikidata_entity_id,
            p.identifiers->>'bioguide_id' AS bioguide_id
        FROM civic.officeholding oh
        JOIN civic.office o ON o.id = oh.office_id
        JOIN core.person p ON p.id = oh.person_id
        WHERE {current_federal_officeholder_predicate()}
        ORDER BY p.canonical_name, oh.person_id
    """


def active_federal_candidate_scope_cte(cte_name: str = "active_federal_candidates") -> str:
    validated_cte_name = _validated_sql_identifier(cte_name, label="cte_name")
    return f"""
        {validated_cte_name} AS (
            SELECT DISTINCT c.id, c.principal_committee_id
            FROM civic.officeholding oh
            JOIN civic.office o ON o.id = oh.office_id
            JOIN core.person p ON p.id = oh.person_id
            JOIN cf.candidate c ON c.person_id = p.id
            WHERE {current_federal_officeholder_predicate()}
        )
    """


__all__ = [
    "SEATED_FEDERAL_OFFICIALS_MAX",
    "SEATED_FEDERAL_OFFICIALS_MIN",
    "active_federal_candidate_scope_cte",
    "current_federal_officeholder_predicate",
    "federal_officeholder_targets_sql",
]
