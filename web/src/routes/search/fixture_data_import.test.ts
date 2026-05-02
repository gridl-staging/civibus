import { spawnSync } from "node:child_process";
import path from "node:path";

import { describe, expect, it } from "vitest";

const WEB_ROOT = path.resolve(import.meta.dirname, "..", "..", "..");

describe("smoke fixture data module", () => {
  it("loads under node experimental strip-types startup path", () => {
    const command = [
      "import { pathToFileURL } from 'node:url';",
      "await import(pathToFileURL('./tests/smoke/fixture-data.ts').href);"
    ].join("\n");
    const result = spawnSync(process.execPath, ["--experimental-strip-types", "--input-type=module", "--eval", command], {
      cwd: WEB_ROOT,
      encoding: "utf-8"
    });

    expect(result.status).toBe(0);
    expect(result.stderr).toBe("");
  });
});
