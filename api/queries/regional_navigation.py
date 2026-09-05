"""Read-only regional projection over typed route and authority owners."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from api.models.regional_navigation import (
    RegionalAuthorityContext,
    RegionalAuthorityHealth,
    RegionalCandidate,
    RegionalChildKind,
    RegionalCommittee,
    RegionalFilingAuthority,
    RegionalFinanceDetail,
    RegionalFinanceSource,
    RegionalFinanceState,
    RegionalGeometryReference,
    RegionalMoneyClass,
    RegionalNavigationNode,
    RegionalNodeKind,
    RegionalProxyAnalysis,
    RegionalSubjectIdentity,
)
from api.queries.campaign_finance import _resolve_county_proxy_cities
from domains.campaign_finance.coverage.lifecycle import (
    AUTHORITY_PROMOTION_RECEIPT_ENV,
    AuthorityPromotionReceipt,
    AuthorityPromotionEvidence,
    AuthorityRecurrenceEvidence,
    AuthoritySourceEvidence,
    DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH,
    assess_authority_promotion_receipt,
    assess_authority_promotion,
    load_authority_promotion_receipt,
    load_lifecycle,
)
from domains.campaign_finance.coverage.registry import (
    DEFAULT_REGISTRY_PATH,
    CoverageRegistry,
    CoverageRegistryRow,
    FilingAuthorityReference,
    IdentityTranslationError,
    IndependentAuthorityRelation,
    ScopedIdentity,
    load_registry,
    translate_identity,
)
from domains.campaign_finance.jurisdictions.config_schema import (
    DataSourceConfig,
    JurisdictionConfig,
    load_jurisdiction_config,
    operational_scope_for_config_identity,
)
from domains.civics.constants import LAUNCH_SCOPE_USPS_STATES, USPS_TO_STATE_NAME


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WA_CONFIG_PATH = _REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "WA" / "config.yaml"
_DAILY_STALE_AFTER = timedelta(days=2)
_CANDIDATE_LIMIT = 25
_COMMITTEE_LIMIT = 25
_MONEY_CLASS_LABELS = {
    "contributions": "Contributions",
    "expenditures": "Expenditures",
    "independent_expenditures": "Candidate-targeted independent expenditures",
    "loans": "Loans",
}
_MONEY_CLASS_ORDER = tuple(_MONEY_CLASS_LABELS)


@dataclass(frozen=True)
class RegionalQueryPlan:
    """Exact config-derived inputs consumed by the shared SQL owner."""

    subject: RegionalSubjectIdentity
    operational_scope: str
    authority_code: str
    source_order: tuple[tuple[str, str, DataSourceConfig], ...]
    person_identifier_key: str
    office_names: tuple[str, ...]


_REGIONAL_SOURCE_RUNTIME_SQL = """
WITH expected AS (
    SELECT source_name, class_key, ordinality
    FROM UNNEST(%(source_names)s::text[], %(class_keys)s::text[])
         WITH ORDINALITY AS rows(source_name, class_key, ordinality)
)
SELECT expected.class_key,
       expected.source_name,
       ds.id AS data_source_id,
       ds.source_url,
       ds.last_pull_at,
       ds.last_pull_status,
       refresh.completed_at AS latest_refresh_completed_at,
       refresh.pull_status AS latest_refresh_status,
       refresh.execution_origin AS latest_refresh_execution_origin
FROM expected
LEFT JOIN core.data_source AS ds
  ON ds.domain = %(domain)s
 AND ds.jurisdiction = %(operational_scope)s
 AND ds.name = expected.source_name
LEFT JOIN LATERAL (
    SELECT rr.completed_at, rr.pull_status, rr.execution_origin
    FROM core.refresh_run AS rr
    WHERE rr.domain = %(domain)s
      AND rr.jurisdiction = %(operational_scope)s
      AND expected.source_name = ANY(rr.data_source_names)
    ORDER BY rr.started_at DESC, rr.id DESC
    LIMIT 1
) AS refresh ON TRUE
ORDER BY expected.ordinality
"""

_BOUNDED_REGIONAL_TRANSACTIONS_CTE = """
WITH expected_sources AS (
    SELECT source_name, class_key
    FROM UNNEST(%(source_names)s::text[], %(class_keys)s::text[])
         AS rows(source_name, class_key)
), bounded_regional_transactions AS (
    SELECT cf_transaction.id,
           cf_transaction.committee_id,
           cf_transaction.amount,
           cf_transaction.transaction_date,
           transaction_source.name AS source_name,
           expected_sources.class_key,
           CASE
             WHEN expected_sources.class_key = 'independent_expenditures'
               THEN NULLIF(BTRIM(transaction_record.raw_fields ->> %(ie_candidate_filer_field)s), '')
             ELSE NULLIF(BTRIM(transaction_record.raw_fields ->> %(filer_field)s), '')
           END AS candidate_filer_id
    FROM cf.transaction AS cf_transaction
    JOIN cf.filing AS filing
      ON filing.id = cf_transaction.filing_id
    JOIN core.source_record AS transaction_record
      ON transaction_record.id = cf_transaction.source_record_id
     AND transaction_record.superseded_by IS NULL
    JOIN core.data_source AS transaction_source
      ON transaction_source.id = transaction_record.data_source_id
     AND transaction_source.domain = %(domain)s
     AND transaction_source.jurisdiction = %(operational_scope)s
    JOIN expected_sources
      ON expected_sources.source_name = transaction_source.name
    JOIN core.source_record AS filing_record
      ON filing_record.id = filing.source_record_id
     AND filing_record.superseded_by IS NULL
    JOIN core.data_source AS filing_source
      ON filing_source.id = filing_record.data_source_id
     AND filing_source.id = transaction_source.id
     AND filing_source.domain = %(domain)s
     AND filing_source.jurisdiction = %(operational_scope)s
     AND filing_source.name = transaction_source.name
    WHERE cf_transaction.transaction_date >= %(period_start)s
      AND cf_transaction.transaction_date <= %(period_end)s
      AND cf_transaction.date_is_reliable = TRUE
      AND cf_transaction.is_memo = FALSE
      AND cf_transaction.amendment_indicator <> 'T'
      AND cf_transaction.amended_by_transaction_id IS NULL
      AND filing.amendment_indicator <> 'T'
      AND NOT EXISTS (
          SELECT 1
          FROM cf.filing AS newer_filing
          WHERE newer_filing.amended_from_filing_id = filing.id
            AND newer_filing.amendment_indicator IN ('A', 'T')
      )
      AND (
          (
              expected_sources.class_key <> 'independent_expenditures'
              AND LOWER(BTRIM(transaction_record.raw_fields ->> %(office_field)s))
                    = ANY(%(office_names)s::text[])
              AND LOWER(BTRIM(transaction_record.raw_fields ->> %(jurisdiction_type_field)s))
                    = ANY(%(jurisdiction_type_values)s::text[])
          )
          OR
          (
              expected_sources.class_key = 'independent_expenditures'
              AND transaction_record.raw_fields ->> %(ie_origin_field)s = %(ie_candidate_origin)s
              AND LOWER(BTRIM(transaction_record.raw_fields ->> %(ie_candidate_office_field)s))
                    = ANY(%(office_names)s::text[])
              AND (
                  LOWER(BTRIM(transaction_record.raw_fields ->> %(ie_candidate_jurisdiction_field)s))
                      = %(subject_jurisdiction_name)s
                  OR LOWER(BTRIM(transaction_record.raw_fields ->> %(ie_candidate_jurisdiction_field)s))
                      ~ %(legislative_jurisdiction_pattern)s
              )
          )
      )
)
"""

_REGIONAL_MONEY_SQL = (
    _BOUNDED_REGIONAL_TRANSACTIONS_CTE
    + """
