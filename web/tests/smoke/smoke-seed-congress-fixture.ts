/**
 * Congress smoke scenario fixture owner.
 *
 * Maps each live smoke scenario (directory / charts / finance) to its deterministic,
 * per-scenario id set so parallel Playwright workers cannot race on shared rows. The
 * congress person seed/cleanup SQL owners (./smoke-seed-congress-person.ts) and the
 * transaction-row fragment owner (./smoke-seed-congress-transactions.ts) consume the
 * `CongressPersonSmokeFixture` this module builds.
 */
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { SMOKE_CHART_LIVE_PERSON_ID, SMOKE_CONGRESS_CANDIDATE_ID, SMOKE_CONGRESS_FILING_ID, SMOKE_CONGRESS_IE_COMMITTEE_ID, SMOKE_CONGRESS_PERSON_CANONICAL_NAME, SMOKE_CONGRESS_PERSON_FIRST_NAME, SMOKE_CONGRESS_PERSON_ID, SMOKE_CONGRESS_PERSON_LAST_NAME, SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, SMOKE_FINANCE_LIVE_PERSON_ID, SMOKE_PERSON_CANONICAL_NAME } from "./fixtures.ts";

export type CongressPersonSmokeScenario = "directory" | "charts" | "finance";
export type CongressSmokeScenario = CongressPersonSmokeScenario | "compare";

type CongressPersonSmokeFixtureInput = {
  namespace: string;
  slug: string;
  personId: string;
  // Per-scenario person identity. The directory scenario's person is listed on
  // /congress alongside the browser-smoke seed's officeholders, so it needs a
  // name no other seeded row shares; the charts and finance scenarios are only
  // ever read on their own /person/[id] page and keep the shared specimen name.
  personCanonicalName: string;
  personFirstName: string;
  personLastName: string;
  candidateId: string;
  principalCommitteeId: string;
  ieCommitteeId: string;
  ieCommitteeBId: string;
  filingId: string;
  ieCommitteeBFilingId: string;
  fecCandidateId: string;
  zctaInDistrict: string;
  zctaOutOfDistrict: string;
};

function buildCongressPersonSmokeFixture(input: CongressPersonSmokeFixtureInput) {
  const fixtureId = (suffix: string) => `${input.namespace}-0000-4000-8000-${suffix}`;
  const fecNamespace = input.namespace.slice(0, 3);
  const isDirectoryFixture = input.slug === "congress";
  return {
    SMOKE_CONGRESS_CIVICS_DATA_SOURCE_ID: fixtureId("000000000401"),
    SMOKE_CONGRESS_FEC_DATA_SOURCE_ID: fixtureId("000000000402"),
    SMOKE_CONGRESS_SOURCE_RECORD_ID: fixtureId("000000000403"),
    SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID: fixtureId("000000000404"),
    SMOKE_CONGRESS_DIVISION_ID: fixtureId("000000000405"),
    SMOKE_CONGRESS_OFFICEHOLDING_ID: fixtureId("000000000406"),
    SMOKE_CONGRESS_PORTRAIT_ID: fixtureId("000000000407"),
    SMOKE_CONGRESS_LINK_ID: fixtureId("000000000408"),
    SMOKE_CONGRESS_IE_SUPPORT_TRANSACTION_ID: fixtureId("000000000409"),
    SMOKE_CONGRESS_IE_OPPOSE_TRANSACTION_ID: fixtureId("000000000410"),
    SMOKE_CONGRESS_RECEIPT_FILING_ID: fixtureId("000000000411"),
    SMOKE_CONGRESS_RECEIPT_JANUARY_ID: fixtureId("000000000412"),
    SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID: fixtureId("000000000413"),
    SMOKE_CONGRESS_COMMITTEE_SUMMARY_2022_ID: fixtureId("000000000414"),
    SMOKE_CONGRESS_COMMITTEE_SUMMARY_2024_ID: fixtureId("000000000415"),
    SMOKE_CONGRESS_COMMITTEE_SUMMARY_2026_ID: fixtureId("000000000416"),
    SMOKE_CONGRESS_PERSON_ID: input.personId,
    personCanonicalName: input.personCanonicalName,
    personFirstName: input.personFirstName,
    personLastName: input.personLastName,
    SMOKE_CONGRESS_CANDIDATE_ID: input.candidateId,
    SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID: input.principalCommitteeId,
    SMOKE_CONGRESS_IE_COMMITTEE_ID: input.ieCommitteeId,
    SMOKE_CONGRESS_IE_COMMITTEE_B_ID: input.ieCommitteeBId,
    SMOKE_CONGRESS_FILING_ID: input.filingId,
    SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_ID: input.ieCommitteeBFilingId,
    SMOKE_CONGRESS_FEC_CANDIDATE_ID: input.fecCandidateId,
    SMOKE_CONGRESS_PRINCIPAL_FEC_COMMITTEE_ID: `C${fecNamespace}00001`,
    SMOKE_CONGRESS_IE_FEC_COMMITTEE_ID: `C${fecNamespace}00002`,
    SMOKE_CONGRESS_IE_FEC_COMMITTEE_B_ID: `C${fecNamespace}00003`,
    SMOKE_CONGRESS_FILING_FEC_ID: `smoke-${input.slug}-filing-2026-q1`,
    SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_FEC_ID: `smoke-${input.slug}-filing-2026-q1-beta`,
    SMOKE_CONGRESS_RECEIPT_FILING_FEC_ID: `smoke-${input.slug}-receipts-2026-q1`,
    scenarioSlug: input.slug,
    namespace: input.namespace,
    divisionName: isDirectoryFixture ? "nc_cd_01" : `nc_cd_01_${input.slug}_smoke`,
    sourceNamePrefix: isDirectoryFixture ? "Congress" : "Person detail",
    portraitHash: isDirectoryFixture ? "d".repeat(64) : input.slug.padEnd(64, "d").slice(0, 64),
    zctaInDistrict: input.zctaInDistrict,
    zctaOutOfDistrict: input.zctaOutOfDistrict
  } as const;
}

