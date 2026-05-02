import { describe, expect, it } from "vitest";
import { sanitizeExternalUrl } from "./sanitize-external-url";

describe("sanitizeExternalUrl", () => {
  it("returns normalized http/https urls and rejects malformed or unsafe schemes", () => {
    expect(sanitizeExternalUrl("https://example.org/path")).toBe("https://example.org/path");
    expect(sanitizeExternalUrl("http://example.org")).toBe("http://example.org/");
    expect(sanitizeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(sanitizeExternalUrl("ftp://example.org/resource")).toBeNull();
    expect(sanitizeExternalUrl("not a url")).toBeNull();
    expect(sanitizeExternalUrl(null)).toBeNull();
  });

  it("rejects http and https urls that embed basic-auth credentials", () => {
    expect(sanitizeExternalUrl("https://alice:secret@example.org/private")).toBeNull();
    expect(sanitizeExternalUrl("http://token:@example.org/feed")).toBeNull();
  });
});
