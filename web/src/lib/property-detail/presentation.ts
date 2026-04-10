/** View-model builders for property detail pages. */
import { formatCountLabel } from "$lib/count-label";
import { formatBoolean, formatDisplayValue } from "$lib/detail-format";
import {
  buildTrustSection,
  type TrustSectionViewModel
} from "$lib/detail-trust/presentation";
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import type {
  ParcelDetailResponse,
  PropertyAssessmentResponse,
  PropertyOwnershipResponse,
  PropertyDatePrecision
} from "$lib/property-detail/contract";

export type PropertyFactRow = {
  label: string;
  value: string;
};

export type PropertyDetailSectionKey = "summary" | "trust" | "metrics" | "records" | "caveats";

export type PropertyOwnershipRow = {
  id: string;
  ownerName: string;
  ownershipRecordedAt: string;
  validPeriod: string;
  datePrecision: PropertyDatePrecision;
  ownerPersonHref: string | null;
  ownerOrganizationHref: string | null;
  mailingAddress: string;
};

export type PropertyAssessmentRow = {
  id: string;
  taxYear: number;
  landAssessedValue: string;
  improvementAssessedValue: string;
  totalAssessedValue: string;
  assessedAt: string;
  heatedArea: string;
  exemptionDescription: string;
};

export type PropertyDetailPresentation = {
  title: string;
  sectionOrder: PropertyDetailSectionKey[];
  factRows: PropertyFactRow[];
  keyMetricRows: PropertyFactRow[];
  ownershipRows: PropertyOwnershipRow[];
  assessmentRows: PropertyAssessmentRow[];
  trustSection: TrustSectionViewModel;
  ownershipEmptyMessage: string | null;
  assessmentEmptyMessage: string | null;
  geometryPlaceholderMessage: string;
};

export type DetailRouteMetadata = {
  title: string;
  description: string;
};

export const PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE =
  "Map data unavailable: this parcel response does not include coordinates or boundary geometry.";

const PROPERTY_SECTION_ORDER: PropertyDetailSectionKey[] = [
  "summary",
  "trust",
  "metrics",
  "records",
  "caveats"
];

const OWNERSHIP_EMPTY_MESSAGE =
  "No ownership history is available yet. Check back after the next county refresh.";
const ASSESSMENT_EMPTY_MESSAGE =
  "No assessment history is available yet. Check back after the next county refresh.";

export function buildPropertyDetailMetadata(
  propertyTitle: string,
  ownershipCount: number,
  assessmentCount: number
): DetailRouteMetadata {
  const ownershipLabel = formatCountLabel(ownershipCount, "ownership record");
  const assessmentLabel = formatCountLabel(assessmentCount, "assessment");

  return {
    title: `${propertyTitle} | Property | Civibus`,
    description: `Property profile with ${ownershipLabel} and ${assessmentLabel}.`
  };
}

export function buildPropertyDetailMetadataFromDetail(detail: ParcelDetailResponse): DetailRouteMetadata {
  return buildPropertyDetailMetadata(detail.site_address, detail.ownership.length, detail.assessments.length);
}

function buildOwnerHref(entityType: "person" | "org", entityId: string | null): string | null {
  if (!entityId) {
    return null;
  }

  return buildEntityRouteHref(entityType, entityId);
}

function compactAddressParts(parts: Array<string | null>): string {
  const nonEmptyParts = parts.filter((part): part is string => Boolean(part && part.trim().length > 0));

  if (nonEmptyParts.length === 0) {
    return "—";
  }

  return nonEmptyParts.join(", ");
}

/** Formats parcel attributes into labeled rows for the summary section. */
export function buildParcelFactRows(detail: ParcelDetailResponse): PropertyFactRow[] {
  return [
    { label: "REID", value: detail.reid },
    { label: "PIN", value: detail.pin },
    { label: "Site address", value: detail.site_address },
    { label: "Property description", value: formatDisplayValue(detail.property_description) },
    { label: "City", value: formatDisplayValue(detail.city) },
    { label: "Zoning class", value: formatDisplayValue(detail.zoning_class) },
    { label: "Land class", value: formatDisplayValue(detail.land_class) },
    { label: "Acreage", value: formatDisplayValue(detail.acreage) },
    { label: "Neighborhood", value: formatDisplayValue(detail.neighborhood) },
    { label: "Fire district", value: formatDisplayValue(detail.fire_district) },
    { label: "Pending", value: formatBoolean(detail.is_pending) },
    { label: "Deed date", value: formatDisplayValue(detail.deed_date) },
    { label: "Deed book", value: formatDisplayValue(detail.deed_book) },
    { label: "Deed page", value: formatDisplayValue(detail.deed_page) }
  ];
}

/** Normalizes ownership records into UI rows with optional linked entities. */
export function buildOwnershipRows(ownership: PropertyOwnershipResponse[]): PropertyOwnershipRow[] {
  return ownership.map((owner) => ({
    id: owner.id,
    ownerName: owner.owner_name,
    ownershipRecordedAt: formatDisplayValue(owner.ownership_recorded_at),
    validPeriod: owner.valid_period,
    datePrecision: owner.date_precision,
    ownerPersonHref: buildOwnerHref("person", owner.owner_person_id),
    ownerOrganizationHref: buildOwnerHref("org", owner.owner_organization_id),
    mailingAddress: compactAddressParts([
      owner.owner_mail_line1,
      owner.owner_mail_line2,
      owner.owner_mail_line3,
      owner.owner_mail_city,
      owner.owner_mail_state,
      owner.owner_mail_zip5
    ])
  }));
}

export function buildAssessmentRows(assessments: PropertyAssessmentResponse[]): PropertyAssessmentRow[] {
  return assessments.map((assessment) => ({
    id: assessment.id,
    taxYear: assessment.tax_year,
    landAssessedValue: formatDisplayValue(assessment.land_assessed_value),
    improvementAssessedValue: formatDisplayValue(assessment.improvement_assessed_value),
    totalAssessedValue: formatDisplayValue(assessment.total_assessed_value),
    assessedAt: formatDisplayValue(assessment.assessed_at),
    heatedArea: formatDisplayValue(assessment.heated_area),
    exemptionDescription: formatDisplayValue(assessment.exemption_description)
  }));
}

function buildPropertyKeyMetricRows(
  ownershipRows: PropertyOwnershipRow[],
  assessmentRows: PropertyAssessmentRow[]
): PropertyFactRow[] {
  return [
    { label: "Ownership records", value: String(ownershipRows.length) },
    { label: "Assessments", value: String(assessmentRows.length) }
  ];
}

/** Assembles the full property detail presentation model from a parcel payload. */
export function buildPropertyDetailPresentation(detail: ParcelDetailResponse): PropertyDetailPresentation {
  const ownershipRows = buildOwnershipRows(detail.ownership);
  const assessmentRows = buildAssessmentRows(detail.assessments);
  const trustSection = buildTrustSection(detail.sources);

  return {
    title: detail.site_address,
    sectionOrder: PROPERTY_SECTION_ORDER,
    factRows: buildParcelFactRows(detail),
    keyMetricRows: buildPropertyKeyMetricRows(ownershipRows, assessmentRows),
    ownershipRows,
    assessmentRows,
    trustSection,
    ownershipEmptyMessage: ownershipRows.length === 0 ? OWNERSHIP_EMPTY_MESSAGE : null,
    assessmentEmptyMessage: assessmentRows.length === 0 ? ASSESSMENT_EMPTY_MESSAGE : null,
    geometryPlaceholderMessage: PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE
  };
}
