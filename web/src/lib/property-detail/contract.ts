/** Route and response contracts for property detail pages. */
import { encodeRoutePathSegment, type SourceInfo } from "$lib/entity-detail/contract";

export type PropertyDatePrecision = "day" | "month" | "quarter" | "year" | "approximate";

export type PropertyAssessmentResponse = {
  id: string;
  tax_year: number;
  land_assessed_value: string | null;
  improvement_assessed_value: string | null;
  total_assessed_value: string | null;
  assessed_at: string | null;
  heated_area: number | null;
  exemption_description: string | null;
  sources: SourceInfo[];
};

/** Ownership history rows exposed by the property detail API. */
export type PropertyOwnershipResponse = {
  id: string;
  owner_name: string;
  owner_mail_line1: string | null;
  owner_mail_line2: string | null;
  owner_mail_line3: string | null;
  owner_mail_city: string | null;
  owner_mail_state: string | null;
  owner_mail_zip5: string | null;
  ownership_recorded_at: string | null;
  valid_period: string;
  date_precision: PropertyDatePrecision;
  owner_person_id: string | null;
  owner_organization_id: string | null;
  owner_address_id: string | null;
  sources: SourceInfo[];
};

/** Property detail payload returned by the parcel detail API route. */
export type ParcelDetailResponse = {
  id: string;
  reid: string;
  pin: string;
  site_address: string;
  property_description: string | null;
  city: string | null;
  zoning_class: string | null;
  land_class: string | null;
  acreage: string | null;
  neighborhood: string | null;
  fire_district: string | null;
  is_pending: boolean;
  deed_date: string | null;
  deed_book: string | null;
  deed_page: string | null;
  jurisdiction_id: string | null;
  sources: SourceInfo[];
  assessments: PropertyAssessmentResponse[];
  ownership: PropertyOwnershipResponse[];
};

export function buildParcelDetailPath(parcelId: string): string {
  return `/v1/parcels/${encodeRoutePathSegment(parcelId)}`;
}

export function buildParcelRoutePath(parcelId: string): string {
  return `/property/${encodeRoutePathSegment(parcelId)}`;
}
