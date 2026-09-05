import { expect, test } from "playwright/test";
import {
  closeSync,
  constants,
  existsSync,
  fchmodSync,
  fsyncSync,
  lstatSync,
  linkSync,
  openSync,
  unlinkSync,
  writeSync,
} from "node:fs";
import { randomBytes } from "node:crypto";
import { basename, dirname, isAbsolute, join } from "node:path";
import {
  SMOKE_STATE_DETAIL_CANDIDATE_NAME,
  SMOKE_STATE_DETAIL_COMMITTEE_NAME,
  SMOKE_STATE_DETAIL_MONEY,
  SMOKE_STATE_DETAIL_STATUS_HEADING,
  SMOKE_STATE_DETAIL_SUPPORTED_CODE,
  SMOKE_STATE_DETAIL_SUPPORTED_NAME,
  SMOKE_STATE_DETAIL_UNAVAILABLE_CODE,
  SMOKE_STATE_DETAIL_UNAVAILABLE_NAME,
} from "./fixtures";
import { capturePageLoadErrors } from "./smoke-helpers";

const isProductionSmokeMode =
  (process.env.SMOKE_MODE ?? "local") === "production";
const rawBrowserEvidenceOutput =
  process.env.CIVIBUS_SURFACE_PARITY_RAW_BROWSER_OUTPUT ?? "";

type RawBrowserRoute = {
  path: string;
  http_status: 200;
  heading: string;
  campaign_finance_status: "available" | "direct" | "inherited";
  authority_identity: string;
};

function requiredEvidenceIdentity(name: string, pattern?: RegExp): string {
  const value = process.env[name] ?? "";
  if (
    value.length === 0 ||
    /[\r\n\0]/.test(value) ||
    (pattern !== undefined && !pattern.test(value))
  ) {
    throw new Error(
      `invalid or missing ${name} for raw browser parity evidence`,
    );
  }
  return value;
}

