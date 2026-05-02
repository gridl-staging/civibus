import { describe, expect, it } from "vitest";
import {
  buildTrustSection,
  TRUST_SECTION_EMPTY_MESSAGE,
  TRUST_SECTION_LAST_PULLED_UNAVAILABLE
} from "$lib/detail-trust/presentation";
import {
  buildAssessmentRows,
  buildOwnershipRows,
  buildParcelFactRows,
  buildPropertyDetailMetadata,
  buildPropertyDetailMetadataFromDetail,
  buildPropertyDetailPresentation,
  PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE
} from "./presentation";

const PARCEL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";

describe("property detail presentation", () => {
  it("builds parcel fact rows from backend parcel detail fields", () => {
    const rows = buildParcelFactRows({
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
      ownership: [],
      assessments: []
    });

    expect(rows).toEqual([
      { label: "REID", value: "200000001" },
      { label: "PIN", value: "0999999999" },
      { label: "Site address", value: "123 MAIN ST" },
      { label: "Property description", value: "Single family home" },
      { label: "City", value: "Durham" },
      { label: "Zoning class", value: "R-20" },
      { label: "Land class", value: "Residential" },
      { label: "Acreage", value: "1.2500" },
      { label: "Neighborhood", value: "Northside" },
      { label: "Fire district", value: "Durham" },
      { label: "Pending", value: "No" },
      { label: "Deed date", value: "2024-01-15" },
      { label: "Deed book", value: "1234" },
      { label: "Deed page", value: "567" }
    ]);
  });

  it("renders null optional parcel fields as fallback dash values", () => {
    const rows = buildParcelFactRows({
      id: PARCEL_ID,
      reid: "200000001",
      pin: "0999999999",
      site_address: "123 MAIN ST",
      property_description: null,
      city: null,
      zoning_class: null,
      land_class: null,
      acreage: null,
      neighborhood: null,
      fire_district: null,
      is_pending: false,
      deed_date: null,
      deed_book: null,
      deed_page: null,
      jurisdiction_id: null,
      sources: [],
      ownership: [],
      assessments: []
    });

    const valueByLabel = new Map(rows.map((row) => [row.label, row.value]));
    expect(valueByLabel.get("Property description")).toBe("—");
    expect(valueByLabel.get("City")).toBe("—");
    expect(valueByLabel.get("Zoning class")).toBe("—");
    expect(valueByLabel.get("Land class")).toBe("—");
    expect(valueByLabel.get("Acreage")).toBe("—");
    expect(valueByLabel.get("Neighborhood")).toBe("—");
    expect(valueByLabel.get("Fire district")).toBe("—");
    expect(valueByLabel.get("Deed date")).toBe("—");
    expect(valueByLabel.get("Deed book")).toBe("—");
    expect(valueByLabel.get("Deed page")).toBe("—");
  });

  it('renders "Yes" when the parcel pending flag is true', () => {
    const rows = buildParcelFactRows({
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
      is_pending: true,
      deed_date: "2024-01-15",
      deed_book: "1234",
      deed_page: "567",
      jurisdiction_id: null,
      sources: [],
      ownership: [],
      assessments: []
    });

    expect(rows.find((row) => row.label === "Pending")?.value).toBe("Yes");
  });

  it("preserves backend ownership order and derives owner links only from person/org ids", () => {
    const rows = buildOwnershipRows([
      {
        id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        owner_name: "Org Owner",
        owner_mail_line1: null,
        owner_mail_line2: null,
        owner_mail_line3: null,
        owner_mail_city: null,
        owner_mail_state: null,
        owner_mail_zip5: null,
        ownership_recorded_at: "2024-02-01",
        valid_period: "[2024-02-01,2025-02-01)",
        date_precision: "month",
        owner_person_id: null,
        owner_organization_id: ORG_ID,
        owner_address_id: null,
        sources: []
      },
      {
        id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        owner_name: "Person Owner",
        owner_mail_line1: null,
        owner_mail_line2: null,
        owner_mail_line3: null,
        owner_mail_city: null,
        owner_mail_state: null,
        owner_mail_zip5: null,
        ownership_recorded_at: "2025-02-01",
        valid_period: "[2025-02-01,)",
        date_precision: "day",
        owner_person_id: PERSON_ID,
        owner_organization_id: null,
        owner_address_id: null,
        sources: []
      }
    ]);

    expect(rows.map((row) => row.id)).toEqual([
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    ]);
    expect(rows[0].ownerPersonHref).toBeNull();
    expect(rows[0].ownerOrganizationHref).toBe(`/org/${ORG_ID}`);
    expect(rows[1].ownerPersonHref).toBe(`/person/${PERSON_ID}`);
    expect(rows[1].ownerOrganizationHref).toBeNull();
  });

  it("renders fallback dash for ownership mailing address when all parts are null", () => {
    const [row] = buildOwnershipRows([
      {
        id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        owner_name: "Org Owner",
        owner_mail_line1: null,
        owner_mail_line2: null,
        owner_mail_line3: null,
        owner_mail_city: null,
        owner_mail_state: null,
        owner_mail_zip5: null,
        ownership_recorded_at: "2024-02-01",
        valid_period: "[2024-02-01,2025-02-01)",
        date_precision: "month",
        owner_person_id: null,
        owner_organization_id: ORG_ID,
        owner_address_id: null,
        sources: []
      }
    ]);

    expect(row.mailingAddress).toBe("—");
  });

  it("preserves backend assessment order with no frontend sorting", () => {
    const rows = buildAssessmentRows([
      {
        id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        tax_year: 2025,
        land_assessed_value: "150000.00",
        improvement_assessed_value: "350000.00",
        total_assessed_value: "500000.00",
        assessed_at: "2025-01-31",
        heated_area: 2500,
        exemption_description: "Homestead",
        sources: []
      },
      {
        id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        tax_year: 2024,
        land_assessed_value: "130000.00",
        improvement_assessed_value: "320000.00",
        total_assessed_value: "450000.00",
        assessed_at: "2024-01-31",
        heated_area: 2400,
        exemption_description: null,
        sources: []
      }
    ]);

    expect(rows.map((row) => row.id)).toEqual([
      "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    ]);
    expect(rows[0].taxYear).toBe(2025);
    expect(rows[1].taxYear).toBe(2024);
  });

  it("renders fallback dash for null assessment value fields", () => {
    const [row] = buildAssessmentRows([
      {
        id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        tax_year: 2025,
        land_assessed_value: null,
        improvement_assessed_value: null,
        total_assessed_value: null,
        assessed_at: null,
        heated_area: null,
        exemption_description: null,
        sources: []
      }
    ]);

    expect(row.landAssessedValue).toBe("—");
    expect(row.improvementAssessedValue).toBe("—");
    expect(row.totalAssessedValue).toBe("—");
    expect(row.assessedAt).toBe("—");
    expect(row.heatedArea).toBe("—");
    expect(row.exemptionDescription).toBe("—");
  });

  it("builds parcel trust-section data from the shared trust contract", () => {
    const sources = [
      {
        domain: "property",
        jurisdiction: "us/nc/durham",
        data_source_name: "Durham County",
        data_source_url: "https://example.org/durham",
        source_record_key: "parcel-detail",
        record_url: "https://example.org/parcel-detail",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ];
    const viewModel = buildPropertyDetailPresentation({
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
      sources,
      ownership: [],
      assessments: []
    });

    expect(viewModel.trustSection).toEqual(buildTrustSection(sources));
  });

  it("builds parcel trust-section data from the shared trust contract when provenance is empty", () => {
    const sources: Array<{
      domain: string;
      jurisdiction: string | null;
      data_source_name: string;
      data_source_url: string;
      source_record_key: string | null;
      record_url: string | null;
      pull_date: string;
    }> = [];
    const viewModel = buildPropertyDetailPresentation({
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
      sources,
      ownership: [],
      assessments: []
    });

    expect(viewModel.trustSection).toEqual(buildTrustSection(sources));
    expect(viewModel.trustSection.lastPulledSummary).toBe(TRUST_SECTION_LAST_PULLED_UNAVAILABLE);
    expect(viewModel.trustSection.freshnessSeverity).toBe("unknown");
    expect(viewModel.trustSection.emptyMessage).toBe(TRUST_SECTION_EMPTY_MESSAGE);
  });

  it("emits summary-first hierarchy with trust before records, count metrics, and next-step empty copy", () => {
    const viewModel = buildPropertyDetailPresentation({
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
      ownership: [],
      assessments: []
    });

    expect(viewModel.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "records",
      "caveats"
    ]);
    expect(viewModel.keyMetricRows).toEqual([
      { label: "Ownership records", value: "0" },
      { label: "Assessments", value: "0" }
    ]);
    expect(viewModel.ownershipEmptyMessage).toBe(
      "No ownership history is available yet. Check back after the next county refresh."
    );
    expect(viewModel.assessmentEmptyMessage).toBe(
      "No assessment history is available yet. Check back after the next county refresh."
    );
    expect(viewModel.geometryPlaceholderMessage).toBe(PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE);
  });

  it("derives key metrics directly from ownership and assessment payload counts", () => {
    const viewModel = buildPropertyDetailPresentation({
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
          owner_name: "Org Owner",
          owner_mail_line1: null,
          owner_mail_line2: null,
          owner_mail_line3: null,
          owner_mail_city: null,
          owner_mail_state: null,
          owner_mail_zip5: null,
          ownership_recorded_at: "2024-02-01",
          valid_period: "[2024-02-01,2025-02-01)",
          date_precision: "month",
          owner_person_id: null,
          owner_organization_id: ORG_ID,
          owner_address_id: null,
          sources: []
        }
      ],
      assessments: [
        {
          id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
          tax_year: 2025,
          land_assessed_value: "150000.00",
          improvement_assessed_value: "350000.00",
          total_assessed_value: "500000.00",
          assessed_at: "2025-01-31",
          heated_area: 2500,
          exemption_description: "Homestead",
          sources: []
        },
        {
          id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
          tax_year: 2024,
          land_assessed_value: "130000.00",
          improvement_assessed_value: "320000.00",
          total_assessed_value: "450000.00",
          assessed_at: "2024-01-31",
          heated_area: 2400,
          exemption_description: null,
          sources: []
        }
      ]
    });

    expect(viewModel.keyMetricRows).toEqual([
      { label: "Ownership records", value: "1" },
      { label: "Assessments", value: "2" }
    ]);
    expect(viewModel.ownershipEmptyMessage).toBeNull();
    expect(viewModel.assessmentEmptyMessage).toBeNull();
  });

  it("does not duplicate route metadata inside the property detail view model", () => {
    const viewModel = buildPropertyDetailPresentation({
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
      ownership: [],
      assessments: []
    });

    expect("metadata" in viewModel).toBe(false);
  });

  it("returns a stable geometry placeholder message when no map data is available", () => {
    expect(PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE).toBe(
      "Map data unavailable: this parcel response does not include coordinates or boundary geometry."
    );
  });

  it("builds metadata from parcel title and record counts", () => {
    expect(buildPropertyDetailMetadata("123 MAIN ST", 1, 2)).toEqual({
      title: "123 MAIN ST | Property | Civibus",
      description: "Property profile with 1 ownership record and 2 assessments."
    });
  });

  it("builds property route metadata directly from the loaded parcel detail", () => {
    expect(
      buildPropertyDetailMetadataFromDetail({
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
            owner_name: "Org Owner",
            owner_mail_line1: null,
            owner_mail_line2: null,
            owner_mail_line3: null,
            owner_mail_city: null,
            owner_mail_state: null,
            owner_mail_zip5: null,
            ownership_recorded_at: "2024-02-01",
            valid_period: "[2024-02-01,2025-02-01)",
            date_precision: "month",
            owner_person_id: null,
            owner_organization_id: ORG_ID,
            owner_address_id: null,
            sources: []
          }
        ],
        assessments: [
          {
            id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
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
      })
    ).toEqual({
      title: "123 MAIN ST | Property | Civibus",
      description: "Property profile with 1 ownership record and 1 assessment."
    });
  });

  it("builds property route metadata with pluralized zero-count wording", () => {
    expect(
      buildPropertyDetailMetadataFromDetail({
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
        ownership: [],
        assessments: []
      })
    ).toEqual({
      title: "123 MAIN ST | Property | Civibus",
      description: "Property profile with 0 ownership records and 0 assessments."
    });
  });
});
