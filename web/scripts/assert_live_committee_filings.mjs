#!/usr/bin/env node
// Fail-closed live assertion for the committee filing-period breakdown table.
//
// Stage 5 runs this after a deployment against captured curl metrics and the live
// committee page HTML. It is deliberately dependency-free (Node built-ins only) and
// fails closed: any missing region, missing label, malformed input, or out-of-range
// count exits non-zero rather than silently passing. It never counts document-wide
// rows — only the data rows inside the filing-breakdown scroll region's first tbody.
//
// Usage:
//   node assert_live_committee_filings.mjs --metrics <path> --html <path> --max-rows <n>
//
// Metrics file: exactly three lines, each "<http_code> <time_total>" or
// "tryN <http_code> <time_total>". All three codes must be 200; timings are
// recorded but no latency threshold is enforced.

import { readFileSync } from "node:fs";

const FILING_SCROLL_TEST_ID = "filing-breakdown-scroll";
const FILING_LABEL_TEST_ID = "filing-breakdown-pagination-label";
const REQUIRED_METRIC_LINE_COUNT = 3;
const RECENT_WINDOW_CEILING = 200;
const CONTRACTED_FIRST_PAGE_START = 1;
const CONTRACTED_FIRST_PAGE_END = 25;
// Matches the honest recent-window-vs-all-time label, using the exact en-dash and
// middot the presenter emits. Count tokens are validated before comma removal.
const FILING_LABEL_PATTERN =
  /Showing (\d+)–(\d+) of (\d[\d,]*) most recent · (\d[\d,]*) total filings/;
const COUNT_TOKEN_PATTERN = /^(?:\d+|\d{1,3}(?:,\d{3})+)$/;
const VOID_ELEMENT_TAGS = new Set([
  "area",
  "base",
  "br",
  "col",
  "embed",
  "hr",
  "img",
  "input",
  "link",
  "meta",
  "param",
  "source",
  "track",
  "wbr"
]);

class AssertionError extends Error {}

function fail(message) {
  console.error(`assert_live_committee_filings: ${message}`);
  process.exit(1);
}

function parseArgs(argv) {
  const parsed = { metrics: null, html: null, maxRows: null };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === "--metrics") {
      parsed.metrics = value;
      index += 1;
    } else if (flag === "--html") {
      parsed.html = value;
      index += 1;
    } else if (flag === "--max-rows") {
      parsed.maxRows = value;
      index += 1;
    } else {
      throw new AssertionError(`unknown argument: ${flag}`);
    }
  }

  if (parsed.metrics == null || parsed.html == null || parsed.maxRows == null) {
    throw new AssertionError("required flags: --metrics <path> --html <path> --max-rows <n>");
  }

  const maxRows = Number(parsed.maxRows);
  if (!Number.isInteger(maxRows) || maxRows < 1) {
    throw new AssertionError(`--max-rows must be a positive integer, got: ${parsed.maxRows}`);
  }

  return { metricsPath: parsed.metrics, htmlPath: parsed.html, maxRows };
}

function parseMetricLine(line) {
  const fields = line.split(/\s+/);
  if (fields.length === 2) {
    return { httpCode: fields[0], timeTotal: fields[1] };
  }
  if (fields.length === 3 && /^try\d+$/.test(fields[0])) {
    return { httpCode: fields[1], timeTotal: fields[2] };
  }
  throw new AssertionError(`malformed metric line: ${line}`);
}

/** Requires exactly three curl metric lines, all HTTP 200. Returns timings. */
function assertMetricsAllOk(metricsText) {
  const lines = metricsText
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  if (lines.length !== REQUIRED_METRIC_LINE_COUNT) {
    throw new AssertionError(
      `expected exactly ${REQUIRED_METRIC_LINE_COUNT} metric lines, got ${lines.length}`
    );
  }

  const timings = [];
  for (const line of lines) {
    const { httpCode, timeTotal } = parseMetricLine(line);
    if (!/^\d{3}$/.test(httpCode)) {
      throw new AssertionError(`malformed http_code in metric line: ${line}`);
    }
    if (!/^\d+(?:\.\d+)?$/.test(timeTotal)) {
      throw new AssertionError(`malformed time_total in metric line: ${line}`);
    }
    if (httpCode !== "200") {
      throw new AssertionError(`metric line reports non-200 status: ${line}`);
    }
    const timing = Number(timeTotal);
    if (!Number.isFinite(timing)) {
      throw new AssertionError(`non-finite time_total in metric line: ${line}`);
    }
    timings.push(timing);
  }

  return timings;
}

