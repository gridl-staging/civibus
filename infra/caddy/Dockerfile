# Caddy edge for Fly.io. Fly machines cannot bind-mount config files the way
# compose does, so the (shared, env-parameterized) infra/Caddyfile is baked in.
# infra/Caddyfile stays the SSOT — compose keeps mounting it directly.
FROM caddy:2

COPY infra/Caddyfile /etc/caddy/Caddyfile
