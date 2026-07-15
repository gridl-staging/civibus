/**
 * Build-provenance probe: serves the dev-repo commit SHA and build timestamp
 * stamped into the image at deploy time (see web/Dockerfile ARG/ENV
 * CIVIBUS_GIT_SHA/CIVIBUS_BUILT_AT). Downstream deploy-drift detection compares
 * this SHA against civibus_dev/main.
 *
 * No runtime git lookup: the container has no .git directory, so values come
 * only from build-time env vars. An absent var reports the literal "unknown"
 * rather than synthesizing a runtime value.
 */
import type { RequestHandler } from '@sveltejs/kit';
import { buildVersionPayload } from './payload';

// adapter-node reads process.env at runtime, so the stamped ENV values resolve here.
export const GET: RequestHandler = () =>
  new Response(JSON.stringify(buildVersionPayload()), {
    headers: { 'Content-Type': 'application/json' }
  });
