import { describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";

let currentPageStatus = 503;

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { status: number; url: URL }) => void): () => void {
      run({ status: currentPageStatus, url: new URL("https://civibus.test/error") });
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

  it("emits the noindex robots meta and recovery links for any rendered error", () => {
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
