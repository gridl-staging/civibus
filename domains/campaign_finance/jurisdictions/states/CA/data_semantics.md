# California CAL-ACCESS data semantics

This document records parsing assumptions for the CA Stage 2 member set. Machine-readable mapping authority stays in config.yaml.

## Date fields
- CVR_CAMPAIGN_DISCLOSURE_CD.RPT_DATE uses slash-delimited month/day/year values in sampled rows; normalization target is ISO date when parseable.
- RCPT_CD.RCPT_DATE, EXPN_CD.EXPN_DATE, and LOAN_CD.LOAN_DATE1 use similar slash-delimited date values.
- Outlier legacy dates occur in sampled data (for example 0200, 1899, 1982, and isolated 1970). Keep raw provenance and quarantine/normalize invalid values at transform time. [S1][S2]

## Name formats
- Counterparty name components are split fields (last, first, title, suffix) per table family: donor (RCPT), payee (EXPN), lender (LOAN).
- Committee naming in CVR is filer-last-name centric (`FILER_NAML`) and may require title-casing during normalization for canonical display.
- Entity typing relies on per-table entity-type columns mapped in config (for example donor.entity_type -> RCPT_CD.ENTITY_CD). [S3]

## Employer/occupation
- Employer and occupation semantics are available only in RCPT rows (`CTRIB_EMP`, `CTRIB_OCC` mapped to donor.employer and donor.occupation).
- Blank strings are treated as null during parse/extract normalization.
- EXPN and LOAN stage-2 extraction does not carry employer/occupation fields. [S3]

## Address format
- Address values are partial components (city/state/zip) in the stage-2 member set; no guaranteed street line for RCPT/EXPN/LOAN entities.
- City values are normalized uppercase in current extraction to improve cross-row matching consistency.
- ZIP accepts either 5-digit or ZIP+4 styles; split into zip5/zip4 where possible.

## Committee IDs
- CVR filer linkage uses FILER_ID and FILING_ID as primary identifiers for filing join context.
- FILERNAME_CD and FILERS_CD provide additional filer dimension records used for reference enrichment and later entity-resolution joins.
- Stage 2 intentionally excludes deeper filing-link tables (for example FILER_FILINGS_CD) from relational loading pending broader schema fit. [S4]

## Amendment handling
- Amendment context is table-specific via AMEND_ID fields in CVR/RCPT/EXPN/LOAN.
- Current stage-2 parse preserves amendment values as provided; authoritative supersession logic remains downstream in load/model stages.

## Missing/null conventions
- Empty tab-delimited cells normalize to null at parse time.
- Malformed row width (header/row field count mismatch) is skipped with warning to prevent silent column drift.
- Literal placeholders from legacy rows are not force-mapped to null unless explicitly blank; preserve source text for provenance.

## Portal Navigation
Not applicable for this source. CAL-ACCESS stage-2 ingest uses direct ZIP download links with no browser automation required. [S5]

## Open questions
- Whether stage-2 should add deterministic handling for legacy outlier dates (reject vs clamp vs preserve-only) before relational load.
- Whether FILER_FILINGS_CD becomes required once filing-to-transaction reconciliation expands beyond current Stage 2 transaction surfaces.

## Sources
- [S1] docs/research/stage2-ca-coverage-verification.md
- [S2] docs/research/stage2-ca-archive-member-investigation.md
- [S3] domains/campaign_finance/jurisdictions/states/CA/config.yaml
- [S4] docs/research/stage2-ca-contract-translation.md
- [S5] https://www.sos.ca.gov/campaign-lobbying/cal-access-resources/raw-data-campaign-finance-and-lobbying-activity
