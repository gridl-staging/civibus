import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";
import type { RegionalNavigationNode } from "$lib/server/api/state-pages-contract";
import { sanitizeExternalUrl } from "$lib/url/sanitize-external-url";

export type RegionalBreadcrumbCrumb = { label: string; href?: string };
export type RegionalRouteMetadata = {
  title: string;
  description: string;
  robots: string;
};
export type RegionalSearchCard = {
  key: string;
  name: string;
  routeLabel: string;
  contextLine: string;
  href: string;
};
export type RegionalFeatureLink = { href: string; label: string };
export type RegionalClockPresentation = {
  datetime: string | null;
  label: string;
};
export type RegionalFinancePresentation = {
  subject: { kind: string; code: string; name: string };
  authorityContext: {
    relation: string;
    translationStatus: string;
    publicRoute: string | null;
    acquisitionScope: string | null;
    provenanceScope: string | null;
    aggregationDisposition: string;
    evidenceDate: RegionalClockPresentation;
    authorities: {
      kind: string;
      code: string;
      name: string;
      scope: string;
      provenanceScope: string;
      href: string | null;
    }[];
    includedScopes: string[];
    excludedScopes: string[];
    provenanceScopes: string[];
    refusalReasons: string[];
  };
  authorityHealth: {
    authorityCode: string;
    freshnessStatus: string;
    degradedSourceNames: string[];
    recurrenceStatus: string;
    recurrenceObservedAt: RegionalClockPresentation;
    revisionParity: string;
    deployedRevision: string | null;
    promotionEligible: boolean;
    refusalReasons: string[];
  }[];
  windowLabel: string;
  asOf: RegionalClockPresentation;
  money: {
    key: string;
    label: string;
    status: string;
    amountLabel: string;
    transactionLabel: string;
    dataThrough: RegionalClockPresentation;
    reason: string;
  }[];
  sources: {
    classKey: string;
    authorityCode: string;
    sourceIdentity: string;
    name: string;
    href: string | null;
    status: string;
    lastSuccessfulPull: RegionalClockPresentation;
    lastVerifiedWorking: RegionalClockPresentation;
    latestRefreshCompletedAt: RegionalClockPresentation;
    latestRefreshStatus: string;
    latestRefreshExecutionOrigin: string;
    recurrenceStatus: string;
    reason: string;
  }[];
  registryEvidenceDate: RegionalClockPresentation;
  lifecycleRegistryUpdatedAt: RegionalClockPresentation;
  candidates: {
    personName: string;
    personHref: string;
    candidacyHref: string;
    contestName: string;
    contestHref: string;
    officeName: string;
    officeHref: string;
    divisionName: string | null;
    party: string | null;
    currentOfficeholdingHref: string | null;
    moneyLabel: string;
    transactionLabel: string;
    connectionLabel: string;
  }[];
  committees: {
    name: string;
    href: string;
    activityLabel: string;
    transactionLabel: string;
    dataThrough: RegionalClockPresentation;
  }[];
  included: string[];
  excluded: string[];
  namedGaps: string[];
};

const NODE_KIND_LABELS: Record<RegionalNavigationNode["kind"], string> = {
  state: "State",
  county: "County",
  municipality: "Municipality",
  school_district: "School district",
  special_district: "Special district",
};

export function buildRegionalBreadcrumbs(
  node: RegionalNavigationNode,
): RegionalBreadcrumbCrumb[] {
  if (node.kind === "state") {
    return [{ label: "Home", href: "/" }, { label: node.name }];
  }
  return [
    { label: "Home", href: "/" },
    { label: node.state_name, href: `/state/${node.state_code}` },
    { label: `${node.name} · ${NODE_KIND_LABELS[node.kind]}` },
  ];
}

