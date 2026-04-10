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

RUN groupadd --system --gid 10001 civibus \
    && useradd --system --uid 10001 --gid civibus --create-home --home-dir /home/civibus --shell /usr/sbin/nologin civibus \
    && chown -R civibus:civibus /app

USER civibus

EXPOSE 3000

CMD ["node", "build"]
