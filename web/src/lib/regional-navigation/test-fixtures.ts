import type {
  RegionalAuthorityContext,
  RegionalAuthorityHealth,
  RegionalFinanceStatus,
  RegionalMoneyClassKey,
  RegionalNavigationNode,
  RegionalSubjectIdentity,
} from "../server/api/state-pages-contract.ts";

const SOURCE_NAMES: Record<RegionalMoneyClassKey, string> = {
  contributions: "WA PDC Contributions",
  expenditures: "WA PDC Expenditures",
  independent_expenditures: "WA PDC Independent Expenditures",
  loans: "WA PDC Loans",
};

const MONEY_VALUES: Record<RegionalMoneyClassKey, string> = {
  contributions: "125.50",
  expenditures: "80.25",
  independent_expenditures: "45.75",
  loans: "20.00",
};

const MONEY_LABELS: Record<RegionalMoneyClassKey, string> = {
  contributions: "Contributions",
  expenditures: "Expenditures",
  independent_expenditures: "Candidate-targeted independent expenditures",
  loans: "Loans",
};

const MONEY_KEYS = [
  "contributions",
  "expenditures",
  "independent_expenditures",
  "loans",
] as const;

function refusedContext(
  subject: RegionalSubjectIdentity,
  publicRoute: string | null,
  reason: string,
): RegionalAuthorityContext {
  return {
    subject,
    public_route: publicRoute,
    acquisition_scope: null,
    provenance_scope: null,
    relation: "unresolved",
    filing_authorities: [],
    included_scopes: [],
    excluded_scopes: [],
    provenance_scopes: [],
    aggregation_disposition: "refuse",
    evidence_date: null,
    translation_status: "refused",
    refusal_reasons: [reason],
  };
}

function refusedHealth(
  authorityCode: string,
  status: RegionalFinanceStatus = "unavailable",
): RegionalAuthorityHealth {
  return {
    authority_code: authorityCode,
    freshness_status: status,
    degraded_source_names: status === "available" ? [] : Object.values(SOURCE_NAMES),
    recurrence_status: status === "available" ? "qualified" : "unknown",
    recurrence_observed_at:
      status === "available" ? "2026-08-28T16:00:00Z" : null,
    revision_parity: "unknown",
    deployed_revision: null,
    promotion_eligible: false,
    refusal_reasons: ["Deployed API/web revision parity is unknown."],
  };
}

