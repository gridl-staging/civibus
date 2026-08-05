#!/usr/bin/env bash
#
# Install the Postgres extension packages the civibus database image needs.
#
# This exists as a script rather than inline Dockerfile shell for one reason:
# the retry behaviour below has to be executable against a stub `apt-get` so a
# test can prove it retries a transient failure AND still fails a permanent
# one. See tests/ci/test_db_image_apt_retry_script.py.
#
# Anchored incident: 2026-08-05. Staging Integration run 30972647556 attempt 1
# failed 23 seconds in, at this exact apt layer:
#
#   E: Failed to fetch .../libkmlengine1_1.3.0-10_amd64.deb
#      File has unexpected size (20136 != 74428). Mirror sync in progress?
#
# A Debian mirror served a truncated .deb. No civibus code participated. A
# re-run of the identical commit passed. That one transient failure was written
# into four artifacts as a hard deploy blocker and stranded the remedy for a
# 48-hour production outage for about twelve hours. The cost of the flake was
# not the four minutes of CI; it was the twelve hours of misdiagnosis.
#
# Why re-run `apt-get update` on every attempt rather than just `install`:
# "Mirror sync in progress" means the cached index names a file the mirror
# cannot yet serve. Retrying `install` against that same stale index just
# reproduces the failure. Refreshing the index is the load-bearing half.
set -euo pipefail

# Bounded on purpose. An unbounded loop against a genuinely broken mirror would
# hang the build instead of failing it, and a build that hangs is harder to
# diagnose than one that stops.
readonly MAX_ATTEMPTS=4

# Overridable so the contract test does not have to sit through real backoff.
# Production builds get the real sleep.
readonly RETRY_SLEEP_SECONDS="${APT_RETRY_SLEEP_SECONDS:-15}"

# The extension set this image exists to provide. PostGIS backs the geometry
# work; AGE backs the legacy graph stack.
readonly PACKAGES=(
  postgresql-18-postgis-3
  postgresql-18-postgis-3-scripts
  postgresql-18-age
)

# apt's own retry handles a dropped connection. It does not reliably handle a
# size/hash mismatch from a half-synced mirror, which is why the outer loop
# below exists as well. Both layers are cheap; neither alone covers the case.
export DEBIAN_FRONTEND=noninteractive
readonly APT_OPTIONS=(-o "Acquire::Retries=3")

# Overridable so the contract test can execute this script without deleting
# the apt cache of whatever host it runs on. Production builds get the real
# path, which is inside the image being built.
readonly APT_LISTS_DIR="${APT_LISTS_DIR:-/var/lib/apt/lists}"

attempt=1
while (( attempt <= MAX_ATTEMPTS )); do
  if apt-get update "${APT_OPTIONS[@]}" \
    && apt-get install -y --no-install-recommends "${APT_OPTIONS[@]}" "${PACKAGES[@]}"; then
    # Drop the package index so it does not ship inside the image layer.
    rm -rf "${APT_LISTS_DIR:?}"/*
    exit 0
  fi

  echo "install_postgres_extensions: attempt ${attempt}/${MAX_ATTEMPTS} failed" >&2

  if (( attempt == MAX_ATTEMPTS )); then
    break
  fi

  # Clear the partial index before backing off. Retrying on top of a corrupt
  # cache is how a transient failure turns into a sticky one.
  rm -rf "${APT_LISTS_DIR:?}"/*
  sleep "${RETRY_SLEEP_SECONDS}"
  attempt=$(( attempt + 1 ))
done

echo "install_postgres_extensions: giving up after ${MAX_ATTEMPTS} attempts" >&2
exit 1
