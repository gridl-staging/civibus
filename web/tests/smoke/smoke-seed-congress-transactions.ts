/**
 * Congress smoke transaction-row fragment owner.
 *
 * Builds the Schedule E independent-expenditure and Schedule A receipt VALUES rows for
 * the congress person seed. Kept separate from the seed SQL owner so the row-shaping
 * math (even money splits, per-scenario donor/employer composition) has one home.
 */
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS, SMOKE_FINANCE_LIVE_TOP_SPENDER_ROWS, SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS, SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS, SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME, SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME, SMOKE_PERSON_TOP_SPENDER_TOTAL } from "./fixtures.ts";
// @ts-expect-error Smoke seed helpers run under Node ESM and import the TS module directly.
import { moneyLiteral, sqlLiteral, sqlUuid } from "./smoke_seed_helpers.ts";
// Type-only import: erased at emit, so the .ts extension needs no @ts-expect-error.
import type { CongressPersonSmokeFixture } from "./smoke-seed-congress-fixture.ts";

type ReceiptTransactionSeedRow = {
  id: string;
  identifierSuffix: string;
  transactionDate: string;
  amount: string;
  contributorName: string;
  contributorEmployer: string | null;
  contributorZip: string;
};

type IeTransactionSeedRow = {
  id: string;
  filingId: string;
  committeeId: string;
  identifierSuffix: string;
  transactionDate: string;
  amount: string;
  supportOppose: "S" | "O";
  memoText: string;
};

function smokeGeneratedUuid(fixture: CongressPersonSmokeFixture, sequence: number): string {
  return `${fixture.namespace}-0000-4000-8000-${String(sequence).padStart(12, "0")}`;
}

function moneyCents(value: string): number {
  const normalized = moneyLiteral(value);
  const [dollars, cents = ""] = normalized.split(".");
  return Number(dollars) * 100 + Number(cents.padEnd(2, "0"));
}

function splitMoney(value: string, count: number): string {
  const cents = moneyCents(value);
  if (cents % count !== 0) {
    throw new Error(`Smoke money value ${value} cannot split evenly across ${count} rows.`);
  }
  return (cents / count / 100).toFixed(2);
}

export function buildCongressPersonIeTransactionRows(
  fixture: CongressPersonSmokeFixture,
  transactionIdentifier: (suffix: string) => string
): string {
  const alphaSupportRows = buildRepeatedIeRows({
    fixture,
    startSequence: 430,
    count: 8,
    total: SMOKE_PERSON_TOP_SPENDER_TOTAL,
    committeeId: fixture.SMOKE_CONGRESS_IE_COMMITTEE_ID,
    filingId: fixture.SMOKE_CONGRESS_FILING_ID,
    identifierPrefix: "ie-alpha-support",
    date: "2026-03-20",
    supportOppose: "S",
    memoText: "Digital ads"
  });
  const alphaOpposeRows = buildRepeatedIeRows({
    fixture,
    startSequence: 440,
    count: 5,
    total: SMOKE_FINANCE_LIVE_TOP_SPENDER_ROWS[1].total,
    committeeId: fixture.SMOKE_CONGRESS_IE_COMMITTEE_ID,
    filingId: fixture.SMOKE_CONGRESS_FILING_ID,
    identifierPrefix: "ie-alpha-oppose",
    date: "2026-03-21",
    supportOppose: "O",
    memoText: "Mailers"
  });
  const betaSupportRows = buildRepeatedIeRows({
    fixture,
    startSequence: 450,
    count: 4,
    total: SMOKE_FINANCE_LIVE_TOP_SPENDER_ROWS[2].total,
    committeeId: fixture.SMOKE_CONGRESS_IE_COMMITTEE_B_ID,
    filingId: fixture.SMOKE_CONGRESS_IE_COMMITTEE_B_FILING_ID,
    identifierPrefix: "ie-beta-support",
    date: "2026-03-22",
    supportOppose: "S",
    memoText: "Field program"
  });
  return [...alphaSupportRows, ...alphaOpposeRows, ...betaSupportRows]
    .map((row) => formatIeTransactionRow(fixture, row, transactionIdentifier))
    .join(",\n  ");
}

function buildRepeatedIeRows(input: {
  fixture: CongressPersonSmokeFixture;
  startSequence: number;
  count: number;
  total: string;
  committeeId: string;
  filingId: string;
  identifierPrefix: string;
  date: string;
  supportOppose: "S" | "O";
  memoText: string;
}): IeTransactionSeedRow[] {
  const amount = splitMoney(input.total, input.count);
  return Array.from({ length: input.count }, (_, index) => ({
    id: smokeGeneratedUuid(input.fixture, input.startSequence + index),
    filingId: input.filingId,
    committeeId: input.committeeId,
    identifierSuffix: `${input.identifierPrefix}-${index + 1}`,
    transactionDate: input.date,
    amount,
    supportOppose: input.supportOppose,
    memoText: input.memoText
  }));
}

