# Indiana campaign-finance law notes

This file is narrative support for the Indiana `laws` block in `config.yaml`.

## Authoritative sources consulted
- Indiana Election Division campaign-finance guidance landing page: <https://www.in.gov/sos/elections/campaign-finance/>
- Indiana Election Division 2026 Campaign Finance Manual (guidance + Indiana Code citations): <https://www.in.gov/sos/elections/files/2026-Campaign-Finance-Manual.FINAL.11-12-25.pdf>
- Indiana Election Division 2026-2027 reporting schedule: <https://www.in.gov/sos/elections/files/2026-C.F.-Reporting-Schedule.pdf>
- Indiana Code title navigation for campaign-finance article (IC 3-9): <https://iga.in.gov/laws/2025/ic/titles/003>

## Contribution limits
Guidance evidence (2026 manual):
- The manual states individuals may make an unlimited amount of contributions.
- The manual states corporations and labor organizations may contribute directly but are subject to IC 3-9-2-4 and IC 3-9-2-5 category caps.
- The manual lists corporate/labor subcategory caps including `$5,000` statewide category caps and `$2,000` caps for several other office/party categories, with a `$22,000` aggregate annual cap.

Config interpretation for Stage 2:
- `individual_to_candidate`: `"unlimited"`
- `pac_to_candidate`: `"unlimited"` (no general per-candidate PAC cap identified in consulted guidance)
- `party_to_candidate`: `"unlimited"` (regular-party transfers are permitted; office-specific limits are not modeled in current schema)
- `corporate_direct` and `union_direct`: conservative structured value uses `2000` and office-level variation is documented in `laws.notes`.

## Itemization threshold
Manual guidance (IC 3-9-5-14 discussion) states:
- Contributions become itemized when an individual contributor exceeds `$100` aggregate in a calendar year.
- Expenditures become itemized when aggregate payments to a payee exceed `$100`.

Config uses `itemization_threshold: 100` with party-committee threshold caveats in notes.

## Reporting periods and deadlines
Manual and published schedule document recurring periods:
- `pre-primary`
- `pre-election`
- `annual`
- supplemental large-contribution window (48-hour/CFA-11 process)

Config period list encodes these as canonical period names and keeps deadline specifics in `laws.notes` / this narrative file.

## Electronic filing requirements
Manual guidance states:
- Statewide and state legislative candidate committees must file electronically at `campaignfinance.in.gov`.
- Local candidates may file with county boards by permitted local methods (email/mail/fax/hand delivery depending on county policy).
- Some PACs are also required to file electronically with the state division.

Config sets `electronic_filing_required: "required"` and documents scope caveats in `laws.notes`.

## Public financing
No statewide public-financing program was identified in consulted Indiana Election Division campaign-finance guidance or IC 3-9 references used for this stage.

Config sets `public_financing: false`.

## Office-level and special-case caveats
- Corporate/labor limits vary by recipient category and include aggregate/subcategory constraints; schema cannot fully express this matrix.
- Allen County Superior Court has a special statutory cap noted in guidance (`IC 33-33-2-11`), including stricter source limitations.
- A 2024 federal-court ruling described in manual guidance affects application of some corporate-limit rules for corporation-to-independent-expenditure-only PAC contributions; this remains a legal-interpretation caveat for downstream legal review.

## Open questions
1. Confirm whether Indiana Election Division has published post-ruling implementation guidance that supersedes 2026 manual language for IC 3-9-2-4 / IC 3-9-2-5.
2. Confirm if any office-specific or local public-financing mechanism should be represented in future schema expansion even though statewide value is `false`.
