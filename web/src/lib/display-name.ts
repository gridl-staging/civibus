/**
 * The single owner of how a human's name is rendered anywhere in the UI.
 *
 * Two spines feed names into the same screens and they disagree on case:
 * `core.person.canonical_name` is already human-formatted (`Ossoff, Jon`), while
 * `cf.candidate.name` is the raw FEC filing string (`OSSOFF, T. JONATHAN`).
 * Rendering both verbatim made one senator look like two unrelated records.
 *
 * The chosen format is `Last, First Middle` in title case — the convention the
 * person spine already ships. `Last, First` rather than `First Last` because the
 * default candidate browse sorts by last name ascending; reordering the display
 * would make its own A-Z sort read as broken.
 *
 * Contract and rationale: docs/reference/screen_specs/candidate_list.md ->
 * "Name presentation contract".
 *
 * Personal names only. Organization, committee, office, and contest names are
 * not `Last, First` and must render verbatim.
 */

/**
 * Generational suffixes that stay fully uppercase. Bounded, closed set — an
 * open-ended "is this a roman numeral" test would also uppercase the surname
 * `DILL` and the initial pair `MI`.
 */
const UPPERCASE_SUFFIXES = new Set(["II", "III", "IV", "VI", "VII", "VIII"]);

/** True when the token carries no lowercase letter, i.e. nothing has cased it yet. */
function isUncased(token: string): boolean {
  return token === token.toUpperCase();
}

/** `JONATHAN` -> `Jonathan`, leaving any leading punctuation in place. */
function capitalizeWord(word: string): string {
  if (word === "") {
    return word;
  }

  // Skip leading punctuation such as the `(` in `(AL)` so the first *letter*
  // gets the capital rather than the bracket swallowing it.
  const firstLetterIndex = word.search(/[a-z]/i);
  if (firstLetterIndex === -1) {
    // Digits and punctuation only, e.g. the `212` in an address-like FEC name.
    // There is no case to correct, and source evidence must survive intact.
    return word;
  }

  return (
    word.slice(0, firstLetterIndex) +
    word.charAt(firstLetterIndex).toUpperCase() +
    word.slice(firstLetterIndex + 1).toLowerCase()
  );
}

/**
 * Applies the two name-particle rules that a plain title-case pass gets wrong.
 *
 * Both are deliberately narrow. `Mc` is included because `MCCONNELL` -> `Mcconnell`
 * is visibly wrong and Mc-prefixed surnames are almost always genuine particles.
 * `Mac` is deliberately excluded: `MACON`, `MACK` and `MACIAS` are ordinary
 * surnames, so a blanket Mac rule would mangle more names than it fixes.
 */
function applyNameParticles(word: string): string {
  // Positional apostrophe rule: only an apostrophe at index 1 marks a particle
  // boundary (`O'Brien`, `D'Amato`). Anywhere else it is punctuation, so a
  // possessive or trailing apostrophe must not trigger a capital.
  if (word.length > 2 && word.charAt(1) === "'") {
    return word.charAt(0) + "'" + word.charAt(2).toUpperCase() + word.slice(3);
  }

  if (word.length >= 4 && word.startsWith("Mc")) {
    return "Mc" + word.charAt(2).toUpperCase() + word.slice(3);
  }

  return word;
}

function formatToken(token: string): string {
  // Already-cased tokens belong to whichever spine formatted them; leaving them
  // alone is what makes this function idempotent and keeps the person spine
  // authoritative over the names it owns.
  if (!isUncased(token)) {
    return token;
  }

  // Strip trailing punctuation before the suffix lookup so `III,` still matches.
  if (UPPERCASE_SUFFIXES.has(token.replace(/[^A-Z]/g, ""))) {
    return token;
  }

  // Hyphenated surnames capitalize every segment: `SMITH-JONES` -> `Smith-Jones`.
  return token
    .split("-")
    .map((segment) => applyNameParticles(capitalizeWord(segment)))
    .join("-");
}

/**
 * Renders a personal name in the one shared display format.
 *
 * Blank input returns an empty string; callers own their own fallback copy
 * rather than having a placeholder invented for them here.
 */
export function formatPersonDisplayName(rawName: string): string {
  const trimmedName = rawName.trim();
  if (trimmedName === "") {
    return "";
  }

  // Splitting on runs of whitespace also collapses the doubled spaces that FEC
  // source strings carry (`212 N HALF  W. JOHN, RODNEY`).
  return trimmedName.split(/\s+/).map(formatToken).join(" ");
}
