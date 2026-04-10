import { fetchEntityDetailBundle } from "$lib/server/api/entity-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(
    () =>
      fetchEntityDetailBundle(locals.api, {
        entityType: "person",
        id: params.id
      }),
    "Backend person detail request failed."
  );
