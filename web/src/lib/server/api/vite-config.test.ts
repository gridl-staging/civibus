import { afterEach, describe, expect, it, vi } from "vitest";

type PreviewProxyRule = {
  target?: string;
  rewrite?: (path: string) => string;
};

type ViteConfig = {
  preview?: {
    proxy?: Record<string, string | PreviewProxyRule>;
  };
};

async function loadViteConfig(env: Record<string, string | undefined>) {
  vi.resetModules();
  vi.unstubAllEnvs();
  for (const [key, value] of Object.entries(env)) {
    vi.stubEnv(key, value);
  }

  return (await import("../../../../vite.config")).default as ViteConfig;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("vite preview proxy", () => {
  it("routes same-origin oracle API requests to the local smoke backend", async () => {
    const config = await loadViteConfig({ SMOKE_API_PORT: "3989" });
    const apiProxy = config.preview?.proxy?.["/api"];

    expect(typeof apiProxy).toBe("object");
    expect((apiProxy as PreviewProxyRule).target).toBe("http://127.0.0.1:3989");
    expect((apiProxy as PreviewProxyRule).rewrite?.("/api/v1/candidates?limit=200&offset=0")).toBe(
      "/v1/candidates?limit=200&offset=0"
    );
    expect((apiProxy as PreviewProxyRule).rewrite?.("/candidate/alice")).toBe("/candidate/alice");
  });
});
