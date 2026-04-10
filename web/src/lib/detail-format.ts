/**
 * Shared display-value formatting for detail presentation layers.
 *
 * Used by entity-detail, civic-detail, and property-detail modules
 * to render nullable API fields as human-readable strings.
 */

const NULL_DISPLAY = "—";

/** Format a nullable scalar value for display. Returns em-dash for null/undefined. */
export function formatDisplayValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return NULL_DISPLAY;
  }

  return String(value);
}

/** Format a nullable boolean for display as Yes/No/em-dash. */
export function formatBoolean(value: boolean | null | undefined): string {
  if (value === null || value === undefined) {
    return NULL_DISPLAY;
  }

  return value ? "Yes" : "No";
}
