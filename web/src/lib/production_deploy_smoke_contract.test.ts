import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const productionDeploySpec = readFileSync(
  resolve(__dirname, "../../tests/smoke/production_deploy.spec.ts"),
  "utf8"
);

const donorJourneySource = productionDeploySpec.slice(
  productionDeploySpec.indexOf(
    'test("donor lookup returns live results and links to recipient finance"'
  ),
  productionDeploySpec.indexOf(
    'test("committee detail exposes official totals, cycle history, and linked candidates in production"'
  )
);

const donorResultSelectionHelperSource = productionDeploySpec.slice(
  productionDeploySpec.indexOf("async function donorResultWithPersonRecipient"),
  productionDeploySpec.indexOf(
    'test.describe("production deployment smoke (read-only)"'
  )
);

describe("production donor smoke contract", () => {
  it("selects a donor result row that contains a person recipient link", () => {
    expect(donorJourneySource).not.toContain(
      'page.getByTestId("donor-result-row").first()'
    );
    expect(donorJourneySource).not.toContain('getByRole("link").first()');
    expect(donorJourneySource).toContain("donorResultWithPersonRecipient(page)");
    expect(productionDeploySpec).toContain("const PERSON_ROUTE_HREF_PATTERN");
    expect(productionDeploySpec).toContain("^\\/person\\/[^/?#]+$");
  });

  it("uses the live person-page visibility budget for streamed finance headings", () => {
    expect(donorJourneySource).toMatch(
      /page\.getByRole\("heading",\s*\{\s*name:\s*PERSON_CAMPAIGN_FINANCE_HEADING\s*\}\s*\)\s*\)\.toBeVisible\(\{\s*timeout:\s*20_000\s*\}\)/
    );
    expect(donorJourneySource).toMatch(
      /page\.getByRole\("heading",\s*\{\s*name:\s*"Fundraising detail"\s*\}\s*\)\)\.toBeVisible\(\{\s*timeout:\s*20_000\s*\}\)/
    );
  });

  it("uses the cold-production visibility budget before scanning donor results", () => {
    expect(donorResultSelectionHelperSource).toMatch(
      /expect\(resultRows\.first\(\)\)\.toBeVisible\(\{\s*timeout:\s*20_000\s*\}\)/
    );
  });

  it("uses a stable blank-route input contract before filling the donor query", () => {
    expect(donorJourneySource).not.toContain(
      'not.toHaveAttribute("value", "")'
    );
    expect(donorJourneySource).not.toContain("waitForLoadState");
    expect(donorJourneySource).toContain("await expect(queryInput).toHaveValue(\"\")");
    expect(donorJourneySource).toContain("await queryInput.fill(donorQuery)");
    expect(donorJourneySource).toContain(
      "await expect(queryInput).toHaveValue(donorQuery)"
    );
    expect(donorJourneySource.indexOf('selectOption("name")')).toBeLessThan(
      donorJourneySource.indexOf("queryInput.fill(donorQuery)")
    );
  });
});
