import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import {
  TRUST_SECTION_EMPTY_MESSAGE,
  TRUST_SECTION_LAST_PULLED_UNAVAILABLE
} from "$lib/detail-trust/presentation";
import { PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE } from "./presentation";
import type { ParcelDetailResponse } from "./contract";
import DetailPage from "./DetailPage.svelte";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";
const PARCEL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

const POPULATED_DETAIL: ParcelDetailResponse = {
  id: PARCEL_ID,
  reid: "200000001",
  pin: "0999999999",
  site_address: "123 MAIN ST",
  property_description: "Single family home",
  city: "Durham",
  zoning_class: "R-20",
  land_class: "Residential",
  acreage: "1.2500",
  neighborhood: "Northside",
  fire_district: "Durham",
  is_pending: false,
  deed_date: "2024-01-15",
  deed_book: "1234",
  deed_page: "567",
  jurisdiction_id: null,
  sources: [],
  ownership: [
    {
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      owner_name: "Civibus Homeowner",
      owner_mail_line1: "123 MAIN ST",
      owner_mail_line2: null,
      owner_mail_line3: null,
      owner_mail_city: "Durham",
      owner_mail_state: "NC",
      owner_mail_zip5: "27701",
      ownership_recorded_at: "2024-02-01",
      valid_period: "[2024-02-01,)",
      date_precision: "day",
      owner_person_id: PERSON_ID,
      owner_organization_id: ORG_ID,
      owner_address_id: null,
      sources: []
    }
  ],
  assessments: [
    {
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      tax_year: 2025,
      land_assessed_value: "150000.00",
      improvement_assessed_value: "350000.00",
      total_assessed_value: "500000.00",
      assessed_at: "2025-01-31",
      heated_area: 2500,
      exemption_description: "Homestead",
      sources: []
    }
  ]
};

const EMPTY_DETAIL: ParcelDetailResponse = {
  ...POPULATED_DETAIL,
  site_address: "999 EMPTY RD",
  sources: [],
  ownership: [],
  assessments: []
};

const NO_LINK_OWNER_DETAIL: ParcelDetailResponse = {
  ...POPULATED_DETAIL,
  ownership: [
    {
      ...POPULATED_DETAIL.ownership[0],
      owner_name: "Unlinked Owner",
      owner_person_id: null,
      owner_organization_id: null
    }
  ]
};

