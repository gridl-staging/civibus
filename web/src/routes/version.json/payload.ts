export type VersionEnvironment = Record<string, string | undefined>;

export interface VersionPayload {
  git_sha: string;
  built_at: string;
}

const GIT_SHA_ENV_VAR = 'CIVIBUS_GIT_SHA';
const BUILT_AT_ENV_VAR = 'CIVIBUS_BUILT_AT';
const UNKNOWN = 'unknown';

export function buildVersionPayload(environment: VersionEnvironment = process.env): VersionPayload {
  return {
    git_sha: environment[GIT_SHA_ENV_VAR] ?? UNKNOWN,
    built_at: environment[BUILT_AT_ENV_VAR] ?? UNKNOWN
  };
}
