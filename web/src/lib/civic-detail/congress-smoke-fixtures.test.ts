import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  buildCongressSmokeCleanupSql,
  buildCongressSmokeSeedSql,
  SMOKE_CANDIDATE_ID,
  SMOKE_COMMITTEE_ID,
  SMOKE_PERSON_ID
} from "../../../tests/smoke/fixtures";

describe("Congress smoke fixture cleanup", () => {
  it("does not target shared live-mode smoke IDs during Stage 4 cleanup", () => {
    const cleanupSql = buildCongressSmokeCleanupSql();

    expect(cleanupSql).not.toContain(SMOKE_PERSON_ID);
    expect(cleanupSql).not.toContain(SMOKE_CANDIDATE_ID);
    expect(cleanupSql).not.toContain(SMOKE_COMMITTEE_ID);
    expect(cleanupSql).not.toMatch(/\bperson_id\s*=/);
    expect(cleanupSql).not.toMatch(/\bcandidate_id\s*=/);
    expect(cleanupSql).not.toMatch(/\bcommittee_id\s*=/);

    expect(cleanupSql).toContain("smoke-congress-officeholding");
    expect(cleanupSql).toContain("smoke-congress-fec-summary");
    expect(cleanupSql).toContain("smoke-congress-ie-support");
    expect(cleanupSql).toContain("smoke-congress-ie-oppose");
  });

  it("does not insert shared live-mode smoke IDs during Stage 4 seeding", () => {
    const seedSql = buildCongressSmokeSeedSql();

    expect(seedSql).not.toContain(SMOKE_PERSON_ID);
    expect(seedSql).not.toContain(SMOKE_CANDIDATE_ID);
    expect(seedSql).not.toContain(SMOKE_COMMITTEE_ID);
  });

  it("materializes and cleans up the Stage 4 person graph node", () => {
    const seedSql = buildCongressSmokeSeedSql();
    const cleanupSql = buildCongressSmokeCleanupSql();

    expect(seedSql).toContain("MERGE (n:Person");
    expect(seedSql).toContain("SET n.canonical_name");
    expect(cleanupSql).toContain("SELECT ag_catalog.create_graph('civibus')");
    expect(cleanupSql).toContain("DETACH DELETE n");
  });

  it("filters before asserting the first Congress member row", () => {
    const specSource = readFileSync(resolve(__dirname, "../../../tests/smoke/congress.spec.ts"), "utf8");
    const firstRowAssertionIndex = specSource.indexOf('getByTestId("congress-member-row-0")');
    const searchFillIndex = specSource.indexOf('getByTestId("congress-search").fill');

    expect(firstRowAssertionIndex).toBeGreaterThan(searchFillIndex);
  });
});
