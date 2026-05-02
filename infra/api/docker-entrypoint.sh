#!/bin/sh
# API container entrypoint.
#
# Runs the startup canary (api.canary_check) before exec-ing the CMD.
# The canary refuses to start the API if the DB is empty / wrong-volume
# bootstrapped — see api/health_content.py for the Apr 30 incident
# context. Override only via CIVIBUS_STARTUP_CANARY=skip (e.g. fresh DB
# bootstrap); never silently disable.
set -e

# Use the venv's python directly (the Dockerfile prepends /app/.venv/bin
# to PATH). DO NOT use `uv run` here — it re-syncs the venv on every
# start, which fails as user `civibus` because the venv was created by
# root during build. See the Dockerfile CMD comment for the full
# explanation; this entrypoint must use the same approach.
python -m api.canary_check

exec "$@"
