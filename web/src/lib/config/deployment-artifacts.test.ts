import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as canonicalHelper from "../seo/canonical";

const testFilePath = fileURLToPath(import.meta.url);
const webRoot = resolve(dirname(testFilePath), "../../..");
const readUtf8 = (relativePath: string): string =>
  readFileSync(resolve(webRoot, relativePath), "utf8");
const routeFiles = [
  "src/routes/+page.svelte",
  "src/routes/candidates/+page.svelte",
  "src/routes/candidate/[id]/+page.svelte",
  "src/routes/committees/+page.svelte",
  "src/routes/committee/[id]/+page.svelte",
  "src/routes/coverage/+page.svelte",
  "src/routes/data-sources/+page.svelte",
  "src/routes/methodology/+page.svelte",
  "src/routes/office/[id]/+page.svelte",
  "src/routes/org/[id]/+page.svelte",
  "src/routes/person/[id]/+page.svelte",
  "src/routes/property/[id]/+page.svelte"
];

describe("frontend deployment artifacts", () => {
  it("ships shared canonical helper module", () => {
    const canonicalHelperPath = "src/lib/seo/canonical.ts";

    expect(existsSync(resolve(webRoot, canonicalHelperPath))).toBe(true);
    expect(canonicalHelper.buildCanonicalUrl).toEqual(expect.any(Function));
  });

  it("ships the fallback social image asset used by shared route head metadata", () => {
    expect(existsSync(resolve(webRoot, "static/og-default.png"))).toBe(true);
  });

  it("uses adapter-node and node-serving deployment assets", () => {
    const packageJson = JSON.parse(readUtf8("package.json")) as {
      devDependencies?: Record<string, string>;
    };
    const svelteConfig = readUtf8("svelte.config.js");
    const dockerfile = readUtf8("Dockerfile");
    const dockerignore = readUtf8(".dockerignore");

    expect(packageJson.devDependencies?.["@sveltejs/adapter-node"]).toBeDefined();
    expect(packageJson.devDependencies?.["@sveltejs/adapter-auto"]).toBeUndefined();

    expect(svelteConfig).toContain("@sveltejs/adapter-node");
    expect(svelteConfig).not.toContain("@sveltejs/adapter-auto");

    expect(existsSync(resolve(webRoot, "static/.gitkeep"))).toBe(true);

    expect(dockerfile).toContain("FROM node:22-bookworm-slim AS builder");
    expect(dockerfile).toContain("npm ci");
    expect(dockerfile).toContain("npm run build");
    expect(dockerfile).toContain("npm prune --production");
    expect(dockerfile).toContain("FROM node:22-bookworm-slim");
    expect(dockerfile).toContain("COPY --from=builder /app/build ./build");
    expect(dockerfile).toContain("COPY --from=builder /app/node_modules ./node_modules");
    expect(dockerfile).toContain("COPY --from=builder /app/package.json ./package.json");
    expect(dockerfile).toContain("groupadd --system --gid 10001 civibus");
    expect(dockerfile).toContain(
      "useradd --system --uid 10001 --gid civibus --create-home --home-dir /home/civibus --shell /usr/sbin/nologin civibus"
    );
    expect(dockerfile).toContain("USER civibus");
    expect(dockerfile).toContain("EXPOSE 3000");
    expect(dockerfile).toContain("CMD [\"node\", \"build\"]");

    expect(dockerignore).toContain("node_modules/");
    expect(dockerignore).toContain(".svelte-kit/");
    expect(dockerignore).toContain("build/");
    expect(dockerignore).toContain("tests/");
    expect(dockerignore).toContain("*.test.ts");
    expect(dockerignore).toContain(".env*");
  });

  it("builds canonical metadata from a trusted public origin", () => {
    const compose = readUtf8("../infra/docker-compose.prod.yml");

    expect(compose).toContain("PUBLIC_ORIGIN: ${ORIGIN:?Set ORIGIN}");

    for (const routeFile of routeFiles) {
      const routeSource = readUtf8(routeFile);

      expect(routeSource).toContain("$env/dynamic/public");
      expect(routeSource).toContain("PUBLIC_ORIGIN");
      expect(routeSource).not.toContain("$page.url.href");
    }
  });
});