export type CongressPersonSmokeFixture = ReturnType<typeof buildCongressPersonSmokeFixture>;

// Built lazily inside a function so the imported fixtures.ts id constants are read at
// call time, not at module-evaluation time. fixtures.ts re-exports this module's seed
// helpers, so the two modules form an import cycle; reading a fixtures.ts constant at
// this module's top level races that cycle and throws
// "Cannot access 'SMOKE_CONGRESS_PERSON_ID' before initialization" (temporal dead zone).
// The seed/cleanup builders only need a fixture at call time, by which point every
// module is fully initialized.
export function congressPersonSmokeFixture(scenario: CongressPersonSmokeScenario): CongressPersonSmokeFixture {
  const inputs: Record<CongressPersonSmokeScenario, CongressPersonSmokeFixtureInput> = {
    directory: {
      namespace: "90000000",
      slug: "congress",
      personId: SMOKE_CONGRESS_PERSON_ID,
      personCanonicalName: SMOKE_CONGRESS_PERSON_CANONICAL_NAME,
      personFirstName: SMOKE_CONGRESS_PERSON_FIRST_NAME,
      personLastName: SMOKE_CONGRESS_PERSON_LAST_NAME,
      candidateId: SMOKE_CONGRESS_CANDIDATE_ID,
      principalCommitteeId: SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID,
      ieCommitteeId: SMOKE_CONGRESS_IE_COMMITTEE_ID,
      ieCommitteeBId: "90000000-0000-4000-8000-000000000417",
      filingId: SMOKE_CONGRESS_FILING_ID,
      ieCommitteeBFilingId: "90000000-0000-4000-8000-000000000418",
      fecCandidateId: "H0NC01999",
      zctaInDistrict: "27513",
      zctaOutOfDistrict: "27601"
    },
    charts: {
      namespace: "94000000",
      slug: "person-charts",
      personId: SMOKE_CHART_LIVE_PERSON_ID,
      personCanonicalName: SMOKE_PERSON_CANONICAL_NAME,
      personFirstName: "Jane",
      personLastName: "Doe",
      candidateId: "94000000-0000-4000-8000-000000000412",
      principalCommitteeId: "94000000-0000-4000-8000-000000000413",
      ieCommitteeId: "94000000-0000-4000-8000-000000000414",
      ieCommitteeBId: "94000000-0000-4000-8000-000000000417",
      filingId: "94000000-0000-4000-8000-000000000415",
      ieCommitteeBFilingId: "94000000-0000-4000-8000-000000000418",
      fecCandidateId: "H0NC01994",
      zctaInDistrict: "94001",
      zctaOutOfDistrict: "94002"
    },
    finance: {
      namespace: "95000000",
      slug: "person-finance",
      personId: SMOKE_FINANCE_LIVE_PERSON_ID,
      personCanonicalName: SMOKE_PERSON_CANONICAL_NAME,
      personFirstName: "Jane",
      personLastName: "Doe",
      candidateId: "95000000-0000-4000-8000-000000000412",
      principalCommitteeId: "95000000-0000-4000-8000-000000000413",
      ieCommitteeId: "95000000-0000-4000-8000-000000000414",
      ieCommitteeBId: "95000000-0000-4000-8000-000000000417",
      filingId: "95000000-0000-4000-8000-000000000415",
      ieCommitteeBFilingId: "95000000-0000-4000-8000-000000000418",
      fecCandidateId: "H0NC01995",
      zctaInDistrict: "95001",
      zctaOutOfDistrict: "95002"
    }
  };
  return buildCongressPersonSmokeFixture(inputs[scenario]);
}
