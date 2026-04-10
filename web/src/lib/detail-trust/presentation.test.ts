import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildTrustSection,
  TRUST_SECTION_ADVISORY_MESSAGE,
  TRUST_SECTION_EMPTY_MESSAGE,
  TRUST_SECTION_LAST_PULLED_UNAVAILABLE
} from "./presentation";

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
          recordUrl: null
        }
      ],
      lastPulledSummary: "Last pulled: 1 day ago (2026-03-20)",
      freshnessSeverity: "fresh",
      emptyMessage: null,
      advisoryMessage: TRUST_SECTION_ADVISORY_MESSAGE
    });
  });

  it("returns tightened empty copy when source payload is empty", () => {
    expect(buildTrustSection([])).toEqual({
      rows: [],
      lastPulledSummary: TRUST_SECTION_LAST_PULLED_UNAVAILABLE,
      freshnessSeverity: "unknown",
      emptyMessage: TRUST_SECTION_EMPTY_MESSAGE,
      advisoryMessage: TRUST_SECTION_ADVISORY_MESSAGE
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
        data_source_url: "https://www.fec.gov",
        source_record_key: "ftp",
        record_url: "ftp://example.org/file",
        pull_date: "2026-03-19T00:00:00Z"
      },
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
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
});
