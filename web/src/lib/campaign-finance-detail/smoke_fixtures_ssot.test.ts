import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const fixturesSource = readFileSync(
  resolve(__dirname, "../../../tests/smoke/fixtures.ts"),
  "utf-8"
);

function assignmentRHS(source: string, constName: string): string {
  const pattern = new RegExp(
    `export\\s+const\\s+${constName}\\s*=\\s*(.+?)\\s*;`
  );
  const match = source.match(pattern);
  if (!match) {
    throw new Error(`Could not find export const ${constName} in fixtures.ts`);
  }
  return match[1].trim();
}

describe("smoke fixtures single-source aliases", () => {
  it("SMOKE_CONTEST_WINNER_NAME is aliased to SMOKE_CANDIDACY_PERSON_NAME, not a string literal", () => {
    expect(assignmentRHS(fixturesSource, "SMOKE_CONTEST_WINNER_NAME")).toBe(
      "SMOKE_CANDIDACY_PERSON_NAME"
    );
  });

  it("SMOKE_OFFICE_RECENT_CONTEST_NAME is aliased to SMOKE_CONTEST_NAME, not a string literal", () => {
    expect(assignmentRHS(fixturesSource, "SMOKE_OFFICE_RECENT_CONTEST_NAME")).toBe(
      "SMOKE_CONTEST_NAME"
    );
  });
});