/**
 * Locates the element carrying `data-testid="<testId>"` at or after `fromIndex`, tracking
 * nesting of the same tag name so a wrapper with nested same-tag children is captured
 * whole. Returns `{ html, tagName, startIndex, endIndex }` (endIndex exclusive) or null
 * when the marker or a matching close tag is absent.
 */
function findElementByTestId(html, testId, fromIndex = 0) {
  const marker = `data-testid="${testId}"`;
  const markerIndex = html.indexOf(marker, fromIndex);
  if (markerIndex === -1) {
    return null;
  }

  const openStartIndex = html.lastIndexOf("<", markerIndex);
  const openEndIndex = html.indexOf(">", markerIndex);
  if (openStartIndex === -1 || openEndIndex === -1) {
    return null;
  }

  const tagNameMatch = html.slice(openStartIndex, openEndIndex + 1).match(/^<([a-z0-9-]+)/i);
  if (!tagNameMatch) {
    return null;
  }

  const tagName = tagNameMatch[1];
  if (html.slice(openStartIndex, openEndIndex + 1).endsWith("/>")) {
    return {
      html: html.slice(openStartIndex, openEndIndex + 1),
      tagName,
      startIndex: openStartIndex,
      endIndex: openEndIndex + 1
    };
  }

  const sameTagPattern = new RegExp(`<\\/?${tagName}(?:\\s[^>]*)?>`, "gi");
  sameTagPattern.lastIndex = openEndIndex + 1;
  let depth = 1;
  let match = sameTagPattern.exec(html);
  while (match !== null) {
    const token = match[0];
    if (token.startsWith("</")) {
      depth -= 1;
    } else if (!token.endsWith("/>")) {
      depth += 1;
    }
    if (depth === 0) {
      const endIndex = match.index + token.length;
      return {
        html: html.slice(openStartIndex, endIndex),
        tagName,
        startIndex: openStartIndex,
        endIndex
      };
    }
    match = sameTagPattern.exec(html);
  }

  return null;
}

/**
 * A label satisfies the probe only when it is inside the selected filing region or is a
 * structural sibling of it. A valid-looking label nested in an unrelated wrapper inside
 * the same filing section must not be honored.
 */
function labelIsAdjacentToRegion(html, label, region) {
  if (label.startIndex >= region.startIndex && label.endIndex <= region.endIndex) {
    return true;
  }
  const labelParent = findImmediateParentElement(html, label);
  const regionParent = findImmediateParentElement(html, region);
  return (
    labelParent !== null &&
    regionParent !== null &&
    labelParent.startIndex === regionParent.startIndex &&
    labelParent.tagName === regionParent.tagName
  );
}

function isSelfClosingToken(tagName, token) {
  return token.endsWith("/>") || VOID_ELEMENT_TAGS.has(tagName.toLowerCase());
}

function findImmediateParentElement(html, element) {
  const elementPattern = /<\/?([a-z0-9-]+)(?:\s[^>]*)?>/gi;
  const stack = [];
  let match = elementPattern.exec(html);
  while (match !== null && match.index < element.startIndex) {
    const token = match[0];
    const tagName = match[1].toLowerCase();
    if (token.startsWith("</")) {
      const index = stack.findLastIndex((entry) => entry.tagName === tagName);
      if (index !== -1) {
        stack.length = index;
      }
    } else if (!isSelfClosingToken(tagName, token)) {
      stack.push({ tagName, startIndex: match.index });
    }
    match = elementPattern.exec(html);
  }
  return stack.length === 0 ? null : stack.at(-1);
}

/** Returns the nearest pagination label element adjacent to the region, or null. */
function findAdjacentLabelElement(html, region) {
  let fromIndex = 0;
  for (;;) {
    const label = findElementByTestId(html, FILING_LABEL_TEST_ID, fromIndex);
    if (label === null) {
      return null;
    }
    if (labelIsAdjacentToRegion(html, label, region)) {
      return label;
    }
    fromIndex = label.endIndex;
  }
}

