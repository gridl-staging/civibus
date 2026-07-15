import { afterEach, describe, expect, it, vi } from "vitest";

type SmokeWebServerConfig = {
  command?: string;
  url?: string;
  env?: Record<string, string>;
};

type SmokePlaywrightConfig = {
  expect?: {
    toHaveScreenshot?: {
      pathTemplate?: string;
    };
  };
  use?: {
    baseURL?: string;
  };
  webServer?: SmokeWebServerConfig | SmokeWebServerConfig[];
};

const LOCAL_FIXTURE_SMOKE_ENV: Record<string, string> = {
  SMOKE_MODE: "local",
  SMOKE_USE_LIVE_API: "0"
};

async function loadPlaywrightConfig(env: Record<string, string | undefined>) {
  vi.resetModules();
  vi.unstubAllEnvs();
  for (const [key, value] of Object.entries(LOCAL_FIXTURE_SMOKE_ENV)) {
    vi.stubEnv(key, value);
  }
  for (const [key, value] of Object.entries(env)) {
    vi.stubEnv(key, value);
  }

  return (await import("../../../../playwright.config")).default as SmokePlaywrightConfig;
}

function localWebServer(config: Awaited<ReturnType<typeof loadPlaywrightConfig>>) {
  const webServer = Array.isArray(config.webServer) ? config.webServer : [];
  const server = webServer.find((entry) => entry.command?.includes("npm run preview"));
  if (server === undefined) {
    throw new Error("Playwright config did not include the local preview web server.");
  }

  return server;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("playwright smoke web port wiring", () => {
  it("stores screenshot baselines in a platform-independent project path", async () => {
    const config = await loadPlaywrightConfig({});

    expect(config.expect?.toHaveScreenshot?.pathTemplate).toBe(
      "{snapshotDir}/{testFileDir}/{testFileName}-snapshots/{arg}{-projectName}{ext}"
    );
    expect(config.expect?.toHaveScreenshot?.pathTemplate).not.toContain("{platform}");
  });

  it("uses SMOKE_WEB_PORT for every local preview URL", async () => {
    const config = await loadPlaywrightConfig({
      SMOKE_WEB_PORT: "4174",
      SMOKE_API_PORT: "4011"
    });
    const server = localWebServer(config);

    expect(config.use?.baseURL).toBe("http://127.0.0.1:4174");
    expect(server.url).toBe("http://127.0.0.1:4174");
    expect(server.command).toContain("--port 4174");
    expect(server.env?.PUBLIC_ORIGIN).toBe("http://127.0.0.1:4174");
  });

  it("preserves explicit SMOKE_BASE_URL for browser navigation only", async () => {
    const config = await loadPlaywrightConfig({
      SMOKE_WEB_PORT: "4174",
      SMOKE_BASE_URL: "http://example.test"
    });
    const server = localWebServer(config);

    expect(config.use?.baseURL).toBe("http://example.test");
    expect(server.url).toBe("http://127.0.0.1:4174");
  });
});