export function buildRegionalRouteMetadata(
  node: RegionalNavigationNode,
): RegionalRouteMetadata {
  const kindLabel = NODE_KIND_LABELS[node.kind];
  return {
    title: `${node.name} | ${kindLabel} | Civibus`,
    description: `Regional navigation for ${node.name}. Campaign-finance data is ${node.finance.status}.`,
    // Regional discovery is intentionally pre-publication until the selected
    // state and municipality pass their separate coverage/product gates.
    robots: "noindex,follow",
  };
}

export function buildRegionalAliasRedirect(
  node: RegionalNavigationNode,
  currentUrl: URL,
): string | null {
  if (currentUrl.pathname === node.canonical_path) return null;
  return `${node.canonical_path}${currentUrl.search}`;
}

export function buildRegionalFeatureLinks(
  nodes: RegionalNavigationNode[],
  geometry: CivicGeometryFeatureCollection,
): Record<string, RegionalFeatureLink> {
  const featureLinks: Record<string, RegionalFeatureLink> = {};
  const ambiguousFeatureIds = new Set<string>();
  for (const node of nodes) {
    const reference = node.geometry_reference;
    if (
      reference === null ||
      reference.namespace !== "civic" ||
      reference.kind !== "electoral_division_name"
    ) {
      continue;
    }
    const matches = geometry.features.filter(
      (feature) =>
        feature.properties.name === reference.value &&
        feature.properties.state === node.state_code &&
        feature.properties.division_type === node.kind,
    );
    if (matches.length === 1) {
      const featureId = matches[0].properties.id;
      if (featureLinks[featureId] !== undefined) {
        delete featureLinks[featureId];
        ambiguousFeatureIds.add(featureId);
        continue;
      }
      if (ambiguousFeatureIds.has(featureId)) continue;
      featureLinks[featureId] = {
        href: node.canonical_path,
        label: node.name,
      };
    }
  }
  return featureLinks;
}

export function buildRegionalSearchCards(
  nodes: RegionalNavigationNode[],
): RegionalSearchCard[] {
  return nodes.map((node) => ({
    key: `${node.kind}:${node.canonical_path}`,
    name: node.name,
    routeLabel: NODE_KIND_LABELS[node.kind],
    contextLine:
      node.finance.authority_context.filing_authorities.length > 0
        ? `Finance ${node.finance.status} · ${node.finance.authority_context.relation}: ${node.finance.authority_context.filing_authorities.map((authority) => authority.name).join(", ")}`
        : `Finance ${node.finance.status} · authority translation ${node.finance.authority_context.translation_status}`,
    href: node.canonical_path,
  }));
}

function buildClockPresentation(
  value: string | null,
): RegionalClockPresentation {
  if (value === null) return { datetime: null, label: "Unknown" };
  const dateOnly = value.slice(0, 10);
  return { datetime: value, label: dateOnly };
}