SELECT class_key,
       source_name,
       COALESCE(SUM(amount), 0::numeric(14,2)) AS amount,
       COUNT(*)::integer AS transaction_count,
       MAX(transaction_date) AS data_through
FROM bounded_regional_transactions
GROUP BY class_key, source_name
"""
)

_REGIONAL_COMMITTEE_SQL = (
    _BOUNDED_REGIONAL_TRANSACTIONS_CTE
    + """
SELECT committee.id AS committee_id,
       committee.organization_id,
       COALESCE(NULLIF(BTRIM(organization.canonical_name), ''), committee.name) AS name,
       SUM(ABS(bounded.amount)) AS activity_amount,
       COUNT(*)::integer AS transaction_count,
       MAX(bounded.transaction_date) AS data_through
FROM bounded_regional_transactions AS bounded
JOIN cf.committee AS committee
  ON committee.id = bounded.committee_id
LEFT JOIN core.organization AS organization
  ON organization.id = committee.organization_id
GROUP BY committee.id, committee.organization_id,
         COALESCE(NULLIF(BTRIM(organization.canonical_name), ''), committee.name)
ORDER BY activity_amount DESC,
         LOWER(COALESCE(NULLIF(BTRIM(organization.canonical_name), ''), committee.name)),
         committee.id
LIMIT %(committee_limit)s
"""
)

_REGIONAL_CANDIDATE_SQL = (
    _BOUNDED_REGIONAL_TRANSACTIONS_CTE
    + """
, unique_filer_identifiers AS (
    SELECT BTRIM(person.identifiers ->> %(person_identifier_key)s) AS filer_id,
           (ARRAY_AGG(person.id ORDER BY person.id))[1] AS person_id
    FROM core.person AS person
    WHERE NULLIF(BTRIM(person.identifiers ->> %(person_identifier_key)s), '') IS NOT NULL
    GROUP BY BTRIM(person.identifiers ->> %(person_identifier_key)s)
    HAVING COUNT(*) = 1
), person_activity AS (
    SELECT unique_filer_identifiers.person_id,
           SUM(ABS(bounded.amount)) AS activity_amount,
           COUNT(*)::integer AS transaction_count
    FROM unique_filer_identifiers
    JOIN bounded_regional_transactions AS bounded
      ON bounded.candidate_filer_id = unique_filer_identifiers.filer_id
    GROUP BY unique_filer_identifiers.person_id
)
SELECT person.id AS person_id,
       person.canonical_name AS person_name,
       candidacy.id AS candidacy_id,
       contest.id AS contest_id,
       contest.name AS contest_name,
       contest.election_date,
       office.id AS office_id,
       office.name AS office_name,
       office.title AS office_title,
       division.id AS division_id,
       division.name AS division_name,
       candidacy.party,
       candidacy.status AS candidacy_status,
       current_holding.id AS current_officeholding_id,
       CASE
         WHEN unique_filer_identifiers.person_id IS NULL THEN NULL
         ELSE JSONB_BUILD_OBJECT(
             'authority_code', %(authority_code)s::text,
             'value', unique_filer_identifiers.filer_id
         )
       END AS native_filer_identifier,
       CASE WHEN unique_filer_identifiers.person_id IS NULL THEN 'unavailable' ELSE 'connected' END
           AS money_connection,
       CASE
         WHEN unique_filer_identifiers.person_id IS NULL THEN NULL
         ELSE COALESCE(person_activity.activity_amount, 0::numeric(14,2))
       END AS activity_amount,
       CASE
         WHEN unique_filer_identifiers.person_id IS NULL THEN 0
         ELSE COALESCE(person_activity.transaction_count, 0)
       END::integer AS transaction_count
