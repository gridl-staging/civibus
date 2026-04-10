import { fetchEntityDetailBundle } from "$lib/server/api/entity-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(
    () =>
      fetchEntityDetailBundle(locals.api, {
        entityType: "org",
        id: params.id
      }),
    "Backend organization detail request failed."
  );
