import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const chartsDir = resolve(fileURLToPath(new URL(".", import.meta.url)));
const srcRoot = resolve(chartsDir, "..", "..");

const LAYERCHART_USAGE_PATTERN =
  /(?:\bimport\s+[^;]*?\bfrom\s+["']layerchart(?:\/[^"']+)?["']|\bimport\s+["']layerchart(?:\/[^"']+)?["']|\bexport\s+(?:\*|\*\s+as\s+\w+|\{[^}]*\})\s+from\s+["']layerchart(?:\/[^"']+)?["']|\bimport\s*\(["']layerchart(?:\/[^"']+)?["']\)|\brequire\s*\(["']layerchart(?:\/[^"']+)?["']\))/;

function usesLayerchartModule(source: string): boolean {
  return LAYERCHART_USAGE_PATTERN.test(source);
}

function collectCodeFiles(directory: string): string[] {
  const entries = readdirSync(directory);
  const files: string[] = [];

  for (const entry of entries) {
    const absolutePath = resolve(directory, entry);
    const stats = statSync(absolutePath);

    if (stats.isDirectory()) {
      files.push(...collectCodeFiles(absolutePath));
      continue;
    }

    const isCodeFile = /\.(?:ts|tsx|js|jsx|svelte)$/.test(entry);
    const isTestFile = /\.(?:test|spec)\.[^.]+$/.test(entry);
    if (isCodeFile && !isTestFile) {
      files.push(absolutePath);
    }
  }

  return files;
}

describe("charts import boundary", () => {
  it("detects direct layerchart usage forms including re-exports and subpaths", () => {
    expect(usesLayerchartModule('import { LineChart } from "layerchart";')).toBe(true);
    expect(usesLayerchartModule('import "layerchart";')).toBe(true);
    expect(usesLayerchartModule('export { BarChart } from "layerchart";')).toBe(true);
    expect(usesLayerchartModule('export * as charts from "layerchart";')).toBe(true);
    expect(usesLayerchartModule('export * from "layerchart";')).toBe(true);
    expect(usesLayerchartModule('import { LineChart } from "layerchart/helpers";')).toBe(
      true
    );
    expect(usesLayerchartModule('const chart = await import("layerchart/render");')).toBe(true);
    expect(usesLayerchartModule('const chart = require("layerchart/runtime");')).toBe(true);
    expect(usesLayerchartModule('import { Chart } from "other-package";')).toBe(false);
  });

  it("forbids layerchart imports outside src/lib/charts", () => {
    const offenders = collectCodeFiles(srcRoot).filter((filePath) => {
      if (filePath.startsWith(`${chartsDir}/`)) {
        return false;
      }

      const source = readFileSync(filePath, "utf8");
      return usesLayerchartModule(source);
    });

    expect(offenders).toEqual([]);
  });

  it("routes every layerchart import through the single Chart.svelte adapter", () => {
    const chartFiles = collectCodeFiles(chartsDir);
    const chartFilenames = chartFiles.map((filePath) =>
      filePath.slice(chartsDir.length + 1)
    );
    const layerchartOwners = chartFiles
      .filter((filePath) => usesLayerchartModule(readFileSync(filePath, "utf8")))
      .map((filePath) => filePath.slice(chartsDir.length + 1));

    expect(chartFilenames).toContain("ComparisonBar.svelte");
    expect(layerchartOwners).not.toContain("ComparisonBar.svelte");
    expect(layerchartOwners).toEqual(["Chart.svelte"]);
  });
});