export function buildWashingtonNode(
  status: RegionalFinanceStatus = "available",
): RegionalNavigationNode {
  const unavailable = status === "unavailable";
  const subject: RegionalSubjectIdentity = {
    kind: "state",
    code: "WA",
    name: "Washington",
  };
  const authorityContext: RegionalAuthorityContext = {
    ...refusedContext(
      subject,
      "/state/WA",
      "Legacy compatibility fields do not carry an accepted typed filing-authority receipt.",
    ),
    acquisition_scope: "state/WA",
    evidence_date: "2026-08-23",
    excluded_scopes: [
      "Legacy compatibility fields do not carry an accepted typed filing-authority receipt.",
    ],
  };
  const health = [refusedHealth("WA", status)];
  return {
    kind: "state",
    name: "Washington",
    state_code: "WA",
    state_name: "Washington",
    slug: null,
    canonical_path: "/state/WA",
    geometry_reference: null,
    finance: {
      status,
      authority_context: authorityContext,
      authority_health: health,
      reason:
        status === "available"
          ? "Exact authority-scoped campaign-finance activity is available."
          : "Typed geography is known, but exact authority money is unavailable.",
    },
    finance_detail: {
      subject,
      authority_context: authorityContext,
      authority_health: health,
      as_of: "2026-08-28T16:00:00Z",
      period_start: "2025-01-01",
      period_end: "2026-08-28",
      money: MONEY_KEYS.map((key) => ({
        key,
        authority_code: "WA",
        source_identity: `state/WA:${SOURCE_NAMES[key]}`,
        label: MONEY_LABELS[key],
        status,
        amount: unavailable ? null : MONEY_VALUES[key],
        transaction_count: unavailable ? 0 : 1,
        data_through: unavailable ? null : "2026-08-23",
        source_name: SOURCE_NAMES[key],
        reason: unavailable
          ? "No exact runtime source is available; no zero is inferred."
          : "Exact authority-scoped rows in the current reporting window.",
      })),
      candidates: unavailable
        ? []
        : [
            {
              person_id: "53000000-0000-4000-8000-000000000001",
              person_name: "Alex Washington",
              candidacy_id: "53000000-0000-4000-8000-000000000005",
              contest_id: "53000000-0000-4000-8000-000000000004",
              contest_name: "WA Governor General 2026",
              election_date: "2026-11-03",
              office_id: "00000000-0000-4000-8000-000000000204",
              office_name: "Governor",
              office_title: "Governor",
              division_id: "00000000-0000-4000-8000-000000000502",
              division_name: "Washington",
              party: "Independent",
              candidacy_status: "qualified",
              current_officeholding_id:
                "53000000-0000-4000-8000-000000000006",
              native_filer_identifier: {
                authority_code: "WA",
                value: "WA-FILER-1",
              },
              money_connection: "connected",
              activity_amount: "271.50",
              transaction_count: 4,
            },
          ],
      committees: unavailable
        ? []
        : [
            {
              committee_id: "53000000-0000-4000-8000-000000000003",
              organization_id: "53000000-0000-4000-8000-000000000002",
              name: "Washington Future Committee",
              activity_amount: "271.50",
              transaction_count: 4,
              data_through: "2026-08-23",
            },
          ],
      sources: MONEY_KEYS.map((classKey) => ({
        class_key: classKey,
        authority_code: "WA",
        source_identity: `state/WA:${SOURCE_NAMES[classKey]}`,
        name: SOURCE_NAMES[classKey],
        url: "https://www.pdc.wa.gov/political-disclosure-reporting-data/open-data",
        status,
        last_successful_pull: unavailable ? null : "2026-08-28T16:00:00Z",
        last_verified_working: "2026-03-27",
        latest_refresh_completed_at: unavailable
          ? null
          : "2026-08-28T16:00:00Z",
        latest_refresh_status: unavailable ? null : "success",
        latest_refresh_execution_origin: unavailable
          ? ("unknown" as const)
          : ("scheduled" as const),
        recurrence_status: unavailable
          ? ("unknown" as const)
          : ("qualified" as const),
        reason: unavailable
          ? "The exact configured runtime source is absent."
          : "The exact configured source has a recent successful pull.",
      })),
      registry_evidence_date: "2026-08-23",
      lifecycle_registry_updated_at: "2026-08-27",
      included: ["Exact authority-scoped state-office activity."],
      excluded: [
        "Federal, county, municipal, school-district, special-district, and unproved rows.",
      ],
      named_gaps: [
        "Candidate roster completeness is not established by the lifecycle owner.",
        "Deployed API/web revision parity is unknown.",
      ],
    },
    proxy_analysis: null,
  };
}

export function buildUnavailableStateNode(
  stateCode: string,
  stateName: string,
): RegionalNavigationNode {
  const subject: RegionalSubjectIdentity = {
    kind: "state",
    code: stateCode,
    name: stateName,
  };
  const context = refusedContext(
    subject,
    null,
    `No typed filing-authority translation is proved for state/${stateCode}.`,
  );
  return {
    kind: "state",
    name: stateName,
    state_code: stateCode,
    state_name: stateName,
    slug: null,
    canonical_path: `/state/${stateCode}`,
    geometry_reference: null,
    finance: {
      status: "unavailable",
      authority_context: context,
      authority_health: [],
      reason:
        "No authorized public state campaign-finance projection is available.",
    },
    finance_detail: null,
    proxy_analysis: null,
  };
}

const WAKE_SUBJECT: RegionalSubjectIdentity = {
  kind: "county",
  code: "NC_WAKE",
  name: "Wake County",
};
const WAKE_CONTEXT = refusedContext(
  WAKE_SUBJECT,
  null,
  "Coverage registry has no typed row for county/NC_WAKE.",
);

export const WAKE_NODE: RegionalNavigationNode = {
  kind: "county",
  name: "Wake County",
  state_code: "NC",
  state_name: "North Carolina",
  slug: "wake",
  canonical_path: "/state/NC/county/wake",
  geometry_reference: {
    namespace: "civic",
    kind: "electoral_division_name",
    value: "nc_county_wake",
  },
  finance: {
    status: "unavailable",
    authority_context: WAKE_CONTEXT,
    authority_health: [],
    reason:
      "No explicit county-wide campaign-finance coverage lineage is available.",
  },
  finance_detail: null,
  proxy_analysis: {
    label: "Mapped committee-city disbursements",
    scope_label: "Raleigh and Wake Forest committees",
    excludes: ["county-wide finance", "donor residence", "candidate residence"],
    overlap_disposition: "not_combined",
  },
};

