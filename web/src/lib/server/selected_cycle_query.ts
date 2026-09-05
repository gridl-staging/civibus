import { error } from "@sveltejs/kit";

const INVALID_CYCLE_ERROR = {
  message: "Invalid cycle query parameter.",
  detail: "The cycle query parameter must be a single four-digit election cycle."
};

/**
 * Parse the route-level syntax for an optional selected-cycle query.
 *
 * This deliberately validates only that one four-digit value was requested.
 * Backend `resolve_selected_cycle` remains the owner of supported cycles.
 */
export function parseSelectedCycleQuery(searchParams: URLSearchParams): number | undefined {
  const cycleValues = searchParams.getAll("cycle");
  if (cycleValues.length === 0) {
    return undefined;
  }

  if (cycleValues.length !== 1) {
    throw error(400, INVALID_CYCLE_ERROR);
  }

  const rawCycle = cycleValues[0].trim();
  if (!/^\d{4}$/.test(rawCycle)) {
    throw error(400, INVALID_CYCLE_ERROR);
  }

  return Number(rawCycle);
}
