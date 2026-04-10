# San Francisco (SF) campaign-finance jurisdiction package

## Jurisdiction overview
San Francisco is a municipality-level jurisdiction (`fips: 06075`) with parent state `CA`.
This package defines the first city campaign-finance configuration scaffold for the Civibus
city pipeline pattern.

## Data sources summary
- Primary source: SF Ethics Commission campaign-finance disclosures via DataSF Socrata.
- Landing page: `https://sfethics.org/disclosures/campaign-finance-disclosure/campaign-finance-disclosure-data`
- Dataset (transactions): `pitq-e56w`
- Access pattern: SODA API + CSV export (`format: api` in config)
- Refresh profile: nightly updates (modeled as `update_frequency: daily`)

Verified supplementary datasets (not yet mapped into `data_sources`):
- Filings Received by SFEC: `qizs-bwft`
- Campaign Filers: `4c8t-ngau`

## Coverage notes
- `coverage.covers_sub_jurisdictions` is `false` because this source is specific to the City and County of San Francisco.
- The mapped transactions source covers contributions, expenditures, loans, and independent-expenditure-related records in one dataset.

## Known data quality issues
- Current Socrata metadata exposes additional fields beyond the Stage 1 baseline mapping scope.
- Supplementary filing/filer datasets are catalog-verified but intentionally deferred from this first config pass.

## Last verified date
- Source access and dataset IDs verified: 2026-03-31
- Laws notes synchronized with config laws block: 2026-03-31