const SEATTLE_SUBJECT: RegionalSubjectIdentity = {
  kind: "municipality",
  code: "WA_SEATTLE",
  name: "Seattle",
};
const SEATTLE_CONTEXT: RegionalAuthorityContext = {
  subject: SEATTLE_SUBJECT,
  public_route: "/state/WA/municipality/seattle",
  acquisition_scope: null,
  provenance_scope: null,
  relation: "partitioned_overlapping",
  filing_authorities: [
    {
      kind: "state",
      code: "WA",
      name: "Washington",
      scope: "Receipt-bounded PDC-directed state lanes.",
      provenance_scope: "PDC Title 29B publication receipt.",
      official_url: null,
    },
    {
      kind: "named_other",
      code: "WA_SEATTLE_CITY_CLERK",
      name: "Seattle City Clerk",
      scope: "Ordinary local C-series reports and the local F-1.",
      provenance_scope: "City Clerk statutory receipt.",
      official_url: null,
    },
    {
      kind: "named_other",
      code: "WA_SEEC",
      name: "Seattle Ethics and Elections Commission",
      scope: "Defined SEEC offices, committees, and Democracy Voucher records.",
      provenance_scope: "SEEC intake and publication receipt.",
      official_url: null,
    },
  ],
  included_scopes: ["PDC lanes", "City Clerk lanes", "SEEC lanes"],
  excluded_scopes: ["No state/local combined total."],
  provenance_scopes: [
    "PDC Title 29B publication receipt.",
    "City Clerk statutory receipt.",
    "SEEC intake and publication receipt.",
  ],
  aggregation_disposition: "refuse_combination",
  evidence_date: "2026-08-28",
  translation_status: "refused",
  refusal_reasons: ["No exact acquisition or provenance translation is proved."],
};

export const SEATTLE_NODE: RegionalNavigationNode = {
  kind: "municipality",
  name: "Seattle",
  state_code: "WA",
  state_name: "Washington",
  slug: "seattle",
  canonical_path: "/state/WA/municipality/seattle",
  geometry_reference: null,
  finance: {
    status: "unavailable",
    authority_context: SEATTLE_CONTEXT,
    authority_health: SEATTLE_CONTEXT.filing_authorities.map((authority) =>
      refusedHealth(authority.code),
    ),
    reason:
      "The accepted typed relation is partitioned across PDC, the Seattle City Clerk, and SEEC. No authority scopes or state/local totals are substituted or combined.",
  },
  finance_detail: null,
  proxy_analysis: null,
};

const NYC_SUBJECT: RegionalSubjectIdentity = {
  kind: "municipality",
  code: "NY_NEW_YORK",
  name: "New York City",
};
const NYC_CONTEXT: RegionalAuthorityContext = {
  subject: NYC_SUBJECT,
  public_route: "/state/NY/municipality/new-york-city",
  acquisition_scope: "municipality/NYC",
  provenance_scope: null,
  relation: "partitioned_overlapping",
  filing_authorities: [
    {
      kind: "state",
      code: "NY",
      name: "New York",
      scope: "NYSBOE parent and conditional-overlap lanes.",
      provenance_scope: "NYSBOE Article 14 receipt.",
      official_url: null,
    },
    {
      kind: "municipality",
      code: "NY_NEW_YORK",
      name: "New York City",
      scope: "Receipt-bounded post-2020 CFB five-office substitution.",
      provenance_scope: "NYC CFB publication-family receipt.",
      official_url: null,
    },
  ],
  included_scopes: ["NYSBOE conditional lanes", "NYC CFB five-office lanes"],
  excluded_scopes: ["Education and special-district elections"],
  provenance_scopes: [
    "NYSBOE Article 14 receipt.",
    "NYC CFB publication-family receipt.",
  ],
  aggregation_disposition: "refuse_combination",
  evidence_date: "2026-08-22",
  translation_status: "refused",
  refusal_reasons: ["No exact provenance translation is proved."],
};

export const NYC_NODE: RegionalNavigationNode = {
  kind: "municipality",
  name: "New York City",
  state_code: "NY",
  state_name: "New York",
  slug: "new-york-city",
  canonical_path: "/state/NY/municipality/new-york-city",
  geometry_reference: null,
  finance: {
    status: "unavailable",
    authority_context: NYC_CONTEXT,
    authority_health: NYC_CONTEXT.filing_authorities.map((authority) =>
      refusedHealth(authority.code),
    ),
    reason:
      "The accepted typed CFB/NYSBOE relation is a bounded post-2020 partition/overlap. No New York State or combined total is shown.",
  },
  finance_detail: null,
  proxy_analysis: null,
};
