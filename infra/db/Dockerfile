FROM postgres:18-bookworm

# The apt install is delegated to a script so its retry behaviour can be
# executed and asserted by tests/ci/test_db_image_apt_retry_script.py. Inline
# Dockerfile shell cannot be tested, and this layer is exactly where a Debian
# mirror flake took CI down on 2026-08-05 and stranded an outage fix for half a
# day. The script is the single owner of this install; do not add a second
# apt-get here.
COPY infra/db/install_postgres_extensions.sh /tmp/install_postgres_extensions.sh
RUN bash /tmp/install_postgres_extensions.sh && rm -f /tmp/install_postgres_extensions.sh
