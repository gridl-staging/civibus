import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildTrustSection,
  buildDonorVendorEmptyStateBanner,
  buildLinkedCommitteeEmptyStateBanner,
  PHL_FRESHNESS_NOTE,
  TRUST_SECTION_ADVISORY_MESSAGE,
  TRUST_SECTION_EMPTY_MESSAGE,
  TRUST_SECTION_LAST_PULLED_UNAVAILABLE
} from "./presentation";

const EXPECTED_INDIANA_FRESHNESS_NOTE =
  "Indiana bulk campaign finance data refreshes less often than weekly; this view may be up to 30 days stale.";
const EXPECTED_ALABAMA_FRESHNESS_NOTE =
  "Alabama campaign finance production data is currently a narrow committee-state slice; totals may be incomplete.";
const EXPECTED_GEORGIA_FRESHNESS_NOTE =
  "Georgia campaign finance production data is currently a narrow committee-state slice; totals may be incomplete.";

describe("detail trust presentation helper", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-21T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("derives trust rows and latest pull summary from source payloads", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: null,
        record_url: "https://example.org/safe",
        pull_date: "2026-03-19T00:00:00Z"
      },
      {
        domain: "property",
        jurisdiction: null,
        data_source_name: "Durham County",
        data_source_url: "https://example.org/durham",
        source_record_key: "parcel-1",
        record_url: "javascript:alert(1)",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ]);

    expect(section).toEqual({
      rows: [
        {
          source: "campaign_finance/federal/fec",
          sourceName: "FEC",
          sourceLabel: "FEC (campaign_finance/federal/fec)",
          sourceRecordKey: "—",
          pullDate: "2026-03-19T00:00:00Z",
          recordUrl: "https://example.org/safe"
        },
        {
          source: "property",
          sourceName: "Durham County",
          sourceLabel: "Durham County (property)",
          sourceRecordKey: "parcel-1",
          pullDate: "2026-03-20T00:00:00Z",
          recordUrl: "https://example.org/durham"
        }
      ],
      lastPulledSummary: "Last pulled: 1 day ago (2026-03-20)",
      freshnessSeverity: "fresh",
      emptyMessage: null,
      advisoryMessage: TRUST_SECTION_ADVISORY_MESSAGE,
      freshnessNote: null
    });
  });

  it("returns tightened empty copy when source payload is empty", () => {
    expect(buildTrustSection([])).toEqual({
      rows: [],
      lastPulledSummary: TRUST_SECTION_LAST_PULLED_UNAVAILABLE,
      freshnessSeverity: "unknown",
      emptyMessage: TRUST_SECTION_EMPTY_MESSAGE,
      advisoryMessage: TRUST_SECTION_ADVISORY_MESSAGE,
      freshnessNote: null
    });
  });

  it("picks the freshest pull date chronologically instead of lexically", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "older-when-parsed",
        record_url: "https://example.org/older",
        pull_date: "2026-03-20T01:00:00Z"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "state/NC",
        data_source_name: "North Carolina",
        data_source_url: "https://example.org/nc",
        source_record_key: "newer-when-parsed",
        record_url: "https://example.org/newer",
        pull_date: "2026-03-19T23:30:00-05:00"
      }
    ]);

    expect(section.lastPulledSummary).toBe("Last pulled: 1 day ago (2026-03-20)");
  });

  it("ignores unparseable pull dates when a parseable freshest row exists", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "newest-parseable",
        record_url: "https://example.org/newest",
        pull_date: "2026-03-20T14:00:00Z"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "state/NC",
        data_source_name: "North Carolina",
        data_source_url: "https://example.org/nc",
        source_record_key: "invalid-date",
        record_url: "https://example.org/invalid",
        pull_date: "definitely-not-a-date"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "state/GA",
        data_source_name: "Georgia",
        data_source_url: "https://example.org/ga",
        source_record_key: "older-parseable",
        record_url: "https://example.org/older",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ]);

    expect(section.lastPulledSummary).toBe("Last pulled: 1 day ago (2026-03-20)");
  });

  it("returns unavailable when no pull date is parseable", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "invalid-1",
        record_url: "https://example.org/invalid-1",
        pull_date: "not-a-date"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "state/NC",
        data_source_name: "North Carolina",
        data_source_url: "https://example.org/nc",
        source_record_key: "invalid-2",
        record_url: "https://example.org/invalid-2",
        pull_date: "2026-13-99"
      }
    ]);

    expect(section.lastPulledSummary).toBe(TRUST_SECTION_LAST_PULLED_UNAVAILABLE);
  });

  it("drops unsafe record URLs and keeps only http/https links", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "safe",
        record_url: "https://example.org/safe-record",
        pull_date: "2026-03-19T00:00:00Z"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "ftp://example.org/invalid-fallback-ftp",
        source_record_key: "ftp",
        record_url: "ftp://example.org/file",
        pull_date: "2026-03-19T00:00:00Z"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "not-a-valid-url",
        source_record_key: "invalid",
        record_url: "not-a-valid-url",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ]);

    expect(section.rows.map((row) => row.recordUrl)).toEqual([
      "https://example.org/safe-record",
      null,
      null
    ]);
  });

  it("applies Stage 1 link precedence for record_url and data_source_url", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://example.org/source-preferred-record",
        source_record_key: "preferred-record-url",
        record_url: "https://example.org/safe-record",
        pull_date: "2026-03-19T00:00:00Z"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "state/NC",
        data_source_name: "North Carolina",
        data_source_url: "https://example.org/source-fallback-malformed-record",
        source_record_key: "fallback-malformed-record-url",
        record_url: "javascript:alert(1)",
        pull_date: "2026-03-19T00:00:00Z"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "state/WA",
        data_source_name: "Washington",
        data_source_url: "https://example.org/source-fallback-missing-record",
        source_record_key: "fallback-missing-record-url",
        record_url: null,
        pull_date: "2026-03-19T00:00:00Z"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "state/MI",
        data_source_name: "Michigan",
        data_source_url: "ftp://example.org/source-invalid-protocol",
        source_record_key: "orphan-invalid-source-url",
        record_url: "not-a-valid-url",
        pull_date: "2026-03-19T00:00:00Z"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "state/MN",
        data_source_name: "Minnesota",
        data_source_url: "not-a-valid-url",
        source_record_key: "orphan-missing-record-url",
        record_url: null,
        pull_date: "2026-03-19T00:00:00Z"
      }
    ]);

    expect(section.rows.map((row) => row.recordUrl)).toEqual([
      "https://example.org/safe-record",
      "https://example.org/source-fallback-malformed-record",
      "https://example.org/source-fallback-missing-record",
      null,
      null
    ]);
  });

  it("returns a freshness severity bucket for trust UI copy", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "row-1",
        record_url: "https://example.org/safe-record",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ]);

    const sectionContract = section as unknown as Record<string, unknown>;
    expect(["fresh", "stale", "unknown"]).toContain(sectionContract.freshnessSeverity);
  });

  it("returns a user-facing source label per trust row", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "Federal Election Commission",
        data_source_url: "https://www.fec.gov",
        source_record_key: "row-1",
        record_url: "https://example.org/safe-record",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ]);

    const firstRow = section.rows[0] as unknown as Record<string, unknown>;
    expect(firstRow.sourceLabel).toBe("Federal Election Commission (campaign_finance/federal/fec)");
  });

  it("includes both relative and absolute date language in last-pulled summary", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "row-1",
        record_url: "https://example.org/safe-record",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ]);

    expect(section.lastPulledSummary).toContain("1 day ago");
    expect(section.lastPulledSummary).toContain("2026-03-20");
  });

  it("classifies recent pull dates as fresh", () => {
    // System time: 2026-03-21T12:00:00Z, pull date 1 day ago => fresh
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "recent",
        record_url: null,
        pull_date: "2026-03-20T00:00:00Z"
      }
    ]);

    expect(section.freshnessSeverity).toBe("fresh");
  });

  it("classifies pull dates at the threshold boundary as fresh", () => {
    // System time: 2026-03-21T12:00:00Z, pull date exactly 7 days ago => fresh (threshold is exclusive)
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "boundary",
        record_url: null,
        pull_date: "2026-03-14T12:00:00Z"
      }
    ]);

    expect(section.freshnessSeverity).toBe("fresh");
  });

  it("classifies old pull dates as stale", () => {
    // System time: 2026-03-21T12:00:00Z, pull date 14 days ago => stale
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "old",
        record_url: null,
        pull_date: "2026-03-07T00:00:00Z"
      }
    ]);

    expect(section.freshnessSeverity).toBe("stale");
  });

  it("classifies all-unparseable pull dates as unknown freshness", () => {
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "bad-date",
        record_url: null,
        pull_date: "not-a-date"
      }
    ]);

    expect(section.freshnessSeverity).toBe("unknown");
  });

  it("derives sourceLabel without jurisdiction when jurisdiction is null", () => {
    const section = buildTrustSection([
      {
        domain: "property",
        jurisdiction: null,
        data_source_name: "Durham County",
        data_source_url: "https://example.org/durham",
        source_record_key: "parcel-1",
        record_url: null,
        pull_date: "2026-03-20T00:00:00Z"
      }
    ]);

    expect(section.rows[0].sourceLabel).toBe("Durham County (property)");
  });

  it("does not add the retired Indiana freshness note for Indiana campaign-finance provenance", () => {
    // IN re-verdicted to weekly-or-better 2026-04-26
    // (see docs/research/in_freshness_recheck_2026_04_26.md):
    // 3 valid probes (Apr 16, Apr 17, Apr 26) over 10 days now satisfy
    // the weekly-or-better rule. The freshness banner has been retired.
    const section = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "state/IN",
        data_source_name: "Indiana Campaign Finance",
        data_source_url: "https://campaignfinance.in.gov/PublicSite/Reporting/DataDownload.aspx",
        source_record_key: "in-1",
        record_url: "https://example.org/in-1",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ], { includeJurisdictionFreshnessNote: true });

    expect(section.freshnessNote).toBeNull();
    // Defense-in-depth: pin the exact retired copy stays out so a
    // typo'd map re-entry can't silently resurrect it.
    expect(section.freshnessNote).not.toBe(EXPECTED_INDIANA_FRESHNESS_NOTE);
  });

  it("keeps the Indiana freshness note off shared trust sections unless the caller opts in", () => {
    const defaultSection = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "state/IN",
        data_source_name: "Indiana Campaign Finance",
        data_source_url: "https://campaignfinance.in.gov/PublicSite/Reporting/DataDownload.aspx",
        source_record_key: "in-1",
        record_url: "https://example.org/in-1",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ]);
    const pennsylvaniaSection = buildTrustSection([
      {
        domain: "campaign_finance",
        jurisdiction: "state/PA",
        data_source_name: "Pennsylvania Campaign Finance",
        data_source_url: "https://example.org/pa",
        source_record_key: "pa-1",
        record_url: "https://example.org/pa-1",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ]);
    const propertySection = buildTrustSection([
      {
        domain: "property",
        jurisdiction: "state/IN",
        data_source_name: "Indiana Property Records",
        data_source_url: "https://example.org/property-in",
        source_record_key: "property-in-1",
        record_url: "https://example.org/property-in-1",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ]);

    expect(defaultSection.freshnessNote).toBeNull();
    expect(pennsylvaniaSection.freshnessNote).toBeNull();
    expect(propertySection.freshnessNote).toBeNull();
  });

  it("shows the Philadelphia freshness note only when the trust-section caller opts in", () => {
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "municipality/PHL",
        data_source_name: "Philadelphia Campaign Finance",
        data_source_url: "https://opendataphilly.org/",
        source_record_key: "phl-1",
        record_url: "https://example.org/phl-1",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ];
    const optedInSection = buildTrustSection(sources, { includeJurisdictionFreshnessNote: true });
    const defaultSection = buildTrustSection(sources);

    expect(optedInSection.freshnessNote).toBe(PHL_FRESHNESS_NOTE);
    expect(defaultSection.freshnessNote).toBeNull();
  });

  it("shows the Alabama freshness note only when the trust-section caller opts in", () => {
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "state/AL",
        data_source_name: "Alabama Campaign Finance",
        data_source_url: "https://fcpa.alabamavotes.gov",
        source_record_key: "al-1",
        record_url: "https://example.org/al-1",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ];
    const optedInSection = buildTrustSection(sources, { includeJurisdictionFreshnessNote: true });
    const defaultSection = buildTrustSection(sources);

    expect(optedInSection.freshnessNote).toBe(EXPECTED_ALABAMA_FRESHNESS_NOTE);
    expect(defaultSection.freshnessNote).toBeNull();
  });

  it("shows the Georgia freshness note only when the trust-section caller opts in", () => {
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "state/GA",
        data_source_name: "Georgia Campaign Finance",
        data_source_url: "https://media.ethics.ga.gov/search/Campaign/Campaign_ByContributions.aspx",
        source_record_key: "ga-1",
        record_url: "https://example.org/ga-1",
        pull_date: "2026-03-20T00:00:00Z"
      }
    ];
    const optedInSection = buildTrustSection(sources, { includeJurisdictionFreshnessNote: true });
    const defaultSection = buildTrustSection(sources);

    expect(optedInSection.freshnessNote).toBe(EXPECTED_GEORGIA_FRESHNESS_NOTE);
    expect(defaultSection.freshnessNote).toBeNull();
  });

  it("returns no-linked-committees copy when candidate has no linked committees", () => {
    expect(buildLinkedCommitteeEmptyStateBanner(0)).toBe(
      "No linked committee summaries are available yet."
    );
  });

  it("returns no linked-committee banner when at least one linked committee exists", () => {
    expect(buildLinkedCommitteeEmptyStateBanner(1)).toBeNull();
  });

  it("returns zero-transactions copy when donor/vendor rows are empty", () => {
    expect(buildDonorVendorEmptyStateBanner(0)).toBe(
      "No donor/vendor transactions are available yet."
    );
  });

  it("returns no donor/vendor banner when at least one transaction exists", () => {
    expect(buildDonorVendorEmptyStateBanner(1)).toBeNull();
  });
});
