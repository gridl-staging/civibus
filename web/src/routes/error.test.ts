import { describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";

let currentPageStatus = 503;
const currentPageUrl = new URL("https://civibus.test//attacker.example/phish?state=NC");

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { status: number; url: URL }) => void): () => void {
      run({ status: currentPageStatus, url: currentPageUrl });
      return () => {};
    }
  }
}));

const { default: ErrorPage } = await import("./+error.svelte");

describe("+error.svelte SSR rendering", () => {
  it("renders service-unavailable copy and HTTP 503 from page status when the status prop is missing", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: undefined as unknown as number,
        error: {
          message: "Backend service unavailable."
        } as App.Error
      }
    });

    expect(rendered.body).toContain("Service temporarily unavailable");
    expect(rendered.body).toContain("HTTP 503");
    expect(rendered.body).not.toContain("HTTP </p>");
  });

  it("renders safe donor-search copy for the structured rollup-unavailable 503", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 503,
        error: {
          detail: {
            code: "donor_search_rollup_unavailable"
          }
        } as unknown as App.Error
      }
    });

    expect(rendered.body).toContain("HTTP 503");
    expect(rendered.body).toContain(
      "Donor search is temporarily unavailable while contribution data is refreshed."
    );
    expect(rendered.body).not.toContain("donor_search_rollup_unavailable");
    expect(rendered.body).not.toContain("Unexpected application error.");
  });

  it("renders the error.message string verbatim when no detail array is present", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 500,
        error: {
          message: "Database connection timed out."
        } as App.Error
      }
    });

    expect(rendered.body).toContain("Database connection timed out.");
    expect(rendered.body).toContain("HTTP 500");
  });

  it("falls back to the generic application-error copy when the error payload is null", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 500,
        error: null as unknown as App.Error
      }
    });

    expect(rendered.body).toContain("Unexpected application error.");
    expect(rendered.body).toContain("Service temporarily unavailable");
    expect(rendered.body).toContain("HTTP 500");
  });

  it("falls back to the generic application-error copy when the error payload is undefined", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 500,
        error: undefined as unknown as App.Error
      }
    });

    expect(rendered.body).toContain("Unexpected application error.");
  });

  it("falls back to the generic application-error copy when detail is an empty array and message is missing", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 422,
        error: { detail: [] } as unknown as App.Error
      }
    });

    expect(rendered.body).toContain("Unexpected application error.");
    expect(rendered.body).toContain("Request could not be completed");
    expect(rendered.body).toContain("HTTP 422");
  });

  it("falls back to the generic application-error copy when message is whitespace and no detail is present", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 500,
        error: { message: "   " } as unknown as App.Error
      }
    });

    expect(rendered.body).toContain("Unexpected application error.");
  });

  it("prefers a string detail over the message field", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 400,
        error: {
          message: "Should not appear.",
          detail: "Validation failed because the search term was missing."
        } as unknown as App.Error
      }
    });

    expect(rendered.body).toContain("Validation failed because the search term was missing.");
    expect(rendered.body).not.toContain("Should not appear.");
    expect(rendered.body).toContain("Request could not be completed");
    expect(rendered.body).toContain("HTTP 400");
  });

  it("falls back when a detail array contains only malformed issues without msg", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 422,
        error: {
          detail: [
            { loc: ["query", "q"] },
            { loc: ["body", "name"], msg: "" },
            null,
            "not-an-object"
          ]
        } as unknown as App.Error
      }
    });

    expect(rendered.body).toContain("Unexpected application error.");
    expect(rendered.body).toContain("HTTP 422");
  });

  it("renders the explicit status prop and overrides the page-store status", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 404,
        error: {
          message: "Record was not found in any covered jurisdiction."
        } as App.Error
      }
    });

    expect(rendered.body).toContain("Page not found");
    expect(rendered.body).toContain("HTTP 404");
    expect(rendered.body).not.toContain("HTTP 503");
    expect(rendered.body).toContain("Record was not found in any covered jurisdiction.");
  });

  it("renders a backend 401 as a Civibus data-service authentication failure with home-only recovery", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 401,
        error: {
          detail: "Invalid or missing API key"
        } as unknown as App.Error
      }
    });

    expect(rendered.head).toContain("<title>Data service authentication failed | Civibus</title>");
    expect(rendered.head).toContain(
      '<meta name="description" content="Civibus could not load this page because it could not authenticate with its data service."'
    );
    expect(rendered.head).toContain('<meta name="robots" content="noindex"');
    expect(rendered.body).toContain('aria-live="assertive"');
    expect(rendered.body).toContain("Data service authentication failed");
    expect(rendered.body).toContain("Civibus could not authenticate with its data service.");
    expect(rendered.body).toContain("This is a Civibus service problem, not an issue with your request.");
    expect(rendered.body).toContain("HTTP 401");
    expect(rendered.body).toContain('href="/"');
    expect(rendered.body).toContain("Return home");
    expect(rendered.body).not.toContain("Invalid or missing API key");
    expect(rendered.body).not.toContain("Check the URL");
    expect(rendered.body).not.toContain('href="/search"');
    expect(rendered.body).not.toContain("Go to search");
    expect(rendered.body).not.toContain('aria-hidden="true"');
  });

  it("renders a backend 429 as a temporary request limit with only same-page retry recovery", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 429,
        error: {
          detail: "Rate-limit bucket exhausted for a configured request window."
        } as unknown as App.Error
      }
    });

    expect(rendered.head).toContain("<title>Requests temporarily limited | Civibus</title>");
    expect(rendered.head).toContain(
      '<meta name="description" content="Civibus is temporarily limiting requests. Please wait a moment, then try this page again."'
    );
    expect(rendered.head).toContain('<meta name="robots" content="noindex"');
    expect((rendered.head.match(/<meta name="robots" content="noindex"/g) ?? []).length).toBe(1);
    expect(rendered.body).toContain('aria-live="assertive"');
    expect(rendered.body).toContain("Requests temporarily limited");
    expect(rendered.body).toContain(
      "Civibus cannot load this page right now because requests are temporarily limited."
    );
    expect(rendered.body).toContain("Please wait a moment, then try this page again.");
    expect(rendered.body).toContain("HTTP 429");
    expect(rendered.body).toContain('href="?state=NC"');
    expect(rendered.body).toContain("data-sveltekit-reload");
    expect(rendered.body).toContain("Try this page again");
    expect(rendered.body).not.toContain("//attacker.example/phish");
    expect(rendered.body).not.toContain("Rate-limit bucket exhausted");
    expect(rendered.body).not.toContain("Check the URL");
    expect(rendered.body).not.toContain('href="/"');
    expect(rendered.body).not.toContain("Return home");
    expect(rendered.body).not.toContain('href="/search"');
    expect(rendered.body).not.toContain("Go to search");
    expect(rendered.body).not.toContain('aria-hidden="true"');
  });

  it.each([
    {
      status: 400,
      heading: "Request could not be completed",
      summary: "The server rejected this request. Check the URL or try searching for a record."
    },
    {
      status: 403,
      heading: "Request could not be completed",
      summary: "The server rejected this request. Check the URL or try searching for a record."
    },
    {
      status: 404,
      heading: "Page not found",
      summary: "The page may have moved, been removed, or the URL may be incorrect."
    },
    {
      status: 422,
      heading: "Request could not be completed",
      summary: "The server rejected this request. Check the URL or try searching for a record."
    },
    {
      status: 500,
      heading: "Service temporarily unavailable",
      summary: "Civibus is having trouble loading this page right now. Please try again shortly."
    },
    {
      status: 503,
      heading: "Service temporarily unavailable",
      summary: "Civibus is having trouble loading this page right now. Please try again shortly."
    }
  ])("keeps the existing $status error semantics and recovery actions", ({ status, heading, summary }) => {
    const detail = `Existing backend detail for ${status}.`;
    const rendered = render(ErrorPage, {
      props: {
        status,
        error: { message: detail } as App.Error
      }
    });

    expect(rendered.body).toContain(heading);
    expect(rendered.body).toContain(summary);
    expect(rendered.body).toContain(`HTTP ${status}`);
    expect(rendered.body).toContain(detail);
    expect(rendered.body).toContain('href="/"');
    expect(rendered.body).toContain("Return home");
    expect(rendered.body).toContain('href="/search"');
    expect(rendered.body).toContain("Go to search");
  });

  it("emits the noindex robots meta and both recovery links for non-401 errors", () => {
    const rendered = render(ErrorPage, {
      props: {
        status: 500,
        error: { message: "boom" } as App.Error
      }
    });

    expect(rendered.head).toContain('<meta name="robots" content="noindex"');
    expect(rendered.body).toContain('href="/"');
    expect(rendered.body).toContain('href="/search"');
    expect(rendered.body).toContain("Return home");
    expect(rendered.body).toContain("Go to search");
  });
});
