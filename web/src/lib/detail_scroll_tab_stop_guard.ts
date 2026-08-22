import { readFileSync } from "node:fs";
import { expect } from "vitest";

export function expectScrollContainersHaveTabStop(sourceUrl: URL): void {
  const source = readFileSync(sourceUrl, "utf8");
  const containers = [...source.matchAll(/<div class="detail__table-scroll"[^>]*>/g)].map(
    (match) => match[0]
  );

  // axe rule scrollable-region-focusable, impact serious. .detail__table-scroll
  // sets overflow-x: auto over a table wider than its container; with no
  // focusable descendant such a region cannot be scrolled from the keyboard at
  // all. The smoke a11y floor refuses serious violations, but it only runs
  // nightly - this holds the same invariant at vitest speed, and it fails the
  // moment a new scroll container is added without the attribute rather than
  // when the fix is deleted from an old one.
  expect(containers.length).toBeGreaterThan(0);
  for (const container of containers) {
    expect(container).toContain('tabindex="0"');
  }
}
