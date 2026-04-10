# Wisconsin campaign-finance law notes

This document supports the `laws` block in `config.yaml`.

## Scope in this stage
Stage 5 implementation is scoped to the verified Sunshine CSV acquisition contract. The legal model fields are intentionally conservative placeholders until statute-level verification is completed in a dedicated laws pass.

## Sources referenced
- Wisconsin Elections Commission Sunshine portal: `https://campaignfinance.wi.gov`
- Wisconsin Elections Commission main site: `https://elections.wi.gov`

## Modeling notes
- `electronic_filing_required` is set to `required` for current machine-readable assumptions and should be verified against current WI filing guidance before legal closeout.
- Contribution-limit fields are intentionally `null` pending statute-specific verification.
- `itemization_threshold` is a provisional structured value and requires law-specific confirmation.
