# San Francisco campaign-finance law notes

This file supports the `laws` section in `config.yaml`.

## Authoritative sources
- SF Ethics Commission campaign-finance disclosure portal: `https://sfethics.org/disclosures/campaign-finance-disclosure`
- SF Campaign and Governmental Conduct Code (campaign-finance sections): `https://codelibrary.amlegal.com/codes/san_francisco/latest/sf_campaign/0-0-0-1`

## Contribution limits
- Stage 2 config currently uses `$500` as the baseline individual and PAC limit to city candidates.
- Corporate direct contributions are modeled as prohibited.
- Union direct contributions currently follow the general `$500` per-source cap rather than the corporate prohibition.
- Office/election-specific variation is preserved in config notes for later legal normalization.

## Reporting periods
- The initial config models recurring filing windows as semi-annual, pre-election,
  post-election, and 24-hour reporting.
- Electronic filing is modeled as required for the SF city disclosure flow.

## Public financing
- San Francisco has a public-financing program administered by the San Francisco Ethics Commission.
- `config.yaml` encodes this as a `public_financing` object with a matching-funds program type.

## Known ambiguities
- City and state campaign-finance obligations can differ by office and committee type.
- The flattened Stage 2 law schema cannot fully encode per-office variation yet.
