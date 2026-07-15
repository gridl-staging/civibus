FROM node:22-bookworm-slim AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build \
    && npm prune --production

FROM node:22-bookworm-slim

WORKDIR /app

COPY --from=builder /app/build ./build
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules

# Build-provenance stamp: MUST live in this FINAL stage — an ARG in the builder
# stage does not cross the FROM boundary, so the runtime image would ship an
# empty SHA. Placed AFTER the cached node_modules COPY so a per-deploy SHA change
# never busts the `npm ci` layer. adapter-node reads these from process.env at
# runtime and /version.json serves them for deploy-drift detection.
ARG CIVIBUS_GIT_SHA=unknown
ARG CIVIBUS_BUILT_AT=unknown
ENV CIVIBUS_GIT_SHA=$CIVIBUS_GIT_SHA
ENV CIVIBUS_BUILT_AT=$CIVIBUS_BUILT_AT

RUN groupadd --system --gid 10001 civibus \
    && useradd --system --uid 10001 --gid civibus --create-home --home-dir /home/civibus --shell /usr/sbin/nologin civibus \
    && chown -R civibus:civibus /app

USER civibus

EXPOSE 3000

CMD ["node", "build"]
