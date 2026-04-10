# New Jersey campaign-finance law notes

This document supports the `laws` block in `config.yaml`.

## Scope in this stage
Stage 6 implementation is scoped to the verified ELEC API acquisition contract. The legal model fields are intentionally conservative placeholders until statute-level verification is completed in a dedicated laws pass.

## Sources referenced
- NJ Election Law Enforcement Commission: `https://www.elec.nj.gov/`
- NJ ELEC e-filing search: `https://www.njelecefilesearch.com/`

## Modeling notes
- `electronic_filing_required` is set to `required` based on current ELEC system availability and should be verified against current NJ filing guidance before legal closeout.
- Contribution-limit fields are intentionally `null` pending statute-specific verification.
- `itemization_threshold` is set to 300 as a provisional value requiring law-specific confirmation.
- NJ has a gubernatorial public financing program (Clean Elections) not yet modeled in `config.yaml`.