/** Strips tags to plain text so labels split across inline markup still match. */
function toPlainText(htmlFragment) {
  return htmlFragment.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

/** Counts data `<tr>` rows inside the region's first `<tbody>`; fails if that tbody is absent. */
function countFilingRows(regionHtml) {
  const tbodyMatch = regionHtml.match(/<tbody(?:\s[^>]*)?>([\s\S]*?)<\/tbody>/i);
  if (tbodyMatch === null) {
    throw new AssertionError("filing-breakdown region has no <tbody>");
  }

  const rowMatches = tbodyMatch[1].match(/<tr(?:\s[^>]*)?>/gi);
  return rowMatches === null ? 0 : rowMatches.length;
}

function parseGroupedDecimalCount(value, label) {
  if (!COUNT_TOKEN_PATTERN.test(value)) {
    throw new AssertionError(`malformed ${label} count: ${value}`);
  }
  const count = Number(value.replace(/,/g, ""));
  if (!Number.isSafeInteger(count)) {
    throw new AssertionError(`unsafe ${label} count: ${value}`);
  }
  return count;
}

function parseDisplayedRange(startValue, endValue) {
  const start = Number(startValue);
  const end = Number(endValue);
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start) {
    throw new AssertionError(`malformed displayed filing range: ${startValue}–${endValue}`);
  }
  return { start, end, size: end - start + 1 };
}

function assertContractedFirstPageRange(displayedRange) {
  if (
    displayedRange.start !== CONTRACTED_FIRST_PAGE_START ||
    displayedRange.end !== CONTRACTED_FIRST_PAGE_END
  ) {
    throw new AssertionError(
      `expected first-page filing range ${CONTRACTED_FIRST_PAGE_START}–${CONTRACTED_FIRST_PAGE_END}, ` +
        `got ${displayedRange.start}–${displayedRange.end}`
    );
  }
}

function main() {
  let args;
  let metricsText;
  let html;
  try {
    args = parseArgs(process.argv.slice(2));
    metricsText = readFileSync(args.metricsPath, "utf-8");
    html = readFileSync(args.htmlPath, "utf-8");
  } catch (error) {
    fail(error instanceof Error ? error.message : String(error));
    return;
  }

  try {
    const timings = assertMetricsAllOk(metricsText);

    const region = findElementByTestId(html, FILING_SCROLL_TEST_ID);
    if (region === null) {
      throw new AssertionError(`missing region: data-testid="${FILING_SCROLL_TEST_ID}"`);
    }
    const regionHtml = region.html;

    const rowCount = countFilingRows(regionHtml);
    if (rowCount < 1 || rowCount > args.maxRows) {
      throw new AssertionError(
        `filing row count ${rowCount} outside allowed range 1..${args.maxRows}`
      );
    }

    // The label lives in an element that is either inside the scroll region or a
    // structural sibling of it, so search the region text plus the adjacent label text.
    // A valid-looking label in an unrelated section is not adjacent and is ignored.
    const adjacentLabel = findAdjacentLabelElement(html, region);
    const labelSearchText = [
      toPlainText(regionHtml),
      adjacentLabel === null ? "" : toPlainText(adjacentLabel.html)
    ].join(" ");
    const labelMatch = labelSearchText.match(FILING_LABEL_PATTERN);
    if (labelMatch === null) {
      throw new AssertionError("missing filing-breakdown label matching the recent-window format");
    }

    const displayedRange = parseDisplayedRange(labelMatch[1], labelMatch[2]);
    const recentCount = parseGroupedDecimalCount(labelMatch[3], "recent-window");
    const allTimeCount = parseGroupedDecimalCount(labelMatch[4], "all-time");
    if (!Number.isInteger(recentCount) || recentCount > RECENT_WINDOW_CEILING) {
      throw new AssertionError(
        `recent-window count ${labelMatch[3]} exceeds ceiling ${RECENT_WINDOW_CEILING}`
      );
    }

    // Cross-check the label against the rendered table. The displayed range size must
    // equal the rows in the first tbody; the recent window must be at least the number
    // of rows shown; and the all-time total must be at least the recent window.
    assertContractedFirstPageRange(displayedRange);
    if (displayedRange.size !== rowCount) {
      throw new AssertionError(
        `displayed range ${displayedRange.start}–${displayedRange.end} ` +
          `expects ${displayedRange.size} rows but found ${rowCount}`
      );
    }
    if (recentCount < rowCount) {
      throw new AssertionError(
        `recent-window count ${recentCount} is smaller than the ${rowCount} rendered rows`
      );
    }
    if (allTimeCount < recentCount) {
      throw new AssertionError(
        `all-time total ${allTimeCount} is smaller than the recent-window count ${recentCount}`
      );
    }

    console.log(
      `OK: ${rowCount} filing rows, recent=${recentCount}, total=${allTimeCount}, ` +
        `timings=[${timings.join(", ")}]`
    );
  } catch (error) {
    fail(error instanceof Error ? error.message : String(error));
  }
}

main();
