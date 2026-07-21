// Focused test for assert_live_committee_filings.mjs using only Node built-ins.
// Writes temporary valid/invalid metrics and HTML files and invokes the script as a
// child process, asserting the success case and representative fail-closed cases.

import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_PATH = fileURLToPath(new URL("./assert_live_committee_filings.mjs", import.meta.url));
const WORK_DIR = mkdtempSync(join(tmpdir(), "assert-live-committee-"));

const VALID_METRICS = "200 0.412\n200 0.318\n200 0.501\n";
const VALID_LABEL = "Showing 1–25 of 200 most recent · 220,706 total filings";

let fileCounter = 0;
function writeTempFile(extension, content) {
  fileCounter += 1;
  const path = join(WORK_DIR, `fixture-${fileCounter}.${extension}`);
  writeFileSync(path, content, "utf-8");
  return path;
}

function buildHtml({
  rowCount = 25,
  label = VALID_LABEL,
  includeRegion = true,
  includeTbody = true,
  documentRows = 0,
  distantLabel = null,
  nestedSectionLabel = null
} = {}) {
  const regionRows = Array.from(
    { length: rowCount },
    (_unused, index) => `<tr><td>Filing ${index + 1}</td></tr>`
  ).join("");
  const tableInner = includeTbody
    ? `<thead><tr><th>Filing</th></tr></thead><tbody>${regionRows}</tbody>`
    : regionRows;
  const region = includeRegion
    ? `<div data-testid="filing-breakdown-scroll"><table>${tableInner}</table></div>`
    : `<div data-testid="some-other-region"><table><tbody><tr><td>x</td></tr></tbody></table></div>`;
  // The real markup nests the label and the scroll region as siblings inside one
  // <section>; mirror that so the adjacency check is exercised against a realistic tree.
  const labelElement =
    label === null ? "" : `<p data-testid="filing-breakdown-pagination-label">${label}</p>`;
  const nestedSectionLabelElement =
    nestedSectionLabel === null
      ? ""
      : `<article><p data-testid="filing-breakdown-pagination-label">${nestedSectionLabel}</p></article>`;
  const filingSection = `<section>${nestedSectionLabelElement}${labelElement}${region}</section>`;
  // A valid-looking label placed in an unrelated section, separated from the filing
  // region by section boundaries, must never satisfy the probe.
  const distantSection =
    distantLabel === null
      ? ""
      : `<section><p data-testid="filing-breakdown-pagination-label">${distantLabel}</p></section>`;
  // Broad document rows outside the scroll region must never be counted.
  const documentTable = `<table><tbody>${Array.from(
    { length: documentRows },
    () => `<tr><td>unrelated</td></tr>`
  ).join("")}</tbody></table>`;
  return `<!doctype html><html><body>${documentTable}${distantSection}${filingSection}</body></html>`;
}

function runScript({ metrics = VALID_METRICS, html, maxRows = "200" }) {
  const metricsPath = writeTempFile("metrics", metrics);
  const htmlPath = writeTempFile("html", html);
  return spawnSync(
    process.execPath,
    [SCRIPT_PATH, "--metrics", metricsPath, "--html", htmlPath, "--max-rows", maxRows],
    { encoding: "utf-8" }
  );
}

test("passes for three-200 metrics, a valid region, and an in-range labelled page", () => {
  const result = runScript({ html: buildHtml() });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /OK: 25 filing rows, recent=200, total=220706/);
});

test("passes when count labels use ungrouped decimal digits", () => {
  const result = runScript({
    html: buildHtml({ label: "Showing 1–25 of 200 most recent · 220706 total filings" })
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /OK: 25 filing rows, recent=200, total=220706/);
});

test("passes for Stage 5 try-prefixed curl metrics", () => {
  const result = runScript({
    metrics: "try1 200 0.412\ntry2 200 0.318\ntry3 200 0.501\n",
    html: buildHtml()
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /OK: 25 filing rows, recent=200, total=220706/);
});

test("fails when a metric line reports a non-200 status", () => {
  const result = runScript({ metrics: "200 0.4\n500 0.4\n200 0.4\n", html: buildHtml() });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /non-200/);
});

test("fails when the metrics file does not have exactly three lines", () => {
  const result = runScript({ metrics: "200 0.4\n200 0.4\n", html: buildHtml() });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /exactly 3 metric lines/);
});