function formatMoney(value: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function transactionLabel(count: number): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? "transaction" : "transactions"}`;
}

export function buildRegionalStateFinancePresentation(
  node: RegionalNavigationNode,
): RegionalFinancePresentation | null {
  const detail = node.finance_detail;
  if (!detail) return null;

  return {
    subject: {
      kind: detail.subject.kind,
      code: detail.subject.code,
      name: detail.subject.name,
    },
    authorityContext: {
      relation: detail.authority_context.relation,
      translationStatus: detail.authority_context.translation_status,
      publicRoute: detail.authority_context.public_route,
      acquisitionScope: detail.authority_context.acquisition_scope,
      provenanceScope: detail.authority_context.provenance_scope,
      aggregationDisposition:
        detail.authority_context.aggregation_disposition,
      evidenceDate: buildClockPresentation(
        detail.authority_context.evidence_date,
      ),
      authorities: detail.authority_context.filing_authorities.map(
        (authority) => ({
          kind: authority.kind,
          code: authority.code,
          name: authority.name,
          scope: authority.scope,
          provenanceScope: authority.provenance_scope,
          href: sanitizeExternalUrl(authority.official_url),
        }),
      ),
      includedScopes: [...detail.authority_context.included_scopes],
      excludedScopes: [...detail.authority_context.excluded_scopes],
      provenanceScopes: [...detail.authority_context.provenance_scopes],
      refusalReasons: [...detail.authority_context.refusal_reasons],
    },
    authorityHealth: detail.authority_health.map((health) => ({
      authorityCode: health.authority_code,
      freshnessStatus: health.freshness_status,
      degradedSourceNames: [...health.degraded_source_names],
      recurrenceStatus: health.recurrence_status,
      recurrenceObservedAt: buildClockPresentation(
        health.recurrence_observed_at,
      ),
      revisionParity: health.revision_parity,
      deployedRevision: health.deployed_revision,
      promotionEligible: health.promotion_eligible,
      refusalReasons: [...health.refusal_reasons],
    })),
    windowLabel: `${detail.period_start} through ${detail.period_end}`,
    asOf: buildClockPresentation(detail.as_of),
    money: detail.money.map((row) => ({
      key: row.key,
      label: row.label,
      status: row.status,
      amountLabel:
        row.amount === null ? "Unavailable" : formatMoney(row.amount),
      transactionLabel: transactionLabel(row.transaction_count),
      dataThrough: buildClockPresentation(row.data_through),
      reason: row.reason,
    })),
    sources: detail.sources.map((source) => ({
      classKey: source.class_key,
      authorityCode: source.authority_code,
      sourceIdentity: source.source_identity,
      name: source.name,
      href: sanitizeExternalUrl(source.url),
      status: source.status,
      lastSuccessfulPull: buildClockPresentation(source.last_successful_pull),
      lastVerifiedWorking: buildClockPresentation(source.last_verified_working),
      latestRefreshCompletedAt: buildClockPresentation(
        source.latest_refresh_completed_at,
      ),
      latestRefreshStatus: source.latest_refresh_status ?? "Unknown",
      latestRefreshExecutionOrigin:
        source.latest_refresh_execution_origin,
      recurrenceStatus: source.recurrence_status,
      reason: source.reason,
    })),
    registryEvidenceDate: buildClockPresentation(detail.registry_evidence_date),
    lifecycleRegistryUpdatedAt: buildClockPresentation(
      detail.lifecycle_registry_updated_at,
    ),
    candidates: detail.candidates.map((candidate) => ({
      personName: candidate.person_name,
      personHref: `/person/${encodeURIComponent(candidate.person_id)}`,
      candidacyHref: `/candidacy/${encodeURIComponent(candidate.candidacy_id)}`,
      contestName: candidate.contest_name,
      contestHref: `/contest/${encodeURIComponent(candidate.contest_id)}`,
      officeName: candidate.office_title ?? candidate.office_name,
      officeHref: `/office/${encodeURIComponent(candidate.office_id)}`,
      divisionName: candidate.division_name,
      party: candidate.party,
      currentOfficeholdingHref:
        candidate.current_officeholding_id === null
          ? null
          : `/officeholding/${encodeURIComponent(candidate.current_officeholding_id)}`,
      moneyLabel:
        candidate.money_connection === "connected" &&
        candidate.activity_amount !== null
          ? formatMoney(candidate.activity_amount)
          : "Unavailable",
      transactionLabel: transactionLabel(candidate.transaction_count),
      connectionLabel:
        candidate.money_connection === "connected"
          ? `Connected by unique ${candidate.native_filer_identifier?.authority_code ?? "authority"} native filer ID`
          : "Money connection unavailable; no name match used",
    })),
    committees: detail.committees.map((committee) => ({
      name: committee.name,
      href: `/committee/${encodeURIComponent(committee.committee_id)}`,
      activityLabel: formatMoney(committee.activity_amount),
      transactionLabel: transactionLabel(committee.transaction_count),
      dataThrough: buildClockPresentation(committee.data_through),
    })),
    included: [...detail.included],
    excluded: [...detail.excluded],
    namedGaps: [...detail.named_gaps],
  };
}