function formatIeTransactionRow(
  fixture: CongressPersonSmokeFixture,
  row: IeTransactionSeedRow,
  transactionIdentifier: (suffix: string) => string
): string {
  return `(${sqlUuid(row.id, "SMOKE_CONGRESS_IE_TRANSACTION_ID")}, ${sqlUuid(row.filingId, "SMOKE_CONGRESS_IE_FILING_ID")}, ${sqlUuid(row.committeeId, "SMOKE_CONGRESS_IE_COMMITTEE_ID")}, '24E', ${sqlUuid(fixture.SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}, ${sqlLiteral(transactionIdentifier(row.identifierSuffix))}, ${sqlLiteral(row.transactionDate)}, ${moneyLiteral(row.amount)}, ${sqlUuid(fixture.SMOKE_CONGRESS_CANDIDATE_ID, "SMOKE_CONGRESS_CANDIDATE_ID")}, ${sqlLiteral(row.memoText)}, FALSE, 'N', TRUE, ${sqlLiteral(row.supportOppose)}, ${sqlLiteral(row.transactionDate)}, ${moneyLiteral(row.amount)})`;
}

export function buildCongressPersonReceiptTransactionRows(
  fixture: CongressPersonSmokeFixture,
  transactionIdentifier: (suffix: string) => string
): string {
  return receiptRowsForScenario(fixture)
    .map((row) => formatReceiptTransactionRow(fixture, row, transactionIdentifier))
    .join(",\n  ");
}

function receiptRowsForScenario(fixture: CongressPersonSmokeFixture): ReceiptTransactionSeedRow[] {
  if (fixture.scenarioSlug === "person-finance") {
    return [
      {
        id: smokeGeneratedUuid(fixture, 460),
        identifierSuffix: "receipt-finance-donor-1",
        transactionDate: "2026-01-15",
        amount: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[0].total,
        contributorName: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[0].name,
        contributorEmployer: SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
        contributorZip: fixture.zctaInDistrict
      },
      {
        id: smokeGeneratedUuid(fixture, 461),
        identifierSuffix: "receipt-finance-donor-2",
        transactionDate: "2026-02-15",
        amount: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[1].total,
        contributorName: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[1].name,
        contributorEmployer: SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
        contributorZip: fixture.zctaOutOfDistrict
      },
      {
        id: smokeGeneratedUuid(fixture, 462),
        identifierSuffix: "receipt-finance-donor-3",
        transactionDate: "2026-03-10",
        amount: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[2].total,
        contributorName: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[2].name,
        contributorEmployer: SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
        contributorZip: fixture.zctaOutOfDistrict
      },
      {
        id: smokeGeneratedUuid(fixture, 463),
        identifierSuffix: "receipt-finance-donor-4",
        transactionDate: "2026-03-20",
        amount: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[3].total,
        contributorName: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[3].name,
        contributorEmployer: SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME,
        contributorZip: fixture.zctaInDistrict
      },
      {
        id: smokeGeneratedUuid(fixture, 464),
        identifierSuffix: "receipt-finance-donor-5",
        transactionDate: "2026-04-05",
        amount: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[4].total,
        contributorName: SMOKE_FINANCE_LIVE_TOP_DONOR_ROWS[4].name,
        contributorEmployer: null,
        contributorZip: fixture.zctaInDistrict
      }
    ];
  }

  return [
    {
      id: fixture.SMOKE_CONGRESS_RECEIPT_JANUARY_ID,
      identifierSuffix: "receipt-january",
      transactionDate: "2026-01-15",
      amount: SMOKE_PERSON_SMALL_ITEMIZED_DOLLARS,
      contributorName: "Smoke Donor One",
      contributorEmployer: SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME,
      contributorZip: fixture.zctaInDistrict
    },
    {
      id: fixture.SMOKE_CONGRESS_RECEIPT_FEBRUARY_ID,
      identifierSuffix: "receipt-february",
      transactionDate: "2026-02-15",
      amount: SMOKE_PERSON_LARGE_ITEMIZED_DOLLARS,
      contributorName: "Smoke Donor Two",
      contributorEmployer: SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
      contributorZip: fixture.zctaOutOfDistrict
    }
  ];
}

function formatReceiptTransactionRow(
  fixture: CongressPersonSmokeFixture,
  row: ReceiptTransactionSeedRow,
  transactionIdentifier: (suffix: string) => string
): string {
  const employerSql =
    row.contributorEmployer === null ? "NULL" : sqlLiteral(row.contributorEmployer);
  return `(${sqlUuid(row.id, "SMOKE_CONGRESS_RECEIPT_TRANSACTION_ID")}, ${sqlUuid(fixture.SMOKE_CONGRESS_RECEIPT_FILING_ID, "SMOKE_CONGRESS_RECEIPT_FILING_ID")}, ${sqlUuid(fixture.SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID, "SMOKE_CONGRESS_PRINCIPAL_COMMITTEE_ID")}, '15', ${sqlUuid(fixture.SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID, "SMOKE_CONGRESS_FEC_SOURCE_RECORD_ID")}, ${sqlLiteral(transactionIdentifier(row.identifierSuffix))}, ${sqlLiteral(row.transactionDate)}, ${moneyLiteral(row.amount)}, ${sqlLiteral(row.contributorName)}, ${employerSql}, 'NC', ${sqlLiteral(row.contributorZip)}, 'IND', NULL, FALSE, 'N', TRUE)`;
}