test("fails on a malformed metric line", () => {
  const result = runScript({ metrics: "200\n200 0.4\n200 0.4\n", html: buildHtml() });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /malformed metric line/);
});

test("fails closed when the filing-breakdown scroll region is missing", () => {
  const result = runScript({ html: buildHtml({ includeRegion: false }) });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /missing region/);
});

test("fails closed rather than counting broad document rows when the region has no tbody", () => {
  const result = runScript({ html: buildHtml({ includeTbody: false, documentRows: 25 }) });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /no <tbody>/);
});

test("fails when the region has zero data rows", () => {
  const result = runScript({ html: buildHtml({ rowCount: 0 }) });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /outside allowed range/);
});

test("fails when the row count exceeds --max-rows", () => {
  const result = runScript({ html: buildHtml({ rowCount: 30 }), maxRows: "25" });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /outside allowed range/);
});

test("fails when the recent-window label is missing", () => {
  const result = runScript({ html: buildHtml({ label: null }) });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /missing filing-breakdown label/);
});

test("fails when the recent-window count exceeds 200", () => {
  const result = runScript({
    html: buildHtml({ label: "Showing 1–25 of 250 most recent · 300 total filings" })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /exceeds ceiling 200/);
});

test("fails when the recent-window count is smaller than the rendered row count", () => {
  const result = runScript({
    html: buildHtml({ rowCount: 25, label: "Showing 1–25 of 1 most recent · 1 total filings" })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /smaller than the 25 rendered rows/);
});

test("fails when the all-time total is smaller than the recent-window count", () => {
  const result = runScript({
    html: buildHtml({ rowCount: 25, label: "Showing 1–25 of 200 most recent · 1 total filings" })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /all-time total 1 is smaller than the recent-window count 200/);
});

test("fails when the displayed range promises more rows than the table renders", () => {
  const result = runScript({
    html: buildHtml({
      rowCount: 1,
      label: "Showing 1–25 of 200 most recent · 220,706 total filings"
    })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /displayed range 1–25 expects 25 rows but found 1/);
});

test("fails when the table renders more rows than the displayed range promises", () => {
  const result = runScript({
    html: buildHtml({
      rowCount: 26,
      label: "Showing 1–25 of 200 most recent · 220,706 total filings"
    })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /displayed range 1–25 expects 25 rows but found 26/);
});

test("fails when the displayed range is not the contracted first page", () => {
  const result = runScript({
    html: buildHtml({
      rowCount: 25,
      label: "Showing 26–50 of 200 most recent · 220,706 total filings"
    })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /expected first-page filing range 1–25/);
});

test("fails when recent-window count grouping is malformed", () => {
  const result = runScript({
    html: buildHtml({
      rowCount: 25,
      label: "Showing 1–25 of 2,00 most recent · 220,706 total filings"
    })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /malformed recent-window count: 2,00/);
});

test("fails when all-time count grouping is malformed", () => {
  const result = runScript({
    html: buildHtml({
      rowCount: 25,
      label: "Showing 1–25 of 200 most recent · 22,07,06 total filings"
    })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /malformed all-time count: 22,07,06/);
});

test("fails when all-time count exceeds finite safe integer representation", () => {
  const oversizedAllTimeCount = "9".repeat(400);
  const result = runScript({
    html: buildHtml({
      rowCount: 25,
      label: `Showing 1–25 of 200 most recent · ${oversizedAllTimeCount} total filings`
    })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /unsafe all-time count/);
});

test("fails closed when the only valid label is in an unrelated section, not adjacent to the region", () => {
  const result = runScript({
    html: buildHtml({ rowCount: 25, label: null, distantLabel: VALID_LABEL })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /missing filing-breakdown label/);
});

test("fails closed when the only valid label is nested in an unrelated element inside the filing section", () => {
  const result = runScript({
    html: buildHtml({ rowCount: 25, label: null, nestedSectionLabel: VALID_LABEL })
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /missing filing-breakdown label/);
});

test("fails when a metric line records a non-finite time_total", () => {
  const oversizedTiming = `${"9".repeat(400)}.0`;
  const result = runScript({
    metrics: `200 0.4\n200 ${oversizedTiming}\n200 0.4\n`,
    html: buildHtml()
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /non-finite time_total/);
});
