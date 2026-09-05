FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY sources.yaml ./sources.yaml
COPY api ./api
COPY core ./core
COPY domains ./domains
COPY infra/fly/regional_refresh_machine_profile.json ./infra/fly/regional_refresh_machine_profile.json
# The deploy owner materializes only a strictly validated immutable bundle in
# this tracked build-context directory. Keeping it inside the image makes an
# API rollback restore code and its matching evidence atomically.
COPY infra/api/authority_promotion_bundle /app/private/civibus/authority-promotion
# The coverage registry is a runtime data dependency of the states/summary
# endpoint (see .dockerignore negation) — keep the repo-relative path the
# code default expects.
COPY docs/reference/research/coverage-registry.json ./docs/reference/research/coverage-registry.json
# Entrypoint runs api.canary_check before exec-ing the CMD; this is the
# mechanical guard against the Apr 30 wrong-volume bootstrap incident.
COPY infra/api/docker-entrypoint.sh /usr/local/bin/civibus-api-entrypoint

RUN uv sync --locked --extra api \
    && groupadd --system --gid 10001 civibus \
    && useradd --system --uid 10001 --gid civibus --create-home --home-dir /home/civibus --shell /usr/sbin/nologin civibus \
    && chmod 0555 /usr/local/bin/civibus-api-entrypoint \
    && test -f /app/infra/fly/regional_refresh_machine_profile.json \
    && test ! -L /app/infra/fly/regional_refresh_machine_profile.json \
    && chmod 0444 /app/infra/fly/regional_refresh_machine_profile.json \
    && test -d /app/private/civibus/authority-promotion \
    && test ! -L /app/private/civibus/authority-promotion \
    && test -z "$(find /app/private/civibus/authority-promotion -type l -print -quit)" \
    && chmod 0555 /app/private/civibus/authority-promotion \
    && find /app/private/civibus/authority-promotion -mindepth 1 -type d -exec chmod 0555 {} + \
    && find /app/private/civibus/authority-promotion -type f -exec chmod 0444 {} + \
    && chmod -R a+rX /app/api /app/core /app/domains /app/docs

ENV PATH="/app/.venv/bin:$PATH"

# Build-provenance stamp: the dev-repo commit SHA and build timestamp are passed
# at deploy time (--build-arg) so /health/version can expose them for deploy-drift
# detection. Placed AFTER the cached `uv sync` layer so a per-deploy SHA change
# never busts that expensive layer. Default "unknown" keeps un-stamped builds
# honest rather than shipping an empty value.
ARG CIVIBUS_GIT_SHA=unknown
ARG CIVIBUS_BUILT_AT=unknown
ENV CIVIBUS_GIT_SHA=$CIVIBUS_GIT_SHA
ENV CIVIBUS_BUILT_AT=$CIVIBUS_BUILT_AT

USER civibus

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/civibus-api-entrypoint"]
# Use the venv's binaries directly (PATH already prepends /app/.venv/bin
# above). DO NOT use `uv run` at runtime — `uv run` re-syncs the venv on
# every start, which fails as user `civibus` because the venv was created
# by root during the build step. The user can't remove the editable
# `_editable_impl_civibus.pth` file root wrote into site-packages, so the
# sync errors out and the container exits 2. That was the 2026-05-01
# :latest image bug. The same constraint applies in docker-entrypoint.sh.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
