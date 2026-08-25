# Dedicated Fly backup-machine image: PostgreSQL 18 client tooling + rclone +
# the checked-in backup scripts, and nothing else.
#
# This is deliberately NOT the DB server image (infra/db/Dockerfile). That image
# builds PostGIS + AGE server extensions it does not need here, and — more
# importantly — making the server image also own the backup job would couple two
# unrelated lifecycles onto one boundary. A client-only backup image keeps the
# dump/upload runtime isolated with its own B2 credentials, exactly the boundary
# Stage 3 exists to create.
#
# The base is postgres:18-bookworm purely for its pg_dump/psql major-18 client,
# which backup_fly_db_to_b2.sh requires to match the civibus-db server major
# version (an unrestorable version-mismatched dump is worse than none). No
# postgres server ever runs in this image.
#
# Build context is the repo root (like infra/fly/db.fly.toml), so the COPY
# paths below are repo-root-relative.
FROM postgres:18-bookworm

# rclone streams the dump to B2; ca-certificates lets rclone verify B2's TLS.
# --no-install-recommends keeps the client image thin. rclone is in Debian main.
RUN apt-get update \
  && apt-get install -y --no-install-recommends rclone ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# The backup scripts resolve their siblings by BASH_SOURCE directory, so the
# wrapper, the shared object contract, and the env helper must land together.
# b2_backup_lib.sh stays the single owner of the B2 object contract; this image
# copies it, it does not restate it.
COPY infra/scripts/backup_fly_db_to_b2.sh /opt/civibus/infra/scripts/backup_fly_db_to_b2.sh
COPY infra/scripts/b2_backup_lib.sh /opt/civibus/infra/scripts/b2_backup_lib.sh
COPY infra/scripts/env_lib.sh /opt/civibus/infra/scripts/env_lib.sh

# The official base already provides this account. The streaming job needs no
# root capability, so keep its database and B2 credentials out of a
# root-running process boundary.
USER postgres:postgres

# No default CMD that would launch postgres: the Fly machine command is the
# backup wrapper. Keep the container inert unless explicitly told to back up.
ENTRYPOINT []
CMD ["bash", "/opt/civibus/infra/scripts/backup_fly_db_to_b2.sh"]
