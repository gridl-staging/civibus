import { describe, expect, it } from 'vitest';
import { buildVersionPayload } from './payload';

describe('buildVersionPayload', () => {
  it('echoes CIVIBUS_GIT_SHA and CIVIBUS_BUILT_AT byte-exactly', () => {
    expect(
      buildVersionPayload({
        CIVIBUS_GIT_SHA: 'a19ecebf4d111dbd6dfbe3e46c4fc4cf304be714',
        CIVIBUS_BUILT_AT: '2026-07-14T21:20:44Z'
      })
    ).toEqual({
      git_sha: 'a19ecebf4d111dbd6dfbe3e46c4fc4cf304be714',
      built_at: '2026-07-14T21:20:44Z'
    });
  });

  it('falls back to "unknown" when a key is absent', () => {
    expect(buildVersionPayload({})).toEqual({ git_sha: 'unknown', built_at: 'unknown' });
    expect(buildVersionPayload({ CIVIBUS_GIT_SHA: 'abc' })).toEqual({
      git_sha: 'abc',
      built_at: 'unknown'
    });
  });
});