FROM civic.candidacy AS candidacy
JOIN core.person AS person
  ON person.id = candidacy.person_id
JOIN civic.contest AS contest
  ON contest.id = candidacy.contest_id
JOIN civic.office AS office
  ON office.id = contest.office_id
 AND office.office_level = %(civic_office_level)s
 AND office.state = %(state_code)s
LEFT JOIN civic.electoral_division AS division
  ON division.id = COALESCE(contest.electoral_division_id, office.electoral_division_id)
LEFT JOIN unique_filer_identifiers
  ON unique_filer_identifiers.person_id = person.id
LEFT JOIN person_activity
  ON person_activity.person_id = person.id
LEFT JOIN LATERAL (
    SELECT holding.id
    FROM civic.officeholding AS holding
    WHERE holding.person_id = person.id
      AND holding.office_id = office.id
      AND holding.valid_period @> %(period_end)s::date
    ORDER BY LOWER(holding.valid_period) DESC NULLS LAST, holding.id
    LIMIT 1
) AS current_holding ON TRUE
WHERE contest.election_date IS NULL OR contest.election_date >= %(period_start)s
ORDER BY contest.election_date DESC NULLS LAST,
         LOWER(person.canonical_name),
         person.id,
         candidacy.id
LIMIT %(candidate_limit)s
"""
)


def _one_row_for_code(rows: Iterable[object], jurisdiction_code: str) -> object:
    matches = [row for row in rows if getattr(row, "jurisdiction_code", None) == jurisdiction_code]
    if len(matches) != 1:
        raise ValueError(f"Expected one owner row for {jurisdiction_code}, found {len(matches)}.")
    return matches[0]


def _current_biennium(as_of: datetime) -> tuple[date, date]:
    year = as_of.year if as_of.year % 2 == 1 else as_of.year - 1
    return date(year, 1, 1), as_of.date()


def _money_source_order(config: JurisdictionConfig) -> tuple[tuple[str, str, DataSourceConfig], ...]:
    by_class: dict[str, tuple[str, str, DataSourceConfig]] = {}
    for source in config.data_sources:
        classes = set(source.coverage.transaction_types) & set(_MONEY_CLASS_ORDER)
        if not classes:
            continue
        if len(classes) != 1:
            raise ValueError(f"Source {source.name!r} owns multiple public money classes.")
        class_key = classes.pop()
        if class_key in by_class:
            raise ValueError(f"Money class {class_key!r} resolves to multiple configured sources.")
        by_class[class_key] = (class_key, _MONEY_CLASS_LABELS[class_key], source)
    if set(by_class) != set(_MONEY_CLASS_ORDER):
        missing = ", ".join(sorted(set(_MONEY_CLASS_ORDER) - set(by_class)))
        raise ValueError(f"Configured money sources are incomplete; missing {missing}.")
    return tuple(by_class[class_key] for class_key in _MONEY_CLASS_ORDER)


def _person_identifier_key(source_order: tuple[tuple[str, str, DataSourceConfig], ...]) -> str:
    canonical_targets = {
        source.field_mappings.get("filer_id")
        for _, _, source in source_order
        if source.field_mappings.get("filer_id") is not None
    }
    if len(canonical_targets) != 1:
        raise ValueError("Configured public sources do not share one exact native filer identity mapping.")
    canonical_target = canonical_targets.pop()
    assert canonical_target is not None
    return canonical_target.replace(".", "_")


def _build_query_plan(config: JurisdictionConfig) -> RegionalQueryPlan:
    if config.jurisdiction.type != "state":
        raise ValueError("The current bounded money query accepts a state authority plan only.")
    source_order = _money_source_order(config)
    office_names = sorted(
        {
            office.replace("_", " ").casefold()
            for _, _, source in source_order
            for office in source.coverage.office_levels
            if office not in {"county", "municipal", "school_district", "special_district"}
        }
    )
    if not office_names:
        raise ValueError("The authority plan has no exact state-office scope.")
    return RegionalQueryPlan(
        subject=RegionalSubjectIdentity(
            kind="state",
            code=config.jurisdiction.code,
            name=config.jurisdiction.name,
        ),
        operational_scope=operational_scope_for_config_identity(config.jurisdiction.identity),
        authority_code=config.jurisdiction.code,
        source_order=source_order,
        person_identifier_key=_person_identifier_key(source_order),
        office_names=tuple(office_names),
    )


def _translation_value(
    registry: CoverageRegistry,
    source: ScopedIdentity,
    target_domain: str,
) -> tuple[str | None, str | None]:
    try:
        target = translate_identity(
            source,
            target_domain=target_domain,  # type: ignore[arg-type]
            translations=registry.identity_translations,
        )
    except IdentityTranslationError as error:
        return None, str(error)
    return (
        target.value if target_domain == "public_route" else f"{target.kind}/{target.value}",
        None,
    )


def _authority_name(reference: FilingAuthorityReference, registry: CoverageRegistry) -> str:
    if reference.name is not None:
        return reference.name
    row = next(
        (
            candidate
            for candidate in registry.rows
            if candidate.jurisdiction_type == reference.kind and candidate.jurisdiction_code == reference.code
        ),
        None,
    )
    return row.name if row is not None else reference.code


def _authority_context(
    *,
    subject: RegionalSubjectIdentity,
    canonical_path: str,
    registry: CoverageRegistry,
    official_urls: dict[str, str] | None = None,
    promotion_receipt: AuthorityPromotionReceipt | None = None,
) -> RegionalAuthorityContext:
    row = next(
        (
            candidate
            for candidate in registry.rows
            if candidate.jurisdiction_type == subject.kind and candidate.jurisdiction_code == subject.code
        ),
        None,
    )
    if row is None:
        return _refused_context(subject, f"Coverage registry has no typed row for {subject.kind}/{subject.code}.")

    source = ScopedIdentity(
        domain="geographic_subject",
        kind=subject.kind,
        value=subject.code,
    )
    public_route, public_route_error = _translation_value(registry, source, "public_route")
    acquisition_scope, acquisition_error = _translation_value(registry, source, "acquisition_scope")
    provenance_scope, provenance_error = _translation_value(registry, source, "provenance_scope")
    if promotion_receipt is not None:
        if (
            promotion_receipt.jurisdiction_code != subject.code
            or promotion_receipt.geographic_subject.kind != subject.kind
        ):
            raise ValueError("Authority promotion receipt belongs to a different typed geographic subject.")
        provenance_scope = promotion_receipt.provenance_scope
        provenance_error = None
    refusals = [message for message in (public_route_error, acquisition_error, provenance_error) if message is not None]
    if public_route is not None and public_route != canonical_path:
        refusals.append(f"Typed public route {public_route!r} contradicts canonical route {canonical_path!r}.")
        public_route = None

    relation = (
        IndependentAuthorityRelation(
            relation=promotion_receipt.authority_relation,
            authority=promotion_receipt.filing_authority,
        )
        if promotion_receipt is not None
        else row.authority_relation
    )
    filing_authorities: list[RegionalFilingAuthority] = []
    included_scopes: list[str] = []
    excluded_scopes: list[str] = []
    provenance_scopes: list[str] = []
    aggregation_disposition = "not_applicable"
    if relation.relation in {"independent", "inherited"}:
        references = [relation.authority]
        for reference in references:
            filing_authorities.append(
                RegionalFilingAuthority(
                    kind=reference.kind,
                    code=reference.code,
                    name=_authority_name(reference, registry),
                    scope=row.evidence_summary or "The registry carries no narrower inclusion scope.",
                    provenance_scope=(
                        promotion_receipt.provenance_scope
                        if promotion_receipt is not None
                        else row.operational_reason or "The registry carries no narrower provenance scope."
                    ),
                    official_url=(official_urls or {}).get(reference.code),
                )
            )
        included_scopes = [filing_authorities[0].scope]
        provenance_scopes = [filing_authorities[0].provenance_scope]
    elif relation.relation == "partitioned_overlapping":
        partitions = {partition.authority.code: partition.scope for partition in relation.partitions}
        provenance = {scope.authority.code: scope.source_scope for scope in relation.provenance}
        for reference in relation.authorities:
            filing_authorities.append(
                RegionalFilingAuthority(
                    kind=reference.kind,
                    code=reference.code,
                    name=_authority_name(reference, registry),
                    scope=partitions[reference.code],
                    provenance_scope=provenance[reference.code],
                    official_url=(official_urls or {}).get(reference.code),
                )
            )
        included_scopes = [partition.scope for partition in relation.partitions]
        excluded_scopes = list(relation.refusals)
        provenance_scopes = [scope.source_scope for scope in relation.provenance]
        aggregation_disposition = relation.deduplication.disposition
    else:
        aggregation_disposition = "refuse"
        excluded_scopes = [relation.reason]
        refusals.append(relation.reason)

    translation_status = "refused" if refusals or relation.relation == "unresolved" else "resolved"
    return RegionalAuthorityContext(
        subject=subject,
        public_route=public_route,
        acquisition_scope=acquisition_scope,
        provenance_scope=provenance_scope,
        relation=relation.relation,
        filing_authorities=filing_authorities,
        included_scopes=included_scopes,
        excluded_scopes=excluded_scopes,
        provenance_scopes=provenance_scopes,
        aggregation_disposition=aggregation_disposition,
        evidence_date=promotion_receipt.issued_at.date() if promotion_receipt is not None else row.evidence_date,
        translation_status=translation_status,
        refusal_reasons=list(dict.fromkeys(refusals)),
    )


def _refused_context(subject: RegionalSubjectIdentity, reason: str) -> RegionalAuthorityContext:
    return RegionalAuthorityContext(
        subject=subject,
        public_route=None,
        acquisition_scope=None,
        provenance_scope=None,
        relation="unresolved",
        filing_authorities=[],
        included_scopes=[],
        excluded_scopes=[],
        provenance_scopes=[],
        aggregation_disposition="refuse",
        evidence_date=None,
        translation_status="refused",
        refusal_reasons=[reason],
    )


def _load_owner_context() -> tuple[
    RegionalQueryPlan,
    RegionalAuthorityContext,
    CoverageRegistryRow,
    object,
    date,
    AuthorityPromotionReceipt | None,
]:
    config = load_jurisdiction_config(_WA_CONFIG_PATH)
    plan = _build_query_plan(config)
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    lifecycle = load_lifecycle(DEFAULT_IMPLEMENTED_REGION_LIFECYCLE_PATH)
    registry_row = _one_row_for_code(registry.rows, plan.subject.code)
    lifecycle_row = _one_row_for_code(lifecycle.rows, plan.subject.code)
    promotion_receipt_path = os.environ.get(AUTHORITY_PROMOTION_RECEIPT_ENV)
    promotion_receipt = (
        load_authority_promotion_receipt(promotion_receipt_path) if promotion_receipt_path is not None else None
    )
    if getattr(registry_row, "jurisdiction_type") != plan.subject.kind:
        raise ValueError("Coverage and config subject kinds disagree.")
    if getattr(registry_row, "tier") != getattr(lifecycle_row, "public_claim_status"):
        raise ValueError("Coverage and lifecycle public-claim owners disagree.")
    source_names = {source.name for _, _, source in plan.source_order}
    if not source_names.issubset(set(getattr(registry_row, "source_names"))):
        raise ValueError("Configured money sources are absent from the coverage row.")
    context = _authority_context(
        subject=plan.subject,
        canonical_path=f"/state/{plan.subject.code}",
        registry=registry,
        official_urls={plan.authority_code: plan.source_order[0][2].url},
        promotion_receipt=promotion_receipt,
    )
    return plan, context, registry_row, lifecycle_row, lifecycle.updated_at, promotion_receipt


def _runtime_source_rows(
    conn: psycopg.Connection,
    plan: RegionalQueryPlan,
) -> dict[str, dict[str, Any]]:
    source_names = [source.name for _, _, source in plan.source_order]
    class_keys = [class_key for class_key, _, _ in plan.source_order]
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _REGIONAL_SOURCE_RUNTIME_SQL,
            {
                "domain": "campaign_finance",
                "operational_scope": plan.operational_scope,
                "source_names": source_names,
                "class_keys": class_keys,
            },
        )
        return {row["source_name"]: row for row in cursor.fetchall()}


def _source_status(row: dict[str, Any], *, as_of: datetime) -> tuple[str, str]:
    if row["data_source_id"] is None:
        return "unavailable", "The exact configured runtime source is absent."
    pull_status = row["last_pull_status"]
    pull_at = row["last_pull_at"]
    if pull_at is None or pull_status is None:
        return "degraded", "Runtime source-pull success is not recorded."
    if pull_status != "success":
        return "degraded", f"Latest source pull is {pull_status}; bounded rows remain visible with that warning."
    if as_of - pull_at.astimezone(timezone.utc) > _DAILY_STALE_AFTER:
        return "stale", "The last successful pull is older than the configured daily-source freshness window."
    return "available", "The exact configured source has a recent successful pull."


def _recurrence_status(row: dict[str, Any]) -> str:
    if row["latest_refresh_status"] is None or row["latest_refresh_completed_at"] is None:
        return "unknown"
    if row["latest_refresh_status"] == "success" and row["latest_refresh_execution_origin"] == "scheduled":
        return "qualified"
    return "degraded"


def _query_rows(conn: psycopg.Connection, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return list(cursor.fetchall())


def _health_for_sources(
    *,
    plan: RegionalQueryPlan,
    context: RegionalAuthorityContext,
    sources: list[RegionalFinanceSource],
    promotion_receipt: AuthorityPromotionReceipt | None = None,
) -> list[RegionalAuthorityHealth]:
    expected = [source.source_identity for source in sources]
    source_evidence = [
        AuthoritySourceEvidence(
            source_identity=source.source_identity,
            freshness_status={
                "available": "fresh",
                "stale": "stale",
                "degraded": "degraded",
                "unavailable": "unknown",
            }[source.status],
            observed_at=source.last_successful_pull,
        )
        for source in sources
    ]
    recurrence_evidence = [
        AuthorityRecurrenceEvidence(
            source_identity=source.source_identity,
            pull_status=source.latest_refresh_status,
            execution_origin=source.latest_refresh_execution_origin,
            completed_at=source.latest_refresh_completed_at,
        )
        for source in sources
        if source.latest_refresh_status is not None
    ]
    if promotion_receipt is not None:
        promotion = assess_authority_promotion_receipt(
            promotion_receipt,
            jurisdiction_code=plan.subject.code,
            authority_identity=f"{plan.subject.kind}/{plan.authority_code}",
            expected_source_identities=expected,
            source_evidence=source_evidence,
            recurrence_evidence=recurrence_evidence,
        )
    else:
        promotion = assess_authority_promotion(
            AuthorityPromotionEvidence(
                authority_identity=f"{plan.subject.kind}/{plan.authority_code}",
                authority_relation=context.relation,
                aggregation_disposition=context.aggregation_disposition,
                expected_source_identities=expected,
                source_evidence=source_evidence,
                recurrence_evidence=recurrence_evidence,
                provenance_source_identities=[],
                keel_source_identities=[],
                deployed_source_identities=[],
                source_revision=None,
                api_revision=None,
                web_revision=None,
            )
        )
    statuses = {source.status for source in sources}
    freshness_status = (
        "unavailable"
        if statuses == {"unavailable"}
        else "degraded"
        if "unavailable" in statuses or "degraded" in statuses
        else "stale"
        if "stale" in statuses
        else "available"
    )
    recurrence_statuses = {source.recurrence_status for source in sources}
    recurrence_status = (
        "refused"
        if context.relation == "unresolved"
        else "degraded"
        if "degraded" in recurrence_statuses
        else "unknown"
        if "unknown" in recurrence_statuses
        else "qualified"
    )
    recurrence_times = [source.latest_refresh_completed_at for source in sources if source.latest_refresh_completed_at]
    refusals = list(dict.fromkeys([*context.refusal_reasons, *promotion.refusal_reasons]))
    return [
        RegionalAuthorityHealth(
            authority_code=plan.authority_code,
            freshness_status=freshness_status,
            degraded_source_names=[source.name for source in sources if source.status != "available"],
            recurrence_status=recurrence_status,
            recurrence_observed_at=max(recurrence_times) if recurrence_times else None,
            revision_parity=promotion.revision_parity,
            deployed_revision=(
                promotion_receipt.promotion_evidence.source_revision if promotion_receipt is not None else None
            ),
            promotion_eligible=promotion.eligible,
            refusal_reasons=refusals,
        )
    ]


def _unavailable_detail(
    *,
    plan: RegionalQueryPlan,
    context: RegionalAuthorityContext,
    as_of: datetime,
    registry_evidence_date: date | None,
    lifecycle_updated_at: date | None,
    reason: str,
    promotion_receipt: AuthorityPromotionReceipt | None = None,
) -> RegionalFinanceDetail:
    period_start, period_end = _current_biennium(as_of)
    sources = [
        RegionalFinanceSource(
            class_key=class_key,
            authority_code=plan.authority_code,
            source_identity=f"{plan.operational_scope}:{source.name}",
            name=source.name,
            url=source.url,
            status="unavailable",
            last_successful_pull=None,
            last_verified_working=source.last_verified_working,
            latest_refresh_completed_at=None,
            latest_refresh_status=None,
            latest_refresh_execution_origin="unknown",
            recurrence_status="unknown",
            reason=reason,
        )
        for class_key, _, source in plan.source_order
    ]
    health = _health_for_sources(
        plan=plan,
        context=context,
        sources=sources,
        promotion_receipt=promotion_receipt,
    )
    money = [
        RegionalMoneyClass(
            key=class_key,
            authority_code=plan.authority_code,
            source_identity=f"{plan.operational_scope}:{source.name}",
            label=label,
            status="unavailable",
            amount=None,
            transaction_count=0,
            data_through=None,
            source_name=source.name,
            reason=reason,
        )
        for class_key, label, source in plan.source_order
    ]
    return RegionalFinanceDetail(
        subject=plan.subject,
        authority_context=context,
        authority_health=health,
        as_of=as_of,
        period_start=period_start,
        period_end=period_end,
        money=money,
        candidates=[],
        committees=[],
        sources=sources,
        registry_evidence_date=registry_evidence_date,
        lifecycle_registry_updated_at=lifecycle_updated_at,
        included=["No money is included while exact runtime evidence is unavailable."],
        excluded=["Federal, county, municipal, school-district, special-district, foreign, and unproved rows."],
        named_gaps=[reason],
    )


def fetch_washington_state_finance(
    conn: psycopg.Connection | None,
    *,
    as_of: datetime | None = None,
) -> RegionalFinanceDetail:
    """Compatibility entrypoint over the authority-parameterized query owner."""

    response_as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    plan, context, registry_row, lifecycle_row, lifecycle_updated_at, promotion_receipt = _load_owner_context()
    if conn is None:
        return _unavailable_detail(
            plan=plan,
            context=context,
            as_of=response_as_of,
            registry_evidence_date=getattr(registry_row, "evidence_date"),
            lifecycle_updated_at=lifecycle_updated_at,
            reason="A database-backed authority projection was not requested.",
            promotion_receipt=promotion_receipt,
        )

    period_start, period_end = _current_biennium(response_as_of)
    source_names = [source.name for _, _, source in plan.source_order]
    class_keys = [class_key for class_key, _, _ in plan.source_order]
    params: dict[str, Any] = {
        "domain": "campaign_finance",
        "operational_scope": plan.operational_scope,
        "source_names": source_names,
        "class_keys": class_keys,
        "office_names": list(plan.office_names),
        "jurisdiction_type_values": ["state", "statewide", "legislative"],
        "period_start": period_start,
        "period_end": period_end,
        "candidate_limit": _CANDIDATE_LIMIT,
        "committee_limit": _COMMITTEE_LIMIT,
        "person_identifier_key": plan.person_identifier_key,
        "authority_code": plan.authority_code,
        "state_code": plan.subject.code,
        "civic_office_level": "state",
        "filer_field": "filer_id",
        "office_field": "office",
        "jurisdiction_type_field": "jurisdiction_type",
        "ie_candidate_filer_field": "candidate_filer_id",
        "ie_origin_field": "origin",
        "ie_candidate_origin": "C6.3 - Identified Entities",
        "ie_candidate_office_field": "candidate_office",
        "ie_candidate_jurisdiction_field": "candidate_jurisdiction",
        "subject_jurisdiction_name": f"state of {plan.subject.name}".casefold(),
        "legislative_jurisdiction_pattern": r"^leg district [0-9]{1,2} - (house|senate)$",
    }
    runtime_rows = _runtime_source_rows(conn, plan)
    sources: list[RegionalFinanceSource] = []
    source_statuses: dict[str, str] = {}
    named_gaps = ["Candidate roster completeness is not established by the lifecycle owner."]
    for class_key, _, configured in plan.source_order:
        runtime = runtime_rows[configured.name]
        status, reason = _source_status(runtime, as_of=response_as_of)
        source_statuses[configured.name] = status
        if status != "available":
            named_gaps.append(f"{configured.name}: {reason}")
        execution_origin = runtime["latest_refresh_execution_origin"] or "unknown"
        if execution_origin not in {"manual", "scheduled"}:
            execution_origin = "unknown"
        sources.append(
            RegionalFinanceSource(
                class_key=class_key,
                authority_code=plan.authority_code,
                source_identity=f"{plan.operational_scope}:{configured.name}",
                name=configured.name,
                url=configured.url,
                status=status,
                last_successful_pull=(runtime["last_pull_at"] if runtime["last_pull_status"] == "success" else None),
                last_verified_working=configured.last_verified_working,
                latest_refresh_completed_at=runtime["latest_refresh_completed_at"],
                latest_refresh_status=runtime["latest_refresh_status"],
                latest_refresh_execution_origin=execution_origin,
                recurrence_status=_recurrence_status(runtime),
                reason=reason,
            )
        )

    money_rows = {row["source_name"]: row for row in _query_rows(conn, _REGIONAL_MONEY_SQL, params)}
    money: list[RegionalMoneyClass] = []
    for class_key, label, configured in plan.source_order:
        status = source_statuses[configured.name]
        row = money_rows.get(configured.name)
        amount = Decimal("0.00") if row is None else row["amount"]
        count = 0 if row is None else row["transaction_count"]
        data_through = None if row is None else row["data_through"]
        money.append(
            RegionalMoneyClass(
                key=class_key,
                authority_code=plan.authority_code,
                source_identity=f"{plan.operational_scope}:{configured.name}",
                label=label,
                status=status,
                amount=None if status == "unavailable" else amount,
                transaction_count=0 if status == "unavailable" else count,
                data_through=None if status == "unavailable" else data_through,
                source_name=configured.name,
                reason=(
                    "No exact runtime source is available; no zero is inferred."
                    if status == "unavailable"
                    else "Exact authority-scoped rows in the current reporting window."
                ),
            )
        )

    candidates = [RegionalCandidate.model_validate(row) for row in _query_rows(conn, _REGIONAL_CANDIDATE_SQL, params)]
    committees = [RegionalCommittee.model_validate(row) for row in _query_rows(conn, _REGIONAL_COMMITTEE_SQL, params)]
    if not candidates:
        named_gaps.append("No current-window candidacies are connected in civic data.")
    if not committees and any(row.transaction_count > 0 for row in money):
        named_gaps.append("Bounded money exists but committee identities could not be presented.")
    if getattr(lifecycle_row, "completeness_intelligence_maturity") == "not_started":
        named_gaps.append("Source completeness is not established by the lifecycle owner.")
    health = _health_for_sources(
        plan=plan,
        context=context,
        sources=sources,
        promotion_receipt=promotion_receipt,
    )
    return RegionalFinanceDetail(
        subject=plan.subject,
        authority_context=context,
        authority_health=health,
        as_of=response_as_of,
        period_start=period_start,
        period_end=period_end,
        money=money,
        candidates=candidates,
        committees=committees,
        sources=sources,
        registry_evidence_date=getattr(registry_row, "evidence_date"),
        lifecycle_registry_updated_at=lifecycle_updated_at,
        included=[
            "Current-window contributions, expenditures, and loans for exact configured state-office scope.",
            "Candidate-targeted independent expenditures for exact configured state-office scope.",
            "Only active transaction and filing provenance resolving to the same configured authority source.",
        ],
        excluded=[
            "Federal, county, municipal, school-district, special-district, and foreign filing activity.",
            "Memo, terminated, superseded, unreliable-date, and unproved-authority rows.",
            "C6.2 vendor outlays and C6.5 funding-source records are not combined with candidate-targeted money.",
            "County proxies and local claims are never combined with the authority total.",
        ],
        named_gaps=list(dict.fromkeys([*named_gaps, *health[0].refusal_reasons])),
    )


def _finance_status(detail: RegionalFinanceDetail) -> str:
    statuses = {row.status for row in detail.money}
    return (
        "unavailable"
        if statuses == {"unavailable"}
        else "degraded"
        if "unavailable" in statuses or "degraded" in statuses
        else "stale"
        if "stale" in statuses
        else "available"
    )


def _washington_state_node(
    conn: psycopg.Connection | None,
    *,
    as_of: datetime | None = None,
) -> RegionalNavigationNode:
    try:
        detail = fetch_washington_state_finance(conn, as_of=as_of)
    except (OSError, TypeError, ValueError) as error:
        subject = RegionalSubjectIdentity(kind="state", code="WA", name="Washington")
        context = _refused_context(subject, f"Checked-in authority owners are contradictory: {error}")
        return RegionalNavigationNode(
            kind="state",
            name=subject.name,
            state_code="WA",
            state_name=subject.name,
            slug=None,
            canonical_path="/state/WA",
            geometry_reference=None,
            finance=RegionalFinanceState(
                status="unavailable",
                authority_context=context,
                authority_health=[],
                reason=context.refusal_reasons[0],
            ),
            finance_detail=None,
            proxy_analysis=None,
        )
    status = _finance_status(detail)
    return RegionalNavigationNode(
        kind="state",
        name=detail.subject.name,
        state_code="WA",
        state_name=detail.subject.name,
        slug=None,
        canonical_path="/state/WA",
        geometry_reference=None,
        finance=RegionalFinanceState(
            status=status,
            authority_context=detail.authority_context,
            authority_health=detail.authority_health,
            reason={
                "available": "Exact authority-scoped campaign-finance activity is available.",
                "stale": "Authority-scoped activity is available but at least one source is stale.",
                "degraded": "Authority-scoped activity is partially available with named source limitations.",
                "unavailable": "Typed geography is known, but exact authority money is unavailable.",
            }[status],
        ),
        finance_detail=detail,
        proxy_analysis=None,
    )


def _unavailable_node(
    *,
    kind: RegionalNodeKind,
    code: str,
    name: str,
    state_code: str,
    state_name: str,
    slug: str | None,
    canonical_path: str,
    registry: CoverageRegistry,
    reason: str,
    geometry_reference: RegionalGeometryReference | None = None,
    proxy_analysis: RegionalProxyAnalysis | None = None,
) -> RegionalNavigationNode:
    subject = RegionalSubjectIdentity(kind=kind, code=code, name=name)
    context = _authority_context(
        subject=subject,
        canonical_path=canonical_path,
        registry=registry,
    )
    health = [
        RegionalAuthorityHealth(
            authority_code=authority.code,
            freshness_status="unavailable",
            degraded_source_names=[],
            recurrence_status="unknown",
            recurrence_observed_at=None,
            revision_parity="unknown",
            deployed_revision=None,
            promotion_eligible=False,
            refusal_reasons=list(
                dict.fromkeys(
                    [
                        *context.refusal_reasons,
                        "No exact authority freshness, recurrence, provenance, Keel, deployed, or revision proof is supplied.",
                    ]
                )
            ),
        )
        for authority in context.filing_authorities
    ]
    return RegionalNavigationNode(
        kind=kind,
        name=name,
        state_code=state_code,
        state_name=state_name,
        slug=slug,
        canonical_path=canonical_path,
        geometry_reference=geometry_reference,
        finance=RegionalFinanceState(
            status="unavailable",
            authority_context=context,
            authority_health=health,
            reason=reason,
        ),
        finance_detail=None,
        proxy_analysis=proxy_analysis,
    )


def _state_node(
    state_code: str,
    conn: psycopg.Connection | None = None,
    *,
    as_of: datetime | None = None,
    registry: CoverageRegistry | None = None,
) -> RegionalNavigationNode:
    if state_code == "WA":
        return _washington_state_node(conn, as_of=as_of)
    active_registry = registry or load_registry(DEFAULT_REGISTRY_PATH)
    state_name = USPS_TO_STATE_NAME[state_code]
    return _unavailable_node(
        kind="state",
        code=state_code,
        name=state_name,
        state_code=state_code,
        state_name=state_name,
        slug=None,
        canonical_path=f"/state/{state_code}",
        registry=active_registry,
        reason="No authorized public state campaign-finance projection is available.",
    )


def _explicit_child_nodes(registry: CoverageRegistry) -> tuple[RegionalNavigationNode, ...]:
    _, wake_proxy_cities = _resolve_county_proxy_cities(state="NC", county_slug="wake")
    wake = _unavailable_node(
        kind="county",
        code="NC_WAKE",
        name="Wake County",
        state_code="NC",
        state_name=USPS_TO_STATE_NAME["NC"],
        slug="wake",
        canonical_path="/state/NC/county/wake",
        registry=registry,
        reason="No explicit county-wide campaign-finance coverage lineage is available.",
        geometry_reference=RegionalGeometryReference(
            namespace="civic",
            kind="electoral_division_name",
            value="nc_county_wake",
        ),
        proxy_analysis=RegionalProxyAnalysis(
            label="Mapped committee-city disbursements",
            scope_label=f"{' and '.join(city.title() for city in wake_proxy_cities)} committees",
            excludes=["county-wide finance", "donor residence", "candidate residence"],
            overlap_disposition="not_combined",
        ),
    )
    seattle = _unavailable_node(
        kind="municipality",
        code="WA_SEATTLE",
        name="Seattle",
        state_code="WA",
        state_name="Washington",
        slug="seattle",
        canonical_path="/state/WA/municipality/seattle",
        registry=registry,
        reason=(
            "The accepted typed relation is partitioned across PDC, the Seattle City Clerk, and SEEC. "
            "No authority scopes or state/local totals are substituted or combined."
        ),
    )
    new_york_city = _unavailable_node(
        kind="municipality",
        code="NY_NEW_YORK",
        name="New York City",
        state_code="NY",
        state_name="New York",
        slug="new-york-city",
        canonical_path="/state/NY/municipality/new-york-city",
        registry=registry,
        reason=(
            "The accepted typed CFB/NYSBOE relation is a bounded post-2020 partition/overlap. "
            "No New York State or combined total is shown."
        ),
    )
    return wake, seattle, new_york_city


def _all_nodes(conn: psycopg.Connection | None = None) -> tuple[RegionalNavigationNode, ...]:
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    states = tuple(_state_node(state_code, conn, registry=registry) for state_code in LAUNCH_SCOPE_USPS_STATES)
    return (*states, *_explicit_child_nodes(registry))


def resolve_regional_navigation_node(
    *,
    kind: RegionalNodeKind,
    state_code: str,
    slug: str | None,
    conn: psycopg.Connection | None = None,
    as_of: datetime | None = None,
) -> RegionalNavigationNode | None:
    """Resolve an exact route-owned identity; typed finance joins may still refuse."""

    if kind == "state":
        if slug is not None or state_code not in LAUNCH_SCOPE_USPS_STATES:
            return None
        return _state_node(state_code, conn, as_of=as_of)
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    nodes = [node for node in _explicit_child_nodes(registry) if node.kind == kind]
    return next((node for node in nodes if node.state_code == state_code and node.slug == slug), None)


def list_regional_navigation_children(
    *,
    state_code: str,
    kind: RegionalChildKind,
) -> list[RegionalNavigationNode]:
    """List explicit child routes, never inferred geographic contents."""

    registry = load_registry(DEFAULT_REGISTRY_PATH)
    return [node for node in _explicit_child_nodes(registry) if node.kind == kind and node.state_code == state_code]


def _search_values(node: RegionalNavigationNode) -> Iterable[str]:
    yield node.name
    yield node.state_code
    yield node.state_name
    yield node.finance.authority_context.subject.code
    if node.slug is not None:
        yield node.slug


def _match_rank(node: RegionalNavigationNode, normalized_query: str) -> int | None:
    values = [value.casefold() for value in _search_values(node)]
    if normalized_query in values:
        return 0
    if any(value.startswith(normalized_query) for value in values):
        return 1
    if any(normalized_query in value for value in values):
        return 2
    return None


def search_regional_navigation_nodes(
    *,
    query: str,
    limit: int,
    conn: psycopg.Connection | None = None,
) -> list[RegionalNavigationNode]:
    """Search typed route subjects while retaining explicit finance refusal."""

    normalized_query = query.strip().casefold()
    if len(normalized_query) < 2:
        return []
    kind_rank = {
        "state": 0,
        "county": 1,
        "municipality": 2,
        "school_district": 3,
        "special_district": 4,
    }
    ranked = [
        (rank, kind_rank[node.kind], node.name, node.canonical_path, node)
        for node in _all_nodes(conn)
        if (rank := _match_rank(node, normalized_query)) is not None
    ]
    ranked.sort(key=lambda item: item[:-1])
    return [item[-1] for item in ranked[:limit]]


__all__ = [
    "fetch_washington_state_finance",
    "list_regional_navigation_children",
    "resolve_regional_navigation_node",
    "search_regional_navigation_nodes",
]
