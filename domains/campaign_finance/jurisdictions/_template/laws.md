# Jurisdiction laws notes template

This file is narrative support for the `laws` block in `config.yaml`. It must not duplicate schema field definitions.

## Authoritative source
- Paste source links (statute, admin code, or rules page) and identify the exact sections that drive each field in `config.yaml`.
- If there is ambiguity between documents, cite the higher-precedence source and note the conflict.

## Contribution limits table
- Replace this section with a concise plain-English summary of donor limits by donor class and recipient class.
- Note any exceptions, caps by election cycle, and whether a class is truly "unlimited" vs unpublished.

## Itemization threshold
- Document the value and statutory basis for the minimum disclosure threshold.
- Clarify currency, rounding rules, and how non-cash contributions are treated.

## Reporting periods and deadlines
- List report frequencies, filing windows, and any staggered deadlines for special elections.
- Convert all observed patterns into `laws.reporting.periods` and explain any mapping assumptions in `laws.notes` if needed.

## Expected filing obligations / completeness cues
- Describe what filings should exist for common committee/candidate scenarios and when they should appear publicly.
- Note any practical cues that would later help missing-filing or late-filing detection, even if the current schema cannot encode them yet.

## Prohibitions
- Record explicit statutory prohibitions that affect schema interpretation (e.g., corporate direct, foreign national).
- Add missing context if the prohibition is narrow (office-level specific, date-bounded, or rule-specific).

## Public financing
- Record whether a public financing mechanism exists.
- If none, keep `public_financing: false` in `config.yaml` and keep this section as a short null/negative confirmation note.
- If present, this section should describe `type`, qualifying thresholds, matching ratios, and administering agency.

## Known ambiguities / recent changes
- Track any law text conflicts, pending litigation, recent amendments, and effective-date caveats that can impact older data.
- Add one concise note per ambiguity, with a date and source citation where available.

## Office-level or election-type variation
- Capture variations that `laws.*` cannot represent yet.
- Document where limits or deadlines change by office class (for example, governor vs. county commission) or election type (primary vs. general).
- Keep `laws.notes` synchronized with this section so model gaps are auditable before Stage 3.
