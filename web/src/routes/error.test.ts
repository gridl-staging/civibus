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
});