describe("property detail page rendering", () => {
  it("renders section headings in the spec order", () => {
    const rendered = render(DetailPage, {
      props: {
        data: POPULATED_DETAIL
      }
    });

    const orderedHeadings = [
      "Parcel facts",
      "Source and freshness",
      "Key metrics",
      "Ownership history",
      "Assessment history",
      "Map and geometry"
    ];
    let previousHeadingIndex = -1;

    for (const heading of orderedHeadings) {
      const headingIndex = rendered.body.indexOf(`<h3>${heading}</h3>`);
      expect(headingIndex).toBeGreaterThan(-1);
      expect(headingIndex).toBeGreaterThan(previousHeadingIndex);
      previousHeadingIndex = headingIndex;
    }
  });

  it("renders ownership and assessment history as semantic tables without debug-style labels", () => {
    const rendered = render(DetailPage, {
      props: {
        data: POPULATED_DETAIL
      }
    });

    expect(rendered.body).toContain('class="detail__table-scroll"');
    expect((rendered.body.match(/<table>/g) ?? []).length).toBe(2);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Owner<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Recorded at<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Valid period<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Date precision<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Mailing address<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Linked records<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Tax year<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Land assessed value<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Improvement assessed value<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Total assessed value<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Assessed at<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Heated area<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Exemption<\/th>/);
    expect(rendered.body).not.toContain('<ul class="detail__list">');
    expect(rendered.body).not.toContain("owner:");
    expect(rendered.body).not.toContain("recorded at:");
    expect(rendered.body).not.toContain("valid period:");
    expect(rendered.body).not.toContain("date precision:");
    expect(rendered.body).not.toContain("mailing address:");
    expect(rendered.body).not.toContain("tax year:");
    expect(rendered.body).not.toContain("linked person");
    expect(rendered.body).not.toContain("linked organization");
  });

  it("renders owner links with record-specific accessible labels", () => {
    const rendered = render(DetailPage, {
      props: {
        data: POPULATED_DETAIL
      }
    });

    expect(rendered.body).toContain(`href="/person/${PERSON_ID}"`);
    expect(rendered.body).toContain(`href="/org/${ORG_ID}"`);
    expect(rendered.body).toContain('aria-label="View person record for Civibus Homeowner"');
    expect(rendered.body).toContain('aria-label="View organization record for Civibus Homeowner"');
    expect(rendered.body).toContain(">View person record</a>");
    expect(rendered.body).toContain(">View organization record</a>");
  });

  it("renders dash fallback and no outbound owner links when owner ids are absent", () => {
    const rendered = render(DetailPage, {
      props: {
        data: NO_LINK_OWNER_DETAIL
      }
    });

    expect(rendered.body).toContain("Unlinked Owner");
    expect(rendered.body).toMatch(/<td class="detail__table-cell-wrap">\s*(?:<!--[^>]*-->)*\s*—\s*(?:<!--[^>]*-->)*\s*<\/td>/);
    expect(rendered.body).not.toContain('href="/person/');
    expect(rendered.body).not.toContain('href="/org/');
  });

  it("keeps ownership and assessment panels visible with empty-state copy when no records exist", () => {
    const rendered = render(DetailPage, {
      props: {
        data: EMPTY_DETAIL
      }
    });

    expect(rendered.body).toContain("<h3>Ownership history</h3>");
    expect(rendered.body).toContain("<h3>Assessment history</h3>");
    expect(rendered.body).toContain(
      "No ownership history is available yet. Check back after the next county refresh."
    );
    expect(rendered.body).toContain(
      "No assessment history is available yet. Check back after the next county refresh."
    );
    expect(rendered.body).not.toContain("<table>");
  });

  it("renders trust section fallback copy for empty provenance", () => {
    const rendered = render(DetailPage, {
      props: {
        data: EMPTY_DETAIL
      }
    });

    expect(rendered.body).toContain("<h3>Source and freshness</h3>");
    expect(rendered.body).toContain(TRUST_SECTION_LAST_PULLED_UNAVAILABLE);
    expect(rendered.body).toContain("Data freshness could not be determined.");
    expect(rendered.body).toContain(TRUST_SECTION_EMPTY_MESSAGE);
  });

  it("applies detail__table-cell-wrap to owner name, valid period, and mailing address cells", () => {
    const rendered = render(DetailPage, {
      props: {
        data: POPULATED_DETAIL
      }
    });

    const ownerCellMatch = rendered.body.match(
      /<td class="detail__table-cell-wrap">Civibus Homeowner<\/td>/
    );
    expect(ownerCellMatch).not.toBeNull();

    const validPeriodMatch = rendered.body.match(
      /<td class="detail__table-cell-wrap">\[2024-02-01,\)<\/td>/
    );
    expect(validPeriodMatch).not.toBeNull();

    const mailingCellMatch = rendered.body.match(
      /<td class="detail__table-cell-wrap">123 MAIN ST, Durham, NC, 27701<\/td>/
    );
    expect(mailingCellMatch).not.toBeNull();
  });

  it("keeps the map and geometry caveat panel visible with placeholder copy", () => {
    const rendered = render(DetailPage, {
      props: {
        data: POPULATED_DETAIL
      }
    });

    expect(rendered.body).toContain("<h3>Map and geometry</h3>");
    expect(rendered.body).toContain(PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE);
    expect(rendered.body).toContain('aria-label="Parcel geometry placeholder"');
  });

  it("renders the map and geometry caveat panel with caveat-banner and note semantics", () => {
    const rendered = render(DetailPage, {
      props: {
        data: POPULATED_DETAIL
      }
    });

    expect(rendered.body).toMatch(
      /<section(?=[^>]*class="detail__panel caveat-banner")(?=[^>]*role="note")(?=[^>]*aria-label="Parcel geometry placeholder")[^>]*>/
    );
  });
});
