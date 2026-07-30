import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";
import {
  buildIdentityDisclosureLabel,
  buildIdentityEvidencePresentation,
  describeCombinedIdentity,
  formatCombinedRecordCount,
  getPublishedConfidenceLabel
} from "./donor-identity-evidence";
import type { IdentityEvidenceRecord } from "./donor-identity-evidence";

const identityEvidenceSource = readFileSync(resolve(__dirname, "IdentityEvidence.svelte"), "utf8");

function identityEvidenceRecord(recordUrl: string | null): IdentityEvidenceRecord {
  return {
    contributor_name: "JANE SMITH",
    contributor_employer: null,
    contributor_occupation: null,
    contributor_city: null,
    contributor_state: null,
    normalized_zip5: null,
    sources: [
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC filing",
        data_source_url: "https://example.org/fec",
        source_record_key: "filing-1",
        record_url: recordUrl,
        pull_date: "2026-07-09T12:00:00Z"
      }
    ]
  };
}

describe("donor identity evidence presentation", () => {
  it("uses the published confidence labels without methodology descriptions", () => {
    expect(getPublishedConfidenceLabel("match")).toBe("match");
    expect(getPublishedConfidenceLabel("probable_match")).toBe("probable_match");
    expect(getPublishedConfidenceLabel("possible_match")).toBe("possible_match");
  });

  it("formats accessible combined-profile labels and public caveat copy", () => {
    expect(formatCombinedRecordCount(2)).toBe("2 records combined");
    expect(buildIdentityDisclosureLabel("JANE SMITH", 2)).toBe("JANE SMITH, 2 records combined");
    expect(describeCombinedIdentity("match", 2)).toBe(
      "These records appear to describe the same donor."
    );
    expect(describeCombinedIdentity("probable_match", 2)).toBe(
      "These records may be two people."
    );
  });

  it("requires a safe direct filing URL before presenting any identity record", () => {
    expect(
      buildIdentityEvidencePresentation([
        identityEvidenceRecord("https://example.org/fec/filing-1")
      ])
    ).toEqual({
      status: "available",
      records: [
        {
          record: identityEvidenceRecord("https://example.org/fec/filing-1"),
          filingHref: "https://example.org/fec/filing-1"
        }
      ]
    });

    expect(buildIdentityEvidencePresentation([identityEvidenceRecord(null)])).toEqual({
      status: "unavailable"
    });
    expect(
      buildIdentityEvidencePresentation([identityEvidenceRecord("javascript:alert('unsafe')")])
    ).toEqual({ status: "unavailable" });
  });
});

describe("IdentityEvidence Svelte correction contract", () => {
  it("keeps correction controls inert and addressable by source contract", () => {
    expect(identityEvidenceSource).toContain('data-testid="donor-identity-correction-combined"');
    expect(identityEvidenceSource).toContain('data-testid="donor-identity-correction-candidate"');
    expect(identityEvidenceSource).toMatch(
      /<button\s+type="button"\s+disabled\s+data-testid="donor-identity-correction-combined"\s+aria-describedby=\{combinedCorrectionReasonId\}/
    );
    expect(identityEvidenceSource).toMatch(
      /<button\s+type="button"\s+disabled\s+data-testid="donor-identity-correction-candidate"\s+aria-describedby=\{candidateCorrectionReasonId\(index\)\}/
    );
    expect(identityEvidenceSource).not.toContain("<form");
    expect(identityEvidenceSource).not.toContain("method=");
    expect(identityEvidenceSource).not.toContain("action=");
    expect(identityEvidenceSource).not.toContain("on:submit");
    expect(identityEvidenceSource).not.toContain("onsubmit");
  });

  it("renders donor-specific source filing links instead of ambiguous generic labels", () => {
    expect(identityEvidenceSource).toContain("function buildFilingLabel(record: IdentityEvidenceRecord): string");
    expect(identityEvidenceSource).toContain("Source filing for");
    expect(identityEvidenceSource).toContain("aria-label={buildFilingLabel(evidence.record)}");
    expect(identityEvidenceSource).not.toContain(">Filing<");
  });
});
