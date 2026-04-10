# Washington campaign-finance law notes

This file is narrative support for the WA `laws` block in `config.yaml`.

## Authoritative source
- RCW 42.56.070 (public records and list-of-individuals restriction context): `https://app.leg.wa.gov/RCW/default.aspx?cite=42.56.070`
- RCW 42.17A.405 (contribution limits by office class): `https://app.leg.wa.gov/RCW/default.aspx?cite=42.17A.405`
- RCW 42.17A.005 (definitions covering state and local scope): `https://app.leg.wa.gov/RCW/default.aspx?cite=42.17A.005`
- WA PDC open-data portal: `https://www.pdc.wa.gov/political-disclosure-reporting-data/open-data`

## Contribution limits table
- WA limits vary by office type, election, and filer class.
- `config.yaml` keeps flattened placeholder values where variation is substantial and documents caveats in notes.

## Itemization threshold
- Stage 4 uses `itemization_threshold: 25` as an operational placeholder pending deeper legal normalization.
- Any downstream compliance use should re-verify thresholds against current RCW/PDC guidance.

## Reporting periods and deadlines
- WA reporting cadence includes regular periodic filings and election-window reporting.
- Electronic reporting is required for covered filers in current PDC operational practice.

## Prohibitions
- PDC dataset metadata includes a CONDITION OF RELEASE citing RCW 42.56.070(9) and AGO 1975 No. 15 with non-commercial reuse language.
- This reuse caveat is recorded in `data_sources[].known_issues`.

## Public financing
- No WA public-financing scheme is modeled in this Stage 4 package (`public_financing: false`).

## Known ambiguities / recent changes
- RCW pages include recodification references from chapter 42.17A to chapter 29B effective context in 2026.
- Citation normalization should be revisited as codification references stabilize.

## Office-level or election-type variation
- WA statutory limits and filing requirements vary between state and local offices.
- The package preserves state-vs-local variation as narrative notes rather than flattening into one office class rule.
