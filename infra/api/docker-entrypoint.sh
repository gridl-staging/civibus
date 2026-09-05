#!/bin/sh
# API container entrypoint.
#
# Runs the startup canary (api.canary_check) before exec-ing the CMD.
# The canary refuses to start the API if the DB is empty / wrong-volume
# bootstrapped — see api/health_content.py for the Apr 30 incident
# context. Override only via CIVIBUS_STARTUP_CANARY=skip (e.g. fresh DB
# bootstrap); never silently disable.
set -e

# Fly release_command must run migrations before the startup canary can require
# newly added columns. Normal API startup still runs the canary below.
if [ "${1:-}" = "python" ] && [ "${2:-}" = "-m" ] && [ "${3:-}" = "core.schema.apply_migrations" ]; then
  exec "$@"
fi

# Promotion evidence is image-local: the deploy owner may stage one validated
# immutable bundle, while ordinary pre-promotion images retain no active input.
# Never accept a Fly-level or shared-host override because it could make old
# code read a new bundle after rollback.
promotion_receipt="/app/private/civibus/authority-promotion/authority-promotion-receipt.json"
configured_promotion_receipt="${CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON:-}"
if [ -e "$promotion_receipt" ] || [ -L "$promotion_receipt" ]; then
  if [ -n "$configured_promotion_receipt" ] && [ "$configured_promotion_receipt" != "$promotion_receipt" ]; then
    echo "civibus-api-entrypoint: conflicting authority promotion receipt path" >&2
    exit 1
  fi
  test -f "$promotion_receipt" && test ! -L "$promotion_receipt" || {
    echo "civibus-api-entrypoint: installed authority promotion receipt must be a regular non-symlink file" >&2
    exit 1
  }
  export CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON="$promotion_receipt"
else
  if [ -n "$configured_promotion_receipt" ]; then
    echo "civibus-api-entrypoint: configured authority promotion receipt is absent from this image" >&2
    exit 1
  fi
  unset CIVIBUS_AUTHORITY_PROMOTION_RECEIPT_JSON
fi

# Use the venv's python directly (the Dockerfile prepends /app/.venv/bin
# to PATH). DO NOT use `uv run` here — it re-syncs the venv on every
# start, which fails as user `civibus` because the venv was created by
# root during build. See the Dockerfile CMD comment for the full
# explanation; this entrypoint must use the same approach.
python -m api.canary_check

exec "$@"
