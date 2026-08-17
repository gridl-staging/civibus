import { DONOR_RESOLVED_CONFIDENCE_BANDS } from "$lib/donors/contract";
import { sanitizeExternalUrl } from "$lib/url/sanitize-external-url";
import type { SourceInfo } from "./contract";

export type IdentityConfidenceBand = (typeof DONOR_RESOLVED_CONFIDENCE_BANDS)[number];
export type NotCombinedConfidenceBand = "possible_match";

export type IdentityEvidenceRecord = {
  contributor_name: string;
  contributor_employer: string | null;
  contributor_occupation: string | null;
  contributor_city: string | null;
  contributor_state: string | null;
  normalized_zip5: string | null;
  sources: SourceInfo[];
};

export type NotCombinedIdentityEvidenceRecord = IdentityEvidenceRecord & {
  confidence_band: NotCombinedConfidenceBand;
};

export type FilingLinkedIdentityEvidenceRecord<T extends IdentityEvidenceRecord> = {
  record: T;
  filingHref: string;
};

export type IdentityEvidencePresentation<T extends IdentityEvidenceRecord> =
  | {
      status: "available";
      records: FilingLinkedIdentityEvidenceRecord<T>[];
    }
  | {
      status: "unavailable";
    };

export const CORRECTION_UNAVAILABLE_REASON = "Correction submission is not yet available";
export const IDENTITY_EVIDENCE_UNAVAILABLE_MESSAGE =
  "Identity evidence is unavailable because its source filing could not be verified.";

export function getPublishedConfidenceLabel(
  confidenceBand: IdentityConfidenceBand | NotCombinedConfidenceBand
): string {
  return confidenceBand;
}

export function formatCombinedRecordCount(recordCount: number): string {
  return `${recordCount} ${recordCount === 1 ? "record" : "records"} combined`;
}

export function buildIdentityDisclosureLabel(donorName: string, recordCount: number): string {
  return `${donorName}, ${formatCombinedRecordCount(recordCount)}`;
}

export function describeCombinedIdentity(
  confidenceBand: IdentityConfidenceBand,
  recordCount: number
): string {
  if (confidenceBand === "probable_match") {
    return `These records may be ${formatPeopleCount(recordCount)}.`;
  }

  return "These records appear to describe the same donor.";
}

export function buildIdentityEvidencePresentation<T extends IdentityEvidenceRecord>(
  records: readonly T[]
): IdentityEvidencePresentation<T> {
  const filingLinkedRecords: FilingLinkedIdentityEvidenceRecord<T>[] = [];

  for (const record of records) {
    const filingHref = record.sources
      .map((source) => sanitizeExternalUrl(source.record_url))
      .find((recordUrl): recordUrl is string => recordUrl !== null);

    if (!filingHref) {
      return { status: "unavailable" };
    }

    filingLinkedRecords.push({ record, filingHref });
  }

  return { status: "available", records: filingLinkedRecords };
}

function formatPeopleCount(recordCount: number): string {
  if (recordCount === 1) {
    return "one person";
  }
  if (recordCount === 2) {
    return "two people";
  }

  return `${recordCount} people`;
}
