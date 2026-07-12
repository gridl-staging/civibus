"""Shared SQL fragments for active federal officeholder scope."""

from __future__ import annotations


def current_federal_officeholder_predicate(
    *,
    officeholding_alias: str = "oh",
    office_alias: str = "o",
) -> str:
    return f"{office_alias}.office_level = 'federal' AND upper_inf({officeholding_alias}.valid_period)"


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
    return f"""
        {cte_name} AS (
            SELECT DISTINCT c.id, c.principal_committee_id
            FROM civic.officeholding oh
            JOIN civic.office o ON o.id = oh.office_id
            JOIN core.person p ON p.id = oh.person_id
            JOIN cf.candidate c ON c.person_id = p.id
            WHERE {current_federal_officeholder_predicate()}
        )
    """


__all__ = [
    "active_federal_candidate_scope_cte",
    "current_federal_officeholder_predicate",
    "federal_officeholder_targets_sql",
]
