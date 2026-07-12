FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY sources.yaml ./sources.yaml
COPY api ./api
COPY core ./core
COPY domains ./domains
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
    && chmod +x /usr/local/bin/civibus-api-entrypoint \
    && chmod -R a+rX /app/api /app/core /app/domains /app/docs

ENV PATH="/app/.venv/bin:$PATH"

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
