# Los Angeles campaign-finance law notes

This file supports the `laws` section in `config.yaml`.

## Authoritative sources
- LA City Ethics Commission campaigns portal: `https://ethics.lacity.gov/campaigns/`
- LA Municipal Code Chapter 4 (campaign financing): `https://codelibrary.amlegal.com/codes/los_angeles/latest/lamc/0-0-0-139020`

## Contribution limits
- The 2025-2026 cycle limit is $900 per source per election for most city races.
- Corporate and LLC direct contributions to city candidates are prohibited.
- Limits are periodically adjusted by the Ethics Commission.

## Reporting periods
- The initial config models recurring filing windows as semi-annual, pre-election,
  post-election, and 24-hour reporting.
- Electronic filing is required for LA city campaign finance disclosure.

## Public financing
- Los Angeles has a public-financing matching funds program administered by the LA City Ethics Commission.
- `config.yaml` encodes this as a `public_financing` object with a matching-funds program type.

## Known ambiguities
- City and state campaign-finance obligations can differ by office and committee type.
- The flattened law schema cannot fully encode per-office variation yet.