function publishRawBrowserEvidence(routes: RawBrowserRoute[]): void {
  if (!isAbsolute(rawBrowserEvidenceOutput)) {
    throw new Error("raw browser parity output must be an absolute path");
  }
  const parent = lstatSync(dirname(rawBrowserEvidenceOutput));
  if (!parent.isDirectory() || parent.isSymbolicLink()) {
    throw new Error(
      "raw browser parity output parent must be an existing regular directory",
    );
  }
  const revision = requiredEvidenceIdentity(
    "CIVIBUS_EXPECTED_SHA",
    /^[0-9a-f]{40}$/,
  );
  const qualifiedImage = requiredEvidenceIdentity("CIVIBUS_QUALIFIED_IMAGE");
  if (/(?:token|password|secret)/i.test(qualifiedImage)) {
    throw new Error(
      "qualified image identity contains a credential-bearing token",
    );
  }
  const payload = {
    schema_version: 1,
    captured_at: new Date().toISOString(),
    source_revision: revision,
    api_revision: revision,
    web_revision: revision,
    candidate_receipt_file_sha256: requiredEvidenceIdentity(
      "CIVIBUS_CANDIDATE_RECEIPT_SHA256",
      /^[0-9a-f]{64}$/,
    ),
    candidate_tree_git_sha: requiredEvidenceIdentity(
      "CIVIBUS_CANDIDATE_TREE_GIT_SHA",
      /^[0-9a-f]{40}$/,
    ),
    qualified_image: qualifiedImage,
    promotion_bundle_sha256: requiredEvidenceIdentity(
      "CIVIBUS_PROMOTION_BUNDLE_SHA256",
      /^[0-9a-f]{64}$/,
    ),
    filing_authority: { kind: "state", code: "WA" },
    federal_identity_sha256: requiredEvidenceIdentity(
      "CIVIBUS_FEDERAL_IDENTITY_SHA256",
      /^[0-9a-f]{64}$/,
    ),
    routes,
    washington_specimens: [
      "WA PDC Contributions",
      "WA PDC Expenditures",
      "WA PDC Independent Expenditures",
      "WA PDC Loans",
    ],
  };
  const data = Buffer.from(`${JSON.stringify(payload)}\n`, "utf8");
  const temporary = join(
    dirname(rawBrowserEvidenceOutput),
    `.${basename(rawBrowserEvidenceOutput)}.${process.pid}.${randomBytes(8).toString("hex")}.tmp`,
  );
  const descriptor = openSync(
    temporary,
    constants.O_WRONLY |
      constants.O_CREAT |
      constants.O_EXCL |
      (constants.O_NOFOLLOW ?? 0),
    0o600,
  );
  try {
    fchmodSync(descriptor, 0o600);
    writeSync(descriptor, data);
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
  try {
    linkSync(temporary, rawBrowserEvidenceOutput);
    const directoryDescriptor = openSync(
      dirname(rawBrowserEvidenceOutput),
      constants.O_RDONLY,
    );
    try {
      fsyncSync(directoryDescriptor);
    } finally {
      closeSync(directoryDescriptor);
    }
  } finally {
    if (existsSync(temporary)) {
      unlinkSync(temporary);
    }
  }
}

test.describe("Washington state campaign-finance product", () => {
  test("searches to Washington and renders bounded money, civic links, committees, and provenance", async ({
    page,
  }: {
    page: any;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);
    await page.goto(`/search?q=Washington&entity_type=region`);
    const washingtonLink = page.getByRole("link", {
      name: SMOKE_STATE_DETAIL_SUPPORTED_NAME,
      exact: true,
    });
    await expect(washingtonLink).toHaveAttribute(
      "href",
      `/state/${SMOKE_STATE_DETAIL_SUPPORTED_CODE}`,
    );
    await washingtonLink.click();

    await expect(page).toHaveURL(
      new RegExp(`/state/${SMOKE_STATE_DETAIL_SUPPORTED_CODE}$`),
    );
    await expect(
      page.getByRole("heading", {
        name: SMOKE_STATE_DETAIL_SUPPORTED_NAME,
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: isProductionSmokeMode
          ? "Campaign finance available"
          : SMOKE_STATE_DETAIL_STATUS_HEADING,
      }),
    ).toBeVisible();
    await expect(
      page.getByText("Washington Public Disclosure Commission").first(),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Current Washington biennium" }),
    ).toBeVisible();

    const moneyLabels = [
      "Contributions",
      "Expenditures",
      "Candidate-targeted independent expenditures",
      "Loans",
    ];
    for (const [index, label] of moneyLabels.entries()) {
      const moneyCard = page.getByRole("article", { name: label, exact: true });
      await expect(moneyCard).toBeVisible();
      if (isProductionSmokeMode) {
        await expect(moneyCard).not.toContainText("Unavailable");
        await expect(moneyCard).toContainText(/\$[0-9,]+\.\d{2}/);
      } else {
        await expect(moneyCard).toContainText(SMOKE_STATE_DETAIL_MONEY[index]);
      }
    }

    const candidateRegion = page.getByRole("region", {
      name: "State candidates and civic connections",
    });
    await expect(candidateRegion).toBeVisible();
    const candidateLink = isProductionSmokeMode
      ? candidateRegion.getByRole("link").first()
      : candidateRegion.getByRole("link", {
          name: SMOKE_STATE_DETAIL_CANDIDATE_NAME,
        });
    await expect(candidateLink).toHaveAttribute(
      "href",
      /^\/person\/[0-9a-f-]+$/,
    );
    await expect(page.getByRole("link", { name: "Candidacy" })).toHaveAttribute(
      "href",
      /^\/candidacy\/[0-9a-f-]+$/,
    );
    const committeeRegion = page.getByRole("region", {
      name: "Committees in this bounded activity",
    });
    await expect(committeeRegion).toBeVisible();
    const committeeLink = isProductionSmokeMode
      ? committeeRegion.getByRole("link").first()
      : committeeRegion.getByRole("link", {
          name: SMOKE_STATE_DETAIL_COMMITTEE_NAME,
        });
    await expect(committeeLink).toHaveAttribute(
      "href",
      /^\/committee\/[0-9a-f-]+$/,
    );

    await expect(
      page.getByRole("heading", { name: "Coverage boundary" }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "No state amount is combined with county, municipality, or committee-city proxy totals.",
      ),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Sources, provenance, and freshness" }),
    ).toBeVisible();
    for (const sourceName of [
      "WA PDC Contributions",
      "WA PDC Expenditures",
      "WA PDC Independent Expenditures",
      "WA PDC Loans",
    ]) {
      await expect(page.getByRole("link", { name: sourceName })).toBeVisible();
    }
    await expect(
      page.getByText("Last successful source pull").first(),
    ).toBeVisible();
    await expect(page.getByText("Latest refresh run").first()).toBeVisible();
    await expect(
      page.getByText("Transaction data through:").first(),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Named gaps and limitations" }),
    ).toBeVisible();
    await pageLoadErrors.assertNoErrors();
  });

  test("keeps Seattle inherited and New York City separate-direct without combined totals", async ({
    page,
  }: {
    page: any;
  }) => {
    await page.goto("/state/WA/municipality/seattle");
    await expect(
      page.getByRole("heading", { name: "Seattle", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Washington (WA)")).toBeVisible();
    await expect(page.getByText("inherited", { exact: true })).toBeVisible();
    await expect(
      page.getByText("covered_by_parent", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "No state, parent, child, or direct-target amount is guessed or combined on this page.",
      ),
    ).toBeVisible();

    await page.goto("/state/NY/municipality/new-york-city");
    await expect(
      page.getByRole("heading", { name: "New York City", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("New York City (NY_NEW_YORK)")).toBeVisible();
    await expect(page.getByText("direct", { exact: true })).toBeVisible();
    await expect(
      page.getByText("independent_target", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(/no New York State total or combined total is shown/i),
    ).toBeVisible();
  });

  test("publishes exact fresh production browser parity evidence", async ({
    page,
  }: {
    page: any;
  }) => {
    test.skip(
      !isProductionSmokeMode || rawBrowserEvidenceOutput.length === 0,
      "raw browser parity publication is a production promotion-evidence contract",
    );

    const routes: RawBrowserRoute[] = [];
    let response = await page.goto("/state/WA");
    expect(response?.status()).toBe(200);
    await expect(
      page.getByRole("heading", { name: "Washington", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Campaign finance available",
        exact: true,
      }),
    ).toBeVisible();
    for (const sourceName of [
      "WA PDC Contributions",
      "WA PDC Expenditures",
      "WA PDC Independent Expenditures",
      "WA PDC Loans",
    ]) {
      await expect(page.getByRole("link", { name: sourceName })).toBeVisible();
    }
    routes.push({
      path: "/state/WA",
      http_status: 200,
      heading: "Washington",
      campaign_finance_status: "available",
      authority_identity: "state/WA",
    });

    response = await page.goto("/state/WA/municipality/seattle");
    expect(response?.status()).toBe(200);
    await expect(
      page.getByRole("heading", { name: "Seattle", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Washington (WA)")).toBeVisible();
    await expect(page.getByText("inherited", { exact: true })).toBeVisible();
    routes.push({
      path: "/state/WA/municipality/seattle",
      http_status: 200,
      heading: "Seattle",
      campaign_finance_status: "inherited",
      authority_identity: "state/WA",
    });

    response = await page.goto("/state/NY/municipality/new-york-city");
    expect(response?.status()).toBe(200);
    await expect(
      page.getByRole("heading", { name: "New York City", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("New York City (NY_NEW_YORK)")).toBeVisible();
    await expect(page.getByText("direct", { exact: true })).toBeVisible();
    routes.push({
      path: "/state/NY/municipality/new-york-city",
      http_status: 200,
      heading: "New York City",
      campaign_finance_status: "direct",
      authority_identity: "named_other/NY_NEW_YORK",
    });

    publishRawBrowserEvidence(routes);
  });

  test("keeps an ordinary unavailable state and Wake County truthful", async ({
    page,
  }: {
    page: any;
  }) => {
    await page.goto(`/state/${SMOKE_STATE_DETAIL_UNAVAILABLE_CODE}`);
    await expect(
      page.getByRole("heading", {
        name: SMOKE_STATE_DETAIL_UNAVAILABLE_NAME,
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Campaign finance unavailable" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "State campaign-finance product unavailable",
      }),
    ).toBeVisible();
    await expect(
      page.getByText(/Federal or parent totals are not substituted/),
    ).toBeVisible();

    await page.goto("/state/NC/county/wake");
    await expect(
      page.getByRole("heading", { name: "Wake County", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Campaign finance unavailable" }),
    ).toBeVisible();
    await expect(page.getByText(/not combined/i)).toBeVisible();
  });
});
