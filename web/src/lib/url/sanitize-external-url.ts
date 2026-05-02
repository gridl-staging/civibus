/** Allows only HTTP(S) links to render as outbound URLs. */
export function sanitizeExternalUrl(value: string | null): string | null {
  if (!value) {
    return null;
  }

  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    if (parsed.username !== "" || parsed.password !== "") {
      return null;
    }

    return parsed.toString();
  } catch {
    return null;
  }
}
