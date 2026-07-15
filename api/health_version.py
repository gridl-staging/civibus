"""Build-provenance version probe.

Serves the dev-repo commit SHA and build timestamp stamped into the image at
deploy time via ``ARG``/``ENV CIVIBUS_GIT_SHA``/``CIVIBUS_BUILT_AT`` (see
``infra/api/Dockerfile``). Downstream deploy-drift detection compares this SHA
against ``civibus_dev/main``.

There is deliberately NO ``git rev-parse`` fallback: the runtime image has no
``.git`` directory, so the values come exclusively from build-time env vars.
When a var is absent the payload reports the literal ``"unknown"`` rather than
synthesizing a runtime value — a ``built_at`` that silently means "now" would be
a lie no test could catch.
"""

from __future__ import annotations

import os
from typing import Mapping

GIT_SHA_ENV_VAR = "CIVIBUS_GIT_SHA"
BUILT_AT_ENV_VAR = "CIVIBUS_BUILT_AT"
_UNKNOWN = "unknown"


def build_version_payload(env: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Return the build-provenance payload read from ``env``.

    Echoes the stamped values byte-for-byte; falls back to ``"unknown"`` for any
    key that is absent.
    """
    return {
        "git_sha": env.get(GIT_SHA_ENV_VAR, _UNKNOWN),
        "built_at": env.get(BUILT_AT_ENV_VAR, _UNKNOWN),
    }
