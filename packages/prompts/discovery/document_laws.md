# Prompt: Document Campaign Finance Laws

**Agent task:** Research a jurisdiction's campaign finance laws and produce the legal/filing-semantics artifacts for its `config.yaml` plus a `laws.md` narrative.

---

## Input

```
JURISDICTION: {name}
TYPE: {federal | state | county | municipality}
FIPS: {fips code}
AUTHORITATIVE_SOURCE: {link to SBE, ethics commission, or statute if known}
```

---

## Instructions

1. Find the authoritative legal source: state statute, administrative code, or the disclosure agency's own rules page. Prefer the primary source over summaries.

2. Extract and encode:
   - **Contribution limits** — by donor type (individual, PAC, corporate, union, party). Note if prohibited outright. **Critically: note in `notes[]` if limits vary by office level (e.g., governor vs. state house) or election type (primary vs. general) — the current schema can't encode this structurally but capturing it is essential.**
   - **Itemization threshold** — minimum amount requiring donor name/address disclosure.
   - **Reporting periods** — when reports are due (quarterly, pre/post-election, annual).
   - **Filing deadlines / completeness cues** — what reports should exist, when they are due, and any practical clues that would later help a missing-filing or late-filing system.
   - **Electronic filing requirement** — required, voluntary, or paper only.
   - **Public financing** — any matching fund, grant, or voucher program? If yes, note program type, matching ratio, qualifying threshold, and administering agency.

3. Note any recent changes (last 3 years) that affect data interpretation.

---

## Output

> **Note:** The `laws` schema below is a Stage 0/1 placeholder. It is too flat to express
> per-office-level or per-election-type variation. Use `notes[]` liberally for anything
> that doesn't fit. The schema will be redesigned as a list-of-rules before Stage 3.

YAML block for `config.yaml`:

```yaml
laws:
  source_url: ""               # URL of the authoritative statute or rules page
  last_verified: ""            # YYYY-MM-DD
  contribution_limits:
    individual_to_candidate: null    # dollar amount or "unlimited" or "prohibited"
    pac_to_candidate: null
    corporate_direct: null
    union_direct: null
    party_to_candidate: null
  itemization_threshold: null
  reporting:
    periods: []                # e.g. ["quarterly", "pre-election", "post-election"]
    electronic_filing_required: null
  public_financing: false      # or object with {type, administering_agency} if applicable
  notes: []                    # flag ambiguities, recent changes, or open questions
```

Also produce a `laws.md` with one section per topic above, plus a short section for **expected filing obligations / completeness cues** that highlights what future gap-detection logic would need to know.

---

## Hallucination rules

- Cite the specific statute or rule section for every limit you state.
- If a limit is not found, write `null` with a note — do not guess.
- If the law changed recently and old data predates the change, flag this in `notes`.
